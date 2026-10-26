"""Protocol v3 acquisition consent foundation (Stage 4B-1). Standard library, no transport or execution.

The worker still accepts v2 requests and refuses production installs. These explicit v3 codecs never upgrade v2.
An internally consistent fingerprint is not authorization: ``validate_and_spend`` compares all terms to a fresh,
independently trusted plan and uses the existing one-time claim callback. Future callers must derive that plan from
reviewed package/model manifests and prove reuse under the acquisition lock. Full-file reuse only in this schema;
authenticated partials, transport ledgers, offline pip and actual build/install/rebuild enforcement remain later work.
"""
from __future__ import annotations

import calendar
import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import Callable

from shared import optional_setup_protocol as proto

VERSION = proto.ACQUISITION_PROTOCOL_VERSION
MAX_MESSAGE_BYTES = 256 * 1024
ENGINE_ACTIONS = ('none', 'install-missing', 'rebuild-canonical')
ARTIFACT_KINDS = ('model', 'package', 'source-archive', 'build-input')
_TERMS = {'schema', 'version', 'target', 'manifest_sha256', 'runtime_lock_sha256', 'effective_lock_sha256',
          'components', 'engine_action', 'engine_readiness', 'artifacts', 'payload', 'disk'}
_ARTIFACT = {'id', 'kind', 'components', 'name', 'version', 'filename', 'size', 'sha256', 'source', 'derivative',
             'verified_reuse_bytes', 'expected_new_bytes', 'retry_headroom_bytes', 'max_payload_bytes'}
_PAYLOAD = {'expected_new_bytes', 'retry_headroom_bytes', 'max_payload_bytes'}
_ENVELOPE = {'protocol', 'version', 'request_id', 'session', 'issued_utc', 'consent_id', 'terms',
             'acquisition_fingerprint'}
_HASH = re.compile(r'[a-f0-9]{64}')
_TOKEN = re.compile(r'[a-z0-9][a-z0-9_.:+-]{0,159}')


def _require(condition: bool, message: str, code: str = proto.BAD_CONSENT) -> None:
    if not condition:
        raise proto.ProtocolError(code, message)


def _keys(value, keys: set, label: str) -> dict:
    _require(type(value) is dict and set(value) == keys, f'{label} must have exactly {sorted(keys)}')
    return value


def _hash(value) -> bool:
    return type(value) is str and _HASH.fullmatch(value) is not None


def _bytes(value, label: str) -> int:
    _require(type(value) is int and 0 <= value <= 2**63 - 1, f'{label} must be an exact nonnegative byte count')
    return value


def _canonical(value) -> bytes:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')
    except (ValueError, TypeError, RecursionError):
        raise proto.ProtocolError(proto.BAD_CONSENT, 'invalid v3 JSON value') from None
    _require(len(raw) <= MAX_MESSAGE_BYTES, 'v3 consent too large')
    return raw


def _selection(value) -> tuple[str, ...]:
    return proto._wire_selection(value, allow_empty=False)


