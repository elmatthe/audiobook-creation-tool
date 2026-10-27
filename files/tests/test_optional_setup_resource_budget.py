"""4D-2C: fixed admission and actual disposable Windows producer integration."""
import contextlib
import ast
import hashlib
import json
import os
from pathlib import Path

import pytest

from shared import artifact_store as store
from shared import artifact_transfer as transfer
from shared import optional_setup_resource_budget as rb
from shared import optional_setup_protocol as proto
from shared import optional_setup_v3 as v3
from tts import qwen3_engine_authority as engine
from tts import qwen3_runtime as rt
from tts import qwen3_setup as setup
from test_artifact_transfer import operation, retry_terms
from test_artifact_store import terms
from test_optional_setup_v3 import SESSION, REQUEST, NOW
from test_optional_setup_authority import authority_world, world, sandbox, tiny_assets, confirmed
from test_qwen3_offline_engine import package_world
from test_optional_tts_setup import _junction

pytestmark = pytest.mark.usefixtures('production_writes_refused')


def test_native_metadata_read_identity(tmp_path):
    path = tmp_path / 'metadata.json'
    path.write_bytes(b'{}')
    with store.checked_open(tmp_path, path, 'rb') as handle:
        before = os.fstat(handle.fileno())
        handle.read()
        after = os.fstat(handle.fileno())
        keys = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
        print('NATIVE IDENTITY', [getattr(before, k) for k in keys],
              [getattr(after, k) for k in keys], transfer.metadata_identity(path), before == after)
    assert transfer.read_metadata(tmp_path, path, rb.Budget()) == b'{}'
    published = tmp_path / 'published.json'
    store.write_once(tmp_path, published, b'{}')
    with store.checked_open(tmp_path, published, 'rb') as handle:
        before = os.fstat(handle.fileno())
        handle.read()
        after = os.fstat(handle.fileno())
        print('PUBLISHED IDENTITY', [getattr(before, k) for k in keys],
              [getattr(after, k) for k in keys], transfer.metadata_identity(published), before == after)
    assert transfer.read_metadata(tmp_path, published, rb.Budget()) == b'{}'


@pytest.mark.parametrize('kind,limit', [('operations', 32), ('events', 4096),
                                     ('partials', 256), ('entries', 8192)])
def test_exact_fixed_counts(kind, limit):
    b = rb.Budget()
    b.take(kind, limit)
    assert b.counts[kind] == limit
    with pytest.raises(rb.ResourceLimit):
        b.take(kind)
    assert b.counts[kind] == limit
    for invalid in (True, False, -1, 1.0):
        with pytest.raises(ValueError):
            rb.Budget().take(kind, invalid)


def test_exact_bytes_deadline_and_cancellation():
    now = [0.0]
    b = rb.Budget(clock=lambda: now[0])
    b.charge(16 * 1024 * 1024)
    now[0] = 30
    b.check()
    with pytest.raises(rb.ResourceLimit, match='byte'):
        b.charge(1)
    now[0] = 30.000001
    with pytest.raises(rb.ResourceLimit, match='deadline'):
        b.check()
    with pytest.raises(rb.Cancelled):
        rb.Budget(cancelled=lambda: True).check()
    for invalid in (True, -1, 1.0):
        with pytest.raises(ValueError):
            rb.Budget().charge(invalid)


def test_encoder_is_exact_incremental_and_cancellable():
    value = {'unicode': '\U0001f600\n\u00ff' * 2000, 'a': [True, None, 13, {'b': 2}]}
    b = rb.Budget()
    assert b.encode(value) == store.canonical(value)
    assert b.used_bytes == len(store.canonical(value))
    c = rb.Budget()
    c.charge(rb.MAX_BYTES - 6)
    with pytest.raises(rb.ResourceLimit):
        c.encode(value)
    assert c.used_bytes <= rb.MAX_BYTES
    checks = [0]
    def cancelled():
        checks[0] += 1
        return checks[0] > 20
    with pytest.raises(rb.Cancelled):
        rb.Budget(cancelled=cancelled).encode(value)


