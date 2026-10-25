"""optional_setup_protocol.py — the four optional voice components, and the bridge to the setup worker that installs them.

v0.7.0 P05A (plan Revision 2 §5.4; owner rulings Q14-Q20 and Q32). This is the vocabulary every optional-setup caller
shares -- the first-run wizard, the in-app Install & Continue and the setup worker -- so none of them can disagree about
what a component is called, what state it is in, what a person agreed to, or what a figure in bytes is worth.

* **Four components, in this order:** Kokoro, Chatterbox Turbo, Qwen3 CustomVoice, Qwen3 Cloned Voices / Base. The
  approved wizard defaults are Kokoro checked and the other three unchecked (Q15). Nothing else may be named.
* **Readiness is structured** (§5.4): ready, missing (installable), damaged (repair required), unsupported, busy, a bad
  reference/transcript bundle, or unverified. Only *missing* can lead to an install and only *damaged* to a repair, each
  under its own consent; unverified is never treated as healthy, broken, or as permission to download.
* **Every byte figure says how it is known:** exact (measured here, now), manifest (a tracked pinned manifest),
  approximate (an estimate), at-least (a known part of a total with an unknown remainder) or unknown.
* **The worker bridge** (§5.4 "first-run execution home"): the setup worker runs only in the app's verified ``.venv``
  interpreter, CPython 3.12, as ``python -E -s -m tts.optional_setup_worker`` from the installation's ``scripts/``
  folder, so neither the current directory nor an ambient ``PYTHONPATH`` can choose the code it runs. Requests and
  results are versioned JSON files in one per-request folder under ``files/runtime-data/optional-setup/``, checked for
  containment and links; progress is marked JSON lines on the worker's stdout; a request has exactly one terminal
  result, published atomically and never overwritten; cancellation is a flag file, then a bounded wait, then the known
  child is ended. A request is bound to the session token of the process that wrote it and expires quickly, so consent
  given before a restart is never replayed.

**P05B Stage 1 (protocol v2).** A consent is bound to the plan the person was shown: it carries the fingerprint of
that plan's *acquisition terms* (selection, readiness and scope per component, and every unit to be acquired with its
source and download figure) plus the terms themselves, and the worker checks both against a plan it computes itself.
An exact main-context consent covers only an identical set of terms; a consent given to the pre-venv estimate is
checked against the estimate the worker reproduces, and then covers the main plan only under a bounded refinement
rule (:func:`consent_covers`). Unknown sizes must have been acknowledged as unknown, an unpinned source is refused, and
each consent and each request can be acted on once (:func:`claim_consent`, :func:`claim_request`). Results are
published only atomically -- never a partial file -- and a worker's whole process tree is contained and ended on
cancel or timeout (:class:`WorkerRun`).

Standard library only, and free of ``subprocess``, ``socket``, ``urllib``, ``http``, ``ssl`` and ``tkinter`` at import
time: the first-run setup imports it in a base interpreter before the app's environment exists. Starting the worker
imports ``subprocess``, ``threading`` and the app's process-containment module when it is asked to, not before.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import os
import re
import stat
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

from shared import venv_layout

# --------------------------------------------------------------------------- #
# The four components
# --------------------------------------------------------------------------- #
KOKORO = "kokoro"
CHATTERBOX = "chatterbox"
QWEN3_CUSTOMVOICE = "qwen3-customvoice"
QWEN3_BASE = "qwen3-base"
#: The order the wizard shows them in and every plan lists them in (Q14). Nothing outside this tuple is ever accepted.
COMPONENTS: tuple[str, ...] = (KOKORO, CHATTERBOX, QWEN3_CUSTOMVOICE, QWEN3_BASE)

LABELS: dict[str, str] = {
    KOKORO: "Kokoro",
    CHATTERBOX: "Chatterbox Turbo",
    QWEN3_CUSTOMVOICE: "Qwen3 CustomVoice",
    QWEN3_BASE: "Qwen3 Cloned Voices / Base",
}

#: Owner-approved first-run defaults (Q15). A planning contract only: the wizard itself changes in P06.
WIZARD_DEFAULTS: dict[str, bool] = {KOKORO: True, CHATTERBOX: False, QWEN3_CUSTOMVOICE: False, QWEN3_BASE: False}

#: The Qwen3 model each Qwen3 component installs (``tts.qwen3_runtime.MODEL_KEYS``; a test pins that they agree).
QWEN3_MODEL_KEYS: dict[str, str] = {QWEN3_CUSTOMVOICE: "customvoice", QWEN3_BASE: "base"}

# --------------------------------------------------------------------------- #
# Readiness
# --------------------------------------------------------------------------- #
READY = "ready"
MISSING = "missing"  # not installed; installable under install consent
DAMAGED = "damaged"  # present but proved wrong; repairable under repair consent
UNSUPPORTED = "unsupported"  # this platform, Python or architecture cannot run it
BUSY = "busy"  # another install, conversion or repair holds it right now
BAD_BUNDLE = "bad-bundle"  # a shipped reference recording or the transcript bundle is missing or invalid
UNVERIFIED = "unverified"  # not proved either way; must be proved before anything is acquired

#: Strongest first. A component's readiness is the first of these any of its parts is in, so a part that cannot be
#: proved makes the whole component unverified rather than installable, and nothing becomes ready by default.
READINESS: tuple[str, ...] = (UNSUPPORTED, BAD_BUNDLE, BUSY, DAMAGED, UNVERIFIED, MISSING, READY)

SCOPE_INSTALL = "install"
SCOPE_REPAIR = "repair"
SCOPES: tuple[str, ...] = (SCOPE_INSTALL, SCOPE_REPAIR)

#: Where a plan was made: the first-run wizard before the app environment exists (an upper-bound estimate that proves
#: nothing), or the app environment itself (the real state).
CONTEXT_PRE_VENV = "pre-venv"
CONTEXT_MAIN = "main"
CONTEXTS: tuple[str, ...] = (CONTEXT_PRE_VENV, CONTEXT_MAIN)


def combine_readiness(states: Iterable[str]) -> str:
    """The readiness of something made of parts in *states*. No parts proves nothing: :data:`UNVERIFIED`."""
    present = set(states)
    unknown = present - set(READINESS)
    if unknown:
        raise ValueError(f"unknown readiness {sorted(unknown)!r}")
    for state in READINESS:
        if state in present:
            return state
    return UNVERIFIED


def acquisition_scope(readiness: str) -> Optional[str]:
    """The consent a component in *readiness* would need before anything is acquired for it, or ``None`` when nothing
    may be acquired at all (it is ready, unsupported, busy, has a bad bundle, or is not proved)."""
    if readiness not in READINESS:
        raise ValueError(f"unknown readiness {readiness!r}")
    return {MISSING: SCOPE_INSTALL, DAMAGED: SCOPE_REPAIR}.get(readiness)


# --------------------------------------------------------------------------- #
# Byte figures that say how they are known
# --------------------------------------------------------------------------- #
EXACT = "exact"  # measured on this computer, now
MANIFEST = "manifest"  # from a tracked manifest pinned to an exact revision
APPROXIMATE = "approximate"  # an estimate: measured elsewhere, or upstream content the app does not pin
AT_LEAST = "at-least"  # the known part of a total whose remainder is unknown
UNKNOWN = "unknown"  # not knowable without asking the network
BASES: tuple[str, ...] = (EXACT, MANIFEST, APPROXIMATE, AT_LEAST, UNKNOWN)


@dataclass(frozen=True)
class Figure:
    """A number of bytes and how it is known. ``bytes`` is ``None`` only when :data:`UNKNOWN`."""

    bytes: Optional[int]
    basis: str

    def __post_init__(self):
        if self.basis not in BASES:
            raise ValueError(f"unknown basis {self.basis!r}")
        if (self.bytes is None) != (self.basis == UNKNOWN):
            raise ValueError("only an unknown figure has no byte count, and it always has none")
        if self.bytes is not None and (type(self.bytes) is not int or self.bytes < 0):
            raise ValueError("a byte count is a non-negative integer")

    def to_json(self) -> dict:
        return {"bytes": self.bytes, "basis": self.basis}


ZERO = Figure(0, EXACT)
NOT_KNOWN = Figure(None, UNKNOWN)


def add_figures(figures: Iterable[Figure]) -> Figure:
    """The sum, as well as it is known: the weakest basis wins, and any unknown part makes the known sum a lower bound."""
    figures = list(figures)
    known = [f for f in figures if f.bytes is not None]
    if len(known) < len(figures):
        return Figure(sum(f.bytes for f in known), AT_LEAST) if known else NOT_KNOWN
    if not known:
        return ZERO
    return Figure(sum(f.bytes for f in known), max((f.basis for f in known), key=BASES.index))


# --------------------------------------------------------------------------- #
# Selections
# --------------------------------------------------------------------------- #
class ProtocolError(ValueError):
    """A request, event, result or path that cannot be trusted. ``code`` is one of the fixed codes below."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


