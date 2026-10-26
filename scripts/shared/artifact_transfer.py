"""Explicit v3 transfer interface; no worker/installer integration.

Accounting measures application-consumed HTTP body bytes, not TLS, headers, DNS or wire traffic.
Reserve an entire response durably BEFORE opening it. Returned bytes become actual spending;
unconfirmed bytes stay reserved after interruption/crash. No refunds, implicit retries or ranges.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import threading
import time
import urllib.request

from shared import optional_setup_protocol as proto
from shared import optional_setup_v3 as v3
from shared.artifact_store import (ArtifactError, ArtifactStore, BLOCK, boundary, canonical, checked_open,
                                   mkdirs, read_small, require, write_once)


class TransferCancelled(ArtifactError):
    """Terminal cancellation; the spent consent cannot be resumed."""


def _apply(state, event, terms):
    """Also used to validate every persisted transition; ledger numbers never confer authority."""
    require(state['status'] == 'open', 'spent/cancelled consent')
    require(set(event) == {'schema', 'version', 'seq', 'previous', 'action', 'artifact', 'bytes'}
            and event['schema'] == 'act-transfer-event' and type(event['version']) is int
            and event['version'] == 1, 'corrupt ledger event schema')
    action, artifact_id, count = event['action'], event['artifact'], event['bytes']
    require(type(count) is int and count >= 0, 'corrupt ledger byte count')
    result = json.loads(canonical(state))
    artifacts = {a['id']: a for a in terms['artifacts']}
    if action in ('finish', 'cancel'):
        require(artifact_id is None and count == 0, 'invalid terminal event')
        result['status'] = 'spent' if action == 'finish' else 'cancelled'
    else:
        require(artifact_id in artifacts, 'unapproved ledger artifact')
        row = artifacts[artifact_id]
        if action == 'reserve':
            require(count == row['size'] and row['source']['kind'] == 'pinned-https',
                    'only a complete approved response can be reserved')
            require(result['actual'][artifact_id] + result['reserved'][artifact_id] + count
                    <= row['max_payload_bytes'], 'per-artifact payload allowance exhausted')
            require(sum(result['actual'].values()) + sum(result['reserved'].values()) + count
                    <= terms['payload']['max_payload_bytes'], 'shared payload allowance exhausted')
            untouched = sum(a['expected_new_bytes'] for a in artifacts.values() if a['id'] != artifact_id
                            and result['actual'][a['id']] + result['reserved'][a['id']] == 0)
            require(sum(result['actual'].values()) + sum(result['reserved'].values()) + count + untouched
                    <= terms['payload']['max_payload_bytes'], 'retry cannot borrow another artifact allowance')
            result['reserved'][artifact_id] += count
        elif action == 'consume':
            require(count <= result['reserved'][artifact_id], 'body exceeds reservation')
            result['reserved'][artifact_id] -= count
            result['actual'][artifact_id] += count
        else:
            raise ArtifactError('unknown ledger action')
    return result


def _initial_state(terms):
    return {'status': 'open', 'actual': {a['id']: 0 for a in terms['artifacts']},
            'reserved': {a['id']: 0 for a in terms['artifacts']}}


class TransferLedger:
    def __init__(self, store: ArtifactStore):
        self.store = store
        self.root = store.root / 'transfers'

    def _read(self, folder):
        raw = read_small(self.store.repo, folder / 'initial.json')
        initial = proto.strict_json(raw, max_bytes=v3.MAX_MESSAGE_BYTES)
        require(set(initial) == {'schema', 'version', 'authorization', 'disclosed_prior_state'}
                and initial['schema'] == 'act-transfer-ledger' and type(initial['version']) is int
                and initial['version'] == 1 and re.fullmatch('[a-f0-9]{64}', initial['disclosed_prior_state']),
                'corrupt transfer ledger')
        auth = initial['authorization']
        # Historical validation at issuance time; this never revives the authorization.
        import calendar
        issued = calendar.timegm(time.strptime(auth['issued_utc'], '%Y-%m-%dT%H:%M:%SZ'))
        consent = v3.decode_consent(canonical(auth), session=auth['session'], request_id=auth['request_id'],
                                    now=lambda: issued)
        require(folder.name == consent.consent_id, 'ledger/consent identity mismatch')
        terms = json.loads(consent.terms)
        state, previous, sequence = _initial_state(terms), hashlib.sha256(raw).hexdigest(), 0
        with boundary(self.store.repo, folder / 'initial.json'):
            names = sorted(p.name for p in folder.iterdir())
        events = [name for name in names if re.fullmatch(r'[0-9]{8}\.json', name)]
        require(all(name == 'initial.json' or name in events for name in names), 'uncertain/corrupt ledger files')
        for name in events:
            require(name == f'{sequence:08d}.json', 'missing/out-of-order ledger event')
            raw = read_small(self.store.repo, folder / name)
            event = proto.strict_json(raw, max_bytes=v3.MAX_MESSAGE_BYTES)
            require(type(event.get('seq')) is int and event['seq'] == sequence
                    and event.get('previous') == previous, 'corrupt ledger chain')
            state = _apply(state, event, terms)
            previous, sequence = hashlib.sha256(raw).hexdigest(), sequence + 1
        return consent, state, sequence, previous

    def prior_state(self):
        """Exact disclosure snapshot, required again at begin; partials have ZERO reuse credit.

        A fresh caller must show these records and its new v3 allowance before confirmation.
        Returning a digest alone to a person does not satisfy that caller's disclosure obligation.
        """
        mkdirs(self.store.repo, self.root)
        history = []
        with boundary(self.store.repo, self.root / 'probe'):
            folders = sorted(self.root.iterdir())
        for folder in folders:
            require(proto._TOKEN.fullmatch(folder.name) is not None, 'unexpected ledger path')
            try:
                consent, state, sequence, previous = self._read(folder)
            except (OSError, KeyError, TypeError, ValueError) as exc:
                raise ArtifactError(f'prior ledger cannot be trusted: {exc}') from None
            history.append({'consent_id': consent.consent_id, 'session': consent.session,
                            'fingerprint': consent.acquisition_fingerprint, 'state': state,
                            'sequence': sequence, 'chain': previous})
        partials = []
        folder = self.store.root / 'incomplete'
        mkdirs(self.store.repo, folder)
        with boundary(self.store.repo, folder / 'probe'):
            paths = sorted(folder.iterdir())
        for path in paths:
            require(re.fullmatch(r'[a-f0-9]{32}\.part', path.name) is not None, 'unexpected partial path')
            with checked_open(self.store.repo, path, 'rb') as handle:
                info = os.fstat(handle.fileno())
                partials.append({'name': path.name, 'size': info.st_size, 'mtime_ns': info.st_mtime_ns,
                                 'verified_reuse_bytes': 0})
        return {'schema': 'act-prior-transfer-state', 'version': 1, 'history': history, 'partials': partials}

    def begin(self, raw, *, session, request_id, disclosed_prior_state, now=time.time):
        require(disclosed_prior_state == self.prior_state(), 'persisted state changed; disclose again')
        for artifact in self.store.catalog.artifacts:
            if artifact['verified_reuse_bytes']:
                self.store.verify(artifact['id'])
        folder = None

        def claim(token):
            nonlocal folder
            folder = self.root / token
            with boundary(self.store.repo, folder):
                try:
                    folder.mkdir()  # durable one-time claim, independent of session/request names
                except FileExistsError:
                    return False
            return True

        consent = v3.validate_and_spend(raw, self.store.catalog.terms, session=session, request_id=request_id,
                                        claim=claim, now=now)
        initial = {'schema': 'act-transfer-ledger', 'version': 1, 'authorization': consent.to_json(),
                   'disclosed_prior_state': hashlib.sha256(canonical(disclosed_prior_state)).hexdigest()}
        write_once(self.store.repo, folder / 'initial.json', canonical(initial))
        return TransferOperation(self, folder, consent)


class TransferOperation:
    """Live operation only. There is deliberately no reopen/resume-old-consent API."""
    def __init__(self, ledger, folder, consent):
        self.ledger, self.folder, self.consent = ledger, folder, consent
        self._lock, self._poisoned = threading.Lock(), False
        recorded, _, self._sequence, self._chain = ledger._read(folder)
        require(recorded == consent, 'ledger authorization identity mismatch')

    def _current(self):
        require(not self._poisoned, 'uncertain ledger; fresh permission required')
        recorded, state, sequence, chain = self.ledger._read(self.folder)
        require(recorded == self.consent and sequence == self._sequence and chain == self._chain,
                'ledger changed/rolled back; fresh permission required')
        return state, sequence, chain

    @property
    def state(self):
        return self._current()[0]

    def _record(self, action, artifact=None, count=0):
        state, seq, previous = self._current()
        event = {'schema': 'act-transfer-event', 'version': 1, 'seq': seq, 'previous': previous,
                 'action': action, 'artifact': artifact, 'bytes': count}
        _apply(state, event, json.loads(self.consent.terms))
        try:
            raw = canonical(event)
            write_once(self.ledger.store.repo, self.folder / f'{seq:08d}.json', raw)
        except BaseException:
            self._poisoned = True
            raise
        self._sequence, self._chain = seq + 1, hashlib.sha256(raw).hexdigest()

    @contextlib.contextmanager
    def exclusive(self):
        require(self._lock.acquire(blocking=False), 'concurrent transfer operation refused')
        try:
            require(self.state['status'] == 'open', 'spent/cancelled consent')
            yield
        finally:
            self._lock.release()

    def finish(self):
        with self.exclusive():
            self._record('finish')


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ArtifactError('redirect refused before following Location')


def https_open(request, *, timeout):
    """No redirects, environment proxies, HTTP fallback or retries. Only acquire constructs requests."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    return opener.open(request, timeout=timeout)