def test_empty_history_has_no_hidden_writes_and_entry_cancel(tmp_path):
    ledger = transfer.TransferLedger(store.ArtifactStore(tmp_path, store.Catalog(terms())))
    expected = {'schema': 'act-prior-transfer-state', 'version': 1, 'history': [], 'partials': []}
    assert ledger.prior_state(budget=rb.Budget()) == expected
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(transfer.TransferCancelled):
        ledger.prior_state(cancelled=lambda: True)
    assert list(tmp_path.iterdir()) == []


def test_real_chained_history_partials_and_shared_charging(tmp_path):
    depot, ledger, live, consent = operation(tmp_path)
    aid = depot.catalog.artifacts[0]['id']
    live._record('reserve', aid, 8)
    live._record('consume', aid, 3)
    live.finish()
    folder = depot.root / 'incomplete'
    folder.mkdir()
    partial = folder / ('e' * 32 + '.part')
    partial.write_bytes(b'abc')
    b = rb.Budget()
    prior = ledger.prior_state(budget=b)
    row = prior['history'][0]
    assert row['consent_id'] == consent.consent_id and row['sequence'] == 3
    assert row['state'] == {'status': 'spent', 'actual': {aid: 3}, 'reserved': {aid: 5}}
    assert row['chain'] == hashlib.sha256((live.folder / '00000002.json').read_bytes()).hexdigest()
    assert prior['partials'] == [{'name': partial.name, 'size': 3,
        'mtime_ns': partial.stat().st_mtime_ns, 'verified_reuse_bytes': 0}]
    assert b.counts == {'operations': 1, 'events': 3, 'partials': 1, 'entries': 0}
    raw_bytes = sum(p.stat().st_size for p in live.folder.iterdir())
    names = [live.folder.name, *(p.name for p in live.folder.iterdir()), partial.name]
    assert b.used_bytes == raw_bytes + sum(len(store.canonical(n)) for n in names) + sum(
        len(store.canonical(value)) for value in (row['state'], row, prior['partials'][0]))
    before = b.used_bytes
    assert b.encode(prior) == store.canonical(prior)
    assert b.used_bytes == before + len(store.canonical(prior))


@pytest.mark.parametrize('kind', ['operations', 'events', 'partials'])
def test_native_traversal_refuses_next_over_cap_without_truncation(tmp_path, kind):
    depot, ledger, live, _ = operation(tmp_path)
    if kind == 'events':
        live.finish()
    if kind == 'partials':
        folder = depot.root / 'incomplete'
        folder.mkdir()
        (folder / ('e' * 32 + '.part')).write_bytes(b'partial')
    before = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob('*'))
    b = rb.Budget()
    b.take(kind, rb.COUNTS[kind])
    with pytest.raises(rb.ResourceLimit):
        ledger.prior_state(budget=b)
    assert sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob('*')) == before


@pytest.mark.parametrize('damage', ['missing', 'chain', 'sequence', 'unexpected', 'directory'])
def test_uncertain_ledger_is_never_empty_or_cleaned(tmp_path, damage):
    _, ledger, live, _ = operation(tmp_path)
    live.finish()
    path = live.folder / '00000000.json'
    if damage == 'missing':
        path.rename(live.folder / '00000001.json')
    elif damage in ('chain', 'sequence'):
        event = json.loads(path.read_bytes())
        event['previous' if damage == 'chain' else 'seq'] = '0' * 64 if damage == 'chain' else 1
        path.write_bytes(store.canonical(event))
    elif damage == 'unexpected':
        (live.folder / 'unexpected').write_bytes(b'evidence')
    else:
        path.unlink()
        path.mkdir()
    with pytest.raises(store.ArtifactError):
        ledger.prior_state()
    assert live.folder.exists()


