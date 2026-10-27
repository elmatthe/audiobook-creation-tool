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
from shared import optional_setup_resource_budget as resources
from shared import venv_layout
from shared.artifact_store import (ArtifactError, ArtifactStore, BLOCK, boundary, canonical, checked_open,
                                   mkdirs, require, write_once)


class TransferCancelled(ArtifactError):
    """Terminal cancellation; the spent consent cannot be resumed."""


class MetadataLimit(ArtifactError, resources.ResourceLimit):
    """Typed non-authorizing producer resource refusal."""


@contextlib.contextmanager
def metadata_budget(budget=None, *, cancelled=lambda: False):
    budget = resources.Budget(cancelled=cancelled) if budget is None else budget
    require(type(budget) is resources.Budget, 'trusted metadata budget required')
    original = budget.cancelled
    budget.cancelled = lambda: original() or cancelled()
    try:
        budget.check()
        yield budget
        budget.check()
    except resources.Cancelled:
        raise TransferCancelled('metadata cancelled; new permission required') from None
    except resources.ResourceLimit as exc:
        raise MetadataLimit(str(exc)) from None
    finally:
        budget.cancelled = original


def metadata_identity(path):
    info = path.stat(follow_symlinks=False)
    require(not venv_layout.is_link(path), 'linked metadata path')
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def metadata_exists(path):
    """Only proved absence is empty; lexists suppresses access/other OS errors."""
    try:
        path.lstat()
        return True
    except FileNotFoundError:
        return False


def read_metadata(repo, path, budget):
    """Charge raw bytes through the SAME protected open; no stat/check-then-open gap."""
    budget.check()
    with checked_open(repo, path, 'rb') as handle:
        before = os.fstat(handle.fileno())
        named_before = metadata_identity(path)
        require(before.st_size <= v3.MAX_MESSAGE_BYTES, 'oversized metadata/ledger')
        budget.ensure_bytes(before.st_size)
        raw = bytearray()
        while True:
            budget.check()
            block = handle.read(min(BLOCK, before.st_size - len(raw) + 1))
            budget.charge(len(block))
            require(len(raw) + len(block) <= before.st_size, 'metadata grew during read')
            if not block:
                break
            raw.extend(block)
        after = os.fstat(handle.fileno())
        # Windows path-stat ctime is creation time; handle-fstat may expose change
        # time after NT publication. Compare each API to itself, not across APIs.
        fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_nlink')
        require(len(raw) == before.st_size
                and all(getattr(before, key) == getattr(after, key) for key in fields)
                and metadata_identity(path) == named_before,
                'metadata changed during read')
    budget.check()
    return bytes(raw)


@contextlib.contextmanager
def _entries(repo, folder, budget, kind, *, missing=False):
    """Bound scandir incrementally, pin ancestry through use, and detect tree changes."""
    with contextlib.ExitStack() as held:
        walked = repo
        for part in folder.relative_to(repo).parts:
            budget.check()
            walked /= part
            held.enter_context(boundary(repo, walked))
            if not metadata_exists(walked):
                require(missing, 'missing ledger directory')
                yield []
                return
            require(walked.is_dir(), 'unexpected ledger directory')
        held.enter_context(boundary(repo, folder / 'probe'))
        before = metadata_identity(folder)
        paths = []
        with os.scandir(folder) as scan:
            for entry in scan:
                budget.check()
                path = folder / entry.name
                if kind == 'events':
                    require(entry.name == 'initial.json' or re.fullmatch(r'[0-9]{8}\.json', entry.name),
                            'uncertain/corrupt ledger files')
                    if entry.name != 'initial.json':
                        budget.take(kind)
                else:
                    budget.take(kind)
                budget.account(entry.name)
                require(not venv_layout.is_link(path), 'linked ledger entry')
                require(entry.is_dir(follow_symlinks=False) if kind == 'operations'
                        else entry.is_file(follow_symlinks=False), 'unexpected ledger entry type')
                paths.append(path)
        budget.check()
        yield sorted(paths)
        budget.check()
        require(metadata_identity(folder) == before, 'ledger directory changed during traversal')


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


