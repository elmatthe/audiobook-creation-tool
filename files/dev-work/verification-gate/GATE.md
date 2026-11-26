# ACT verification gate — policy and command reference

This is the authoritative ACT-specific verification policy. General verification guidance (the AI Workspace's, kept
local-only) defers to this file; the module docstring and `--help` of `verify.py` describe what each mode *does*, this
file says which of them an agent may *start*. Plan: `files/plans/Developer-Experience-Upgrade.md` (§5; Phase 1A,
Revision 5: 1A-1, 1A-2, 1A-3).

**Status: v0.8.2 Phase 1A-1.** Every request now resolves into one explicit execution plan, `changed` selection reads Git
and routes through the reverse import closure, and routine pytest runs inside a restricted envelope that refuses
heavyweight effects. **The interim restrictions on heavyweight execution stay in force** until Phase 1A-2 (admission: the
machine-wide lock of decisions A5-W/A5-M and the single-attempt authorization of A6-R) and Phase 1A-3 (execution and
evidence of the plan-only modes). Nothing in 1A-1 grants or activates a heavyweight run.

## Modes: what each resolves to and what executes now

| Request | Plan (resolved before anything runs) | Executes in 1A-1 |
|---|---|---|
| `--mode quick` | The fixed static checks of `verification.json` `quick.checks` (docnames, docs, doc-links, JSON validity, deps, config, import smoke). | No: prints its plan (exit 3) until 1A-3. |
| `--mode focused --test <id> [...]` | The named selectors plus the required guard. A declared heavyweight node asked for by name is withheld and the plan is INCOMPLETE; a mixed module asked for whole runs its routine tests and lists the heavyweight ones as obligations. | **Yes, routine.** |
| `--mode focused --feature <id> [...]` | The feature's routine tests plus the guard; its journeys, media, qualification and owner checks are listed as obligations, never run. | No: plan only until 1A-3. |
| `--mode changed [--base REV]` | HEAD against staged, unstaged and untracked work (with `--base`, also the committed side since the merge base of REV and HEAD), routed tests, static checks, guards, gaps and obligations. | No: plan only until 1A-3. |
| `--mode regression --component <id> [...]` | The reviewed components of `verification.json` `regression.components`, expanded through their features. No unnamed or `all` regression. | No: plan only until 1A-3. |
| `--mode qualification --scenario <name>` | One named scenario (with `--network <policy>` only where the scenario declares it). | Only with the **owner's authorization for that run** (interim rule). |
| `--mode qualification --journey <id> [...]` | A set of registered native journeys. | No: plan only until 1A-3; then owner authorization. |
| `--mode full` | The complete release partition: every journey, the whole ordinary suite, every guarded group, the static gates, the collection partition, the inventory and the self-tests. The only plan that names the whole suite. | Only with the **owner's authorization for that run** (interim rule). |
| any of the above `--plan` | Resolve and print the plan as JSON; run nothing, write nothing. Exit 3 (2 when the plan targets another platform). | Data only. |
| `--status`, `--evidence`, `--audit-scratch`, `--help` | Read-only readers. | Data only. |

Removed behaviour, refused with a clear message: `--mode focused --journey` (exit 64; a focused run never starts a
journey, use `--mode qualification --journey`); the `changed-conservative-full` widening (an unresolved path is a
selection gap, never the whole suite); the `origin/master` default base (the default anchor is HEAD); an empty or unknown
selector, an unknown feature, component, journey or scenario, `--component` outside regression, `--base` outside changed,
qualification with neither or both of `--scenario` and `--journey`, `--plan` with `--preflight-only`/`--collect-only`
(all exit 64 before anything exists).

**Plan status** (`PLAN:` line and `selection.json`): COMPLETE (every requested item resolves to executable work;
obligations may still be pending and are listed as pending), INCOMPLETE (a requested test is withheld, a selection gap is
unresolved, or only an added guard would run), NOT RUN (nothing relevant, e.g. changed with no relevant change), BLOCKED
(another native platform). A plan is never a PASS. An executed run whose plan is not COMPLETE runs nothing and reads
NOT RUN. Run exit codes are unchanged: 0 PASS for the requested scope, 1 FAIL, 2 BLOCKED, 3 NOT RUN or incomplete, 64
invalid invocation, 130 interrupted.