MALFORMED = "malformed"
UNSUPPORTED_VERSION = "unsupported-version"
UNKNOWN_COMPONENT = "unknown-component"
DUPLICATE_COMPONENT = "duplicate-component"
BAD_CONSENT = "bad-consent"
STALE_REQUEST = "stale-request"
WRONG_SESSION = "wrong-session"
UNSAFE_PATH = "unsafe-path"
ALREADY_ANSWERED = "already-answered"
WRONG_INTERPRETER = "wrong-interpreter"
CONSENT_STALE = "consent-stale"
ACQUISITION_UNAVAILABLE = "acquisition-unavailable"
CANCELLED = "cancelled"
NO_RESULT = "no-result"
INTERNAL = "internal"
CONSENT_USED = "consent-used"  # this confirmation was already acted on once
NOT_ACQUIRABLE = "not-acquirable"  # a chosen component is unverified, busy, unsupported or has a bad bundle
SOURCE_UNPINNED = "source-unpinned"  # something would be acquired from a source that is not pinned to an exact identity
PUBLICATION_UNAVAILABLE = "publication-unavailable"  # this folder cannot publish a file atomically
CONTAINMENT_UNAVAILABLE = "containment-unavailable"  # the worker could not be placed where its whole tree can be ended
TIMED_OUT = "timed-out"
ACQUISITION_FAILED = "acquisition-failed"  # an acquisition stopped short, failed, or acquired something unexpected
HEALTH_UNPROVED = "health-unproved"  # the acquisition finished but working components were not proved afterwards
ERROR_CODES: tuple[str, ...] = (MALFORMED, UNSUPPORTED_VERSION, UNKNOWN_COMPONENT, DUPLICATE_COMPONENT, BAD_CONSENT,
                                STALE_REQUEST, WRONG_SESSION, UNSAFE_PATH, ALREADY_ANSWERED, WRONG_INTERPRETER,
                                CONSENT_STALE, ACQUISITION_UNAVAILABLE, CANCELLED, NO_RESULT, INTERNAL, CONSENT_USED,
                                NOT_ACQUIRABLE, SOURCE_UNPINNED, PUBLICATION_UNAVAILABLE, CONTAINMENT_UNAVAILABLE,
                                TIMED_OUT, ACQUISITION_FAILED, HEALTH_UNPROVED)


def canonical_selection(components: Iterable[object]) -> tuple[str, ...]:
    """*components* as a validated selection in the canonical order. Unknown or repeated names are refused."""
    if isinstance(components, (str, bytes)):
        raise ProtocolError(MALFORMED, "components must be a list of component names")
    seen: list[str] = []
    for name in components:
        if type(name) is not str or name not in COMPONENTS:
            raise ProtocolError(UNKNOWN_COMPONENT, f"{name!r} is not an optional component")
        if name in seen:
            raise ProtocolError(DUPLICATE_COMPONENT, f"{name!r} is listed twice")
        seen.append(name)
    return tuple(c for c in COMPONENTS if c in seen)


def _wire_selection(value: object, *, allow_empty: bool) -> tuple[str, ...]:
    """A selection as it must appear on the wire: a list, already in canonical order."""
    if type(value) is not list:
        raise ProtocolError(MALFORMED, "components must be a list")
    selection = canonical_selection(value)
    if list(selection) != value:
        raise ProtocolError(MALFORMED, "components must be listed in the canonical order")
    if not selection and not allow_empty:
        raise ProtocolError(MALFORMED, "no component was named")
    return selection


# --------------------------------------------------------------------------- #
# Requests
# --------------------------------------------------------------------------- #
PROTOCOL = "act-optional-setup"
#: 1 = P05A (a consent named a fingerprint nothing checked); 2 = P05B Stage 1 (the consent is bound to checked terms).
#: Only this version is accepted: a v1 consent cannot be trusted, so it is refused, never upgraded.
PROTOCOL_VERSION = 2
ACTION_PLAN = "plan"  # report readiness and the plan; acquires nothing
ACTION_INSTALL = "install"  # acquire under consent; this build checks the consent, then acquires nothing
ACTIONS: tuple[str, ...] = (ACTION_PLAN, ACTION_INSTALL)

REQUEST_KEYS = frozenset({"protocol", "version", "request_id", "session", "issued_utc", "action", "components",
                          "consent", "options"})
CONSENT_KEYS = frozenset({"consent_id", "plan_context", "components", "scopes", "units", "unknown_units",
                          "download_bytes", "acquisition_fingerprint"})
OPTION_KEYS = frozenset({"probe_hardware"})
#: Every message is small; anything larger is not one this protocol wrote.
MAX_MESSAGE_BYTES = 64 * 1024
#: A request is acted on promptly or not at all: consent does not outlive the moment it was given.
MAX_REQUEST_AGE_S = 600
MAX_CLOCK_SKEW_S = 60
#: Plan unit ids are plain tokens (``qwen3-engine``, ``kokoro-voice:af_heart``).
_UNIT = re.compile(r"[a-z0-9][a-z0-9_.:-]{0,79}")
_TOKEN = re.compile(r"[0-9a-f]{32}")
_FINGERPRINT = re.compile(r"[0-9a-f]{64}")
_UTC = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")


def new_token() -> str:
    """A fresh random 128-bit token in lowercase hex (request ids and session tokens)."""
    return os.urandom(16).hex()


def utc_text(when: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(when))


