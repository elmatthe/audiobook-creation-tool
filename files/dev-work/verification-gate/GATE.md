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

## The routine envelope (Phase 1A-1, corrected in R1 and R2)

Every pytest process of this checkout is a routine verification process, and so is every Python child one of them starts.
The shared contract -- marker names, launch roots, data-only argument shapes, the Python command-line reading, the synthetic
recipes, the operation check and the effect-ledger format -- has one home, `helpers/routine_context.py` (standard library
only); `files/tests/routine_effects.py` enforces it, `files/tests/routine_child.py` is the child bootstrap, and
`files/tests/routine_fixtures.py` holds the small set of reviewed bounded fixture and measurement profiles.

- **Supported invocations.** `files/tests/routine_pytest.py <pytest args>` (ordinary pytest: the gate's ordinary stages
  and a direct targeted run) and `files/tests/guarded_pytest.py` (the guarded groups, through the gate). Both call the
  same early setup, `routine_effects.bootstrap`, before pytest, its plugins, `conftest.py` or any test module is imported:
  third-party plugin autoload off, opt-ins and overrides scrubbed, the envelope installed, and the session's accounting
  bound to the launch its parent reserved for it (the gate's stage launch, or a parent session's) or, for a direct run, a
  new ledger beside the basetemp. The guarded runner keeps its own stronger hooks and lifetime report; it judges its
  reviewed callsite profiles on the command a test asked for, and its exit status consumes the ledger verdict (the whole
  ledger when it owns it or runs as a gate stage; nested in another session, its own clean record, the owner judging the
  rest). Its end record carries the status it exits with, and a reserved runner that refuses its arguments still binds
  and ends its record before it exits. A raw
  `python -m pytest` still gets the restrictions from `conftest.py`, after its plugins loaded; it is not verification
  evidence.
- **Scrubbed.** Real-engine opt-ins (`ACT_*_REAL`), the destination overrides `ACT_P2_EVIDENCE`, `ACT_XHE_PROOF_APPLE_CAF`,
  `ACT_MAC_FFMPEG`, and an inherited disposable-root marker never reach a test or a child. They never grant anything.
- **Nothing grants a heavyweight effect.** `routine_effects.admitted()` is always False until Phase 1A-2; no `--mock`
  flag, no environment-variable bypass, no "under pytest" grant.
- **Operations refuse where an audit event exists**: a non-loopback `socket.connect`/`getaddrinfo`/`sendto`/`bind`;
  reading a model-weight file outside the disposable roots from a model library; resolving `SendInput` and its kin outside
  the gate's native-input adapter, or a native process-creation function (`CreateProcessW`, `CreateProcessAsUserW`, ...)
  outside the reviewed containment module; `os.startfile`; and every process mechanism that cannot take part in launch
  preparation (`os.system`, `os.exec*`, `os.spawn*`, `os.fork`, a direct `os.posix_spawn` or `_winapi.CreateProcess`).
  The gate's own callables check their operation (`routine_context.check_operation`) as before.
