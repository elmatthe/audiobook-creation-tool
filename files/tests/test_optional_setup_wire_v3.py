"""Offline full-disclosure wire contracts; never observe or mutate installed components."""
import dataclasses
import hashlib
import json
import time
import tracemalloc
from pathlib import Path

import pytest

from shared import optional_setup_protocol as proto
from shared import optional_setup_v3 as v3
from test_optional_setup_v3 import model_terms

pytestmark = pytest.mark.usefixtures('production_writes_refused')
SESSION, P, I, PLAN = (c * 32 for c in 'abcd')
NOW = 1792886400


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')


def document(terms=None):
    terms = model_terms() if terms is None else terms
    return {'components': terms['components'], 'engine_readiness': terms['engine_readiness'], 'terms': terms,
            'prior_state': {'schema': 'act-prior-transfer-state', 'version': 1, 'history': [], 'partials': []},
            'reasons': [], 'operations': {r['id']: r['scope'] or 'none' for r in terms['components']},
            'installed_disk_bounds': {'engine': {'bytes': 0, 'basis': 'approximate'},
                                      'spacy': {'bytes': 0, 'basis': 'approximate'}}}


def planning(components=None, engine_action='none'):
    from shared import optional_setup_wire_v3 as wire
    raw = wire.encode_planning_request(request_id=P, intended_request_id=I, session=SESSION, plan_id=PLAN,
        components=[proto.QWEN3_BASE] if components is None else components, engine_action=engine_action,
        issued_utc=proto.utc_text(NOW), now=lambda: NOW)
    return wire.decode_planning_request(raw, session=SESSION, request_id=P, now=lambda: NOW)


def disclosure(doc=None, request=None):
    from shared import optional_setup_wire_v3 as wire
    request = planning() if request is None else request
    raw = wire.encode_disclosure(canonical(document() if doc is None else doc), planning=request,
                                issued_utc=proto.utc_text(NOW), now=lambda: NOW)
    return wire.decode_disclosure(raw, planning=request, session=SESSION, now=lambda: NOW)


def confirmation(shown=None):
    from shared import optional_setup_wire_v3 as wire
    shown = disclosure() if shown is None else shown
    consent = v3.new_consent(shown.to_json()['document']['terms'], session=SESSION, request_id=I, now=lambda: NOW)
    raw_consent = v3.encode_consent(consent)
    raw = wire.encode_confirmation_request(disclosure=shown, raw_consent=raw_consent,
                                          issued_utc=proto.utc_text(NOW), now=lambda: NOW)
    return raw, shown, raw_consent


def decode_confirmation(raw, shown, raw_consent, **changes):
    from shared import optional_setup_wire_v3 as wire
    kwargs = dict(raw_disclosure=shown.raw, raw_consent=raw_consent, expected_disclosure=shown,
                  session=SESSION, request_id=I, now=lambda: NOW)
    kwargs.update(changes)
    return wire.decode_confirmation_request(raw, **kwargs)


def test_original_disclosure_and_separate_consent_round_trip():
    from shared import optional_setup_wire_v3 as wire
    raw, shown, raw_consent = confirmation()
    result = decode_confirmation(raw, shown, raw_consent)
    assert result.disclosure.raw == shown.raw
    assert result.disclosure.document == canonical(document())
    assert result.raw_consent == raw_consent
    assert result.consent.request_id == I != P
    assert wire.encode_confirmation_request(disclosure=result.disclosure, raw_consent=result.raw_consent,
        issued_utc=proto.utc_text(NOW), now=lambda: NOW) == raw
    assert proto.PROTOCOL_VERSION == 2 and v3.VERSION == 3
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.disclosure.raw = b'changed'


def engine_identity():
    return {'parent': [1, 2], 'parent_cfg': '1' * 64, 'canonical_exists': False, 'entries': [], 'record': {},
            'selected_canonical': True, 'path': '<synthetic-canonical-engine>'}


