# ACT verification gate — policy and command reference

This is the authoritative ACT-specific verification policy. General verification guidance (the AI Workspace's, kept
local-only) defers to this file; the module docstring and `--help` of `verify.py` describe what each mode *does*, this
file says which of them an agent may *start*. Plan: `files/plans/Developer-Experience-Upgrade.md` (§5, Phase 1A).

**Status: interim policy, in force from v0.8.2 Phase 0A until Phase 1A** implements safe execution controls (six
proportional modes, no GUI escalation from routine modes, owner consent and a machine-wide lock). Phase 1A replaces the
interim sections below in the same commit that changes the gate.

## Interim rule

During ordinary implementation, never invoke:

| Invocation | Why it is unsafe today |
|---|---|
| `--mode full` | Runs every native GUI journey first (it takes over the mouse and keyboard), then the whole suite (about 17,800 tests, 1.5 to 2 h on HOME-PC), every guarded group and the inventory checks. |
| `--mode qualification` | Runs one expensive named scenario: real engines, network, fresh installs or multi-hour scaling. |
| `--mode changed` | Routes changed paths to native journeys (`acceptance.journey_routes`; any `scripts/` change pulls `inventory.live-surfaces`), and any `scripts/shared/` change, requirement, conftest, guard module or unmapped path widens it to `changed-conservative-full`: the whole suite plus all journeys. |
| `--mode focused --feature <id>` | Appends the feature's registered native GUI journeys to the selection. |
| `--journey <id>` (any mode, focused included) | Starts a native GUI journey in a real application instance. |

These need the owner's explicit authorization for the specific run (mode or scenario, platform, candidate). An agent
never treats a failure of the cheaper checks as a reason to escalate to them on its own.

Allowed instead, after inspecting what the selected tests do:

1. `verify.py --mode focused --test <path or node id> [--test ...]`: explicitly named selectors only. The gate adds the
   required guard (`files/tests/test_application_source_boundary.py`), routes any module of
   `files/tests/guarded_groups.json` through `files/tests/guarded_pytest.py` itself, keeps scratch in the approved root
   below and seals evidence under `outputs/`. With `--test` alone the acceptance stage reads NOT APPLICABLE: no journey
   runs.
2. A narrowly targeted direct pytest run (below) when the gate cannot run in the current checkout.

Before executing any test, inspect whether it can start the GUI, a real engine, a network download, an installer or
another heavyweight operation. If it can, it needs authorization like the modes above.

## Safe current commands

Run from the repository root with the checkout's own project interpreter (`.venv\Scripts\python.exe`; macOS
`.venv/bin/python`).

| Command | What it does |
|---|---|
| `verify.py --mode focused --test files/tests/test_x.py [--test files/tests/test_y.py::test_name]` | The routine gate run. PASS covers only that scope. |
| `verify.py --mode focused --test ... --preflight-only` | Preflight only (policy, identity, guarded specification, interpreter pin, process ownership, error mode); runs no test. |
| `verify.py --mode focused --test ... --collect-only` | Collects the named selection; runs nothing and establishes nothing. |
| `verify.py --status <run> [--require-current]` | Reads a finished run back, read-only. |
| `verify.py --evidence [--test ID]` | Bookkeeping over recorded runs; prints EVIDENCE, never RESULT. The rerun commands it suggests are subject to this policy: a suggested `--journey` still needs authorization. |
| `verify.py --audit-scratch` | Lists the scratch root's children; changes nothing. |
| `python -m pytest files/tests/test_x.py -q -p no:cacheprovider --basetemp files/run-temp/<short-id>` | Direct targeted run (below). |

**Direct pytest rules.** Use it only for modules that need no guarded runner and build no nested git repository under
`tmp_path`. Run from the repository root so `pytest.ini` and `files/tests/conftest.py` load: their guards stay active
(never `--noconftest`, never `-p no:` a guard plugin, never `-I`). Modules listed in `files/tests/guarded_groups.json`
run only through the gate (`guarded_pytest.py`), never directly. Include `files/tests/test_application_source_boundary.py`
when application source changed, and the tree-reading meta-guards when tests or tracked Markdown changed (for example
`files/tests/test_verification_gate_contract.py::test_no_active_caller_depends_on_the_retired_gate_path`). Keep the
basetemp short and inside the repository (`files/run-temp/<short-id>`), and remove it afterwards. Count results from
pytest's own summary or JUnit XML, never from a pipeline's exit code.

## Known execution limitations

- **The gate needs the checkout's own real `.venv`.** Preflight's `guarded-specification` check resolves the reviewed
  process sources of `guarded_groups.json`, one of which is `.venv/Lib/site-packages/numpy/...` relative to the
  checkout. A checkout without its own `.venv` (the nested `files/dev-work/wt082` worktree, a fresh clone) fails
  preflight in every mode, so focused runs read FAIL there for an environment reason. Do not satisfy it with a junction:
  product link checks refuse linked environments by design, so a junction only moves the failure.