def _header(response, name):
    headers = response.headers
    values = headers.get_all(name) if hasattr(headers, 'get_all') else [
        v for k, v in headers.items() if k.lower() == name.lower()]
    require(not values or len(values) == 1, f'ambiguous {name}')
    return values[0] if values else None


def acquire(store, operation, artifact_id, *, opener=https_open, cancelled=lambda: False):
    """One explicit full GET; retry means another explicit call against the SAME live operation.

    Content-Length frames the body. Reads stop at that exact length, never an unbudgeted EOF probe.
    The injected opener must obey read(n)'s byte bound and must not follow redirects internally.
    Production's opener enforces redirect policy before any subsequent request.
    """
    require(operation.ledger.store is store, 'operation/store identity mismatch')
    artifact = store.catalog.artifact(artifact_id)
    require(artifact['source']['kind'] == 'pinned-https', 'local-only artifact cannot be downloaded')
    url = artifact['source']['url']
    require(re.fullmatch(r'https://[A-Za-z0-9.-]+/[^\s?#\\]+', url) is not None, 'unapproved HTTPS URL')
    with operation.exclusive():
        def check_cancel():
            if cancelled():
                raise TransferCancelled('transfer cancelled; new consent required')

        consumed = 0
        reserved = False
        try:
            check_cancel()
            # Unknown objects/destinations cannot be supplied by a response or caller.
            blob, metadata = store._paths(artifact_id)
            mkdirs(store.repo, blob.parent)
            with boundary(store.repo, blob), boundary(store.repo, metadata):
                require(not blob.exists() and not metadata.exists(), 'destination already exists; validate reuse')
            partial = store.new_partial()
            operation._record('reserve', artifact_id, artifact['size'])
            reserved = True
            check_cancel()
            request = urllib.request.Request(url, headers={'Accept-Encoding': 'identity',
                                                           'User-Agent': 'ACT-Artifact-Transport/1'})
            with opener(request, timeout=15) as response:
                require(type(response.status) is int and response.status == 200 and response.geturl() == url,
                        'HTTP status/source identity mismatch')
                length = _header(response, 'Content-Length')
                require(type(length) is str and re.fullmatch(r'0|[1-9][0-9]*', length) is not None
                        and int(length) == artifact['size'], 'missing/mismatched Content-Length')
                require(_header(response, 'Content-Range') is None, 'range responses unsupported')
                require(_header(response, 'Content-Encoding') in (None, 'identity'), 'unsupported content encoding')
                require(_header(response, 'Transfer-Encoding') is None, 'transfer encoding unsupported')
                with checked_open(store.repo, partial, 'xb') as target:
                    while consumed < artifact['size']:
                        check_cancel()
                        limit = min(BLOCK, artifact['size'] - consumed)
                        block = response.read(limit)
                        require(type(block) is bytes and len(block) <= limit, 'opener violated bounded read contract')
                        require(bool(block), 'interrupted/short response')
                        consumed += len(block)  # count BEFORE cancellation, hashing or disk writes
                        target.write(block)
                    target.flush()
                    os.fsync(target.fileno())
                check_cancel()
            return store.promote(artifact_id, partial)
        except TransferCancelled:
            if reserved and consumed:
                operation._record('consume', artifact_id, consumed)
                consumed = 0
            operation._record('cancel')
            raise
        finally:
            # Even hash failures, disk errors and closed/failed streams pay for every returned byte.
            if reserved and consumed:
                operation._record('consume', artifact_id, consumed)
