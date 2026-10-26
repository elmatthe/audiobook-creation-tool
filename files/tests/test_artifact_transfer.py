"""Bounded application-consumed HTTP body bytes, using injected responses only."""
import io
import copy
import json
from email.message import Message

import pytest

from shared import artifact_store as store
from shared import artifact_transfer as transfer
from shared import optional_setup_v3 as v3
from test_artifact_store import DATA, terms
from test_optional_setup_v3 import SESSION, REQUEST, NOW

pytestmark = pytest.mark.usefixtures('production_writes_refused')


class Response(io.BytesIO):
    def __init__(self, data=DATA, *, status=200, headers=None, url=None):
        super().__init__(data)
        self.status = status
        self.headers = {'Content-Length': str(len(DATA))} if headers is None else headers
        self.url = url or terms()['artifacts'][0]['source']['url']
        self.reads = []

    def geturl(self):
        return self.url

    def read(self, n=-1):
        assert 0 < n <= store.BLOCK
        self.reads.append(n)
        return super().read(n)


def operation(root, value=None):
    catalog = store.Catalog(value or terms())
    depot = store.ArtifactStore(root, catalog)
    ledger = transfer.TransferLedger(depot)
    consent = v3.new_consent(catalog.terms, session=SESSION, request_id=REQUEST, now=lambda: NOW)
    spend = ledger.begin(v3.encode_consent(consent), session=SESSION, request_id=REQUEST,
                         disclosed_prior_state=ledger.prior_state(), now=lambda: NOW)
    return depot, ledger, spend, consent


def acquire(depot, spend, response=None, cancel=lambda: False):
    calls = []
    def opener(request, *, timeout):
        calls.append(request)
        return response or Response()
    result = transfer.acquire(depot, spend, depot.catalog.artifacts[0]['id'], opener=opener, cancelled=cancel)
    return result, calls


def test_valid_bounded_transport(tmp_path):
    depot, ledger, spend, _ = operation(tmp_path)
    receipt, calls = acquire(depot, spend)
    assert receipt == depot.verify(depot.catalog.artifacts[0]['id'])
    assert len(calls) == 1 and not calls[0].has_header('Range')
    assert spend.state['actual'] == {depot.catalog.artifacts[0]['id']: 8}
    assert sum(spend.state['reserved'].values()) == 0
    spend.finish()


@pytest.mark.parametrize('response', [
    lambda: Response(status=302, headers={'Location': 'https://evil.invalid/file'}),
    lambda: Response(url='https://evil.invalid/file'),
    lambda: Response(headers={}),
    lambda: Response(headers={'Content-Length': '7'}),
    lambda: Response(headers={'Content-Length': '9'}),
    lambda: Response(headers={'Content-Length': '8', 'Content-Encoding': 'gzip'}),
    lambda: Response(status=206, headers={'Content-Length': '8', 'Content-Range': 'bytes 0-7/8'}),
    lambda: Response(headers={'Content-Length': '8', 'Content-Range': 'bytes 1-7/8'}),
    lambda: Response(data=b'abcd'),
    lambda: Response(data=b'ABCDEFGH'),
], ids=['redirect', 'response-url', 'missing-length', 'short-length', 'long-length', 'encoding',
        'unsupported-range', 'wrong-range', 'partial', 'hash'])
def test_bad_response_never_promotes(tmp_path, response):
    depot, _, spend, _ = operation(tmp_path)
    with pytest.raises(store.ArtifactError):
        acquire(depot, spend, response())
    with pytest.raises(store.ArtifactError):
        depot.verify(depot.catalog.artifacts[0]['id'])
    assert sum(spend.state['actual'].values()) + sum(spend.state['reserved'].values()) == 8


def test_cancel_before_transfer_spends_consent_without_request(tmp_path):
    depot, _, spend, _ = operation(tmp_path)
    with pytest.raises(transfer.TransferCancelled):
        acquire(depot, spend, cancel=lambda: True)
    assert spend.state['status'] == 'cancelled'
    assert sum(spend.state['actual'].values()) == 0
    with pytest.raises(store.ArtifactError):
        acquire(depot, spend)