**Changed selection** (`helpers/git_changes.py`, `helpers/selection.py`): NUL-delimited, rename-aware name-status
(both rename paths, staged reversal kept and noted, case-only renames, staged delete and recreate, untracked files
anywhere outside ignored roots); unresolved conflicts, an unknown, ambiguous or unrelated base, and several best merge
bases are refused. Owner-declared local-only paths (`changed.local_only`) are excluded while untracked and reported by
entry and count only; a tracked change there is a policy violation (a gap). Links and reparse points are never followed.
Routing: a changed test selects itself (a deleted test never satisfies itself: its features' surviving tests, or a gap);
Python source selects its reverse import consumers (built once per snapshot from `helpers/evidence_ledger.py`) and its
reviewed feature tests; documents, configuration and launchers route to static checks and obligations; suite-wide test
infrastructure selects representative controls and records a gap; a module reached by more test modules than
`changed.max_routed_modules` keeps its reviewed tests and becomes a gap with a component regression owed; a parse failure,
an unreached source or an unknown path is a gap; platform-specific paths owe the other platform. Nothing widens. The
selection identity (`candidate_identity`) binds the checkout, HEAD, the index entries, the working bytes or deletion
markers and the policy digest; it is not the Phase 1B evidence fingerprint.

## Interim rule (still in force)

During ordinary implementation, never start, without the owner's explicit authorization for the named run (mode or
scenario, platform, candidate): `--mode full`; `--mode qualification --scenario`; any native GUI journey; real-engine
synthesis or model loads; setup, installers, optional-engine installs or repair against a real environment; network
downloads; scaling, benchmarks and multi-hour runs; release builds and packaging of distributable archives. Authorization
covers the named run only. An agent never treats a failure of the cheaper checks as a reason to escalate on its own.
Printing any plan (`--plan`, or a plan-only mode) is always allowed.

Allowed, after inspecting what the selected tests do: `verify.py --mode focused --test <path or node id> [--test ...]`,
and a narrowly targeted direct pytest run (rules below). Use `--mode changed --plan` (or `--feature ... --plan`,
`--component ... --plan`) to see what a change owes, then run its routine tests with `--test`.

## The routine envelope (Phase 1A-1)

Every pytest process of this checkout is a routine verification process.

- **Bootstrap.** The gate starts ordinary pytest as `files/tests/routine_pytest.py <pytest args>`, which installs
  `files/tests/routine_effects.py` before pytest, its plugins, `conftest.py` or any test module is imported, and disables
  third-party plugin autoload. `files/tests/conftest.py` installs the same envelope for raw pytest runs, and `pytest.ini`
  passes `--disable-plugin-autoload`. Guarded groups keep `guarded_pytest.py` (unchanged) with the same envelope from
  `conftest.py`.
- **Scrubbed.** Real-engine opt-ins (`ACT_*_REAL`, for example `ACT_KOKORO_P2_REAL`, `ACT_OMNIVOICE_P1_REAL`) and the
  destination overrides `ACT_P2_EVIDENCE`, `ACT_XHE_PROOF_APPLE_CAF`, `ACT_MAC_FFMPEG` never reach a test or a child; the
  gate's stage environment scrubs them too. They never grant anything on their own.
- **Nothing grants a heavyweight effect.** `routine_effects.admitted()` is always False until Phase 1A-2; there is no
  `--mock` flag, no environment-variable bypass and no "under pytest" grant.
- **Declared boundaries refuse.** A test that reaches a real heavyweight boundary declares it once, in a module-level
  literal the gate reads statically, and calls `routine_effects.require(effect, detail)` immediately before the real
  operation. Effects: `native-desktop`, `real-app-launch`, `real-engine`, `external-network`, `install`, `scaling`,
  `release-build`.

  ```python
  import routine_effects
  ACT_EFFECTS = {"test_real_clone_proof": ("real-engine",)}      # or {"*": (...)} for the whole module

  def test_real_clone_proof():
      routine_effects.require("real-engine", "loads the multi-gigabyte model")
      ...
  ```

  A pytest marker or a file name classifies nothing. Declared now: `test_macos_p1b_gui_containment.py` (whole module),
  `test_macos_p2_kokoro_real.py` (whole module), `test_omnivoice_phase1.py::test_real_clone_proof`, the two application
  arms of `test_root_lifetime.py`, and `test_first_run_setup_ownership.py::test_force_quitting_the_first_run_window_ends_its_worker_pip_and_helper`.