- **Nested git fixtures need a short basetemp outside the repository.** `test_verification_gate_contract.py` (its
  synthetic gate trees) and most of `test_verify_evidence.py` `git init` throw-away repositories below `tmp_path`. Git is
  not long-path aware by default, so a basetemp inside a deep checkout fails them for path length, not for a defect. The
  gate places them in the approved scratch root; a direct run cannot, so in a checkout where the gate cannot run they
  are NOT RUN until a D-1 location exists.
- **Worktree path depth.** `files/dev-work/wt082` has a 123-character root (the primary checkout 102). There, 22 guarded
  cases fail "disposable consumer process cwd exceeds Windows bound", optional-engine installs exceed their path limits
  and NLTK/model data is absent. Docs and static work only; no real-environment, guarded or depth-sensitive run there.
- **D-1 (approved 2026-11-25): `C:\ACT-Dev`** is the permanent short-path development clone for real-environment verification (its own real root `.venv/`).
  Run the gate, guarded groups and the nested-git-fixture modules there. Every limitation above still applies to a checkout that has no real `.venv` or a deep path.

## Heavyweight operations: owner authorization required

Each needs explicit owner authorization for that run: full and qualification gates; any native GUI journey; changed
runs (until Phase 1A); real-engine synthesis or model loads; setup, installers, optional-engine installs or repair runs
against a real environment; network downloads; scaling, benchmarks and multi-hour runs; release builds and packaging of
distributable archives. Authorization covers the named run only, never a later one.

## Approved scratch exception

`%TEMP%\act-gate` is the one owner-approved exception to repository-only scratch (2026-11-06, Decisions.md, v0.7.2 Phase
3). It covers gate-run children only: each carries `act-gate-owner.json` naming its run and process, and
`helpers/scratch.py` keeps the owner's conditions (only identified ACT scratch is created or cleaned, never another
application's files or an active run's, failed-run diagnostics copied into repository evidence, no general TEMP sweep).
Direct pytest runs do not use it. The exception is not widened by this policy.

## Instructions and call sites that conflict with this policy (inventory for Phase 1A)

Corrected in Phase 0A: the `verify.py` module docstring (full described as "the routine gate"), the CLI epilog ("full
is the routine gate"), and step 4 of `files/dev-work/feature-map/README.md` (`--feature`, then a changed run).

Still in code or data, deliberately left for Phase 1A because they are behaviour, pinned output or byte-locked:

| Where | What |
|---|---|
| `verify.py` `select()` (`self.scope["profile"] = "routine"` for full) and the summary line "scope: routine gate only" | Labels a full run "routine" in its evidence. |
| `verify.py` `_focused_journeys` | `--feature` appends the feature's journeys. |
| `verify.py` `_changed_selection`; `helpers/selection.py` `journeys_for_changes`, `conservative_full` (`full_on`, unmapped paths) | Changed runs reach journeys and widen to the whole suite. |
| `verification.json` `acceptance.journey_routes`, `changed.full_on`, `coverage.require_reviewed_inventory` | The policy data behind the two rows above; a stale review stamp fails changed runs. |
| `helpers/evidence_ledger.py` (rerun command builder) | Suggests `--journey` reruns. |
| `scripts/requirements.txt` (dev/test comment) | Names the retired gate path; byte-locked into setup, so it waits for the next dependency change (Phase 4). |
| Local-only workspace files (AI Workspace shared rules; the primary checkout's stale Claude Code adapter) | Describe the full gate as routine before pushing, or name the retired gate path. Not tracked; reconciled locally (Handoff). |

Consumers of the documentation contract (exact-four until Phase 0A, five documents since): `verify.py` `CANONICAL_DOCS`
and `check_doc_names`; `files/tests/test_repository_contract.py`; `files/tests/test_plan3_boundaries.py`
(`test_only_the_five_canonical_documents_keep_their_exact_names`); the synthetic tree of
`files/tests/test_verification_gate_contract.py`; `files/tests/test_verify_evidence.py` (records the real `docnames`
answer); Briefing's contract paragraph. The doc-content pins Phase 0B must respect are listed in the plan (§ Verified
baseline).

## Planned Phase 1A changes

From the plan (§5 and Phase 1A), not implemented yet: add `quick` and `regression`; focused and changed never reach the
GUI (journeys become displayed obligations, `--journey` a qualification selector); remove `changed-conservative-full`
(an unresolved route is a selection gap, never a silent widening); changed defaults to HEAD against the working tree with
explicit `--base`, rename and deletion detection and untracked files outside ignored roots; routing through the
evidence ledger's import closure; preflight prints scope, estimated cost and budget; wall and idle budgets; owner-issued
scoped consent (A6) and a machine-wide heavyweight lock (A5) enforced at every heavy entrypoint (`verify.py`
qualification and full, `acceptance_runner.py`, `qualification/*`, `scaling/*`); stable exit codes and clear errors for
removed behaviour. Phase 1A rewrites this file, and drops the interim "never changed" rule only once changed is safe.
