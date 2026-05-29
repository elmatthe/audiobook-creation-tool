# Audiobook-Creation-Tool — Master Implementation Plan

> **Purpose of this file:** This markdown is a one-shot brief for Claude Code. It defines the target repository, the migration path from four existing source repos, the new features to build, and the verification gates between phases. **Remove this file once Phase 8 is complete and the CHANGELOG/Briefing files are in place.**

> **Working style expected:**
> - Treat each phase as a checkpoint. **Do not start a phase until the prior phase's "Debug Gate" passes.**
> - When you hit ambiguity, prefer reading the source repos over guessing. The four source repos are the source of truth for existing behavior.
> - This will run across **multiple sessions**. End each session by updating `CHANGELOG.md` (both copies) with what was done, and start the next session by reading the CHANGELOG and Briefing first.
> - Research GitHub for prior art when useful (e.g., PyInstaller patterns for bundling Python apps, audiobookshelf metadata tag conventions, cross-platform installer patterns). Cite findings in the Briefing file.

---

## 1. Goals (read first, refer back often)

1. **Single repo, two OS targets.** One repository (`Audiobook-Creation-Tool`) cleanly split into `Windows/` and `MacOS/` halves so a non-technical user only ever interacts with the root.
2. **Double-click setup for non-technical users.** A user downloads the zip, unzips it, double-clicks one file, and ends up with a working GUI app — no terminal commands, no Python knowledge, no manual ffmpeg install, no visible console windows during normal use.
3. **One launcher GUI per OS.** All five MP3 tools + the TTS tool launch from a single window (modeled on the existing `MP3_Tools` `launcher.py`), with subprocess console windows suppressed.
4. **Two new features:** series tagging in M4B Maker, and a new Script 5 (M4B Metadata Tag Editor) that preserves unchanged fields on edit.
5. **Documented and bug-hunted.** Each OS folder maintains its own `CHANGELOG.md` and `Briefing.md`. Final phase is a structured bug hunt across every script.

---

## 2. Final Target Repository Structure

The root must contain **exactly 5 items** when finished. Nothing else at root level — ever.

```
Audiobook-Creation-Tool/
├── README.md                      # General CV-quality project overview
├── setup_and_run.bat              # Windows: double-click entry point
├── setup_and_run.command          # macOS: double-click entry point
├── Windows/
│   ├── md-instructions/
│   │   ├── CHANGELOG.md           # Running changelog, updated every session
│   │   └── Briefing.md            # Project brief for future Claude chats
│   ├── scripts/                   # All .py files, organized as Claude Code sees fit
│   │   ├── launcher.py            # Main GUI — unified entry point
│   │   ├── tts/                   # TTS subsystem (from TTS_Project Windows)
│   │   ├── mp3_tools/             # MP3 tools subsystem (from MP3_Tools Windows)
│   │   └── shared/                # Cross-cutting helpers (config, paths, logging)
│   ├── resources/                 # Icons, default cover art, bundled binaries if any
│   ├── requirements.txt
│   └── (any other files needed for Windows to run)
└── MacOS/
    ├── md-instructions/
    │   ├── CHANGELOG.md
    │   └── Briefing.md
    ├── scripts/
    │   ├── launcher.py
    │   ├── tts/
    │   ├── mp3_tools/
    │   └── shared/
    ├── resources/
    ├── requirements.txt
    └── (any other files needed for macOS to run)
```

**Hard rules for structure:**
- Root has **only** those 5 items. No stray dotfiles, no `.venv` at root, no `requirements.txt` at root.
- Both `Windows/` and `MacOS/` have **identical layout** at the folder level (file contents differ as needed).
- `md-instructions/` always contains exactly two markdown files (`CHANGELOG.md`, `Briefing.md`) plus any temporary instruction files the user drops in.
- All Python lives under `scripts/`. Sub-organization within `scripts/` is your call, but follow the structure above unless you have a clear reason to deviate (and document the reason in the Briefing).

---

## 3. Source Repositories (input material)

The user will drop these four repos into the working area:

| Source | Drop location during work | Role |
|---|---|---|
| TTS_Project (Windows) | `Windows/scripts/tts/` (after extraction) | The current epub2tts-edge fork — EPUB/PDF/TXT → MP3/M4B, GUI, batch PDF, Edge TTS + Kokoro |
| TTS_Project (Mac) | `MacOS/scripts/tts/` | Mac variant of the same |
| MP3_Tools (Windows) | `Windows/scripts/mp3_tools/` | `launcher.py` + 4 scripts |
| MP3_Tools (Mac) | `MacOS/scripts/mp3_tools/` | Mac variant of MP3_Tools |

