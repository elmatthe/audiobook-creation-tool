# Audiobook Creation Tool — Handoff

## Current Focus
**UX progress + metadata layout drop (`0.5.0-ux-progress-and-metadata-layout.md`) —
ALL PHASES (1–5) DONE on HOME-MacOS (2026-07-08), awaiting maintainer final sign-off
+ the single drop commit.** Phase-4 layout was visually approved by the maintainer
(scrolling, larger Log, de-staled description, progress all confirmed). Phase 5
close-out: full suite 46 passed / 3 skipped; `python scripts/verify.py` →
RESULT: PASS; Windows/classic path proven unchanged (scoped win32 stub on ui_theme →
classic mode, Segoe UI, 6 ttk sidebar buttons, all six tools built, zero error
panels); CHANGELOG [Unreleased] Added+Changed entries, Briefing (ui_theme /
worker-progress / metadata-editor bullets), DECISIONS ADR (progress placement in
ui_theme.py + the deliberate M4B Maker indeterminate call). Drop file deliberately
NOT deleted and nothing committed (maintainer instruction — no .git on this copy;
the maintainer carries files to a real clone, single commit, no AI co-author
trailers).
Work summary — Phase 2: shared `ProgressIndicator` (ttk.Progressbar +
counter/percentage label, main-thread-only `update/set_indeterminate/reset/finish`
API) in `shared/ui_theme.py` (NOT the launcher — tools import shared.*, never
launcher.py) + headless-guarded test. Phase 3: progress wired into all six tools
strictly through each tool's EXISTING worker queue/drain (workers only enqueue
`("progress", (done, total))` / `("progress_ind", text)`; no off-thread widget
violations found in any tool). Determinate: M4B Converter (files), Cover Image
(images), M4B Metadata (files ×3 workers), MP3 Tool (SAFE-combine per track,
time-edit + ID3 per file), TTS (Edge batch + Kokoro batch per file; Kokoro single
per chunk and Edge single per paragraph via new additive `progress_callback=None`
params in `kokoro_file_to_mp3` / `read_book` / `run_conversion_job`). Indeterminate:
M4B Maker (single concat/encode — its old bar was dead: 0 until one jump at the end;
dead `progress_max` queue kind removed) and MP3 Tool's single-concat stages (FAST
mode, SAFE final concat). Phase 4: metadata editor tag/settings sections wrapped in
the exact TTS-style scroll canvas (canvas_wrap + create_window + scrollregion/width
sync + `enable_mousewheel`), Log enlarged to a fixed 14 rows outside the scroll
area, stale "(Added in Phase 6.)" description fixed in launcher.py. Cancel + Log
untouched on every tool. The two previous foci below also still await their single
maintainer commits.

## Previous Focus (component-verify drop — awaiting maintainer commit)
**macOS component-verify drop (`0.5.0-macos-component-verify.md`) — ALL PHASES DONE on
HOME-MacOS (2026-07-08), awaiting maintainer sign-off + the single drop commit.**
Phase 1 kickoff gates green; Phase 2 (Kokoro §2.4) was already fixed 2026-07-07, health
re-confirmed only; Phase 3 voice samples 11/11, approved by maintainer listen; Phase 4
per-tool live pass — **all six tools confirmed working live on macOS** (maintainer reviewed
screenshots), zero macOS-specific breakage, zero code changes; Phase 5 close-out — full
suite 45 passed / 3 skipped, `python scripts/verify.py` → RESULT: PASS, docs updated.
**Residual gap (not a bug):** M4B Converter was verified on a standard AAC-LC M4B only —
the `aac_at` xHE-AAC/USAC decode path on macOS is still unverified (no USAC sample on
hand); see Briefing known limitations. Drop file deliberately NOT deleted and nothing
committed (maintainer instruction). Still no `.git` on this copy — the maintainer carries
files to a real clone. Previous focus below (UI-shell drop close-out) also remains
awaiting its single maintainer commit.