def graph_document(all_components=False, histories=0):
    """Use the FULL public identities, without Planner/health/store/runtime observations.

    Local-derived sox reuse is synthetic disclosure, not proof of portable supply.
    The 123-row graph deduplicates shared Qwen content just like the authority.
    """
    from tts import qwen3_package_manifest as packages
    from tts import model_assets as assets
    root = Path(__file__).resolve().parents[2]
    raw = (root / 'scripts/qwen3-artifacts.json').read_bytes()
    manifest = packages.load_manifest(raw, (root / 'scripts/qwen3-requirements.txt').read_bytes())
    components = list(proto.COMPONENTS) if all_components else [proto.QWEN3_BASE]
    qwen = [c for c in components if c in proto.QWEN3_MODEL_KEYS]
    terms = model_terms()
    terms.update(manifest_sha256=manifest.content_sha256, runtime_lock_sha256=packages.ORIGINAL_LOCK_SHA256,
                 effective_lock_sha256=manifest.effective_lock_sha256, engine_action='install-missing',
                 engine_readiness='missing',
                 components=[{'id': c, 'readiness': 'missing', 'scope': 'install'} for c in components])
    rows = {}

    def row(key, owners, kind, name, version, filename, size, digest, source, derivative=None):
        rows[key] = dict(id=key, kind=kind, components=owners, name=name, version=version, filename=filename,
            size=size, sha256=digest, source=source, derivative=derivative, verified_reuse_bytes=0,
            expected_new_bytes=size, retry_headroom_bytes=0, max_payload_bytes=size)

    for wheel in manifest.wheels:
        key = 'qwen3-package:' + wheel.name
        row(key, qwen, 'package', wheel.name, wheel.version, wheel.filename, wheel.size, wheel.sha256,
            dict(kind='pinned-https', url=wheel.source_url, revision=wheel.sha256))
        if wheel.name == 'sox':
            rows[key].update(verified_reuse_bytes=wheel.size, expected_new_bytes=0, max_payload_bytes=0,
                source=dict(kind='local-derived', url=None, revision=packages.SOX_SOURCE_SHA256),
                derivative=dict(source_filename='sox-1.5.0.tar.gz', source_size=63905,
                    source_sha256=packages.SOX_SOURCE_SHA256, output_sha256=packages.SOX_WHEEL_SHA256,
                    build_inputs_sha256=hashlib.sha256(canonical(json.loads(raw)['build_only'])).hexdigest()))
    assert len(rows) == 89
    if all_components:
        models = json.loads((root / 'scripts/tts/qwen3_models.json').read_bytes())['models']
        for component in qwen:
            spec = models[proto.QWEN3_MODEL_KEYS[component]]
            for name, want in spec['files'].items():
                key = 'qwen3-file:' + want['sha256']
                if key in rows:
                    rows[key]['components'].append(component)
                else:
                    row(key, [component], 'model', 'qwen3-file', 'reviewed', Path(name).name,
                        want['size'], want['sha256'], dict(kind='pinned-https', revision=spec['revision'],
                            url=f"https://huggingface.co/{spec['repo']}/resolve/{spec['revision']}/{name}"))
        for component, repo, revision, files in (
            (proto.KOKORO, assets.KOKORO_REPO, assets.KOKORO_REVISION, assets.KOKORO_FILES),
            (proto.CHATTERBOX, assets.CHATTERBOX_REPO, assets.CHATTERBOX_REVISION, assets.CHATTERBOX_FILES)):
            for name, (size, digest) in files.items():
                row(component + ':' + digest, [component], 'model', component, 'reviewed', Path(name).name,
                    size, digest, dict(kind='pinned-https', revision=revision,
                                      url=f'https://huggingface.co/{repo}/resolve/{revision}/{name}'))
        row('spacy-english:' + assets.SPACY_WHEEL_SHA256, [proto.KOKORO], 'model', 'spacy-english', 'reviewed',
            assets.SPACY_WHEEL_NAME, assets.SPACY_WHEEL_SIZE, assets.SPACY_WHEEL_SHA256,
            dict(kind='pinned-https', url=assets.SPACY_WHEEL_URL, revision=assets.SPACY_WHEEL_SHA256))
        assert len(rows) == 123
    terms['artifacts'] = sorted(rows.values(), key=lambda a: a['id'])
    expected = sum(a['expected_new_bytes'] for a in rows.values())
    terms['payload'] = dict(expected_new_bytes=expected, retry_headroom_bytes=0, max_payload_bytes=expected)
    terms['disk'] = dict(new_bytes=expected * 2, temporary_headroom_bytes=8_000_000_000)
    v3.validate_terms(terms)
    doc = document(terms)
    doc['engine_identity'] = engine_identity()
    doc['disclosure_metadata'] = {'basis': 'synthetic public identity fixture', 'detail': 'Full terms, café / 音声'}
    for index in range(histories):
        state = dict(status=('open', 'spent', 'cancelled')[index % 3],
                     actual={a['id']: min(a['size'], 1024) for a in rows.values()},
                     reserved={a['id']: a['size'] if i % 3 == 0 else 0 for i, a in enumerate(rows.values())})
        doc['prior_state']['history'].append(dict(consent_id=f'{index + 1:032x}', session='e' * 32,
            fingerprint='f' * 64, state=state, sequence=index + 2, chain=f'{index + 1:064x}'))
        doc['prior_state']['partials'].append(dict(name=f'{index + 1:032x}.part', size=137 + index,
                                                  mtime_ns=1_700_000_000_000_000_000 + index,
                                                  verified_reuse_bytes=0))
    return doc


@pytest.mark.parametrize('all_components,histories,count', [(False, 0, 89), (True, 0, 123), (True, 5, 123)])
def test_complete_public_graph_and_original_histories_round_trip(all_components, histories, count):
    from shared import optional_setup_wire_v3 as wire
    doc = graph_document(all_components, histories)
    request = planning([r['id'] for r in doc['components']], 'install-missing')
    shown = disclosure(doc, request)
    raw, _, consent = confirmation(shown)
    for _ in range(3):
        result = decode_confirmation(raw, shown, consent)
        assert result.disclosure.document == canonical(doc)
        assert len(result.disclosure.to_json()['document']['terms']['artifacts']) == count
        assert result.disclosure.to_json()['document']['prior_state'] == doc['prior_state']
        assert wire.encode_disclosure(result.disclosure.document, planning=request,
            issued_utc=proto.utc_text(NOW), now=lambda: NOW) == shown.raw
    altered_copy = result.disclosure.to_json()
    altered_copy['document']['prior_state']['history'].clear()
    assert result.disclosure.document == canonical(doc)


