# Audiobook Creation Tool — Handoff

Current state only. Earlier text: this file was compacted in v0.8.2 Phase 0B from 27,317 lines; the full previous Handoff is
`git show 85462005bc203e6b33fd975e2709fe3d9014b7b3:md-instructions/Handoff.md` (the same path in `Briefing.md`). Architecture and limits: `Briefing.md`;
why: `Decisions.md` index; what shipped: `Changelog.md` index.

## Execution Snapshot

- **Date:** 2026-11-27
- **Last agent:** Claude Code (Opus 5.5), v0.8.2 Phase 1A-1 R2 recovery, D-R2-10 campaign and closeout
- **Machine:** HOME-PC (Windows 11)
- **Branch:** `0.8.2` (long-running, from published v0.8.1), developed in the permanent short-path clone `C:\ACT-Dev` (owner decision D-1, 2026-11-25) with its own real root `.venv/`; the old nested worktree `files/dev-work/wt082` and the owner's primary checkout (`0.8.1`, uncommitted owner work) are preserved as found and were not modified
- **Status:** Phase 1A-1 failed independent review twice (8d7226d, then the R1 re-verification of 9b5eb0a). The R2 remediation's history: its first attempt stopped BLOCKED as a compatibility discovery and planning stop; the implemented R2 then stopped BLOCKED in self-verification (the bounded compatibility campaign exhausted its budget at 16 of 19 batches with routine-effects failures, and the real v3-planning and v3-supervisor guarded stages failed because their scrubbed worker environments drop the routine marker). The owner then decided D-R2-6 to D-R2-10. The R2 recovery is implemented and its pilot passed through the gate (every reviewed family, both real guarded groups, the gate contract in three parts, the evidence module; each with `routine-effects` 0 refusals, 0 problems), and the D-R2-10 campaign's first segment ran 10 of 17 planned batches (32 minutes): eight PASS, and two whose pytest, routine-effects and cleanup all passed but which failed on findings outside R2 -- the requested-scope check on `test_kokoro_voices.py`, a manual script with no pytest test that the campaign manifest wrongly requested, and the skip policy on a Qwen3 test skipped for want of a Qwen3 environment (the known environment-only finding). The second segment was first BLOCKED by resources (free disk space just below the 10 GiB required before a segment); the owner then authorized removing three historical gate scratch folders (about 32 GiB, their sealed evidence kept elsewhere), and the campaign finished on 2026-11-27 inside the D-R2-10 budget (74 of 120 minutes, three segments): batches 10 to 16 (the Qwen3 packaging/process group, release packaging and repository contract, suite isolation group, and the gate contract module in four parts against the final `verify.py`) and the five named control runs of both real guarded groups (v3-supervisor 75 passed; v3-planning 85, 47, 242 and 83 passed) all PASS, except batch 12, whose pytest passed but whose routine-effects named two launches of `test_tk_finalisation.py`'s deliberate Tcl_AsyncDelete crash test as unexplained: that crash fixture lacked its exact `routine_stop("native-crash", codes=(0x80000003,))` marker. The marker was added (a marker-off control reproduces both problems, marker-on has none), batch 12 stays FAIL in the record, and its rerun on the fixed candidate (plus the hardening-matrix guard that parses that file) PASSES (716 passed, routine-effects clean); every post-fix batch differs from batch 0 only in that one test file. Reconciled on 2026-11-27: batches 0 to 9 ran on the current executable candidate (only the documentation digest differs since); the Kokoro script is excluded by `verification.json` `inventory.modules_without_tests` (batch 3 stays FAIL in the record); the Qwen3 skip is not recognized by the skip policy, neither the test nor the policy changed in R2, and it stays an environment-blocked obligation of this machine (no Qwen3 environment), not waived; the direct-run FFmpeg refusals come from a direct run's TEMP lying outside its disposable roots (the same test passes with TEMP inside them, and through the gate), not from a profile defect. R2 is committed as one remediation commit on `0.8.2` (agent-verified, not independent) and awaits independent Codex R2 review. Gate and test infrastructure only (VERSION stays 0.8.1)
- **Active plan:** `files/plans/Developer-Experience-Upgrade.md` (Revision 5, amendment R2)
- **Current phase:** v0.8.2 Developer Experience Upgrade, Phase 1A-1 R2 remediated (agent-verified, not independent; awaiting independent Codex R2 review); Phase 1A-2 (heavyweight admission) on HOLD, NOT started
- **Recommended next execution tier:** independent Codex R2 review of the R2 commit; Phase 1A-2 only after that passes and on its own prompt
- **Last verification:** Phase 1A-1 R2, agent-reported, not independent: the R2 gate pilot and the D-R2-10 campaign (focused gate runs only; results in Status above and plan amendment R2; run ids in the R2 commit message); both real guarded groups on the final candidate PASS. Before that, Phase 1A-1 R1: focused gate runs on the frozen R1 tree, each with `routine-effects` and `requested-scope` PASS -- the R1 infrastructure and collateral modules `2026-11-25_231539_focused_b69f` (896 passed, 0 skipped, 18 modules), the gate contract (explicit routine nodes) and evidence modules `2026-11-25_230754_focused_595d` (449 passed, 0 skipped: 170 routine contract functions and the evidence module), and the mandatory guarded run of v3-planning and v3-supervisor `2026-11-25_231843_focused_d8c3`; defect reproduction 20/20 RED on 8d7226d and GREEN on R1. No full run: the last full gate, on 87dd2bf (2026-11-22), is FAIL/BLOCKED and does not describe this candidate
- **Manual gate:** owner listening to four regenerated Shadow Slave MP3s; owner decisions D-1 to D-4, D-6, D-8; plus the owner-acceptance items below
- **Relevant evidence:** the old worktree `files/dev-work/wt082` still holds the protected local evidence (see Development Checkout and Evidence Locations); the new gate runs are in `C:\ACT-Dev\files\dev-work\verification-gate\outputs\`; `files/release-history/ACT-v0.8.1-Windows-MacOS-Release-Acceptance.md`
- **Next exact action:** independent Codex R2 review of the R2 commit on `0.8.2` (its D-R2-10 campaign results are in plan amendment R2 and the Status above). Open obligations it does not close: the Qwen3 skip needs a Qwen3 environment on this machine (installing one needs separate owner authorization), and native macOS verification of the R2 envelope. Do not begin Phase 1A-2. The interim heavyweight restrictions (GATE.md) stay in force. Do not merge, tag or release

## In Progress

**Phase 1A-1 R2 is committed on `0.8.2`, awaiting independent Codex R2 review** (gate and test infrastructure: the ledger v3 accounting, the launch decision and child bootstrap, reviewed fixture profiles, explained termination, D-R2-6 to D-R2-9 and the recovery's accounting corrections; plan amendment R2 and its Decisions entry). Its gate pilot passed; its D-R2-10 campaign resolved all 17 manifest batches and the five guarded controls (one localized marker fix, rerun PASS; the Kokoro manifest error and the environment-only Qwen3 skip recorded, neither waived), after a disk interruption the owner resolved. Earlier, **Phase 1A-1 R1** remediated
(plan amendment R1; Decisions 2026-11-25 R1; GATE.md "Routine envelope"): H1 location is never evidence of a synthetic run (maintained roots refuse
themselves wherever they lie; one reviewed synthetic gate fixture, `act-synthetic-fixture.json`); H2 the launch contract judges the program actually
started, its form, working directory and environment (reviewed bounded shapes: stage 0, the setup launchers' stand-in sandboxes, `sh -n`); H3 one
early envelope (`routine_effects.bootstrap`) for `routine_pytest.py` and `guarded_pytest.py` before pytest loads, plus operation checks at the gate's
heavyweight callables; H4 canonical selector identity before guarded routing; M1 the requested module or node is the scope (`requested-scope`);
M2 per-process effect ledgers that fail closed; M3 `execution_plan.admit` re-resolves; C1-C4 one no-follow inventory, local-only identity by the
filesystem's case rule, staged deletion with recreation, dependency uncertainty as a gap and a diagnostic candidate identity. Earlier: Phase 1A-1 implemented the explicit execution plan (`helpers/execution_plan.py`), the six-mode
contracts with `--plan`, Git changed-file selection (`helpers/git_changes.py`) routed through the reverse import closure (`helpers/selection.py`), static
capability classification (`helpers/effects.py`, `ACT_EFFECTS`, `effects.reviewed_bounded`, the ENTRY table of 60 entrypoints) and the runtime routine
envelope (`files/tests/routine_effects.py`, `routine_pytest.py`, `conftest.py`, `helpers/routine_context.py`); recorded plan Revision 5 (A5-W, A5-M, A6-R,
ENTRY, the 1A-1/1A-2/1A-3 split); and added the sanitized spike report `files/plans/ASTRA-ARCHITECTURE-SPIKE-VERDICT.md`. GATE.md is the current
command and policy reference. Pre-Phase 1A (28d8c7b) prepared `C:\ACT-Dev`; DOC-1 archival belongs to Phase 2; nothing is archived.

## Open Issues and Blockers

Status words: **FAIL**, **BLOCKED** (could not run), **NOT RUN**, **PENDING** (owner), **UNVERIFIED**. Agent-reported verification is not independent
review. Items marked (?) could not be proven closed from the record and are kept on purpose.

**Phase 0A carry-forward and workspace**
- RESOLVED (Pre-Phase 1A): the tree-building tests of `test_verification_gate_contract.py` (including the edited `docnames` fixture) and the rest of
  `test_verify_evidence.py` ran through the gate in `C:\ACT-Dev`: preflight PASS, 411 passed, 0 skipped (details under Verification and Evidence).
- AI Workspace alignment DONE locally (2026-11-26, local-only, never staged): the owner's 2026-11-04 workspace snapshot is installed unchanged in `C:\ACT-Dev` (`AI-WORKSPACE.md` and the seven `.ai/` guides; its master and template `AI-WORKSPACE.md` are identical; no install
  record). The ACT-specific `AGENTS.md` keeps every ACT rule and gains an override section for the shared text's conflicts: `main` (ACT uses `master`), tracked `AGENTS.md`/`.ai/ENVIRONMENT.md` (D-5 keeps them local), plans in `md-instructions/`
  (ACT: `files/plans/`), the `src/`/`tests/` layout and `unittest` (ACT: `scripts/`, `files/tests/`, pytest through `routine_pytest.py` or the gate), the "legacy" template gate (ACT's `GATE.md` is authoritative), commit-and-push autonomy, scratch
  locations. Thin `CLAUDE.md` imports `AGENTS.md` and `AI-WORKSPACE.md`; `.ai/ENVIRONMENT.local.md` holds machine facts. Not adopted: the template `.claude/settings.json` (its `git add`/`git commit` allow rules conflict with reviewed staging), the scaffolder, installer,
  `Replace_AI-WORKSPACE.bat`, launchers and the template gate. Open: the shared text assumes `files/run-temp/` is gitignored; in ACT it is untracked and unignored (below; a tracked `.gitignore` correction is the owner's call).
- The primary checkout's `.claude/CLAUDE.md` is stale (retired gate path `scripts/verify.py`, old document spellings, a `files/dev/qwen_worker.py` delegation rule
  although `files/dev/` does not exist, `scripts/Universal`) and Claude Code loads it as a parent-directory file in sessions started below the primary checkout (`wt082`).
  `C:\ACT-Dev` has no competing parent instruction file (its parent is the drive root); the stale file remains for the owner to retire or replace and was not modified.
  A sanitized review bundle of the Phase 0A files is local-only under the old worktree's `files/run-temp/`.
- Phase 0B review corrections (recorded in Pre-Phase 1A): the Decisions index is a navigation aid and never supersedes an unlisted decision; outstanding historical defects are
  reassessed for release relevance at the final independent review; `files/run-temp/` is untracked AND unignored (owner decision), so a careless `git add` stages review bundles
  and ledgers: Phase 2 decides its treatment.
- Owner-local tooling stale (?): `scripts/project-status.py` (untracked, primary checkout) also reads `files/runtime/verify-state.json`, which the gate no
  longer writes; `files/dev-work/local-model-worker.py` and `capability-discovery.py` are absent (not adopted). `scripts/requirements.txt` line ~106 still names the
  retired `scripts/verify.py` (its bytes are hashed into the locks; leave until a lock regeneration).

**Verification and gate**
- Phase 1A-1 R1 (agent-reported, NOT independent): awaiting Codex R1 re-verification. Residual limits (GATE.md): a cooperating-verification control, not an
  OS sandbox; native code, Quartz input, arbitrary shell code and a shell fed on standard input are outside the audit hooks; a child that refuses, cannot
  write its record and whose exit its caller ignores is caught only when the ledger is unusable; renamed or stand-in recognition is by exact bytes;
  raw `python -m pytest` is not evidence (supported: `routine_pytest.py` and the gate); a whole module with declared heavyweight nodes is INCOMPLETE
  (request its routine nodes); native macOS verification of the R1 envelope and of the case-sensitive routing is PENDING (a portable simulation passes).
  Obligations carried to 1A-2/1A-3: admission at every heavyweight entrypoint (the R1 refusals become admissions only with an A6-R grant under the A5
  lock), the plan-only modes, the final evidence schema (1B). The whole ordinary suite was swept diagnostically by direct runs (not evidence; every
  envelope collateral fixed); `test_root_lifetime`'s two declared nodes refuse there by design.
- Interim rule (GATE.md, in force until 1A-2/1A-3): no `--mode full` or `--mode qualification --scenario`, no journey, real engine, install, download, benchmark or
  release build without the owner's authorization for that run. quick, changed, regression, focused `--feature` and qualification `--journey` print their plans only (exit 3).
- Phase 1A-1 compatibility seams (removal criteria in GATE.md): an owner-authorized Windows full run cannot PASS until 1A-2, because its ordinary stage now runs inside the
  routine envelope and refuses the declared heavyweight tests of the release partition (`test_root_lifetime.py`'s two application arms, the first-run force-quit test);
  full and qualification `--scenario` execute outside the new admission (interim rule); the plan-only modes execute from 1A-3; `selection.json` keeps its legacy keys until 1B.
- Phase 1A-1 limits (GATE.md): a cooperating-verification control, not an OS sandbox (a child given a replacement environment, arbitrary shell code); non-loopback sockets
  are not refused globally and no ambient model-hub offline flag is imposed (1A-2/1A-3); the whole ordinary suite was NOT run against the new envelope (routine scope only;
  a static scan found no other routine test that launches a refused root from this checkout, so residual risk is a test that does so dynamically); macOS is unverified
  (`test_macos_*` paths and the A5-M lock are not exercised here).
- Windows full gate on `87dd2bf` (run `2026-11-22_092257_full_910a`, short-path clone, offline-built `.venv`): **FAIL/BLOCKED**, self-reviewed. Journeys 55 PASS +
  1 NOT APPLICABLE, guarded 457 + 75, coverage 273 of 273. Two environmental failures remain: the Kokoro tallest-notice case needs the real 327 MB Kokoro
  snapshot inside the checkout (links are refused); `test_qwen3_calm_harness` needs the Qwen3 engine and Base model (3.07 GB) and its skip is deliberately not
  excused. A third (the `files/dev-work/` colliding-basename skip) was excused by the exact rule `windows-dev-work-local-fixture-absent` (963f6fe) without a rerun.
  Closing it needs the owner to authorize the Kokoro/Qwen3 resources in a disposable clone, or a full run in a checkout with every engine.
- Visual baselines: none approved (`baselines/approved.json` is empty); candidates (87 Windows, 14 macOS) await the owner; the visual stage is NOT RUN; `release_ready` false.
- Known flakes (?): `test_cover_importing` processing_cancel (about 2 in 6), `test_m4b_retry` occurrence identity, one interrupted-run case in `test_verify_evidence`, one
  gate-contract test under load. Root-cause only if one recurs. Hazards: synthetic gate processes outlive pytest briefly; Qwen3 supervisor give-up race; the profiler
  `current_thread` pattern in `TkCallsFromWorkers`. Environment skips: Windows real-symlink WinError 1314; PowerShell may pick the WSL `bash.exe` (use Git Bash).
- macOS cannot run a canonical full gate (Windows-only tests fail instead of skipping; about 60 ids plus 17 errors); the Option A test-portability drop is owed; one Mac test
  leaks an eSpeak link into runtime data. These are not fixed.

**Shadow Slave / OmniVoice (fix `56c83cf`, 24-seed re-rendering)**
- PENDING owner listening: the four regenerated MP3s for chapters 72, 299, 338 and 490 at `files/dev-work/v082-fc/r1-failed4/mp3/` (PROTECTED, ignored; never
  open, move, regenerate or delete; placing them in the library is an owner action). NOT proven that every word is spoken (no offline ASR); not run on a Mac; the 900 s
  worker stall deadline was measured only on CUDA; the owner's working copy is on `0.8.1` and lacks the fix.
- Independent review of `56c83cf` NOT done (self-verified). Whether the run Summary line should name the retry cause is the owner's call (pinned contract).
- v0.8.1 C2 (80 Reverend Insanity chapters, OmniVoice Male 3, all PASS): PENDING owner listening for 103 voiced letterless chunks in 35 chapters and for high
  characters-per-second chunks; audio is private in the primary checkout's `files/dev-work/`. `vol-ren-zu/00-ri-intro-ren-zu.txt` (121 bytes) produced no output and no failure line:
  owner to confirm. The untracked failed-chapter logs in `files/plans/` (primary and here) must never be staged.
- Voices and engines (?): 28 previews published, six OmniVoice rows are placeholders, none authorized; redistribution authority for the 18 shipped reference WAVs is
  unaddressed (owner); Qwen3 temperature experiment is owner-gated and speed deferred; legacy `.venv-qwen3` retirement is the owner's; final-tail listening flags (Qwen3 Ryan,
  Qwen3 Male 2, three Edge tails) were never recorded done; Chatterbox `torch_cpu.dll` 0xC0000005 crash (once, 2026-08-17) never reproduced and not claimed fixed, and Chatterbox
  memory grows about 1.4 GB per voice in one process; two app copies can run Qwen3 and OmniVoice on one GPU together.

**v0.8.1 and earlier owner acceptance (v0.8.1 is PUBLISHED, on a maintainer exception: no passing final canonical Full gate)**
- Not qualified per the acceptance record: Windows owner-manual folder checks, conditional first-run visuals, a real symlink rejection on a privileged account, and every v0.8.0
  item not retested. No fresh install of the exact release on a fresh Windows PC or fresh Mac; native macOS checks unsigned: Preferences Reset Aqua outlined buttons, Finder panel
  at the remembered folder, Full Keyboard Access Tab traversal, Retina outline softness.
- Checkpoint A/B owner-manual GUI checks (6-step remembered dialog folders, Light/Dark outlined buttons, focus ring, Cleanup/Qwen3/Install dialogs in Dark) were never signed (?).
- Older owner gates never run (?): AUD-004 standard-user Windows, AUD-008 final release ZIP, AUD-009 unseeded Qwen3 network download, AUD-010 transitive revisions; v0.7.0
  clean PC, 125–200% scaling, long-paths-off drills; xHE-AAC/USAC on real media (Windows Media Foundation and macOS `aac_at`).

**macOS (PENDING; Apple Silicon qualification P7 for v0.8.2)**
- `ACT.SHARED.WORKSPACE-SCALING` and the `*.PREPARATION` features (TTS, Maker, Metadata, Cover) carry a macOS standing of pending (owner decision 2026-11-21); nothing measured on a Mac.
- v0.8.0 macOS release gates held by the owner were never recorded closed (?): a REAL CLEAN `fresh-macos` run on a real Apple Silicon Mac with 16 GB or more (D18), the canonical
  macOS full gate, the KX-10 Force Quit checklist, the OmniVoice preview deferral; the D16/D18 sign-off is not on record (D16 route C was overtaken: v0.8.1 shipped both ZIPs).
- Open acceptance (?): P2 (24 listening MP3s, Kokoro peak 7.29/6.0 GiB, OmniVoice 43 min at 10.94 GiB, 19 journey pictures), P5 closeout items, the Windows E-B2 Kokoro phoneme-parity
  run and the HOME-PC regression of macOS touchpoints (prepared, completion never seen); accepted debt: 20 P1B visual findings and OBS items, ACT72-080 native NSOpenPanel selection UNVERIFIED,
  D11b/ACT72-076 work-area recovery, D11c, MAC-042 name/icon, ACT72-077 wording, Edge voice Andrew sends no audio for some short clauses (upstream).
- Containment residuals (documented, not fixed): `setsid` escapees, a 0.2 s kill window, a POSIX grandchild of a normally exited worker, a hung filesystem call. Repository folders are
  created world-writable (777/666) on macOS: correction PENDING the owner, nothing changed. The Windows launcher's Smart App Control fix (`python.exe`, hidden hand-off) has no live
  first-run, repair or fresh-Windows qualification (?). Mac checkout hygiene in the primary clone (filemode, CRLF files, stale worktree records) is unverified from here.

**Windows environment and qualification**
- Qualified only on HOME-PC, Windows 11, 100% scaling: other scaling (the app is DPI-unaware by decision), Windows 10, other GPUs, a non-admin target (Phase 9 WAIVED, never passed) and a
  fresh VM are unproven. Smart App Control blocks unsigned natives (sklearn, FFmpeg WinError 4551, `pythonw.exe`); a fresh venv can pull unsigned transitive wheels; WinError 206 on deep paths;
  Qwen3 needs about 11 GB commit (see the headroom floor). The old worktree `wt082` has a 123-character root and no `.venv`; real-environment work runs in `C:\ACT-Dev` (10-character root).
- Owner-held cleanup (?): the Fresh-Install-Acceptance set, an 8.35 GB set-aside venv, drive-root `+97a/+57a`, `%TEMP%` `bfa7` and 31 `epub2tts_*` folders, ComDlg32 history values, `.act67` sets,
  `tree-phase12` (2.2 GB). Owner-held ACL-locked folders (D-3) and `C:\t\` scratch (D-2).
- The owner's uncommitted work in the primary checkout (tracked deletions of historical plans and release-history files, `.ai/`, `scripts/project-status.py`, local reports) must never be staged or touched.

**Scalability backlog (v0.8.2, Checkpoints 1–6: MP3 Tool, Maker/Editor, TTS naming and Start, Converter and Cover, imports; persistence withdrawn by the owner)**
- Checkpoints 1–6 are SELF-REVIEWED only (the Checkpoint 1 independent review's five findings were fixed in R1 and not re-reviewed independently; the 3dcaa43 fix has no independent review).
  The owner chooses controlled testing on a separate 0.8.2 copy (v0.8.1 is the rollback) or an independent review.
- Remaining Tk limits: Cover standard Start up to 143 ms at 5,000 images; Replace-originals validates sources on Tk (1.3 s at 5,000); Converter planning is not cancellable; readback about 30 ms
  per file; a blocking filesystem call in a preparation worker cannot be interrupted; four copies of the offer/adopt/withdraw preparation protocol are a deferred cleanup.
- Defects left for the owner: M4B Maker Build and Metadata Editor actions are not refused during a folder scan; a dangling Windows junction on a numbered name is planned then refused at publication;
  a cosmetic TTS Start log line and empty run folder; one unexplained early teardown error did not recur (?).

**Defects and known limits (owner-held; none blocks a release)**
- ACT72-030: eleven unreferenced helpers remain (removal deferred by the owner; six MP3 test modules pin them). ACT72-064: five PDF cleaning limits pinned by `test_limit_*` tests (accept or
  defer); ACT72-057 (PDF half) and ACT72-073 unclosed.
- Narration of about 24.85 hours or more cannot be encoded; a final heading with no text is not spoken; Edge has no run-level circuit breaker and a -58 dBFS trim can drop a quiet last sound;
  cancel and crash residues are as listed in `Briefing.md`; Kokoro `log=print` default on cp1252 consoles; M4B Metadata copies its input before the tag write (?); the M4B Converter residuals
  (non-idempotent `sanitize_component`, short-read timeline cases, multi-cover rule undecided) (?); release builder once overwrote `dist/` ZIPs without warning (?).
- Owner small calls (?): MP3 duration-fix Windows smoke; Save Tags confirmation on six books; whether human listening is wanted for M4B Maker/Editor; minor UI items accepted without a fix
  (density-switch shrink, 920x600 path clipping, launcher status wording).

**Further limits and old items not proven closed (?)** — kept so nothing is lost; each is small or low risk.
- Qualification gaps: Edge multi-file (v0.7.1) not exercised on a real second volume, exFAT or network drive, and no long real book end to end; local-engine concurrency research (v0.7.x Phase 9) never started;
  Qwen3 hardware figures come from one machine; Windows Phase 4/6A not verified in installed-optional-engine states or dialogs beyond Preferences; real-source M4B rows rest on synthetic proofs; the fresh one-click
  install was verified only in pieces and the Windows long-path switch-on was never tested on a machine where it was off; Chatterbox portability to another machine needs the owner's authorization; the new
  every-platform pins of the POSIX containment series have not been run on Windows; the macOS release-order plan (P6a freeze, P7a–d), the designed FAST-concat fallback to Safe and the Riedl FFmpeg pin (accepted for P1A, not for release) are unfinished.
- Cancel and crash residues: a killed process can leave `.work`; work-area recovery is Windows-only; the Edge CLI M4B route handles Ctrl+C only; a supervised-cancel close-window race and a Cancel that loses to the last commit
  are documented boundaries; a Windows venv killed in the ensurepip gap needs a shared fix the owner has not decided; a pre-P1A Mac `.venv` on Homebrew Python is not rebuilt automatically.
- Small items: the F1 Tk image-order fix is test-only (an app-side three-line rebuild was proposed, not made); the HEIC encode-unavailable path is covered only by injected seams; a rejected capture can consume one id; TXT input is UTF-8 only;
  first-run log wording blames Python 3.13 for a blocked DLL; the `.bat` can flash a cmd window; `SHA256SUMS` lists 0.6.6; numba writes about 40 cache files into site-packages on the first Chatterbox run; Kokoro has no cleanup lock;
  macOS 1024x800 Aqua is covered by automated evidence only; per-monitor DPI rendering is future work.

**Pronunciation (OPEN requirement, home: Decisions 2026-11-25)**
- The maintainer requires "Tay-mar" for the name Tamar; Chatterbox says it inconsistently. NOT solved, deliberately not a word rule: it needs a general, separately designed pronunciation-override
  facility (global and per-voice; override versus generation consistency kept apart). Related deferred text issues: Chatterbox URL misread, `12:30` mangled, `Apt.` treated as a sentence end,
  Male-1 rare 11.8 s silence and slower cadence.

**Documentation**
- Decisions.md ordering is broken in two places (documented in its index; no entry moved). DOC-1 (approved, Phase 2): classified archival of Decisions and Changelog into
  per-era tracked documents under `files/documentation-history/{decisions,changelog}/`, keeping five permanent documents, indexes and links; nothing archived yet.

## Pending Owner Decisions

- **Approved (Phase 1A-1, plan Revision 5, 2026-11-25):** A5-W (Windows machine-wide lock, control directory in `C:\ACT-Dev`, fail closed, no checkout-local fallback), A5-M (macOS shared machine-common location only after native proof and approval; macOS heavyweight blocked until then), A6-R (single-attempt authorization), ENTRY (entrypoint classification), the 1A-1/1A-2/1A-3 split. None of the lock or authorization machinery is implemented yet (1A-2).
- **Approved (Pre-Phase 1A, 2026-11-25):** D-1 the permanent development clone `C:\ACT-Dev` (done); A5 machine-wide lock and A6 scoped authorization records in principle (designed in the Phase 1A spike, not implemented); DOC-1 historical archival in Phase 2; fixed requirement: the main application environment is always `.venv/` directly inside the ACT application root (Phase 3 A1 concerns independent engine environments only).
- **D-2** external scratch under `C:\t\` (about 14.5 GB) — by Phase 2. **D-3** ACL-locked folders (owner-run `takeown`/`icacls` or leave) — by Phase 2. **D-4** adopt the owner's uncommitted plan and release-history archiving on `0.8.2` or keep them tracked — by Phase 2 (D17 is now in Decisions).
- **D-6** Windows PowerShell-blocked fallback (`curl.exe`/`tar.exe` with hashes, recommended, or drop it) — by Phase 4. **D-8** disk cost versus offline repair depth (the A4 retention proposal) — at the Phase 3 report.
- Resolved: D-5 (AI Workspace is local-only), D-7 (v0.8.1 published 2026-11-21T05:45:50Z, both assets).
- Also awaiting the owner: controlled testing versus independent review of Checkpoints 1–6; supplying the canonical `AI-WORKSPACE.md`; the macOS permissions correction; ACT72-030 and ACT72-064; M4B scan-refusal and junction handling.

## Development Checkout and Evidence Locations

- **Development checkout (D-1):** `C:\ACT-Dev`, a separate clone on `0.8.2` (upstream `origin/0.8.2`) with its own real root `.venv/` (CPython 3.12.15, python-build-standalone 20261009, 172 distributions
  from the hash-locked store), the local-only `AGENTS.md` and `CLAUDE.md`, and the reused interpreter, wheel store, NLTK and spaCy data in `files/runtime-data/`. Run the gate with
  `.venv\Scripts\python.exe files\dev-work\verification-gate\verify.py`. Disk: about 3.1 GB (`.venv` 2.4 GB; `files/runtime-data` 0.66 GB: interpreter 146 MB, wheel store 504 MB). Never hard-coded in application code or user documentation.
- **Preserved, not used for runs:** the owner's primary checkout (`0.8.1`) and the old worktree `files/dev-work/wt082` inside it. Protected evidence stays in the old worktree under these relative paths
  (they do NOT exist in `C:\ACT-Dev`): regenerated Shadow Slave MP3s `files/dev-work/v082-fc/r1-failed4/mp3/` (never open, move, regenerate or delete); checkpoint and qualification evidence
  `files/dev-work/v0.8.2-cp1-evidence` to `cp6-evidence` and `v0.8.2-qual-evidence`; earlier gate runs `files/dev-work/verification-gate/outputs/`; the Phase 0A review bundle `files/run-temp/p0a-review/`; the Phase 0B ledgers
  and reconciliation `files/run-temp/p0b/`. Prefix them with `<primary checkout>\files\dev-work\wt082\`. Gate runs in `C:\ACT-Dev` write to its own `files/dev-work/verification-gate/outputs/`.
- Abandoned gate scratch under `%TEMP%\act-gate` from earlier full runs (runs 2cf1, 52ac, 910a, d0db; `--audit-scratch` reports about 31.6 GiB, hard links may be double-counted) is untouched: owner decision D-2 / Phase 2.
- Phase 1A-1 R1: the owner removed the three scratch folders left outside containment (`C:\t\p1a1` and `%TEMP%\act-gate\fd57`, `f2c1`); R1 created no
  external scratch (direct runs used short basetemps under `files/run-temp/`, removed). Free space on C: was about 7 GiB during R1: below the comfort
  margin for a full run; check it before any expensive run.
- Historical (Phase 1A-1, superseded by the owner's cleanup above): Phase 1A-1 left two folders of its own that it was not permitted to delete: `%TEMP%\act-gate\fd57` (1.06 GiB, the retained scratch of its failed iteration run `2026-11-25_192340_focused_5fd4`; `--audit-scratch` reports it abandoned and owned by that run) and `C:\t\p1a1` (about 0.46 GB of direct-run basetemps). Both are disposable; the owner may remove them. Free space on C: was about 6 GiB at the end of Phase 1A-1: check it before any expensive run.

## Verification and Evidence

- **Phase 1A-1 R1 (this checkpoint, agent-reported, not independent).** Original verdict: Phase 1A-1 FAIL at independent review (eleven findings). Regression
  controls fail on 8d7226d and pass on R1: `files/run-temp/r1_repro.py`-style reproduction (local, not committed) 20/20 RED-to-GREEN across H1, H2, H3 and M2;
  the fork-side controls (`test_r1_*` in `test_execution_plan.py` and the gate contract) red first (44 direct, 6 Git through the gate), then green; the envelope
  collateral (launcher sandboxes, packaging syntax check) red in a diagnostic sweep, then green. Focused gate runs on the frozen R1 tree: `2026-11-25_231539_focused_b69f`
  (896 passed, 0 skipped, 18 modules); `2026-11-25_230754_focused_595d` (449 passed, 0 skipped: 170 routine contract functions and the evidence module); guarded `2026-11-25_231843_focused_d8c3` (v3-planning and v3-supervisor through `guarded_pytest.py`: membership, process-spec identity,
  lifetime report with `routine_accounting` bootstrap `guarded-pytest`, ledger PASS, no refusals, no surviving child). Each PASS with `routine-effects`,
  `requested-scope` and `tree` PASS, all on one tree (`f2af75a3…`). Superseded iteration: `2026-11-25_225748_focused_f267` FAIL (two test-design defects
  in the new gate-contract controls, then fixed: a wrapper process can never satisfy the gate's direct-child session identity, so the M2 ledger damage now
  happens at `check_routine_effects`; the sealed-BLOCKED qualification test now adopts the real runner's expected `scaling` refusal). Mutation check: the
  8d7226d rule "skip a missing stage ledger" restored in `verify.py` was CAUGHT by the M2 `delete-ledger` case and the file restored byte for byte.
  NOT RUN by design: full, changed execution, qualification, focused `--feature`, journeys, real engines, installs,
  downloads, benchmarks, release builds. Historical evidence limits: the Phase 1A-1 runs below were produced by the defective envelope and prove nothing
  about the R1 contracts.

- **Phase 1A-1 (this checkpoint, agent-reported, not independent).** In `C:\ACT-Dev`, on the final candidate tree (gate tree digest `72ec515f…`; the commit adds only this
  Handoff update on top of it), three focused gate runs, each PASS with `routine-effects` PASS (no heavyweight effect refused in any stage), `tree` unchanged and
  `--status --require-current` PASS: (1) the Pre-1A baseline command, `--test files/tests/test_verification_gate_contract.py --test files/tests/test_verify_evidence.py`:
  442 passed (314 gate-contract, 115 evidence, 13 source-boundary), 0 failed, 0 skipped, pytest 339.02 s, 371.1 s total, run `2026-11-25_194632_focused_4cc8`
  (the historical Pre-1A baseline on a86538b stays 411 passed, 0 failed, 0 skipped, pytest 353.453 s, 384.922 s total, run `2026-11-25_163611_focused_8f89`; the
  architecture spike inspected it and did not rerun it); (2) the gate self-tests and the new modules (`test_execution_plan` 78, `test_routine_effects` 61,
  `test_native_acceptance`, `test_verification_coverage`, `test_dev_work_isolation`, `test_repository_contract`, `test_suite_isolation`,
  `test_macos_p1b_closeout_gate`, `test_gate_scratch_exception`, `test_verify_guarded`, `test_surface_discovery`, `test_real_media_acceptance`): 529 passed,
  3 policy-named skips, pytest 43.15 s, 57.6 s total, run `2026-11-25_195248_focused_27c4`; (3) the declared and mixed modules and the harness consumers
  (`test_omnivoice_phase1`, `test_root_lifetime`, `test_first_run_setup_ownership`, `test_plan3_boundaries`, `test_plan6_boundaries`, `test_job_ui`,
  `test_book_workspace_ui`, `test_m4b_metadata_editor_ui`, `test_dialog_containment`, `test_cancel_semantics`; the plan withheld four declared nodes as
  qualification obligations): 1,067 passed, 19 policy-named skips (POSIX-only), pytest 68.71 s, 76.7 s total, run `2026-11-25_194511_focused_9557`.
  Iteration runs on earlier trees, superseded: `2026-11-25_192340_focused_5fd4` FAIL (two defects then fixed: plan admission now follows preflight; a synthetic
  in-process test of the real gate stands the new guard in explicitly; its tree also changed under it because documents were edited during the run),
  `2026-11-25_193515_focused_6472` and `2026-11-25_194146_focused_7304` PASS, `2026-11-25_194250_focused_7655` FAIL (the envelope refused the containment
  adapter's read-only `--probe`, started by `test_dialog_containment.py`'s negative control; the entrypoint row now allows exactly `--probe` as data-only).
  Mutation checks, each CAUGHT by its targeted tests after a passing no-change control (22 passed) and restored byte for byte: the audit hook not installed, the
  boundary's partition rule disabled, an unrouted path widened to every test, a swallowed refusal not counted, the untracked stream dropped, an opt-in not
  scrubbed, a declared node not withheld. `--plan` resolved every mode against the real tree. NOT RUN by design: full; execution of quick, changed, regression,
  focused `--feature` and qualification `--journey` (plan only); qualification; journeys; real engines; installs; downloads; benchmarks; distribution builds; the
  whole ordinary suite.
- **Pre-Phase 1A (this checkpoint, agent-reported, not independent).** In `C:\ACT-Dev`: `bootstrap.py --headless` offline in 86 s (172 distributions, Tk 8.6.15, no link); `verify.py --mode focused --test
  files/tests/test_verification_gate_contract.py --test files/tests/test_verify_evidence.py`: preflight PASS (policy, identity, guarded specification, interpreter, process ownership, error mode), collection PASS, execution PASS:
  411 collected and passed (299 gate-contract, 99 evidence, 13 source-boundary), 0 failed, 0 skipped, no native journey, no guarded test, 353 s, one `audioop` DeprecationWarning from pydub; `--status --require-current` PASS.
  NOT RUN by design: full, changed, qualification, journey, real engine, install, benchmark. Evidence `files/dev-work/verification-gate/outputs/2026-11-25_163611_focused_8f89` (ignored).
- **Phase 0B (agent-reported).** Read-only extraction by eleven subagents plus one reconciler into a local preservation ledger (761 items, reconciled to 131; 57 OPEN, 24 OPEN-UNCERTAIN kept, 15 resolved with
  cited evidence, 4 superseded, 31 historical with a live home) and checked against the rewritten documents; documentation checks (five-document contract, `check_docs`, paths, release status, privacy, the recovery reference returning the four originals byte-for-byte, snapshot
  parse by the owner's `project-status.py` read-only); direct focused pytest of the documentation-content tests: 520 passed, 0 failed, 0 skipped; mutation checks of the retargeted Tay-mar pin with a control.
  NOT RUN by design: any `verify.py` mode, full, changed, qualification, journey, real engine, install, benchmark.
- **Last full Windows gate:** `87dd2bf`, FAIL/BLOCKED (above). v0.8.0 gate `c8e8` stays FAIL (owner exception); v0.8.1's `2cf1` on `00ae625` FAIL with 56/56 journeys passing; neither describes the current tree.
- **Evidence roots (ignored, local):** `files/dev-work/v082-fc/`, `v0.8.2-cp1..cp6-evidence/`, `v0.8.2-qual-evidence/`, `verification-gate/outputs/` (the old worktree `wt082`); macOS and v0.8.1 roots (`macos-*`, `v0.8.1-*`) exist only in the primary checkout.
  Release records: `files/release-history/` (v0.8.1 acceptance record, v0.8.0 records). The local review bundle and reconciliation ledger: `files/run-temp/p0b/` (never committed).

## Recent Checkpoints (newest first; cite by `git log`, not by tip)

- Phase 1A-1 R1 — the independent review FAIL remediated (H1-H4, M1-M3, C1-C4), plan amendment R1 (this commit).
- 8d7226d Phase 1A-1 — explicit execution plans, Git changed selection, routine capability classification and envelope, plan Revision 5 (FAILED independent review).
- 28d8c7b Pre-Phase 1A — permanent checkout `C:\ACT-Dev`, local-only workspace files, base environment, outstanding Phase 0A baseline PASS, owner decisions recorded.
- a86538b Phase 0B — Handoff/Briefing compaction, Decisions and Changelog indexes, v0.8.1 release status corrected.
- 8546200 Phase 0A: five-document contract, plan moved to `files/plans/`, local-only workspace, interim verification rule. 3546a4f plan readiness review.
- 56c83cf OmniVoice silent chunk re-rendered with derived seeds (Shadow Slave chapters 72, 299, 338, 490).
- 963f6fe Windows skip-policy rule; 3938a40 and 87dd2bf Windows full-gate closeout and test corrections; b87a36f and 3dcaa43 Windows qualification (Import Folder edit-loss guard).
- 5da1271 CP6 imports off Tk; 1d47024 CP5 Converter index and Cover Start; fee286f CP4 TTS Start; de62430 CP3 collision search; 4465b94 CP2 Maker/Editor preparation; ffd1621 and b1fbb49 CP1 MP3 Tool and review fixes.
- v0.8.1 (tag `v0.8.1` = `6a7be75` on `master`, published 2026-11-21T05:45:50Z): Windows and macOS ZIPs; see the acceptance record.

## Historical Reference

Everything older than the list above (v0.5.0 to v0.8.1 phase logs, macOS P1–P5 blocks, Plan 4 Chatterbox, v0.7.2 hardening) is in `git show 85462005bc203e6b33fd975e2709fe3d9014b7b3:md-instructions/Handoff.md`;
the durable parts are in `Decisions.md` (index), `Changelog.md` (index) and `Briefing.md`. Release qualification: `files/release-history/`. Plan: `files/plans/Developer-Experience-Upgrade.md`.
