# Audiobook Creation Tool — Handoff

Current state only. Earlier text: this file was compacted in v0.8.2 Phase 0B from 27,317 lines; the full previous Handoff is
`git show 85462005bc203e6b33fd975e2709fe3d9014b7b3:md-instructions/Handoff.md` (the same path in `Briefing.md`). Architecture and limits: `Briefing.md`;
why: `Decisions.md` index; what shipped: `Changelog.md` index.

## Execution Snapshot

- **Date:** 2026-11-25
- **Last agent:** Claude Code (Sonnet 5.5), v0.8.2 Phase 0B
- **Machine:** HOME-PC (Windows 11)
- **Branch:** `0.8.2` (long-running, from published v0.8.1), developed in the worktree `files/dev-work/wt082`; the owner's primary checkout (`0.8.1`, uncommitted owner work) was not touched
- **Status:** Phase 0B (documentation compaction) committed and pushed to origin/0.8.2, awaiting planning-chat review. No application, launcher, dependency or version change (VERSION stays 0.8.1)
- **Active plan:** `files/plans/Developer-Experience-Upgrade.md` (Revision 3)
- **Current phase:** v0.8.2 Developer Experience Upgrade, Phase 0B complete; Phase 1A NOT started
- **Recommended next execution tier:** planning-chat review first; the next agent task needs owner decision D-1 (verification location) before it can run real-environment verification
- **Last verification:** Phase 0B: documentation-only checks and focused direct pytest (520 passed, 0 failed, 0 skipped across five modules and one named test, about 22 s), agent-reported, not independent; no gate run (`verify.py` not started). Details below. The last full gate, on 87dd2bf (2026-11-22), is FAIL/BLOCKED and does not describe this candidate
- **Manual gate:** owner listening to four regenerated Shadow Slave MP3s; owner decisions D-1 to D-4, D-6, D-8; plus the owner-acceptance items below
- **Relevant evidence:** `files/dev-work/v082-fc/` (regenerated audio, protected), `files/dev-work/verification-gate/outputs/` (gate runs), `files/release-history/ACT-v0.8.1-Windows-MacOS-Release-Acceptance.md`
- **Next exact action:** resolve D-1, complete the outstanding Phase 0A verification in the approved development location, and review the A5/A6 execution-control designs before beginning Phase 1A. Do not start Phase 1A, merge, tag or release

## In Progress

Nothing is mid-implementation. Phase 0A (8546200) was approved by the planning chat with the limitations carried below (workspace adoption
partial; its gate-contract tests unexecuted). Phase 0B is this compaction: Handoff and Briefing rewritten; Decisions and Changelog gained
navigation indexes only (no entry moved or rewritten); the Tay-mar requirement and D17 now live in Decisions; the v0.8.1 release status was
corrected to published. A proposed archival split of Decisions/Changelog awaits the owner (below).

## Open Issues and Blockers

Status words: **FAIL**, **BLOCKED** (could not run), **NOT RUN**, **PENDING** (owner), **UNVERIFIED**. Agent-reported verification is not independent
review. Items marked (?) could not be proven closed from the record and are kept on purpose.

**Phase 0A carry-forward and workspace**
- NOT RUN: the tree-building tests of `files/tests/test_verification_gate_contract.py` (including its edited `docnames` fixture) and the rest of
  `files/tests/test_verify_evidence.py`. They run `git init` under `tmp_path`, which needs a short basetemp outside this 123-character worktree, and
  the gate's focused mode FAILs preflight here (`guarded-specification`: no `.venv` in `wt082`). Run both with `verify.py --mode focused --test` in the
  approved D-1 location **before Phase 1A changes gate execution or evidence behaviour**.
- Canonical AI Workspace adoption is PARTIAL: the owner's canonical `AI-WORKSPACE.md` is not on this machine (every local copy is the older
  `bd91c654e279` template). Adopted local-only in `wt082` (never staged): ACT-specific `AGENTS.md`, thin root `CLAUDE.md`. Not adopted: `AI-WORKSPACE.md`,
  the `.ai/` guides, `.ai/VERIFICATION.md`. Never install an old template or fabricate the canonical files.
- The primary checkout's `.claude/CLAUDE.md` is stale (retired gate path `scripts/verify.py`, old document spellings, a `files/dev/qwen_worker.py`
  delegation rule although `files/dev/` does not exist, `scripts/Universal`) yet Claude Code loads it as a parent-directory file in `wt082` sessions: a
  competing entrypoint for the owner to retire or replace. Not modified (off-limits). A sanitized review bundle is local-only under `files/run-temp/`.
- Owner-local tooling stale (?): `scripts/project-status.py` (untracked, primary checkout) also reads `files/runtime/verify-state.json`, which the gate no
  longer writes; `.ai/ENVIRONMENT.md` pool table unfilled; `files/dev-work/local-model-worker.py` absent. `scripts/requirements.txt` line ~106 still names the
  retired `scripts/verify.py` (its bytes are hashed into the locks; leave until a lock regeneration).