def validate_terms(value: dict) -> dict:
    """Strict exact terms; returns an independent JSON copy. No unknown counts become zero.

    Artifact caps include their disclosed retry headroom. Shared retry may be smaller than their sum; both ceilings
    apply. Disk/headroom are separate disclosure. Scope follows proved component readiness; engine damage must be
    separately proved and explicitly authorized. Model-only terms always carry engine_action=none.
    """
    d = _keys(value, _TERMS, 'v3 acquisition terms')
    _require(d['schema'] == 'act-acquisition-terms' and type(d['version']) is int and d['version'] == 1,
             'unsupported v3 terms schema')
    _require(d['target'] == {'implementation': 'CPython', 'python': '3.12', 'platform': 'win_amd64'},
             'unreviewed acquisition target')
    _require(all(_hash(d[k]) for k in ('manifest_sha256', 'runtime_lock_sha256', 'effective_lock_sha256')),
             'missing manifest/lock identity')
    rows = d['components']
    _require(type(rows) is list and rows, 'v3 must name component scopes')
    scopes = {}
    for row in rows:
        _keys(row, {'id', 'readiness', 'scope'}, 'component')
        _require(type(row['id']) is str and row['id'] in proto.COMPONENTS and row['id'] not in scopes,
                 'unknown/duplicate component')
        _require(type(row['readiness']) is str and row['readiness'] in proto.READINESS, 'unknown readiness')
        _require(row['scope'] == proto.acquisition_scope(row['readiness']), 'scope does not match readiness')
        scopes[row['id']] = row['scope']
    _selection([r['id'] for r in rows])
    action, engine = d['engine_action'], d['engine_readiness']
    _require(type(action) is str and action in ENGINE_ACTIONS, 'unknown engine action')
    _require(type(engine) is str and engine in proto.READINESS, 'unknown engine readiness')
    if action != 'none':
        _require(engine == {'install-missing': proto.MISSING, 'rebuild-canonical': proto.DAMAGED}[action],
                 'engine install/rebuild needs a proved matching state')
        required = proto.SCOPE_INSTALL if action == 'install-missing' else proto.SCOPE_REPAIR
        _require(any(scopes.get(c) == required for c in proto.QWEN3_MODEL_KEYS),
                 'engine action needs explicit matching Qwen component scope')
    artifacts = d['artifacts']
    _require(type(artifacts) is list and len(artifacts) <= 256, 'invalid artifact set')
    seen, expected, retry, packages = [], 0, 0, 0
    for a in artifacts:
        _keys(a, _ARTIFACT, 'artifact')
        for key in ('id', 'name', 'version'):
            _require(type(a[key]) is str and _TOKEN.fullmatch(a[key]) is not None, f'invalid artifact {key}')
        _require(a['id'] not in seen, 'duplicate artifact')
        seen.append(a['id'])
        _require(type(a['kind']) is str and a['kind'] in ARTIFACT_KINDS, 'unknown artifact kind')
        owners = _selection(a['components'])
        _require(all(c in scopes and scopes[c] is not None for c in owners), 'artifact lacks install/repair scope')
        if a['kind'] != 'model':
            packages += 1
            _require(action != 'none' and all(c in proto.QWEN3_MODEL_KEYS for c in owners),
                     'package acquisition needs explicit engine authority')
        _require(type(a['filename']) is str and re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.+-]{0,199}', a['filename'])
                 is not None, 'invalid artifact filename')
        _require(_hash(a['sha256']), 'artifact needs reviewed SHA-256')
        size = _bytes(a['size'], 'artifact size')
        reuse = _bytes(a['verified_reuse_bytes'], 'verified reuse')
        new = _bytes(a['expected_new_bytes'], 'expected new payload')
        extra = _bytes(a['retry_headroom_bytes'], 'artifact retry headroom')
        cap = _bytes(a['max_payload_bytes'], 'artifact payload cap')
        _require(size > 0 and reuse in (0, size) and new == size - reuse, 'unverified/partial reuse or wrong new payload')
        _require(cap == new + extra and (new > 0 or extra == 0), 'artifact ceiling differs from new payload plus retry')
        source = _keys(a['source'], {'kind', 'url', 'revision'}, 'immutable source')
        _require(type(source['revision']) is str and re.fullmatch(r'(?:[a-f0-9]{40}|[a-f0-9]{64})',
                                                                source['revision']) is not None,
                 'source revision must be an immutable commit/hash')
        if source['kind'] == 'pinned-https':
            _require(type(source['url']) is str and re.fullmatch(r'https://[A-Za-z0-9.-]+/[^\s?#\\]+',
                                                               source['url']) is not None,
                     'source must be an exact HTTPS URL without redirects/options')
            _require((len(source['revision']) == 64 and source['revision'] == a['sha256']) or (
                len(source['revision']) == 40 and '/' + source['revision'] + '/' in source['url']),
                'source URL/revision does not bind the immutable artifact or commit')
        else:
            _require(source['kind'] == 'local-derived' and source['url'] is None and a['kind'] == 'package'
                     and a['derivative'] is not None and reuse == size and cap == 0,
                     'local derivative must already be verified; missing supply is blocked')
        derivative = a['derivative']
        if derivative is not None:
            _keys(derivative, {'source_filename', 'source_sha256', 'source_size', 'build_inputs_sha256',
                               'output_sha256'}, 'source/build derivative')
            _require(a['kind'] == 'package' and all(_hash(derivative[k]) for k in (
                'source_sha256', 'build_inputs_sha256', 'output_sha256')), 'invalid derivative hashes')
            _require(type(derivative['source_filename']) is str and re.fullmatch(
                r'[A-Za-z0-9_][A-Za-z0-9_.+-]{0,199}', derivative['source_filename']) is not None,
                'invalid derivative source filename')
            _require(_bytes(derivative['source_size'], 'source size') > 0
                     and derivative['output_sha256'] == a['sha256']
                     and derivative['source_sha256'] != a['sha256'], 'source/output hash confusion')
            if source['kind'] == 'local-derived':
                _require(source['revision'] == derivative['source_sha256'], 'derivative source revision mismatch')
        expected += new
        retry += extra
    _require(seen == sorted(seen), 'artifacts must be in canonical id order')
    _require(action == 'none' or packages > 0, 'model-only consent must have engine_action=none')
    payload = _keys(d['payload'], _PAYLOAD, 'shared payload allowance')
    for key in _PAYLOAD:
        _bytes(payload[key], key)
    _require(payload['expected_new_bytes'] == expected and payload['retry_headroom_bytes'] <= retry
             and payload['max_payload_bytes'] == expected + payload['retry_headroom_bytes'],
             'shared allowance must disclose exact new payload and bounded separate retries')
    disk = _keys(d['disk'], {'new_bytes', 'temporary_headroom_bytes'}, 'disk/headroom disclosure')
    for key in disk:
        _bytes(disk[key], key)
    return json.loads(_canonical(d))


