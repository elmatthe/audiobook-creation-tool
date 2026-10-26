"""Small exact v3 contracts; no acquisition, network, model import or installer."""
import copy
import dataclasses
import json
import hashlib
from pathlib import Path

import pytest

from shared import optional_setup_protocol as proto
from shared import optional_setup_v3 as v3

pytestmark = pytest.mark.usefixtures('production_writes_refused')
SESSION, REQUEST, NOW = 'a' * 32, 'b' * 32, 1792886400


def model_terms():
    return {
        'schema': 'act-acquisition-terms', 'version': 1,
        'target': {'implementation': 'CPython', 'python': '3.12', 'platform': 'win_amd64'},
        'manifest_sha256': '1' * 64, 'runtime_lock_sha256': '2' * 64, 'effective_lock_sha256': '3' * 64,
        'components': [{'id': proto.QWEN3_BASE, 'readiness': 'missing', 'scope': 'install'}],
        'engine_action': 'none', 'engine_readiness': 'ready',
        'artifacts': [{
            'id': 'qwen3-base:weights', 'kind': 'model', 'components': [proto.QWEN3_BASE],
            'name': 'qwen3-base', 'version': 'reviewed-commit', 'filename': 'model.safetensors',
            'size': 8, 'sha256': '4' * 64,
            'source': {'kind': 'pinned-https', 'url': 'https://example.invalid/' + '5' * 40 + '/model.safetensors',
                       'revision': '5' * 40},
            'derivative': None, 'verified_reuse_bytes': 0, 'expected_new_bytes': 8,
            'retry_headroom_bytes': 2, 'max_payload_bytes': 10,
        }],
        'payload': {'expected_new_bytes': 8, 'retry_headroom_bytes': 2, 'max_payload_bytes': 10},
        'disk': {'new_bytes': 16, 'temporary_headroom_bytes': 32},
    }


def consent(terms=None):
    return v3.new_consent(terms or model_terms(), session=SESSION, request_id=REQUEST, now=lambda: NOW)


def test_v3_round_trip_and_one_time_spending():
    original = consent()
    raw = v3.encode_consent(original)
    assert v3.decode_consent(raw, session=SESSION, request_id=REQUEST, now=lambda: NOW) == original
    used = set()

    def claim(token):
        fresh = token not in used
        used.add(token)
        return fresh

    assert v3.validate_and_spend(raw, model_terms(), session=SESSION, request_id=REQUEST,
                               claim=claim, now=lambda: NOW) == original
    with pytest.raises(proto.ProtocolError) as caught:
        v3.validate_and_spend(raw, model_terms(), session=SESSION, request_id=REQUEST,
                              claim=claim, now=lambda: NOW)
    assert caught.value.code == proto.CONSENT_USED


def test_model_only_never_grants_engine_rebuild():
    terms = model_terms()
    terms['engine_action'] = 'rebuild-canonical'
    terms['engine_readiness'] = 'damaged'
    terms['components'][0].update(readiness='damaged', scope='repair')
    with pytest.raises(proto.ProtocolError):
        v3.validate_terms(terms)


def test_retry_allowance_is_separate_from_expected_new_payload():
    terms = model_terms()
    assert v3.validate_terms(terms) == terms
    changed = copy.deepcopy(terms)
    changed['payload']['expected_new_bytes'] = 10
    with pytest.raises(proto.ProtocolError):
        v3.validate_terms(changed)


def package_terms(action='install-missing'):
    terms = model_terms()
    terms.update(engine_action=action, engine_readiness='missing' if action == 'install-missing' else 'damaged')
    if action == 'rebuild-canonical':
        terms['components'][0].update(readiness='damaged', scope='repair')
    artifact = copy.deepcopy(terms['artifacts'][0])
    artifact.update(id='qwen3-package:sox', kind='package', name='sox', version='1.5.0',
                    filename='sox-1.5.0-py3-none-any.whl', size=5, sha256='6' * 64,
                    verified_reuse_bytes=5, expected_new_bytes=0, retry_headroom_bytes=0, max_payload_bytes=0,
                    source={'kind': 'local-derived', 'url': None, 'revision': '7' * 64},
                    derivative={'source_filename': 'sox-1.5.0.tar.gz', 'source_sha256': '7' * 64,
                                'source_size': 6, 'build_inputs_sha256': '8' * 64, 'output_sha256': '6' * 64})
    terms['artifacts'].append(artifact)
    terms['payload'] = {'expected_new_bytes': 8, 'retry_headroom_bytes': 2, 'max_payload_bytes': 10}
    return terms