def test_multicomponent_without_engine_action():
    terms = model_terms()
    terms['components'].insert(0, {'id': proto.KOKORO, 'readiness': proto.READY, 'scope': None})
    shown = disclosure(document(terms), planning([proto.KOKORO, proto.QWEN3_BASE]))
    raw, _, consent = confirmation(shown)
    assert decode_confirmation(raw, shown, consent).consent.to_json()['terms'] == terms


@pytest.mark.parametrize('field,value', [
    ('version', 2), ('version', True), ('version', 4), ('protocol', 'other'), ('action', 'install'),
    ('request_id', P), ('request_id', 'x'), ('session', 'e' * 32), ('plan_id', 'f' * 32),
    ('planning_request_id', I), ('engine_action', 'rebuild-canonical'), ('engine_action', 'execute'),
    ('components', [proto.KOKORO]), ('components', [proto.QWEN3_BASE, proto.QWEN3_BASE]),
    ('components', ['unknown']), ('components', [proto.QWEN3_BASE, proto.KOKORO]),
    ('plan_sha256', 'f' * 64), ('plan_sha256', 'A' * 64), ('consent_sha256', 'e' * 64),
    ('options', {'runner': 'pip'}), ('options', {'purpose': 'local-qualification'}), ('options', []),
    ('consent', {'version': 2}), ('consumer', {'action': 'install'}), ('intended_request_id', I),
])
def test_confirmation_control_tampering(field, value):
    raw, shown, consent = confirmation()
    assert decode_confirmation(raw, shown, consent)
    d = json.loads(raw)
    d[field] = value
    with pytest.raises(proto.ProtocolError):
        decode_confirmation(canonical(d), shown, consent)


@pytest.mark.parametrize('missing', sorted(['plan_sha256', 'consent_sha256', 'options', 'planning_request_id',
                                         'plan_id', 'request_id', 'issued_utc', 'engine_action', 'components']))
def test_confirmation_missing_fields(missing):
    raw, shown, consent = confirmation()
    d = json.loads(raw)
    del d[missing]
    with pytest.raises(proto.ProtocolError):
        decode_confirmation(canonical(d), shown, consent)


@pytest.mark.parametrize('kind', ['history-change', 'history-reduction', 'partial-reduction', 'disk', 'engine',
                                 'metadata', 'payload', 'reuse', 'source', 'remove-original-field'])
def test_independently_retained_original_defeats_internally_consistent_substitutions(kind):
    from shared import optional_setup_wire_v3 as wire
    doc = graph_document(True, 1)
    request = planning(list(proto.COMPONENTS), 'install-missing')
    original = disclosure(doc, request)
    if kind == 'history-change':
        doc['prior_state']['history'][0]['state']['actual'][doc['terms']['artifacts'][0]['id']] += 1
    elif kind == 'history-reduction':
        doc['prior_state']['history'] = []
    elif kind == 'partial-reduction':
        doc['prior_state']['partials'] = []
    elif kind == 'disk':
        doc['terms']['disk']['new_bytes'] -= 1
    elif kind == 'engine':
        doc['engine_identity']['parent_cfg'] = '2' * 64
    elif kind == 'metadata':
        doc['disclosure_metadata']['detail'] = 'replacement'
    elif kind == 'payload':
        row = next(a for a in doc['terms']['artifacts'] if a['expected_new_bytes'])
        row['size'] += 1
        row['expected_new_bytes'] += 1
        row['max_payload_bytes'] += 1
        doc['terms']['payload']['expected_new_bytes'] += 1
        doc['terms']['payload']['max_payload_bytes'] += 1
    elif kind == 'reuse':
        row = next(a for a in doc['terms']['artifacts'] if a['expected_new_bytes'])
        row.update(verified_reuse_bytes=row['size'], expected_new_bytes=0, max_payload_bytes=0)
        doc['terms']['payload']['expected_new_bytes'] -= row['size']
        doc['terms']['payload']['max_payload_bytes'] -= row['size']
    elif kind == 'source':
        row = next(a for a in doc['terms']['artifacts'] if a['source']['kind'] == 'pinned-https')
        row['source']['url'] = 'https://replacement.invalid/' + row['source']['revision'] + '/object'
    else:
        del doc['disclosure_metadata']
    replacement = disclosure(doc, request)
    forged_request, _, forged_consent = confirmation(replacement)
    # All received hashes, terms and fingerprints agree with the forged Plan.
    assert decode_confirmation(forged_request, replacement, forged_consent)
    with pytest.raises(proto.ProtocolError):
        wire.decode_confirmation_request(forged_request, raw_disclosure=replacement.raw,
            raw_consent=forged_consent, expected_disclosure=original, session=SESSION, request_id=I, now=lambda: NOW)


@pytest.mark.parametrize('source', ['planning', 'disclosure', 'confirmation', 'consent'])
@pytest.mark.parametrize('issued', [proto.utc_text(NOW - 601), proto.utc_text(NOW + 61), '2026-02-30T00:00:00Z',
    '2026-10-25T23:59:60Z', '2026-10-25T00:00:00+00:00', 'not-a-time', True, None])
