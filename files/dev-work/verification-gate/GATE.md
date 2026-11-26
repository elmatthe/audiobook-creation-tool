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

**R1 correction (2026-11-25).** Phase 1A-1 failed independent review; its R1 remediation corrected the contracts below
(selector identity, requested-scope reconciliation, authoritative plan admission, the routine child-launch contract, the
common early envelope and fail-closed refusal accounting). The architecture (Revision 5) is unchanged; the record is in the
plan's "1A-1 R1" amendment and in Handoff.

## Modes: what each resolves to and what executes now

| Request | Plan (resolved before anything runs) | Executes in 1A-1 |
|---|---|---|
| `--mode quick` | The fixed static checks of `verification.json` `quick.checks` (docnames, docs, doc-links, JSON validity, deps, config, import smoke). | No: prints its plan (exit 3) until 1A-3. |
| `--mode focused --test <id> [...]` | The named selectors plus the required guard. The requested module or node is the scope (R1): a declared heavyweight node asked for by name, or held by a module asked for whole, is withheld by its exact id and the plan is INCOMPLETE; a nonexistent module or node is a `missing` gap. Select a mixed module's routine nodes by name. | **Yes, routine.** |
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
NOT RUN.

**Requested scope (R1).** Explicit `--test` module: the whole module is the scope; withheld heavyweight nodes are disclosed
and the scope is incomplete. Explicit `--test` node: validated before any whole-module deduplication (function, class and
method heads statically; parametrized and generated ids after the run); a nonexistent or withheld node never disappears.
Feature or component: a scoped plan may list heavyweight obligations separately while its routine behavioural coverage
stays complete; a feature whose behavioural tests are all withheld, or mapped to a missing file, is a gap. Changed:
unresolved mappings, missing required tests or withheld work prevent a complete plan. A guard alone never satisfies
requested behavioural work. After a passing run, `requested-scope` reconciles every requested item with the node ids the
session actually executed.

**Admission (R1).** At the execution boundary the gate re-resolves the plan from the authoritative request (this command
line) under the current policy, guarded membership, effect classification and candidate, and admits the plan only if it
is exactly that plan (`execution_plan.admit`); `validate` independently refuses omitted guards, guarded modules in
ordinary pytest, wrong guarded paths, overlapping identities, a scope that is not what runs, an item both withheld and
executable, unrepresented requested work, plan-only modes marked executable and whole-suite selection outside `full`. Plan
fields are immutable; supplemental facts cannot overwrite record fields. A source edit between resolution and admission
makes the run `selection` NOT RUN.

**Selector identity (R1).** Every selector is canonicalized against a no-follow, contained inventory of the checkout
(`helpers/repo_files.py`) before classification, normalization, guarded membership, deduplication, validation and
evidence: separators and `./` are normalized, a case variant resolves to the on-disk spelling where the filesystem folds
case (NTFS, default APFS) and is a different, missing file where it does not, ambiguous aliases and links or reparse points
are refused, and guarded membership matches the canonical path `files/tests/<module>`, never a basename. `_ordinary_scope`
refuses a guarded module in ordinary pytest independently of the plan. Run exit codes are unchanged: 0 PASS for the requested scope, 1 FAIL, 2 BLOCKED, 3 NOT RUN or incomplete, 64
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

R1 corrections: one contained, no-follow inventory serves candidate identity, AST discovery, the dependency closure,
effect classification, selector existence and routing, and nothing classified unsafe is read afterwards (unreadable,
unsupported or unstable paths are gaps; this is not race-free containment against a hostile concurrent writer).
Local-only matching follows the filesystem's case rule, both separators and component boundaries, and inspects the index
(`git ls-files`), so an already-tracked local-only path is a violation even with no delta; private names never reach the
record. A staged deletion with a recreated working file keeps both facts and routes the working file. Unparsed or unsafe
test-reachable helpers, ambiguous imports and missing mapped tests are gaps; imports of computed names are counted in a
routing note. Every plan's candidate (`git_changes.selection_identity`) binds the working bytes of every relevant changed and
untracked path; it is diagnostic and says so (`limitation`): Phase 1A-2 must bind a grant to the candidate bytes, the
policy and the scope.

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

## The routine envelope (Phase 1A-1, corrected in R1)

Every pytest process of this checkout is a routine verification process. The shared contract -- marker names, launch
roots, data-only argument shapes, the synthetic-fixture rule, the operation check and the effect-ledger format -- has one
home, `helpers/routine_context.py` (standard library only); `files/tests/routine_effects.py` enforces it in pytest
processes.