**Verification and gate**
- Interim rule (GATE.md, active until Phase 1A): no `--mode full`, `qualification`, `changed`, `focused --feature` or `--journey` without the owner's authorization.
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
  Qwen3 needs about 11 GB commit (see the headroom floor). The worktree here has a 123-character root and no `.venv`.
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
- Decisions.md ordering is broken in two places (documented in its index; no entry moved). A permanent archival split of Decisions and Changelog by era is PROPOSED in the Phase 0B report for
  planning-chat approval; nothing was archived.

## Pending Owner Decisions

- **D-1** permanent location for real-environment verification and engine installs — due before Phase 1A. Options: a named short-path clone outside the repository (recommended), switch the primary checkout to `0.8.2`, or docs/static only here with runs deferred.
- **D-2** external scratch under `C:\t\` (about 14.5 GB) — by Phase 2. **D-3** ACL-locked folders (owner-run `takeown`/`icacls` or leave) — by Phase 2. **D-4** adopt the owner's uncommitted plan and release-history archiving on `0.8.2` or keep them tracked — by Phase 2 (D17 is now in Decisions).
- **D-6** Windows PowerShell-blocked fallback (`curl.exe`/`tar.exe` with hashes, recommended, or drop it) — by Phase 4. **D-8** disk cost versus offline repair depth (the A4 retention proposal) — at the Phase 3 report.
- Resolved: D-5 (AI Workspace is local-only), D-7 (v0.8.1 published 2026-11-21T05:45:50Z, both assets).
- Also awaiting the owner: controlled testing versus independent review of Checkpoints 1–6; supplying the canonical `AI-WORKSPACE.md`; the macOS permissions correction; ACT72-030 and ACT72-064; M4B scan-refusal and junction handling; the Decisions/Changelog archival split.

## Verification and Evidence

- **Phase 0B (this checkpoint, agent-reported).** Read-only extraction by eleven subagents plus one reconciler into a local preservation ledger (761 items, reconciled to 131; 57 OPEN, 24 OPEN-UNCERTAIN kept, 15 resolved with
  cited evidence, 4 superseded, 31 historical with a live home) and checked against the rewritten documents; documentation checks (five-document contract, `check_docs`, paths, release status, privacy, the recovery reference returning the four originals byte-for-byte, snapshot
  parse by the owner's `project-status.py` read-only); direct focused pytest of the documentation-content tests: 520 passed, 0 failed, 0 skipped; mutation checks of the retargeted Tay-mar pin with a control.
  NOT RUN by design: any `verify.py` mode, full, changed, qualification, journey, real engine, install, benchmark.
- **Last full Windows gate:** `87dd2bf`, FAIL/BLOCKED (above). v0.8.0 gate `c8e8` stays FAIL (owner exception); v0.8.1's `2cf1` on `00ae625` FAIL with 56/56 journeys passing; neither describes the current tree.
- **Evidence roots (ignored, local):** `files/dev-work/v082-fc/`, `v0.8.2-cp1..cp6-evidence/`, `v0.8.2-qual-evidence/`, `verification-gate/outputs/` (this worktree); macOS and v0.8.1 roots (`macos-*`, `v0.8.1-*`) exist only in the primary checkout.
  Release records: `files/release-history/` (v0.8.1 acceptance record, v0.8.0 records). The local review bundle and reconciliation ledger: `files/run-temp/p0b/` (never committed).

## Recent Checkpoints (newest first; cite by `git log`, not by tip)

- Phase 0B — Handoff/Briefing compaction, Decisions and Changelog indexes, v0.8.1 release status corrected (this commit).
- 8546200 Phase 0A: five-document contract, plan moved to `files/plans/`, local-only workspace, interim verification rule. 3546a4f plan readiness review.
- 56c83cf OmniVoice silent chunk re-rendered with derived seeds (Shadow Slave chapters 72, 299, 338, 490).
- 963f6fe Windows skip-policy rule; 3938a40 and 87dd2bf Windows full-gate closeout and test corrections; b87a36f and 3dcaa43 Windows qualification (Import Folder edit-loss guard).
- 5da1271 CP6 imports off Tk; 1d47024 CP5 Converter index and Cover Start; fee286f CP4 TTS Start; de62430 CP3 collision search; 4465b94 CP2 Maker/Editor preparation; ffd1621 and b1fbb49 CP1 MP3 Tool and review fixes.
- v0.8.1 (tag `v0.8.1` = `6a7be75` on `master`, published 2026-11-21T05:45:50Z): Windows and macOS ZIPs; see the acceptance record.

## Historical Reference

Everything older than the list above (v0.5.0 to v0.8.1 phase logs, macOS P1–P5 blocks, Plan 4 Chatterbox, v0.7.2 hardening) is in `git show 85462005bc203e6b33fd975e2709fe3d9014b7b3:md-instructions/Handoff.md`;
the durable parts are in `Decisions.md` (index), `Changelog.md` (index) and `Briefing.md`. Release qualification: `files/release-history/`. Plan: `files/plans/Developer-Experience-Upgrade.md`.
