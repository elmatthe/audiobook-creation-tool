# Project Briefing — Audiobook Creation Tool

> **Audience:** future Claude chat sessions and any new contributor.
> **Purpose:** be the single document you can hand someone (or paste into a new chat) to get them fully oriented without re-explaining the project.
> **Maintained by:** Claude Code, updated at the end of every session.
> **Status:** Phase 1 (Repository Restructure & File Migration) complete — all source code now
> lives under `scripts/{tts,mp3_tools,shared}` in both OS folders, imports rewired to the `tts.*` /
> `mp3_tools.*` convention, no behavior change. **Phase 2 (setup_and_run bootstrap) is next.**

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
| Launcher | `scripts/launcher.py` | Unified Tk GUI; sidebar of 6 tools, single content panel (built in Phase 3) |
| TTS | `scripts/tts/` | EPUB / PDF / TXT → MP3 (Edge TTS + Kokoro local AI) |
| M4B Converter | `scripts/mp3_tools/m4b_converter.py` | Batch M4B → clean MP3 |
| MP3 Tool | `scripts/mp3_tools/mp3_tool.py` | Combine MP3s, time-edit, bulk ID3 tagging |
| M4B Maker | `scripts/mp3_tools/m4b_maker.py` | MP3s → M4B with chapters, metadata, cover, **series tags** (new in Phase 6) |
| Cover Image Converter | `scripts/mp3_tools/cover_resizer.py` | Pad/crop cover art to square |
| M4B Metadata Editor | `scripts/mp3_tools/m4b_metadata_editor.py` | **New in Phase 6** — edit existing M4B tags; preserves untouched fields |
| Shared | `scripts/shared/` | `paths.py`, `subprocess_utils.py`, `metadata.py`, `settings.py`, `logging_setup.py`, `bootstrap.py` (created Phases 1–3) |

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
- **Launcher UX: sidebar + single swappable content panel. DECIDED.** (vs. tabs / separate windows). Each tool exposes `build_ui(parent_frame)`; the launcher clears and repopulates one content `Frame` on tool selection. Feels like one app, not a launcher of scripts. See §8 sketch.
- **Console-window suppression:** run the launcher under **`pythonw.exe`** on Windows; route **every** `subprocess` call through `shared/subprocess_utils.py` which applies `CREATE_NO_WINDOW` + `STARTUPINFO/SW_HIDE` on Windows. The old MP3 launcher already proves the `pythonw` detection pattern. Known caveat: `pydub`/`edge-tts` spawn ffmpeg internally; running everything under `pythonw` is the canonical fix for residual flashes (set `AudioSegment.converter` to our ffmpeg path).
- **Metadata library: mutagen** (already a TTS dep) for the shared `metadata.py`. ffmpeg writes tags at encode time; mutagen reads/edits after the fact and is required for the preserve-unset Metadata Editor.
- **Series tag format (Phase 6.1): freeform MP4 atoms `----:com.apple.iTunes:SERIES` and `----:com.apple.iTunes:SERIES-PART`.** See §6 research — this is what Audiobookshelf's ffprobe-based scanner actually reads (surfaced as `series` / `series-part`).
- **Keep one shared codebase per subsystem with thin platform shims** rather than two divergent Win/Mac copies, since Phase 0 proved the code is ~identical. The repo still ships physically separate `Windows/` and `MacOS/` trees (per the structure rule and for clean zips), but their `scripts/` contents should be kept in lockstep; document any intentional divergence here.
- **`.venv` location:** inside `Windows/` and `MacOS/` (not at root — keeps root at exactly 5 items).
- **Settings storage:** `resources/settings.json` via `shared/settings.py`.
- **Output locations:** the legacy tools hardcode `~/Downloads/edited_mp3s-*`, `~/Downloads/M4B-Output-*`, `~/Downloads/m4b_converter_output-*`. Phase 5 should route these through `shared/paths.py` / settings (remembered output folder) instead of hardcoding `Path.home()/"Downloads"`.

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

- TTS requirements are **unpinned**; MP3 requirements too. Pin all in Phase 2.
- `epub2tts_edge.make_m4b`/`make_mp3` and all MP3 tools call ffmpeg via **raw `subprocess`** — must move to `shared/subprocess_utils` (Phase 3/5) or console windows will flash.
- Legacy tools **hardcode `~/Downloads/...` output folders** — route through settings/`paths.py` in Phase 5.
- TTS GUI has **no Cancel button** — add in Phase 4.2.
- `check_for_file()` and `setup_env.uninstall()` use blocking `input()` — fine for CLI, must not be reachable from GUI.
- PDF extraction heuristics may over/under-merge on footnotes / multi-column — test in Phase 7.2.

---

## 12. Test Matrix (filled in Phase 7)

| Test | Windows | macOS |
|---|---|---|
| Fresh install via `setup_and_run` | | |
| Re-launch under 2s | | |
| TTS EPUB → MP3 (Edge voice) | | |
| TTS EPUB → MP3 (Kokoro voice) | | |
| TTS PDF → MP3 | | |
| TTS batch folder | | |
| TTS cancel mid-batch | | |
| M4B Converter batch | | |
| MP3 Tool (combine / time-edit / ID3) | | |
| M4B Maker with chapters | | |
| M4B Maker with series tag | | |
| Cover Image Converter (square/tall) | | |
| Metadata Editor single-file | | |
| Metadata Editor multi-file | | |
| Metadata Editor blank-field preserve | | |
| No console flash anywhere | | |
| Unicode filenames | | |
| Paths with spaces | | |
| Settings persist across restart | | |

---

## 13. Release Process

1. All test matrix cells PASS.
2. CHANGELOG `[Unreleased]` → `[X.Y.Z] - YYYY-MM-DD`.
3. Version bumped in both OS folders.
4. Zip each OS folder + root files; attach to GitHub Release.
5. README download links updated.

---

## 14. Project Owner Notes (persistent)

- Root folder must always contain exactly 5 items.
- No visible console windows during normal operation.
- Non-technical users are the primary audience for the installed app.
- Windows and macOS folders mirror each other in structure; keep `scripts/` contents in lockstep.
- Pin every dependency to an exact version.
- Upstream credit (GPL-3.0): epub2tts-edge (Christopher Aedo), edge-tts, Kokoro-82M.