- **Supported invocations.** `files/tests/routine_pytest.py <pytest args>` (ordinary pytest: the gate's ordinary stages
  and a direct targeted run) and `files/tests/guarded_pytest.py` (the guarded groups, through the gate). Both call the
  same early setup, `routine_effects.bootstrap`, before pytest, its plugins, `conftest.py` or any test module is imported:
  third-party plugin autoload off, opt-ins and overrides scrubbed, the launch, network, model-weight and native-input checks
  installed, and the session's accounting opened in its effect ledger. The guarded runner installs its own stronger hooks
  first and keeps its process-site, write-tripwire, network/model and lifetime-report contracts; its lifetime report now
  carries `routine_accounting`, which also decides its exit status. A raw `python -m pytest` still gets the restrictions
  from `conftest.py`, but only after its plugins loaded and with its accounting opened at session start; it prints that it
  is not verification evidence, and it is not a supported verification invocation.
- **Scrubbed.** Real-engine opt-ins (`ACT_*_REAL`), the destination overrides `ACT_P2_EVIDENCE`, `ACT_XHE_PROOF_APPLE_CAF`,
  `ACT_MAC_FFMPEG`, and an inherited disposable-root marker never reach a test or a child. They never grant anything.
- **Nothing grants a heavyweight effect.** `routine_effects.admitted()` is always False until Phase 1A-2; no `--mock`
  flag, no environment-variable bypass, no "under pytest" grant.
- **Declared boundaries refuse** (`ACT_EFFECTS` plus `routine_effects.require`, as before), and so do the operations where
  an audit event exists: a non-loopback `socket.connect`/`getaddrinfo`/`sendto`/`bind`; reading a model-weight file
  (`.pt .pth .safetensors .onnx .ckpt .gguf`) outside the session's disposable roots; resolving `SendInput` and its kin
  (`ctypes.dlsym`) outside the gate's own native-input adapter; `os.startfile`. Importing a library (torch, spaCy, Kokoro)
  is not an effect; loading real weights is.
- **Operation checks in the gate's own callables** (`routine_context.check_operation`), not only in `__main__`: the
  acceptance runner before its desktop lease, the native-input sender before `SendInput`, every scaling program's `main()`
  after argument parsing, and the gate itself before it starts the acceptance runner or a qualification runner.