def retry_terms(*, second=False, shared_retry=8, artifact_retry=8):
    value = terms()
    row = value['artifacts'][0]
    row.update(retry_headroom_bytes=artifact_retry, max_payload_bytes=8 + artifact_retry)
    if second:
        another = copy.deepcopy(row)
        another['id'] += '-second'
        value['artifacts'].append(another)
    expected = 8 * len(value['artifacts'])
    value['payload'] = {'expected_new_bytes': expected, 'retry_headroom_bytes': shared_retry,
                        'max_payload_bytes': expected + shared_retry}
    return value


def test_retry_uses_remaining_budget_and_never_resets_it(tmp_path):
    depot, _, spend, _ = operation(tmp_path, retry_terms())
    with pytest.raises(store.ArtifactError, match='hash'):
        acquire(depot, spend, Response(b'ABCDEFGH'))
    receipt, calls = acquire(depot, spend)
    assert len(calls) == 1 and receipt.size == 8
    assert sum(spend.state['actual'].values()) == 16
    assert sum(spend.state['reserved'].values()) == 0


@pytest.mark.parametrize('shared_retry,artifact_retry,expected', [
    (8, 8, 'per-artifact'), (0, 8, 'shared'),
])
def test_retry_exhaustion_is_refused_before_opener(tmp_path, shared_retry, artifact_retry, expected):
    depot, _, spend, _ = operation(tmp_path, retry_terms(shared_retry=shared_retry, artifact_retry=artifact_retry))
    for attempt in range(2 if shared_retry else 1):
        with pytest.raises(store.ArtifactError, match='hash'):
            acquire(depot, spend, Response(b'ABCDEFGH'))
    def forbidden(*args, **kwargs):
        pytest.fail('request began without allowance')
    with pytest.raises(store.ArtifactError, match=expected):
        transfer.acquire(depot, spend, depot.catalog.artifacts[0]['id'], opener=forbidden)


def test_retry_cannot_pay_with_another_artifacts_expected_bytes(tmp_path):
    depot, _, spend, _ = operation(tmp_path, retry_terms(second=True, shared_retry=0))
    first, second = depot.catalog.artifacts
    with pytest.raises(store.ArtifactError, match='hash'):
        acquire(depot, spend, Response(b'ABCDEFGH'))
    with pytest.raises(store.ArtifactError, match='borrow'):
        acquire(depot, spend)
    result = transfer.acquire(depot, spend, second['id'], opener=lambda *a, **k: Response())
    assert result.size == 8 and spend.state['actual'] == {first['id']: 8, second['id']: 8}


def test_per_artifact_ceiling_is_independent_of_generous_shared_budget(tmp_path):
    value = retry_terms(second=True)
    value['artifacts'][0].update(retry_headroom_bytes=0, max_payload_bytes=8)
    depot, _, spend, _ = operation(tmp_path, value)
    with pytest.raises(store.ArtifactError, match='hash'):
        acquire(depot, spend, Response(b'ABCDEFGH'))
    with pytest.raises(store.ArtifactError, match='per-artifact'):
        acquire(depot, spend)


def test_zero_byte_permission_refuses_replacement(tmp_path):
    value = terms()
    row = value['artifacts'][0]
    row.update(verified_reuse_bytes=8, expected_new_bytes=0, retry_headroom_bytes=0, max_payload_bytes=0)
    value['payload'] = {'expected_new_bytes': 0, 'retry_headroom_bytes': 0, 'max_payload_bytes': 0}
    catalog = store.Catalog(value)
    depot = store.ArtifactStore(tmp_path, catalog)
    source = tmp_path / 'source'
    source.write_bytes(DATA)
    depot.import_local(row['id'], source, source_url=row['source']['url'])
    ledger = transfer.TransferLedger(depot)
    consent = v3.new_consent(value, session=SESSION, request_id=REQUEST, now=lambda: NOW)
    spend = ledger.begin(v3.encode_consent(consent), session=SESSION, request_id=REQUEST,
                         disclosed_prior_state=ledger.prior_state(), now=lambda: NOW)
    # File disappearing after zero-byte confirmation cannot purchase a replacement.
    blob, meta = depot._paths(row['id'])
    blob.unlink()
    meta.unlink()
    with pytest.raises(store.ArtifactError, match='per-artifact'):
        acquire(depot, spend)
    assert sum(spend.state['actual'].values()) == 0


