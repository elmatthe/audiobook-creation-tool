# P05B Stage 4B-3A planning and locked authorization

Production identity is 0.6.6. Production acquisition stays disabled. This checkpoint authorizes only disposable,
injected v3 model/spaCy acquisition. Package consumption, offline pip and canonical engine mutation remain 4B-3B.

The planner reads the code-pinned package manifest, independently pinned Qwen model identities and pinned local
engine assets. It hashes existing candidates without trusting mutable cache records. Health comes from a fresh
bounded observer, with an explicit injected observer in synthetic tests. Missing, damaged, unverified, busy,
unsupported, bad-bundle and ready remain distinct. An inconclusive engine probe grants no mutation authority.

A plan retains immutable request settings, exact v3 terms and the full read-only transfer-history disclosure.
Confirmation pairs those original disclosures with v3 consent; history is never silently refreshed at execution.
Any changed term, including a reduction, requires confirmation again. Retry policy is independently configured by
the trusted planner and appears separately in both artifact and shared allowances. No v2 upgrade is supported.

One existing InstallLock covers final all-group observation, identity checks, exact comparison, spending and model
execution. Setup precedes inference, with the existing worker exclusion and MachineGuard behavior unchanged.
All groups are checked before importing local artifacts, spending consent, transferring or changing model files.
Verified local candidates are imported through the existing store after exact confirmation validation. Store reuse
is revalidated before beginning the existing persistent transfer ledger. Every model transfer uses that ledger and
strict transport; native download_file and ScopedOpener cannot serve the v3 path. Failure/cancel is terminal and
requires a fresh plan, history disclosure and consent. There is no second byte tracker or model installer.

The adapter invokes native install_model under its held lock with a scoped authority. That authority checks the
engine again before native mutation and supplies each exact verified file. Native environment mutation is refused
within this scope even with explicit engine terms: 4B-3A can validate those terms but cannot execute them. A test-only
simulator may inspect explicit engine authority, without creating/deleting an environment or running pip.
spaCy is acquired as a verified artifact only; wheel consumption is deferred too.

Disk disclosure is conservative simultaneous new retained bytes: a complete missing store object plus each
required destination copy. Temporary headroom includes one full artifact staging copy and the existing reserve;
engine and spaCy installed sizes remain separately identified as approximate bounds in the plan, included in the
disk/headroom disclosure even while installation is deferred, never used as network allowances.
Models are hash-verified at final validation and at publication; no hardlinks to mutable caches are introduced.
Package-store sealing and protection throughout pip consumption are explicitly outside this checkpoint.

Legacy CLI/manual installation keeps its existing independent download/repair contract. The old v2 acquirer remains
only an injected historical test seam behind the disabled worker; these changes do not claim whole-app consent
safety. P06 owns bootstrap integration. Stage 4C owns the calm-harness/Numba and M20 follow-up qualification.

The Stage 3 B1/B2/B3 test names remain in `test_optional_setup_acquisition.py`, now delegated to actual v3
planner/acquirer/native-boundary fixtures. The original +66-line v2 patch and its three failing executions are
retained in ignored Stage 4B-3A evidence. B1's former initial zero-byte premise is deliberately no longer possible:
initial corruption now plans explicit repair bytes. Its migrated zero-byte attack changes content after legitimate
confirmation, before final locked validation; another test changes content at native entry after final validation.
B2 changes engine health after model-only approval and again at native pre-transfer validation; B3 retains the
original 7-byte/307-byte lock race. None of these tests routes through the production-disable gate.
The earlier +41 disappearing-lock controls and +23 historical Handoff lines remain byte-identical and unstaged.

`Confirmation` is a trusted caller contract pairing the displayed immutable plan/history with raw v3 consent.
History is not an extra field in the v3 wire codec: a future UI must retain this exact confirmed disclosure object.
Passing freshly observed history instead of the original displayed snapshot is prohibited. Any production UI/wire
bridge and wheel/spaCy consumption still require their separately authorized integration checkpoints.
