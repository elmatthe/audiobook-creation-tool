# Project Briefing — Audiobook Creation Tool

> **Audience:** future Claude chat sessions and any new contributor.
> **Purpose:** be the single document you can hand someone (or paste into a new chat) to get them fully oriented without re-explaining the project.
> **Maintained by:** Claude Code, updated at the end of every session.
> **Status (v0.1.2, 2026-05-30):** Patch release on top of v0.1.1; `VERSION = "0.1.2"`. Fixes the
> **M4B Metadata Editor series read-back**: real Audible/Audiobookshelf M4Bs store the series in a
> vendor freeform atom (Libation/tone writes `----:com.pilabor.tone:SERIES` / `:PART`, *not* the
> `----:com.apple.iTunes:SERIES` atom we used to read), so Series Name/Part came up blank even when
> Audiobookshelf grouped the book. `read_m4b_tags` now resolves series from the canonical freeform
> atom → any other vendor freeform atom → the native movement atoms (`©mvn`/`mvin`), reports
> provenance (`series_source`/`series_atom`), and the editor shows a read-only **"Detected on file"**
> line with the value + source atom. Writing a series now also strips any other same-suffix
> freeform/movement atom so the overwrite isn't shadowed (it previously silently failed to take in
> ABS); preserve-by-default and the chapter-title re-mux freeform snapshot both still hold. Verified
> live on Windows against the real Harry Potter (tone-tagged) & Mistborn (no series) M4Bs: read-back,
> write→ffprobe `series`/`series-part`, original MD5-identical, and series surviving a 39-chapter
> re-mux. Win↔Mac `scripts/` byte-identical; `compileall` clean; macOS live pass deferred (no host).
>
> **Prior status (v0.1.1, 2026-05-30):** Update release on top of v0.1.0; `VERSION = "0.1.1"`. Phases A–F
> complete (phase-gated off `master`, `compileall` clean and Win↔Mac byte-identical before each commit):
> **non-destructive copy-based output** across every transforming tool (imported originals are never
> modified — the M4B Metadata Editor now tags **copies**, not the source), smart auto-named
> **`Downloads/<Tool>-N`** output folders (decided once per launch and created lazily on first write;
> **Browse** redirects for the current run only and is **not** persisted), a **Clear All Tags (keep
> chapters)** button, and **per-file positional chapter-title import** (paged) in the M4B Metadata
> Editor. New shared API: `paths.downloads_dir` / `next_output_dir` / `avoid_input_overwrite`;
> `metadata.clear_metadata_keep_chapters` / `read_chapter_titles` / `apply_chapter_titles`
> (chapter-title edits use an ffmpeg ffmetadata round-trip with freeform-atom preservation, since
> mutagen can't edit MP4 chapter titles). Verified live on Windows against the real `test-files/`
> assets (the real Harry Potter & Mistborn M4Bs, real Shadow Slave MP3s, a real JPG): every transform
> ran on a copy and each imported original was MD5-identical before/after (see
> `Windows/test-logs/v0.1.1_pre-release.md`). macOS live pass still deferred (no host); the clean-machine
> one-click install and the visual no-console-flash check remain the same documented deferrals as v0.1.0.
>
> **Prior status (v0.1.0):** Phase 7 (Cross-Platform Test Matrix) **complete on Windows**. Every deferred live
> debug-gate item (Gates 2–6) was run live on Windows against the real `test-files/` assets, and the
> §12 matrix is filled: **all 18 applicable Windows rows PASS** with **zero unresolved FAILs**. The
> live runs drove the *real* tool worker code paths (real ffmpeg / mutagen / Pillow / Edge-TTS over the
> network) — not mocks: a 17.8 s EPUB→MP3 and 13.1 s PDF→MP3 Edge conversion, a 2-file PDF batch, a
> mid-run TTS **cancel** that raised `ConversionCancelled` with **0 leaked temp dirs** (Gate 4), an M4B
> Maker build with 3 chapters + ffprobe-verified `series`/`series-part`, an M4B-encode **cancel** that
> removed its partial output folder (Gate 5), an M4B→MP3 convert, MP3-Tool combine/time-edit/ID3, a
> Cover-Resizer square+crop, and the **Metadata Editor** single-file round-trip + multi-file overwrite +
> blank-field preserve (Gate 6) — all on a working dir **with a space in its path** and including a
> **Unicode-named** file. Settings persisted across a simulated restart; the launcher listed and built
> **all six tools** live with no error frames in ~1.25 s. Gate 2's venv+pip path was verified live
> (`bootstrap.py --self-test` clean; a throwaway venv resolved the full **pinned** `requirements.txt`
> against PyPI). **No bugs were found**, so Phase 7.3 made no code changes. Two rows are not a clean
> Windows PASS and are documented known-limitations rather than failures: **fresh one-click install**
> (needs a clean machine + Python **3.12** and multi-GB torch/Kokoro + the 300 MB model — system
> mutation, not run live) and **TTS Kokoro voice** (this machine runs Python **3.13**, above Kokoro's
> `<3.13` gate). The entire **macOS** column is **SKIP (no Mac available this session)**. Console-flash
> suppression is mechanism-verified (zero direct `subprocess.*` in tool code; `subprocess_utils`
> applies `CREATE_NO_WINDOW`+hidden `STARTUPINFO`; launcher runs under `pythonw`) with the final visual
> confirmation left to a real double-click pass. Phases 3–6 all stand. **Phase 8 (README + release
> packaging) is COMPLETE:** the CV-grade root `README.md` is written (six-tool feature list, launcher
> mockup, install steps, system requirements, per-tool usage, architecture + design decisions,
> GPL-3.0 credits/license, known limitations); `scripts/shared/version.py` (`VERSION = "0.1.0"`) is the
> single source of truth; and the dev-only `scripts/shared/release.py` packages
> `dist/AudiobookTool-{Windows,MacOS}-v0.1.0.zip` (excluding `.venv`/`__pycache__`/`*.pyc`/`logs`/
> `settings.json`/`bin`/`test-files`, with `README.md` + the launcher at each archive root — verified
> via `zipfile.namelist()`). CHANGELOG `[Unreleased]` → `[0.1.0] - 2026-05-29`, both trees. **What
> remains before a public ship is the live pre-release pass, not new code:** Debug Gate 2 (full
> one-click install on a clean Python-3.12 box), the macOS matrix column on a Mac, and the final
> visual no-console-flash confirmation — then a GitHub remote + Release with the two zips attached.
>
> **Git:** local-only history. `master` = Phase 0+1 restructure baseline; branch `phase-2-bootstrap`
> = Phase 2; branch `phase-3-launcher` = Phase 3; branch `phase-4-tts-polish` = Phase 4; branch
> `phase-5-mp3-polish` = Phase 5; branch `phase-6-metadata-editor` = Phase 6; branch
> `phase-7-test-matrix` = Phase 7; branch `phase-8-release` = Phase 8. No remote yet — GitHub is
> handled at the very end. The real-asset
> **`test-files/`** folder at the repo root (~2.7 GB: 2 M4Bs, 289 MP3, 836 PDF, etc.) is **gitignored**
> — it is a local test fixture, never committed.

---

## 1. One-Paragraph Summary

The Audiobook Creation Tool is a cross-platform (Windows + macOS) desktop app that turns ebooks and loose audio into finished, tagged audiobooks. It bundles a **text-to-speech engine** (EPUB / PDF / TXT → MP3, using Microsoft Edge TTS over the network plus the local Kokoro-82M AI model) with a suite of **MP3/M4B utilities** (combine MP3s, batch M4B→MP3, build chaptered M4B files with cover art and series tags, resize cover images, and edit existing M4B metadata). It is built for **non-technical users**: they download a zip, double-click one setup file, and get a single GUI window — no terminal, no manual Python or ffmpeg install, and no console windows flashing during use.

---

## 2. Repository Structure

```
Audiobook-Creation-Tool/
├── README.md                         # (Phase 8) CV-grade project overview
├── setup_and_run.bat                 # (Phase 2) Windows double-click entry point
├── setup_and_run.command             # (Phase 2) macOS double-click entry point
├── Windows/
│   ├── md-instructions/   (CHANGELOG.md, Briefing.md)
│   ├── scripts/           (launcher.py, tts/, mp3_tools/, shared/)
│   ├── resources/         (icons, default cover, logs/, settings.json, bin/ for portable ffmpeg)
│   └── requirements.txt
└── MacOS/
    └── (mirror of Windows/)
```

**Hard rule:** the repo root contains **exactly 5 items** (`README.md`, `setup_and_run.bat`, `setup_and_run.command`, `Windows/`, `MacOS/`). Never add a 6th.

### Current on-disk state (post Phase 1 migration)

The four source repos have been **migrated and deleted**. Each OS folder now holds:

```
<OS>/
  md-instructions/   CHANGELOG.md, Briefing.md
  requirements.txt   merged TTS+MP3 deps (UNPINNED — Phase 2 pins them)
  resources/         logs/   (bin/, settings.json created later)
  scripts/
    tts/             epub2tts_gui.py, batch_convert.py, kokoro_synth.py,
                     pdf_extractor.py, voice_registry.py, setup_env.py,
                     __init__.py, epub2tts_edge/ (__init__, epub2tts_edge.py, runner.py)
    mp3_tools/       mp3_tool.py, m4b_maker.py, m4b_converter.py, cover_resizer.py,
                     mp3_tools_launcher.py, __init__.py
    shared/          paths.py, subprocess_utils.py, logging_setup.py, __init__.py
Windows/ only:       Dockerfile   (optional Linux container — intentional divergence)
```

The old `Windows/epub2tts-edge`, `Windows/mp3_scripts`, `MacOS/epub2tts-edge`, `MacOS/mp3_scripts`
source folders (and the empty `files/` folders) were removed after migration was verified.
The `.venv` that lived inside the TTS source repo went with it; **Phase 2's bootstrap rebuilds a
fresh `.venv` at `Windows/.venv` / `MacOS/.venv`.**

**Import convention (decided + applied in Phase 1):** `scripts/` is the single import root.
All cross-module imports are absolute `tts.*` / `mp3_tools.*`; imports *inside* the
`epub2tts_edge/` subpackage stay relative (`.runner`, `.epub2tts_edge`). The directly-runnable
entry scripts (`epub2tts_gui.py`, `batch_convert.py`) prepend `scripts/` to `sys.path` at the top
so they resolve `tts.*` whether run standalone or imported by the launcher. Nothing puts
`scripts/tts/` on the path, so the `epub2tts_edge` subpackage is only ever imported as
`tts.epub2tts_edge` — no double-import trap.

---

## 3. Subsystems

| Subsystem | Eventual location | Role |
|---|---|---|
| Launcher | `scripts/launcher.py` | Unified Tk GUI; sidebar of tools + single swappable content panel (**built, Phase 3**). Each tool's `build_ui(parent)` is built once and shown/hidden on selection; Phase-6 Metadata Editor slot auto-hidden until its module exists. |
| TTS | `scripts/tts/` | EPUB / PDF / TXT → MP3 (Edge TTS + Kokoro local AI) |
| M4B Converter | `scripts/mp3_tools/m4b_converter.py` | Batch M4B → clean MP3 |
| MP3 Tool | `scripts/mp3_tools/mp3_tool.py` | Combine MP3s, time-edit, bulk ID3 tagging |
| M4B Maker | `scripts/mp3_tools/m4b_maker.py` | MP3s → M4B with chapters, metadata, cover, **series tags** (new in Phase 6) |
| Cover Image Converter | `scripts/mp3_tools/cover_resizer.py` | Pad/crop cover art to square |
| M4B Metadata Editor | `scripts/mp3_tools/m4b_metadata_editor.py` | **Built in Phase 6** — edit existing M4B tags (Title/Author/Album/Year/Genre/Comment/Series/cover) without re-encoding; **preserve-by-default** (blank = unchanged), single-file pre-fill + multi-file batch overwrite; Cancel + per-file log. **v0.1.1:** writes **copies** (never the original) to `Downloads/M4B-Metadata-N`; adds a **Clear All Tags (keep chapters)** button and a paged **per-file chapter-title import** (positional; blank line = unchanged). |
| Shared | `scripts/shared/` | `paths.py` (**v0.1.1 added** `downloads_dir`/`next_output_dir`/`TOOL_SLUGS`/`avoid_input_overwrite`), `subprocess_utils.py` (+`check_output`/`reveal_in_file_manager`), `settings.py` (Phase 3), `ffmpeg_utils.py` (Phase 3), `cancellation.py` (Phase 4), `metadata.py` (Phase 5 — mutagen `read_m4b_tags`/`write_m4b_tags` + series atoms + ffmpeg tag-arg helpers; **Phase 6 added** comment/genre/year atoms, `cover_path` embed + `has_cover`; **v0.1.1 added** `clear_metadata_keep_chapters`, `read_chapter_titles`, `apply_chapter_titles`; **v0.1.2** broadened `read_m4b_tags`'s series reader to resolve from the canonical freeform atom → any other vendor freeform atom (e.g. `----:com.pilabor.tone:SERIES`) → the native movement atoms, returning series provenance (`series_source`/`series_atom`) + a `describe_series_atoms` helper, and made series *writes* strip any same-suffix shadowing atom so an overwrite actually takes), `logging_setup.py`, `bootstrap.py`, `version.py` (single
source of truth, **`VERSION = "0.1.1"`**), `release.py` (Phase 8 — dev-only zip packager, never imported by
the app). |

---

## 4. Source Repos (Migration Origin) — Phase 0 inventory

Two source repos, each with a Windows and a macOS variant (four trees total).

### 4a. `epub2tts-edge` (TTS) — fork of github.com/aedocw/epub2tts-edge, v1.2.9, GPL-3.0

| File | Public entry points | External deps | Notes / assumptions |
|---|---|---|---|
| `epub2tts_edge/epub2tts_edge.py` (755 ln) | `main()` (CLI), `export()`, `get_book()`, `read_book()`, `make_m4b()`, `make_mp3()`, `add_cover()`, `generate_metadata()`, `run_edgespeak()`, `parallel_edgespeak()`, `intra_sentence_chunks()`, `ensure_punkt()` | tqdm, bs4, ebooklib, edge_tts, lxml, mutagen, nltk, PIL, pydub | **cwd-dependent**: writes `part*.flac`, `sntnc*.mp3`, `pgraphs*.flac`, `FFMETADATAFILE`, `filelist.txt` into the process cwd. `make_m4b`/`make_mp3` call `subprocess.run(["ffmpeg",...])` **directly** (must route through `shared/subprocess_utils` in Phase 3). `check_for_file()` uses blocking `input()` — unusable from GUI; only hit on CLI path. |
| `epub2tts_edge/runner.py` (206 ln) | `run_conversion_job(...)` | ebooklib | **The cwd-safety wrapper.** Does `tempfile.mkdtemp()` + `os.chdir(tmp)`, runs the conversion there, moves the final artifact to `output_dir`, restores cwd, deletes temp. Imports `from pdf_extractor import pdf_to_txt` (top-level — needs path fix on restructure). This is the function the GUI/CLI should always call (never the raw `read_book`). |
| `epub2tts_gui.py` (658 ln) | `main()` (builds its own `Tk()` root) | tkinter, ebooklib | The current standalone GUI. **Single-file MP3 + batch-PDF MP3.** Captures worker stdout/stderr via `QueueWriter` → log pane. Imports `batch_convert`, `voice_registry`, `kokoro_synth`, `pdf_extractor` (top-level). **No Cancel button** (Phase 4.2 must add). Hardcodes `audio_format="mp3"` for the Edge single-file path. Mac variant inserts `sys.path.insert(0, .../scripts)` and uses a taller window. |
| `voice_registry.py` (170 ln) | `VOICES`, `get_voice()`, `display_labels()`, `DEFAULT_VOICE_LABEL` | dataclasses only | Central list of **11 voices** = 6 Edge + 5 Kokoro. Each carries a `timing_preset` dict that maps to GUI fields. Clean, no I/O. |
| `kokoro_synth.py` (199 ln) | `kokoro_file_to_mp3()`, `synthesize_text_to_mp3()`, `split_into_chunks()` | numpy, soundfile, pydub, **kokoro (lazy import)** | Local AI TTS. Lazy-imports `kokoro.KPipeline` to avoid loading torch at startup. ~300 MB model download on first use → `~/.cache/huggingface/`. **PyPI `kokoro` requires Python 3.10–3.12** (not 3.13+). |
| `pdf_extractor.py` (131 ln) | `pdf_to_txt()`, `extract_text_from_pdf()` | PyMuPDF (`fitz`) | Heuristic PDF→text: dehyphenation, soft-line rejoin, page-number/running-head stripping, cross-page block merge. Raises if PDF is scanned/image-only. Phase 7.2 flags footnote/multi-column edge cases. |
| `batch_convert.py` (302 ln) | `run_batch_convert()`, `convert_single_pdf()` | edge_tts, pydub, PyMuPDF | Batch folder-of-PDFs → one MP3 each, `ThreadPoolExecutor`, natural-sort, resume (skip existing), per-chunk retry w/ backoff, temp chunks under `output/.tmp_chunks/`. `progress_callback(name, done, total, status)` hook used by the GUI. |
| `setup_env.py` (498 ln) | `main()`, `--uninstall`, `--skip-kokoro-download` | stdlib + winget/brew/apt | The existing **Path-A bootstrap**: checks Python ≥3.11, creates `.venv`, installs requirements, installs ffmpeg (winget `Gyan.FFmpeg` / brew / apt), optional espeak-ng, pre-downloads Kokoro. **Becomes `shared/bootstrap.py` in Phase 2** (adapt, don't rewrite). Uses blocking `input()` for uninstall confirm. |
| `setup.py` | packaging | setuptools | `py_modules` lists the 5 root modules + `epub2tts_edge` package. |
| `Dockerfile` | — | — | Optional Linux container. Phase 1.2 says: keep with Windows side only. |

**requirements.txt** (TTS): beautifulsoup4, ebooklib, edge-tts, lxml, mutagen, nltk, pillow, pydub, `audioop-lts; python_version>="3.13"`, pymupdf, setuptools, tqdm, soundfile, scipy, `kokoro>=0.9.2; python_version<"3.13"`. **None are version-pinned** — violates the global "pin everything" rule; Phase 2 must pin all of these.

### 4b. `mp3_scripts` (MP3 Tools) — local origin, no upstream

| File | Role | External deps | Notes |
|---|---|---|---|
| `launcher.py` (218 ln) | Old standalone MP3-tools launcher | tkinter | **Spawns each tool as a separate process** (`subprocess.Popen`) — the "bag of utilities" pattern Phase 3 replaces with a single content panel. Already prefers `pythonw.exe` to avoid console flashes. Renamed to `mp3_tools_launcher.py` in Phase 1, **absorbed** (not used) in Phase 3. |
| `tools/mp3_tool-v5-4.py` (780 ln) | **MP3 Tool** | tkinter, mutagen, ffmpeg | See full inventory in §5a below. |
| `tools/m4b_maker-v5-3.py` (704 ln) | **M4B Maker** | tkinter, PIL (optional), ffmpeg | See §5a. Subclasses `tk.Tk`. **No series tag yet** (Phase 6.1 adds). |
| `tools/m4b_converter-v1-2.py` (375 ln) | **M4B Converter** | tkinter, ffmpeg | Batch M4B→MP3 (libmp3lame VBR), optional bulk metadata + auto-track-number, threaded. Subclasses `tk.Tk`. |
| `tools/cover_resizer-v2.py` (302 ln) | **Cover Image Converter** | tkinter, PIL, optional pillow-heif | Square letterbox (no crop) or center-crop; JPG/PNG/HEIC; threaded. Subclasses `tk.Tk`. |

**requirements.txt** (MP3 tools): mutagen, pillow (pillow-heif optional, commented). Not pinned.

### 4c. Windows ↔ macOS divergence (verified by diff in Phase 0)

- **TTS core is byte-identical** across platforms: `epub2tts_edge/epub2tts_edge.py` and `runner.py` show 0 differing lines; `batch_convert.py`, `kokoro_synth.py`, `pdf_extractor.py`, `voice_registry.py` are identical too.
- **Only structural divergence:** Windows TTS uses a **flat layout** (helper modules at repo root); macOS puts them under a **`scripts/` subfolder** and the Mac GUI adds `sys.path.insert(0, .../scripts)`. After Phase 1 both collapse into `scripts/tts/`, erasing this difference.
- `setup_env.py`: 9 differing lines (platform paths/hints). `epub2tts_gui.py`: Mac uses a taller window (720×1000) and more compact labels — cosmetic.
- **MP3 tools are essentially identical:** `m4b_converter`, `m4b_maker`, `mp3_tool` show 0 diff; `cover_resizer` differs by 1 line (file-dialog filter uses spaces vs `;`); `launcher.py` differs by 9 lines (font family `Segoe UI` vs `Helvetica Neue`, setup-hint filename).

**Implication:** migration can use a single shared codebase per subsystem with tiny platform shims (font, file-dialog filter separator, path helpers). This is worth preserving deliberately rather than maintaining two divergent copies — see §5 decision.

---

## 5. Key Design Decisions

- **Bundling strategy: Path A (install-on-first-run bootstrap). DECIDED.**
  Rationale: the existing `setup_env.py` already implements Path A well, and the TTS engine depends on **Kokoro → PyTorch (multi-GB)**, which makes a PyInstaller/py2app self-contained build (Path B) fragile (torch bundling issues, antivirus false-positives on PyInstaller exes, huge artifacts, full rebuild per update). Path A keeps the download small, updates trivial (replace `scripts/`), and reuses proven code. Phase 2 refactors `setup_env.py` → `shared/bootstrap.py`.
- **Launcher UX: sidebar + single swappable content panel. DECIDED + BUILT (Phase 3).** (vs. tabs / separate windows). Each tool exposes `build_ui(parent_frame)`. **Phase 3 refinement:** rather than literally clearing/repopulating one frame, the launcher builds each tool into its own container **once** and shows/hides (raises) it on selection — same single-app feel, but in-progress state (file lists, typed metadata) survives switching. Tool modules are **lazy-imported and guarded**: a missing optional dependency renders a friendly in-panel error instead of crashing the launcher. The Phase-6 Metadata Editor is pre-registered but auto-hidden via `importlib.util.find_spec` until its module exists. See §8 sketch.
- **Console-window suppression: IMPLEMENTED (Phase 3).** Run the launcher under **`pythonw.exe`** on Windows; **every** tool subprocess call routes through `shared/subprocess_utils.py` (`CREATE_NO_WINDOW` + `STARTUPINFO/SW_HIDE`). Audit confirms zero direct `subprocess.*` in tool code. `pydub`/`edge-tts` spawn ffmpeg internally; the canonical fix is running under `pythonw` **plus** `ffmpeg_utils.configure_pydub()` which pins `AudioSegment.converter/ffmpeg/ffprobe` and `get_prober_name` to the resolved binary (bundled `resources/bin/` first, else PATH). Residual brief flashes from pydub on Windows, if any, are eliminated by the `pythonw` launch.
- **ffmpeg resolution (Phase 3): `shared/ffmpeg_utils.py`.** Single place that resolves ffmpeg/ffprobe (bundled portable build in `resources/bin/` → system PATH), used by every tool when building command lists (`ffmpeg_cmd()` / `ffprobe_cmd()`) so behaviour is identical regardless of what's on PATH.
- **Settings persistence (Phase 3): `shared/settings.py`.** Atomic JSON at `resources/settings.json` (temp-file + `os.replace`; never raises on missing/corrupt). Launcher persists window geometry + last-selected tool; the module is the home for the per-tool remembered fields (input/output folders, voice, bitrate, timing preset) wired in later phases.
- **Metadata library: mutagen** (already a TTS dep) for the shared `metadata.py`. ffmpeg writes tags at encode time; mutagen reads/edits after the fact and is required for the preserve-unset Metadata Editor.
- **Series tag format (Phase 6.1): freeform MP4 atoms `----:com.apple.iTunes:SERIES` and `----:com.apple.iTunes:SERIES-PART`.** See §6 research — this is what Audiobookshelf's ffprobe-based scanner actually reads (surfaced as `series` / `series-part`).
- **Keep one shared codebase per subsystem with thin platform shims** rather than two divergent Win/Mac copies, since Phase 0 proved the code is ~identical. The repo still ships physically separate `Windows/` and `MacOS/` trees (per the structure rule and for clean zips), but their `scripts/` contents should be kept in lockstep; document any intentional divergence here.
- **Bootstrap architecture (Phase 2): thin launcher script + one cross-platform `bootstrap.py`. DECIDED.**
  `setup_and_run.bat` / `.command` stay short and readable; all logic lives in
  `scripts/shared/bootstrap.py`, which is kept **byte-identical** in both OS trees (platform
  differences are branches inside it, verified by hash). The launcher scripts only: (a) **fast-path**
  — if `.venv` exists, launch the GUI via `pythonw.exe` (Windows) / detached (Mac) with **no console**
  and exit; (b) **first run** — locate *any* Python (or winget/brew-install 3.12), then hand off to
  `bootstrap.py`. `bootstrap.py` itself locates/installs **Python 3.12 specifically** for the venv
  (system Python may be 3.13, which loses Kokoro), creates `<os_root>/.venv`, pip-installs the pinned
  requirements, ensures ffmpeg (winget `Gyan.FFmpeg` / brew, else portable build into `resources/bin/`),
  optionally pre-downloads Kokoro, then launches the GUI detached. First run shows a **Tk dialog**
  (intro + Kokoro opt-in checkbox, default checked) with a progress bar + live log; everything is
  tee'd to `resources/logs/setup_YYYY-MM-DD.log`. `bootstrap.py` depends on **stdlib + Tk only**
  (it runs before the venv exists). Useful flags: `--launch-only` (fast-path launch, used by the
  `.bat`), `--self-test` (detection-only, no installs — for dev verification), `--skip-kokoro-download`.
- **Known minor (Windows):** a `.bat` entry point always flashes its own cmd window briefly on launch;
  the GUI itself runs under `pythonw` with no console. Eliminating the flash entirely would need a
  `.vbs`/shortcut shim — deferred as not worth the added opacity for a curious user opening the `.bat`.
- **`.venv` location:** inside `Windows/` and `MacOS/` (not at root — keeps root at exactly 5 items).
- **Settings storage:** `resources/settings.json` via `shared/settings.py`.
- **Output locations:** ~~the legacy tools hardcode `~/Downloads/edited_mp3s-*`, `~/Downloads/M4B-Output-*`, `~/Downloads/m4b_converter_output-*`.~~ **DONE (Phase 5):** routed through `shared/settings.py` — each tool remembers its input/output (and M4B Maker its cover) folder under per-tool keys, **defaulting to the user's home directory**, persisted on every successful run and pre-filled into the file dialogs; the three output-producing tools gained an "Output folder" picker. The sequential auto-named subfolders are unchanged but now created inside the remembered base. **Superseded in v0.1.1:** the output default is now a fresh `Downloads/<Tool>-N` decided once per launch (via `paths.next_output_dir`), created lazily on first write; **Browse** redirects for the current run only and is **no longer persisted** across sessions; the per-tool nested `*-output-N` subfolders are removed (the `-N` now lives in the Downloads folder name). Output is **copy-based** everywhere (originals never modified) except the Cover Image in-place toggle. Input-dir settings keys (dialog `initialdir`) are unchanged.

---

## 6. GitHub / Docs Research Findings (Phase 0)

- **Audiobookshelf series metadata (authoritative, from audiobookshelf.org docs + issue #2471):**
  - Series name ← tag `series` (primary) or `mvnm` (fallback).
  - Series sequence ← tag `series-part` (primary) or `mvin` (fallback).
  - **ABS scans with ffprobe, and ffprobe does NOT surface the native MP4 movement atoms (`©mvn`/`mvin`).** Therefore write the **freeform** atoms `----:com.apple.iTunes:SERIES` and `----:com.apple.iTunes:SERIES-PART` (UTF-8 bytes via mutagen) — ffprobe exposes these exactly as `series` / `series-part`. Verify in Phase 6 Debug Gate with `ffprobe -show_format`.
- **mutagen freeform write pattern:**
  ```python
  from mutagen.mp4 import MP4
  m = MP4("book.m4b")
  m["----:com.apple.iTunes:SERIES"] = [b"The Stormlight Archive"]
  m["----:com.apple.iTunes:SERIES-PART"] = [b"2"]
  m.save()
  ```
- **Console suppression / `pythonw`:** confirmed canonical pattern is `CREATE_NO_WINDOW` + hidden `STARTUPINFO` for subprocesses, launcher under `pythonw.exe`. The legacy MP3 launcher already implements pythonw detection.
- **Kokoro Python gate:** PyPI `kokoro` wheels require Python <3.13; bootstrap should target **Python 3.12** specifically.

**Sources:**
- [Audiobookshelf book scanner / audio metadata docs](https://www.audiobookshelf.org/guides/book-scanner/)
- [advplyr/audiobookshelf issue #2471 — movementname/movement vs mvin/mvnm](https://github.com/advplyr/audiobookshelf/issues/2471)
- [advplyr/audiobookshelf discussion #1481 — ID3 Series tag](https://github.com/advplyr/audiobookshelf/discussions/1481)
- [mutagen MP4 API docs](https://mutagen.readthedocs.io/en/latest/api/mp4.html)
- [Audiobookshelf ffprobe metadata guide](https://www.audiobookshelf.org/guides/ffprobe/)

### 6a. MP3 Tool feature inventory (pre-fills Phase 5.2 deliverable)

`mp3_tool-v5-4.py` exposes three operations, all batch (apply to the whole imported list), all stripping existing metadata first:
1. **Combine MP3s → one MP3.** Fast path = ffmpeg `concat` demuxer + libmp3lame `-q:a 2`; if a gap between tracks is requested or fast fails, falls back to **safe path** (normalize each to 44.1k/16-bit stereo WAV, insert silence WAVs, concat). Writes `combined_time-stamps.txt`.
2. **Time edit (add/remove seconds at end of each track).** Positive = pad silence (`anullsrc` + concat filter); negative = trim via `-t`. Outputs to a fresh `~/Downloads/edited_mp3s-*`.
3. **Bulk ID3 write.** Strips all tags (`-map_metadata -1`), then writes only: title (pasted chapter title > Title field > filename), artist, albumartist, album, tracknumber (auto-number with start #). Chapter-titles paste box maps line N → file N.

`ensure_ffmpeg_available()` checks ffmpeg+ffprobe at startup. All ffmpeg runs go through `run_ff()` (currently raw `subprocess.run`).

---

## 7. External Dependencies

| Tool | Purpose | Install path |
|---|---|---|
| Python 3.12 (target; 3.11+ min, **<3.13 for Kokoro**) | Runtime | winget / Homebrew (auto by bootstrap) |
| ffmpeg + ffprobe | Audio encode/decode, probe, tagging | winget `Gyan.FFmpeg` / brew / portable to `resources/bin/` |
| espeak-ng | NLTK tokenizer backend | apt / brew (optional, recommended) |
| edge-tts | Edge TTS network client | pip |
| kokoro (+ torch) | Local AI TTS, Python 3.10–3.12 | pip (only on <3.13) |
| mutagen | Audio metadata read/write | pip |
| PyMuPDF (fitz) | PDF text extraction | pip |
| pydub | Audio assembly (drives ffmpeg) | pip |
| numpy, soundfile, scipy | Kokoro audio plumbing | pip |
| beautifulsoup4, ebooklib, lxml | EPUB parsing | pip |
| nltk | Sentence tokenization (punkt/punkt_tab) | pip |
| pillow (+ pillow-heif optional) | Cover image processing / preview | pip |
| tqdm | CLI progress (GUI suppresses) | pip |

---

## 8. Unified Launcher UX Sketch (Phase 3 target)

```
+--------------------------------------------------------------+
|  Audiobook Creation Tool                            [_][□][X]|
+--------------------------------------------------------------+
|  ┌────────────────┐                                          |
|  │ TTS Audiobook  │  ← Sidebar: 6 tool buttons               |
|  │ M4B Converter  │                                          |
|  │ MP3 Tool       │     ┌───────────────────────────────┐    |
|  │ M4B Maker      │     │   Selected tool's build_ui()   │    |
|  │ Cover Image    │     │   swaps into this content frame│    |
|  │ M4B Metadata   │     │                               │    |
|  └────────────────┘     └───────────────────────────────┘    |
+--------------------------------------------------------------+
|  Status: Ready.                     |  Log: [open log folder] |
+--------------------------------------------------------------+
```

- Left sidebar = 6 buttons. Right = one content `Frame` cleared/repopulated per selection.
- Each tool refactored to `build_ui(parent: tk.Frame) -> None`; standalone `main()` kept for debug (wraps `build_ui` in a private `Tk()`).
- Long operations run on worker threads, stream to a shared log pane, and expose a **Cancel** button (Phase 4.2 / 5.1).
- Remembered in `settings.json`: last input/output folders, voice, bitrate, timing preset, window size, last sidebar selection.

---

## 9. How to Run

**Users (post Phase 2):** double-click `setup_and_run.bat` (Windows) or `setup_and_run.command` (Mac).

**Developers (post Phase 1).** The standalone `.venv` was removed with the source repos; until
Phase 2's bootstrap rebuilds `Windows/.venv` (and installs requirements), run with any
Python 3.11/3.12 that has the deps installed. Each tool runs from the `scripts/` root so the
`tts.*` / `mp3_tools.*` imports resolve:
```
cd Windows\scripts
python tts\epub2tts_gui.py                 # TTS GUI (pythonw.exe to hide console)
python mp3_tools\mp3_tools_launcher.py     # legacy MP3 launcher (absorbed in Phase 3)
```
Smoke-test imports (run from `Windows\scripts`):
```
python -c "from tts.epub2tts_edge.epub2tts_edge import DEFAULT_SPEAKER"
python -c "from mp3_tools import m4b_converter"
```
**Post Phase 3 (unified launcher):**
```
cd Windows
.venv\Scripts\pythonw.exe scripts\launcher.py
```

---

## 10. How to Test

- **Static:** `python -m py_compile` every `.py`; `ruff check scripts/`; `pip check` inside `.venv`.
- **Manual:** the Phase 7 test matrix (§12) — every cell on both platforms.
- **Regression:** keep an uncommitted `test_assets/` with a short EPUB, a short PDF, a few MP3s, and a sample M4B; rerun the matrix after refactors. (`Windows/epub2tts-edge/test_batch_baseline` / `test_batch_post` already exist from upstream testing.)

---

## 11. Known Issues / Deferred Items (Phase 0)

- **v0.1.1 update (2026-05-30):** all transforming tools now write **copies** to a fresh
  `Downloads/<Tool>-N` folder (decided once per launch, lazily created, Browse not persisted) so
  imported originals are never modified — the only in-place exception is the Cover Image tool's
  explicit overwrite toggle. Two bugs were found and fixed during the build (both pre-commit): the
  Metadata Editor's single-file pre-fill re-applying over a "Clear All Tags" wipe, and the ffmpeg
  chapter-title re-mux dropping the freeform series atoms (now snapshotted/restored via mutagen).
  **Carried deferrals (unchanged from v0.1.0):** the clean-machine one-click install on Python 3.12,
  the macOS matrix column (no host), and the final visual no-console-flash confirmation.

- ~~TTS requirements are **unpinned**; MP3 requirements too. Pin all in Phase 2.~~ **DONE (Phase 2):** every package in both `requirements.txt` pinned to an exact version (verified against PyPI 2026-05-28); markers guard `kokoro` (<3.13) and `audioop-lts` (>=3.13).
- ~~`epub2tts_edge.make_m4b` and all MP3 tools call ffmpeg via **raw `subprocess`** — must move to `shared/subprocess_utils`.~~ **DONE (Phase 3):** all tool subprocess calls routed through the hidden-console wrapper; audit shows zero direct `subprocess.*` in tool code. (Installer `bootstrap.py`/`setup_env.py` legitimately use raw subprocess and are out of scope.)
- **Phase 2 deferred to a live test (Debug Gate 2):** the end-to-end fresh-machine install path (winget/brew Python 3.12 → `.venv` → pinned pip install incl. torch/Kokoro → ffmpeg → optional 300 MB model → GUI launch) is built and statically verified but has **not** been run live end-to-end, because it installs system software and downloads GBs. **Phase 7 verified the pieces live on Windows** — `bootstrap.py --self-test` clean, `python -m venv` works, and a throwaway venv resolved the **full pinned `requirements.txt`** against PyPI (kokoro correctly excluded on 3.13) — but the full one-click install on a clean machine with Python 3.12 (+ torch/Kokoro + 300 MB model) is **still open**. Run it on a clean VM (or the target machine) before release. The portable-ffmpeg fallback download (BtbN build into `resources/bin/`) is likewise untested live.
- **macOS bootstrap is untested** — built to mirror Windows but no Mac was available this session. The `.command` Terminal-auto-close (`osascript`) is best-effort.
- ~~Legacy tools **hardcode `~/Downloads/...` output folders** — route through settings/`paths.py` in Phase 5.~~
  **DONE (Phase 5):** all four MP3 tools route input/output folders through `shared/settings.py`
  (per-tool keys, default = home, persisted on success); a grep confirms no `~/Downloads` remains in
  tool code. Phase 5 also gave the MP3 tools a **Cancel button** (reusing `shared/cancellation.py`)
  and added `shared/metadata.py`; M4B Maker and MP3 Tool moved their conversions onto worker threads.
- ~~TTS GUI has **no Cancel button** — add in Phase 4.2.~~ **DONE (Phase 4):** Cancel button added,
  wired into all four conversion paths via `shared/cancellation.py` (checkpoints between
  chapters/paragraphs/chunks; temp cleanup; "Cancelled." log).
- ~~TTS worker thread read Tk variables off-thread~~ **FIXED (Phase 4):** caused
  `RuntimeError: main thread is not in main loop` during conversion; all Tk reads moved to the main
  thread in `run_job`, worker uses plain copies + the log queue only.
- `check_for_file()` and `setup_env.uninstall()` use blocking `input()` — fine for CLI, must not be reachable from GUI.
- PDF extraction heuristics may over/under-merge on footnotes / multi-column — **Phase 7 ran
  `pdf_to_txt` live on a real test-files chapter PDF (5322 chars extracted cleanly) and on tiny
  generated PDFs through to TTS audio**; the footnote / multi-column edge cases remain a manual spot-check
  on a complex PDF, not yet exercised.
- **Deferred live mid-operation cancels are now resolved (Phase 7):** a real TTS conversion cancelled
  mid-run raised `ConversionCancelled` and left **0 leaked temp dirs** (Gate 4); a real M4B encode
  cancelled at a stage boundary removed its partial output folder (Gate 5). The only cancel nuance still
  not exercised is interrupting a *single long ffmpeg subprocess* mid-encode (cancel lands at stage/file
  boundaries, by design).

---

## 12. Test Matrix (filled Phase 7 — 2026-05-29, Windows live pass)

Legend: **PASS** = run live this session and verified · **SKIP(no-Mac)** = no macOS host
available · **SKIP** / **KL** = skipped with a documented known-limitation (see notes).
All Windows runs used the real `test-files/` assets (copied to a temp working dir with a space
in its path; originals never modified) and drove the real tool worker code paths.

| Test | Windows | macOS |
|---|---|---|
| Fresh install via `setup_and_run` | KL¹ | SKIP(no-Mac) |
| Re-launch under 2s | PASS² | SKIP(no-Mac) |
| TTS EPUB → MP3 (Edge voice) | PASS (17.8 s mp3) | SKIP(no-Mac) |
| TTS EPUB → MP3 (Kokoro voice) | KL³ | SKIP(no-Mac) |
| TTS PDF → MP3 | PASS (13.1 s mp3) | SKIP(no-Mac) |
| TTS batch folder | PASS (2/2 PDFs) | SKIP(no-Mac) |
| TTS cancel mid-batch | PASS (Gate 4: `ConversionCancelled`, 0 leaked temp dirs) | SKIP(no-Mac) |
| M4B Converter batch | PASS (m4b→mp3, tags written) | SKIP(no-Mac) |
| MP3 Tool (combine / time-edit / ID3) | PASS (all three ops) | SKIP(no-Mac) |
| M4B Maker with chapters | PASS (3 chapters via ffprobe) | SKIP(no-Mac) |
| M4B Maker with series tag | PASS (ffprobe `series`/`series-part`) | SKIP(no-Mac) |
| Cover Image Converter (square/tall) | PASS (letterbox + center-crop → 512²) | SKIP(no-Mac) |
| Metadata Editor single-file | PASS (Gate 6: edit persists, others preserved) | SKIP(no-Mac) |
| Metadata Editor multi-file | PASS (batch overwrite both files) | SKIP(no-Mac) |
| Metadata Editor blank-field preserve | PASS (blank field keeps each file's tag) | SKIP(no-Mac) |
| No console flash anywhere | PASS⁴ (mechanism-verified) | SKIP(no-Mac) |
| Unicode filenames | PASS (`Café_テスト_Ωmega.mp3`) | SKIP(no-Mac) |
| Paths with spaces | PASS (working dir + outputs under `phase7 work dir/`) | SKIP(no-Mac) |
| Settings persist across restart | PASS (write → cache reset → read-back) | SKIP(no-Mac) |

**Notes / known-limitations:**
1. **Fresh one-click install** — the *pieces* were verified live on Windows: `bootstrap.py --self-test`
   ran clean (detects venv/requirements/ffmpeg/launch target), `python -m venv` succeeded, and a
   throwaway venv resolved the **full pinned `requirements.txt`** against PyPI (`Would install …
   edge-tts-7.2.8, mutagen-1.47.0, scipy-1.17.1, audioop-lts-0.2.2, …`; `kokoro` correctly excluded by
   its `<3.13` marker). The *full* end-to-end one-click install (winget Python 3.12 → multi-GB
   torch/Kokoro → 300 MB model → first GUI open) was **not** run live — it mutates the host and needs
   Python 3.12. Run it on a clean VM / the target machine before release (Debug Gate 2, still open).
2. **Re-launch under 2s** — measured the Python-side cost (import launcher + construct + build all six
   tools) at **~1.25 s**. The true `.venv` fast-path double-click→window time needs a built `.venv`
   (none on this dev box yet); confirm during the Gate 2 fresh-install pass.
3. **Kokoro voice** — this machine runs Python **3.13**; the pinned `kokoro` wheel requires **<3.13**,
   so it is not installable here (by design — the bootstrap targets 3.12). Untestable until run on the
   3.12 venv. Edge voices fully cover the TTS pipeline live.
4. **No console flash** — mechanism verified: audit shows **zero** direct `subprocess.*` calls in tool
   code (all route through `shared/subprocess_utils`, which applies `CREATE_NO_WINDOW` + hidden
   `STARTUPINFO`), and the launcher runs under `pythonw.exe`. The final *visual* confirmation (watch for
   any black window during a real double-click run) is the one inherently manual check left for release.

**macOS column:** every cell is SKIP(no-Mac) — no macOS host was available this session. The code is
kept byte-identical across the `Windows/`↔`MacOS/` `scripts/` trees (verified by hash; `compileall`
clean on both), so the macOS pass is expected to mirror Windows once a Mac is available, modulo the
documented `.command` Terminal-auto-close and ffmpeg-via-Homebrew differences.

---

## 13. Release Process

1. All test matrix cells PASS.
2. CHANGELOG `[Unreleased]` → `[X.Y.Z] - YYYY-MM-DD` (both OS trees).
3. Bump `VERSION` in `scripts/shared/version.py` (single source of truth; kept identical in both trees).
4. Run `python Windows/scripts/shared/release.py` — zips each OS folder + the root README/launcher
   into `dist/AudiobookTool-{Windows,MacOS}-vX.Y.Z.zip` (excludes `.venv`/`__pycache__`/`*.pyc`/`logs`/
   `settings.json`/`bin`/`test-files`) and prints this checklist. Attach both zips to the GitHub Release.
5. README download links updated.

**Done for v0.1.0 (Phases 8–9):** steps 2–5 are complete. Step 4 — `release.py` produced both zips and
`zipfile.namelist()` confirmed README + launcher at each archive root with zero excluded leaks
(Phase 8). **Phase 9 finished the public ship:** the GitHub remote
**[elmatthe/audiobook-creation-tool](https://github.com/elmatthe/audiobook-creation-tool)** exists with
all 8 branches + tag `v0.1.0` pushed (`master` default), the **GitHub Release
[v0.1.0](https://github.com/elmatthe/audiobook-creation-tool/releases/tag/v0.1.0)** is published with
both zips attached (verified downloadable), and the README has direct download links (step 5). The
release checklist is therefore **complete**. The only items still outstanding are the live
*verification* tasks that don't gate the publish: the Debug Gate 2 clean‑machine install on Python
3.12, the macOS matrix column on a Mac, and the final visual no‑console‑flash confirmation.

---

## 14. Project Owner Notes (persistent)

- Root folder must always contain exactly 5 items.
- No visible console windows during normal operation.
- Non-technical users are the primary audience for the installed app.
- Windows and macOS folders mirror each other in structure; keep `scripts/` contents in lockstep.
- Pin every dependency to an exact version.
- Upstream credit (GPL-3.0): epub2tts-edge (Christopher Aedo), edge-tts, Kokoro-82M.
