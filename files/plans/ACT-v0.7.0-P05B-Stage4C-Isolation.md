# P05B Stage 4C test isolation qualification

Production identity remains **0.6.6**. P05B remains **OPEN** for review and the remaining acquisition decisions.
The production optional-setup install/repair gate remains disabled. P06, portable sox supply, actual acquisition,
clean-machine qualification and release work are outside this checkpoint.

The calm-harness tests use the real worker environment builder against a disposable repository root. An independent
patch context owns containment through the operation and teardown; a test's `monkeypatch.undo()` cannot remove it.
Registered reference recordings and the installed library/config used by the no-model selfcheck are read-only inputs.
The production entrypoint, sampling/output comparisons and numerical assertions remain in use.

`cache_sandbox.py` establishes a writable repository-local Numba cache before collection can import librosa/Numba.
JIT and compiled disk caching stay enabled. Only `UserProvidedCacheLocator` is eligible: failure cannot fall back to
installed-library `__pycache__` paths. The sandbox lives through teardown and is restored/removed at process exit.
The tripwire retains every raw refusal, including stacks, test phases and both lexical and resolved paths captured
at refusal time. Only the actual frozen CPython bytecode writer receives bytecode classification. A path named
`__pycache__`, even an existing directory or a disguised `.pyc`, is insufficient.

## Protected focused runner

Run `files/tests/guarded_pytest.py` with an explicit interpreter, `-I -B`, a versioned local JSON configuration,
an owned audit-report path and pytest arguments including one explicit `--basetemp=`. Stage 4C evidence/configuration
lives under ignored `files/dev-work/p05b-stage4c/`; the requested checkpoint is
`files/dev-work/act070-remediation/checkpoints/P05B-STAGE4C.md`.

Configuration version 1 pins reviewed process-source files by SHA-256 and function name, and external tools by
resolved path and SHA-256. Matching a source pin alone does not permit execution: the runner also checks explicit
command profiles and disposable path boundaries, including resolved junction targets. Read-only Git/PID queries,
the existing no-install/rejected-installer bootstrap tests, disposable lock/worker/process trees, media fixtures
and the already accepted tiny offline-pip proof have distinct profiles. Unknown process/OS execution is refused.
NumPy's Windows-unavailable SVE `lscpu` probe is refused before execution and reported as an expected fallback.
The broken-import test's explicitly unavailable `torch` is also refused and retained as a synthetic control.

The outer boundary starts before pytest imports/collection and stays armed through fixture teardown and `atexit`.
Its final report and exit status account for swallowed mkdir refusals and shutdown writes as well as pytest results.
Synthetic child controls prove collection, import, setup, body, teardown and shutdown refusal independently of pytest
success. Production roots, prior evidence and owner paths have no broad write exclusions. Native media scratch and
child temp paths are established inside the repository before imports/process execution. Packaging Git mutations
are limited to proved disposable repositories; the actual repository permits read queries only. Inherited Git
steering is removed, hooks/fsmonitor are disabled, and long-path support is enabled only in the test process.

Python audit hooks do **not** automatically protect independent child interpreters or arbitrary native operations.
Allowed children are reviewed fixed programs with proved disposable roots; offline pip additionally retains its own
child-side network/process guard and Job Object completion proof. The installed-library selfcheck uses `-I -B`,
disposable cache/temp paths and no model load. Full before/after production preservation remains a separate check.

The final focused selection contains all 34 Stage 3 modules and the nine Stage 4B/isolation additions, without
deselecting conflicting subprocess tests. The historical disappearing-lock test names are retained: the original
read-only probe leaves a disappeared lock absent; the `O_CREAT` M20 mutant creates a replacement and is caught.
Exact selection, intermediate failures, mutation results, final pytest/outer results and preservation evidence
belong in the ignored checkpoint. Passing these tests does not authorize activation or settle fresh-machine sox.