class Interrupt(Response):
    def __init__(self):
        super().__init__()
        self.once = False
    def read(self, n):
        if self.once:
            raise ConnectionError('interrupted stream')
        self.once = True
        return super().read(min(3, n))


def test_interrupted_stream_charges_actual_and_uncertain_remainder(tmp_path):
    depot, ledger, spend, _ = operation(tmp_path)
    with pytest.raises(ConnectionError):
        acquire(depot, spend, Interrupt())
    assert sum(spend.state['actual'].values()) == 3
    assert sum(spend.state['reserved'].values()) == 5
    snapshot = ledger.prior_state()
    assert snapshot['partials'][0]['size'] == 3 and snapshot['partials'][0]['verified_reuse_bytes'] == 0
    assert snapshot['history'][0]['state'] == spend.state
    with pytest.raises(store.ArtifactError, match='per-artifact'):
        acquire(depot, spend)


def test_cancel_during_read_charges_bytes_and_is_terminal(tmp_path):
    depot, _, spend, _ = operation(tmp_path)
    stopped = False
    class CancelResponse(Response):
        def read(self, n):
            nonlocal stopped
            stopped = True
            return super().read(min(n, 3))
    with pytest.raises(transfer.TransferCancelled):
        acquire(depot, spend, CancelResponse(), cancel=lambda: stopped)
    assert spend.state['status'] == 'cancelled'
    assert sum(spend.state['actual'].values()) == 3
    assert sum(spend.state['reserved'].values()) == 5
    with pytest.raises(store.ArtifactError, match='spent/cancelled'):
        acquire(depot, spend)


def test_crash_reservation_persists_and_old_consent_never_reopens(tmp_path):
    depot, ledger, spend, consent = operation(tmp_path)
    artifact = depot.catalog.artifacts[0]['id']
    spend._record('reserve', artifact, 8)  # crash after fsynced reservation, before response/settlement
    del spend
    restarted = transfer.TransferLedger(depot)
    disclosure = restarted.prior_state()
    assert disclosure['history'][0]['state']['reserved'] == {artifact: 8}
    assert disclosure['history'][0]['state']['actual'] == {artifact: 0}
    with pytest.raises(Exception) as caught:
        restarted.begin(v3.encode_consent(consent), session=SESSION, request_id=REQUEST,
                        disclosed_prior_state=disclosure, now=lambda: NOW)
    assert 'spent' in str(caught.value)
    fresh = v3.new_consent(depot.catalog.terms, session='c' * 32, request_id='d' * 32, now=lambda: NOW)
    new = restarted.begin(v3.encode_consent(fresh), session=fresh.session, request_id=fresh.request_id,
                          disclosed_prior_state=disclosure, now=lambda: NOW)
    assert sum(new.state['actual'].values()) == 0
    assert restarted.prior_state()['history'][0 if consent.consent_id < fresh.consent_id else 1]['state'][
        'reserved'] == {artifact: 8}


def test_new_session_refuses_old_consent_and_v2(tmp_path):
    depot, ledger, _, consent = operation(tmp_path)
    for raw, session in [(v3.encode_consent(consent), 'c' * 32),
                          (b'{"protocol":"act-optional-setup","version":2}', SESSION)]:
        with pytest.raises(Exception) as caught:
            ledger.begin(raw, session=session, request_id=REQUEST,
                         disclosed_prior_state=ledger.prior_state(), now=lambda: NOW)
        assert 'session' in str(caught.value).lower() or 'v3' in str(caught.value).lower()


