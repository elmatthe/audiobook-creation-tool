"""Bounded v3 disclosure/control codecs. No I/O, planner, consent creation or spending.

The controller must retain the issued Disclosure and supply it independently at
confirmation admission. Public digests in received JSON alone confer no trust.
Decoded confirmation is only an immutable binding: locked fresh authority and
one-time spending remain separate, unimplemented production integration.
"""
from __future__ import annotations

import calendar
import hashlib
import json
import math
import re
import time
from dataclasses import dataclass

from shared import optional_setup_protocol as proto
from shared import optional_setup_v3 as v3

VERSION = proto.ACQUISITION_PROTOCOL_VERSION
DISCLOSURE_SCHEMA = 'act-optional-setup-disclosure'
DISCLOSURE_VERSION = 1
MAX_CONTROL_BYTES = 64 * 1024
MAX_DISCLOSURE_BYTES = 256 * 1024
MAX_CONSENT_BYTES = v3.MAX_MESSAGE_BYTES
MAX_DEPTH = 24
MAX_NODES = 65_536
RESOURCE_LIMIT = 'wire-resource-limit'
_COMMON = {'protocol', 'version', 'request_id', 'session', 'issued_utc', 'action', 'components',
           'engine_action', 'plan_id', 'planning_request_id', 'options'}
_PLANNING = _COMMON | {'intended_request_id'}
_CONFIRMATION = _COMMON | {'plan_sha256', 'consent_sha256'}
_DISCLOSURE = {'schema', 'version', 'plan_id', 'planning_request_id', 'intended_request_id',
               'session', 'issued_utc', 'selected', 'engine_action', 'document'}
_RESULT = (_COMMON - {'options'}) | {'intended_request_id', 'plan_sha256', 'confirmable', 'verified'}
_PLAN_REQUIRED = {'components', 'engine_readiness', 'terms', 'prior_state', 'reasons', 'operations'}


def _require(condition, message, code=proto.MALFORMED):
    if not condition:
        raise proto.ProtocolError(code, message)


def _keys(value, keys, label):
    _require(type(value) is dict and set(value) == keys, f'{label} requires exactly {sorted(keys)}')


def _token(value, label):
    _require(type(value) is str and proto._TOKEN.fullmatch(value) is not None, f'invalid {label}')


def _digest(value):
    _require(type(value) is str and proto._FINGERPRINT.fullmatch(value) is not None, 'invalid SHA-256')


def _count(value, label):
    _require(type(value) is int and 0 <= value <= 2**63 - 1, 'invalid ' + label)


def _preflight(text):
    """Count value tokens/depth before json.loads allocates the object graph.

    Strings are scanned with JSON escape boundaries; keys do not count as value
    nodes. This is an admission scan, not a second JSON grammar/parser.
    json.loads still rejects every invalid grammar and duplicate key.
    """
    index = depth = nodes = 0
    while index < len(text):
        char = text[index]
        if char.isspace() or char in ',:':
            index += 1
            continue
        if char in '}]':
            depth -= 1
            index += 1
            continue
        value_depth = depth + 1
        if char == '"':
            index += 1
            while index < len(text):
                if text[index] == '\\':
                    index += 2
                elif text[index] == '"':
                    index += 1
                    break
                else:
                    index += 1
            after = index
            while after < len(text) and text[after].isspace():
                after += 1
            if after < len(text) and text[after] == ':':
                continue
        elif char in '{[':
            depth += 1
            index += 1
        else:
            index += 1
            while index < len(text) and text[index] not in ' \t\r\n,]}:{["':
                index += 1
        nodes += 1
        _require(nodes <= MAX_NODES and value_depth <= MAX_DEPTH,
                 'JSON value node/depth limit exceeded', RESOURCE_LIMIT)


def _walk(value):
    # Also bounds trusted Python encoder inputs before serialization. No cycles
    # or hostile object methods are followed: only exact JSON built-in types.
    stack, nodes = [(value, 1)], 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        _require(nodes <= MAX_NODES and depth <= MAX_DEPTH, 'JSON value node/depth limit exceeded', RESOURCE_LIMIT)
        if type(item) in (str, dict):
            strings = [item] if type(item) is str else item.keys()
            for string in strings:
                _require(type(string) is str and len(string) <= MAX_DISCLOSURE_BYTES,
                         'invalid or excessive JSON string', RESOURCE_LIMIT)
                try:
                    string.encode('utf-8')
                except UnicodeError:
                    raise proto.ProtocolError(proto.MALFORMED, 'invalid Unicode scalar in JSON') from None
        if type(item) in (dict, list):
            _require(len(item) <= MAX_NODES - nodes, 'JSON value node limit exceeded', RESOURCE_LIMIT)
            children = item.values() if type(item) is dict else item
            stack.extend((child, depth + 1) for child in children)
        else:
            _require(type(item) in (str, int, float, bool, type(None)), 'not a JSON value')
            _require(type(item) is not float or math.isfinite(item), 'nonfinite JSON number')