- **Unclassified boundaries are gaps.** `helpers/effects.py` flags test modules showing a live-boundary indicator (a
  real-engine opt-in name, a real driver program, a multi-line child program that opens the real window, an import of
  the gate's native adapters or runner, native input calls) that neither declare effects nor are reviewed in
  `verification.json` `effects.reviewed_bounded`; such a module is withheld as a selection gap.
  `test_execution_plan.py` keeps the real suite free of unclassified boundaries.
- **Launches are classified** (an audit hook on `subprocess.Popen`, `os.system`, `os.startfile`, `os.spawn*`,
  `os.exec*`, `os.posix_spawn`): starting a classified heavyweight entrypoint of this checkout by its real path, any
  interpreter of a real engine environment, a package manager or installer, an online `pip install`, `os.startfile` or a
  desktop hand-off is refused before the process exists. Only an interpreter's or a shell's script argument is treated as
  a script. Data-only invocations and reviewed bounded fixtures are allowed. A disposable copy a test makes outside the
  checkout is the test's own and is judged by that test's classification.
- **Every executable entrypoint is classified** (`verification.json` `entrypoints`, decision ENTRY): active,
  maintained, obsolete, bounded or support, with its routine disposition (refused, data-only, bounded) and effects.
  Discovery of `__main__` blocks under the gate, `files/dev-tools` and the test helpers keeps the table complete
  (`test_execution_plan.py`). The maintained heavyweight roots (`acceptance_runner.py`, `qualification/*` through
  `common.start`, `qualification/fresh_copy.py`, `scaling/*`, the test drivers and manual harnesses) refuse to start
  under the inherited `ACT_VERIFY_CONTEXT=routine` marker themselves (`helpers/routine_context.py`), because a child
  Python has no audit hook. `verify.py` refuses to execute a run against this checkout inside routine verification;
  reading and planning stay available.
- **A refusal cannot be swallowed.** Each refusal is recorded in memory and in the stage's effect ledger
  (`ACT_EFFECT_LEDGER`, inherited by children). `conftest.py` errors the test that caused it in any phase, and fails the
  session for one outside any test; `routine_pytest.py` fails the process for one after the session ended (an `atexit`
  callback); the gate's `routine-effects` check fails the run for any refusal in any stage.

**Limitations, stated plainly.** This makes accidental heavyweight execution from supported routine paths fail closed;
it is a cooperating-verification control, not an operating-system sandbox. A child given a replacement environment (no
marker, a private ledger) or arbitrary code in an unrestricted shell is outside what a test process can enforce. Static
classification cannot certify every dynamic launch. Non-loopback sockets are not refused globally (the existing
download, bootstrap and Qwen3 guards stay); an ambient offline setting for model hubs is not imposed because tests assert
that production code sets it. These are Phase 1A-2/1A-3 items.

## Compatibility seams (each with its removal criterion)

| Seam | Removed when |
|---|---|
| `full` and `qualification --scenario` execute under the interim owner-authorization rule, outside the new admission (the resolver marks them executable; admission does not exist yet). | Phase 1A-2 admission (lock and single-attempt authorization) gates them. |
| A full run's ordinary stage runs inside the routine envelope, so the declared heavyweight tests in the release partition (`test_root_lifetime.py`'s two application arms and the first-run force-quit test on Windows) are refused and fail that run; the real-engine opt-in tests skip under their existing permitted skip rules. An owner-authorized Windows full run cannot PASS until then. | Phase 1A-2 delegates an authorized full run's admission to its stage. |
| `quick`, `changed`, `regression`, `focused --feature` and `qualification --journey` resolve and print their plans only. | Phase 1A-3 integrates their execution and evidence. |
| `selection.json` keeps the legacy keys `kind`, `ordinary`, `guarded`, `journeys`, `requested` beside `"format": "execution-plan/1"` (`ordinary` is now a list, never null). | Phase 1B's evidence schema. |
| `--evidence` rerun suggestions print qualification journey lines as plan-only. | Phase 1A-3. |

None of these is less safe than the interim policy: each either keeps the owner-authorization rule or refuses more.

## Safe current commands

Run from the repository root with the checkout's own project interpreter (`.venv\Scripts\python.exe`; macOS
`.venv/bin/python`).

| Command | What it does |
|---|---|
| `verify.py --mode focused --test files/tests/test_x.py [--test files/tests/test_y.py::test_name]` | The routine gate run. PASS covers only that scope. |
| `verify.py --mode <any> ... --plan` | Prints the execution plan; runs and writes nothing. |
| `verify.py --mode focused --test ... --preflight-only` / `--collect-only` | Preflight only, or collection of the named selection; runs no test and establishes nothing. |
| `verify.py --status <run> [--require-current]` | Reads a finished run back, read-only. |
| `verify.py --evidence [--test ID]` | Bookkeeping over recorded runs; prints EVIDENCE, never RESULT. Its suggestions are subject to this policy. |
| `verify.py --audit-scratch` | Lists the scratch root's children; changes nothing. |
| `python files/tests/routine_pytest.py files/tests/test_x.py -q -p no:cacheprovider --basetemp <short dir>` | Direct targeted run inside the routine envelope (below). |

**Direct pytest rules.** Use it only for modules that need no guarded runner. Run from the repository root so
`pytest.ini` and `files/tests/conftest.py` load; their guards and the routine envelope stay active (never `--noconftest`,
never `-p no:` a guard plugin, never `-I`). `routine_pytest.py` establishes the envelope before collection; plain
`python -m pytest` gets it from `conftest.py`. Modules listed in `files/tests/guarded_groups.json` run only through the
gate. A module with declared heavyweight tests fails closed when run whole directly (its declared tests are refused):
select its routine nodes through the gate, which expands it. Include `files/tests/test_application_source_boundary.py`
when application source changed, and the tree-reading meta-guards when tests or tracked Markdown changed. Keep the
basetemp short; modules that build nested git repositories (`test_verification_gate_contract.py`, most of
`test_verify_evidence.py`, the Git cases of `test_execution_plan.py`) need it outside the repository. Count results from
pytest's own summary or JUnit XML, never from a pipeline's exit code.