def test_new_consent_must_disclose_newly_persisted_partial_state(tmp_path):
    depot, ledger, spend, _ = operation(tmp_path)
    shown = ledger.prior_state()
    with pytest.raises(store.ArtifactError):
        acquire(depot, spend, Response(b'abc'))
    assert shown != ledger.prior_state()
    fresh = v3.new_consent(depot.catalog.terms, session=SESSION, request_id='d' * 32, now=lambda: NOW)
    with pytest.raises(store.ArtifactError, match='disclose'):
        ledger.begin(v3.encode_consent(fresh), session=SESSION, request_id=fresh.request_id,
                     disclosed_prior_state=shown, now=lambda: NOW)
    new = ledger.begin(v3.encode_consent(fresh), session=SESSION, request_id=fresh.request_id,
                       disclosed_prior_state=ledger.prior_state(), now=lambda: NOW)
    receipt, calls = acquire(depot, new)
    assert receipt.size == 8 and len(calls) == 1 and not calls[0].has_header('Range')
    assert sorted(p['size'] for p in ledger.prior_state()['partials']) == [3]
    assert sum(new.state['actual'].values()) == 8  # no prefix discount


@pytest.mark.parametrize('damage', ['json', 'chain', 'unknown', 'gap', 'negative', 'initial', 'extra'])
def test_corrupt_ledger_is_refused(tmp_path, damage):
    depot, ledger, spend, _ = operation(tmp_path)
    artifact = depot.catalog.artifacts[0]['id']
    spend._record('reserve', artifact, 8)
    path = spend.folder / '00000000.json'
    record = json.loads(path.read_bytes())
    if damage == 'json':
        path.write_bytes(b'{')
    elif damage == 'gap':
        path.rename(path.with_name('00000001.json'))
    elif damage == 'initial':
        (spend.folder / 'initial.json').write_bytes(b'{}')
    else:
        if damage == 'chain':
            record['previous'] = '0' * 64
        elif damage == 'unknown':
            record['artifact'] = 'unapproved'
        elif damage == 'negative':
            record['bytes'] = -1
        else:
            record['extra'] = True
        path.write_bytes(store.canonical(record))
    with pytest.raises(store.ArtifactError):
        ledger.prior_state()


def test_finished_consent_cannot_be_reused(tmp_path):
    depot, _, spend, _ = operation(tmp_path)
    spend.finish()
    with pytest.raises(store.ArtifactError, match='spent/cancelled'):
        acquire(depot, spend)


def test_live_operation_detects_a_truncated_terminal_journal(tmp_path):
    depot, _, spend, _ = operation(tmp_path)
    spend.finish()
    (spend.folder / '00000000.json').unlink()
    with pytest.raises(store.ArtifactError, match='rolled back'):
        acquire(depot, spend)


def test_real_redirect_handler_never_follows_location():
    handler = transfer._NoRedirect()
    request = transfer.urllib.request.Request(terms()['artifacts'][0]['source']['url'])
    with pytest.raises(store.ArtifactError, match='redirect'):
        handler.redirect_request(request, None, 302, 'Moved', {}, 'https://evil.invalid/file')


@pytest.mark.parametrize('headers', [
    {'Content-Length': '8,8'}, {'Content-Length': '+8'}, {'Content-Length': '08'},
    {'Content-Length': '8', 'Transfer-Encoding': 'chunked'},
    {'Content-Length': '8', 'Content-Encoding': 'br'},
])
def test_ambiguous_or_encoded_response_refused(tmp_path, headers):
    depot, _, spend, _ = operation(tmp_path)
    response = Response(headers=headers)
    with pytest.raises(store.ArtifactError):
        acquire(depot, spend, response)
    assert response.reads == []


def test_duplicate_content_length_refused_before_read(tmp_path):
    depot, _, spend, _ = operation(tmp_path)
    headers = Message()
    headers['Content-Length'] = '8'
    headers['Content-Length'] = '8'
    response = Response(headers=headers)
    with pytest.raises(store.ArtifactError, match='ambiguous'):
        acquire(depot, spend, response)
    assert response.reads == []


def test_model_only_operation_cannot_request_a_package(tmp_path):
    depot, _, spend, _ = operation(tmp_path)
    with pytest.raises(store.ArtifactError, match='unknown'):
        transfer.acquire(depot, spend, 'qwen3-package:sox', opener=lambda *a, **k: pytest.fail('network'))


