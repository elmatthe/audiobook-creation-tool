"""M3 Reference B: the commit-pinned published sox derivative is identity, never production authority.

All transfers use hermetic adapters with synthetic bodies; the real wheel is never embedded or fetched.
"""
import ast
import copy
import dataclasses
import hashlib
import json
import os
from email.message import Message
from pathlib import Path

import pytest

from shared import artifact_store as store
from shared import artifact_transfer as transfer
from shared import optional_setup_protocol as proto
from shared import optional_setup_v3 as v3
from tts import optional_setup_authority as auth
from tts import qwen3_package_manifest as qm
from tts import qwen3_packages as qp
from tts import qwen3_runtime as rt
from test_artifact_store import package_terms
from test_optional_setup_v3 import SESSION, REQUEST, NOW
from test_optional_setup_authority import (authority_world, world, sandbox, tiny_assets,  # noqa: F401
                                           confirmed, Response, execute)
from test_qwen3_offline_engine import package_world, run  # noqa: F401

pytestmark = pytest.mark.usefixtures('production_writes_refused')

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / 'scripts/qwen3-requirements.txt'
MANIFEST = ROOT / 'scripts/qwen3-artifacts.json'
PUB = qm.PUBLISHED_SUPPLY_PURPOSE
C = 'b7e1b1aea9cd78c67c540b556a64392f22d0bfc1'
# Literal approved URL from the owner authorization; constructing it differently must not be equivalent.
URL = ('https://raw.githubusercontent.com/elmatthe/audiobook-creation-tool/b7e1b1aea9cd78c67c540b556a64392f22d0bfc1'
       '/supply/python/sox/1.5.0/sha256-d7f2d5a2390fa235b4195700e72d5bd9b507d88e4598cadcfd17aaccae2b8934'
       '/sox-1.5.0-py3-none-any.whl')
BLOCKED = 'BLOCKED: portable sox supply pending; existing local development only'
REFUSED = (store.ArtifactError, qm.ManifestError, proto.ProtocolError)


def manifest():
    return qm.load_manifest(MANIFEST.read_bytes(), LOCK.read_bytes())


def self_hashed(document):
    document = copy.deepcopy(document)
    document.pop('content_sha256', None)
    digest = hashlib.sha256(qm._canonical(document)).hexdigest()
    document['content_sha256'] = digest
    return json.dumps(document).encode(), digest


# --- versioned reference / manifest -------------------------------------------------------------

def test_v2_manifest_keeps_original_identities_and_names_the_exact_commit_pinned_supply():
    reviewed = manifest()
    assert json.loads(MANIFEST.read_bytes())['version'] == qm.VERSION == 2
    assert reviewed.content_sha256 == qm.REVIEWED_MANIFEST_SHA256 == (
        '8ef2179cd7a0f3e0e979b1e9d907aa02c6bb8fe67617b9d4e3dff5ce3566a2e2')
    # Unchanged bytes keep their identities: original lock, 89 pins, effective wheel lock.
    assert qm.ORIGINAL_LOCK_SHA256 == 'b1851204f0852fbdbf179186800727cba0e99b006adca0c43e6301d858a0ae6e'
    assert reviewed.effective_lock_sha256 == '5c600759b04ae1ce23e6503b47eba5497b6240390de92fe44a897692c92882a4'
    assert len(reviewed.runtime) == len(reviewed.wheels) == 89
    assert sum(a.filename.endswith('.whl') for a in reviewed.runtime) == 88
    source = next(a for a in reviewed.runtime if a.name == 'sox')
    assert (source.filename, source.size, source.sha256) == ('sox-1.5.0.tar.gz', 63905, qm.SOX_SOURCE_SHA256)
    assert reviewed.sox_wheel == qm.Artifact('sox', '1.5.0', 'sox-1.5.0-py3-none-any.whl', 40164,
                                             qm.SOX_WHEEL_SHA256, ('py3-none-any',), None)
    assert reviewed.sox_distribution == qm.SupplyDistribution(
        'elmatthe/audiobook-creation-tool', C,
        'supply/python/sox/1.5.0/sha256-' + qm.SOX_WHEEL_SHA256 + '/sox-1.5.0-py3-none-any.whl',
        URL, 40164, qm.SOX_WHEEL_SHA256, ('py3-none-any',), 'published-endpoint-qualified')
    assert qm.SOX_SUPPLY_URL == URL
    assert qm.published_sox_source(reviewed) == {'kind': 'pinned-https', 'url': URL, 'revision': C}
    # Identity and eligibility stay different facts; nothing became production-authorized.
    derivative = json.loads(MANIFEST.read_bytes())['sox_derivative']
    assert (derivative['authorization'], derivative['publisher_wheel'], derivative['portable_supply'],
            derivative['build_authorized']) == ('existing-local-only', False, 'pending', False)