def _journal_bounds(terms):
    """Upper bound for canonical events/state written by this live implementation."""
    state = {'status': 'cancelled', 'actual': {}, 'reserved': {}}
    terminal = {'schema': 'act-transfer-event', 'version': 1, 'seq': resources.MAX_EVENTS - 1,
                'previous': 'f' * 64, 'action': 'cancel', 'artifact': None, 'bytes': 0}
    largest = len(canonical(terminal))
    for row in terms['artifacts']:
        for key in ('actual', 'reserved'):
            state[key][row['id']] = row['max_payload_bytes']
        event = {'schema': 'act-transfer-event', 'version': 1, 'seq': resources.MAX_EVENTS - 1,
                 'previous': 'f' * 64, 'action': 'consume', 'artifact': row['id'],
                 'bytes': row['max_payload_bytes']}
        largest = max(largest, len(canonical(event)))
    # Even a legitimate zero-artifact operation must journal a complete terminal event.
    return largest + len('"00000000.json"'), len(canonical(state))


def _workflow_capacity(terms, initial):
    """Pre-spend proof for all allowed full-response retries, accounting and terminality.

    Conservative per-artifact retries may exceed the tighter shared payload cap;
    refusal never lends payload or changes consent. Deadline/OS failure is still
    possible later and must retain the spent uncertain journal.
    """
    with metadata_budget() as budget:
        attempts = 0
        for row in terms['artifacts']:
            if row['expected_new_bytes'] and row['source']['kind'] == 'pinned-https':
                attempts += row['max_payload_bytes'] // row['size']
                budget.ensure('events', 2 * attempts + 1)
        budget.ensure('events', 2 * attempts + 1)
        event_bytes, state_bytes = _journal_bounds(terms)
        encoded_initial = budget.encode(initial)
        if len(encoded_initial) > v3.MAX_MESSAGE_BYTES:
            raise MetadataLimit('initial ledger metadata limit exceeded')
        budget.account('initial.json')
        budget.charge((2 * attempts + 1) * event_bytes + state_bytes)