def test_begin_refusal_precedes_claim_and_preserves_history(tmp_path):
    depot, ledger, live, _ = operation(tmp_path)
    prior = ledger.prior_state()
    live.finish()
    consent = v3.new_consent(depot.catalog.terms, session=SESSION, request_id=REQUEST, now=lambda: NOW)
    raw = v3.encode_consent(consent)
    with pytest.raises(store.ArtifactError, match='changed'):
        ledger.begin(raw, session=SESSION, request_id=REQUEST, disclosed_prior_state=prior, now=lambda: NOW)
    assert not (ledger.root / consent.consent_id).exists()
    b = rb.Budget()
    b.charge(rb.MAX_BYTES)
    with pytest.raises(rb.ResourceLimit):
        ledger.begin(raw, session=SESSION, request_id=REQUEST, disclosed_prior_state=ledger.prior_state(),
                     budget=b, now=lambda: NOW)
    assert not (ledger.root / consent.consent_id).exists()


def test_known_unbounded_retry_workflow_cannot_spend(tmp_path):
    value = retry_terms(shared_retry=8 * 4096, artifact_retry=8 * 4096)
    depot = store.ArtifactStore(tmp_path, store.Catalog(value))
    ledger = transfer.TransferLedger(depot)
    consent = v3.new_consent(value, session=SESSION, request_id=REQUEST, now=lambda: NOW)
    with pytest.raises(rb.ResourceLimit, match='events'):
        ledger.begin(v3.encode_consent(consent), session=SESSION, request_id=REQUEST,
                     disclosed_prior_state=ledger.prior_state(), now=lambda: NOW)
    assert not ledger.root.exists()


def test_actual_planner_preserves_original_bytes_and_cancels_history(authority_world, monkeypatch):
    from tts import optional_setup_authority as auth
    root, planner, _, calls, _, _ = authority_world
    plan = planner.plan([proto.CHATTERBOX])
    assert plan._document == store.canonical(plan.to_json()) and plan.terms is not None
    assert not (root / store.STORE).exists() and not calls
    original = transfer.TransferLedger.prior_state
    reached = [False]
    def enter(ledger, **kwargs):
        reached[0] = True
        assert kwargs['cancelled'] is cancelled
        return original(ledger, **kwargs)
    def cancelled():
        return reached[0]
    monkeypatch.setattr(transfer.TransferLedger, 'prior_state', enter)
    with pytest.raises(setup.SetupCancelled):
        planner.plan([proto.CHATTERBOX], cancelled=cancelled)
    assert not (root / store.STORE).exists()


def historical(ledger, index):
    """Real valid persisted initial/terminal chain, no replaced producer implementation."""
    consent = v3.new_consent(ledger.store.catalog.terms, session=SESSION,
                             request_id=f'{index:032x}', now=lambda: NOW)
    folder = ledger.root / consent.consent_id
    folder.mkdir(parents=True)
    initial = store.canonical({'schema': 'act-transfer-ledger', 'version': 1,
        'authorization': consent.to_json(), 'disclosed_prior_state': '0' * 64})
    (folder / 'initial.json').write_bytes(initial)
    event = store.canonical({'schema': 'act-transfer-event', 'version': 1, 'seq': 0,
        'previous': hashlib.sha256(initial).hexdigest(), 'action': 'finish', 'artifact': None, 'bytes': 0})
    (folder / '00000000.json').write_bytes(event)
    return folder


def test_native_32_operations_and_aggregate_events_preserved(tmp_path):
    ledger = transfer.TransferLedger(store.ArtifactStore(tmp_path, store.Catalog(terms())))
    for i in range(32):
        historical(ledger, i)
    b = rb.Budget()
    prior = ledger.prior_state(budget=b)
    assert len(prior['history']) == 32 and b.counts['events'] == 32
    assert all(row['sequence'] == 1 and row['state']['status'] == 'spent' for row in prior['history'])
    assert [row['consent_id'] for row in prior['history']] == sorted(row['consent_id'] for row in prior['history'])
    exact = rb.Budget()
    exact.take('events', 4096 - 32)
    assert ledger.prior_state(budget=exact) == prior and exact.counts['events'] == 4096
    over = rb.Budget()
    over.take('events', 4096 - 31)
    with pytest.raises(rb.ResourceLimit, match='events'):
        ledger.prior_state(budget=over)
    historical(ledger, 33)
    with pytest.raises(rb.ResourceLimit, match='operations'):
        ledger.prior_state()
    assert len(list(ledger.root.iterdir())) == 33