def test_exact_reference_is_accepted():
    qm.supply_reference('elmatthe/audiobook-creation-tool', C, qm.SOX_SUPPLY_PATH, URL)


def _url(old, new):
    assert old in URL
    return URL.replace(old, new, 1)


BAD_URLS = {
    'branch-main': _url(C, 'main'), 'branch-feature': _url(C, 'feature/0.7.0-release-remediation'),
    'branch-supply': _url(C, 'supply/sox-1.5.0-d7f2d5a2'), 'tag': _url(C, 'v1.5.0'), 'latest': _url(C, 'latest'),
    'head': _url(C, 'HEAD'), 'short-commit': _url(C, C[:7]), 'upper-commit': _url(C, C.upper()),
    'other-commit': _url(C, '4070e0bad2a7b5890bbc1eb3a26984b0cc858693'), 'wheel-sha-as-commit': _url(C, qm.SOX_WHEEL_SHA256),
    'other-repo': _url('/audiobook-creation-tool/', '/other-tool/'),
    'other-owner': _url('/elmatthe/', '/someone/'),
    'github-host': _url('raw.githubusercontent.com', 'github.com'),
    'suffix-spoof': _url('raw.githubusercontent.com', 'raw.githubusercontent.com.evil.invalid'),
    'objects-host': _url('raw.githubusercontent.com', 'objects.githubusercontent.com'),
    'http': _url('https://', 'http://'), 'explicit-port': _url('.com/', '.com:443/'),
    'alternate-port': _url('.com/', '.com:8443/'), 'userinfo': _url('https://', 'https://user@'),
    'query': URL + '?raw=1', 'empty-query': URL + '?', 'fragment': URL + '#x',
    'encoded-slash': _url('/sox/1.5.0/', '/sox%2F1.5.0/'), 'encoded-letter': _url('/sox/1.5.0/', '/%73ox/1.5.0/'),
    'traversal': _url('/python/sox/', '/python/../python/sox/'), 'dot-segment': _url('/python/sox/', '/python/./sox/'),
    'double-slash': _url('/python/sox/', '/python//sox/'), 'backslash': _url('/python/sox/', '/python\\sox/'),
    'trailing-suffix': URL + '.zip', 'trailing-slash': URL + '/',
    'other-hash-dir': _url('sha256-' + qm.SOX_WHEEL_SHA256, 'sha256-' + '0' * 64),
    'source-hash-dir': _url('sha256-' + qm.SOX_WHEEL_SHA256, 'sha256-' + qm.SOX_SOURCE_SHA256),
    'other-version': _url('/1.5.0/', '/1.5.1/'), 'other-filename': _url('sox-1.5.0-py3-none-any.whl', 'sox-1.5.0-py2.py3-none-any.whl'),
    'case-path': _url('/supply/python/', '/Supply/python/'), 'whitespace': _url('/supply/', '/supply /'),
}


@pytest.mark.parametrize('name', sorted(BAD_URLS))
def test_url_substitution_is_refused_by_reference_validation(name):
    with pytest.raises(qm.ManifestError):
        qm.supply_reference(qm.SOX_SUPPLY_REPOSITORY, C, qm.SOX_SUPPLY_PATH, BAD_URLS[name])


@pytest.mark.parametrize('field,value', [
    ('commit', C[:7]), ('commit', C[:39]), ('commit', C.upper()), ('commit', '4070e0bad2a7b5890bbc1eb3a26984b0cc858693'),
    ('commit', 'main'), ('commit', qm.SOX_WHEEL_SHA256), ('repository', 'elmatthe/other'), ('repository', 'Elmatthe/audiobook-creation-tool'),
    ('path', qm.SOX_SUPPLY_PATH.replace('1.5.0/', '1.5.1/', 1)), ('path', qm.SOX_SUPPLY_PATH + '/'),
    ('path', '/' + qm.SOX_SUPPLY_PATH), ('commit', None), ('path', b'bytes')])
def test_component_substitution_is_refused_even_with_the_exact_url(field, value):
    parts = {'repository': qm.SOX_SUPPLY_REPOSITORY, 'commit': C, 'path': qm.SOX_SUPPLY_PATH, 'url': URL, field: value}
    with pytest.raises(qm.ManifestError):
        qm.supply_reference(**parts)


def _with_url(d, url):
    d.update(url=url)