def test_timestamps_are_strict_and_fresh(source, issued):
    from shared import optional_setup_wire_v3 as wire
    raw, shown, consent = confirmation()
    if source == 'planning':
        d = planning().to_json()
        d['issued_utc'] = issued
        attempt = lambda: wire.decode_planning_request(canonical(d), session=SESSION, request_id=P, now=lambda: NOW)
    elif source == 'disclosure':
        d = shown.to_json()
        d['issued_utc'] = issued
        attempt = lambda: wire.decode_disclosure(canonical(d), planning=planning(), session=SESSION, now=lambda: NOW)
    elif source == 'confirmation':
        d = json.loads(raw)
        d['issued_utc'] = issued
        attempt = lambda: decode_confirmation(canonical(d), shown, consent)
    else:
        d = json.loads(consent)
        d['issued_utc'] = issued
        consent = canonical(d)
        d = json.loads(raw)
        d['consent_sha256'] = hashlib.sha256(consent).hexdigest()
        attempt = lambda: decode_confirmation(canonical(d), shown, consent)
    with pytest.raises(proto.ProtocolError):
        attempt()


@pytest.mark.parametrize('age', [-60, 600])
def test_existing_freshness_boundaries_remain_admitted(age):
    from shared import optional_setup_wire_v3 as wire
    request = planning().to_json()
    request['issued_utc'] = proto.utc_text(NOW - age)
    assert wire.decode_planning_request(canonical(request), session=SESSION, request_id=P, now=lambda: NOW)


@pytest.mark.parametrize('kind', ['v2-consent', 'nested-legacy', 'wrong-fingerprint', 'different-terms',
                                 'wrong-request', 'wrong-session', 'null-terms', 'missing-consent-field'])
def test_separately_decoded_consent_is_original_v3(kind):
    raw, shown, consent = confirmation()
    c = json.loads(consent)
    if kind == 'v2-consent':
        c['version'] = 2
    elif kind == 'nested-legacy':
        c['terms'] = {'consent_id': 'e' * 32, 'version': 2}
    elif kind == 'wrong-fingerprint':
        c['acquisition_fingerprint'] = 'f' * 64
    elif kind == 'different-terms':
        c['terms']['disk']['new_bytes'] += 1
        c['acquisition_fingerprint'] = v3.acquisition_fingerprint(c['terms'])
    elif kind == 'wrong-request':
        c['request_id'] = P
    elif kind == 'wrong-session':
        c['session'] = 'e' * 32
    elif kind == 'null-terms':
        c['terms'] = None
    else:
        del c['issued_utc']
    consent = canonical(c)
    control = json.loads(raw)
    control['consent_sha256'] = hashlib.sha256(consent).hexdigest()
    with pytest.raises(proto.ProtocolError):
        decode_confirmation(canonical(control), shown, consent)


@pytest.mark.parametrize('kind', ['null-terms', 'null-history', 'blocked', 'all-ready', 'engine-identity-missing',
                                 'disk-bounds-missing'])
def test_read_only_planning_result_never_permits_confirmation(kind):
    from shared import optional_setup_wire_v3 as wire
    doc = document()
    request = planning()
    if kind == 'null-terms':
        doc['terms'] = None
    elif kind == 'null-history':
        doc['prior_state'] = None
    elif kind == 'blocked':
        doc['reasons'] = ['BLOCKED: no supply']
    elif kind == 'disk-bounds-missing':
        del doc['installed_disk_bounds']
    elif kind == 'all-ready':
        terms = doc['terms']
        terms['components'][0].update(readiness='ready', scope=None)
        terms['artifacts'] = []
        terms['payload'] = dict(expected_new_bytes=0, retry_headroom_bytes=0, max_payload_bytes=0)
        doc['operations'][proto.QWEN3_BASE] = 'none'
    else:
        doc = graph_document()
        del doc['engine_identity']
        request = planning(engine_action='install-missing')
    shown = disclosure(doc, request)
    result = wire.encode_planning_result(disclosure=shown, issued_utc=proto.utc_text(NOW), now=lambda: NOW)
    decoded = wire.decode_planning_result(result, expected_disclosure=shown, session=SESSION, request_id=P,
                                          now=lambda: NOW)
    assert decoded['confirmable'] is False and decoded['verified'] == []
    # Supply a valid independent consent where terms are null. It cannot repair
    # missing/blocked original disclosure into executable authority.
    terms = doc['terms'] if doc['terms'] is not None else model_terms()
    consent = v3.encode_consent(v3.new_consent(terms, session=SESSION, request_id=I, now=lambda: NOW))
    with pytest.raises(proto.ProtocolError):
        wire.encode_confirmation_request(disclosure=shown, raw_consent=consent,
                                          issued_utc=proto.utc_text(NOW), now=lambda: NOW)


def test_v2_decoders_never_accept_v3_controls_or_consent():
    raw, _, consent = confirmation()
    for data in (planning().raw, raw, consent):
        with pytest.raises(proto.ProtocolError) as caught:
            proto.decode_request(data, session=SESSION, now=lambda: NOW)
        # Legacy v2 checks its exact request keys before its version header.
        assert caught.value.code == proto.MALFORMED


@pytest.mark.parametrize('raw', [b'{', b'{} trailing', b'[]', b'null', b'\xff', b'\xef\xbb\xbf{}',
    b'{"version":3,"version":3}', b'{"x":{"a":1,"a":2}}', b'{"x":NaN}', b'{"x":Infinity}',
    b'{"x":-Infinity}', b'{"x":1e9999}', b'{"x":"\\ud800"}', b'{"x":"\\udfff"}', b'{"x":' + b'9' * 5000 + b'}'])
