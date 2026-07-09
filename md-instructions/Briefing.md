# Audiobook Creation Tool — Briefing

> **Audience:** future AI sessions and any new contributor.
> **Purpose:** the single document that fully orients a new session without the user re-explaining
> anything. Version history lives in `CHANGELOG.md`; architectural decisions in `DECISIONS.md`;
> in-flight work and open bugs in `handoff.md`.

## What This Project Does

The Audiobook Creation Tool is a cross-platform (Windows + macOS) desktop app that turns ebooks
and loose audio into finished, tagged audiobooks. It bundles a **text-to-speech engine**
(EPUB / PDF / TXT → MP3, using Microsoft Edge TTS over the network plus the local Kokoro-82M AI
model) with a suite of **MP3/M4B utilities** (combine MP3s, batch M4B→MP3, build chaptered M4B
files with cover art and series tags, resize cover images, and edit existing M4B metadata). It is
built for **non-technical users**: they download a zip, double-click one setup file, and get a
single GUI window — no terminal, no manual Python or ffmpeg install, and no console windows
flashing during use.

## Tech Stack

- **Language:** Python 3.12 (the bootstrap installs 3.12 specifically — PyPI `kokoro` wheels
  require <3.13; 3.13+ works but loses the Kokoro voices)
- **GUI:** tkinter (single launcher window, sidebar + swappable content panel). macOS gets
  a Finder-style shell on the native `aqua` theme; Windows keeps the classic look
  byte-for-byte — the platform split lives in `shared/ui_theme.py`
- **Key libraries:** edge-tts (network TTS), kokoro + torch (local AI TTS), mutagen (audio
  metadata), PyMuPDF/fitz (PDF text extraction), pydub + soundfile + numpy/scipy (audio
  assembly), ebooklib + beautifulsoup4 + lxml (EPUB parsing), nltk (sentence tokenization),
  pillow (cover images). All pinned to exact versions in `scripts/requirements.txt`.
- **External binaries:** ffmpeg + ffprobe — installed system-wide by the bootstrap (winget
  `Gyan.FFmpeg` / Homebrew) or dropped as a portable build into `files/bin/`.
- **Platform:** cross-platform Windows + macOS from a **single code tree**
  (`scripts/Universal/`); platform differences are `sys.platform` branches inside shared code.

## Architecture

- **Entry point (users):** `Setup_and_Run-audiobook-creation-tool.bat` (Windows) / `.command`
  (macOS) at the repo root — the only files a user ever touches. Fast path: if `.venv` exists,
  launch via `pythonw.exe` (Windows — no console) / detached (macOS). First run hands off to the
  bootstrap.
- **`scripts/Universal/shared/bootstrap.py`** — single cross-platform setup + launch brain
  (stdlib + Tk only; runs before the venv exists). Locates/installs Python 3.12, creates the
  repo-root `.venv`, pip-installs pinned requirements, ensures ffmpeg, optionally pre-downloads
  the Kokoro model (~300 MB), **self-heals a missing/broken Kokoro install on every launch**
  (probes kokoro/soundfile/scipy, repairs without blocking the GUI), redirects the HuggingFace
  cache into the project tree, then launches the GUI detached with stdout/stderr captured to
  `files/runtime-data/logs/launch_<date>.log`. `--launch-only` is the fast-path flag;
  `--self-test` is detection-only.
- **`scripts/Universal/launcher.py`** — the unified Tk GUI. Sidebar of 6 tools; each tool
  exposes `build_ui(parent_frame)`, is lazy-imported and guarded (a missing dependency renders
  an in-panel error, never a crash), built once and shown/hidden on selection so in-progress
  state survives switching. Installs `install_no_window_guard()` first so even pydub/edge-tts
  *internal* ffmpeg spawns are console-hidden on Windows. All theming comes from
  `shared/ui_theme.apply_theme()`: on macOS a Finder-style shell (native aqua controls,
  tinted source-list sidebar with hover/selection rows and glyphs, toolbar strip, content
  card); on Windows/other the classic pre-v0.5.0 layout, unchanged (see DECISIONS.md
  2026-07-08).