DISTRIBUTION_CHANGES = {
    **{'url-' + k: (lambda u: lambda d: _with_url(d, u))(u) for k, u in BAD_URLS.items()},
    'commit-short': lambda d: d.update(commit=C[:7], url=_url(C, C[:7])),
    'commit-other': lambda d: d.update(commit='0' * 40, url=_url(C, '0' * 40)),
    'commit-branch': lambda d: d.update(commit='main', url=_url(C, 'main')),
    'repository': lambda d: d.update(repository='elmatthe/other', url=_url('/audiobook-creation-tool/', '/other/')),
    'path-hash-dir': lambda d: d.update(path=d['path'].replace(qm.SOX_WHEEL_SHA256, '0' * 64),
                                        url=d['url'].replace(qm.SOX_WHEEL_SHA256, '0' * 64)),
    'size': lambda d: d.update(size=40165), 'size-bool': lambda d: d.update(size=True),
    'size-str': lambda d: d.update(size='40164'),
    'sha': lambda d: d.update(sha256='0' * 64), 'source-sha-as-output': lambda d: d.update(sha256=qm.SOX_SOURCE_SHA256),
    'tags': lambda d: d.update(tags=['py2.py3-none-any']), 'tags-extra': lambda d: d.update(tags=['py3-none-any', 'py3-none-win_amd64']),
    'publication-production': lambda d: d.update(publication='production-eligible'),
    'publication-pending': lambda d: d.update(publication='pending'),
    'extra-key': lambda d: d.update(production_eligible=True), 'missing-key': lambda d: d.pop('commit'),
    'not-object': lambda d: d.clear(),
}


@pytest.mark.parametrize('forge_anchor', [False, True], ids=['self-hash', 'forged-anchor'])
@pytest.mark.parametrize('name', sorted(DISTRIBUTION_CHANGES))
def test_changed_distribution_is_refused_even_with_a_forged_content_anchor(monkeypatch, name, forge_anchor):
    """The anchor alone never approves; with it forged, the code-pinned supply contract still refuses."""
    document = json.loads(MANIFEST.read_bytes())
    DISTRIBUTION_CHANGES[name](document['sox_derivative']['distribution'])
    raw, digest = self_hashed(document)
    if forge_anchor:
        monkeypatch.setattr(qm, 'REVIEWED_MANIFEST_SHA256', digest)
    with pytest.raises(qm.ManifestError):
        qm.load_manifest(raw, LOCK.read_bytes())


DOCUMENT_CHANGES = {
    'v1-reinterpreted': lambda d: (d['sox_derivative'].pop('distribution'), d.update(version=1)),
    'v1-number-with-distribution': lambda d: d.update(version=1),
    'v3': lambda d: d.update(version=3), 'v2-without-distribution': lambda d: d['sox_derivative'].pop('distribution'),
    'distribution-top-level': lambda d: d.update(distribution=d['sox_derivative']['distribution']),
    'publisher-wheel': lambda d: d['sox_derivative'].update(publisher_wheel=True),
    'build-authorized': lambda d: d['sox_derivative'].update(build_authorized=True),
    'portable-available': lambda d: d['sox_derivative'].update(portable_supply='available'),
    'portable-authorization': lambda d: d['sox_derivative'].update(authorization='portable'),
    # A different artifact cannot inherit the approved published identity, even consistently renamed.
    'inherit-other-wheel': lambda d: (d['sox_derivative']['artifact'].update(sha256='1' * 64),
                                      d['sox_derivative']['distribution'].update(sha256='1' * 64)),
    'inherit-other-size': lambda d: (d['sox_derivative']['artifact'].update(size=40165),
                                     d['sox_derivative']['distribution'].update(size=40165)),
    'source-hash-as-derivative': lambda d: (d['sox_derivative']['artifact'].update(sha256=qm.SOX_SOURCE_SHA256),
                                            d['sox_derivative']['distribution'].update(sha256=qm.SOX_SOURCE_SHA256)),
    'artifact-gets-url': lambda d: d['sox_derivative']['artifact'].update(source_url=URL),
    'runtime-sox-gets-url': lambda d: next(a for a in d['runtime'] if a['name'] == 'sox').update(source_url=URL),
}


@pytest.mark.parametrize('name', sorted(DOCUMENT_CHANGES))
def test_schema_and_eligibility_changes_are_refused_even_with_a_forged_anchor(monkeypatch, name):
    document = json.loads(MANIFEST.read_bytes())
    DOCUMENT_CHANGES[name](document)
    raw, digest = self_hashed(document)
    monkeypatch.setattr(qm, 'REVIEWED_MANIFEST_SHA256', digest)
    with pytest.raises(qm.ManifestError):
        qm.load_manifest(raw, LOCK.read_bytes())


def test_forged_anchor_control_isolates_the_validator(monkeypatch):
    raw, digest = self_hashed(json.loads(MANIFEST.read_bytes()))
    assert digest == qm.REVIEWED_MANIFEST_SHA256
    monkeypatch.setattr(qm, 'REVIEWED_MANIFEST_SHA256', digest)
    assert qm.load_manifest(raw, LOCK.read_bytes()) == manifest()


