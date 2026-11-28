# Audiobook Creation Tool — Handoff

Current state only. Earlier text: this file was compacted in v0.8.2 Phase 0B from 27,317 lines; the full previous Handoff is
`git show 85462005bc203e6b33fd975e2709fe3d9014b7b3:md-instructions/Handoff.md` (the same path in `Briefing.md`). Architecture and limits: `Briefing.md`;
why: `Decisions.md` index; what shipped: `Changelog.md` index.

## Execution Snapshot

- **Date:** 2026-11-27
- **Last agent:** Claude Code (Opus 5.5), v0.8.2 Phase 5A (engine registry and Qwen3 isolation)
- **Machine:** HOME-PC (Windows 11, RTX 5070), development checkout `C:\ACT-Dev`; disposable roots only under `files/run-temp/`
- **Branch:** `0.8.2` (long-running, from published v0.8.1). The owner's primary checkout and its uncommitted work were not touched
- **Status:** Phase 5A COMPLETE on Windows on `0.8.2` (agent-verified, not independently reviewed): the owed Phase 4 Windows regression ran, the D-6 cold fallback was proved (one defect fixed), the engine registry and shared engine provisioning exist, and Qwen3 installs through uv into `.venv-engines/qwen3` with an earlier engine kept in use until the new one is proved (one real install, two real interruptions, the library proof). A native **macOS regression of the shared changes is owed** (Qwen3 itself is not offered on macOS). VERSION stays 0.8.1; nothing merged, tagged or released
- **Active plan:** `files/plans/Developer-Experience-Upgrade.md` (Revision 10)
- **Current phase:** Phase 5A complete on Windows; **next is Phase 5B (OmniVoice into `.venv-engines/omnivoice`)** on its own prompt, after the owner reviews 5A
- **Recommended next execution tier:** owner review of 5A; the owed macOS regression (Open Issues, Phase 5A) on HOME-MacOS; optionally the authorized Qwen3 synthesis smoke (Pending Owner Decisions); then 5B on HOME-PC
- **Last verification:** v0.8.2 Phase 5A on HOME-PC, agent-run, not independent (Verification and Evidence). The last full gate, on 87dd2bf (2026-11-22), is FAIL/BLOCKED and does not describe this candidate
- **Manual gate:** owner review of 5A (and of Phase 4); the macOS regression; the synthesis-smoke authorization; owner listening to four regenerated Shadow Slave MP3s; owner decisions D-2 to D-4 and the `files/run-temp/` ignore recommendation; the owner-acceptance items below
- **Relevant evidence:** `C:\ACT-Dev\files\dev-work\verification-gate\outputs\` (the Phase 5A runs are named under Verification and Evidence); native-proof summaries in `C:\ACT-Dev\files\run-temp\n5-ev\` (local, never committed)
- **Next exact action:** the owner reviews 5A; on HOME-MacOS, fast-forward and run the macOS regression selection (Open Issues, Phase 5A); then Phase 5B on its own prompt. The interim heavyweight rule (GATE.md) stays in force. Do not merge, tag or release

## In Progress

**Phase 5A (engine registry and Qwen3 isolation) is committed on `0.8.2`, verified on Windows** (agent-verified, not independently
reviewed). Nothing is in progress; the macOS regression of the shared changes is owed (Open Issues).
`scripts/tts/engines/registry.py` is the one explicit list of the five engines (standard library only); `engine_policy`,
`voice_registry.BACKENDS`, `optional_setup_protocol`, `bootstrap.WINDOWS_OPTIONAL_CHOICES`, `local_engine_host.ENGINE_NAMES`,
`venv_layout` and `release` derive their tables from it, values unchanged. `scripts/shared/engine_env.py` holds what every
`.venv-engines/<engine>` shares (place, project, `uv venv`/`uv sync` through `uv_runner`, identity on the managed CPython, RECORD
check, receipt, retirement of an earlier version's environment). Qwen3 installs only through uv from `scripts/tts/engines/qwen3/`
(`pyproject.toml` + `uv.lock`, the 89 reviewed v0.8.1 packages, no package cache) into `.venv-engines/qwen3`; it becomes the engine in
use only when its install record is written, last; an earlier `.venv/engines/qwen3` stays in use until then and is moved whole into
`files/runtime-data/qwen3/set-aside/` afterwards; `.venv-qwen3` is never moved. OmniVoice, Kokoro and Chatterbox are unchanged (5B-5D).
The base application environment `ACT_ROOT/.venv` is now provisioned only by uv on both platforms: stage 0 obtains the pinned uv 0.13.10 and
uv's managed CPython 3.12.15 (PBS 20261009, ACT-owned download metadata) into `files/runtime-data/uv` with consent and hash checks; D-6's
`curl.exe`/`certutil`/`tar.exe` fallback replaces the PATH-Python fallback; one wrapper (`scripts/shared/uv_runner.py`) runs every uv
command (`--python 3.12.15`, `--locked`, explicit user/dev profile, offline-first from the repair cache `files/runtime-data/uvc`, consent
before any download, copy on Windows / clone on macOS, bytecode at install); the root `pyproject.toml` + `uv.lock` are a parity translation
of the v0.8.1 locks (Kokoro and Chatterbox stay in the base; pytest is the `dev` group and the gate's only pin); the receipt
`.venv/.act-environment.json` is written only after a direct RECORD check (a missing RECORD is damage) and real imports; a v0.8.1 `.venv`
is migrated through the set-aside transaction with its engines carried byte for byte and the legacy interpreter kept; one resolver
(`scripts/shared/app_python.py`) gives the not-yet-migrated OmniVoice installer and Qwen3's sealed-package seam a valid base on fresh and
legacy layouts (Qwen3's production installer no longer uses it since 5A).

## Open Issues and Blockers

Status words: **FAIL**, **BLOCKED** (could not run), **NOT RUN**, **PENDING** (owner), **UNVERIFIED**. Agent-reported verification is not independent
review. Items marked (?) could not be proven closed from the record and are kept on purpose.

**Phase 5A (engine registry and Qwen3 isolation; agent-verified on Windows, not independently reviewed)**
- **macOS regression OWED (HOME-MacOS)** for the shared changes: the registry and its seven consumers (`voice_registry`, `engine_policy`,
  `optional_setup_protocol`, `bootstrap`, `local_engine_host`, `venv_layout`, `release`), `uv_runner` (owner records, process-free
  import), `files/tests/conftest.py` (three new guarded paths). Qwen3 is not offered on macOS and nothing about it changed there.
  `--mode changed --plan` is INCOMPLETE by design (suite-wide `conftest.py`), so run: `verify.py --mode quick`; `verify.py --mode focused`
  with `test_engine_registry.py`, `test_qwen3_uv_project.py`, `test_uv_provisioning.py`, `test_suite_isolation.py`,
  `test_venv_recovery.py`, `test_bootstrap_host_macos.py`, `test_local_engine_worker.py`, `test_chatterbox_integration.py`,
  `test_optional_tts_setup.py`, `test_omnivoice_layout.py`, `test_release_packaging.py`, `test_macos_p1b_containment.py`,
  `test_epub_retirement.py`, `test_macos_p1b_gate.py`; then one macOS ZIP from `release.py` in a disposable clone (it carries
  `scripts/tts/engines/qwen3/` as inert data) and one launch of a uv copy to the window (owner-supervised, as in Phase 4).
- **Not run:** real Qwen3 synthesis on the new environment (no authorization; the smallest smoke is proposed under Pending Owner
  Decisions); a model load. The library proof ran against the owner's Base `generation_config.json` only.
- **Kept on purpose (seams below):** the sealed-package seam's pip route; support for an earlier nested or `.venv-qwen3` engine; the
  parity references; retired engines in set-aside.
- **Pre-existing, not 5A (proved on a clean `930ade9` worktree):** `test_p05b_isolation.py::test_numba_compiles_and_writes_only_the_contained_cache`
  and one `test_tts_appearance.py` tallest-notice case (Kokoro Female (Default)) fail when the suite runs directly, outside the gate.
  `test_macos_p1b_containment.py`'s direct-spawn allow-list lacked `uv_runner.run` since Phase 4 (fixed in 5A).
- **Not done:** the CLAUDE.md delegation helper `files/dev/qwen_worker.py` does not exist in `C:\ACT-Dev` (see Phase 0A carry-forward);
  nothing was delegated.

**Phase 4 (uv base provisioning; agent-verified on Windows and, natively, on macOS)**
- **Windows regression DONE (HOME-PC, 5A prompt §2, on unmodified `930ade9`):** quick `2026-11-27_212433_quick_7029` PASS; focused
  (the 14 named modules) `…_212451_focused_e345` PASS (744 passed, 55 policy skips, scope 14/14); `regression --component setup`
  `…_212608_regression_183c` FAIL, kept as evidence: ordinary 2,918 passed / 217 skipped and v3-supervisor 75 passed; v3-planning
  33 failed on a pre-existing harness defect (the controlled read-only context refused uv's `pyvenv.cfg` shape; fixed in 5A); the tree
  and coverage checks failed because 5A's first edits landed during the run. No application defect. D-6 cold fallback: see 5A.
- **macOS native acceptance DONE** (candidate `7a45222`, results under Verification and Evidence). Corrected here, each with a regression
  test: the `.command` sent a moved copy (dangling `.venv/bin/python` link) through first-time setup instead of the repair; the test guard
  did not excuse the macOS managed interpreter's first-import stdlib bytecode (every gate run from a new uv dev environment failed); a repair
  asked the download question twice; the four Windows minor findings below. Observations, not changed: `--venv-check` takes 1.38 s on macOS,
  about 1.07 s of it the containment guardian's orderly exit after `main()` (P1A/P5-I; the Mac launcher never calls `--venv-check`); the first
  launch after setup took 11 s to the window (the one-time Kokoro proof), later preparations 0.45-0.68 s; a repair with downloads refused on
  a damaged cache downloads nothing and keeps the environment but reinstalls the damaged package from the damaged cache, so the environment
  stays flagged for repair (no receipt) rather than byte-for-byte as before; the procedure's `.venv/bin/python --venv-check` on a moved copy
  exits 127 (the link dangles; run the check with the managed interpreter).
- **Seams (each removed only when its criterion holds; transitional rules 1-8):**

  | Seam | Why it stays now | Removal criterion (phase) |
  |---|---|---|
  | Legacy interpreter `files/runtime-data/python` | engines built on it (and a `.venv` not yet migrated) run on it; `app_python.app_env_base` names it only for them | no `pyvenv.cfg` `home` in `.venv` or any engine names it (Phase 6) |
  | OmniVoice installer's own route (`-m venv` from the resolved base + its pinned manifest) | transitional rule 1 | it installs through uv into `.venv-engines/omnivoice` (5B). **Qwen3: resolved by 5A** |
  | Engines nested in `.venv/engines/*`, carried by `VenvReplacement` | OmniVoice's current installer; an earlier Qwen3 engine not yet replaced | no engine is nested any more (after 5B); then the carry protocol is retired (Phase 6) |
  | Qwen3 sealed-package seam (`qwen3_engine_authority`, `optional_setup_authority.acquire_disposable`; no production caller) installs with pip into the nested place | the v3 qualification contracts it was designed for | Phase 6 removes the pip paths |
  | Support for an earlier Qwen3 engine (`.venv/engines/qwen3`, `.venv-qwen3`): selected while no new engine is installed, carried, protected by Clear Downloaded Data | nothing working is broken by an update (5A item 4) | Phase 6, with the carry protocol |
  | Retired engines in `files/runtime-data/qwen3/set-aside/nested-qwen3-*` (with `RETIRED-READ-ME.txt`) | the app never deletes a moved environment | the owner deletes them; Phase 6 cleanup offers it with consent |
  | `scripts/qwen3-requirements.txt` + `qwen3-artifacts.json` as parity references of `engines/qwen3/uv.lock` (`test_qwen3_uv_project.py`), still the source of the stated download size | the PyTorch index publishes no sizes | the first Qwen3 dependency change, at the latest Phase 6 |
  | v0.7.0-v0.8.1 Qwen3 wheel store `files/runtime-data/qwen3/cache/wheels` and pip cache `…/cache/pip` | removed after a successful uv install (the store only when its `verified.json` shows it is the app's; never through a link) | gone on each copy after its first 5A install |
  | uv scratch folders under `files/runtime-data/uv/t/` without an `owner.json` (made before 5A) | an owner that cannot be proved gone is left alone | Phase 6 cleanup |
  | `scripts/requirements.txt`, the two v0.8.1 hash locks, `base_packages.py`, `files/dev-tools/lock_base_requirements.py`, the gate's `deps` check | frozen parity reference held equal to `pyproject.toml` by `test_base_packages.py`; the app never installs from them | the first base change that breaks parity (5C/5D), at the latest Phase 6; the `deps` check then moves to `uv lock --check` |
  | Kokoro and Chatterbox (torch 2.6.0 stacks) in the base project | transitional rule 4 | 5C (Kokoro) and 5D (Chatterbox) isolate them |
  | The kept spaCy English model reinstalled by `uv pip install` of its verified wheel after each sync | it belongs to Kokoro | 5C moves it into the Kokoro environment |
  | v0.8.1 `python-packages` store and `pip-cache` under `files/runtime-data` | protected runtime data: no longer used, never deleted by an agent | Phase 6 cleanup, with the owner's consent |
  | A v0.8.1 `.requirements-state.json` stamp | recognised as "not a receipt", so the environment is rebuilt | Phase 6 |
- **Gate defects D1-D3 (Phase 3B report §7): corrected, Windows-verified, confirmed natively on macOS** (runs `5673`, `2d89`, `160f`:
  the ten 3B selectors PASS with cleanup PASS, D2's nine parameters skip by policy, an active run's scratch audited as `active`; census:
  `ACT.GATE.ROUTINE-EFFECTS` given its native macOS standing, 8 of 8, and `ACT.GATE.SCRATCH` corrected to native). D1 `helpers/winproc.py` treats EPERM like
  ESRCH around both `killpg` calls and polls the group up to `kill_wait` before recording a POSIX survivor; D2 the `m4b-scaling` exit-code
  contract test is Windows-only; D3 `helpers/scratch.py` calls a POSIX owner alive unless `kill(pid, 0)` proves it gone. Tests:
  `test_gate_scratch_exception.py` (`test_on_posix_an_owner_is_alive_unless_its_process_is_gone`,
  `test_a_posix_group_that_answers_eperm_while_exiting_is_stopped_without_raising`).
- **Fixed during the Phase 4 scenarios (real defects found by real runs):** stage 0 garbled a Unicode folder name read back from Python's
  ANSI output (pre-existing in v0.8.1): the path now goes to Python as an argument and stage 0 reports a relative ASCII path; uv's real
  offline-miss text did not match the expected markers; a damaged cached package was "fetched again" from the same damaged unpacked
  archive (`--refresh-package` only revalidates): its cache entries are now removed (`uv cache clean <package>`) after consent; the test
  guard did not excuse first-import stdlib bytecode of the managed interpreter (the legacy one only).
- **Minor findings (Windows Phase 4), dispositions in the macOS acceptance:** (1) FIXED: a failed rebuild said "The environment was rebuilt
  but its packages could not be installed" (seen natively twice); it now says the rebuild could not be done; (2) FIXED: the headless summary
  follows a real Tk proof of the environment; (3) unchanged by design: the launch health check samples one file per package (deep damage is
  found by the import proof, 7-day window, or Preferences' Check and repair); (4) FIXED: the developer `uv` passthrough drops only the
  separator `--`; (5) FIXED: a second module failing to import gets its own targeted reinstall (once per module, none after a failed sync).
- **Not exercised for real:** the fallback `.cmd` download-and-consent path (`choice.exe`; its decline path is tested); Smart App Control
  against the uv venv launcher on a fresh Windows (HOME-PC ran it without a block); a non-admin account; long paths off.

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
  retired `scripts/verify.py` (its bytes are hashed into the frozen v0.8.1 locks; it goes with the parity seam above).

**Verification and gate**
- Verification simplification (2026-11-27, agent-verified, NOT independent): the gate is accident prevention for trusted tests and cooperating agents,
  not a sandbox. Not covered by design: a test that gives a child a replacement environment without the marker, native code, a shell program's internals.
  A changed plan touching suite-wide test infrastructure is INCOMPLETE by design (named focused runs or a component regression owed). Native macOS
  verification of the simplified routine path DONE in Phase 3B: marker inheritance, stall/timeout supervision, canonical routing and stage/JUnit
  reporting PASS; it found D1, D2 and D3, all corrected in Phase 4 (above; the macOS re-check is part of the Phase 4 macOS instructions).
  The Qwen3 installed-library proof stays an owner-deferred environment obligation.
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
- **APPROVED (2026-11-27, Phase 4 prompt) D-6:** when PowerShell cannot run, a contained `curl.exe`/`certutil`/`tar.exe` fallback
  (`scripts/shared/bootstrap_host_fallback.cmd`) with pinned hashes and no PATH Python. Implemented in Phase 4.
- **NEW (Phase 5A): authorize the smallest real Qwen3 synthesis smoke?** Proposed, not run: one CustomVoice preset voice, one short
  sentence, in a disposable root with a uv-built `.venv-engines/qwen3` (about 3.1 GB download, 5.5 GB on disk, about 6 minutes), the
  owner's existing CustomVoice model copied in after its hashes are verified (about 4.3 GB; no download), output only in disposable
  scratch, the root removed afterwards. It would prove a model load and generation on the new environment, which 5A did not.
- Resolved: D-5 (AI Workspace is local-only), D-7 (v0.8.1 published 2026-11-21T05:45:50Z, both assets).
- Also awaiting the owner: controlled testing versus independent review of Checkpoints 1–6; supplying the canonical `AI-WORKSPACE.md`; the macOS permissions correction; ACT72-030 and ACT72-064; M4B scan-refusal and junction handling.

## Development Checkout and Evidence Locations

- **HOME-MacOS (Phase 4 macOS acceptance):** the owner's primary macOS checkout keeps its v0.8.1-era `.venv` (legacy interpreter; the gate
  still runs on it). Kept, ignored: the verified pinned archives `files/temp/bootstrap/uv-aarch64-apple-darwin.tar.gz` and
  `cpython-3.12.15+20261009-aarch64-apple-darwin-install_only.tar.gz` (39 MB, clones of Phase 3B's; the macOS real-uv stage 0 test needs
  them), `files/dev-work/uv-3b/` unchanged, the gate runs named in the snapshot. Removed: `files/dev-work/p4m/`. Capabilities used: the
  agent's built-in shell, file and question tools only; no skill, plugin, MCP server or subagent (two configured MCP servers failed to
  connect and were not needed).

- **Development checkout (D-1):** `C:\ACT-Dev`, a separate clone on `0.8.2` (upstream `origin/0.8.2`) whose root `.venv/` is, since Phase 4
  (2026-11-27), uv's **dev** profile on the managed CPython 3.12.15 (`files/runtime-data/uv/python/cpython-3.12.15-windows-x86_64-none`): 170
  distributions plus the kept spaCy model, migrated from the v0.8.1 `.venv` through the repair transaction in 72 s (only pytest and its two
  dependencies downloaded). The local-only `AGENTS.md` and `CLAUDE.md`, NLTK and spaCy data, and the now-unused legacy interpreter and wheel
  store stay in `files/runtime-data/`. Run the gate with `.venv\Scripts\python.exe files\dev-work\verification-gate\verify.py`. Disk:
  `.venv` 2.36 GB, repair cache `files/runtime-data/uvc` 2.05 GB, uv and the managed Python 221 MB, legacy interpreter 146 MB, wheel store
  504 MB. Never hard-coded in application code or user documentation.
- **Phase 3A prototypes (ignored, local):** `C:\ACT-Dev\files\dev-work\uv-3a\` holds the verified uv 0.13.10 binary and ZIP, the PBS 20261009 archive (`dl/pbs/`), the five prototype projects with their `uv.lock` files (`proj/`), the managed Python, the shared uv cache, the snapshot and comparison tools (`tools/`), logs and before/after snapshots. Nothing outside it was created; no production path depends on it.
- **Preserved, not used for runs:** the owner's primary checkout (`0.8.1`) and the old worktree `files/dev-work/wt082` inside it. Protected evidence stays in the old worktree under these relative paths
  (they do NOT exist in `C:\ACT-Dev`): regenerated Shadow Slave MP3s `files/dev-work/v082-fc/r1-failed4/mp3/` (never open, move, regenerate or delete); checkpoint and qualification evidence
  `files/dev-work/v0.8.2-cp1-evidence` to `cp6-evidence` and `v0.8.2-qual-evidence`; earlier gate runs `files/dev-work/verification-gate/outputs/`; the Phase 0A review bundle `files/run-temp/p0a-review/`; the Phase 0B ledgers
  and reconciliation `files/run-temp/p0b/`. Prefix them with `<primary checkout>\files\dev-work\wt082\`. Gate runs in `C:\ACT-Dev` write to its own `files/dev-work/verification-gate/outputs/`.
- **Phase 5A local leftovers (`C:\ACT-Dev\files\run-temp\`, untracked, never committed):** kept `n5-ev/` (the native proof's JSON
  summaries and the library-proof output), `p5a/` (29 MB: the proof driver, logs, both sweeps' JUnit, the gate plans), `d6-cold*.log`
  and `p5a-reg-*.log`; removed: the proof root `n5` (5.4 GB, after checking it held no link out of itself), the sweeps' basetemps and the
  archive clone. `C:\ACT-Dev` itself has no `.venv-engines` (no Qwen3 engine is installed in the development checkout).
- `%TEMP%\act-gate` (`--audit-scratch` at the end of Phase 5A, 2026-11-28, read-only): five abandoned folders, 7.57 GiB, left as found
  for the owner: `b18e` (run 04a6, 0 MiB), Phase 4's `bad4` (run 2fdc, 4.17 GiB), `bbb8` (d5a9, 0 MiB) and `cb5b` (7d73, 0.2 MiB), and
  5A's `d118` (3.59 GiB, the retained scratch of the failed regression `183c`); `6dc8` is gone. `C:\ACT-Dev` local evidence after Phase 2: gate `outputs/` 311 MB, guarded basetemps `files/dev-work/p05b-stage4c/` 646 MB (R2-campaign era), `files/run-temp/` 17 MB: within GATE.md's 2 GiB soft budget, kept.
- Phase 1A-1 R1: the owner removed the three scratch folders left outside containment (`C:\t\p1a1` and `%TEMP%\act-gate\fd57`, `f2c1`); R1 created no
  external scratch (direct runs used short basetemps under `files/run-temp/`, removed). Free space on C: was about 7 GiB during R1: below the comfort
  margin for a full run; check it before any expensive run.
- Historical (Phase 1A-1, superseded by the owner's cleanup above): Phase 1A-1 left two folders of its own that it was not permitted to delete: `%TEMP%\act-gate\fd57` (1.06 GiB, the retained scratch of its failed iteration run `2026-11-25_192340_focused_5fd4`; `--audit-scratch` reports it abandoned and owned by that run) and `C:\t\p1a1` (about 0.46 GB of direct-run basetemps). Both are disposable; the owner may remove them. Free space on C: was about 6 GiB at the end of Phase 1A-1: check it before any expensive run.

## Verification and Evidence

- **Phase 5A (HOME-PC, `C:\ACT-Dev`, agent-run, not independent).** Phase 4 Windows regression and D-6: under Open Issues (Phase 4)
  and in the plan's 5A record. **Native proof** in the disposable root `files/run-temp/n5` (a copy of `scripts/`, the managed CPython and
  uv, a stand-in `.venv`, a legacy nested Qwen3 engine made as v0.8.1 made one, without its packages; removed afterwards; JSON summaries
  kept in `files/run-temp/n5-ev/`): two production installs killed 20-21 s in, mid-download (fresh and re-sync paths): the legacy engine
  unchanged and still in use, status ok, the new folder recorded `created`, no receipt, repair offered; the first kill left 422 MB of
  partial downloads in uv's scratch, which led to the owner-record fix, after which the second kill's scratch was cleared by the next
  install. **The one authorized full install** through Check and repair: 351.5 s (89 packages downloaded in 4 m 32 s, installed 18.5 s,
  13,813 files compiled 6.7 s, RECORD check about 19 s, probe about 27 s); engine in use, identity, receipt and RECORD clean; 89/89
  distributions equal to the reviewed manifest; imports in 4.6 s, torch 2.10.0+cu128, CUDA 12.8 on the RTX 5070, a CUDA kernel run from
  the engine's own interpreter, its base the managed CPython, no app `.venv` on its path; the nested engine moved whole (identical) to
  `set-aside/nested-qwen3-<UTC>-<id>/` beside its note; the app's `.venv` unchanged; no package cache; 5.46 GB on disk. **Damage:** a
  deleted `pydub/playback.py` found read-only by Check and repair (rebuild offered, 3.1 GB stated); clean after restore. **Library proof:**
  `test_qwen3_calm_harness.py::test_the_real_library_merges_…` PASSED (6.4 s) on that engine with the owner's Base
  `generation_config.json` (SHA-256 `f1b90b45…` as pinned; read only, copied in). **Direct test runs:** the new modules
  (`test_engine_registry.py` 16, `test_qwen3_uv_project.py` 12, `test_engine_env.py` 19) and every changed module pass; a direct sweep of
  the suite (9,815 tests, 40.6 min, kept as evidence in `files/run-temp/p5a/`) found the adaptations still owed, then fixed; its
  guarded-group failures are direct-run artefacts (those groups run only through the gate) and two failures are pre-existing (Open
  Issues); a second, targeted sweep of the 103 modules reachable from the late changes (5,402 tests, 18 min): 5,158 passed, 242
  skipped, only the two pre-existing failures. **Gate** (about 12.5 minutes, on the candidate before
  these result lines): quick `2026-11-27_235253_quick_4c1e` PASS; `--mode changed --plan` INCOMPLETE by design (346 selectors, 26
  gaps: the suite-wide `conftest.py` and 20 sources over the 40-module budget; five paths with no policy route: two READMEs, the
  fallback `.cmd` and the Qwen3 project's `pyproject.toml` and `uv.lock`, which `test_layout_canary.py`, `test_bootstrap_host.py` and
  `test_qwen3_uv_project.py` cover but the policy does not route (left as is, like the root project in Phase 4); the direct sweeps
  above ran its ordinary modules); focused `2026-11-27_235425_focused_6188` PASS on the 26 key modules and both guarded
  groups the Phase 4 regression failed on (1,783 passed, 92 policy-named skips; v3-planning 294 and v3-supervisor 75 passed; scope
  33/33, tree unchanged; `test_p05b_isolation.py`'s numba test passes here, inside its guarded group); then a quick run on the final tree,
  these document lines included, before the commit (named in the completion report). **Downloads:**
  about 3.8 GB (two interrupted installs about 0.85 GB, the full install about 2.9 GB), D-6's uv (twice) and CPython archive about 78 MB. **Disk:** free
  space on C: never below 18 GB (24 GB before the install). NOT RUN by design: full, qualification, journeys, any R1-R3 replay, model
  downloads or loads, synthesis, the app's window.
- **Phase 4 native macOS acceptance (this checkpoint, HOME-MacOS, M4 Pro, macOS 27; agent-run, one owner-supervised launch, not
  independent).** Candidate `7a45222` (fast-forwarded; the owner's uncommitted work identical before and after). The retired procedure ran in
  disposable copies under the ignored `files/dev-work/p4m/` (folder names with spaces and accents), every command timed:
  **stage 0 cold** with the real consent prompt answered Yes (a pty helper; an EOF first gave the decline path: exit 2, nothing downloaded):
  uv 0.13.10 (14.7 MB) and the CPython 3.12.15 archive (24 MiB) downloaded, size- and SHA-256-verified, uv signed by Astral, the interpreter
  installed from the kept mirror, 6.0 s; Tk 9.0.4 `aqua`, OpenSSL 3.5.9 with a working HTTPS fetch, `arm64`; no `com.apple.quarantine`
  anywhere. **Cold user-profile setup** (`--headless --skip-kokoro-download`) 44.4 s: offline miss then the online sync, 166 packages
  prepared 5.7 s, installed 0.44 s, 17,053 files compiled 4.0 s, FFmpeg 9.0.1 (Riedl, Developer ID) and NLTK data; receipt `uv user`, record
  and imports ok, 166 distributions, no pytest; `pyvenv.cfg` home the managed 3.12.15, `uv = 0.13.10`. **Warm:** stage 0 0.31-0.42 s;
  `--venv-check` 1.38 s (0.36 s of work, the rest the containment guardian's exit); launch preparation with only the window stubbed
  0.45-0.68 s. **App launch (owner-supervised):** the owner's first double-click did not reach the test copy (no trace in it); the agent then
  opened the test copy's `.command` with `open` (LaunchServices, the double-click route) while the owner watched: the window opened on the uv
  environment 11 s after the start (first launch after setup, one-time Kokoro proof), Terminal closed itself, no prompt; the owner closed
  the window. **Targeted repair:** `tqdm/__init__.py` removed, `--venv-check` 3, repair offline behind a dead proxy with downloads refused
  15.3 s, one package reinstalled, interpreter and `pyvenv.cfg` untouched, healthy again. **Cache damage:** one byte of the cached
  `tqdm/std.py` flipped (the environment's copy is a separate clone): downloads refused, exit 1 in 13.9 s, nothing downloaded, environment kept
  (the damaged-cache copy reinstalled, receipt withdrawn), message and double question then defective (fixed); downloads allowed 15.2 s:
  `Removed 42 files (324.0KiB)`, fetched again, every file matches, the cache entry back to its digest. **Relocation:** the folder moved;
  stage 0 offline behind a dead proxy refreshed the minor-version link (2.2 s); `.venv/bin/python` dangled (exit 127: the launcher defect,
  fixed); repair offline 38.7 s, 166 packages cloned in 0.97 s, free space changed by 9 MiB for a 1.5 GiB environment, a stand-in engine
  byte- and mtime-identical. **Interruption:** `home` broken, the repair started in its own session and its process group SIGKILLed 1.7 s in,
  while `uv sync` ran (uv in a group of its own, ended by the lifeline with the guardian within 1.2 s; nothing of it left); next start
  "an earlier environment repair did not finish"; recovery restored, rebuilt offline 39.9 s, engine identical. **Legacy:** a v0.8.1 shape
  (a clone of the legacy interpreter, a pip `.venv` with its `.requirements-state.json`, a nested `-m venv` OmniVoice stand-in);
  `app_owned_python()` the legacy interpreter; a broken lock rolled back in 2.7 s with the legacy `.venv`, engine and interpreter identical
  (and, by a seeding mistake, an empty cache with downloads refused: rolled back in 2.4 s, identical); migration offline 34.7 s (166
  cloned in 0.43 s, 316 MiB of disk for a 1.5 GiB environment), engine (6 files, 3 links) and legacy interpreter (2,032 files) byte- and
  mtime-identical, the carried engine still runs on the legacy interpreter, `app_owned_python()` now the managed one. No real engine was
  installed and nothing was synthesised: stand-ins only. **Distribution:** `release.py` from a disposable clone at a local commit of this
  candidate: both ZIPs; the macOS one has 207 members with `pyproject.toml`, `uv.lock`, the download metadata, stage 0, launcher `0755`
  LF, nothing excluded; extracted with `ditto`, stage 0 from the verified archives and an offline environment from a copied cache behind a
  dead proxy: 34.4 s, 166 distributions. **Profiles:** user (no pytest) in every app copy; a new dev clone with the `dev` profile through the
  repair route, 37.4 s (pytest 9.1.1, iniconfig, pluggy downloaded; 169 distributions; a damaged cache entry it inherited was found by the
  RECORD proof and fetched again with consent). **Gate** (aggregate about 7.8 min): checkout `.venv` quick `7637` PASS; focused `8404` FAIL
  (the real-uv test skipped: the pinned archives were absent; the verified 3B archives were cloned into `files/temp/bootstrap/`), `2d89`
  PASS (243); the ten 3B selectors `5673` PASS (30, 9 policy skips, cleanup PASS, audit `active`); features ROUTINE-EFFECTS + SCRATCH
  `160f` PASS (160); new dev environment quick `d393` PASS, focused `aaa9` FAIL (the session guard on the managed interpreter's stdlib
  bytecode; fixed), `3c4c` PASS (789, 15 policy skips, 19/19 scope); final tree in the checkout `0dab` PASS (790, 14 policy skips, 19/19).
  Direct checks: 8 `test_venv_recovery.py` failures identical on pristine `7a45222` (Windows-only tests, the owed portability drop);
  the launcher test red on the old `.command`, green on the fix. **Global state** before/after identical (every default uv location, pip and
  Python caches, `~/.local/bin`, PATH, the checkout's `.venv`, engine and runtime stores). **Downloads** about 0.43 GiB (base wheels about
  0.34 GiB, FFmpeg pair 54 MB, CPython 24 MiB, uv 14.7 MB, NLTK 4.3 MB, pytest set, two tqdm refetches). **Disk:** `p4m/` reached 12 GiB
  apparent (APFS clones counted in full); removing it freed 3.5 GiB physical, and the two failed runs' own gate scratch another 1.17 GiB. NOT RUN by design: full,
  qualification, journeys, real engines, model downloads, synthesis, a standard-user account, a browser-quarantined ZIP.
- **Phase 4 (HOME-PC, agent-reported, not independent).** Targeted tests: every module the changes touch, adapted and
  re-run directly on the final code, plus the new `test_uv_provisioning.py`. Real disposable scenarios in `C:\ACT-Dev\files\dev-work\p4s\`
  (removed afterwards; their logs summarised here), each with the pinned uv and managed Python, in folders named `Livres été` and
  `Fresh ü copy` (spaces and accents): **fresh cold install** from a test archive built by `release.py` (stage 0 downloads uv 15.6 MB and the
  Python archive 46.4 MB with consent; headless setup 113.7 s: 167 packages prepared in 47 s, installed in 17 s, 17,066 files compiled in
  0.46 s; `.venv` 2.13 GB, repair cache 2.04 GB, uv dir 221 MB); **relocation** (the folder moved; stage 0 refreshed uv's stale minor-version
  link offline in 2.9 s; the `.venv` on the old home rebuilt offline behind a dead proxy with downloads refused in 65.2 s, a stand-in engine
  byte- and mtime-identical); **warm launch** (stage 0 0.42 s, `--venv-check` 0.28 s); **package repair** (two packages damaged; reinstalled in
  place offline in 35.7 s, nothing rebuilt); **cache damage** (a cached package corrupted: a No downloads nothing and leaves the environment
  intact; a Yes first failed to re-fetch, which exposed the `--refresh-package` defect, then after the fix removed its 42 cached files and
  re-fetched it in 66.2 s; a cache lacking a package: one online fetch after a Yes, 37.3 s); **interruption** (a rebuild killed during the
  sync: the next start reported the unfinished repair, restored, rebuilt offline in 67.1 s, engine identical; a kill during an in-place sync
  kept the environment and withdrew the receipt); **legacy migration** (a v0.8.1-shaped install: legacy interpreter, pip `.venv` with a
  stamp and a stand-in Qwen3 engine venv: a broken lock rolled back in 0.9 s with everything identical; then the migration offline in
  52.9 s, the engine's 8 files and the legacy interpreter's 3,605 files byte- and mtime-identical, the carried engine still runs);
  **legacy engine route** on the legacy layout (base = legacy interpreter) and on the uv layout (base = managed interpreter), each building a
  working engine venv; **fallback `.cmd`** in a fresh ZIP copy with uv and the archive pre-seeded (2.8 s, no network); **cached/offline
  install** of that fresh copy from a copied repair cache behind a dead proxy (62.9 s; only the NLTK fetch failed, as designed). Archive
  inspection: both test archives (Windows 207 members, macOS 207) carry `pyproject.toml`, `uv.lock`, the download metadata and the three stage-0
  scripts and nothing excluded. Global state before and after (registry `Software\Python` and `Software\Astral`, every default uv location,
  `pip` and `Python` user folders, the user PATH): identical. `C:\ACT-Dev` migrated to the dev profile (72 s). Gate on the uv dev environment:
  quick `0018` PASS; changed `d5a9` NOT RUN (its plan is INCOMPLETE: the suite-wide `conftest.py`, `bootstrap.py` and `app_python.py` over the 40-module budget, `pyproject.toml` and `scripts/shared/README.md` unmapped, three heavyweight nodes withheld), so its 300 ordinary selectors ran as focused runs: F1 `2fdc` (119 selectors) FAIL with 5 failed and 1 error (four tests still pinned to pip-era fixtures, the test guard not excusing first-import bytecode seen through uv's minor-version junction, two macOS skip reasons reworded so the policy no longer named them; all fixed) plus the pre-existing census failure below; then on the final tree `1d7c` PASS (the 181 gate-contract nodes: 328 passed, 7 min 21 s) and `2e4c` PASS (F1's selection with the census node split out, 145 selectors: 4,828 passed, 364 skips each named by policy, 9 min 31 s); `7d73` FAIL on exactly one test, `test_macos_p1b_gate.py::test_every_feature_has_exactly_one_macos_standing_derived_from_the_census`, pre-existing since 8d7226d (`ACT.GATE.ROUTINE-EFFECTS` has no macOS standing at HEAD a44ad6d either; a native census is owed, outside Phase 4). Gate time was about 27 minutes, over the prompt's ~15 because F1 had to be repeated on the final tree. NOT RUN by design: full, qualification, journeys, any R1-R3 replay, model downloads, synthesis, the app's window.
- **Phase 3B (HOME-MacOS, agent-reported, not independent).** Prototypes in the primary checkout's ignored `files/dev-work/uv-3b/` (report sections 1-8 give commands, timings and results): uv 0.13.10 digest verified three ways, signature and notarization, a controlled quarantine fixture (uv runs; a quarantined interpreter hangs under Gatekeeper); the ACT-owned interpreter pin installed, compared file by file, Aqua Tk 9.0.4 window (auto-closed, 1.84 s), ssl, venv, offline restore; three parity locks compared artifact by artifact with a negative control; base, OmniVoice and Kokoro installed and import-proved (MPS available); clone/copy/hardlink timings, physical disk, damage isolation, offline repair, an interrupted clone sync; A1 recreation with an engine running; move and copy relocation, permissions, case, path depth. Before/after snapshots: 14 of 14 protected locations unchanged (root `.venv` with its nested OmniVoice engine, `files/runtime-data/python`, the wheel store, every default uv location, Homebrew and `/usr/local/bin`, shell startup files). Downloads about 0.7 GiB; free space never below 510 GiB. Gate on HOME-MacOS (candidate `c988bd3` + the owner's uncommitted work): `2026-11-27_153023_quick_8383` quick PASS (8 s); `2026-11-27_153203_focused_0c84` FAIL (10 selectors: 29 passed, 10 failed = D1 and D2; reporting accurate, cleanup PASS); `2026-11-27_153708_focused_d42d` PASS (8 selectors, 29 passed, requested scope 8/8); `--plan` checks of canonical and case-varied selectors; direct single-test reproductions and an isolated `run_supervised` errno trace for D1. Closeout on the doc changes: `2026-11-27_154508_quick_ef85` quick PASS; `2026-11-27_154517_focused_8785` FAIL only on D3 (11 modules, 652 passed, 10 policy-named skips, 1 failed: `helpers/scratch.py` cannot prove a POSIX owner alive, so `--audit-scratch` calls an active macOS run's scratch abandoned; read-only, low severity); the ~170 gate-contract nodes `--mode changed` would also route are NOT RUN on this Mac (owed to the next Windows `changed` run). Routine verification about 4.5 minutes. NOT RUN by design: full, qualification, journeys, the suite, model loads, synthesis, an app launch on a uv environment, production setup or repair.
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

- Phase 5A — engine registry, shared engine provisioning, Qwen3 through uv into `.venv-engines/qwen3`, Phase 4 Windows regression, D-6 cold fallback fix (this commit).
- 930ade9 Phase 4 macOS acceptance — native verification on HOME-MacOS, five corrections, census, procedure retired.
- 7a45222 Phase 4 — production uv-based base provisioning, D-6 fallback, D1-D3 gate corrections.
- a44ad6d Phase 3B — native macOS uv feasibility, owner approvals of the Phase 3A proposals recorded.
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
