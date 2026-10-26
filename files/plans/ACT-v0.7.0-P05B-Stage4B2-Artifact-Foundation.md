# P05B Stage 4B-2 artifact foundation

Production identity remains 0.6.6. P05B remains open. The optional-setup production acquisition gate stays disabled.
These modules provide an explicit foundation interface; no worker, installer, pip, model load or synthesis uses it.
Stage 4B-3 requires a separately authorized integration checkpoint.

## Authority and interface

`shared.artifact_store.Catalog(trusted_terms, package_manifest=..., purpose=...)` takes **independently trusted**
v3 acquisition terms from a future locked planner. Received consent JSON and calculated candidate hashes are never
sources of approval. Package rows additionally match `tts.qwen3_package_manifest`'s code-pinned manifest, original
requirements identity and effective lock. Model rows must come from the caller's independently reviewed model manifest.
The foundation validates identities; it does not implement that future all-group planner.

`ArtifactStore(repo, catalog)` verifies/imports only known identities. `TransferLedger(store).prior_state()` reports
earlier actual spending, outstanding reservations and partial files. A caller must disclose that snapshot **and** the
new terms before confirmation. `begin(raw_v3_consent, session=..., request_id=..., disclosed_prior_state=...)` checks
exact fresh terms/session/request, revalidates claimed complete reuse, compares the snapshot and exclusively claims
the consent. A changed snapshot requires renewed disclosure. This separate disclosure parameter is a trusted caller
obligation; Stage 4B-3 must bind the UI's confirmed snapshot to the call rather than automatically accepting a new one.
No v2 promotion, unknown-size authorization or old-operation reopening exists.

`artifact_transfer.acquire(store, operation, artifact_id, opener=..., cancelled=...)` makes one full GET.
Further attempts require another explicit call using the same live operation and remaining authorization.
`operation.finish()` makes it terminal. Cancellation is terminal immediately. Neither permits subsequent acquisition.
An operation serializes its calls; atomic consent claims and publication also prevent competing writers.

## Storage and consumption

The fixed layout is `files/runtime-data/artifact-store-v1/{objects,incomplete,transfers}` under the supplied repository.
It is outside existing disposable Qwen pip cache/tmp cleanup. Objects are named by a canonical manifest/artifact
identity digest, with separate exact canonical metadata and complete byte verification. Partials never count as objects.
An incomplete blob/metadata pair is a conflict, not permission to overwrite. Existing objects are always rehashed.

Local imports open candidates read-only and copy into an exclusive private partial. They never hardlink a mutable
cache or change its contents. A fully verified existing store object is reused without another copy. There is no bulk
import in this checkpoint. A real package/model file was never requested or copied for qualification.

All actual reads/creates/publication check containment and reject links, junctions, hardlinks and nonregular files.
Windows directory handles pin the hierarchy. Ordinary I/O denies directory write/delete sharing. Publication captures
a source handle denying byte writes/deletion, then uses a handle-relative `NtSetInformationFile` rename into the
pinned destination directory with `ReplaceIfExists=False`. Its ancestors deny write/delete sharing. The destination
directory temporarily permits write sharing because the kernel rename requires it; using its handle prevents a late
in-place junction from redirecting publication. Failure has no overwrite/copy fallback. The native rename emits the
standard Python `os.rename` audit event before mutation, so the existing production-write tripwire covers it.
This platform boundary is qualified for Windows; other platforms fail closed rather than silently weakening it.
The primitives follow Microsoft's [CreateFile](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)
and [FILE_RENAME_INFORMATION](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/ns-ntifs-_file_rename_information)
contracts and are exercised with actual synthetic filesystem races.

**Verification is point-in-time.** Returned `Verification` records contain no consumable path and always carry
`requires_revalidation=True`. There is deliberately no installer consumption API. Stored bytes are not ACL-immutable
against later writes by their owner/administrator. Stage 4B-3 must revalidate and seal/hold the exact files throughout
consumption; a receipt, filename, size or earlier successful check is insufficient authority for pip or model loading.

## Transport and accounting

Only the exact catalog-approved HTTPS URL is requested. No indexes, mirrors, proxies, redirects, retries, shell or
Range requests are used. The native opener refuses redirects before following Location. Responses must be HTTP 200
with the exact original URL, one canonical decimal Content-Length equal to the reviewed size, no Content-Range,
no Transfer-Encoding, and absent/identity Content-Encoding. Unsupported or ambiguous responses fail before body reads.
Reads are at most 64 KiB and stop at the exact Content-Length framing boundary, without an unauthorized extra-byte
EOF probe. Injected openers are trusted transport adapters: they must honor `read(n)` and never follow redirects.
Complete size and SHA-256 verification precede publication; unexpected response filenames/destinations are never used.
Each blocking network operation has a 15-second timeout; cancellation is checked before opening and between reads.

The measurement is **application-consumed HTTP body bytes returned by bounded reads**. This does not bound DNS,
headers, TLS, transport buffering or wire traffic. Each full response is conservatively reserved in a flushed,
atomically published ledger event before the request begins. Both per-artifact and operation caps apply independently.
Expected new bytes and disclosed retry headroom remain distinct. Untouched artifacts' expected bytes are held aside,
so a retry cannot spend another artifact's baseline allowance. Zero-byte reuse cannot buy replacement bytes, and
model-only terms contain no package authority.

Returned bytes are counted before disk writes, cancellation or hash verification. At response exit, actual spending
is persisted and that many reserved bytes are reclassified as actual; unused uncertain reservations are never refunded.
On a process crash before settlement, the entire persisted reservation remains charged and actual is a lower bound.
The ledger uses strict versioned records, exclusive publication, sequential hash chains and validated transitions.
The live operation also detects journal rollback/authorization replacement and poisons itself on publication failure.
Corrupt/uncertain ledgers (including abandoned publication temporaries or an empty claim) stop for review; they are
never reset automatically. This assumes functioning local filesystem persistence, not recovery from arbitrary media
loss, malicious deletion or backup rollback. No old consent can be resumed through the public ledger interface.

There is no range resume or authenticated-prefix claim. Earlier partials are disclosed with **zero verified reuse**.
Fresh permission starts a separate partial from byte zero and leaves previous files/spending untouched.

## Sox and next integration gate

`sox-1.5.0-py3-none-any.whl` is local-only: size 40,164, SHA-256
`d7f2d5a2390fa235b4195700e72d5bd9b507d88e4598cadcfd17aaccae2b8934`.
Only controlled local development/synthetic qualification may import it. Missing or altered supply is refused,
including before spending terms that claim its complete reuse. Its source hash, wheel hash and reviewed build-input
digest remain distinct. No URL, replacement hash, build, redistribution or portable-supply promotion is authorized.

Stage 4B-3 must derive all-group terms under the existing InstallLock; prove reuse and disclose persisted state;
carry explicit engine authority to mutation boundaries; obtain every verified wheel before environment mutation;
qualify sealed consumption and offline pip with no fallback; then repair B1/B2/B3 without weakening their controls.
Healthy existing engines, legacy rollback, production model state and requirements remain valid and unchanged.
Fresh-machine sox supply, Stage 4C isolation/M20, and P06 bootstrap/wizard integration remain separate gates.