def _canonical(value, limit):
    _walk(value)
    chunks, size = [], 0
    try:
        for chunk in json.JSONEncoder(sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                                      allow_nan=False).iterencode(value):
            size += len(chunk)
            _require(size <= limit, 'complete document exceeds wire cap; new reviewed design required', RESOURCE_LIMIT)
            chunks.append(chunk)
        return ''.join(chunks).encode('ascii')
    except (ValueError, TypeError, RecursionError):
        raise proto.ProtocolError(proto.MALFORMED, 'invalid JSON serialization') from None


def _load(raw, limit):
    _require(type(raw) is bytes, 'wire document must be bytes')
    _require(len(raw) <= limit, 'complete document exceeds wire cap; new reviewed design required', RESOURCE_LIMIT)
    try:
        text = raw.decode('utf-8')
    except UnicodeError:
        raise proto.ProtocolError(proto.MALFORMED, 'invalid UTF-8') from None
    _preflight(text)
    value = proto.strict_json(raw, max_bytes=limit)
    _walk(value)  # rejects exponent overflow, escaped surrogates and excessive strings too
    return value


def _fresh(d, *, session, request_id, now):
    proto.check_session_freshness({**d, 'request_id': request_id}, session=session, now=now)
    # strptime accepts leap seconds and normalizes some invalid calendar dates.
    # Keep the existing age/session contract, adding exact calendar round-trip.
    issued = d['issued_utc']
    stamp = calendar.timegm(time.strptime(issued, '%Y-%m-%dT%H:%M:%SZ'))
    _require(proto.utc_text(stamp) == issued, 'issued_utc is not an exact calendar timestamp')


def _control(raw, keys, action, *, session, request_id, now):
    d = _load(raw, MAX_CONTROL_BYTES)
    _require(d.get('protocol') == proto.PROTOCOL, 'unknown control protocol')
    _require(type(d.get('version')) is int and d['version'] == VERSION,
             'explicit v3 wire protocol required', proto.UNSUPPORTED_VERSION)
    _keys(d, keys, action)
    _require(d['action'] == action, 'wrong control action')
    _fresh(d, session=session, request_id=d['request_id'], now=now)
    _token(request_id, 'expected request ID')
    _require(d['request_id'] == request_id, 'unexpected request ID')
    for key in ('plan_id', 'planning_request_id'):
        _token(d[key], key)
    proto._wire_selection(d['components'], allow_empty=False)
    _require(type(d['engine_action']) is str and d['engine_action'] in v3.ENGINE_ACTIONS, 'unknown engine action')
    if 'options' in keys:
        _keys(d['options'], set(), 'options')
    return d


@dataclass(frozen=True)
class PlanningRequest:
    raw: bytes

    def to_json(self):
        return _load(self.raw, MAX_CONTROL_BYTES)


@dataclass(frozen=True)
class Disclosure:
    raw: bytes  # exact original canonical displayed envelope, including unknown Plan metadata
    document: bytes  # exact original canonical Plan, never reconstructed from consent

    def to_json(self):
        return _load(self.raw, MAX_DISCLOSURE_BYTES)


@dataclass(frozen=True)
class Confirmation:
    raw: bytes
    disclosure: Disclosure
    raw_consent: bytes
    consent: v3.ConsentV3


def decode_planning_request(raw, *, session, request_id, now=time.time):
    d = _control(raw, _PLANNING, 'plan', session=session, request_id=request_id, now=now)
    _token(d['intended_request_id'], 'intended request ID')
    _require(d['planning_request_id'] == request_id != d['intended_request_id'], 'P and I must be distinct and bound')
    return PlanningRequest(raw)


def encode_planning_request(*, request_id, intended_request_id, session, plan_id, components,
                            engine_action, issued_utc, now=time.time):
    raw = _canonical(dict(protocol=proto.PROTOCOL, version=VERSION, request_id=request_id, session=session,
        issued_utc=issued_utc, action='plan', components=components, engine_action=engine_action, plan_id=plan_id,
        planning_request_id=request_id, intended_request_id=intended_request_id, options={}), MAX_CONTROL_BYTES)
    return decode_planning_request(raw, session=session, request_id=request_id, now=now).raw


