# Audiobook Creation Tool — Handoff

## Current Focus
v0.5.0 Drop 2 (metadata-editor shared detection) is **implementation-complete and verified**
on branch `restructure-v0.5.0`, stacked directly on the Drop 1 commit `a7044d4` (maintainer
ruling 2026-07-07: continue on this branch deliberately even though Drop 1 is pushed but not
yet merged to master). All phases done incl. the Jack Ryan QA pass (14/14, no findings);
`scripts/verify.py` → RESULT: PASS (26 passed, 3 env-gated skips). **Awaiting maintainer
review, then ONE commit covering the whole drop** (per the DECISIONS.md commit-policy entry;
the agent never pushes). Next after merge: Drop 3 (TTS), Drop 4 (script hardening), UI drop.

---

## Open Issues / Bugs

| # | Severity | File | Description | Status | Found by |
|---|----------|------|-------------|--------|----------|
| — | — | — | No open issues. (Windows xHE-AAC decode is a documented known limitation, not a bug — see CHANGELOG [0.3.2].) | — | — |

---

## Migration Map — contract for Phase 2 (drop `0.5.0-drop1-restructure-and-docs.md`)

Grounded in the fresh REPO-STRUCTURE.md (2026-07-06 15:56) and the maintainer's answers to all
nine open questions. Windows tree is the canonical source (trees byte-identical except the two
dead legacy files below).

**Program code → `scripts/Universal/`** (git mv from `Windows/scripts/`):
- `mp3_tools/{__init__,cover_resizer,m4b_converter,m4b_maker,m4b_metadata_editor,mp3_tool}.py`
- `shared/{__init__,bootstrap,cancellation,close_terminal,ffmpeg_utils,logging_setup,metadata,paths,release,settings,subprocess_utils,version}.py`
- `tts/{__init__,batch_convert,epub2tts_gui,kokoro_synth,pdf_extractor,voice_registry}.py`
- `tts/epub2tts_edge/{__init__,epub2tts_edge,runner}.py`
- `launcher.py`
- `Windows/requirements.txt` → `scripts/requirements.txt` (single shared; the two files were
  identical except the header comment — maintainer confirmed Q6)

**Deleted, not migrated (maintainer Q2 — confirmed dead, no legacy folder):**
- `scripts/mp3_tools/mp3_tools_launcher.py` (both trees)
- `scripts/tts/setup_env.py` (both trees)

**Dev-only → `files/`:**
- `scripts/tests/test_kokoro_voices.py` → `files/tests/`
- root `test-files/` → `files/test-files/` (stays gitignored — copyrighted media)
- `Windows/test-logs/` → `files/test-logs/` (gitignored)
- `Windows/Dockerfile` → `files/Dockerfile` (maintainer Q3 — dev-only, not a shipped path)
- v0.3.1 one-shot docs (`MACOS-DEBUG-v0.3.1.md`, `MACOS-FIX-REPORT-v0.3.1.md`,
  `WINDOWS-RELEASE-HANDOFF-v0.3.1.md`) → `files/release-history/` (one copy each)
- `files/vibe-coding-templates/` — already in place, unchanged

**Runtime-writable data → `files/runtime-data/` (maintainer Q4; layout chosen by agent):**
- `<OS>/resources/logs/` → `files/runtime-data/logs/` (gitignored; old log files not carried —
  runtime-generated)
- `<OS>/resources/settings.json` → `files/runtime-data/settings.json` (gitignored; Windows copy
  wins if the two diverge — it is the actively-used one)
- `Windows/resources/models/huggingface/` (Kokoro-82M cache, ~300 MB) →
  `files/runtime-data/models/huggingface/` (gitignored, never committed; answers Q5 — this is
  the ONE canonical in-repo cache path for `bootstrap.py`/`launcher.py`/`kokoro_synth.py`)
- `resources/bin/` concept (portable ffmpeg fallback) → `files/bin/` (the AI-WORKSPACE-standard
  home for setup-downloaded binaries; gitignored)
- Implementation: repoint `RESOURCES_DIR`-style constants in `paths.py` / `bootstrap.py` once;
  keep the internal `logs / models / settings.json` names so the diff stays minimal.

**md-instructions — two sets collapse into one root set:**
- `Windows/md-instructions/{Briefing,CHANGELOG}.md` + identical MacOS copies → one
  `md-instructions/{Briefing,CHANGELOG}.md` (byte-identical today, verified by diff — merge is
  trivial; then rewritten per Phase 3)
