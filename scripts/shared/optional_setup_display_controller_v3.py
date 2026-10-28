"""Shared presentation lifecycle; no launch, consent or acquisition.

The caller independently supplies the issued request and an existing approved
PlanningRun. A separately bound trusted TEST callback receives the complete
immutable payload and returns exactly True to acknowledge that software handoff.
This is not evidence that a human saw a screen. Retention is a further explicit
transition, and strict readback always uses those retained bytes. Python code in
this process is trusted; private attributes are not an adversarial-code sandbox.
"""
from __future__ import annotations

import math
import threading
import time
import weakref
from dataclasses import dataclass

from shared import optional_setup_exchange_v3 as exchange
from shared import optional_setup_planning_bridge_v3 as bridge
from shared import optional_setup_protocol as proto
from shared import optional_setup_supervisor_v3 as supervisor
from shared import optional_setup_wire_v3 as wire

_ISSUE_LOCK = threading.Lock()
_USED_IDS = set()  # bounded, process-local test issuance; never durable consent
_ACTIVE = weakref.WeakValueDictionary()
_CONSTRUCTION = object()


class ControllerError(ValueError):
    """Stable bounded controller code; never worker exception text."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class Presentation:
    raw_disclosure: bytes
    document: bytes

    def to_json(self):
        """Lossless complete envelope/Plan model, as a detached JSON copy.

        No field selection, history hashes in place of history, or truncation.
        Mutable view copies cannot change the underlying immutable snapshot.
        """
        return wire._load(self.raw_disclosure, wire.MAX_DISCLOSURE_BYTES)


@dataclass(frozen=True, slots=True)
class RetainedOriginal:
    """Archival read-only bytes, never execution permission (even while fresh)."""
    planning: wire.PlanningRequest
    disclosure: wire.Disclosure
    raw_result: bytes


class DisplayLifecycle:
    def __init__(self, token):
        if token is not _CONSTRUCTION:
            raise ControllerError('disposable-factory-required')

    @classmethod
    def _bind(cls, *, run, planning, session, display_adapter, now=time.time):
        """Common state only. Concrete factories independently restrict issuers."""
        if type(planning) is not wire.PlanningRequest or not callable(display_adapter) or not callable(now):
            raise ControllerError('trusted-input-required')
        self = cls(_CONSTRUCTION)
        self._lock = threading.Lock()
        self._state, self._error = 'request-issued', None
        self._clock, self._adapter, self._run = now, display_adapter, run
        self._session, self._context, self._repo = session, run.context, run.context.root / 'app'
        self._planning = wire.PlanningRequest(planning.raw)
        self._candidate = self._outcome = self._payload = self._retained = None
        self._displaying = False
        sample = self._sample()
        with self._lock:
            self._validate(sample)
        p = self._planning.to_json()
        with _ISSUE_LOCK:
            if p['request_id'] in _USED_IDS or p['intended_request_id'] in _USED_IDS:
                raise ControllerError('request-id-reused')
            if len(_USED_IDS) >= 4096:
                raise ControllerError('test-issuance-limit')
            _USED_IDS.update((p['request_id'], p['intended_request_id']))
            previous = _ACTIVE.get(session)
            if previous is not None:
                previous.invalidate('superseded')
            _ACTIVE[session] = self
        return self

    def _context_is_trusted(self):
        raise NotImplementedError('concrete issuer required')

    @property
    def state(self):
        with self._lock:
            return self._state

    @property
    def error_code(self):
        with self._lock:
            return self._error

    def _fail(self, code):
        # Called under _lock. First failure is sticky; no invalidated revival.
        if self._state != 'invalidated':
            self._state, self._error = 'invalidated', code
            self._retained = None
        raise ControllerError(self._error)

    def _require_live(self):
        if self._state == 'invalidated':
            raise ControllerError(self._error)

    def _sample(self):
        # No controller lock across external calls, including the test clock.
        try:
            stamp = self._clock()
            if type(stamp) not in (int, float) or not math.isfinite(stamp):
                raise ValueError
            return stamp, self._run.result(), self._run.candidate()
        except BaseException:
            with self._lock:
                self._fail('observation-failed')

    def _validate(self, sample):
        self._require_live()
        stamp, outcome, candidate = sample
        run = self._run
        if (run.context is not self._context or run.repo != self._repo or run.session != self._session
                or type(run.planning) is not wire.PlanningRequest
                or run.planning.raw != self._planning.raw
                or not self._context_is_trusted()):
            self._fail('request-changed')
        try:
            p = self._planning.to_json()
            wire.decode_planning_request(self._planning.raw, session=self._session,
                request_id=p.get('request_id'), now=lambda: stamp)
            if self._candidate is not None:
                if outcome is not self._outcome or candidate is not self._candidate:
                    self._fail('candidate-replaced')
                shown = wire.decode_disclosure(self._candidate.raw_disclosure,
                    planning=self._planning, session=self._session, now=lambda: stamp)
                wire.decode_planning_result(self._candidate.raw_result, expected_disclosure=shown,
                    session=self._session, request_id=p['request_id'], now=lambda: stamp)
                if self._state == 'original-retained':
                    original = self._retained
                    if (type(original) is not RetainedOriginal or original.planning != self._planning
                            or original.disclosure.raw != self._payload.raw_disclosure
                            or original.disclosure.document != self._payload.document
                            or original.raw_result != self._candidate.raw_result):
                        self._fail('original-changed')
        except proto.ProtocolError as error:
            self._fail('presentation-expired' if error.code == proto.STALE_REQUEST else 'candidate-invalid')

    def admit_candidate(self):
        sample = self._sample()
        with self._lock:
            self._validate(sample)
            if self._state != 'request-issued':
                self._fail('duplicate-candidate')
            stamp, outcome, candidate = sample
            if outcome is None and candidate is None:
                raise ControllerError('candidate-not-ready')
            if type(outcome) is not supervisor.Outcome or not outcome.accepted:
                self._fail('worker-cancelled' if outcome is not None
                    and outcome.state == 'cancelled' else 'worker-failed')
            if (type(candidate) is not exchange.UntrustedPlanningCandidate
                    or candidate.raw_result != outcome.raw_result):
                self._fail('candidate-invalid')
            try:
                shown = wire.decode_disclosure(candidate.raw_disclosure,
                    planning=self._planning, session=self._session, now=lambda: stamp)
                wire.decode_planning_result(candidate.raw_result, expected_disclosure=shown,
                    session=self._session, request_id=self._planning.to_json()['request_id'], now=lambda: stamp)
            except proto.ProtocolError as error:
                self._fail('presentation-expired' if error.code == proto.STALE_REQUEST else 'candidate-invalid')
            self._candidate, self._outcome = candidate, outcome
            self._state = 'candidate-admitted'

    def prepare_presentation(self):
        sample = self._sample()
        with self._lock:
            self._validate(sample)
            if self._state != 'candidate-admitted':
                self._fail('candidate-required')
            shown = wire.decode_disclosure(self._candidate.raw_disclosure,
                planning=self._planning, session=self._session, now=lambda: sample[0])
            self._payload = Presentation(shown.raw, shown.document)
            self._state = 'presentation-pending'
            return self._payload

    def acknowledge_display(self, payload):
        """Explicit TEST handoff, never invoked by decoding or view construction.

        Concurrent/reentrant invalidation wins before acknowledgement commits.
        Duplicate attempts invalidate rather than presenting two originals.
        """
        sample = self._sample()
        with self._lock:
            self._validate(sample)
            if self._displaying or self._state in ('display-acknowledged', 'original-retained'):
                self._fail('duplicate-acknowledgment')
            if self._state != 'presentation-pending':
                self._fail('presentation-required')
            if payload is not self._payload:
                self._fail('display-payload-changed')
            self._displaying = True
        try:
            acknowledged = self._adapter(payload)
        except BaseException:
            with self._lock:
                self._fail('display-failed')
        sample = self._sample()
        with self._lock:
            self._validate(sample)
            if acknowledged is not True:
                self._fail('display-failed')
            self._displaying = False
            self._state = 'display-acknowledged'

    def retain_original(self):
        sample = self._sample()
        with self._lock:
            self._validate(sample)
            if self._state == 'original-retained':
                return self._retained
            if self._state != 'display-acknowledged':
                self._fail('display-required')
            # Original comes ONLY from the issued presentation, never a file.
            shown = wire.decode_disclosure(self._payload.raw_disclosure,
                planning=self._planning, session=self._session, now=lambda: sample[0])
            if shown.document != self._payload.document or shown.raw != self._candidate.raw_disclosure:
                self._fail('original-changed')
            self._retained = RetainedOriginal(self._planning, shown, self._candidate.raw_result)
            self._state = 'original-retained'
            return self._retained

    def readback(self):
        sample = self._sample()
        with self._lock:
            self._validate(sample)
            if self._state != 'original-retained':
                self._fail('original-required')
            original = self._retained
        try:
            checked = exchange.read_planning_exchange(self._repo, planning=self._planning,
                expected_disclosure=original.disclosure, session=self._session, now=self._clock)
        except BaseException as error:
            with self._lock:
                self._fail('presentation-expired' if isinstance(error, proto.ProtocolError)
                    and error.code == proto.STALE_REQUEST else 'original-changed')
        sample = self._sample()
        with self._lock:
            self._validate(sample)
            if self._retained is not original or checked.raw_result != original.raw_result:
                self._fail('original-changed')
            return checked

    def invalidate(self, reason='cancelled'):
        if reason not in ('cancelled', 'superseded', 'presentation-interrupted', 'retention-timeout'):
            raise ControllerError('unknown-invalidation')
        with self._lock:
            if self._state != 'invalidated':
                self._state, self._error = 'invalidated', reason
                self._retained = None

    def cancel(self):
        self.invalidate('cancelled')
        self._run.cancel()  # native coordination stays with the approved bridge


class DisposableDisplayController(DisplayLifecycle):
    @classmethod
    def for_test(cls, *, run, planning, session, display_adapter, now=time.time):
        """Unchanged TEST-only issuer and synchronous software callback contract."""
        if (type(run) is not bridge.PlanningRun
                or type(run.context) is not bridge.ApprovedDisposableContext
                or bridge._ISSUED.get(id(run.context)) is not run.context):
            raise ControllerError('disposable-run-required')
        return cls._bind(run=run, planning=planning, session=session,
                         display_adapter=display_adapter, now=now)

    def _context_is_trusted(self):
        return bridge._ISSUED.get(id(self._context)) is self._context