@pytest.mark.parametrize('action', ['install-missing', 'rebuild-canonical'])
def test_engine_authority_is_explicit_and_derivative_identity_is_bound(action):
    terms = package_terms(action)
    encoded = v3.encode_consent(consent(terms))
    assert v3.decode_consent(encoded, session=SESSION, request_id=REQUEST, now=lambda: NOW).terms
    assert v3.acquisition_fingerprint(terms) != v3.acquisition_fingerprint(model_terms())


@pytest.mark.parametrize('change', [
    lambda d: d.update(engine_action='none'),
    lambda d: d.update(engine_readiness='unverified'),
    lambda d: d['components'][0].update(scope='repair'),
    lambda d: d['artifacts'][1]['derivative'].update(source_sha256='6' * 64),
    lambda d: d['artifacts'][1]['derivative'].update(output_sha256='7' * 64),
    lambda d: d['artifacts'][1]['source'].update(revision='9' * 64),
    lambda d: d['artifacts'][1]['source'].update(url='https://example.invalid/sox.whl'),
    lambda d: d['artifacts'][1].update(derivative=None),
    lambda d: d['artifacts'][1].update(verified_reuse_bytes=0, expected_new_bytes=5, max_payload_bytes=5),
], ids=['package-without-authority', 'unproved-engine', 'wrong-scope', 'source-wheel-confusion',
        'wrong-output', 'wrong-source-revision', 'publisher-claim', 'absent-derivation', 'absent-local-supply'])
def test_invalid_package_authority_and_derivation(change):
    terms = package_terms()
    change(terms)
    with pytest.raises(proto.ProtocolError):
        v3.validate_terms(terms)


@pytest.mark.parametrize('change', [
    lambda d: d.update(extra=1),
    lambda d: d.update(version=True),
    lambda d: d['target'].update(python='3.13'),
    lambda d: d.update(manifest_sha256=None),
    lambda d: d['components'].append(d['components'][0]),
    lambda d: d['components'][0].update(readiness='unknown'),
    lambda d: d['components'][0].update(scope='repair'),
    lambda d: d.update(engine_action='rebuild'),
    lambda d: d['artifacts'].append(d['artifacts'][0]),
    lambda d: d['artifacts'][0].update(sha256='A' * 64),
    lambda d: d['artifacts'][0].update(size=None),
    lambda d: d['artifacts'][0].update(expected_new_bytes=True),
    lambda d: d['artifacts'][0].update(expected_new_bytes=0),
    lambda d: d['artifacts'][0].update(verified_reuse_bytes=4, expected_new_bytes=4, max_payload_bytes=6),
    lambda d: d['artifacts'][0].update(max_payload_bytes=11),
    lambda d: d['artifacts'][0].update(retry_headroom_bytes=-1),
    lambda d: d['artifacts'][0]['source'].update(revision='main'),
    lambda d: d['artifacts'][0]['source'].update(url='https://example.invalid/main/model.safetensors'),
    lambda d: d['artifacts'][0]['source'].update(revision='9' * 64),
    lambda d: d['artifacts'][0]['source'].update(url='http://example.invalid/model'),
    lambda d: d['artifacts'][0]['source'].update(url='https://user@host.invalid/model'),
    lambda d: d['artifacts'][0].update(filename='../model'),
    lambda d: d['payload'].update(max_payload_bytes=11),
    lambda d: d['payload'].update(retry_headroom_bytes=3, max_payload_bytes=11),
    lambda d: d['payload'].update(max_payload_bytes=None),
    lambda d: d['disk'].update(new_bytes=True),
], ids=['extra-field', 'bool-version', 'target', 'no-manifest', 'duplicate-component', 'unknown-readiness',
        'implicit-repair', 'unknown-action', 'duplicate-artifact', 'invalid-hash', 'unknown-size', 'bool-count',
        'zero-expansion', 'unqualified-partial', 'wrong-cap', 'negative-retry', 'mutable-source',
        'commit-url-mismatch', 'source-content-mismatch', 'http-source',
        'credential-source', 'unsafe-filename', 'wrong-total', 'excess-shared-retry', 'unknown-total', 'bool-disk'])
def test_strict_v3_terms(change):
    terms = model_terms()
    change(terms)
    with pytest.raises(proto.ProtocolError):
        v3.validate_terms(terms)


def test_shared_allowance_and_artifact_caps_both_apply():
    terms = model_terms()
    added = copy.deepcopy(terms['artifacts'][0])
    added['id'] += '2'
    terms['artifacts'].append(added)
    terms['payload'].update(expected_new_bytes=16, retry_headroom_bytes=1, max_payload_bytes=17)
    assert v3.validate_terms(terms)['artifacts'][1]['max_payload_bytes'] == 10
    assert terms['payload']['max_payload_bytes'] < sum(a['max_payload_bytes'] for a in terms['artifacts'])


