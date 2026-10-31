# Audiobook Creation Tool — Decisions (ADR log)

Append-only. Newest entries on top. Each entry: date, decision, why, signed by whoever made it.

---

## 2026-10-31 - The app environment installs only from a complete hash lock through a verified local store; pip and NLTK stay inside the app folder; an ending that stops mid-sound is flagged (v0.7.0 portability remediation)

**Context.** The independent review of `9b1349e` (ignored `files/dev-work/act070-rc/evidence/VERIFICATION-REVIEW-9b1349e.md`)
found three release-readiness MAJORs and one diagnostic gap: the base `pip install` left its cache in
`%LOCALAPPDATA%\pip\cache` (pip finds that folder through the Windows known-folder API, so redirecting `LOCALAPPDATA`
does not move it); `ensure_punkt` called `nltk.download` at the start of every narration (unhashed, unconsented, into
`%APPDATA%\nltk_data`); 112 of the 170 base packages and `pip install --upgrade pip` were unpinned and unhashed; and the
final-tail policy reported an ending cut mid-sound (Qwen3 Aiden) as "0.00 s; nothing removed". Owner directive
2026-10-31: resolve them without disturbing the engines, installer, recovery, 28 voices or non-TTS tools. This
supersedes the AUD-010 deferral of main-stack transitive pinning (P04C closing state).

**Decision.**
- *One lock.* `scripts/requirements-lock-windows-py312.txt` names every package of the app environment for Windows
  x86-64 CPython 3.12 at one version, with the SHA-256 of the one artifact pip installs there (170 packages; two have
  no wheel: `docopt`, `antlr4-python3-runtime`). It freezes the versions the qualified portable install p1 proved (28/28
  voices; the only difference from HOME-PC's gate environment was `filelock` 4.2.5 vs 4.2.4) and is generated, never
  hand-edited, by `files/dev-tools/lock_base_requirements.py` with pip's own resolver (`--dry-run --report` under those
  versions as constraints; refused unless the resolution is exactly the proven set). It records the SHA-256 of
  `requirements.txt`, which stays the human-maintained list; `verify.py`'s deps gate fails on a stale, incomplete or
  loosened lock, and a test proves the lock closed and minimal under the packages' own dependency metadata and the gate
  environment identical to it.
- *One installer.* `bootstrap.install_base_packages` serves setup, repair, the drift reconcile and the Kokoro/Chatterbox
  self-heals: the locked setuptools first, then every artifact fetched with `pip download --require-hashes --no-deps
  --no-build-isolation` into `files/runtime-data/python-packages` (kept; pruned to the lock), then `pip install
  --no-index --find-links <store> --require-hashes --no-build-isolation` with dependencies checked, so a package the
  lock does not name cannot be installed. A complete store repairs without the network; a kept file that fails its hash
  is fetched once more. pip is never upgraded: the environment keeps its base Python's `ensurepip` pip (25.0.1 for the
  pinned 3.12.15). Another interpreter installs `requirements.txt` under the same policy.
- *One pip policy* (`shared/base_packages.pip_environment`): no inherited `PIP_*`/`PYTHON*`/activation variables,
  `PIP_CONFIG_FILE` = the null device, `PIP_CACHE_DIR` = `files/runtime-data/pip-cache`, no version check, no prompts;
  the locked commands also pass `--no-cache-dir` (the store is the cache). The Qwen3 engine (`--isolated
  --no-cache-dir`, offline, hash-locked) and the spaCy restore (`--isolated --no-cache-dir --no-index`) keep their own.
- *Sentence data* (`shared/nltk_store`). nltk 3.9.4 needs only `tokenizers/punkt_tab/english/` (four files). The archive
  is pinned at nltk_data commit `4f15a3d` (4,319,076 bytes, SHA-256 `e57f6418…0106`, the SHA-256 NLTK's own index
  publishes) and the four files are pinned and re-checked before use. NLTK searches only `files/runtime-data/nltk_data`.
  It is fetched by first-run setup (named in the wizard text the person accepts with Begin Setup; a failure is not
  fatal), otherwise only after a Yes at Create for an Edge run of a directly added file; `ensure_punkt` never downloads,
  and the Edge folder route, Kokoro, Chatterbox and Qwen3 never depend on it.
- *Endings.* `FinalTail.abrupt` (sound at -60 dBFS within the last 10 ms window) makes the ending `uncertain`, so every
  route's run log says "please listen". Nothing is added or removed, and Qwen3 sampling is unchanged: Aiden stays an
  owner-listening case.
- *Stage 0.* Hashes with .NET instead of `Get-FileHash`, and the launcher clears `PSModulePath` for its stage-0 call:
  started from a PowerShell 7 window, Windows PowerShell 5.1 inherited PowerShell 7's module path, could not load
  `Get-FileHash`, and stopped after downloading Python (found by the isolated qualification).
- *Cleanup.* The post-exit Clear Downloaded Data coordinator may run on the app's own base Python
  (`files/runtime-data/python/python.exe`, outside `.venv` and every cleanup target); every other interpreter inside
  the folder stays refused. Without it, a computer whose only Python is the app's could not clear `.venv` (found by
  the 3.12.15 qualification). A required import that fails after install reinstalls the whole lock from the store
  (a dependency whose files are gone but whose metadata remains is "already satisfied" to pip).

**Not chosen.** `--no-cache-dir` alone (no reuse, no offline repair); pip's HTTP cache moved into the folder as the only
store (index pages expire, so it cannot repair offline); pip-tools or uv for the lock (a new dependency for what pip's
own resolver report already gives); hashes of every file of each release (one artifact is stricter, and pip filters
candidates to the allowed hashes); bundling `punkt_tab` in the release ZIP (redistribution not reviewed; the owner asked
for a consented, verified acquisition); padding or fading an abrupt ending (the policy never adds audio, Q1).

**Consequences.** Every existing installation reconciles once at its next launch (the requirements fingerprint now
covers the lock): about 505 MB is fetched into its store and only differing packages change (HOME-PC 2026-10-31:
`filelock` only). Editing `requirements.txt` requires regenerating the lock. A new package without a wheel must be
reviewed (a test lists the two). The store uses about 505 MB of disk inside the folder.

Signed: Claude Code (Opus 5.5), under the owner directive of 2026-10-31.

---

## 2026-10-25 - Optional voices are acquired only from pinned identities, under a spent consent, and inference loads only verified local copies; Chatterbox's unused s3gen file is dropped (v0.7.0 P05B Stage 2)

Plan Revision 2 §5.4 and §6 / P05B; owner spaCy ruling 2026-10-25; recorded by Claude Code.

**Identity, not location.** Kokoro and Chatterbox Turbo files are pinned by repository, commit, size and SHA-256 in one table
(`tts/model_assets.py`) that the planner, the acquirer and inference all read. URLs name the commit; `refs/main` is never consulted, so a
moved upstream cannot change what is reported, fetched or loaded. Because the identity is pinned, a file of another size or content is
`damaged` (repairable under repair consent), replacing the P05A "unverified, maybe newer". The spaCy model is the owner-approved wheel:
verified before pip, installed with `--no-index --no-deps --require-hashes` into a compatible spaCy that is never changed; not added to
`requirements.txt`.

**One acquirer, existing machinery.** Qwen3 goes through `qwen3_setup.install`/`repair` (one call for both models) rather than a second
installer; Kokoro/Chatterbox files through the same resumable, hash-verified `download_file`, behind an opener that refuses any URL outside
the confirmed files; local work under the existing Qwen3 `InstallLock`, so it is serialized with Qwen3 installs, Qwen3 conversions and
repairs of the app's own environment in the order they already use. Each destination is checked at the write. A proved-broken local engine
gets no download: model files cannot repair packages, which is the launcher's job.

**Inference refuses instead of fetching.** Kokoro is built from the verified local files (`KModel(config=, model=)`, voices from their
`.pt` through the pipeline instance), a missing spaCy model is refused before misaki's `spacy.cli.download`, Chatterbox uses `from_local`.
The refusal is its own exception type so it is never retried as an Application Control block nor taken as proof the packages broke.

**Health is a bounded fact.** The launcher's own proofs run contained, offline and time-limited; an inconclusive probe is unverified,
never healthy and never broken, and is not recorded.

**Chatterbox `s3gen.safetensors` dropped** (Stage 1 open item 7): `from_local` never reads it; acquiring 1.06 GB nobody loads would be an
unexpected file outside the required set.

**Tests refuse production writes at the write.** An audit-hook tripwire (tests only) turns any write-capable operation under the real
installation into `PermissionError` before it happens, for the optional-setup modules; after-the-fact fingerprints remain the suite-wide
guard.

**Not chosen.** `HF_HUB_OFFLINE` alone (offline mode resolves whatever `refs/main` names and verifies nothing); hashing on every load
without a record (gigabytes per Chatterbox load); repairing Kokoro/Chatterbox packages from optional setup (that is the base stack, Q32);
wiring bootstrap's first-run pre-downloads or any UI (P06).

## 2026-10-25 - A consent is bound to the acquisition terms of the plan that was shown; the setup worker's process tree is contained; results are atomic or absent (v0.7.0 P05B Stage 1)

Plan Revision 2 §5.4 and §6 / P05B; owner rulings Q14–Q20; recorded by Claude Code.

**Consent.** The P05A consent named a plan fingerprint that nothing checked. Protocol v2 binds a consent to the SHA-256 of the plan's
acquisition terms (selection; each chosen component's readiness and scope; every acquired unit's components, state, source and download
figure) and carries those terms; the worker recomputes the plan and compares both. Unconditional fingerprint equality was not chosen:
the approved first run confirms a pre-venv estimate and only later sees the exact plan. A pre-venv consent must name the estimate the
worker reproduces (it is deterministic) and covers the main plan only as a per-unit bounded refinement; anything else, and any repair,
needs a renewed confirmation. Scopes are per component, so a mixed install/repair plan is agreed explicitly, never under one scope.
Unknown sizes are listed and agreed as unknown, never counted as zero. Version 1 is refused rather than upgraded. A consent is spent once
just before acquiring; a request has one worker.

**Provenance.** A unit is acquirable only from an exact source: a Hugging Face commit, the Qwen3 manifest, or the hash-locked Qwen3
requirements. The spaCy English model has none until the owner rules, so it cannot be acquired through the plan.

**Process and results.** The worker is started through the existing `qwen3_process.spawn(require_job=True)` (suspended, Job Object,
resumed) rather than a second containment implementation; cancel, timeout and the end of every run end the whole tree and confirm the
job empty. Results are published only by hard link; where that is impossible nothing is published (the P05A exclusive-create fallback
could expose a partial file). An install success must name every component proved working afterwards.

**Not chosen.** An HMAC over the consent (the session token is already on the command line, and any process that can write the exchange
folder runs as the same user; the binding to a recomputed plan is the protection that matters); killing by PID or `taskkill /T` for the
worker; enabling any acquirer in this stage; adopting the spaCy wheel before the owner's ruling.

## 2026-10-25 - Optional voice setup is planned by one acquisition-free planner and answered by a worker that runs only in the app's own CPython 3.12 environment; what is not proved stays unverified (v0.7.0 P05A)

Plan Revision 2 §5.4 and §6 / P05A exit row; owner rulings Q14–Q20, Q32; recorded by Claude Code.

**Contract.** Four components in a fixed order (Kokoro, Chatterbox Turbo, Qwen3 CustomVoice, Qwen3 Cloned Voices / Base), with Kokoro
checked and the other three unchecked as the approved first-run defaults; the wizard itself changes in P06. Seven readiness states with a
fixed precedence: unsupported, bad-bundle, busy, damaged, unverified, missing, ready. Only *missing* can lead to an install and only
*damaged* to a repair, each under its own consent. A component with any unproved part is unverified: never installable, never healthy.
Engine health that needs a probe is a fact the caller supplies; files being present do not prove it.

**Sizes.** Every acquisition is a unit counted once (the shared Qwen3 engine; the Qwen3 files both models share, which are copied or
linked locally). Every figure states its basis: exact, manifest, approximate, at-least or unknown. Kokoro and Chatterbox sizes are
measured from HOME-PC's cache at recorded revisions and stay approximate because upstream is unpinned; what cannot be known without the
network (the spaCy package, the base-package download) is reported as unknown. Base application packages are always disclosed
separately and include the Kokoro and Chatterbox packages (Q32).

**Execution home.** Before the app environment exists only a manifest-derived upper-bound estimate runs (standard library, imports proved
in a bare interpreter). The worker runs as `.venv/Scripts/python.exe -E -s -m tts.optional_setup_worker` from `scripts/`, refuses any
other interpreter itself, accepts one contained request bound to its launcher's session token and at most 10 minutes old, and publishes
exactly one terminal result, which nothing replaces. A consent lists its units and known download; a plan that grows beyond it is stale.

**Not chosen.** Importing `qwen3_setup` into the pre-venv path (the exact Qwen3 plan runs in the worker, reusing `plan_install`); a
second Qwen3 planner; inferring Kokoro/Chatterbox health from file presence; reusing the old ~300 MB / ~3.9 GB strings as totals;
probing locks for `busy` in P05A (it would create lock files; P05B wires real locks).

## 2026-10-25 - P04C closes on the nested Qwen3 layout: .venv/engines/qwen3 is canonical, HOME-PC runs on it, the legacy .venv-qwen3 is kept unused for rollback; MachineGuard stays out of repair and cleanup; residual debt is assigned, not closed (v0.7.0 P04C Stage 5C)

Plan Revision 2 §5.5 and §6 / P04C exit row; owner rulings on P04C Stage 4 (Option B, MachineGuard, pinning, classifications); recorded
by Claude Code. Closure is conditional on the P04C full gate recorded in `checkpoints/P04C.md`.

**Topology.** The nested layout is adopted: a Qwen3 engine is an independent venv at `.venv/engines/qwen3`, created at that final path by
the verified base CPython 3.12, its identity kept outside `.venv`. Legacy `.venv-qwen3` copies keep working while they are the only engine;
when both exist the canonical one is used and judged, and the legacy one is never installed into, rebuilt or deleted. No automatic
migration, and no relocation of an existing environment.

**HOME-PC.** Stage 5B satisfied the exit's "create/verify canonical environment at final destination; retain legacy environment": the
production installer built the canonical engine (89/89 locked, 0 package bodies downloaded, GPU probe PASS), and the preset and clone
narrations matched the Stage 2 goldens byte for byte. `.venv-qwen3` is retained untouched as the rollback target (lease, rename the
canonical folder to an ignored quarantine, remove only `nested_environment`). Its retirement, and deletion of the Q/Q2 qualification copies
and the O3 cache, are separate owner approvals.

**MachineGuard: retained outside repair and cleanup.** Every holder of the guard in a copy already holds that copy's `inference.lock`
(conversion, clone transcription) or `InstallLock` (probe), both inside the engine lease, and an orphan worker holds `engine.lock`. Adding
the guard would add no file safety and would let another copy or another Windows user's conversion (or a `denied` guard) block repair of
a broken app.

**Assigned, not closed.** Main-stack transitive pinning stays deferred (AUD-010; P07/P10 fresh-ZIP qualification covers the drift
risk). Pip-less parent repair (Minor) and Kokoro/Chatterbox model removal under a second window of the same copy (Minor) → P07. The P04B
L cases (true standard user, restricted ACL, long paths disabled, clean-machine SAC, other GPUs/CPU-only, cross-user MachineGuard `denied`)
are UNPROVED → P10 / AUD-004.

**Not chosen.** Option A (closing on the Q2 qualification copy with an exit amendment); migrating `.venv-qwen3` by rename or copy;
deleting the legacy engine at adoption; taking MachineGuard in the repair/cleanup lease.

## 2026-10-25 - The Qwen3 dialog states the engine in use and the destination of a new one from the path authority; a real canonical engine is guarded per test by its identity and top level, and walked whole once per session (v0.7.0 P04C Stage 5A)

Plan Revision 2 §5.5 and §6 / P04C; recorded by Claude Code. Source + tests only; no environment created or changed.

**Dialog.** The install dialog no longer names a fixed engine folder. `qwen3_install_ui.location_text()` asks the runtime
(`venv_dir`, `is_nested`, `environment_status`) and keeps two facts apart: the engine in use (an earlier version's `.venv-qwen3`,
never said to have moved, or `.venv/engines/qwen3`, healthy or needing repair) and where a new or rebuilt engine goes (always
`.venv/engines/qwen3`). It no longer invites deleting folders, and says the engine is not part of the app's own dependencies.

**Test guard.** Walking `.venv/engines` around every test is free while it is absent and about an hour per gate once a real engine is
installed. Per test it is now fingerprinted by what identifies and lays out an engine (one-level listings of `engines`, the engine and
`site-packages`; `pyvenv.cfg` by hash; `Scripts` in full); the whole tree is walked once at the session boundary without following
links. Listings record names, kinds and the folder's own `stat` mtime, never the entries' listing timestamps, which NTFS lets lag.
Accepted limits: no package content is hashed, and a deep edit is reported for the run rather than the test. Nothing in the engine is
exempted; lock files live outside it and keep their own guard.

**Not chosen.** Hashing the engine (5.5 GB); a per-test recursive walk of `site-packages`; exempting `__pycache__`.

## 2026-10-25 - Clear Downloaded Data removes the app environment and the models only under the Qwen3 engine lease; nested engines and repair asides can never be packaged or staged (v0.7.0 P04C Stage 3)

Plan Revision 2 §5.5 and §6 / P04C; recorded by Claude Code. Source + tests only; no live environment changed.

**Lease.** The post-exit coordinator only looked for `.venv/engines/`; with no child yet, a first Qwen3 install holding `setup.lock` (folder
not yet created) passed the look, and an install starting mid-deletion could build inside a half-deleted parent. Models had the same gap
against a conversion, model check, model install or orphan worker. Catalog items now carry `requires_engine_lease` (True for
`virtual_environment` and `downloaded_models`); the coordinator takes `shared.engine_lease` (setup → inference → engine, all or none,
never waiting) before re-authorizing such an item and holds it through removal. Busy, denied, linked or unmakeable locks refuse that item
(`refused`, nothing removed, lock-specific sentence or "could not check"); every other selected item is handled as before. Taken per item,
so a refusal never blocks binaries or logs. MachineGuard is not taken (it protects no file; Stage 1 ADR stands).

**Not chosen.** Detaching, recreating or migrating a held engine so `.venv` can be cleared; offering the engine as a fifth item; waiting
for a busy lock; refusing the whole request when one leased item is busy.

**Wording.** The `.venv` item says it rebuilds "the app's own dependencies" and that "the Qwen3 voice engine is not part of this item"; the
held-engine refusal is unchanged.

**Packaging/ignore.** The packager already walked only `scripts/`; it now also excludes directory components starting `.venv.` or `.venv-`
(set-aside and preserved copies) besides `.venv`/`.venv-qwen3`. `.gitignore` gains `/.venv.replaced*/` and `/.venv.discarded*/`, which were
not ignored. Regression tests force-commit nested engines, asides, preserved copies, models and private records into a fixture repo.

## 2026-10-25 - The Qwen3 engine is installed at .venv/engines/qwen3, built from the verified base Python; a repair always takes the engine lease first (v0.7.0 P04C Stage 2)

Plan Revision 2 §5.5 and §6 / P04C; recorded by Claude Code. Source integration only: no live HOME-PC environment was migrated, rebuilt or
removed. Extends the Stage 1 entry below (its "taken only when something is held" rule is superseded by the unconditional lease here).

**Path authority.** `qwen3_runtime.venv_dir()` is `.venv/engines/qwen3` unless only the legacy `.venv-qwen3` is present. Anything at the
canonical path (a link, an empty or half-made folder included) makes it the one judged, so a damaged new engine is reported, never hidden
behind an older one; when both exist and the canonical one is unusable, the status sentence says the older one is not used. Nothing else
is searched for.

**Creation.** The installer always targets the canonical path, never the legacy one. It creates the engine there directly with
`<base> -I -m venv <final absolute path>`, where `<base>` is `sys._base_executable` (as `python.exe`) proved first on disk (a file, not a
link, outside the app folder, no `pyvenv.cfg` beside or above it) and then by running it isolated (CPython 3.12, `prefix == base_prefix`,
itself as executable). The new `pyvenv.cfg` must name that base. Identity lives outside the replaceable parent, in `state.json` under
`nested_environment`: path, stage (`creating` before `-m venv`, `created` with `venv_layout.base_identity` after it, `installed` after the
probe, `removing` before a rebuild deletes it). `environment_status` trusts the canonical engine only when `venv_layout.assess_child`
proves identity against that recorded base and the record is complete. The legacy record keeps its old key and shape.

**Legacy.** Never installed into, rebuilt or deleted by the app (`safe_to_remove_environment` accepts only the canonical folder). A
healthy legacy-only engine keeps working; adding a model does not reinstall the engine. If it needs rebuilding, the repair builds the
canonical one instead and the plan says so ("installed in its new place … the older .venv-qwen3 … is not changed or deleted"). Removing
`.venv-qwen3` stays the owner's decision. Flagged for review: on such a copy the old folder's disk space (about 5 GB) is not reclaimed.

**First-install race.** `bootstrap._take_engine_lease` (renamed from `_take_held_engines_lease`) takes `setup` → `inference` → `engine`
before any parent mutation even when nothing is under `engines/`. `install_environment` holds `InstallLock` (setup → inference) from its
first check to its last record, taking it itself when the caller does not and reusing one this thread already holds (never two handles on
one lock, which would refuse itself). So whichever starts first wins and the other refuses with nothing changed. `InstallLock` also
checks `engine.lock` is free and gives it back at once: every worker this copy starts is started under `inference.lock`, which the
installer holds, so only an orphan worker can hold it, and the installer's own probe must be able to take it. Order and non-blocking
refusal are unchanged; MachineGuard stays out of the repair lease (Stage 1 ADR). Consequence: a conversion on a legacy engine now also
refuses a main repair, because its `inference.lock` cannot be told apart from an install's.

**Refusals added.** The engine is never created in a parent without `pyvenv.cfg`, reached through a link, or with a `.venv.replaced*`
pending (only setup/repair resolves that); pip is never run into a canonical engine that cannot be verified (it is left alone until a
repair rebuilds it); an interrupted creation or removal is cleared and redone by the next install.

**Subprocess environment.** `worker_environment` (and so `installer_environment`) drops every inherited `PYTHON*` and `PIP_*` variable and
the venv/conda activation variables, and removes from `PATH` the folders of any other Python environment (a folder whose own or parent
folder holds `pyvenv.cfg`, or with `conda-meta` up to two levels up), the app's `.venv\Scripts` included. Everything else on `PATH`
(Windows, GPU driver, CUDA, a base Python) is kept in order.

**Not decided here.** Migration or removal of `.venv-qwen3` on HOME-PC; maintenance/cleanup wording and the packaging check for the nested
layout; main-stack pinning. Each is a later P04C stage behind owner review.

---

## 2026-10-24 - A voice engine held inside .venv is protected by its users' own locks, taken together before any change to the environment (v0.7.0 P04C Stage 1)

Plan Revision 2 §5.5 and §6 / P04C; recorded by Claude Code. Supersedes P04A's assumption that a running engine would make a repair
fail safely: P04B proved natively that Windows renames a folder whose programs are mapped into memory, so file-system refusals protect
nothing here.

**Protocol.** Three lock files in the copy's `files/runtime-data/qwen3/`, all with `qwen3_runtime.FileLock`'s non-blocking byte-0
protocol: `setup.lock` (engine install/repair, `InstallLock`), `inference.lock` (every conversion, transcription and model check, held by
the app for the run; `InstallLock` takes it too) and `engine.lock` (held by the worker process itself, so an engine whose app has gone is
still seen). `shared/engine_lease.Lease` takes them in exactly that order, never waits, and on any refusal releases what it took in
reverse. The operating system drops them when a process dies (measured: free 0.22 s after a kill). Taking a lock creates its empty file
and writes nothing else.

**Who takes it.** `repair_venv` and `run_setup`, before recovery or any rename, whenever `.venv` or `.venv.replaced` holds anything under
`engines/`, held until commit/rollback/cleanup end. Busy, denied, unreadable or reached through a link is an immediate refusal with
nothing changed. With nothing held (the shipped `.venv-qwen3` layout) no lock is consulted and behaviour is unchanged. When the nested
layout is adopted and the installer can create the child, the lease must be taken unconditionally (adoption stage).

**Machine guard excluded.** `MachineGuard` keeps every copy of the app on the computer to one model on the GPU at a time; it protects no
file of this copy, and every user of this copy's engine already holds `inference.lock` or `engine.lock`. Taking it would refuse this
copy's environment repair because another copy (or another Windows user) is converting, and its `denied` case could block the repair
of a broken app indefinitely. Reversible: one more lock in `ORDER` if the owner rules otherwise.

**Worker.** Refuses (stage `engine`) before any heavy import when its job names no `engine_lock`, when that lock is held, or when its
interpreter's prefix lies inside `.venv.replaced*` or `.venv.discarded*`: an engine only ever runs at its own final path.

**Superseded environments.** Renamed to `.venv.discarded` before deletion, so a deletion cut short (mapped DLLs, a crash) can only be
finished, never restored as last-known-good. A leftover is reported in the log and the repair message (still a successful repair — the
new environment launches — but never a clean one); recovery finishes deleting it. A rename refused by an open handle keeps the old
environment whole under its own name.

## 2026-10-24 - The app environment's own lifecycle keeps anything held under .venv/engines/; the nested Qwen3 layout stays a candidate, not adopted

Plan Revision 2 §5.5 and §6 / P04A (owner task "Execute P04A: Nested Environment Lifecycle Safety and Recovery Tests"); recorded by
Claude Code.

**Not a topology change.** Qwen3 still runs from `.venv-qwen3` (`qwen3_runtime.venv_dir()` unchanged). `.venv/engines/qwen3/` is a
candidate only: nothing installs there, nothing is migrated, and adoption needs P04B's real proof and the owner's decision.

**Vocabulary.** New `shared/venv_layout.py` (read-only, standard library only, imported by the bootstrap and the cleanup
coordinator). Anything under `<parent>/engines/` is *held*: a folder, a file or a link, with an unreadable folder counting as holding
something. A child environment is identified, never assumed: at its own final path, reached through no link below the repository
root, `include-system-site-packages = false`, interpreter present, not built from the parent's interpreter, still where `pyvenv.cfg`
`command` says it was created, and matching a recorded base-interpreter identity (home, version, executable, its size and mtime).
Missing, changed or unrecorded evidence is `unverified`, never healthy, and identity is not engine health (the import probe is still
required). The two Qwen3 locations are named exactly; both present is reported, never resolved by deleting one.

**Bootstrap transaction** (inert today because nothing is held). `VenvReplacement.commit` first moves `engines/` from the set-aside
environment into the replacement (one `os.replace`, so it is in exactly one place at every instant and returns to the same absolute
path), with the same bounded Windows WinError 5/32 retry as setting a venv aside (now one helper, `_replace_retrying`). An aside that
still holds anything is never deleted; commit keeps it (`retained`), the repair still succeeds and says the folder was kept, and the
next recovery retries. A rollback moves whatever the candidate holds back into the aside before deleting the candidate and refuses to
delete if it cannot; it now removes the candidate's import proof before deleting anything, so an interrupted rollback can never be
mistaken for a finished repair. Recovery applies the same rules in every branch. A link, a conflict (both sides hold something) or a
refused rename leaves both sides as they were. The main repair cannot reach the Qwen3 installer.

**Cleanup.** The "Private Python environment" item is refused while `.venv` holds anything under `engines/`, both in the inventory (row
present, not selectable, with the reason) and again in the coordinator immediately before acting: "dependencies rebuild on the next
launch" is not true of a voice engine. The catalog is still exactly four items; including or separately offering a held engine is a
P04C/owner decision. The coordinator's module set grows by `venv_layout.py`.

**Qwen3 removal.** `safe_to_remove_environment` and `environment_location_problem` also refuse a link in any folder between the
repository root and the environment (`qwen3_runtime.link_below_root`). For `.venv-qwen3` this is exactly the old leaf check; for a
nested path it closes a bypass in which a junction at `.venv` or `.venv/engines` to another folder inside the repository passed both
old checks and a rebuild would have deleted that folder's contents.

**Not chosen:** copying or renaming an installed environment into the nested path (environments are not relocatable; the identity check
rejects a moved one); merging or choosing between two held copies; deleting a backup that holds the only copy; force-stopping
processes, elevation, ACL or antivirus/Smart App Control changes to make a rename succeed; widening retries beyond the existing 250 ms.

**Not changed.** Production paths, model pins, generation parameters, TTS behaviour, the transcript bundle, the six WAVs, the 28
previews, version identity 0.6.6.

---

## 2026-10-24 - Developer mode is a typed config.toml boolean, shipped false; the reference-transcript tools and any local override are developer-only

Plan Revision 2 §5.3 config contract and §6 / P03D (owner task "Execute P03D"); recorded by Claude Code.

**Setting.** `config.toml` gains `[development] developer_mode = false`. `shared/config.py` accepts only a genuine TOML boolean
(`type(raw) is bool`); a missing key or section is the built-in `false`; a string ("true"), number, table, date or malformed file
resolves to `false` with the normal per-key diagnostic. The typed immutable snapshot carries it as `EffectiveConfig.development.developer_mode`
with its source layer (`default` or `config.toml`). It is not a `settings.json` overlay (`SETTINGS_OVERLAY` is unchanged, so any settings key
naming it is reported and ignored), there is no environment-variable shortcut, and the app never writes the TOML. `config.developer_mode()`
reads the cached snapshot, so an edit takes effect when the app is started again (documented in the TOML). The repository gate
(`verify.py` config check) fails unless the committed file states `developer_mode = false` explicitly, and the packager refuses a checkout,
and re-checks each finished archive's own `config.toml` member, unless it says exactly `false`.

**Normal mode (false).** "Install / repair Qwen3 voices" creates no transcript-tool button (`btn_clones is None`); installing, repairing
and all eight Qwen3 voices are unchanged, and the six clones read only the shipped bundle (P03C). Nothing checks, downloads or runs the speech
recognizer. Enforcement is in the backend, not only the widget: `qwen3_runtime.require_developer_mode()` (`DeveloperModeRequired`) guards
every restricted path. `load_transcript(..., override=)` returns a refusal. `ACT_QWEN3_TRANSCRIPTS` is ignored (`local_store_path()` is the
default file). A selection file is never read. `qwen3_clone_setup` refuses `install_recognizer`, `create_drafts` (through
`drafting_problem`), `approve`, `write_store`, `select_for_narration` and `return_to_shipped` before touching the store. The clone dialog
refuses to build. `qwen3_transcript_review.py` refuses `build`, `apply` and `status --store` (plain `status` still reports the bundle), and
`voice_previews.py` refuses `--provisional-transcripts` and the provisional loader. The calm harness only reads `load_transcript` and needs no
gate.

**Developer mode (true).** One entry point appears: "Developer tools → Reference transcripts..." (dialog title "Developer tools →
Reference transcripts"), reusing the existing recognizer-install / local-draft / listen-and-approve workflow and its save-error recovery. The
dialog states that local approvals do not replace the shipped transcripts. Downloads and transcription still need their own button and
confirmation. Developer mode alone activates neither the ambient store nor the variable: narration changes only for a clone the developer
deliberately selects ("4. Narrate with my approved texts...", confirmed; "Use the shipped texts" undoes it). The selection is private state in
`files/runtime-data/qwen3/transcript-selection.json` (ignored, never packaged): `{"schema": 1, "voices": {<voice_id>: {"reference_id",
"wav_sha256", "text_sha256"}}}`. It stores no text or path, is keyed by stable voice id, and only an approved local entry for the recording on
disk can be selected (all or nothing). At use, the local entry must still be literally approved, bound to the registered recording, pass the
bundle's text rules and hash to the selected digest. Otherwise that clone fails closed with "Developer tools → Reference transcripts" advice and
never falls back to the bundle. A damaged selection file refuses all six until it is cleared. The bundle file is never written. A preview never
records a developer-selected text as the shipped one.

**Not changed.** The bundle (`dd953523…7429`, byte-identical), the six reference WAVs, the 28 preview WAVs, speech parameters, P01 tail and
P02 naming policies, the other engines and tools, version identity 0.6.6.

---

## 2026-10-24 - The six clone transcripts ship as a curated bundle; narration trusts only that verified bundle

Owner approval 2026-10-24 (plan Revision 2 §5.3 step 5 / P03C, owner rulings Q8, Q13, Q35); recorded by Claude Code.

**Approval.** The owner personally reviewed and approved the six final Qwen3 clone reference texts in the 4,334-byte private review file with
SHA-256 `48f5dbeff1e866f94da2b4f93fc91a2842533ed96a5c1b0661605295ab20c236` (not the superseded `c22a9dc5…9b4`), and authorised publishing exactly
those six texts, only in `scripts/tts/data/bundled_clone_transcripts.json`, with only these fields: top level `schema_version`, `bundle_revision`,
`entries`; per entry `reference_id`, `voice_id`, `wav_sha256`, `text`, `text_sha256`. No approval record, personal information, original store or
review artifact is published. The approval does not cover further transcript changes, audio synthesis or P03D. The private review file, the preserved
store and all review evidence stay ignored.

**Generation.** `files/dev-tools/clone_transcript_bundle.py` (developer only) read the approved file once and refused it unless its SHA-256 equals the
approved hash. It refused any envelope or entry whose fields were not exactly the expected set, and checked the six registered IDs in order with their
voice IDs and WAV hashes, each text (non-blank, ≤ 2,000 characters, no outer whitespace or control characters, Male-4 starts with "Hello Arthur.") and
the six recordings on disk. It then wrote the bundle by exclusive create, copying the texts byte for byte (UTF-8, LF, fixed key order). The model
never typed or read the texts. The result: bundle revision 1, 3,002 bytes, SHA-256 `dd9535236ca2d09012ffdc1946de78115176dc95902da47e9ae7cdbb51cd7429`. The
six text digests equal the owner-validated ones (Female-1 `74b8174d…`, Female-2 `dd7cbd39…`, Male-1 `5afea1f7…`, Male-2 `3589fb60…`,
Male-3 `7be44794…`, Male-4 `a66dcfea…`), and `test_bundled_clone_transcripts.py` pins all six. `--check` mode reproduces the committed file byte for
byte. `.gitattributes` keeps `scripts/tts/data/*.json` LF on every checkout. Hashing is integrity binding, not a publisher signature.

**Resolution (supersedes the v0.6.7 Q5 "never committed, each user approves locally" rule).** `qwen3_runtime.load_transcript(voice_id)` returns the
bundle text exactly as stored (no strip, no normalisation) and nothing else: no search path, no `ACT_QWEN3_TRANSCRIPTS`, no local store. A local
store is read only through an explicit `load_transcript(..., override=path)` (the maintainer tools); `local_store_path()` names where those tools
keep it. The whole bundle is validated on every read (`load_bundle`): exact top-level and entry field sets, `schema_version` the integer 1, a
positive integer `bundle_revision`, exactly six entries for the six registered clones with no duplicates, the registered voice ID and recording hash
for each, text rules as above, and a lowercase `text_sha256` equal to the UTF-8 digest. Duplicate JSON keys, a BOM, invalid UTF-8/JSON and files
over 64 KiB are refused too. A bundle that fails any check is trusted in no part: all six clones report "Setup required for <label>: the reference
transcripts shipped with the app are … . Extract a fresh copy of the app to restore the files it ships with." The presets, Edge, Kokoro and
Chatterbox are unaffected, and nothing falls back to a local store. A recording whose bytes differ from its registered hash still blocks only its own
clone (Q10, unchanged). A fresh install with the engine, the Base model and the six recordings therefore has six ready clones, with no recognizer, no
approval and no write.

**Tooling and UI.** The install dialog reports "Cloned voice transcripts: included with the app." (or the bundle problem) instead of a local
"set up: N of 6" count. "Set up cloned voices…" stays visible until P03D gates it behind developer mode. Its wording and the clone-setup module now
call it a maintainer workflow whose approvals stay in the local store and do not change the voices. `qwen3_transcript_review.py status` reports the
bundle, and `status --store FILE` reports one named store. The voice-preview tool's provisional loader takes `override=`, and its README paragraph now says
the app uses the shipped approved texts (the six clone preview WAVs are unchanged and still labelled provisional). The calm-narration harness already
used the app's resolution, so it now reads the bundle. The README's "Set up cloned voices" step is removed.

**Packaging.** The packager already ships every tracked file under `scripts/`, so the bundle ships with no packager change. The tests' blanket "no
member names a transcript" ban becomes a one-path exception for exactly `scripts/tts/data/bundled_clone_transcripts.json`. Near-miss paths and every
local store, model, environment and log stay refused, and the bundle must appear once in each archive with its committed bytes. A packager-side
allowlist check stays with P07A.

**Not changed.** Voice identity, recordings (6/6 Appendix A), the 28 preview WAVs, generation parameters, `config.toml` (P03D adds `developer_mode`),
the extraction helper and the original private store (`8469606c…`, untouched).

---

## 2026-10-24 - The six clone references live in files/Cloned-Voice-Uploads/, resolved canonical-only; the no-echo extraction helper is tracked developer tooling

Plan Revision 2 §5.3 and §6 / P03A; recorded by Claude Code.

**Move.** The six tracked WAVs moved by scoped `git mv` from `files/Chatterbox-Voice-Uploads/` to `files/Cloned-Voice-Uploads/`; basenames and bytes
unchanged (SHA-256 = plan Appendix A, 6/6). The old folder was not moved or emptied: it keeps the owner's six ignored MP3 originals.
`voice_registry.REFERENCE_DIRECTORY` is the one path authority for both engines; `release.REFERENCE_ASSETS` keeps its own literal closed allowlist (the
packager imports nothing from the app) and a test pins the two together. This completes the 2026-10-24 P02A note that the directory stays until P03A.

**Canonical-only; no legacy lookup.** No supported workflow leaves the recordings at the old path: a fresh archive ships them at the new path and an
archive extracted over an older folder writes them there too; a git checkout moves them with the commit; there is no in-app updater and the README
documents fresh extraction only; the P12 restoration covers `.venv`, `.venv-qwen3` and `files/runtime-data`, never the references; Chatterbox
derivatives/conditionals and Qwen3 transcript bindings are keyed by WAV SHA-256, not by path (the clip manifest's `source_path` is never read back). So a
missing canonical file is "setup required", a canonical file with the wrong hash fails closed, and an old copy is never consulted, opened or deleted.
Revisit only if a supported path that needs a lookup is found; then it must be exact-basename, hash-matched, canonical-preferred and report conflicts.

**Ignore rules.** `files/Cloned-Voice-Uploads/*` with exact-basename exceptions for the six WAVs; `files/Chatterbox-Voice-Uploads/` ignored whole, so a
WAV cannot be re-added at the old path. Fixes baseline hazard H4 (the exceptions named non-existent `Female-1.wav`-style files; the real WAVs were
tracked only because they were already indexed). Git on Windows matches case-insensitively (`core.ignorecase`), so a case variant of a canonical name
matches its exception; on that filesystem it is the same file.

**No-echo helper.** `files/dev-tools/clone_transcript_extract.py` implements §5.3 steps 1–3 and 6: store found only through the named preservation
manifest, read once read-only and fingerprinted before/after, exactly six IDs with literal `approved: true`, registered WAV and text digests, Male-4
opening check, exact text copied without strip or normalisation, exclusive-create owner-only ignored output, link/escape/overwrite refusals, and
metadata-only stdout/stderr/report (unexpected exceptions by type name only). Adapted from the ignored private tool used for the earlier exceptional
review, with: the manifest named by argument and its tag read from `preservation-<tag>.json` (no owner-specific constant in tracked code); the
canonical folder; owner-only access in both modes (the private tool restricted only review-pending); a store size cap; a fixed refusal for an existing
run folder. Its registry is pinned and test-checked against the app. Tested on synthetic fixtures only (`test_clone_transcript_extract.py`); it has
not been run on the real store. P03B runs it unchanged, and only when authorised. The private tool and its owner-edit validator stay ignored.

**Not changed.** Transcript resolution (`qwen3_runtime.load_transcript` and its search paths), voice identity, naming, timing and generation parameters.
The previously validated private review artifact stays UNAPPROVED and NOT FOR SYNTHESIS (identity in ignored evidence only); that exceptional review is
not P03B or P03C authorisation.

---

## 2026-10-24 - One TTS output name: <source-stem>-<frozen display label>.mp3; collisions numbered; an invalid voice list is a registry error

Owner decisions Q4/Q5/Q6 (plan §2 and §5.2), implemented at P02B; recorded by Claude Code.

**Name.** Every narration route (Edge direct and folder, Kokoro, Chatterbox, Qwen3 presets and clones, standalone `batch_convert.py`) names its file
`<source-stem>-<display label>.mp3` through `tts/output_names.py`. Superseded: Edge direct `<stem> (<speaker>).mp3` and every other route's `<stem>.mp3`.
The label is frozen by value in the run's tool options (`freeze_tts_options(label=...)`) and destinations are planned from that frozen value once, at
run start; a retry reuses the planned destinations, so a renamed or reordered registry moves no run. The label is only ever text in a file name. No
backend or voice-id suffix is added; clashes (existing files, case-only, Unicode-composition and sanitised duplicates, same-stem PDF/TXT, duplicate
occurrences, mixed direct/folder) are numbered by the shared `DestinationPlanner` (`stem-1.mp3`). The Edge direct engine still writes its private
`<stem> (<speaker>).mp3` inside a temporary folder; only the planned name is ever published.

**Sanitation (TTS-local, on top of `shared.output_paths`).** Stem and label are cleaned separately (so `AC/DC` is `AC_DC`, not a name cut at the `/`):
NFC, control characters dropped, Windows-forbidden characters and separators and unpaired surrogates become `_`, outer whitespace stripped; spaces,
punctuation and Unicode kept. A device name is guarded with `_` only where Windows would see one (before the first dot: `nul.backup-…`); `CON-Label.mp3`
is legal and kept.

**Length.** A planned name leaves room for the longest collision suffix (`-10000`) and the longest temporary publish name (`.<8 hex>.part`, Qwen3):
20 units in the 255 component and, where the platform limits it, in the whole path (Windows without long-path support: 259, folders 247, counted in
UTF-16 units; macOS/Linux: 1023 UTF-8 bytes; Windows with `RtlAreLongPathsEnabled`: component only). Only the source stem is shortened, from its end;
the label is never cut. If even one stem character cannot fit, or the folder itself is too deep, planning raises `OutputNameError` (an
`OutputPathError`) before anything is synthesised, and the panel releases the empty run folder it had reserved.

**Standalone helper.** `run_batch_convert(label=None)` defaults to the registered label of the Edge `speaker` and refuses an unregistered speaker
without an explicit label (`--label`). Without `--resume` an existing file is never overwritten (the new file is numbered); with it, names are planned
without the disk so an earlier output is found under its own name and skipped. The Edge folder route's scratch folder is now a 16-hex digest of the
destination (the joined relative path could exceed one 255 component). Non-TTS tools' names and `shared/output_paths.py` are unchanged.

**Registry error at launch.** The launcher's per-tool error panel recognises a genuine `tts.voice_registry.VoiceRegistryError` (class name, defining
module and `ValueError` base; the exception itself only) and shows its message with "correct the listed entries in scripts/tts/voice_registry.py"
instead of "a dependency is missing … reinstall requirements". TTS stays unavailable (no fallback, no skipped voice); the other five tools load. Every
other load failure keeps the original advice and traceback. The status bar still reads "— ready." after any failed load, as before (pre-existing).

## 2026-10-24 - Voice identity is (backend, voice_id); labels and order are cosmetic; the six recordings are fixed by table

Owner decisions Q5/Q31 (plan §5.2), implemented at P02A; recorded by Claude Code.

**Identity.** `VoiceEntry.key == (backend, voice_id)` is the durable identity. `display_label` and row position may be edited freely: the dropdown is
`VOICES` order exactly (engine groups may interleave; nothing regroups or sorts), the default is `DEFAULT_VOICE_KEY` (Steffan) under whatever label he
carries (`default_voice_label()`), and lookups (`voice_by_key`, `label_for`, `get_voice`) read `VOICES` at call time.

**Recordings by table, not by label.** `reference_recording_filename(voice_id)` (which built `"<Chatterbox label>.wav"`) is replaced by explicit data:
`VOICE_REFERENCES[(backend, voice_id)]` → stable reference id (`Female-1` … `Male-4`, which is also the Qwen3 transcript key `reference_name`) →
`REFERENCE_RECORDINGS` fixed basename (`Chatterbox - Female 1.wav` … `Chatterbox - Male 4.wav`, unchanged). `reference_recording_filename(backend,
voice_id)` now takes the backend. `CLONE_REFERENCE_VOICE` (qwen→chatterbox id map) is removed; the shared recording is found through the reference id.
The directory stays `files/Chatterbox-Voice-Uploads/` until P03A. This supersedes the 2026-10-20 "reference recordings named after their labels" wording
(the files, bytes and hashes are untouched).

**One label authority.** `qwen3_runtime.Qwen3Voice` and `chatterbox_synth.ReferenceVoice` no longer store a label; `.label` is a property reading the
registry by stable key (lazy import in `qwen3_runtime`, so the registry never imports an engine). Visible consequences: Chatterbox engine log/status text
now says `Chatterbox - Female 1` (the registry label) instead of the engine's own em-dash `Chatterbox — Female 1`, and the Qwen3 install dialog lists
the presets as `Qwen3 - Aiden and Qwen3 - Ryan` (was the fixed `Aiden and Ryan`). An unregistered Chatterbox evaluation candidate is shown by its id.
Model descriptions (`CustomVoice`, `Base`), preset speaker tokens (`Aiden`, `Ryan`) and the clone generation profile are unchanged.

**Validation (`registry_problems` / `check_registry`, run on import).** Refused, each with the stable keys named: unknown backend; a voice id that is not
a plain token; the same `(backend, voice_id)` twice; the same voice id under two backends (preview files and the panel's voice code key on the id alone);
an empty, padded or control-character label; two labels equal after Unicode NFC (displayed text is kept exactly as written; case-only differences are a
P02B filename concern, not a label duplicate); a missing default voice; a Chatterbox row with no reference mapping. On import failure the launcher's
existing per-tool error panel shows the message for TTS only; other tools load (bootstrap never imports the registry).

**Panel.** `run_job` refuses a label that resolves to no registered voice ("Voice not recognised") instead of the old silent fallback to backend `edge`
with the last voice id. `_default_timing_preset` is now unreachable from `run_job`; it is left in place (P01 tests pin it) for a later cleanup decision.

**Previews.** `files/dev-tools/voice_previews.py sync-labels` is a metadata-only operation: it copies registry labels and order into `previews.json`
and re-renders the README; it reads no WAV, calls no engine, downloads nothing, refuses a roster or engine change, and its result must pass
`label_sync_problems` (only per-voice `label` and voice order may differ) before anything is written. `check` now also reports labels that differ from
the registry ("run sync-labels"). The existing `sync` was measured as a no-op on the committed manifest and is unchanged.

## 2026-10-23 - P01C before the combined owner listening session (checkpoint order only; acceptance unchanged)

Owner direction 2026-10-23 ("ACT v0.7.0 — P01C Edge EOF remediation and five-voice listening evidence"); recorded by Claude Code.

**The owner wants real production samples of all 28 voices before one consolidated manual listening session, so P01C (Edge) is implemented and
technically verified before the P01B listening checkpoint instead of after it.** The plan (§6 P01B/P01C exit rows) put owner listening of the local
endings before further audio changes; this changes the order of checkpoints only.

- Acceptance standards are unchanged: every ending still needs ≤ 300 ms measured trailing near-silence **and** owner listening PASS (§5.1). Mechanical
  figures never stand in for listening.
- Status words stay exact: P01B owner listening **NOT RUN**; combined 28-voice listening **NOT RUN**; P01C technical verification may PASS while its
  owner listening stays **OPEN**. Nothing is marked accepted without the owner's exported verdicts.
- If the combined session finds a clipped or wrong ending (local or Edge), it is corrected then; no long tail is added to compensate (§6 P01 exit).
- P02/P03 and later phases are not authorised by this exception.

## 2026-10-23 - Edge narration ends with its last sound: direct and folder routes share the P01B final-tail policy

Owner decision Q1 (plan §5.1), implemented at P01C; recorded by Claude Code.

**Edge direct (`epub2tts_edge.read_book` → `make_mp3`):** the book's final sentence gets no sentence/paragraph pause and the final chapter no chapter
pause; every pause between rendered content (sentence, paragraph, comma/ellipsis/dash, title, between-chapter) is unchanged. `end_of_book_pause` is still
accepted by `read_book`, `run_conversion_job` and the `--end-pause` command-line option, so no caller breaks, but it adds nothing and its default is 0 —
the same treatment P01B gave the local engines' `end_silence_ms`. Measured old stack after the final word: paragraph 850 + chapter 2,000 + end 3,000 =
5.85 s (the "about 6 s" seen in the app).

**Edge folder (`batch_convert.merge_mp3s`):** the 50 ms `CHUNK_PAUSE_MS` join goes between chunks only, and `END_RECORDING_SILENCE_MS` (3,000) is
deleted rather than set to 0, so it cannot quietly come back. The padding Edge returns at the end of every earlier network chunk is pacing and is kept.

**One policy, no extra encode:** both routes apply `tts.audio_tail` (−60 dBFS nominal end + 150 ms, never less than the −70 dBFS end, terminal suffix
only) through a new pydub adapter `apply_final_tail_policy_to_segment`, which reads the segment's own signed PCM (8/16/32-bit) and returns an exact
sample prefix (`get_sample_slice`). It runs on the already-decoded assembly immediately before each route's existing single MP3 encode; the encoder calls,
bitrate handling and no-clobber/cancel paths are untouched (the direct route's encode line is byte-identical). The folder worker logs the tail line per
file; the direct engine prints it like its other progress lines.

**Deliberately unchanged:** the direct route's per-sentence −58 dBFS edge trim (approved v0.6.5; it also shapes every internal pause), the generic MP3/M4B
tools, the Edge CLI's own `--format m4b` route (not used by the app: it now has no closing pause structurally, but no tail policy, because applying it
there would mean another decode), and `generate_voice_samples`' raw single-chunk Edge preview call (no ACT assembly or pause; trimming it would add a
lossy generation). Speech-characterization goldens for `edge_direct`/`edge_folder` were regenerated on purpose; every changed field is the removed pause
arithmetic (`audio/p01c/golden-diff.txt`, `golden-reconcile.txt`); text, splits and the other four routes are byte-identical.

## 2026-10-23 - A venv that must be replaced but cannot be set aside fails the repair; Windows retries WinError 5/32 within 250 ms

Owner-authorised at P01B (owner task "P01B Windows Venv-Rename Reliability Fix"); recorded by Claude Code.

**When the health authority says REPAIRABLE, the old environment must be renamed aside before anything is created in its place.** If that rename fails
and the environment is still there, `_create_validated_venv` returns False and the repair reports failure with the previous environment unchanged. There is no
create, no package reconcile, no stamp and no commit. Before this, the environment was kept and `repair_venv` could report "rebuilt, with limits" when
nothing had been rebuilt. Healthy and deliberately DEGRADED environments are still kept as before.

**`_move_venv_aside` retries only on Windows and only for WinError 5 (access denied) or 32 (sharing violation).** These are the refusals another process's brief
handle causes, and they were measured to clear within 2 ms. It retries the same source and destination with delays of 5–80 ms inside a single 250 ms
monotonic budget. No sleep or attempt may run past that budget, and before each retry it re-checks that no aside has appeared. Any other error, or a refusal
that outlasts the window, is a failure.

Not chosen: unbounded or generic filesystem retry; ACL changes, elevation, process killing or antivirus/SAC exclusions; test-side retries, stubbing the
rename, or accepting a failed aside in tests. The test-side options would weaken the contract rather than fix the defect.

## 2026-10-23 - Qwen3 hash lock moves scikit-learn to 1.9.0 (Smart App Control drift; same build as the main environment)

Owner-authorised at P01B (plan Revision 2 §6); recorded by Claude Code.

**`scripts/qwen3-requirements.txt` now locks `scikit-learn==1.9.0 --hash=sha256:4306775fad04cc4b472a1b15af1ae9cede1540fbfcc17fbce3767cd8dc7ae283`**
(was 1.9.1 `4b59abb3…`). Smart App Control (Enforce) refused 1.9.1's unsigned `sklearn/utils/_isfinite` on HOME-PC. transformers' generation module
imports scikit-learn, so the Qwen3 worker could not start. The official 1.9.0 cp312 wheel is the one already pinned in the main environment. The full locked
Qwen3 stack with only this line changed was qualified first in a disposable environment and then in the live `.venv-qwen3`. Results: hashed install, `pip check`
clean, 0 SAC-blocked natives, the real worker probe passes, and so does the real-library self-check. The other 88 pins and hashes are unchanged. Existing
installs see a new requirements fingerprint and report "out of date". `qwen3_setup.install()` then re-runs the hashed pip command in place (a one-package
change) and re-records the probe. The full-check `repair()` path rebuilds the whole environment instead (`rebuild=True`, about 3 GB to download). That is
existing behaviour, not changed here.

Not chosen: disabling SAC or adding exclusions, wheel substitution outside the hash lock, or a rebuild of the 5 GB environment for a one-package delta.

## 2026-10-23 - scikit-learn pinned to 1.9.0 in the main environment (Smart App Control drift, srsly precedent)

Owner-authorised at P01B (plan Revision 2 §6); recorded by Claude Code.

**`scikit-learn==1.9.0 ; python_version < "3.13"` is pinned in `scripts/requirements.txt`.** scikit-learn is a transitive dependency
(chatterbox-tts → librosa 0.11.0, which accepts >=1.1.0), and transformers' generation module imports it, so every local engine depends on it. The 2026-10-21
fresh install resolved 1.9.1. On 2026-10-23 Smart App Control (Enforce) refused its unsigned `sklearn/utils/_isfinite` extension (earlier
`__check_build`), so Kokoro and Chatterbox could not import. Re-probing later the same day did not clear it. 1.9.0 is the build the main environment
ran from 2026-08-16. Its official wheel (sha256 `4306775f…`) was qualified in disposable environments and then in the live `.venv`: 0 blocked natives,
`pip check` clean, and the real Kokoro proof passes. Existing installs pick the pin up through the launch-time requirements reconciliation.

Not chosen: disabling SAC or adding exclusions (end users run SAC, so the qualification would stop meaning anything), unqualified wheel substitution, or waiting
indefinitely. `.venv-qwen3`'s hash lock stays 1.9.1 until its own qualification and an owner decision. The srsly entry's recommendation stands: a
full transitive lock of the main environment would prevent this class of drift. Still not done.

## 2026-10-23 - v0.7.0 supersedes the v0.6.7 release target; new working branch; owner preservation is guarded by exact ignore rules

Owner decisions from the approved plan `files/plans/ACT-v0.7.0-Final-Release-QA-Remediation-Implementation-Plan.md` (Revision 2: D36, Q33, §3),
recorded by Claude Code at checkpoint P00B.

**The release target is v0.7.0 (D36).** The Revision 2 plan is the authority for the remaining release work. It supersedes the v0.6.7 remediation target
and the "Codex closure check, then version bump, merge, tag and release" sequence in the 2026-10-21 records. Historical v0.6.7 plans, evidence and
entries keep their original identifiers and are not rewritten. Code and config identity stays 0.6.6 until the separately authorised final-identity
checkpoint (P11); each plan checkpoint is separately assigned and stops for review.

**New working branch from the verified feature tip (Q33).** `feature/0.7.0-release-remediation` was created from `feature/0.6.7-speech-pipeline-and-layout`
at `d61822b` after confirming that tip equals the remote tip, never from `master`. The old branch is preserved; no history rewrite, no remote deletion.

**Owner preservation is protected by exact ignore rules, not by cleanup (§3).** The three directories renamed before the 2026-10-21 fresh-install test
(tag `20261021-184021-592ae0be`) are ignored by root-anchored, directory-only rules that match only those exact names; near-miss names, nested copies and
other paths stay visible. This was proved with `git check-ignore` on synthetic paths, without reading the private contents. They are not install, repair,
migration or cleanup targets and no interpreter inside them is run; restoration is plan checkpoint P12 only, with separate owner approval. Ignoring them
does not replace explicit, path-scoped staging. Rejected: a broad `*.act67-preserved-*` glob (it could hide unrelated future work) and ignoring their
parent folders.

**The plan lives under `files/plans/`, not `md-instructions/`.** The four-document contract (`Briefing.md`, `Handoff.md`, `Decisions.md`, `Changelog.md`)
is unchanged. The tracked plan contains no absolute local path or account identity; owner- and machine-specific details stay in ignored evidence under
`files/dev-work/`.

**Known local-only items stay as found.** `.ai/`, `scripts/project-status.py` and `files/run-temp/` remain untracked, unignored and unstaged by owner
decision; no new ignore rule was added for them. A clean checkpoint exit means clean tracked and staging state, not an artificially empty `git status`.

Signed: the owner (plan Revision 2 decisions and the P00B brief); recorded by Claude Code.

---

## 2026-10-21 - v0.6.7 closure corrections: three-state Kokoro health, a fail-closed Qwen3 guard, one Tk bound, a session-wide test redirect

Implementation decisions by Claude Code under the owner's narrow corrective brief for the second Codex closure audit (CLR-001 to CLR-004).

**"Not proven broken" is not "proven healthy" (CLR-001).** `kokoro_is_healthy` returns `(True | False | None, reason)` and `ensure_kokoro_installed`
returns `True | False | None`; `None` means the proof timed out or could not be started. The smallest representation that keeps every caller's tuple
shape: tests and call sites that already unpack `(ok, reason)` keep working, and only the three callers that must tell the states apart (launch,
setup, repair) branch on `is None`. `None` is never recorded (no success cache, no failure cache), never triggers a repair, rebuild or download,
and launches the app with an honest notice; the next launch proves again, so a completed proof recovers to healthy or finds the real fault. After a
repair whose proof cannot finish, launch reports "unverified" at once instead of waiting out the same limit a second time.

**Machine-wide protection fails closed (CLR-002, owner decision).** `MachineGuard` uses the `Global\` mutex only. The `Local\` fallback is removed:
a session-scoped mutex cannot exclude another Windows session on the same GPU, and a fallback in one process with a Global guard in another would
protect different kernel objects. Outcomes are now distinguishable: `failure == "busy"` (wait timed out; the established contention message),
`failure == "denied"` (access denied opening an existing mutex; a message that says Windows refused permission and does NOT claim another user is
running anything), and a raised `Qwen3Unavailable` carrying the Windows error number when creation or the wait itself fails. Callers (the lease and
the model-load probe) take the message from `guard.refusal_message`. Normal contention, crash-release by the kernel and the per-installation file
locks are unchanged. Rejected: an "accepted reduced-scope" mode (more states to explain, and it would have to be surfaced by every caller).

**One bound for every Tk proof (CLR-003).** `probe_venv` uses `TK_PROOF_TIMEOUT_S` like `_tcl_tk_ok`; the stage-0 script already used 30 s. A source-level
test pins that no literal timeout sits beside a Tk proof, and real hung interpreters (and a real stage-0 `Test-Candidate` with an accelerated bound)
prove the bound is enforced and the child is gone. The macOS `.command` `tk_ok` still uses `tkinter.Tcl()` with no timeout; it only picks an
interpreter and the Python bootstrap proves real Tk afterwards, so it was left alone as out of scope (recorded in the Handoff).

**Test isolation is established by an explicit import, not by luck (CLR-004).** `conftest._isolated_runtime_data` imports `shared.paths` and
`shared.settings` (constants-only modules, safe to import, unlike `shared.bootstrap`) and redirects `paths.LOGS_DIR` and `paths.SETTINGS_FILE` for the
whole session, before any test body can start the logger. Redirecting `SETTINGS_FILE` (not calling `settings.use_path`) matters: ten test modules end with
`use_path(None)`, which falls back to `paths.SETTINGS_FILE`. Production log retention was not touched. The proof runs in a disposable copy of the
checkout, never against the real runtime-data.

## 2026-10-21 - v0.6.7 Codex audit remediation: no-clobber packaging, proved Kokoro health, a cross-installation Qwen3 guard, real Tk proofs

Implementation decisions by Claude Code under the owner's remediation brief for `files/dev-work/final-codex-audit/ACT-v0.6.7-Final-Audit.md`.

**Release archives are never replaced (AUD-001).** `release.py` checks both destinations first and refuses if either exists; nothing in `dist/` is deleted
or overwritten except the run's own `.staging-*` folder. Archives are validated member by member (order, size, CRC32 against the source, launcher mode 0755)
and published with `os.link`, chosen because it fails on an existing destination on NTFS, APFS and ext4 alike (`os.replace` would silently overwrite on
POSIX). If a later link fails, earlier links of the same run are withdrawn only while `os.path.samefile` proves they are still this run's file. A drive
without hard links is refused rather than given a replacing fallback. There is deliberately no "replace" option: moving old archives aside stays a manual act.

**Kokoro health = presence + a recorded offline proof (AUD-002).** Presence (`find_spec`) still runs every launch (cheap). The proof imports kokoro, torch,
misaki, spaCy, srsly, soundfile and scipy and, when spaCy's English model is installed, builds the English G2P with `model=False` under
`HF_HUB_OFFLINE=1`, so it can never download the Kokoro weights or spaCy's model. It is recorded in `.venv/.kokoro-proof.json`, keyed to the requirements
hash and the interpreter: success trusted 7 days (same as the import proof), failure 1 day. `kokoro_synth` deletes the record when a real pipeline load
fails. Repairs run `pip install -r scripts/requirements.txt` (never the hand-kept `KOKORO_PKGS` list), and a repair whose proof still fails is not rerun
that day, because reinstalling the same pinned files cannot change an Application Control decision. The repair no longer warms the full model (which could
download ~300 MB unasked); setup's opt-in warmup is unchanged.

**Qwen3 resource scope (AUD-003).** `rt.MachineGuard` is a Windows named mutex, `Global\AudiobookCreationTool-Qwen3-ModelGuard-v1`: one heavy Qwen3 model
operation at a time across every copy of the app and every Windows user/session (one GPU, one RAM). If Windows refuses the `Global\` namespace for any
reason other than access denied, it falls back to `Local\` (this logon session) and says so in `scope`. Access denied means another user's copy holds it
open and is treated as busy. Acquisition never waits; the kernel releases an abandoned mutex, so a crash cannot strand it; it is thread-owned, so it is only
used as a `with` block. Taken by `inference_lease` (conversions, transcription drafting) and around the install/repair model-load probe; downloads do not
take it. The per-installation `setup.lock`/`inference.lock` file locks stay for the installation's own files. A mutex rather than a shared lock file avoids a
global file location; Qwen3 is Windows-only, so elsewhere the guard is an explicit no-op (`scope = "none"`). The test suite uses its own mutex name.

**GUI health means Tk initialises (AUD-006).** One proof everywhere: `tkinter.Tk()`, `withdraw()`, `destroy()` before any event loop (no window), 30 s bound,
in the venv probe, `_tcl_tk_ok` and stage 0 (which now runs candidates as a bounded process, not with `&`). A TclError about a missing display is a property
of where the app runs, not of the environment: reported as degraded `no-display`, never as a reason to rebuild.

**Clone approval persistence (AUD-007).** `write_store` maps any filesystem error to `SetupError` with one actionable message; the dialog also catches any
other exception. Failures return before the rows reload, so the user's text and ticks stay. `atomic_write_text` removes only its own partial temp file.

**Packaging and docs (AUD-011/AUD-012).** The README gallery link is absolute and must name the same ref as `voice_previews.RAW_BASE` (a test pins that); both
move to the stable branch together at the owner's merge decision. The release walk skips exactly three tracked developer entry points
(`DEVELOPER_ONLY_SCRIPTS`); no application module imports them (tested on the built archive).

**Recorded, not changed (AUD-010).** The main `.venv` pins direct requirements only; transitive packages can drift between installs (two qualified
environments already differ in spaCy 3.8.15 vs 3.8.16), and Chatterbox's weights are fetched without a pinned revision. A full transitive lock and a pinned
Chatterbox revision are a separate, owner-approved change; nothing was upgraded or locked here. `.venv-qwen3` remains fully hash-pinned.

**Gates kept open, not waived:** AUD-004 (clean standard-user Windows install), AUD-005 (redistribution authority for the six reference recordings), AUD-008
(an exact final release-candidate ZIP), AUD-009 (real network acquisition of the Qwen3 models and recognizer).

---

## 2026-10-20 - v0.6.7 final implementation: owner listening approval, in-app clone set-up, Windows stage 0, the reference names and the B2 split

**Owner listening approval (owner).** The owner listened to all 28 published voice previews and approved their audio quality. The six Qwen3 clones PASS at temperature 0.70 and sub-talker
temperature 0.80 (`CLONE_GENERATION_REVISION = 1`); no further experiments. The 28 WAVs and every voice identity are preserved as published. This approves AUDIO; it approves no reference
transcript: the preview drafts stay provisional (`approved: false`) and nothing in the repository becomes a production transcript.

**Production transcripts come from each user, in the app (implementation decision under the owner's brief).** A clone is used only with a transcript the person at that computer approved,
bound to the recording's SHA-256 (unchanged loader rule). TTS Audiobook → "Install / repair Qwen3 voices..." → "Set up cloned voices...": (1) install the pinned Whisper small.en recognizer
(revision `e8727524…`, 11 files, 970,930,930 bytes, each size- and SHA-256-checked; only after the size is shown and confirmed), (2) draft all six locally in `.venv-qwen3`
(`qwen3_worker.py` job kind `transcribe`, at most 30 s of audio, result written to a file, never stdout), saved `approved: false`, (3) the person plays each recording, corrects the text,
ticks "I listened" and approves. An approved entry is never overwritten by a draft; a draft for a changed recording reads as stale. No CLI, no JSON editing, no review page, no external
provider, no silent download. Modules: `tts/qwen3_clone_setup.py`, `tts/qwen3_clone_setup_ui.py` (named so no tracked `scripts/` file name contains "transcript", the Q5 guard).

**Windows stage 0 (`scripts/shared/bootstrap_host.ps1`).** The launcher no longer depends on winget to get Python. Stage 0 RUNS each candidate (py launcher 3.12/3.11, the per-user and
Program Files installs, `python` on PATH; the Store alias is skipped) and accepts only 3.11/3.12 with ssl, venv and Tk. With none, it asks, then downloads the pinned python.org 3.12.10 amd64
installer (26,964,224 bytes, SHA-256 `67B5635E…95FB`, Authenticode subject must be the Python Software Foundation) into `files/temp/bootstrap/`, reuses it when still valid, and installs
per-user with no PATH change, no file associations, no py launcher. winget (user scope) is only the fallback. Exit 0 ok / 2 declined / 3 failed. Not proven: running the installer on
HOME-PC (it already has 3.12.10, and Windows Sandbox is unavailable), so the clean-machine path stays unverified.

**Reference recordings named after their labels.** `files/Chatterbox-Voice-Uploads/Chatterbox - Female 1.wav` ... `Chatterbox - Male 4.wav` (`git mv`, bytes and hashes unchanged), derived
from `voice_registry` (`reference_recording_filename`); one copy serves both engines (`CLONE_REFERENCE_VOICE`). `qwen3_runtime.reference_name` ("Female-1") stays the stable transcript key.

**S5 production fixes.** (a) Runaway Qwen3 chunk: longer than 1.0 s + 0.6 s per word → re-render with seed + k·104729, at most twice, keep the shortest (found as Ryan laughing after
"Chapter One"; Aiden unchanged). (b) The worker uses CUDA only when `is_available()` AND `device_count() > 0` (an empty `CUDA_VISIBLE_DEVICES` made PyTorch report a GPU it could not open).
(c) The clone set-up rows scroll inside a box sized to the screen (it was 942 px tall). (d) A status message became a named constant so no string `.set()` literal names a voice
(`test_voice_labels` reads one as a persisted voice setting). None of these changes text, chunks or seeds: `PIPELINE_REVISION` stays 1 and the A0 golden is unchanged.

**B2 (Plan 01B §5.1 Level 3).** `scripts/mp3_tools/` is split into `mp3/`, `m4b/` (`converter/`, `maker/`, `metadata/` + the shared M4B modules) and `artwork/`; 30 modules moved with their
names, classes and behaviour unchanged. Relative imports became absolute. `source_probe.APPLICATION_PACKAGES = ("shared", "tts", "mp3", "m4b", "artwork")`. Three content pins were
re-pinned on purpose (each records its previous digest): `shared/numbering.py` and `m4b/m4b_numbering.py` (docstring dotted names only) and `test_m4b_numbering.py` (imports and path
constants only). `paths.MP3_TOOLS_DIR` (unused) became `MP3_DIR`/`M4B_DIR`/`ARTWORK_DIR`. No stale-folder warning was added for `scripts/mp3_tools/`: it only ever existed in development
checkouts, where a pull leaves at most an ignored `__pycache__`.

**`srsly==2.5.3` pinned (release blocker found by the extracted-ZIP test).** The main `.venv` pins only direct dependencies; a fresh install resolved the transitive `srsly` to 2.5.4,
and Smart App Control (enforcing on HOME-PC) refused its unsigned `srsly/msgpack/_epoch` extension, so every Kokoro pipeline failed. 2.5.3 is the build S5 qualified and it loads under
the same policy; the launch-time requirements reconciliation applies the pin to existing installs. A full transitive lock of the main `.venv` (as `.venv-qwen3` has) is recommended, not done.

**Version identity stays 0.6.6.** `version.py` says the identity is bumped at the approved release-candidate checkpoint; no such approval exists, so the qualification archive is the
committed tree packaged as 0.6.6 and renamed `-identity-<sha>` in a separate folder. The bump to 0.6.7 is an owner decision.

## 2026-10-20 - Qwen3 clone previews: provisional transcripts for listening samples, the calmer profile, and the reference-tail fix

**Decision (owner).** The six clone previews are published NOW for the owner to listen to, before any further approval. The owner authorized using Whisper's existing drafts as PROVISIONAL reference text for these
listening samples only, and ordered less dramatic delivery. Publishing a sample is not an approval of its audio quality.

- *Provisional transcripts.* `voice_previews.py generate --provisional-transcripts` reads the Whisper drafts (`qwen3-initial/transcripts/verified.json`), proves each is bound to the registered recording's SHA-256 (they also read back at
  word error rate 0.00 against a fresh transcription of the originals), and lets the production clone path see them for exactly that one synthesis, in the tool's own process. The production approval rule is untouched: the application
  still refuses a clone without an approved, reference-bound transcript, nothing is ever written to `transcripts.json`, all six drafts remain `approved: false`, and no PASS decision was invented. Each clone preview records
  `transcript.status = provisional` (a hash of the text, never the text) and the README labels the rows "(provisional transcript)". Re-render with approved transcripts once the owner approves them.
- *Calmer sampling (production, clones only).* A clone job carries temperature 0.70 and sub-talker temperature 0.80 (the Base defaults are 0.90 / 0.90), forwarded by the worker as validated floats; top_p, top_k,
  repetition_penalty, max_new_tokens and the deterministic chunk seeds are the Base model's own / unchanged; Aiden, Ryan and the other engines are untouched. Proved in the installed `qwen-tts 0.1.1` that both values reach
  the talker and the code predictor. `CLONE_GENERATION_REVISION = 1` identifies the profile and is logged and recorded per preview; `PIPELINE_REVISION` stays 1 because the immutable A0 golden pins it and text, chunks and seeds are unchanged.
- *Root-cause defect found by validating the audio, and its fix.* Three clones (Female 1, Female 2, Male 4) opened with a stray leftover sound and, for Male 4, lost the word "Welcome"; re-seeding (six takes each) did not help. The cause:
  those three reference recordings were cut at 15.0 s mid-sound, and a clone continues from its reference, whereas the three whose references end in silence opened cleanly. Appending 0.6 s of silence to the reference copy fixed all
  three in a scratch test. It is now production behavior: `snapshot_reference` appends `CLONE_REFERENCE_TAIL_SILENCE_S = 0.6` to the COPY the worker receives, after proving the copy is the approved recording (the file in the
  repository, its hash and its transcript are unchanged; silence adds no words). This also removes the same stray opening from every chunk of a cloned audiobook, so it is a real application change that the owner's listening review covers.
- *What the preview tool now validates.* A preview must begin from near-silence (first 10 ms below -50 dBFS), a clone take must read back (local whisper-small.en) with its first and last word and a word error rate of at most 0.10,
  and a failing clone take is re-rendered with the next seed take (at most six; the take is recorded). A bounded clean-up for a short leftover (under 0.6 s, followed by a 100 ms pause) exists for the preview tool only; with
  the fix above none of the six needed a re-take or a trim (`seed_take` 0, `leading_fragment_trimmed_ms` 0).
- *Result.* 28 of 28 previews exist. All 28 read back at word error rate 0.00; clone pitch tracks each reference; the 22 earlier files are byte-identical to what was published. Not established without listening: naturalness,
  whether the calmer delivery is calm enough, identity likeness, and any residual artifacts. Two clips are loud (Male 1 peak 0.91, Male 3 peak 0.95; not clipped).
- *Verification.* Focused suites (preview tool 101, Qwen3 synth/worker/runtime/packaging/harness/review, release packaging, layout and boundary guards, A0) and mutation checks of the new guards; no full `verify.py`.

-- Provisional-transcript use and publication ordered by the owner (2026-10-20); recorded and implemented by Claude Code

---

## 2026-10-20 - Qwen3 clone narration: calm-delivery preference, the transcript review package, and the temperature experiment (owner-gated)

**Preference (owner).** The six Qwen3 Base clones should narrate calmly and evenly: noticeably less variation in pitch, emotional intensity and pace than their Chatterbox counterparts; no sudden
high-to-low pitch swings, exaggerated inflection, dramatic sentence endings, needless loudness or cadence changes, or different delivery between adjacent chunks. Each clone keeps its reference voice and
natural accent, accurate and complete text, natural phrasing and pauses, the six original Chatterbox reference WAVs (unchanged), and Qwen3 Base ICL cloning from an owner-approved, hash-bound transcript.
Excluded by the owner: a new model, voice substitution, style instructions embedded in the text, a pitch-flattening filter, a dependency upgrade.

**Facts established from the pinned install (no model loaded, no audio).** `qwen-tts==0.1.1`. Production passes no sampling argument, so a clone uses the Base model's own `generation_config.json` (the library's
docstring says `generate_config.json`; the code reads `generation_config.json`): `do_sample` true, `temperature` 0.9, `top_p` 1.0, `top_k` 50, `repetition_penalty` 1.05, `max_new_tokens` 8192, and for the
sub-talker `subtalker_dosample` true, `subtalker_temperature` 0.9, `subtalker_top_p` 1.0, `subtalker_top_k` 50. `generate_voice_clone(**kwargs)` forwards sampling arguments through
`_merge_generate_kwargs`: an explicit `temperature=0.9` is the identical merge to passing nothing, and `temperature=0.8` changes that one value and nothing else (proved against the real library by
`qwen3_calm_venv_tools.py selfcheck`, and by a test that runs it where `.venv-qwen3` exists). Each chunk's seed (`derive_seed`) does not depend on temperature, so candidates are paired.

**Could `subtalker_temperature` help?** Plausibly, but secondarily. In the model code the main talker samples one codec token per frame (the first codebook: what is said, its timing and its overall contour) and the
sub-talker (`code_predictor`) then fills in the remaining codebooks for that frame (acoustic detail). So the main `temperature` is the more plausible lever for pitch, inflection and pace, and the sub-talker's for
fine texture. That is an inference from the code structure, not a measurement. It is NOT varied in the first experiment (the owner asked for it to stay 0.9); the harness cannot override it. It is a possible second
axis if 0.8/0.7 do not calm the delivery enough, and adding it would be an owner decision.

**What was built (development only; nothing in production changed).**
- `files/dev-tools/qwen3_transcript_review.py`: builds `files/dev-work/qwen3-eval/transcript-review/review.html`, an offline, self-contained page that plays the six ORIGINAL reference WAVs (embedded byte for byte,
  each checked against the SHA-256 the app registered), shows each Whisper draft beside an editable field with a "listened" tick and PASS / NEEDS CORRECTION, and downloads one decisions file. `apply FILE` is a
  dry run; `apply FILE --write` records PASS entries as `approved: true`, bound to the recording's SHA-256, in the local untracked `files/runtime-data/qwen3/transcripts.json` (the file the app's own loader reads).
  Nothing is approved by building the page, by a dry run, by NEEDS CORRECTION or by an undecided voice; the Whisper drafts, the recordings and every tracked file are never modified.
- `files/dev-tools/qwen3_calm_worker.py` + `qwen3_calm_experiment.py` + `qwen3_calm_venv_tools.py`: the comparison harness. Every clip goes through the PRODUCTION entry point `qwen3_file_to_mp3` (its availability and
  transcript-approval rules apply; no `availability`, `python` or other safety seam is overridden). The baseline (0.9) runs the production worker with no override; a candidate runs the same production worker
  through a wrapper that forwards one extra argument, `temperature` (range 0.1-1.5), to clone `synth` jobs only (a preset such as Aiden or Ryan is never altered). Candidates 0.8 and 0.7, optional 0.6; the text
  (a fixed 2,328-character passage with prose, dialogue, punctuation and paragraph transitions), the reference, the transcript, the chunking, the seeds and every other control are identical. Output (WAVs, manifest
  with seeds and hashes but never transcript text, pitch/loudness/pace measurements, a whisper read-back for completeness, a labelled `listen.html`) goes only under ignored `files/dev-work/`, never into `files/voice-previews/`.
- Tests: `test_qwen3_calm_harness.py` (68) and `test_qwen3_transcript_review.py` (25), offline; 25 of 25 mutants of the new guards killed on the final pass (the one early survivor was a guard whose error was
  masked by a later one; its test now requires the explicit reason).

**Owner gate (unchanged by this entry).** No clone audio has been generated, because no transcript is approved. After the owner approves the six transcripts: run the harness on one female and one male clone,
provide labelled baseline / 0.8 / 0.7 samples for listening, and let the owner choose. Until the owner approves a candidate: no new production temperature, no change to the Qwen3 generation contract or pipeline
revision, no replacement of any published preview. If a lower temperature is approved: ONE shared, tested clone narration profile, a tracked pipeline-revision change, Aiden and Ryan untouched, and the six
genuine public clone previews generated with that profile. The transcripts must be verified and approved either way. No full `verify.py` before S5.

-- Preference and gate set by the owner (2026-10-20); recorded and prepared by Claude Code

---

## 2026-10-20 - Owner publication decision: preview audio for all 28 voices may be published (supersedes the Q5/Q8 preview restriction)

**Decision.** The owner explicitly authorized publishing short generated preview audio for **all 28 registered ACT voices** in `files/voice-previews/`. The earlier rule that kept
the Edge, Chatterbox and Qwen3-clone previews unpublished (CP6 rulings Q5 and Q8, 2026-10-19, and the Q8 rights gate built from them) is superseded **for preview audio**. It was
a mistake as a blanket block, and it must not be used to stop these samples being generated or uploaded. The 2026-10-19 entries stay as written; they are history.

- *What this is, and is not.* It is an **owner publication decision**. No third-party legal opinion was obtained and no external license or service terms (Microsoft's Edge Read
  Aloud service, the Chatterbox reference recordings' owners, the Qwen3 clones) were independently verified by this project; the manifest and README say exactly that and claim
  nothing more. For Kokoro and the two Qwen3 presets the earlier license-review evidence (Apache-2.0 model cards, hashed) is unchanged.
- *Scope.* Short generated preview audio only. **Not covered:** the private reference transcripts, the reference recordings (Q5 still applies to both: neither is committed), any
  untracked or private asset, the rejected Qwen3 presets, or any voice outside the 28 registered ones. Previews stay out of the release archives, as before.
- *Four things kept apart, because they are different facts.*
  1. **Publication permission: APPROVED** for 28 of 28.
  2. **Audio generated and verified: 22 YES, 6 NO.** Nine Kokoro, Qwen3 Aiden and Ryan (already published, untouched), and now five Edge and six Chatterbox. The six Qwen3 clones are
     NOT generated.
  3. **Qwen3 clone transcript validation is independently required.** A clone is only made from an owner-approved transcript bound to the reference recording's SHA-256
     (`qwen3_runtime.load_transcript`); the only transcripts on HOME-PC are the Whisper drafts in `files/dev-work/qwen3-eval/runs/qwen3-initial/transcripts/verified.json`, all six
     `"approved": false`. Nothing was approved, invented, bypassed or copied from Chatterbox. The six are recorded **pending generation** (not blocked) with that exact reason.
  4. **Qwen3 production-clone qualification is unchanged:** it remains under its separate S5 gates; a published preview does not qualify a voice.
- *Model.* `previews.json` is schema 2: an `owner_decision` block (stated by the tool and checked equal), per-voice `rights.status` of `confirmed` (license evidence), `owner_authorized`
  (the 17 voices the decision names, in `OWNER_AUTHORIZED_VOICES`) or `unresolved` (now meaning only *withdrawn*), and preview status `generated` / `pending` (with a required
  `pending_reason`) / `blocked` (withdrawal only). A schema-1 record that was `unresolved` is migrated once by `sync`; from schema 2 on an `unresolved` voice is never re-authorized
  by a sync. A voice added to the registry later is not in the decision, so it starts blocked until someone decides. The set is still never called complete while any row is
  missing, and a preview marked generated for a non-authorized voice is refused, uncounted and unrendered.
- *How the new previews were made (no substitution).* The same standardized sentence and target (24 kHz mono PCM16 WAV, edges trimmed to 120 ms, 8-13 s, no clipping or silence,
  SHA-256 and duration recorded). **Edge:** the folder route's own `batch_convert.synthesize_chunk_mp3` request for the registered voice at that voice's own rate, the service's MP3
  decoded straight to WAV (no re-encode); no retry, fallback voice or other engine, and a refusal is reported in the `edge_failures` wording and leaves the voice pending.
  **Chatterbox:** the production `chatterbox_file_to_mp3` on the bundled approved reference for that voice, pauses zero, encoder swapped for a lossless WAV and restored afterwards
  even on failure. Each voice asks the app's own availability answer first; one that cannot run here stays pending and is never a failure.
- *Verification.* `test_voice_previews.py` (70 offline tests; an Edge fake bound to the real `Communicate` signature, the Chatterbox/Qwen3 seams, the migration, the withdrawal path,
  the transcript approval rule on the real loader); 13 of 14 mutants of the new guards killed (the survivor, a duplicate non-mono check that `audio_problems` also makes, is
  redundant). All 22 files: whisper-small.en read-back WER 0.00 for the whole sentence, pitch consistent with the named voice (Chatterbox against its own reference recording),
  distinct SHA-256 per file, none clipped. No full `verify.py` (reserved for S5); A0 `check` OK; no production GUI, synthesis setting, model pin or A0-A6 behavior changed.
- *To finish the last six (owner action).* Listen to each reference recording, correct its draft transcript so it matches exactly what is spoken, set `approved: true` (the entry
  already carries the recording's `wav_sha256`) in the untracked `files/runtime-data/qwen3/transcripts.json` (or `ACT_QWEN3_TRANSCRIPTS`); then
  `python files/dev-tools/voice_previews.py generate qwen3-female-1 qwen3-female-2 qwen3-male-1 qwen3-male-2 qwen3-male-3 qwen3-male-4` and commit the six WAVs, manifest and README.
  The transcript is never committed.

-- Decided by the owner (2026-10-20); recorded and implemented by Claude Code

---

## 2026-10-20 - Edge TTS reliability and recovery (final hardening checkpoint): classify, retry only what can recover, say what to do

**Decision.** Both Edge routes (direct `run_edgespeak`, folder `convert_single_pdf`) now decide whether another attempt can help from the exception's real type and
attributes, instead of retrying every exception. One new module, `scripts/tts/edge_failures.py`, is the only place that classifies and words failures.

| Kind | Real signals | Retried? | What the user is told |
|---|---|---|---|
| service refused | `aiohttp.ClientResponseError`/`WSServerHandshakeError` status 401/403; `edge_tts.SkewAdjustmentError` | no | Microsoft's service refused the connection; retrying/reinstalling/updating may not fix it; check connection and PC date/time; report if it persists; an offline voice can be chosen *by the user* |
| protocol | other HTTP statuses (400/404/426/...); `UnknownResponse`, `UnexpectedResponse` | no | the service answered in a way this ACT version does not understand (it has probably changed); retrying will not fix it; report it |
| network / temporary | status 408/425/429/5xx; `WebSocketError`; `aiohttp.ClientConnectionError`/`ClientPayloadError`/timeouts; `TimeoutError`, `ConnectionError`, `socket.gaierror` | yes, the existing bounds | could not reach the service after several tries; check connection/VPN/firewall; Retry Failed |
| local | `OSError` that is not a network error, `ValueError`, `TypeError` | no | not an Edge message at all: the original exception is raised unchanged |
| cancelled | `ConversionCancelled`, `asyncio.CancelledError`, `KeyboardInterrupt` | no | never wrapped, never reported as a service failure |
| unknown | `NoAudioReceived`, other `EdgeTTSException`, anything unrecognised | yes, the existing bounds | failed unexpectedly after several tries; Retry Failed; report with the log |

- *Retry bounds are the approved ones, only applied to failures that can recover.* Direct: 3 attempts, 3 s apart. Folder: `CHUNK_MAX_RETRIES = 5` (2/4/8/16 s) inside
  `PDF_MAX_RETRIES = 2` whole-file redos (5 s) -- both constants and `INTER_CHUNK_DELAY_SEC` unchanged and still pinned by existing tests. A refused handshake used to cost
  3 requests (direct) or 15 (folder, 5 x 3, ~100 s of waiting); it now costs 1 and no wait. The folder's whole-file redo is also skipped for permanent failures.
- *Cancellation:* the folder route checks the user's cancel before each back-off and before the whole-file pause, so a cancelled run no longer sits out up to 30 s of waits.
  The direct route is unchanged there (cancel is already checked between sentences; its longest wait is 3 s).
- *Diagnostics survive, secrets and book text do not.* The final error is `EdgeServiceError` (a `RuntimeError`), `str()` = `<one-line advice> | Technical detail: <type,
  HTTP status, scrubbed message, attempt count, edge-tts version>`, with the original exception chained. Every URL query string and bare `TrustedClientToken`/`Sec-MS-GEC`/
  `ConnectionId` is removed (also from the folder route's traceback text in `batch_errors.log`). The direct route's log line no longer prints the sentence it was synthesizing.
  A failed attempt's partial audio file is removed. Nothing is published on failure: the direct route moves its file only after assembly; the folder route merges only after
  every chunk succeeded (unchanged).
- *Panel:* `record_failure` appends the advice line to the item's `display_message` when the failure text carries one (`split_failure_text`); the technical detail stays in
  `technical_detail` and the log. Items stay `retryable=True`, so Retry Failed means what it always did.
- *Recovery is guidance, not action.* Setup_and_Run is named only when the installed `edge_tts.__version__` differs from the pin (`EXPECTED_EDGE_TTS`, kept equal to
  `requirements.txt` by a test); a remote 403 is never promised to be fixable by reinstalling. `edge-tts==7.3.1` and every other pin are unchanged; no auto-upgrade, no
  alternative provider, no venv repair, no new startup network call, no fallback voice or engine, no dialog.
- *Not done on purpose:* a run-level circuit breaker that would skip the remaining files after the first refusal. Each file now fails after one quick request, the failures
  are individually retryable, and skipping would change which items are reported as failed. Revisit only if a service-wide outage makes long queues noisy.
- *Verification:* `files/tests/test_edge_failures.py` (57 offline tests; the real `Communicate` boundary replaced by a scripted fake that is checked against the real
  signature; real aiohttp/edge_tts exception types), three panel tests in `test_tts_jobs.py`; run against the pre-change route code the refusal, token and cancel tests fail
  (15 requests, token and sentence in the log). Eight mutants of the new logic killed. One live request through the production path with the pinned dependency and
  `en-US-SteffanNeural` succeeded (live availability is a service fact, not a test prerequisite). The full `verify.py` gate is reserved for S5; A0 `check` OK.

-- Decided by the owner's deferral (2026-10-20); implemented by Claude Code

---

## 2026-10-20 - Plan 01B checkpoint A6: the Chatterbox colon compatibility code is RETAINED WITH EVIDENCE

**Question.** With speech preparation on (A5, G2 passed), can either Chatterbox colon mechanism be retired?
(A) the structural-colon `punc_norm` patch (`_structural_colon_punc_norm`, `_ensure_structural_colon_patch`, applied in `_instantiate_model`), which keeps
times, ratios, references, URL schemes and paths away from the pinned wheel's blanket `:` -> `,`; (B) the prose-colon pause (`_PROSE_COLON`,
`split_at_prose_colon`, `COLON_PAUSE_MS = 75`, joined in `_synthesize_chunk`). Evaluated independently.

**Evidence (text level, no audio; `files/dev-tools/chatterbox_colon_matrix.py`, output `files/dev-work/speech-ab/a6/text-matrix.{json,md}`).**
- The pinned `chatterbox-tts==0.1.7` `ChatterboxTurboTTS.generate()` calls the module-level `punc_norm` unconditionally before tokenizing, with no parameter
  to skip or configure it; the wheel's `punc_norm` replaces every `:`. Token level (pinned tokenizer, offline): `6:45` -> `:` id 25 becomes `,` id 11;
  `https://` -> `://` id 1378 becomes `,` + `//`; `C:\` -> `:\` id 7479 becomes `,` + `\`. Colon-free text: identical ids.
- With preparation `v1` (A5 table) **and** `off`, these colons still reach `generate()` by policy and only the patch keeps them: cue-less times (`It was 6:45
  when`, `His best lap was 1:30`, `3:15`, `01:02:03`), bare ratios (`2:1`, DIFFICULT_SHORT's `3:1`), references (`John 3:16`, `clause 4:2`), URL schemes
  (`https://`, `ftp://`, `mailto:`) and Windows paths (`C:\`). Cued times and ratios (`6:45 p.m.`, `at 1:30`, `odds were 3:1`) are expanded in `v1` and no
  longer need it. DIFFICULT_SHORT: 4 colons kept by the patch with `off`, 3 with `v1` (`6:45`, `3:1`, the URL; `7:15` is expanded).
- Prose colons never reach the tokenizer either way (patched and wheel output are identical); their pause comes only from the split and the 75 ms PCM gap.
- The immutable A0 OFF golden (`files/tests/golden/speech/chatterbox.json`) pins both mechanisms: `colon_pause_ms` 75, the prose-colon segments, the exact
  `generate()` inputs, the patched `punc_norm` output (4 colons in `qc_difficult_short`, 5 in `punctuation`) and the assembled sample counts.

**Gate A (mechanical feasibility) not met -- no credible candidate, so no GPU evaluation was run.**
- (A) Unmet: A6 criterion 1 and prerequisites 1 and 3. No defined non-patch fate exists for the unexpanded and protected colons: (a) spoken forms for URLs and
  paths are URL respelling, closed as a forbidden substitution; (b) the only patch-free ways to keep a colon from the wheel are a look-alike character (the
  tokenizer then never sees the approved `:` / `://` tokens -- a new pronunciation contract) or re-implementing `generate()` against the wheel's internals
  (a deeper coupling than one attribute); (c) an accepted residual risk is not approved and is not a substitute for correctness. Expanding the ambiguous
  forms would reopen the A2-A5 ambiguity and protected-span policies, and `off` would still need the patch. Removing the patch changes the A0 OFF golden.
- (B) Unmet: prerequisites 3 and 6. Without the split the wheel reads a prose colon as a comma -- the 0 ms option the owner did not choose (0 / 75 / 125 ms set,
  2026-08-16). A text-only pause was proven impossible for a colon (every spacing variant normalises to the same comma); substituting other punctuation
  (`;`, `.`) would be a new pacing contract with a model-chosen, unseeded length, would add or remove prose colons (Plan 01B 3.3 forbids it), and before
  chunking would change the clause-level chunk plan (the semicolon outranks the colon). Removing it changes the A0 OFF golden. Mechanism B is the app's own
  assembly code, not a patch of the wheel; it depends only on the wheel turning a colon into a comma.

**Decision.** Both mechanisms stay unchanged, as an evidenced engine exception (Plan 01B 4.6 convergence rule; A6 criterion 5). No production code, wheel
pin, golden or test assertion changed. New tracked evidence: `files/tests/test_chatterbox_colon_a6.py` (mutation-checked: removing the patch, removing the
split or zeroing the pause each fails it); the existing colon contract tests are unchanged. G3 does not arise (no candidate audio).
**Re-evaluation:** at the final S5 review, or at any explicitly authorised Chatterbox wheel change (the byte-parity test in
`test_chatterbox_colon_integration.py` flags a `punc_norm` change), or if the owner approves spoken forms for URLs and paths.
*Observation, not a finding:* the split makes each colon segment its own `generate()` call, so the wheel capitalises the segment's first letter (`never` ->
`Never`) and the word before the colon ends a call (`one rule,`); this is the approved behaviour and the G2 recording passed by ear.

-- Evaluated and recorded by Claude Code under the owner's A6 authorisation; no owner verdict required (no candidate)

---

## 2026-10-20 - Plan 01B gate G2 approved (4/4 PASS); A6 authorised, G3 not approved

**Owner verdicts (G2, approved).** The owner listened to all four ~3-minute production recordings in `files/dev-work/speech-ab/g2/`:

| Recording | Verdict | Notes |
|---|---|---|
| `1-Edge-Steffan.mp3` | PASS | none |
| `2-Kokoro-Heart.mp3` | PASS | none |
| `3-Chatterbox-Female-1.mp3` | PASS | none |
| `4-Qwen3-Aiden.mp3` | PASS | none |

**Decision.**
- G2 is passed. No pronunciation, voice, timing, pacing or normalization change is requested; the A5 configuration (G1 mode table, four native exceptions,
  `[tts] speech_prep = "v1"`, Qwen3 revision handling) stands as approved. G2 samples are not regenerated; G1 is not reopened.
- The advisory Whisper read-back of "one rule:" as "one roll" in the Chatterbox recording is **not** an owner-reported failure: the recording passed by ear.
- A6 (Chatterbox colon compatibility retirement *evaluation*) is authorised. It is not permission to remove the workaround; removal needs the A6 mechanical criteria
  and owner gate G3, which is **not** approved.

-- Decided by the owner (G2 verdicts); recorded by Claude Code

---

## 2026-10-20 - Plan 01B gate G1 verdicts and checkpoint A5: the production mode table

**Owner verdicts (G1, approved).** 60 comparisons in `files/dev-work/speech-ab/a4/listen-ordered/`: 11 A, 18 B, 31 Same, 0 Neither, decoded through the private
key (A/B are listening slots, never preparation sides). Tracked record: `files/tests/golden/speech/g1-verdicts.json`. Decoded: 25 preferences for the expanded
reading, 4 for the engine's own reading, 31 Same.

**Decision.**
- *Rule.* A cell expands unless the owner preferred the native reading. A Same verdict expands (Plan 01B 7.2, convergence decision D6): all 60 pairs passed every
  mechanical and integrity check, so no Same cell was held back as mechanically unsafe. HYG (mechanical-only, never a listening class) expands everywhere.
- *Exceptions (native), each an explicit owner preference, each re-tested at the next RULESET_VERSION change and at S5:*
  - edge CUR (comparison 047, verdict B = native): Microsoft's server-side reading of currency was preferred.
  - edge FRAC (comparison 050, verdict B = native): the service reads `1/2 cup` well natively; preferred.
  - edge SYM (comparison 056, verdict A = native): native `&` / `x` reading preferred.
  - kokoro CUR (comparison 017, verdict B = native): misaki's own currency handling (it knows the `$` symbol) was preferred.
  Edge direct and Edge folder share the `edge` row (same service, same glossary scope); both routes are tested separately against it.
- *Default.* `[tts] speech_prep` defaults to `v1`; `off` restores the pre-A5 text exactly (the A0 baselines still characterize that path, unchanged).
- *Qwen3 revision.* `PIPELINE_REVISION` stays 1: it describes the planner/seed/generation/assembly code, which A0 proves unchanged, and the immutable A0 golden records it.
  A run with speech preparation on reports `SPEECH_PREP_PIPELINE_REVISION = 2` (`qwen3_synth.pipeline_revision`, logged in Details), because its text -- and so its
  chunks, seeds and audio -- can differ. This reconciles "bump the revision when audio can change" with "never edit the A0 goldens"; flagged for the owner.
- *Chatterbox colon shim stays* (structural-colon `punc_norm` patch, 75 ms prose-colon pause) until A6 decides.
- *A4 listening copies* in `listen-ordered/` were trimmed of terminal silence (evaluation hygiene only; production timing untouched).
- *Edge hardening deferred (owner, verbatim):* "ACT v0.6.7 will retain pinned edge-tts 7.3.1. A dedicated Edge reliability and recovery enhancement is deferred to
  final release hardening. It will consider service-failure detection, explicit recovery/repair, safe verified dependency updates, and preservation of user work. No
  automatic unverified upgrades or silent voice substitutions."

-- Decided by the owner (G1 verdicts, deferral); implemented by Claude Code

---

## 2026-10-20 - edge-tts pinned to 7.3.1; the A4 ordered listening export

**Decision.**
- *edge-tts 7.2.8 -> 7.3.1 (owner-authorized).* The read-aloud endpoint answers 7.2.8's WebSocket handshake with HTTP 403 (clock verified in sync); upstream issue
  #490 was fixed in 7.3.0, and 7.3.1 also fixes server date parsing. 7.3.1 declares the same four dependencies and every installed version satisfies them; a
  `pip install --dry-run -r scripts/requirements.txt` would change only `edge-tts`, and the bootstrap's own reconcile then changed exactly that one package. No other pin,
  no voice parameter and no protocol detail changed; no token is embedded. Proven first in a throwaway venv, then through `runner.run_conversion_job` for all five
  registered Edge voices. `test_edge_tts_pin.py` pins the version, the installed package, the `Communicate` API ACT calls, and the fingerprint change that makes an existing
  install reconcile.
- *Ordered export slots follow the blind sheet.* In `listen-ordered/`, `NNN-Engine-CLASS-A.wav` is the pair's lower-numbered blind clip and `-B` the higher one -- the same
  rule as the original sheet's First/Second -- never the preparation side. The private mapping (`key/ordered-mapping.json`) records each file's source clip, SHA-256 and side.
  The export copies bytes and never synthesizes. The first `listen/REVIEW-SHEET.md` is kept as issued; `listen-ordered/REVIEW-SHEET.md` is the current sheet.

**Why.** A non-technical user's Edge voices had silently stopped working; the A4 review needs all four engines and a folder that sorts naturally in Explorer.

-- Decided by the owner's instruction; implemented by Claude Code

---

## 2026-10-20 - Plan 01B checkpoint A3: how speech preparation is wired, frozen and kept switched off

**Decision.**
- *Normalization runs on the decoded text, before each route's structure stage.* The normalizer protects `Title:`/`Author:`/`#` markers and never changes a line count, so
  the structure stage sees the same structure, and every offset indexes the decoded source as Plan 01B 4.4 requires. Edge direct keeps `get_book`; it reads the prepared text.
- *One mode-table row per engine* (edge, kokoro, chatterbox, qwen3): the two Edge routes share the `edge` row, as they share the glossary scope. `data/modes.json` ships with
  all 64 cells `native` (D6).
- *The setting is a configuration key, not a settings.json key.* `[tts] speech_prep = "off" | "v1"` is validated in `shared/config.py` (unknown values fall back to `off`
  with a diagnostic). `USER_STATE_SETTINGS` lists only keys a real `settings.set` writer produces, so it does not gain one.
- *Off means the old call.* The panel passes `speech_prep=` to an engine, and the Edge runner passes it to `get_book`, only when the snapshot is enabled; an `off` run makes
  byte-for-byte the calls it made before, so existing engine fakes and the A0 baselines are untouched.
- *By value, once.* `SpeechPrepSnapshot` (frozen dataclass of tuples, frozen glossary entries) is built on the main thread at run start, frozen into `tool_options`, and
  re-used by Retry Failed. Worker threads never read a file. Notes (a broken user file) are written to Details once per attempt.
- *Defects never fail a conversion.* An integrity failure in one file falls back to that file's unchanged text with a Details line; an unreadable bundled mode table turns
  speech preparation off for the run with a note.
- *Qwen3 keeps its `Chunk`.* The A0 golden serialises `Chunk` with `asdict`, so source spans are not new fields: `qwen3_synth.chunk_source_spans` derives them through a
  verified structure map and the normalization map, only when preparation is on. Seeds still hash the spoken chunk text, so unchanged documents keep identical plans and seeds;
  `PIPELINE_REVISION` is not bumped in A3 because no audio can change.

**Why.** The owner's acceptance condition for A3: off and native paths must reproduce the A0 characterization exactly; a run must not be able to see a glossary edited after it
started; and broken user data must never cost a non-technical user a conversion.

-- Decided under the owner's A2-A6 authorisation; implemented by Claude Code

---

## 2026-10-20 - Plan 01B checkpoint A2: normalizer core decisions

**Decision.**
- *Hygiene resolves last, on what the classes leave.* Plan 4.3 lists hygiene above the classes; its spans are single characters, and the only overlap is a no-break space
  inside a numeric token (`5 km` from PDF extraction), whose spoken form already uses an ordinary space. Resolving it first would have blocked that token.
- *A claim is a claim.* An ambiguous token, and an edit whose class is not `expand`, still claims its span, so no lower rule rewrites part of it (`5 km` with UNIT native is
  never half-expanded by CARD). A mixed-number match also offers its bare fraction, because a longer claim can otherwise hide a candidate that a second pass would find (I6).
- *Mode semantics.* `expand` applies the class's rule edits; `glossary_only` withholds them but lets an owner glossary entry change the token; `native` leaves the token to the
  engine, glossary included. A glossary entry on ordinary words applies whenever its engine scope matches.
- *Metadata lines are protected whole.* Edge direct uses the `Title:`/`Author:` values as metadata, so they are never edited; `#` markers are protected and heading text is
  normalized like body text.
- *Years.* The ambiguous band is 1000-2099 (the plan said 1100; `in 1066` needs the same cue logic). A cued year is classed YEAR even where both readings coincide (`since 2005`),
  so the YEAR mode governs every cued year. A year cue together with a count noun (`in 1500 cases`) is a conflict and is left unchanged.
- *Numbers that look like identifiers* (leading zero, more than 15 digits, a cue such as Room/Flight/No., or a street address) are left unchanged from 100 upward.
- *Clock markers are spoken `A M` / `P M`.* The plan's example wrote `p m`; a lower-case `a` risks being read as the article. Open for the A4 listening.
- *English detection is a line heuristic* (non-Latin script share, or more foreign than English function words); a line it rejects is protected, never edited (D14, D15).
- *Fail closed in the core.* A violated invariant raises `IntegrityError`; how a run reacts is decided where the core is wired (A3).
- *Versioning.* `RULESET_VERSION` = 1. A test pins a fingerprint of the version, every data table and the rule registry, so a data change cannot land without a bump; a code
  change to a rule still needs a deliberate bump and a Changelog line.
- *Package boundary.* The speech-package import guard now allow-lists the exact standard-library modules used and forbids randomness, clocks, network, processes and threads.

**Why.** Each choice keeps the plan's conservative policy (unchanged unless a positive cue exists) and keeps behaviour traceable and testable before anything is wired.

-- Decided under the owner's A2-A6 authorisation; implemented by Claude Code

---

## 2026-10-19 - Application source is an explicit registry, not discovery

**Decision.** `source_probe.APPLICATION_PACKAGES = ("shared", "tts", "mp3_tools")` is the only definition of production packages for guards; folders are never discovered from disk. A new production top-level folder requires a deliberate registry edit, enforced by a tracked-tree canary. **Why.** Discovery by `__init__.py` pulled untracked developer packages into FFmpeg, architecture and syntax guards. This supersedes the discovery clause in the entry below.

-- Decided by the owner's instruction; implemented by Claude Code

---

## 2026-10-20 - Plan 01B checkpoint A1: one structure loader, existing engine differences kept as options; intermediate Codex reviews deferred

**Decision.**
- *One loader, explicit options.* `tts/speech/document.py` owns decoding and the `Title:`/`Author:`/`#` rules. Engine differences are options, not forks: Qwen3 makes a heading a paragraph of
  its own (and drops an empty heading), Kokoro/Chatterbox keep heading text in line (an empty heading leaves an empty line), Edge folder takes the text untouched. Unifying any of these
  would change audio and remains the owner's decision ([D10], [D11]); A1 changes none.
- *The speech package is a pure-Python leaf.* Standard library only; it imports no engine and no UI module (pinned by a test). It is listed in the production-source allow-list on purpose.
- *Review cadence.* The owner explicitly deferred the independent Codex review of B1's final correction and of every intermediate checkpoint (A1 onward) to ONE consolidated pre-merge verification before v0.6.7 closes. Codex has NOT independently passed the final B1 correction; that evidence stays unresolved until the consolidated qualification.

-- Decided by the owner's instruction; implemented by Claude Code

---

## 2026-10-19 - Plan 01B corrective checkpoint: where a startup notice is shown, and what "application source" means to a guard

**Decision (Codex findings on B1).**
- *A notice travels with the launch, not with the check.* The only reliable GUI-visible place on a Windows launch is the launcher window, so `bootstrap.launch_gui`
  sets `ACT_STARTUP_NOTICE` in the child's environment and the launcher shows it once in its status bar and removes it. `main()` does not evaluate it, which keeps
  `--venv-check` and `--launch-only` from losing or duplicating it. It is a one-line status, never a modal; detection and presentation failures are swallowed.
- *Detection covers `.py` and `.json`.* A leftover application folder can hold data files only; `__pycache__` is ignored; counts are named per type.
- *Guards over production modules call `source_probe.application_python_files`.* That is `launcher.py` plus every `.py` under the application packages (any top-level
  folder with an `__init__.py` is a package), not `scripts/**/*.py`. Whole-tree scans that must be broad (layout, packaging, "this file exists nowhere") stay raw and are
  listed in `test_application_source_boundary.py`; adding a new raw walk fails that test until it is justified.

**Why.** After the lift to `scripts/`, a glob over `scripts/` also reads `verify.py` and untracked local helpers, so a guard's verdict depended on the machine. The old
notice also could not be seen on the launch path the owner actually uses.

-- Decided by the owner's instruction; implemented by Claude Code

---

## 2026-10-19 - Plan 01B working decisions; `scripts/` is the import root (checkpoints C0, A0, B1)

**Decision (owner working decisions D1-D15, recorded in `files/plans/ACT-v0.6.7-Plan-01B-Text-Pipeline-and-Script-Layout.md` section 0).**
- *Layout.* `scripts/Universal/{launcher.py,shared,tts,mp3_tools}` moved up to `scripts/`, which is now the import root; the `MacOS/` and
  `Windows/` placeholders were removed. The package names did not change, so no import statement changed. The deep MP3/M4B package split is
  deferred until after S5 (592 test references); navigation is by short README maps instead. A leftover `scripts/Universal` produces a
  warning only: the app never deletes it, and no ignored or untracked file was deleted to make the folder disappear.
- *Sequence.* C0, then A0 (characterization baselines of the five text routes, captured from the original code **before** anything moved),
  then B1; A1-A5 and S5 follow only after the owner's manual Windows launch and Codex's independent review of B1.
- *Baselines live under `files/tests/golden/speech/`.* `files/test-files/` is gitignored local-fixture space, so a tracked golden cannot live
  there. They are text, chunk and seed baselines (no audio, no network) and any later pure refactor must leave them byte-identical.
- *Test counts.* The pre-existing suite must show no regression and the new tests must pass; the two counts are recorded separately and the
  total is allowed to rise.
- *Chatterbox colon behaviour is temporary compatibility.* The structural-colon `punc_norm` patch and the 75 ms prose-colon pause stay
  untouched through B1 and A1-A5; checkpoint A6 defines the criteria (including unexpanded and protected colons and URLs) for retiring them.
- *A run freezes its speech-preparation settings by value* (an immutable run-scoped copy; a hash alone does not freeze anything), so Retry
  Failed cannot see an edited glossary. Shared normalization is the end state for every engine; per-engine modes are rollout scaffolding,
  and each exception needs evidence, a Decisions entry, a review checkpoint and independent review.
- *One pinned test was re-pinned on purpose.* `test_plan6_boundaries.PHASE6_PROMOTION_HASHES` pins the content of `test_m4b_numbering.py`; its
  single changed line is the path constant, so the digest was updated once with the old value recorded beside it.

**Why.** The relocation removes an extra directory level and three confusing folder names without touching behaviour; characterising the text
routes first lets the move and the later speech-pipeline work prove they changed no text path.

-- Decided by the owner's working decisions; implemented by Claude Code

---

## 2026-10-19 - CP6 build decisions: how the Qwen3 voices are installed, contained, locked and previewed

**Decision (engineering, inside the owner's Q1-Q8 rulings; independent Codex review after every slice).**
- *Install and repair are in-app only.* One dialog ("Install / repair Qwen3 voices...", shown beside a Qwen3 voice) serves first-time
  and existing users; `bootstrap.py` is unchanged and nothing downloads on launch. The sizes are on the buttons and again in a
  confirmation before anything is acquired. CustomVoice and Base install independently (or together); files already present and
  intact are reused, and the nine files the two models share are downloaded once.
- *Downloads are verified, bounded and contained.* The tracked manifest lists, per model, the 11 files the loader needs with size and
  SHA-256 at an immutable commit. File names are validated (no traversal, absolute paths, device names or aliases) and nothing beneath a
  model folder may be a link. A response is checked against the manifest (status, `Content-Range`, `Content-Length`, no content
  encoding), never written past the manifest size, and accepted only after its SHA-256 matches; an interrupted file resumes from its
  `.part`. The models root itself may be a link so the models can live on another drive. A leftover `.part` or temporary file that is a
  link, or that shares its bytes with another file, is removed and never written through, and a Cancel during a retry wait is honoured
  within half a second.
- *The environment is isolated and pinned to artifacts.* pip runs `--isolated --require-virtualenv --require-hashes --no-deps` against a
  requirements file whose 89 lines each pin one exact wheel by SHA-256 (taken from the evaluation's install report), with ambient `PIP_*`
  settings removed and TEMP/caches inside the repository tree. `.venv-qwen3` must be a real folder inside the repository: a link or
  junction is refused and never deleted through. CPython 3.12 only (the tested wheels are cp312).
- *Nothing can outlive a Cancel.* The worker and pip start suspended inside a Windows Job Object that kills every member (including the
  venv launcher's child) and, if that containment cannot be established, they are not run. After a kill there is a final deadline, so
  the conversion thread can never wait forever. A worker's `done` is believed only if it also exits with status 0.
- *Setup and conversion exclude each other machine-wide* with operating-system file locks (`setup.lock`, `inference.lock`): an install
  or repair needs both, a conversion holds `inference.lock`. A crash cannot leave a stale lock. One Qwen3 conversion per machine at a
  time, which also suits a GPU that holds a multi-gigabyte model.
- *Repair checks first.* "Check and repair" starts the engine (a repaired-away DLL leaves every record valid), hashes every installed file,
  shows what it found and what fixing it would download, and acts only on a yes, re-hashing nothing it has just proved good. The check
  itself holds both install locks (it starts the engine and reads every model file, so it may not overlap an install or a conversion), and
  a model whose files are all intact but whose verified record is missing, unreadable or for another version (what a cancel between the
  record's removal and its rewrite leaves) is found and marked again with nothing to download.
- *Previews.* `files/voice-previews/previews.json` is the per-voice rights/status record. Eleven previews exist (nine Kokoro, Qwen3 Aiden
  and Ryan) because their licenses are documented and no third-party voice is involved; seventeen (Edge, Chatterbox, the six Qwen3
  clones) are blocked pending the owner's rights decisions. The set is never reported complete while any row is blocked. A preview
  tool refuses to generate for a voice whose rights are not `confirmed`; availability, the counts and the README are derived from rights
  and preview status together (a manifest that contradicts the rule is refused, never rendered); a new take is validated and its hash
  computed before it replaces the published file, and a published preview, its record and the README change together or are all rolled
  back. The recorded basis states only what the pinned model cards say (Apache-2.0 for the weights) and that the training-data provenance
  is the model author's claim. *(The `confirmed`-only generation rule described here is superseded by the 2026-10-20 owner decision; Kokoro/Qwen3-preset evidence is unchanged.)*
- *Trust boundary for link guards.* Anything that can write into the repository folder can already replace the scripts, so the
  link/junction/hard-link guards defend against accidental or content-driven redirection of the app's own state, locks, job text, caches,
  scratch files and downloaded model files, not against an attacker who can edit code. `files/runtime-data` and the models folder may
  themselves be links (moving data to another drive is legitimate); the Qwen3 runtime folder, everything the app creates beneath it,
  `.venv-qwen3` and anything inside a model folder may not. Four Codex follow-up rounds each found the same class one folder deeper; it
  is now closed by class (`ensure_runtime_dir`, `remove_entry`, exclusive temp-file + `os.replace`), not by path.
- *The install dialog imports none of the Plan 3 job foundation.* `test_plan3_boundaries` pins the adopters at exactly twenty modules, so
  `tts/qwen3_install_ui.py` receives its confirmation and style functions from the adopting TTS panel instead of importing `shared.job_ui`.
- *Left deliberately unchanged:* the data-cleanup tool keeps its four assets (only the wording of "Downloaded voice models" now says the
  Qwen3 models must be installed again); the Qwen3 environment is not a fifth asset, so freeing its ~5 GB is a manual folder delete
  (stated in the dialog). Adding it would be an owner decision.

**Why.** The owner asked for verified cancellation, failure recovery and output preservation, honest hardware disclosure, and no
automatic downloads, and Codex's reviews of S1-S3 found real gaps in each area (path traversal, ambient pip configuration, stale locks,
repair without confirmation, an uncontained fallback, unbounded downloads); each is fixed and has a regression test that was
mutation-checked.

-- Decided by maintainer's rulings, implemented by Claude Code

---

## 2026-10-19 - CP6: Qwen3-TTS production architecture approved (owner rulings Q1-Q8)

**Decision (owner, explicit).**
- **Q1** A second isolated `.venv-qwen3` and one Qwen worker subprocess per source file. The root `.venv`, production dependencies and Chatterbox are unchanged.
- **Q2** CustomVoice (Aiden, Ryan) and Base (the six clones) install independently, with an "Install Both" choice, in one shared environment. Download/install sizes are shown first, valid cached assets are reused, and nothing downloads on ordinary launch.
- **Q3** CPU fallback on Windows without an NVIDIA GPU, with hardware and speed stated plainly. The measured 2.15x real time applies only to the tested Ryzen 7 9800X3D. No silent downgrade, quantization or alternate model.
- **Q4** Windows first. On macOS the existing engines keep working and the Qwen3 voices read "not yet available"; no macOS Qwen3 claim without a Mac test.
- **Q5** NOT approved for public redistribution: the six verified transcripts, new cloned-voice previews and (pending a rights audit) the original reference recordings are not committed. The transcript interface is built with synthetic fixtures and accepts development-only local files; real clone synthesis still needs the owner's `verified.json` approval; there is no transcript-free cloning; the clones stay blocked for public-release qualification. **[Superseded for preview audio by the owner's publication decision of 2026-10-20 (the entry at the top of this log). The history is kept as written.]**
- **Q6** Qwen follows ACT's existing local-engine narration policy (the voice preset's paragraph pause between chunks, its end pause), not the evaluation's fixed pauses; source text and chunk/paragraph boundaries are preserved; one final MP3 encode.
- **Q7** About 1.4-1.9x real time is acceptable for the first integration; speed is disclosed as machine-dependent and no fixed performance is promised.
- **Q8** The permanent 10-second previews stay in scope but are generated or published only per voice with confirmed output rights and source permissions. Edge and cloned-voice previews are not published while rights are unresolved, a per-voice rights/status manifest is kept, and the 28-preview deliverable is not declared complete while any preview is blocked. **[Superseded for preview audio by the owner's publication decision of 2026-10-20 (the entry at the top of this log). The history is kept as written.]**

**Build choices made under these rulings.**
- *In-app install/repair only; `bootstrap.py` is not changed.* One "Install / repair Qwen3 voices" dialog serves first-time and existing users. This drops the draft's bootstrap slice (D8), so no new setup behaviour needs separate approval and the every-launch fast path never touches Qwen3.
- *Transcripts are read from a local, untracked file* (`files/runtime-data/qwen3/transcripts.json`, or the path in `ACT_QWEN3_TRANSCRIPTS`) in the same shape as the evaluation's `verified.json`, and are accepted only when `approved` is the literal `true` and the entry is bound to the reference recording's SHA-256. A tracked transcript file must not exist (a test enforces it).
- *One tested wheel set* (the cu128 build the evaluation and the CPU measurement used) is installed on every Windows machine. A smaller CPU-only wheel is a later optimisation because the CPU speed was measured with the cu128 build.
- *No automatic device fallback after a failure.* The worker uses the GPU when torch reports one and the CPU otherwise; a GPU that is present but fails (for example out of memory) fails that file with a clear message instead of silently re-running on the CPU.
- *Cancellation is bounded:* a flag file asked for between chunks, then the whole process tree is killed after a short grace period (the Windows venv `python.exe` is a launcher that starts the real interpreter as a child, so killing only the launcher would leave inference running).

-- Decided by maintainer, recorded by Claude Code

---

## 2026-10-19 - Final ACT voice roster: Decision B (28 voices)

**Decision (owner, explicit).** Retain Chatterbox and add selected Qwen3 voices. Final target inventory: Edge 5 (unchanged), Kokoro 9
(the five existing plus `am_fenrir`, `am_puck`, `am_onyx`, `bm_daniel`), Chatterbox 6 (unchanged: no removal, rename, archival or
replacement), Qwen3-TTS 8 (CustomVoice Aiden and Ryan; the six Base clones Female 1, Female 2, Male 1, Male 2, Male 3, Male 4) = **28**.
Excluded from production: Dylan, Eric, Ono_Anna, Serena, Sohee, Uncle_Fu, Vivian (their evaluation evidence stays).

**Labels and identity.** `Qwen3 - Aiden`, `Qwen3 - Ryan`, `Qwen3 - Female 1` ... `Qwen3 - Male 4`; a separate Qwen3 GUI group; distinct internal ids and
backend dispatch (never keyed on display labels); a Qwen clone is independent of its Chatterbox counterpart; the default voice, existing identities, saved
settings and ordering are preserved.

**Why / consequences.** The sustained Qwen evaluation target changes from four recordings (Aiden, Dylan, a female preset, a clone) to eight
(Aiden, Ryan and the six clones) on the existing frozen long corpus; the earlier selection matrix is superseded in the plan. This approves the
roster only: transcript approval, audio validation, regression gates and the bounded Qwen3 production addendum (new runtime, bootstrap and
platform decisions need the owner's approval) all still apply, and no Chatterbox retirement is authorized. Permanent 10-second previews cover the
final 28 voices only, subject to a per-voice redistribution check. *(Preview audio: see the 2026-10-20 owner publication decision.)*

-- Decided by maintainer, recorded by Claude Code

---

## 2026-10-18 - Plan 01 evaluation: isolated Qwen3-TTS runtime and dev-only tooling

**Decision.** The Qwen3-TTS / Kokoro / Chatterbox voice evaluation runs from `files/dev-tools/` (never shipped) and an
ignored isolated venv at `files/dev-work/qwen3-eval/.venv/`. Production `scripts/requirements.txt`, the root `.venv`,
the voice registry, the GUI and `scripts/Universal/shared/release.py` are untouched; the only tracked production edit is
the opt-in `--qwen-eval` flag group in `generate_voice_samples.py`. The evaluation stack is pinned in
`files/dev-tools/qwen_eval_constraints.txt` (89 exact pins: `qwen-tts==0.1.1`, `transformers==4.57.3`,
`accelerate==1.12.0`, `torch`/`torchaudio` `2.10.0+cu128`), models are pinned to immutable Hugging Face revisions in
`files/dev-tools/qwen_eval_assets.py`, and synthesis loads complete local snapshot directories with Hugging Face offline
mode on.

**Why.** Qwen needs a Transformers pin that conflicts with the production one, and the root torch is a CPU build that
cannot use the RTX 5070. An isolated interpreter keeps the working product intact while giving Qwen a real GPU
(`torch 2.10.0+cu128` was proven on sm_120 with bf16 matmul and SDPA before any model was downloaded). Gradio is installed
only because `qwen-tts` declares it; no server is run.

**Choices a future agent might undo, and why they stand.**

- *Join profile.* 50 ms of silence after **every** chunk plus 3,000 ms at the end, exactly as `chatterbox_file_to_mp3`
  and `kokoro_file_to_mp3` do, so Qwen files are comparable with the baselines. The plan's wording ("between chunks")
  differs from the engines by one trailing 50 ms; the engines were followed and the manifest records every inserted sample.
- *Audible duration* excludes inserted silence (engine-configured pauses are read from the engine's own signature).
  The 45-90 s / 8-12 min targets apply to this figure.
- *Evaluation passages* live in `qwen_eval_corpus.py`, not in `quality_corpus.py`, so the production corpus identity
  (`407fa95d7c524c64`) is unchanged and a test pins it. They were revised once, globally, after pilot timing (short
  172 -> 154 words, long 1,428 -> 1,528 words) and are frozen byte-exact per run; a changed passage requires a new run.
- *Chunk ceiling 600 characters* for Qwen only (pilot: peak VRAM 4.7 GB, the longest chunk used <= 6% of the generation cap); Chatterbox keeps
  its 300-character ceiling and Kokoro its own chunker.
- *Transcript gate.* A reference transcript conditions a clone only when `verified.json` holds `"approved": true` for it
  (a literal boolean); Whisper drafts never count, `x_vector_only_mode` is never used, and the transcript hash is part of
  the resume identity, so editing an approved transcript invalidates the clone.
- *Seeds* are `sha256(base|row|chunk|attempt)` per chunk; Chatterbox and Kokoro stay unseeded because that is production.
- *Resume* needs BOTH the identity (text, plan, profile, model revision, package pins, reference/transcript hashes and a
  deliberate `PIPELINE_REVISION`, not whole source files, so reporting/ASR edits never invalidate finished work) AND a
  match between what the row recorded about how it was made (installed package versions, model revision, Kokoro voice-asset
  hash, device build, reference and transcript hashes) and the present state. There is deliberately no "rebase"
  operation: it could legitimise audio made under a different profile.
- *Nothing complete is touched by accident.* A complete recording whose evidence no longer matches is reported STALE and
  kept; `--eval-rerun-stale` regenerates it, and `--eval-dry-run` shows every row's reuse/block/run decision without
  starting a worker. A temporarily missing prerequisite never demotes a complete result. Retired attempts have their
  files moved to `attempts/<row>/attempt-NN/`, and `Manifest.restore_attempt` can bring them back; every worker call keeps
  its own timestamped job file and log. Archive folders are numbered from the folders that exist, never from the list
  length. Retiring or restoring an attempt is ONE transaction (the file moves and the manifest save succeed or fail
  together; a restore is fully preflighted first; a rollback that cannot complete says which files it could not return). A row that is retired while blocked or failed keeps its
  diagnostics archived, and a recording that was received but failed to encode stays tracked. (Learned the hard way on 2026-10-18: the first version of the runtime check
  compared `torch` package metadata `2.6.0` with the runtime `2.6.0+cpu`, so one stage run retired and began regenerating
  12 good recordings. They were restored byte-identically and the spurious takes stay archived; the stale-guard and
  dry-run exist so that cannot recur silently.)
- *Transcript approval is bound to the reference recording's SHA-256* (`wav_sha256` in `verified.json`); an approval made
  for a different recording is not used.
- *Run ids* are one plain filename component and are checked to resolve inside `files/dev-work/qwen3-eval/runs/`.
- *ASR read-back* (`--qwen-eval asr-check`) is advisory: it can flag gross omissions, never approve or overrule listening.
- *Codex independent review* ran three times on 2026-10-18 (after one usage-limit delay): 10 major + 1 minor findings
  against `2ad8272`, 8 major + 2 minor against `a80825e`, and 5 major + 3 minor against `842a524`. Every finding was
  verified against the code before fixing, all were real, and all were fixed with regression tests. The later rounds
  are failure-injection scenarios (a save that fails after files moved, a restore whose archived file vanished), which is
  why retire/restore became a transaction. A further confirmation pass is the closeout review's job; a Claude
  self-review is never labelled independent.

Nothing here selects a voice or authorises integration: the owner's listening decisions (CP4/CP6) are separate gates.

-- Decided by maintainer (Plan 01 and its 2026-10-18 CP1 rulings), implemented by Claude Code

---

## 2026-09-30 - Post-release v0.6.6 bundled-reference ruling

This is the explicitly maintainer-authorized later master cleanup, starting from live
`d2be236832eb5d5e5ce0cde5ed82b08edfa740de`. The six curated MP3s currently present are the
approved sources, superseding older reference hashes for this task. They remain byte-identical,
read-only, ignored and untracked. Exactly six same-stem WAVs (Female-1, Female-2, Male-1,
Male-2, Male-3, Male-4) are now canonical production references. Each is exactly the leading
15 seconds, PCM s16le, mono, 24 kHz. Only trim/channel/rate/sample-format conversion was used;
no normalization, denoising, pitch/speed changes or silence padding. No LFS/dependency was added.

Voice IDs/labels, leading-window conditioning, read-only handling and source-hash derivative/
conditional identity remain intact. Runtime derivatives/caches stay in ignored runtime-data.
`release.py` uses a closed six-path WAV allowlist, requires tracked/present assets, refuses
uncommitted packaged-asset changes, and never walks `files/`. Tests prove exact names/hashes,
PCM metadata, tracked/package scope, byte identity and exclusion of MP3s/extras/runtime state.
README states that six references are bundled and no manual recording placement is needed.

Required full-gate remediation also reconciles the screenshot guard with the already-changed
kickoff master (exact 14-image set and committed bytes) and makes the first-run test fixture
start without a venv instead of creating/deleting one. No screenshot, bootstrap or launcher
changes were made. Single full run: 7,914 passed / 58 skips / 4 initial failures; all four are
closed by the final 380-test focused pass. The full verifier was not repeated or reported PASS.

**Publication distinction:** historical tag `v0.6.6` remains at
`7222083a732bbb0f1ef91e104725fc9a5cd2d141`. Original publication/archive facts below remain
history. Application/config identity stays **0.6.6**. The authorized local v0.6.6 ZIP rebuild
uses the later committed/pushed cleanup master containing this record, not the historical tag.
GitHub Release metadata/assets are not changed; the maintainer will manually replace the two
ZIPs after reviewing the local proof. No tag movement, force-push or history rewrite.

After focused checks and one full verifier, commit/push this cleanup on master, create/push
`feature/0.6.7-bundled-chatterbox-references` at exactly that SHA with no unique commit, leave
that branch checked out, rebuild/prove both local `dist/` v0.6.6 ZIPs through real `release.py`,
then STOP. This reserves a future branch; it does not start v0.6.7 feature work or publication.
The approved v0.6.7 manual backlog and waivers remain deferred, never newly passed.

Recorded under explicit maintainer ruling (Elijah Matthew).

---

## 2026-09-30 — Published v0.6.6 documentation closeout

**v0.6.6 is the current published release (2026-09-30).**
PR [#13](https://github.com/elmatthe/audiobook-creation-tool/pull/13) is merged into `master` as
`7222083a732bbb0f1ef91e104725fc9a5cd2d141`, the verified master SHA at publication.
Tag `v0.6.6` points exactly to that commit. The
[GitHub Release](https://github.com/elmatthe/audiobook-creation-tool/releases/tag/v0.6.6) is published,
neither draft nor prerelease.

| Published archive | Bytes | Approved SHA-256 |
|---|---:|---|
| [AudiobookTool-Windows-v0.6.6.zip](https://github.com/elmatthe/audiobook-creation-tool/releases/download/v0.6.6/AudiobookTool-Windows-v0.6.6.zip) | 786842 | `e8e1e7cafb97c2915e5a25af65759356799b46838732eb4e2b887dc3a1f96c75` |
| [AudiobookTool-MacOS-v0.6.6.zip](https://github.com/elmatthe/audiobook-creation-tool/releases/download/v0.6.6/AudiobookTool-MacOS-v0.6.6.zip) | 788642 | `fe2462917936e45d4c224736784c4d8f52bc51fefc4b7929651df641e7521de6` |

GitHub's live asset digests match these approved hashes. The published artifacts retain
the committed-source proof at `files/release-history/v0.6.6-integration-package-proof.json`
(package source `1e100e98b5c4f4a11020bdce0e98a631df8b0ee7`). This documentation closeout does not
rebuild packages; their embedded pre-publication README remains part of the approved artifacts.

**Decision:** close out README and the four canonical documents against verified live release
facts under the maintainer's explicit documentation-only authorization. README remains a
compact user guide, states the current published release and links each archive directly;
the general Releases page remains a secondary link. Changelog promotes the release material
to `## [0.6.6] - 2026-09-30` with a fresh `[Unreleased]` above it.

This record supersedes all earlier current-state claims that v0.6.6 is unpublished or awaits
PR merge, tag or publication, and earlier instructions to stop at those now-completed gates.
Dated pre-release decisions and execution evidence remain history. This closeout changes no
application behavior, version identity, tag, GitHub Release or release asset.

The approved **v0.6.7 manual/follow-up backlog remains deferred, never passed**:

- Native macOS all-six-tool Light/Dark, minimum/maximized geometry, Aqua rendering,
  keyboard/dialog/menu behavior and native automated suites.
- Hands-on clean Windows/macOS double-click setup, Python/FFmpeg acquisition, cold network
  install, Gatekeeper quarantine/App Translocation, optional models, repair and relaunch.
- Physical Windows 125%/150% scaling and the hands-on all-tool visual matrix.
- Long real-workload Pause/Resume/Cancel/Retry Failed drills, listening judgments
  (including Kokoro's accepted early breakpoint) and real phone-photo Cover checks.
- Broader TXT encoding support and sharper per-monitor DPI rendering remain future work.

USAC remains a real-media evidence waiver; accepted Kokoro breakpoint, density and wording
decisions stand. Publication does not turn these evidence gaps into manual acceptance.

Exactly `Briefing.md`, `Changelog.md`, `Decisions.md`, `Handoff.md` remain tracked under
`md-instructions/`. Archives and known local-only items are preserved; retired planning/drop/
archive files stay retired. The feature branch remains. Commit/push only this documentation
closeout to master, verify live content, then STOP. No history rewrite, force-push, branch
deletion or v0.6.7 implementation is authorized.

Recorded by Codex under explicit maintainer authorization.

---

## 2026-09-30 - Maintainer pre-merge README refinement and final candidate refresh

PR #13 was opened under separate Phase-15 Step-2 authorization and remains unmerged into
master. The maintainer now authorizes a bounded README rewrite and package refresh, followed
by a final read-only PR readiness check. README is a compact v0.6.6 user guide, with exact
archive/launcher names, install/use/output/safety/requirements information and brief GPL
attribution. It links the four canonical documents for project/developer detail. Old release
download names and historical engineering narrative are removed; the Releases-page wording
explicitly treats v0.6.6 as unpublished, rather than claiming a download already exists.
This supersedes earlier README capability-only or published-v0.4.0-link restrictions.

Pushed source `1e100e98b5c4f4a11020bdce0e98a631df8b0ee7` contains only README and its
existing PDF/TXT wording-guard reconciliation. The real release builder then refreshed both
82-member RCs. Only README bytes differ from the prior candidate; every other payload byte,
including application code, pins and both launchers, is unchanged. Handoff and the integration
package proof record the new sizes/hashes/source and prior evidence references; SHA256SUMS
agrees. Earlier candidate archives and proof are retained in ignored scratch and Git history.

Focused README/attribution/docs/repository/packaging checks pass 192/0/0, with static gates,
changed-test compile and exact archive/source/extraction/EOL/executable metadata proof.
Phase-14 full verification and previous extracted runtime smoke remain historical and
applicable to unchanged runtime bytes; no full rerun or new native/clean-machine/listening
acceptance is claimed. Approved v0.6.7 deferrals, waivers and the four-doc/local-Archives
contract remain unchanged. Existing local-only/archive content and status are preserved.

The following checkpoint records unpackaged evidence only. After pushing and rechecking PR
head/base/mergeability and package proof, STOP for separate Step-3 merge approval. This scope
authorizes no merge/auto-merge, tag, GitHub Release, publication or Phase 16 work.

Recorded by Codex under explicit maintainer authorization.

---

## 2026-09-30 — Phase 14 final package proof complete; release and integration remain gated

Final Windows/macOS 0.6.6 archives were built through the real release entry point after source
commit `3bb7425801ae18e4a0a40ef27baceb8d5c64a692` was pushed. Both have exact 82-member scope, committed-content/EOL proof,
CRC/safe extraction and correct launcher syntax/Unix executable metadata. Handoff records the
archive sizes/hashes; `files/release-history/v0.6.6-rc-package-proof.json` retains member-level proof.
This evidence-only checkpoint changes no shipped blob and is re-proved against the same archives.

Real first-run pinned setup in the extracted Windows package passed; its actual batch launcher
opened a responsive window and exited normally through WM_CLOSE. Both extracted code trees built
all six panels and preserved containers during appearance switching on Windows. The final macOS
shell executed success/error/repair/translocation paths under Git Bash with interpreter shims;
none of this claims native Aqua, physical scaling, listening or clean-machine acceptance.
The initial disposable Windows window harness timed out because venv redirectors use base
pythonw for the GUI; exact package command-line matching fixed the harness, without app changes.

Full `scripts/verify.py` passed once after final packaged changes: 7,905 passed, 58 skips,
zero failures/errors; all five gates green. Capture-only logging preserved pytest output/JUnit.
All skips are accounted for, strict compilation and whitespace checks pass, and all 16 original
local-only entries are unchanged. The remaining hands-on/native checks stay the approved v0.6.7
backlog, detailed in Handoff. Broader TXT encoding, DPI clarity, USAC waiver and accepted Kokoro
breakpoint disposition are unchanged. No further Phase-14 application change is justified.

**Phase 14 complete; STOP.** Candidate notes remain under `[Unreleased]`, identity 0.6.6.
Maintainer approval of readiness authorizes neither integration nor release/publication.
Phase 15 has not started; no PR/merge/tag/GitHub Release/publication was performed.

— Recorded by Codex under the maintainer's Phase-14 authorization.

---


## 2026-09-30 ? Refreshed integration candidate proof after archival reconciliation

Reconciliation source `21e36163ccc992ef4ba94cb16e58caeda8f236c8` is committed/pushed. The real release builder
then produced refreshed 82-member Windows/macOS RC archives. Their exact source/member/hashes
are in `files/release-history/v0.6.6-integration-package-proof.json` and Handoff. Original
Phase-14 archives and immutable proof are retained; publication must use the current proved
candidate, not silently attach the historical package. Only the four documented verifier/reference
paths changed in the payload. Executable application AST, pins/markers and launcher blobs are unchanged.
Both final extracted code trees pass six-panel Windows Tk/in-place theme smoke; Mac shell paths
pass Git Bash/shim smoke, never native Mac acceptance. Focused 212/0/0 and static gates pass;
Phase-14 full gate/first-run smoke remain historical and no new full suite/install is claimed.
This evidence-only checkpoint changes no packaged blob; reprove it after commit and push.
Then perform the authorized read-only Step-1 recheck and STOP. No PR or later integration/
publication/Phase-16 action is authorized. The archival policy and v0.6.7 deferrals below stand.

? Codex under the maintainer's bounded reconciliation authorization.

---


## 2026-09-30 ? Maintainer archival ruling and bounded Phase-15 readiness reconciliation

The maintainer supersedes the former permanent-reference/archive contract. The only tracked
files under `md-instructions/` are `Briefing.md`, `Changelog.md`, `Decisions.md`, `Handoff.md`.
Retire tracked `don't-delete/`, the completed v0.6.6 instruction drop, and `files/archived-code/`.
The maintainer's existing copies under `files/Archives/` remain untouched; the entire tree is
local-only and must never be tracked, packaged or published. Agents must not delete, overwrite
or recreate its contents. Local copies are optional for fresh clones and verification.
This ruling overrides earlier permanent/protected-path and active-drop language; dated records
and Git history remain intact. Retiring the stale index/roadmap eliminates their current-state
contradictions rather than editing them. EPUB remains retired; its upstream package names are a
compatibility boundary preserving GPL-3.0 attribution, not an offer of EPUB support.

Promote the live integration and closeout contract to Handoff before retiring the drop. The
Phase-15 sequence remains independently gated: readiness, PR, maintainer merge approval, merge,
live-master verification, separate tag authorization, separate release/publication authorization,
then publication of proved packages. Phase 16 has not started and still requires separate
approval after publication/integration facts are confirmed. No branch deletion, history rewrite,
force-push or new AI co-author trailer is permitted by this authorization. Manual checks remain
the accepted v0.6.7 backlog, and the USAC waiver, Kokoro breakpoint, density and wording decisions
are carried truthfully rather than recast as passes.

Briefing's Aqua description now matches `CompactAqua.*`: native layouts/fonts/metrics are
inherited; semantic colors and the Shared tint come from the application appearance bundle.
Verifier/tests enforce exactly four canonical files, reject extra files/directories and aliases,
and prove local Archives exclusion without relying on local archive contents. Archive-content
preservation tests are retired with the live archived-code contract; production EPUB rejection,
dispatch, dependency, source-safety and licence/provenance guards remain.

**Evidence warrants refreshing the RC.** The archived paths never ship, but `scripts/verify.py`
is in both archives. Its new documentation gate and current README/TTS/requirements references
change four packaged paths. Dependencies and application AST/behavior remain unchanged. Preserve
Phase-14 archives and their original proof; build again from the pushed reconciliation source
commit, then record a separate integration package proof. Historical full verification and
runtime smoke apply to unchanged application blobs; focused verifier/repository/packaging gates
cover this bounded change. No expensive full-suite rerun is justified by these edits.

? Explicit maintainer instruction, recorded by Codex.

---


## 2026-09-30 — Phase 13 READY approved; Phase 14 unpublished candidate identity and package repair

The maintainer approved Phase 13 at `56012558a93853ec2b4847297a0372b4050743e7`; local/remote
feature-branch state matched before edits. Phase 14 alone is authorized. Application identity
advances coherently to 0.6.6; live guards/config/README agree. `[Unreleased]` holds explicit
candidate notes covering the whole plan, including Phases 0–6 omitted from the later session log.
There is no dated release heading or claim of merge/tag/GitHub Release/publication. Download
links remain on the existing published release. Older dated identity statements remain history.

**Confirmed defects justify bounded remediation.** Real Bash over packaged macOS launcher bytes
reproduced a repair failure: `rc=$?` after an `if` without `else` receives zero rather than the
failed bootstrap status. Capture moves into `else`; exit 3 enters repair and ordinary failure
still stops. Interpreter shims prevent installs/GUI activity during this shell regression.
Archive metadata also reproduced `create_system=0` (DOS) despite high-bit Unix mode `100755`
on Windows. Executable entries now declare Unix (`3`), so their intended permissions are
unambiguous to Unix extractors. The existing mode test gains that assertion; it failed first.
No runtime policy, dependency pin, application processing or UI behavior is otherwise changed.

**Proof ordering:** commit/push packaged identity and documentation first; run the real builder,
prove exact contents against that commit, perform available extracted-package smoke, and run
the full checkpoint after final packaged changes. A later evidence-only commit may update
unpackaged documents; reproof must establish identical shipped content at the final checkpoint.
Release checklist text now distinguishes automated gates/approved deferrals and stops for
separate integration/release/publication authorization. Native Mac, clean-machine, physical
scaling, listening and long real-workload checks remain v0.6.7 deferrals, never manual PASS.
Exact final source/hash/verification evidence belongs in Handoff and the active Phase-14 note.

— Recorded by Codex under the maintainer's Phase-14 authorization.

---

## 2026-09-29 — Phase 12 approved; Phase 13 independent release review and bounded appearance remediation

Started from the verified local/tracking/live-remote Phase-12 checkpoint
`685c29becae1453d33c1349865d48a2a3bc78957`, against the integrated v0.6.5/master merge base
`f7fb762e63bc7d46d099ddc8cead2dc68fb188e0`. Prior review conclusions were independently checked
against the complete diff, current code, regressions and Git history. Scope is Phase 13 only.

**Three confirmed appearance defects were release blockers and are fixed.** Reset Preferences
cleared saved Dark without refreshing the live theme/toggle; a failed atomic appearance save
returned the requested value after storage rolled back; Aqua native controls followed OS appearance
while classic Tk content followed the app, and its empty style catalogue omitted the Shared tint.
Reset now refreshes existing listeners from the actual default; the toggle returns the actual stored
value. Cancelled/failed reset remains unchanged. No panel, Book, job or widget is reconstructed.

**Aqua retains native controls.** `CompactAqua.*` is a distinct namespace, so even a platform-branch
comparison cannot leave Windows cloned layouts/font/padding on native controls. Semantic surface,
label and Treeview colors are configured; only the Shared group border is cloned from clam.
Per-window native appearance follows the app preference for the root and new/existing owned dialogs.
Native menus are left to Aqua. This keeps control layouts/metrics and existing composition hints.

The API and startup timing were checked against Tk's own
[macOS documentation](https://github.com/tcltk/tk/blob/core-8-6-branch/macosx/README) and
[WmWinAppearance implementation](https://github.com/tcltk/tk/blob/core-8-6-branch/macosx/tkMacOSXWm.c).
The command can return an empty result before the native window exists. A one-time Map binding
retries the latest choice, replacing an older pending binding; it does not run an event loop inside
construction. Unsupported builds are harmless no-ops. Command, timing, nested-window refresh,
native inheritance and Shared tint are automated seams, **not native Mac rendering evidence**.

**Documentation truth:** Briefing's old ACT/classic boundary and unresolved Converter/popdown
claims were superseded by the implemented compact state. Its all-engine contentless-source claim
was too broad: Edge rejects all four empty/header/heading/punctuation cases; local engines reject
empty text after header stripping and retain headings as text. Current documentation and the test
docstring now state the actual coverage. No parsing policy/model behavior was changed.

Eight regressions were added; failing-write/reset/native-command cases were observed RED first,
and the unmapped-window seam separately failed before its correction. Old Aqua empty-style
assertions now prove native inheritance instead. Full verification passed 7,903 tests with 58
independently accounted skips; after the last native timing refinement, all 254 affected tests
passed. Strict compilation of 243 tracked Python files and whitespace checks pass. Exact sequencing,
review dispositions, evidence limits and skip categories are recorded in Handoff's Phase-13 entry.

**READY under the maintainer's standing deferrals.** No confirmed release blocker remains after
re-review. Hands-on Mac/scaling/listening/clean-machine/long-workload evidence remains v0.6.7 work;
USAC is still a real-media waiver, Kokoro's breakpoint stays accepted without a retune, and broader
TXT encodings/DPI awareness remain future work. Identity stays `0.6.2`, unreleased; no final artifacts,
merge, tag, publication or Phase 14 action. Local-only work is preserved and excluded from the commit.

— Recorded by Codex, independent reviewer, under the maintainer's Phase-13 authorization.

---


## 2026-09-29 -- Phase 11 approved; Phase 12 automated acceptance and warning-safe test literals

The maintainer approved Phase 11 at `1a218f96ab57c53758186ac1e2cd9f483ce22d96` and
authorized Phase 12 only. Local and remote feature-branch HEAD matched that exact checkpoint
before edits. Known local-only workspace/status-helper/screenshot changes remain outside the commit.

The standing 2026-09-28 manual-testing deferral applies: Phase 12 uses the existing real-Tk
six-tool matrix, bounded synthetic-media jobs, deterministic failure/control seams, and the
complete regression gate. Native Aqua, physical Windows scaling, clean-machine installation,
listening and long real-workload drills remain the v0.6.7 backlog. Windows measurements at
1024×800 are not native macOS acceptance; stubbed TTS synthesis is not audio-quality evidence.
No test is weakened or relabelled as a manual pass to close this phase.

Forced compilation reproduced both invalid-escape `SyntaxWarning`s in
`test_edge_make_m4b_chapters.py`. Only the backslash-containing title literal and its nearby
docstring gain raw-string prefixes. A before/after AST comparison proves their values and all
test behavior are identical; all 243 tracked Python files compile with `SyntaxWarning` as an
error. The existing real-FFmpeg chapter regression passes with the original title expectations.

The first full gate exposed seven additional test portability defects with repository-contained
temporary files: five eSpeak fixtures presumed an absolute short path, and two cleanup assertions
presumed temporary repositories lived outside the checkout. The eSpeak tests now pass short
relative candidate paths from a temporary cwd while keeping real links, absolute long sources
and the exact buffer boundary checks. Cleanup tests assert the supplied copy's exact target and
protect the real environment, rather than excluding the whole repository's developer scratch.
The eighth failure was executable selection: WSL's `bash.exe` exists but cannot start Bash here.
The verification process now selects installed Git Bash through its own PATH, without changing
the packaged-launcher test or global settings. The four affected modules pass all 302 tests.
These confirmed failures require a final full gate after remediation; the earlier failed gate
is retained as evidence, not reported as acceptance.

Acceptance evidence and final gate/skip accounting live in the Phase-12 Handoff entry. No
production change or version bump is warranted. Identity stays `0.6.2`, unreleased, until Phase 14.
Phase 12 ends at a committed/pushed checkpoint for maintainer review; Phase 13 requires the next
authorization and has not started.

— Codex, 2026-09-29.

## 2026-09-29 -- Phase 10 approved; the v0.6.6 TXT encoding contract is UTF-8 only; Phase 11 packaging, setup and release hygiene, including a first-run setup Critical found by a real install from the archive

**Phase 10 approved.** The maintainer approved the Phase 10 checkpoint `098ef9a`. Phase 11 started
from that exact commit, with the local-only `.ai/`, `scripts/project-status.py` and screenshot
renames preserved uncommitted.

**1. Maintainer ruling on the Phase 10 TXT-encoding Minor: no fallback in v0.6.6.**
- **Contract:** a `.txt` source is **UTF-8, with or without a byte-order mark**. No ANSI/cp1252 or
  guessed-encoding fallback is added in v0.6.6. A file in another encoding fails that one item
  (with the technical decode message) and the run continues; it is never guessed at or spoken as
  mojibake. Broader encoding support is deferred to **v0.6.7**.
- **Documented** as a README input requirement (the TTS feature line, and a Known Limitations entry
  with the Notepad re-save step) and in `Briefing.md`'s known limitations.
- **Made true on every read path.** Phase 10 fixed the three direct-file engines. Phase 11 found the
  fourth: a folder-imported Edge `.txt` goes through `batch_convert.convert_single_pdf`, which still
  read plain `utf-8`. The BOM reached Edge as the first character of the first chunk, and a BOM-only
  file became one `"﻿"` chunk instead of "no text". It now reads `utf-8-sig`, RED-first.
- **Pinned:** `test_tts_text_bom.py` gains the folder path (same text with or without a BOM; a
  BOM-only file is "No text chunks") and one contract test. A cp1252 file with accented letters raises
  `UnicodeDecodeError` in `get_book`, Kokoro and Chatterbox, and fails the folder item, speaking
  nothing.

**2. Only committed files are packaged, and the release build refuses a dirty tree.**
- **Gap, confirmed by a real build:** `release.py` walked `scripts/` on disk, so the maintainer's
  local-only, never-committed `scripts/project-status.py` landed in **both** archives. The existing
  completeness test derived its expectation from the same disk walk, so it could not notice.
- **Decision:** inside `scripts/` a file ships only if git tracks it. The name/suffix exclusions
  (`__pycache__`, `*.pyc`, `.DS_Store`, `Thumbs.db`) still apply, even to a tracked file. `main()`
  refuses to build while any packaged path (`scripts/`, `README.md`, `config.toml`, both
  launchers) differs from HEAD in the working tree or index, so an archive always matches a commit.
  Untracked files are reported as "not packaged (untracked)", not refused. Outside a git checkout
  the packager refuses (`ReleaseError`) rather than guessing.
- **Why not the alternatives:**
  - excluding `project-status.py` by name is exactly the forgotten-exclusion trap that the
    explicit-scope design (2026-08-08) exists to avoid;
  - packaging HEAD blobs (`git archive` / `git show`) would ship the `.bat` with the repository's
    normalized LF endings rather than the CRLF that `.gitattributes` gives it on checkout;
  - silently packaging a modified tracked file would make an archive that matches no commit.
- **Boundary kept:** `release.py` stays out of the application's import graph. Its only new import is
  `subprocess`, for git; the stdlib-only import test now names it.

**3. The launchers, proved byte for byte.** New tests read the packaged bytes:
- the `.bat` is CRLF throughout;
- the `.command` starts `#!/bin/bash`, holds no CR, parses under `bash -n`, is stored `0o755` and
  is committed `100755`;
- `.gitattributes` pins both endings.

The `.command`'s App Translocation help told Mac users to move an `"audiobook-creation-tool"`
folder. Finder actually extracts `AudiobookTool-MacOS-vX.Y.Z.zip` into a folder of that name. The
text now names the `"AudiobookTool-MacOS-v..."` folder (text only; no logic changed).

**4. README corrected to the package it describes:**
- archive contents (`config.toml` was missing; the committed-only rule and the dirty-tree refusal);
- the macOS extracted-folder name;
- the Cover Image output (a numbered run folder by default, not "next to the source images"), and
  the one opt-in exception to "originals are never modified";
- the shared compact layout and the remembered Light/Dark toggle;
- the UTF-8 TXT contract;
- the disk requirement: the environment is ~2.5 GB, measured, because the local-voice libraries
  always install. Only the voice models are optional. The old row said "a few hundred MB";
- the clean-install limitation, restated with the evidence below.

**5. CRITICAL, found by a real first-run install from the freshly built archive, and fixed:
first-run setup failed on a healthy machine.**
- **What happened:**
  - built the Windows archive and extracted it under `files/dev-work/phase11/`;
  - ran the launcher's first-run path, `bootstrap.py --headless`, with the base
    Python the `.bat` would pick. Every package installed.
  - `validate_installed_packages` then reported `nltk` and `chatterbox` as "failed to import";
  - setup ended **"Python packages installed but could not be imported… Setup did not
    complete"** (exit 1, 5:19).
- **Root cause, measured:**
  - nothing was broken; both imported fine afterwards;
  - the per-module probe allowed **30 s**, and a cold first import in a brand-new venv
    compiles and security-scans thousands of fresh files. `import nltk` (it pulls in
    `scipy.stats`) took **32.4 s** cold against **1.1 s** warm, and `chatterbox` (torch) also
    ran past 30 s;
  - the launch-time proof (`prove_required_imports`) already allowed 600 s and treats a probe
    that cannot finish as no finding. Only the setup-time check was tight.
- **Second defect on the same path, measured:**
  - the "repair" was `pip install --force-reinstall <name>` with no version, so it replaced the
    package and its whole dependency tree with that day's PyPI releases;
  - afterwards five pins had drifted: `nltk` 3.9.4→3.10.3, `pillow` 12.2.0→12.3.0,
    `tqdm` 4.67.3→4.70.1, `soundfile` 0.13.1→0.14.0 and **`setuptools` 80.9.0→84.0.0**.
    setuptools is the deliberate compatibility hold for `pkg_resources`, which Chatterbox's
    watermarker needs;
  - the fresh, uncompiled files also made the re-probe cold again, so it timed out again;
  - the requirements stamp hashes the file, not the installed set, so the drift would never
    have been reconciled.
- **Decision:**
  - one named window, `IMPORT_PROBE_TIMEOUT_S = 600`, is shared by both import proofs. The
    stdlib capability probes on a base interpreter keep their 30 s;
  - the reinstall is constrained with `-c scripts/requirements.txt`, so a real repair stays
    on the pins.

  RED-first: `test_bootstrap_import_validation.py` (6 tests). Both halves were mutation-checked.
- **Re-proved for real, from a rebuilt archive:**
  - first-run setup **exit 0** (1:32, warm pip cache): all required imports clean; the WinGet
    Gyan FFmpeg 9.0.1 pair verified and pinned with nothing installed; **all 25 pins exact**
    across 169 packages; `.venv` 2.5 GB;
  - `--venv-check` then answered 0;
  - the extracted **`.bat` itself**, run non-interactively, took the fast path. It started the
    GUI detached under `pythonw.exe` from the extracted venv: a visible, responding "Audiobook
    Creation Tool" window, closed cleanly, with no repair on that launch;
  - all six tools were built in the extracted venv from the archive's code alone (no module
    loaded from the dev tree).
  - **Not a clean machine:** Python 3.12, the FFmpeg pair and the pip cache were already present.
    The README says so.

**Re-proved, not reopened:** the first-run, self-heal, venv-recovery, requirements-stamp and
FFmpeg repair/acquisition contracts. Only the two validation defects above changed. The sweep counts
are in `Handoff.md`.

**Flagged, not fixed (Minor):** `files/tests/test_edge_make_m4b_chapters.py` (added in Phase 10)
raises two `SyntaxWarning: invalid escape sequence` warnings at collection (`'\s'`, `'\`'` in a
string and a docstring). This is harmless today and becomes an error in a future Python. It is left
for the maintainer's review.

**Deferred to the v0.6.7 manual backlog (maintainer ruling 2026-09-28):** a hands-on double-click of
each extracted archive on a clean Windows and a clean macOS machine, including Gatekeeper
quarantine, App Translocation and first-run network installs.

Version identity remains `0.6.2`, unreleased. Nothing was tagged, released or published. Phase 12 is
not started.

— Recorded by Claude Code on the maintainer's Phase 10 approval and Phase 11 instruction, 2026-09-29.

---

## 2026-09-28 -- Phase 9 approved; Phase 10 product hardening and the disposition of every open deferral

**Phase 9 approved.** The maintainer approved the Phase 9 checkpoint `758e24f`. Phase 10 started
from that exact commit.

**1. Edge `make_m4b` chapter-muxing hazard (v0.6.5 Phase 9 note): not reproducible here. The
path is kept and hardened, not retired.**
- **Evidence.** The 2026-09-20 truncation needed a cover-art *video* stream in the mux (lcm of
  44.1 kHz and 1/90000 = 4,410,000; a chapter longer than ~487 s then does not fit). `make_m4b`
  muxes audio only, so the chapter text track takes the audio's timescale: 1/24000 for Edge's clips.
  That holds a chapter of about 24.8 hours. `add_cover` adds the cover afterwards with mutagen as a
  `covr` atom and never re-muxes the chapter track.
- **Measured** with FFmpeg 9.0.1 at 24 kHz and 44.1 kHz. Chapters of 30/600/1300/20 s kept four
  titles, four text-track samples and exact boundaries, before and after `add_cover`.
- **Negative control.** Forcing `-movie_timescale 4410000` into `make_m4b` reproduces the
  2026-09-20 displacement exactly (`Intro, Outro, Outro`). The new test catches it.
- **Why keep it.** The path stays CLI-only (`--format m4b`); the GUI's MP3-only dispatch is pinned in
  `test_tts_importing.py`. Retiring it would edit the vendored upstream CLI and its provenance guards
  for no user-facing gain. Three real defects on it were small and were fixed instead:
  - `generate_metadata` wrote values unescaped; they now go through `shared.metadata.ffmetadata_escape`;
  - it wrote in the locale encoding, so cp1252 raised on a non-Latin title; it now writes UTF-8;
  - `_run_ffmpeg` ignored the exit status; it now uses `check=True`.
- Pinned by `files/tests/test_edge_make_m4b_chapters.py` (real FFmpeg).

**2. Kokoro break placement: accepted as-is, not retuned.** `split_into_chunks` tries `.`, `!` and
`?` in turn and keeps the *last punctuation type* with a valid break, not the rightmost break. So a
`?` near the start of a window can produce a one-sentence chunk; the measured case is 19 characters
where the rightmost valid break was at 2,988.
- No text is lost, duplicated or reordered, and no chunk passes the ceiling. The only effect is where
  one 50 ms chunk seam falls, which only listening could judge.
- Under the 2026-09-28 ruling (no listening evidence, so no retune) it is accepted and documented.
- A multi-chunk case in `test_segmentation_source_span.py` pins it. The corpus items there were too
  short to split at all.

**3. The two persistent focused-suite failures were test portability defects, not product bugs.**
- `test_tk_gate.py::test_the_reset_clears_a_leaked_minsize_floor`. Windows applies a *withdrawn*
  toplevel's `geometry()` only when it is mapped, so the test read the pre-reset size (200 or 1100).
  It now measures mapped. A leaked floor still clamps 920×600 to 1024×800 there (probed), so the
  test still discriminates. A mutation that drops the reset's `minsize(1, 1)` fails it.
- `test_m4b_maker_processing.py::test_write_concat_list_escapes_an_apostrophe...`. A POSIX literal
  built as `Path` renders with backslashes on Windows. It now uses `PurePosixPath`. The escape was
  always right, and the real-FFmpeg apostrophe build passes on Windows.

**4. Fresh six-tool audit: three confirmed defects, each fixed with a regression written RED first.**
- **TTS, UTF-8 BOM.** The three direct engines read `.txt` as plain `utf-8`, which keeps U+FEFF on
  the first line; `strip` leaves it, so the `Title:` / `Author:` / `#` checks missed. Edge spoke the
  header under an extra blank chapter and lost the title and author; Kokoro and Chatterbox spoke the
  `Title:` line. Now `utf-8-sig`, which is identical for BOM-less files.
- **TTS, Edge direct with nothing to speak.** This covers empty, header-only, heading-only and
  punctuation-only files. It published a 0-second MP3 as a success, while the folder path, Kokoro
  and Chatterbox already failed the item. The runner now raises the Kokoro/Chatterbox message
  before any synthesis, and nothing is written.
- **Cover, EXIF orientation.** Output, preview and Details used the raw pixels and dropped the tag,
  so phone photos came out turned, and replace mode overwrote the original that way. Now the image
  goes through `ImageOps.exif_transpose`. HEIC is untouched: pillow-heif rotates on decode and resets
  the tag to 1, and a test proves there is no double turn. MP3/M4B artwork is out of scope here: it
  embeds JPEG/PNG bytes unmodified by design, and HEIC arrives upright.

**Audited clean, no change:**
- Hidden files and subfolders: every tool's folder import goes through the shared walk, which skips
  dot-prefixed names (including macOS `._` AppleDouble files) and Windows hidden files.
- Naming, collisions and Unicode: the shared planner NFC-normalizes and case-folds, so NFC/NFD and
  case-only twins are numbered, never overwritten.
- Pause/Resume/Cancel/Retry Failed and partial cleanup: TTS discards the occurrence's own partial on
  failure and on cancel. Cover's replace mode is temp-sibling → validate → atomic `os.replace`.
- The list keyboard shortcuts added in Phase 2 go through the same run lock as the buttons in all
  tools.
- A PDF with no text already fails with a clear message.

**Flagged minors, re-investigated:**
- The latent status-bar squeeze is not a defect. Every launcher status message is a fixed string or
  a tool title; the longest is 325 px against a ~467 px budget.
- The tight→regular density step is inherent to the approved rule.
- Family A/B importer wording stays accepted.
- **New Minor, not fixed:** a `.txt` that is not UTF-8 (a legacy "ANSI"/cp1252 file) fails that one
  item with a technical `UnicodeDecodeError` detail; the rest of the run continues. Adding an
  encoding fallback is a policy choice, left to the maintainer.

Version identity remains `0.6.2`, unreleased. Phase 11 is not started.

— Recorded by Claude Code on the maintainer's Phase 9 approval and Phase 10 instruction, 2026-09-28.

---

## 2026-09-28 -- Phase 8 approved; hands-on testing deferred to a v0.6.7 bug-fix branch; Phase 9 cross-tool geometry, DPI, accessibility and consistency

**Phase 8 approved.** The maintainer's required Windows gate on the M4B Metadata Editor at
`81680d1` passed: Light, Dark and the manual workflow. Phase 8 is closed.

**Maintainer ruling: hands-on testing is deferred to v0.6.7.** For the rest of v0.6.6, hands-on
bug and edge-case testing moves to a future long-lived **v0.6.7 post-merge bug-fix branch**. Each
remaining phase instead automates and mechanically proves as much as it practically can through the
CLI and tests. A phase does **not** stop merely because a manual-only check is unavailable. It
records exactly what stayed unverified by hand, and that list becomes the v0.6.7 backlog (kept in
`Handoff.md`). This supersedes the plan's remaining manual hard gates:

- Phase 9: "Manual Windows and macOS matrix is a hard gate".
- Phase 10: "Manual/listening gates wherever automation cannot establish correctness". With no
  listening evidence, the Kokoro breakpoint rule is not retuned; Phase 10 accepts and documents it
  instead.
- Phase 11: "real packaged-launch manual gates on both platforms".
- Phase 12: the manual visual matrix on both platforms and the long Pause/Resume/Cancel/Retry
  Failed drills.
- Phase 14: the final package launch smoke on both platforms.
- The Hard Boundaries line "bypass a required Windows/macOS/manual/listening gate", and the
  Definition of Done's "Windows/macOS visual/manual gates pass". Both now read "automated evidence
  plus a recorded v0.6.7 manual backlog".

**What is not superseded:** the maintainer's own authorization checkpoints. Every phase still
stops and reports. Merge, tag, release and publication still each need their own explicit approval.
Nothing deferred here is described anywhere as passed.

**Phase 9 (cross-tool geometry, DPI, accessibility + consistency).** The six panels were audited
as one application in the real launcher shell. A generic probe walked **every** interactive widget
of every tool (not a hand-picked list) at seven sizes in Light and Dark. The real Windows content
areas measured:

| Window | Content area | Layouts (TTS / Converter / MP3 / Maker / Cover / Metadata) |
|---|---|---|
| 920×600 (minimum) | 721×457 | split / split / tight / tight / columns / tight |
| 1024×720 (default) | 825×577 | split / split / tight / tight / columns / tight |
| 1024×800 (the macOS minimum's size) | 825×657 | split / split / regular / tight / columns / tight |
| 1280×900 | 1081×757 | wide / wide / regular / regular / split / regular |
| 1536×800 (125% maximized, logical) | 1337×657 | split / split / regular / tight / columns / tight |
| 1280×665 (150% maximized, logical) | 1081×522 | split / split / tight / tight / columns / tight |
| maximized (100%, 1920×1080) | 1721×866 | wide / wide / regular / regular / wide / regular |

Findings and dispositions:

1. **Windows 920×600, no core scrolling: PASS.** At every size, in both appearances, every control
   of all six tools is on screen, inside the content area and the window, and at its full requested
   size, with no overlaps. The flexible lists, editors, browser and logs keep usable sizes. No
   Canvas or Scrollbar wraps a section. Activity sits right of Sections 1–2 on the guided tools and
   below Section 3 on the dense ones.
2. **macOS 1024×800: automated evidence, not a live pass.** HOME-PC has no Mac. The evidence:
   - the same contract passes at the 1024×800 size under Windows metrics;
   - every panel picks its density or layout from live requested sizes, not pixel breakpoints;
   - the new cross-tool module is platform-aware: on aqua it measures 1024×800, 1280×900 and
     maximized, skips nothing, and pins no Windows pixel counts. It *is* the Mac gate.

   The audit also found the aqua-only `test_m4b_layout.py` and `test_mp3_tool_layout.py` **stale
   against the approved v0.6.6 design**. They still demanded a two-row floor, a separate preserve
   note line, and growth across the tight→regular switch. Wherever the Mac lands in the tight
   density, they would fail for the wrong reason. Both were reconciled to the approved density
   rules. Run with their aqua skip removed, on Windows metrics, they pass except the two
   `mode == "aqua"` identity pins, which are correct on a Mac. The five per-tool real-shell tests'
   Windows-measured density/mode names are now asserted on Windows only; their on-screen checks
   still run on aqua. **The live Mac run is deferred to v0.6.7.**
3. **Windows 125% / DPI awareness: the 2026-08-02 deferral is dispositioned. The process stays
   DPI-unaware for v0.6.x, deliberately.**
   - **State:** `GetProcessDpiAwareness` is `UNAWARE` with Tk running, under both `python.exe` and
     `pythonw.exe` (the `Setup_and_Run` path), and Tk lays out at 96 dpi.
   - **Why that is a valid proof:** Windows bitmap-scales an unaware window, so its logical
     geometry is scale-invariant. The logical client areas of a maximized window on 1920×1080 at
     125% (1536×800) and 150% (1280×665) were measured and pass.
   - **Why no live 125% run:** both HOME-PC displays are at 100% (checked per-monitor-aware).
     Changing the system display setting was not done.
   - **Why not opt in now:** it would make every fixed pixel metric wrong until re-measured. That
     includes the 180/220 px sidebars, the 40 px previews, the 13 px check/radio images, the 170 px
     status wrap, the 460 px dialog wrap and the tight paddings. It would also need fresh visual
     evidence, which the deferral rules out. The cost of staying unaware is soft text; clipping
     cannot result.
   - **Guard:** a tripwire test fails on any `SetProcessDpiAwareness*` / `SetProcessDPIAware` /
     `tk scaling` call.
   - **Future:** sharp per-monitor DPI text is future work (a v0.6.7+ candidate), not v0.6.6.
4. **Clipping / wrapping / field reachability: PASS; no new defect.** The Phase 6–8 known minors
   stand as display-only yields at 920×600: long read-back lines and the navigator heading.
5. **Focus and keyboard: one DEFECT, fixed.** Cover's three source-browser views share one grid
   cell and switch by `tkraise`, so the two lowered views stayed mapped. Tab visited both — two
   invisible focus stops before the visible one. `CoverBrowser._raise_view` now takes the lowered
   views out of the Tab order (restoring each view's own `takefocus` when shown). A keyboard
   already inside a lowered view follows to the one shown. In every tool, Tab reaches every
   visible, enabled control and walks Section 1 → 2 → 3 → Activity.
6. **Section / importer / Activity consistency: PASS.** In both appearances, all six share the
   numbered titles, one section style, one Activity (Summary | Detailed, Clear Log, identical log
   colors and font) and one job-control set (Pause / Resume / Cancel / Retry Failed). No ttk
   widget sits on a non-`Compact` style. *Suggestion only:* the guided tools say
   `Add Files…` / `Clear All` and the dense tools `Add Files` / `Clear All Imports`. That is
   accepted Family A/B wording, so it was not changed.
7. **Light/Dark switching and state: PASS.** The shell's toggle, pressed from one tool with the
   other five hidden and then pressed back, moves and rebuilds no control in any tool, and every
   layout mode is kept. Cover was the one tool without a toggle-during-a-running-job test; one was
   added (parked real resize, SUCCEEDED, sources byte-identical).
8. **Minimum vs maximized: PASS.** Every flexible region is at least as large maximized as at the
   minimum. *Minor, flagged, not fixed:* the tight→regular density switch re-spends height on
   chrome, so between those two sizes a region can shrink as the window grows. Examples: Metadata
   Chapter Titles 76→58 px, 1024×720→1280×900; Maker 101→92 px. The step is inherent to the
   approved §1 density rule and appears in the approved Phase 6–8 tables. Moving the threshold
   would change approved appearance, so it is left for the maintainer (or v0.6.7).
9. **Owned dialogs, title bar and combobox theming: no gap; no change.** Cover's replacement
   confirmation and Preferences & Data already follow the bundle. Every other dialog is a native
   messagebox or file dialog, which the contract keeps native. The TTS and three Family-B
   drop-downs already recolor their pop-downs; the Converter and Cover have none. The title bar is
   OS chrome over an unchanged shell.
10. **Latent Minor, flagged, not fixed:** the status label in the Windows and aqua shell status
    bars is packed before its buttons. A status message wider than ~467 px at 920 px would squeeze
    Preferences & Data, the Light/Dark toggle and Open log folder out. The longest real message is
    325 px, so it cannot happen today.

**Alternatives considered:**
- Turning DPI awareness on now: rejected (see 3).
- Moving the density threshold for monotonic growth: rejected; it changes approved appearance.
- A whole-panel scroll or larger minimum anywhere: rejected by §1, and not needed.
- Leaving the stale aqua tests alone: rejected; they would fail on the Mac for the wrong reason
  and hide the real gate.

**Consequences:**
- New `files/tests/test_cross_tool_consistency.py`.
- The Cover focus fix, with its tests in `test_cover_browser.py`, and the Cover mid-run toggle
  test.
- The aqua reconciliation in seven test files.
- The plan gains a manual-deferral clarification and Phase 8/9 notes; `Handoff.md` records the
  checkpoint and the v0.6.7 backlog; `Briefing.md`'s DPI limitation gains its disposition.

Version identity remains `0.6.2`, unreleased. Phase 10 is not started.

— Recorded by Claude Code on the maintainer's Phase 8 approval and Phase 9 instruction, 2026-09-28.

---

## 2026-09-28 -- Phase 7 approved; M4B Metadata Editor rebuilt to the compact Family-B hierarchy (Phase 8), retiring the last `ACT.*` tool interior

**Phase 7 approved.** The maintainer's required Windows manual gate on the M4B Maker at `333134f`
passed. It covered Light, Dark and the manual workflow. Phase 7 is closed.

**Phase 8 (M4B Metadata compact visual standardization).** The Editor was the last panel still
drawn in the retired `ACT.*` interior. Measured inside the real launcher at 920×600 (content
721×457), it asked for 1334×665:

- the Chapter Titles box and the log were never mapped;
- Open Output Folder, Resume / Cancel / Retry Failed and Clear Log lay outside the content area;
- the fourteen Shared/Book entries were squeezed to 57–66 of their 78 px.

At 1024×720 the chapter box was still unmapped and the log 3 px tall. Its presentation is rebuilt
on the approved Cover/TTS/Converter/MP3 Tool/Maker control language, through the shared
`appearance`/`job_ui` primitives only. It follows the Maker's Phase 7 pattern where the panels
are alike:

- **Hierarchy:**
  - `1. Import & Books`: Import Folder, Add Files, Clear All Imports, import status, output hint,
    Book navigator (Remove Book only).
  - `2. Metadata`: Shared over Current Book, the seven text fields and artwork in each, the
    source read-back beneath the Book's fields.
  - `3. Chapters & Save`: the Chapter Titles box; Auto-number Series Part / Start Part and the
    preserve note; then Save Tags, Clear All Tags (keep chapters), Remove Series Numbering and
    Open Output Folder beside the shared job area.
  - Activity below, with Summary | Detailed and Clear Log.
- **Shared vs Current Book:** the same `shared_labelframe` / `labelframe` treatment as the MP3
  Tool and the Maker, in Light and Dark.
- **Save Tags** is the tool's one primary action: the compact button with the restrained accent
  outline (`default="active"`). No button is a filled primary. Clear All Tags and Remove Series
  Numbering keep the shared destructive treatment.
- **Theme:** the whole interior uses the shared compact bundle through a new `appearance_bundle`
  seam. `theme` supplies only the aqua composition hints. A live toggle recolors the Chapter
  Titles box, the log panes and the Book selector's drop-down in place; nothing is rebuilt.
- **Small windows:** the same measured **tight density** (the §1 order: padding and chrome, then
  reflow, then one-row/one-line floors held by `rowconfigure(minsize=...)`), and the left-eliding
  output hint.

Rulings taken within the maintainer's instructions, where the Editor differs:

- **The Shared caption takes the dense tools' one wording:** "Shared — applies to every Book and
  overrides its own value" (was "Shared — a value here overrides every Book; blank = each Book on
  its own"). The Current Book caption keeps the Editor's preserve-by-default statement ("blank or
  unchanged = keep the source's own value"). Semantics are unchanged.
- **Open Output Folder joins the actions**, beneath Save Tags, with the two destructive actions in
  the second column. This was aqua's arrangement since v0.6.4 Phase 13 and is now the compact
  default everywhere, on the Converter's precedent (its Open Output Folder lives in Output & Run).
  In the import band it left the output hint almost no width at 920×600. Same control and command.
- **Clear Log joins Activity**, as on every compact panel.
- **The compact read-back is the default** (aqua's since Phase 13): the source line runs the full
  width, and the "Detected on file" line shares a line with the facts and Status. The Windows
  "rows" arrangement (three lines beside the artwork) is kept for a theme that asks for it.
- **The tight density keeps every statement and control, on fewer lines.** At 920×600 every
  flexible region was at its floor and Activity still ran ~12 px below the content area:
  - The job area is 11 px taller than the two-column action grid beside it. The status cannot
    sit beside the controls as on the Maker: the grid leaves 81 px there.
  - The Editor's two read-back lines cost one more line than the Maker's Book-only row.

  So in the tight density:
  - Auto-number Series Part / Start Part join the Chapter Titles caption's line, in short
    wording ("Auto-number Series Part", "Start Part:"). The caption takes a short form that
    keeps its preserve rule: "Chapter Titles — line N renames chapter N; blank or unchanged
    keeps it".
  - The preserve note's own line steps aside, and its statement joins the Current Book caption,
    which already carries the other half of it: "Current Book — blank or unchanged = keep the
    source's own value; originals are never modified (copies are written)".
  - The job status takes two lines (the MP3 Tool's Phase 6 arrangement).

  With room, everything returns to its regular wording and lines. Variables, controls and meaning
  are unchanged. The shell tests fail if the preserve statement is ever off screen.
- **Both artwork previews are at most 40 px** (`COMPACT_PREVIEW_MAX`, opt-in, as on the Maker).
  `PREVIEW_MAX` (56 px) remains the control's default, though no production panel uses it now.
- **Metrics:** entries ask for 8 characters (was 9), field gap 6, group padding 6, artwork gap 8.
  The Chapter Titles box asks for 6 rows (floor 2, tight 1) and the log for 6 lines (floor 2,
  tight 1).
- **No §4 list shortcuts are added.** The Editor has no ordered list; its Books are pages behind
  the navigator, and Entry and Chapter Titles keys stay the text's own.

**Deliberately unchanged:**

- one page per imported file; preserve-by-default; Shared precedence (`disabled_fields`);
- source prefill never becoming an edit; the per-page chapter buffers;
- Save Tags / Clear All Tags / Remove Series Numbering and their confirmations;
- artwork validation, success-only Auto-number, staged validation and publication, output runs and
  collisions, no re-encoding;
- Pause/Resume/Cancel, Retry Failed, the frozen run state and source immutability.

`m4b_metadata_workflow.py`, `m4b_metadata_plan.py`, `m4b_metadata_batch.py`,
`m4b_metadata_processing.py`, `m4b_artwork_ui.py` and every `shared/` module are untouched.

**Known minor:** at 920×600 a long "Detected on file" line is clipped where the facts and Status
sit beside it. The source line is also clipped when its path is long. Both show whole from
1280×900 up, and the facts, Status and source file name stay visible.

**Consequences:** the plan gains a Phase 8 note and `Handoff.md` records the checkpoint. Tests that
pinned the Editor's `ACT.*` styling moved to the compact system:
- `test_m4b_metadata_editor_ui.py`: the compact-style and namespaced-style tests, the classic
  widgets in Light and Dark, and the two aqua tests now pass a darwin bundle and pin the compact
  composition;
- `test_launcher_smoke.py`: `CONVERTED_TOOLS` is empty, and the Editor joins `COMPACT_DENSE_TOOLS`;
- `test_clear_all_imports.py`, `test_output_location_refresh.py` and
  `test_prototype_regression.py`.

No tool interior names an `ACT.*` style any more. `ACT.*` remains the launcher shell's chrome and
the developer-only prototype specimen. Version identity remains `0.6.2`, unreleased. Phase 9 is
not started.

— Recorded by Claude Code on the maintainer's Phase 7 approval and Phase 8 instruction, 2026-09-28.

---

## 2026-09-28 -- Phase 6 approved; M4B Maker rebuilt to the compact Family-B hierarchy (Phase 7), with the Phase 6 tight density plus three Maker-specific reflows

**Phase 6 approved.** The maintainer's required Windows manual gate on the MP3 Tool at `d6cb0be`
passed. It covered Light, Dark and the manual workflow. Phase 6 is closed.

**Phase 7 (M4B Maker compact visual standardization).** The Maker was the second dense panel
still drawn in the retired `ACT.*` interior. Measured inside the real launcher at 920×600
(content 721×457), it asked for 1043×649:

- the track list, Chapter Titles box and all four track buttons were never mapped;
- Remove Book and the custom-destination toggle were outside the content area;
- the log was 3 px tall.

At 1024×720 the lists were squeezed to 5 px. Its presentation is rebuilt on the approved
Cover/TTS/Converter/MP3 Tool control language, through the shared `appearance`/`job_ui`
primitives only. It follows the MP3 Tool's Phase 6 pattern exactly where the panels are alike:

- **Hierarchy:**
  - `1. Import & Books`: Import Folder, Clear All Imports, import status, output hint, Book
    navigator.
  - `2. Book Settings`: Shared over Current Book. Current Book holds the five fields, artwork, and
    the Book-only Title / Series Part / Output Filename / Status row.
  - `3. Tracks, Chapters & Build`: the track list beside Chapter Titles, then the run options,
    then Build and the shared job area.
  - Activity below, with Summary | Detailed and Clear Log.
- **Shared vs Current Book:** the same `shared_labelframe` / `labelframe` treatment as the MP3 Tool,
  in Light and Dark.
- **Build** is the tool's one run action. It uses the compact button with the restrained accent
  outline (`default="active"`), and no button is a filled primary.
- **Theme:** the whole interior uses the shared compact bundle through a new `appearance_bundle`
  seam. `theme` supplies only the aqua composition hints. A live toggle recolors the track list,
  Chapter Titles, the log panes and the Book selector's drop-down in place; nothing is rebuilt.
- **Small windows:** the same measured **tight density** (the §1 order: padding and chrome, then
  reflow, then one-row/one-line floors held by `rowconfigure(minsize=...)`). Also carried over:
  the left-eliding output hint, and the §4 track-list shortcuts, which now exist on the Maker and
  go through the run lock.

Rulings taken within the maintainer's instructions, where the Maker differs from the MP3 Tool:

- **The compact default puts the Book-only row full width beneath the artwork** (`"wide"`, aqua's
  arrangement since v0.6.4 Phase 13). Beside the artwork, Title / Series Part / Output Filename /
  Status widened the five field columns past the 920×600 content width. Title is 12 characters
  and stretches.
- **The job status sits beside the job controls in the tight density.** The Maker has one more
  run row than the MP3 Tool: its options (series numbering, FAST, custom destination). At 920×600
  the MP3 arrangement (controls over a two-line status, 65 px beside a 25 px Build) left Activity
  ~28 px short. Tight now puts the status view's two lines beside Pause/Resume/Cancel/Retry
  Failed, with a 110 px bar and a 150 px status wrap, so the area is 38 px. These are grid
  positions only, on the same widgets and variables. Regular is the adapter's own layout.
- **Two run options take a short wording in the tight density:** "Start Part:" and "Try FAST
  first". This follows the MP3 Tool's "Mixed" precedent. Everywhere there is room they read
  "Start Part (blank → 1):" and "Try FAST first (auto-fallback to Safe)". The variables, controls
  and meaning are unchanged, and "Choose custom destination" keeps its pinned label.
- **In the tight density the custom destination's path row joins the options line** (beside its
  toggle) instead of adding a line beneath. At 920×600 every flexible region is already at its
  floor, so an extra line pushed Activity off screen. With room, the path row stays beneath. It
  is still hidden until the toggle is on (Decision 10A). Showing or hiding it re-measures the
  density and row floors. The options line grows only by the Browse button's extra 4 px.
- **The artwork preview is at most 40 px** (the MP3 Tool's Phase 6 value), so choosing artwork
  never grows Book Settings. The Maker's `ArtworkControl` is shared with the Metadata Editor, so
  this is an additive, opt-in `preview_max` argument (`COMPACT_PREVIEW_MAX`). The shared default
  `PREVIEW_MAX` (56 px) and the Editor are unchanged until Phase 8.
- The Start Part entry is 4 characters (was 6), and the option gaps are 8 px. Both are needed to
  fit the options line at 920×600 in the regular wording.

**Deliberately unchanged:**

- the multi-Book import/workspace model and Shared precedence (`disabled_fields`);
- series numbering (Auto-number Series Part disables the manual Series Part; Start Part), FAST/Safe;
- the custom destination (off on every fresh build, never persisted, Decision 10A);
- artwork validation, metadata, chapter titles, output naming and collisions;
- Pause/Resume/Cancel, Retry Failed, the frozen run state and source immutability.

`m4b_maker_workflow.py`, `m4b_maker_plan.py`, `m4b_maker_batch.py`, `m4b_maker_processing.py` and
every `shared/` module are untouched. The track-list labels (Add Files / Move Up / Move Down /
Remove Selected) and the workspace-level Import Folder / Clear All Imports are kept for the same
reason as the MP3 Tool's (§4's per-list Add Folder / Clear All would duplicate workspace actions).

**Known minor (shared, as the MP3 Tool):** at 920×600 a long Book name is truncated in the
navigator's heading; the selector beside it shows the name whole.

**Consequences:** the plan gains a Phase 7 note and `Handoff.md` records the checkpoint. Tests that
pinned the Maker's `ACT.*` styling were moved to the compact system:
- `test_m4b_maker_ui.py`: the compact-style test, and the aqua tests now pass a darwin bundle and
  pin the compact default composition;
- `test_launcher_smoke.py`: the Maker moves to `COMPACT_DENSE_TOOLS`;
- `test_clear_all_imports.py`, `test_output_location_refresh.py` and
  `test_prototype_regression.py`.

The M4B Metadata Editor is now the one remaining `ACT.*` panel, until Phase 8. Version identity
remains `0.6.2`, unreleased. Phase 8 is not started.

— Recorded by Claude Code on the maintainer's Phase 6 approval and Phase 7 instruction, 2026-09-28.

---

## 2026-09-28 -- Phase 5 approved; MP3 Tool rebuilt to the compact Family-B hierarchy (Phase 6), with a measured tight density for the launcher's small windows

**Phase 5 approved.** The maintainer approved the Phase 5 documentation checkpoint (`bc52a05`).

**Phase 6 (MP3 Tool compact visual standardization).** The MP3 Tool was the dense multi-Book panel
still drawn in the retired oversized `ACT.*` interior. Measured inside the real launcher at
920×600 (content 721×457), it asked for 1032×635:

- the track list, the Chapter Titles box and the log collapsed to 1 px;
- Remove Book and Retry Failed were cut off.

Its presentation is rebuilt on the approved Cover/TTS/Converter control language, through the
shared `appearance`/`job_ui` primitives only. There is no MP3-specific visual system:

- **Hierarchy:** `1. Import & Books` (Import Folder, Clear All Imports, import status, output hint,
  Book navigator) / `2. Book Settings` (Shared over Current Book) / `3. Tracks & Run` (track list |
  Chapter Titles, then the operations and the shared job area). Activity (Summary | Detailed,
  Clear Log) is below, at full width, never beside.
- **Shared vs Current Book:** Shared uses the shared palette's `shared_labelframe` treatment, the
  same in Light and Dark: a restrained cool tint (chroma ≤ 0.1), a stronger blue border and a bold
  blue heading, captioned "Shared — applies to every Book and overrides its own value". Current
  Book uses the ordinary section surface and border.
- **Operations:** Write ID3 Tags and Combine MP3s are two run actions of equal rank. Both take the
  compact button with ttk's restrained accent outline (`default="active"`, the Start/Resize/Convert
  treatment). Two filled blue buttons would be two competing "primary actions" (§5).
- **Theme:** the whole interior takes the shared compact bundle through a new `appearance_bundle`
  seam, like the Family-A tools'. `theme` now supplies only the composition hints, so the accepted
  aqua arrangement is unchanged. A live toggle recolors the classic Tk widgets in place (track
  list, Chapter Titles, log panes, the Book selector's drop-down). Nothing is rebuilt.

Rulings taken within the maintainer's instructions:

- **A measured tight density for the real launcher's small content areas** (920×600 and 1024×720).
  Where the regular density would squeeze a flexible region below its floor, §1's steps apply in
  order. Every control stays at its full requested size, and the minimum size is unchanged:
  - less padding and chrome: section/group padding and gaps tighten, and the run separator and
    Activity's explanatory note step aside;
  - then a reflow: Clear Log moves beside the Summary | Detailed view, and the shared job status
    takes two lines instead of three;
  - only then the lower floors: the track list gives way to one row and the log to one line (§3
    lets Activity shrink before a setting does).

  Tracks & Run and Activity carry measured row minimum sizes, so a short window can never squeeze
  the buttons or job area inside them.
- **Auto-number / Start # / Status share the mixed-marker row**, under Time and Artwork: the two
  columns no marker uses. This makes Current Book one row shorter. The aqua arrangement keeps them
  on their own row.
- **The mixed-source marker reads "Mixed" in the tight density.** "Mixed source metadata" stays
  everywhere there is room. At the minimum a field column is ~60–125 px, so the full wording either
  widened its column (squeezing every Current Book label) or wrapped taller (pushing Activity off
  screen). The marker keeps the same place, style and meaning.
- **The output hint shows the path's tail.** ttk clips an overlong label from the right whatever
  its anchor, which hid the run folder. The label now elides from the left ("…\MP3-Tool-Outputs");
  `var_outdir` keeps the whole path.
- **The artwork preview is at most 40 px,** the height of the control's caption and buttons, so
  choosing artwork never makes Book Settings grow. It is still display-only.
- **Fixed, not reopened: the §4 track-list shortcuts now obey the run lock.** Phase 2 bound
  Delete/BackSpace/Alt+Up/Down straight to the move/remove methods, so while a run locked the four
  track buttons the keys could still edit the list. They now pass through the same lock. No MP3
  workflow decision changed.

**Deliberately unchanged:**

- **Behaviour:** multi-Book import/workspace behaviour, Shared precedence, chapter titles, artwork,
  signed Time, Write ID3 Tags, Combine MP3s, FAST/Safe, numbering, output planning/collisions,
  Pause/Resume/Cancel/Retry Failed, frozen run state and source immutability. No engine, plan or
  workflow file changed.
- **Track-list labels:** Add Files / Move Up / Move Down / Remove Selected keep their accepted
  labels. Folder import stays workspace-level (`Import Folder`, Section 1) and Clear All stays
  `Clear All Imports`. §4's per-list "Add Folder" and "Clear All" would each duplicate those
  workspace actions per Book, so they genuinely do not apply here.

**Known minor:** at 920×600 a long Book name is truncated in the navigator's heading. That label
belongs to the shared navigator; the selector beside it, and its drop-down, show the name whole.

**Consequences:** the plan gains a Phase 6 note and `Handoff.md` records the checkpoint. Tests that
pinned the MP3 Tool's `ACT.*` styling were updated to the compact system:
`test_mp3_tool_ui`, `test_launcher_smoke`, `test_clear_all_imports`,
`test_output_location_refresh` and `test_prototype_regression`. The M4B Maker and Metadata Editor
remain `ACT.*` until Phases 7–8. Version identity remains `0.6.2`, unreleased. Phase 7 is not
started.

— Recorded by Claude Code on the maintainer's Phase 5 approval and Phase 6 instruction, 2026-09-28.

---

## 2026-09-28 -- Phase 4 approved; Phase 5 (Cover Image guided layout) recorded as SATISFIED by the approved Phase 2 remediation

**Phase 4 approved.** The Windows manual M4B Converter gate at `cfe0678` passed. It covered:

- Light and Dark;
- the responsive small-window (`split`) layout;
- the metadata modes (fields disabled only under Write none);
- the approved Cover/TTS visual language.

Phase 4 is maintainer-approved and closed.

**Phase 5 is satisfied, not re-implemented.** Under the 2026-09-28 sequencing override, Cover's
Family-A conversion and its Windows manual gate were completed and approved as the final Phase 2
remediation (`39352c7`, gate PASSED). Phase 5 re-checked that checkpoint against its own
requirements at `cfe0678` and found no gap:

- `1. Sources` / `2. Resize Options` / `3. Output & Run` with Activity on the right.
- Details / List / Medium Thumbnails are kept as the source-browser views.
- The compact Cover/TTS control language and coherent Light/Dark are in place.
- There is no core-panel scrolling; this is proved in the real launcher shell by
  `test_cover_layout.py`.
- The image, HEIC, output and job behavior is preserved.

The only shared-code change since `39352c7` is Phase 3's `appearance.py` addition: the combobox
drop-down helper and the `Link.TLabel` surface. Cover uses neither. Phase 4 changed no shared
module. The focused Cover, import, image, job, theme, layout, launcher and boundary suites passed
(16 files: 965 passed, 4 environment-only skips, 0 failed). `cover_resizer.py` is unchanged: nothing
was redone or cosmetically altered to create Phase 5 work.

macOS 1024×800 and Windows 125% remain Phase 9's.

— Recorded by Claude Code on the maintainer's Phase 4 approval and Phase 5 instruction, 2026-09-28.

---

## 2026-09-28 -- Phase 3 approved; M4B Converter rebuilt to the Family-A guided layout (Phase 4); its Plan-5 byte pin retired

**Phase 3 approved.** The Windows manual TTS gate at `d03a7aa` passed in Light and Dark, maximized
and at the small supported size. The responsive small-window TTS arrangement (`split`: 1 over 2 on
the left, 3 over Activity on the right) is approved and is now precedent for any Family-A tool whose
vertical workflow cannot fit the real launcher's small content areas.

**Phase 4 (M4B Converter guided layout).** The Converter's presentation is rebuilt on the approved
Cover/TTS interiors. There is no Converter-specific visual system:

- **Layout:** `1. Sources` / `2. Conversion & Metadata` / `3. Output & Run` on the left, Activity on
  the right.
- **Theme:** the whole interior takes the shared compact Light/Dark bundle.
- **Section 2:** Output structure (Whole book / Split by chapter) is the first, heading-weight row,
  above quality, the metadata mode, the four fields and auto-numbering.
- **Small windows:** the TTS precedent applies. At 920×600 and 1024×720 in the real launcher
  (content areas 721×457 and 825×577) the Converter uses `split`. At 1280×900 and larger it uses the
  vertical workflow with Activity beside it.

Three rulings taken within the maintainer's instructions:

- **The four metadata fields are disabled only under Write none.** They stay visible and in place
  in every mode. The instruction was "visible and disabled when not applicable". Preserve is *not*
  "not applicable": `m4b_metadata.whole_book_tags`/`segment_tags` let a filled field override the
  source's own value in Preserve. So only Write none, which writes nothing, disables them. A run in
  flight keeps them disabled, as before. Typed text is kept, and `read_options` reads it exactly as
  before. No metadata semantics moved.
- **The raw "Log" box became Activity's Detailed pane.** The ffmpeg command lines, per-file lines
  and error text keep flowing to the same place in the same order, now Activity's Detailed pane.
  The FFmpeg status line and the run's closing line reach Summary too, which is Cover's `log_write`
  contract. Summary is still the adapter's own projection of the run's events; the panel adds only
  those two lines.
- **The Plan-5 byte pin on `m4b_converter.py` is retired**, exactly as the MP3 Tool, M4B Maker and
  Metadata Editor pins were:
  - `PHASE0_PLAN5_HASHES` is now empty.
  - The Phase 0 digest is kept as `CONVERTER_PHASE0_HASH`.
  - A new test requires the file to differ from that digest *and* to be the real compact adopter.
  - The pin's purpose ("the promotion left the Converter alone") is still proved structurally: the
    Converter defines no numbering implementation of its own.
  - The pin was recorded as "a stop gate, not a value to update". It is retired, not updated,
    because this phase's instruction is precisely to rebuild that file's presentation.

**Why:** the Converter was the last Family-A tool drawn in classic widgets in one tall column. In
Dark it was a light island, and inside the real launcher's minimum content area its run area and
logs were squeezed. The approved Cover/TTS language and the approved small-window precedent solve
both without touching a single conversion rule.

— Recorded by Claude Code on the maintainer's Phase 3 approval and Phase 4 instruction, 2026-09-28.

---

## 2026-09-28 -- Phase 2 approved; the approved Cover Image UI at `39352c7` is the concrete visual reference for every remaining tool interior; TTS keeps its frozen layout, with Activity kept on the right in the real launcher's small windows

**Phase 2 approved.** The final Cover Image manual gate at `39352c7` passed in Light and Dark. It
covered the Family-A layout, right-side Activity, compact controls, no core scrolling and a working
resize run. Phase 2 is maintainer-approved and closed.

**Ruling: the approved Cover Image UI is the concrete visual reference.** Every remaining
tool-interior conversion uses the same compact visual language as Cover at `39352c7`: control sizing,
button/field treatment, check/radio indicators, section borders, spacing and density, disabled
states, Light/Dark treatment, and Activity presentation. Layout geometry may differ only where the
active plan explicitly distinguishes Family A from Family B. No tool gets its own visual system;
everything goes through `shared/appearance.py` and the shared `job_ui` components.

**Phase 3 (TTS reference conformance) applied that language to TTS.** The panel was the one tool
interior still drawn entirely with native widgets, a bright island in the Dark shell. Every widget
it owns, and every shared component it hosts, now takes the same `Compact.*` styles and bundle Cover
uses. Captions take palette roles instead of fixed navy/orange/red/gray. The combobox drop-down lists
and the Activity panes follow live toggles. Two shared-primitive changes follow:

- `appearance.style_combobox_popdown` colors a compact combobox's drop-down list, a classic Tk listbox
  that no ttk style reaches.
- The compact `Link.TLabel` role, used by nothing before, sits on the section surface in the body font
  like its sibling caption roles.

No text, voice, engine, worker, job, retry or output behavior changed.

**Ruling: TTS in the real launcher's small windows.** TTS's layout is frozen:
`1. Sources` / `2. Voice & Audio` / `3. Output & Run` with Activity on the right. Measurement showed
the v0.6.5 small-window behavior never actually held inside the launcher:

- The suite sized a bare 920×600 toplevel, but the launcher's sidebar and header leave the panel
  721×457 at 920×600 and 825×577 at 1024×720.
- There, the vertical workflow's floor alone is 645 px, and its "Activity beneath" fallback needs
  about 550 px.
- So Start, the job controls and Activity sat below the visible area at both sizes.

Asked for a ruling, the maintainer chose **1 over 2 on the left, 3 over Activity on the right**
(`split`) wherever the vertical workflow cannot fit.

- At 1280×900 and larger, the frozen geometry is unchanged pixel for pixel.
- In `split`, the frozen contract's own tight-window steps (§1) apply, and nothing is hidden or
  removed:
  - vertical section padding and in-section gaps tighten;
  - Sources' six actions take two rows of three;
  - the job controls take two rows of two, and the read-only path field asks for fewer characters.
- The imported list is the region allowed to give way: down to one row in `split`, and only when
  Kokoro's notice needs the height.
- `stacked` (Activity beneath) remains only as a last resort for a panel too small even for `split`.

**Why:** a tool that is a white island in Dark, or whose Start button sits off screen at the
supported minimum, fails the frozen contract however faithful its geometry is. Keeping the frozen
layout wherever it fits, and choosing the smallest change that keeps Activity on the right
everywhere else, respects both rulings.

**Consequences:** the plan gains a 2026-09-28 Phase 3 note, and `Handoff.md` records the checkpoint.
Four v0.6.5 layout tests that pinned "Activity beneath at 920×600" were updated to the ruled geometry.
`test_launcher_smoke.py` now separates the shell chrome (still `ACT.*` only) from the hosted tool
interior (`ACT.*` or `Compact.*`, never generic). Version identity remains `0.6.2`, unreleased; no
merge, tag, package or release. Phase 4 is not started.

— Recorded by Claude Code, 2026-09-28, on the maintainer's Phase 3 instruction and small-window ruling.

---

## 2026-09-28 -- Sequencing override: Cover Image's Phase-5 Family-A conversion completed now as the final Phase 2 remediation; "TTS-like" means TTS's actual control language, expressed through the shared compact primitives

**Decision (v0.6.6 Phase 2 remediation, maintainer override).** The Phase 2 repeat manual gate on
`5e41f9d` failed on Cover Image presentation/layout. Dark coverage passed and every tested function
still worked. The maintainer ruled:

- **TTS is the exact visual-control reference, not a color reference.** Matching it means TTS's real
  control metrics and treatment: button size/padding/borders/font, field sizing, check/radio sizing
  and glyphs, label sizing, LabelFrame sections, separators, gaps, disabled appearance,
  primary-action emphasis, density. This is done through the shared `shared/appearance.py`
  primitives, not a Cover-only design system.
- **Sequencing override:** the Cover Family-A conversion assigned to Phase 5 is brought forward and
  completed now. Phase 5 must not redo it (plan file, Phase 5 note).

**What changed, measured rather than guessed.** The TTS panel draws native Windows `vista` controls
with `TkDefaultFont` (Segoe UI 9). The shared `Compact.*` catalogue drew a 10 pt font with larger
padding: Button 103×31 px vs TTS 76×25, Entry 76×25 vs 66×21. That size gap, not the colors, is
what read as "oversized". Shared-primitive fixes:

- The body font now derives from `TkDefaultFont`.
- `field_pad` (6,3)→(2,1), `button_pad` (10,4)→(2,2), `tab_pad`, `tree_row_height` 22→20. Measured
  after: Button 76×25, Entry 68×21, Combobox 63×21, Checkbutton 21 px, all matching native.
- Compact buttons use `relief="raised"`, so they keep a thin native-like outline in every state,
  including disabled. `default="active"` gets TTS's restrained accent outline.
- Check/radio indicators are small palette-drawn images (box + checkmark, ringed dot) replacing the
  `clam` X glyph. They redraw in place on a toggle.
- The Light palette now matches classic Windows: #f0f0f0 panel and sections, near-white bordered
  buttons, white fields. The accent was darkened so its WCAG bar holds against the grey surface;
  every contrast test still passes.
- The compact log pane is a white field, like TTS's.
- The section caption is the body font in text color.

**Cover Image (`mp3_tools/cover_resizer.py`), Family A:**

- **Left:** `1. Sources` holds the source browser (Details/List/Medium Thumbnails) as the flexible
  region, the six import actions, the three type filters, the three import options, and Cancel
  Import. `2. Resize Options` is fully visible, with no canvas and no scrollbar; behavior is
  unchanged. `3. Output & Run` holds the destination, **Resize Covers** as the default button, and
  the shared Pause/Resume/Cancel/Retry Failed controls and progress.
- **Right:** `Activity`, the one persistent shared Summary | Detailed view. **Clear Log** is added,
  closing the gap recorded 2026-09-27. The worker transcript goes to Detailed; the closing line is
  also shown in Summary.
- **The browser is the list** (frozen contract §4's `[list/browser]`). The shared importer's
  duplicate listbox is withdrawn from view, not destroyed. It is kept in step, so every button and
  its availability work unchanged. Delete/Backspace and Alt+Up/Down are bound on all three views.
- **Responsive and measured, like TTS:**
  - `wide`: 1/2/3 vertical beside Activity.
  - `split`: 2 beside 3 under Sources.
  - `columns`: Sources | (2 over 3) | Activity.
  - `stacked`: last resort only.

  Sources-on-top layouts are used only while the browser keeps a full thumbnail row. In the real
  launcher (content host 721×457 at 920×600), `columns` is chosen at 920×600 and 1024×720, `split`
  at 1280×900, and `wide` at 1920×1009 and above. Activity stays on the right at every size.
- **Also fixed: the `appearance` settings key.** Phase 1 wrote it without registering it as user
  state, so after any toggle every launch reported it as an unrecognised configuration override. It
  is now in `config.USER_STATE_SETTINGS`, with a regression test.

**Why:** a recolored old layout is not the same application. The TTS reference and the frozen
no-core-scroll rule are the acceptance bar, so Cover now meets both. Doing it now instead of in
Phase 5 means the shared primitives are proven on one real, fully converted panel before Phases
3/4/6/7/8 apply them.

**Consequences:** the active plan gains a 2026-09-28 clarification and a Phase 5 note; `Handoff.md`
records the checkpoint. No other tool panel was converted. The Preferences & Data dialog (Phase 1)
inherits the retuned compact metrics and Light palette automatically, as intended by one shared
system. Version identity remains `0.6.2`, unreleased; no merge, tag, package, or release.

---

## 2026-09-27 -- TTS is the visual-control reference for every tool interior, not only layout; Dark mode must theme an app-owned tool interior coherently, with no leftover native/light regions; v0.6.6 Phase 2 remediated on this ruling

**Decision (v0.6.6 -- UI Parity, Hardening & Release, Phase 2 remediation).** The maintainer's manual
gate on the original Phase 2 checkpoint (`0ab862d`) **failed**. That checkpoint had wired only the two
shared `job_ui` Activity/importer components on Cover Image Resizer to the new compact appearance
bundle, leaving every other widget on the panel -- the browser's three views, the resize-options form,
the output/action row, the panel's own run log -- classic/native. In Light that read as coherent; in
Dark it left large unstyled light/white regions inside an otherwise-Dark tool, made worse by a
thumbnail canvas literally hardcoded `background="white"` and a selection-highlight tile painted with
two hardcoded hex colors. The maintainer's ruling, now authoritative for the rest of v0.6.6:

- **TTS Audiobook is the visual-control reference for every tool interior, not only the layout
  reference** the frozen contract already named it. Every tool's compact ttk-style buttons,
  entries/text boxes, check/radio controls, labels and section treatment converge on the same
  control language TTS uses.
- **Dark mode must theme an entire app-owned tool interior coherently.** No large light/white panel
  region may remain inside a Dark tool. Partial theming -- some widgets on the compact bundle, the
  rest left native -- is exactly the defect this ruling forbids, not an acceptable intermediate state.
- **Cover Image Resizer's prior oversized/ACT-like presentation must not become the project standard.**
  The compact system's own metrics (already smaller than `ACT.*`'s -- e.g. `button_pad (10, 4)` vs
  `ACT.*`'s `(14, 7)`) were not the actual problem; a colored, bordered "card" island floating inside
  an otherwise-native panel reads as boxy/ACT-like regardless of its own padding, purely from the
  contrast with everything left unstyled around it. Full-surface coverage removes that contrast.
- The outer launcher shell remains substantially unchanged, as the frozen contract already states;
  this ruling is about each tool's own interior, not the shell.

**Remediation applied, bounded to Cover Image Resizer (the plan's Family-A/simple representative) and
the shared primitives it and every other tool already draw from:**

- `shared/job_ui.py`'s `style_tk_widget`/`bind_list_shortcuts` and the `Compact.*` catalogue in
  `shared/appearance.py` needed no changes -- both were already correct and already more compact than
  `ACT.*`. The defect was coverage, not the primitives.
- `mp3_tools/cover_resizer.py`: every widget the panel or its `CoverBrowser` builds now carries a
  `style=` resolved through `job_ui.style_name(self.appearance_bundle, ...)` -- the panel's own frame,
  the browser's `LabelFrame`/`Radiobutton`s/`Treeview`s, the resize-options form's `Spinbox`/
  `Checkbutton`s/`Radiobutton`s/`Entry`/`Label`s, the primary action button, and the panel's own raw run
  log. The thumbnail canvas's hardcoded `background="white"` and the selection tile's two hardcoded hex
  colors are gone, replaced by `job_ui.style_tk_widget(..., "field")` and the live `colors` dict. The
  destructive replacement confirmation dialog (an app-owned `Toplevel`) now takes and follows the same
  bundle. A live appearance toggle re-colors every classic Tk widget in place via a new
  `CoverBrowser.apply_appearance()` alongside the panel's own `_on_appearance_changed`, mirroring the
  Phase 1 pattern. `CoverResizerUI` gained an `appearance_bundle` constructor seam (production default:
  the real remembered setting) so the suite can inject an exact Light or Dark bundle deterministically.
- **Phase 5's own layout reorganization was explicitly not performed.** No grid/pack position moved;
  every edit only changed what a widget is styled with, per this remediation's own bound.
- Two AST-based regression tests in `files/tests/test_cover_browser.py` guard the structural half of
  this from regressing: every `style=` keyword anywhere in the module must resolve through
  `style_name(...)`, never a literal string, and no classic-widget color keyword
  (`background`/`foreground`/`fill`/`outline`) may carry a literal hex or named-color string. A new
  `files/tests/test_cover_appearance.py` proves the coherence half against a real panel built on an
  explicit Dark bundle: the panel's own background, every resize-option control, the browser's three
  views including the thumbnail canvas, the panel's run log, and the selection-tile colors all resolve
  to the Dark palette -- plus the live in-place toggle path, state preserved.

**Why:** a partially-themed panel is a worse outcome than a wholly-native one, because it reads as
broken rather than merely unconverted -- and it was specifically what the maintainer's manual gate
exists to catch before the pattern is repeated across five more tools in Phases 3/4/6/7/8.

**Consequences:** `md-instructions/0.6.6-ui-parity-hardening-release.md` gains a dated clarification
appended to its Frozen UI Contract, not a rewrite of the original text, recording this ruling as binding
on every remaining phase. `Handoff.md` records the remediation checkpoint. No other tool panel was
broadly converted by this remediation; Phases 3/4/6/7/8 apply this same clarified standard to TTS,
Converter, MP3 Tool, Maker and Metadata Editor respectively, each against its own full interior, not
only its shared components. Application version identity remains `0.6.2`, unreleased. No merge, tag,
package, or release occurred.

---

## 2026-09-27 -- Pull request #12 confirmed merged (v0.6.5 TTS Quality Refinement complete and integrated); Plan 9 reassigned to v0.6.6 as the final v0.6.x implementation plan; the frozen UI-parity contract is recorded as the active direction

**Decision (v0.6.6 -- UI Parity, Hardening & Release, Phase 0).** Fresh `git fetch origin` confirmed
`origin/master` at `f7fb762e63bc7d46d099ddc8cead2dc68fb188e0` -- the merge commit for **pull request
#12**, merging `feature/0.6.5-tts-quality-refactor` (post-remediation tip `e94a212`) into `master`.
v0.6.5 TTS Quality Refinement is therefore **confirmed merged and integrated**, superseding every
"not merged" / "integration pending" statement recorded in `Handoff.md`, this file's own 2026-09-26
entries, `Briefing.md`, and both `don't-delete` roadmap files as of the Phase 9 closeout -- those
statements were accurate when written and are not being called wrong, only overtaken by the
maintainer's subsequent merge decision. `feature/0.6.6-ui-parity-hardening-release` was created from
that verified `origin/master` (local `master` fast-forwarded `e36ab7d` -> `f7fb762` in the same
checkpoint) and pushed to `origin` with upstream tracking; Phase 0's baseline/audit work is recorded
in `Handoff.md`.

**Plan 9 is reassigned from DISPLACED to v0.6.6.** The 2026-09-18 entry below marked Plan 9 --
remaining Windows panel conversion, macOS parity, full regression, packaging and the final release
checkpoint -- as "DISPLACED -- FUTURE ALLOCATION UNASSIGNED" while the v0.6.5 identity was spent on
the unrelated TTS Quality Refinement plan. The maintainer has now opened Plan 9 as **v0.6.6**, the
final v0.6.x implementation plan: `md-instructions/0.6.6-ui-parity-hardening-release.md`, on
`feature/0.6.6-ui-parity-hardening-release`. Plan 9's full previously-approved scope carries forward
intact; nothing already approved is narrowed by this reassignment.

**Old Plan-9 deferrals were audited against the current tree before carrying them forward** (not
assumed blindly): `shared/ui_theme.py` still defines `MIN_SIZE = (920, 600)` and
`AQUA_MIN_SIZE = (1024, 800)`; no Windows DPI-awareness call exists anywhere under
`scripts/Universal/`; and `ACT.*` styling is still confined to `job_ui.py`, `mp3_tool.py`,
`book_workspace_ui.py`, `m4b_metadata_editor.py`, `m4b_maker.py`, `m4b_artwork_ui.py`,
`launcher.py` and `preferences_ui.py` -- TTS Audiobook, M4B Converter and Cover Image Resizer remain
classic, exactly as recorded. The `.DS_Store`/`Thumbs.db` packaging leak and the M4B Metadata
Editor's whole-form scroll are confirmed already discharged (`07ebbe8`, v0.6.4 Phase 10) and are
**not** re-opened as v0.6.6 scope. No global Light/Dark toggle, universal Activity component, or
universal importer/list keyboard contract exists yet anywhere in the tree -- these are genuinely new
v0.6.6 (Phase 1/2) scope, not a restatement of an older deferral.

**The frozen UI contract in the new plan is recorded as the active direction for v0.6.6:** compact
Tkinter/ttk-styled interiors project-wide; TTS Audiobook frozen as the Family-A layout reference
(Sources / Voice & Audio / Output & Run / Activity-right, no redesign); M4B Converter and Cover Image
Resizer adopt that same Family-A 1/2/3-plus-right-Activity structure; MP3 Tool, M4B Maker and M4B
Metadata Editor keep their dense multi-Book geometry (Family B) but revert to compact ttk styling
with Activity at the bottom; a global remembered Light/Dark appearance setting (`settings`, not
`config.toml`; Light is the first-run default); universal Activity and importer/list contracts; and
no core-panel scrolling at the supported Windows/macOS minimums.

**Why:** the maintainer chose to finish v0.6.5 first, confirm it merged, and only then reopen the
long-displaced Plan 9 as the final v0.6.x drop, now that its scope, layout language and UI direction
are fully specified in the new plan document.

**Consequences:** `Handoff.md`, `Briefing.md`, and both
`don't-delete/Audiobook-Creation-Tool-v0.6.x-*` roadmap files each gain a dated supersession note
recording this exact merge and reassignment, following their own existing append/supersede
conventions; no prior dated text in any of them is rewritten. Application version identity remains
`0.6.2`, unreleased -- this checkpoint authorizes no version bump, tag, package, release, or merge
to `master` beyond the already-completed PR #12. No production code changed in this checkpoint.

**Focused validation:** `git diff --check` clean; documentation/repository-contract review only, no
full `verify.py` run (no production code touched).

-- Decided by maintainer (Elijah Matthew), recorded by Claude Code, 2026-09-27

---

## 2026-09-26 -- A fresh independent review of pull request #12 found six confirmed, bounded correctness gaps; all six closed before merge

**Decision:** Six confirmed findings from an independent read-only review of
pull request #12 (`feature/0.6.5-tts-quality-refactor` -> `master`, reviewed at
head `8094135`) are fixed, each with a direct regression test. Two cleanup-only
findings from the same review (the concurrency-cap-to-1 stopgap already
documented in code comments, and a handful of dead-code/duplication items) were
explicitly deferred, per the maintainer's bounded remediation scope, and are
not touched here.

**1. M4B Metadata Editor: `validate_staged` no longer requires the original
source to still exist on a Retry Failed reusing an already-validated
candidate.** The Editor's chapter-truncation guard (`validate_chapter_structure`,
added against the 2026-09-20 FFmpeg 9 defect) had `validate_staged` re-read
`book.source` on every call, including the retained-candidate reuse path a
publication-failure retry takes. A candidate already proved against the source
once does not need the source proved again; `validate_staged` and
`validate_chapter_structure` (`mp3_tools/m4b_metadata_processing.py`) now take
`require_source_match` / a nullable `source`, and `m4b_metadata_batch.py`
passes `False` exactly when reusing an already-validated retained candidate
(both the reuse check and, when Auto-number is on, the tag-rewrite
re-validation that follows it). New regression: publication failure -> the
candidate is retained -> the source file is deleted -> Retry Failed still
publishes it (`test_m4b_metadata_batch.py`).

**2. Edge's "Effective workers" log line is now truthful for direct-item
queues.** `epub2tts_edge.runner._CWD_ISOLATION_LOCK` fully serializes every
direct Edge conversion against every other direct Edge conversion (folder-
derived Edge items carry no such lock and freely overlap). The single shared
`ThreadPoolExecutor` size and its log line, however, were computed from
`resolve_effective_workers(requested, queued_files, backend)` alone, so an
all-direct-Edge queue reported an "Effective workers" figure implying real
parallelism that the lock never delivered. `resolve_effective_workers` now
takes `direct_files`, and for Edge caps the result to `folder_files + 1` (any
number of folder items can overlap each other and the one direct item that
can run alongside them; a second direct item can never make progress
concurrently, so it cannot widen the cap) -- an all-direct queue now correctly
resolves to `1` regardless of the request. New regressions, pure-function and
panel-level, for an all-direct queue and a mixed direct+folder queue
(`test_tts_worker_concurrency.py`); two pre-existing panel-level tests that
had asserted the old, untruthful figure for an all-direct queue now use a
folder-only queue instead, preserving their original "oversized request
degrades safely" intent.

**3. `shared.metadata._chapter_track_samples` no longer substitutes an
unrelated stream's frame count.** It preferred the `codec_tag_string=="text"`
data/subtitle stream but silently fell through to try any other data/subtitle
stream's `nb_frames` if the preferred one's count did not parse -- capable of
feeding the truncation check a different track's sample count entirely. It
now considers only the preferred stream(s) when any exist, returning `None`
(fail-closed, which `validate_chapter_structure` already turns into a raise)
rather than trying an unrelated stream. New regressions covering a missing/
non-numeric count on the real track beside an unrelated stream with a
parseable one, and the pre-existing older-build (untagged subtitle) fallback
path (`test_metadata_smoke.py`).

**4. `trim_from_end_mp3` no longer treats an unreadable duration as
zero-length.** `ffprobe_duration_seconds(in_mp3) or 0.0` silently produced
`-t 0.000000` (a near-empty output) while still returning `True`, the one
call site in `mp3_processing.py` that was not updated when every other call
site was made to fail on `None`. It now fails safely (logs and returns
`False`) instead. This function has no live GUI call site today (dead but
exported); it is fixed in place and not wired into the GUI. New regression in
`test_mp3_duration_authority.py`.

**5. The direct-Edge `_CWD_ISOLATION_LOCK` proof in
`test_tts_worker_concurrency.py` no longer depends on a fixed sleep.** It
previously inferred the lock held by sleeping 300 ms and checking that a
second thread never got inside the stubbed `read_book` -- a contended CI
runner could pass this by the second thread simply never being scheduled in
time, not by the lock actually holding it out. It now wraps the real lock in
a small acquire-counting substitute and waits (bounded, not sleeping) for
proof that the second thread genuinely reached (attempted) the lock before
asserting -- deterministic either way, and faster in practice.

**6. A missing edge case in the structural-colon regex's own test coverage
was filled in.** `chatterbox_synth._STRUCTURAL_COLON` (`:(?!\S)`) treats a
colon at the literal end of a string as prose, same as one followed by
whitespace, but every existing parametrized case had a colon followed by
more text -- a future narrowing of the pattern (e.g. requiring an actual
trailing whitespace character) would have passed every existing test while
silently breaking end-of-string prose colons. New case in
`test_chatterbox_colon_integration.py`.

**Why:** the maintainer commissioned a fresh, independent review of PR #12
specifically to not assume the prior integration-readiness verdict was
correct; it found these six issues with concrete failure scenarios (a
retry regression, a misleading log figure, a silent wrong-stream substitution,
a silent zero-length trim, a spuriously-passable test, and an uncovered regex
branch) and asked for a bounded fix of exactly these, nothing else.

**Alternatives considered:** leaving finding #4 wired into the GUI while
fixing it (rejected -- out of the review's and the maintainer's stated
scope: `trim_from_end_mp3` stays a dead-but-safe export); retuning the
Kokoro/Chatterbox concurrency caps or removing the dead candidate-evaluation
code the same review flagged (rejected -- the maintainer explicitly scoped
those out as cleanup-only, not confirmed correctness bugs).

**Verification:** every new/updated test passes in isolation and as part of
a full sweep of every affected test file (494 passed); `scripts/verify.py`
run once at the end.

— Root-caused and implemented by Claude Code per the maintainer's bounded
post-review remediation request, 2026-09-26

---

## 2026-09-26 -- Kokoro's multi-file worker cap was never actually proven safe; lowered to 1, matching Chatterbox's existing correctness-constraint precedent

**Decision:** `epub2tts_gui.KOKORO_BACKEND_SAFE_WORKERS` lowered from `8` to `1`.
A v0.6.5 Phase 9 fresh independent review of the complete TTS flow (P14 worker
capping/intra-file serialization/resource safety, per the plan's Phase 9
charter) found that Kokoro's multi-file concurrency was never actually proven
safe, only assumed so from device capacity. `kokoro_synth._get_pipeline`
caches exactly one `KPipeline` per lang_code, and every production voice of
that language shares it (lang "a": af_heart/af_bella/am_michael; lang "b":
bf_emma/bm_george). That shared pipeline's out-of-vocabulary G2P fallback
(`misaki.espeak.EspeakFallback`, used by every English voice) calls
`phonemizer.backend.EspeakBackend`, whose own vendored source
(`phonemizer/backend/espeak/api.py`) states outright that the underlying
espeak-ng library is "not designed to be wrapped nor to be used in
multithreaded/multiprocess contexts (massive use of global variables)" --
true of one instance's own calls, not just of two different instances
colliding (the per-instance private `dlopen` copy that module already takes
solves the latter, not the former). Any out-of-vocabulary word -- a real
book's proper nouns, foreign terms, invented names -- reaches this fallback,
so two Kokoro files converting at once could race the same shared,
non-reentrant third-party C library. The Phase 6 "overlap proof" this cap
originally rested on (`test_tts_worker_concurrency.py`, see the 2026-09-21
entry below) only proved the `ThreadPoolExecutor` dispatches concurrently,
with `kokoro_file_to_mp3` stubbed out entirely -- it never exercised the real
pipeline, so this hazard was never actually ruled out despite the comment
beside the old constant claiming Kokoro's ceiling was "a sanity limit," not a
correctness one.

Kokoro's cap now follows the exact precedent already established for
Chatterbox in the same Phase 6 entry below: capped to a truthful `1` until a
concrete isolation proof (a pipeline instance per worker, or a lock scoped to
the G2P call) is done for real, rather than assumed. `resolve_effective_workers`
needed no change -- `KOKORO_BACKEND_SAFE_WORKERS` is exactly the seam Phase 6
already built for this. The previously-positive Kokoro overlap test in
`test_tts_worker_concurrency.py` is rewritten as a negative (non-overlap)
proof, mirroring the pre-existing Chatterbox test line for line.

**Why:** the plan's own P14 principle is general, not backend-specific:
"never obtain concurrency by racing shared state." It was applied rigorously
to Chatterbox at Phase 6 (a real investigation of `model.conds` mutable
state) but never to Kokoro, whose ceiling was set from CPU headroom alone.
Phase 9's explicit charter is to fresh-review exactly this kind of
worker-capping/resource-safety claim rather than trust the prior phase's own
account of it.

**Alternatives considered:** a lock scoped only around the G2P/`pipeline()`
call, preserving concurrent model-inference time across files while
serializing just the unsafe step (rejected for now -- a real fix, but a
larger and less-tested seam than this bounded phase justifies; left as the
documented path for a future isolation-proof phase, P11); giving every
worker its own `KPipeline` instance (rejected -- multiplies the ~300+ MB
per-language model footprint by the worker count for a backend already
capped for a decade-old sanity reason, disproportionate for an unconfirmed
hazard, P14); leaving the cap at `8` since no corruption had yet been
observed in practice (rejected -- the plan's own standard for this exact
class of hazard, already applied to Chatterbox, is proof of isolation before
raising a cap, not absence of an observed incident).

— Root-caused and implemented by Claude Code per the v0.6.5 Phase 9
fresh-review charter, 2026-09-26

---

## 2026-09-26 -- Ratification: the Kokoro worker-cap fix above is confirmed by the maintainer's live Phase 9 closeout smoke/listening gate

**Decision:** No new decision -- this entry ratifies the entry immediately
above with live evidence, per P6/P7's requirement that a human listening/
manual gate closes a fix before it is treated as final, not merely an
automated-gate pass. The maintainer ran the Phase 9 closeout manual gate on
real hardware and reported PASS at
`ee6c2b712a845f68e0106d219a803b313805ed88`: Kokoro, two files sharing a
language queued at Workers=4, logged `Requested workers: 4 | Effective
workers: 1` (the new cap took effect as intended) and both files completed
and passed listening; Edge, two files queued at Workers=4, logged
`Effective workers: 2` and both passed listening; Chatterbox, two files
queued at Workers=4, logged `Effective workers: 1` (its pre-existing cap)
and both passed listening. Edge and Chatterbox were untouched this phase --
their results confirm no regression, not new evidence of a fix.

**Why:** closes the one confirmed release blocker found by the Phase 9
fresh review with the mandatory human gate, satisfying the plan's
Definition of Done (§18).

— Ratified by the maintainer; recorded by Claude Code, 2026-09-26

---

## 2026-09-24 -- The shared Tk test root's reset must undo process-wide state, not just widget state; a full-suite-only test failure is investigated to its real cause before it is accepted as environmental

**Decision:** `files/tests/tk_gate.py`'s `_reset_root` -- the boundary that is
supposed to return the one shared Tcl interpreter every GUI test file uses to
"the state a freshly created one would be in" -- was missing two pieces of
**process-wide, not per-widget** state: `wm minsize` and `ttk.Style`'s active
theme. Both are set by real, existing tests (`test_m4b_layout.py`/
`test_mp3_tool_layout.py` set minsize to `ui_theme.AQUA_MIN_SIZE` to exercise
the real aqua floor; any test that calls `ui_theme.apply_theme(root, style,
platform="win32")` to render the Windows bundle on this Mac switches the real
theme to `clam`), and neither was ever reversed. `_reset_root` now resets
both at every module boundary: `root.minsize(1, 1)` (own `try`, since a
stand-in root in `test_tk_gate.py` may not implement it) and
`ttk.Style(root).theme_use(_NATIVE_THEME)`, where `_NATIVE_THEME` is captured
once in `shared_root`, before any module can have changed it.

The minsize leak was the actual, sole cause of two `scripts/verify.py`
failures in `test_tts_compact_ui.py`
(`test_the_minimum_window_stacks_and_large_windows_use_two_columns`,
`test_the_log_grows_substantially_on_larger_windows`) that reproduced only
inside the full ~7600-test suite, never standalone or in a small subset.
Confirmed by reading the toplevel's *actual* geometry at the point of
failure -- `920x600` was requested, `1024x800` was measured -- rather than
trusting the panel's own measured widths, which were entirely ordinary. The
theme leak is real and independently confirmed (manually switching themes
measurably changes a live panel's section widths) but was confirmed, once
isolated, **not** the cause of these two specific failures; it is fixed
anyway because it is the same class of contract violation and would
eventually cause a real, harder-to-diagnose one.

**Why:** the maintainer's instruction was explicit -- root-cause the
suite-order/state contamination or the genuine test defect; do not skip,
weaken, or mark flaky. A test that only fails inside the full suite is not
automatically "environmental noise" to route around; here it was two
concrete, fixable defects in shared infrastructure, found by bisecting the
full suite down to a 70-file, ~105-second reproduction and then reading real
window/interpreter state at the exact failure point instead of guessing from
correlation (an earlier hypothesis -- font/DPI scaling drift -- was
investigated and ruled out for lack of any code path that touches it).

**Alternatives considered:** accepting the two `test_tts_compact_ui.py`
failures as a known full-suite-only flake and marking them
`xfail`/`flaky`/skip (rejected -- the maintainer explicitly ruled this out,
and it would have hidden a real defect that could affect any other module's
geometry-dependent test, not just this one); fixing only inside
`test_tts_compact_ui.py` (e.g., forcing its own toplevel's minsize down
before each geometry assertion) (rejected -- the defect is in the shared
reset boundary every GUI test file relies on, and every other module has the
identical exposure; a local workaround here would have left the same trap for
the next module that happens to run after an aqua-floor or Windows-bundle
test).

— Root-caused and implemented by Claude Code per maintainer instruction,
2026-09-24

---

## 2026-09-24 -- The release packager never excluded macOS/Windows folder-metadata artifacts, and the archive-completeness test hand-copied its exclusion rules instead of importing them

**Decision:** `scripts/Universal/shared/release.py`'s `_is_excluded` gained
`EXCLUDED_FILE_NAMES = {".DS_Store", "Thumbs.db"}`. Both are gitignored (never
committed) but a real dev checkout is not guaranteed free of them at
packaging time -- a real Mac checkout that had simply been browsed in Finder
shipped `scripts/.DS_Store` in the real archive before this was caught
(`test_release_packaging.py::test_no_developer_or_runtime_state_leaks`,
building from the real repository, not a synthetic one). Separately,
`test_the_scripts_tree_is_complete` had hand-copied `release.py`'s exclusion
sets as its own literal `{".venv", "__pycache__", ".pytest_cache"}`/
`{".pyc", ".pyo", ".pyd"}` rather than importing `release.EXCLUDED_DIR_NAMES`/
`EXCLUDED_SUFFIXES` -- exactly how this test stayed green while the real
packager's exclusion list was already incomplete. It now imports all three
exclusion sets (`EXCLUDED_DIR_NAMES`/`EXCLUDED_SUFFIXES`/`EXCLUDED_FILE_NAMES`)
from `release.py` directly, and the synthetic `fake_repo()` fixture plants a
`.DS_Store`/`Thumbs.db` so this exact regression is caught by the fast
synthetic test even on a checkout that happens to be clean right now.

**Why:** found investigating a `scripts/verify.py` FAIL the maintainer asked
to be root-caused, not skipped. A hand-duplicated copy of another module's
constants is a durable staleness risk on its own, independent of this
specific bug -- the two are meant to be redundant descriptions of the same
rule, and only one of them was ever exercised against a real folder-metadata
artifact.

**Alternatives considered:** deleting the stray `.DS_Store` and calling the
test suite clean again (rejected -- the underlying gap in the real packager
would remain, and any future Mac checkout would reproduce it); leaving
`test_the_scripts_tree_is_complete`'s exclusion set hand-copied and just
adding `.DS_Store`/`Thumbs.db` to it separately (rejected -- keeps the exact
staleness risk that let this go undetected, for no benefit over importing the
one real source of truth).

— Root-caused and implemented by Claude Code per maintainer instruction,
2026-09-24

---

## 2026-09-24 -- A new module-global tied to the shared Tk root's lifetime must be added to every fixture that already snapshots/restores that lifetime, not just to the root's own reset

**Decision:** `test_tk_gate.py`'s `_no_shared_root_leaks` autouse fixture nulls
`tk_gate._SHARED_ROOT` before most of its own tests (so a `FakeTk`-based test
builds its own throwaway root without disturbing the real one) and restores
the real root afterward. It predates `_NATIVE_THEME` (added this session, see
the sibling entry on the minsize/theme reset gaps) and never saved or
restored it, so a `FakeTk`-based test's own `shared_root()` call captured
`_NATIVE_THEME` from the fake -- which fails, leaving it `None` -- and that
corruption outlived the fixture's restore, because `_SHARED_ROOT` never
becomes `None` again afterward for `shared_root`'s "capture once, only when
`_SHARED_ROOT` is `None`" guard to retry against a real root. The fixture now
saves and restores `_NATIVE_THEME` in the identical save-null-restore shape
it already uses for `_SHARED_ROOT`.

**Why:** found by the new regression test for the theme-reset fix itself
failing inside the full suite (not in `test_tk_gate.py` alone), bisected to a
140-file reproduction. The general rule this confirms: any state whose
lifetime is tied to `_SHARED_ROOT` -- present or future -- needs the same
save/restore treatment in this one fixture, or a `FakeTk`-based test in this
file becomes a second, independent way to leak state into the real suite,
exactly the class of defect `tk_gate.py` exists to prevent.

**Alternatives considered:** having `shared_root()` retry the capture on
every call rather than only when `_SHARED_ROOT is None` (rejected -- would
re-run it needlessly on every real-Tk module for no benefit, and does not fix
the actual gap: the fixture is the one place that already knows it is
temporarily substituting a fake root and must be the one to protect
everything tied to that substitution).

— Root-caused and implemented by Claude Code per maintainer instruction,
2026-09-24

---

## 2026-09-24 -- Aqua-only presentation fixes for shared-widget rows belong in the panel that owns the layout, not in shared/job_ui.py; a below-the-real-floor geometry is a Windows-only test claim, not a defect

**Decision:** When native aqua ttk metrics make a row built from a shared
component (`shared.job_ui.ImportedFileList`'s six action buttons,
`JobControlBar`'s four buttons, `JobStatusView`'s progress bar) too wide for
an adopting panel's own layout invariant, restyle/resize the already-built
widgets from the adopting panel (`button.configure(style=...)`,
`bar.configure(length=...)`, reached through the shared class's already-public
attributes) rather than adding a new constructor parameter to the shared
class. Applied in the TTS Compact UI's Phase 8 macOS remediation:
`_compact_import_actions` and the aqua branch in `_install_jobs`
(`epub2tts_gui.py`) restyle six + four buttons to the built-in `Toolbutton`
style and narrow the progress bar to 140px, entirely without editing
`shared/job_ui.py`. Separately, a composition test at a window size smaller
than `ui_theme.AQUA_MIN_SIZE` in both dimensions is a Windows-only claim
(`windows_only`/`sys.platform != "win32"`), not a real cross-platform
invariant, once the real launcher's own minsize makes that geometry
unreachable on that platform.

**Why:** `shared/job_ui.py` is used by the MP3/M4B tools too; touching its
button-row grid layout to fix a TTS-only aqua-metric defect would have
widened the blast radius of a bounded Phase 8 fix into tools the active plan
explicitly rules out of scope. Every one of the shared class's public
widgets/attributes (`ImportedFileList.buttons`, `JobControlBar.buttons`,
`ProgressIndicator.bar`) already exposes exactly what a caller needs to adapt
presentation without a shared-code change. Reaching into them from the
adopting panel keeps the fix diff to one file's worth of blast radius and
zero risk to sibling tools -- confirmed by running the full focused TTS/
Chatterbox/Kokoro/job_ui sweep unchanged and by `git diff --stat` showing
`shared/job_ui.py` untouched. The 920x600-vs-`AQUA_MIN_SIZE` point mirrors the
identical ruling already made for the M4B/MP3 layout suites
(`test_m4b_maker_ui.py`/`test_mp3_tool_layout.py`'s own `windows_only`
markers) -- this is the same fact discovered a third time, not a new policy.

**Alternatives considered:** adding opt-in constructor parameters to
`ImportedFileList`/`JobAdapter`/`JobStatusView` for a folded button layout
and a configurable progress length (rejected -- a bigger, structural change to
shared code for a presentation-only need the caller can already reach
directly); re-gridding the import buttons into two rows instead of
restyling in place (tried -- it fixed the width but cost `Sources` a
list-display row via `WIDE_LIST_ROWS`'s height-budget cascade, a real
regression, for a fix `Toolbutton` achieves with zero height cost); stacking
the two run-option checkboxes to shave the last ~24px of the "Activity is at
least double" refinement at 1920x1009 (tried -- same list-row-budget
regression, and it did not even close the gap, since the checkbox row was
never the true bottleneck once the button rows were fixed); demanding the
"at least double" refinement hold on aqua regardless (rejected -- the
remaining gap is genuinely necessary content -- an entry field, two checkbox
labels, a 44-character voice combo -- not a fixable presentation excess, and
cutting it needs a maintainer-authorized content change this bounded fix was
not scoped to make).

— Root-caused and implemented by Claude Code per maintainer instruction,
2026-09-24

---

## 2026-09-24 -- `controller.is_terminal` can be true before the settled `RunResult` reaches the main thread; a test that needs the result must wait on the result itself

**Decision:** `settle()` (`epub2tts_gui.py`) moves the controller to its
terminal state (`finish_cancelled`/`succeed`/`complete_with_failures`) and
publishes that state change *before* it enqueues the settled `RunResult` on
`log_q` for the main-thread pump to drain into `panel._result`. This ordering
is correct and stays as-is: nothing in production reads `panel._result`
synchronously off `controller.is_terminal` (`has_retryable`/Retry Failed reads
`panel._result` directly, never `is_terminal`, in `shared/job_ui.py`'s
`JobAdapter`). Any test that needs the settled result, not just the terminal
state, must wait on `panel._result is not None` as its own, second condition
-- `wait_for(lambda: controller.is_terminal, ...)` alone is not sufficient and
must never be read as a proxy for "the result is populated." This was already
the established pattern in `test_tts_jobs.py`'s cancellation-cleanup test
(its own comment records the same ordering); the newer P14 worker-concurrency
test had not applied it, and consequently flaked (P14, ~1 in 3 runs) reading
`panel._result` immediately after observing `is_terminal`.

**Why:** discovered as a real, reproducible flake
(`test_a_success_finishing_during_cancellation_is_recorded_not_orphaned`,
Phase 8 macOS Mac-only findings) while investigating the maintainer-authorized
remaining Phase 8 Mac verification blockers. Confirmed not a production race:
the only production reader of the settled result already depends on
`panel._result` itself.

**Alternatives considered:** reordering `settle()` to enqueue the result
before transitioning the controller (rejected -- the controller's own
terminal-state transition and publication is what unblocks `close()`/
`cancel_job()`'s own `is_terminal` guards and the shared control-bar's state
rendering; delaying it behind the result queue put would just move the same
kind of ordering question elsewhere, for no test this file's suite actually
needs); reading `panel._result` synchronously without a second wait (the
status quo -- rejected, it is the flake itself).

— Root-caused and implemented by Claude Code per maintainer instruction,
2026-09-24

---

## 2026-09-24 -- A fixed bug class does not propagate to a duplicate implementation on its own; a retryable Book failure is one Summary line regardless of occurrence count; a bounded generation retry that exhausts fails closed

**M4B Maker's concat-list writer carried the exact bug the MP3 Tool's own
concat writer was fixed for on 2026-08-07** (ffmpeg concat-demuxer quote
escaping: a literal `'` must become `'\''`, not `\'`) -- because
`m4b_maker_processing.write_concat_list` is a separate, duplicate
implementation (moved verbatim from the pre-v0.6.4 `m4b_maker.py`), not a
shared call into the already-fixed one. **The durable rule: this codebase
does not assume a fix in one module reaches a sibling duplicate.** When a
bug class is fixed, a maintainer or agent should grep for other
implementations of the same mechanism (concat-list writers, chapter
writers, pause/silence escapers) rather than trusting the fix propagated.
Here that check is additionally blocked by a deliberate architectural
boundary (`test_the_engine_reads_no_tk_workspace_or_panel_and_discovers_ffmpeg_only_once`
bars `m4b_maker_processing.py` from importing `mp3_tools.mp3_processing`),
so the two escapers must be corrected and kept correct independently, not
unified by import.

**A retryable Book failure is exactly one `reporter.failure()` call, however
many source occurrences it spans.** `m4b_maker_batch.py` used to call it
once per occurrence -- correct for the per-occurrence `FailureRecord` tuple
Retry Failed's bookkeeping needs, wrong for the user-facing Summary, which
showed one failure ~264 times for a 264-track Book. The fix separates the
two concerns explicitly: build the full per-occurrence `FailureRecord`
tuple exactly as before (Retry Failed needs every occurrence id), but
report exactly once per Book, using its first occurrence id (the same
convention progress reporting already uses). **The durable rule:**
retry/state bookkeeping and user-facing Summary reporting are two different
concerns with two different cardinalities, and a fix to one must not assume
the other's cardinality follows along for free.

**A bounded generation retry that exhausts every attempt fails the file,
never publishes the last known-bad draw.** Chatterbox's pathological-
silence retry (2026-09-24, above) originally kept the last attempt on
exhaustion; a same-day before/after Mac rerun showed the retry works as
designed but does not guarantee zero recurrence, which meant that
"keep the last attempt" path would have shipped defective narration to a
real audiobook. Changed to raise `ChatterboxPathologicalSilence` instead --
the conversion fails that one file explicitly and reports it truthfully,
rather than looping past the bounded attempt count chasing a lucky sample
or silently keeping a demonstrated-bad result. **The durable rule: a
bounded mechanical retry around a demonstrated defect must have a
fail-closed exhaustion path, not a best-effort one** -- the same principle
P8/P9 already apply to source/reference integrity and pronunciation hacks,
extended here to generation-defect retries.

---

## 2026-09-24 -- A Chatterbox chunk's pathological internal silence is a raw, stochastic model artifact, not an assembly or chunking defect; a bounded per-draw retry masks it without guaranteeing it away

During the v0.6.5 Phase 8 macOS listening gate the maintainer confirmed two
real Chatterbox artifacts flagged by the Mac bounded-validation run (Male 1,
13.75 s; the second one mislabeled "Male 2" in review but mechanically
confirmed as Male 3, 7.98 s -- four independent checks: manifest order,
production code's own frozen_voice_id, the engine's transcript log, and an
independent ffprobe duration match).

Applying the same exact-zero-vs-model-floor technique the v0.6.1 Plan 4
Phase 12 chunking investigation used (2026-08-18): assembly's `np.zeros` gaps
survive MP3 decode as literal zero samples; model output never does. Neither
flagged silence was anywhere near an exact-zero run -- both live entirely
inside one raw `model.generate()` draw (Male 1: chunk 21; Male 3: chunk 10,
segment 1). Unlike the Phase 12 defect, neither chunk contains a raw newline
or any pattern the splitter misses -- `split_for_chatterbox` is working
correctly. This is a Chatterbox Turbo sampling artifact (unseeded,
temperature 0.72), not a chunking bug.

A bounded reproduction (4 repeated draws per flagged/control segment, same
voice/reference/settings, no seed) showed it is **stochastic**: Male 1's
flagged text reproduced 0/4 (consistent with its original "rare" Windows
characterization); Male 3's flagged text reproduced **2/4** -- a materially
elevated rate for that specific sentence.

**Fix: `chatterbox_synth._generate_checked` retries a demonstrated
pathological internal silence (4.0 s below -50 dB, the same definition
Phase 8's final-acceptance harness uses) up to 3 times, keeping the first
clean draw; if every attempt is still defective, the last attempt is kept
and logged, never silently dropped (P8/P9). `_synthesize_chunk` reaches
every draw -- the whole-chunk path and each colon-segment path -- through
this helper. No generation parameter, text, or voice/reference changed
(P1).** Regression coverage: `test_chatterbox_silence_retry.py` (10 tests).

**Honest before/after result, not oversold: the fix works exactly as
designed but does not guarantee zero recurrence.** Re-running the identical
sample after the fix: Male 3 came back clean (no retry needed that draw).
Male 1 still showed a **new** pathological silence -- 11.99 s, landing in
the *same* chunk 10 / segment 1 as Male 3's original defect, a second
different voice failing on the identical text after the retry fired and
exhausted all three attempts (confirmed in the transcript). This is a
suggestive, still-small-sample signal that this one sentence carries an
elevated cross-voice risk, not yet confirmed as a distinct root cause and
not investigated further here.

**Ruling: accepted as a real mitigation, not a guarantee (P6 -- maintainer
decides next step).** The residual-risk decision (accept it, raise the
retry bound, or treat chunk 10's text as a separate follow-up) is the
maintainer's, recorded at the Phase 8 macOS gate in Handoff.md rather than
decided here.

---

## 2026-09-23 -- Kokoro's longer pause after a prose colon is accepted as model-native; an isolated colon-to-comma A/B showed no audible improvement and is not integrated

During the v0.6.5 Phase 8 maintainer listening gate (plan Section 9), the
maintainer separately tested an isolated colon-to-comma text substitution for
Kokoro voices, hypothesizing it might shorten Kokoro's longer model-native
pause after a prose colon. This is a different pause than the already-
approved Chatterbox structural-colon normalization from Phase 5 iteration 5
(integrated Phase 6) -- that candidate is unrelated and unaffected by this
finding. The isolated Kokoro candidate produced no audible improvement.

**Ruling: REJECTED, not integrated (P1, P6).** Kokoro's longer pause after a
prose colon stands as accepted, model-native behavior. No Kokoro code,
segmentation, or assembly changed as a result. This finding is preserved so a
later phase or a fresh agent context does not repeat the same rejected
experiment.

---

## 2026-09-22 -- v0.6.5 Phase 7 closed (maintainer PASS at e1c416a); Phase 8
Windows final-voice evidence runs through the real TTS panel job path

**Decision.** (1) Recorded: the maintainer passed the final Phase 7 Windows
layout/functional review at `e1c416abf5267490fc5c40367f9aa67de6c4eb6f`.
(2) Phase 8's final listening evidence is produced by a new `--final-acceptance`
mode of the existing `generate_voice_samples.py`, not a new tool. Unlike the
Phase 1 `--quality-suite` (direct engine calls, raw Edge audio), it drives a
headless `TtsPanel` through `run_job()` with the panel's defaults, so what the
maintainer hears is exactly what a user's run produces. Only the output base is
redirected, to gitignored `files/dev-work/`.

**Why.** Section 9 is final acceptance of the integrated product. Evidence from a
side path could hide a defect in the Phase 6 assembly or P14 dispatch that users
would hear.

**Mechanical bounds are catch-nets, not quality thresholds (P3, P6):** 8-25
chars/s, no internal silence over 4 s, no full-scale samples, strict decode,
container vs. decoded duration within 0.5 s. All 35 files met them; listening
still decides.

**Noted, not acted on:** about 1.4 GB of private-memory growth per Chatterbox
run inside one process (flagged for Phase 9), and the known 160 kbps effective
cap at 24 kHz (earlier ruling unchanged). `scripts/verify.py`: PASS (7624 passed, 57 skipped).

-- Implemented by Claude Code per the maintainer's Phase 8 (Windows portion)
authorization, 2026-09-22

---

## 2026-09-22 -- v0.6.5 Phase 7 final layout refinement: beside Activity the TTS
workflow is one vertical column with a compact Sources; Activity takes the rest

**Decision.** Per the maintainer's screenshot feedback on the responsive
redesign: whenever Activity is beside the workflow, sections 1, 2 and 3 are one
top-anchored vertical column -- never Voice & Audio beside Output & Run. The
imported list shows at most WIDE_LIST_ROWS = 8 rows there (fewer when the
height needs them, never below IMPORTER_FLOOR_ROWS = 2) and scrolls locally
instead of stretching. The workflow column is its measured natural width plus
at most WORKFLOW_BREATHING = 48 px, replacing the earlier one-third-of-spare
rule; Activity takes all remaining width and the full height (1331 of 1920 px
on HOME-PC, up from 829).

**Why.** The workflow reads as a sequence (sources, voice/audio, output/run),
and side-by-side sections broke that order on the very windows where space was
plentiful. A tall list with few files was empty space that pushed sections 2
and 3 away from Sources; a queue that long is better scrolled. Width beyond what
the workflow's fixed-size controls need was empty band; the log turns it into
readable lines.

**The one exception.** At the supported 920x600 minimum, Activity drops beneath
the workflow and sections 2 and 3 still share a row. Measured, it is the only
arrangement that fits: the vertical workflow's floor alone is 655 px against
580 px of content height, and the two columns' natural widths exceed the
window. The maintainer's instruction to preserve the minimum layout governs
there, and a test pins the measured reason.

**Unchanged.** Every capability and behavior; no TTS, audio, import, output-
planning or job-control code changed. `scripts/verify.py`: RESULT: PASS (full pytest 7616 passed, 57 skipped).

**Not touched in this drop:** the `99195a2` trailer (left for a separate
authorization), Phase 8 (unauthorized). Phase 7 is not marked passed.

-- Implemented by Claude Code per the maintainer's final Phase 7 layout-
refinement authorization, 2026-09-22

---

## 2026-09-22 -- v0.6.5 Phase 7 UI/UX redesign: the TTS panel becomes four sections
arranged responsively from measured sizes (workflow left, Activity right when
both fit; stacked below that)

**Decision.** Per the maintainer's redesign request after the Phase 7 manual
review, the TTS panel is recomposed into 1. Sources, 2. Voice & Audio,
3. Output & Run, and Activity (the one persistent Summary | Detailed log). The
arrangement is chosen by `TtsPanel._choose_layout` as a pure function of the
panel's size, using natural sizes measured from the live widgets
(`_measure_layout`): two columns only when the workflow and Activity both fit
at their natural widths and the workflow's floor fits the height; sections 2
and 3 side by side whenever the width allows; otherwise Activity drops beneath
the workflow. No whole-tool scrollbar in any arrangement.

**Why these rules, not a fixed ratio.** The maintainer's 60/40 was offered as a
starting point, not a requirement. The workflow's controls are fixed-size, so
spare width in that column is empty band -- the exact complaint about the old
full-width Voice/Audio bands. So each column first gets its natural width and
the spare width goes one third to the workflow, two thirds to the log
(workflow/log widths 517/477 at 1024x720, 602/648 at 1280x900, 1061/829 at
1920x1009, where sections 2 and 3 sit side by side). The one content-chosen number is
the log's minimum width, LOG_WIDTH_CHARS=52, sized to a typical Detailed line;
every other threshold is measured, so the breakpoints follow real fonts and
scaling. On HOME-PC that puts the 1024x720 launcher default in the two-column
layout and the 920x600 minimum in the stacked one.

**Why the column width is set explicitly.** Wrapped captions re-wrap to their
section's width, which makes a column's request follow its allocation. Left to
grid weights, the workflow column ratcheted wider on every resize and squeezed
the log below its natural width (found and measured during this drop). Wrap
widths now come from the layout arithmetic, and the workflow column's width is
set by `_size_columns`. Regressions are mutation-checked.

**Correction to the previous entry.** The remediation entry below recorded the
log as "900x61 px (a real, multi-line, readable region)" at 920x600. That
measured its size without checking it was inside the window: it sat at
y=650-711 in a 600 px window, fully off-screen. This redesign supersedes that
claim; the log now shows ~4 lines at 920x600 and ~37-56 lines on larger
windows.

**Unchanged.** Every capability and behavior listed in the redesign request:
unified PDF/TXT queue and its options, voice/setup-required behavior, bitrate,
requested workers with truthful effective reporting, Edge rate / Kokoro speed /
no Chatterbox control, Resume, Overwrite, Start/Pause/Resume/Cancel/Retry
Failed, progress + ETA, one persistent log with the transcript in Detailed
only, Clear Log, Open Output Folder, output planning, and all Phase 5/6 audio
and worker behavior. No timing/trim control was reintroduced and no voice
preset changed. `scripts/verify.py`: RESULT: PASS (full pytest 7602 passed, 57 skipped).

**Not touched in this drop:** Phase 8 -- not started, unauthorized. Phase 7 is
not marked passed; the maintainer's screenshot/manual UI review is outstanding.

-- Implemented by Claude Code per the maintainer's Phase 7 UI/UX redesign
authorization, 2026-09-22

---

## 2026-09-21 -- v0.6.5 Phase 7 remediation: TTS's Summary/Details view and its
separate "Engine output" box are consolidated into one persistent
job_ui.SummaryDetailsView, matching the MP3 Tool/M4B Maker/M4B Metadata Editor

**Decision/implementation.** The maintainer's manual Phase 7 gate ran and came
back FAIL: the TTS panel showed two separate log regions -- the JobAdapter's
own internally built Summary/Details notebook, plus a second, standalone
"Engine output" `scrolledtext.ScrolledText` immediately below it -- duplicating
and fragmenting run information and wasting the vertical space the previous
layout-refinement pass had just fought to recover. The correction: TTS adopts
the exact persistent-view pattern the MP3 Tool, M4B Maker and M4B Metadata
Editor already use, while keeping the panel's own classic (no design-system
theme) styling -- this was a structural fix, not a visual-parity pass.

**1. One view, built once, handed to every adapter.** `self.log =
job_ui.SummaryDetailsView(self, theme=None, height=2, details_label=
"Detailed", limit=LOG_LIMIT)` is built in `__init__` and gridded at row 4 in
place of the deleted "Engine output" `LabelFrame`/`ScrolledText`; `_install_
jobs` passes `views=self.log` into every run's `JobAdapter`, so the adapter
never builds or grids its own view and history survives a rebuild. `LOG_LIMIT
= 400` and `DIVIDER_MARK = "────"` are the same constants the three
sibling tools already use, copied rather than reinvented.

**2. `shared/job_ui.py` gained one additive method: `SummaryDetailsView.
append_detail()`.** No existing method could write to Details alone --
`append()` always writes both panes, which conflicts directly with keeping raw
engine chatter out of Summary. `append_detail()` mirrors `append()`'s
freeze-then-extend-then-trim-then-redraw contract exactly, touching only the
Details history. Backward compatible: every existing caller of `append()`,
`set_summary()`, `set_details()`, `divider()` and `clear()` is unchanged.

**3. Engine transcript routing.** The worker->GUI `_log_q` "log" kind already
carried both raw stdout/stderr (via `QueueWriter`, `contextlib.redirect_
stdout`/`redirect_stderr`) and the worker's own milestone strings (`_RunContext.
log`, e.g. "[12:00:00] file.txt -- completed", "Requested workers: N |
Effective workers: N") -- both were already going into one visual box before
this drop, so no worker-side code changed. Only the panel's own routing
changed: `_append_engine_output()` line-buffers this channel across drain
ticks and calls `self.log.append_detail()` with complete lines only, and
`_flush_engine_output_buffer()` catches a trailing partial line when a "done"
message ends the run, so nothing already reaching the log is lost. Summary is
unaffected by any of this: it is still exactly job_control.project_summary's
own state/progress/warnings/failures/completion projection, driven from the
job event stream and nothing else.

**4. Row weights: row 3 (shared run controls) pinned, row 4 (the log)
absorbed its weight.** Row 3 held Summary/Details until this drop, which made
weight=2 (elastic) the correct choice; now it holds only the JobAdapter's
fixed-height control bar and status view, so weight=0 is correct and row 4
rose from weight=4 to weight=6 to receive the difference, exactly the "give
the recovered space to the one log" instruction this drop was scoped to.
`_hold_job_area_open()` was rewritten to measure `controls.frame`/
`status.frame` directly rather than call `JobAdapter.minimum_height()`, which
still unconditionally adds `views.minimum_height()` regardless of whether the
caller owns those views -- with `views` now external to `job_area`, that
method would misattribute row 4's own floor onto row 3.

**5. A real floor-computation bug was found and fixed, not merely designed
around.** Both `_hold_job_area_open()` and `_hold_log_open()` read their
target widgets' `winfo_reqheight()` immediately after those widgets were
built, in the same call that built them, before Tk's geometry manager had
necessarily settled a real value in place of a small-but-positive placeholder
-- which is well above zero, so the existing `floor <= 0` retry guard never
fired. Measured directly: row 3's floor landed at ~10 px (needed: 93 px) and
row 4 got no floor at all, so the log collapsed to a real, mechanically
measured 1x1 px sliver at the 920x600 minimum -- worse than the *previous*
drop's already-accepted "compresses to effectively nothing" trade-off for the
old Engine output box, not an improvement on it. Both methods now force an
idle-task pass unconditionally before their first measurement, matching the
pattern `_hold_importer_open()` already used. Corrected and mechanically
re-measured at the exact 920x600 minimum: log 900x61 px (a real, multi-line,
readable region), job area 900x93 px, importer 900x163 px, options form
920x331 px, Start row 304x41 px; at 1280x900 the log grows to 1260x108 px.
Zero overlaps among the five top-level bands at either size.

**6. Tests.** `files/tests/test_job_ui.py`: 5 new focused tests for
`append_detail` (details-only, multi-line, freeze-then-extend interaction with
a live Summary re-render, divider interaction, limit). `test_tts_compact_ui.
py`: 5 existing tests fixed for the new `self.log` shape (no longer a raw Text
widget), plus 2 new tests (exactly one Notebook and no "Engine output" widget
anywhere in the tree; the floor-computation regression at 920x600).
`test_tts_jobs.py`: a new "P. Summary/Detailed log consolidation" section (7
tests) proving persistent-view identity across an adapter rebuild, raw log
lines and a partial unterminated line both landing in Detailed only, a real
run's transcript in Detailed while Summary carries only its own completion
wording, history surviving both a retry and a second fresh run with the
correct divider text, and Clear Log emptying both panes without touching the
frozen `RunResult`. `test_tts_importing.py`/`test_tts_worker_concurrency.py`:
4 pre-existing tests updated from `panel.log.get(...)` to `panel.log.details`.
Full TTS + job_ui sweep: 465 passed. Full `pytest`: 7582 passed, 57
skipped, zero failures. `scripts/verify.py`: RESULT: PASS. No TTS synthesis,
audio quality, timing, worker, importing or output-planning behavior changed.

**Not touched in this drop:** Phase 8 -- not started, unauthorized. The
maintainer's manual Windows layout/functional smoke gate -- this entry
records implementation and mechanical verification only, not that gate's
outcome, which remains outstanding and is explicitly not claimed here, and
Phase 7 is explicitly not marked passed by this entry.

-- Implemented by Claude Code per the maintainer's Phase 7 remediation
authorization, 2026-09-21

---

## 2026-09-21 -- v0.6.5 Phase 7 (final layout-refinement pass): the options
form's canvas/scrollbar is gone; adopts the M4B Converter/MP3 Tool's own weighted-
row scheme for the 920x600 minimum

**Decision/implementation.** Per the maintainer's request for one final Phase 7
layout-refinement pass (no TTS/audio/concurrency behavior change) before the
manual Windows gate: the options form's own canvas/scrollbar machinery -- which
the Compact UI pass (previous entry) had already shrunk to ~445 px but not
removed -- is gone entirely, and the panel's five top-level rows now use the same
weighted-row scheme this codebase already uses for the identical problem in the
MP3 Tool and M4B Converter.

**1. Investigated before editing.** A real, unconstrained `TtsPanel` was measured
directly (`winfo_reqheight()` per band) before any change: the options form's own
canvas/scrollbar contributed no real value at 445 px against bands that, added
together (importer 275 + Start row 41 + job area 259 + log 124 = 699 px), already
exceeded the 600 px minimum on their own -- meaning simply removing the canvas
without also adopting a real compression scheme elsewhere would have made the
panel need a *bigger* window, not fit a smaller one.

**2. The options-form canvas/scrollbar is removed entirely.** `frm` (Voice/
Engine + Audio/Processing + run options) is now an ordinary `ttk.Frame` gridded
directly at row 1 -- no `tk.Canvas`, no `ttk.Scrollbar`, no `<Configure>`
rebinding, no `enable_mousewheel` call. Verified directly: zero `tk.Canvas`
widgets exist anywhere in the panel (`files/tests/test_tts_compact_ui.py::
test_no_canvas_anywhere_in_the_panel`), matching the MP3 Tool's own established
convention for this exact situation (`test_no_whole_tool_scrollbar_only_local_
ones`, `assert widgets_of(panel, tk.Canvas) == []`).

**3. Row weights now match the M4B Converter's own scheme for the same problem**
(`m4b_converter.py`, `rowconfigure(0, weight=4)` / `(1, weight=0)` / `(2, weight=0)`
/ `(3, weight=2)` / `(4, weight=4)`): the imported queue (row 0) and the engine
log (row 4) carry the weight and compress/scroll locally; the options form
(row 1) and the Start/Open Output Folder/Clear Log row (row 2) are pinned at
weight=0, never squeezed below what their controls ask for; the shared run
controls' row (row 3, Summary/Details/progress) gets weight=2 and a measured
floor (below).

**4. Two floor-protection methods were added, both adopting the exact mechanism
the M4B Converter already uses and already has a dedicated shared-infrastructure
test for (`test_job_ui.py::test_the_views_keep_one_readable_line_however_hard_
they_are_squeezed`):**
- `_hold_job_area_open()` mirrors the M4B Converter's own method of the same
  name near-verbatim: measures `JobAdapter.minimum_height()` (shared, already
  tested infrastructure) and sets `rowconfigure(3, minsize=...)` so Summary
  never collapses to a sliver. TTS never had this protection before this pass
  -- a genuine fix, not merely a port.
- `_hold_importer_open()` and `_hold_log_open()` are new (no direct prior-art
  method to mirror, since `ImportAdapter` exposes no `minimum_height()` of its
  own): the first protects the imported queue's Add Files/Import Folder/Include
  Subfolders and import-status rows (both weight=0 inside `ImportAdapter.
  frame`) from being squeezed below their own request when the *outer* queue
  row is compressed -- without it, a real defect was found and fixed during
  this pass: `grid` does not clip a child to a cell smaller than its own
  request, so the effect of an unprotected floor was those controls
  **overlapping** the Voice/Engine section below them, not merely shrinking.
  The second gives the engine-output log a floor of two visible lines (this
  codebase's own "at least two rows" bar for variable-length regions,
  e.g. plan §11 / `test_m4b_layout.py`), rather than letting weight=4 alone
  compress it to a single, effectively-invisible pixel.

**5. Further compaction, all textual/spacing only (no behavior change):**
`details_height` (Summary/Details) and the engine-output log's own visible-line
count both dropped from 8/8 to 4/4, matching the M4B Converter's own already-
accepted values exactly (not an invented number). The options form's footer
paragraph (five sentences restating what the per-backend notice/status labels
already say live) is now one line naming only the default voice; the workers
caption and the Edge-rate caption are both shortened to fit one wrapped line
each. LabelFrame/row padding tightened from 8-10 px to 6 px throughout the form.
Net effect: the form's own `winfo_reqheight()` fell from ~445 px (previous entry)
to 331 px.

**6. Mechanically verified, not just estimated.** A real, sized `TtsPanel`
(packed to fill its window, exactly as the real launcher does) was measured at
both the supported minimum (920x600) and a larger window (1280x900):
zero overlaps among the five top-level bands at either size; every primary
control (Add Files/Import Folder, voice dropdown, bitrate, workers, Start, Open
Output Folder, Clear Log) stays mapped and reachable at both sizes; backend
switching (Edge/Kokoro/Chatterbox) still shows exactly the one correct rate
control at the 920x600 minimum specifically. At 920x600: options form 920x331
(its full, protected request), importer 900x163, Start row 304x41, job area
900x141 (close to its measured Summary floor), engine log compresses to
effectively nothing -- an accepted, explicit trade-off, since the log is
precisely the kind of "may continue to scroll internally" region §11 already
allows, and it recovers immediately at any window taller than the exact
minimum (38 px of visible log at 1280x900).

**Verification.** `files/tests/test_tts_compact_ui.py` section D was rewritten:
the two tests that depended on the now-removed canvas were replaced with tests
proving zero canvases exist, every scrollbar belongs to a locally-scrolling
widget, the form is a plain pinned frame, the form stayed compact (< 400 px,
down from the previous entry's < 1000 px bound), no top-level band overlaps
another at 920x600 or 1280x900 (parametrized, with real geometry/deiconify/pack
-- an unmanaged or withdrawn panel reports meaningless `winfo_rootx`/`ismapped`,
so the test explicitly packs and deiconifies before measuring, mirroring
`test_mp3_tool_layout.py`/`test_m4b_layout.py`'s own convention), and backend
switching's rate control at the 920x600 minimum specifically. Two existing
tests whose assertions named the old, now-shortened caption text were updated
to the new wording. Full `pytest`: 7568 passed, 57 skipped, zero failures.
`scripts/verify.py`: RESULT: PASS. No TTS/audio/concurrency behavior was
touched; the real production-path smoke campaign (recorded separately, this
same date) was not re-run, since nothing on that path changed.

**Not touched in this drop:** Phase 8 -- not started, unauthorized. The
maintainer's manual Windows layout/functional smoke gate itself -- this entry
records implementation and mechanical verification only, not that gate's
outcome, which remains outstanding and is explicitly not claimed here.

-- Implemented by Claude Code per the maintainer's Phase 7 final layout-
refinement authorization, 2026-09-21

---

## 2026-09-21 -- v0.6.5 Phase 7: Compact TTS UI -- pause/trim controls removed
from user-editable state; the per-voice policy behind them is unchanged

**Decision/implementation.** Per the maintainer's authorization for the plan's Section
10 compacting pass, the TTS panel's user-facing surface is reduced to exactly the
bands Section 10 specifies, with no change to any approved TTS/audio/concurrency
behavior from Phases 1-6.

**1. Removed from user-editable state:** sentence/paragraph/title/chapter pause,
end-silence, trim threshold, and trim-edge-chunks. Their Tk StringVar/BooleanVar
backing (`sentence_ms_var`, `paragraph_ms_var`, `title_ms_var`, `chapter_ms_var`,
`end_pause_var`, `trim_edge_chunks_var`, `trim_dbfs_var`) and the "Pause timing" and
two provenance-scoped ("files added directly" / "imported from a folder") LabelFrames
are gone entirely, along with the now-unused `_parse_pause_ms`/`_parse_trim_dbfs`
input-validation helpers they existed only to serve.

**2. The maintainer-approved per-voice policy behind those controls is unchanged.**
`voice_registry.VoiceEntry.timing_preset` still varies per voice exactly as before
(e.g. Edge Andrew's 820/870 ms sentence/paragraph pause vs. Steffan's 800/850) --
`epub2tts_gui.TtsPanel.run_job` now reads it directly from the registry at run time
instead of from a widget, so the values a run actually uses are byte-identical to
before, just no longer editable. `voice_registry.py`'s own module docstring is updated
to state this plainly (its `timing_preset` keys no longer name live Tk StringVars).

**3. Retained exactly as Section 10 specifies:** the unified PDF/TXT queue/importer,
voice dropdown and backend/setup-required status, MP3 bitrate, the requested
file-worker control with P14's truthful effective-cap reporting, and the one
rate control the selected backend actually supports -- Edge shows a "%"-rate entry,
Kokoro shows its speed spinbox, and **Chatterbox now shows neither** (previously the
Edge-rate entry was shown, inertly, regardless of backend -- a real "fake control"
this pass corrects, not a new restriction). The Edge rate control is captioned
honestly: it has only ever affected folder-imported Edge conversions (the direct/rich
engine has never accepted a rate parameter), a pre-existing asymmetry now stated
rather than left implicit.

**4. Bitrate and workers are no longer framed as provenance-specific.** Both already
applied to every queued item regardless of direct-vs-folder origin (bitrate always
did; workers did so precisely because Phase 6 unified dispatch), so the two old
LabelFrame headings implying otherwise were already misleading before this pass. Both
now live in one consolidated "Audio / Processing" LabelFrame (§10 Band 3), alongside
the rate control, ordered after a new "Voice / Engine" LabelFrame (§10 Band 2) so the
backend-dependent rate control's own band follows the choice that determines it.

**5. Resume and Overwrite** (neither explicitly named in Section 10's table, neither
in its Remove column) are kept, moved together into one small "run options" row
rather than left split across the two retired provenance-specific groups.

**6. Added: Clear Log and Open Output Folder**, bringing this panel to parity with
the sibling MP3/M4B tools that already have both (`mp3_tool.py`, `m4b_converter.py`,
`m4b_maker.py`, `m4b_metadata_editor.py`). Neither is a processing option and neither
locks through the shared matrix, matching those tools' own convention exactly.
`open_output_folder` reveals this run's own reserved directory once one exists, or
the tool's parent folder before any run -- reusing `output_paths.ensure_tool_parent`
and `shared.subprocess_utils.reveal_in_file_manager`, both already used by the
sibling tools for the identical purpose.

**7. Layout.** No whole-tool scrollbar: the options form keeps the one internal
scroll canvas it already had before this phase (unchanged architecture), and no
second canvas/scrollbar wraps the panel itself. Removing the entire pause/trim band
and merging two LabelFrames into one measurably shrank the scrollable form (a real,
mechanical Tk measurement: 445 px, down from the ~1300 px the form's own prior
comment documented) and the panel's always-visible bands (importer + Start row +
job area) measure ~575 px total -- comfortably under the shared 920x600 minimum
window (`shared.ui_theme.MIN_SIZE`) the launcher already applies. This is a
mechanical proxy, not the mandatory Windows manual layout/functional smoke gate,
which remains outstanding.

**Verification.** Two pre-existing tests that asserted the removed StringVars
directly (`test_tts_importing.py::test_the_voice_dropdown_still_applies_a_timing_
preset`, `test_chatterbox_integration.py::test_selecting_a_chatterbox_voice_applies_
its_timing_preset`) were rewritten to prove the same underlying per-voice values
still reach the frozen run params with no widget in the path, rather than asserting
on removed attributes. New `files/tests/test_tts_compact_ui.py` (18 tests) covers:
removed attributes/helpers/wording are gone; the consolidated Audio/Processing band
holds bitrate/workers/rate; exactly the backend-supported rate control is shown per
voice (Edge/Kokoro/Chatterbox, parametrized); Clear Log and Open Output Folder behave
correctly and are not registered as processing options; no second outer scrollbar
exists; and the real, mechanical form-height/fixed-band-height measurements above.
Full `pytest`: 7561 passed, 57 skipped, zero failures. `scripts/verify.py`:
RESULT: PASS.

**Not touched in this drop:** Phase 8 (final voice acceptance + macOS validation) --
not started, unauthorized. The mandatory Windows manual layout/functional smoke gate
this phase's own instruction requires is also still outstanding -- this entry records
implementation and mechanical verification only, not that gate's outcome.

-- Implemented by Claude Code per the maintainer's Phase 7 (Compact TTS UI)
authorization, 2026-09-21

---

## 2026-09-21 -- v0.6.5 Phase 6: bounded file-worker concurrency (P14) implemented;
a real os.chdir race discovered and fixed in the Edge direct/rich engine

**Decision/implementation.** Per the maintainer's authorization to close the audio-
integration subtask and execute only the file-worker/concurrency subtask, P14 is now
implemented: concurrency exists only between whole source files (never inside one
file's own synthesis units), and effective workers are resolved at run start rather
than trusting the raw requested count.

**1. Direct and folder items now share one pool and one resolved worker count.**
`epub2tts_gui._RunContext.run_all_items` replaces the old two-phase design
(`run_direct_items` -- strictly sequential, one at a time -- followed by
`run_folder_items`/`convert_folder_items` -- pooled, folder-only). Every queued item,
regardless of provenance, now goes through one `ThreadPoolExecutor` sized by one
resolved effective-worker count. A direct Edge file still takes the rich chapter/
pause engine and a folder-derived Edge file still takes the chunked batch worker
(P10 -- provenance selects the engine, never audio quality); Kokoro/Chatterbox take
the same engine call regardless of provenance, as before.

**2. `resolve_effective_workers(requested, queued_files, backend)`** is the one place
the cap is computed: `min(requested, queued_files, backend_safe_ceiling,
device_safe_ceiling)`, floored at 1. Backend-safe ceilings are unchanged from the
pre-existing folder-pool code (Edge 32, Kokoro 8, Chatterbox 1 -- a correctness
constraint, not a tuning choice). The device-safe ceiling is new: read from the real
machine's `os.cpu_count()` (via a small patchable seam, `_cpu_count()`), not an
invented formula -- Edge (network-bound locally) is offered up to one worker per
logical core, Kokoro (sustained local CPU inference per file) is offered half the
cores, leaving headroom for the OS/UI/FFmpeg either way. An oversized request (e.g.
"100") degrades safely to whatever the machine/backend/queue can actually support and
is never silently ignored: `run.log` always states
"Requested workers: X | Effective workers: Y".

**3. A real, previously-latent bug was found and fixed while implementing this:**
`epub2tts_edge.runner.run_conversion_job` isolates one conversion's relative-path
scratch files (`part1.flac`, `sntnc0.mp3`, `FFMETADATAFILE`, etc.) by `os.chdir`'ing
into a private temp directory for the whole call. This was safe only because direct
Edge items were previously guaranteed to run one at a time; `os.chdir` is process-wide
state, not thread-local, so two concurrent direct Edge conversions would have raced,
each potentially writing one book's chapter/paragraph scratch files into the other's
temp directory. Fixed with `runner._CWD_ISOLATION_LOCK`, serializing only that
chdir'd critical section -- not the whole engine, so a folder-derived Edge file or any
Kokoro/Chatterbox file dispatched to a different pool worker still runs fully
concurrently with a gated direct Edge file (neither of those paths ever calls
`os.chdir`). A conversion that is cancelled while queued behind this lock re-checks
`cancel_check()` immediately on acquiring it, so it never starts a whole new
conversion no one wants, even though the wait itself cannot be interrupted early (the
same "indivisible operation" contract every other checkpoint in this codebase already
accepts). Rewriting the vendored engine to take an explicit working directory instead
of relying on cwd would remove the need for this lock entirely, but that is a larger
change to vendored internals than this bounded subtask justifies (P11/P14).

**4. A second, related correctness gap in the pre-existing folder-only pool was
fixed while unifying it:** the old code broke out of its results loop and called
`future.cancel()` on remaining futures as soon as it noticed a cancellation, but
`future.cancel()` only succeeds for a future that has not yet started -- an
already-running task's eventual successful result was then silently discarded when
the pool's context manager finished waiting for it, leaving a real output file on
disk that the run never counted, logged, or could offer for retry. The new unified
loop drains every submitted future's result unconditionally; nothing is silently
dropped because the run was cancelled overall.

**5. Chatterbox investigated for a bounded >1-file proof, per the plan's own
conditional instruction, and found not justified.** `chatterbox_synth._get_model`
caches exactly one model instance per device; `load_conditionals` mutates that
instance's `.conds` attribute in place immediately before each `generate()` call --
a genuine shared-mutable-state race if two files' conversions overlapped, not a
theoretical concern. Making two concurrent files safe would require either a second
~3.86 GiB model instance per extra worker (disproportionate VRAM/RAM cost the plan
explicitly warns against) or an invasive rearchitecture of the pinned wheel's
stateful conditioning mechanism -- both out of proportion for this bounded subtask.
**Chatterbox's cap remains 1**, verified directly: a real test drives two files with
two distinct reference voices at a requested worker count of 4, and confirms the
second file's engine call never starts while the first is in flight.

**6. Pause/Cancel/Retry Failed all remain correct under concurrency.** Pause is still
honoured at the same cooperative boundary (`controller.checkpoint()`) each task hits
before starting real work, now shared by every item regardless of provenance. Four
existing tests in `test_tts_jobs.py` that assert exact pause/cancel *ordering* between
two direct files now explicitly pin `workers_var.set("1")` (matching a convention this
codebase already established for one folder-based pause test) -- they test the
boundary semantics, not worker count, and pinning isolates that concern cleanly rather
than leaving them to race real concurrency. Retry Failed needed no change: neither
change here is a new user-facing option, so `epub2tts_gui.freeze_tts_options` is
unaffected and a retry still replays the original frozen `RunSnapshot` untouched.

**Verification.** New `files/tests/test_tts_worker_concurrency.py` (25 tests):
`resolve_effective_workers` at representative 1/2/4/oversized requests and backend
differences; the unified dispatch still routes every item through its correct engine;
truthful requested-vs-effective logging including an oversized-request case; real
overlap proof for folder-Edge and Kokoro under workers=2/4; the Chatterbox
non-overlap proof; a proof that a success finishing during cancellation is still
recorded, not orphaned; and two focused tests against the real
`runner.run_conversion_job` proving the new cwd-isolation lock actually prevents two
direct conversions from being inside `read_book` at once, and that a conversion
cancelled while queued behind that lock never starts real work. Full `pytest`: 7542
passed, 57 skipped, zero failures. `scripts/verify.py`: RESULT: PASS.

**Not touched in this drop:** Phase 7 (Compact TTS UI) -- the workers spinbox's
1-16 range and its display are unchanged; showing the resolved effective count in the
UI itself belongs to that later phase, not this one.

-- Implemented by Claude Code per the maintainer's Phase 6 concurrency-subtask
authorization, 2026-09-21

---

## 2026-09-21 — v0.6.5 Phase 6: approved Phase 5 audio changes integrated into
production (Edge PCM assembly + i.e./e.g. fix; Chatterbox structural-colon normalization)

**Decision/integration (not a new listening judgment — implements verdicts already
recorded below, in this same file).** Per the maintainer's authorization to close Phase 5
and execute only the Phase 6 AUDIO-INTEGRATION subtask, the following previously-approved-
but-unintegrated candidates are now live in production:

1. **Edge direct/rich PCM-domain assembly** (approved iteration 1/4, below):
`epub2tts_edge.read_book`'s per-sentence/per-sub-chunk trim/intra-pause/sentence-pause work
now stays in memory as pydub `AudioSegment` objects, from the raw Edge network bytes through
to each paragraph's own FLAC export, removing the 3-5 avoidable intermediate lossy MP3
re-encodes per multi-sub sentence that existed before. Paragraph/chapter FLAC and the final
single lossy encode (`make_mp3`/`make_m4b`) are unchanged.
2. **NLTK/Punkt `abbrev_types` extension** (approved iteration 2/4, below):
`epub2tts_edge.sent_tokenize` now wraps a deep-copied Punkt tokenizer with "i.e"/"e.g" added
to its `abbrev_types` set, fixing the false sentence-boundary split with zero regression on
any other false-boundary marker. NLTK's own shared cached tokenizer is never mutated (a
deep copy is extended instead).
3. **Chatterbox structural-colon normalization** (approved iteration 5, below):
`chatterbox_synth._structural_colon_punc_norm` replaces the pinned wheel's own blanket
colon-to-comma replacement, preserving structured colons (times, ratios, `://` URL schemes)
while retaining today's prose-colon-to-comma behavior. Applied by monkeypatching
`chatterbox.tts_turbo.punc_norm` at model-load time (`_ensure_structural_colon_patch`,
called from `_instantiate_model`) -- the installed wheel is never edited on disk, and the
patch is idempotent (applied once per process).
4. **Terminal pause-supersede candidate remains rejected** (iteration 3 verdict, below) --
current pause constants/stacking are completely untouched by this integration.
5. **Chatterbox HTTPS URL pronunciation remains model-native/deferred** (iteration 6
finding, below) -- no dictionary/word hack was added; this residual issue is unchanged.
6. **Current Chatterbox generation settings (`generation_params()`) are unchanged. Kokoro
is unchanged.**

**Direct-vs-folder audio-quality semantics unified.** Before this integration, the Edge
direct/rich path performed multiple avoidable lossy MP3 re-encodes per multi-sub sentence
while the Edge folder/batch path (`batch_convert.merge_mp3s`) already decoded each network
chunk once and performed exactly one final lossy encode. Both paths now share the same
contract: raw Edge network audio is decoded once and assembled in PCM, with exactly one
final lossy encode producing the output artifact. Segmentation/pause granularity between
the two paths remains intentionally different (a separate, larger, unauthorized scope --
plan Section 15 explicitly forbids the previously-rejected sentence-pause-parity rewrite
without new evidence); "quality semantics" here means the no-avoidable-lossy-generation
contract, not identical segmentation.

**Retry Failed reproduces the original attempt.** Neither integrated change is a new
user-facing option -- both are unconditional engine-internal behavior with no new field in
`epub2tts_gui.freeze_tts_options`. `retry_failed` re-uses the original frozen `RunSnapshot`
rather than re-reading configuration, so nothing about this integration can behave
differently between an original attempt and its retry.

**Verification.** Full `pytest` suite: 7517 passed, 57 skipped, zero failures (611-623s).
`scripts/verify.py` -> **RESULT: PASS** (pytest/deps/docs/docnames/config all PASS). New
tracked tests: `files/tests/test_edge_direct_pcm_assembly.py` (9 tests -- zero intermediate
MP3 encodes during `read_book`, valid decodable output, pause values preserved, the
i.e./e.g. fix proven against production's own tokenizer with no regression on any other
false-boundary marker, and proof NLTK's shared cached tokenizer is never mutated) and
`files/tests/test_chatterbox_colon_integration.py` (9 tests -- structural colons preserved,
prose colons still converted, byte-parity with the real wheel's `punc_norm` on non-colon
text as a future-wheel-version drift guard, patch-helper idempotency/narrowness, and a
static guard that `_instantiate_model` still calls the patch). `test_segmentation_source_
span.py`'s and `test_chatterbox_punc_norm_evidence.py`'s "found, not fixed" sections were
updated (docstrings only, no assertion changed) to document that they exercise the raw,
unpatched upstream/stock behavior that motivated -- and remains distinct from -- the
now-integrated production fix.

**Not touched in this drop:** the Phase 6 file-worker/concurrency subtask (explicitly out
of scope for this run -- a hard stop per instruction).

-- Integrated by Claude Code per the maintainer's Phase 6 audio-integration authorization
(implementing verdicts already recorded below, not a new subjective judgment), 2026-09-21

---

## 2026-09-21 — v0.6.5 Phase 5 iteration 6 finding: residual Chatterbox URL pronunciation is
model-native under the pinned tokenizer; no general structural candidate justified

**Finding, not a fix (investigation-only; no production file changed, no generation parameter
tuned, no candidate built or integrated).** Per the maintainer's iteration 5 verdict (below), the
approved structural-colon candidate was used as the baseline for this diagnostic, so colon
corruption is no longer a variable.

**1. Mechanical localization, source URL → approved normalization → tokenizer text/tokens →
generation input, across a 10-case diagnostic matrix** (scheme presence/absence/word choice,
domain-only, path-only, a generic path word, query-string punctuation, and a domain-dot-at-a-real-
sentence-boundary control), all using the real production tokenizer loaded from the pinned model:
- The scheme word (`"https"`/`"http"`) tokenizes as a single, ordinary, unfragmented token in every
  case — not the rarity/fragmentation pattern that would explain an unstable reading by itself.
  (`"ftp"`, untested by the maintainer, does fragment into two tokens — noted, not pursued further.)
- `"://"` is a single dedicated token, confirmed present and unchanged regardless of scheme choice —
  the approved colon candidate's fix holds.
- Path and query punctuation (`/`, `-`, `?`, `=`, `&`) all tokenize as clean, ordinary, unambiguous
  single tokens in every variant tested — no fragmentation or structural anomaly found there.
- **The one confirmed structural fact:** the domain-boundary `"."` in `"example.com"` is the *same
  token id* as an ordinary sentence-final period, in every variant tested, with or without a scheme,
  with or without a path. The pinned tokenizer gives the model no signal distinguishing "this period
  ends a domain" from "this period ends a sentence."
- The original test URL's `"lighthouse-log"` path fragmenting into `"l"` + `"ighthouse"` was
  confirmed to be an artifact of that specific English word's rarity in this vocabulary, **not a URL-
  structural issue** — a generic path word (`"page"`) tokenizes as one clean token in the identical
  position.

**2. No general structural candidate is justified.** The domain-dot/sentence-dot token identity is
real, but no permitted normalization can resolve it: any change that would make the model reliably
render a domain dot differently from a sentence-ending dot amounts to inserting a pronunciation cue
(effectively spelling out "dot"), which is a forbidden word-substitution/phonetic-respelling
technique, not a structural rule. Every other URL component (scheme word, `"://"`, path, query
punctuation) already tokenizes cleanly with no fixable ambiguity to target. **Per the phase's explicit
fallback, this stops here rather than forcing a workaround: the residual URL-reading imperfection is
best classified as model-native** (an inherently rare "read a URL aloud" utterance shape, and/or the
model's own acronym/domain-dot handling) — not a text-normalization gap this investigation can close.

**Consequences:** No candidate was built; no A/B was run; no tracked test was added (the finding
requires loading the real pinned model/tokenizer, which does not belong in the ordinary fast tracked
suite, matching how other model-requiring findings — e.g., the Phase 3 Male-1 gap analysis — were
handled: documented as evidence, not promoted to a tracked test). The disposable diagnostic script
and its full output remain at `files/dev-work/v0.6.5-phase5-chatterbox-url-diagnostic/`
(gitignored). This closes the URL-pronunciation thread for Phase 5 unless new evidence (e.g., a
demonstrated case with a genuinely different failure shape) reopens it; per instruction, this does
not move to generation-parameter research in this run.

— Investigated by Claude Code per the maintainer's Phase 5 authorization; no maintainer ruling
required (investigation-only, no subjective judgment made), 2026-09-21

---

## 2026-09-21 — v0.6.5 Phase 5 iteration 5 verdict: approved structural-colon candidate carried
forward for later integration; HTTPS URL pronunciation still fails

**Decision.** Having listened to all three seeded A/B pairs from the fifth Phase 5 A/B experiment
(the structural-colon-preserving `punc_norm` candidate against the pinned wheel's own blanket
colon-to-comma replacement, on `chatterbox-male-1`), the maintainer reported, per seed and per test
case:

- **Seed 0: B preferred. Seed 1: B preferred. Seed 2: B preferred.**
- **6:45 / 7:15: B PASS. 3:1: B PASS. Ordinary prose colon: B PASS.**
- **HTTPS URL: still FAIL** (both A and B render it incorrectly — the colon fix did not resolve the
  URL specifically).
- **Overall: B preferred.**

**Ruling: carry the structural-colon normalization candidate forward for later Phase 6
integration. Do not integrate it yet.** The residual URL failure is carried into a further,
targeted Phase 5 iteration (recorded separately above) rather than blocking this candidate's
approval — the colon fix demonstrably resolved times, ratios, and prose colons; the URL's remaining
problem is evidently a separate, additional issue.

— Decided by maintainer (Elijah Matthew) after listening to the Phase 5 iteration 5 A/B artifacts;
recorded by Claude Code, 2026-09-21

---

## 2026-09-21 — v0.6.5 Phase 5 iteration 5 finding: the pinned chatterbox-tts==0.1.7 wheel corrupts
structural colons before tokenization; a structural (non-word-specific) candidate fixes it, not adopted

**Finding, not a fix (investigation-only; no production file changed, no generation parameter
tuned).** Traced Phase 4's cleared-for-segmentation times/ratio/URL pronunciation inconsistency one
level deeper, into the exact installed `chatterbox-tts==0.1.7` wheel `chatterbox.tts_turbo` uses.

**1. Root cause: `chatterbox.tts_turbo.punc_norm()`, called unconditionally immediately before
tokenization inside `ChatterboxTurboTTS.generate()`, performs a blanket `text.replace(":", ",")`
with no context awareness.** This is internal to the pinned wheel — nothing in `chatterbox_synth.py`
does this or could prevent it without intercepting `punc_norm` itself. "6:45" becomes "6,45"; "3:1"
becomes "3,1"; "https://example.com" becomes "https,//example.com", destroying the URL scheme
separator. Tokenizer-level proof (not just string-level): "6:45" tokenizes to `[21, 25, 2231]` but
what the model actually receives, "6,45", tokenizes to `[21, 11, 2231]` — token 25 (":") replaced by
token 11 (","), a real change to the model's input. The URL case loses a dedicated single token for
"://" (1378) entirely, re-tokenizing into unrelated pieces instead.

**2. This is a different symptom from the historical Phase 12 finding already recorded in
`chatterbox_synth.py`'s own comments** ("a text-only fix is impossible... the pause therefore has to
come from assembly"). That investigation was about recovering *pause duration* after a prose colon
(every spacing variant collapses to the same comma, so `COLON_PAUSE_MS`/`split_at_prose_colon`
supply the pause at the assembly level instead, unchanged by this finding). This finding is about
*pronunciation correctness* of structured digit:digit and URL-scheme colons, which
`split_at_prose_colon` never touches (no whitespace follows those colons, so they reach `generate()`
unprotected).

**3. A structural, non-word-specific candidate was built and evaluated, not adopted.** A colon is
replaced with a comma only when followed by whitespace or end-of-string (a prose colon — the same
principle `chatterbox_synth._PROSE_COLON` already uses elsewhere in this codebase); a colon
immediately followed by a non-whitespace character (any digit:digit form, any `://` URL scheme, or
any other structural use) is left untouched. One general regex rule, not a dictionary, not special-
cased to any exact string. Verified: preserves all four structural cases tested (both times, the
ratio, the URL) and leaves the ordinary prose-colon case byte-for-byte identical to today's behavior
(tokenizer ids confirmed identical for that case). Verified against the real, unmodified production
chunking of `quality_corpus.DIFFICULT_SHORT`: the candidate's output differs from the real wheel's
at exactly the 4 structural-colon character positions across the 4 real chunks, and nowhere else.

**4. Evaluated across 3 matched seeds (`chatterbox-male-1`, real reference conditioning, current
production `generation_params()` unchanged) for a small repeated set rather than one pair, since
generation is stochastic.** All 6 files (3 seeds × 2 sides) produced valid, non-clipping audio;
durations stayed in the expected 74–82 s range for this text at this voice. No listening verdict was
requested or given in this finding — evidence only, per the plan's investigation order.

**Consequences:** `files/tests/test_chatterbox_punc_norm_evidence.py` added (6 tests, all passing,
no model/network required — pure text-function tests) documenting the found defect and the
ordinary-prose-colon non-defect, in the same "found, not fixed" spirit as the existing Ascended/
Tamar and NLTK i.e./e.g. guards. No `chatterbox_synth.py` line changed; the installed wheel was never
edited on disk. The candidate remains a Phase 5 finding only — whether to adopt it (and by what
mechanism, since it cannot be shipped by editing the pinned third-party wheel) is a decision for a
later Phase 5 iteration or Phase 6, not made here.

— Investigated by Claude Code per the maintainer's Phase 5 authorization; no maintainer ruling
required (investigation/candidate-evaluation only, no subjective judgment made), 2026-09-21

---

## 2026-09-21 — v0.6.5 Phase 5 iteration 4 verdict: combined Edge candidate (PCM assembly +
abbrev_types segmentation) APPROVED for Phase 6 integration, not integrated yet

**Decision.** Having listened to the neutral-labeled A/B pairs on both `difficult_short` and
`structural_stress` from the fourth Phase 5 A/B experiment — production's Edge direct/rich path
against the two approved candidates combined (PCM-domain assembly, one final encode; NLTK
`abbrev_types` i.e./e.g. fix; current pause behavior unchanged) — the maintainer **preferred
candidate B on both texts.**

**Ruling:** the **combined Edge candidate is APPROVED for later Phase 6 integration**:
1. PCM-domain direct/rich assembly with one final MP3 encode.
2. NLTK/Punkt `abbrev_types` extension for i.e./e.g.

**Current production terminal-pause behavior remains unchanged** (iteration 3's candidate stays
rejected). **Do not integrate any Edge candidate yet** — Phase 5 continues (Chatterbox work is next)
before any Phase 6 integration phase begins. The disposable build scripts and evidence for all four
Edge iterations remain under `files/dev-work/v0.6.5-phase5-*-ab/` (gitignored), for reference when
Phase 6 integration is eventually authorized.

— Decided by maintainer (Elijah Matthew) after listening to the Phase 5 iteration 4 A/B artifacts;
recorded by Claude Code, 2026-09-21

---

## 2026-09-21 — v0.6.5 Phase 5 iteration 3 verdict: terminal pause-supersede candidate REJECTED

**Decision.** Having listened to the neutral-labeled A/B pairs for both test texts
(`structural_stress` and `two_chapter`) from the third Phase 5 A/B experiment — current production's
stacked terminal silence (paragraphpause + chapter_trailing_pause + end_of_book_pause, ~5.9–5.97 s)
against the candidate that lets `end_of_book_pause` supersede the lower-level pauses at the book's
terminal boundary (~3.0–3.1 s) — the maintainer reported **no preference on either text and could
not perceive a meaningful difference.**

**Ruling: the terminal-pause-supersede candidate is NOT approved for integration.** Current
production pause behavior — including the terminal stacking the candidate targeted — is
**preserved unless later evidence justifies revisiting it.** This is a rejection, not a deferral:
future Phase 5 work should not re-propose the same candidate without new evidence.

**What remains approved:** only the two candidates from iterations 1 and 2 (PCM-domain assembly;
NLTK `abbrev_types` i.e./e.g. extension) — both still unintegrated, pending further Phase 5 work
(including a combined-compatibility check) before any Phase 6 integration.

— Decided by maintainer (Elijah Matthew) after listening to the Phase 5 iteration 3 A/B artifacts;
recorded by Claude Code, 2026-09-21

---

## 2026-09-21 — v0.6.5 Phase 5 iteration 2 verdict: NLTK abbrev_types i.e./e.g. segmentation
candidate approved for later integration, not integrated yet

**Decision.** Having listened to the neutral-labeled `A.mp3` (current production Punkt
segmentation, which false-splits at "i.e."/"e.g.") and `B.mp3` (the same production code with
`sent_tokenize` swapped for NLTK's own default Punkt model plus `"i.e"`/`"e.g"` added to its
existing `abbrev_types` set — no new dependency, assembly/encoding held constant) from the second
Phase 5 A/B experiment, the maintainer **preferred candidate B**, noting the audible difference was
subtle, and preferred **B's slightly shorter/more natural gaps.**

**Ruling:** carry the NLTK/Punkt `abbrev_types` candidate forward for later integration. **Do not
integrate it yet** — Phase 5 continues with further isolated experiments before any integration
phase begins.

**What this does and does not authorize.** This is a listening verdict on the mechanically
demonstrated difference (10 vs. 8 sentences on `DIFFICULT_SHORT`; identical trailing silence and
segmentation on every other corpus item; ~1,842 ms shorter duration from two fewer 800 ms
sentence-pauses; ~0.1 dB dBFS difference, consistent with assembly being held constant) — it does not
by itself authorize touching `epub2tts_edge.py`, does not combine with the iteration 1 assembly
candidate (also approved, also not yet integrated), and does not open Phase 6. The disposable build
script and evidence remain at `files/dev-work/v0.6.5-phase5-segmentation-ab/` (gitignored), for
reference when Phase 6 integration is eventually authorized.

— Decided by maintainer (Elijah Matthew) after listening to the Phase 5 iteration 2 A/B artifacts;
recorded by Claude Code, 2026-09-21

---

## 2026-09-21 — v0.6.5 Phase 5 iteration 1 verdict: Edge PCM-domain assembly (candidate B) approved
for Phase 6 integration, not integrated yet

**Decision.** Having listened to the neutral-labeled `A.mp3` (real production direct/rich assembly)
and `B.mp3` (the same raw Edge network audio, same segmentation, same pause constants/order, same
final format, reassembled in a PCM/lossless domain with exactly one final MP3 encode instead of A's
3–5 avoidable intermediate re-encodes per multi-sub sentence) from the first Phase 5 A/B experiment,
the maintainer **preferred candidate B — it sounds clearer.**

**Ruling:** carry candidate B forward as the **approved** assembly candidate for later Phase 6
integration. **Do not integrate it yet** — Phase 5 continues with further isolated experiments
(segmentation, pause policy, Chatterbox) before any integration phase begins.

**What this does and does not authorize.** This is a listening verdict on the *mechanically
demonstrated* difference (196 vs. 61 MP3 encode generations for the measured corpus item; 1.56 dB
speech-only level shift; identical duration, trailing silence, and segmentation otherwise) — it does
not by itself authorize touching `epub2tts_edge.py`, does not combine with any other Phase 5
variable (segmentation, pause values), and does not open Phase 6. The disposable build script and
evidence remain at `files/dev-work/v0.6.5-phase5-edge-ab/` (gitignored), for reference when Phase 6
integration is eventually authorized.

— Decided by maintainer (Elijah Matthew) after listening to the Phase 5 iteration 1 A/B artifacts;
recorded by Claude Code, 2026-09-21

---

## 2026-09-20 — v0.6.5 Phase 4 findings: a real NLTK/Punkt false-split on Edge's direct path;
Male-1's gap and slow cadence are model-native, not segmentation

**Finding, not a fix (Phase 4 is investigation-only per plan §15; no production file changed, no
generation parameter tuned).** Proved source-span coverage across all four segmentation paths and
traced every demonstrated Phase 1/3 Chatterbox defect to its cause, per the plan's explicit
investigation order (segmentation/context first, generation-parameter tuning only later and only if
authorized).

**1. Source-span coverage proven for all four current paths, two of which had no runtime guard
before this phase.** New `files/tests/test_segmentation_source_span.py` (37 tests) proves, against
the real QA corpus, that `chatterbox_synth.split_for_chatterbox`, `batch_convert.split_into_chunks`,
`kokoro_synth.split_into_chunks`, and the Edge direct/rich path's own NLTK `sent_tokenize` +
`intra_sentence_chunks` composition all preserve every non-whitespace character, in order.
Chatterbox already enforced this in production (`ChunkPlanError`); the other three did not.

**2. One real, demonstrated segmentation defect was found, specific to Edge's direct/rich path.**
That path inserts an audible 800 ms `sentencepause` after every NLTK `sent_tokenize` boundary, and
Punkt incorrectly treats "i.e." and "e.g." as sentence-ending abbreviations on the plan's
`DIFFICULT_SHORT` false-boundary corpus — splitting one continuous sentence into three, each
boundary earning an unwanted mid-sentence pause. "vs." and every title abbreviation (Dr./Mr./Mrs./
Prof.) are handled correctly by the same tokenizer on the same text, so this is a specific, narrow
gap, not a general failure. Chatterbox's final packed chunks never split any of the 13 false-boundary
markers (over-splitting at the sentence level is harmless there — packing rejoins consecutive units
with a plain space and no pause, absent a coincidence with the 300-char ceiling); Edge folder/batch
and Kokoro never split this corpus item at all (under both ceilings). The defect is therefore
Edge-direct-path-specific: the other three paths never pause per NLTK sentence.

**3. A bounded pysbd evaluation was performed and is not adopted.** The i.e./e.g. finding meets the
plan's bar for comparing NLTK/Punkt against pysbd. pysbd was installed only into an isolated
`pip install --target` scratch directory under `files/dev-work/` — never added to
`requirements.txt`, never imported by production code or by the tracked test suite — and run against
the identical corpus: zero false splits at "i.e."/"e.g." and no regression on any of the other 12
markers, with content-preservation intact. This is real, evidence-backed grounds for Phase 5's
decision gate (adopt pysbd, patch an abbreviation exception list, or accept the gap as-is); no
dependency was added and no code path was changed.

**4. Times, a ratio, and the HTTPS URL reach every engine's model input as one intact, unsplit
string.** "6:45", "7:15", "3:1", and `https://example.com/lighthouse-log` survive whole in all four
paths — the prose-colon rule correctly excludes them because none has whitespace immediately after
its colon. Since the text is byte-identical across voices, any cross-voice reading inconsistency for
these strings is necessarily model-native sampling behavior, not a segmentation or context-loss
defect. No dictionary replacement, per-word hack, or source-text rewrite was made or considered.

**5. Chatterbox Male-1's ~11.8 s gap (Phase 3: localized to generation output) does not reproduce on
identical input, confirming model-native sampling rather than a structural/chunk defect.** Real
production `chatterbox_file_to_mp3` was re-run against the exact `LONGER_STRESS` text for
`chatterbox-male-1`, instrumented to scan each chunk's own raw PCM for internal quiet spans before
MP3 encoding. Result: 51 chunks, zero raw newlines survived into any `generate()` call (the v0.6.1
Phase 12 fix still holds), and zero chunks produced an internal quiet span ≥3 s anywhere — the exact
class of anomaly Phase 3 found. This run's own reconstructed timeline places chunk 10 of 51 at
130.540 s–151.895 s, almost exactly bracketing Phase 3's original 140.520 s–152.300 s gap — strong
circumstantial localization to that chunk's text (clean prose, one ordinary mid-sentence colon, no
newline/ellipsis/dialogue quote), which rendered normally this time. The same clean text and the
same deterministic chunk boundaries produced the anomaly once and not the next time: this rules out a
chunk-boundary or segmentation cause and is consistent with rare, non-deterministic model-sampling
behavior, unlike the historical Chapter 1144 newline defect, which was 100% text-reproducible.

**6. Male-1's slower cadence is cleared of a segmentation cause by the same logic.**
`split_for_chatterbox` takes no voice parameter, so chunk boundaries, chunk count, and total
inserted pause time are identical across Chatterbox voices for the same text. Yet the Phase 1
manifest shows Male-1 consistently renders ~13–15% more total duration than Female-1 for the exact
same text across three different-length samples (76.00 vs 67.12 s; 335.86 vs 294.77 s; 730.40 vs
637.80 s) — a consistency across text lengths far exceeding what the one isolated 11.8 s anomaly
could explain, pointing to a genuinely slower per-word speech rate as an inherent characteristic of
that voice's reference conditioning: model-native, not segmentation-driven.

**Consequences:** No `chatterbox_synth.py`, `batch_convert.py`, `kokoro_synth.py`, or
`epub2tts_edge.py` line changed; no generation parameter tuned. `files/tests/test_segmentation_source_
span.py` added (37 tests, all passing) — content preservation (20), false-boundary marker survival
in Chatterbox and Edge folder/batch (14), and one test documenting (not asserting as correct) the
NLTK i.e./e.g. false split, in the same spirit as the existing Ascended/Tamar guards (P9): expected to
need updating if a future phase fixes it. Phase 5 inherits three real decisions: whether to address
the NLTK false split (pysbd is now an evidenced, non-adopted candidate); how to treat Male-1's slower
cadence and rare silence anomaly (both model-native — mitigation, if any, is generation-parameter
research, or accept as inherent voice character); and that no segmentation remedy exists for the
times/URL pronunciation variance, so P9's no-hack rule leaves it either accepted or unaddressed.

— Investigated by Claude Code per the maintainer's Phase 4 authorization; no maintainer ruling
required (investigation-only, no subjective judgment made), 2026-09-20

---

## 2026-09-20 — v0.6.5 Phase 3 findings: Edge's direct/rich path has a demonstrable avoidable-re-encode
defect; Chatterbox Male-1's ~11.8s gap is generation output, not assembly

**Finding, not a fix (Phase 3 is investigation-only per plan §15; no production file changed).**
Root-caused, with mechanical instrumentation rather than arithmetic guesswork, the trailing-silence
and re-encode questions plan §6/§7 raised about Edge's three assembly paths, and localized (without
opening Phase 4's text-correlation work) the Chatterbox Male-1 long-silence class of defect.

**1. Edge's direct/rich path (`epub2tts_edge.py`) re-encodes the same sentence audio 3–5 times
before the paragraph ever reaches lossless FLAC.** `trim_tts_chunk_file` and `append_silence` are
both pure PCM edits (trim silence; append digital zeros) but both write back through
`_export_audio`, which re-encodes to MP3 purely because the temp file's extension is `.mp3`. A
temporary instrumentation wrapper around `_export_audio`/`run_edgespeak` (removed immediately after
one measurement call; no production line touched) counted, on a real run: raw-network(1) →
trim-reencode(2) → pause-reencode(3) for a plain sentence, and up to 5 generations for a
comma/ellipsis/dash-split one. `folder_batch` (`batch_convert.merge_mp3s`) needs only 2 (raw +
one unavoidable merge-encode to stitch independently-fetched network chunks) — the same overhead its
historical v0.5.0-era reference already carried. This is the *identical* anti-pattern this codebase
already found and fixed for both other engines: Chatterbox's own code comment records measuring
5.67 dB of SNR lost to one unnecessary MP3 generation before switching to assemble-in-PCM/encode-once
(v0.6.1 Plan 4 Phase 12); Kokoro already does the same. Measured confirmation: speech-only dBFS
(leading/trailing silence excluded, so this cannot be silence dilution) is −19.20 dBFS raw, −19.66
dBFS folder/batch, **−21.32 dBFS direct** — a genuine ~2.1 dB shift consistent with the maintainer's
"more noticeable background/static" report on the direct path specifically.

**2. The three-path trailing-silence progression (raw 860 ms → folder/batch 3,930 ms → direct
5,860 ms) is fully explained by configured constants stacking, not a bug in any single constant.**
Direct's 5,860 ms = `paragraphpause` (850 ms, baked into the last sentence) + `chapter_trailing_pause`
(2,000 ms) + `end_of_book_pause` (3,000 ms) = 5,850 ms configured + ~10 ms natural residual, confirmed
stage-by-stage by the same instrumentation. Folder/batch's 3,930 ms = the raw chunk's own ~860 ms
tail + `CHUNK_PAUSE_MS` (50 ms, applied unconditionally even after the last chunk) +
`END_RECORDING_SILENCE_MS` (3,000 ms) = 3,910 ms predicted vs. 3,930 ms measured. Left as an open
question for Phase 4/5: `chapter_trailing_pause`/`end_of_book_pause` each fire only once per real
book (the true last chapter), so this 5.86 s stack may be an artifact of testing a short
single-chapter QA item rather than a defect that shows up in a real multi-chapter book — not tested.

**3. Chatterbox Male-1's confirmed ~11.8 s internal near-silence is generation output, not
assembly/silence-insertion, not encoding, and not duration/container handling.** Localized (no
resynthesis — read the existing Phase 1 evidence file) to
`files/dev-work/quality-suite/chatterbox_chatterbox-male-1/longer_stress.mp3`, 140.520 s–152.300 s
(11,780 ms, matching "~11.8 seconds" exactly), using the same exact-zero-sample-run-vs-model-floor
technique the v0.6.1 Plan 4 Phase 12 silence audit used to separate assembly's inserted `np.zeros`
(which survive MP3 encode as literal digital zero) from the model's own near-silent output (never
exact zero). The span is 99.5% non-exact-zero, RMS −66.79 dBFS against ≈−26 dBFS in the immediately
surrounding speech, with a measurable −32.7 dBFS peak — not digital silence, and not bordered by any
assembly-inserted exact-zero run (the file's only long exact-zero run is its intentional 3.05 s
terminal end-silence). Same *class* of defect as the historically-diagnosed Chapter 1144
dialogue-quote sentence-boundary case, but the specific text cause was deliberately not chased —
that correlation work belongs to Phase 4, per the plan's explicit investigation order.

**4. Kokoro inspected, confirmed clean, not touched.** `kokoro_synth.py` already assembles every
chunk in PCM and encodes to MP3 exactly once, matching Chatterbox's fixed pattern; no defect found,
nothing retuned.

**Consequences:** No `voice_registry.py`, `epub2tts_edge.py`, `batch_convert.py`,
`chatterbox_synth.py`, or `kokoro_synth.py` line changed. Two disposable, gitignored QA scripts were
written under `files/dev-work/` (`v0.6.5-phase3-edge-audit/instrument_direct_path.py`,
`v0.6.5-phase3-chatterbox-audit/localize_silence.py`) for Phase 5 to reuse when A/B-testing a
candidate PCM-domain redesign of the direct/rich path's trim/pause steps — no candidate was selected
or integrated. Phase 4 inherits: the Male-1 text-correlation question, and whether the direct path's
silence stacking is a real-book problem. Phase 5 inherits: the demonstrated avoidable-re-encode
finding as its leading Edge assembly candidate.

— Investigated by Claude Code per the maintainer's Phase 3 authorization; no maintainer ruling
required (investigation-only, no subjective judgment made), 2026-09-20

---

## 2026-10-01 — Strip only recognised embedded MP3 join metadata before strict decoding

**Confirmed defect and bounded decision.** The macOS MP3-Tool-3/-4 44-track Book
accepted Intro and Synopsis but refused all 42 chapters. These chapters are raw
concatenations of independently tagged 24 kHz mono MP3 segments. At each interior
boundary, FFmpeg 9.0.1's parser presents the complete ID3 tag plus non-audio Info
frame as an audio packet. Strict decoding exits 183 with `Header missing`; this
is a container boundary problem, not corrupt MPEG audio. Intro/Synopsis contain
no interior tags. Independently decoding Chapter 3161's ten segments is clean.

Preserve the 2026-09-20 fully decoded duration contract: no header estimate,
Mutagen/ffprobe fallback, relaxed tolerance, ignored decoder error or partial
progress acceptance. Walk Layer III frame lengths and recognise only complete
ID3 metadata with validated frame lengths/padding, followed by a matching
Info/Xing frame with empty side information at a frame boundary. Never search/strip
signatures inside audio payload. Unknown,
truncated or damaged structure stays intact for strict decoding to reject.

For this recognised structure only, construct a private temporary input with
those metadata bytes removed, retaining every MPEG audio byte. Decode the entire
result with the existing audio-only `-xerror`, sample-derived timestamps and
exit/stderr/progress checks. Use that same corrected input for copy/append/trim,
including Combine's constituent staging. Operation copies live in private
staging; standalone duration scratch lives in ignored runtime-data/temp. Each
owned temporary directory is removed on exit, including failure. Originals are
never opened for writing. This narrowly updates the old no-temporary-audio
implementation detail; its duration authority and publication contract stand.

**Mechanical proof.** All 42 actual chapters become error-free strict decodes;
PCM is byte-identical to the audio normal playback decodes from the originals.
Repo-contained generated tones reproduce the exact concatenation structure and
exercise signed Time, Write ID3, Combine FAST/Safe, the shared controller,
source hashes, scratch cleanup and whole-Book refusal on damaged tag/header/
side-information bytes. The original stale Info/Xing regressions remain intact.
No dependency, UI, application version or unrelated v0.6.7 behavior is changed.

**Checkpoint disposition (maintainer-authorized, 2026-10-01).** MP3-Tool-5's
manual macOS rerun passed: one Book, 44 completed, zero failed/skipped/not
attempted, all previously failing chapters processed and whole Book published.
Complete verification remains FAIL (7,882 passed / 93 skipped / 16 failures).
All 16 test IDs and complete XML failure elements (type/message/traceback) match
exactly on the fix and untouched `62b0c095`; no normalization is required. The
baseline worktree is clean, failing test blobs are unchanged, and failure stacks
never enter the changed processing module. The maintainer authorized the bounded
commit/push on that proof. This is not a full-gate PASS or an unrelated-failure
waiver. Preserve the failures; do not expand this task into UI/layout/import work.

**Authority:** maintainer's bounded regression-fix and disposition instructions,
2026-10-01.

---

## 2026-09-20 — MP3 Time calculations and validation use fully decoded audio duration

**Decision (maintainer-authorized MP3 defect remediation on the v0.6.5 branch; no phase
advance).** Keep the public `mp3_processing.ffprobe_duration_seconds` name for compatibility,
but replace its header-only ffprobe query with a full decode through the existing proved
FFmpeg and hidden-console subprocess wrapper. Map `0:a:0`, rebuild timestamps using
`asetpts=N/SR/TB`, encode PCM to the null muxer, and read the final machine-readable
`out_time_us` in seconds. This measures actual decoded samples after decoder delay/padding,
without retaining PCM or per-frame JSON in Python and without writing temporary audio.

Require exit zero, no error-level stderr, positive duration and `progress=end`; use `-xerror`
to stop on decoding errors. Disable speculative stream-info decoding with
`-nofind_stream_info`: malformed source cover images are discarded by the MP3 Tool and
must not invalidate otherwise good audio. Audio decoding itself remains strict. The same
measurement applies before trim endpoints are calculated and when staged/combined audio is
validated. Existing tolerances, transforms, metadata rules and atomic publication stay intact.

**Why.** A 49-track Write ID3 +0.1 run failed only its split author-note source: its Info
header claimed 17,612 frames / 3,680,757 bytes, but the first piece held 16,306 frames and the
companion the other 1,306; their combined MPEG byte counts matched the retained header exactly.
Quick ffprobe and Mutagen both reported 460.068571 s, whereas only 425.940658 s decoded. The
transformation correctly produced 426.040658 s and tag/artwork writes did not alter the audio.
Zero Time also false-failed; -0.1 targeted an endpoint beyond EOF and removed nothing. Combine
shares that endpoint calculation, so a fallback only after failed Write ID3 validation would
leave a real trim defect. Broadening tolerance, swapping to Mutagen/stream.duration, and
special-casing this source were rejected. No FFmpeg upgrade is needed.

**Tradeoff and proof.** A full sequential decode costs more than reading a header, but observes
the exact audio available to the operation, catches decode errors and works for CBR/VBR and
headerless inputs. On this Mac all 49 real originals measured in about 21 s. Production
stage/tag/validate reproductions at +0.1/zero/-0.1 changed decoded sample counts by exactly
+4,410/0/-4,410. The 24-case synthetic regression in `test_mp3_duration_authority.py` uses raw
PCM length independently, includes MPEG-1 Info and MPEG-2 Xing splits and Combine FAST/Safe,
and refuses genuinely shortened output even when its header still claims the correct length.
No source or failed-run evidence was modified. Windows shares the implementation; its runtime
acceptance remains pending. No v0.6.5 listening or phase gate is superseded.

**Signed:** maintainer (diagnosis approved and implementation directed 2026-09-20);
implemented by the AI session on that authorization.

---

## 2026-09-20 — v0.6.5 Phase 2 closeout: original Male-3 candidate approved and registered; the
bounded pitch-retry variant rejected and its machinery removed entirely

**Decision (v0.6.5 Phase 2, final maintainer ruling).** After hearing both the original Male-3
candidate sample and the §14 bounded pitch-retry variant, the maintainer's ruling: **Male-4 —
approved, unchanged.** **Male-3 original candidate — approved.** **Male-3 pitch-retry variant —
rejected:** "I prefer the original voice exactly as it was before the retry." This supersedes the
2026-09-20 entry below on Male-3's disposition only; that entry's account of what the retry was and
how it was built stands as an accurate historical record of a rejected approach, not of anything
still in the codebase.

**1. Original Male-3 is registered exactly as its untouched candidate sample, with no pitch or
timbre adjustment reaching production.** `chatterbox_synth.REFERENCE_VOICES["chatterbox-male-3"]`
binds to the already-recorded `Male-3.mp3` hash (never recomputed — the source file was never
written to at any point in Phase 2, including during the retry), and `voice_registry.VOICES` gains
`chatterbox-male-3` / "Chatterbox - Male 3" immediately before `chatterbox-male-4`, using the same
shared, unmodified `_chatterbox_preset()` as every other Chatterbox row. `REFERENCE_VOICES` grows
from five to six; the registry total moves from 15 to 16 rows. `CANDIDATE_REFERENCE_VOICES` is now
`{}` — both candidates resolved — but is kept in place as reusable infrastructure for whatever
future candidate a later phase introduces; it is explicitly not retry-specific and was not removed.

**2. The rejected retry's machinery is deleted outright, not deprecated.** Because the maintainer's
own words ("no longer represents supported behavior") ruled out keeping it as dead code behind a
flag, `generate_voice_samples.py` loses `MALE3_RETRY_PITCH_RATIO`, `MALE3_RETRY_SUBDIR`,
`_pitch_shift_preserve_tempo()`, `render_male3_pitch_retry()`, and the
`--chatterbox-male3-pitch-retry` CLI flag with its dispatch branch. `CHATTERBOX_CANDIDATE_VOICE_IDS`
is now `()`. New regression tests in `test_chatterbox_candidates.py` assert each of those symbols
and that CLI flag are gone, so the rejected path cannot silently reappear. The reusable
candidate-evaluation path itself (`run_chatterbox_candidate_evaluation`, the `--chatterbox-candidates`
flag, the candidate text/subdir helpers) is untouched — it is generic infrastructure, not the
rejected mechanism.

**3. No other voice or generation behavior was touched.** Chatterbox generation parameters, pacing,
segmentation, and conditioning logic for every other voice are unchanged; only the registration
state of Male-3 moved from candidate-only to production.

**Consequences:** Twelve tracked test files' Chatterbox-count/voice-count assumptions moved from
15/5 to 16/6 (retargeted, never weakened): `test_chatterbox_boundaries.py`,
`test_chatterbox_candidates.py`, `test_chatterbox_engine.py`, `test_chatterbox_evaluation.py`,
`test_chatterbox_integration.py`, `test_epub_retirement.py`, `test_fatal_diagnostics.py`,
`test_mp3_finalization.py`, `test_tts_importing.py`, `test_tts_jobs.py`, `test_tts_smoke.py`,
`test_voice_labels.py`. Full suite: 7428 passed, 57 skipped, 0 failed, in 9:53; `compileall` clean.
Both `Male-3.mp3` and `Male-4.mp3` re-verified byte-for-byte unchanged against their registered
hashes immediately before this closeout. Phase 2 is fully complete; Phase 3 requires its own
separate authorization.

— Decided by maintainer (Elijah Matthew); implemented by Claude Code, 2026-09-20

---

## 2026-09-20 — v0.6.5 Phase 2 §14 remediation: Male-4 approved and registered; Male-3 rejected for
a single bounded pitch-only retry on a scratch reference-conditioning clip

**Decision (v0.6.5 Phase 2, §14 manual-gate-failure/rollback protocol).** The maintainer's listening
verdict against the two candidate WAVs: **Male-4 — approve.** **Male-3 — reject for bounded retry
only:** "otherwise good, make it ever so slightly deeper... only a very small timbre/pitch
reduction. Do not otherwise change its pacing, generation settings, clarity, or character."

**1. Male-4 is now a registered production voice, exactly as approved.** Moved verbatim from
`chatterbox_synth.CANDIDATE_REFERENCE_VOICES` into the production `REFERENCE_VOICES` (same
`source_name`, same hash — no hash was recomputed, the source file was never touched) and appended
to `voice_registry.VOICES` as `chatterbox-male-4` / "Chatterbox - Male 4", using the exact shared,
unmodified `_chatterbox_preset()` every other Chatterbox row uses (no per-voice tuning, per §6).
`REFERENCE_VOICES` grows from four to five; the existing frozen-set test
(`test_mp3_finalization.py::test_the_settled_chatterbox_values_are_untouched`) is updated to five
with an explanatory comment, not weakened. The registry total moves from 14 to 15 rows; every
count/index-based test across nine files was retargeted to match.

**2. Male-3's retry is a pitch-only adjustment to a scratch copy of its reference-conditioning
clip, never to `Male-3.mp3` and never to the cached production derivative.** New
`generate_voice_samples.render_male3_pitch_retry()` reuses `chatterbox_synth.build_reference_clip`
(the same 15s leading-window extraction production uses) to make a scratch copy, applies a single
ffmpeg `asetrate`+`atempo` pitch shift (no new dependency — ffmpeg is already required and already
the exact binary `build_reference_clip` shells out to) to that copy only, and conditions the model
on the shifted copy directly via `model.prepare_conditionals()` — bypassing the cached
`derivative_path`/`conditionals_path` identity system entirely, so no other voice's cache and no
global generation parameter is touched. Generation itself uses the unmodified
`generation_params()` (current production temperature/top_p/top_k/repetition_penalty) and the same
`CHATTERBOX_CANDIDATE_TEXT` every other candidate reads.

**3. The bounded value: `MALE3_RETRY_PITCH_RATIO = 0.97`** (~3% lower, roughly half a semitone) —
a single value, not a ladder, per the explicit instruction to try one minimal adjustment before
considering anything broader. A real ffmpeg math error was caught and fixed before this value was
trusted: the first attempt used `atempo=pitch_ratio`, which lengthened the reference clip's
duration by ~6.3% instead of preserving it; the corrected filter (`atempo=1/pitch_ratio`) was
verified to hold duration to within 0.05% (15.0000s → 15.0075s) before the real retry was run.

**4. Output goes to a clearly distinct filename beside the original candidate sample, which is
never regenerated or overwritten.** `chatterbox-male-3-pitch-retry.wav`, alongside the untouched
original `chatterbox-male-3.wav`, both under `files/test-for-manual-listen-elmatthe/
chatterbox-candidates/` (gitignored). The retry's own scratch artifacts (the plain and pitch-shifted
reference-conditioning clips) live under `files/dev-work/male-3-pitch-retry/`, separate from any
listening artifact.

**Consequences:** `CHATTERBOX_CANDIDATE_VOICE_IDS` now holds only `chatterbox-male-3`; Male-4 is
removed from the candidate pool entirely (it is production now, not pending). Nine tracked test
files' Chatterbox-count assumptions moved from four to five approved voices, and
`test_chatterbox_candidates.py` was substantially rewritten to reflect Male-4's departure from
"candidate" status and to add coverage for the new retry mechanism (mocked — no real recording,
model, or ffmpeg call). Male-3 remains unapproved and unregistered; only the maintainer's next
listening pass decides whether this one bounded adjustment is sufficient.

— Decided by maintainer (Elijah Matthew) per the plan's §14 protocol; implemented by Claude Code,
2026-09-20

---

## 2026-09-20 — v0.6.5 Phase 2: multilingual Edge voices removed; Male-3/Male-4 evaluated on a
separate candidate path that reuses the production reference/conditioning machinery without
touching it

**Decision (v0.6.5 Phase 2 — voice inventory + Chatterbox candidates).**

**1. `en-US-AndrewMultilingualNeural` and `en-US-AvaMultilingualNeural` are removed from
`voice_registry.VOICES` entirely**, not relabeled or deprecated in place, per the plan's final
voice inventory (Section 3). Fourteen rows remain: five Edge, five Kokoro, four Chatterbox.
Ordinary Andrew and Ava are unaffected. Every count-based test that assumed sixteen/twelve/seven
rows (`test_tts_smoke.py`, `test_voice_labels.py`, `test_chatterbox_boundaries.py`,
`test_chatterbox_evaluation.py`, `test_chatterbox_integration.py`, `test_chatterbox_selected_tuning.py`,
`test_epub_retirement.py`, `test_fatal_diagnostics.py`, `test_tts_importing.py`, `test_tts_jobs.py`)
was updated to the new counts/indices; none had its actual invariant weakened.

**2. Male-3/Male-4 get a genuinely separate evaluation path, not a widened historical one.**
`chatterbox_synth.REFERENCE_VOICES` (the four approved, production voices) is frozen at exactly
four entries — an existing test already pins this
(`test_mp3_finalization.py::test_the_settled_chatterbox_values_are_untouched`) and continues to.
The two candidates live in a new, separate `CANDIDATE_REFERENCE_VOICES` dict instead.
`get_reference_voice(voice_id)` now checks `REFERENCE_VOICES` first, then
`CANDIDATE_REFERENCE_VOICES` — the one seam every existing reference/derivative/conditioning
function (`resolve_reference`, `prepare_reference_clip`, `derivative_path`, `conditionals_path`,
`voice_availability`) already goes through, so candidates get the exact same hash-binding,
derivative-caching and P8 safety contract as the four approved voices for free, with no
duplicated machinery and no risk of a parallel implementation drifting from the original.

**3. Candidates render under current production generation settings
(`generation_params()`), not the historical Phase 9 temperature
(`phase9_evaluation_params()`).** The plan (Section 5) is explicit that candidates are judged
against what an audiobook actually sounds like today, not the historical approval contract the
four-voice evaluation must keep reproducing untouched. `run_chatterbox_evaluation` (the historical
four-voice command) is not modified at all; `run_chatterbox_candidate_evaluation` is a new,
independent function reusing only the generic, already-shared table/report formatters
(`format_chatterbox_table`, and a candidate-specific report wrapper with its own approval-language
footer). Both candidates read the same evaluation sentence the four approved voices did
(`CHATTERBOX_CANDIDATE_TEXT = CHATTERBOX_EVAL_TEXT`), so the comparison is about the voice, not a
different script.

**4. Hashes computed and cross-verified by two independent methods (certutil and Python
hashlib) on HOME-PC, 2026-09-20, against the maintainer-placed files:**
`files/Chatterbox-Voice-Uploads/Male-3.mp3` →
`0bb698d934515c690b97c85922dcfb61a0e2e07f07fd66b4e0b2e8ca13c292c4`;
`files/Chatterbox-Voice-Uploads/Male-4.mp3` →
`1db9bb339748edede0b8d6a20171ea0672e59914516e49fd9b1b910cc6f028f5`. Both files were only ever
read, never written to; `git status` shows no change under `files/Chatterbox-Voice-Uploads/`, and
the hashes were re-verified identical immediately after the candidate WAVs were rendered.

**5. No tracked test touches the real recordings.** Every existing Chatterbox test stubs
`resolve_reference`/`prepare_reference_clip`/etc. at the engine seam rather than reading real
files (`protected_uploads_dir()` monkeypatched to `tmp_path`); the new
`files/tests/test_chatterbox_candidates.py` follows the same convention, so the suite runs
identically on a machine that has never seen the two candidate recordings. Hash verification
against the real files is a one-off manual check recorded here and in `Handoff.md`, not a tracked
test — consistent with how the four approved voices' real files were never asserted against in
the tracked suite either.

**Consequences:** `voice_registry.VOICES` is untouched by this drop — no `chatterbox-male-3` or
`chatterbox-male-4` row exists there, and none will unless and until the maintainer's listening
gate (Section 5) returns a `YES` for a given candidate in a later phase. `REFERENCE_VOICES`
remaining frozen at four is a private implementation detail of `chatterbox_synth.py`, not
something Phase 2 is scoped to change.

— Decided by maintainer (Elijah Matthew) per the plan; implemented by Claude Code, 2026-09-20

---

## 2026-09-20 — The chapter-title remux pins its movie timescale, an ffmpeg error is a failure at any exit status, and chapter validation reads structure, not titles

**Decision (v0.6.4 defect, bounded remediation carried onto `feature/0.6.5-tts-quality-refactor`
as a cherry-picked fix commit; no v0.6.5 plan phase is affected).** Three rules, each protected by
a real-FFmpeg test in `files/tests/test_m4b_chapter_remux_timescale.py` and the Editor engine
suite:

1. **`shared.metadata.apply_chapter_titles` passes `-movie_timescale 1000`
   (`CHAPTER_REMUX_MOVIE_TIMESCALE`) and stays `-c copy`.** FFmpeg 9's mov muxer defaults the
   movie timescale to the lcm of the mapped streams' timescales; with 44.1 kHz audio beside a
   1/90000 cover-art video stream the chapter text track lands at 4,410,000 ticks per second and
   every chapter longer than INT_MAX / 4,410,000 ≈ 487 s is dropped from it with exit status 0.
   1000 is what every earlier FFmpeg wrote, what the sources themselves carry, and what the
   Editor's outputs must keep carrying. The M4B Maker's concat maps audio only (lcm 44100, ~13.5 h
   per chapter) and is not changed; the Editor's remux is the one path that maps the cover video.

2. **A `-loglevel error` ffmpeg step that prints anything did not succeed.** At that level the
   only thing ffmpeg can print is an error, and the muxer's "Application provided duration … is
   invalid" was printed and ignored while the exit status said 0. `_run_chapter_remux_step`
   raises `ChapterRemuxError` on any stderr; the copy under edit is untouched and the temporary
   sibling removed. Scoped to the chapter remux — no other ffmpeg call site changed.

3. **Staged validation compares chapter structure with the source.** `validate_chapter_structure`
   requires the same chapter count, boundaries equal within 10 ms (a 1/44100 source rescaled to
   1/1000 moves at most half a millisecond), and — exactly when the remux ran
   (`chapter_titles_retitled`, the same predicate `stage_book` uses) — a QuickTime chapter text
   track with one sample per chapter; when it did not run, the track must simply be unchanged, so
   a `chpl`-only source stays valid. ffprobe merges `chpl` and the text track by id, which is why
   titles alone passed a one-sample track whose surviving title sat at id 0.

**Why the tests missed it.** Every generated fixture had chapters of a few seconds, the Phase 13
positional chapter edit ran on a 50-second fixture, and the real hour-per-chapter file received no
chapter edit. The new fixtures are 660 s with a cover and a 600 s chapter; the negative control
forces the pathological timescale explicitly so the proof does not depend on the host FFmpeg's
default.

**Signed:** maintainer (investigation, remediation and carry-forward directed 2026-09-20);
implemented by the AI session on the maintainer's authorization.

---

## 2026-09-18 — v0.6.4 confirmed merged (PR #11); v0.6.5 identity reassigned to the TTS Quality
Refinement plan; the displaced Plan 9 scope is preserved and marked DISPLACED — FUTURE ALLOCATION
UNASSIGNED

**Decision (v0.6.5 — TTS Quality Refinement, Phase 0).** Fresh `git fetch origin` confirmed
`origin/master` advanced to `1f9bdcf347edaad36d68e237933d3ac6036d0a42` — the merge commit for pull
request #11, merging `feature/0.6.4-m4b-maker-metadata-editor` (tip `f5f3926`). v0.6.4 is therefore
**confirmed merged**, superseding every "not merged" statement recorded in `Handoff.md` and the
Master Index as of the v0.6.4 Phase 15 closeout — those statements were accurate when written and are
not being called wrong, only overtaken by the maintainer's subsequent integration decision.
`feature/0.6.5-tts-quality-refactor` was created from that verified `origin/master` and Phase 0's
baseline/audit work is recorded in `Handoff.md`.

**The v0.6.5 identity is reassigned.** The 2026-07-31 roadmap and every later note through the
2026-09-17 v0.6.4 closeout (including this file's own 2026-09-17 entry) assigned v0.6.5 to **Plan 9 —
remaining Windows UI conversion, macOS parity, QA, docs, and packaging** (proposed filename
`0.6.5-ui-parity-hardening-release.md`). The maintainer has now opened v0.6.5 as a different,
unrelated plan instead: `md-instructions/0.6.5-tts-quality-refactor.md` ("TTS Quality Refinement",
v4 Final), scoped to `scripts/Universal/tts/` audio-quality/UI work, on
`feature/0.6.5-tts-quality-refactor`. Plan 9 was never drafted and no code was ever written against
it, so nothing is reverted — only the version-number binding moves.

**Explicit maintainer ruling on disposition (2026-09-18):** preserve Plan 9's full scope intact —
conversion of all remaining Windows tool panels (TTS Audiobook, M4B Converter, Cover Image Resizer),
macOS parity, full regression/long-run drills, release-package launch testing, and the final
version/tag/release checkpoint — but mark it **"displaced / future allocation unassigned"** rather
than inventing a new version, branch, or plan number for it now. Plan 9 remains real, approved-scope
future work; it simply has no version identity until a later, separate maintainer decision assigns
one.

**Why:** The maintainer chose to spend the v0.6.5 identity on the TTS quality work now rather than on
Plan 9, and preferred to leave Plan 9's renumbering as a genuinely separate future decision rather
than have this Phase 0 checkpoint guess at a v0.6.6 (or later) slot, a branch name, or a sequencing
relative to other future work.

**Consequences:** `don't-delete/Audiobook-Creation-Tool-v0.6.x-Approved-Plan-Series-Map.md` and
`don't-delete/Audiobook-Creation-Tool-v0.6.x-Master-Implementation-Plan-Index.md` each gain a dated
supersession note recording this exact reassignment, following their own existing append/supersede
conventions; neither document's original 2026-07-31/2026-08-03 text is rewritten. Every other
reference to "Plan 9" throughout both documents (ownership of DPI awareness, `.DS_Store` packaging,
the M4B Converter's `920×600` clipping, the three remaining classic panels, the Combobox/title-bar
theming review, the final release-package gate) is unaffected — Plan 9 still owns all of it; only its
"= v0.6.5" binding is removed. No production behavior changed in this checkpoint.

— Decided by maintainer (Elijah Matthew), recorded by Claude Code, 2026-09-18

---

## 2026-09-17 — v0.6.4 closeout: the M4B Maker and M4B Metadata Editor's approved product contracts, and the macOS minimum is 1024×800

**Decision (v0.6.4 — M4B Maker + M4B Metadata Editor, Phase 14 closeout).** Both M4B tools are
rebuilt on the shared multi-Book foundation, accepted on Windows (2026-09-15, Phase 12) and on macOS
(2026-09-15, Phase 13), and these are the rules that outlive the temporary plan that carried them.
Each was approved during the plan, is implemented, and is protected by tests. The Plan 6 Decision
Register 1–55 under `don't-delete/` is not reopened or rewritten; where this entry departs from a
numbered decision or from the 2026-07-31 roadmap, the departure is recorded here as a later, dated
supersession and the original text stands as history.

**One coordinated drop, one branch — the old roadmap split is superseded.** By maintainer ruling on
2026-09-13 the two tools were delivered together as **v0.6.4** on
`feature/0.6.4-m4b-maker-metadata-editor`, replacing the roadmap's "Plan 7 / v0.6.3 Drop 2 = M4B
Maker alone" and "Plan 8 / v0.6.4 = MP3 Tool + M4B Metadata Editor", the later "v0.6.4 Maker, v0.6.5
Metadata Editor" proposal, and the Master Index §15 branch names `feature/0.6.4-m4b-maker` /
`feature/0.6.5-m4b-metadata-editor`. The MP3 half of the old Plan 8 had already shipped in the v0.6.3
focused MP3 redesign. The old Plan 9 assignment — v0.6.5 = final visual parity, hardening, packaging
and release — is unchanged. The two tools remain **two tools**: separate business models, separate
Tk-free engines, no shared processing base class, no generic "M4B mega-tool".

**One foundation, reused rather than re-implemented.** Both panels are thin Tk composition layers
over the same shared authorities the MP3 Tool consumes: `shared/book_workspace(_ui)` (Book identity,
navigation, Shared → Book precedence, `has_meaningful_work`, frozen run capture, retry dispositions),
`shared/importing` + `import_coordination` (the scan), `shared/job_control` + `job_ui` (one
`JobController` / `JobReporter` / `JobAdapter` / `LockGroup` per batch, one `SummaryDetailsView`),
`shared/output_paths` (reservation, sanitiser, collision planner, containment),
`shared/image_capabilities` (the one HEIC probe) and `shared/numbering.SuccessNumbers`. Structural
tests pin that every authority is defined in exactly one module and that no second workspace,
controller, coordinator, reservation, planner, event stream or pump class exists anywhere. Two things
are shared by the M4B family only: `mp3_tools/m4b_artwork(_ui)` (the M4B cover service and its Tk
control) and `mp3_tools/m4b_staging` (the private-staging / atomic-publication pattern both engines
delegate to). `BookNavigator` gained an opt-in action subset so a consumer may offer fewer Book
actions; its default is unchanged for the MP3 Tool.

**M4B Maker: one Book = one directory of MP3s = at most one M4B.** `Import Folder` makes one Book per
directory that directly contains MP3s (natural order, never flattened); `Add Files` extends the
current Book; Add / Duplicate (configuration, no tracks) / Remove / Previous / Next / selector are the
shared operations. **Shared fields are exactly six** — Artist / Author, Album Artist / Author, Album,
Series Name, Silence Between Tracks (seconds), Book Artwork — deliberately not the MP3 Tool's set;
**Book-only fields are Title, Series Part, Output Filename and Chapter Titles**. A populated Shared
value overrides and disables the matching Book control and leaves the Book's stored value intact. The
Maker observes no source ID3 and pre-fills nothing; the metadata vocabulary stays Title, Artist, Album
Artist, Album, Series Name, Series Part and cover — **no Year, Genre or Comment** were added merely
because another M4B component supports them. Silence is a **non-negative** gap inserted between
adjacent tracks only (never after the last; negative refused before any reservation), not the MP3
Tool's signed Time. Chapter titles are positional, one per line, defaulting to cleaned filenames, and
are frozen at Build. Fast-first (default ON) with automatic Safe fallback is preserved, Safe being
mandatory whenever silence is inserted, and the chosen path and any fallback reason are logged.

**Maker naming is Decision 51A through shared authorities only.** The output name resolves from the
explicit Output Filename → effective Title → effective Album → the unambiguous source folder name →
`Book N`, sanitised by the shared cross-platform sanitiser, `.m4b` appended exactly once, collision-
numbered by the shared planner; a blank Title takes the resolved output name as the embedded Title so
no Book is nameless. Filename and embedded Title are two values. Standard runs go directly inside one
reserved `M4B-Maker-N`; the explicit custom destination (Decision 10A) writes directly into the chosen
folder with **no nested run folder**, stages in an operation-owned temporary directory outside it, and
keeps collision safety.

**Series numbering is success-only, on both tools, through the shared allocator.** With Auto-number
ON (Start Part blank = 1; Book Series Part controls disabled) a number is proposed for a staged Book,
written onto the staged file, validated, and **committed only after publication succeeds**; a failed,
skipped or not-attempted Book consumes nothing, so A ✓ / B ✗ / C ✓ yields 1 and 2 with no gap, and a
later Retry Failed of B receives 3. The Editor's former position-based numbering (`start + index`),
which left gaps on failure, is superseded by this contract (Decision 48A applied to both consumers).

**M4B Metadata Editor: one imported file = one Book/page, and blank means preserve.** The Editor
accepts `.m4b`, `.m4a` and `.mp4`; `Import Folder` (with the shared subfolders option) and `Add Files`
create one Book per imported occurrence — the directory-to-Book grouping rule is never applied here —
with Remove / Previous / Next / selector and deliberately **no Add Book and no Duplicate Book**. Each
page is pre-filled from a frozen `SourceObservation` of its own file (seven text fields, series
provenance as `read_m4b_tags` resolves it, cover presence, chapter titles); showing a source value is
never an edit. **Blank Shared + blank/unchanged Book value = preserve the source value; blank does not
mean remove**, and a value retyped equal to its source writes nothing, so a vendor, movement or
album-implied series representation is never silently migrated to the canonical atom. **Shared starts
blank** even when every imported file agrees, so coincidence never becomes a global override; a
populated Shared value is an explicit edit for every Book and disables the matching Book control. The
seven Shared/Book text fields are Title, Author / Artist, Album, Year, Genre, Comment and Series Name,
plus artwork; **Series Part is read-back plus the Auto-number contract, never a text override**.
Chapter titles are positional with **blank-line-preserve** semantics (line N → chapter N; blank or
unchanged = leave it; extra lines ignored) — not the MP3 Tool's blank-line-collapse. No action
re-encodes audio (audio-stream MD5 proved equal).

**Three Editor actions, each a frozen plan.** **Save Tags** writes only actual intent (Shared over
Book), the explicit artwork (Shared → every Book; Book → that Book; none → preserve source artwork)
and explicit chapter edits, and touches nothing else. **Clear All Tags (keep chapters)** copies to
staging, removes identifying metadata and artwork while keeping the chapter structure, and re-applies
**only explicit** Shared/Book values, explicit replacement artwork and explicit chapter edits —
prefilled-but-unchanged values are not re-applied, otherwise the action would not clear. **Remove
Series Numbering** removes the numbering surfaces (`trkn` used as series numbering, movement
index/count, every vendor `…:PART` / `…:SERIES-PART`) and **keeps the Series Name** and every unrelated
tag, cover and chapter; `shared.metadata.clear_series_numbering` gained `keep_series_name=` for it, its
default unchanged. Clear All Tags remains the one wholesale removal. Each action reserves **one**
standard `M4B-Metadata-N` run (no custom destination) and publishes every Book flat inside it under
its own source filename, extension kept, collision-numbered.

**Every Book is staged privately and published whole or not at all.** Both engines build in
`<run>/.work/<stem>/` (the Maker's custom mode in its own temporary root), do all the work there —
audio assembly, chapters, tags, cover, series part, then a read-back validation through the shared
probe/metadata readers — and only then `os.replace` into the destination, refusing an existing file
and routing across filesystems through a plan-owned temporary sibling. A failed or cancelled Book
leaves no partial output and no staging; a publication failure retains the validated candidate for the
retry. This closes the Editor's recorded debt of copying to the final path before the tag write.
Staging cleanup asks the shared reparse-aware link authority: a link inside staging is unlinked as a
link and never followed (a Windows junction is a link too).

**Artwork on M4B is capability-driven and container-native.** The chooser filter is
`decodable_suffixes()` from the one shared probe; JPEG and PNG bytes are embedded as their own format;
HEIC/HEIF are decoded only where the probe says so and converted **in memory** to a PNG `covr` with
pixel dimensions preserved, no sidecar written, the source never resized, cropped or rewritten; an
unavailable capability is a visible refusal in both panels. The Maker resolves the cover **before**
any FFmpeg launch and embeds it on the staged file without re-encoding; the ID3 `apply_artwork` path is
deliberately not reused for MP4 containers.

**One run model and one log region, common to both.** validate → reserve → plan/freeze → lock →
execute → settle → publish; workers receive frozen values only and may consult no Tk variable, live
workspace, Shared value, file list or setting after start; Pause/Resume are acknowledged at safe
checkpoints, Cancel stops at the next boundary keeping published Books and leaving unreached Books
*Not attempted* (no Book-level "cancelled"), a failed Book does not stop later Books, and Retry Failed
re-runs only the failed Books from the original frozen plan in the same run directory. Summary |
Detailed, history kept across runs with a divider per run and per retry, Clear Log clears the visible
text only; no Copy button, no severity selector.

**Clear All Imports (maintainer-directed amendment at Phase 12).** All three multi-Book tools carry one
destructive workspace reset beside Import Folder, styled as the platform's danger button: it returns the
tool to its pristine startup workspace, keeps the visible log history, touches nothing on disk, asks
for confirmation only when meaningful work exists (any Book with work or any populated Shared value),
and is locked out while a run or an import scan is active. The Editor keeps `Clear All Imports`
(workspace) and `Clear All Tags (keep chapters)` (output copies) as two visibly distinct actions.

**Platform presentation, and the macOS minimum is 1024×800.** Windows draws both tools in the ACT
design system at the unchanged `MIN_SIZE = (920, 600)`; macOS draws them natively. Phase 13 measured
both tools in the real launcher under aqua at the 2026-09-12 floor of 1024×720 and found a genuine
Mac-only layout defect whose bounded remedies fold bands onto more lines than a 1024×720 content host
can absorb while keeping the chapter editor and log readable; the maintainer ruled on 2026-09-15 that
**`AQUA_MIN_SIZE = (1024, 800)`, which is also `AQUA_GEOMETRY`, the size the launcher opens at on
macOS**. *This supersedes, for macOS only, the 1024×720 figure in the 2026-09-12 entry below;* the rule
of that entry — the minimum is the platform's, presentation differences live behind the theme bundle as
composition hints the panels read with the Windows values as defaults, and business behaviour never
branches on platform — is unchanged and is exactly how the Phase 13 remediation was built. The Editor's
whole-form scrolling canvas, an accepted v0.6.0 Drop 1 limitation, is gone: only the chapter box and
the log scroll on either tool.

**What deliberately did *not* become a decision record.** The aqua hint token names and values, the
`ADOPTED` / hash-gate guard reconciliation sequence, the ffmetadata escaping fix and the junction fix
(Phase 11), the FFmpeg argument shapes, and the exact test counts are implementation mechanics or
enforcement of rules already approved; they live in `Handoff.md`, `Changelog.md` and the code.

*Approved across the v0.6.4 drop (Windows Phase 12 accepted 2026-09-15, macOS Phase 13 accepted
2026-09-15) and recorded at Phase 14 closeout by Claude Code. Version identity remains `0.6.2`,
unreleased; nothing merged, tagged or published.*

---

## 2026-09-12 — Focused MP3 closeout: the MP3 Tool's approved product contract, and the minimum window is the platform's

**Decision (v0.6.3 focused MP3 redesign, Phase 13 closeout).** The MP3 Tool redesign is complete
and accepted on both platforms, and these are the rules that outlive the temporary focused plan
that carried them. Each was approved during the plan, is implemented, and is protected by tests.
The numbered decisions of the Plan 6 foundation (the Decision Register 1–55 under `don't-delete/`)
are not repeated here; this entry records what the focused continuation added or superseded.

**The MP3 Tool is a multi-Book workspace with exactly two actions.** `Import Folder` makes one
Book per directory that directly contains MP3s; `Add Files` extends the current Book; Book
identity is the stable Plan 6 id, the visible number a position. The actions are **Write ID3
Tags** and **Combine MP3s → One MP3** and no third; the separate Time-edit operation, the FAST
checkbox, the combined-filename prompt and the preserve/remove metadata modes of the old
single-book form are retired for this tool.

**Shared → Book → blank, and blank means blank.** The Shared area is exactly five fields — Artist,
Album Artist, Album, one signed Time, artwork. A populated Shared value overrides and disables the
matching Book field and leaves the Book's stored value intact. Source tags pre-fill a Book's three
scalars once and are never an output fallback: a cleared field writes no frame. A track's own
default Title (source Title, else cleaned filename) is the one source-derived fallback. There is no
Book-level Title; a Book is named by its Album.

**Title, filename and track number are three values.** The output filename is derived **from the
final Title** (`mp3_plan.track_filename`): one existing leading number removed, sanitised through
the shared cross-platform sanitiser, the calculated number added exactly once when Auto-number is
on, at least two digits wide and widening with the Book's last number; a Title that sanitises to
nothing falls back to the source's cleaned name. The embedded Title never carries the prefix; `TRCK`
is an ordinary unpadded integer; Start # blank means 1. *This supersedes the focused plan's §16.2
wording ("take the source-derived basename") — the accepted authority is the Title, as implemented
at Phase 5 and accepted on both platforms.*

**One signed Time.** Positive appends silence to the end of every track, negative trims, zero still
produces clean new copies; Combine applies it to every constituent including the final one.

**Write ID3 writes a whitelist from a clean tag.** `TIT2` always; `TPE1`, `TPE2`, `TALB` when
populated; `TRCK` when Auto-number is on; one front-cover `APIC` when artwork is selected. Nothing
else from the source survives — old artwork included when no artwork is selected.

**Combine is one file per Book, FAST first, Safe automatically.** Books never merge. FAST (a
one-pass concat-demuxer re-encode) is tried when the staged constituents share codec, sample rate
and channel count; otherwise, or when FAST fails, the Safe WAV-normalising path runs and the reason
is emitted as a technical event. The combined tag is Title = effective Album, Artist / Album Artist
/ Album when populated, the artwork, no `TRCK`, no `CHAP`/`CTOC`; `combined_time-stamps.txt` lists
the final Titles at their adjusted offsets. A FAST rejection by FFmpeg on otherwise compatible media
(observed on macOS with FFmpeg 9.0.1) is this contract working, not a defect.

**Artwork is explicit and read-only.** The chooser filter comes from
`shared.image_capabilities.decodable_suffixes()`; JPG/PNG bytes are embedded as-is; HEIC/HEIF are
decoded through the one shared probe into an **in-memory** PNG for the embed only, pixel
dimensions preserved, no sidecar written; the selected file is never resized, cropped or rewritten.

**One run, one controller, atomic Books, frozen retry.** A processing button reserves one
`MP3-Tool-N` run for the whole batch, freezes one `RunPlan`, and runs one `JobController` /
`JobReporter` / `JobAdapter` for every Book in order. A Book publishes whole or not at all
(private `.work/` staging beside its subfolder, which is named Album → source folder → `Book N`
through the shared collision planner); a failed Book does not stop later Books; Cancel leaves
unreached Books *Not attempted* and the batch cancelled (there is no Book-level "cancelled");
Retry Failed re-runs exactly the failed occurrences of the failed Books against the same frozen
plan inside the same run directory, reusing retained staged pieces, and no live edit can reach it.
Staging cleanup unlinks a link as a link and never follows it.

**One log region.** Summary | Detailed, history kept across runs with a divider per run and per
retry, Clear Log clears the visible text only, the persistent session logger continues; no Copy
Log button, no severity selector, no second engine-output pane.

**The minimum window is the platform's.** Windows keeps `MIN_SIZE = (920, 600)` and its accepted
Phase 11 ACT composition. macOS aqua's minimum is `AQUA_MIN_SIZE = (1024, 720)` — the size the
launcher opens at — because native aqua control, font and bezel metrics make the six fixed bands of
this composition (~440 px) taller than the 484 px content host a 920×600 window leaves, before any
list or log height at all; no wrap, weight or padding change closes that, only a Mac-only redesign,
and the maintainer chose the minimum instead after inspecting 1024×720 and larger on the real
launcher. This supersedes the plan's universal 920×600 wording **for macOS only**. Platform
presentation differences live behind the theme bundle: the aqua metrics carry composition hints the
panel reads with the Windows values as defaults, so the Windows layout is untouched by
construction; business behaviour never branches on platform.

**Tests request a presentation through the theme seam, never by falsifying the host.**
`ui_theme.apply_theme(root, style, platform="win32")` selects the Windows bundle on any machine.
A fixture that rewrites `sys.platform` while a panel runs real FFmpeg is a defect — it sent
`shared/subprocess_utils` down the Windows path on macOS — and is not to be reintroduced.

**What deliberately did *not* become a decision record.** The aqua hint token values, the CRLF
canonicalisation of the Phase-0 hash guards, the casefolded-name comparison in the planner test,
the FFmpeg argument shapes and the Phase 10/12 bug fixes are implementation mechanics or enforcement
of rules already approved; they live in `Handoff.md` and the code.

*Approved across the focused MP3 redesign (Windows Phase 11 and macOS Phase 12, both accepted by
2026-09-12) and recorded at closeout by Claude Code.*

---

## 2026-09-05 — Two already-pushed commits keep their AI co-author trailers: a one-time historical exception, not a change of rule

**Status: historical waiver. This entry does NOT supersede, weaken or amend the 2026-07-07 decision
*"No AI co-author trailers in commit messages, ever"*, which remains fully binding for all future
work.** It disposes of two commits that already exist and already violate it.

**The facts, verified mechanically rather than asserted.** Two commits on the pushed branch
`maintenance/0.6.2-setup-self-healing` carry authorship trailers:

| Commit | Subject | Offending trailers |
|---|---|---|
| `592a72b90886a33bf03172fab39409b786af9dc5` | v0.6.2 PRE-PLAN-6 Phase 8: accept macOS self-repair | `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>` and `Claude-Session: …` |
| `e916cb1128cb71c6fbe3de10f1d54238d5bfa345` | v0.6.2 PRE-PLAN-6: fix macOS test isolation | `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>` and `Claude-Session: …` |

Both were authored on the macOS machine during Phase 8 and the macOS test-isolation checkpoint. The
2026-07-07 rule forbids not only the `Co-Authored-By` line but **trailers of any kind**, so each of
these commits violates it twice. The remaining seventeen commits of the nineteen-commit maintenance
series comply.

**These commits are NOT reclassified as compliant.** They were and remain violations of the standing
policy. Nothing here makes them correct, and nothing here says Claude is an author of anything:
under the 2026-07-07 decision the maintainer is the sole author and sole committer of this
repository, and that is unchanged. What follows is a decision about *what to do now*, not a
re-reading of what happened.

**Decision (maintainer, 2026-09-05): preserve the history. Grant a one-time, closed-set exception
covering exactly the two commits named above, and nothing else.**

**Why.** The only way to remove a trailer from a commit is to rewrite that commit, which rewrites
every descendant SHA. Both commits are already pushed, and both sit in the middle of a nineteen-commit
series that an independent READ-ONLY integration-readiness review has already read end to end at
`a170e41b71168f33247471be79110b871f88cb3d`. Rewriting would invalidate every SHA that review cites,
including the Phase-10 closeout commit recorded across `Handoff.md`, `Changelog.md` and the master
plan index, and would force a force-push over a branch whose contents have been reviewed and found
sound. The maintainer judged the cost of destroying a reviewed, cited history higher than the cost of
recording two historical trailers truthfully and leaving them in place. Honest provenance is the
point of the rule; erasing the evidence to satisfy it would serve the letter and defeat the purpose.

**The exception is deliberately narrow. It:**

- applies **only** to the continued existence of those two already-created commits;
- is a **closed set of two named SHAs** — it cannot be extended by analogy to any other commit;
- **sets no precedent** and grants no discretion to a future session;
- does **not** authorize an AI co-author or session trailer on the remediation commit that carries
  this entry, or on any future commit;
- does **not** authorize any history rewrite, amend, rebase, squash, cherry-pick or force-push — the
  point of the exception is precisely that history is left alone.

**What every future agent must still do.** Write plain commit messages with **no `Co-Authored-By`
line, no session or provenance trailer, and no other authorship trailer of any kind**, exactly as the
2026-07-07 decision requires. If a coding-agent environment appends one automatically, remove it from
the still-unpushed commit before pushing rather than treating this entry as cover. Only the maintainer
may create a new decision that changes this.

— Disposition ruled by the maintainer (Elijah Matthew), recorded by Claude Code, 2026-09-05

---

## 2026-09-05 — PRE-PLAN-6 closeout: observation is not permission, and a launch owns its own readiness

**Decision (v0.6.2 PRE-PLAN-6 maintenance closeout, Phase 10).** `Setup_and_Run` is now responsible
for the state it launches into, on both platforms. These are the durable rules that outlive the
maintenance drop that carried them; that drop is deleted at this closeout.

**This entry supersedes exactly one paragraph of the 2026-08-28 entry below** — *"Why `have_ffmpeg()`
did not simply become 'verified'"*, which recorded that `have_ffmpeg()` means only *a coherent pair is
available* and that the strong claim lives separately in `verified_ffmpeg()`. That compromise existed
so a machine which had never run setup could still use the tools. A launch now repairs and proves
instead, so the weaker meaning has no remaining purpose — and the split it created was a trap, because
the weak name is the one every consumer gate in the app was written against.

**Everything else in the 2026-08-28 entry stands and is not reopened:** ffmpeg and ffprobe are one
coherent sibling pair; a candidate must actually be executed to count; the winning pair is pinned
**where it lives** and is never copied into `files/bin/` merely to centralise it; a package-manager or
system installation stays owned by the manager that installed it; identity is path + size + mtime with
SHA-256 kept as durable evidence rather than as a per-launch check; rejected and blocked candidates are
remembered and not executed again; and path existence or resolvability is never readiness. That entry's
security boundary is untouched — nothing here weakens, disables or routes around Smart App Control,
Defender, WDAC or any endpoint policy.

### Observation is not permission

1. **`shared/ffmpeg_health.py` remains the sole health and proof authority.** Nothing else decides
   whether FFmpeg is usable.
2. **Discovery is observational only.** `discovered_ffmpeg()` may report that a coherent pair *appears*
   to exist. It enumerates, executes nothing, and never authorises execution — so drawing a status line
   cannot raise the Windows Security prompt that executing a blocked binary raises.
3. **`have_ffmpeg()` now carries the same strong meaning as `verified_ffmpeg()`:** a proved, durably
   pinned, still-matching coherent ffmpeg + ffprobe pair is active. A gate written against either name
   is therefore safe. The older, weaker question moved to `discovered_ffmpeg()`, under a name that
   cannot be mistaken for permission.
4. **`ffmpeg_path()` / `ffprobe_path()` return only the pinned pair**, or `None`.
5. **`ffmpeg_cmd()` / `ffprobe_cmd()` return only absolute paths** to that one accepted sibling pair.
6. **There is no bare `"ffmpeg"` / `"ffprobe"` fallback anywhere.** When no accepted pair exists the
   command APIs raise `FFmpegUnavailable`. A refusal the caller can see beats a command line that
   quietly runs whatever `PATH` offers, with two halves that need not even be the same installation.
7. **pydub is explicitly configured to the accepted absolute pair.** Left unconfigured it shells out to
   the bare names, which was the one audio route no consumer gate sat in front of. With nothing pinned
   it is pointed at a sentinel directory path that no process API will execute, so an operation that
   slips past a gate fails immediately and visibly instead of quietly running something unproved.
8. **A normal launch owns readiness: ASSESS → REPAIR → PROVE → PIN → LAUNCH.**
9. **An installer's exit status is never readiness.** WinGet and Homebrew can return 0 and leave nothing
   usable, so the resulting pair is always proved independently before it is pinned.
10. **A healthy installation does the minimum.** A launch that finds everything already proved is a
    no-op, not a reinstall.

### The setup / bootstrap self-healing contract

**Venv health.** The existence of `.venv` is not health, and treating it as health is the defect this
maintenance existed to remove. A normal launch assesses interpreter liveness, a supported Python,
`ssl`, Tk when the GUI needs it, requirements state, and an import proof. The full-feature Python
contract is **`>=3.11,<3.13`**, expressed in exactly one place; the preference order is **3.12, then a
healthy 3.11**; and **3.13+ is not a fully healthy full-feature setup** under the current pins. No
unrelated interpreter is uninstalled or modified.

**Requirements success cannot be claimed before it is proved.** A requirements success stamp is written
only after reconciliation or install succeeds **and** the required imports actually succeed — pip
exiting 0 proves nothing, since a partial wheel, an ABI mismatch or a clobbered install all exit 0. The
real-import proof is recorded separately and is bounded, so a rebuilt environment cannot inherit an
older one. **A false success stamp is forbidden**, because nothing re-probes afterwards.

**Venv recovery is transactional.** Replacing a broken environment sets the old one aside rather than
destroying it; an interrupted repair preserves or restores the last-known-good state, and an existing
aside is never overwritten. **No normal recovery requires the user to delete `.venv` by hand.**

**Windows package acquisition — user scope, explicitly.** Every production `winget install` names
**`--scope user`**: the Python install, the `Gyan.FFmpeg` install, and the root `.bat`'s Python
fallback. **Nothing requests machine scope, and there is no `runas` or elevation fallback.** Scope is
stated rather than inherited from a package default that can change underneath us. A scope or elevation
refusal is not an error to report — it means *this route is unavailable*, and the caller falls through
to the repo-local portable build. That portable fallback stays pinned to the approved **Gyan 9.0.1**
artifact by exact URL **and** exact SHA-256, verified before extraction, staged, proved in staging, and
promoted by a single same-volume rename into a versioned destination before it can ever be active.

**macOS acquisition.** A normal launch with an existing venv can reach the Homebrew FFmpeg repair, and
the application may call `brew install ffmpeg` when Homebrew is present. **It does not install Homebrew
itself** — it points at `https://brew.sh` and says what that would enable. Homebrew reporting success is
not readiness: the resulting pair is still proved and pinned like any other.

**Failure UX.** A repairable prerequisite failure must not trap the user in a blocking pre-GUI "run it
again" loop, which is advice to repeat an identical non-repairing action. Attempt the repair first,
launch where that is safe, and give at most one truthful limited-mode notice when a capability genuinely
cannot be established.

**Test isolation is part of the contract.** Automated tests must not mutate the real `.venv`
requirements or import state, the production `ffmpeg-state.json`, production `files/bin`, production
setup logs, or package-manager state. Two issues found while accepting macOS were **test-harness
defects, not production defects**: a repair sandbox that could reach the host's real Homebrew, because
production deliberately restores the brew directories to `PATH` and candidate discovery searches `PATH`
before the seam the fixture controlled; and a cross-platform recovery test that seeded a Windows
`Scripts/` venv layout. Both were fixed in the harness, leaving production behaviour and candidate
ordering untouched.

### Accepted real-machine evidence, and one named waiver

**HOME-PC (Windows).** A healthy existing `.venv`, with FFmpeg missing. The first ordinary Explorer
double-click **repaired itself** with no manual intervention, through the user-scope WinGet
`Gyan.FFmpeg` route; the resulting pair was independently proved and pinned, and the GUI launched. A
second launch was healthy, with no repair loop. `.venv` was preserved throughout and never deleted by
hand.

**HOME-MacOS.** A healthy existing `.venv`, with FFmpeg genuinely absent. The first ordinary Finder
`.command` double-click repaired through Homebrew; the resulting pair was proved and pinned, and the GUI
launched. A second launch was healthy with no repair loop, and `.venv` was preserved. The specific
Homebrew and GPAC build numbers present on that machine are incidental evidence, **not** architectural
requirements.

**Phase 9 — CSPW-PC non-admin validation: WAIVED / NOT APPLICABLE.** The maintainer decided that CSPW-PC
is no longer a deployment target, so this was **not tested and did not pass**, and **no HOME-PC
substitute evidence was used or claimed** — HOME-PC's account is an Administrator, so a run there
exercises the elevated path and cannot demonstrate the Standard-User restriction. Automated coverage
proves the explicit user-scope argv and the fallback route, including an AST inventory that stops a new
call site from omitting the scope; **that is not a substitute for a real Standard-User target-machine
acceptance**, which remains unperformed. **If a non-admin Windows deployment target is ever
reintroduced, that validation must be reinstated and actually run.** A waiver stays a waiver.

*Recorded 2026-09-05 by Claude Code, at the maintainer's direction, during the PRE-PLAN-6 Phase-10
maintenance closeout. Version identity remains 0.6.2, UNRELEASED.*

---

## 2026-09-01 — D4 clarified: Strip writes no split-fragment metadata at all

**Decision (post-closeout documentation remediation).** The split-fragment metadata rule recorded as
**D4** in the 2026-08-31 closeout entry below is **incomplete as written**, and this entry supersedes
that wording. D4 says a fragment "inherits only `artist`, `album_artist` and `album`; it regenerates
its own `title` and its structural `track`". That is true of **Preserve** and **Replace** only.

**The complete rule, in both directions:**

- **Split — Preserve / Replace:** the fragment inherits the book-level identity and **regenerates a
  generated structural title and track**, which always win over any book-level title a Replace run
  supplies.
- **Split — Strip / Write none:** **no metadata is written at all.** Nothing is regenerated — not a
  title, not a track number, not an inherited field. Strip is not "the other two minus the inherited
  fields"; it is empty by design, and reading D4's regeneration clause as universal would describe a
  behaviour the tool does not have.

**Why this is a documentation correction and nothing more.** The production invariant is already
embodied by `mp3_tools/m4b_metadata.segment_tags()`, whose Strip branch returns an empty mapping
before any inheritance or regeneration is considered, and it is covered by the existing Plan-5
tests. **No behaviour changed, no code changed, and no approved product decision was reopened** —
D4's substance stands exactly as approved; only its statement here was too narrow. The 2026-08-31
entry below is left intact as written, per this log's append-only rule.

*Recorded 2026-09-01 by Claude Code, during the bounded post-closeout documentation remediation.*

---

## 2026-08-31 — Plan 5 closeout: the M4B Converter's approved product contract

**Decision (v0.6.2 Plan 5, Phase 18 closeout).** The Converter upgrade is complete, and these are
the product rules that outlive the implementation drop. They are recorded here because the drop that
carried them is deleted at this closeout; each was approved during the plan and is implemented.

**One entry, not six, and deliberately so.** The split-placement decision already has its own entry
(2026-08-30), as do the Windows xHE-AAC routing decision, the whole-book cover-from-a-second-input
finding and the FFmpeg-pair pinning rule (2026-08-28/29). Those are not repeated. What follows is the
remainder, which is a single coherent contract rather than six independent architectural choices.

**Layout (D1).** The Converter keeps `MIN_SIZE == (920, 600)`, the `1024x720` default and its
classic, non-`ACT.*` visual identity. Plan 5 added its controls within that window rather than
redesigning the panel; broad visual conversion stays Plan 9's. The sanctioned local scrolling
fallback was **never needed** — every Plan-5 control is a real target at the supported minimum.

**Artwork (D2).** Preserve and Replace keep the source cover; Strip removes it. Only a stream
positively identified by `disposition.attached_pic` is copied, by absolute stream index, so ordinary
video ahead of a cover can never be mistaken for one. A source with no artwork is valid. Two attached
pictures is an ambiguity and **fails closed** rather than guessing. Covers are stream-copied, never
re-encoded, and Plan 5 ships **no** replacement-image picker — that is Plan 8's.

**Split-fragment metadata (D4).** A fragment is not the book. It inherits only `artist`,
`album_artist` and `album`; it regenerates its own `title` and its structural `track`; and it never
carries the whole book's chapter map or title. The regenerated pair always wins, so a Replace run's
book title cannot become a chapter's title.

**Numbering (D5).** Three concepts that never mix: a split output's **structural** track is its
position within its own book and restarts per book; a whole book's **sequential** track is optional,
allocated **only on success** so a failure consumes nothing and the sequence stays gap-free, and it
is derived from the run's own result rather than from any filename or directory listing; and the
filename order prefix is rendered, never allocated. The whole-book option defaults **off** — numbering
a library is something a user asks for, not something a default does on the way past.

**Whole-book chapter retention (D6A).** A whole output *is* the whole book, so Preserve **and**
Replace both keep the source chapter map — replacing a book's text does not invalidate its
navigation. Strip removes it with everything else. Retention means the titles as well as the
boundaries: a map of anonymous timing points is not the map the source had.

**Shared recursion (D7A).** `ImportOptions.include_subfolders` is a shared importing field, default
`True`, honoured at the single existing descent point, and frozen per import so toggling it changes
only the next import. It was extended in shared code rather than forked into the Converter.

**The metadata vocabulary did not grow.** `title`, `artist`, `album_artist`, `album` and an optional
`track` — the same set `shared/metadata.py` already supported. Everything reaching an output is named
explicitly; nothing is inherited because ffmpeg could inherit it.

**What deliberately did *not* become a decision record.** ffmpeg argument shapes, the ID3 version
pin, the worker's exception boundary, the frozen-reservation correction and the Phase-17 bug fixes
are implementation mechanics or enforcement of rules already approved — the plan's own closeout
instruction forbids standalone ADRs for them, and they live in `Handoff.md` instead.

*Approved across Plan 5 and recorded at closeout by Claude Code.*

---

## 2026-08-30 — A split run groups every book in its own folder; whole books stay flat

**Decision (v0.6.2 Plan 5, Phase 16; maintainer disposition after real macOS multi-book validation).
This supersedes the *split* half of D3 / Decision 31A. The whole-book half is unchanged and stays
exactly as approved.**

A **split** occurrence now gets **one container directory named for its source filename's stem**, at
the place its own provenance already puts it, and all of that occurrence's segments go inside it.
`Arazan's Wolves.m4b` becomes `Arazan's Wolves/` — only the final extension is removed before the
shared sanitiser sees the name. A **whole-book** output is untouched: directly selected books stay
flat in the run folder, folder-imported books still mirror, and no per-book container is ever
invented for them.

**Why, and it took a real corpus to see it.** 31A was a reasonable rule and the implementation
followed it literally. Then Phase 16 ran **12 real audiobooks through Split in one run**: 353 chapter
MP3s landed flat in a single folder, interleaved by book — `01 - Arazan's Wolves-Part01.mp3` next to
`01 - Opening Credits.mp3` next to `02 - Prologue.mp3` — and **53 of the 353 carried a collision
suffix** for no reason except that different books name their chapters alike. Collision-safe planning
was working perfectly; the *organisation* was the problem, and it is only visible at corpus scale.
The maintainer judged the result unusable and superseded the rule. **The previous behaviour was not a
defect and is not recorded as one.**

**The folder is the source stem, never the metadata title.** A Replace run rewrites the book's
textual metadata, and naming the folder from that would rename it out from under the user
mid-decision. The filename is the identity people already recognise.

**One authority, not two.** The container is planned through the *same* three shared planners the
outputs themselves use, with the stem standing in for a filename: `plan_flat` for a directly chosen
book, `plan_mirrored` under its mirrored parent, `plan_multi_root` inside its root container. So
provenance, `assert_contained`, `assert_not_input` and the single run-wide collision domain are all
still decided in one place, and no shared contract changed — `DestinationPlanner.plan` already
accepted a sanitised `subdir`.

**Reserved once per occurrence, deliberately.** Two occurrences that would take the same folder are
separated at the *folder* level (`Book`, `Book-1`), and every segment of one book then shares that
one container. Numbering each segment's parent independently would scatter a single book across
several folders — the failure this ordering exists to prevent. Two deliberate duplicates of one file
remain two occurrences with two containers. A failed split book **keeps** its reservation rather than
releasing it, so Retry Failed writes to the identical frozen paths.

**A chapterless source in a split run keeps its folder too** — one output, but it belongs with the
books beside it rather than loose at the run root.

One incidental improvement, measured: because each book now owns its folder, the cross-book chapter
name collisions disappear. The suffixes that 53 of those 353 files carried are simply not generated.

*Maintainer disposition 2026-08-30; implemented and recorded by Claude Code.*

---

## 2026-08-29 — Phase 15 closes on maintainer acceptance, with the untested rows recorded as waived

**Decision (v0.6.2 Plan 5, Phase 15; maintainer disposition, and it overrides the plan's own §26
completion requirement for this phase only).**

Phase 15 Windows validation is **COMPLETE BY EXPLICIT MAINTAINER ACCEPTANCE**. The maintainer
accepted the real-world Windows validation already performed and explicitly waived the remaining
unperformed synthetic/manual §26 rows as prerequisites: *"I'm not going to test all of that since it
would take too long and i don't have time … i tested enough with the other files and I am happy with
how it's performing, if in the future i encounter an error i will come back to the chat and we can
work on it but for now let's move on."*

**The waived rows are recorded as waived, never as passed.** They are enumerated in `Handoff.md` and
summarised in the plan's §26, under the wording *not manually exercised; explicitly waived by
maintainer on 2026-08-29; non-blocking for Phase-15 completion*. Nothing may reclassify them as PASS
on the grounds that the implementation exists, that automated tests cover the behaviour, that
synthetic fixtures were prepared for them, or that the product is performing well. "Phase 15
complete" does not mean "all of §26 passed", and any future summary that says so is wrong.

**Why this is a legitimate close rather than a shortcut.** What was validated is the part that
carries the risk, and it was validated on real 9-to-13-hour audiobooks through the real launcher
rather than on fixtures: FFmpeg provisioning and clean-install acceptance; AAC-LC Whole; the Windows
Media Foundation xHE-AAC route Whole at 100.0004 % and Split at 15/15; a human listen across a split
boundary; the cp1252 Unicode regression with all three Whole metadata modes; Pause, Resume and
Cancel with verified cleanup; and source immutability by hash on three real books. Four genuine
Windows blockers were found and fixed along the way — FFmpeg provisioning, whole-book artwork
truncation, the xHE-AAC decode gap, and the ffprobe code-page refusal — which is the real return
this phase produced. The waived rows are breadth over synthetic fixtures, and the maintainer judged
that breadth not worth further time. That is their call to make, and the honest record of it is this
entry rather than a matrix quietly filled in.

**One row could not have been tested anyway.** *First chapter starting after zero* is not
representable as a valid M4B here: ffmpeg's MOV/M4B muxer normalises the first chapter start to `0`
(verified against the default, `+disable_chpl` and `-disable_chpl`; the same metadata keeps
`2.000000` in Matroska), and all five real books on hand also begin at `0.000000`. No invalid file
was fabricated to satisfy the row. `test_m4b_timeline_partition.py` covers the planner behaviour it
was meant to exercise.

**What this does not close.** The true no-Python + no-FFmpeg fresh-machine proof stays outstanding
as a *release* gate, not a Phase-15 one. The waived rows may be revisited if a real defect appears,
or folded into the Phase 17 bug hunt. Plan 5 stays ACTIVE, Phase 16 is not started, `VERSION`
remains `0.6.1`, and nothing was tagged, released, packaged or merged.

*Maintainer disposition 2026-08-29; recorded by Claude Code.*

---

## 2026-08-29 — Project work lives in the repository; external workspaces need permission

**Decision (repository-wide standing policy, maintainer-directed; not tied to one plan or phase).**

All project-related work created while working inside this repository stays **inside** it —
scratch files, synthetic fixtures, diagnostics, backups, clean-room environments, generated test
media, temporary evidence, logs and agent working directories. The repo-local home is
**`files/dev-work/`**, gitignored in full and organised by phase or purpose. Creating a project
workspace elsewhere on the machine — `C:\act-*`, a Desktop scratch tree, an arbitrary
`%TEMP%` project folder — is not permitted for convenience.

External paths remain legitimate only where the operating system or the thing under test requires
them: installed Python and FFmpeg, WinGet and other system package locations, OS-managed caches
and temp directories the dependencies create themselves at runtime, and the user-selected
application output location. A test whose purpose *is* to prove out-of-repository behaviour is an
exception — and before creating such a workspace the agent must **stop and ask**, stating why
`files/` cannot serve, the exact path proposed, what will be created, and the cleanup plan.

Committable content is application source, tests, required scripts, documentation, and fixtures
deliberately meant to survive a `git pull` on another machine. Everything local-only stays
ignored. Sitting inside the repository does not make temporary evidence GitHub content: no broad
`git add files/`, no force-add of ignored material, and no promotion into `files/test-files/`
merely because something now lives in-tree.

**Why.** By Phase 15 the project had scattered roughly **5 GB** across five `C:\act-phase15-*`
folders and eleven `%TEMP%\act-*` directories — a clean-room checkout with its own `.venv`, an
inactive FFmpeg backup, two diagnostic sets, a synthetic fixture workspace and a registered git
worktree. None of it was discoverable from the repository, none was covered by `.gitignore`, and
a fresh clone gave no hint that any of it existed. Keeping the material in-tree and ignored makes
it visible to whoever is working, disposable in one delete, and impossible to commit by accident,
while the checkout stays usable as the project's clean development and release source.

**Consequence, accepted knowingly.** The relocated clean-room carries a second copy of
`files/tests/`, so a bare `pytest` invoked from the repository root now hits 164 basename
collisions. The authoritative gate is unaffected and was re-measured: `scripts/verify.py` runs
`pytest files/tests/` explicitly and still collects **5160**. Use `python scripts/verify.py` (or
`pytest files/tests`), not bare `pytest`.

*Resolved 2026-08-29 by the follow-up checkpoint, and the rule it establishes belongs with this
one: repository-contained is not the same as active project source, so a local workspace is
excluded from test and source discovery as well as from Git.* A tracked root `pytest.ini` pins
`testpaths = files/tests` and adds `dev-work` and `runtime-data` to `norecursedirs`. Bare
`pytest` now collects the same tree as `verify.py`. The sweep also found the defect was never
unique to `dev-work`: `files/runtime-data/phase14/tree-phase12/` has carried a second copy of
`files/tests/` since 2026-08-22, so `pytest .` was already broken before the migration.

**Historical evidence keeps its original paths.** Reports that say evidence was collected at
`C:\act-phase15-xhe-diag` remain true as written; `Handoff.md` carries the current location map.
Relocation does not invalidate the evidence.

*Maintainer-directed, 2026-08-29; recorded by Claude Code.*

---

## 2026-08-29 — ffprobe's JSON is read as bytes; the host code page never decodes it

**Decision (v0.6.2 Plan 5, Phase 15 blocker remediation; narrow, one production line).**

`m4b_probe.probe_source` asks `check_output` for **bytes** and hands them to `json.loads`, which
decodes JSON's own way (UTF-8/16/32, per RFC 4627). It never asks for `text=True`, an `encoding=`
or an `errors=` mode. A payload that is not valid JSON — or not valid UTF-8 — still fails closed
through the existing typed `ProbeStatus.PROBE_FAILED`, unrepaired.

**Why.** A maintainer imported the real `ToA 4 - The Tyrant's Tomb.m4b` and the Converter refused
it: *`probe status probe_failed: UnicodeDecodeError: 'charmap' codec can't decode byte 0x9d in
position 6528`*. The book is an ordinary valid AAC-LC audiobook — 48,123.24 s, 44 chapters, one
PNG cover, five readable tags — and ffprobe read it perfectly: **exit 0, empty stderr, 22,545
bytes of valid UTF-8 that `json.loads` parses straight from bytes**. The failure was ours.
`text=True` with no encoding makes Python decode with `locale.getpreferredencoding(False)`, which
is **cp1252** on a stock English Windows install. Byte 6528 is the third byte of
`b"\xe2\x80\x9d"` — U+201D RIGHT DOUBLE QUOTATION MARK — inside chapter 4's title *A simple “no”
works*. The typed failure was truthful about what it saw; what it saw was a defect one layer up.

**Crashing was the loud half.** cp1252 *maps* most of the bytes it should not touch: U+2014
arrives as `â€”`, U+2019 as `â€™`, U+00E9 as `Ã©`. A book whose titles avoided the handful of
unmapped bytes would have converted successfully with mojibake baked into every chapter name and
tag. So the fix is measured by exact round-trip, not by the absence of an exception — which is
also why `errors="ignore"` and `errors="replace"` are rejected outright: both turn a refusal into
a silent corruption of the user's chapter titles.

**Why not decode UTF-8 explicitly.** It would work — ffprobe does emit UTF-8 — but it makes this
module a second authority on an encoding `json` already determines correctly, including the
BOM/UTF-16 cases. `shared.metadata.read_chapter_titles` has passed ffprobe's bytes straight to
`json.loads` since it was written; the Converter's probe was the one place that did not, and this
makes them agree rather than inventing a third way.

**Scope, decided on evidence rather than tidiness.** The sweep found one other locale-decoded
ffprobe call reachable from the Converter: `ffmpeg_utils.probe_audio_stream`, used by
`measured_duration` for the drift guard. It is **not** the same contract — `-of
default=noprint_wrappers=1` over six fixed entries — and its output on the very book that broke
the probe is **pure ASCII** (`codec_name/profile/sample_rate/channels/channel_layout/duration`),
which cannot carry a title or a tag. It was left alone. `-decoders` likewise. Nothing in TTS,
Cover, the M4B Maker or the Metadata Editor was touched.

**Why the suite was green while a real audiobook was being refused.** Every generated probe
fixture titles its chapters `Ch One`. A pure-ASCII book cannot fail this way. The regression now
builds a book whose titles carry the same characters, and asserts the payload really is
cp1252-undecodable so the guard cannot quietly stop guarding.

— Diagnosed and implemented by Claude Code from the maintainer's real-book report, 2026-08-29

---

## 2026-08-29 — Windows decodes xHE-AAC through Media Foundation; ordinary AAC stays on ffmpeg

**Decision (v0.6.2 Plan 5, Phase 15 blocker remediation; maintainer-approved, no new dependency).**

A source the probe marks `undecodable_xhe` has its audio decoded by **Windows Media Foundation**
and piped into the unchanged MP3 encode. Everything else — all 54 AAC-LC books in the real
corpus — keeps the existing ffmpeg path untouched. Where Windows cannot decode it either, the run
**fails closed at preflight** rather than producing a shortened audiobook.

**Why ffmpeg is not enough today.** Measured against the real 9.78-hour xHE-AAC book: ffmpeg 9.0.1
refuses **362,465 of 1,515,928 frames** with *"Not yet implemented in FFmpeg, patches welcome"* —
**23.91 %** of the audio — concatenates the rest into 26,783 s against a planned 35,200 s, and
**exits 0**. Split is no better: every chapter span comes back at ~76 %. The audio is not merely
short, it carries ~362,000 excisions. Only the drift guard stopped it shipping. Upstream added the
USAC frequency-domain path in FFmpeg 8.0 and still returns *patches welcome* for eSBR, uniDrc and
time-warped MDCT; since 23.91 % of frames fail rather than all of them, the gap is a **per-frame**
tool. Naming it exactly needs an instrumented build and does not change this decision.

**Why Media Foundation and not FDK-AAC.** FDK v2 does decode xHE-AAC. But `--enable-libfdk-aac`
requires `--enable-nonfree`, which combined with `--gpl` yields a binary that **may not be
redistributed**; this project is GPL-3.0, and no reputable pre-built ffmpeg ships it. Windows 11's
decoder is already installed, needs no download, raises no Smart App Control question, and is
driven from `ctypes` — **stdlib**. It delivered **35,199.78 s of that book: 100.0004 %**.

**Why `IMFSourceReader` and not `MediaTranscoder`.** MediaTranscoder also decodes this book
correctly, but only into a file, and the decoded book is **6.2 GB**. Chunking it was measured and
rejected: `[600,1200)` yields 26,452,025 frames while `[600,900) + [900,1200)` yields 26,443,970 —
every seek discards **8,055 frames (0.183 s)** to decoder priming. The reader is a *pull* interface:
strictly sequential, so nothing is primed away, handing back **4 KB** at a time so the 6.2 GB flows
through a pipe and is never stored.

**Why a split book decodes once.** Because seeking is lossy, `PcmTimeline` runs the decoder once
per item and cuts the PCM at frozen chapter boundaries in the order the segments already run in.
Measured on the real book: opening, early, middle and **final tail** spans all at **100.00 %**.
A short read is reported, never padded — silence in place of missing audio would defeat the guard.

**Capability is probed, never inferred from a version.** Windows N/KN editions ship without the
media feature pack and components can be removed by policy, so the question asked is whether the
libraries load and `MFStartup` succeeds.

**What did not change.** The >3 % drift guard, the encoder, the quality, the metadata allowlist,
ID3v2.3, destinations, numbering, retry, cancellation, and macOS — which keeps `aac_at`, and
therefore reports such sources *decodable* and never reaches this path at all.

**One bug this decision cost, recorded so it is not repeated.** The first live run produced a
complete 100.0004 % audiobook with **zero chapters**: `pcm_argv` emitted `-map_chapters 1` and the
shared `output_args` emitted `-map_chapters 0`, and argument order settled it in favour of the PCM
pipe, which has no chapters. The chapter map is now owned by exactly one place on this route.

— Claude Code, at the maintainer's direction

---

## 2026-08-28 — A whole book with a cover opens its source twice, and the picture comes from input 1

**Decision (v0.6.2 Plan 5, Phase 15 blocker remediation).**

When a Whole output retains artwork, the command opens the same audiobook **twice**: input 0 is
decoded for audio and supplies the chapter map, input 1 exists solely so the attached picture can be
stream-copied out of it.

```
ffmpeg … -i BOOK.m4b -i BOOK.m4b -map 0:a:0 -map 1:<abs index> -c:v copy
         -disposition:v:0 attached_pic … -map_chapters 0 … -c:a libmp3lame …
```

**Why, and it is not obvious.** Mapping the cover out of the *same* input whose audio is being
decoded makes ffmpeg **exit 0** after encoding a handful of audio frames. The artifact that started
this was a 600 KB "audiobook" holding **0.32 seconds** of a 13.5-hour book, alongside its cover,
reported as success. A controlled matrix on the real source isolated it exactly: audio alone passed,
audio **plus chapters** passed, and only the same-input picture truncated — so the chapter map, the
obvious suspect, was innocent. Cover size is irrelevant; a 247-byte cover truncates like a 597 KB
one. The trigger is **source length**: everything up to 50 minutes is fine, 55 minutes and beyond
always truncates. Opening the file a second time for the cover alone fixes it, proven on the full
book — 743 MB, duration exact, all 50 chapters, cover intact, audio encoded once.

**Why not two passes.** Split already attaches artwork in a second stream-copy pass, and copying that
shape here would also have worked. It was rejected: for a book this size it means writing ~750 MB
twice for no benefit the one-command form does not already give. A Whole book remains **one ffmpeg
invocation and one audio encode**, which is what the plan always said it was.

**What this is explicitly not.** It is **not** recorded as an ffmpeg 9.0.1 regression. No evidence
establishes when the behaviour began: every previous Whole output on this machine is a 0-byte
placeholder, and the automated suite's real-media Whole+cover test is six seconds long — two orders
of magnitude below the boundary — so it would have passed against the defect at any version. The
coverage gap alone explains why this survived to a manual matrix. A `~60`-minute generated fixture
now closes it, and it was verified to fail against the pre-fix shape before being trusted.

**Do not simplify the second input away.** `m4b_commands._core` and `_media_args` carry the reasoning,
and five separate guards — in `test_m4b_commands`, `test_m4b_metadata`, `test_m4b_execution` and
`test_m4b_conversion_plan` — pin `1:<index>` and refuse `0:<index>`.

— Claude Code, at the maintainer's direction

---

## 2026-08-28 — The proven FFmpeg pair is *pinned where it lives*, never copied into `files/bin/`

**Decision (v0.6.2 Plan 5, Phase 15 blocker remediation; maintainer cleared risk gate #9 for this
bounded shared change).**

FFmpeg capability now exists only through **one coherent ffmpeg + ffprobe pair that setup or repair
has actually executed**. `shared/ffmpeg_health.py` discovers candidate pairs, proves them by running
`-version` on both halves, and records the winner — **by absolute path** — in
`files/runtime-data/ffmpeg-state.json`. `shared/ffmpeg_utils.py` consumes that record. The pair is
**not** copied into `files/bin/`.

**Why a pinned external pair rather than a normalized local copy.** Copying was the obvious
alternative and it loses on every axis that matters here. The proven Windows build is a 222 MB
static ffmpeg plus a 222 MB static ffprobe, so a copy costs ~444 MB of duplicated bytes for no new
capability. A copy also goes **stale silently**: `files/bin` is checked first, so a copy left behind
by a `winget upgrade` would become an unbeatable candidate — which is a rebuild of the exact defect
this phase removed, where a bad candidate won because it happened to be looked at first. And
copying a GPL third-party binary into the repository tree edges toward redistribution, which is
Plan 9's question, not this phase's. Pinning keeps **one** source of truth, keeps the installation
owned by the package manager that installed it, and makes an upgrade *detectable* — the recorded
size/mtime stop matching, the pin is invalidated, and the pair is re-proven.

**Why identity is path + size + mtime, with SHA-256 as evidence rather than as the check.** Hashing
444 MB on every launch is a visible cost for no extra safety against accidental change. The hash is
computed once at proof time and kept as durable evidence, and re-derived on repair.

**What identity deliberately cannot see, and what covers it.** Nothing about the bytes changes when
a *policy* changes: a pair that ran yesterday and is refused today is byte-identical. So
`ensure_ready()` re-proves the **pinned pair only** on every launch — two bounded `-version` calls,
~60 ms measured — and never sweeps PATH. That distinction is load-bearing: **executing a blocked
binary is itself what raises the Windows Security notification**, so probing strangers on a normal
launch would manufacture the very popup this phase exists to remove. Candidates already proven
unusable are recorded and skipped without being executed again.

**Why `have_ffmpeg()` did not simply become "verified".** It now means *a coherent pair is
available* — still not a claim that either half runs — because a machine that has never run setup
must still be able to use the tools rather than be told it has no FFmpeg at all. The strong claim
lives in the new `verified_ffmpeg()`, and `status_line()` is the single place the difference is
worded, so "found" can never again be printed as "detected" and read as "ready".

**Security boundary, explicitly.** Nothing here disables, weakens, excludes from, or works around
Smart App Control, Defender, WDAC or any endpoint policy, and nothing suppresses a Windows
notification while still using a blocked binary. When no candidate runs, the app says so at the
setup/repair boundary and points at an administrator allowlisting FFmpeg. An organisation's policy
that refuses every legitimate build is a limit the application accepts, not one it routes around.
Getting an unsigned FFmpeg trusted by reputation or signature is release work and stays in Plan 9.

— Claude Code, at the maintainer's direction

---

## 2026-08-22 — Plan 4 closeout: EPUB is retired and archived, Decision 52B is partially superseded, and the licence obligation survives in production

**Decision (v0.6.1 Plan 4, Phase 5, ratified at the Phase 15 closeout).**

**1. EPUB is not a supported input. PDF and TXT are the only ones.** This **partially supersedes
Decision 52B**, which read *"TTS folder batch remains PDF/TXT only; EPUB remains single-file
only."* The folder-batch half stands unchanged; **the single-file EPUB half is withdrawn.** There
is no EPUB mode, no conversion option, no `.epub` dialog filter, and no internal route — stale
persisted state, a retry and a direct internal dispatch call are all refused exactly as the UI is,
proven by 101 AST- and metadata-driven guards rather than by review.

**Why:** EPUB was the least-used and most brittle input, and it was the only one dragging three
parsing dependencies (`ebooklib`, `beautifulsoup4`, `lxml`) into every install. Keeping a
half-supported path alive through the Plan 4 panel restructure would have meant maintaining and
re-testing a mode nobody had asked for.

**2. The source is archived, not deleted, and the archive is permanent.**
`files/archived-code/epub-tts/` holds three extracted source files plus a `README.md` manifest
giving, per file, the original path, purpose, source SHA, retirement reason, retained production
counterpart, licence and restoration guidance. Every byte came from `git show`, never from a
working directory. **It is not a temporary drop and is never deleted with one.** Its inertness is
proved, not asserted: outside `scripts/`, imported and named by nothing in production, uncollectable
as tests, no `__init__.py` / `conftest.py` / `setup.py` / `pyproject.toml` / `sitecustomize`, no
top-level `if` and no top-level call in any archived module, and unreachable by `release.py`, which
walks `ROOT_FILES` + one launcher + `scripts/` only.

**Why:** deleting working GPL-3.0 upstream-derived code to save four files is a false economy. An
archive that cannot be imported, collected or packaged costs nothing and makes restoration a
mechanical act rather than an archaeology exercise.

**3. The module names `epub2tts_edge` and `epub2tts_gui` are deliberately kept.** They are **not**
evidence of EPUB support. Renaming would have had to move atomically across the launcher module
path, `bootstrap.LAUNCHER_FALLBACK`, `tts/__init__.py`, nine test modules holding those paths as
literal strings, `files/Dockerfile` and `README.md` — while Phases 6 and 7 restructured that same
panel. The boundary is written down in three places instead (the panel docstring, the README
`scripts/tts` bullet, and a dedicated manifest section), and a guard asserts the manifest says so.

**Why:** the names carry the upstream provenance, and a half-completed rename during a
simultaneous restructure is exactly the failure the drop warned about. This is disclosure, not
avoidance.

**4. The GPL-3.0 licence and the upstream attribution are obligations of *production*, not of the
archive.** The surviving Edge PDF/TXT engine is the same derivation of
[epub2tts-edge](https://github.com/aedocw/epub2tts-edge) by **Christopher Aedo**, so the README
License section and the credit stay byte-identical and are now pinned by tests, and
`generate_metadata` still writes the upstream URL into every M4B. One line was removed — `ebooklib`
left the "gratefully relying on" list — because that is a dependency acknowledgement, not the
protected attribution, and the project genuinely no longer relies on it.

**Why:** retiring a feature does not retire a licence. Anyone reading the shipped product must
still be told what it derives from.

— Ruled by the maintainer for Plan 4 (superseding the EPUB half of Decision 52B); implemented at
Phase 5 and recorded by Claude Code at the Phase 15 closeout on 2026-08-22.

---

## 2026-08-22 — TTS has one unified PDF/TXT queue; direct files and folders are not two modes

**Decision (v0.6.1 Plan 4, decisions 1A and 2A, ratified at the Phase 15 closeout).**

**Direct files and whole folders coexist in one queue and one run.** There is no Single-File mode,
no Batch-Folder mode and no mode switch. One run preserves occurrence identity, deliberate
duplicates, provenance and natural ordering; **folder-derived items are mirrored** into the output
tree so same-named files from different books cannot collide, and **direct files are placed flat**.
The frozen snapshot captured at run start is what a Retry Failed re-runs, so a retry reproduces the
exact original configuration rather than today's UI state.

**Why:** the two old modes differed in almost nothing except which widget the user had touched
last, and every difference between them was a place for placement rules to diverge. Collapsing
them removed a whole class of "which mode was I in" bugs, and it is what let TTS adopt the Plan 3
importer as-is instead of growing a second list. Mixed provenance in one run is the normal case for
a real audiobook project, not an edge case worth a mode for.

— Ruled by the maintainer on 2026-08-11 (decisions 1A and 2A, "ambiguities remaining: none");
implemented across Phases 6–7 and recorded by Claude Code at the Phase 15 closeout.

---

## 2026-08-22 — Chatterbox is an authorized Plan 4 scope expansion, on the exact model measured in Phase 8, with its dependency cost stated rather than absorbed

**Decision (v0.6.1 Plan 4, Phases 8–10, ratified at the Phase 15 closeout).**

**1. Chatterbox belongs to Plan 4.** It is a recorded scope expansion, explicitly ruled in by the
maintainer on 2026-08-11 rather than deferred to a plan of its own. Phases 8–10 were kept
self-contained so the expansion could be gated, measured and stopped at a hard boundary if the
evidence had gone the other way.

**Why:** the plan was already rebuilding the TTS panel's queue, dispatch and job control. Adding a
third backend afterwards would have meant reopening every one of those seams a second time. It was
scoped in with its own gates precisely so "we are already in here" could not become an excuse for
an unmeasured integration.

**2. The model is `ResembleAI/chatterbox-turbo`, from the published `chatterbox-tts==0.1.7`
wheel — and the import path is `chatterbox.tts_turbo.ChatterboxTurboTTS`.** Everything here was
read off the wheel, not off documentation or upstream master. The package root exports only
`ChatterboxTTS`, `ChatterboxVC`, `ChatterboxMultilingualTTS` and `SUPPORTED_LANGUAGES`, so the
documented `from chatterbox import ChatterboxTurboTTS` **fails**. **Nano is not reachable from
0.1.7** — `from_pretrained` takes `device` only, and the `nano=` parameter exists solely on
unversioned master. The model is 4,044,167,698 bytes (~3.86 GiB), MIT-licensed; output is float32
at 24 kHz; Turbo logs a warning and **ignores** `cfg_weight`, `exaggeration` and `min_p`; and the
upstream PerTh watermark is applied inside `generate` and is mandatory and default.

**Why:** the §5.6 Turbo/Nano discrepancy in the plan was real, and building against the documented
import would have failed at runtime on a fresh machine. Recording what the wheel actually exposes
is what makes a future upgrade a diff rather than a rediscovery.

**3. The dependency cost is stated, not absorbed.** Adopting the pin **downgraded**
`torch` and `torchaudio` to **2.6.0**, `transformers` to **5.2.0**, `safetensors` to **0.5.3**, and
pinned `numpy` to **1.26.4**, alongside the pins upstream leaves floating (`resemble-perth==1.0.1`,
`s3tokenizer==0.3.0`, `spacy-pkuseg==1.0.1`, `pyloudnorm==0.2.0`, `omegaconf==2.3.1`). All are
gated `python_version < "3.13"` alongside Kokoro. **This was proven not to damage Kokoro before it
was accepted**: on the combined stack in an isolated Python 3.12.10 venv, a real CPU synthesis
through the production `tts/kokoro_synth.py` produced byte-identical output (33,837 bytes, 8.35 s)
and the full suite passed unchanged; a clean venv then built from the committed
`requirements.txt` in one `pip install` with no manual correction. Installed size grew ~1,152 MB
(111 → 169 packages).

**4. `setuptools` is held at `80.9.0` as declared compatibility debt.** `resemble-perth` imports
`pkg_resources` while declaring no dependencies at all, and `chatterbox-tts` declares no setuptools
bound. Under this project's `82.0.1`, which removed `pkg_resources`, the import fails, perth
swallows it, sets its watermarker class to `None`, and model construction dies with a misleading
`TypeError: 'NoneType' object is not callable`. The reason lives beside the pin, and the
instruction is to move forward as soon as upstream stops importing it.

**Why:** a silent four-package downgrade under a working Kokoro stack is exactly the kind of change
that surfaces months later as "the voices sound different." Writing down each moved pin, and
proving Kokoro byte-identical across the move, is what makes the downgrade auditable. Pinning
backwards to keep a third party's undeclared import alive is debt and is labelled as debt.

— Ruled by the maintainer on 2026-08-11 (scope) and 2026-08-15 (gate G, the setuptools pin);
recorded by Claude Code at the Phase 15 closeout.

---

## 2026-08-22 — Chatterbox was adopted CPU-first on measured evidence; CUDA remains open and unauthorized

**Decision (v0.6.1 Plan 4, decision 7A and the Phase 8b gate E ruling).**

**Discovery was CPU-first and the numbers went to the maintainer before anything was integrated.**
On HOME-PC the measured aggregate real-time factor was **1.211** (0.826 audio-seconds per
compute-second) with a **~6,191 MB** peak working set — **slower than real time**, and it must never
be described as real-time CPU synthesis. That is neither clearly fine nor clearly fatal, and
calling it "practical" would have meant inventing a threshold. The phase stopped and returned the
measurements.

**Maintainer ruling (2026-08-15): accepted, for an optional, non-default engine.** Device selection
resolves `cuda → mps → cpu` behind one testable seam, so a CUDA machine will use it if one is
present — but **no CUDA-specific launcher, requirements entry, bootstrap step, index URL or
shared-PyTorch change is authorized**, and none was made. No CUDA build was installed or
benchmarked. On Apple Silicon the same seam resolves to `mps` and was later proven live in Phase 13
against the real model.

**Why:** an engine this heavy is a user-visible cost, not an implementation detail, so the decision
to ship it belonged to the maintainer with the figures attached. Leaving CUDA as an untaken branch
rather than an unbuilt feature means the acceleration question can be reopened later without
unpicking anything — and means no one can quietly add a multi-gigabyte CUDA wheel to a
requirements file that a non-technical user installs by double-clicking.

— Measured at Phase 8a; ruled by the maintainer on 2026-08-15; recorded by Claude Code at the
Phase 15 closeout.

---

## 2026-08-22 — The Chatterbox voice set is exactly four maintainer-authorized recordings, approved by ear before any registry row existed

**Decision (v0.6.1 Plan 4, Phases 9–10 and the Phase 13 macOS gate).**

**The voice set is fixed at four**, cloned from four maintainer-supplied reference recordings, and
labelled `Chatterbox - Female 1`, `Chatterbox - Female 2`, `Chatterbox - Male 1`,
`Chatterbox - Male 2` (ASCII hyphens). The earlier built-in-voice / gender-split design is
**superseded**.

**Approval preceded registration, deliberately.** Phase 9 was a hard stop: four evaluation outputs
were produced from the four references and returned to the maintainer with a summary table and
performance figures, and **no `VoiceEntry` row existed** until they had listened. They approved all
four on 2026-08-15, and approved all four again on 2026-08-21 after hearing them synthesized on
real Metal through the production path on macOS. The twelve original rows kept their identity —
voice IDs, backends, timing presets, ordering and the Steffan default (`VOICES[0]`,
`en-US-SteffanNeural`, edge) are unchanged.

**Display labels are the one thing that did move**, by explicit maintainer override on 2026-08-21,
into one consistent `Engine Gender - Name (locale)` form across all sixteen rows. **The override is
limited to user-facing display labels**; the exact ordered list, each former label proven
unoffered and unresolvable, and every other column are pinned by 39 tests. **No migration mechanism
was built, deliberately** — the selected voice is not persisted at all, by any key, so
compatibility code would have been fiction; two tests pin that absence so a future change which
starts persisting a voice fails loudly.

**Why:** a cloned voice is a judgement call about how someone sounds, and no automated gate can
make it. Registering a voice the maintainer had not heard would have put an unapproved identity in
front of users behind a passing test suite.

— Approved by the maintainer on 2026-08-15 (listening) and 2026-08-21 (macOS + labels); recorded by
Claude Code at the Phase 15 closeout.

---

## 2026-08-22 — Local Chatterbox assets are a portability boundary: never committed, never packaged, and never made portable without separate authorization

**Decision (v0.6.1 Plan 4, standing rule from Phase 0 through the Phase 15 closeout).**

**The four reference recordings in `files/Chatterbox-Voice-Uploads/`, every derivative made from
them, and every cached voice-identity conditional are local-only.** They are ignored by a narrow
rule at `.gitignore:55`, are untracked, were never staged, and exist nowhere in this repository's
history. Nothing derived from them is committed or packaged: derivatives and conditionals live
under the ignored `files/runtime-data/chatterbox/`, and production **refuses structurally** to
write inside the recordings folder and re-verifies each source SHA-256 **on every use**. Their only
authorized provenance statement is *maintainer-supplied local reference recording, authorized by
the maintainer for use by this local Chatterbox integration* — no copyright, consent,
redistribution or licence claim is made, and the speakers are not to be identified.

**Therefore Chatterbox is not portable, and that is the intended state.** A clone of this
repository on another machine will start, convert, and report every Chatterbox voice as *setup
required*. **Making Chatterbox work elsewhere requires separate explicit maintainer authorization**
and their own placement of their own recordings. No packaging step, installer change, download or
bundling may be added to close that gap on anyone's initiative.

**Why:** these are recordings of real people. The moment one enters Git history it is effectively
permanent and effectively published, and no later commit removes it. A boundary that depends on
remembering to be careful is not a boundary — so it is enforced by an ignore rule, by hash
verification on every use, by a structural write refusal, and by a degraded path that is truthful
instead of resourceful.

— Standing maintainer rule from Phase 0 (2026-08-11), re-verified at every phase gate including
Phase 13 on macOS and Phase 15 at closeout; recorded by Claude Code.

---

## 2026-08-22 — A hover-scoped global Tk binding must be released by ownership, on every path that ends the hover; and a missing Tk root is a failure where the desktop is the platform

**Decision (v0.6.1 Plan 4, Phase 14 / 14C / 14D).**

**1. `enable_mousewheel` keeps taking the shared root's single global `<MouseWheel>` slot — and now
gives it back on every path that ends the hover.** The launcher runs all six tools inside one root,
so `bind_all` owns exactly one wheel slot that every scrollable options region takes turns holding.
That design stays. What was wrong was the release side: only `<Leave>` released it, and **two real
lifecycle paths never fire a `<Leave>`** — the launcher's tool switch `pack_forget()`s the outgoing
panel out from under the pointer, and closing a panel destroys the region outright. Release is now
also bound to **`<Unmap>`** and **`<Destroy>`**.

**2. Release is guarded by ownership, never unconditional.** Because there is only one slot, a
second region entering *replaces* the first region's handler. A departing region therefore
compares the currently installed Tcl script against the script it installed, and gives the slot
back **only if it still holds it**. The script Tk installs names the region's own registered
callback, which makes it a self-describing ownership token needing no extra bookkeeping.

**Why:** an unconditional release would silently kill scrolling for the region the pointer is
actually over — trading a stale-binding bug for a dead-scroll bug. The measured symptoms of the
original defect were both real: the wheel scrolled the tool the user had just left, and once the
widget was destroyed the stranded callback named a Tcl command that no longer existed, so **every**
later wheel tick anywhere in the launcher raised `TclError: invalid command name …` through
Tkinter's callback reporter.

**3. The `<Unmap>` binding is kept because `pack_forget()` is the real tool-switch lifecycle**, and
it was proven to leak. It is not defensive padding.

**4. A test contract may not be corrected by weakening it.** The Cover browser's rule had been
*"no global `<MouseWheel>` binding may exist anywhere, ever"* — true of the browser, false of the
application, and therefore a tripwire for any other panel's legitimate hover state. It was replaced
by what actually matters and is strictly harder to satisfy: the browser's binding lives on its own
Canvas, and building, scrolling and closing it leaves whatever owned the shared slot **exactly** as
it found it, including when an unrelated region legitimately holds it.

**5. Where a windowing system is part of the platform, a failed `tk.Tk()` fails the run.** Every
live-Tk module used to wrap its root in `try/except TclError → pytest.skip`. That is correct on a
headless POSIX box and wrong on Windows, where an interactive login always owns a window station:
Phase 14 measured one full-suite invocation that **silently dropped forty-nine Chatterbox
integration tests and still exited zero**. The classification now lives once, in
`files/tests/tk_gate.py`, and is made **from the platform, not from the text of the error** —
Windows fails and carries the original exception; macOS and Linux still skip. Only `TclError` is
classified; anything else propagates as itself, because labelling a programming error "headless" is
how the coverage went missing. A structural AST guard forbids any collected module from opening a
root outside the gate.

**Why (5):** a skip is a claim that an absence is acceptable. On Windows that claim is false, and a
false skip is worse than a failure because the run still reports success. Deciding from the
platform rather than from the exception text also means a *new* Tcl failure mode cannot pattern-match
its way into being tolerated.

— Diagnosed, fixed and proved at Phase 14B/14C/14D; approved by the maintainer on 2026-08-22 in the
prompt authorizing Phase 15; recorded by Claude Code.

---

## 2026-08-22 — HEIC/HEIF format preservation is confirmed by live evidence; the 2026-08-11 ruling stands unchanged

**Decision (v0.6.1 Plan 4, decisions 3A and 54A — ratification, not a new rule).**

The rule is already recorded in full in the **2026-08-11** ADR below (*"Image-format capability is
a fifth shared module … with decode and encode kept separate and a missing encoder refusing rather
than substituting"*). It is repeated here only to record that it survived contact with real
hardware and is closed:

**HEIC output preserves the input format, and an unavailable encoder refuses truthfully rather than
silently writing a `.jpg`.** Phase 1 could only prove this through injected probe seams — no real
HEIC file was involved and none was claimed. **Phase 13 proved it live** on Apple Silicon against a
genuine maintainer-supplied `.heic` through the production code: real ISO-BMFF `ftyp` brand,
decode, **HEIC in → HEIC out with no `.jpg` anywhere**, decode and encode capabilities reported
separately and truthfully, and the output reopened and verified at 1024×1024 HEIF. **The source
file's SHA-256 was unchanged afterwards.** The `.jpg` fallback for genuinely *unknown* extensions
such as `.webp` is unchanged, and `REPLACEABLE_SUFFIXES` / `written_suffix()` remain byte-for-byte
as they were.

**Why record a ratification at all:** the original ADR was written from seam-level evidence and
said so. Leaving it there would have left a permanent decision resting on a proof it explicitly
disclaimed. This closes that gap without restating or amending the rule.

— Ruled by the maintainer on 2026-08-11 (decisions 3A / 54A); live evidence obtained at Phase 13 on
2026-08-20/21 and recorded by Claude Code at the Phase 15 closeout.

---

## 2026-08-19 — Chatterbox narration timing is frozen for Plan 4, and the MP3 file-size question is closed at the tested default

**Decision (v0.6.1 Plan 4, Phase 12 closeout — the maintainer's ruling after listening to the
regenerated chapter).**

**1. The remaining pauses are accepted, and narration timing is frozen for the rest of Plan 4.**
The natural-boundary remediation did what it was scoped to do: it removed *unpredictable,
formatting-driven* silence, taking the worst interior gap from 8.73 s to 2.90 s. The maintainer
listened and approved — much better, dead air resolved, a small amount of pause/lag remaining and
acceptable for this release. So: no global silence trimming, no maximum-model-silence cap, no change
to temperature (0.72), the 300-character ceiling, the chunk/paragraph pause, the end silence or
`COLON_PAUSE_MS` (75), and no further text-boundary heuristics without a demonstrated defect.

**Why:** the goal was never uniform timing. The four remaining ≥2 s pauses each correlate to a chunk
with zero newlines whose text contains a written ellipsis or literally narrates a silence — the model
pausing where the author wrote a pause. Post-processing those away would flatten intentional prose to
cure a symptom that no longer has the defect behind it, and it would do so on approved, listened-to
audio. Fine-grained pause/rhythm tuning is recorded as a future observation needing its own
authorization and its own evidence, not as pending work.

**2. The bitrate stays where it was tested. The file-size consequence is accepted, not re-litigated.**
The MP3 finalization ADR below referred one open question to the maintainer: honouring the panel's
`192k` default makes local-engine output an effective 160 kbps, ~5× the old 32 kbps (144 MB → 720 MB
for a ten-hour audiobook). **Ruling: keep the currently tested bitrate and default behaviour.** No
`64k` option is added, the default is not changed to `128k`, and the finalization architecture is not
reopened.

**Why:** the ~5× size is the price of the defect being fixed, and it was paid knowingly — the flagged
consequence went to the maintainer with the numbers attached, and the approval came *after* listening
to two long-form chapters produced at that contract. Changing the encode now would invalidate the
manual evidence that just closed the phase. Nothing is lost by waiting: the existing dropdown already
offers `128k` with no code change, and the 64 kbps correctness floor below stands regardless of which
value is chosen.

**3. The one native crash is still not claimed to be fixed.** The `pythonw.exe` / `torch_cpu.dll`
`0xC0000005` access violation is recorded as historical, characterised from the WER minidump, and
never reproduced in nine controlled attempts or any later run. Fatal-fault diagnostics were added and
self-proved so a recurrence is observable. **Closing Phase 12 does not close that**, and no document
may describe it as resolved.

— Ruled by the maintainer on 2026-08-19 after the Chapter 1144 recheck; recorded by Claude Code at
the Phase 12 closeout.

---

## 2026-08-18 — Chatterbox text is planned on natural boundaries, and no structural newline ever reaches the model

**Decision (v0.6.1 Plan 4, Phase 12 uncontrolled-silence remediation).**

**1. A raw newline is never an instruction to the model.** `split_for_chatterbox` guarantees that
no structural `\n` reaches `model.generate()`. A line break after a completed sentence becomes a
boundary; a line break inside a continuing sentence becomes an ordinary space.

**Why:** a newline handed to Chatterbox is rendered as a pause of no fixed length. A real chapter
contained an **8.73-second** silence produced that way, plus five more of 2.2–2.5 s. Every
configured pause in that file was correct — the silence was inside a single `generate()` call, and
the application had no control over it. Pause length must be the application's decision, expressed
in the assembly, not the model's improvisation on a formatting character.

**2. A sentence ends at a terminator followed by optional closing quotes or brackets.** The old rule
required the terminator to be the last character before the whitespace, so `."` / `?"` / `!"` — how
every line of dialogue ends — was not a sentence. Seventeen line breaks survived into the model in
one 6,251-character chapter.

**3. The hierarchy is paragraph → sentence → clause → whitespace → hard limit**, descended only as
far as the ceiling forces. Clause splitting (`;` `:` `—` `,`, in that order) applies **only** to a
single sentence already over the ceiling, so ordinary prose is never cut at a comma. The colon sits
below the semicolon on purpose: a colon that stays inside a chunk still earns its 75 ms
`COLON_PAUSE_MS`, whereas promoting it to a boundary would convert that into the 700 ms inter-chunk
pause.

**4. Units are packed, not emitted one per sentence.** Every chunk boundary earns a configured
pause, so one-sentence-per-chunk would insert a gap after every full stop and read as machine-gun
narration. Consecutive units are joined up to the 300-character ceiling.

**5. A chunk plan that does not preserve its source is refused, not returned.**
`_assert_content_preserved` compares every non-whitespace character, in order, and raises
`ChunkPlanError` on mismatch. Whitespace is deliberately excluded — this splitter is *required* to
normalise structural whitespace, which is how decision 1 is kept — so the invariant is
content-exact rather than byte-exact.

**Why:** Phase 10 shipped a run that truncated a 2,889-character chunk to 2.1% of its content **and
reported success**. Silent loss of narration is the failure mode that matters here; a run that stops
and says so is strictly better.

**6. The Web Novel Editor was a design reference only.** `elmatthe/web-novel-editor`
(`ai/chunking.py`, `rules/spacing_cleanup.py`) supplied two ideas: retain natural boundaries and
refuse a plan that cannot reproduce its input, and the closing-punctuation sentence-end form. **No
code was copied, imported or vendored, and no cross-repository dependency exists.**

**7. This is Chatterbox's splitter alone.** `kokoro_synth.split_into_chunks` (3,000 characters) and
Edge's `batch_convert.split_into_chunks` are untouched. The 300-character ceiling is not imposed on
any other engine.

*— Decided by the maintainer, implemented and measured 2026-08-18 on HOME-PC.*

---

## 2026-08-18 — Every TTS final MP3 is encoded exactly once, through one explicit contract, never on ffmpeg's defaults — and never below 64 kbps

**Decision (v0.6.1 Plan 4, Phase 12 audio-finalization audit).**

**1. The final encode contract is explicit and lives in one place.**
`shared.ffmpeg_utils.mp3_export_options(bitrate)` returns `format`/`codec`/`bitrate` — explicit
`libmp3lame`, explicit bitrate — and every TTS finalization goes through it: Kokoro, Chatterbox,
and the Edge *folder* path. Returned as keywords rather than performed there, so the encode stays
next to the audio and a test can assert the contract without running ffmpeg.

**Why:** pydub's `DEFAULT_CODECS` maps only `ogg`, so `export(path, format="mp3")` runs ffmpeg with
no codec and no bitrate and the output shape becomes a property of whichever ffmpeg is installed.
On this project's build that was 32 kbps for 24 kHz mono.

**2. Never below 64 kbps for a 24 kHz mono stream. This is a correctness floor, not taste.**
A Xing/Info header needs a 100-byte seek table, which does not fit in a 32 kbps MPEG-2 frame
(96 bytes). ffmpeg is therefore forced to emit the header frame at 64 kbps while the audio frames
stay at 32 — and still tag the file `Info`, i.e. constant bitrate. Any player that trusts that
declaration and reads the first frame's bitrate reports **exactly half** the real duration.
Measured with Windows Media Foundation on a 2:00 fixture: 1:50 at 24 kbps, 1:54 at 32, 1:58 at 48,
and exactly 2:00 from 64 kbps up. **Consequence: the panel's bitrate combobox must never offer a
value below 64k.**

**3. ffprobe and mutagen are not sufficient evidence that an MP3 is well-formed.**
Both read the Xing frame count and so report the correct duration for a file that is internally
inconsistent. All 168 shipped outputs passed under both. The regression guard therefore asserts a
structural invariant — the header frame's bitrate must equal the audio frames' bitrate — read from
the frame headers directly.

**4. Local engines assemble in PCM and encode once; the Edge folder path cannot and is exempt.**
Kokoro and Chatterbox hold numpy arrays, so writing per-chunk MP3s and decoding them back to merge
was a whole lossy generation for nothing — measured at **2.47 dB** on real Chatterbox speech
(19.25 dB → 16.79 dB SNR), consistent with the 1.66 dB recorded earlier on different material. The
Edge folder path receives already-encoded MP3 chunks from the network, so its second generation is
unavoidable; only its final contract was made explicit.

**5. Sample rate and channel count are deliberately NOT normalized.**
The MP3 Tool normalizes to 44.1 kHz stereo through PCM for its own job, and that remains correct
there. TTS output stays at the engine's native 24 kHz mono: resampling and channel expansion would
add cost and loss without improving duration, seeking or compatibility — the 64 kbps floor is what
fixes those, and a single-encoded 24 kHz mono file reads correctly in every parser tested.

**6. The bitrate comes from the control the user already sets, not a new constant.**
The TTS panel has always had an "MP3 bitrate" combobox (128k/192k/320k, default 192k) frozen into
each run as `params["bitrate"]` — but only the Edge *direct* path read it. Honouring it everywhere
fixes the defect for every selectable value with no new setting and no GUI change.
**Known consequence, flagged rather than absorbed:** local-engine output goes from 32 kbps to an
effective 160 kbps (192k clamps to the MPEG-2 ceiling at 24 kHz), so files are ~5× larger —
144 MB → 720 MB for a ten-hour audiobook. Changing it needs no code: pick `128k` in the existing
dropdown, or add a `64k` option if smaller files are wanted.

— Root-caused and implemented by Claude Code under the maintainer's Phase 12 audio-audit
authorization; the file-size consequence is referred to the maintainer for decision.

---

## 2026-08-11 — Image-format capability is a fifth shared module, proved by behaviour rather than by import, with decode and encode kept separate and a missing encoder refusing rather than substituting

**Decision (v0.6.1 Plan 4, Phase 1).** Four choices, recorded here because Phase 1 requires a
new `shared/` module to justify itself in this log — the module-split precedent from Plan 3 §7.

**1. A new `shared/image_capabilities.py` rather than an extension of an existing module.**
The phase's instruction is to prefer extending something that already exists, so the four
candidates were checked before adding a fifth: `ffmpeg_utils.py` resolves and configures external
*binaries* and pydub, `metadata.py` is M4B/MP4 tag mapping, `paths.py` is project-relative paths,
and `bootstrap.py` is first-run setup and installation. **Why none of them:** an image codec
capability is not a binary on PATH, not an audio tag, not a path and not a setup step, and
putting it in the closest of them (`ffmpeg_utils.py`, on the grounds that both "probe for
something optional") would mean a module whose docstring promises ffmpeg answering questions
about Pillow plugins. That is the kind of shared module later readers stop trusting. The new
module imports only the standard library at module level, so it costs nothing to import on a
machine missing every optional image dependency.

**2. Decode and encode are separate capabilities and are never collapsed into one boolean.**
`pillow-heif` wraps a `libheif` build that may have been compiled with a decoder and no encoder,
so "HEIC works" is two different questions. **Why it matters here rather than in the abstract:**
the Cover tool has a source-side *replacement* mode. A machine that can read HEIC but not write
it, reported as one boolean, would either crash mid-run or write a JPEG over an original's
name — an irreversible, silent format change to the user's own file. Two flags make that state
representable, and the panel offers HEIC for import while refusing it for output.

**3. Capability is proved by encoding one real pixel, not by an import succeeding.**
`register_heif_opener()` registers a *saver* whether or not an encoder exists behind it, so
asking Pillow's registry would report an encoder that is not there. The probe therefore imports,
registers, checks that Pillow genuinely gained the HEIF reader, and then encodes a 1×1 image to
memory and sees what happens. **Why this shape:** it also means the module depends on no upstream
symbol beyond `register_heif_opener`, so a `pillow-heif` release that renames or drops its own
capability-query helpers still probes correctly. The probe never raises — every failure becomes a
capability that says what is missing, with a truthful `detail` string for the log — which is what
replaces the bare `try: import pillow_heif … except Exception: pass` that previously sat at
module scope in `cover_resizer.py` and advertised support it had not verified.

**4. A missing encoder refuses; it does not substitute (Decision 3A).** `resize_for_audiobook`
now asks the probe before writing a `.heic`/`.heif` destination and raises
`UnsupportedImageFormat` when it cannot honour the format. The pre-existing `.jpg` fallback for
*unknown* extensions such as `.webp` is deliberately untouched: that format was never advertised
as preserved, so falling back breaks no promise, while HEIC was. `REPLACEABLE_SUFFIXES` and
`written_suffix()` are unchanged, because they encode what the writer can round-trip *by format*,
which is a static fact and not a property of the machine.

**And one thing deliberately not done.** `pillow-heif` is now pinned at `1.5.0` in
`scripts/requirements.txt` (Decision 54A: officially pinned, probed, tested) but is **not** added
to `bootstrap.REQUIRED_IMPORTS`. That list is the set of imports a machine must have, and adding
it would turn optional HEIC support into a startup requirement — the opposite of the degraded
behaviour this module exists to make truthful.

*Recorded at v0.6.1 Plan 4 Phase 1, 2026-08-11, on `feature/0.6.1-tts-cover-workflows`. These are
implementation decisions taken under the drop's delegated authority; maintainer approval of
Phase 1 is pending and no closeout claim is made here.*

---

## 2026-08-10 — Plan 3 is infrastructure with no adopters; truthfulness is enforced by construction rather than by review; the Tk boundary is one guarded module; and the manual evidence is recorded with its gaps intact

**Decision (v0.6.0 Drop 3, Phases 1–9; recorded at the Phase 10 closeout).** Six choices worth
keeping.

**1. The foundation ships adopted by nothing, and structural tests keep it that way.** Four new
shared modules exist and not one production panel, tool or launcher imports them. **Why build
something and then deliberately not use it:** six panels currently each own their own importing,
threading and progress code, and converting them in the same drop that invents the shared
contracts would mean debugging the contracts and the conversions at once, with no way to tell
which was wrong. Building the foundation first makes each later adoption a small, reviewable
change against something already proven. The boundary is not a promise: parameterised guards
AST-parse every module under `scripts/Universal/` and fail if any of them names a Plan 3 module,
`launcher.TOOLS` is pinned at six entries, and the three Tk-free modules are proved to import no
Tk at all. That last one is what makes the whole foundation testable with no display.

**2. A state that would be a lie is made unconstructible, not merely unasserted.** Two claims
matter most in a job UI, because both are easy to make and wrong: "it is paused" while an
indivisible stage is still running, and "it is cancelled" before the worker has stopped. Rather
than checking for them, the reporter mints every state-bearing event **from a controller
snapshot** the controller itself handed out, and that snapshot type refuses to exist for a
cancelled run without acknowledgement. **Why this rather than a validation rule:** a rule is a
thing a future caller can forget or route around; an unconstructible value is not. The same
reasoning shapes the Summary, which cannot leak a diagnostic because the projection that builds
it **never reads the field diagnostics live in** — proven with 200 files' worth of churn
producing three Summary lines — and the ETA, which returns `Calculating…` for every unreliable
case (unknown total, fewer than three comparable samples, a changed category, paused, ended, or a
question about another run) instead of a number nobody should trust.

**3. Every timestamp and every clock read is injected.** None of the three Tk-free modules
imports `time` or `datetime` or calls a clock; the caller supplies one. **Why:** §6.13's rolling
ETA, the pause-exclusion arithmetic and the event ordering are all time-dependent, and the only
way to test time-dependent behaviour without sleeping is to control the clock. The whole drop's
1,460 tests contain **no sleep at all**; races are arranged with barriers, events and bounded
joins, which means a hang fails loudly instead of the suite becoming slow and flaky.

**4. The Tk boundary is one module, one `after` chain, and one guard.** `job_ui.py` is the only
module in the drop that imports Tk. Inside it, `MainThreadPump` owns the single `after` chain —
the Phase 4 import poller rides its `schedule`/`cancel` seam rather than opening a second one —
and every public method that can reach a widget opens with a main-thread guard that **raises
before the widget is touched**. **Why a guard rather than a convention:** "workers must not touch
Tk" is the rule every tkinter application already has and the one they all eventually break, and
a violation shows up as an intermittent crash in somebody else's feature months later. Here a
worker's call fails immediately, at the call site, and a test proves the widget was unchanged.
The pump's single chain is also what makes "no lingering callback after close" checkable at all:
there is exactly one place to look.

**5. Composition, and reuse of what already exists.** The adapters own frames rather than being
them, take every decision as a callback, and define no base panel — a later tool builds its own
layout and hands these components a parent. They create no second manager, coordinator,
cancellation controller, event stream, progress implementation, logger, estimator or output
planner; they reuse the existing `ui_theme.ProgressIndicator` unstyled and the existing
`logging_setup` session logger. **Why:** an inheritance hierarchy invented before its first
adopter is a hierarchy the adopters spend the next five plans fighting, and a second progress
widget or a second log file is a divergence that only becomes visible once the two disagree.
Windows widgets ask the theme bundle for `ACT.*` names and the macOS/aqua and classic branches
ask for **no style at all**, which is why the native appearance is preserved without this module
ever testing the platform — and a before/after snapshot proves no generic ttk style was touched,
so the five unconverted panels render exactly as they did.

**6. The manual evidence is recorded with its gaps intact.** The Windows matrix was run on
HOME-PC and explicitly approved by the maintainer, and that attestation is the complete result —
the supplied screenshots support only a subset of it and are described that way. Three things are
written down rather than smoothed over: **exact 100%-display-scaling was never independently
confirmed**, so the functional matrix is a pass while the true-100% claim is not made; the
harness's literal source-tree before/after console line was not supplied, so repository
verification is recorded as corroborating source integrity rather than presented as the harness's
own output; and the maintainer additionally imported the repository folder as a root, which is
**broader than the plan's disposable-fixture-only preference** and is recorded as a test-scope
deviation. That last one was harmless and provably so: importing's entire filesystem budget is
`scandir` and `lstat`, the worktree stayed completely clean with no untracked file, `git diff
HEAD` was empty, and every tracked file and all 22 approved screenshots stayed byte-identical.
**Why record all three:** the honest failure mode of an approval phase is a green box nobody
observed, and a gap that is written down can be closed later, while a gap that is quietly rounded
up to a pass cannot. **Windows 125% and live macOS were not run for Plan 3 and remain deferred to
Plan 9**, consistent with the standing decision recorded on 2026-08-08.

*Signed: Elijah Matthew (maintainer), 2026-08-10 — approving v0.6.0 Drop 3 Phase 9 at
`9f0cf211a89efb064f6acf435b324bd8c4c1805f` and Plan 3 as a whole.*

---

## 2026-08-08 — Archives ship `config.toml` by explicit scope, concat lists follow ffmpeg's own quoting rules, panels are told when the output base moves, and two validations are deferred rather than faked

**Decision (v0.6.0 Drop 2, Phase 8 and its remediation; recorded at the Phase 9 closeout).**
Four choices worth keeping.

**1. The packager names its root files instead of excluding unwanted ones.** `release.py` writes
an enumerated `ROOT_FILES` list plus exactly one walked tree, and it never mentions
`config-template.toml`. **Why this rather than an exclusion rule:** an exclusion list is only as
good as the last person who remembered to extend it, and the file most likely to leak here sits
directly beside the file we must ship. A packager that never names a file cannot ship it by
accident, so the safety property holds for files nobody has thought of yet. `config.toml` is
copied byte-for-byte rather than generated, so what a user extracts is exactly what the
repository documents and the verify gate checks.

**2. Concat-list escaping follows ffmpeg's documented syntax, not shell intuition.** A path is
wrapped in single quotes and every `'` becomes `'\''` — close the quote, emit an escaped quote
outside it, reopen — and nothing else is touched. **Why the old code was wrong and why this is
not a guess:** ffmpeg's *Quoting and escaping* section states that characters inside single
quotes are literal, so the previous `\'` escaped nothing and ffmpeg read the quote as the
closing delimiter, silently truncating the path. The same function also doubled backslashes,
which survived only because Windows collapses repeated separators and would corrupt a genuine
one. The replacement is the exact form ffmpeg's own documentation gives
(`file '/mnt/share/file 3'\''.wav'`), and it is pinned by tests that drive the real binary over
spaces, Unicode, apostrophes and all three combined — never inferred from one passing fixture.
Shell quoting was deliberately not used: these are file-format rules, and `shlex.quote` stays
confined to the human-readable error log.

**3. A shared registry refreshes the panels; the panels do not learn to resolve paths.** Each
panel registers the read-only variable it already owns, and a successful Save or Reset calls one
helper that re-points them all. **Why not rebuild the panel, pass a callback down six
constructors, or let each panel recompute:** rebuilding would discard a user's in-progress
selections to update a label; new constructor parameters would churn six modules including the
five that Plan 1 deliberately left unconverted; and recomputing in a panel would duplicate the
resolution rules the whole plan exists to centralise. The registry is called from exactly two
places — the successful commit and the successful reset — so a rejected, cancelled or unsaved
value can never be displayed as effective, and a dead registration is dropped rather than raised
over, because refreshing a label must never break the call that just saved a preference. Run
reservation still re-reads the configuration at operation start, so the display is a hint and the
reservation remains the truth.

**4. Live macOS and the Windows 125% matrix are recorded as deferrals, not as passes.** Neither
was run for Plan 2. **Why record rather than approximate:** the honest failure mode of a long
validation phase is a green box that nobody actually observed. Automated aqua coverage is
import- and build-level and is not a live pass; changing Windows scaling needs the maintainer's
own action, and simulating it through the registry would produce evidence of the simulation
rather than of the product. The maintainer's standing decision is that Windows stays at true
100% for the remaining feature drops and the real 125% pass happens in the later dedicated
UI-compression/no-scroll phase, against a stable layout. Both deferrals are written down as
deferrals wherever Plan 2's result is recorded.

*Signed: Elijah Matthew (maintainer), 2026-08-08 — approving v0.6.0 Drop 2 Phase 8 at
`0e7ad0c264cb2a46f3c64f968e24f00963cb1987` and Plan 2 as a whole.*

---

## 2026-08-06 — Cleanup runs in a verified non-venv helper, the app closes only on a positive acknowledgement, the request is retired before the first deletion, and the inventory is never treated as permission

**Decision (v0.6.0 Drop 2, Phase 7).** The post-exit coordinator exists and deletes. Seven
choices behind it.

**1. The maintenance state lives at `files/runtime-data/maintenance/`, and the project owns
it.** Not configurable, not nameable from a request, derived from a repository root the caller
had to prove, and re-validated on every use to be inside the repository and outside all four
removable targets. **Why there rather than a temp folder or the user profile:** the record of
what cleanup was asked to do must survive cleanup, must belong to this project so uninstalling
is still "delete the folder", and must be somewhere the operation itself can never delete. It
sits beside `logs/` and `models/` without being inside either, is already ignored by
`files/runtime-data/`, and is never packaged because archives carry only `scripts/` plus the
root launcher and README.

**2. The helper is a separate process under an interpreter *verified* to be outside any
virtual environment.** Candidates come from `sys._base_executable`, `sys.base_prefix` and
`PATH`; anything inside the repository is rejected before it is probed; the survivor must
itself report `sys.prefix == sys.base_prefix`. **Why verified rather than assumed:** the first
thing this helper may be asked to remove is the interpreter the application is running from. A
guess that turns out to be the venv would delete the process's own feet. The helper is
standard-library only for the same reason — it has to keep working while `.venv` disappears
underneath it.

**3. Cleanup is *not* routed through `bootstrap.py` or the root launchers, and neither file was
changed.** **Why, when the plan named them as the boundary:** the plan's requirement is that
cleanup runs outside the venv, and the reason it named `bootstrap.py` is that `bootstrap.py` is
the existing stdlib pre-venv code. But importing it opens a dated setup log inside
`files/runtime-data/logs/` — one of the four selectable targets — and on Windows that open
handle blocks the deletion the run was asked to perform. A dedicated stdlib module honours the
requirement without sabotaging it, and the coordinator logs into the maintenance folder
instead. The rebuild the plan asks for already works untouched: the `.bat` fast path tests for
`.venv\Scripts\pythonw.exe` and falls through to ordinary setup when it is gone. Changing a
working launcher to add a route nothing needs would have been the larger risk.

**4. The application closes only after a positive acknowledgement — never after a successful
spawn.** The helper writes its acknowledgement only once it has started, loaded *that* request,
validated it, checked the repository root and the state folder, and is ready to wait; the GUI
waits for that, bounded, and gives up early if the process dies. **Why not treat `Popen`
returning as success:** "the helper started" and "the helper understood and accepted the job"
are different facts, and only the second one justifies telling a user their data will be
cleared and then taking their window away. Every failure path withdraws the request and leaves
the app open, so the worst outcome is a wasted click rather than a lie.

**5. The request is retired before the first deletion, not after the last.** `os.replace` moves
it to a consumed name the moment the wait ends and before anything is removed. **Why that
order:** a crash halfway through a pass must not leave an executable request behind — a second
run would start deleting again against a tree that is already half gone, with no record of what
the first attempt did. Retiring first means a crash costs a partial cleanup and an honest
absence of a result, never a repeat. If the request has vanished at that moment because the
requester withdrew it, the run stops and deletes nothing.

**6. The inventory the user saw is never authorization.** Every target is re-derived from its
enumerated ID and re-checked — exact compiled target, containment, repository root, protected
paths, links at every level, and type — immediately before it is touched. **Why re-check what
was checked minutes ago:** between the confirmation and the deletion the app closed, which is
plenty of time for a folder to be replaced by a junction pointing at someone's photo library. A
target that changed shape is refused and recorded, not followed. For the same reason, a link
found *inside* a target is detached rather than descended into: removing a junction never
touches what it points at, and walking one might.

**7. Process-id reuse is defended with a handle, not a hope.** On Windows the helper opens a
handle to the requesting process *before* acknowledging, so the wait is bound to that exact
process object; a recycled id cannot end it early. Elsewhere it polls liveness and relies on
the six-hour staleness ceiling. **Why this matters at all:** the entire safety of "delete after
the app exits" rests on knowing *which* exit was observed. A bounded wait that ends because
some unrelated program inherited the number would delete while the app was still running.

— Elijah Matthew, 2026-08-06

---

## 2026-08-04 — The cleanup catalog is a closed set of four IDs, a request may never carry a path, nothing is selected by default, an unreadable size is said out loud, and Phase 6 fails closed rather than pretending

**Decision (v0.6.0 Drop 2, Phase 6).** The downloaded-data inventory and its confirmation now
exist. Six choices behind them.

**1. Exactly four asset IDs, in a closed catalog that cannot grow at runtime.**
`virtual_environment`, `portable_binaries`, `downloaded_models`, `application_logs` — held as
frozen dataclasses inside a tuple behind a `MappingProxyType`. **Why closed rather than
discovered:** a cleanup feature that enumerates "regenerable-looking" directories is one
mislabelled folder away from deleting someone's work. Every ID here was approved individually
and maps to a directory this project created and can recreate. The audit did notice other
regenerable-looking directories; none were added, per the drop's instruction to stop and ask.
Settings, `config.toml`, outputs, source media, repository source/docs/tests and anything
system-installed are absent by construction, not by a filter that could be widened later.

**2. A request carries enumerated IDs and no path — ever.** There is no `path`, `target`,
`directory`, `root`, `command` or executable field in the request or the result schema, and a
test asserts that of every field name plus the serialized bytes. **Why this specific shape:**
the dangerous version of this feature is one where a widget, a JSON file or a TOML key can
name a directory that reaches a recursive delete. Making the schema physically incapable of
expressing a path removes that whole class of bug rather than defending against it. The single
ID→path mapping takes an always-explicit repository root, has no default, and returns nothing
until the result is proved to be the exact compiled target, contained, non-protected and
link-free. Normalisation deliberately uses `abspath` rather than `resolve()`, because
`resolve()` would *follow* a junction and quietly hand back somewhere else on the machine —
the exact failure the check exists to catch.

**3. Nothing is selected by default, and nothing is remembered.** Every checkbox is created
unchecked on every open; missing and unsafe rows have no usable control; `selected_ids()`
intersects "ticked" with "eligible" so a forced variable yields nothing. **Why no "recommended"
preset:** a preselected destructive set converts a deliberate act into a default one, and the
whole safety argument for this feature rests on the user having chosen each item. Selection is
never persisted for the same reason — a remembered choice is a choice made in a context the
user can no longer see.

**4. An unreadable size is reported, not guessed.** An estimate that skipped a link or hit a
permission error comes back `complete=False`, the row reads `1.2 MB (at least)`, and the
confirmation says *"plus data whose size could not be read safely."* **Why not just show the
partial number:** the figure is the user's main basis for consenting, and a total that silently
under-reports is a lie told at exactly the wrong moment. Links are never followed during
estimation, so a junction cannot inflate — or redirect — the walk.

**5. One custom confirmation, Cancel as the focused default, no suppression.** Not a
`messagebox`: this needs the item list, the sizes, the effect lines and the exclusions in one
place. The destructive button is never the default, so a reflexive Return dismisses it safely;
Escape and the window-close control both cancel; and the window is rebuilt from the live
selection every time, so there is no cached text and no "don't ask again" to find. This mirrors
the Phase 5 replacement confirmation deliberately — the two most dangerous actions in the app
should behave identically under the user's hands.

**6. Phase 6 fails closed rather than pretending.** Accepting builds one validated request and
passes it to a callback; the production callback returns `False` and the dialog says *"Cleanup
did not start. Safe post-exit cleanup is not available yet. No data was changed, and Audiobook
Creation Tool will remain open."* **Why ship a dead end at all:** the alternative was to hold
the UI back until Phase 7, which would have meant designing the request schema, the
authorization rules and the confirmation *against* an executor rather than before one — and the
safety properties above are precisely the ones that are cheap to establish first and expensive
to retrofit. A callback that raises is treated identically to one that refuses, so a future
coordinator crashing can never leave the app claiming cleanup was scheduled.

**A note for Phase 7.** `AssetDefinition.removes_target_itself` already records the difference
between removing `.venv` and emptying the other three, and `requires_post_exit` already records
which assets are open while the app runs. Those are inputs to the coordinator, not decisions it
should make again.

— Claude Code, on the maintainer's instruction (v0.6.0 Drop 2 Phase 6)

---

## 2026-08-04 — Cover replacement is gated three ways and installed atomically; the temporary sibling lives beside its source; a custom destination is the user's folder, so cleanup may never remove it

**Decision (v0.6.0 Drop 2, Phase 5).** The two destination exceptions of Decision 10A now
exist. Five choices behind them.

**1. Replacement needs three independent gates, and each is inert alone.** The
`Save beside source images` toggle, the `Replace original files` radio, and the per-run
confirmation. `effective_mode()` is the single place that combines them, and it returns a safe
mode unless *both* switches are open — so a stale radio behind a switched-off toggle cannot do
anything, and turning the toggle off actively resets the action. **Why three rather than a
confirmation alone:** a confirmation is the last thing a user reads, and people click through
last things. Two deliberate, visible selections mean the dialog is a confirmation of an
intention the user already expressed, not the first time they learn what is about to happen.

**2. The temporary sibling is written beside the source, not in the system temp directory.**
An atomic install requires the temporary file and its target on the same filesystem;
`%TEMP%` frequently is not (a different drive, a different volume). Writing beside the source
guarantees it. `tempfile.mkstemp` supplies uniqueness atomically, so the name cannot collide
with the source, another planned temporary, or an unrelated file. The distinctive
`.act-tmp-` prefix is not decoration: `discard_temporary()` **refuses** any path without it, so
a cleanup path can never be talked into deleting a user's file.

**3. The order is write → validate → replace, and never delete-then-rename.** The finished
image is reopened and its dimensions checked *before* it is installed, so a truncated or
unreadable write cannot reach the original. `os.replace` is atomic on both Windows and POSIX,
so there is no instant where the original is missing. Delete-then-rename was rejected outright:
it opens a window where a crash loses the file entirely. Everything before the `os.replace`
call is recoverable — which is why the failure tests inject at three different points (write,
validation, replace) and all three assert the original is byte-for-byte intact.

**4. A partial batch tells the truth.** Files already installed stay installed; the run reports
"N of M original(s) replaced; any not reached are unchanged." The confirmation says the same
thing in advance. **Why not roll back:** a rollback would need a second copy of every original,
which is the very duplication the user opted out of by choosing replacement — and a failed
rollback is worse than an honest report.

**5. Numbered copies start at `-1`, and sequences are per source directory.** Beside a source,
the unnumbered name *is* the source, so offering it would mean proposing to overwrite the file
being read; `plan_beside()` therefore starts at index 1 and asserts the result differs from the
source. Sequences are tracked per directory so two same-named images in different folders each
get their own `-1` rather than sharing one counter — which is what a user who imported
`shoot1/cover.jpg` and `shoot2/cover.jpg` expects to see.

**The bug this phase found before it shipped.** Phase 4's cancellation path ran
`shutil.rmtree(out_dir)` unconditionally. That is correct for a reserved run, which belongs
entirely to one build — but in the new custom-destination mode `out_dir` **is the folder the
user chose**, so cancelling a build would have deleted it and everything in it. Cancellation now
branches on the mode and removes only this operation's own staging and its own partial output.
Staging in custom mode also moved to an operation-owned `tempfile.mkdtemp()`, so a user's folder
never sees a `build/` directory or an `ERROR.txt`. **Any future cleanup added to this tool must
ask the same question first: does this path belong to us, or to the user?**

**Testing note worth keeping.** The confirmation dialog is built by
`build_replacement_dialog()`, separate from the modal `_ask_replacement()` wrapper, because
driving a real modal loop headlessly hangs. The wording lives in `replacement_message()` and
`replacement_button_label()` so the dialog and the suite read the *same* text — a test that
restated the wording would let the two drift, and this is the one message a user relies on
before an irreversible action. Real focus cannot be observed on a withdrawn root, so the
dialog records `default_widget` explicitly and the suite asserts that plus a source-level check
that `focus_set` targets Cancel and nothing targets Replace.

**Alternatives considered:** a typed confirmation phrase (rejected by the maintainer — the two
explicit selections, exact count, safe default and labelled destructive button are the approved
strong confirmation); `messagebox.askyesno` (rejected — a bare Yes/No cannot carry
"Replace 3 Original Files", and its default is not reliably the safe answer); rolling a partial
batch back (rejected — see 4); keeping the temporary file in the system temp directory
(rejected — see 2); allowing replacement of formats that fall back to `.jpg` (rejected — the
written file would not be the source's name, so it is refused before the dialog with a pointer
to numbered copies).

— Decided by maintainer via drop `0.6.0-drop2-config-output-maintenance-foundation.md` plus the
exact confirmation wording supplied for Phase 5, implemented and recorded by Claude Code,
2026-08-04 (HOME-PC, Windows 11, repo venv Python 3.12.10, ffmpeg and Pillow present)

---

## 2026-08-03 — The output base is managed only in Preferences; per-tool Browse controls are removed; the Cover overwrite option is disabled until Phase 5 rebuilds it safely

**Decision (v0.6.0 Drop 2, Phase 4).** All six tools now write to
`<output base>/<Tool>-Outputs/<Tool>-N/`, reserved at validated operation start. Four choices
came with that.

**1. Per-tool output-folder Browse controls are gone.** Five panels had an editable output
field with a Browse button, defaulted at `build_ui()` time to a `Downloads/<Tool>-N` guess.
Under Plan 2 the output base is a *configuration* value managed in Preferences & Data, and a
per-panel override would bypass it — the plan explicitly forbids stale output-folder fields
that route around the configured base. Each panel now shows its tool folder read-only and names
the actual reserved run once an operation starts. **Why not keep Browse and validate it?**
Because that is the M4B Maker *custom destination* feature, which Decision 10A and the drop
assign to Phase 5 with its own validation and containment rules; shipping an unvalidated
version of it in Phase 4 would pre-empt that design. Input and cover folder history is
untouched — those are dialog conveniences, not destinations.

**2. Reservation happens at operation start, and only there.** The old model picked a number
when the panel was built and froze it for the session, which meant the displayed folder was a
*prediction*: two tools open at once could show the same number, and the number could be taken
by anything else before the first save. Now nothing is created until inputs validate, and the
number comes from the atomic `mkdir` at that moment. A displayed path therefore never promises
a run that does not exist. An AST test asserts `reserve_run_directory` is called only from
action handlers, never from `build_ui` or `__init__` — attributing to the *innermost* enclosing
function, because TTS's `run_job` is a closure defined inside its builder.

**3. Each output-producing action gets its own run — not one run per panel session.** MP3
Tool's combine, time-edit and ID3 are three separate operations, as are the editor's Write
Tags, Clear All Tags and Remove Series Numbering. Sharing one run across them would mix
unrelated results and make "which files came from which action?" unanswerable. It also keeps
cancellation cleanup honest: staging belongs to exactly one operation, so it can never reach
another run, the tool parent or the base.

**4. Cover Image's legacy overwrite control is disabled, not removed and not left live.** This
was the §G blocker: the drop specifies the Phase 4 default and the Phase 5 source-side mode but
never rules on the already-shipped destructive checkbox in between. The maintainer chose the
disabled-placeholder route, and the implementation goes past the widget state deliberately:
`var_overwrite` is forced `False` and the captured worker parameter is the **literal** `False`
rather than a widget read, so re-enabling the checkbox alone could not route an operation into
the source-side branch. `next_version_path()` and that branch are retained as dormant legacy
code — removing them would be churn Phase 5 immediately undoes — and a test asserts the
parameter is a literal and that no Phase 5 interface (mode toggle, numbered-copy/replace
choice, confirmation dialog) exists yet.

**A real bug this migration exposed and fixed.** `avoid_input_overwrite()` only guarded against
writing *onto an input*. Two imported files with the same name from different folders silently
overwrote each other in the Converter, MP3 Tool and Metadata Editor. The shared batch planner
tracks existing files *and* already-planned names, so the second becomes `Book-1.mp3`.

**A real bug this migration introduced, and what it changed about testing.** Routing the
Converter through the planner removed its local `stem` assignment while the metadata fallback
title still used it — every conversion failed with `name 'stem' is not defined` and produced
nothing. **Every planner-level test passed**, because they exercised destinations rather than
the worker body. It was caught by driving the real worker on a generated tone fixture. The
lesson is recorded in the suite: `test_tool_output_integration.py` now runs the actual
Converter, time-edit and Cover workers, so a migration that breaks a worker cannot pass again.

**Alternatives considered:** keeping the Browse field but validating it against the base
(rejected — that is Phase 5's custom-destination feature); one reservation per panel session
(rejected — see 3); removing the Cover overwrite code entirely (rejected — Phase 5 rebuilds it,
so deleting it is churn); deleting `next_output_dir`/`avoid_input_overwrite` now (rejected —
kept as documented dormant API in case of an out-of-tree caller, with a test proving nothing
shipped calls them).

— Decided by maintainer via drop `0.6.0-drop2-config-output-maintenance-foundation.md` and the
Option A ruling on the Cover control, implemented and recorded by Claude Code, 2026-08-03
(HOME-PC, Windows 11, repo venv Python 3.12.10, ffmpeg present)

---

## 2026-08-03 — Output planning is pure and materialisation is explicit; `mkdir` is the reservation race boundary; collisions are case-insensitive everywhere; only the final suffix is an extension

**Decision (v0.6.0 Drop 2, Phase 3).** Five choices behind `shared/output_paths.py`. None of
them is visible to a user yet — no tool consumes the module until Phase 4 — but they are the
shape every later phase builds on.

**1. Planning is pure; materialisation is explicit and narrow.** Every `plan_*` function, the
sanitizer and the collision service compute paths and touch nothing. Only `ensure_output_base()`
and `reserve_run_directory()` create anything, and only directories. **Why:** it makes the
entire surface testable in a temporary tree with no mocking, and it makes "merely opening a tool
creates no folder" a structural property rather than a discipline. It is also what lets a plan
be built on the main thread and handed to a worker, which is the pattern every tool already
uses for its job snapshot.

**2. `mkdir` without `exist_ok` *is* the reservation race boundary.** There is deliberately no
"does this number exist?" check before the create — that check-then-create sequence is exactly
the race the plan forbids. `mkdir` either creates the directory or raises `FileExistsError`;
the loop simply moves to the next number. **Why it matters:** two tools running concurrently, or
one tool started twice, would otherwise silently share a run directory. An 8-thread test with a
barrier proves all eight get distinct directories numbered 1–8. The loop is bounded so a wedged
directory cannot hang a worker. **Do not "optimise" this by pre-scanning the parent.**

**3. Collision comparison is case-insensitive on every platform.** Windows and macOS are both
case-insensitive by default, so `Book.m4b` and `book.m4b` are one file there. Making the
comparison platform-dependent would make a plan differ between the two machines this project
ships to; making it case-insensitive everywhere keeps plans identical and errs toward an extra
`-1` rather than toward an overwrite. On a case-sensitive Linux box the cost is one redundant
suffix; the alternative cost is data loss. **The safer direction is the default.**

**4. Only the *final* suffix is treated as the extension.** `Path.suffixes` would call
`.5 - Extras.m4b` the extension of `Book 1.5 - Extras.m4b` and mangle it; audiobook filenames
contain dots constantly, and multi-part extensions like `.tar.gz` never appear in this
project's outputs. So `archive.tar.gz` collides to `archive.tar-1.gz`, which loses nothing, and
`Book 1.5 - Extras.m4b` collides to `Book 1.5 - Extras-1.m4b`, which is right. The drop's
"preserve the complete suffix" is satisfied — the extension is never truncated or lost — and
its own examples (`stem-1.ext`, `Book-1.m4b`) are all single-suffix.

**5. Link safety is a separate check from containment, because containment cannot catch it
all.** A junction pointing *outside* the run directory is caught by containment: `resolve()`
follows it and the destination normalises outside the root. But a junction pointing *back
inside* the root resolves to a contained path and passes containment entirely — and following
it would still mean establishing a destination through a link an attacker or a stray tool
placed there. `assert_no_link_in` walks every existing component and refuses any reparse point,
which is what closes that gap. Both tests exist, and the second one exists precisely because
the first does not cover it.

**Trailing dots and spaces are stripped deliberately.** Windows silently drops them when
writing, so `Book.m4b` and `Book.m4b ` would land on one file after the collision service had
already decided they were two different names. Stripping them in the sanitizer makes the
collision check see what the filesystem will see.

**Windows link testing uses junctions.** `mklink /J` needs neither Developer Mode nor
elevation, so the directory-link safety tests get real coverage on an ordinary account instead
of being skipped. Only the file-symlink test still requires the privilege and skips with its
exact `WinError 1314` reason recorded.

**`paths.next_output_dir()` stays untouched until Phase 4.** It is marked as a compatibility
wrapper scheduled for removal, and a test records the exact five panels that still call it — so
a sixth caller fails the suite and Phase 4's removals show up in the diff. Phase 3 changes no
current output behaviour at all.

**Alternatives considered:** a lock file or a global counter for run numbers (rejected —
`mkdir` is already atomic on every filesystem this runs on, and a lock file adds a stale-state
failure mode); platform-dependent case comparison (rejected — see 3); `Path.suffixes` for
multi-part extensions (rejected — see 4); rewriting a traversal attempt to something safe
instead of raising (rejected — silently "fixing" `../..` hides a real defect in the caller);
letting the planner create directories as it goes (rejected — it would make every planning test
require a filesystem and would break the "opening a tool creates no folder" guarantee).

— Decided by maintainer via drop `0.6.0-drop2-config-output-maintenance-foundation.md`,
implemented and recorded by Claude Code, 2026-08-03 (HOME-PC, Windows 11, repo venv
Python 3.12.10)

---

## 2026-08-03 — The Preferences dialog is presentation-only and platform-neutral; the launch-warning guard lives in the config layer; the Clear Downloaded Data placeholder carries no command

**Decision (v0.6.0 Drop 2, Phase 2).** Four choices worth not re-litigating.

**1. `preferences_ui.py` decides nothing.** Every rule the dialog enforces — what a valid
output base is, what precedence applies, what a reset clears — lives in `shared/config.py`
and `shared/settings.py` and is tested without Tk. The dialog collects choices and shows
results. **Why:** the Plan 2 contract requires configuration, path and reset logic to be
platform-neutral and testable headlessly; the moment a validation rule lives in a widget
callback, it can only be tested by building a window.

**Styling degrades instead of branching.** `_style(theme, name)` returns `""` wherever
`theme["styles"]` is absent, and a ttk widget naming no style resolves the platform's generic
one. So the Windows build is fully `ACT.*` and the macOS build is fully native from a single
code path, with **no `sys.platform` branch anywhere in the file**. This is the same mechanism
that keeps the five unconverted panels native — not a coincidence, and worth preserving.

**2. The once-per-launch guard belongs in the configuration layer, not the UI.**
`config.take_launch_warning()` consumes the guard; `reset_launch_warning_guard()` re-arms it
for tests. **Why:** diagnostics are produced on *every* load, so a UI-owned flag would let a
reload storm become a dialog storm, and a headless test could not assert the "at most once"
contract at all. Putting it beside the thing that generates diagnostics makes the rule
testable without a display and makes "reopening Preferences must not repeat the warning" fall
out for free rather than needing its own special case.

**The warning is a non-modal `Toplevel`, not a `messagebox`.** The drop calls for a
*nonblocking* summary presented after the root window is ready. A `messagebox` is modal by
definition, so it was rejected; a plain `Toplevel` with a Close button shows the whole
aggregated summary at once — one window for every diagnostic, never one per bad key — and
cannot block the launcher. A failure to present it is caught and logged: **a warning about
configuration must never itself become a startup failure.**

**3. The Clear Downloaded Data placeholder carries no command.** It is created disabled *and*
with no callback at all, so there is nothing to invoke even if some future code re-enabled it,
and `preferences_ui.py` is AST-asserted to import no `shutil`/`subprocess`/`os` and to call no
`rmtree`/`unlink`/`remove`/`Popen`. **Why:** "disabled" is a UI state that a one-line change
can undo; "there is no function to call" is a structural guarantee. Phase 6 owns the catalog,
the confirmation, the coordinator and the deletions.

**4. A failed settings write is now rolled back in memory.** `settings.set()`/`update()`
previously mutated the cache and then returned `False` if the atomic write failed, leaving the
running application believing a preference that never reached disk. They now restore the
previous value on failure. **Why:** the dialog tells the user "the previous setting is still in
use" after a failed save, and that sentence has to be true. Found by building the failure path
rather than by a bug report; regression-tested from both the settings layer and the dialog.

**Layout, measured rather than assumed.** The first build was **689 px tall under the Windows
theme** — taller than the application's own `920×600` minimum — while the unstyled build was
556 px, so a test that only exercised the unstyled bundle passed and hid it. Entry/Browse/Save
now share one row, Reset sits on its card's heading row, and the outer padding uses the tight
end of the spacing scale: **618×596 px on Windows, 630×488 px unstyled**, no whole-dialog
scrolling. The fit test now asserts the Windows path explicitly. `MIN_SIZE = (920, 600)` and
`DEFAULT_GEOMETRY = "1024x720"` are unchanged.

**Alternatives considered:** a modal `messagebox` for the warning (rejected — the drop requires
nonblocking, and one modal per key was explicitly forbidden); a UI-owned "already warned" flag
(rejected — untestable headlessly and vulnerable to reload storms); omitting the Clear
Downloaded Data control until Phase 6 (rejected — the maintainer expressly wants the disabled
placeholder, so it ships inert and clearly labelled); a menubar instead of a status-bar button
(rejected — the launcher has no menubar on any platform, and adding one is a shell change Plan
1 did not sanction); a scroll region to solve the height (rejected — the fit contract says
adaptive layout first, and scrolling is for genuinely unbounded content).

— Decided by maintainer via drop `0.6.0-drop2-config-output-maintenance-foundation.md`,
implemented and recorded by Claude Code, 2026-08-03 (HOME-PC, Windows 11, 1920×1080 at 100%
scaling, repo venv Python 3.12.10)

---

## 2026-08-03 — Configuration is a three-layer precedence with a one-key mutable overlay; the four documentation names are a permanent, mechanically enforced contract; the maximized-fit rule is the Plan 9 acceptance target

**Decision (v0.6.0 Drop 2, Phase 1).** Five things are settled and later plans should build on
them rather than re-litigate them.

**1. Precedence is code defaults → `config.toml` → an allowlisted mutable overlay.** A
committed, commented root `config.toml` holds the project's documented defaults;
`shared/config.py` resolves one typed, immutable `EffectiveConfig` snapshot from it. The
overlay is deliberately **one key** — `output_base_directory` in `settings.json` overriding
`output.base_directory` — declared in `config.SETTINGS_OVERLAY`, which is the whole allowlist.
Anything else in `settings.json` is either known user state (`last_tool`, remembered dialog
directories, voice, bitrate) that is skipped silently, or an unrecognised key that is ignored
with one diagnostic.

**Why a whitelist rather than "any settings key may override its TOML twin":** a name-matching
rule would silently promote a future preference into a configuration override the moment
someone happened to name it after a TOML key. An explicit table makes every override a
deliberate, reviewable line of code. **Do not add a key to it without a plan that says so.**

**Why the existing user-state keys got no TOML counterpart:** they are per-user memory, not
project configuration; inventing `[state] last_tool = …` would put a machine-specific value in
a committed, shipped file for no benefit.

**2. Validation is per key, and the runtime and the repository gate deliberately disagree.**
At runtime a bad value falls back and warns — a user's hand-edit must never stop the
application from starting, and one bad key must never discard its valid neighbours.
`scripts/verify.py` does the opposite and **fails on any diagnostic**, because a *committed*
file that needs a fallback is a defect being shipped. Both use the same loader, so the rules
cannot drift apart. Diagnostics carry a human-readable `message` and a separate technical
`detail`, so a summary can never leak a traceback while the log keeps everything.

**3. Relative output bases are rejected; environment variables are never expanded.** A
relative path would mean something different depending on where the launcher was started
from, so it is refused rather than resolved against the working directory. `~` **is** expanded
because it is portable and machine-agnostic; `%USERPROFILE%` / `$HOME` are **not**, which
makes them literal, therefore relative, therefore rejected. This is a safety boundary, not an
oversight — arbitrary shell-style expansion in a path that later feeds output and (in Plan 2's
later phases) cleanup is exactly the wrong place for surprises.

**4. The four documentation names are permanent and mechanically enforced.**
`md-instructions/Briefing.md`, `Changelog.md`, `Decisions.md`, `Handoff.md`, in exactly that
casing. Never rename, recase, duplicate or alias them; never recreate `CHANGELOG.md`,
`DECISIONS.md` or `handoff.md`. The gate compares **real directory entries** via `os.listdir`
rather than calling `Path.exists()`. That distinction is the whole point: `verify.py` had been
reading `md-instructions/CHANGELOG.md` ever since the documents were recased, and reported
`PASS` for weeks purely because a Windows path lookup is case-insensitive — on a case-sensitive
filesystem the gate would have failed outright. The stale *reference* was the bug; the files
were correct. `files/tests/test_repository_contract.py` proves the gate rejects a missing
canonical file, every case-variant alias, and a deleted `don't-delete/` reference, using
temporary trees because a case-insensitive filesystem will not let a real alias be staged
beside its canonical twin.

**5. The maximized-fit rule is the Plan 9 acceptance target and binds new UI now.** At
1920×1080 on Windows at 100% and 125%, plus the approved live macOS reference display, the
maximized launcher must show each complete tool view without a whole-panel or whole-form
scrollbar where practical, reached through adaptive layout rather than by wrapping a tool in a
permanently scrolling canvas. Scrolling stays valid for genuinely unbounded content (file
lists, book collections, chapter titles, logs, thumbnail browsers) and must stay local to that
region with primary actions, Cancel/Pause/Resume, progress, status and output access still
reachable. At `920×600` the requirement is graceful adaptation, not simultaneous visibility.
`MIN_SIZE = (920, 600)` and `DEFAULT_GEOMETRY = "1024x720"` are **unchanged**. The M4B
Metadata Editor's permanently scrolling form remains an accepted Plan 1 limitation that Plan 9
must reflow — recording the target here does not reopen the Plan 1 approval.

**Structural rule worth keeping:** `shared/config.py` must never import `logging_setup`.
Retention reads configuration, so the dependency runs one way only; `logging_setup` imports
config lazily *inside* `configured_max_sessions()` and falls back to 30 on any failure,
because logging has to come up even when configuration cannot.

**Alternatives considered:** a TOML parser dependency such as `tomlkit` (rejected — stdlib
`tomllib` is sufficient for reading, and the plan forbids a new dependency without proving the
standard library insufficient); letting the GUI write `config.toml` (rejected — the committed
file must stay machine-agnostic and diffable, so user choices go to `settings.json`); making
the runtime *fail* on an invalid config to match the gate (rejected — a non-technical user who
mistypes a number must still get their application); mutable overlay by name-matching
(rejected — see above); renaming `Changelog.md` back to `CHANGELOG.md` to make the stale
reference correct (rejected outright — the maintainer's canonical names are the contract, and
the reference was what was wrong).

— Decided by maintainer via drop `0.6.0-drop2-config-output-maintenance-foundation.md`,
implemented and recorded by Claude Code, 2026-08-03 (HOME-PC, Windows 11, repo venv
Python 3.12.10)

---

## 2026-08-02 — The Windows dark design system is APPROVED as the durable UI contract; tkinter/ttk stays; geometry, DPI awareness and live macOS are explicitly deferred

**Decision:** After reviewing the ten-image screenshot matrix, the maintainer **approved** the
v0.6.0 Drop 1 Windows UI prototype. What is approved is a *design contract*, not a release:
`version.py` remains `0.5.1`, no v0.6.0 exists, and nothing merged to `master` on approval.
The contract, which later plans must follow rather than re-litigate:

- **Centralized semantic tokens.** Windows colours, metrics and fonts live in
  `shared/ui_theme.py` and reach panels only through the theme bundle
  (`theme["colors"] / ["metrics"] / ["fonts"] / ["styles"]`) or `ui_theme.style_tk_widget()`
  for the classic Tk widgets ttk cannot style. **A panel may not declare a hex literal or a
  layout magic number.**
- **`ACT.*` namespaced style isolation.** `vista` stays the base theme; every style this
  project registers is prefixed `ACT.`; generic ttk styles are never created, reconfigured or
  re-laid-out; no `option_add` / `tk_setPalette` anywhere. Recolorable elements are cloned out
  of `clam` into the live theme because vista's native parts ignore colour options. ttk has no
  style inheritance, so an unconverted panel resolving the generic style is exactly what keeps
  it native — the isolation is structural, not a convention.
- **Converted surfaces are the launcher shell and the M4B Metadata Editor. Only those.**
  TTS Audiobook, M4B Converter, MP3 Tool, M4B Maker and Cover Image Resizer stay classic until
  Plan 9. Approval did **not** widen Plan 1's scope.
- **Shared Metadata is a visual treatment of behaviour that already exists.** It adds no
  per-book override, no precedence, no disabling. Decision 20B's full model still requires the
  Plan 6 workspace and the Plan 8 editor workflow.
- **Summary/Details is a presentation-only specimen** in a developer-only, launcher-unreachable
  fixture. No Plan 3 behaviour (filtering, dual log buffers, technical-log routing, job
  snapshots, ETA, Retry Failed, Pause/Resume) exists in the product.
- **Non-Windows behaviour is preserved and must stay preserved.** macOS `aqua`/Finder and the
  Linux/other `classic` fallback are byte-identical to the pre-drop `master` at the function
  level, and four automated tests hold that line.

**Approved evidence:** `files/UI-Prototype-Screenshots/v0.6.0-drop1/` — ten images, 1920×1080,
maximized, five states at true 100% and the same five at true 125% Windows display scaling,
captured at Phase 5 SHA **`b2e809fe4e25f5aaaef1684b5998bc652374de87`** on branch
`feature/0.6.0-drop1-windows-ui-prototype`. The 125% pass was captured on the secondary
1920×1080 display (the one set to 125%); the maintainer accepted it as valid evidence and
required no primary-monitor reshoot. The current specimen is accepted as sufficient — no
additional Details screenshot is to be added.

**Why tkinter/ttk remains acceptable (the question this drop existed to settle):** the hard
part — a genuinely modern dark UI without a toolkit switch — works. Cloning clam elements into
the live vista theme produced a fully colourable dark control set (buttons, entries,
comboboxes, spinboxes, checkbuttons, notebook tabs, scrollbars, Treeview, labelframes,
progressbars) while five panels kept byte-identical native rendering, proven by snapshot tests
across a whole application build. No image assets were needed to fake controls, no new runtime
dependency was added, and no per-machine hack was required. The two things ttk genuinely cannot
reach — the `Combobox` popdown and the window title bar — are narrow and separately solvable.
**Do not propose a toolkit change for the remaining conversion.**

**Geometry: deliberately unchanged.** `MIN_SIZE = (920, 600)` and
`DEFAULT_GEOMETRY = "1024x720"` stay as they are. The M4B Converter's primary action and Log
remain clipped at the 920×600 minimum (~19 px, and ~108 px bottom + 75 px right), identical at
both scaling levels. That panel is unconverted and Plan 9 will rebuild it, so widening the
application minimum on behalf of a layout that is about to change would be a theme-contract
change made for the wrong reason. The converted editor clips nothing at any size or scaling;
its long form is a deliberate scroll region at every size (plan §7.3 requires deliberate
scrolling, not zero scrolling), with the action bar and Log outside it. **Deferred to the
Plan 9 conversion of that panel.**

**DPI awareness: explicitly unresolved future work, and explicitly not a blocker.** The
application is DPI-**unaware** — `GetProcessDpiAwareness` returns `UNAWARE`, and neither the
venv's `python.exe`/`pythonw.exe` nor the base Python 3.12.10 they copy carries a `dpiAware`
manifest; `pythonw.exe` is what `Setup_and_Run` launches, so this is the real user path. At
125% Windows therefore bitmap-scales the whole window: text is soft rather than re-rendered at
120 DPI. The maintainer accepted this for Plan 1 **because the app remains usable and nothing
clips** — the same uniform scaling that softens the text is why the layout cannot break, and
the measured geometry at 1024×720 and 920×600 is byte-identical between the two passes. It is
recorded here as **unresolved Windows work for Plan 9 or an appropriately scoped future plan**,
not as finished behaviour. A fix means a manifest or a `SetProcessDpiAwareness` call at startup
**plus** a re-measure of every fixed pixel metric and fresh screenshot evidence; it was
deliberately not attempted during closeout.

**Live macOS: an approved deferral, never a pass.** No Mac was available across Phases 4–6, so
the v0.6.0 line has **not** been live-verified on macOS and must not be described as such. The
exact five-step smoke test is preserved in `handoff.md`. Automated aqua-branch coverage plus
the byte-identical non-Windows code paths are *evidence*, not a live pass. This deferral did
not block approval because the drop changes no non-Windows code path.

**Alternatives considered:** switching toolkits (rejected — the prototype proved ttk sufficient
and the cost is enormous); converting the other five panels now (rejected — approval
establishes the contract Plan 9 applies, and unconverted panels are what makes the isolation
claim testable); raising `MIN_SIZE` to clear the converter clipping now (rejected — see
Geometry); fixing DPI awareness during closeout (rejected — a production behaviour change would
invalidate the visual evidence just approved).

— Approved by maintainer (Elijah Matthew) 2026-08-02 after reviewing the ten-image matrix;
recorded by Claude Code, 2026-08-02

---

## 2026-07-19 — Batch-timing-parity rewrite implemented, measured, and ABANDONED by ear; the original chunk pipeline is the confirmed-preferred batch method

**Decision:** The Edge batch path stays on its original chunk pipeline
(`split_into_chunks` → one `edge_tts.Communicate` call per ~3000-char chunk →
`merge_mp3s` with a flat 50 ms chunk join), which honors only `speaker` and `rate` and
leaves all inter-sentence pacing to Edge's natural prosody. A full timing-parity
rewrite — batch delegating each file to `run_conversion_job` in a child subprocess
(thread-level delegation is unsafe: the engine's `os.chdir` is process-global, proven
to corrupt concurrent conversions), plus per-path registry presets
(`batch_timing_preset` overrides re-tuned so every non-Jenny voice matched its
old-batch median gap within −22…0 ms) — was fully implemented and measured across
all 7 Edge voices, hit its numeric targets almost exactly, and was then **abandoned
after the maintainer's manual A/B listening: it sounded subjectively worse than the
original batch method for every compared voice.** Do not blindly re-attempt this;
sentence-level pause insertion plus per-chunk silence trimming audibly changes the
speech character of a batch render in ways gap statistics do not capture. Any future
attempt must lead with ear-testing, not measurements, and should start from the
session records around this date (handoff work log, CHANGELOG notes).

**Why:** The maintainer compared old-vs-new batch renders of the same chapter for six
voices; despite median-gap parity, the new engine's output was consistently judged
worse by ear. Measured-identical cadence is not perceived-identical audio: the old
pipeline's single continuous synthesis per chunk preserves Edge's natural prosodic
flow across sentences, while per-sentence synthesis + trim + inserted silence does
not.

**Consequences:** Batch mode intentionally ignores the five GUI pause fields (they
apply to Edge single-file conversion only — documented in Briefing.md); Jenny's
`timing_preset` (sentence 750 / paragraph 800) affects single-file mode only. The
one surviving artifact of the effort is knowledge, recorded here.

— Decided by maintainer (Elijah Matthew) after A/B listening, implemented-and-reverted
by Claude Code, 2026-07-19

## 2026-07-08 — AI-WORKSPACE.md and files/vibe-coding-templates/ are excluded from version control

**Decision:** Neither `AI-WORKSPACE.md` nor `files/vibe-coding-templates/` is tracked in git,
effective this session. Both are listed in `.gitignore`. `AI-WORKSPACE.md` stays on disk as the
authoritative *local* reference for this machine's conventions (including the HOME-MacOS
section), but is never committed. `files/vibe-coding-templates/` is permanently removed from the
tree and is not referenced in any doc.

**Why:** Privacy — `AI-WORKSPACE.md` contains private machine/workspace details that should not
be published to the public GitHub repo; the vibe-coding-templates were workspace scaffolding
with no role in the shipped tool. Upstream commits that delete `AI-WORKSPACE.md` (e.g.
`9c89479`) are therefore correct and must not be reverted.

**Alternatives considered:** committing a redacted `AI-WORKSPACE.md` (rejected — the file's
value is the private local detail; a redacted copy adds maintenance for no benefit); keeping the
templates as dev-only reference (rejected — they duplicate the workspace tooling that lives
outside the repo).

— Decided by maintainer (Elijah Matthew), recorded by Claude Code, 2026-07-08

---

## 2026-07-08 — Shared progress widget lives in ui_theme.py; M4B Maker progress is deliberately indeterminate

**Decision:** Per-tool run progress is one shared class,
`shared.ui_theme.ProgressIndicator` (ttk.Progressbar + counter/percentage label,
main-thread-only `update / set_indeterminate / reset / finish` API), placed in
`ui_theme.py` — **not** in `launcher.py` — and rendered inside each tool's own
layout near its action buttons/status area. Updates are marshaled exclusively
through each tool's existing worker queue (`("progress", (done, total))` /
`("progress_ind", text)` payloads) and applied only in the main-thread drain,
the same channel that feeds each Log box. Determinate wherever a real total
exists (M4B Converter / Cover Image / M4B Metadata per file, MP3 Tool per
track/file, TTS per batch file / Kokoro chunk / Edge paragraph). The **M4B Maker
build is deliberately indeterminate**: it is a single ffmpeg concat/encode with
no observable sub-steps, so the bar animates while working and shows 1/1 on
success rather than faking a percentage. Do not "fix" the Maker to determinate
without a real progress source.

**Why:** `ui_theme.py` is the shared UI module every tool already imports, and
tools also run standalone via their own `main()` while `launcher.py` imports
the tools — placing the widget in the launcher would invert that dependency.
Inventing Maker percentages (e.g. ticking on log lines) would display made-up
numbers; the drop explicitly prefers an honest indeterminate bar.

**Alternatives considered:** launcher-owned status-bar progress (rejected —
tools must work standalone, and per-tool placement keeps the bar next to the
action it describes); parsing ffmpeg `-progress` output for a real Maker
percentage (viable future improvement, but new subprocess plumbing — out of
this drop's scope).

— Decided and implemented by Claude Code per drop
`0.5.0-ux-progress-and-metadata-layout.md`, 2026-07-08

---

## 2026-07-08 — Panel wheel scrolling: crossing events on the wrap frame + Tcl-level NotifyInferior guard

**Decision:** Scroll-on-hover for canvas-based panels is provided by
`shared.ui_theme.enable_mousewheel(scroll_target, hover_region)`: `<Enter>` on the
hover region installs a `bind_all("<MouseWheel>")` handler, `<Leave>` removes it —
but a Leave whose crossing detail is `NotifyInferior` (the pointer merely moved into
a CHILD widget, still inside the region) is ignored. The Leave side is deliberately
bound **at the Tcl level** (`widget.tk.call("bind", …, "+cmd %d")`), not via
`widget.bind()`, because tkinter's event substitution has no `%d` — `event.detail`
does not exist on Python-level events (verified live on Tk 9.0.3), so a pure-tkinter
guard silently never fires. Do not "simplify" this back to a tkinter-level bind.

**Why:** The TTS options canvas is fully covered by its form frame, so the old
Enter/Leave-on-the-canvas wiring never armed the wheel handler in normal use
(wheel/trackpad scrolling simply did nothing, on Windows too). Binding on the wrap
frame arms it anywhere over the panel; without the inferior-guard the binding tears
down the moment the pointer touches any child control, which is the same bug again.

**Alternatives considered:** binding `<MouseWheel>` recursively on every descendant
(fragile — widgets created later are missed); `winfo_containing` hit-testing on every
Leave (heavier, same result); Button-4/5 bindings (X11-only, irrelevant on
macOS/Windows). Listbox/Text widgets in the other tools scroll natively via Tk class
bindings and intentionally do not use the helper.

— Implemented by Claude Code per maintainer instruction, 2026-07-08

---

## 2026-07-08 — macOS launcher uses the native aqua theme, not a Finder-styled clam

**Decision:** On macOS the launcher applies ttk's native `aqua` theme (with a
`TclError` fallback to the classic clam look for Tk builds without aqua). The
Finder-style chrome — tinted source-list sidebar, hover/selection rows, toolbar,
content card — is built from **classic tk widgets** colored via macOS *semantic*
system colors resolved at runtime in `shared/ui_theme.py`; all six tool panels keep
native aqua ttk controls. Windows/other platforms take the classic branch, which
reproduces the pre-v0.5.0 look byte-for-byte.

**Why (both tested live on this Mac, Tk 9.0.3, dark mode):** aqua gives real native
controls in every tool panel and automatic light/dark adaptation for free, which a
Finder-styled clam would have to fake and maintain by hand. aqua's one limit — it
ignores background styling on native-drawn ttk widgets — is confined to the launcher
chrome, hence the classic-tk sidebar. Fonts use the `.AppleSystemUIFont` alias for
San Francisco (SF Pro Text/Display are NOT installed font families on macOS 26);
alpha-based semantic colors flatten through `winfo_rgb`, so secondary/hover/separator
shades are computed blends instead.

**Alternatives considered:** Finder-styled `clam` everywhere (rejected: non-native
controls in all six panels, manual dark-mode); PyObjC/AppKit for true vibrancy
(rejected per drop constraint — no heavy deps for a visual effect; flagged as an
optional future decision).

— Decided and implemented by Claude Code per drop `0.5.0-macos-ui-shell.md`, 2026-07-08

---

## 2026-07-07 — macOS venv must be built on Python 3.12 for Kokoro; 3.13+ is a degraded fallback only

**Decision:** Kokoro's PyPI wheels require Python >=3.10,<3.13, so the venv base on macOS
must be 3.12 (the `PREFERRED_PY` sweet spot). `bootstrap.py` now enforces this in two
places: (1) `run_setup` no longer accepts a >=3.13 interpreter as-found — it first calls
`install_python` (brew `python@3.12` + `python-tk@3.12`) and only keeps the newer
interpreter if 3.12 truly cannot be installed; (2) `_create_validated_venv` detects an
existing venv built on >=3.13 and rebuilds it once a Kokoro-compatible (<3.13) base is
available, closing the "3.13 venv is reused forever" gap. Python 3.13+ is accepted only
as a degraded fallback: Edge TTS works, Kokoro voices are disabled (the requirements
marker `kokoro==0.9.4 ; python_version < "3.13"` skips the wheel, and the self-heal
repair cannot install it either). The compatibility range lives in one helper,
`_is_kokoro_compatible`.

**Why:** A live Mac run (2026-07-07, only Homebrew python3.13 present) built the venv on
3.13.7; every launch-time Kokoro self-heal then failed with "No matching distribution
found for kokoro==0.9.4" — an environmental failure, unfixable from `kokoro_synth.py`.
The old flow only ran `install_python` when NO interpreter was found at all, so a
3.13-only Mac never attempted the 3.12 install, and the fast path reused the bad venv
forever.

**Alternatives considered:** pinning a newer Kokoro that supports 3.13 (none exists —
the newest 3.13-compatible release on PyPI is 0.7.16, an older API); fixing inside
`kokoro_synth.py` (rejected — the package can never be installed on 3.13, so no
synth-side change helps). The Windows path is unaffected: it selects `py -3.12`
directly and never enters these branches.

— Root-caused and implemented by Claude Code per maintainer instruction, 2026-07-07

---

## 2026-07-07 — Kokoro pause fields: paragraph maps to the inter-chunk gap; full parity deferred

**Decision:** For Kokoro voices, the GUI's "After each paragraph block" field drives
`kokoro_file_to_mp3(chunk_pause_ms=…)` (the silence appended after every ~3000-char
synthesis chunk) and "End of recording" drives `end_silence_ms`. The Between-sentences,
After-title, and Before-chapter fields intentionally do **nothing** on Kokoro voices.
Full per-sentence/title/chapter parity requires sentence-level synthesis inside
`kokoro_synth` (Edge gets it from per-sentence clips) — that is a deliberate deferral to
its own future drop and needs maintainer sign-off to expand. Do not "fix" the missing
parity piecemeal in a bug hunt.

**Why:** The Drop 3 plan scoped Kokoro timing to paragraph + end pause to keep the drop
tractable and avoid a synth rewrite. Kokoro chunks are split on ~3000-char sentence
boundaries, not paragraphs, so the mapping is approximate by design.

**Alternatives considered:** sentence-tokenizing inside kokoro_synth (a rewrite — its own
drop); leaving all pause fields dead on Kokoro (rejected — silently ignoring visible GUI
fields is worse than an approximate mapping).

— Decided by maintainer via drop `drop3-plan`, implemented by Claude Code, 2026-07-07

---

## 2026-07-07 — No AI co-author trailers in commit messages, ever

**Decision:** All commits on this repo are authored solely by the maintainer. Commit
messages are plain text with **no trailers of any kind** — in particular, never a
`Co-Authored-By: Claude ...` (or any Claude/Anthropic co-author) line. Claude appears
only in whatever tooling/log metadata arises naturally, never as an author or co-author.

**Why:** Maintainer is the sole author and sole committer on this repo (stated
2026-07-07 when a co-author trailer was about to be added to the Drop 1 commit).
Applies to Drops 2–5 and all future work — future sessions must not add the trailer
by default.

— Decided by maintainer (Elijah Matthew), recorded by Claude Code, 2026-07-07

---

## 2026-07-06 — One commit per drop for the entire v0.5.0 sequence (not per phase)

**Decision:** For all of v0.5.0 — Drop 1 (restructure), Drop 2 (metadata), Drop 3 (TTS),
Drop 4 (script hardening), and the final UI drop — work through every phase of a drop
back-to-back with **no git commits per phase**. Checkpoint progress only via
`md-instructions/handoff.md` (work log) and the session task list. When a drop's final
bug-hunt/verify phase is fully green, stop and present a final summary; the maintainer
reviews and then a **single commit covering the whole drop** is made, followed by a
maintainer-triggered push/force-push. The agent never pushes.

**Why:** Maintainer wants to review + force-push each drop as a single unit. This
overrides the AI-WORKSPACE.md default of committing after each completed phase for the
rest of the v0.5.0 line — future sessions must not default back to per-phase commits.

— Decided by maintainer (Elijah Matthew), recorded by Claude Code

---

## 2026-07-06 — Runtime-writable data lives in `files/runtime-data/` + `files/bin/`

**Decision:** All state the app writes at runtime goes under `files/`: session/setup/launch
logs in `files/runtime-data/logs/`, persisted settings at `files/runtime-data/settings.json`,
the ~300 MB Kokoro HuggingFace cache at `files/runtime-data/models/huggingface/`, and the
portable-ffmpeg fallback in `files/bin/`. All gitignored. `shared/paths.py` keeps the
`RESOURCES_DIR` name pointing at `files/runtime-data/` so the code diff stayed minimal.

**Why:** Maintainer ruled out `scripts/resources/` and OS user-data dirs (Q4): keeping
everything in-tree preserves the "delete the folder to fully uninstall" property; `files/`
is the AI-WORKSPACE home for non-script assets. Alternatives: `%APPDATA%`-style dirs
(rejected — scatters state, breaks portable uninstall).

— Decided by maintainer (layout details by Claude Code), 2026-07-06

---

## 2026-07-06 — Restructured to the AI-WORKSPACE standard layout (v0.5.0 Drop 1)

**Decision:** Unified the two mirrored per-OS root trees into
`scripts/{Universal,Windows,MacOS}` + dev-only `files/` + one `md-instructions/` set, venv at
the repo root, launchers renamed to `Setup_and_Run-audiobook-creation-tool.*`.

**Why:** The mirrored trees had to be kept byte-identical by hand and duplicated every doc —
pure drift risk with zero benefit (Phase-0 diffs proved the trees identical). Alternatives:
keep mirrored trees (rejected — drift, double docs). Consequences: all imports/paths rewired
once; future OS work goes in `Universal/` unless truly platform-specific.

— Decided by maintainer via drop 0.5.0-drop1, implemented by Claude Code

---

## 2026-07-06 — Almost everything lives in `scripts/Universal/`

**Decision:** The entire application is cross-platform code in `Universal/`;
`scripts/Windows/` and `scripts/MacOS/` are empty (.gitkeep) by design.

**Why:** The two per-OS `scripts/` trees were byte-identical except two unused legacy files
(`mp3_tools_launcher.py`, `tts/setup_env.py` — deleted, maintainer Q2); platform differences
are `sys.platform` branches inside shared code and stay that way. Consequence: a file only
moves out of `Universal/` when it genuinely cannot be shared.

— Decided by maintainer via drop 0.5.0-drop1, implemented by Claude Code

---

## 2026-07-06 — Version 0.5.0, not 0.3.x

**Decision:** This restructure line is **v0.5.0**.

**Why:** v0.3.1 is tagged and v0.4.0 released; a MINOR bump keeps linear history honest.
Alternatives: 0.3.2 (behind already-released history), 1.0.0 (deferred for a stability
milestone).

— Decided by maintainer via drop 0.5.0-drop1

---

## 2026-07-06 — `verify.py` adopted as the mechanical gate

**Decision:** `scripts/verify.py` (from the workspace `verify-template.py`) must print
`RESULT: PASS` before any drop is considered done: pytest suite in `files/tests/` (fails on
"no tests collected"), every dependency `==`-pinned, permanent docs de-templated.

**Why:** No mechanical pass/fail gate existed; releases relied on manual checklists.
Consequence: every phase/drop now ends with the same objective check.

— Decided by maintainer via drop 0.5.0-drop1, implemented by Claude Code

---

## 2026-10-27 — Owner-approved Option B: base preparation is separate from optional acquisition

**Decision:** Early **Continue** prepares the base ACT application only. It does
not authorize any optional model acquisition. Python stage-0 installation retains
its own separate explicit consent.

After verified main CPython 3.12 is available, show the complete exact v3 Plan,
including full history, identities, acquisition terms, reuse, disk/headroom and
explicit repair/rebuild effects. Require genuine trusted GUI presentation
acknowledgment, independently retain the immutable original bytes, then perform
strict original-bound exchange readback. None of selection, early Continue,
worker success, presentation acknowledgment or original retention is consent.
Only a later live **Install Selected Components** (repair-aware when needed)
affirmative action may authorize exact v3 issuance, subject to fresh validation.

Keep Kokoro checked and Chatterbox, Qwen3 CustomVoice and Qwen3 Cloned Voices/Base
unchecked. Estimates remain estimates; unknown base network costs remain unknown.
Count shared Qwen bytes once and distinguish network, reuse, disk and headroom.
All skipped/no eligible mutation means no optional consent or acquisition; a
zero-network repair/local copy is still a mutation requiring disclosure.
Skip/Cancel/close/failure is safe, with no automatic retry, deferred install or
surprise download. A future in-app Skip/Cancel abandons the frozen narration
intent and requires another Create. Fixed resource limits refuse losslessly;
never omit history, relax caps or imply qualified availability.

**Supersession:** This append-only decision changes only Revision 2 section 5.4's
early checkbox/setup-action acquisition-consent interpretation and older P05
commentary treating pre-main estimates as optional acquisition consent. Historical
entries and all other approved choices and security/release gates remain intact.
The Stage 4D-2F presentation-adapter ordering is approved. M1 authorizes only
controlled read-only qualification; consent issuance, production acquisition,
actual first-run/run_job integration, P06 and release activation remain blocked.
Application identity remains 0.6.6.

— Approved by the owner on 2026-10-27; recorded during consolidated M1 qualification.

---

## 2026-10-30 — Release installer: Option B through the existing consented v2 pipeline

**Decision:** The v0.7.0 first-run wizard and the TTS panel's Install & Continue install the four optional
components through the existing optional-setup protocol (contained setup worker in `.venv`, lifecycle, consent
bound to the acquisition fingerprint of the worker's own fresh plan, spent once) and `RealAcquirer`, now the
production default. Option B's user-facing order is kept: early **Begin Setup** builds the base only; after the
base exists a read-only plan is shown in full; only a live click on **Install Selected Components** creates the
consent; Skip/Cancel/close never download, keep what works and never retry by themselves.

The three P05B Stage 3 consent-scope escapes are closed in the acquirer itself: every response passes a byte
budget fixed by the consent (known download plus a stated ceiling for units shown as unknown), refused before the
body is read when its length exceeds what remains; the Qwen3 installer may touch the engine only when the consent
includes the `qwen3-engine` unit. The engine's packages are the reviewed manifest's 89 exact wheels (sox: the
accepted derivative at supply commit `b7e1b1ae`), each fetched by size and SHA-256 through that budgeted opener and
installed offline (`--no-index --require-hashes --no-deps --only-binary=:all:` under the offline bootstrap), so pip
no longer has index access. The bootstrap's unpinned pre-download and warm-up routes are removed.

**Why:** The owner's 2026-10-30 directive makes a working, user-installable application the priority and forbids a
second installation framework. The v3 presentation-acknowledgment/retention/readback machinery (M1/M2) remains in
the tree, qualified and unused by production; it is not required for the consent to be exact, because the worker
refuses any plan whose terms differ from the confirmed ones.

— Directed by the owner on 2026-10-30; implemented by Claude Code.
