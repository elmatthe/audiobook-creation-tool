# ACT verification gate — policy and command reference

This is the authoritative ACT-specific verification policy. General verification guidance (the AI Workspace's, kept
local-only) defers to this file; the module docstring and `--help` of `verify.py` describe what each mode *does*, this
file says which of them an agent may *start*. Plan: `files/plans/Developer-Experience-Upgrade.md` (§5 and the
"Verification simplification" amendment of 2026-11-27).

**Status: v0.8.2 verification simplification (2026-11-27).** The gate is an accident-prevention and verification tool for
trusted repository tests and cooperating coding agents. It is not a security sandbox. Phase 1A-1's universal routine
envelope (launch interception, child bootstrapping, per-child effect ledgers, explained-stop accounting, exact fixture
profiles) was retired by owner directive; its R1-R3 review history and FAIL verdicts stay in the record. The routine modes
now execute. Heavyweight work still needs the owner's authorization for each run.

## Modes

| Request | Plan (resolved before anything runs) | Executes |
|---|---|---|
| `--mode quick` | The fixed static checks of `verification.json` `quick.checks`: docnames, docs, doc-links, json-validity, deps, config, import-smoke. | **Yes, routine.** No pytest. |
| `--mode focused --test <id> [...]` | The named selectors plus the required guard. A declared heavyweight node asked for by name, or held by a module asked for whole, is withheld and the plan is INCOMPLETE; a nonexistent module or node is a `missing` gap. | **Yes, routine.** |
| `--mode focused --feature <id> [...]` | The feature's routine tests plus the guard; its journeys, media, qualification and owner checks are listed as obligations, never run. | **Yes, routine.** |
| `--mode changed [--base REV]` | HEAD against staged, unstaged and untracked work (with `--base`, also the committed side since the merge base), routed tests, static checks, guards, gaps and obligations. An unresolved path is a gap: the plan is INCOMPLETE and nothing runs. No relevant change is NOT RUN. | **Yes, routine.** |
| `--mode regression --component <id> [...]` | The reviewed components of `verification.json` `regression.components`, expanded through their features. No unnamed or `all` regression. | **Yes, routine.** |
| `--mode qualification --scenario <name>` | One named scenario (with `--network <policy>` only where the scenario declares it). | Only with the **owner's authorization for that run**. |
| `--mode qualification --journey <id> [...]` | A set of registered native journeys. | No: plan only. |
| `--mode full` | The complete release partition: every journey, the whole ordinary suite, every guarded group, the static gates, the collection partition, the inventory and the self-tests. | Only with the **owner's authorization for that run**. |
| any of the above `--plan` | Resolve and print the plan as JSON; run nothing, write nothing. Exit 3 (2 for another platform). | Data only. |
| `--status`, `--evidence`, `--audit-scratch`, `--help` | Read-only readers. | Data only. |

Refused before anything exists (exit 64): `--mode focused --journey`, an empty or unknown selector, an unknown feature,
component, journey or scenario, `--component` outside regression, `--base` outside changed, qualification with neither or
both of `--scenario` and `--journey`, `--plan` with `--preflight-only`/`--collect-only`.

**Plan status:** COMPLETE, INCOMPLETE (a requested test withheld, an unresolved gap, or only a guard would run), NOT RUN
(nothing relevant), BLOCKED (another native platform). A plan is never a PASS; a plan that is not COMPLETE runs nothing.
Selection (`helpers/execution_plan.py`, `helpers/selection.py`, `helpers/git_changes.py`, `helpers/repo_files.py`) is
unchanged by the simplification: canonical selectors against a no-follow inventory, guarded membership by canonical path,
rename-aware Git change collection, reverse-import routing, gaps instead of widening, and `execution_plan.admit`
re-resolving the plan at the execution boundary.

Exit codes: 0 PASS for the requested scope, 1 FAIL, 2 BLOCKED, 3 NOT RUN or incomplete, 64 invalid invocation, 130
interrupted.

## What a PASS requires