def test_native_256_partials_preserved_then_257_refuses(tmp_path):
    ledger = transfer.TransferLedger(store.ArtifactStore(tmp_path, store.Catalog(terms())))
    folder = ledger.store.root / 'incomplete'
    folder.mkdir(parents=True)
    for i in range(256):
        (folder / f'{i:032x}.part').write_bytes(b'x' * (i % 3))
    prior = ledger.prior_state()
    assert len(prior['partials']) == 256
    assert [row['name'] for row in prior['partials']] == [f'{i:032x}.part' for i in range(256)]
    assert all(row['size'] == i % 3 and row['verified_reuse_bytes'] == 0 for i, row in enumerate(prior['partials']))
    (folder / f'{256:032x}.part').write_bytes(b'last')
    with pytest.raises(rb.ResourceLimit, match='partials'):
        ledger.prior_state()
    assert len(list(folder.iterdir())) == 257


def test_live_append_headroom_and_replay_are_bounded(tmp_path, monkeypatch):
    depot, ledger, live, _ = operation(tmp_path, retry_terms())
    original = ledger._read
    def near_limit(folder, *, budget=None, **kwargs):
        result = original(folder, budget=budget, **kwargs)
        if budget is not None:
            budget.take('events', 4093)
        return result
    monkeypatch.setattr(ledger, '_read', near_limit)
    aid = depot.catalog.artifacts[0]['id']
    live._record('reserve', aid, 8)  # 4093 + reserve + consume + terminal == 4096
    before = sorted(live.folder.iterdir())
    with pytest.raises(rb.ResourceLimit, match='events'):
        live._record('reserve', aid, 8)
    assert sorted(live.folder.iterdir()) == before
    live._record('consume', aid, 8)
    live.finish()
    assert live.state['status'] == 'spent' and live._sequence == 3
    assert original(live.folder)[2] == 3


def representative_engine(root):
    canonical = rt.nested_venv_dir()
    canonical.mkdir(parents=True, exist_ok=True)
    (canonical / 'z.txt').write_bytes(b'weight stand-in')
    (canonical / 'a.txt').write_bytes(b'a')
    return canonical


def test_native_inventory_exact_identity_complete_sort_and_entry_boundary(authority_world):
    root = authority_world[0]
    canonical = representative_engine(root)
    b = rb.Budget()
    b.take('entries', 8189)
    result = engine.snapshot(budget=b)
    expected = [[name, transfer.metadata_identity(canonical / name)] for name in ('.', 'a.txt', 'z.txt')]
    assert result['entries'] == expected and b.counts['entries'] == 8192
    parent = rt.parent_venv_dir().stat()
    assert result['parent'] == [parent.st_dev, parent.st_ino]
    assert result['parent_cfg'] == hashlib.sha256((rt.parent_venv_dir() / 'pyvenv.cfg').read_bytes()).hexdigest()
    assert result['path'] == str(canonical) and result['canonical_exists'] and result['record'] == {}
    root_names = sum(len(store.canonical(p.name)) for p in root.iterdir())
    expected_bytes = root_names + (rt.parent_venv_dir() / 'pyvenv.cfg').stat().st_size
    expected_bytes += sum(len(store.canonical(row)) for row in expected)
    expected_bytes += sum(len(store.canonical(name)) for name in ('a.txt', 'z.txt'))
    expected_bytes += len(store.canonical({k: v for k, v in result.items() if k != 'entries'}))
    assert b.used_bytes == expected_bytes
    over = rb.Budget()
    over.take('entries', 8190)
    with pytest.raises(rb.ResourceLimit, match='entries'):
        engine.snapshot(budget=over)
    assert engine.snapshot()['entries'] == expected


