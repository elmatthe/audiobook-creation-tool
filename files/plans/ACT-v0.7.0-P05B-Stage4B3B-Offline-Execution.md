# P05B Stage 4B-3B protected offline Qwen execution

Production identity remains **0.6.6**, P05B remains **OPEN**, and the production optional-setup worker still refuses
install/repair before observation or spending. No launcher/UI can select a network opener or engine executor.
This extends the existing explicitly injected disposable v3 seam. It does not authorize production acquisition,
portable sox supply, Stage 4C, P06, clean-machine qualification or release work.

## Package authority and consumption

The unchanged reviewed manifest and original runtime lock define all 89 runtime versions and artifact identities.
The effective wheel lock substitutes only the already reviewed local sox derivative. Missing local supply still
blocks planning; no source build, new derivative, redistribution or substitute hash is authorized.

`Planner.acquire_disposable(..., opener=..., engine_runner=...)` requires an explicit trusted runner for engine
execution. No runner/opener is derived from request JSON. The existing simulator remains separate: it never gains
native engine authority. One existing InstallLock encloses all-group validation, exact original plan/history/consent
comparison, disk checks, persistent consent claim, bounded transfers, package sealing and environment/model proof.
Verified local reuse is imported before `TransferLedger.begin`, whose existing contract independently checks that
reuse. Network acquisition cannot precede the durable claim. Failed/cancelled attempts cannot restore old budgets.

`qwen3_packages.sealed_packages(store, operation, reviewed)` requires the actual open, spent transfer operation,
its exact catalog/consent, the current repository's held InstallLock and the complete reviewed 89-wheel set.
It revalidates objects, copies them into an operation-specific contained wheel-only view and generates the
deterministic effective lock. Both store and independent view copies are included in disk disclosure.

Every consumable wheel and lock is opened with Windows CREATE_NEW, READ|WRITE access and FILE_SHARE_READ only.
The same non-inherited handles remain held through consumption. There can be no earlier writable file handle or
mapping to these new files. Other writers, deletion, replacement and reparse write handles fail sharing checks.
Existing directory-pinning primitives protect the entire path hierarchy. The final files are rehashed, checked
for exact size/name/version/tag/catalog identity, and associated with an opaque live operation/thread capability.
Receipts, filenames, dataclasses, claimed digests, previously checked objects and expired capabilities cannot mint it.
Verification/copy loops support cancellation; no existing pip cache confers verification.

Directory sharing does **not** prevent adding new child files. Final checks reject unexpected entries, and pip
receives explicit hash-qualified relative local-file roots for every approved wheel, in addition to the effective
lock. Its cwd is the protected view. Thus even a candidate inserted after enumeration cannot replace a root chosen
by pip. Relative roots avoid Windows' command-length ceiling; the complete command is checked before mutation.
Pip merges hashes from duplicate requirements: both the effective lock and all direct roots must therefore be
generated from, and checked against, the same reviewed capability. Pip flags alone are not that authority check.

## Existing installer, scoped offline execution

The existing `qwen3_setup.install_environment` creates/proves the canonical environment, runs pip and performs its
existing contained health proof and state recording. Its v3 branch uses the explicit nested interpreter with
`-I -B -c <fixed offline bootstrap>` to run pip, with:

```
install --isolated --require-virtualenv --no-index --find-links <protected-view>
--require-hashes --no-deps --only-binary=:all: --no-cache-dir --no-input
--disable-pip-version-check -r <protected-effective-lock> <89 hash-qualified local wheel roots>
```

No pip upgrade, index URL, source archive, dependency resolution, dynamic build dependency or online fallback is
provided. The existing environment scrub removes PIP/PYTHON/activation steering; PIP_CONFIG_FILE=NUL disables all
external pip configuration, including site configuration (`--isolated` alone does not disable all config files).
The fixed child bootstrap refuses socket creation/resolution/connect/send and subprocess/OS execution before pip
imports. Local hostname reads are permitted. Its raw refusal list is emitted on normal interpreter shutdown.
Bundled pip's IPv6 capability and Windows platform-version probes are denied, recorded and allowed to fall back;
no egress or source-build process is allowed. This is not an OS sandbox for arbitrary hostile native extensions.

The existing Job Object runner stays in use. For this fixed offline bootstrap it additionally confirms zero active
job members before returning/releasing package protections, including cancellation and errors. If the OS cannot
prove exit, the capability is revoked and its handles are quarantined in memory rather than released. There is no
automatic quarantine reuse/release API. Ordinary/manual command containment behavior remains unchanged.