Each stage runs under `helpers/winproc.py` `run_supervised`: a stage deadline and stall limit, a Windows kill-on-close Job
(macOS: a process group), the owned tree stopped at the end, and any remaining or surviving owned process reported as a
`cleanup` FAIL. Ordinary pytest starts as `python -u -s -m pytest` in a scrubbed environment: no `PYTHONPATH`,
`PYTHONHOME`, `PYTHONSTARTUP`, `PYTHONINSPECT`, `PYTHONUSERBASE`, user site, `PYTEST_*` overrides, real-engine opt-ins or
destination overrides (R3-01: the stage's interpreter starts clean). A pytest stage passes only when its exit status, its
JUnit report and the session probe (token, pid, collected, deselected and executed items) agree; a session whose initial
collection does not reconcile with what it kept and deselected fails. After a passing run, `requested-scope` reconciles
every requested item with the node ids that actually executed: a missing requested node never passes on a guard alone.
Unexpected skips, a timeout, a stall, an interruption or a missing stage outcome are visible non-passing results. Each run
records platform, interpreter, command, plan, candidate identity, results and cleanup in its own folder under `outputs/`.

## The routine guard

`files/tests/conftest.py` installs `files/tests/routine_effects.py` before any test module is imported, in every pytest
process of this checkout (gate stage or direct run):

- **Marker.** `ACT_VERIFY_CONTEXT=routine` is set in the process environment, so every ordinary child inherits it. The
  maintained heavyweight entrypoints check it themselves and refuse (`helpers/routine_context.py`
  `refuse_under_routine` in their `__main__`, `check_operation` inside the callables that start real work: the gate's
  acceptance and scenario stages, the scaling programs, the native adapters, the real test drivers). The check is in their
  own bytes, so a copy anywhere refuses as the original does.
- **Scrub.** `ACT_*_REAL` opt-ins and the destination overrides `ACT_P2_EVIDENCE`, `ACT_XHE_PROOF_APPLE_CAF`,
  `ACT_MAC_FFMPEG` are removed.
- **In-process refusals** (one audit hook): a non-loopback network connection or lookup, a model library reading a weight
  file outside the session's basetemp, resolving a native input function outside the gate's input adapter, `os.startfile`.
- **Declared boundaries.** A test calls `routine_effects.require(effect, ...)` immediately before real heavyweight work;
  `admitted()` is always False. Such tests are declared statically (`ACT_EFFECTS`) and routine plans withhold them.
- **Refusals fail.** A refusal raises `EffectRefused`; `conftest.py` fails the test that caused it even if the test
  caught it, and fails the session. `expected_refusals(effect)` marks a synthetic negative control's own refusals as
  expected; it grants nothing.
- **Synthetic gate fixtures.** A disposable tree inside the session's basetemp, declared in `act-synthetic-fixture.json`,
  may run its own copy of `verify.py` and start that tree's stand-ins (`files/tests/routine_recipes/`). A real runner copied
  there still refuses itself. The scripted acceptance stand-in creates every journey folder exclusively under a non-linked
  evidence folder and accepts only plain identifiers (R3-02).

Not covered, by design: a test that gives its child a replacement environment without the marker, native code, a shell
program's internals, a hostile process. Child processes are not intercepted, bootstrapped or accounted one by one: a test
asserts its own child's behaviour (exit codes, cancellation, cleanup), and the gate supervises the stage's whole tree.

## Guarded groups

`files/tests/guarded_groups.json` lists the guarded modules (`v3-planning`, `v3-supervisor`). They run only through the gate,
each group once, under `files/tests/guarded_pytest.py`: process-site pins by SHA-256, `ProcessPolicy` exact profiles,
write tripwire, network/model guard and the lifetime report through teardown. A guard finding fails its group even when
its tests passed. The guarded runner no longer stacks the routine envelope or a ledger verdict on top (simplification);
`conftest.py` still installs the routine guard inside it. A module that installs a synthetic wheel into a disposable venv
(the spaCy consumer control) runs only where that offline fixture installation is authorized.

## Heavyweight operations: owner authorization required

Never start, without the owner's explicit authorization for the named run (mode or scenario, platform, candidate): `--mode
full`; `--mode qualification --scenario`; any native GUI journey; real-engine synthesis or model loads; setup, installers,
optional-engine installs or repair against a real environment; network downloads; scaling, benchmarks and multi-hour
runs; release builds and packaging of distributable archives. Authorization covers the named run only, never a later one.
An agent never treats a failure of the cheaper checks as a reason to escalate on its own. Printing any plan is always
allowed.

A Windows full run's ordinary stage runs with the routine guard, so the declared heavyweight nodes of the release partition
(`test_root_lifetime.py`'s two application arms, the first-run force-quit test) refuse there; an owner-authorized full run
cannot PASS until the reduced Phase 1A-2 gives an authorized run a way to admit them. That admission, when a heavyweight
run first needs it, is deliberately small: one owner-supervised attempt, serialization across checkouts by an OS lock,
manual recovery after an interruption, no automatic crash recovery or delegated grants.

## Privacy and evidence identity

- **D-5 local-only paths** (`verification.json` `changed.local_only`: `.ai/`, `AI-WORKSPACE.md`, `AGENTS.md`, `CLAUDE.md`,
  `.claude/`, `.codex/`, `scripts/project-status.py`, `files/run-temp/`) are filtered out before any read, hash, rename
  detection or diagnostic. A tracked local-only path, or an in-scope path through a link, stops the run (`privacy`
  BLOCKED) with a count only; names are never written. `.codex/` was added on 2026-11-27 (R3-04).
- **Candidate identity.** Every run records HEAD, the tree fingerprint by digest class and the environment, compared at
  start and finish; a source edit during the run is not a PASS. Routine evidence never qualifies a different commit
  automatically; `--status --require-current` says `exact`, `docs-only` or `stale`.
- **Documentation does not invalidate executable evidence.** `md-instructions/`, `files/plans/`, `files/release-history/`,
  `README.md`, this `GATE.md` and the published review summaries in `files/codex-summary-for-remote-access/` are the
  `docs` digest class: publishing a report or editing this policy text makes a run `docs-only`, never `stale` (R3 evidence
  finding).

## Commands

Run from the repository root with the checkout's own interpreter (`.venv\Scripts\python.exe`; macOS `.venv/bin/python`).

| Command | What it does |
|---|---|
| `verify.py --mode quick` | Static checks and the import smoke. |
| `verify.py --mode focused --test files/tests/test_x.py [--test files/tests/test_y.py::test_name]` | The routine gate run of named tests. |
| `verify.py --mode focused --feature ACT.X.Y` | A feature's routine tests. |
| `verify.py --mode changed [--base REV]` | What the current change owes, run. Use `--plan` first to see gaps. |
| `verify.py --mode regression --component <id>` | A reviewed component set. |
| `verify.py --mode <any> ... --plan` | Prints the execution plan; runs and writes nothing. |
| `verify.py --status <run> [--require-current]` | Reads a finished run back, read-only. |
| `verify.py --evidence [--test ID]` | Bookkeeping over recorded runs; prints EVIDENCE, never RESULT. |
| `verify.py --audit-scratch` | Lists the scratch root's children; changes nothing. |
| `python -m pytest files/tests/test_x.py -q -p no:cacheprovider --basetemp files/run-temp/<short>` | A direct targeted run (rules below). |

**Direct pytest.** Allowed for modules that need no guarded runner, from the repository root so `pytest.ini` and
`conftest.py` load (never `--noconftest`, never `-p no:` a repository plugin). The routine guard is active; a direct run is
a developer check, the gate run is the verification evidence. Modules in `guarded_groups.json` run only through the gate.
Keep the basetemp short and under `files/run-temp/`. Include `test_application_source_boundary.py` when application
source changed. Count results from pytest's own summary or JUnit XML, never from a pipeline's exit code.

## Known limitations

- The gate needs the checkout's own real `.venv` (`guarded-specification` resolves a pinned numpy source inside it); a
  junction is refused by design. Real-environment work runs in `C:\ACT-Dev` (D-1).
- **Development environment (v0.8.2 Phase 4).** The checkout's `.venv` is uv's, built on the managed CPython 3.12.15 in
  `files/runtime-data/uv/python` with the **dev** profile: `python scripts/shared/bootstrap.py --profile dev` records the
  choice (it is never inferred from pytest) and every later sync keeps it. The gate's one pytest pin is the `dev` dependency
  group of the root `pyproject.toml` (`verify.py` `_pinned_pytest`, the interpreter preflight); `scripts/requirements.txt`
  and its hash locks are a frozen parity reference that the `deps` check still validates, held equal to `pyproject.toml`
  by `test_base_packages.py`, until the seam is removed. `C:\ACT-Dev` was migrated through the repair transaction on
  2026-11-27 (Handoff, Phase 4). macOS (Phase 4 macOS acceptance): a new uv dev environment
  (`cpython-3.12.15-macos-aarch64-none`) runs quick and focused gate runs; `conftest.py` excuses that interpreter's own first-import
  standard-library bytecode (`lib/python3.12`, tag from `lib/libpython3.12.dylib`) as it does on Windows. The macOS real-uv stage 0 test
  needs the pinned uv and CPython archives in `files/temp/bootstrap/` (policy `macos-pinned-archives-not-downloaded`).
- A changed plan that touches suite-wide test infrastructure (`changed.suite_wide`: `conftest.py`, the guard, the runners)
  selects representative controls and records a gap: it is INCOMPLETE by design and owes a component regression or named
  focused runs.
- Native macOS verification of the simplified routine path ran in Phase 3B (2026-11-27, HOME-MacOS): marker inheritance,
  stall and total-timeout supervision of the stage's process group, canonical routing on case-insensitive APFS and stage/JUnit
  reporting pass. Three defects found there (Phase 3B report §7) are **corrected in v0.8.2 Phase 4, Windows-verified and
  confirmed natively on HOME-MacOS** (Phase 4 macOS acceptance, 2026-11-27): **D1** Darwin answers `killpg` with EPERM while a killed group is exiting;
  `helpers/winproc.py` now treats `PermissionError` like `ProcessLookupError` around both `killpg` calls and polls
  `_group_alive` up to `kill_wait` before recording POSIX survivors (so no false `cleanup` FAIL and no raise before
  `results.json`). **D2** the exit-code verdict contract test plants the Windows-only `m4b-scaling` qualification and is now
  marked Windows-only (test portability). **D3** `helpers/scratch.py` had no POSIX process creation time; on POSIX an owner
  is now alive unless `kill(pid, 0)` says the process is gone (a reused pid errs towards "alive", never towards cleaning an
  active run's scratch). Native re-check: the ten Phase 3B selectors PASS with `cleanup` PASS (run
  `2026-11-27_192555_focused_5673`; D2's nine parameters skip by a policy-named reason) and `--audit-scratch` taken during that run lists
  it `active`.

## Approved scratch exception

`%TEMP%\act-gate` is the one owner-approved exception to repository-only scratch (2026-11-06, Decisions.md, v0.7.2 Phase
3). It covers gate-run children only: each carries `act-gate-owner.json` naming its run and process, and
`helpers/scratch.py` keeps the owner's conditions (only identified ACT scratch is created or cleaned, never another
application's files or an active run's, failed-run diagnostics copied into repository evidence, no general TEMP sweep).
Direct pytest runs do not use it. The exception is not widened by this policy.

## Retention and cleanup (v0.8.2 Phase 2)

Simple rules, applied by hand; nothing deletes historical evidence automatically and there is no cleanup service.

- **Own work.** Every agent removes its own disposable work (direct-run basetemps, probes, review bundles no longer needed)
  before it stops, and reports what it kept, what it removed and the space freed. The gate already removes its own
  `%TEMP%\act-gate` scratch after a clean run; `--audit-scratch` lists what is left there and changes nothing.
- **Gate evidence.** `outputs/` run folders and the guarded basetemps under `files/dev-work/p05b-stage4c/` are kept while a
  permanent document, the plan or a review cites them, and the newest run of each mode is always kept. Any other run folder
  is eligible for manual removal after 7 days. Soft budget: 2 GiB for those two folders together (about 0.93 GiB at
  Phase 2); over budget, report it at the checkpoint and remove only eligible folders of finished runs.
- **Never removed by an agent:** `dist/`, `files/Archives/`, `.venv/`, `files/runtime-data/`, `files/bin/`, user data and
  outputs, `files/test-files/`, the old worktree `files/dev-work/wt082` and the owner's listening evidence, another agent's
  scratch, an unknown path, an unreadable (ACL-locked) folder, a link or junction target. Unknown or unreadable means leave
  it and report it.
- **External locations.** Never create `C:\t\` scratch or another external basetemp without approval. The historical
  `C:\t\` folders (D-2) and the ACL-locked folders (D-3) wait for the owner. Check free disk space before an expensive run.

Phase 2 removed the four obsolete `files/dev-tools/*` programs that nothing imports; the other 13 the entrypoint table calls
obsolete stay, because a maintained tool or a test that runs production code imports them.

Still open from earlier phases: `scripts/requirements.txt`'s dev/test comment names the retired gate path; Phase 4 left
it unchanged on purpose (the file is now a frozen parity reference whose bytes its v0.8.1 hash locks record; it goes with
the seam, Handoff seam table); `coverage.require_reviewed_inventory` and the `source_review` stamps (moved off the routine
path; Phase 2 or later).

Consumers of the five-document contract: `verify.py` `CANONICAL_DOCS` and `check_doc_names`;
`files/tests/test_repository_contract.py`; `files/tests/test_plan3_boundaries.py`; the synthetic tree of
`files/tests/test_verification_gate_contract.py`; `files/tests/test_verify_evidence.py`; Briefing's contract paragraph.

## Next

Phase 4 (production uv-based base provisioning) is committed with the D1-D3 corrections above and accepted natively on both
platforms (macOS: 2026-11-27); next is the small Windows regression the macOS corrections owe (Handoff), then Phase 5A, on its own
prompt. The reduced Phase 1A-2 admission is built only when the first genuinely needed heavyweight run requires it. See the plan's "Verification simplification"
amendment for the consolidated checkpoint dispositions.