def test_actual_planner_shares_history_inventory_and_encoding_budget(package_world, monkeypatch):
    root, planner = package_world[:2]
    # Native producer wrappers only observe; original implementations still run.
    prior, snapshot, encode = transfer.TransferLedger.prior_state, engine.snapshot, rb.Budget.encode
    seen = []
    def history(ledger, **kwargs):
        b = kwargs['budget']
        result = prior(ledger, **kwargs)
        b.charge(1000)
        seen.append(('history', b, b.used_bytes))
        return result
    def inventory(**kwargs):
        b = kwargs['budget']
        assert b is seen[0][1] and b.used_bytes >= seen[0][2]
        result = snapshot(**kwargs)
        seen.append(('inventory', b, b.used_bytes))
        return result
    def encoding(b, value):
        if 'components' in value and 'prior_state' in value:
            assert b is seen[0][1] is seen[1][1]
            before = b.used_bytes
            result = encode(b, value)
            assert result == store.canonical(value) and b.used_bytes == before + len(result)
            seen.append(('encoding', b, b.used_bytes))
            return result
        return encode(b, value)
    monkeypatch.setattr(transfer.TransferLedger, 'prior_state', history)
    monkeypatch.setattr(engine, 'snapshot', inventory)
    monkeypatch.setattr(rb.Budget, 'encode', encoding)
    plan = planner.plan([proto.QWEN3_CUSTOMVOICE], engine_action='install-missing')
    assert plan.terms is not None and [row[0] for row in seen] == ['history', 'inventory', 'encoding']
    assert plan._document == store.canonical(plan.to_json())
    # Each producer alone fits; sharing the remaining byte rejects final encoding.
    seen.clear()
    def filled_history(ledger, **kwargs):
        result = prior(ledger, **kwargs)
        kwargs['budget'].charge(rb.MAX_BYTES - kwargs['budget'].used_bytes - 100)
        return result
    monkeypatch.setattr(transfer.TransferLedger, 'prior_state', filled_history)
    monkeypatch.setattr(engine, 'snapshot', snapshot)
    monkeypatch.setattr(rb.Budget, 'encode', encode)
    refused = planner.plan([proto.QWEN3_CUSTOMVOICE], engine_action='install-missing')
    assert refused.terms is None and refused.to_json()['prior_state'] is None
    assert all(c['readiness'] == proto.UNVERIFIED for c in refused.to_json()['components'])


@pytest.mark.parametrize('phase', ['engine', 'encoding'])
def test_actual_planner_cancellation_during_engine_and_encoding(package_world, monkeypatch, phase):
    planner = package_world[1]
    reached = [False]
    if phase == 'engine':
        original = os.scandir
        def scan(path):
            if Path(path) == rt.parent_venv_dir().parent:
                reached[0] = True
            return original(path)
        monkeypatch.setattr(os, 'scandir', scan)
    else:
        original = rb.Budget.chunks
        def chunks(b, value):
            if type(value) is dict and 'prior_state' in value:
                for chunk in original(b, value):
                    reached[0] = True
                    yield chunk
            else:
                yield from original(b, value)
        monkeypatch.setattr(rb.Budget, 'chunks', chunks)
    with pytest.raises(setup.SetupCancelled):
        planner.plan([proto.QWEN3_CUSTOMVOICE], engine_action='install-missing', cancelled=lambda: reached[0])
    assert reached[0] and not list((rt.repo_root() / store.STORE / 'transfers').glob('*'))


def test_under_lock_fresh_budget_refuses_before_spend(authority_world, monkeypatch):
    root, planner, _, calls, opener, _ = authority_world
    confirmation = confirmed(planner, [proto.CHATTERBOX])
    prior = transfer.TransferLedger.prior_state
    seen = []
    def current(ledger, **kwargs):
        b = kwargs['budget']
        assert setup.InstallLock.held_by_this_thread()
        assert b.used_bytes == 0 and b.counts == dict.fromkeys(rb.COUNTS, 0)
        seen.append(b)
        b.charge(rb.MAX_BYTES)
        return prior(ledger, **kwargs)
    monkeypatch.setattr(transfer.TransferLedger, 'prior_state', current)
    result = planner.acquire_disposable(confirmation, opener=opener)
    assert result.state == proto.REFUSED and not result.consent_spent and not calls
    assert len(seen) == 1 and not (root / store.STORE / 'transfers').exists()