**Existing MP3_Tools scripts (controlled by `launcher.py`):**
1. **M4B_Converter** — batch import M4B files, output clean MP3s (no metadata).
2. **MP3_Tool** — FFmpeg-driven MP3 metadata tagging + utility functions (explore and document all of them).
3. **M4B_Maker** — assemble MP3s into M4B with chapter markers and metadata, any length, any count.
4. **cover_image_converter** — pad/format cover art to fit M4B frame without cropping.

**Existing TTS_Project (from the chat context):**
- `epub2tts_gui.py` (Tkinter GUI), `batch_convert.py`, `kokoro_synth.py`, `voice_registry.py`, `pdf_extractor.py`, `epub2tts_edge/` package, `setup_env.py`, `setup_env.bat` / `setup_env.command`, `requirements.txt`, `Dockerfile`.

---

## 4. Phase 0 — Research & Discovery (do this first, every session)

**Goal:** Build a precise mental model before touching code.

### Steps

1. **Read all four source repos end-to-end.** Don't skim. For each Python file, record:
   - Public entry points (functions called from outside the module)
   - External dependencies (PyPI packages, OS binaries like ffmpeg/espeak-ng)
   - Hidden assumptions (cwd dependence, hardcoded paths, platform-specific calls)
   - Differences between the Windows and Mac variants of the same script

2. **GitHub prior-art research.** Search for reusable patterns. Suggested queries:
   - "PyInstaller hide console window subprocess" (for the no-popup requirement)
   - "tkinter launcher multi-tool python" (for unified launcher patterns)
   - "audiobookshelf m4b metadata series tag" (for the series tagging spec)
   - "mutagen m4b chapter metadata python" (for metadata editor implementation)
   - "ffmpeg batch m4b to mp3 python" (for confirming M4B_Converter approach)
   - "python bootstrap installer non-technical users" (for setup script patterns)
   - "py2app vs PyInstaller macOS" (for the macOS double-click `.command` approach)

   Record findings in `Briefing.md` (both copies) with links.

3. **Decide the bundling strategy.** Two viable paths — pick one and justify in the Briefing:
   - **Path A (recommended for non-technical users):** Ship a one-time bootstrap. `setup_and_run.bat` / `.command` checks for Python, installs it via winget/Homebrew if missing, creates `.venv`, installs requirements, downloads ffmpeg portable binary, then launches the GUI. Subsequent double-clicks skip setup and just launch.
   - **Path B:** Ship a fully self-contained PyInstaller / py2app build. Larger download, but zero install time. Harder to update.

   Path A is the existing pattern (`setup_env.py`) and is more maintainable. Default to Path A unless research shows a clear reason otherwise.

4. **Map the unified launcher UX** on paper before writing code. Sketch (in the Briefing) the window layout: top bar with the 6 tools (TTS, M4B_Converter, MP3_Tool, M4B_Maker, cover_image_converter, M4B_Metadata_Editor), main area shows the selected tool's controls. Settle on whether tools open in tabs, in separate windows, or swap into a single content panel. Recommended: **swap into single content panel** — feels like a single app, not a bag of utilities.

### Debug Gate 0
- [ ] `Briefing.md` exists in both `Windows/md-instructions/` and `MacOS/md-instructions/` with: source repo inventory, GitHub research findings, bundling strategy decision, launcher UX sketch.
- [ ] `CHANGELOG.md` initialized in both with a "Phase 0 complete" entry.
- [ ] No code changes yet. **Do not proceed to Phase 1 until you can answer:** what does each of the 4 MP3_Tool subscripts actually do, line by line at the public-API level?

---

## 5. Phase 1 — Repository Restructure & File Migration

**Goal:** Get the final folder shape in place with all source files moved to their new homes. No behavior changes yet.

### 1.1 — Create skeleton