- New: `DECISIONS.md`, `Instructions_Template.md` (from `files/vibe-coding-templates/`)
- This `handoff.md` is already at its final location

**Entry points (maintainer Q1 + Q7):**
- Root launchers renamed to exactly `Setup_and_Run-audiobook-creation-tool.bat` /
  `Setup_and_Run-audiobook-creation-tool.command` (Phase 5). These stay the ONLY user-facing
  entry files.
- Fast path stays `bootstrap.py --launch-only` (self-heal on every launch preserved exactly),
  repointed to `scripts/Universal/shared/bootstrap.py`. No `cd` into `Windows/`/`MacOS/`.
- Preserve untouched: Windows `pythonw.exe` no-console fast path, macOS Gatekeeper/App
  Translocation guard, Kokoro/venv/ffmpeg self-heal. `.venv` moves to the repo root (the
  AI-WORKSPACE location) since the per-OS trees disappear.

**Other maintainer decisions:**
- Q8: create `.codex/` (CODEX.md pointer to AI-WORKSPACE.md + settings) — Codex is used.
- Q9: README gets a short v0.5.0 status line (internal restructure, no feature changes); keep
  v0.4.0 download links until a v0.5.0 release is published.
- Pending master edits (console-flash fix + AI-WORKSPACE.md) committed on master as `e80ba7f`
  BEFORE branching, so the restructure branch contains only restructure work.

**Drift found vs the drop's assumptions (reality followed, per drop rules):**
- The "loose root handoff.md" no longer exists; `md-instructions/handoff.md` was a blank
  template (no live state to migrate from it — live state reconstructed from the v0.3.1
  one-shots + CHANGELOG).
- Empty `scripts/{Universal,Windows,MacOS}/`, `md-instructions/`, and `files/` skeletons were
  pre-created by the maintainer before this session.
- Working tree had uncommitted `[Unreleased]` changes on master (handled above).
- `dist/` (gitignored release zips) stays at root — `release.py` writes there by design.

---

