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

### Added
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

---

## [0.1.0] - YYYY-MM-DD

_Initial restructure release. Placeholder until Phase 8 ships._