def test_hostile_json_is_refused_with_typed_error(raw):
    from shared import optional_setup_wire_v3 as wire
    with pytest.raises(proto.ProtocolError):
        wire.decode_planning_request(raw, session=SESSION, request_id=P, now=lambda: NOW)
    with pytest.raises(proto.ProtocolError):
        wire.decode_disclosure(raw, planning=planning(), session=SESSION, now=lambda: NOW)


@pytest.mark.parametrize('target', ['control', 'disclosure', 'consent', 'result'])
def test_exact_raw_byte_limits_and_one_byte_over(target):
    from shared import optional_setup_wire_v3 as wire
    raw, shown, consent = confirmation()
    if target == 'disclosure':
        d = shown.to_json()
        d['document']['metadata_padding'] = ''
        d['document']['metadata_padding'] = 'x' * (wire.MAX_DISCLOSURE_BYTES - len(canonical(d)))
        data = canonical(d)
        assert len(data) == wire.MAX_DISCLOSURE_BYTES
        admit = lambda value: wire.decode_disclosure(value, planning=planning(), session=SESSION, now=lambda: NOW)
    elif target == 'consent':
        data = consent + b' ' * (wire.MAX_CONSENT_BYTES - len(consent))
        def admit(value):
            control = json.loads(raw)
            control['consent_sha256'] = hashlib.sha256(value).hexdigest()
            return decode_confirmation(canonical(control), shown, value)
    elif target == 'result':
        data = wire.encode_planning_result(disclosure=shown, issued_utc=proto.utc_text(NOW), now=lambda: NOW)
        data += b' ' * (wire.MAX_CONTROL_BYTES - len(data))
        admit = lambda value: wire.decode_planning_result(value, expected_disclosure=shown, session=SESSION,
                                                         request_id=P, now=lambda: NOW)
    else:
        data = raw + b' ' * (wire.MAX_CONTROL_BYTES - len(raw))
        admit = lambda value: decode_confirmation(value, shown, consent)
    assert admit(data)
    with pytest.raises(proto.ProtocolError) as caught:
        admit(data + b' ')
    assert caught.value.code == wire.RESOURCE_LIMIT


def count_values(value):
    return 1 + (sum(count_values(v) for v in value.values()) if type(value) is dict else
                sum(count_values(v) for v in value) if type(value) is list else 0)


@pytest.mark.parametrize('resource', ['depth', 'nodes'])
def test_exact_structural_limits_and_preparse_refusal(resource, monkeypatch):
    from shared import optional_setup_wire_v3 as wire
    d = disclosure().to_json()
    if resource == 'nodes':
        d['document']['additional_metadata'] = []
        d['document']['additional_metadata'] = [0] * (wire.MAX_NODES - count_values(d))
        assert count_values(d) == wire.MAX_NODES
    else:
        nested = 0
        for _ in range(wire.MAX_DEPTH - 3):
            nested = [nested]
        d['document']['additional_metadata'] = nested
    data = canonical(d)
    assert wire.decode_disclosure(data, planning=planning(), session=SESSION, now=lambda: NOW)
    if resource == 'nodes':
        d['document']['additional_metadata'].append(0)
    else:
        d['document']['additional_metadata'] = [d['document']['additional_metadata']]
    too_large = canonical(d)
    def parser_must_not_run(*args, **kwargs):
        raise AssertionError('excessive graph reached JSON parser')
    # Test the same parser admission used by every document, independently of
    # the preliminary trusted planning-request revalidation.
    monkeypatch.setattr(proto, 'strict_json', parser_must_not_run)
    with pytest.raises(proto.ProtocolError) as caught:
        wire._load(too_large, wire.MAX_DISCLOSURE_BYTES)
    assert caught.value.code == wire.RESOURCE_LIMIT


def test_no_field_dropping_to_admit_long_history():
    from shared import optional_setup_wire_v3 as wire
    doc = graph_document(True, 24)
    snapshot = canonical(doc)
    assert len(snapshot) > wire.MAX_DISCLOSURE_BYTES
    with pytest.raises(proto.ProtocolError) as caught:
        wire.encode_disclosure(snapshot, planning=planning(list(proto.COMPONENTS), 'install-missing'),
                                issued_utc=proto.utc_text(NOW), now=lambda: NOW)
    assert caught.value.code == wire.RESOURCE_LIMIT
    assert canonical(doc) == snapshot and len(doc['prior_state']['history']) == 24


def test_original_bytes_and_identity_are_required():
    from shared import optional_setup_wire_v3 as wire
    raw, shown, consent = confirmation()
    for bad in (None, b'', shown.document, shown.raw + b' '):
        with pytest.raises(proto.ProtocolError):
            decode_confirmation(raw, shown, consent, raw_disclosure=bad)
    for bad in (None, wire.Disclosure(shown.raw, b'{}')):
        with pytest.raises(proto.ProtocolError):
            decode_confirmation(raw, shown, consent, expected_disclosure=bad)
    with pytest.raises(proto.ProtocolError):
        decode_confirmation(raw, shown, consent, request_id='e' * 32)
    with pytest.raises(proto.ProtocolError):
        decode_confirmation(raw, shown, consent, session='e' * 32)
    # An I cannot be moved to P or a fresh I by rehashing the control.
    d = shown.to_json()
    d['intended_request_id'] = P
    with pytest.raises(proto.ProtocolError):
        wire.decode_disclosure(canonical(d), planning=planning(), session=SESSION, now=lambda: NOW)