def _plan(document, selected, action):
    _require(type(document) is dict and _PLAN_REQUIRED <= set(document), 'incomplete original Plan')
    rows = document['components']
    _require(type(rows) is list, 'Plan components must be an array')
    for row in rows:
        _keys(row, {'id', 'readiness', 'scope'}, 'Plan component')
        _require(type(row['readiness']) is str and row['readiness'] in proto.READINESS, 'unknown readiness')
        _require(row['scope'] == proto.acquisition_scope(row['readiness']), 'scope differs from readiness')
    _require(proto._wire_selection([r['id'] for r in rows], allow_empty=False) == tuple(selected),
             'Plan selection differs from displayed selection')
    _require(type(document['engine_readiness']) is str and document['engine_readiness'] in proto.READINESS,
             'unknown engine readiness')
    _keys(document['operations'], set(selected), 'Plan operations')
    _require(document['operations'] == {r['id']: r['scope'] or 'none' for r in rows}, 'unrecognized Plan operations')
    _require(type(document['reasons']) is list and all(type(r) is str and len(r) <= 4096
             for r in document['reasons']), 'invalid Plan reasons')
    terms = document['terms']
    if terms is not None:
        terms = v3.validate_terms(terms)  # no weaker parallel terms/consumer validator
        _require(terms['components'] == rows and terms['engine_action'] == action
                 and terms['engine_readiness'] == document['engine_readiness'], 'inner/outer Plan terms differ')
    prior = document['prior_state']
    if prior is not None:
        _keys(prior, {'schema', 'version', 'history', 'partials'}, 'prior transfer state')
        _require(prior['schema'] == 'act-prior-transfer-state' and type(prior['version']) is int
                 and prior['version'] == 1 and type(prior['history']) is list and type(prior['partials']) is list,
                 'unknown prior transfer state schema')
        for entry in prior['history']:
            _keys(entry, {'consent_id', 'session', 'fingerprint', 'state', 'sequence', 'chain'}, 'prior operation')
            _token(entry['consent_id'], 'historical consent ID')
            _token(entry['session'], 'historical session')
            _digest(entry['fingerprint'])
            _digest(entry['chain'])
            _count(entry['sequence'], 'historical sequence')
            state = entry['state']
            _keys(state, {'status', 'actual', 'reserved'}, 'historical transfer state')
            _require(type(state['status']) is str and state['status'] in ('open', 'spent', 'cancelled'),
                     'unknown historical transfer status')
            for name in ('actual', 'reserved'):
                _require(type(state[name]) is dict, 'invalid historical byte map')
                for artifact, count in state[name].items():
                    _require(v3._TOKEN.fullmatch(artifact) is not None, 'invalid historical artifact ID')
                    _count(count, 'historical bytes')
            _require(set(state['actual']) == set(state['reserved']), 'incomplete historical byte maps')
        for partial in prior['partials']:
            _keys(partial, {'name', 'size', 'mtime_ns', 'verified_reuse_bytes'}, 'prior partial')
            _require(type(partial['name']) is str and re.fullmatch(r'[a-f0-9]{32}\.part', partial['name']) is not None,
                     'invalid historical partial name')
            for key in ('size', 'mtime_ns', 'verified_reuse_bytes'):
                _count(partial[key], 'partial ' + key)
            _require(partial['verified_reuse_bytes'] == 0, 'partial history grants no reuse credit')
    if 'installed_disk_bounds' in document:
        bounds = document['installed_disk_bounds']
        _keys(bounds, {'engine', 'spacy'}, 'installed disk bounds')
        for bound in bounds.values():
            _keys(bound, {'bytes', 'basis'}, 'installed disk bound')
            _require(type(bound['bytes']) is int and 0 <= bound['bytes'] <= 2**63 - 1
                     and bound['basis'] == 'approximate', 'invalid installed disk bound')
    if 'engine_identity' in document:
        identity = document['engine_identity']
        _keys(identity, {'parent', 'parent_cfg', 'canonical_exists', 'entries', 'record', 'selected_canonical', 'path'},
              'engine identity')
        _digest(identity['parent_cfg'])
        _require(type(identity['path']) is str and 0 < len(identity['path']) <= 4096
                 and type(identity['record']) is dict and type(identity['entries']) is list
                 and type(identity['canonical_exists']) is bool and type(identity['selected_canonical']) is bool,
                 'invalid engine identity')
        def stat_identity(values, size):
            _require(type(values) is list and len(values) == size
                     and all(type(n) is int and 0 <= n < 2**128 for n in values), 'invalid engine stat identity')
        stat_identity(identity['parent'], 2)
        for entry in identity['entries']:
            _require(type(entry) is list and len(entry) == 2 and type(entry[0]) is str
                     and 0 < len(entry[0]) <= 4096, 'invalid engine inventory entry')
            stat_identity(entry[1], 5)
    # The Plan is an opaque retained authority snapshot beyond these existing
    # interfaces. Preserve EVERY extra field/history/identity entry, never use
    # extensions as commands or silently project the document onto known keys.


