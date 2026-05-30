# Changelog

All notable changes to the Audiobook Creation Tool are recorded here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Version numbers follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

**Convention:**
- During active development, log work-in-progress under `[Unreleased]` with one entry per session.
- When a phase from `IMPLEMENTATION_PLAN.md` is complete, note it as a sub-bullet.
- On release, rename `[Unreleased]` to `[X.Y.Z] - YYYY-MM-DD` and start a new `[Unreleased]` section above it.
- Categories: **Added** / **Changed** / **Fixed** / **Deprecated** / **Removed** / **Security**.

---

## [Unreleased]

_Nothing yet — first section after the 0.1.0 release._

## [0.1.0] - 2026-05-29

### Added
- **Phase 8 (README + Release Packaging) — complete (docs + dev tooling; no app code
  changed).** Wrote the CV-grade **`README.md`** at the repo root (root only, never duplicated
  into the OS trees): one-paragraph summary, six-tool feature list, an ASCII launcher mockup,
  Windows + macOS install steps, a system-requirements table (Python 3.11–3.12 for Kokoro, 3.13
  for Edge-only), a per-tool usage walkthrough, a full architecture section
  (`scripts/{tts,mp3_tools,shared}` layout + the thread-safety / console-suppression / atomic-settings
  / ffmpeg-isolation / cancellation design decisions), upstream credits (epub2tts-edge — Christopher
  Aedo, GPL-3.0; edge-tts; Kokoro-82M), a GPL-3.0 license section, and the known limitations. Added
  **`scripts/shared/version.py`** (`VERSION = "0.1.0"`, the single source of truth) and the developer
  packaging helper **`scripts/shared/release.py`** — a stdlib-only, never-imported-by-the-app tool that
  zips each OS tree (excluding `.venv/`, `__pycache__/`, `*.pyc`, `resources/logs/`,
  `resources/settings.json`, `resources/bin/`, `test-files/`) into
  `dist/AudiobookTool-{Windows,MacOS}-vX.Y.Z.zip`, placing `README.md` + the correct double-click
  launcher at each archive root, then prints the Briefing §13 release checklist. Verified the produced
  zips with `zipfile.namelist()` (README + correct launcher at root, OS tree nested, zero excluded
  leaks). `version.py` and `release.py` mirrored byte-identical to both trees; `compileall` clean.