@pytest.mark.parametrize('field', ['url', 'commit', 'sha256', 'size', 'publication'])
def test_forged_reviewed_manifest_object_cannot_change_the_published_identity(field):
    reviewed = manifest()
    value = {'url': BAD_URLS['other-commit'], 'commit': '0' * 40, 'sha256': '0' * 64, 'size': 1,
             'publication': 'production-eligible'}[field]
    forged = dataclasses.replace(reviewed, sox_distribution=dataclasses.replace(reviewed.sox_distribution, **{field: value}))
    for call in (qm.published_sox_source, qm.effective_lock):
        with pytest.raises(qm.ManifestError, match='untrusted'):
            call(forged)
    value, _ = published_terms()
    with pytest.raises(qm.ManifestError, match='untrusted'):
        store.Catalog(value, package_manifest=forged, purpose=PUB)


def test_forged_wheel_identity_cannot_inherit_the_published_source():
    reviewed = manifest()
    forged = dataclasses.replace(reviewed, sox_wheel=dataclasses.replace(reviewed.sox_wheel, sha256='1' * 64))
    with pytest.raises(qm.ManifestError, match='untrusted'):
        qm.published_sox_source(forged)


# --- Catalog -----------------------------------------------------------------------------------

def published_terms():
    value, reviewed = package_terms('sox')
    row = value['artifacts'][0]
    row.update(source=qm.published_sox_source(reviewed), verified_reuse_bytes=0, expected_new_bytes=40164,
               retry_headroom_bytes=0, max_payload_bytes=40164)
    value['payload'] = {'expected_new_bytes': 40164, 'retry_headroom_bytes': 0, 'max_payload_bytes': 40164}
    return value, reviewed


def test_catalog_accepts_the_exact_remote_row_only_for_the_explicit_qualification_purpose():
    value, reviewed = published_terms()
    catalog = store.Catalog(value, package_manifest=reviewed, purpose=PUB)
    assert catalog.purpose == PUB and catalog.artifacts == value['artifacts']
    row = catalog.artifacts[0]
    assert row['source'] == {'kind': 'pinned-https', 'url': URL, 'revision': C}
    assert row['derivative']['source_sha256'] == qm.SOX_SOURCE_SHA256 != row['sha256'] == qm.SOX_WHEEL_SHA256
    with pytest.raises(store.ArtifactError, match='BLOCKED: portable sox'):
        store.Catalog(value, package_manifest=reviewed)  # production default
    for purpose in (*qm.LOCAL_SUPPLY_PURPOSES, 'fresh-machine', 'developer', PUB.upper()):
        with pytest.raises(store.ArtifactError):
            store.Catalog(value, package_manifest=reviewed, purpose=purpose)
    local, _ = package_terms('sox')  # zero-download local-derived row cannot pose as the remote supply
    with pytest.raises(store.ArtifactError):
        store.Catalog(local, package_manifest=reviewed, purpose=PUB)
    assert store.Catalog(local, package_manifest=reviewed, purpose='synthetic-qualification').purpose == (
        'synthetic-qualification')


def test_remote_and_local_derivative_never_share_a_store_identity(tmp_path):
    remote, reviewed = published_terms()
    local, _ = package_terms('sox')
    a = store.ArtifactStore(tmp_path, store.Catalog(remote, package_manifest=reviewed, purpose=PUB))
    b = store.ArtifactStore(tmp_path, store.Catalog(local, package_manifest=reviewed, purpose='synthetic-qualification'))
    assert a._paths('qwen3-package:sox') != b._paths('qwen3-package:sox')