def acquisition_fingerprint(terms: dict) -> str:
    return hashlib.sha256(b'act-optional-setup/v3/acquisition\0' + _canonical(validate_terms(terms))).hexdigest()


@dataclass(frozen=True)
class ConsentV3:
    consent_id: str
    session: str
    request_id: str
    issued_utc: str
    terms: bytes  # immutable canonical snapshot; callers cannot mutate consent after validation
    acquisition_fingerprint: str

    def to_json(self) -> dict:
        return {'protocol': proto.PROTOCOL, 'version': VERSION, 'consent_id': self.consent_id,
                'session': self.session, 'request_id': self.request_id, 'issued_utc': self.issued_utc,
                'terms': json.loads(self.terms), 'acquisition_fingerprint': self.acquisition_fingerprint}


def encode_consent(consent: ConsentV3) -> bytes:
    _require(type(consent) is ConsentV3, 'v2 is not v3 acquisition authority', proto.UNSUPPORTED_VERSION)
    try:
        issued_at = calendar.timegm(time.strptime(consent.issued_utc, '%Y-%m-%dT%H:%M:%SZ'))
        raw = _canonical(consent.to_json())
    except (ValueError, TypeError, UnicodeError):
        raise proto.ProtocolError(proto.BAD_CONSENT, 'invalid v3 consent serialization') from None
    # Serialization validates the complete shape at its issuance time. Freshness is checked again at spending.
    decode_consent(raw, session=consent.session, request_id=consent.request_id, now=lambda: issued_at)
    return raw


def decode_consent(raw: bytes, *, session: str, request_id: str,
                   now: Callable[[], float] = time.time) -> ConsentV3:
    d = proto.strict_json(raw, max_bytes=MAX_MESSAGE_BYTES)
    _require(d.get('protocol') == proto.PROTOCOL, 'not an optional setup consent', proto.MALFORMED)
    _require(type(d.get('version')) is int and d['version'] == VERSION,
             'explicit v3 consent required; v2 is not upgraded', proto.UNSUPPORTED_VERSION)
    _keys(d, _ENVELOPE, 'v3 consent')
    proto.check_session_freshness(d, session=session, now=now)
    _require(d['request_id'] == request_id, 'v3 consent belongs to another request', proto.BAD_CONSENT)
    _require(type(d['consent_id']) is str and proto._TOKEN.fullmatch(d['consent_id']) is not None,
             'invalid one-time consent token')
    terms = validate_terms(d['terms'])
    _require(_hash(d['acquisition_fingerprint']) and d['acquisition_fingerprint'] == acquisition_fingerprint(terms),
             'forged/mismatched v3 acquisition fingerprint')
    return ConsentV3(d['consent_id'], d['session'], d['request_id'], d['issued_utc'], _canonical(terms),
                     d['acquisition_fingerprint'])


def new_consent(terms: dict, *, session: str, request_id: str,
                now: Callable[[], float] = time.time) -> ConsentV3:
    terms = validate_terms(terms)
    consent = ConsentV3(proto.new_token(), session, request_id, proto.utc_text(now()), _canonical(terms),
                        acquisition_fingerprint(terms))
    return decode_consent(encode_consent(consent), session=session, request_id=request_id, now=now)


def validate_and_spend(raw: bytes, expected_terms: dict, *, session: str, request_id: str,
                       claim: Callable[[str], bool], now: Callable[[], float] = time.time) -> ConsentV3:
    """Validate fresh exact authoritative terms before one-time spending, using proto.claim_consent's callback seam.

    No bounded expansion/refinement in this foundation: any changed term requires new consent. This function does
    not execute acquisition; future callers must also hold the existing lease and revalidate the sealed input set.
    """
    consent = decode_consent(raw, session=session, request_id=request_id, now=now)
    _require(consent.terms == _canonical(validate_terms(expected_terms)), 'v3 plan changed; new consent required',
             proto.CONSENT_STALE)
    _require(claim(consent.consent_id) is True, 'v3 consent already spent', proto.CONSENT_USED)
    return consent