@pytest.mark.parametrize('target', ['history', 'inventory'])
@pytest.mark.parametrize('fault', ['deadline', 'cancel', 'inaccessible'])
def test_mid_traversal_refusal_has_no_partial_success(authority_world, monkeypatch, target, fault):
    root = authority_world[0]
    ledger = transfer.TransferLedger(store.ArtifactStore(root, store.Catalog(terms())))
    if target == 'history':
        historical(ledger, 1)
        watched = ledger.root
    else:
        watched = representative_engine(root)
    now, stop = [0.0], [False]
    b = rb.Budget(clock=lambda: now[0], cancelled=lambda: stop[0])
    scan = os.scandir
    @contextlib.contextmanager
    def injected(path):
        if Path(path) != watched:
            with scan(path) as rows:
                yield rows
            return
        if fault == 'inaccessible':
            raise PermissionError('fixture enumeration refused')
        with scan(path) as rows:
            def iterate():
                for row in rows:
                    if fault == 'deadline':
                        now[0] = 30.0001
                    else:
                        stop[0] = True
                    yield row
            yield iterate()
    monkeypatch.setattr(os, 'scandir', injected)
    expected = transfer.TransferCancelled if fault == 'cancel' else rb.ResourceLimit if fault == 'deadline' else OSError
    with pytest.raises(expected):
        ledger.prior_state(budget=b) if target == 'history' else engine.snapshot(budget=b)
    assert watched.exists()


def test_content_time_is_excluded_without_resetting_metadata_budget():
    now = [0.0]
    b = rb.Budget(clock=lambda: now[0])
    b.charge(123)
    now[0] = 10
    with b.content():
        now[0] = 1000
    assert b.used_bytes == 123
    now[0] = 1020
    b.check()  # Exactly 30 seconds of metadata, not 1020 seconds of hashing.
    now[0] += .001
    with pytest.raises(rb.ResourceLimit, match='deadline'):
        b.check()


def test_exact_16_mib_serialization_and_one_over():
    b = rb.Budget()
    encoded = b.encode('x' * (rb.MAX_BYTES - 2))
    assert len(encoded) == rb.MAX_BYTES == b.used_bytes
    with pytest.raises(rb.ResourceLimit):
        rb.Budget().encode('x' * (rb.MAX_BYTES - 1))


def test_actual_planner_mid_history_cancellation(authority_world, monkeypatch):
    root, planner = authority_world[:2]
    ledger = transfer.TransferLedger(store.ArtifactStore(root, store.Catalog(terms())))
    historical(ledger, 1)
    stop = [False]
    reads = []
    original_read = transfer.read_metadata
    def read(*args, **kwargs):
        reads.append(args[1])
        return original_read(*args, **kwargs)
    monkeypatch.setattr(transfer, 'read_metadata', read)
    scan = os.scandir
    @contextlib.contextmanager
    def enumerating(path):
        with scan(path) as rows:
            def iterate():
                for row in rows:
                    if Path(path) == ledger.root:
                        stop[0] = True
                    yield row
            yield iterate()
    monkeypatch.setattr(os, 'scandir', enumerating)
    with pytest.raises(setup.SetupCancelled):
        planner.plan([proto.CHATTERBOX], cancelled=lambda: stop[0])
    assert reads == [], 'cancellation must stop history before replay, not only during later encoding'
    assert len(list(ledger.root.iterdir())) == 1