- **`scripts/Universal/shared/`** — `paths.py` (single source of truth for every project
  path — everything derives from `REPO_ROOT`), `subprocess_utils.py` (hidden-console subprocess
  wrapper + the global Popen no-window guard), `ffmpeg_utils.py` (resolves ffmpeg/ffprobe:
  `files/bin/` → PATH; pins pydub to the resolved binaries; xHE-AAC decoder selection),
  `settings.py` (atomic JSON at `files/runtime-data/settings.json`), `cancellation.py` (shared
  Cancel/threading.Event pattern), `metadata.py` (mutagen M4B tag read/write incl. series
  atoms + chapter-title re-mux), `logging_setup.py` (session logs, pruned to 30),
  `ui_theme.py` (platform theming: aqua/Finder palette on macOS vs classic elsewhere, plus
  the `enable_mousewheel` scroll-on-hover helper and the shared `ProgressIndicator` —
  progressbar + counter/percentage label, main-thread-only API, used by all six tools),
  `version.py` (single source of truth),
  `release.py` (dev-only zip packager, never imported by the app), `close_terminal.py`
  (macOS Terminal auto-close helper).
- **Import convention:** `scripts/Universal/` is the single import root. Cross-module imports
  are absolute (`tts.*`, `mp3_tools.*`, `shared.*`); entry scripts prepend the import root to
  `sys.path` so they work standalone or via the launcher. The `epub2tts_edge/` subpackage is
  only ever imported as `tts.epub2tts_edge`.
- **Data flow (TTS):** GUI → `tts/epub2tts_edge/runner.run_conversion_job` (cwd-safe temp-dir
  wrapper) → Edge TTS, or `tts/pdf_extractor.pdf_to_txt` → `tts/kokoro_synth.kokoro_file_to_mp3`
  for the Kokoro path. Batch PDF folders go through `tts/batch_convert.py` (threaded, resume,
  retry). Long operations run on worker threads with a Cancel button and a per-tool progress
  indicator (determinate with a percentage where the total is known; indeterminate otherwise —
  e.g. the M4B Maker's single concat/encode); **workers never read Tk variables** (hoisted to
  the main thread — see DECISIONS/memory), and progress flows the same way: the worker enqueues
  `("progress", (done, total))` on its existing queue and only the main-thread drain touches
  the widget.
- **Outputs are copy-based everywhere:** transforming tools write to a fresh auto-named
  `Downloads/<Tool>-N` folder (decided once per launch, created lazily); imported originals are
  never modified. The only in-place exception is the Cover Image tool's explicit overwrite
  toggle.

## Features

- **TTS Audiobook** (`tts/epub2tts_gui.py`) — EPUB/PDF/TXT → MP3; 11 voices (6 Edge network +
  5 Kokoro local AI); single file or batch folder (PDF / TXT; nested subfolders are mirrored
  in the output so same-named files in different books never collide); per-chunk retry;
  Cancel. Edge voices honor all five pause fields; Kokoro voices honor the paragraph pause
  (mapped to the inter-chunk gap) and the end-of-recording pause — sentence/title/chapter
  parity is deliberately deferred (see DECISIONS.md). Dev/QA helper
  `tts/generate_voice_samples.py` writes one short sample per voice to
  `files/test-for-manual-listen-elmatthe/` (gitignored, never imported by the app).
- **M4B Converter** (`mp3_tools/m4b_converter.py`) — batch M4B → clean MP3 (libmp3lame VBR),
  optional bulk metadata + auto track numbers.
- **MP3 Tool** (`mp3_tools/mp3_tool.py`) — combine MP3s into one, time-edit track ends, bulk
  ID3 tagging with chapter-title paste.