def _confirmable(d):
    doc = d['document']
    return (doc['terms'] is not None and doc['prior_state'] is not None and not doc['reasons']
            and 'installed_disk_bounds' in doc
            and all(r['readiness'] in (proto.READY, proto.MISSING, proto.DAMAGED) for r in doc['components'])
            and any(r['scope'] in proto.SCOPES for r in doc['components'])
            and (d['engine_action'] == 'none' or type(doc.get('engine_identity')) is dict))


def decode_disclosure(raw, *, planning, session, now=time.time):
    _require(type(planning) is PlanningRequest, 'original planning request required')
    p = planning.to_json()
    decode_planning_request(planning.raw, session=session, request_id=p.get('request_id'), now=now)
    d = _load(raw, MAX_DISCLOSURE_BYTES)
    _keys(d, _DISCLOSURE, 'disclosure')
    _require(d['schema'] == DISCLOSURE_SCHEMA and type(d['version']) is int
             and d['version'] == DISCLOSURE_VERSION, 'unknown disclosure schema', proto.UNSUPPORTED_VERSION)
    _fresh(d, session=session, request_id=d['planning_request_id'], now=now)
    for key in ('plan_id', 'planning_request_id', 'intended_request_id', 'engine_action'):
        _require(d[key] == p[key], 'disclosure differs from original planning request: ' + key)
    _require(d['selected'] == p['components'], 'disclosure selection differs from original request')
    _plan(d['document'], d['selected'], d['engine_action'])
    _require(raw == _canonical(d, MAX_DISCLOSURE_BYTES), 'original disclosure must be canonical bytes')
    return Disclosure(raw, _canonical(d['document'], MAX_DISCLOSURE_BYTES))


def encode_disclosure(document, *, planning, issued_utc, now=time.time):
    _require(type(planning) is PlanningRequest, 'original planning request required')
    doc = _load(document, MAX_DISCLOSURE_BYTES)
    _require(document == _canonical(doc, MAX_DISCLOSURE_BYTES), 'original Plan must be canonical bytes')
    p = planning.to_json()
    decode_planning_request(planning.raw, session=p.get('session'), request_id=p.get('request_id'), now=now)
    raw = _canonical(dict(schema=DISCLOSURE_SCHEMA, version=DISCLOSURE_VERSION, plan_id=p['plan_id'],
        planning_request_id=p['request_id'], intended_request_id=p['intended_request_id'], session=p['session'],
        issued_utc=issued_utc, selected=p['components'], engine_action=p['engine_action'], document=doc),
        MAX_DISCLOSURE_BYTES)
    return decode_disclosure(raw, planning=planning, session=p['session'], now=now).raw


def _retained(disclosure, *, session, now):
    _require(type(disclosure) is Disclosure, 'independently retained original disclosure required')
    d = _load(disclosure.raw, MAX_DISCLOSURE_BYTES)
    _keys(d, _DISCLOSURE, 'retained disclosure')
    p = encode_planning_request(request_id=d['planning_request_id'], intended_request_id=d['intended_request_id'],
        session=session, plan_id=d['plan_id'], components=d['selected'], engine_action=d['engine_action'],
        issued_utc=d['issued_utc'], now=now)
    checked = decode_disclosure(disclosure.raw, planning=PlanningRequest(p), session=session, now=now)
    _require(checked.document == disclosure.document, 'retained Plan bytes differ from retained envelope')
    return d