ROW_CHANGES = {
    **{'url-' + k: (lambda u: lambda r: r['source'].update(url=u))(u) for k, u in BAD_URLS.items()},
    'revision-other-commit-in-url': lambda r: r['source'].update(revision='0' * 40, url=_url(C, '0' * 40)),
    'revision-short': lambda r: r['source'].update(revision=C[:7]),
    'revision-other-url-unchanged': lambda r: r['source'].update(revision='4070e0bad2a7b5890bbc1eb3a26984b0cc858693'),
    'revision-wheel-digest': lambda r: r['source'].update(revision=qm.SOX_WHEEL_SHA256),
    'revision-source-digest': lambda r: r['source'].update(revision=qm.SOX_SOURCE_SHA256),
    'kind-local-with-url': lambda r: r['source'].update(kind='local-derived'),
    'size': lambda r: r.update(size=40165, expected_new_bytes=40165, max_payload_bytes=40165),
    'sha': lambda r: (r.update(sha256='1' * 64), r['derivative'].update(output_sha256='1' * 64)),
    'source-sha-as-output': lambda r: (r.update(sha256=qm.SOX_SOURCE_SHA256),
                                       r['derivative'].update(output_sha256=qm.SOX_SOURCE_SHA256)),
    'version': lambda r: r.update(version='1.5.1'), 'filename': lambda r: r.update(filename='sox-1.5.0-py2.py3-none-any.whl'),
    'name': lambda r: r.update(name='pysox'), 'no-derivative': lambda r: r.update(derivative=None),
    **{'derivative-' + k: (lambda k: lambda r: r['derivative'].update(
        {k: {'source_filename': 'sox-1.5.1.tar.gz', 'source_size': 63906}.get(k, '2' * 64)}))(k)
       for k in ('source_filename', 'source_sha256', 'source_size', 'build_inputs_sha256', 'output_sha256')},
    'derivative-source-is-wheel': lambda r: r['derivative'].update(source_sha256=qm.SOX_WHEEL_SHA256),
}


@pytest.mark.parametrize('name', sorted(ROW_CHANGES))
def test_changed_remote_source_or_derivative_is_refused_before_any_transfer(name):
    value, reviewed = published_terms()
    ROW_CHANGES[name](value['artifacts'][0])
    row = value['artifacts'][0]
    value['payload'] = {k: row[k] for k in ('expected_new_bytes', 'retry_headroom_bytes', 'max_payload_bytes')}
    with pytest.raises(REFUSED):
        store.Catalog(value, package_manifest=reviewed, purpose=PUB)


# --- transfer (existing no-redirect transport; hermetic bodies only) ---------------------------

class Body:
    def __init__(self, data, *, status=200, url=URL, headers=None):
        self.data, self.status, self.url, self.offset = data, status, url, 0
        self.headers = Message()
        for key, item in (headers if headers is not None else {'Content-Length': str(len(data))}).items():
            self.headers[key] = item

    def geturl(self):
        return self.url

    def read(self, n):
        block = self.data[self.offset:self.offset + n]
        self.offset += len(block)
        return block

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def live(tmp_path):
    value, reviewed = published_terms()
    depot = store.ArtifactStore(tmp_path, store.Catalog(value, package_manifest=reviewed, purpose=PUB))
    ledger = transfer.TransferLedger(depot)
    consent = v3.new_consent(depot.catalog.terms, session=SESSION, request_id=REQUEST, now=lambda: NOW)
    operation = ledger.begin(v3.encode_consent(consent), session=SESSION, request_id=REQUEST,
                             disclosed_prior_state=ledger.prior_state(), now=lambda: NOW)
    return depot, operation


LFS = b'version https://git-lfs.github.com/spec/v1\noid sha256:' + qm.SOX_WHEEL_SHA256.encode() + b'\nsize 40164\n'
BODIES = {
    'redirect-302': lambda: Body(b'', status=302, headers={'Location': URL, 'Content-Length': '0'}),
    'redirect-same-url-308': lambda: Body(b'x' * 40164, status=308, headers={'Location': URL, 'Content-Length': '40164'}),
    'final-url-other-commit': lambda: Body(b'x' * 40164, url=BAD_URLS['other-commit']),
    'final-url-branch': lambda: Body(b'x' * 40164, url=BAD_URLS['branch-main']),
    'not-found': lambda: Body(b'404: Not Found', status=404),
    'html': lambda: Body(b'<!DOCTYPE html><html>sign in</html>'.ljust(40164, b' ')),
    'lfs-pointer': lambda: Body(LFS),
    'lfs-pointer-padded': lambda: Body(LFS.ljust(40164, b'\n')),
    'wrong-bytes': lambda: Body(b'\0' * 40164),
    'short': lambda: Body(b'x' * 100, headers={'Content-Length': '40164'}),
    'missing-length': lambda: Body(b'x' * 40164, headers={}),
    'wrong-length': lambda: Body(b'x' * 40163),
    'duplicate-length': lambda: Body(b'x' * 40164, headers={'Content-Length': '40164', 'content-length': '40164'}),
    'gzip': lambda: Body(b'x' * 40164, headers={'Content-Length': '40164', 'Content-Encoding': 'gzip'}),
    'chunked': lambda: Body(b'x' * 40164, headers={'Content-Length': '40164', 'Transfer-Encoding': 'chunked'}),
    'range': lambda: Body(b'x' * 40164, status=206, headers={'Content-Length': '40164', 'Content-Range': 'bytes 0-40163/40164'}),
}