@pytest.mark.parametrize('state', ['ready', 'unverified', 'busy', 'unsupported', 'bad-bundle'])
def test_nonacquirable_states_are_preserved_without_authority(state):
    terms = model_terms()
    terms['components'][0].update(readiness=state, scope=None)
    terms['artifacts'] = []
    terms['payload'] = dict.fromkeys(terms['payload'], 0)
    assert v3.validate_terms(terms)['components'][0]['readiness'] == state
    terms['artifacts'] = model_terms()['artifacts']
    with pytest.raises(proto.ProtocolError):
        v3.validate_terms(terms)


def test_zero_payload_authority_cannot_expand_or_gain_retry_on_reused_file():
    terms = model_terms()
    terms['artifacts'][0].update(verified_reuse_bytes=8, expected_new_bytes=0,
                                 retry_headroom_bytes=0, max_payload_bytes=0)
    terms['payload'] = dict.fromkeys(terms['payload'], 0)
    raw = v3.encode_consent(consent(terms))
    claims = []
    with pytest.raises(proto.ProtocolError) as caught:
        v3.validate_and_spend(raw, model_terms(), session=SESSION, request_id=REQUEST,
                              claim=lambda token: claims.append(token), now=lambda: NOW)
    assert caught.value.code == proto.CONSENT_STALE and claims == []
    terms['artifacts'][0].update(retry_headroom_bytes=1, max_payload_bytes=1)
    terms['payload'].update(retry_headroom_bytes=1, max_payload_bytes=1)
    with pytest.raises(proto.ProtocolError):
        v3.validate_terms(terms)


@pytest.mark.parametrize('field', ['source', 'version', 'artifact-set', 'transfer-cap', 'manifest', 'disk', 'repair'])
def test_any_changed_authoritative_term_requires_new_consent_before_spending(field):
    shown = model_terms()
    current = copy.deepcopy(shown)
    artifact = current['artifacts'][0]
    if field == 'source':
        artifact['source']['url'] = 'https://another.invalid/' + '5' * 40 + '/model.safetensors'
    elif field == 'version':
        artifact['version'] = 'another-version'
    elif field == 'artifact-set':
        added = copy.deepcopy(artifact)
        added['id'] = 'qwen3-base:weights2'
        current['artifacts'].append(added)
        current['payload'] = {k: v * 2 for k, v in current['payload'].items()}
    elif field == 'transfer-cap':
        artifact.update(retry_headroom_bytes=3, max_payload_bytes=11)
        current['payload'].update(retry_headroom_bytes=3, max_payload_bytes=11)
    elif field == 'manifest':
        current['manifest_sha256'] = '9' * 64
    elif field == 'disk':
        current['disk']['temporary_headroom_bytes'] += 1
    else:
        current['components'][0].update(readiness='damaged', scope='repair')
    calls = []
    with pytest.raises(proto.ProtocolError) as caught:
        v3.validate_and_spend(v3.encode_consent(consent(shown)), current, session=SESSION, request_id=REQUEST,
                              claim=lambda token: calls.append(token), now=lambda: NOW)
    assert caught.value.code == proto.CONSENT_STALE and calls == []


@pytest.mark.parametrize('change,code', [
    ({'version': 2}, proto.UNSUPPORTED_VERSION), ({'version': True}, proto.UNSUPPORTED_VERSION),
    ({'session': 'c' * 32}, proto.WRONG_SESSION), ({'request_id': 'c' * 32}, proto.BAD_CONSENT),
    ({'issued_utc': '2026-01-01T00:00:00Z'}, proto.STALE_REQUEST),
    ({'issued_utc': '2030-01-01T00:00:00Z'}, proto.STALE_REQUEST),
    ({'acquisition_fingerprint': '0' * 64}, proto.BAD_CONSENT), ({'extra': True}, proto.BAD_CONSENT),
])
def test_forged_stale_wrong_session_or_v2_envelopes_are_refused(change, code):
    wire = consent().to_json()
    wire.update(change)
    with pytest.raises(proto.ProtocolError) as caught:
        v3.decode_consent(json.dumps(wire).encode(), session=SESSION, request_id=REQUEST, now=lambda: NOW)
    assert caught.value.code == code