@dataclass(frozen=True)
class Consent:
    """What a person agreed to by confirming one plan (:func:`consent_fields` derives everything but the id from it).

    ``consent_id`` is fresh for each confirmation and can be acted on once. ``plan_context`` says which kind of plan was
    shown. ``scopes`` gives each chosen component's agreement -- install, repair, or ``None`` (it was ready; nothing is
    acquired for it) -- so a plan mixing an install and a repair is agreed component by component, never under one
    scope. ``units`` are every unit that may be acquired; ``unknown_units`` those of them whose size was shown as
    unknown (never counted as zero); ``download_bytes`` the known part. ``acquisition_fingerprint`` binds all of it to
    the plan's terms (:func:`acquisition_fingerprint`).
    """

    consent_id: str
    plan_context: str
    components: tuple[str, ...]
    scopes: dict
    units: tuple[str, ...]
    unknown_units: tuple[str, ...]
    download_bytes: int
    acquisition_fingerprint: str

    def terms_json(self) -> dict:
        """Everything but the id: what :func:`consent_fields` derives from the plan it names."""
        return {"plan_context": self.plan_context, "components": list(self.components), "scopes": dict(self.scopes),
                "units": list(self.units), "unknown_units": list(self.unknown_units),
                "download_bytes": self.download_bytes, "acquisition_fingerprint": self.acquisition_fingerprint}

    def to_json(self) -> dict:
        return {"consent_id": self.consent_id, **self.terms_json()}


@dataclass(frozen=True)
class Request:
    request_id: str
    session: str
    issued_utc: str
    action: str
    components: tuple[str, ...]
    consent: Optional[Consent] = None
    probe_hardware: bool = False

    def to_json(self) -> dict:
        return {"protocol": PROTOCOL, "version": PROTOCOL_VERSION, "request_id": self.request_id,
                "session": self.session, "issued_utc": self.issued_utc, "action": self.action,
                "components": list(self.components),
                "consent": None if self.consent is None else self.consent.to_json(),
                "options": {"probe_hardware": self.probe_hardware}}


def new_request(action: str, components: Iterable[str], *, session: str, consent: Optional[Consent] = None,
                probe_hardware: bool = False, now: Callable[[], float] = time.time) -> Request:
    """A request with a fresh id, checked exactly as the worker will check it."""
    request = Request(new_token(), session, utc_text(now()), action, canonical_selection(components), consent,
                      probe_hardware)
    return decode_request(encode(request.to_json()), session=session, now=now)