- **One launch decision (R2).** `routine_effects.decide_launch` (side-effect free) judges the program actually started --
  resolved by the platform's own search, an `executable=` override included -- its arguments, working directory and
  effective environment, and returns exactly one of: **refuse**; **bootstrap** (the same interpreter and options run
  `routine_child.py`, which binds to the launch's reservation, records its start and initialization, installs the envelope
  and then runs the script, `-m` module or `-c` code exactly as the unprepared command would have: `sys.argv`,
  `sys.path[0]`, `__main__`, and a `PYTHONPATH` moved past the envelope and restored); or **profile** (run unchanged under
  an exact reviewed profile). The same decision prepares the launch (a verification-only wrapper of the pinned CPython
  3.12 `subprocess.Popen._execute_child`, which validates that interface and fails closed if it differs) and, through the
  audit hook, admits the actual `subprocess.Popen` event, which must be the prepared one.
  - Heavyweight entrypoints (the `LAUNCH_ROOTS`, with `verification.json` `entrypoints`) are recognized wherever they lie
    and by their bytes, and refused outside their reviewed data-only shapes, as in R1.
  - A Python child's startup customization is reviewed: `PYTHONHOME`, `PYTHONINSPECT` and a `PYTHONPATH` holding a
    `sitecustomize`/`usercustomize` are refused (unless `-E`/`-I` makes the interpreter ignore them); an interpreter must be
    this session's, its base, or a disposable venv or copy made from it.
  - **Shells run only in reviewed forms**: `cmd /c rem`, a junction between two disposable paths, the setup-launcher sandbox
    recipe, the gate contract's console-host helper, stage 0 declined or judging a disposable offline archive, the tk_proof
    stage-0 harness, the fake-ffmpeg wrapper, Git for Windows' bash (beside the session's `git`, or the session PATH's bash
    when it is Git for Windows' own) for `-c "exit 0"`, `-n` over the launcher's exact
    bytes and the packaged launcher against its reviewed shims, and the clone-transcript extractor's fixed owner-only
    access script on a disposable artifact. Arbitrary shell text, expansions, chains, stdin programs and encoded commands
    are refused.
  - **Reviewed profiles are exact and few** (`routine_fixtures.py`, D-R2-2..4): fixture sources are pinned by SHA-256, and
    a modified source, target or environment is not the family. Startup measurements run unchanged with parent-side
    evidence only: the tk_proof hanging `sitecustomize` under a production Tk probe and its bound, and the `-I -S`
    pre-venv import-footprint probe; the tk_proof Tk-breaking `sitecustomize` runs through the bootstrap with its
    `PYTHONPATH` kept. Native leaf programs: Git (no network subcommand, writes only to disposable repositories; `git init`
    only of a disposable directory, with no template or a disposable one and at most a plain initial-branch name), an installed FFmpeg/ffprobe on disposable
    outputs, the two exact read-only NVIDIA queries (the product's and the Qwen evaluation tool's), `tasklist` of one pid,
    `taskkill` of a process this session owns, disposable PING copies on loopback, deliberately invalid stubs and missing
    programs. **Inert Python stand-ins** (D-R2-8): a `-c` program on this session's interpreter whose syntax tree uses only
    `time.sleep`, standard-stream writes and flushes, `print`, `sys.exit` and ignoring a signal, with constant arguments,
    runs unchanged and owes no participant, so a cancellation inside its startup is measured as written (nothing may
    follow the program, `-i` is refused, and `PYTHONPATH`, `PYTHONHOME`, `PYTHONINSPECT`, `PYTHONUSERBASE` and
    `PYTHONEXECUTABLE` must be unset unless `-I`/`-E` ignores them; `PYTHONSTARTUP` is read only by an interactive session);
    any other program is effect-capable and bootstrapped. A test that measures a cancellation after readiness waits for an
    independently observed ready condition (the decoder's first samples) before it cancels. The guarded runner's exact profiles are honoured; its generic Python profiles
    never let a Python child skip the bootstrap.
  - **Scrubbed guarded workers (D-R2-9).** The v3 supervisor's fixed fake worker, the read-only planning worker and the
    planning bridge worker keep their production six-name environment exactly (`SystemRoot` the real Windows directory,
    the temporary folders the run root, the two offline flags) and run unchanged under exact profiles: this interpreter
    with `-I -B -S`, the reviewed program (the fake worker's fixed text, production's `_BOOTSTRAP` or one of the read-only
    worker's negative controls assembled only from its test's literals), a working directory whose every file is a
    byte-identical copy of the marked `scripts/` (the bridge's test adapter must open with the reviewed containment prefix
    `FIXTURE_ADAPTER`; the module-pin control's one inert comment line is the only other admitted difference). The
    envelope cannot run inside them (their own audit hooks refuse its writes); their Jobs own them and the parent records
    launch, pid and observed exit. A routine marker is never added to such an environment, and any other replacement
    environment, a changed worker or a widened one is refused as before.
  - **Worker network-guard measurements (D-R2-7).** The real OmniVoice worker on the reviewed stand-in stack (launcher,
    worker copy and stand-in libraries byte-identical to the test's own; every output disposable), the reference probe and
    the dev-tools worker's inert-event measurement run through the bootstrap with `measurement: network-guard` in their
    reservation. In that child the envelope's network refusal is appended behind every hook the program installed, so the
    worker's own guard decides first; whatever it lets through is still refused before anything resolves or connects, and
    recorded, so the test fails.
  - **Native process creation**: only `containment.spawn_low`'s reviewed Low-integrity launches (its own preflight probe and
    test_dialog_containment's two probes: the integrity probe and the labelled-scratch write probe, each in its exact text
    and paths) run, through a verification-only proxy that records each as a profiled launch with its spawn and observed
    end. Labels and ledger permissions are never widened.
  - **Multiprocessing `spawn`** children start through the bootstrap (spawn semantics, `__main__` preparation and exit codes
    kept); the launch identity travels on the command line, because the spawn copies the environment itself. The wrapper is
    applied when a program loads `multiprocessing.spawn` (a meta-path finder), never eagerly: an eager import put `socket`,
    `select` and `multiprocessing` into every bootstrapped child's module set.
  - The envelope's own ledger I/O uses the original `open` captured at import, so a test that replaces `builtins.open`
    cannot redirect the evidence.
- **The reviewed synthetic gate fixture (R2: positive recipes).** A disposable tree inside the session's owned disposable
  roots, declared in `act-synthetic-fixture.json` (format 2: the tree's own path and, for each stand-in, the reviewed
  recipe it is), whose orchestrator, runners and envelope are this checkout's own bytes. A stand-in is valid only while
  its bytes are exactly its recipe's source in this checkout (`files/tests/routine_recipes/`), it stands where the recipe
  may stand, and its data file validates in the recipe's closed vocabulary; a real runner, a modified or historical runner,
  another recipe or arbitrary code is never a stand-in. The free-standing stand-in for pytest accounts as the routine pytest
  session its stage reserved, only in its exact bytes: a gate driven by a test reserves a substituted stage command in the
  session role only when it is that recipe in a disposable root (any other substitute is a routine child), and the stand-in
  writes the same initial collection inventory the real probe writes.
- **Accounting obligations (R2, ledger format 3).** A launch that owes accounting is reserved before it exists: the
  reserving parent writes a reservation file (`r-<launch>.json`, exclusive, authoritative) and a corroborating `reserve`
  row, then records the spawn (actual pid and creation time; a Windows venv redirector is bound only with its recorded
  redirector role, the participant as its direct child and the same interpreter), any intentional stop it makes and the
  observed end. The child records its start and initialization before any target work and its end last. Every reserved
  launch must be reconciled exactly once: a required child that never wrote its first record, an unresolved launch, a
  duplicate, orphan or foreign participant, a reservation that disagrees with its row, or a mismatched exit is a problem.
  Exact profiles owe no participant; their `profiled`, spawn and observation rows are their parent-side evidence. The
  reader is total: any malformed record is a controlled problem, never an exception. Format 2 ledgers read back only as
  history. A write failure is an accounting failure, never absorbed. `conftest.py` errors the test that caused a refusal
  or accounting failure in any phase, and the runners fail the process for one after the session ended.
  `expected_refusals(effect, ...)` marks refusals of the named effects on its own thread as expected for a synthetic
  negative control (it grants nothing) and adopts a private child ledger, in which refusals of other effects count as
  unexpected.
- **Explained termination (D-R2-1).** A participant may end without its own end record only by an explained stop: its
  launch was reserved, before it existed, with an expected lifecycle (`expected_termination`, or the `routine_stop` test
  marker); it initialized its accounting; its owner recorded the stop's intent and action for that launch's own process
  (`Popen.kill`/`terminate`, `os.kill`, `taskkill` of an owned pid, kernel32 job and process terminations and the close of
  a kill-on-close Job reached through ctypes), successfully, before the outcome was observed; the observed outcome agrees
  with the mechanism; and every descendant is accounted (ended, explained, or observed gone after a tree stop). After any
  recorded stop -- also one made after the launch had ended, when a worker exited and its Job then ended what it left --
  the owner observes the stopped tree's unended participants and the profiled leaves their parents never observed. A
  descendant of an ancestor that ended with its own record is accounted through a declared, successful tree stop its
  reserving parent then made; a descendant held in the kill-on-close Job of a participant whose own end is an explained
  stop is accounted when it was then observed gone (the envelope records `contained` when a process assigns its own launch
  to such a Job; children inherit membership); a profiled leaf its parent never observed, only when an ancestor saw its own
  process gone after that ancestor's tree stop of the chain, or after its stop of a parent that itself ended by an
  explained stop. An exit that differs from a participant's own end record is accepted only
  as the code of an explained stop recorded after that record. A crash fixture is explained only by an observed exit among
  the codes its reservation declared. A kill request alone, a post-hoc explanation, a child that never initialized, or a
  gate stage's runner killed at a timeout is never explained; no graceful end record is ever written for a process that did
  not end gracefully, and an interrupted run's evidence stays incomplete. Markers are exact and per test: they name the
  mechanisms the code under test uses on the launches that test makes.
- **Stage binding.** The gate's own participant in each stage ledger reserves the stage runner's launch, records its spawn
  and observed end, and binds the runner's participant to the session that wrote the probe. Its `routine-effects` check
  judges every ledger whole and is a sealed FAIL if a ledger cannot be judged; ledgers are kept as evidence without
  following links.
- **Collection reconciles (M1).** The probe records every collected item before any hook can drop one; the gate (and, in
  memory, a direct run's `conftest.py`) fails a session whose initial inventory does not equal what it kept plus what it
  deselected.
- **Owner-private paths are private before any read (C2).** The local-only rule applies to the tree fingerprint, the
  incremental-evidence file map, the candidate identity and changed selection before a file is read; a tracked local-only
  path stops the run (`privacy` BLOCKED) and blocks a plan, and its name is never written.
- **Ambiguous imports are gaps (C4).** A dotted import that resolves to more than one file, in a module some test reaches,
  is a gap for the importer, each candidate and everything reached through them.
- **R3 (independent R2 review).** These tighten the rules above; nothing is relaxed.
  - *Launch evidence.* Every completed reserved launch carries its reserving parent's own `spawned` row and exactly one
    terminal observation (`exited`) of that spawned process; the child's own records never stand in for them (for a child
    linked to a private ledger, they are required in the parent's ledger). A completed child whose parent was stopped
    first is accounted only when the writer of that stop observed it gone afterwards. Only a `not-spawned` row by the
    reserving parent excuses both.
  - *Stop attribution.* An explained stop is ONE successful action by the reserving parent (or `self`), for the launch's
    own process -- pid and, where read, creation time -- before that parent's observation of exactly the code the action
    leaves (`Popen.kill`/`taskkill /F` 1, `TerminateJobObject` its code, the close of a kill-on-close Job 0); a stop with
    no known code explains nothing. Its own tree flag, never another record's, decides its descendants, which are
    accounted only when that stop's writer observed them gone after it. A reviewed `taskkill` is recorded from its actual
    result, after it ran. `expected_termination` and the `routine_stop` marker reach the launches of the thread that opened
    them and of threads started from it while open, never an unrelated concurrent launch.
  - *Startup and admission.* One startup check judges every Python launch -- bootstrapped, nested runner and unchanged
    form: startup variables, a sitecustomize/usercustomize on PYTHONPATH, and the user site's startup code where that
    interpreter would process it. A nested runner also has nothing beside it shadowing a library module, and its
    PYTHONPATH (like a bootstrapped child's) is restored only after its envelope exists; `routine_pytest.py` imports
    nothing from the working directory, its own folder or PYTHONPATH before its bootstrap. The inert profile needs a trusted
    import path (-I/-P, or no module in the working directory standing for one it imports). The final admission of a
    process creation compares the program the platform starts, the complete arguments, the working directory, the
    effective environment's values and, for an unchanged form, the reviewed profile itself with what was prepared.
  - *Recipes and stage 0.* A synthetic recipe is admitted on its actual command: every destination it writes inside its
    fixture tree with no link on the way, every identifier one plain name, no abbreviated option; the gate's operation
    check is given the exact command it supervises. Stage 0 runs only as a disposable copy whose app folder holds no
    interpreter it would prove before consent other than a proved disposable state -- an inert stub, or (D-R2-2's stage-0
    Tk measurement) a byte-identical copy of this session's base interpreter with no startup code but the base's own
    `.pth` files and, at most, the pinned BREAK_TK fault -- with no planted PowerShell module path; cmd forms without `/d` run only
    while no AutoRun is set, and the setup sandbox holds nothing runnable cmd would find first; bash forms refuse
    `BASH_ENV`/`ENV`/exported functions and resolve helpers to the reviewed shims, then system folders (macOS proof pending).
  - *Qwen3 read-only selfcheck (R3-05).* Exactly `<this checkout's Qwen3 interpreter> -I -B
    files/dev-tools/qwen3_calm_venv_tools.py selfcheck <a folder under files/runtime-data/models>`, offline
    (`HF_HUB_OFFLINE=1`) with every cache and scratch destination disposable, runs under its exact profile; every other
    engine-interpreter launch is refused. The installed-library proof is a separate environment obligation.
  - *Privacy (C2).* The local-only policy is mandatory: unavailable or malformed, nothing is fingerprinted, read, logged
    or compared (`privacy` unavailable); a tracked local-only path stops capture with a count only; a tracked or in-scope
    path through a link or junction stops it too. Names are listed before content, rename detection runs only when no
    side is private, file bytes are read through the no-follow inventory and Git blob ids are made from those bytes
    (`hash-object --stdin --path`; an external `filter=` is refused). Historical maps are filtered as they are read,
    never rewritten; Git's stderr and logged arguments never carry a private name; equal digests never make an identity
    current while either side records a privacy problem.

**Limitations, stated plainly.** This makes accidental heavyweight execution from supported routine paths fail closed; it
is a cooperating-verification control, not an operating-system sandbox. Native code a process runs directly, a hostile
child, Quartz/pyobjc input on macOS, and what a reviewed shell program or a profiled native program does internally are
outside what Python audit hooks see; that is why shells and native programs run only in exact reviewed forms. A
grandchild a reviewed shell or native program starts (stage 0's probe interpreter, the setup sandbox's stub run) is
accounted only through its profile's parent-side evidence. Static classification cannot certify every dynamic launch.
macOS native verification of all of this is pending.

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