@pytest.mark.parametrize('name', sorted(BODIES))
def test_bad_published_responses_fail_closed_without_promotion_retry_or_refund(tmp_path, name):
    depot, operation = live(tmp_path)
    requests = []
    response = BODIES[name]()

    def opener(request, *, timeout):
        requests.append((request.full_url, request.get_method(), timeout, request.has_header('Range')))
        return response

    with pytest.raises(store.ArtifactError):
        transfer.acquire(depot, operation, 'qwen3-package:sox', opener=opener)
    assert requests == [(URL, 'GET', 15, False)]
    with pytest.raises(store.ArtifactError):
        depot.verify('qwen3-package:sox')
    state = operation.state
    assert state['actual']['qwen3-package:sox'] + state['reserved']['qwen3-package:sox'] == 40164
    # The single disclosed response allowance is spent: no implicit retry and no refund.
    with pytest.raises(store.ArtifactError, match='per-artifact'):
        transfer.acquire(depot, operation, 'qwen3-package:sox', opener=lambda *a, **k: pytest.fail('second request'))


def test_existing_no_redirect_handler_refuses_the_published_location():
    import urllib.request
    handler = transfer._NoRedirect()
    with pytest.raises(store.ArtifactError, match='redirect refused'):
        handler.redirect_request(urllib.request.Request(URL), None, 302, 'Found', {}, URL)


# --- Planner / sealed matching (real reviewed manifest) ----------------------------------------

def published_plan(fixture, selected=(proto.QWEN3_CUSTOMVOICE, proto.QWEN3_BASE), retry=0):
    _, planner, state, _, _, _ = fixture
    planner.purpose, planner.retry_bytes = PUB, retry
    state['engine'] = proto.MISSING
    return planner.plan(list(selected), engine_action='install-missing')


def test_published_purpose_plans_one_remote_sox_transfer_shared_by_both_models(authority_world):
    root, planner, _, calls, _, _ = authority_world
    plan = published_plan(authority_world, retry=7)
    terms = plan.terms
    assert terms is not None and plan.to_json()['reasons'] == [], plan.to_json()
    packages = [a for a in terms['artifacts'] if a['kind'] == 'package']
    sox = [a for a in packages if a['name'] == 'sox']
    assert len(packages) == 89 and len(sox) == 1
    row = sox[0]
    assert row['components'] == [proto.QWEN3_CUSTOMVOICE, proto.QWEN3_BASE]
    assert row['source'] == {'kind': 'pinned-https', 'url': URL, 'revision': C}
    assert row['derivative'] == {'source_filename': 'sox-1.5.0.tar.gz', 'source_size': 63905,
                                 'source_sha256': qm.SOX_SOURCE_SHA256, 'output_sha256': qm.SOX_WHEEL_SHA256,
                                 'build_inputs_sha256': hashlib.sha256(store.canonical(
                                     json.loads(MANIFEST.read_bytes())['build_only'])).hexdigest()}
    # A remote artifact is an actual transfer: no false local-derived zero-download accounting.
    assert (row['verified_reuse_bytes'], row['expected_new_bytes'], row['retry_headroom_bytes'],
            row['max_payload_bytes']) == (0, 40164, 7, 40171)
    assert all(a['source']['kind'] == 'pinned-https' for a in terms['artifacts'])
    assert terms['payload']['expected_new_bytes'] == sum(a['expected_new_bytes'] for a in terms['artifacts'])
    assert terms['manifest_sha256'] == qm.REVIEWED_MANIFEST_SHA256
    assert terms['effective_lock_sha256'] == '5c600759b04ae1ce23e6503b47eba5497b6240390de92fe44a897692c92882a4'
    assert v3.validate_terms(terms) == terms and len(v3._canonical(terms)) < v3.MAX_MESSAGE_BYTES
    single = published_plan(authority_world, selected=(proto.QWEN3_CUSTOMVOICE,)).terms
    one = next(a for a in single['artifacts'] if a['name'] == 'sox')
    assert one['components'] == [proto.QWEN3_CUSTOMVOICE] and one['expected_new_bytes'] == 40164
    assert calls == [] and not (root / store.STORE).exists()