@pytest.mark.parametrize('target', ['history', 'inventory'])
def test_native_junction_ancestry_is_refused(authority_world, target):
    root = authority_world[0]
    foreign = root / 'foreign'
    foreign.mkdir()
    (foreign / 'evidence').write_bytes(b'intact')
    ledger = transfer.TransferLedger(store.ArtifactStore(root, store.Catalog(terms())))
    link = ledger.root if target == 'history' else rt.parent_venv_dir() / 'engines'
    assert _junction(link, foreign), 'native junction qualification required'
    with pytest.raises(store.ArtifactError):
        ledger.prior_state() if target == 'history' else engine.snapshot()
    assert (foreign / 'evidence').read_bytes() == b'intact'


def test_late_substituted_metadata_open_is_refused(tmp_path, monkeypatch):
    import builtins
    _, ledger, live, _ = operation(tmp_path)
    other = tmp_path / 'substituted'
    other.write_bytes((live.folder / 'initial.json').read_bytes())
    original = builtins.open
    def replaced(path, mode='r', *args, **kwargs):
        return original(other if Path(path) == live.folder / 'initial.json' and mode == 'rb' else path,
                        mode, *args, **kwargs)
    monkeypatch.setattr(builtins, 'open', replaced)
    with pytest.raises(store.ArtifactError):
        ledger.prior_state()
    assert live.folder.exists()


def test_inventory_change_between_stat_and_return_is_refused(authority_world, monkeypatch):
    root = authority_world[0]
    canonical = representative_engine(root)
    original = transfer.metadata_identity
    changed = [False]
    def identity(path):
        result = original(path)
        if Path(path) == canonical / 'a.txt' and not changed[0]:
            changed[0] = True
            (canonical / 'a.txt').write_bytes(b'changed fixture')
        return result
    monkeypatch.setattr(transfer, 'metadata_identity', identity)
    with pytest.raises(store.ArtifactError, match='changed'):
        engine.snapshot()
    assert changed[0] and (canonical / 'a.txt').read_bytes() == b'changed fixture'


def test_complete_4096_event_replay_and_4097_refusal(tmp_path, monkeypatch):
    """Real replay/chain validator, streamed synthetic directory/file I/O at expensive count."""
    _, ledger, live, _ = operation(tmp_path)
    initial = (live.folder / 'initial.json').read_bytes()
    original_scan, original_read = os.scandir, transfer.read_metadata
    count, previous, reads = [4096], [hashlib.sha256(initial).hexdigest()], [0]
    class Entry:
        def __init__(self, name):
            self.name = name
        def is_file(self, **kwargs):
            return True
    @contextlib.contextmanager
    def scan(path):
        if Path(path) == live.folder:
            yield (Entry('initial.json' if i < 0 else f'{i:08d}.json') for i in range(-1, count[0]))
        else:
            with original_scan(path) as rows:
                yield rows
    def read(repo, path, budget):
        if path.parent != live.folder or path.name == 'initial.json':
            return original_read(repo, path, budget)
        seq = int(path.stem)
        event = {'schema': 'act-transfer-event', 'version': 1, 'seq': seq,
                 'previous': previous[0], 'action': 'finish' if seq == 4095 else 'consume',
                 'artifact': None if seq == 4095 else ledger.store.catalog.artifacts[0]['id'], 'bytes': 0}
        raw = store.canonical(event)
        budget.charge(len(raw))
        previous[0] = hashlib.sha256(raw).hexdigest()
        reads[0] += 1
        return raw
    monkeypatch.setattr(os, 'scandir', scan)
    monkeypatch.setattr(transfer, 'read_metadata', read)
    b = rb.Budget()
    result = ledger._read(live.folder, budget=b)
    assert result[2:] == (4096, previous[0]) and result[1]['status'] == 'spent'
    assert reads[0] == b.counts['events'] == 4096
    count[0] = 4097
    with pytest.raises(rb.ResourceLimit, match='events'):
        ledger._read(live.folder)
    assert reads[0] == 4096  # Refusal during enumeration, before any incomplete replay.