## Previous Focus (UI-shell drop — awaiting maintainer commit)
**macOS UI-shell drop (`0.5.0-macos-ui-shell.md`) — ALL PHASES DONE on HOME-MacOS
(look approved by maintainer 2026-07-08; wheel/trackpad scroll fix added; Phase 5
close-out complete, verify → RESULT: PASS).** Awaiting two maintainer actions:
(1) live-test wheel/two-finger scrolling on the TTS panel, then (2) make the single
drop commit (drop file deliberately NOT deleted and nothing committed until then).
Earlier: the Kokoro-on-macOS §2.4 fix in `bootstrap.py` is live-verified on this
machine and still uncommitted alongside this drop's work. **⚠ This Mac's working copy
has NO `.git` directory** (not a clone — likely copied/zip-transferred), so nothing
can be committed or pushed from this machine as-is; the maintainer must reconcile
these changes onto a real clone. Windows-side drops still pending after this:
Drop 4 (script hardening), then the Windows UI drop.

---

## Open Issues / Bugs

| # | Severity | File | Description | Status | Found by |
|---|----------|------|-------------|--------|----------|
| 1 | Minor | scripts/Universal/shared/bootstrap.py | Drop 3 §2.4 (Kokoro on macOS) — RESOLVED 2026-07-07 on the MacBook. Real root cause: ENVIRONMENTAL, not `kokoro_synth.py`. The venv was built on Python 3.13.7 (the Mac's only Python), but Kokoro's PyPI wheels require >=3.10,<3.13, so the requirements marker skipped the wheel and every self-heal repair failed with "No matching distribution found for kokoro==0.9.4". Fixed in `bootstrap.py`: `run_setup` now installs Python 3.12 before accepting a >=3.13 interpreter (3.13+ kept only as Edge-only fallback), and `_create_validated_venv` rebuilds a >=3.13 venv once a <3.13 base exists. Verified live: 3.12.13 venv, `kokoro_is_healthy` → `(True, 'ok')`. See DECISIONS.md 2026-07-07 ADR. | **Closed — fixed in bootstrap.py** | Claude Code |
| 2 | Minor | scripts/Universal/tts/kokoro_synth.py | CLI-only cosmetic: `kokoro_file_to_mp3`'s default `log=print` emits a `→` character, which raises UnicodeEncodeError on a cp1252-encoded Windows console (found while scripting Drop 3 verification). The GUI is unaffected (logs go through the Tk queue, never stdout). Flagged for review, not fixed — out of Drop 3 scope. | Open — flagged for maintainer | Claude Code |
|   |       |     | (Windows xHE-AAC decode is a documented known limitation, not a bug — see CHANGELOG [0.3.2]. The macOS `aac_at` counterpart decodes AAC-LC fine (verified 2026-07-08) but an actual xHE-AAC/USAC decode on macOS is still unverified — no USAC sample on hand.) | | |

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
- 2026-07-08 — UX-progress drop Phase 5 — DROP DONE (MacBook session; no commit —
  no .git here; drop file NOT deleted per maintainer instruction). Maintainer
  approved the Phase-4 metadata layout visually (scroll, larger Log, description,
  progress). Close-out gates: full suite 46 passed / 3 skipped;
  `python scripts/verify.py` → RESULT: PASS. Windows/classic proof: launcher
  constructed under a win32 stub scoped to ui_theme's sys reference (a global
  sys.platform stub breaks stdlib shutil — same technique as the UI-shell drop):
  theme mode "classic", family "Segoe UI", colors/metrics None, 6 plain ttk.Button
  sidebar entries, all six tools built through the real LauncherApp with zero error
  panels, settings.json snapshot/restored. Docs: CHANGELOG [Unreleased] gained the
  UX-progress Added + Changed entries; Briefing updated (ui_theme bullet gains
  ProgressIndicator, worker/data-flow bullet gains the progress-marshaling rule,
  metadata-editor bullet gains the scroll layout + 14-row Log); DECISIONS gained
  the progress-placement + Maker-indeterminate ADR; handoff (this file — focus,
  work log, sync log). Awaiting maintainer final sign-off and the single drop
  commit; the maintainer deletes the drop file at commit time (or asks for it to
  be deleted then). — Claude Code
