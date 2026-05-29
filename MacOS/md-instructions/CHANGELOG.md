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
- _(nothing yet — Phase 1 is restructure only, no behavior change)_

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