def test_noncanonical_original_cannot_be_silently_reencoded():
    from shared import optional_setup_wire_v3 as wire
    shown = disclosure()
    with pytest.raises(proto.ProtocolError):
        wire.decode_disclosure(shown.raw + b' ', planning=planning(), session=SESSION, now=lambda: NOW)
    with pytest.raises(proto.ProtocolError):
        wire.encode_disclosure(json.dumps(document(), indent=2).encode(), planning=planning(),
                                issued_utc=proto.utc_text(NOW), now=lambda: NOW)


def test_codec_has_no_filesystem_claim_process_network_or_consent_creation(monkeypatch):
    from shared import optional_setup_wire_v3 as wire
    import builtins
    import os
    import subprocess
    import socket
    raw, shown, consent = confirmation()
    def forbidden(*args, **kwargs):
        raise AssertionError('pure codec attempted a side effect or minted consent')
    for obj, name in ((builtins, 'open'), (os, 'open'), (os, 'urandom'), (subprocess, 'Popen'),
                      (socket, 'socket'), (v3, 'new_consent'), (v3, 'validate_and_spend'),
                      (proto, 'claim_consent'), (proto, 'claim_request')):
        monkeypatch.setattr(obj, name, forbidden)
    assert decode_confirmation(raw, shown, consent)
    assert wire.encode_confirmation_request(disclosure=shown, raw_consent=consent,
        issued_utc=proto.utc_text(NOW), now=lambda: NOW) == raw
    assert wire.decode_planning_request(planning().raw, session=SESSION, request_id=P, now=lambda: NOW)


@pytest.mark.parametrize('target', ['planning', 'disclosure', 'result'])
@pytest.mark.parametrize('kind', ['version', 'missing', 'extra', 'selection-order', 'engine-action', 'wrong-session',
                                 'wrong-P', 'wrong-I', 'plan-id', 'options'])
def test_every_control_and_disclosure_binding_is_checked(target, kind):
    from shared import optional_setup_wire_v3 as wire
    request = planning([proto.KOKORO, proto.QWEN3_BASE])
    terms = model_terms()
    terms['components'].insert(0, dict(id=proto.KOKORO, readiness=proto.READY, scope=None))
    shown = disclosure(document(terms), request)
    if target == 'planning':
        d = request.to_json()
        admit = lambda data: wire.decode_planning_request(data, session=SESSION, request_id=P, now=lambda: NOW)
    elif target == 'disclosure':
        d = shown.to_json()
        admit = lambda data: wire.decode_disclosure(data, planning=request, session=SESSION, now=lambda: NOW)
    else:
        data = wire.encode_planning_result(disclosure=shown, issued_utc=proto.utc_text(NOW), now=lambda: NOW)
        d = json.loads(data)
        admit = lambda data: wire.decode_planning_result(data, expected_disclosure=shown, session=SESSION,
                                                         request_id=P, now=lambda: NOW)
    assert admit(canonical(d))
    if kind == 'version':
        d['version'] = True
    elif kind == 'missing':
        del d['issued_utc']
    elif kind == 'extra':
        d['runner'] = ['pip', 'install']
    elif kind == 'selection-order':
        d['selected' if target == 'disclosure' else 'components'].reverse()
    elif kind == 'engine-action':
        d['engine_action'] = 'rebuild-canonical'
        if target == 'planning':
            altered = admit(canonical(d))
            with pytest.raises(proto.ProtocolError):
                wire.decode_disclosure(shown.raw, planning=altered, session=SESSION, now=lambda: NOW)
            return
    elif kind == 'wrong-session':
        d['session'] = 'e' * 32
    elif kind == 'wrong-P':
        d['planning_request_id'] = I
    elif kind == 'wrong-I':
        d['intended_request_id'] = P
    elif kind == 'plan-id':
        d['plan_id'] = 'f' * 32
        if target == 'planning':
            # Initial planning accepts the trusted caller's new plan ID; the
            # resulting disclosure must still match that original request.
            altered = admit(canonical(d))
            with pytest.raises(proto.ProtocolError):
                wire.decode_disclosure(shown.raw, planning=altered, session=SESSION, now=lambda: NOW)
            return
    else:
        d['options'] = {'consumer': 'main-spacy'}
    with pytest.raises(proto.ProtocolError):
        admit(canonical(d))


@pytest.mark.parametrize('path,value', [
    (('terms', 'version'), True), (('terms', 'version'), 2),
    (('terms', 'consumers'), [{'runner': 'pip'}]), (('terms', 'purpose'), 'local-qualification'),
    (('terms', 'payload', 'expected_new_bytes'), True), (('terms', 'disk', 'new_bytes'), False),
    (('terms', 'artifacts', 0, 'size'), True), (('terms', 'artifacts', 0, 'max_payload_bytes'), 11),
    (('terms', 'artifacts', 0, 'source', 'kind'), 'executable'),
    (('terms', 'artifacts', 0, 'source', 'runner'), 'pip'),
    (('operations', proto.QWEN3_BASE), 'rebuild'), (('engine_readiness',), 'healthy'),
    (('installed_disk_bounds', 'engine', 'bytes'), True),
    (('installed_disk_bounds', 'spacy', 'basis'), 'exact'),
    (('prior_state', 'version'), True), (('prior_state', 'schema'), 'unknown'),
    (('prior_state', 'history'), [1]), (('prior_state', 'partials'), [None]),
    (('reasons',), 'reason'), (('components', 0, 'scope'), 'anything'),
])
def test_original_plan_structure_and_existing_v3_terms_are_strict(path, value):
    from shared import optional_setup_wire_v3 as wire
    doc = document()
    item = doc
    for key in path[:-1]:
        item = item[key]
    item[path[-1]] = value
    with pytest.raises(proto.ProtocolError):
        wire.encode_disclosure(canonical(doc), planning=planning(), issued_utc=proto.utc_text(NOW), now=lambda: NOW)