- 2026-07-08 — UX-progress drop Phases 1–4 done; STOPPED at the Phase-4 visual gate
  (MacBook session; no commit — no .git here). Phase 1 re-run after a context clear:
  confirmed no prior Phase 2/3/4 work existed on disk before starting. Phase 2:
  `ProgressIndicator` in shared/ui_theme.py + test_ui_theme.py test. Phase 3 per tool —
  M4B Converter/Cover Image: existing queue "progress" payload widened to (done, total),
  bar swapped for the indicator (determinate, per file/image); M4B Metadata: same for
  all three workers (save / clear-tags / remove-numbering; determinate per file);
  M4B Maker: indeterminate during the single concat/encode, 1/1 on success (old bar was
  dead — value 0 until one end-jump; dead "progress_max" pump branch removed);
  MP3 Tool: new indicator + queue kinds — combine determinate per track in SAFE
  normalize, indeterminate "Concatenating…" during FAST/final concat, time-edit + ID3
  determinate per file; TTS: indicator beside Start/Cancel, Edge/Kokoro batch per-file
  counts, Kokoro single per-chunk and Edge single per-paragraph via new additive
  progress_callback=None params (kokoro_synth.py, epub2tts_edge.py read_book,
  runner.py) — defaults keep all non-GUI callers byte-identical in behaviour. All
  updates flow worker→queue→main-thread drain (same path as each Log box); Cancel and
  Log wiring untouched on every tool. Phase 4: metadata editor scroll canvas mirroring
  the TTS wiring exactly, Log 8→14 rows fixed below the scroll area, launcher
  description de-staled. Gates: compileall clean; suite 46 passed / 3 skipped
  (test_launcher_smoke builds all 6 tools); real-Tk behavioural check of the new
  layout (canvas window, %d Leave bind, log row, busy/idle toggle) passed. NOT done
  (deliberate): Phase 5 close-out — waits for the maintainer's visual sign-off on the
  metadata editor. — Claude Code
- 2026-07-08 — Component-verify drop Phases 4–5 — DROP DONE (MacBook session; no commit —
  no .git here; drop file NOT deleted per maintainer instruction). **Phase 3 gate:**
  maintainer listened to all 11 samples and approved. **Phase 4 (per-tool live pass) —
  PASS:** all six tools exercised end-to-end on macOS under the new Finder shell and
  confirmed working by the maintainer (screenshots reviewed): TTS Audiobook (Edge +
  Kokoro voices, pause-timing fields effective, panel scrolling works), M4B Converter,
  MP3 Tool, M4B Maker, Cover Image, M4B Metadata Editor (Drop 2 shared-metadata
  pre-fill + "(varies)" + Open Folder…). No macOS-specific breakage found — zero code
  changes, so no new regression tests were needed. Caveat recorded everywhere: the M4B
  Converter ran against a standard AAC-LC M4B; the `aac_at` xHE-AAC/USAC decode path is
  still unverified on macOS (no USAC sample on hand). **Phase 5 (close-out):** full
  suite 45 passed / 3 skipped; `python scripts/verify.py` → RESULT: PASS. Docs:
  CHANGELOG [Unreleased] component-verify Verified entry; Briefing macOS-live-pass
  known-limitation bullet retired (replaced by the narrow xHE-AAC-on-macOS residual,
  folded into the Windows xHE-AAC bullet) + High-Level State notes the macOS live pass;
  handoff (this file — focus, open-issues note, work log, sync log). Open Issues #1 was
  already closed 2026-07-07; no DECISIONS ADR needed (no new aac_at/MPS decision arose —
  decoder selection pre-existed in ffmpeg_utils.py). Awaiting maintainer sign-off and
  the single drop commit. — Claude Code
- 2026-07-08 — Component-verify drop Phases 1–3 (MacBook session; no commit — no .git here).
  **Phase 1 (kickoff gates) — PASS:** venv Python 3.12.13; edge-tts 7.2.8 imports;
  `kokoro_is_healthy(venv_python())` → `(True, 'ok')`; real `.command` fast-path launch OK
  (Kokoro health-check ok, GUI detached, launch log clean); test instance closed (a
  pre-existing maintainer launcher window from 04:03 was left running). **Phase 2 (§2.4):**
  treated as CLOSED per maintainer — fixed 2026-07-07 in bootstrap.py (environmental: 3.13
  venv; now forced 3.12), `kokoro_synth._get_pipeline` untouched; only the health check was
  re-run. **Phase 3 (voice samples):** `tts/generate_voice_samples.py` run on macOS →
  11/11 OK (6 Edge + 5 Kokoro) in `files/test-for-manual-listen-elmatthe/`. STOPPED at the
  maintainer manual-listen gate; Phase 4 (per-tool live pass) starts only after sign-off.
  — Claude Code