def encode(message: dict) -> bytes:
    data = json.dumps(message, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
    if len(data) > MAX_MESSAGE_BYTES:
        raise ProtocolError(MALFORMED, "the message is too large")
    return data


def _reject_duplicate_keys(pairs: list) -> dict:
    keys = [k for k, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ProtocolError(MALFORMED, "a key appears twice")
    return dict(pairs)


def _reject_constant(name: str):
    raise ProtocolError(MALFORMED, f"{name} is not a number")


def strict_json(raw: bytes) -> dict:
    """One JSON object, at most :data:`MAX_MESSAGE_BYTES`, UTF-8, no repeated keys, no NaN/Infinity."""
    if type(raw) is not bytes or len(raw) > MAX_MESSAGE_BYTES:
        raise ProtocolError(MALFORMED, "the message is missing or too large")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys,
                           parse_constant=_reject_constant)
    except ProtocolError:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise ProtocolError(MALFORMED, "the message is not valid JSON") from None
    if type(value) is not dict:
        raise ProtocolError(MALFORMED, "the message is not a JSON object")
    return value


def _exact_keys(value: object, keys: frozenset, what: str) -> dict:
    if type(value) is not dict or set(value) != keys:
        raise ProtocolError(MALFORMED, f"{what} must have exactly the keys {sorted(keys)}")
    return value


def _check_header(message: dict) -> None:
    if message.get("protocol") != PROTOCOL:
        raise ProtocolError(MALFORMED, "this is not an optional-setup message")
    version = message.get("version")
    if type(version) is not int:
        raise ProtocolError(MALFORMED, "the protocol version is not an integer")
    if version != PROTOCOL_VERSION:
        raise ProtocolError(UNSUPPORTED_VERSION, f"protocol version {version} is not supported")


def _unit_list(value: object, what: str) -> tuple[str, ...]:
    if type(value) is not list or any(type(u) is not str or not _UNIT.fullmatch(u) for u in value) \
            or len(set(value)) != len(value):
        raise ProtocolError(BAD_CONSENT, f"the consented {what} are not a list of distinct unit ids")
    return tuple(value)


def _decode_consent(value: object, components: tuple[str, ...]) -> Consent:
    if type(value) is not dict or set(value) != CONSENT_KEYS:
        raise ProtocolError(BAD_CONSENT, f"consent must have exactly the keys {sorted(CONSENT_KEYS)}")
    raw = value
    if type(raw["consent_id"]) is not str or not _TOKEN.fullmatch(raw["consent_id"]):
        raise ProtocolError(BAD_CONSENT, "the consent id is not a 32-character lowercase hex token")
    if raw["plan_context"] not in CONTEXTS:
        raise ProtocolError(BAD_CONSENT, "the consent does not say which kind of plan was shown")
    consented = _wire_selection(raw["components"], allow_empty=False)
    if consented != components:
        raise ProtocolError(BAD_CONSENT, "the consent does not name exactly the requested components")
    scopes = raw["scopes"]
    if type(scopes) is not dict or set(scopes) != set(consented) \
            or any(s is not None and s not in SCOPES for s in scopes.values()):
        raise ProtocolError(BAD_CONSENT, "the consent must give each chosen component install, repair or null")
    if raw["plan_context"] == CONTEXT_PRE_VENV and set(scopes.values()) != {SCOPE_INSTALL}:
        raise ProtocolError(BAD_CONSENT, "a consent given to the first-run estimate can only be an install consent")
    units = _unit_list(raw["units"], "plan units")
    unknown = _unit_list(raw["unknown_units"], "units of unknown size")
    if not set(unknown) <= set(units):
        raise ProtocolError(BAD_CONSENT, "a unit of unknown size was not among the consented units")
    if type(raw["download_bytes"]) is not int or raw["download_bytes"] < 0:
        raise ProtocolError(BAD_CONSENT, "the consented download size is not a byte count")
    if type(raw["acquisition_fingerprint"]) is not str or not _FINGERPRINT.fullmatch(raw["acquisition_fingerprint"]):
        raise ProtocolError(BAD_CONSENT, "the consent does not carry the fingerprint of the plan that was shown")
    return Consent(raw["consent_id"], raw["plan_context"], consented, dict(scopes), units, unknown,
                   raw["download_bytes"], raw["acquisition_fingerprint"])


def decode_request(raw: bytes, *, session: str, now: Callable[[], float] = time.time) -> Request:
    """Parse and check a request completely, or raise :class:`ProtocolError`.

    It must belong to *session* (the token of the process that started this worker) and be fresh, so a request left
    behind by an earlier run -- with whatever it once consented to -- is refused rather than replayed.
    """
    message = _exact_keys(strict_json(raw), REQUEST_KEYS, "a request")
    _check_header(message)
    for key in ("request_id", "session"):
        if type(message[key]) is not str or not _TOKEN.fullmatch(message[key]):
            raise ProtocolError(MALFORMED, f"{key} is not a 32-character lowercase hex token")
    if type(session) is not str or not _TOKEN.fullmatch(session) or message["session"] != session:
        raise ProtocolError(WRONG_SESSION, "the request belongs to another session; it is not replayed")
    issued = message["issued_utc"]
    if type(issued) is not str or not _UTC.fullmatch(issued):
        raise ProtocolError(MALFORMED, "issued_utc is not a UTC time like 2026-01-31T12:00:00Z")
    try:
        issued_at = calendar.timegm(time.strptime(issued, "%Y-%m-%dT%H:%M:%SZ"))
    except ValueError:
        raise ProtocolError(MALFORMED, "issued_utc is not a real time") from None
    age = now() - issued_at
    if age > MAX_REQUEST_AGE_S or age < -MAX_CLOCK_SKEW_S:
        raise ProtocolError(STALE_REQUEST, "the request is too old (or from the future); ask again")
    action = message["action"]
    if action not in ACTIONS:
        raise ProtocolError(MALFORMED, "the action is not plan or install")
    components = _wire_selection(message["components"], allow_empty=action == ACTION_PLAN)
    options = _exact_keys(message["options"], OPTION_KEYS, "options")
    if type(options["probe_hardware"]) is not bool:
        raise ProtocolError(MALFORMED, "probe_hardware must be true or false")
    consent = None
    if action == ACTION_PLAN:
        if message["consent"] is not None:
            raise ProtocolError(BAD_CONSENT, "a plan request carries no consent")
    else:
        if message["consent"] is None:
            raise ProtocolError(BAD_CONSENT, "an install request needs the person's consent")
        consent = _decode_consent(message["consent"], components)
    return Request(message["request_id"], message["session"], issued, action, components, consent,
                   options["probe_hardware"])


# --------------------------------------------------------------------------- #
# Consent bound to a plan's acquisition terms
# --------------------------------------------------------------------------- #
#: Domain separation for the terms fingerprint, so it can never be confused with any other hash of the same JSON.
_TERMS_DOMAIN = b"act-optional-setup/acquisition-terms/1\n"
_TERM_UNIT_KEYS = ("id", "components", "state", "source", "download")


def acquisition_terms(plan: dict) -> dict:
    """The part of *plan* (a :func:`tts.optional_setup.plan_to_json` plan) that a consent agrees to.

    The selection, each chosen component's readiness and consent scope, and every unit to be acquired with the
    components it serves, its state, its source and its download figure. Wording, hardware facts, reused bytes and
    disk/temp figures are not terms: they can change without changing what would be fetched.
    """
    units = {u["id"]: u for u in plan["units"]}
    chosen = set(plan["selected"])
    return {
        "schema": plan["schema"],
        "context": plan["context"],
        "selected": list(plan["selected"]),
        "components": [{"id": c["id"], "readiness": c["readiness"], "consent_scope": c["consent_scope"]}
                       for c in plan["components"] if c["id"] in chosen],
        "acquire": [{key: units[unit_id][key] for key in _TERM_UNIT_KEYS} for unit_id in plan["acquire_units"]],
    }


def acquisition_fingerprint(plan: dict) -> str:
    """SHA-256 of :func:`acquisition_terms` (canonical JSON, domain-separated): what a consent is bound to."""
    body = json.dumps(acquisition_terms(plan), sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")
    return hashlib.sha256(_TERMS_DOMAIN + body).hexdigest()


def _not_acquirable(entry: dict) -> str:
    label = LABELS.get(entry["id"], entry["id"])
    reason = (entry.get("reason") or "").strip()
    return f"{label} is {entry['readiness']}{': ' + reason if reason else ''}. Nothing may be acquired for it."


def consent_fields(plan: dict) -> dict:
    """Everything a consent to *plan* says, except its id (:meth:`Consent.terms_json`), or ``not-acquirable``.

    From the pre-venv estimate every chosen component is an install (nothing is proved yet; an unsupported one cannot be
    agreed to). From a main plan each chosen component must be ready, missing (install) or damaged (repair): an
    unverified, busy, unsupported or bad-bundle component cannot be agreed to at all.
    """
    context = plan["context"]
    if context not in CONTEXTS:
        raise ProtocolError(MALFORMED, "the plan does not say where it was made")
    scopes: dict = {}
    for entry in plan["components"]:
        if not entry["selected"]:
            continue
        if context == CONTEXT_PRE_VENV:
            if entry["readiness"] == UNSUPPORTED:
                raise ProtocolError(NOT_ACQUIRABLE, _not_acquirable(entry))
            scopes[entry["id"]] = SCOPE_INSTALL
        elif entry["readiness"] in (READY, MISSING, DAMAGED):
            scopes[entry["id"]] = entry["consent_scope"]
        else:
            raise ProtocolError(NOT_ACQUIRABLE, _not_acquirable(entry))
    units = {u["id"]: u for u in plan["units"]}
    acquire = list(plan["acquire_units"])
    unknown = [unit_id for unit_id in acquire if units[unit_id]["download"]["bytes"] is None]
    return {"plan_context": context, "components": list(plan["selected"]), "scopes": scopes, "units": acquire,
            "unknown_units": unknown,
            "download_bytes": sum(units[u]["download"]["bytes"] for u in acquire if u not in unknown),
            "acquisition_fingerprint": acquisition_fingerprint(plan)}


def consent_covers(consent: Consent, plan: dict, *, estimate: Optional[dict] = None) -> tuple[bool, str, str]:
    """``(covered, error code, reason)``: whether *consent* authorises acquiring what the fresh main *plan* needs.

    *plan* is computed by the caller itself, now; nothing in the request is trusted to describe it. The consent must
    name, by fingerprint and by every term, the plan the person was shown:

    * ``main`` consent: that plan is *plan* itself -- the terms must be identical. Any material change (a component,
      scope, source, unit or download figure) needs a fresh confirmation.
    * ``pre-venv`` consent: that plan is the first-run estimate for the same choices, which the caller reproduces and
      passes as *estimate* (the consent is refused if it names anything else). The main plan is then covered only as a
      bounded refinement of it: every unit it acquires was in the estimate, serves no new component, comes from the
      same source and costs no more; a unit of unknown size must have been shown and agreed as unknown; a component
      that now needs a repair needs its own repair confirmation.

    In both cases each chosen component must be ready or need exactly the agreed scope, nothing unverified, busy,
    unsupported or blocked by a bad bundle can be acquired, and nothing is acquired from an unpinned source.
    """
    if plan.get("context") != CONTEXT_MAIN:
        return False, MALFORMED, "a consent is checked only against a fresh plan made in the app's environment"
    if tuple(plan.get("selected", ())) != consent.components:
        return False, CONSENT_STALE, "the plan is for other choices than the ones that were confirmed"
    for entry in plan["components"]:
        if entry["selected"] and entry["readiness"] not in (READY, MISSING, DAMAGED):
            return False, NOT_ACQUIRABLE, _not_acquirable(entry)

    if consent.plan_context == CONTEXT_MAIN:
        reference = plan
    elif estimate is None or estimate.get("context") != CONTEXT_PRE_VENV \
            or tuple(estimate.get("selected", ())) != consent.components:
        return False, BAD_CONSENT, "the first-run estimate this consent was given to cannot be reproduced"
    else:
        reference = estimate
    expected_fingerprint = acquisition_fingerprint(reference)
    if consent.acquisition_fingerprint != expected_fingerprint:
        if reference is plan:
            return False, CONSENT_STALE, ("the plan is not the one that was confirmed: it has changed since, or the "
                                          "confirmation names a different plan")
        return False, BAD_CONSENT, "the confirmation does not name this installation's estimate for these choices"
    try:
        expected = consent_fields(reference)
    except ProtocolError as exc:
        return False, exc.code, str(exc)
    if consent.terms_json() != expected:
        return False, BAD_CONSENT, "the confirmation's terms do not match the plan it names"

    units = {u["id"]: u for u in plan["units"]}
    for unit_id in plan["acquire_units"]:
        if not units[unit_id].get("source"):
            return False, SOURCE_UNPINNED, (f"{units[unit_id]['label']} would be fetched from a source that is not "
                                            "pinned to an exact version; it cannot be acquired")
    if reference is plan:
        return True, "", "ok"

    for entry in plan["components"]:  # the estimate agreed to installs only
        if entry["selected"] and entry["consent_scope"] == SCOPE_REPAIR:
            return False, CONSENT_STALE, (f"{LABELS[entry['id']]} now needs a repair, which needs its own "
                                          "confirmation")
    shown = {u["id"]: u for u in estimate["units"]}
    for unit_id in plan["acquire_units"]:
        unit, before = units[unit_id], shown.get(unit_id)
        if before is None or unit_id not in consent.units:
            return False, CONSENT_STALE, f"{unit['label']} would be acquired, which was not confirmed"
        if set(unit["components"]) - set(before["components"]):
            return False, CONSENT_STALE, f"{unit['label']} now serves a choice it was not confirmed for"
        if unit["source"] != before["source"]:
            return False, CONSENT_STALE, f"{unit['label']} would now come from a different source"
        size, agreed = unit["download"]["bytes"], before["download"]["bytes"]
        if size is None:
            if agreed is not None or unit_id not in consent.unknown_units:
                return False, CONSENT_STALE, f"the size of {unit['label']} is not known; confirm it as unknown"
        elif agreed is None:
            return False, CONSENT_STALE, (f"{unit['label']} was confirmed with an unknown size; its size is now "
                                          "known and must be confirmed")
        elif size > agreed:
            return False, CONSENT_STALE, f"{unit['label']} would now download more than was confirmed"
    known = sum(units[u]["download"]["bytes"] or 0 for u in plan["acquire_units"])
    if known > consent.download_bytes:  # implied by the per-unit bound; kept as the plain statement of the rule
        return False, CONSENT_STALE, "the download is now larger than was confirmed"
    return True, "", "ok"


# --------------------------------------------------------------------------- #
# Progress events (stdout) and the one terminal result (a file)
# --------------------------------------------------------------------------- #
EVENT_MARK = "@@ACT-OPTIONAL-SETUP "
EVENT_KEYS = frozenset({"protocol", "version", "request_id", "seq", "kind", "payload"})
EVENT_KINDS: tuple[str, ...] = ("started", "readiness", "plan", "progress")

SUCCEEDED = "succeeded"
FAILED = "failed"
CANCELLED_STATE = "cancelled"
REFUSED = "refused"
TERMINAL_STATES: tuple[str, ...] = (SUCCEEDED, FAILED, CANCELLED_STATE, REFUSED)
RESULT_KEYS = frozenset({"protocol", "version", "request_id", "state", "error", "plan", "forced", "verified"})
ERROR_KEYS = frozenset({"code", "message"})
#: The worker's exit status for each terminal state; 2 means it could not even write a result.
EXIT_CODES: dict[str, int] = {SUCCEEDED: 0, CANCELLED_STATE: 3, REFUSED: 4, FAILED: 5}
EXIT_NO_RESULT = 2


def encode_event(request_id: str, seq: int, kind: str, payload: dict) -> str:
    if kind not in EVENT_KINDS:
        raise ValueError(f"unknown event kind {kind!r}")
    body = encode({"protocol": PROTOCOL, "version": PROTOCOL_VERSION, "request_id": request_id, "seq": seq,
                   "kind": kind, "payload": payload})
    return EVENT_MARK + body.decode("ascii")


def decode_event(line: str, *, request_id: str) -> Optional[dict]:
    """The event on *line*, ``None`` for an unmarked line (ordinary output), or :class:`ProtocolError`."""
    if not line.startswith(EVENT_MARK):
        return None
    event = _exact_keys(strict_json(line[len(EVENT_MARK):].strip().encode("utf-8")), EVENT_KEYS, "an event")
    _check_header(event)
    if event["request_id"] != request_id:
        raise ProtocolError(MALFORMED, "the event belongs to another request")
    if type(event["seq"]) is not int or event["seq"] < 0 or event["kind"] not in EVENT_KINDS \
            or type(event["payload"]) is not dict:
        raise ProtocolError(MALFORMED, "the event is malformed")
    return event


def make_result(request_id: str, state: str, *, error: Optional[tuple[str, str]] = None, plan: Optional[dict] = None,
                forced: bool = False, verified: Iterable[str] = ()) -> dict:
    """A terminal result. *verified* names the components proved to work after an install (all of them, for a
    success); a plan answer verifies nothing."""
    if state not in TERMINAL_STATES:
        raise ValueError(f"unknown terminal state {state!r}")
    if (state == SUCCEEDED) == (error is not None):
        raise ValueError("a success carries no error, and anything else carries one")
    if error is not None and error[0] not in ERROR_CODES:
        raise ValueError(f"unknown error code {error[0]!r}")
    return {"protocol": PROTOCOL, "version": PROTOCOL_VERSION, "request_id": request_id, "state": state,
            "error": None if error is None else {"code": error[0], "message": str(error[1])[:2000]},
            "plan": plan, "forced": forced, "verified": list(canonical_selection(verified))}


def decode_result(raw: bytes, *, request_id: str, request: Optional[Request] = None) -> dict:
    """Parse and check a terminal result, or raise :class:`ProtocolError`.

    Given the *request* it answers, a success is accepted only when it is complete: an install success must name every
    requested component as proved working afterwards, and a plan answer verifies nothing. So a result that claims
    success for an acquisition that was not finished and proved is refused, not believed.
    """
    result = _exact_keys(strict_json(raw), RESULT_KEYS, "a result")
    _check_header(result)
    if result["request_id"] != request_id:
        raise ProtocolError(MALFORMED, "the result belongs to another request")
    if result["state"] not in TERMINAL_STATES or type(result["forced"]) is not bool:
        raise ProtocolError(MALFORMED, "the result state is not a terminal state")
    error = result["error"]
    if (result["state"] == SUCCEEDED) != (error is None):
        raise ProtocolError(MALFORMED, "the result's error does not match its state")
    if error is not None:
        _exact_keys(error, ERROR_KEYS, "an error")
        if error["code"] not in ERROR_CODES or type(error["message"]) is not str:
            raise ProtocolError(MALFORMED, "the result's error is malformed")
    if result["plan"] is not None and type(result["plan"]) is not dict:
        raise ProtocolError(MALFORMED, "the result's plan is malformed")
    verified = _wire_selection(result["verified"], allow_empty=True)
    if request is not None:
        if not set(verified) <= set(request.components):
            raise ProtocolError(MALFORMED, "the result vouches for a component that was not requested")
        if request.action == ACTION_PLAN and verified:
            raise ProtocolError(MALFORMED, "a plan answer cannot vouch for anything")
        if request.action == ACTION_INSTALL and result["state"] == SUCCEEDED and verified != request.components:
            raise ProtocolError(MALFORMED, "an install success must prove every requested component works afterwards")
    return result


def publish_once(path: Path, data: bytes) -> bool:
    """Publish *data* at *path* atomically, only if nothing is there yet. ``False`` when something already was.

    Written beside the target, then hard-linked into place: the link either appears complete or fails because the name
    is taken, so a reader never sees half a result and a second writer can never replace the first. A folder that
    cannot make the link (no hard links there) raises ``publication-unavailable`` and publishes nothing: there is no
    fallback that could leave a partly written file visible under the name.
    """
    path = Path(path)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{new_token()[:8]}.tmp")
    with open(temporary, "xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        try:
            os.link(temporary, path)
        except FileExistsError:
            return False
        except OSError as exc:
            raise ProtocolError(PUBLICATION_UNAVAILABLE,
                                f"{path.name} cannot be published atomically in this folder "
                                f"({exc.strerror or exc}); nothing was published") from None
        return True
    finally:
        try:
            os.unlink(temporary)
        except OSError:
            pass


def read_message_file(path: Path) -> bytes:
    """A protocol file's bytes, refusing a link or anything that is not a small regular file."""
    if venv_layout.is_link(path):
        raise ProtocolError(UNSAFE_PATH, f"{Path(path).name} is a link")
    try:
        info = os.stat(path)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_MESSAGE_BYTES:
            raise ProtocolError(MALFORMED, f"{Path(path).name} is not a small regular file")
        with open(path, "rb") as handle:
            return handle.read(MAX_MESSAGE_BYTES + 1)
    except OSError as exc:
        raise ProtocolError(MALFORMED, f"{Path(path).name} cannot be read: {exc.strerror or exc}") from None


# --------------------------------------------------------------------------- #
# Where requests and results may live
# --------------------------------------------------------------------------- #
EXCHANGE_DIR: tuple[str, ...] = ("files", "runtime-data", "optional-setup")
REQUEST_NAME = "request.json"
RESULT_NAME = "result.json"
CANCEL_NAME = "cancel"
CLAIM_NAME = "claim"  # the worker answering this request (one at most)
_EXCHANGE_NAMES = (REQUEST_NAME, RESULT_NAME, CANCEL_NAME, CLAIM_NAME)
#: Under the exchange root: one marker per consent that has been acted on.
CONSENTS_DIR = "consents"


def exchange_root(repo_root: Path) -> Path:
    return Path(repo_root).joinpath(*EXCHANGE_DIR)


def exchange_dir(repo_root: Path, request_id: str) -> Path:
    if type(request_id) is not str or not _TOKEN.fullmatch(request_id):
        raise ProtocolError(MALFORMED, "the request id is not a 32-character lowercase hex token")
    return exchange_root(repo_root) / request_id


def check_exchange_path(repo_root: Path, raw: object, name: str) -> tuple[Path, str]:
    """``(path, request_id)`` for a protocol file named on a command line, or :class:`ProtocolError` (``unsafe-path``).

    It must be absolute, spelled without ``.``/``..``, be exactly ``files/runtime-data/optional-setup/<request id>/
    <name>`` of this installation, reach that folder through no link or junction, and still resolve inside the
    installation. The file itself is checked by whoever opens it.
    """
    if name not in _EXCHANGE_NAMES:
        raise ValueError(f"unknown exchange file {name!r}")
    if type(raw) is not str or not raw or "\x00" in raw:
        raise ProtocolError(UNSAFE_PATH, "the path is missing")
    path = Path(raw)
    if not path.is_absolute() or any(part in (".", "..") for part in re.split(r"[\\/]+", raw)):
        raise ProtocolError(UNSAFE_PATH, "the path must be absolute and plain")
    request_id = path.parent.name
    if not _TOKEN.fullmatch(request_id) or path.name != name \
            or not venv_layout.same_path(path, exchange_dir(repo_root, request_id) / name):
        raise ProtocolError(UNSAFE_PATH, f"the path is not this installation's optional-setup {name}")
    folder = path.parent
    if venv_layout.unsafe_component(repo_root, folder) is not None:
        raise ProtocolError(UNSAFE_PATH, "the exchange folder is reached through a link or lies outside the app")
    real_root = os.path.realpath(repo_root)
    try:
        inside = os.path.commonpath([real_root, os.path.realpath(folder)]) == real_root
    except ValueError:
        inside = False
    if not inside:
        raise ProtocolError(UNSAFE_PATH, "the exchange folder resolves outside the app")
    return path, request_id


def write_request(repo_root: Path, request: Request) -> Path:
    """Create the request's own new folder and publish ``request.json`` in it. Refuses an existing folder."""
    folder = exchange_dir(repo_root, request.request_id)
    root = exchange_root(repo_root)
    if venv_layout.unsafe_component(repo_root, root) is not None:
        raise ProtocolError(UNSAFE_PATH, "the optional-setup folder is reached through a link")
    root.mkdir(parents=True, exist_ok=True)
    folder.mkdir()  # a fresh folder per request: never reuse one
    path, _ = check_exchange_path(repo_root, str(folder / REQUEST_NAME), REQUEST_NAME)
    if not publish_once(path, encode(request.to_json())):
        raise ProtocolError(ALREADY_ANSWERED, "a request with this id already exists")
    return path


def cancel_requested(repo_root: Path, request_id: str) -> bool:
    return os.path.lexists(exchange_dir(repo_root, request_id) / CANCEL_NAME)


def claim_request(repo_root: Path, request_id: str) -> bool:
    """Become the one worker answering *request_id*. ``False`` when another run already claimed it."""
    path, _ = check_exchange_path(repo_root, str(exchange_dir(repo_root, request_id) / CLAIM_NAME), CLAIM_NAME)
    return publish_once(path, f"{os.getpid()}\n".encode("ascii"))


def claim_consent(repo_root: Path, consent_id: str, request_id: str) -> bool:
    """Spend *consent_id* on *request_id*, once. ``False`` when it was already acted on.

    Called just before anything is acquired, so one confirmation can never start two acquisitions -- not a duplicate
    request, not a request copied after the first one ran. (A restart cannot replay it either: the request is bound
    to its session, and a new session means a new confirmation.)
    """
    if type(consent_id) is not str or not _TOKEN.fullmatch(consent_id):
        raise ProtocolError(BAD_CONSENT, "the consent id is not a 32-character lowercase hex token")
    folder = exchange_root(repo_root) / CONSENTS_DIR
    if venv_layout.unsafe_component(repo_root, folder) is not None:
        raise ProtocolError(UNSAFE_PATH, "the consent record folder is reached through a link or lies outside the app")
    folder.mkdir(parents=True, exist_ok=True)
    real_root = os.path.realpath(repo_root)
    try:
        inside = os.path.commonpath([real_root, os.path.realpath(folder)]) == real_root
    except ValueError:  # another drive
        inside = False
    if venv_layout.unsafe_component(repo_root, folder) is not None or not inside:
        raise ProtocolError(UNSAFE_PATH, "the consent record folder resolves outside the app")
    return publish_once(folder / consent_id, f"{request_id}\n".encode("ascii"))


# --------------------------------------------------------------------------- #
# The execution home: where the setup worker may run
# --------------------------------------------------------------------------- #
#: The app's main interpreter for the worker (the Qwen3 installer's ``SUPPORTED_PYTHON``; a test pins that they agree).
MAIN_PYTHON = (3, 12)
WORKER_MODULE = "tts.optional_setup_worker"
#: Settings that could steer an interpreter or the tools it starts; dropped from the worker's environment. ``-E`` already
#: ignores ``PYTHON*`` inside the worker; removing them as well keeps them from whatever the worker may start later.
_STEERING = ("VIRTUAL_ENV", "CONDA_PREFIX", "CONDA_DEFAULT_ENV", "__PYVENV_LAUNCHER__")


def main_venv(repo_root: Path) -> Path:
    return Path(repo_root) / ".venv"


def main_console_python(repo_root: Path) -> Path:
    """The app environment's console interpreter (``python.exe``, never the windowless ``pythonw.exe``)."""
    return venv_layout.interpreter(main_venv(repo_root))


def execution_home_problem(repo_root: Path, *, implementation: Optional[str] = None,
                           version: Optional[tuple] = None, prefix: Optional[str] = None,
                           base_prefix: Optional[str] = None, executable: Optional[str] = None) -> str:
    """Why the running interpreter (or the one described) is not the worker's home, or ``""``.

    The home is the app's own verified environment, ``.venv``, on CPython 3.12: not the base interpreter, not the Qwen3
    engine's environment, not the legacy ``.venv-qwen3``, not anything reached through a link.
    """
    implementation = sys.implementation.name if implementation is None else implementation
    version = tuple(sys.version_info[:2]) if version is None else tuple(version)[:2]
    prefix = sys.prefix if prefix is None else prefix
    base_prefix = sys.base_prefix if base_prefix is None else base_prefix
    executable = sys.executable if executable is None else executable
    shown = f"{implementation} {'.'.join(str(p) for p in version)}"
    if implementation != "cpython" or version != MAIN_PYTHON:
        return f"the setup worker needs CPython {MAIN_PYTHON[0]}.{MAIN_PYTHON[1]}, not {shown}"
    if venv_layout.same_path(prefix, base_prefix):
        return "the setup worker must run in the app's environment, not in a base interpreter"
    if not venv_layout.same_path(prefix, main_venv(repo_root)):
        return "the setup worker must run in the app's own environment (.venv), not in another environment"
    if venv_layout.unsafe_component(repo_root, main_venv(repo_root)) is not None:
        return "the app's environment is reached through a link"
    if not venv_layout.same_path(executable, main_console_python(repo_root)):
        return "the setup worker must be started with the app environment's console interpreter"
    return ""


@dataclass(frozen=True)
class LaunchSpec:
    argv: tuple[str, ...]
    cwd: Path
    env: dict
    request_path: Path
    result_path: Path


def worker_launch(repo_root: Path, request_path: Path, session: str, *, python: Optional[Path] = None,
                  base_env: Optional[dict] = None) -> LaunchSpec:
    """How to start the worker for the request at *request_path*: an argv list, never a shell string.

    *python* must be the app environment's console interpreter (default: that one); this is checked on disk here and
    again by the worker on itself. The working folder is the installation's ``scripts/`` (``-m`` finds ``tts`` there);
    ``-E`` and ``-s`` keep ``PYTHONPATH``/``PYTHONHOME`` and user site-packages out of it.
    """
    python = Path(main_console_python(repo_root) if python is None else python)
    if not venv_layout.same_path(python, main_console_python(repo_root)):
        raise ProtocolError(WRONG_INTERPRETER, "the setup worker runs only with the app environment's console Python")
    if venv_layout.unsafe_component(repo_root, python) is not None or not python.is_file():
        raise ProtocolError(WRONG_INTERPRETER, "the app environment's console Python is missing or reached through a link")
    if not (Path(repo_root) / "scripts" / "tts" / "optional_setup_worker.py").is_file():
        raise ProtocolError(INTERNAL, "this installation has no setup worker")
    request_path, request_id = check_exchange_path(repo_root, str(request_path), REQUEST_NAME)
    result_path, _ = check_exchange_path(repo_root, str(request_path.with_name(RESULT_NAME)), RESULT_NAME)
    if type(session) is not str or not _TOKEN.fullmatch(session):
        raise ProtocolError(MALFORMED, "the session is not a 32-character lowercase hex token")
    env = dict(os.environ if base_env is None else base_env)
    for key in list(env):
        if key.upper().startswith("PYTHON") or key.upper() in _STEERING:
            del env[key]
    argv = (str(python), "-E", "-s", "-m", WORKER_MODULE, "--request", str(request_path), "--result",
            str(result_path), "--session", session)
    return LaunchSpec(argv, Path(repo_root) / "scripts", env, request_path, result_path)


#: How long a cancelled worker is given to stop by itself before its whole process tree is ended.
CANCEL_GRACE_S = 10.0
#: How long ending the tree, and confirming that no member of it is left, may take.
TERMINATE_WAIT_S = 15.0


def _process_control():
    """The app's one process-containment implementation, ``tts.qwen3_process`` (reused, not duplicated).

    On Windows the worker is started *suspended*, placed in a Job Object that ends every member when it is terminated or
    closed, and only then resumed: from its first instruction, everything it starts -- the venv launcher's real
    interpreter, and any installer it runs -- is a member, and nothing outside the job is ever touched. Elsewhere the
    worker leads a new process group. Imported only when a worker is started, so the pre-venv path stays free of
    ``ctypes`` and ``subprocess``.
    """
    from tts import qwen3_process

    return qwen3_process


def _contained_spawn(argv: list, **kwargs):
    """Start *argv* only if its whole tree can be ended later (``require_job``): otherwise it never runs."""
    return _process_control().spawn(argv, require_job=True, **kwargs)


class WorkerRun:
    """One worker process for one request: start it, follow its events, stop it, and get its one terminal result.

    * **Contained.** The worker runs inside a Job Object (a process group elsewhere): a cancel, a timeout, or the end of
      the run ends it *and every descendant*, then confirms none is left. A worker that cannot be contained is not run.
    * **One terminal result.** The result file is the authority. If the worker exits (or is ended) without publishing
      one, this publishes the terminal result in its place -- ``cancelled`` when it was stopped, ``failed`` with
      ``timed-out`` when it overran, ``failed`` otherwise -- through the same exclusive, atomic publication, so whichever
      comes first is the only result there will ever be. When nothing trustworthy can be read or written (a link, a
      malformed or incomplete success, no atomic publication) the answer is a failure held in memory: never a success.
    * **Never stranded.** A failing event callback is recorded, stops being called, cancels the worker, and its output
      keeps being drained so the worker cannot block on a full pipe.
    """

    def __init__(self, repo_root: Path, spec: LaunchSpec, request: Request, *,
                 on_event: Optional[Callable[[dict], None]] = None, spawn: Optional[Callable] = None):
        self.repo_root = Path(repo_root)
        self.spec = spec
        self.request = request
        self.on_event = on_event
        self._spawn = spawn
        self.process = None
        self.events: list[dict] = []
        self.protocol_errors: list[str] = []
        self.callback_errors: list[str] = []
        self.output: list[str] = []
        self.cancel_sent = False
        self.stop_requested = False
        self.timed_out = False
        self.terminated = False
        #: Members still in the job once the run ended (``None``: not measured -- no job on this platform).
        self.lingering: Optional[int] = None
        #: Every process that was ever a member of the job (the worker, the venv launcher's interpreter, children).
        self.members_seen: Optional[int] = None
        self._reader = None
        self._outcome: Optional[dict] = None

    def start(self) -> None:
        import subprocess
        import threading

        if self.process is not None or self._outcome is not None:
            raise RuntimeError("this worker run was already started")
        spawn = self._spawn or _contained_spawn
        try:
            self.process = spawn(list(self.spec.argv), cwd=str(self.spec.cwd), env=self.spec.env,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, encoding="utf-8", errors="replace")
        except Exception as exc:
            contained = isinstance(exc, _process_control().ContainmentUnavailable)
            code = CONTAINMENT_UNAVAILABLE if contained else INTERNAL
            self._outcome = self._forced(FAILED, code, f"The setup worker was not started: {exc}")
            raise
        self._reader = threading.Thread(target=self._read, name="optional-setup-events", daemon=True)
        self._reader.start()

    def _read(self) -> None:
        try:
            for raw in self.process.stdout:
                line = raw.rstrip("\r\n")
                try:
                    event = decode_event(line, request_id=self.request.request_id)
                except ProtocolError as exc:
                    self.protocol_errors.append(str(exc))
                    continue
                if event is None:
                    self.output.append(line[:500])
                    continue
                self.events.append(event)
                callback = self.on_event
                if callback is None:
                    continue
                try:
                    callback(event)
                except Exception as exc:  # noqa: BLE001 - a broken callback must not strand the worker
                    self.on_event = None
                    self.callback_errors.append(f"{type(exc).__name__}: {exc}")
                    try:
                        self.cancel()
                    except (ProtocolError, OSError) as cancel_exc:
                        self.callback_errors.append(f"the cancel request could not be written: {cancel_exc}")
        except (OSError, ValueError) as exc:  # the pipe broke or was closed under us
            self.protocol_errors.append(f"the worker's output could not be read: {exc}")

    def cancel(self) -> None:
        """Ask the worker to stop at its next checkpoint (a flag file in the request's own folder)."""
        folder = exchange_dir(self.repo_root, self.request.request_id)
        path, _ = check_exchange_path(self.repo_root, str(folder / CANCEL_NAME), CANCEL_NAME)
        self.cancel_sent = True
        publish_once(path, b"cancel\n")

    def stop(self, grace_s: float = CANCEL_GRACE_S) -> dict:
        """Cancel: ask the worker to stop, give it *grace_s*, then end its whole tree. Returns the one result."""
        import subprocess

        if self.process is None:
            raise RuntimeError("this worker run was never started")
        self.stop_requested = True
        if self.process.poll() is None:
            try:
                self.cancel()
                self.process.wait(timeout=grace_s)
            except (ProtocolError, OSError) as exc:  # the flag could not be written: no point waiting for it
                self.protocol_errors.append(f"the cancel request could not be written: {exc}")
                self._terminate()
            except subprocess.TimeoutExpired:
                self._terminate()
        return self._finish()

    def wait(self, timeout_s: float, *, cancel_grace_s: float = CANCEL_GRACE_S) -> dict:
        """Wait at most *timeout_s*; past it the run is stopped (cancel, grace, end the tree). Returns the one result."""
        import subprocess

        if self.process is None:
            raise RuntimeError("this worker run was never started")
        try:
            self.process.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            self.timed_out = True
            return self.stop(cancel_grace_s)
        return self._finish()

    def _terminate(self) -> None:
        self.terminated = True
        _process_control().kill_tree(self.process, wait_s=TERMINATE_WAIT_S)

    def _finish(self) -> dict:
        """The run is over: end anything the worker left behind, confirm the job is empty, reap, and settle the result."""
        import subprocess
        import time as _time

        if self._outcome is not None:
            return self._outcome
        job = getattr(self.process, "act_job", None)
        if job is not None:
            job.terminate()  # a grandchild that outlived the worker (it may still hold the output pipe) ends here
            deadline = _time.monotonic() + TERMINATE_WAIT_S
            try:
                while True:
                    active, self.members_seen = job.accounting()
                    if active == 0 or _time.monotonic() >= deadline:
                        break
                    _time.sleep(0.05)
                self.lingering = active
            except OSError as exc:
                self.protocol_errors.append(f"the worker's process group could not be measured: {exc}")
            if self.lingering:
                self.protocol_errors.append(f"{self.lingering} process(es) of the worker had not ended in time")
            _process_control().release(self.process)  # closing the job ends any member still there
        try:
            self.process.wait(timeout=TERMINATE_WAIT_S)
        except subprocess.TimeoutExpired:
            self.protocol_errors.append("the setup worker did not exit")
        if self._reader is not None:
            self._reader.join(timeout=5)
        if self.process.poll() is None:  # pragma: no cover - the OS refused to end it; never pretend it finished
            self._outcome = self._forced(FAILED, INTERNAL, "The setup worker could not be ended.", publish=False)
        else:
            self._outcome = self.result()
        return self._outcome

    def _forced_terms(self) -> tuple[str, str, str]:
        status = None if self.process is None else self.process.returncode
        if self.timed_out:
            return FAILED, TIMED_OUT, "The setup worker took too long and was stopped."
        if self.stop_requested or self.cancel_sent:
            return CANCELLED_STATE, CANCELLED, "Cancelled. The setup worker was stopped before it reported a result."
        return FAILED, NO_RESULT, f"The setup worker stopped without reporting a result (exit status {status})."

    def _forced(self, state: str, code: str, text: str, *, publish: bool = True) -> dict:
        """The terminal result written in the worker's place; held in memory if it cannot be published atomically."""
        rid = self.request.request_id
        forced = make_result(rid, state, error=(code, text), forced=True)
        if not publish:
            return forced
        try:
            path, _ = check_exchange_path(self.repo_root, str(self.spec.result_path), RESULT_NAME)
            if publish_once(path, encode(forced)):
                return forced
        except (ProtocolError, OSError) as exc:
            return make_result(rid, state, error=(code, f"{text} (The result could not be recorded: {exc})"),
                               forced=True)
        return self.result()  # the worker's own result arrived first: it is the one

    def result(self) -> dict:
        """The one terminal result (the worker's own when it published a trustworthy one). Never a partial success."""
        if self._outcome is not None:
            return self._outcome
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError("the setup worker is still running")
        rid = self.request.request_id
        try:
            path, _ = check_exchange_path(self.repo_root, str(self.spec.result_path), RESULT_NAME)
        except ProtocolError as exc:
            return make_result(rid, FAILED, error=(UNSAFE_PATH, f"The result cannot be trusted: {exc}"), forced=True)
        if not os.path.lexists(path):
            return self._forced(*self._forced_terms())
        try:
            return decode_result(read_message_file(path), request_id=rid, request=self.request)
        except ProtocolError as exc:
            return make_result(rid, FAILED, error=(MALFORMED, f"The setup worker's result cannot be trusted: {exc}"),
                               forced=True)
