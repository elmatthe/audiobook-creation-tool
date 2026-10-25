"""optional_setup_lifecycle.py — one optional-setup operation, from a fresh plan to exactly one terminal outcome.

v0.7.0 P05B Stage 1 (plan Revision 2 §5.4; Q14-Q20). GUI-independent, and the one path the setup worker answers a
request through. The states, in order::

    planning -> validating -> acquiring -> verifying -> succeeded
                    |             |            |
                    +-------------+------------+--> refused | cancelled | failed   (exactly one terminal outcome)

* **planning** -- the plan is made fresh, now, from the real state (never taken from the request).
* **validating** -- a ``plan`` request ends here (succeeded). An ``install`` request's consent must cover that fresh
  plan (``proto.consent_covers``: bound to the plan the person was shown, per-component install/repair scope, sizes,
  sources). Then the acquirer must be available, and the consent is spent (``claim``) so it can never start a second
  acquisition. Until here nothing has changed anywhere.
* **acquiring** -- only units the consent covers, with progress and cancellation; a stop, a failure, an incomplete
  report or anything outside the plan ends in cancelled/failed, never in success. After an incomplete acquisition the
  components are still proved one by one, so the failed result names those that do work (``verified``).
* **verifying** -- the plan is made again, with the post-install health facts. Success only when every chosen component
  is then ready, i.e. proved working; otherwise failed (``health-unproved``), naming what was proved.

Failure is recoverable by design: nothing here touches the app's own environment, the base app stays launchable, and
a retry is a new plan and a new confirmation (a spent consent is never reused).

P05B Stage 1 built this with :class:`DisabledAcquirer` as its only acquirer. Since Stage 2 the setup worker hands it the
real one (``tts.optional_setup_acquire.RealAcquirer``); an ``Operation`` built without an acquirer still gets the
disabled one, which refuses with ``acquisition-unavailable`` after the consent is checked and before it is spent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Optional, Protocol

from shared import optional_setup_protocol as proto

PLANNING = "planning"
VALIDATING = "validating"
ACQUIRING = "acquiring"
VERIFYING = "verifying"
PHASES: tuple[str, ...] = (PLANNING, VALIDATING, ACQUIRING, VERIFYING)

Emit = Callable[[str, dict], None]
CancelCheck = Callable[[], bool]


@dataclass(frozen=True)
class AcquisitionReport:
    """What an acquirer says it did. ``completed`` only when every unit it was given is fully in place."""

    completed: bool
    units: tuple[str, ...]
    detail: str = ""


class Acquirer(Protocol):
    """Fetches the units of a plan under a checked, spent consent (``tts.optional_setup_acquire.RealAcquirer``)."""

    available: bool

    def acquire(self, plan: dict, consent: proto.Consent, *, progress: Callable[[dict], None],
                cancel_check: CancelCheck) -> AcquisitionReport: ...


class DisabledAcquirer:
    """No acquirer: the default of an ``Operation`` not given one. Asked anyway, it refuses loudly rather than pretend."""

    available = False

    def acquire(self, plan, consent, *, progress, cancel_check) -> AcquisitionReport:
        raise RuntimeError("optional-voice acquisition is not part of this build")


class _Cancelled(Exception):
    pass


class Operation:
    """One request, answered once.

    *planner(health)* makes a fresh main-context plan (``plan_to_json``) with the given post-install health facts
    (``None`` before acquiring); *estimator()* reproduces the first-run estimate for the same choices (needed only to
    check a consent given to it); *health(components)* proves, after acquiring, which components work (``True``),
    are broken (``False``) or are unproved (``None``/absent); *claim(consent_id)* spends a consent once.
    """

    def __init__(self, request: proto.Request, *, planner: Callable[[Optional[Mapping]], dict],
                 estimator: Callable[[], dict], emit: Emit, cancel_check: CancelCheck,
                 acquirer: Optional[Acquirer] = None,
                 health: Optional[Callable[[tuple[str, ...]], Mapping[str, Optional[bool]]]] = None,
                 claim: Optional[Callable[[str], bool]] = None):
        self.request = request
        self._planner = planner
        self._estimator = estimator
        self._emit = emit
        self._cancel_check = cancel_check
        self.acquirer = acquirer or DisabledAcquirer()
        self._health = health or (lambda components: {})
        self._claim = claim
        self.phase = PLANNING
        self.history: list[str] = [PLANNING]
        self.outcome: Optional[dict] = None
        self.consent_spent = False

    # -- transitions ---------------------------------------------------------------------------------------------
    def _enter(self, phase: str) -> None:
        if self.outcome is not None:
            raise RuntimeError("the operation already has its terminal outcome")
        if PHASES.index(phase) <= PHASES.index(self.phase):
            raise RuntimeError(f"cannot go from {self.phase} back to {phase}")
        self.phase = phase
        self.history.append(phase)

    def _finish(self, state: str, *, error: Optional[tuple[str, str]] = None, plan: Optional[dict] = None,
                verified: tuple[str, ...] = ()) -> dict:
        """Settle the one terminal outcome. A second attempt is a programming error, and is refused."""
        if self.outcome is not None:
            raise RuntimeError("the operation already has its terminal outcome")
        self.outcome = proto.make_result(self.request.request_id, state, error=error, plan=plan, verified=verified)
        self.history.append(state)
        return self.outcome

    def _checkpoint(self) -> None:
        if self._cancel_check():
            raise _Cancelled()

    # -- the run -------------------------------------------------------------------------------------------------
    def run(self) -> dict:
        """Answer the request; return its terminal result. Never raises for an expected outcome."""
        request = self.request
        try:
            self._emit("started", {"action": request.action, "components": list(request.components)})
            self._checkpoint()
            data = self._planner(None)
            self._checkpoint()
            self._emit("readiness", {c["id"]: c["readiness"] for c in data["components"] if c["selected"]})
            self._emit("plan", {"fingerprint": data["fingerprint"],
                                "acquisition_fingerprint": data["acquisition_fingerprint"],
                                "download": data["totals"]["download"], "acquire_units": data["acquire_units"]})
            self._checkpoint()
        except _Cancelled:
            return self._finish(proto.CANCELLED_STATE,
                                error=(proto.CANCELLED, "Cancelled. Nothing was downloaded or changed."))

        self._enter(VALIDATING)
        if request.action == proto.ACTION_PLAN:
            return self._finish(proto.SUCCEEDED, plan=data)
        estimate = self._estimator() if request.consent.plan_context == proto.CONTEXT_PRE_VENV else None
        covered, code, why = proto.consent_covers(request.consent, data, estimate=estimate)
        if not covered:
            return self._finish(proto.REFUSED, plan=data, error=(code, f"{why}. Nothing was downloaded; confirm the "
                                                                       "current plan to continue."))
        if data["acquire_units"]:
            if not self.acquirer.available:
                return self._finish(proto.REFUSED, plan=data, error=(
                    proto.ACQUISITION_UNAVAILABLE,
                    "Installing optional voices is not part of this build yet. Nothing was downloaded or changed."))
            try:
                self._checkpoint()
            except _Cancelled:
                return self._finish(proto.CANCELLED_STATE, plan=data,
                                    error=(proto.CANCELLED, "Cancelled. Nothing was downloaded or changed."))
            try:
                claimed = self._claim is not None and self._claim(request.consent.consent_id)
            except proto.ProtocolError as exc:  # no safe place to record it: refuse rather than acquire unrecorded
                return self._finish(proto.REFUSED, plan=data, error=(exc.code, f"{exc}. Nothing was downloaded."))
            if not claimed:
                return self._finish(proto.REFUSED, plan=data, error=(
                    proto.CONSENT_USED, "This confirmation was already used. Nothing was downloaded; confirm the "
                                        "current plan again to continue."))
            self.consent_spent = True
            self._enter(ACQUIRING)
            failure = self._acquire(data)
            if failure is not None:
                return failure
        return self._verify(data)

    def _acquire(self, data: dict) -> Optional[dict]:
        """Run the acquisition; the terminal outcome if it did not finish exactly as planned, else ``None``."""
        def progress(payload: dict) -> None:
            self._emit("progress", dict(payload))

        try:
            report = self.acquirer.acquire(data, self.request.consent, progress=progress,
                                           cancel_check=self._cancel_check)
        except Exception as exc:  # noqa: BLE001 - one recoverable failure, never an unanswered request
            return self._finish(proto.FAILED, plan=data, error=(
                proto.ACQUISITION_FAILED, f"The download stopped with an error ({type(exc).__name__}: {exc}). "
                                          "Voices that were already working still work."))
        if self._cancel_check():
            return self._finish(proto.CANCELLED_STATE, plan=data, error=(
                proto.CANCELLED, "Cancelled. Anything partly downloaded is checked again before it is ever used."))
        if not isinstance(report, AcquisitionReport) or not report.completed:
            detail = getattr(report, "detail", "") or "it did not finish"
            return self._verify(data, failure=(proto.ACQUISITION_FAILED, f"The download did not complete: {detail}."))
        if set(report.units) != set(data["acquire_units"]):
            return self._finish(proto.FAILED, plan=data, error=(
                proto.ACQUISITION_FAILED, "The download did not match the confirmed plan, so it is not trusted."))
        return None

    def _verify(self, data: dict, *, failure: Optional[tuple[str, str]] = None) -> dict:
        """Prove which components work now. With *failure* (an incomplete acquisition) the outcome is that failure
        whatever is proved; the proof only says which components work despite it."""
        self._enter(VERIFYING)
        components = self.request.components
        try:
            facts = dict(self._health(components))
            after = self._planner(facts)
        except Exception as exc:  # noqa: BLE001 - an unproved install is a failure, not a success
            return self._finish(proto.FAILED, plan=data, error=failure or (
                proto.HEALTH_UNPROVED, f"The voices could not be checked afterwards ({type(exc).__name__}: {exc})."))
        if failure is None and self._cancel_check():  # a probe stopped by the cancel proved nothing either way
            return self._finish(proto.CANCELLED_STATE, plan=data, error=(
                proto.CANCELLED, "Cancelled while the voices were being checked. Everything downloaded is kept and "
                                 "checked again before it is used."))
        states = {c["id"]: c["readiness"] for c in after["components"] if c["selected"]}
        proved = tuple(c for c in components if states.get(c) == proto.READY)
        if failure is not None:
            working = ", ".join(proto.LABELS[c] for c in proved)
            return self._finish(proto.FAILED, plan=after, verified=proved, error=(
                failure[0], failure[1] + (f" Working now: {working}." if working else "")))
        if proved == components:
            return self._finish(proto.SUCCEEDED, plan=after, verified=proved)
        unproved = ", ".join(f"{proto.LABELS[c]} ({states.get(c, 'unknown')})" for c in components if c not in proved)
        return self._finish(proto.FAILED, plan=after, verified=proved, error=(
            proto.HEALTH_UNPROVED, f"Not proved to work afterwards: {unproved}."))