- **Launches are classified** (`subprocess.Popen`, `os.system`, `os.exec*`, `os.spawn*`, `os.posix_spawn`) by the program
  actually started (an `executable=` override, not `argv[0]`), its arguments, working directory and environment:
  - a heavyweight entrypoint (the `LAUNCH_ROOTS` of `routine_context.py`, with `verification.json` `entrypoints`
    dispositions) is recognized **wherever it lies** -- this checkout, another checkout, a disposable copy, a renamed copy
    (by its bytes) -- and refused unless the arguments have the entry's reviewed data-only shape (`--help` only as the sole
    argument, a reviewed flag only as the first argument, the gate's `--plan` as a standalone token) or the entry is
    reviewed as bounded;
  - Python is judged by its script, its `-m` module (resolved from the working directory and `PYTHONPATH`) and path
    literals in `-c` code; a nested pytest must use `routine_pytest.py`;
  - shells by what they run (`cmd /c`, `call`, `sh -c`, `powershell -File`); an unreviewed PowerShell `-Command` is refused;
  - a Python or shell child whose environment drops the routine marker, changes the marked checkout, replaces the ledger
    or re-adds an opt-in is refused, except a child the guarded runner's reviewed process profile vouches for (that profile
    constrains it: fixed module, disposable request and result, scrubbed environment);
  - installers, online pip, network tools, desktop hand-offs, machine-configuration programs, engine interpreters and
    unreviewed native programs are refused; reviewed native programs (`NATIVE_BOUNDED`: Git, FFmpeg, process probes and
    similar) and programs the test made in its own disposable folder are allowed; stage 0 (`bootstrap_host.ps1`/`.sh`)
    only in its reviewed no-install shapes; a setup launcher (`Setup_and_Run-*`) only as a copy in the session's
    disposable tree in which every (interpreter, script) pair it can start has a stand-in side (a script that is absent or
    not this checkout's bytes, an interpreter that is absent or a text shim) and whose stage 0 is a stand-in; `sh -n`
    (a syntax check) runs nothing.
- **The maintained roots refuse themselves, wherever they lie.** A child Python has no audit hook, so the gate, the
  acceptance runner, the qualification scenarios (`common.start`), the scaling programs, the native adapters and the test
  drivers check the inherited marker first and refuse -- in this checkout, in another checkout or in a copy alike. Location
  is never evidence that an execution is synthetic.
- **The reviewed synthetic gate fixture** is the one exception, for the gate's own contract tests: a disposable tree inside
  the session's owned disposable root (its basetemp), declared in `act-synthetic-fixture.json` at the tree's root (the
  tree's own path and the exact SHA-256 of each synthetic stand-in), whose gate orchestrator is byte-identical to this
  checkout's. Its orchestrator may run (only this session's interpreter may start it); its acceptance and qualification
  launches start only declared stand-ins whose bytes differ from the real runner; a real runner copied into it is refused at
  the gate's operation boundary and by its own guard. The declaration grants nothing outside its tree, outside the
  session's disposable root, or without the routine session that owns that root.
- **Accounting fails closed.** Each stage's effect ledger is a directory the gate creates and initializes (a header with
  the run's token) before the stage's process exists; every cooperating process writes its own record file (start,
  refusals, end), so concurrent writers never share a file. A write failure is an accounting failure, never absorbed. The
  gate's `routine-effects` check passes only initialized, complete, well-formed ledgers in which the stage's own runner
  recorded a completed session and nothing unexpected was refused: a missing, empty, unreadable, incomplete or malformed
  ledger -- or a cooperating child that exited without completing its record -- fails the run. `conftest.py` errors the test
  that caused a refusal or accounting failure in any phase; the bootstrap fails the process for one after the session
  ended. `expected_refusals(effect, ...)` marks refusals of the named effects on its own thread as expected for a synthetic
  negative control (it grants nothing), and adopts a private child ledger: refusals of other effects in it count as
  unexpected.

**Limitations, stated plainly.** This makes accidental heavyweight execution from supported routine paths fail closed; it
is a cooperating-verification control, not an operating-system sandbox. A cooperating Python child inherits the marker,
the ledger and the disposable scope (so every maintained root refuses in it, and accounts for it), but not this process's
audit hook: what a child's own code does directly (an engine interpreter it starts itself, its own sockets) is outside
parent enforcement unless it reaches a maintained root or a routine bootstrap. Native code, Quartz/pyobjc input on macOS,
and an unrestricted shell are outside what Python audit hooks see (a shell fed commands on standard input is judged
only by its environment). A child that refuses but cannot write its record, and
whose exit status its caller ignores, is detected only when the ledger itself was unusable. Static classification cannot
certify every dynamic launch. Another checkout's maintained roots are refused at launch by this process; started through
an intermediary, they refuse only if they carry the R1 guard. macOS native verification of all of this is pending.

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
never `-p no:` a guard plugin, never `-I`). `routine_pytest.py` establishes the envelope and its accounting before
collection, in a new effect ledger beside the basetemp (`<basetemp>-effects`), and judges that ledger whole at exit; plain
`python -m pytest` gets the restrictions from `conftest.py` but is not verification evidence. Modules listed in `files/tests/guarded_groups.json` run only through the
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
The old `files/dev-work/wt082` worktree, the historical `C:\t\` scratch (D-2), the ACL-locked folders (D-3) and the owner's
listening evidence stay untouched until Phase 2's classified cleanup. Phase 1A-1 created `C:\t\p1a1` as a direct-run basetemp,
outside the approved containment; the owner removed it (with `%TEMP%\act-gate\fd57` and `f2c1`) on 2026-11-25. Never create
new `C:\t\` scratch or another external basetemp without approval: Git-fixture modules run through the gate (its approved
scratch), other direct runs use a short basetemp under `files/run-temp/`. Free disk on HOME-PC is about 6-8 GiB: check it
before any expensive run.

## Next

- **Phase 1A-2:** heavyweight admission. The machine-wide lock (A5-W: a native Windows kernel object with machine-wide
  semantics and a protected recovery control directory in the development checkout, one authority shared by every
  checkout, fail closed, no checkout-local fallback; A5-M: macOS stays blocked until a shared developer-only lock
  location in a stable machine-common domain has a native proof and owner approval), single-attempt authorization records
  (A6-R), process-tree delegation of an admission to its stages, run-wide deadlines.
- **Phase 1A-3:** execution and evidence of `quick`, `changed`, `regression`, `focused --feature` and
  `qualification --journey`; preflight cost estimates and budgets; dropping the plan-only seams.