**Manual/legacy behavior remains separate:** outside the v3 scope, existing CLI/manual install/repair keeps its
original index/cache/source-build contract and its existing user decisions. It is not brought under v3 consent
by this change. The old injected v2 acquirer also retains its separately documented limitations behind the disabled
production worker. Existing healthy environments need no new receipt and retain the original requirements identity.

## Engine action and destructive boundaries

`qwen3_engine_authority` mints live scoped execution authority only from spent exact terms plus a sealed package
capability. It binds the original confirmed canonical/parent identity and recovery record. It is checked at entry,
removal, creation, package installation and final state recording. Base interpreter proof happens before deletion.
All selected model/package transfers finish and all packages are sealed before any engine removal/creation.

| Original action/state | Allowed execution |
|---|---|
| `none`, healthy engine | Model files only; later damage/unverified/busy means refusal and new confirmation |
| `install-missing`, genuinely absent canonical and no stale creation/removal record | Exclusively create canonical, offline pip, existing import/model health proof |
| `rebuild-canonical`, proved damaged canonical, verified destructive scope and safe_to_remove_environment | Capture approved tree, remove canonical only, exclusively recreate and prove |
| Missing versus damaged mismatch, uncertain identity, legacy-only selection, busy/unproved health | Refuse; never infer damage or silently rebuild |

Creation uses handle-relative NtCreateFile FILE_CREATE to create **and pin** the new directory in one operation;
an unexpectedly appeared directory is never adopted. The handle stays held through the complete environment
operation. Missing/damaged state, readiness, original lock, free space and identities are rechecked before mutation.
Malformed, unreadable, null or wrongly located canonical state records are unverified, never evidence of absence.
The tolerant legacy state reader is not used to grant v3 engine mutation authority.

Path-based recursive deletion can race with a changed child directory on Windows. The v3 removal adapter therefore
captures every approved tree entry with non-sharing read/delete handles, refuses reparse points and compares the
complete original identity before deletion. After the installer records `removing`, it rechecks the tree and disposes
only those captured handles bottom-up using SetFileInformationByHandle. It never follows or deletes an inserted
entry. Unexpected insertion makes validation or nonempty-directory deletion fail closed. Every native create/delete
emits the existing audit event before mutation. Legacy and parent environments are outside this removal scope.
The existing installer still owns state ordering and all subsequent environment/pip/probe work; this is a mutation
safeguard, not another installer. Manual removal remains unchanged.

Cancellation/failure leaves the truthful existing `removing`, `creating` or `created` stage and no success receipt.
There is no automatic rollback to the old canonical engine. A crash between exclusive directory creation and its
first state record can leave an empty unrecorded directory: it is not silently adopted or eligible for automatic
deletion; review is required. Old consent claims, reservations, partials and operation views are retained. Stale
views grant no authority. A fresh plan/history/consent is required for any later attempt.

## Qualification boundary and remaining work

Routine tests use tiny synthetic identities, reviewed version/tag fixtures, actual contained filesystem operations,
the actual planner/store/ledger/installer and fake environment/package/model commands. Separate native tests use
CPython's bundled pip (installer tooling only) and one tiny test-only pure-Python wheel in a disposable venv. They
exercise the actual command builder, held handles, hostile config, wrong-hash rejection, Job Object completion and
cancellation with the child no-egress guard. No ACT runtime package/model is acquired or installed, and no real
Qwen environment or production cache is touched. No real 89-wheel installation/model load is claimed.

The ignored checkpoint and raw audits carry exact counts, negative mutations, observed native argv, preservation
comparison and Git exit. Fresh-machine sox supply remains blocked. Stage 4C still owns the 60 calm-harness production
mkdir attempts, 78 hidden Numba cache attempts, M20 disappearing-lock mutation work and complete P05B isolation.
The original disappearing-lock tests remain intact. No full 34-module suite or full verify.py is run here.

Native primitives follow Microsoft's [CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew),
[NtCreateFile](https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntcreatefile) and
[SetFileInformationByHandle](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-setfileinformationbyhandle)
contracts. Pip's [install options](https://pip.pypa.io/en/stable/cli/pip_install/) and
[configuration rules](https://pip.pypa.io/en/stable/topics/configuration/) supplement the native qualification.

**P05B remains OPEN. STOP FOR CHATGPT REVIEW.**