def test_budget_has_only_stdlib_imports_and_fixed_ceilings():
    tree = ast.parse(Path(rb.__file__).read_text())
    assert {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} == {'__future__'}
    assert {a.name for node in ast.walk(tree) if isinstance(node, ast.Import) for a in node.names} == {
        'contextlib', 'json', 'time'}
    assert (rb.MAX_OPERATIONS, rb.MAX_EVENTS, rb.MAX_PARTIALS, rb.MAX_ENTRIES,
            rb.MAX_BYTES, rb.MAX_SECONDS) == (32, 4096, 256, 8192, 16777216, 30)
    with pytest.raises(TypeError):
        rb.Budget(max_bytes=2**40)


def test_begin_cancellation_precedes_claim_even_after_history(tmp_path, monkeypatch):
    depot = store.ArtifactStore(tmp_path, store.Catalog(terms()))
    ledger = transfer.TransferLedger(depot)
    consent = v3.new_consent(depot.catalog.terms, session=SESSION, request_id=REQUEST, now=lambda: NOW)
    original = transfer._workflow_capacity
    stop = [False]
    def capacity(*args):
        original(*args)
        stop[0] = True
    monkeypatch.setattr(transfer, '_workflow_capacity', capacity)
    with pytest.raises(transfer.TransferCancelled):
        ledger.begin(v3.encode_consent(consent), session=SESSION, request_id=REQUEST,
            disclosed_prior_state=ledger.prior_state(), now=lambda: NOW, cancelled=lambda: stop[0])
    assert not ledger.root.exists()


def test_uncertain_live_journal_is_retained_without_terminal_fabrication(tmp_path):
    _, ledger, live, _ = operation(tmp_path)
    initial = live.folder / 'initial.json'
    initial.write_bytes(b'{}')
    with pytest.raises(store.ArtifactError):
        live.finish()
    assert initial.read_bytes() == b'{}' and not (live.folder / '00000000.json').exists()


def test_initial_ledger_read_limit_is_admitted_before_spending():
    with pytest.raises(rb.ResourceLimit, match='initial ledger'):
        transfer._workflow_capacity(terms(), {'padding': 'x' * v3.MAX_MESSAGE_BYTES})


def test_uncertain_absence_cannot_be_an_empty_history(tmp_path, monkeypatch):
    depot = store.ArtifactStore(tmp_path, store.Catalog(terms()))
    ledger = transfer.TransferLedger(depot)
    ledger.root.mkdir(parents=True)
    original = Path.lstat
    def denied(path):
        if path == ledger.root:
            raise PermissionError('fixture cannot determine directory existence')
        return original(path)
    monkeypatch.setattr(Path, 'lstat', denied)
    with pytest.raises((OSError, store.ArtifactError)):
        ledger.prior_state()


def test_zero_artifact_workflow_still_reserves_full_terminal_metadata(tmp_path):
    value = terms()
    value['artifacts'] = []
    value['payload'] = dict.fromkeys(value['payload'], 0)
    event_bytes, _ = transfer._journal_bounds(value)
    terminal = {'schema': 'act-transfer-event', 'version': 1, 'seq': rb.MAX_EVENTS - 1,
                'previous': 'f' * 64, 'action': 'cancel', 'artifact': None, 'bytes': 0}
    assert event_bytes >= len(store.canonical(terminal)) + len(store.canonical('00000000.json'))
    _, ledger, live, _ = operation(tmp_path, value)
    live.finish()
    assert live.state == {'status': 'spent', 'actual': {}, 'reserved': {}}
    assert ledger.prior_state()['history'][0]['sequence'] == 1


def test_changed_complete_history_at_lock_requires_new_confirmation(authority_world):
    root, planner, _, calls, opener, _ = authority_world
    confirmation = confirmed(planner, [proto.CHATTERBOX])
    ledger = transfer.TransferLedger(store.ArtifactStore(root, store.Catalog(terms())))
    folder = historical(ledger, 1)
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    result = planner.acquire_disposable(confirmation, opener=opener)
    assert result.state == proto.REFUSED and not result.consent_spent and not calls
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before
    assert list(ledger.root.iterdir()) == [folder]
