"""M3 source delivery adversaries. All HTTP responses are hermetic adapters."""
import hashlib
from email.message import Message

import pytest

from shared import artifact_store as store
from shared import artifact_transfer as transfer
from tts import model_assets as assets
from tts import optional_setup_authority as authority
from tts import qwen3_runtime as rt
from tts import qwen3_setup as setup
from test_artifact_transfer import operation, acquire, Response, retry_terms
from test_artifact_store import terms, DATA

pytestmark = pytest.mark.usefixtures('production_writes_refused')


@pytest.mark.parametrize('component', ['kokoro', 'chatterbox', 'customvoice', 'base', 'spacy'])
def test_exact_approved_source_reaches_only_explicit_fake_opener(tmp_path, component):
    value = terms()
    row = value['artifacts'][0]
    if component in ('kokoro', 'chatterbox'):
        group = assets.kokoro_set() if component == 'kokoro' else assets.chatterbox_set()
        name = next(iter(group.files))
        size, digest = group.files[name]
        revision = group.revision
        url = setup.HUB_URL.format(repo=group.repo, revision=revision, path=name)
    elif component == 'spacy':
        size, digest, revision, url = (assets.SPACY_WHEEL_SIZE, assets.SPACY_WHEEL_SHA256,
                                       assets.SPACY_WHEEL_SHA256, assets.SPACY_WHEEL_URL)
    else:
        spec = rt.model_spec(component)
        name = next(iter(spec.files))
        size, digest = spec.files[name]['size'], spec.files[name]['sha256']
        revision, url = spec.revision, setup.hub_url(spec, name)
    row.update(size=size, sha256=digest, expected_new_bytes=size, retry_headroom_bytes=0,
               max_payload_bytes=size, source={'kind': 'pinned-https', 'url': url, 'revision': revision})
    value['payload'].update(expected_new_bytes=size, retry_headroom_bytes=0, max_payload_bytes=size)
    depot, _, live, _ = operation(tmp_path, value)
    calls = []
    def offline(request, *, timeout):
        assert request.full_url == url and request.get_method() == 'GET' and timeout == 15
        assert not request.has_header('Range') and not request.has_header('If-Range')
        assert live.state['reserved'] == {row['id']: size}
        calls.append(url)
        raise ConnectionError('intentional hermetic endpoint; no upstream qualification')
    with pytest.raises(ConnectionError):
        transfer.acquire(depot, live, row['id'], opener=offline)
    assert calls == [url]
    assert live.state['actual'] == {row['id']: 0}


@pytest.mark.parametrize('etag', ['"old"', '"new"', 'W/"weak"', None])
def test_range_and_validator_changes_never_adopt_a_partial(tmp_path, etag):
    depot, ledger, live, _ = operation(tmp_path)
    partial = depot.new_partial()
    partial.write_bytes(b'bad-prefix')
    headers = {'Content-Length': '8', 'Content-Range': 'bytes 0-7/8'}
    if etag:
        headers['ETag'] = etag
    response = Response(status=206, headers=headers)
    with pytest.raises(store.ArtifactError):
        acquire(depot, live, response)
    assert not response.reads and partial.read_bytes() == b'bad-prefix'
    assert all(p['verified_reuse_bytes'] == 0 for p in ledger.prior_state()['partials'])


@pytest.mark.parametrize('damage', ['missing', 'corrupt'])
def test_missing_or_corrupt_partial_is_never_reuse_or_range_credit(tmp_path, damage):
    depot, ledger, live, _ = operation(tmp_path)
    partial = depot.new_partial()
    if damage == 'corrupt':
        partial.write_bytes(b'ABCDEFGH')
    receipt, calls = acquire(depot, live)
    assert receipt.size == 8 and len(calls) == 1 and not calls[0].has_header('Range')
    assert live.state['actual'] == {depot.catalog.artifacts[0]['id']: 8}
    assert all(p['verified_reuse_bytes'] == 0 for p in ledger.prior_state()['partials'])


def test_changing_etag_on_full_retry_cannot_replace_hash_identity(tmp_path):
    depot, _, live, _ = operation(tmp_path, retry_terms())
    with pytest.raises(store.ArtifactError, match='hash'):
        acquire(depot, live, Response(b'ABCDEFGH', headers={'Content-Length': '8', 'ETag': '"first"'}))
    receipt, _ = acquire(depot, live, Response(headers={'Content-Length': '8', 'ETag': '"changed"'}))
    assert receipt.sha256 == hashlib.sha256(DATA).hexdigest()
    assert sum(live.state['actual'].values()) == 16


def test_excessive_adapter_response_never_publishes_or_grants_retry(tmp_path):
    depot, _, live, _ = operation(tmp_path)
    class Excess(Response):
        def read(self, n):
            return b'x' * (n + 1)  # violates the trusted adapter's explicit read(n) precondition
    with pytest.raises(store.ArtifactError, match='bounded read'):
        acquire(depot, live, Excess())
    with pytest.raises(store.ArtifactError):
        depot.verify(depot.catalog.artifacts[0]['id'])
    with pytest.raises(store.ArtifactError, match='per-artifact'):
        acquire(depot, live)


@pytest.mark.parametrize('name', ['Content-Length', 'Content-Range', 'Content-Encoding', 'Transfer-Encoding'])
def test_duplicate_headers_are_never_interpreted_as_one(tmp_path, name):
    depot, _, live, _ = operation(tmp_path)
    headers = Message()
    headers['Content-Length'] = '8'
    if name != 'Content-Length':
        headers[name] = 'identity'
    headers[name] = '8' if name == 'Content-Length' else 'identity'
    response = Response(headers=headers)
    with pytest.raises(store.ArtifactError):
        acquire(depot, live, response)
    assert not response.reads


@pytest.mark.parametrize('stage', ['blob', 'metadata'])
def test_publication_failure_keeps_spending_and_never_marks_complete(tmp_path, monkeypatch, stage):
    depot, _, live, _ = operation(tmp_path)
    original = store.publish
    destinations = depot._paths(depot.catalog.artifacts[0]['id'])
    def unavailable(repo, source, destination):
        if destination == destinations[0 if stage == 'blob' else 1]:
            raise OSError('synthetic full disk/interrupted publication')
        return original(repo, source, destination)
    monkeypatch.setattr(store, 'publish', unavailable)
    with pytest.raises(OSError, match='full disk'):
        acquire(depot, live)
    assert sum(live.state['actual'].values()) == 8
    with pytest.raises(store.ArtifactError):
        depot.verify(depot.catalog.artifacts[0]['id'])


def test_original_manifest_has_no_live_or_unpinned_package_source():
    reviewed = authority.reviewed_packages()
    assert len(reviewed.runtime) == 89
    assert all(a.source_url and a.sha256 and a.size > 0 for a in reviewed.runtime)
    assert reviewed.sox_wheel.source_url is None
    assert all('/main/' not in a.source_url for a in reviewed.runtime)