- **Phase 7 (Cross-Platform Test Matrix) — complete on Windows (live verification pass; no
  feature code changes).** Ran every deferred live debug-gate item (Gates 2–6) and filled the
  Briefing §12 matrix against the real `test-files/` assets. **18/18 applicable Windows rows PASS,
  zero unresolved FAILs**; **no bugs found**, so Phase 7.3 changed no tool code. The runs drove the
  *real* worker code paths (not mocks): Edge-TTS **EPUB→MP3** (17.8 s) and **PDF→MP3** (13.1 s) over
  the network, a **2-file PDF batch**, a mid-run **TTS cancel** raising `ConversionCancelled` with
  **0 leaked temp dirs** (Gate 4), an **M4B Maker** build with 3 ffprobe-verified chapters +
  `series`/`series-part` atoms, an **M4B-encode cancel** that removed its partial output folder
  (Gate 5), an **M4B→MP3** convert, **MP3-Tool** combine/time-edit/ID3, a **Cover-Resizer**
  letterbox+crop (→512²), and the **Metadata Editor** single-file round-trip + multi-file overwrite +
  blank-field preserve (Gate 6). All on a working dir **with a space in its path**, including a
  **Unicode-named** file; settings persisted across a simulated restart; the launcher listed and built
  **all six tools** live (no error frames, ~1.25 s). **Gate 2** verified live: `bootstrap.py
  --self-test` clean and a throwaway venv resolved the **full pinned `requirements.txt`** against PyPI
  (kokoro correctly excluded on Python 3.13). **Console-flash** suppression is mechanism-verified
  (zero direct `subprocess.*` in tool code; `subprocess_utils` applies `CREATE_NO_WINDOW`+hidden
  `STARTUPINFO`; launcher under `pythonw`). Documented known-limitations (not failures): **fresh
  one-click install** (needs a clean machine + Python 3.12 + multi-GB torch/Kokoro — not run live) and
  **TTS Kokoro voice** (this box is Python 3.13, above Kokoro's `<3.13` gate). The whole **macOS**
  column is **SKIP (no Mac available)**. `compileall` clean on both trees.
- **Phase 6 (M4B Metadata Editor + Series Tags) — complete (new editor tool, series
  fields in M4B Maker, verified headless).**
  - Added **`scripts/mp3_tools/m4b_metadata_editor.py`** — a new tool that opens one or
    more existing M4B files and edits their tags **without re-encoding**, built on
    `shared/metadata.py`'s `read_m4b_tags` / `write_m4b_tags` (mutagen). Editable fields:
    **Title, Author/Artist, Album, Year, Genre, Comment, Series Name, Series Part**, and a
    **cover image** (Browse/Clear). It is **preserve-by-default**: a blank field is never
    written, so each file keeps its existing tag; a field with a value overwrites that tag
    in every selected file. **Single-file mode** pre-fills the form from the file's current
    tags (and notes if a cover is already present); **multi-file mode** shows a *batch*
    notice and starts blank. The Save runs on a **worker thread** with the standard
    **Cancel** button (idle-disabled / active-enabled, cooperative cancellation *between
    files* via `shared/cancellation.py`) and reports **per-file success/failure** in the log
    pane (one failure doesn't abort the batch). Exposes `build_ui(parent)` for the launcher
    and a standalone `main()` for debugging.
  - **Extended `shared/metadata.py` (additively) for the editor's fields.** Added the text
    atoms **comment (`©cmt`), genre (`©gen`), year (`©day`)** to the mutagen read/write
    mapping, plus **`cover_path`** (embed a JPEG/PNG as the front `covr` atom, or clear it)
    and a **`has_cover`** boolean from `read_m4b_tags`. The Phase-5 ffmpeg encode-time
    helpers (`ffmpeg_metadata_args` / `ffmetadata_header_lines`) are unchanged, so the M4B
    Converter and the Maker's existing tag path are unaffected.
  - **Un-hid the Metadata Editor in the launcher sidebar.** The slot was pre-registered in
    Phase 3 and auto-hidden via `importlib.util.find_spec`; now that the module exists the
    guard reveals it automatically — **no launcher code change was needed** (verified the
    sidebar lists all six tools).
  - **Series tags in M4B Maker.** Added **Series Name** and **Series Part** fields to
    `M4BMakerUI`. Because ffmpeg cannot write the freeform iTunes atoms, the maker writes
    them with mutagen (`shared/metadata.write_m4b_tags`) **immediately after a successful
    encode**, so newly built M4B files carry the `----:com.apple.iTunes:SERIES` /
    `SERIES-PART` atoms (read by ffprobe as `series` / `series-part`) from the start — not
    just on a later edit pass.
- **Phase 5 (MP3 Tools Polish) — complete (Cancel buttons + settings-backed folders +
  shared metadata module, verified headless).**
  - Added a **Cancel button** to all four MP3 tools (M4B Converter, MP3 Tool, M4B Maker,
    Cover Image Converter), beside their action buttons. Each is **disabled when idle and
    enabled only while an operation is running**; clicking it disables itself, sets a
    `threading.Event`, and the worker bails at the next **natural checkpoint (between files /
    between tracks / at stage boundaries)** via `shared/cancellation.py`
    (`raise_if_cancelled` / `ConversionCancelled`). On cancel the tool **cleans up its partial
    output** (M4B Maker / MP3 Tool delete the staging output folder; the Converter drops a
    partial MP3) and reports a clear **"Cancelled."** line in the log/status.
  - **M4B Maker and MP3 Tool now run their conversions on a worker thread.** They previously ran
    synchronously on the main thread, which froze the GUI (and made a Cancel button impossible).
    Each now reads all Tk variables on the main thread, hands plain copies to the worker, and the
    worker talks back only through a thread-safe queue drained by a `pump_queue` (`after`) loop —
    the same pattern (and the same fix) as the Phase 4 TTS worker, avoiding
    "main thread is not in main loop". The M4B Converter and Cover Resizer already used worker
    threads; their off-thread widget writes were likewise routed through the queue.
  - Added `scripts/shared/metadata.py` — the canonical M4B/MP4 metadata module:
    `read_m4b_tags(path) -> dict` and `write_m4b_tags(path, tags)` (mutagen; `write` only touches
    the keys you pass, preserving every other tag — for the Phase 6 Metadata Editor), plus the
    encode-time helpers `ffmpeg_metadata_args` / `ffmetadata_header_lines` shared by the two M4B
    tools, and the Audiobookshelf series-atom constants `----:com.apple.iTunes:SERIES` /
    `SERIES-PART` (Briefing §6). `m4b_maker.py` and `m4b_converter.py` now build their ffmpeg
    tag fields from this module instead of each spelling them out.
- **Phase 4 (TTS Integration & Polish) — complete (Cancel button + cancellation plumbing,
  verified headless).**
  - Added a **Cancel button** to the TTS tool, beside Start. It is **disabled when idle and
    enabled only while a conversion is running**; clicking it disables itself and requests a stop.
    Works for **all four conversion paths** — single-file Edge, batch-PDF Edge, single Kokoro, and
    batch Kokoro.
  - Added `scripts/shared/cancellation.py` — a small cooperative-cancellation primitive
    (`ConversionCancelled` + `raise_if_cancelled`). The Cancel button sets a `threading.Event`;
    a `cancel_check` callable (`event.is_set`) is threaded into the worker, which consults it at
    **natural checkpoints (between chapters, paragraphs, and TTS chunks)**. Lives in `shared/`
    (not `tts/`) so the MP3 tools can reuse it for their own Cancel (Phase 5.1).
  - Wired `cancel_check` through `epub2tts_edge.read_book` (chapter / paragraph / sentence-chunk
    checkpoints), `runner.run_conversion_job`, `batch_convert.run_batch_convert` /
    `convert_single_pdf` (between PDFs and between chunks; queued PDFs are cancelled, in-flight
    workers bail at the next chunk), and `kokoro_synth.kokoro_file_to_mp3` (between chunks).
    On cancel the worker **cleans up its temp directory** (the runner's existing `finally` and the
    synth helpers' `TemporaryDirectory` contexts) and logs a clear **"Cancelled."** line.
  - **Feature-parity audit (4.1):** confirmed the Phase 3 `main()`→`build_ui(parent)` refactor
    dropped no controls and broke no bindings — `main()` now simply wraps `build_ui` in a private
    `Tk()`, so the launcher panel and the standalone window are the same UI. The only intentional
    UI change is the new Cancel button.
  - **Runner cwd isolation (4.3):** verified `runner.run_conversion_job` captures `old_cwd` before
    `os.chdir(tmp)` and restores it in a `finally` (alongside `shutil.rmtree(tmp)`), so launching
    via the unified launcher leaves no cwd side-effects between tool invocations. No change needed.

- **Phase 3 (Unified Launcher GUI) — code-complete; live conversion + visual console-flash check pending.**
  - Built `scripts/launcher.py`: a single Tk window with a left **sidebar of tools** and one
    **swappable content panel** on the right (matches the Briefing UX sketch). Includes a status
    bar with an **"Open log folder"** link. The launcher initialises the per-session file logger
    and calls `ffmpeg_utils.configure_pydub()` once at startup.
  - **Refactored all five existing tools to expose `build_ui(parent)`** so they render inside the
    launcher's content panel instead of owning a `Tk` root. Each keeps a standalone `main()`
    (wraps `build_ui` in a private `Tk()`) for debugging. The MP3 tools changed from
    `class App(tk.Tk)` / `MP3ToolGUI(root)` to embeddable `ttk.Frame` subclasses
    (`CoverResizerUI`, `M4BConverterUI`, `MP3ToolUI`, `M4BMakerUI`); the TTS GUI's `main()` body
    became `build_ui(parent)`.
  - **Tools are built once and shown/hidden (raise) on selection**, not destroyed and rebuilt, so
    in-progress state (file lists, typed metadata) survives switching tabs. This is a deliberate
    refinement of the "clear and repopulate" sketch — same single-panel feel, better UX.
  - **Lazy, guarded tool loading:** each tool module is imported on first selection and wrapped in
    try/except, so a missing optional dependency shows a friendly in-panel error instead of
    crashing the whole launcher. The Phase 6 **M4B Metadata Editor** is pre-registered in the
    sidebar but auto-hidden until its module exists (detected via `importlib.util.find_spec`).
  - Added `scripts/shared/settings.py` — atomic JSON settings at `resources/settings.json`
    (temp-file + `os.replace`; never raises on missing/corrupt file). The launcher persists
    **window geometry** and **last-selected tool** across restarts.
  - Added `scripts/shared/ffmpeg_utils.py` — resolves ffmpeg/ffprobe (bundled `resources/bin/`
    first, then PATH) and configures pydub (`AudioSegment.converter/ffmpeg/ffprobe`,
    `get_prober_name`) so audio ops use the right binary and don't depend on PATH.

- **Phase 2 (`setup_and_run` cross-platform bootstrap) — code-complete; live install pending.**
  - **Initialized the git repository** at the root with a `.gitignore` (`.venv/`, `__pycache__/`,
    `*.pyc`, `dist/`, `build/`, `*.spec`, `resources/bin/`, `resources/logs/`, `settings.json`,
    `test-logs/`, OS/editor cruft) and a `.gitattributes` that forces `*.command`/`*.sh` to **LF**
    (so the macOS launcher is never corrupted by CRLF) and `*.bat` to CRLF. Verified the initial
    stage contains only source — no `.venv`/`__pycache__`/logs leaked.
  - Built `scripts/shared/bootstrap.py` — a single **cross-platform** bootstrap (kept byte-identical
    in both OS trees; platform logic is branched inside). It: fast-path launches the GUI if `.venv`
    exists; otherwise locates/installs **Python 3.12** for the venv (system Python may be 3.13, which
    drops Kokoro), creates `<os_root>/.venv`, pip-installs the pinned `requirements.txt`, ensures
    ffmpeg (winget `Gyan.FFmpeg` / Homebrew, with a portable-build fallback into `resources/bin/`),
    optionally pre-downloads the Kokoro model, and launches the GUI detached via `pythonw` (Windows).
    First run shows a **Tk progress dialog** (intro + Kokoro opt-in checkbox, default checked) with a
    progress bar and live log; all output is tee'd to `resources/logs/setup_YYYY-MM-DD.log`. Depends
    on **stdlib + Tk only** (runs before the venv exists). Flags: `--launch-only`, `--self-test`,
    `--skip-kokoro-download`. Adapted from the legacy `tts/setup_env.py`.
  - Rewrote `setup_and_run.bat` and `setup_and_run.command` from stubs into real, **simple/readable**
    entry points: fast-path (no-console GUI launch when `.venv` exists) + first-run Python discovery
    (winget/Homebrew install, browser fallback) that hands off to `bootstrap.py`.

- **Phase 1 (Repository Restructure & File Migration) complete — restructure only, no behavior change.**
  - Built the final `scripts/{tts,mp3_tools,shared}` skeleton in both `Windows/` and `MacOS/`,
    with `__init__.py` for each package and the `epub2tts_edge/` subpackage preserved intact.
  - Migrated the TTS subsystem into `scripts/tts/` (`epub2tts_gui.py`, `batch_convert.py`,
    `kokoro_synth.py`, `pdf_extractor.py`, `voice_registry.py`, `setup_env.py`, and the
    `epub2tts_edge/` package). On macOS the helper modules that lived under a `scripts/`
    subfolder were flattened into `tts/`, erasing the old Win/Mac layout divergence.
  - Migrated the four MP3 tools into `scripts/mp3_tools/`, renamed to importable module names:
    `mp3_tool-v5-4.py`→`mp3_tool.py`, `m4b_maker-v5-3.py`→`m4b_maker.py`,
    `m4b_converter-v1-2.py`→`m4b_converter.py`, `cover_resizer-v2.py`→`cover_resizer.py`.
    The old MP3 `launcher.py` was copied as `mp3_tools_launcher.py` (absorbed in Phase 3) and its
    tool paths updated to the new flat, renamed files.
  - Created the `shared/` module: `paths.py` (pathlib single-source-of-truth for all project
    paths — no more hardcoded/absolute paths), `subprocess_utils.py` (Windows console-hiding
    `run`/`popen` wrappers), `logging_setup.py` (per-session file logger under `resources/logs/`,
    keeps last 30 sessions).
  - Created merged OS-level `requirements.txt` (TTS + MP3, de-duplicated) in both `Windows/`
    and `MacOS/`. Versions left **unpinned** for now — Phase 2 pins all per the dependency rules.
  - Created stub `setup_and_run.bat` / `setup_and_run.command` at the repo root (full bootstrap
    in Phase 2); `.command` marked executable.
  - Created `resources/logs/` in both OS folders.
- **Phase 0 (Research & Discovery) complete.** Full source inventory of both source repos
  (`epub2tts-edge` TTS + `mp3_scripts` MP3 tools) recorded in `Briefing.md` §4, including
  public entry points, dependencies, and cwd/hardcoded-path assumptions per file.
- GitHub/docs research recorded in `Briefing.md` §6: authoritative Audiobookshelf series-tag
  mapping (write freeform atoms `----:com.apple.iTunes:SERIES` / `SERIES-PART`, which ffprobe
  surfaces as `series` / `series-part`), mutagen freeform write pattern, console-suppression
  pattern, and the Kokoro Python <3.13 gate.
- MP3 Tool feature inventory pre-filled (`Briefing.md` §6a) ahead of Phase 5.2.
- Unified launcher UX sketch (`Briefing.md` §8): sidebar + single swappable content panel.

### Changed
- **Phase 7: added `test-files/` to `.gitignore`.** A ~2.7 GB folder of real test assets (2 M4Bs,
  289 MP3, 836 PDF, JPGs, TXT) sits at the repo root as a local fixture for the test matrix; it must
  never be committed. (No tool/source code changed in Phase 7.)
- **Phase 5: routed every MP3-tool input/output folder through `shared/settings.py`** instead of
  hardcoding `~/Downloads/...`. Each tool remembers its folders under per-tool keys
  (`m4b_maker.input_dir` / `.output_dir` / `.cover_dir`, `m4b_converter.input_dir` / `.output_dir`,
  `mp3_tool.input_dir` / `.output_dir`, `cover_resizer.input_dir`). **First run defaults to the
  user's home directory** (no more `~/Downloads`); the chosen folders persist on every successful
  operation and pre-fill the file dialogs (`initialdir`) and a new **"Output folder" picker** added
  to M4B Maker, M4B Converter, and MP3 Tool. The Cover Resizer writes next to its source images, so
  it only remembers its input folder. The sequential auto-named subfolders (`M4B-Output-N`,
  `m4b_converter_output-N`, `edited_mp3s-N`) are unchanged — they're now created **inside** the
  remembered base folder.
- **Phase 3: routed every tool's external-binary call through `shared/subprocess_utils`** so no
  console window flashes on Windows. The MP3 tools' `subprocess.run` / `check_output` and the TTS
  engine's two `subprocess.run(["ffmpeg", …])` calls in `epub2tts_edge.make_m4b` now go through the
  hidden-console wrapper; folder-opening (`os.startfile` / `open` / `xdg-open`) goes through the new
  `subprocess_utils.reveal_in_file_manager`. Audit confirms **zero direct `subprocess.*` calls** in
  tool code (installer `bootstrap.py`/`setup_env.py` and the legacy `mp3_tools_launcher.py` are out
  of scope). Extended `subprocess_utils` with `check_output` and `reveal_in_file_manager`.
- **Phase 3: unified the two previously-divergent tool files across OS trees.** `cover_resizer.py`
  (file-dialog filter) and `epub2tts_gui.py` (Mac window size/labels/`sys.path` shim) are now
  byte-identical Win↔Mac; all platform differences are handled by `sys.platform` branches inside
  the shared code (console-hide kwargs, exe suffix, file-manager command, launcher font/theme).
- **Phase 3: demoted startup "ffmpeg not found" modals to log lines** in the MP3 tools, so switching
  between tools in the single-panel launcher never pops a dialog on every selection.
- **Pinned every dependency** in both `Windows/requirements.txt` and `MacOS/requirements.txt` to an
  exact version (project rule), verified against PyPI on 2026-05-28: beautifulsoup4 4.14.3,
  ebooklib 0.20, edge-tts 7.2.8, lxml 6.1.1, mutagen 1.47.0, nltk 3.9.4, pillow 12.2.0, pydub 0.25.1,
  pymupdf 1.27.2.3, setuptools 82.0.1, tqdm 4.67.3, soundfile 0.13.1, scipy 1.17.1,
  `audioop-lts==0.2.2 ; python_version >= "3.13"`, `kokoro==0.9.4 ; python_version < "3.13"`
  (optional `pillow-heif==1.3.0` pinned but commented). The `<3.13` Kokoro marker matches the
  bootstrap targeting Python 3.12.
- **Import convention established:** `scripts/` is the single import root; all cross-module
  imports are absolute `tts.*` / `mp3_tools.*` (subpackage-internal imports inside
  `epub2tts_edge/` stay relative). Entry-point scripts that can be run directly
  (`epub2tts_gui.py`, `batch_convert.py`) self-bootstrap `scripts/` onto `sys.path`, so they
  work both standalone and when imported by the future unified launcher — and the same module
  is never importable under two names (avoids the double-import trap).
- Rewrote all internal imports in the migrated TTS files to the new convention
  (e.g. `from pdf_extractor import` → `from tts.pdf_extractor import`); removed the macOS GUI's
  old `sys.path.insert(..., "scripts")` shim, replaced with the standard bootstrap.
- Moved `Dockerfile` into `Windows/` only (optional Linux container; documented divergence —
  macOS has no Dockerfile).
- `Briefing.md` fully populated (was placeholder): summary, structure, subsystems, source
  inventory, Win↔Mac divergence analysis, design decisions, research, dependency table.

### Removed
- Deleted the four source-repo folders after migration was verified: `Windows/epub2tts-edge`,
  `Windows/mp3_scripts`, `MacOS/epub2tts-edge`, `MacOS/mp3_scripts` (including their `.git`
  fork histories and the working `.venv`). Also removed the empty `Windows/files` and
  `MacOS/files` folders — the project structure uses `resources/`, not `files/`.
  The `.venv` is rebuilt fresh by Phase 2's bootstrap.

### Fixed
- **Phase 4: TTS conversion crash — "main thread is not in main loop."** The TTS worker thread was
  reading Tk variables directly (`mode_var.get()`, `workers_var.get()`, `resume_var.get()`,
  `voice_var.get()`, `rate_var.get()`, `bitrate_var.get()`, `overwrite_var.get()`,
  `epub_convert_var.get()`, `kokoro_speed_var.get()`, `end_pause_var.get()`). Tcl variable access
  off the main thread raises `RuntimeError: main thread is not in main loop`. Fixed by reading
  **every** Tk variable on the main thread in `run_job` (into plain Python locals) before spawning
  the worker; the worker now uses only those copies and talks to the GUI exclusively through the
  thread-safe log queue (drained by `pump_queue` via `root.after`). Surfaced by the Phase 4 headless
  test and reported live during conversion.

---

## Decisions (Phase 0)

- **Bundling = Path A** (install-on-first-run bootstrap), not PyInstaller/py2app. Reason:
  Kokoro→PyTorch makes self-contained builds fragile/huge; existing `setup_env.py` already
  implements Path A and becomes `shared/bootstrap.py` in Phase 2.
- **Launcher UX = sidebar + single swappable content panel**; each tool exposes `build_ui(parent)`.
- **Single shared codebase per subsystem** with thin platform shims — Phase 0 diff proved the
  TTS core and MP3 tools are ~byte-identical across Win/Mac; only divergence is layout
  (Win flat-root vs Mac `scripts/` subfolder) + cosmetic GUI lines.

---

## Open Questions

> Use this section to log anything that needs the project owner's input before proceeding.
> Move resolved items into the appropriate Unreleased category once answered.

- _(none — Phase 0 surfaced no blockers; series-tag convention resolved via research)_

---

## Session Log

> One entry per Claude Code session. Newest at the top. Keep short — point at file changes, not full diffs.

### 2026-05-29 — Session 9
- **Phase:** Phase 8 — README + Release Packaging (complete).
- **Git:** work on new branch `phase-8-release` (off `phase-7-test-matrix`). Local only.
- **Done:** wrote the CV-grade root **`README.md`** (summary, six-tool feature list, ASCII launcher
  mockup, Windows/macOS install, system-requirements table, per-tool usage, architecture +
  design-decisions section, GPL-3.0 credits/license, known limitations). Added
  **`shared/version.py`** (`VERSION = "0.1.0"`) as the single source of truth and the dev-only
  **`shared/release.py`** packager (stdlib-only; zips each OS tree with the documented exclusions,
  README + launcher at the archive root, prints the §13 checklist). Mirrored both new modules
  byte-identical to Windows + MacOS. Finalised both CHANGELOG copies: `[Unreleased]` → `[0.1.0] -
  2026-05-29` with a fresh empty `[Unreleased]` on top, and removed the stale bottom `[0.1.0]`
  placeholder.
- **Verification:** ran `release.py` → two zips under `dist/`; `zipfile.namelist()` confirms each has
  `README.md` + the correct launcher at root, the OS tree nested under its folder, and **zero**
  excluded leaks (no `.venv`/`__pycache__`/`.pyc`/logs/settings/bin/test-files). `compileall` clean,
  both trees.
- **Next:** GitHub remote + first Release (attach both zips). Before a real public ship, still run
  **Debug Gate 2** (full one-click install on a clean Python-3.12 box), the **macOS** matrix column on
  a Mac, and the final **visual** no-console-flash confirmation.
- **Blockers:** none.

### 2026-05-29 — Session 8
- **Phase:** Phase 7 — Cross-Platform Test Matrix (complete on Windows; macOS deferred — no host).
- **Git:** work on new branch `phase-7-test-matrix` (off `phase-6-metadata-editor`). Local only.
- **Done:** ran every deferred live gate (2–6) and filled Briefing §12 against the real `test-files/`
  assets (copied to a temp working dir **with a space**; originals untouched). Verified live on
  Windows, driving the real worker code paths: Edge-TTS EPUB→MP3 + PDF→MP3 + 2-file batch + mid-run
  cancel (Gate 4, 0 leaked temp dirs); M4B Maker chapters + series (ffprobe-verified); M4B-encode
  cancel cleanup (Gate 5); M4B→MP3; MP3-Tool combine/time-edit/ID3; Cover-Resizer square+crop;
  Metadata Editor single/multi/blank-preserve (Gate 6); Unicode filename; spaces in path; settings
  persist across simulated restart; launcher builds all six tools (~1.25 s). Gate 2 verified live
  (`bootstrap.py --self-test` + throwaway-venv pip dry-run resolving the full pinned requirements).
  Console-flash mechanism re-audited (zero direct `subprocess.*` in tool code). Added `test-files/`
  to `.gitignore`.
- **Result:** **18/18 applicable Windows rows PASS, 0 FAIL.** **No bugs found → no tool code changed**
  (Phase 7.3 was a no-op by design). `compileall` clean on both trees.
- **Next:** Phase 8 — README + release packaging. Before release, still run **Debug Gate 2** (full
  one-click install on a clean machine with Python 3.12) and the **macOS** matrix column on a Mac.
- **Blockers:** none. **Deferred (documented known-limitations):** fresh one-click install (system
  mutation + Python 3.12), TTS Kokoro voice (needs Python <3.13; this box is 3.13), final *visual*
  no-console-flash confirmation, and the entire macOS column (no Mac).

### Debug Gate 7 — PASS (Windows live; macOS deferred)
- [x] **Gate 2** — venv + pip path verified live: `bootstrap.py --self-test` clean; `python -m venv`
  works; throwaway venv resolved the full **pinned** `requirements.txt` against PyPI (kokoro excluded
  on 3.13). [~] Full one-click fresh install on a clean machine w/ Python 3.12 — still deferred.
- [x] **Gate 3** — real conversions run from the tool worker paths (TTS single-file Edge → MP3 incl.).
  Console-flash mechanism-verified (zero direct `subprocess.*` in tool code; `subprocess_utils` hides
  the window; launcher under `pythonw`). [~] Final *visual* no-flash confirmation — manual, deferred.
- [x] **Gate 4** — real TTS conversion cancelled mid-run: `ConversionCancelled` raised, **0 leaked
  temp dirs**; GUI logs "Cancelled." (Phase 4 behavior unchanged).
- [x] **Gate 5** — real M4B encode cancelled at a stage boundary: partial output folder removed,
  `("cancelled")` posted.
- [x] **Gate 6** — Metadata Editor on a real M4B (slice of a `test-files/` audiobook): edit a field →
  save → re-read confirms the change persisted, untouched fields preserved; multi-file overwrite and
  blank-field preserve verified.
- [x] Full §12 matrix filled: **18/18 applicable Windows rows PASS**, 0 unresolved FAIL.
- [x] `compileall` clean, both trees. **No bugs found → no code changes.**
- [~] **macOS** column — SKIP(no-Mac), deferred to a Mac host.

### 2026-05-29 — Session 7
- **Phase:** Phase 6 — M4B Metadata Editor + Series Tags (complete).
- **Git:** work on new branch `phase-6-metadata-editor` (off `phase-5-mp3-polish`). Local only.
- **Done:** added `mp3_tools/m4b_metadata_editor.py` (open/edit existing M4B tags without
  re-encoding; Title/Author/Album/Year/Genre/Comment/Series/cover; preserve-by-default;
  single-file pre-fill + multi-file batch overwrite; worker-thread Save + Cancel + per-file
  log; `build_ui` + `main`). Extended `shared/metadata.py` additively (comment/genre/year
  atoms, `cover_path` embed/clear, `has_cover` read flag) — ffmpeg encode helpers untouched.
  Added **Series Name / Series Part** fields to `M4BMakerUI`, written via mutagen right after
  a successful encode (ffmpeg can't write the freeform atoms). Launcher slot auto-reveals via
  the existing `find_spec` guard — no launcher change. Mirrored all 3 changed/new code files
  byte-identical to MacOS.
- **Verification:** `compileall` clean (both full trees); a temporary headless test (real Tk +
  real mutagen + real ffmpeg/ffprobe) passed **17/17 on each tree** — launcher reveal,
  single-file round-trip (edit one field, others preserved), comment/genre/cover round-trip,
  batch blank-preserve / non-blank-overwrite, ffprobe surfacing `series` / `series-part`, and a
  real short M4B-Maker build whose output carries the series atoms. Test scaffold removed.
- **Next:** Phase 7 — full cross-platform test matrix (§12) on Windows + a Mac.
- **Blockers:** none. **Deferred:** live click-through of the editor on a Mac and the broader
  Phase 7 matrix (manual pre-release pass).

### Debug Gate 6 — PASS (headless)
- [x] `m4b_metadata_editor.py` exists and compiles; `build_ui(parent)` and `main()` both present.
- [x] Launcher sidebar shows the Metadata Editor without any manual config change (`_available_tools`
  lists `m4b_metadata`; the `find_spec` auto-hide now reveals it).
- [x] Single-file tag round-trip: read tags → edit one field → write → re-read confirms the change,
  with untouched fields preserved (headless, real mutagen). Comment/genre/cover atoms round-trip too.
- [x] Batch mode: a blank field preserves each file's existing tag; a non-blank field overwrites all.
- [x] Series atoms written as `----:com.apple.iTunes:SERIES` / `SERIES-PART` and read back by ffprobe
  as `series` / `series-part`.
- [x] M4B Maker series fields present in the UI and written to the output on a real (short) M4B build
  (ffprobe confirms `series` on the produced file).
- [x] `compileall` clean, both trees.
- [~] Live click-through of the editor GUI on a Mac — deferred to the Phase 7 manual pass.

### 2026-05-29 — Session 6
- **Phase:** Phase 5 — MP3 Tools Polish (complete).
- **Git:** work on new branch `phase-5-mp3-polish` (off `phase-4-tts-polish`). Local only.
- **Done:** added `shared/metadata.py` (mutagen `read_m4b_tags`/`write_m4b_tags` + series atoms +
  `ffmpeg_metadata_args`/`ffmetadata_header_lines`); `m4b_maker.py` and `m4b_converter.py` now build
  their tag fields from it. Added a **Cancel button** to all four MP3 tools (idle-disabled,
  active-enabled, `threading.Event` checkpoints via `shared/cancellation.py`, "Cancelled." line,
  partial-output cleanup). **Moved M4B Maker and MP3 Tool conversions onto worker threads** (they
  were synchronous on the main thread) with a queue + `pump_queue` so Tk is only touched on the main
  thread; routed the Converter/Resizer off-thread widget writes through the queue too. Replaced every
  hardcoded `~/Downloads/...` path with `shared/settings.py`-backed per-tool input/output folders
  (default = home), added an "Output folder" picker to the three output-producing tools, and persist
  folders on success + pre-fill dialogs. Mirrored all 5 changed/new files byte-identical to MacOS.
- **Verification:** `compileall` clean (both full trees); a temporary headless test (real Tk + real
  ffmpeg/ffprobe) passed 38/38 — Cancel state machine (idle→busy→cancel→idle) for all four tools,
  `normalize_to_wav` honouring `cancel_check`, the `ffmpeg_metadata_args`/`ffmetadata_header_lines`
  output, and a full M4B tag round-trip incl. **ffprobe surfacing the freeform series atoms as
  `series` / `series-part`** (validates Briefing §6 live). Test scaffold removed after the pass.
- **Next:** Phase 6 (M4B Metadata Editor + series tags in M4B Maker) — builds directly on
  `shared/metadata.py`.
- **Blockers:** none. **Deferred:** live mid-operation cancel during a single long ffmpeg encode
  (cancel lands at stage/file boundaries, not mid-subprocess) — manual pre-release pass, same posture
  as the deferred TTS live cancel.

### Debug Gate 5 — PASS (headless)
- [x] Cancel button present and correctly state-managed in all four MP3 tools (headless: idle
  `disabled`; enabled while busy; `cancel()` sets the event and disables itself; `_finish_idle()`
  clears busy and leaves Cancel disabled).
- [x] No hardcoded `~/Downloads` paths remain in tool code (grep: only doc-comment mentions left);
  all folders route through `shared/settings.py` with a home-dir default.
- [x] Last-used input/output folders persist per tool independently via distinct settings keys
  (`<tool>.input_dir` / `.output_dir` / `.cover_dir`); written on success, read as dialog `initialdir`.
- [x] `shared/metadata.py` exists; `m4b_maker.py` and `m4b_converter.py` import its ffmpeg tag
  helpers; no duplicated field-mapping logic remains. `read_m4b_tags`/`write_m4b_tags` round-trip
  verified, and ffprobe confirms the series atoms surface as `series` / `series-part`.
- [x] `compileall` clean, both trees.
- [x] Existing MP3-tool functionality preserved (same ffmpeg command construction, same output-folder
  naming, same ID3/timestamp behaviour; the only changes are the worker-thread move, Cancel, and the
  remembered folders).
- [~] Live mid-encode cancel on real audio — deferred to the manual pre-release pass.

### 2026-05-29 — Session 5
- **Phase:** Phase 4 — TTS Integration & Polish (complete).
- **Git:** work on new branch `phase-4-tts-polish` (off `phase-3-launcher`). Local only.
- **Done:** added `shared/cancellation.py`; added a **Cancel button** to the TTS GUI (idle-disabled,
  active-enabled) wired into all four conversion paths; threaded `cancel_check` through `read_book`
  (chapter/paragraph/chunk checkpoints), `runner.run_conversion_job`, `batch_convert`
  (`run_batch_convert` + `convert_single_pdf`), and `kokoro_synth.kokoro_file_to_mp3`; cancel logs
  "Cancelled." and temp dirs are removed by existing `finally`/`TemporaryDirectory` cleanup.
  Completed the 4.1 feature-parity audit (Phase 3 refactor dropped nothing) and confirmed 4.3
  runner cwd is restored in a `finally` (no change needed). Mirrored all 6 files byte-identical to
  both trees.
- **Fixed (critical):** TTS worker thread was reading Tk variables off-thread →
  `RuntimeError: main thread is not in main loop` during conversion (reported live, also caught by
  the headless test). All Tk reads hoisted to the main thread in `run_job`; worker now uses plain
  copies + the log queue only.
- **Verification:** `compileall` clean (both trees); a headless GUI test (real Tk, stubbed runner,
  no network) confirmed idle→active→cancel→idle button states, the engine + batch cancel checkpoints
  raising/returning without network, a clean "Cancelled." log, and **no** "main thread" error. Test
  scaffold was temporary and removed after the pass.
- **Next:** Phase 5 (MP3 tools polish; route hardcoded `~/Downloads/...` outputs through
  settings/`paths.py`; MP3-tools Cancel can reuse `shared/cancellation.py`).
- **Blockers:** none. **Deferred:** live mid-conversion cancel on real audio (manual pre-release pass,
  same posture as the deferred Debug Gate 2/3 live items).

### Debug Gate 4 — PASS (headless)
- [x] Cancel button visible; correctly enabled/disabled idle vs. active (headless test: idle Cancel
  `disabled` / Start `normal`; after start Cancel `normal` / Start `disabled`; after cancel click
  Cancel `disabled`; back-to-idle Start `normal`).
- [x] Worker thread exits cleanly on cancel; temp dir removed (runner `finally` + synth
  `TemporaryDirectory`); **"Cancelled."** present in the log pane.
- [x] Feature-parity: every control from the standalone TTS GUI is present in the launcher panel
  (`main()` wraps the same `build_ui`); only addition is the Cancel button.
- [x] `runner.py` restores cwd in a `finally` (captured before `os.chdir`); no cwd leakage between
  tools.
- [x] No "main thread is not in main loop" error — all Tk reads moved to the main thread.
- [x] `compileall` clean, both trees.
- [~] Live mid-conversion cancel on real EPUB/PDF audio — deferred to the manual pre-release pass.

### 2026-05-29 — Session 4
- **Phase:** Phase 3 — Unified Launcher GUI (code-complete; live conversion + visual no-flash check pending).
- **Git:** committed the existing work as two local commits before starting — `Phase 0+1 restructure
  baseline` on `master`, `Phase 2 bootstrap` on branch `phase-2-bootstrap`. Phase 3 work is on a new
  branch `phase-3-launcher` (off `phase-2-bootstrap`). Local only; no remote yet (GitHub at the end).
- **Done:** wrote `scripts/launcher.py` (sidebar + swappable panel, status bar w/ open-log link,
  geometry + last-tool persistence, lazy guarded tool loading, Phase-6 metadata slot auto-hidden);
  refactored all 5 tools to `build_ui(parent)` as embeddable frames with standalone `main()`;
  added `shared/settings.py` (atomic JSON) and `shared/ffmpeg_utils.py` (ffmpeg/ffprobe resolve +
  pydub config); routed all tool subprocess calls through `shared/subprocess_utils` (added
  `check_output`, `reveal_in_file_manager`); unified the 2 divergent files Win↔Mac. Mirrored all
  10 changed/new files to MacOS (byte-identical).
- **Verification (static + headless, no system mutation):** `compileall` clean (both trees);
  subprocess audit shows **zero** direct `subprocess.*` calls in tool code (both trees); `import
  launcher` succeeds without heavy deps; **headless GUI smoke test** instantiated the launcher and
  built all 5 tools into the content panel (all `BUILT`, no error frames) and persisted geometry +
  last-tool on close; settings round-trip verified; bootstrap `--self-test` confirms
  `launch target = scripts/launcher.py (exists=True)` — the bootstrap now opens the unified launcher.
- **Next:** Phase 4 — TTS integration & polish (feature-parity pass inside the launcher; add the
  **Cancel button**; confirm Runner keeps all temp I/O out of the launcher cwd).
- **Blockers:** none. **Deferred:** the live items in Debug Gate 3 (run a real conversion from the
  launcher and visually confirm no console flash under `pythonw`) — manual pre-release, same posture
  as the deferred Debug Gate 2 live install.

### Debug Gate 3 — PARTIAL (static + headless PASS; live conversion deferred)
- [x] Launcher opens; each of the 5 existing tools loads into the content panel (headless smoke test:
  all 5 `BUILT`). The 6th (Metadata Editor) arrives in Phase 6 and is auto-hidden until then.
- [x] Settings persist across restarts (window geometry + last sidebar selection round-trip to
  `resources/settings.json`).
- [x] Subprocess audit: zero direct `subprocess.*` calls in tool code; all routed through
  `shared/subprocess_utils` (which applies `CREATE_NO_WINDOW` + hidden `STARTUPINFO` on Windows).
- [x] pydub pointed at the resolved ffmpeg/ffprobe via `ffmpeg_utils.configure_pydub()`.
- [~] Running a TTS / MP3 / M4B operation **from inside the launcher** produces output identical to
  the old standalone GUI — **not run live this session** (needs a real conversion with sample assets).
- [~] **No console window flashes during any operation** under `pythonw.exe` — code-verified (routing
  + pythonw launch), **visual confirmation deferred** to the manual pre-release pass.

### 2026-05-28 — Session 3
- **Phase:** Phase 2 — `setup_and_run` cross-platform bootstrap (code-complete; live install pending).
- **Done:** `git init` + `.gitignore` + `.gitattributes` (LF for `.command`/`.sh`); pinned every dep
  in both `requirements.txt`; wrote `scripts/shared/bootstrap.py` (one byte-identical cross-platform
  file, adapted from `setup_env.py`) with fast-path launch, Python-3.12 locate/install, venv create,
  pinned pip install, ffmpeg ensure (+ portable fallback), Kokoro opt-in, detached GUI launch, dated
  setup log, and `--launch-only`/`--self-test`/`--skip-kokoro-download` flags; rewrote
  `setup_and_run.bat` and `.command` from stubs into real fast-path + first-run-Python-discovery
  entry points.
- **Verification (static, no system mutation):** `py_compile` clean (both trees); `--self-test`
  detection ran with no side effects and correct results; auto-driven headless GUI smoke test ran the
  intro→worker→progress→done→launch wiring to success (install/launch stubbed); `bootstrap.py`
  confirmed byte-identical across trees; `.command` confirmed 0 CR bytes (LF-only); git stage
  confirmed free of `.venv`/`__pycache__`/logs.
- **Next:** Phase 3 — unified launcher GUI (`scripts/launcher.py`). Once it exists, the bootstrap's
  launch target switches from the TTS-GUI fallback to it automatically (no bootstrap change needed).
  After Phase 3, run the **live Debug Gate 2** fresh-machine install on Windows + a Mac.
- **Blockers:** none. **Deferred:** live fresh-machine install (Debug Gate 2) — see below.

### Debug Gate 2 — PARTIAL (static PASS; live install deferred)
- [x] `setup_and_run.bat` / `.command` rewritten from stubs; fast-path + first-run logic in place.
- [x] `bootstrap.py` compiles, self-tests, and its first-run GUI wiring runs to completion (stubbed).
- [x] Logs written to `resources/logs/setup_YYYY-MM-DD.log` (verified by self-test run).
- [~] Fresh-machine install (winget/brew Python 3.12 → venv → pinned pip incl. torch/Kokoro → ffmpeg
  → optional 300 MB model → GUI open, 1 click) — **NOT run live.** Mutates the host (system Python +
  ffmpeg, multi-GB downloads); to be run on a clean VM / the target machine before release.
- [~] Second-launch under 2s, no console window — **needs a real `.venv` + Phase 3 `launcher.py`** to
  verify end-to-end; the fast-path code path is in place and the GUI runs under `pythonw`.
- [-] macOS double-click flow — **skipped this session** (no Mac available); `.command` built to mirror
  Windows and confirmed LF-only.

### 2026-05-28 — Session 2
- **Phase:** Phase 1 — Repository Restructure & File Migration (complete).
- **Done:** Built `scripts/{tts,mp3_tools,shared}` skeleton (both OS); migrated TTS + MP3 source
  into it; renamed MP3 tools to importable names; rewrote all internal imports to the `tts.*` /
  `mp3_tools.*` convention with a `scripts/`-root bootstrap in entry scripts; created `shared/`
  (paths, subprocess_utils, logging_setup); merged unpinned `requirements.txt`; moved Dockerfile
  to Windows/; created root `setup_and_run.*` stubs. Smoke-tested all imports + `py_compile`
  (both trees) and launch-verified both GUIs under `pythonw.exe`. Deleted the four source-repo
  folders + empty `files/` folders.
- **Verification:** Debug Gate 1 — all items pass (see below).
- **Next:** Phase 2 — `setup_and_run` bootstrap. Adapt `tts/setup_env.py` into
  `shared/bootstrap.py` (Python/ffmpeg detect+install, create `Windows/.venv` / `MacOS/.venv`,
  pin + install requirements, optional Kokoro download, launch GUI via `pythonw`/detached).
  **First Phase 2 action: pin every dependency in both `requirements.txt`.**
- **Blockers:** none.

### Debug Gate 1 — PASS
- [x] Root has exactly 5 permanent items (+ temp `IMPLEMENTATION_PLAN.md`): `README.md`,
  `setup_and_run.bat`, `setup_and_run.command`, `Windows/`, `MacOS/`.
- [x] `Windows/` and `MacOS/` have identical folder shape (`diff` of dir trees = identical;
  Windows carries an extra `Dockerfile` file — documented intentional divergence).
- [x] TTS GUI launches from new location (`scripts/tts/epub2tts_gui.py`) under `pythonw.exe`
  — process stayed alive, window opened, no crash.
- [x] MP3 launcher launches from new location (`scripts/mp3_tools/mp3_tools_launcher.py`).
- [x] Imports succeed from `scripts/` for both trees: `from tts.epub2tts_edge.epub2tts_edge
  import DEFAULT_SPEAKER`, `from mp3_tools import m4b_converter`, all helpers, runner, shared.
- [x] `python -m py_compile` clean across every migrated `.py` (both OS).
- [x] `CHANGELOG.md` + `Briefing.md` updated (both copies).

### 2026-05-28 — Session 1
- **Phase:** Phase 0 — Research & Discovery (complete).
- **Done:** Read all 4 source trees end-to-end; diffed Win↔Mac (core is identical, only layout
  differs); researched Audiobookshelf series tags + mutagen + console suppression; decided
  bundling (Path A) and launcher UX; fully wrote `Briefing.md` (both copies).
- **Next:** Phase 1 — Repository Restructure & File Migration. Create the `scripts/{tts,mp3_tools,shared}`
  skeleton, migrate both source repos into it, fix top-level imports, create empty `shared/` stubs,
  smoke-test imports. No behavior change.
- **Blockers:** none.

_The version history above (Phases 0–8) all ships under **[0.1.0]** — the initial public release._