Create the folder skeleton from Section 2 with empty `__init__.py` where needed. Create stub `README.md` (will be filled in Phase 8), stub `CHANGELOG.md` and `Briefing.md` in both `md-instructions/` folders (the Briefing already exists from Phase 0 — extend it, don't overwrite).

### 1.2 — Migrate TTS_Project

For each of `Windows/` and `MacOS/`:

1. Copy all `.py` files from TTS_Project into `scripts/tts/`. Preserve the `epub2tts_edge/` package as a subdirectory.
2. Adjust imports so the tts subpackage is importable as `from tts.epub2tts_edge import ...` or similar — pick a convention and apply it consistently.
3. Move `requirements.txt` content into the OS-folder-level `requirements.txt`. Don't duplicate at root.
4. Move the `Dockerfile` only into `Windows/` (Linux container — keep with the Windows side for now; it's optional anyway). Note this choice in the Briefing.
5. Delete the existing `setup_env.bat` / `setup_env.command` from inside `scripts/tts/` — those get replaced by the new root-level `setup_and_run.*` in Phase 2. Keep `setup_env.py` as a library that the new setup script can call into.

### 1.3 — Migrate MP3_Tools

For each of `Windows/` and `MacOS/`:

1. Copy all `.py` files into `scripts/mp3_tools/`.
2. Keep the existing `launcher.py` from MP3_Tools renamed to `mp3_tools_launcher.py` temporarily — it will be **absorbed** into the unified launcher in Phase 3, not used as-is.
3. Merge MP3_Tools requirements into the OS-folder `requirements.txt` (deduplicate).

### 1.4 — Create the `shared/` module

Inside `scripts/shared/`, create:
- `paths.py` — single source of truth for project-relative paths (resources dir, default output dir, ffmpeg binary location, etc.). Use `pathlib`. **No hardcoded absolute paths anywhere else in the codebase after this phase.**
- `subprocess_utils.py` — wrapper around `subprocess.Popen` / `subprocess.run` that on Windows passes `CREATE_NO_WINDOW` (or `STARTUPINFO` with `SW_HIDE`) to suppress console pop-ups. **All ffmpeg / external binary calls go through this wrapper from Phase 3 onward.**
- `logging_setup.py` — file logger that writes to a per-session log under `resources/logs/` so users can attach a log when reporting bugs.

### 1.5 — Smoke test

From inside `Windows/scripts/`:
```
python -c "from tts.epub2tts_edge.epub2tts_edge import DEFAULT_SPEAKER; print(DEFAULT_SPEAKER)"
python -c "from mp3_tools import m4b_converter"  # adjust to your actual module name
```
Both must succeed without ModuleNotFoundError. Repeat from `MacOS/scripts/`.

### Debug Gate 1
- [ ] Root has exactly 5 items (note: the two `setup_and_run` files are stubs at this point — that's fine).
- [ ] Both `Windows/` and `MacOS/` have identical folder shape.
- [ ] Existing TTS GUI still launches when run directly via `python scripts/tts/epub2tts_gui.py` (imports work, GUI window opens).
- [ ] Existing MP3 launcher still launches when run directly via `python scripts/mp3_tools/mp3_tools_launcher.py`.
- [ ] `CHANGELOG.md` (both) updated with "Phase 1 complete — restructure only, no behavior change."

---

## 6. Phase 2 — `setup_and_run` Scripts (Cross-Platform Bootstrap)

**Goal:** A non-technical user double-clicks one file and ends up with a working environment + the launcher GUI open. Second double-click should skip setup and launch instantly.

### 2.1 — Behavior contract for both scripts

The bootstrap script must, in order:

1. Detect the platform (sanity check — refuse to run the .bat on Mac and vice versa).
2. Detect if `.venv` exists inside the OS subfolder. If yes and it's valid → skip to step 7.
3. Detect Python 3.11 or 3.12. If missing:
   - Windows: try `winget install Python.Python.3.12`. If winget unavailable, open the python.org download page in the browser and exit with a clear message.
   - macOS: try `brew install python@3.12`. If Homebrew unavailable, open the Homebrew install page and exit clearly.
4. Create `.venv` inside the OS subfolder (`Windows/.venv/` or `MacOS/.venv/`). **Not at root** — keeps the root clean per the structure rule.
5. Install requirements from the OS-folder `requirements.txt` into `.venv`.
6. Ensure ffmpeg:
   - Windows: prefer winget (`Gyan.FFmpeg`); fallback to downloading a portable build into `Windows/resources/bin/` and adding that to the spawned process PATH (don't permanently modify user PATH).
   - macOS: prefer `brew install ffmpeg`.
   - Either way, after install verify `ffmpeg -version` works from the script's resolved PATH.
7. Launch the unified launcher GUI as a detached process so the bootstrap terminal/console can close.
8. Suppress the console window on subsequent launches: on Windows use `pythonw.exe` (not `python.exe`) for the launcher. On macOS, the `.command` script should `exec` so the Terminal window closes when the GUI starts (or use `osascript` to launch without a visible terminal — research and pick the cleanest).

### 2.2 — Implementation files

- `setup_and_run.bat` — Windows. Should be **simple and readable** since it's the first thing a curious user opens. The heavy lifting lives in a Python helper: `Windows/scripts/shared/bootstrap.py`.
- `setup_and_run.command` — macOS. Same pattern: bash wrapper that calls `MacOS/scripts/shared/bootstrap.py`.

**Anti-patterns to avoid:**
- Don't reinvent `setup_env.py` — adapt it. It already handles ffmpeg/espeak/Kokoro logic well. Refactor it into `bootstrap.py` and have the .bat/.command call it.
- Don't require admin/sudo unless absolutely necessary. Winget and Homebrew user-level installs are fine.
- Don't print scary error messages. Catch failures and show a friendly dialog (use `tkinter.messagebox` since tk is in the stdlib and you'll need it for the GUI anyway).
- Don't leave a console window open behind the GUI. This is explicit user requirement.

### 2.3 — First-run vs subsequent-run UX

- **First run:** Show a small Tk progress dialog ("Installing Python… Installing ffmpeg… Downloading voice model… 2/5 done"). The text-only console output should also be tee'd to a log file in `resources/logs/` for debug.
- **Subsequent runs:** No setup checks beyond the existence of `.venv`. Should feel like launching any normal desktop app. Target: under 2 seconds from double-click to GUI window appearing.

### 2.4 — Kokoro model handling

The current `setup_env.py` pre-downloads the Kokoro model (~300 MB) at install time. Keep that, but make it **opt-in** via a checkbox on the first-run Tk dialog ("Download Kokoro AI voices now (~300 MB) — skip and they'll download the first time you pick a Kokoro voice"). Default: checked.

### Debug Gate 2
- [ ] Fresh Windows VM (or a Windows machine with no Python installed): double-click `setup_and_run.bat` → user sees a friendly progress UI → ends with the launcher GUI open. Total user clicks: 1.
- [ ] Same on macOS: double-click `setup_and_run.command` → friendly UI → launcher opens.
- [ ] Second double-click on both platforms: launcher opens in under 2 seconds, no console window visible.
- [ ] Logs written to `resources/logs/setup_YYYY-MM-DD.log`.
- [ ] `CHANGELOG.md` (both) updated.

---

## 7. Phase 3 — Unified Launcher GUI

**Goal:** One window that exposes all six tools. Looks like a single application, not a bag of utilities. No console pop-ups during any tool's operation.

### 3.1 — Layout

Build a Tk application with this structure (subject to refinement during Phase 0 UX sketch):

```
+--------------------------------------------------------------+
|  Audiobook Creation Tool                            [_][□][X]|
+--------------------------------------------------------------+
|  ┌────────────────┐                                          |
|  │ TTS Audiobook  │  ← Sidebar: 6 tool buttons               |
|  │ M4B Converter  │                                          |
|  │ MP3 Tool       │     ┌───────────────────────────────┐    |
|  │ M4B Maker      │     │                               │    |
|  │ Cover Image    │     │   Selected tool's content     │    |
|  │ M4B Metadata   │     │   panel swaps in here         │    |
|  └────────────────┘     │                               │    |
|                         └───────────────────────────────┘    |
+--------------------------------------------------------------+
|  Status bar:  Ready.  |  Log: open log folder                |
+--------------------------------------------------------------+
```

Implementation: a left sidebar of buttons, a right content `Frame` that gets cleared and repopulated when a tool is selected. Each tool exposes a `build_ui(parent_frame)` function.

### 3.2 — Refactor each existing tool to expose `build_ui(parent_frame)`

Both the existing TTS GUI (`epub2tts_gui.py` → `main()` builds its own `Tk()` root) and the MP3 launcher's tool windows currently assume they own the root window. Refactor:

- Extract each tool's widget-building code into a function `build_ui(parent: tk.Frame) -> None`.
- The original standalone entry points (`if __name__ == "__main__": main()`) remain so each tool can still be run alone for debugging, but they now wrap the same `build_ui` inside a private `Tk()` root.
- The unified launcher calls `build_ui(content_frame)` and never spawns a child Tk root.

### 3.3 — Suppress console windows from subprocess calls

Every `subprocess.run`, `subprocess.Popen`, `asyncio.create_subprocess_exec`, or `os.system` call in any of the tools must go through `shared/subprocess_utils.py`. On Windows that wrapper applies:

```python
# scripts/shared/subprocess_utils.py
import subprocess, sys

def _hidden_kwargs():
    if sys.platform != "win32":
        return {}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return {
        "startupinfo": si,
        "creationflags": subprocess.CREATE_NO_WINDOW,
    }

def run(cmd, **kw):
    return subprocess.run(cmd, **{**_hidden_kwargs(), **kw})

def popen(cmd, **kw):
    return subprocess.Popen(cmd, **{**_hidden_kwargs(), **kw})
```

Grep the codebase after refactor — there should be **zero** direct `subprocess.run(` / `subprocess.Popen(` calls outside this file.

For `edge-tts` and `pydub` (which spawn ffmpeg internally), check whether they expose a way to pass startup info. If not, document the limitation in the Briefing — pydub on Windows is known to flash console windows briefly. Mitigation options to research: setting `pydub.utils.get_prober_name` / `AudioSegment.converter` to a wrapper script, or running the whole launcher under `pythonw.exe` (which is the recommended fix).

### 3.4 — Persistent settings

Add `scripts/shared/settings.py` — load/save a JSON config to `resources/settings.json`. Tools should remember:
- Last-used input folder, output folder
- Last-selected voice, bitrate, pause-timing preset
- Window size and sidebar selection at last close

### Debug Gate 3
- [ ] Launcher opens. Each of the 5 existing tools (the 6th comes in Phase 6) loads into the content panel when its sidebar button is clicked.
- [ ] Running a TTS conversion from inside the launcher produces the same output file it did when run from the old standalone GUI.
- [ ] Running an MP3_Tool / M4B_Maker / M4B_Converter / cover_image operation from inside the launcher works identically to before.
- [ ] **Critical:** during any operation, no console window flashes on Windows. Verify by running with `pythonw.exe`.
- [ ] Settings persist across launcher restarts.
- [ ] `CHANGELOG.md` (both) updated.

---

## 8. Phase 4 — TTS Integration & Polish

**Goal:** The TTS tool inside the unified launcher matches or exceeds the current standalone GUI.

### 4.1 — Verify feature parity

Run through the existing `epub2tts_gui.py` feature list and confirm every control still works inside the launcher panel:

- Single-file mode (EPUB / PDF / TXT → MP3)
- Batch mode (folder of PDFs → MP3s)
- Voice selector with all 11 voices (6 Edge + 5 Kokoro)
- Per-voice timing preset auto-load
- Edge TTS pause/trim controls
- Kokoro speed control
- Resume support for batch
- Overwrite behavior
- Live log streaming into the panel
- Cancel mid-job (if the current GUI supports it; if not, **add it** — see 4.2)

### 4.2 — Add cancel-job button

Currently the GUI starts a worker thread but doesn't expose a clean way to cancel. Add a **Cancel** button next to **Start** that:
- Sets a `threading.Event` the worker checks between chunks/files.
- Kills any in-flight `asyncio` Edge TTS task by cancelling the event loop.
- Cleans up temp directories.
- Returns the UI to idle state.

### 4.3 — Cross-platform path handling audit

The current TTS code has a few cwd-dependent spots (per the README's developer guide: "Original upstream logic wrote `part*.flac`, `sntnc*.mp3`, etc. into the process cwd. Runner pins all of that under one temp directory"). Confirm the runner is being used everywhere — including from inside the new launcher — and that no operation writes anything to the launcher's cwd.

### Debug Gate 4
- [ ] All 11 voices work from inside the launcher.
- [ ] A test EPUB converts to MP3 with identical audio output to the pre-refactor version (spot check: same duration ± 1 sec, same chapter count).
- [ ] Cancel button stops a running batch within 5 seconds.
- [ ] No files created outside the user-specified output folder or `resources/logs/`.
- [ ] `CHANGELOG.md` (both) updated.

---

## 9. Phase 5 — MP3 Tools Integration

**Goal:** All four existing MP3 tools work inside the unified launcher. Same outputs, cleaner UX, no console flashes.

### 5.1 — Per-tool integration checklist

For each of M4B_Converter, MP3_Tool, M4B_Maker, cover_image_converter:

1. Extract `build_ui(parent_frame)` (from Phase 3.2).
2. Replace any `subprocess` calls with `shared/subprocess_utils.run`.
3. Replace any hardcoded paths with `shared/paths.py` references.
4. Route progress output to the launcher's log panel (don't `print()` to stdout — use a logger that the launcher subscribes to).
5. Confirm ffmpeg invocations work with the bundled-or-system ffmpeg the bootstrap installed.
6. Add a "Cancel" button where long operations exist.

### 5.2 — MP3_Tool deep-dive (this one is underspecified in the brief)

The user described MP3_Tool as "uses ffmpeg to modify and metadata tag mp3 files and a few other functions (explore)". **Treat exploration as a deliverable:** read the existing MP3_Tool source carefully, then write a one-page summary in `Briefing.md` documenting every function/feature it currently exposes. Confirm with a session check-in if any feature seems unclear or risky to port.

### 5.3 — Shared metadata layer

M4B_Maker, MP3_Tool, and the new M4B_Metadata_Editor (Phase 6) all manipulate metadata. Build a shared module: `scripts/shared/metadata.py` using **mutagen** (already in TTS requirements). Expose:
- `read_metadata(file_path) -> dict`
- `write_metadata(file_path, fields: dict, preserve_unset: bool = True)` — the `preserve_unset` flag is critical for the new Metadata Editor (Phase 6.2).
- Support both MP3 (ID3) and M4B (MP4 atoms) transparently.

All three tools should consume this module instead of each rolling their own tagging code.

### Debug Gate 5
- [ ] Each MP3 tool runs from the launcher and produces output bit-equivalent to its standalone pre-refactor version (when given the same input).
- [ ] `Briefing.md` contains the MP3_Tool feature inventory.
- [ ] No tool flashes a console window on Windows.
- [ ] `shared/metadata.py` exists and is the single tagging path.
- [ ] `CHANGELOG.md` (both) updated.

---

## 10. Phase 6 — New Features

### 6.1 — Series tagging in M4B_Maker

**Spec:** Audiobookshelf groups audiobooks into series via specific metadata fields. Research which atoms it uses (typical convention: `----:com.apple.iTunes:SERIES` and `----:com.apple.iTunes:SERIES-PART` as freeform MP4 atoms, sometimes also `tvsh` and `tves` as legacy fallbacks). Confirm by checking Audiobookshelf's documentation/source on GitHub and record findings in the Briefing.

**UI additions to M4B_Maker:**
- **Series name** text field (optional — empty means standalone book).
- **Series position** numeric field (e.g., `1`, `2`, `2.5`). Empty allowed when series name is empty; required when series name is filled.
- Save these as MP4 atoms when the file is written, in whatever format Audiobookshelf reads. **Verify by importing the resulting M4B into Audiobookshelf** if the user has a test instance, or by inspecting with `mutagen-inspect` / `AtomicParsley` if not.

### 6.2 — New Script 5: M4B Metadata Tag Editor

**Spec:**
- Sidebar entry in the launcher: "M4B Metadata Editor".
- UI:
  - File picker supports **single file** or **multiple files** (multi-select).
  - When a single file is loaded, all fields populate with that file's current values.
  - When multiple files are loaded, fields show either the common value (if all files share it) or an explicit placeholder like `<multiple values>`.
  - Editable fields: Title, Author, Album/Book title, Genre, Year, Description/Comment, Series name, Series position, Cover image.
  - **Preserve-on-blank rule:** any field left at its placeholder or untouched is NOT written. Only fields the user explicitly edits get written. This is the core behavioral requirement and must be tested rigorously.
  - "Apply to all selected" button when multi-file mode is active.
- Backend: uses `shared/metadata.py` with `preserve_unset=True`.

**Edge cases to handle and test:**
- File is open/locked by another process → show a friendly error, skip that file, continue with the others.
- File is not actually an M4B (mismatched extension) → reject before any write.
- Cover image replacement must not break existing chapter markers.
- Atomicity: write to a temp file, then move-replace, so a crash doesn't corrupt the original.

### 6.3 — Wire both features into the launcher

Add the M4B Metadata Editor as the 6th sidebar entry. Re-test the launcher end-to-end after the addition.

### Debug Gate 6
- [ ] Create three M4B files via M4B_Maker, all with the same series name and positions 1/2/3. Inspect tags with `mutagen-inspect` — confirm series fields are present in the format Audiobookshelf expects.
- [ ] Load one of those M4Bs into the Metadata Editor: all fields show correct existing values.
- [ ] Edit only the year, save: verify year changed, all other fields (especially series name, cover image, chapter markers) are byte-identical to before.
- [ ] Load all three M4Bs into the Metadata Editor in multi-mode: shared fields show common values, differing fields show `<multiple values>`. Edit only the genre, apply to all: all three files now have the new genre, every other field unchanged in each.
- [ ] Try to edit a file that's been opened in another program: friendly error, no corruption.
- [ ] `CHANGELOG.md` (both) updated with feature notes.

---

## 11. Phase 7 — Bug Hunt & Hardening

**Goal:** Catch bugs lurking in the legacy code (some MP3 scripts are old per the user's note) before declaring this done.

### 7.1 — Static audit

Run on each platform:
- `python -m py_compile` on every `.py` file → zero errors.
- `ruff check scripts/` (install ruff if not already) → triage every warning. Fix or document.
- `python -m pip check` inside `.venv` → no broken dependency graph.

### 7.2 — Targeted manual test matrix

Build the table below in `Briefing.md` and check every cell on each platform:

| Test | Windows | macOS |
|---|---|---|
| Fresh install via setup_and_run | | |
| Re-launch (no setup) under 2s | | |
| TTS: short EPUB → MP3, Edge voice | | |
| TTS: short EPUB → MP3, Kokoro voice | | |
| TTS: PDF → MP3 | | |
| TTS: batch folder of PDFs | | |
| TTS: cancel mid-batch | | |
| M4B Converter: batch M4B → MP3 | | |
| MP3 Tool: each function exposed | | |
| M4B Maker: assemble 10 MP3s into M4B with chapters | | |
| M4B Maker: with series tag (new) | | |
| Cover Image Converter: square → padded | | |
| Cover Image Converter: tall → padded | | |
| Metadata Editor: single-file edit | | |
| Metadata Editor: multi-file edit | | |
| Metadata Editor: blank-field preservation | | |
| Launcher: no console flash anywhere | | |
| Unicode filenames (e.g., accents, CJK) | | |
| Path with spaces | | |
| Very long path | | |
| Cancel + retry | | |
| Settings persist across restart | | |

### 7.3 — Specific bug-prone areas to audit

Based on the source code I can already see, prioritize checking:

1. **`batch_convert.py` `_natural_sort_key`** — confirmed working but verify Unicode behavior.
2. **`pdf_extractor.py` heuristics** — soft-line rejoin and dehyphenation can occasionally over-merge or under-merge; test a PDF with footnotes and one with multi-column layout.
3. **`kokoro_synth.py` Python version gate** — currently `< 3.13`. Confirm bootstrap installs 3.12 specifically on systems where user might have 3.13 already.
4. **`epub2tts_edge.py` cwd dependence** — already documented as a risk; verify Runner is used everywhere.
5. **MP3_Tool's ffmpeg invocations** — audit for shell=True (dangerous and not needed) and for unquoted paths with spaces.
6. **M4B_Maker chapter offset accuracy** — concatenating many MP3s, chapter timestamps must remain exact; check with `ffprobe -show_chapters` on the output.
7. **cover_image_converter** — confirm it handles PNG with alpha, animated GIF (should reject or flatten), CMYK JPEG (Pillow can choke).
8. **Error handling everywhere** — every `except Exception` should at minimum log to file. No silent swallows.

### 7.4 — Logging consistency

Confirm `resources/logs/` accumulates a clean log per session and rotates (keep last 30 sessions). Make the "open log folder" status-bar link work on both platforms.

### Debug Gate 7
- [ ] Every cell of the test matrix is filled in as PASS or has a documented known issue with severity.
- [ ] Zero critical (data loss / corruption) issues open.
- [ ] Static audit clean.
- [ ] `CHANGELOG.md` (both) lists every bug found and whether it was fixed or deferred.

---

## 12. Phase 8 — Documentation & Final Polish

### 12.1 — Root `README.md`

Audience: someone landing on the GitHub page from your CV. Should cover:
- One-paragraph what-it-does.
- Screenshot of the launcher.
- "Download for Windows" / "Download for Mac" badges/links (release artifacts, not requiring git clone).
- 3-step quickstart: download zip, unzip, double-click setup file.
- Features list (TTS engines, MP3 utilities, M4B creation with series tagging, metadata editor).
- Tech stack (Python, Tk, mutagen, edge-tts, Kokoro-82M, ffmpeg, PyMuPDF).
- Credit upstream projects (epub2tts-edge, edge-tts, Kokoro) per their licenses.
- License (GPL-3.0 per the existing LICENSE).

**Tone:** professional, no marketing fluff, no emoji-heavy. CV-grade.

### 12.2 — Finalize `Briefing.md` (both copies)

Make it the document a future Claude chat session reads first to get fully caught up. Include:
- Project goals (copy from this plan's Section 1).
- Final structure (Section 2).
- Where each subsystem lives and what it does.
- Key design decisions and rationale (bundling strategy, launcher UX, metadata library choice).
- Known issues / deferred items.
- How to run, how to test, how to release.

### 12.3 — Finalize `CHANGELOG.md` (both copies)

Reorganize the session-by-session entries into a clean per-version format (Keep-a-Changelog style):

```
## [1.0.0] - YYYY-MM-DD
### Added
### Changed
### Fixed
### Deprecated
### Removed
### Security
```

Future bug fixes append to this. Make sure the convention is documented at the top of the file.

### 12.4 — Remove this plan

Delete `IMPLEMENTATION_PLAN.md` from the repo root. Its content is now distributed across the Briefing and CHANGELOG files.

### Debug Gate 8 (final)
- [ ] Root has exactly 5 items: `README.md`, `setup_and_run.bat`, `setup_and_run.command`, `Windows/`, `MacOS/`.
- [ ] README renders well on GitHub.
- [ ] Both Briefings are self-sufficient — a new Claude chat reading only the Briefing can answer "what is this project and what's done?" without ambiguity.
- [ ] CHANGELOGs are clean and consistent across both copies.
- [ ] This file is deleted.
- [ ] A first-time test user (or a fresh VM) can go from zip download to working audiobook output in under 5 minutes with zero terminal interaction.

---

## 13. Cross-Cutting Guidelines (apply throughout every phase)

1. **Don't break what works.** Every refactor must preserve existing behavior unless the brief explicitly says to change it. Keep one-file rollbacks easy.
2. **No hidden state.** All paths derive from `shared/paths.py`. All settings persist in `resources/settings.json`. No reliance on cwd, no scattered constants.
3. **Never spawn a visible console window during normal operation.** Use `pythonw` on Windows, route all subprocesses through `shared/subprocess_utils.py`. This is a hard requirement, not a nice-to-have.
4. **Mirror Windows ↔ MacOS.** Anything done in `Windows/scripts/` has an equivalent in `MacOS/scripts/`. If they diverge intentionally, document the divergence in both Briefings.
5. **Keep diffs reviewable.** End each session with a clean commit message and a CHANGELOG entry. Don't dump 20 file changes with a one-line message.
6. **Ask before going off-spec.** If the source code reveals a contradiction with this plan, write the question into the CHANGELOG under "Open Questions" and pause rather than guess.

---

## 14. Quick Phase Index

| Phase | Outcome | Risk if skipped |
|---|---|---|
| 0 — Research | Mental model + GitHub prior art | Wasted work in later phases |
| 1 — Restructure | Final folder shape, no behavior change | Repo never becomes shippable |
| 2 — Bootstrap | Non-technical install in one click | Project is dev-only |
| 3 — Unified Launcher | Single GUI, no console flashes | Feels like a bag of scripts |
| 4 — TTS Integration | TTS works inside launcher | Regression on the existing feature |
| 5 — MP3 Tools Integration | All 4 MP3 tools work inside launcher | Regression on existing features |
| 6 — New Features | Series tagging + Metadata Editor | User's primary feature request unmet |
| 7 — Bug Hunt | Hardened, tested across platforms | Ships with known bugs |
| 8 — Docs & Polish | CV-grade README, briefings, changelogs | Looks unfinished on GitHub |

Begin at Phase 0. Do not skip ahead.