class TransferLedger:
    def __init__(self, store: ArtifactStore):
        self.store = store
        self.root = store.root / 'transfers'

    def _read(self, folder, *, budget=None, cancelled=lambda: False):
        try:
            with metadata_budget(budget, cancelled=cancelled) as budget:
                with _entries(self.store.repo, folder, budget, 'events') as paths:
                    result = self._replay(folder, paths, budget)
                budget.account(result[1])
                return result
        except (ArtifactError, resources.ResourceLimit):
            raise
        except (KeyError, TypeError, ValueError, OverflowError):
            raise ArtifactError('transfer ledger cannot be trusted') from None

    def _replay(self, folder, paths, budget):
        raw = read_metadata(self.store.repo, folder / 'initial.json', budget)
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
        for path in paths:
            budget.check()
            name = path.name
            if name == 'initial.json':
                continue
            require(name == f'{sequence:08d}.json', 'missing/out-of-order ledger event')
            raw = read_metadata(self.store.repo, path, budget)
            event = proto.strict_json(raw, max_bytes=v3.MAX_MESSAGE_BYTES)
            require(type(event.get('seq')) is int and event['seq'] == sequence
                    and event.get('previous') == previous, 'corrupt ledger chain')
            state = _apply(state, event, terms)
            previous, sequence = hashlib.sha256(raw).hexdigest(), sequence + 1
        return consent, state, sequence, previous

    def prior_state(self, *, budget=None, cancelled=lambda: False):
        """Exact disclosure snapshot, required again at begin; partials have ZERO reuse credit.

        A fresh caller must show these records and its new v3 allowance before confirmation.
        Returning a digest alone to a person does not satisfy that caller's disclosure obligation.
        """
        with metadata_budget(budget, cancelled=cancelled) as budget:
            history, partials = [], []
            with _entries(self.store.repo, self.root, budget, 'operations', missing=True) as folders:
                for folder in folders:
                    budget.check()
                    require(proto._TOKEN.fullmatch(folder.name) is not None, 'unexpected ledger path')
                    try:
                        consent, state, sequence, previous = self._read(folder, budget=budget)
                    except (TransferCancelled, resources.ResourceLimit):
                        raise
                    except (OSError, KeyError, TypeError, ValueError):
                        raise ArtifactError('prior ledger cannot be trusted') from None
                    row = {'consent_id': consent.consent_id, 'session': consent.session,
                           'fingerprint': consent.acquisition_fingerprint, 'state': state,
                           'sequence': sequence, 'chain': previous}
                    budget.account(row)
                    history.append(row)
                with _entries(self.store.repo, self.store.root / 'incomplete', budget,
                              'partials', missing=True) as paths:
                    for path in paths:
                        budget.check()
                        require(re.fullmatch(r'[a-f0-9]{32}\.part', path.name), 'unexpected partial path')
                        with checked_open(self.store.repo, path, 'rb') as handle:
                            info = os.fstat(handle.fileno())
                            row = {'name': path.name, 'size': info.st_size, 'mtime_ns': info.st_mtime_ns,
                                   'verified_reuse_bytes': 0}
                            budget.account(row)
                            after = os.fstat(handle.fileno())
                            require(all(getattr(info, key) == getattr(after, key) for key in (
                                'st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_nlink')),
                                'partial metadata changed during traversal')
                            partials.append(row)
            return {'schema': 'act-prior-transfer-state', 'version': 1, 'history': history, 'partials': partials}

    def begin(self, raw, *, session, request_id, disclosed_prior_state, now=time.time,
              budget=None, cancelled=lambda: False):
        with metadata_budget(budget, cancelled=cancelled) as budget:
            require(disclosed_prior_state == self.prior_state(budget=budget, cancelled=cancelled),
                    'persisted state changed; disclose again')
            # Decode without claiming first: prove the known workflow can be journaled.
            consent = v3.decode_consent(raw, session=session, request_id=request_id, now=now)
            initial = {'schema': 'act-transfer-ledger', 'version': 1, 'authorization': consent.to_json(),
                       'disclosed_prior_state': hashlib.sha256(budget.encode(disclosed_prior_state)).hexdigest()}
            _workflow_capacity(self.store.catalog.terms, initial)
            for artifact in self.store.catalog.artifacts:
                if artifact['verified_reuse_bytes']:
                    with budget.content():
                        self.store.verify(artifact['id'])
                    budget.check()
        folder = None

        def claim(token):
            nonlocal folder
            if cancelled():
                raise TransferCancelled('metadata cancelled; no consent claimed')
            mkdirs(self.store.repo, self.root)
            folder = self.root / token
            with boundary(self.store.repo, folder):
                try:
                    folder.mkdir()  # durable one-time claim, independent of session/request names
                except FileExistsError:
                    return False
            return True

        consent = v3.validate_and_spend(raw, self.store.catalog.terms, session=session, request_id=request_id,
                                        claim=claim, now=now)
        write_once(self.store.repo, folder / 'initial.json', canonical(initial))
        return TransferOperation(self, folder, consent)


class TransferOperation:
    """Live operation only. There is deliberately no reopen/resume-old-consent API."""
    def __init__(self, ledger, folder, consent):
        self.ledger, self.folder, self.consent = ledger, folder, consent
        self._lock, self._poisoned = threading.Lock(), False
        recorded, _, self._sequence, self._chain = ledger._read(folder)
        require(recorded == consent, 'ledger authorization identity mismatch')

    def _current(self, *, budget=None):
        require(not self._poisoned, 'uncertain ledger; fresh permission required')
        recorded, state, sequence, chain = self.ledger._read(self.folder, budget=budget)
        require(recorded == self.consent and sequence == self._sequence and chain == self._chain,
                'ledger changed/rolled back; fresh permission required')
        return state, sequence, chain

    def _capacity(self, action, *, budget=None):
        """Reserve -> consume -> terminal must remain replayable, before any response."""
        with metadata_budget(budget) as budget:
            state, seq, previous = self._current(budget=budget)
            slots = 3 if action == 'reserve' else 2 if action == 'consume' else 1
            budget.ensure('events', slots)
            event_bytes, state_bytes = _journal_bounds(json.loads(self.consent.terms))
            budget.ensure_bytes(slots * event_bytes + state_bytes)
            return state, seq, previous

    @property
    def state(self):
        return self._current()[0]

    def _record(self, action, artifact=None, count=0):
        with metadata_budget() as budget:
            state, seq, previous = self._capacity(action, budget=budget)
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
            operation._capacity('reserve')
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