## Known execution limitations

- **The gate needs the checkout's own real `.venv`.** Preflight's `guarded-specification` check resolves the reviewed
  process sources of `guarded_groups.json`, one of which is `.venv/Lib/site-packages/numpy/...` relative to the
  checkout. A checkout without its own `.venv` (the nested `files/dev-work/wt082` worktree, a fresh clone) fails
  preflight in every mode. Do not satisfy it with a junction: product link checks refuse linked environments by design.
- **Nested git fixtures need a short basetemp outside the repository** (see above); the gate places them in the approved
  scratch root.
- **Worktree path depth.** `files/dev-work/wt082` has a 123-character root; docs and static work only there.
- **D-1 (approved 2026-11-25): `C:\ACT-Dev`** is the permanent short-path development clone for real-environment
  verification (its own real root `.venv/`); a development location only, never a production dependency.

## Heavyweight operations: owner authorization required

Each needs explicit owner authorization for that run: full and qualification gates; any native GUI journey; real-engine
synthesis or model loads; setup, installers, optional-engine installs or repair runs against a real environment;
network downloads; scaling, benchmarks and multi-hour runs; release builds and packaging of distributable archives.
Authorization covers the named run only, never a later one. Phase 1A-2 replaces this prose with enforced admission:
a native machine-wide lock (Windows A5-W; macOS A5-M blocked until a native proof and owner approval) and owner-issued,
single-attempt authorization records (A6-R).

## Approved scratch exception

`%TEMP%\act-gate` is the one owner-approved exception to repository-only scratch (2026-11-06, Decisions.md, v0.7.2 Phase
3). It covers gate-run children only: each carries `act-gate-owner.json` naming its run and process, and
`helpers/scratch.py` keeps the owner's conditions (only identified ACT scratch is created or cleaned, never another
application's files or an active run's, failed-run diagnostics copied into repository evidence, no general TEMP sweep).
Direct pytest runs do not use it. The exception is not widened by this policy.

## Conflicting instructions and call sites

Resolved in Phase 1A-1: `select()` and its `routine` profile label for full (the full summary now says "the full release
partition of this checkout"), `_focused_journeys` (`--feature` lists journeys as obligations), `_changed_selection` and
`helpers/selection.py` `conservative_full`/`full_on` (removed; `journeys_for_changes` now yields suggested obligations),
`verification.json` `changed.full_on` (removed) and `acceptance.journey_routes` (obligations only), the evidence ledger's
`--journey` rerun lines (now qualification, plan only), and step 4 of `files/dev-work/feature-map/README.md`.

Still open: `scripts/requirements.txt` (its dev/test comment names the retired gate path; byte-locked into setup, so it
waits for the next dependency change, Phase 4); `coverage.require_reviewed_inventory` and the `source_review` stamps
(Phase 1B); local-only workspace files that still describe the old modes (reconciled locally).

Consumers of the five-document contract: `verify.py` `CANONICAL_DOCS` and `check_doc_names`;
`files/tests/test_repository_contract.py`; `files/tests/test_plan3_boundaries.py`; the synthetic tree of
`files/tests/test_verification_gate_contract.py`; `files/tests/test_verify_evidence.py`; Briefing's contract paragraph.

## Cleanup obligations recorded for Phase 2

The entrypoint table classifies 17 `files/dev-tools/*` programs as obsolete (historical evaluation and macOS-phase
tools); they are refused in routine verification and are Phase 2 removal candidates after their still-cited facts move.
The old `files/dev-work/wt082` worktree, the `C:\t\` scratch (D-2), the ACL-locked folders (D-3) and the owner's
listening evidence stay untouched until Phase 2's classified cleanup. Free disk on HOME-PC is about 7 GiB: check it
before any expensive run.

## Next

- **Phase 1A-2:** heavyweight admission. The machine-wide lock (A5-W: a native Windows kernel object with machine-wide
  semantics and a protected recovery control directory in the development checkout, one authority shared by every
  checkout, fail closed, no checkout-local fallback; A5-M: macOS stays blocked until a shared developer-only lock
  location in a stable machine-common domain has a native proof and owner approval), single-attempt authorization records
  (A6-R), process-tree delegation of an admission to its stages, run-wide deadlines.
- **Phase 1A-3:** execution and evidence of `quick`, `changed`, `regression`, `focused --feature` and
  `qualification --journey`; preflight cost estimates and budgets; dropping the plan-only seams.