## Work Log (newest first)
- 2026-07-07 — Drop 2 Phase QA + close-out complete — DROP 2 DONE (no commit yet —
  maintainer reviews then makes the single drop commit). `files/tests/
  test_jack_ryan_final_product.py` added (env-gated on JACK_RYAN_M4B_FOLDER; `_m4bs()`
  guards the unset var at collection time so verify/CI skip cleanly — agreed deviation
  from the drop's verbatim code). Run against the real fixtures: **14/14 PASS, zero
  findings** (all 12 books: title, author, cover, titled chapters, integer parts, one
  consistent series name) — no Open Issues row needed. Unit tests
  `test_m4b_metadata_editor_shared.py` added (7 tests: shared/varies, missing key,
  album-implied, series_part display-only, unreadable-file exclusion, empty list,
  strip-compare). Gates: compileall scripts/+files/tests clean; full suite 26 passed /
  3 skipped (the one warning is the pre-existing pydub audioop deprecation, not Drop 2);
  `python scripts/verify.py` → RESULT: PASS. Docs: CHANGELOG [Unreleased] Drop 2 entry;
  Briefing metadata-editor bullet updated. Drop file `0.5.0-drop2-metadata.md` deleted.
  — Claude Code
- 2026-07-07 — Drop 2 Phase 3 complete (no commit — one-commit-per-drop rule).
  `btn_add_folder` added to the `disable_inputs` widget set. Smoke vs the real fixture
  tree (real UI instance, real `read_m4b_tags`, dialogs injected): Harry Potter 7 files →
  artist 'J.K. Rowling' + series 'Harry Potter' pre-filled, Title blank; Shadow Slave /
  Supreme Magus / Noble Queen also share Genre 'Web Novel'; Dungeon Crawler 8 files OK;
  Jack Ryan OUTER folder → "No audiobooks found" box (subfolder hint shown), list
  unchanged; Jack Ryan INNER folder → 12 files, Tom Clancy + 'Jack Ryan' shared;
  single-file pre-fill unchanged (title + per-file readback w/ source atom); empty
  folder → info box, list unchanged. series_part never pre-filled anywhere. Next:
  Phase QA (Jack Ryan inspection test) + unit tests + verify + docs. — Claude Code
- 2026-07-07 — Drop 2 Phase 2 complete (no commit — one-commit-per-drop rule). Added
  "Open Folder…" button + `add_folder()` (non-recursive .m4b/.m4a/.mp4; "No audiobooks
  found" box now explicitly says subfolders aren't searched — the drop's Jack Ryan
  caveat); `_refresh_mode` n>1 branch now calls `_prefill_shared(n)` (shared values
  pre-filled + snapshotted into `_prefill`, mode line names shared fields,
  `_batch_series_readback` summarises series identical/varies/none). Docstrings
  corrected vs the drop verbatim: module + `_prefill_shared` now state that shared
  NON-series fields left unedited ARE written on Save (byte-identical rewrite —
  maintainer ruling), only series keys are preserve-by-default. Verified via real Tk
  instance w/ monkeypatched `_tags_for`: shared artist/genre/series pre-fill; differing
  title blank; series_part never pre-filled; `_collect_tags` excludes unedited shared
  series but includes shared artist; varies read-back correct; empty-list mode label
  intact. py_compile clean. Next: Phase 3 (disable-state + manual smoke). — Claude Code
- 2026-07-07 — Drop 2 Phase 1 complete (no commit — one-commit-per-drop rule). Per
  `0.5.0-drop2-metadata.md`: added `self._tag_cache` to `__init__`, new `_tags_for()`
  (cached, fault-tolerant read — a failing file is logged and excluded, never aborts) and
  `_shared_tags()` (shared/varies across all readable files; `series_part` display-only;
  album-implied series treated as absent) in `m4b_metadata_editor.py`; cache cleared in
  `clear_list()` and `remove_selected()`. Purely additive — nothing calls the helpers yet.
  Two agreed deviations from the drop's literal anchors: new methods inserted after the
  complete `_prefill_from` body (the drop's mid-method anchor would break the file), and
  (upcoming, QA phase) `_m4bs()` will guard the unset env var at collection time.
  Maintainer rulings recorded: continue on `restructure-v0.5.0` atop unmerged Drop 1;
  NO `album_artist` row this drop; NO preserve-by-default for shared non-series fields
  (`_collect_tags` untouched). Verified: py_compile clean; `_shared_tags` on a stub —
  empty list → `({}, set())`; 3 files sharing artist w/ differing titles + album-implied
  series → `({'artist': 'X'}, {'title', 'series'})`. Next: Phase 2 (folder picker +
  batch wiring). — Claude Code
- 2026-07-07 — Phase 6 complete — DROP 1 DONE (no commit yet — maintainer reviews then makes
  the single drop commit). Bug hunt: whole-tree grep for stale tokens (`scripts\shared`,
  `resources\logs|bin|models|settings`, `Windows\...`, `MacOS\...`, `setup_and_run`) —
  remaining hits only in CHANGELOG history (preserved verbatim by design), handoff's own
  migration map, and files/release-history snapshots; live code + launchers + tests are clean.
  README repo-describing sections updated to the new layout (structure diagram, one-tree
  design note, files/bin ffmpeg path, release-build command; install steps use the new
  launcher names with "(named setup_and_run.* in the v0.4.0 zip)" parentheticals; v0.4.0
  download links kept per maintainer Q9). release.py dry run: both v0.5.0 zips built, exit 0,
  archive root = README + correct launcher only, zero runtime/test leaks, .command packaged
  0o755. Final gates: compileall scripts/ + files/tests clean; verify.py → 19 passed,
  RESULT: PASS. Deleted scratch REPO-STRUCTURE.md + Map-Repo-Structure.bat + the drop file
  `0.5.0-drop1-restructure-and-docs.md`. Root now: README, AI-WORKSPACE.md, two Setup_and_Run
  launchers, scripts/, files/, md-instructions/ (+ gitignored .venv/ + dist/). — Claude Code
- 2026-07-07 — Phase 5 complete (no commit — one-commit-per-drop rule). Root launchers
  git-mv-renamed to the exact maintainer-specified names
  `Setup_and_Run-audiobook-creation-tool.bat` / `.command` and rewired: no more `cd` into
  Windows/-MacOS/ (cd to repo root), BOOTSTRAP → scripts/Universal/shared/bootstrap.py,
  log-path messages → files/runtime-data/logs/. Preserved verbatim: Windows pythonw
  no-console fast path, macOS Gatekeeper/App-Translocation guard (sibling marker changed
  from MacOS/ to scripts/ — same logic + message), foreground --launch-only +
  close_terminal.py Terminal auto-close, Tk-capable-Python probe + Homebrew repair +
  headless fallback, winget Python install path. Kokoro install logic untouched (Drop 3).
  Verified live: bootstrap --self-test all green on the new layout (venv valid at root,
  requirements found, HF_HOME → files/runtime-data, kokoro health ok, launch target =
  scripts/Universal/launcher.py); real double-click path via the renamed .bat launched the
  GUI detached under pythonw (launch log in files/runtime-data/logs/, no crash output);
  test instance closed. — Claude Code
- 2026-07-07 — Phase 4 complete (no commit — one-commit-per-drop rule). scripts/verify.py
  stood up from verify-template (project name set; deps check made PEP-508-marker-aware so
  `kokoro==… ; python_version < "3.13"` / `audioop-lts==… ; python_version >= "3.13"` don't
  false-fail the operator regex — the pin rule applies to the spec before ';'). pytest==9.1.1
  added to scripts/requirements.txt and installed in the venv. files/tests/ suite written:
  conftest (import-root bootstrap) + launcher build-all smoke (all 6 tools through the real
  LauncherApp, error-panel monkeypatch, settings.json snapshot/restore) + per-tool
  behaviour-preservation smokes (tts voice registry 11-voice contract + pdf_to_txt on a
  generated PDF; mp3_tool hms/concat-escape/next-folder; m4b_maker natural sort/title
  normalization/ffmetadata chapters/concat quoting; m4b_converter sanitize_filename;
  cover_resizer letterbox+crop+ext-fallback+next_version_path via real PIL; shared.metadata
  ffmpeg args/header lines/freeform namespace/ABS series-atom constants). No network anywhere.
  One test expectation corrected against real behaviour (normalize_title: first `_` becomes
  the colon before the possessive rule can see it). `python scripts/verify.py` → 19 passed,
  RESULT: PASS. — Claude Code
- 2026-07-06 — Phase 3 complete (no commit — one-commit-per-drop rule). Briefing.md rewritten
  to current state per the template (architecture, all 6 tools, new layout, known limitations;
  old v0.1–0.3 status stack dropped — that history lives in CHANGELOG + files/release-history).
  CHANGELOG: prior [Unreleased] items (console-flash fix, test-fixture history scrub) folded
  into a new [0.5.0] - 2026-07-06 entry along with the restructure/Added-verify entries
  (explicitly "no user-facing tool changes"); fresh empty [Unreleased] on top; ALL prior
  history preserved verbatim. DECISIONS.md seeded with the drop's four ADRs + the
  runtime-data-layout ADR (+ the earlier commit-policy ADR). Instructions_Template.md written
  (project-tailored, uses <angle> slots so verify's [bracket] scan can't false-positive).
  version.py → 0.5.0; README status line → short v0.5.0-in-development note, v0.4.0 download
  links kept (maintainer Q9). .claude/CLAUDE.md + .codex/CODEX.md created pointing at
  AI-WORKSPACE.md with the kickoff read order and the no-per-phase-commit rule. — Claude Code
- 2026-07-06 — Phase 2 complete (no commit — one-commit-per-drop rule). Executed the full
  migration map: git mv Windows/scripts → scripts/Universal (git recorded all as renames —
  history preserved); requirements → scripts/requirements.txt (header de-Windows-ified);
  Dockerfile + v0.3.1 one-shots → files/{,release-history}; test_kokoro_voices.py →
  files/tests/; deleted mp3_tools_launcher.py + tts/setup_env.py + entire MacOS dupe tree.
  Untracked moves: settings.json/models/huggingface → files/runtime-data/, harness MP3s →
  files/test-logs/kokoro-voices/, test-files → files/test-files/, Windows/.venv → root .venv
  (old resources/logs discarded — runtime-generated). Rewired paths.py + bootstrap.py to
  REPO_ROOT derivation (RESOURCES_DIR → files/runtime-data, BIN_DIR → files/bin, VENV_DIR →
  root .venv, REQUIREMENTS → scripts/requirements.txt); removed the OS_ROOT alias everywhere;
  kokoro_synth HF fallback now walks to the repo root (scripts/+files/ present); release.py
  reworked for the single-tree layout (both zips = README + OS launcher + scripts/**);
  updated all stale resources/-and-setup_and_run docstrings. .gitkeep in scripts/{Windows,
  MacOS} so the empty OS dirs survive clone. Verified: compileall clean; headless build-all
  6/6 tools, no error panels, 1.35 s; all derived paths print correct new locations; moved
  venv works (Python 3.12.10). Old Windows/ + MacOS/ trees deleted. — Claude Code
- 2026-07-06 — Phase 1 complete (no commit — maintainer's one-commit-per-drop rule, see
  DECISIONS.md 2026-07-06 entry; applies to the whole v0.5.0 sequence). Rewrote .gitignore to
  the final layout (`.venv/` root, `files/bin/`, `files/runtime-data/`, `files/test-files/`,
  any-depth `test-logs/`; dropped all Windows/-MacOS/-prefixed rules); verified with
  `git check-ignore -v`. Created files/ skeleton (tests, release-history,
  runtime-data/{logs,models}, bin). DECISIONS.md created early with the standing commit-policy
  decision. Next: Phase 2 (the big migration). — Claude Code
- 2026-07-06 — Phase 0 complete. Committed pending console-flash fix + AI-WORKSPACE.md on
  master (`e80ba7f`); cut branch `restructure-v0.5.0`; re-ran Map-Repo-Structure.bat and
  reconciled the migration map (this file) against the fresh tree + all nine maintainer
  answers. Baseline recorded: `compileall` clean on both trees (venv Python 3.12.10); headless
  launcher build-all via the real `LauncherApp` = 6/6 tools built, zero error panels, 4.32 s.
  This is the known-good bar for every later phase. Next: Phase 1 (skeleton + .gitignore).
  — Claude Code
- 2026-07-06 — Session kickoff: read AI-WORKSPACE.md, both Briefing/CHANGELOG copies (verified
  byte-identical Win↔Mac), the three v0.3.1 one-shots, and the full Drop 1 instruction file.
  Confirmed version state: version.py/README = 0.4.0, CHANGELOG top release [0.4.0], tags
  v0.1.0–v0.4.0 incl. v0.3.1 (`49bb51a`). — Claude Code

---

## Session Sync Log (newest first)

### 2026-07-07 — HOME-PC — Drop 2 — not committed, not pushed
- Changed: scripts/Universal/mp3_tools/m4b_metadata_editor.py (tag cache + _tags_for/
  _shared_tags/_prefill_shared/_batch_series_readback, Open Folder… button + add_folder,
  batch branch of _refresh_mode, disable_inputs set, docstrings)
- Added:   files/tests/test_m4b_metadata_editor_shared.py (7 detection unit tests)
- Added:   files/tests/test_jack_ryan_final_product.py (env-gated QA inspection)
- Changed: md-instructions/CHANGELOG.md ([Unreleased] Drop 2 entry)
- Changed: md-instructions/Briefing.md (metadata-editor feature bullet)
- Changed: md-instructions/handoff.md (this file — focus, work log, sync log)
- Deleted: md-instructions/0.5.0-drop2-metadata.md (drop implemented)
- Note:    Awaiting maintainer review → single Drop 2 commit on restructure-v0.5.0
           (stacked on a7044d4). Agent does not push. No AI co-author trailers.
- Note:    A SECOND separate commit follows Drop 2 (maintainer ruling, same precedent
           as e80ba7f): the refreshed root AI-WORKSPACE.md + the synced copy at
           files/vibe-coding-templates/AI-WORKSPACE.md. Pre-Drop-2 working-tree
           leftovers resolved: Map-Repo-Structure.bat + REPO-STRUCTURE.md discarded
           (scratch); md-instructions/Instructions_Template.md restored from HEAD
           (deletion predated the session; the refreshed AI-WORKSPACE still
           references it).

### 2026-07-07 — HOME-PC — not committed, not pushed
- Entire v0.5.0 Drop 1 restructure sits UNCOMMITTED in the working tree of branch
  `restructure-v0.5.0` (per the one-commit-per-drop rule): all git mv renames staged,
  new files (tests, verify.py, DECISIONS.md, handoff.md, Instructions_Template.md,
  .claude/CLAUDE.md, .codex/, files/vibe-coding-templates/) untracked pending the single
  drop commit the maintainer will make after review.
- Do NOT start work on another machine until this branch is committed, force-pushed by the
  maintainer, and merged — the whole tree has moved.

### 2026-07-06 — HOME-PC — not pushed
- Changed: AI-WORKSPACE.md (refreshed global workspace doc — committed on master `e80ba7f`)
- Changed: Windows+MacOS scripts/launcher.py, scripts/shared/subprocess_utils.py,
  md-instructions/CHANGELOG.md (console-flash fix, committed on master `e80ba7f`)
- Added:   md-instructions/handoff.md (this file — de-templated, migration map written)
- Note:    Branch `restructure-v0.5.0` active; restructure in flight. Do not start work on
           another machine until this branch merges — the whole tree is about to move.