@pytest.mark.parametrize('path,value', [
    (('engine_identity', 'parent', 0), True), (('engine_identity', 'parent_cfg'), 'wrong'),
    (('engine_identity', 'selected_canonical'), 1), (('engine_identity', 'entries'), [['file', [True] * 5]]),
    (('prior_state', 'history', 0, 'sequence'), True),
    (('prior_state', 'history', 0, 'chain'), 'wrong'),
    (('prior_state', 'history', 0, 'state', 'status'), 'ready'),
    (('prior_state', 'partials', 0, 'size'), False),
    (('prior_state', 'partials', 0, 'verified_reuse_bytes'), 1),
])
def test_complete_history_and_engine_identity_structures_reject_malformed_values(path, value):
    doc = graph_document(histories=1)
    item = doc
    for key in path[:-1]:
        item = item[key]
    item[path[-1]] = value
    with pytest.raises(proto.ProtocolError):
        disclosure(doc, planning(engine_action='install-missing'))


def test_complete_rebuild_identity_inventory_is_retained():
    doc = graph_document()
    doc['engine_readiness'] = doc['terms']['engine_readiness'] = proto.DAMAGED
    doc['terms']['engine_action'] = 'rebuild-canonical'
    doc['components'][0].update(readiness=proto.DAMAGED, scope=proto.SCOPE_REPAIR)
    doc['operations'][proto.QWEN3_BASE] = proto.SCOPE_REPAIR
    identity = doc['engine_identity']
    identity.update(canonical_exists=True, entries=[['.', [1, 3, 0, NOW * 10**9, NOW * 10**9]],
        ['Lib/site-packages/example.py', [1, 4, 537, NOW * 10**9, NOW * 10**9]]],
        record={'path': '<synthetic-canonical-engine>', 'stage': 'installed', 'extra_identity': 'retained'})
    shown = disclosure(doc, planning(engine_action='rebuild-canonical'))
    raw, _, consent = confirmation(shown)
    assert decode_confirmation(raw, shown, consent).disclosure.to_json()['document'] == doc


@pytest.mark.parametrize('target', ['confirmation', 'consent'])
@pytest.mark.parametrize('payload', [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}', b'\xff', b'{',
                                    b'{"x":' + b'[' * 25 + b'0' + b']' * 25 + b'}'])
def test_hostile_confirmation_and_raw_consent_are_refused(target, payload):
    raw, shown, consent = confirmation()
    if target == 'consent':
        consent = payload
        d = json.loads(raw)
        d['consent_sha256'] = hashlib.sha256(consent).hexdigest()
        raw = canonical(d)
    else:
        raw = payload
    with pytest.raises(proto.ProtocolError):
        decode_confirmation(raw, shown, consent)


def test_result_cannot_claim_installed_readiness_or_confirmation_authority():
    from shared import optional_setup_wire_v3 as wire
    shown = disclosure()
    raw = wire.encode_planning_result(disclosure=shown, issued_utc=proto.utc_text(NOW), now=lambda: NOW)
    for field, value in [('verified', [proto.QWEN3_BASE]), ('confirmable', 1), ('confirmable', False),
                         ('plan_sha256', 'f' * 64), ('action', 'confirm')]:
        d = json.loads(raw)
        d[field] = value
        with pytest.raises(proto.ProtocolError):
            wire.decode_planning_result(canonical(d), expected_disclosure=shown, session=SESSION,
                                        request_id=P, now=lambda: NOW)
    _, _, consent = confirmation(shown)
    with pytest.raises(proto.ProtocolError):
        decode_confirmation(raw, shown, consent)


def test_leap_second_is_rejected_even_inside_freshness_window():
    from shared import optional_setup_wire_v3 as wire
    import calendar
    issued = '2026-10-25T23:59:60Z'
    normalized = calendar.timegm(time.strptime(issued, '%Y-%m-%dT%H:%M:%SZ'))
    d = planning().to_json()
    d['issued_utc'] = issued
    with pytest.raises(proto.ProtocolError, match='calendar'):
        wire.decode_planning_request(canonical(d), session=SESSION, request_id=P, now=lambda: normalized)


def test_no_application_or_side_effect_imports():
    import ast
    from shared import optional_setup_wire_v3 as wire
    tree = ast.parse(Path(wire.__file__).read_text(encoding='utf-8'))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module)
    assert imports <= {'__future__', 'calendar', 'hashlib', 'json', 'math', 're', 'time', 'dataclasses', 'shared'}