def decode_confirmation_request(raw, *, raw_disclosure, raw_consent, expected_disclosure,
                                session, request_id, now=time.time):
    d = _control(raw, _CONFIRMATION, 'confirm', session=session, request_id=request_id, now=now)
    original = _retained(expected_disclosure, session=session, now=now)
    _require(type(raw_disclosure) is bytes and raw_disclosure == expected_disclosure.raw,
             'missing/changed original displayed disclosure', proto.CONSENT_STALE)
    _require(_confirmable(original), 'read-only Plan cannot authorize confirmation', proto.BAD_CONSENT)
    _require(d['request_id'] == original['intended_request_id'] != original['planning_request_id'], 'wrong intended I')
    for key in ('planning_request_id', 'plan_id', 'engine_action'):
        _require(d[key] == original[key], 'confirmation differs from displayed binding: ' + key)
    _require(d['components'] == original['selected'], 'confirmation selection differs from display')
    _require(type(raw_consent) is bytes, 'separate raw consent required')
    _require(len(raw_consent) <= MAX_CONSENT_BYTES, 'raw consent exceeds wire cap', RESOURCE_LIMIT)
    for key, data in (('plan_sha256', raw_disclosure), ('consent_sha256', raw_consent)):
        _digest(d[key])
        _require(type(data) is bytes and d[key] == hashlib.sha256(data).hexdigest(), 'document digest mismatch')
    _load(raw_consent, MAX_CONSENT_BYTES)
    consent = v3.decode_consent(raw_consent, session=session, request_id=request_id, now=now)
    _fresh(consent.to_json(), session=session, request_id=request_id, now=now)
    _require(consent.terms == _canonical(original['document']['terms'], MAX_CONSENT_BYTES),
             'consent differs from original displayed terms', proto.CONSENT_STALE)
    return Confirmation(raw, expected_disclosure, raw_consent, consent)


def encode_confirmation_request(*, disclosure, raw_consent, issued_utc, now=time.time):
    _require(type(disclosure) is Disclosure, 'original disclosure required')
    d = disclosure.to_json()
    _keys(d, _DISCLOSURE, 'disclosure')
    _require(type(raw_consent) is bytes and len(raw_consent) <= MAX_CONSENT_BYTES,
             'missing or excessive raw consent', RESOURCE_LIMIT)
    raw = _canonical(dict(protocol=proto.PROTOCOL, version=VERSION, request_id=d['intended_request_id'],
        session=d['session'], issued_utc=issued_utc, action='confirm', components=d['selected'],
        engine_action=d['engine_action'], plan_id=d['plan_id'], planning_request_id=d['planning_request_id'],
        plan_sha256=hashlib.sha256(disclosure.raw).hexdigest(), consent_sha256=hashlib.sha256(raw_consent).hexdigest(),
        options={}), MAX_CONTROL_BYTES)
    return decode_confirmation_request(raw, raw_disclosure=disclosure.raw, raw_consent=raw_consent,
        expected_disclosure=disclosure, session=d['session'], request_id=d['intended_request_id'], now=now).raw


def encode_planning_result(*, disclosure, issued_utc, now=time.time):
    """Small read-only result reference; verified is ALWAYS empty, even for ready terms."""
    _require(type(disclosure) is Disclosure, 'original disclosure required')
    d = disclosure.to_json()
    _retained(disclosure, session=d.get('session'), now=now)
    raw = _canonical(dict(protocol=proto.PROTOCOL, version=VERSION, action='plan-result',
        request_id=d['planning_request_id'], planning_request_id=d['planning_request_id'],
        intended_request_id=d['intended_request_id'], session=d['session'], issued_utc=issued_utc,
        plan_id=d['plan_id'], components=d['selected'], engine_action=d['engine_action'],
        plan_sha256=hashlib.sha256(disclosure.raw).hexdigest(), confirmable=_confirmable(d), verified=[]),
        MAX_CONTROL_BYTES)
    decode_planning_result(raw, expected_disclosure=disclosure, session=d['session'],
                           request_id=d['planning_request_id'], now=now)
    return raw


def decode_planning_result(raw, *, expected_disclosure, session, request_id, now=time.time):
    d = _control(raw, _RESULT, 'plan-result', session=session, request_id=request_id, now=now)
    original = _retained(expected_disclosure, session=session, now=now)
    for key in ('planning_request_id', 'intended_request_id', 'plan_id', 'engine_action'):
        _require(d[key] == original[key], 'planning result binding differs: ' + key)
    _require(request_id == original['planning_request_id'] and d['components'] == original['selected'],
             'wrong planning result request/selection')
    _digest(d['plan_sha256'])
    _require(d['plan_sha256'] == hashlib.sha256(expected_disclosure.raw).hexdigest(), 'planning result digest differs')
    _require(type(d['confirmable']) is bool and d['confirmable'] == _confirmable(original)
             and type(d['verified']) is list and d['verified'] == [], 'planning cannot prove installed readiness')
    return d  # independent JSON copy, carries no execution authority
