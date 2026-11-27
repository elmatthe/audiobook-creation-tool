# Audiobook Creation Tool — Handoff

Current state only. Earlier text: this file was compacted in v0.8.2 Phase 0B from 27,317 lines; the full previous Handoff is
`git show 85462005bc203e6b33fd975e2709fe3d9014b7b3:md-instructions/Handoff.md` (the same path in `Briefing.md`). Architecture and limits: `Briefing.md`;
why: `Decisions.md` index; what shipped: `Changelog.md` index.

## Execution Snapshot

- **Date:** 2026-11-27
- **Last agent:** Claude Code (Opus 5.5), v0.8.2 Phase 3B native macOS uv feasibility
- **Machine:** HOME-MacOS (Apple Silicon, macOS 27.0.1)
- **Branch:** `0.8.2` (long-running, from published v0.8.1). On HOME-MacOS the owner's primary checkout was fast-forwarded from `0.8.1` to `0.8.2` (`c988bd3`) with its uncommitted owner work carried unchanged (tracked deletions of historical plans and release-history files, `files/plans/archived-plans/`, `files/run-temp/`, `scripts/project-status.py`, the HOME-PC cleanup note); its real root `.venv/` (built on 0.8.1; the locks are unchanged) runs the gate. Windows work stays in `C:\ACT-Dev` (D-1)
- **Status:** Phase 3B COMMITTED on `0.8.2` (agent-verified, not independently reviewed): native macOS uv feasibility PASS; the owner's approvals of the Phase 3A proposals recorded (plan Revision 7, Decisions 2026-11-27 Phase 3B). Report `files/plans/ACT-v0.8.2-Phase3B-macOS-uv-Feasibility.md`; pin `files/plans/phase3a-uv-examples/python-downloads-macos.json`. Docs and examples only: no production, setup, environment, gate or application change (VERSION stays 0.8.1)
- **Active plan:** `files/plans/Developer-Experience-Upgrade.md` (Revision 7)
- **Current phase:** Phase 3 complete (3A Windows, 3B macOS); **next is Phase 4, production uv-based provisioning**
- **Recommended next execution tier:** Phase 4 on its own prompt; open it with the gate's D1 correction (Phase 3B report §7) and the D-6 decision
- **Last verification:** v0.8.2 Phase 3B on HOME-MacOS, agent-run, not independent (details under Verification and Evidence). The last full gate, on 87dd2bf (2026-11-22), is FAIL/BLOCKED and does not describe this candidate
- **Manual gate:** D-6 (Windows PowerShell-blocked fallback) before Phase 4; optional macOS OmniVoice cache retention (Phase 3B report §12); owner listening to four regenerated Shadow Slave MP3s; owner decisions D-2 to D-4 and the `files/run-temp/` ignore recommendation; plus the owner-acceptance items below
- **Relevant evidence:** HOME-MacOS gate runs `2026-11-27_153023_quick_8383`, `…_153203_focused_0c84` (FAIL, D1/D2), `…_153708_focused_d42d` (PASS) in the primary checkout's ignored `files/dev-work/verification-gate/outputs/`; prototypes in its ignored `files/dev-work/uv-3b/`; Windows runs in `C:\ACT-Dev\files\dev-work\verification-gate\outputs\`; `files/release-history/ACT-v0.8.1-Windows-MacOS-Release-Acceptance.md`
- **Next exact action:** Phase 4 (base bootstrap and locked application provisioning through uv) on its own prompt, implementing the carried requirements in the Phase 3B report §11; correct gate defect D1 first; the owner decides D-6. Open obligations: Windows OmniVoice uv installation proof (Phase 5B), the Qwen3 installed-library proof (owner-deferred). The interim heavyweight rule (GATE.md) stays in force. Do not merge, tag or release

## In Progress