def test_intended_I_cannot_be_rebound_even_with_fresh_consistent_consent():
    raw, shown, _ = confirmation()
    new_i = 'e' * 32
    consent = v3.encode_consent(v3.new_consent(shown.to_json()['document']['terms'], session=SESSION,
                                             request_id=new_i, now=lambda: NOW))
    d = json.loads(raw)
    d['request_id'] = new_i
    d['consent_sha256'] = hashlib.sha256(consent).hexdigest()
    with pytest.raises(proto.ProtocolError, match='intended I'):
        decode_confirmation(canonical(d), shown, consent, request_id=new_i)


def test_limits_are_fixed_reviewed_contract_not_fixture_tuning():
    from shared import optional_setup_wire_v3 as wire
    assert wire.MAX_CONTROL_BYTES == 65_536
    assert wire.MAX_DISCLOSURE_BYTES == wire.MAX_CONSENT_BYTES == 262_144
    assert wire.MAX_DEPTH == 24 and wire.MAX_NODES == 65_536


@pytest.mark.parametrize('bad', [b'{}', b' ', b' ' * 65_537, b'\xff'],
                         ids=['missing-fields', 'invalid-json', 'oversize', 'invalid-utf8'])
def test_hand_constructed_planning_wrapper_cannot_bypass_admission(bad):
    from shared import optional_setup_wire_v3 as wire
    request = wire.PlanningRequest(bad)
    raw = disclosure().raw
    with pytest.raises(proto.ProtocolError):
        wire.decode_disclosure(raw, planning=request, session=SESSION, now=lambda: NOW)


def test_raw_admission_precedes_json_parsing_and_consent_hashing(monkeypatch):
    from shared import optional_setup_wire_v3 as wire
    def forbidden(*args, **kwargs):
        raise AssertionError('oversized input reached parser/hash')
    raw, shown, consent = confirmation()
    with monkeypatch.context() as scope:
        scope.setattr(proto, 'strict_json', forbidden)
        with pytest.raises(proto.ProtocolError) as caught:
            wire._load(b' ' * 262_145, wire.MAX_DISCLOSURE_BYTES)
        assert caught.value.code == wire.RESOURCE_LIMIT
    # Already validated retained disclosure can be supplied independently; an
    # oversized received consent must fail before hashing that consent.
    real_hash = hashlib.sha256
    def bounded_hash(data):
        if len(data) > wire.MAX_CONSENT_BYTES:
            forbidden()
        return real_hash(data)
    monkeypatch.setattr(hashlib, 'sha256', bounded_hash)
    with pytest.raises(proto.ProtocolError) as caught:
        decode_confirmation(raw, shown, b' ' * 262_145)
    assert caught.value.code == wire.RESOURCE_LIMIT


def test_largest_admitted_and_rejected_resource_measurements(record_property):
    from shared import optional_setup_wire_v3 as wire
    d = disclosure().to_json()
    d['document']['metadata_padding'] = ''
    d['document']['metadata_padding'] = 'x' * (wire.MAX_DISCLOSURE_BYTES - len(canonical(d)))
    max_bytes = canonical(d)
    d['document'].pop('metadata_padding')
    d['document']['metadata_nodes'] = []
    d['document']['metadata_nodes'] = [0] * (wire.MAX_NODES - count_values(d))
    max_nodes = canonical(d)
    d['document']['metadata_nodes'].append(0)
    request = planning()
    cases = [('256KiB-admitted', max_bytes, True), ('256KiB-plus-one-refused', max_bytes + b' ', False),
             ('65536-values-admitted', max_nodes, True), ('65537-values-refused', canonical(d), False)]
    records = []
    for name, data, accepted in cases:
        tracemalloc.start()
        start = time.perf_counter()
        try:
            if accepted:
                wire.decode_disclosure(data, planning=request, session=SESSION, now=lambda: NOW)
            else:
                with pytest.raises(proto.ProtocolError):
                    wire.decode_disclosure(data, planning=request, session=SESSION, now=lambda: NOW)
            elapsed = time.perf_counter() - start
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        records.append(dict(case=name, raw_bytes=len(data), elapsed_seconds=elapsed, peak_traced_bytes=peak))
    largest = wire.decode_disclosure(max_bytes, planning=request, session=SESSION, now=lambda: NOW)
    control, _, consent = confirmation(largest)
    consent += b' ' * (wire.MAX_CONSENT_BYTES - len(consent))
    c = json.loads(control)
    c['consent_sha256'] = hashlib.sha256(consent).hexdigest()
    control = canonical(c)
    control += b' ' * (wire.MAX_CONTROL_BYTES - len(control))
    graph = graph_document(True, 5)
    graph_shown = disclosure(graph, planning(list(proto.COMPONENTS), 'install-missing'))
    graph_control, _, graph_consent = confirmation(graph_shown)
    for name, c, shown, auth in [('576KiB-confirmation-admitted', control, largest, consent),
                                ('123-artifacts-5-histories', graph_control, graph_shown, graph_consent)]:
        tracemalloc.start()
        start = time.perf_counter()
        try:
            decode_confirmation(c, shown, auth)
            elapsed = time.perf_counter() - start
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        records.append(dict(case=name, raw_bytes=len(c) + len(shown.raw) + len(auth),
                            elapsed_seconds=elapsed, peak_traced_bytes=peak))
    record_property('wire_resource_measurements', json.dumps(records))
    print('WIRE_RESOURCE_MEASUREMENTS=' + json.dumps(records, sort_keys=True))
