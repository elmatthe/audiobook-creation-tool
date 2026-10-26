"""Authoritative v3 planning and disposable locked model acquisition (P05B 4B-3A).

No production worker uses this interface. Observers/openers/simulators are trusted
injected adapters, never request JSON. Package/spaCy installation remains disabled.
Legacy manual Qwen install/repair retains its separate contract.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from shared import artifact_store as storage
from shared import artifact_transfer as transfer
from shared import optional_setup_protocol as proto
from shared import optional_setup_v3 as v3
from shared import venv_layout
from tts import model_assets as assets
from tts import optional_setup as old_plan
from tts import optional_setup_health as health
from tts import qwen3_package_manifest as packages
from tts import qwen3_runtime as rt
from tts import qwen3_setup as setup

MODEL_IDENTITIES_SHA256 = 'acc0179f2ac424d7501bdf3112d362cb90899d3967cf9efbca226cb47c4ca810'


def model_identities_sha256():
    # Include destination directory/voice metadata too: content-only identity
    # must not permit a mutable manifest to redirect an approved operation.
    return hashlib.sha256(storage.canonical(rt.load_manifest()['models'])).hexdigest()


def reviewed_packages():
    folder = Path(__file__).resolve().parents[1]
    return packages.load_manifest((folder / 'qwen3-artifacts.json').read_bytes(),
                                  (folder / 'qwen3-requirements.txt').read_bytes())


@dataclass(frozen=True)
class Observation:
    health: dict
    engine: str
    busy: frozenset = frozenset()


def observe(selected, *, locked, cancelled):
    """Read-only facts/probes. An inconclusive probe never proves engine damage."""
    busy = frozenset() if locked else health.busy_components(selected)
    local = health.local_health(rt.repo_root(), selected, cancel_check=cancelled)
    engine = proto.READY
    if any(c in proto.QWEN3_MODEL_KEYS for c in selected):
        unit, _ = old_plan._qwen_engine_unit()
        engine = unit.state
        if busy & set(proto.QWEN3_MODEL_KEYS):
            engine = proto.BUSY
        elif engine == proto.READY:
            try:
                # Planning probes need the same setup -> inference exclusion as
                # native repair analysis. Final validation reuses its held lock.
                with setup.install_lock_held():
                    try:
                        setup.probe_environment(cancel_check=cancelled)
                    except setup.SetupError as exc:
                        engine = proto.BUSY if str(exc) == (
                            rt.MACHINE_BUSY_MESSAGE + ' Everything downloaded so far is kept.') else proto.UNVERIFIED
            except setup.SetupError:
                engine = proto.BUSY  # InstallLock refusal, never proof of damage
    return Observation(local, engine, busy)


def file_state(root, path, row):
    """Hash bytes, ignoring records/filename/mtime caches. Absence has no write side effect."""
    path = Path(path)
    if venv_layout.unsafe_component(root, path) is not None:
        return proto.UNVERIFIED
    if not os.path.lexists(path):
        return proto.MISSING
    try:
        with storage.boundary(root, path), open(path, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return proto.UNVERIFIED
            try:
                storage.verify_stream(stream, row)
            except storage.ArtifactError:
                return proto.DAMAGED
        return proto.READY
    except (OSError, storage.ArtifactError):
        return proto.UNVERIFIED


@dataclass(frozen=True)
class Plan:
    selected: tuple
    engine_action: str
    _document: bytes

    def to_json(self):
        return json.loads(self._document)

    @property
    def terms(self):
        return self.to_json()['terms']


@dataclass(frozen=True)
class Confirmation:
    # The original displayed plan/history is retained, not reconstructed from consent.
    plan: Plan
    raw_consent: bytes
    session: str
    request_id: str


@dataclass(frozen=True)
class Result:
    state: str
    message: str
    consent_spent: bool = False
    transfer_state: dict | None = None


class Planner:
    def __init__(self, *, observer=observe, disk_free=setup.free_bytes, retry_bytes=0,
                 shared_retry_bytes=0, purpose='fresh-machine'):
        storage.require(type(retry_bytes) is int and retry_bytes >= 0
                        and type(shared_retry_bytes) is int and shared_retry_bytes >= 0,
                        'invalid independently configured retry policy')
        self.observer, self.disk_free = observer, disk_free
        self.retry_bytes, self.shared_retry_bytes, self.purpose = retry_bytes, shared_retry_bytes, purpose

    def plan(self, selected, *, engine_action='none', cancelled=lambda: False):
        try:
            return self._evaluate(selected, engine_action, locked=False, cancelled=cancelled)[0]
        except (storage.ArtifactError, packages.ManifestError, OSError, rt.Qwen3Unavailable) as exc:
            selected = proto._wire_selection(list(selected), allow_empty=False)
            return Plan(selected, engine_action, storage.canonical({
                'components': [{'id': c, 'readiness': proto.UNVERIFIED, 'scope': None} for c in selected],
                'engine_readiness': proto.UNVERIFIED, 'terms': None, 'prior_state': None,
                'reasons': [str(exc)], 'operations': {c: 'none' for c in selected}}))

    def _evaluate(self, selected, engine_action, *, locked, cancelled):
        selected = proto._wire_selection(list(selected), allow_empty=False)
        storage.require(engine_action in v3.ENGINE_ACTIONS, 'unknown engine action')
        if locked:
            storage.require(setup.InstallLock.held_by_this_thread(), 'final validation requires InstallLock')
        setup._check_cancel(cancelled)
        reviewed = reviewed_packages()
        storage.require(model_identities_sha256() == MODEL_IDENTITIES_SHA256, 'unreviewed Qwen model manifest')
        observation = self.observer(selected, locked=locked, cancelled=cancelled)
        storage.require(type(observation) is Observation and observation.engine in proto.READINESS,
                        'unproved environment observation')
        root = rt.repo_root()
        items, states, reasons = {}, {}, []

        def add(component, group, name, size, digest, url, revision, target=None, candidates=()):
            rt.check_relative_name(name)
            # Content-shared Qwen files get one immutable source and one transfer.
            artifact_id = group + ':' + digest
            row = {'id': artifact_id, 'kind': 'model', 'components': [component], 'name': group,
                   'version': MODEL_IDENTITIES_SHA256 if group == 'qwen3-file' else 'reviewed',
                   'filename': Path(name).name, 'size': size, 'sha256': digest,
                   'source': {'kind': 'pinned-https', 'url': url, 'revision': revision}, 'derivative': None}
            item = items.setdefault(artifact_id, {'row': row, 'targets': [], 'candidates': []})
            storage.require(item['row']['size'] == size, 'conflicting shared identity')
            if component not in item['row']['components']:
                item['row']['components'].append(component)
            if target is not None:
                current = file_state(root, target, row)
                states.setdefault(component, []).append(current)
                item['targets'].append((component, target, current))
            item['candidates'].extend(candidates)

        for component in selected:
            if component in proto.QWEN3_MODEL_KEYS:
                key = proto.QWEN3_MODEL_KEYS[component]
                spec = rt.model_spec(key)
                for name, want in spec.files.items():
                    twins = [rt.safe_model_path(other, name) for k in rt.MODEL_KEYS
                             for other in (rt.model_spec(k),) if other.files.get(name) == want]
                    add(component, 'qwen3-file', name, want['size'], want['sha256'], setup.hub_url(spec, name),
                        spec.revision, rt.safe_model_path(spec, name), twins)
            else:
                group = assets.kokoro_set() if component == proto.KOKORO else assets.chatterbox_set()
                names = tuple(group.files) if component == proto.CHATTERBOX else (
                    *assets.KOKORO_MODEL_NAMES, *(assets.kokoro_voice_name(v) for v in old_plan.kokoro_roster()))
                for name in names:
                    storage.require(name in group.files, 'unreviewed local voice asset')
                    size, digest = group.files[name]
                    target = assets.snapshot_dir(group).joinpath(*name.split('/'))
                    add(component, component, name, size, digest,
                        setup.HUB_URL.format(repo=group.repo, revision=group.revision, path=name), group.revision,
                        target, [target])
                if component == proto.KOKORO:
                    spacy, _ = assets.spacy_english_state()
                    states[component].append(spacy)
                    if spacy == proto.MISSING:
                        add(component, 'spacy-english', assets.SPACY_WHEEL_NAME, assets.SPACY_WHEEL_SIZE,
                            assets.SPACY_WHEEL_SHA256, assets.SPACY_WHEEL_URL, assets.SPACY_WHEEL_SHA256)

        components = []
        for component in selected:
            current = states.get(component, [])
            qwen = component in proto.QWEN3_MODEL_KEYS
            engine = observation.engine if qwen else (
                proto.READY if observation.health.get(component) is True else
                proto.DAMAGED if observation.health.get(component) is False else proto.UNVERIFIED)
            unsupported = not rt.platform_supported() if qwen else bool(old_plan._local_engine_unsupported(old_plan.Facts()))
            bad_bundle = qwen and (not rt.bundle_status()[0] or (
                component == proto.QWEN3_BASE and bool(old_plan._reference_problem())))
            if unsupported:
                state = proto.UNSUPPORTED
            elif bad_bundle:
                state = proto.BAD_BUNDLE
            elif component in observation.busy:
                state = proto.BUSY
            elif proto.UNVERIFIED in current or engine == proto.UNVERIFIED:
                state = proto.UNVERIFIED
            elif engine != proto.READY:
                state = engine
            elif proto.DAMAGED in current:
                state = proto.DAMAGED
            elif proto.MISSING in current:
                state = proto.DAMAGED if qwen and rt.marker_path(proto.QWEN3_MODEL_KEYS[component]).is_file() else proto.MISSING
            elif qwen and not rt.model_status(proto.QWEN3_MODEL_KEYS[component])[0]:
                state = proto.MISSING  # legitimate zero-transfer re-verification/marker repair
            else:
                state = proto.READY
            components.append({'id': component, 'readiness': state, 'scope': proto.acquisition_scope(state)})
            if state not in (proto.READY, proto.MISSING, proto.DAMAGED):
                reasons.append(component + ': ' + state)
            if engine != proto.READY and (not qwen or engine_action == 'none'):
                reasons.append(component + ': engine authority/health required')

        scopes = {c['id']: c['scope'] for c in components}
        if engine_action != 'none':
            required = {'install-missing': proto.MISSING, 'rebuild-canonical': proto.DAMAGED}[engine_action]
            if observation.engine != required or not any(c in proto.QWEN3_MODEL_KEYS for c in selected):
                reasons.append('explicit engine action lacks proved matching engine state')
            owners = [c for c in selected if c in proto.QWEN3_MODEL_KEYS and scopes[c] is not None]
            for wheel in reviewed.wheels:
                row = {'id': 'qwen3-package:' + wheel.name, 'kind': 'package', 'components': owners,
                       'name': wheel.name, 'version': wheel.version, 'filename': wheel.filename,
                       'size': wheel.size, 'sha256': wheel.sha256,
                       'source': {'kind': 'pinned-https', 'url': wheel.source_url, 'revision': wheel.sha256},
                       'derivative': None}
                if wheel.name == 'sox':
                    row.update(source={'kind': 'local-derived', 'url': None, 'revision': packages.SOX_SOURCE_SHA256},
                        derivative={'source_filename': 'sox-1.5.0.tar.gz', 'source_size': 63905,
                                    'source_sha256': packages.SOX_SOURCE_SHA256,
                                    'output_sha256': packages.SOX_WHEEL_SHA256,
                                    'build_inputs_sha256': hashlib.sha256(storage.canonical(
                                        json.loads(reviewed._document)['build_only'])).hexdigest()})
                items[row['id']] = {'row': row, 'targets': [], 'candidates': []}

        rows = []
        for item in items.values():
            row = item['row']
            row['components'] = [c for c in selected if c in row['components'] and scopes[c] is not None]
            if not row['components']:
                continue
            # Probe the fixed store identity read-only, using provisional non-reuse terms below.
            row.update(verified_reuse_bytes=0, expected_new_bytes=row['size'],
                       retry_headroom_bytes=self.retry_bytes, max_payload_bytes=row['size'] + self.retry_bytes)
            if row['source']['kind'] == 'local-derived':
                row.update(verified_reuse_bytes=row['size'], expected_new_bytes=0,
                           retry_headroom_bytes=0, max_payload_bytes=0)
            rows.append(row)

        def terms_for(artifacts, disk):
            expected = sum(a['expected_new_bytes'] for a in artifacts)
            retry = min(self.shared_retry_bytes, sum(a['retry_headroom_bytes'] for a in artifacts))
            return {'schema': 'act-acquisition-terms', 'version': 1, 'target': packages.TARGET,
                    'manifest_sha256': reviewed.content_sha256, 'runtime_lock_sha256': packages.ORIGINAL_LOCK_SHA256,
                    'effective_lock_sha256': reviewed.effective_lock_sha256, 'components': components,
                    'engine_action': engine_action, 'engine_readiness': observation.engine,
                    'artifacts': sorted(artifacts, key=lambda a: a['id']),
                    'payload': {'expected_new_bytes': expected, 'retry_headroom_bytes': retry,
                                'max_payload_bytes': expected + retry}, 'disk': disk}

        prior = None
        terms = None
        engine_disk = rt.environment_installed_bytes() if engine_action != 'none' else 0
        spacy_disk = old_plan.SPACY_ENGLISH_INSTALLED_BYTES if any(
            row['name'] == 'spacy-english' for row in rows) else 0
        if not reasons:
            provisional = storage.Catalog(terms_for(rows, {'new_bytes': 0, 'temporary_headroom_bytes': 0}),
                                          package_manifest=reviewed, purpose=self.purpose)
            object_store = storage.ArtifactStore(root, provisional)
            new_disk = 0
            for row in rows:
                item = items[row['id']]
                blob, metadata = object_store._paths(row['id'])
                stored = False
                if os.path.lexists(blob) or os.path.lexists(metadata):
                    object_store.verify(row['id'])  # corrupt/orphan store is not silently replaced
                    stored = True
                candidate = next((p for p in item['candidates'] if file_state(root, p, row) == proto.READY), None)
                item['candidate'], item['stored'] = candidate, stored
                if stored or candidate is not None:
                    row.update(verified_reuse_bytes=row['size'], expected_new_bytes=0,
                               retry_headroom_bytes=0, max_payload_bytes=0)
                if row['source']['kind'] == 'local-derived' and not stored:
                    reasons.append('BLOCKED: approved local sox supply missing; no build or portable supply')
                new_disk += (0 if stored else row['size']) + sum(
                    row['size'] for _, _, state in item['targets'] if state != proto.READY)
            # Preserve full-operation disk disclosure even though wheel consumption
            # is deferred. These measured installed bounds never authorize payload.
            new_disk += engine_disk + spacy_disk
            disk = {'new_bytes': new_disk, 'temporary_headroom_bytes': max(
                (a['size'] for a in rows), default=0) + spacy_disk + old_plan.QWEN3_DISK_MARGIN_BYTES}
            terms = v3.validate_terms(terms_for(rows, disk))
            prior = transfer.TransferLedger(storage.ArtifactStore(root, storage.Catalog(
                terms, package_manifest=reviewed, purpose=self.purpose))).prior_state()
            if reasons:
                terms = None
        document = {'components': components, 'engine_readiness': observation.engine, 'terms': terms,
                    'prior_state': prior, 'reasons': reasons,
                    'installed_disk_bounds': {'engine': {'bytes': engine_disk, 'basis': 'approximate'},
                                              'spacy': {'bytes': spacy_disk, 'basis': 'approximate'}},
                    'operations': {c['id']: c['scope'] or 'none' for c in components}}
        return Plan(selected, engine_action, storage.canonical(document)), items, reviewed

    def acquire_disposable(self, confirmation, *, opener, cancelled=lambda: False, simulate_engine=None):
        """Explicit test seam. No default network or environment executor; no production caller.

        All selected groups and original history are checked under ONE existing lock.
        Reductions are changes too. Exactly one Result; a failed spent operation is terminal.
        """
        operation = None
        claim_path = None
        try:
            storage.require(type(confirmation) is Confirmation, 'original planning confirmation required')
            with setup.InstallLock():
                fresh, items, reviewed = self._evaluate(confirmation.plan.selected, confirmation.plan.engine_action,
                                                       locked=True, cancelled=cancelled)
                storage.require(fresh.terms is not None, 'selected groups are not authorizable: ' +
                                '; '.join(fresh.to_json()['reasons']))
                storage.require(fresh._document == confirmation.plan._document,
                                'all-group plan/history changed; new confirmation required')
                consent = v3.decode_consent(confirmation.raw_consent, session=confirmation.session,
                                            request_id=confirmation.request_id)
                storage.require(consent.terms == v3._canonical(fresh.terms), 'exact v3 terms required')
                storage.require(self.disk_free(rt.repo_root()) >= sum(fresh.terms['disk'].values()),
                                'insufficient disk/temp headroom')
                if fresh.engine_action != 'none':
                    storage.require(simulate_engine is not None, 'engine execution deferred to Stage 4B-3B')
                setup._check_cancel(cancelled)
                object_store = storage.ArtifactStore(rt.repo_root(), storage.Catalog(
                    fresh.terms, package_manifest=reviewed, purpose=self.purpose))
                ledger = transfer.TransferLedger(object_store)
                candidate_claim = ledger.root / consent.consent_id
                storage.require(not os.path.lexists(candidate_claim), 'v3 consent already spent')
                native = _NativeAuthority(self, fresh, object_store, items, cancelled)
                if fresh.engine_action == 'none':
                    # The native boundary's later health check must precede even local
                    # imports/transfer spending, across all selected groups.
                    for component in fresh.selected:
                        if component in proto.QWEN3_MODEL_KEYS and any(
                                c['id'] == component and c['scope'] is not None for c in fresh.terms['components']):
                            native.before_model(proto.QWEN3_MODEL_KEYS[component])
                for row in object_store.catalog.artifacts:
                    item = items[row['id']]
                    if row['verified_reuse_bytes'] and not item['stored']:
                        _import_candidate(object_store, row, item['candidate'], cancelled)
                claim_path = candidate_claim
                operation = ledger.begin(confirmation.raw_consent, session=confirmation.session,
                    request_id=confirmation.request_id, disclosed_prior_state=confirmation.plan.to_json()['prior_state'])
                setup._check_cancel(cancelled)
                with setup.scoped_model_acquisition(native):
                    if fresh.engine_action != 'none':
                        simulate_engine(fresh.terms)  # synthetic inspection only; native env boundary still refuses
                    else:
                        for row in object_store.catalog.artifacts:
                            if not row['verified_reuse_bytes']:
                                transfer.acquire(object_store, operation, row['id'], opener=opener, cancelled=cancelled)
                        # All transfers complete before publishing any model changes.
                        for component in fresh.selected:
                            if not next(c['scope'] for c in fresh.terms['components'] if c['id'] == component):
                                continue
                            setup._check_cancel(cancelled)
                            if component in proto.QWEN3_MODEL_KEYS:
                                setup.install_model(proto.QWEN3_MODEL_KEYS[component], cancel_check=cancelled)
                            else:
                                for row in object_store.catalog.artifacts:
                                    for owner, path, state in items[row['id']]['targets']:
                                        if owner == component and state != proto.READY:
                                            _publish_model(object_store, row, path, state, cancelled)
                setup._check_cancel(cancelled)
                operation.finish()
                return Result(proto.SUCCEEDED, 'Synthetic engine authority validated' if fresh.engine_action != 'none'
                              else 'Verified model artifacts acquired; package/spaCy installation remains deferred',
                              True, operation.state)
        except (storage.ArtifactError, packages.ManifestError, proto.ProtocolError, setup.SetupError, rt.Qwen3Unavailable,
                setup.SetupCancelled, OSError) as exc:
            spent = operation is not None or (claim_path is not None and os.path.lexists(claim_path))
            state = proto.CANCELLED if isinstance(exc, (setup.SetupCancelled, transfer.TransferCancelled)) else (
                proto.FAILED if spent else proto.REFUSED)
            terminal = None
            try:
                if operation is not None:
                    if operation.state['status'] == 'open':
                        with operation.exclusive():
                            operation._record('cancel' if state == proto.CANCELLED else 'finish')
                    terminal = operation.state
            except (storage.ArtifactError, OSError):
                # A poisoned/uncertain journal cannot be repaired/refunded here.
                # Still return one terminal result and retain the durable claim.
                return Result(proto.FAILED, str(exc) + '; uncertain ledger requires review', True)
            return Result(state, str(exc), spent, terminal)


def _copy_verified(root, source, target, row, cancelled):
    """Independent verified copy; allows existing native shared hardlinks as read-only inputs.

    No receipt/candidate is a consumption proof. Hash the copy before publication.
    """
    storage.mkdirs(root, target.parent)
    with storage.boundary(root, source), open(source, 'rb') as incoming, storage.checked_open(root, target, 'xb') as out:
        remaining = row['size']
        while remaining:
            setup._check_cancel(cancelled)
            block = incoming.read(min(storage.BLOCK, remaining))
            storage.require(bool(block), 'local input changed during copy')
            out.write(block)
            remaining -= len(block)
        out.flush()
        os.fsync(out.fileno())
    with storage.checked_open(root, target, 'rb') as stream:
        storage.verify_stream(stream, row)


def _import_candidate(object_store, row, candidate, cancelled):
    storage.require(candidate is not None, 'verified local reuse disappeared')
    partial = object_store.new_partial()
    _copy_verified(object_store.repo, candidate, partial, row, cancelled)
    object_store.promote(row['id'], partial)


def _publish_model(object_store, row, target, expected_state, cancelled):
    storage.require(setup.InstallLock.held_by_this_thread(), 'model publication requires InstallLock')
    storage.require(file_state(object_store.repo, target, row) == expected_state,
                    'model readiness changed at mutation; reconfirm')
    object_store.verify(row['id'])
    blob, _ = object_store._paths(row['id'])
    partial = target.with_name(proto.new_token() + '.part')
    _copy_verified(object_store.repo, blob, partial, row, cancelled)
    setup._check_cancel(cancelled)
    with storage.boundary(object_store.repo, target):
        if os.path.lexists(target):
            target.unlink()
    storage.publish(object_store.repo, partial, target)
    storage.require(file_state(object_store.repo, target, row) == proto.READY, 'model publication failed identity proof')


class _NativeAuthority:
    def __init__(self, planner, plan, object_store, items, cancelled):
        self.planner, self.plan, self.store, self.items, self.cancelled = planner, plan, object_store, items, cancelled
        self.engine_action = plan.engine_action

    def before_model(self, key):
        storage.require(setup.InstallLock.held_by_this_thread(), 'native mutation requires InstallLock')
        component = next(c for c, k in proto.QWEN3_MODEL_KEYS.items() if k == key)
        storage.require(any(c['id'] == component and c['scope'] is not None
                            for c in self.plan.terms['components']), 'unconsented native model operation')
        observed = self.planner.observer(self.plan.selected, locked=True, cancelled=self.cancelled)
        storage.require(self.engine_action == 'none' and observed.engine == proto.READY
                        and component not in observed.busy,
                        'model-only operation cannot repair an unhealthy or unproved engine')

    def ensure_file(self, key, name, target):
        spec = rt.model_spec(key)
        storage.require(model_identities_sha256() == MODEL_IDENTITIES_SHA256, 'native model manifest changed')
        matches = [(row, path, state) for row in self.store.catalog.artifacts
                   for owner, path, state in self.items[row['id']]['targets']
                   if proto.QWEN3_MODEL_KEYS.get(owner) == key and path == target]
        storage.require(len(matches) == 1 and spec.files[name]['sha256'] == matches[0][0]['sha256'],
                        'unconsented native file')
        row, path, state = matches[0]
        if state == proto.READY:
            storage.require(file_state(self.store.repo, path, row) == proto.READY, 'reused model changed at mutation')
        else:
            _publish_model(self.store, row, path, state, self.cancelled)