def test_v2_and_v3_authorities_are_never_interpreted_as_each_other():
    legacy = proto.new_request(proto.ACTION_PLAN, [proto.KOKORO], session=SESSION, now=lambda: NOW)
    with pytest.raises(proto.ProtocolError) as caught:
        v3.decode_consent(proto.encode(legacy.to_json()), session=SESSION, request_id=REQUEST, now=lambda: NOW)
    assert caught.value.code == proto.UNSUPPORTED_VERSION
    with pytest.raises(proto.ProtocolError):
        proto.decode_request(v3.encode_consent(consent()), session=SESSION, now=lambda: NOW)
    with pytest.raises(proto.ProtocolError):
        v3.encode_consent(legacy)
    with pytest.raises(proto.ProtocolError):
        v3.encode_consent(dataclasses.replace(consent(), acquisition_fingerprint='0' * 64))


def test_valid_legacy_package_consent_cannot_be_promoted_to_v3():
    old = proto.Consent('c' * 32, proto.CONTEXT_MAIN, (proto.QWEN3_BASE,), {proto.QWEN3_BASE: 'install'},
                         ('qwen3-engine',), (), 13, 'd' * 64)
    request = proto.new_request(proto.ACTION_INSTALL, [proto.QWEN3_BASE], session=SESSION, consent=old,
                                now=lambda: NOW)
    with pytest.raises(proto.ProtocolError) as caught:
        v3.decode_consent(proto.encode(request.to_json()), session=SESSION, request_id=request.request_id,
                           now=lambda: NOW)
    assert caught.value.code == proto.UNSUPPORTED_VERSION
    with pytest.raises(proto.ProtocolError):
        v3.encode_consent(old)


def test_v3_json_identity_is_deterministic_and_snapshots_input():
    original = model_terms()
    result = consent(original)
    raw = v3.encode_consent(result)
    reordered = dict(reversed(list(original.items())))
    assert v3.acquisition_fingerprint(original) == v3.acquisition_fingerprint(reordered)
    original['artifacts'][0]['source']['url'] = 'https://other.invalid/model'
    assert v3.encode_consent(result) == raw


def test_complete_reviewed_89_package_graph_and_one_model_can_be_serialized():
    from tts import qwen3_package_manifest as packages

    root = Path(__file__).resolve().parents[2]
    raw = (root / 'scripts/qwen3-artifacts.json').read_bytes()
    document = json.loads(raw)
    manifest = packages.load_manifest(raw, (root / 'scripts/qwen3-requirements.txt').read_bytes())
    terms = model_terms()
    terms.update(manifest_sha256=manifest.content_sha256, runtime_lock_sha256=packages.ORIGINAL_LOCK_SHA256,
                 effective_lock_sha256=manifest.effective_lock_sha256, engine_action='install-missing',
                 engine_readiness='missing')
    for wheel in manifest.wheels:
        artifact = copy.deepcopy(terms['artifacts'][0])
        artifact.update(id='qwen3-package:' + wheel.name, kind='package', name=wheel.name, version=wheel.version,
                        filename=wheel.filename, size=wheel.size, sha256=wheel.sha256,
                        expected_new_bytes=wheel.size, retry_headroom_bytes=0, max_payload_bytes=wheel.size,
                        source={'kind': 'pinned-https', 'url': wheel.source_url, 'revision': wheel.sha256})
        if wheel.name == 'sox':
            artifact.update(verified_reuse_bytes=wheel.size, expected_new_bytes=0, max_payload_bytes=0,
                            source={'kind': 'local-derived', 'url': None, 'revision': packages.SOX_SOURCE_SHA256},
                            derivative={'source_filename': 'sox-1.5.0.tar.gz',
                                        'source_sha256': packages.SOX_SOURCE_SHA256, 'source_size': 63905,
                                        'build_inputs_sha256': hashlib.sha256(json.dumps(document['build_only'],
                                            sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
                                        'output_sha256': packages.SOX_WHEEL_SHA256})
        terms['artifacts'].append(artifact)
    terms['artifacts'].sort(key=lambda a: a['id'])
    expected = sum(a['expected_new_bytes'] for a in terms['artifacts'])
    terms['payload'] = {'expected_new_bytes': expected, 'retry_headroom_bytes': 2, 'max_payload_bytes': expected + 2}
    encoded = v3.encode_consent(consent(terms))
    result = v3.decode_consent(encoded, session=SESSION, request_id=REQUEST, now=lambda: NOW)
    assert len(result.to_json()['terms']['artifacts']) == 90
    assert len(encoded) <= v3.MAX_MESSAGE_BYTES


@pytest.mark.parametrize('raw', [b'{"version":3,"version":3}', b'{"value":NaN}', b'[]', b'no json',
                                  b'x' * (v3.MAX_MESSAGE_BYTES + 1)],
                         ids=['duplicate', 'nan', 'array', 'invalid', 'oversized'])
def test_malformed_v3_serialization(raw):
    with pytest.raises(proto.ProtocolError):
        v3.decode_consent(raw, session=SESSION, request_id=REQUEST, now=lambda: NOW)