def test_stored_remote_object_is_reused_and_counted_zero_new(authority_world, monkeypatch):
    """Only the sox store proof is a trusted synthetic stand-in, as in the accepted engine-authority test."""
    root, _, _, calls, _, _ = authority_world
    original_paths, original_verify, original_exists = store.ArtifactStore._paths, store.ArtifactStore.verify, os.path.lexists
    proved = []

    def paths(self, artifact_id):
        if artifact_id == 'qwen3-package:sox':
            assert self.catalog.artifact(artifact_id)['source']['revision'] == C
            return root / 'remote-sox-proof.blob', root / 'remote-sox-proof.json'
        return original_paths(self, artifact_id)

    def verify(self, artifact_id, **kwargs):
        if artifact_id == 'qwen3-package:sox':
            proved.append(self.catalog.artifact(artifact_id)['source'])
            row = self.catalog.artifact(artifact_id)
            return store.Verification('synthetic-proof-only', row['sha256'], row['size'])
        return original_verify(self, artifact_id, **kwargs)

    monkeypatch.setattr(store.ArtifactStore, '_paths', paths)
    monkeypatch.setattr(store.ArtifactStore, 'verify', verify)
    monkeypatch.setattr(os.path, 'lexists', lambda p: Path(p).name.startswith('remote-sox-proof.') or original_exists(p))
    row = next(a for a in published_plan(authority_world, retry=7).terms['artifacts'] if a['name'] == 'sox')
    assert (row['verified_reuse_bytes'], row['expected_new_bytes'], row['retry_headroom_bytes'],
            row['max_payload_bytes']) == (40164, 0, 0, 0)
    assert row['source']['kind'] == 'pinned-https' and proved and calls == []


def test_production_planner_remains_non_confirmable(authority_world):
    _, planner, state, calls, _, _ = authority_world
    assert auth.Planner().purpose == 'fresh-machine'
    state['engine'] = proto.MISSING
    for selected in ([proto.QWEN3_CUSTOMVOICE], [proto.QWEN3_CUSTOMVOICE, proto.QWEN3_BASE]):
        document = planner.plan(selected, engine_action='install-missing').to_json()
        assert document['terms'] is None and document['prior_state'] is None
        assert document['reasons'] == [BLOCKED]
    planner.purpose = 'synthetic-qualification'  # the old explicitly scoped local behaviour is unchanged
    document = planner.plan([proto.QWEN3_CUSTOMVOICE], engine_action='install-missing').to_json()
    assert document['terms'] is None
    assert 'BLOCKED: approved local sox supply missing; no build or portable supply' in document['reasons']
    assert calls == []


@pytest.mark.parametrize('purpose', ['fresh-machine', 'synthetic-qualification', 'controlled-local-development'])
def test_published_confirmation_cannot_be_spent_under_another_purpose(authority_world, purpose):
    root, planner, state, calls, _, _ = authority_world
    planner.purpose, state['engine'] = PUB, proto.MISSING
    confirmation = confirmed(planner, [proto.QWEN3_CUSTOMVOICE], engine_action='install-missing')
    planner.purpose = purpose
    result = execute(authority_world, confirmation, simulate_engine=lambda terms: pytest.fail('engine adapter'))
    assert result.state == proto.REFUSED and not result.consent_spent, result
    assert calls == [] and not (root / store.STORE / 'transfers').exists() and not rt.nested_venv_dir().exists()


def test_no_op_and_model_only_plans_are_purpose_independent(authority_world):
    _, planner, state, _, _, _ = authority_world
    state['engine'] = proto.READY
    documents = []
    for purpose in ('fresh-machine', PUB):
        planner.purpose = purpose
        plan = planner.plan(list(proto.canonical_selection([proto.QWEN3_CUSTOMVOICE, proto.CHATTERBOX])))
        assert plan.terms is not None and all(a['kind'] == 'model' for a in plan.terms['artifacts'])
        documents.append(plan._document)
    assert documents[0] == documents[1]


@pytest.mark.parametrize('engine', [proto.UNVERIFIED, proto.BUSY, proto.DAMAGED, proto.READY])
def test_unverified_busy_or_mismatched_engine_stays_non_authorizable(authority_world, engine):
    _, planner, state, calls, _, _ = authority_world
    planner.purpose, state['engine'] = PUB, engine
    document = planner.plan([proto.QWEN3_CUSTOMVOICE], engine_action='install-missing').to_json()
    assert document['terms'] is None and document['reasons'] and calls == []


def test_unsupported_platform_stays_non_authorizable(authority_world, monkeypatch):
    _, planner, state, calls, _, _ = authority_world
    planner.purpose, state['engine'] = PUB, proto.MISSING
    monkeypatch.setattr(rt, 'platform_supported', lambda: False)
    document = planner.plan([proto.QWEN3_CUSTOMVOICE], engine_action='install-missing').to_json()
    assert document['terms'] is None and document['components'][0]['readiness'] == proto.UNSUPPORTED
    assert calls == []


def test_sealed_matching_reconstructs_the_catalog_under_its_own_purpose(authority_world):
    root, *_ = authority_world
    plan = published_plan(authority_world)
    reviewed = manifest()
    depot = store.ArtifactStore(root, store.Catalog(plan.terms, package_manifest=reviewed, purpose=PUB))
    rows, lock = qp._matching_rows(depot, reviewed)
    assert len(rows) == 89 and lock == qm.effective_lock(reviewed)
    for tampered in ('fresh-machine', 'synthetic-qualification'):
        depot.catalog._purpose = tampered
        with pytest.raises(store.ArtifactError):
            qp._matching_rows(depot, reviewed)