- **M4B Maker** (`mp3_tools/m4b_maker.py`) — MP3s → chaptered M4B with cover art, metadata, and
  Audiobookshelf-compatible series tags (freeform `----:com.apple.iTunes:SERIES`/`SERIES-PART`
  atoms — what ABS's ffprobe scanner actually reads).
- **Cover Image Converter** (`mp3_tools/cover_resizer.py`) — pad/crop cover art to square;
  JPG/PNG/HEIC.
- **M4B Metadata Editor** (`mp3_tools/m4b_metadata_editor.py`) — edit existing M4B tags without
  re-encoding; preserve-by-default (blank = unchanged); series detection across vendor freeform
  + movement atoms; auto-number series parts; per-file chapter-title import; writes copies.
  Batch mode (multiple files or the "Open Folder…" picker, non-recursive) pre-fills fields
  whose value is identical across all loaded files and marks differing ones "(varies)";
  single-file mode is unchanged. The tag/settings sections scroll in a TTS-style canvas
  (wheel/trackpad via `enable_mousewheel`); the action buttons and a fixed 14-row Log sit
  below the scroll area, always visible.

## Project Layout Notes

Standard AI-WORKSPACE.md layout since v0.5.0:

```
Audiobook-Creation-Tool/
├── README.md, AI-WORKSPACE.md, .gitignore
├── Setup_and_Run-audiobook-creation-tool.bat / .command   ← the ONLY user-facing entry files
├── .venv/                      ← auto-built by the bootstrap (gitignored)
├── .claude/  .codex/           ← agent wiring
├── md-instructions/            ← Briefing, CHANGELOG, DECISIONS, handoff (+ temporary drops)
├── scripts/
│   ├── requirements.txt        ← single pinned cross-platform list
│   ├── verify.py               ← mechanical gate: pytest + pinned deps + de-templated docs
│   ├── Universal/              ← ALL program code (launcher.py, tts/, mp3_tools/, shared/)
│   ├── Windows/  MacOS/        ← empty by design (.gitkeep) — only truly OS-specific code
└── files/                      ← dev-only + runtime (nothing here ships in release zips)
    ├── bin/                    ← portable ffmpeg fallback (gitignored)
    ├── runtime-data/           ← logs/, settings.json, models/huggingface/ (Kokoro ~300 MB;
    │                             all gitignored — delete with .venv for a full uninstall)
    ├── tests/                  ← pytest suite + Kokoro voice harness
    ├── test-files/             ← local fixtures incl. copyrighted media (entirely untracked;
    │                             point tests at it via KOKORO_TEST_PDF_FOLDER)
    ├── test-logs/              ← QA logs + harness outputs (gitignored)
    └── release-history/        ← one-shot docs from past releases (v0.3.1 set)
```

Release zips (built by `shared/release.py` into `dist/`) contain README + the OS's launcher +
the whole `scripts/` tree; both OS zips share the same code and differ only in launcher.

## Current Version

v0.5.0 (restructure line in progress on branch `restructure-v0.5.0`; v0.4.0 is the latest
published GitHub release — remote: [elmatthe/audiobook-creation-tool](https://github.com/elmatthe/audiobook-creation-tool))

## High-Level State

All six tools are built, live-verified on Windows (v0.1.0 test matrix: 18/18 applicable rows
PASS; later releases re-verified their areas) **and on macOS (2026-07-08: full per-tool live
pass under the Finder shell — the `0.5.0-macos-component-verify` plan)**, and shipped through
GitHub Releases v0.1.0–v0.4.0.
v0.4.0 added Kokoro self-heal on every launch, the in-tree HF model cache, and the 5-voice
verification harness. v0.5.0 is a multi-drop line: Drop 1 (this restructure — no tool behaviour
changes), then metadata, TTS, script hardening, and UI drops.

**Known limitations (documented, not bugs):**
- **Windows xHE-AAC decode** — ffmpeg's native AAC decoder can't decode xHE-AAC (USAC) M4Bs;
  macOS routes decoding through Apple's `aac_at` decoder, which supports xHE-AAC. Confirmed
  Windows limitation since v0.3.2. The macOS `aac_at` path is live-verified on standard
  AAC-LC M4Bs, but an actual xHE-AAC/USAC decode on macOS is still unverified — no USAC
  sample on hand (2026-07-08).
- **Fresh one-click clean-machine install** (winget Python 3.12 + multi-GB torch + 300 MB
  model) is verified in pieces, not yet end-to-end on a virgin box.
- The `.bat` entry point briefly flashes its own cmd window on launch (the GUI itself never
  shows a console); eliminating it entirely would need a shortcut shim — deferred.

**Owner ground rules:** non-technical users are the audience; no visible consoles; every
dependency `==`-pinned; repo root stays minimal; upstream credit (GPL-3.0): epub2tts-edge
(Christopher Aedo), edge-tts, Kokoro-82M.