**Phase 3B (native macOS uv feasibility) is committed on `0.8.2`** (agent-verified, not independently reviewed). Nothing is in progress.
Approved by the owner and recorded: uv 0.13.10; A2 exact pinned CPython 3.12.15 + PBS 20261009 through ACT-owned download metadata; A1
independent sibling engine environments `ACT_ROOT/.venv-engines/<engine>/` (base fixed at `ACT_ROOT/.venv/`; the engine part of the
2026-11-13 layout superseded); A4/D-8 Windows `copy`, macOS `clone` (proved), base repair cache retained, no Qwen3/OmniVoice package cache
by default; bytecode at install; the Windows OmniVoice installation proof in 5B. Phase 3B results: uv notarized and quarantine-safe;
interpreter identical except uv's two macOS install-time patches; parity base 169/169, OmniVoice 86/86, Kokoro 97/97 + spaCy model, all
installed and import-proved with MPS; clone 0.56 s / 18 MiB with isolated damage and 0.10 s offline repair; siblings survive base
recreation; relocation offline. Native gate: PASS except D1 (Darwin `killpg` EPERM in `helpers/winproc.py`, smallest correction in the
report) and D2 (a Windows-only scenario test, test portability). Raw artifacts (uv, PBS archive, locks, base cache, managed Python, logs,
about 1.4 GiB) stay in HOME-MacOS's ignored `files/dev-work/uv-3b/`; Windows' stay in `C:\ACT-Dev\files\dev-work\uv-3a\`.

## Open Issues and Blockers

Status words: **FAIL**, **BLOCKED** (could not run), **NOT RUN**, **PENDING** (owner), **UNVERIFIED**. Agent-reported verification is not independent
review. Items marked (?) could not be proven closed from the record and are kept on purpose.

**Phase 0A carry-forward and workspace**
- RESOLVED (Pre-Phase 1A): the tree-building tests of `test_verification_gate_contract.py` (including the edited `docnames` fixture) and the rest of
  `test_verify_evidence.py` ran through the gate in `C:\ACT-Dev`: preflight PASS, 411 passed, 0 skipped (details under Verification and Evidence).
- AI Workspace alignment DONE locally (2026-11-26, local-only, never staged): the owner's 2026-11-04 workspace snapshot is installed unchanged in `C:\ACT-Dev` (`AI-WORKSPACE.md` and the seven `.ai/` guides; its master and template `AI-WORKSPACE.md` are identical; no install
  record). The ACT-specific `AGENTS.md` keeps every ACT rule and gains an override section for the shared text's conflicts: `main` (ACT uses `master`), tracked `AGENTS.md`/`.ai/ENVIRONMENT.md` (D-5 keeps them local), plans in `md-instructions/`
  (ACT: `files/plans/`), the `src/`/`tests/` layout and `unittest` (ACT: `scripts/`, `files/tests/`, pytest directly or through the gate), the "legacy" template gate (ACT's `GATE.md` is authoritative), commit-and-push autonomy, scratch
  locations. Thin `CLAUDE.md` imports `AGENTS.md` and `AI-WORKSPACE.md`; `.ai/ENVIRONMENT.local.md` holds machine facts. Not adopted: the template `.claude/settings.json` (its `git add`/`git commit` allow rules conflict with reviewed staging), the scaffolder, installer,
  `Replace_AI-WORKSPACE.bat`, launchers and the template gate. Open: the shared text assumes `files/run-temp/` is gitignored; in ACT it is untracked and unignored (below; a tracked `.gitignore` correction is the owner's call).
- The primary checkout's `.claude/CLAUDE.md` is stale (retired gate path `scripts/verify.py`, old document spellings, a `files/dev/qwen_worker.py` delegation rule
  although `files/dev/` does not exist, `scripts/Universal`) and Claude Code loads it as a parent-directory file in sessions started below the primary checkout (`wt082`).
  `C:\ACT-Dev` has no competing parent instruction file (its parent is the drive root); the stale file remains for the owner to retire or replace and was not modified.
  A sanitized review bundle of the Phase 0A files is local-only under the old worktree's `files/run-temp/`.
- Phase 0B review corrections (recorded in Pre-Phase 1A): the Decisions index is a navigation aid and never supersedes an unlisted decision; outstanding historical defects are
  reassessed for release relevance at the final independent review; `files/run-temp/` is untracked AND unignored (owner decision), so a careless `git add` stages review bundles
  and ledgers: Phase 2 recommends ignoring it with one `.gitignore` line (owner's call; unchanged).
- Owner-local tooling stale (?): `scripts/project-status.py` (untracked, primary checkout) also reads `files/runtime/verify-state.json`, which the gate no
  longer writes; `files/dev-work/local-model-worker.py` and `capability-discovery.py` are absent (not adopted). `scripts/requirements.txt` line ~106 still names the
  retired `scripts/verify.py` (its bytes are hashed into the locks; leave until a lock regeneration).

**Verification and gate**
- Verification simplification (2026-11-27, agent-verified, NOT independent): the gate is accident prevention for trusted tests and cooperating agents,
  not a sandbox. Not covered by design: a test that gives a child a replacement environment without the marker, native code, a shell program's internals.
  A changed plan touching suite-wide test infrastructure is INCOMPLETE by design (named focused runs or a component regression owed). Native macOS
  verification of the simplified routine path DONE in Phase 3B: marker inheritance, stall/timeout supervision, canonical routing and stage/JUnit
  reporting PASS; FAIL on one native gate defect, D1 (Darwin answers `killpg` with EPERM for an exiting group: `helpers/winproc.py` then reports a
  false survivor or raises; smallest correction in the Phase 3B report §7, owed before Phase 4 relies on macOS gate cleanup), plus D2 (one
  exit-code contract test assumes the Windows-only `m4b-scaling` scenario; test portability) and D3 (`helpers/scratch.py` has no POSIX process
  creation time, so `--audit-scratch` on macOS calls an active run's scratch abandoned; read-only, low severity). The Qwen3 installed-library proof stays an owner-deferred environment obligation.
- Interim rule (GATE.md, in force): no `--mode full` or `--mode qualification --scenario`, no journey, real engine, install, download, benchmark or
  release build without the owner's authorization for that run. quick, focused, changed and regression execute; `qualification --journey` is plan only.
  Guarded groups run only through the gate. The reduced Phase 1A-2 (one owner-supervised attempt, an OS lock across checkouts, manual recovery) is built
  only when a heavyweight run needs it; an owner-authorized Windows full run cannot PASS before then (its ordinary stage refuses the declared heavyweight
  nodes of the release partition).
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
- DOC-1 DONE (Phase 2): Decisions entries before 2026-11-13 and Changelog sections from `[0.7.3]` down are in
  `files/documentation-history/{decisions,changelog}/`, unchanged; the Decisions ordering breaks now sit in the archive files. Kept on purpose:
  13 dev-tools the entrypoint table still calls obsolete (a maintained tool or a production-path test imports them), the P05B Stage 4B-2,
  4B-3A and 4B-3B plans (contracts linked from `scripts/shared/README.md` and `scripts/tts/README.md`), the v0.7.2 Phase 7A plan (the
  m4b-scaling qualification record), the v0.8.0 and v0.8.1 plans, the spike verdict and all of `files/release-history/`.

## Pending Owner Decisions

- **Approved (Phase 1A-1, plan Revision 5, 2026-11-25; reduced by Revision 6, 2026-11-27):** A5-W, A5-M and A6-R stay approved in principle but are implemented only to the reduced 1A-2 extent (one owner-supervised attempt, an OS lock across checkouts, manual recovery), when a heavyweight run first needs it; ENTRY (entrypoint classification) is in force. Nothing of the lock or authorization is implemented yet.
- **Approved (Pre-Phase 1A, 2026-11-25):** D-1 the permanent development clone `C:\ACT-Dev` (done); A5 machine-wide lock and A6 scoped authorization records in principle (designed in the Phase 1A spike, not implemented); DOC-1 historical archival in Phase 2; fixed requirement: the main application environment is always `.venv/` directly inside the ACT application root (Phase 3 A1 concerns independent engine environments only).
- **D-2** `C:\t\`, inventoried read-only in Phase 2, about 24.5 GB: `q82bt` 10 GB (2026-11-22 full-gate closeout scratch: basetemps `t1`-`t3`, logs, document blobs), `f1` 6.2 GB, `d4` 4.4 GB, `a82` 3.8 GB (a detached clone at 963f6fe with uncommitted OmniVoice changes: compare with 56c83cf before calling it disposable), `fc` 57 MB, `d1`-`d3` 15 MB, `pytest-of-<user>` 0.5 MB, `guardian.bak`, `tmp4b9_jwk3`, empty `act-tts`; nothing removed. **D-3** at least 486 unreadable directories (to depth 4) under the primary checkout's `files/dev-work/p05b-stage4*` (346 in `p05b-stage4c`), `v0.8.1-independent-codex`, `act080-independent-feca89f-20261114` and several `files/run-temp/` review folders; untouched, no `takeown`/`icacls`. **D-4** the primary checkout (`0.8.1` at f7a0b51) still holds the owner's uncommitted work: 12 plan deletions (Phase 2 removed 8 of them on `0.8.2`, each byte-identical to the owner's local copy; Stage 4B-2/4B-3A/4B-3B stay as linked contracts, Phase 7A as a qualification record), 5 release-history deletions with no local copy (kept tracked on `0.8.2`), a `.gitignore` edit dropping the `files/livid-lady-test-files/` rule, and untracked `.ai/`, `files/plans/archived-plans/`, two failed-chapter logs, `files/release-history/ACT-v0.8.0-HOME-PC-Cleanup.md`, `files/run-temp/` and `scripts/project-status.py`; nothing adopted or overwritten. **`files/run-temp/`**: recommend one `.gitignore` line (owner).
- **APPROVED (2026-11-27, recorded in Phase 3B; plan Revision 7):** the Phase 3A proposals: uv 0.13.10; A2 exact pinned build through ACT-owned metadata; A1 siblings `ACT_ROOT/.venv-engines/<engine>/` (supersedes the engine part of the 2026-11-13 layout); A4/D-8 Windows `copy`, base repair cache kept, no Qwen3/OmniVoice package cache by default, macOS `clone` (proved in 3B); bytecode at install; Windows OmniVoice installation proof in 5B; 3B before Phase 4 (done).
- **Optional, new (Phase 3B report §12):** retain an OmniVoice package cache on macOS, where clone makes it cheap and gives offline OmniVoice repair (default stays `--no-cache`).
- **D-6** Windows PowerShell-blocked fallback (`curl.exe`/`tar.exe` with hashes, recommended, or drop it) — by Phase 4. Phase 3A used the built-in `tar.exe` to extract the uv ZIP.
- Resolved: D-5 (AI Workspace is local-only), D-7 (v0.8.1 published 2026-11-21T05:45:50Z, both assets).
- Also awaiting the owner: controlled testing versus independent review of Checkpoints 1–6; supplying the canonical `AI-WORKSPACE.md`; the macOS permissions correction; ACT72-030 and ACT72-064; M4B scan-refusal and junction handling.

## Development Checkout and Evidence Locations

- **Development checkout (D-1):** `C:\ACT-Dev`, a separate clone on `0.8.2` (upstream `origin/0.8.2`) with its own real root `.venv/` (CPython 3.12.15, python-build-standalone 20261009, 172 distributions
  from the hash-locked store), the local-only `AGENTS.md` and `CLAUDE.md`, and the reused interpreter, wheel store, NLTK and spaCy data in `files/runtime-data/`. Run the gate with
  `.venv\Scripts\python.exe files\dev-work\verification-gate\verify.py`. Disk: about 3.1 GB (`.venv` 2.4 GB; `files/runtime-data` 0.66 GB: interpreter 146 MB, wheel store 504 MB). Never hard-coded in application code or user documentation.
- **Phase 3A prototypes (ignored, local):** `C:\ACT-Dev\files\dev-work\uv-3a\` holds the verified uv 0.13.10 binary and ZIP, the PBS 20261009 archive (`dl/pbs/`), the five prototype projects with their `uv.lock` files (`proj/`), the managed Python, the shared uv cache, the snapshot and comparison tools (`tools/`), logs and before/after snapshots. Nothing outside it was created; no production path depends on it.
- **Preserved, not used for runs:** the owner's primary checkout (`0.8.1`) and the old worktree `files/dev-work/wt082` inside it. Protected evidence stays in the old worktree under these relative paths
  (they do NOT exist in `C:\ACT-Dev`): regenerated Shadow Slave MP3s `files/dev-work/v082-fc/r1-failed4/mp3/` (never open, move, regenerate or delete); checkpoint and qualification evidence
  `files/dev-work/v0.8.2-cp1-evidence` to `cp6-evidence` and `v0.8.2-qual-evidence`; earlier gate runs `files/dev-work/verification-gate/outputs/`; the Phase 0A review bundle `files/run-temp/p0a-review/`; the Phase 0B ledgers
  and reconciliation `files/run-temp/p0b/`. Prefix them with `<primary checkout>\files\dev-work\wt082\`. Gate runs in `C:\ACT-Dev` write to its own `files/dev-work/verification-gate/outputs/`.
- `%TEMP%\act-gate` (Phase 2 `--audit-scratch`, read-only): the earlier 31.6 GiB is gone; two abandoned folders remain, `6dc8` (run d0db) and `b18e` (run 04a6), about 0 MiB each, left as found. `C:\ACT-Dev` local evidence after Phase 2: gate `outputs/` 311 MB, guarded basetemps `files/dev-work/p05b-stage4c/` 646 MB (R2-campaign era), `files/run-temp/` 17 MB: within GATE.md's 2 GiB soft budget, kept.
- Phase 1A-1 R1: the owner removed the three scratch folders left outside containment (`C:\t\p1a1` and `%TEMP%\act-gate\fd57`, `f2c1`); R1 created no
  external scratch (direct runs used short basetemps under `files/run-temp/`, removed). Free space on C: was about 7 GiB during R1: below the comfort
  margin for a full run; check it before any expensive run.
- Historical (Phase 1A-1, superseded by the owner's cleanup above): Phase 1A-1 left two folders of its own that it was not permitted to delete: `%TEMP%\act-gate\fd57` (1.06 GiB, the retained scratch of its failed iteration run `2026-11-25_192340_focused_5fd4`; `--audit-scratch` reports it abandoned and owned by that run) and `C:\t\p1a1` (about 0.46 GB of direct-run basetemps). Both are disposable; the owner may remove them. Free space on C: was about 6 GiB at the end of Phase 1A-1: check it before any expensive run.

## Verification and Evidence

- **Phase 3B (this checkpoint, HOME-MacOS, agent-reported, not independent).** Prototypes in the primary checkout's ignored `files/dev-work/uv-3b/` (report sections 1-8 give commands, timings and results): uv 0.13.10 digest verified three ways, signature and notarization, a controlled quarantine fixture (uv runs; a quarantined interpreter hangs under Gatekeeper); the ACT-owned interpreter pin installed, compared file by file, Aqua Tk 9.0.4 window (auto-closed, 1.84 s), ssl, venv, offline restore; three parity locks compared artifact by artifact with a negative control; base, OmniVoice and Kokoro installed and import-proved (MPS available); clone/copy/hardlink timings, physical disk, damage isolation, offline repair, an interrupted clone sync; A1 recreation with an engine running; move and copy relocation, permissions, case, path depth. Before/after snapshots: 14 of 14 protected locations unchanged (root `.venv` with its nested OmniVoice engine, `files/runtime-data/python`, the wheel store, every default uv location, Homebrew and `/usr/local/bin`, shell startup files). Downloads about 0.7 GiB; free space never below 510 GiB. Gate on HOME-MacOS (candidate `c988bd3` + the owner's uncommitted work): `2026-11-27_153023_quick_8383` quick PASS (8 s); `2026-11-27_153203_focused_0c84` FAIL (10 selectors: 29 passed, 10 failed = D1 and D2; reporting accurate, cleanup PASS); `2026-11-27_153708_focused_d42d` PASS (8 selectors, 29 passed, requested scope 8/8); `--plan` checks of canonical and case-varied selectors; direct single-test reproductions and an isolated `run_supervised` errno trace for D1. Closeout on the doc changes: `2026-11-27_154508_quick_ef85` quick PASS; `2026-11-27_154517_focused_8785` FAIL only on D3 (11 modules, 652 passed, 10 policy-named skips, 1 failed: `helpers/scratch.py` cannot prove a POSIX owner alive, so `--audit-scratch` calls an active macOS run's scratch abandoned; read-only, low severity); the ~170 gate-contract nodes `--mode changed` would also route are NOT RUN on this Mac (owed to the next Windows `changed` run). Routine verification about 4.5 minutes. NOT RUN by design: full, qualification, journeys, the suite, model loads, synthesis, an app launch on a uv environment, production setup or repair.
- **Phase 3A (c988bd3, agent-reported, not independent).** Prototype experiments on HOME-PC in `files/dev-work/uv-3a/` (report sections 1-9 give the commands, timings and results): uv 0.13.10 digest verified three ways; managed CPython install, byte comparison, ssl, venv, one native Tk window (auto-closed, 1.56 s), offline restores and two corrupt-archive refusals; five parity locks compared artifact by artifact; base installed cold (62 s) and warm (copy 14.8 s, hardlink 2.8 s) with an import smoke under SAC; Qwen3 installed (268 s, CUDA 12.8 visible, RECORD hashes clean); A1 recreation, foreign-folder, mistargeting and running-worker cases on small disposable projects; copy and hardlink damage and repair, an interrupted sync and its RECORD-based recovery; MOTW-tagged extraction under SAC (zero Code Integrity events); move and copy relocation. Before/after snapshots: the root `.venv`, `files/runtime-data`, the primary checkout's `.venv` (engines included), both interpreters, the wheel store, four registry keys and every default uv user location unchanged (23 of 23 items). Downloads about 3.5 GiB; free space never below 20 GB. Gate in `C:\ACT-Dev`: `2026-11-27_134452_quick_3c06` quick PASS (12 s); `2026-11-27_134554_changed_c4e7` changed PASS (44 s: the five modules routed from the Decisions change, 571 passed, 0 skipped, plus docnames, docs and doc-links); `2026-11-27_134641_quick_3139` quick PASS. Gate time about 1.5 minutes in total. NOT RUN by design: full, qualification, journeys, any test suite, real synthesis or model loads, OmniVoice installation, long paths off, production setup or repair.
- **Phase 2 (this checkpoint, agent-reported, not independent).** In `C:\ACT-Dev` on HEAD `dabb02d` plus the Phase 2 changes: `2026-11-27_121656_quick_d94d` quick PASS (12 s) after the removals and archival; `2026-11-27_121925_focused_48a8` PASS (56 s; 476 passed, 1 policy-named skip: `test_speech_g1`, `test_epub_retirement`, `test_repository_contract`, `test_chatterbox_selected_tuning`, `test_execution_plan`, `test_routine_guard`, `test_dev_work_isolation` and four named gate-contract functions for the retired-path history exemption and the docs-only evidence class); on the closeout tree (tree f86907a5…): `2026-11-27_122348_quick_844c` quick PASS and `2026-11-27_122401_focused_542d` PASS (the same selection: 476 passed, 1 policy-named skip). `--mode changed --plan` was INCOMPLETE by design (the four deleted modules are unmapped gaps that no test imported; three heavyweight gate-contract nodes withheld), so the named focused run replaced it. Mutation control (direct pytest): the two retargeted Decisions pins passed, failed with the archive moved aside, and passed after it was restored. DOC-1 reassembly: archive bodies plus the kept part equal the `dabb02d` blobs byte for byte. Aggregate verification wall time about 4 minutes (within the 10-minute target). NOT RUN by design: full, qualification, journeys, real engines, installs, downloads, setup, repair, the whole suite.
- **Verification simplification (dabb02d, agent-reported, not independent).** Gate runs in `C:\ACT-Dev` on HEAD `ec3343b` plus the working changes: `2026-11-27_113829_quick_88e9` quick PASS (the seven static checks and the import smoke, 12 s); `2026-11-27_113901_focused_f2c6` FAIL, kept in the record (28 modules: the gate's own modules, `test_routine_guard.py`, and representative application modules whose `routine_stop` markers were removed or which start children -- Qwen3 process, runtime, setup, synth, lifecycle locks and nested adoption, TTS work area, M4B continuous, media children, launch crash detection, cleanup engine lease, Tk finalisation, first-run setup close, optional TTS setup, OmniVoice synth, the M4B metadata plan; 1,480 passed, 87 policy-named skips, 7 failed, all in `test_launcher_isolation.py`, whose disposable checkout copy lacked the new guard module; the fixture was fixed and the module passed 7/7); `2026-11-27_114445_focused_4df7` NOT RUN (the whole gate-contract module holds two declared heavyweight nodes, so the plan was INCOMPLETE and ran nothing, as designed); `2026-11-27_114450_focused_629b` PASS (the omitted guarded control plus v3-supervisor: v3-planning 83, v3-supervisor 75, ordinary guards 13, requested scope and cleanup PASS, 286 s); `2026-11-27_115000_focused_8cb2` FAIL, kept in the record (169 routine gate-contract functions and the launcher module: 319 passed, 16 failed -- the hardened acceptance stand-in refused the evidence folder the gate expects the runner to create, and a changed run was still held to the reviewed-inventory check; both fixed: the stand-in creates its evidence folder exclusively under a non-linked parent, and the inventory check is required only in full runs); `2026-11-27_115909_focused_67c3` PASS on the final tree (the 16 failed functions: 29 passed, requested scope 16/16, cleanup PASS). Direct developer checks: `test_routine_guard.py` 5 passed; edited contract cases 14 passed; launcher module 7 passed. Aggregate verification wall time about 1,210 s (marginally over the 20-minute budget). NOT RUN by design: full, qualification, journeys, real engines, installs, downloads, the whole suite, any R1-R3 campaign replay, a mutation control of the guard (budget). Evidence limits: the passing modules of `f2c6` and the 319 passes of `8cb2` ran on trees that differ from the final one only in the two test-fixture fixes and the one-line inventory requiredness change; only `67c3` (and `629b` for the guarded control, before those two fixes) are on or next to the final candidate.
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

- Phase 3B — native macOS uv feasibility, owner approvals of the Phase 3A proposals recorded (this commit).
- c988bd3 Phase 3A — Windows uv feasibility: report, example projects, owner proposals.
- b1a28d5 Phase 2 — classified repository cleanup, DOC-1 archival, simple manual retention.
- dabb02d Verification simplification — routine envelope retired, routine modes execute, plan Revision 6. ec3343b Codex simplification investigation.
- 94683a8 R3 independent review (FAIL); ac762cf R3; a0789bf R2 review (FAIL); b96c36f R2; 9b5eb0a R1 (FAIL at review).
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