# --- hermetic end-to-end with tiny synthetic identities -----------------------------------------

def published_world(package_world, response=None):
    root, planner, state, calls, opener, runner, commands, reviewed, depot = package_world
    planner.purpose = PUB
    sox = []
    tiny = b'SYNTHETIC-NOT-A-WHEEL:sox'  # package_world's trusted tiny stand-in; never real wheel bytes

    def published(request, *, timeout):
        if request.full_url == URL:
            sox.append((request.full_url, request.has_header('Range')))
            return response() if response else Response(tiny, request.full_url)
        return opener(request, timeout=timeout)

    return (root, planner, state, calls, published, runner, commands, reviewed, depot), sox, tiny


def test_end_to_end_both_models_download_published_sox_once_then_seal_89_wheels(package_world):
    fixture, sox, tiny = published_world(package_world)
    root, planner, state, calls, _, _, commands, reviewed, _ = fixture
    confirmation = confirmed(planner, [proto.QWEN3_CUSTOMVOICE, proto.QWEN3_BASE], engine_action='install-missing')
    row = next(a for a in confirmation.plan.terms['artifacts'] if a['name'] == 'sox')
    assert row['source'] == {'kind': 'pinned-https', 'url': URL, 'revision': C}
    assert (row['verified_reuse_bytes'], row['expected_new_bytes']) == (0, len(tiny))  # local object is not reused
    result = run(fixture, confirmation)
    assert result.state == proto.SUCCEEDED and result.consent_spent, result
    assert sox == [(URL, False)]
    assert result.transfer_state['actual']['qwen3-package:sox'] == len(tiny)
    assert len([url for url in calls if any(url == a.source_url for a in reviewed.wheels)]) == 88
    assert len([c for c in commands if qp.OFFLINE_BOOTSTRAP in c]) == 1
    assert rt.requirements_sha256() == qm.ORIGINAL_LOCK_SHA256


@pytest.mark.parametrize('name', ['redirect-302', 'final-url-other-commit', 'html', 'lfs-pointer', 'chunked'])
def test_end_to_end_bad_published_response_spends_and_never_mutates_the_engine(package_world, name):
    fixture, sox, _ = published_world(package_world, BODIES[name])
    _, planner, _, _, _, _, commands, _, _ = fixture
    confirmation = confirmed(planner, [proto.QWEN3_CUSTOMVOICE], engine_action='install-missing')
    result = run(fixture, confirmation)
    assert result.state == proto.FAILED and result.consent_spent, result
    assert sox == [(URL, False)] and commands == [] and not rt.nested_venv_dir().exists()


# --- production callsite guard (AST, not substring) ---------------------------------------------

def test_no_production_callsite_selects_the_published_qualification_purpose():
    users, literals, selectors = set(), [], []
    scripts = ROOT / 'scripts'
    for folder, dirs, files in os.walk(scripts):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for name in files:
            if not name.endswith('.py'):
                continue
            path = Path(folder) / name
            rel = path.relative_to(scripts).as_posix()
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if isinstance(node, ast.Constant) and node.value == PUB:
                    literals.append(rel)
                if isinstance(node, ast.Attribute) and node.attr == 'PUBLISHED_SUPPLY_PURPOSE':
                    users.add(rel)
                if isinstance(node, ast.Call) and getattr(node.func, 'attr', getattr(node.func, 'id', None)) in (
                        'Planner', 'Catalog', 'verified_wheel_lock'):
                    for keyword in node.keywords:
                        value = keyword.value
                        if keyword.arg == 'purpose' and not (isinstance(value, ast.Name) and value.id == 'purpose'
                                                             or isinstance(value, ast.Attribute) and value.attr == 'purpose'):
                            selectors.append((rel, ast.unparse(node)))
                if isinstance(node, ast.Assign) and any(isinstance(t, ast.Attribute) and t.attr == 'purpose'
                                                        for target in node.targets for t in ast.walk(target)):
                    if any(isinstance(v, ast.Constant) and isinstance(v.value, str)
                           or isinstance(v, ast.Attribute) and v.attr.endswith('PURPOSE') for v in ast.walk(node.value)):
                        selectors.append((rel, ast.unparse(node)))
    assert literals == ['tts/qwen3_package_manifest.py']
    assert users == {'shared/artifact_store.py', 'tts/optional_setup_authority.py', 'tts/qwen3_packages.py'}
    # Only pass-through of an existing purpose; no production code ever chooses a purpose value.
    assert selectors == [], selectors