- 2026-07-08 — Wheel/trackpad scroll fix + UI-shell drop Phase 5 close-out (MacBook
  session; maintainer approved the Finder look first; no commit — maintainer makes the
  single drop commit after live-testing scroll). **Scroll fix:** the TTS options panel
  never scrolled on wheel/trackpad (only scrollbar drag worked) — pre-existing bug in
  SHARED code, so the fix improves Windows and macOS alike. Root cause: the wheel
  handler was armed by Enter/Leave on `options_canvas`, but the form frame covers the
  canvas, so the canvas Enter almost never fired. New
  `shared.ui_theme.enable_mousewheel(scroll_target, hover_region)` binds Enter/Leave
  on the panel's wrap frame instead and ignores Leave-with-detail-NotifyInferior
  (pointer into a child = still inside the panel). CRITICAL non-obvious bit: tkinter's
  bind() never delivers the crossing detail (`%d` absent from `Misc._subst_format_str`
  — verified live on Tk 9.0.3), so the Leave side is a Tcl-level bind; see the
  2026-07-08 DECISIONS ADR before "simplifying" it. `epub2tts_gui.py` now calls
  `enable_mousewheel(options_canvas, hover_region=canvas_wrap)` (old inline handler
  removed). All-scrollers sweep: every other scroller (M4B Converter / MP3 Tool /
  M4B Maker / Cover Image / M4B Metadata Listbox + Text/ScrolledText widgets) already
  scrolls natively via Tk class bindings — verified live with synthetic MouseWheel
  events — so NONE needed the helper; none were touched. Verified end-to-end on the
  real TTS panel (real Tk): Enter-on-wrap arms bind_all, wheel over a child Entry
  scrolls the canvas, Leave(NotifyInferior) keeps the binding, real Leave unbinds;
  same flow re-proven under the classic/win32 path (ui_theme-scoped platform stub —
  stubbing sys.platform globally breaks stdlib shutil) incl. Windows ±120 deltas.
  **Phase 5:** `test_ui_theme.py` gained the headless-guarded `enable_mousewheel`
  wiring test (asserts Enter/Leave bound + Tcl-level %d on the Leave script; wheel
  motion itself can't be simulated headless). Full suite 45 passed / 3 skipped;
  `python scripts/verify.py` → RESULT: PASS. Docs: CHANGELOG (UI shell Added + scroll
  Fixed), Briefing (GUI/launcher/shared bullets + macOS-live caveat narrowed to the
  per-tool matrix), DECISIONS (aqua-vs-clam ADR deferred from Phase 3 + wheel-binding
  ADR). Drop file NOT deleted, nothing committed — both deliberate, awaiting the
  maintainer's live scroll test and single drop commit. — Claude Code
- 2026-07-08 — macOS UI-shell drop Phases 1–4 done (MacBook session spanning the
  07-07→07-08 midnight; no commit — awaiting maintainer UI review before Phase 5).
  **Phase 1** — AI-WORKSPACE.md → HOME-MacOS filled from the real machine: root
  `~/Desktop/Coding_Repositories` (claude-skills-main inside it, no MyProjects split),
  MacBook Pro 14" M4 Pro (14c) · 24 GB · macOS Tahoe 26.5.2 · 1 TB (~466 GB free),
  user `elijahmatthew` = Administrator (sudo w/ password), brew python@3.12+3.13 with
  Tk, default python3 = 3.13.7; noted TCC blocks agent shells from listing ~/Desktop.
  **Phase 2 (baseline launch gate) — PASS**: deleted `.venv`, invoked the real
  `.command` via Finder-equivalent `open`. First-run setup: correct 3.12 base chosen
  (the §2.4 fix working), venv built, all pinned deps installed, ffmpeg on PATH,
  Kokoro model + voices ready (setup_2026-07-07.log, run marker 23:48:28). Caveat:
  the setup window's final auto-launch step wasn't observed (window was closed
  on-screen right at the end — agent shells here have no Accessibility permission,
  so the "Begin Setup" click and window handling happened at the physical machine);
  launch itself was then proven via the `.command` fast path: Kokoro health-check ok,
  GUI on screen detached, Terminal auto-closed promptless, session log clean.
  Health: edge-tts 7.2.8 imports, kokoro_is_healthy → (True, 'ok'), 11 voices
  (6 Edge + 5 Kokoro). Logs: files/runtime-data/logs/{setup_2026-07-07.log,
  launch_2026-07-07.log, launch_2026-07-08.log}.
  **Phase 3** — `scripts/Universal/shared/ui_theme.py` added (apply_theme(root, style)
  → fonts/colors/metrics dict). Research done live on this Mac (Tk 9.0.3): native
  `aqua` chosen over Finder-styled clam (native controls in all six panels, auto
  dark-mode — this Mac runs dark mode; aqua can't recolor native ttk buttons, so the
  sidebar chrome uses classic tk widgets); fonts via `.AppleSystemUIFont` (SF Pro
  Text/Display are NOT installed font families on Tahoe), fallback Helvetica Neue;
  macOS semantic system colors + computed blends (alpha colors flatten in Tk).
  DECISIONS.md ADR deferred to Phase 5 per drop. win32/other branch reproduces the
  old look byte-identically (vista/Segoe UI; clam/TkDefaultFont). Headless-guarded
  `files/tests/test_ui_theme.py` added (3 tests: current platform, stubbed win32
  values, stubbed linux) — pass.
  **Phase 4** — launcher.py wired to ui_theme.apply_theme(); `_build_ui` split into
  `_build_ui_classic` (old body verbatim — Windows tree unchanged) and
  `_build_ui_darwin` (Finder shell: tinted source-list sidebar w/ hover +
  accent-selection rows + emoji glyphs, toolbar strip naming the active tool +
  description, hairline-bordered content card, refined status bar w/ system link
  color). `build_ui(parent)` contract, lazy build-once/show-hide, last_tool restore,
  load-error panel, `_on_close` all untouched; the six tools' internals untouched
  (only launcher.py edited + ui_theme.py/test added). Verified: compileall clean;
  test_launcher_smoke (6/6 tools through the real LauncherApp on the new shell) +
  test_ui_theme pass; scoped win32-stub constructs the classic layout (6 ttk
  buttons); darwin behavioral check (selection/hover/toolbar/build-once) pass; real
  `.command` fast-path launch with the new UI confirmed on screen and left open for
  review. NOT done yet (deliberately): Phase 5 bug hunt, full verify.py run, doc
  close-out, DECISIONS ADR, drop-file deletion, commit. — Claude Code
- 2026-07-07 — §2.4 Kokoro-on-macOS root-caused and FIXED (MacBook session; no commit —
  maintainer reviews first). Live diagnosis: `.venv` was Python 3.13.7 (the Mac's only
  Python — no python3.12 anywhere), and the setup log showed pip skipping kokoro
  (`markers 'python_version < "3.13"' don't match`) then every self-heal repair dying on
  "No matching distribution found for kokoro==0.9.4" (newest 3.13-compatible release on
  PyPI is 0.7.16). ENVIRONMENTAL — `kokoro_synth.py` untouched. Three `bootstrap.py`
  changes: `_is_kokoro_compatible()` helper (single source of the >=3.10,<3.13 range);
  `run_setup` now calls `install_python` when the found interpreter is >=3.13 and only
  keeps it if 3.12 truly can't be installed (logs "Edge TTS works, Kokoro voices
  disabled"); `_create_validated_venv` rmtree-rebuilds an existing >=3.13 venv when the
  chosen base is <3.13 (closes the "bad venv reused forever" gap). Windows path
  unaffected (`py -3.12` is found directly, branches never fire). Verified live: brew
  python@3.12 + python-tk@3.12 installed, old venv deleted, full headless setup → venv
  Python 3.12.13, ssl=True tkinter=True, kokoro==0.9.4 installed,
  `kokoro_is_healthy(venv_python())` → `(True, 'ok')`. New test
  `files/tests/test_bootstrap_python_version.py` (7 params over the version gate,
  pure logic). `python scripts/verify.py` → RESULT: PASS (41 passed, 3 skipped).
  Docs: CHANGELOG macOS-verify entry, DECISIONS ADR, Open Issues #1 closed. — Claude Code
- 2026-07-07 — Drop 3 complete — DROP 3 DONE (no commit yet — maintainer reviews then
  makes the single drop commit). Per `drop3-plan.md` (deleted on close-out):
  **Phase 1** — batch Kokoro now passes `end_silence_ms=end_pause` (was baking the 3000 ms
  default); `chunk_pause_ms=50` kwarg anchor confirmed pre-existing, untouched.
  **Phase 2.1** — `paragraph_pause` hoisted on the main thread next to `end_pause`
  (never read Tk vars off-thread) and passed as `chunk_pause_ms` into BOTH the
  single-file and batch `kokoro_file_to_mp3` calls. Sentence/title/chapter parity
  deliberately deferred — ADR added to DECISIONS.md.
  **Phase 2.2** — `run_batch_convert` + the GUI Kokoro batch now mirror each source's
  path relative to the input dir under the output dir (same-stem files in different
  subfolders no longer overwrite); Resume checks the mirrored target; per-file temp
  chunk dirs keyed off the relative path (they collided on stem too); flat inputs
  keep the exact old flat layout. **Phase 2.3** — batch discovers `.txt` alongside
  `.pdf` on both engines; `.txt` is read directly (PDF extractor bypassed — the GUI
  Kokoro `_do_one` needed the same suffix branch, a necessary deviation from the
  plan's "label + glob only" wording since `pdf_to_txt` would fail on `.txt`);
  labels updated. **Phase 2.4** — BLOCKED (see Open Issues #1): needs a real Mac.
  **Phase 3.1** — `tts/generate_voice_samples.py` added per plan verbatim (only
  change: removed the plan's unused `import tempfile`); output folder gitignored;
  live run 11/11 voices OK. **Phase 3.2** — 8 new tests in
  `test_batch_convert_folders.py` (5: mirroring / same-stem PDFs via fitz / txt
  bypasses extractor / flat regression / mirrored resume; fake `synthesize_chunk_mp3`,
  no network) + `test_kokoro_timing_wiring.py` (3: fake `_get_pipeline`; duration
  deltas prove `end_silence_ms`/`chunk_pause_ms` are applied). **Phase 3.3** — Edge
  pause scaling verified live (small 10 269 ms vs large 23 769 ms — scales, no
  escalation needed). Extra live QA: real-model Kokoro single-file (chunk 200→2000 ms
  = exactly +1800 ms; end 0→3000 ms = exactly +3000 ms) and a real-Tk GUI smoke
  driving the actual panel (batch radio → voice combobox event → spinboxes → Start)
  over nested txt+pdf with same-stem books: mirrored tree, no collisions, 4/4 outputs.
  Gates: compileall scripts/Universal + files/tests clean; `python scripts/verify.py`
  → RESULT: PASS (34 passed, 3 skipped; 1 pre-existing pydub audioop warning).
  Docs: CHANGELOG Drop 3 entries, Briefing TTS bullet, DECISIONS pause-mapping ADR.
  — Claude Code
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

### 2026-07-08 — MacBook — UX-progress drop (all phases) — NOT committed (no .git on this copy)
- Changed: scripts/Universal/shared/ui_theme.py (new ProgressIndicator class)
- Changed: scripts/Universal/mp3_tools/m4b_converter.py (indicator + (done,total) payload)
- Changed: scripts/Universal/mp3_tools/cover_resizer.py (indicator + (done,total) payload)
- Changed: scripts/Universal/mp3_tools/m4b_maker.py (indicator, indeterminate encode,
  dead progress_max branch removed)
- Changed: scripts/Universal/mp3_tools/mp3_tool.py (new indicator + progress/progress_ind
  queue kinds + per-worker ticks)
- Changed: scripts/Universal/mp3_tools/m4b_metadata_editor.py (indicator + (done,total)
  payloads; Phase 4 scroll-canvas layout + 14-row Log)
- Changed: scripts/Universal/tts/epub2tts_gui.py (indicator beside Start/Cancel; progress
  enqueues in all four conversion paths)
- Changed: scripts/Universal/tts/kokoro_synth.py (additive progress_callback param)
- Changed: scripts/Universal/tts/epub2tts_edge/epub2tts_edge.py (read_book
  progress_callback, paragraph units)
- Changed: scripts/Universal/tts/epub2tts_edge/runner.py (progress_callback pass-through)
- Changed: scripts/Universal/launcher.py (M4B Metadata description de-staled)
- Changed: files/tests/test_ui_theme.py (ProgressIndicator test)
- Changed: md-instructions/CHANGELOG.md ([Unreleased] UX-progress Added + Changed)
- Changed: md-instructions/Briefing.md (ui_theme / worker-progress / metadata-editor
  bullets)
- Changed: md-instructions/DECISIONS.md (progress-placement + Maker-indeterminate ADR)
- Changed: md-instructions/handoff.md (this file — focus, work log, sync log)
- Note:    Phase 5 close-out complete (suite 46/3, verify PASS, win32-stub classic
           proof). Drop file 0.5.0-ux-progress-and-metadata-layout.md intentionally
           NOT deleted and nothing committed (maintainer instruction) — maintainer
           does the final sign-off, carries files to a real clone, and makes the
           single drop commit (no AI co-author trailers).

### 2026-07-08 — MacBook — component-verify drop (all phases) — NOT committed (no .git on this copy)
- Changed: md-instructions/CHANGELOG.md ([Unreleased] component-verify Verified entry)
- Changed: md-instructions/Briefing.md (xHE-AAC bullet reworded w/ macOS USAC residual;
  macOS-live-pass caveat retired; High-Level State notes the macOS per-tool pass)
- Changed: md-instructions/handoff.md (this file — focus, open-issues note, work log,
  sync log)
- Note:    NO program-code changes this drop — the live pass found no macOS breakage.
  The only working-tree deltas vs the previous sync entries are the three docs above.
- Note:    Drop file 0.5.0-macos-component-verify.md intentionally NOT deleted and
  nothing committed (maintainer instruction) — maintainer does the manual sign-off,
  carries files to a real clone, and makes the single drop commit (no AI co-author
  trailers).

### 2026-07-08 — MacBook — scroll fix + UI-shell Phase 5 close-out — NOT committed (no .git on this copy)
- Changed: scripts/Universal/shared/ui_theme.py (new enable_mousewheel helper —
  wrap-frame Enter/Leave + Tcl-level NotifyInferior guard)
- Changed: scripts/Universal/tts/epub2tts_gui.py (inline wheel handler + canvas
  Enter/Leave block replaced by enable_mousewheel(options_canvas, canvas_wrap);
  shared.ui_theme import added)
- Changed: files/tests/test_ui_theme.py (added enable_mousewheel wiring test)
- Changed: md-instructions/CHANGELOG.md ([Unreleased] macOS UI shell Added + Fixed)
- Changed: md-instructions/Briefing.md (GUI/launcher/shared/ui_theme bullets;
  macOS-live-pass caveat narrowed)
- Changed: md-instructions/DECISIONS.md (2 ADRs: aqua theme choice; wheel-binding
  Tcl-level detail guard)
- Changed: md-instructions/handoff.md (this file — focus, work log, sync log)
- Note:    Drop file 0.5.0-macos-ui-shell.md intentionally NOT deleted yet —
  maintainer live-tests scrolling on the TTS panel, then makes the single drop
  commit (one commit for Phases 1–5 + this fix; no AI co-author trailers) and
  deletes the drop file.

### 2026-07-08 — MacBook — UI-shell drop Phases 1–4 — NOT committed (no .git on this copy)
- Changed: AI-WORKSPACE.md (HOME-MacOS section filled in from the real machine)
- Added:   scripts/Universal/shared/ui_theme.py (apply_theme; aqua/Finder vs classic)
- Changed: scripts/Universal/launcher.py (wired to ui_theme; _build_ui split into
  classic (verbatim old body) + darwin Finder shell; _highlight_selection branch;
  _row_hover; _ui_font_family/DEFAULT_GEOMETRY/MIN_SIZE moved into ui_theme)
- Added:   files/tests/test_ui_theme.py (3 headless-guarded theme tests)
- Changed: md-instructions/handoff.md (this file — focus, work log, sync log)
- Note:    Machine state: `.venv` deleted and rebuilt fresh via the .command
  (Python 3.12.13, Kokoro healthy) as the Phase 2 launch-gate test.
- Note:    ⚠ This working copy has NO .git directory — the maintainer must carry
  these files onto a real clone (branch `restructure-v0.5.0` per plan) to commit.
  One commit for the whole drop, maintainer-made, no AI co-author trailers.

### 2026-07-07 — MacBook — §2.4 Kokoro fix — not committed, not pushed
- Changed: scripts/Universal/shared/bootstrap.py (`_is_kokoro_compatible` helper;
  run_setup installs 3.12 before accepting >=3.13; _create_validated_venv rebuilds a
  >=3.13 venv on a <3.13 base)
- Added:   files/tests/test_bootstrap_python_version.py (version-gate regression test)
- Changed: md-instructions/CHANGELOG.md ([Unreleased] macOS component-verify Fixed entry)
- Changed: md-instructions/DECISIONS.md (macOS-venv-on-3.12 ADR)
- Changed: md-instructions/handoff.md (this file — focus, Open Issues #1 closed,
  work log, sync log)
- Note:    Machine state changed: brew installed python@3.12 + python-tk@3.12; root
  `.venv` rebuilt on Python 3.12.13 (Kokoro healthy). No commits — maintainer reviews
  and commits. No AI co-author trailers.

### 2026-07-07 — HOME-PC — Drop 3 — committed, merged to master, pushed
- Changed: scripts/Universal/tts/epub2tts_gui.py (batch end_silence_ms fix; paragraph_pause
  hoist + chunk_pause_ms into both Kokoro calls; Kokoro batch .pdf/.txt discovery with
  mirrored output subfolders; mode/browse/docstring labels)
- Changed: scripts/Universal/tts/batch_convert.py (mirrored output tree + collision-safe
  temp dirs + .txt support; out_mp3 threaded through convert_single_pdf; docstrings/CLI text)
- Added:   scripts/Universal/tts/generate_voice_samples.py (per-voice manual-listen QA)
- Added:   files/tests/test_batch_convert_folders.py (5 tests)
- Added:   files/tests/test_kokoro_timing_wiring.py (3 tests)
- Changed: .gitignore (files/test-for-manual-listen-elmatthe/ — generated MP3 samples)
- Changed: md-instructions/CHANGELOG.md ([Unreleased] Drop 3 Fixed + Added)
- Changed: md-instructions/Briefing.md (TTS feature bullet)
- Changed: md-instructions/DECISIONS.md (Kokoro pause-mapping ADR)
- Changed: md-instructions/handoff.md (this file — focus, open issues, work log, sync log)
- Deleted: md-instructions/drop3-plan.md (drop implemented)
- Note:    md-instructions/Instructions_Template.md restored from HEAD — the working
           tree showed it deleted alongside the untracked drop file (the drop was
           evidently created from the template, same as before Drop 2), so the net
           working-tree diff for it is zero.
- Note:    Single Drop 3 commit made on restructure-v0.5.0 (stacked on 97758c2) at the
           maintainer's explicit instruction, then fast-forward merged to master and
           pushed. restructure-v0.5.0 RETAINED and pushed (base for macOS work).
           No AI co-author trailers.
- Note:    REMOTE ANOMALY FOUND AND RESOLVED at ship time: origin/master had been
           force-moved to a stale pre-restructure line (a20fa21 "Delete AI-WORKSPACE.md",
           a Jul 2 GitHub web-UI commit atop 391326e — the OLD test-files-scrub rewrite,
           content-identical to our 45c66e5 but with no common ancestor). Maintainer
           ruled it a stale accident: our line was force-pushed over it
           (--force-with-lease), so a20fa21 is gone from master and the root
           AI-WORKSPACE.md remains (as refreshed in 97758c2). If another machine still
           has the old line locally, hard-reset its master to origin/master before
           doing anything.
- Note:    Drop 3 §2.4 (Kokoro on macOS) is NOT done — blocked on a real Mac (Open
           Issues #1). It is the FIRST task for the MacBook session, from master.

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