def test_operation_store_identity_mismatch_refused(tmp_path):
    depot, _, spend, _ = operation(tmp_path)
    other = store.ArtifactStore(tmp_path, depot.catalog)
    with pytest.raises(store.ArtifactError, match='identity mismatch'):
        transfer.acquire(other, spend, depot.catalog.artifacts[0]['id'])


def test_concurrent_operation_refused_before_request(tmp_path):
    depot, _, spend, _ = operation(tmp_path)
    with spend.exclusive():
        with pytest.raises(store.ArtifactError, match='concurrent'):
            acquire(depot, spend)


def test_failed_reservation_publication_cannot_start_network(tmp_path, monkeypatch):
    depot, _, spend, _ = operation(tmp_path)
    def unavailable(*args):
        raise OSError('ledger unavailable')
    monkeypatch.setattr(transfer, 'write_once', unavailable)
    with pytest.raises(OSError, match='ledger unavailable'):
        transfer.acquire(depot, spend, depot.catalog.artifacts[0]['id'],
                         opener=lambda *a, **k: pytest.fail('request began without durable reservation'))
    with pytest.raises(store.ArtifactError, match='uncertain'):
        acquire(depot, spend)


def test_connection_failure_has_no_implicit_retry_or_refund(tmp_path):
    depot, _, spend, _ = operation(tmp_path)
    calls = []
    def failed(*args, **kwargs):
        calls.append(args)
        raise ConnectionError('cannot connect')
    with pytest.raises(ConnectionError):
        transfer.acquire(depot, spend, depot.catalog.artifacts[0]['id'], opener=failed)
    assert len(calls) == 1
    assert sum(spend.state['actual'].values()) == 0 and sum(spend.state['reserved'].values()) == 8


def test_multiple_streaming_reads_are_bounded(tmp_path):
    import hashlib
    payload = b'x' * (store.BLOCK * 2 + 3)
    value = terms()
    row = value['artifacts'][0]
    row.update(size=len(payload), sha256=hashlib.sha256(payload).hexdigest(),
               expected_new_bytes=len(payload), retry_headroom_bytes=0, max_payload_bytes=len(payload))
    value['payload'] = {key: row[key] for key in ('expected_new_bytes', 'retry_headroom_bytes', 'max_payload_bytes')}
    depot, _, spend, _ = operation(tmp_path, value)
    response = Response(payload, headers={'Content-Length': str(len(payload))})
    acquire(depot, spend, response)
    assert response.reads == [store.BLOCK, store.BLOCK, 3]
    assert sum(spend.state['actual'].values()) == len(payload)


def test_failed_disk_write_still_pays_for_returned_body(tmp_path, monkeypatch):
    import contextlib
    depot, _, spend, _ = operation(tmp_path)
    original = transfer.checked_open
    @contextlib.contextmanager
    def failed_write(repo, path, mode):
        if mode == 'xb':
            class Target:
                def write(self, block):
                    raise OSError('disk full')
            yield Target()
        else:
            with original(repo, path, mode) as handle:
                yield handle
    monkeypatch.setattr(transfer, 'checked_open', failed_write)
    with pytest.raises(OSError, match='disk full'):
        acquire(depot, spend)
    assert sum(spend.state['actual'].values()) == 8


def test_missing_local_reuse_is_refused_before_spending_or_request(tmp_path):
    from test_artifact_store import package_terms
    value, manifest = package_terms()
    catalog = store.Catalog(value, package_manifest=manifest, purpose='synthetic-qualification')
    depot = store.ArtifactStore(tmp_path, catalog)
    ledger = transfer.TransferLedger(depot)
    consent = v3.new_consent(value, session=SESSION, request_id=REQUEST, now=lambda: NOW)
    with pytest.raises(store.ArtifactError):
        ledger.begin(v3.encode_consent(consent), session=SESSION, request_id=REQUEST,
                     disclosed_prior_state=ledger.prior_state(), now=lambda: NOW)
    assert list(ledger.root.iterdir()) == []
