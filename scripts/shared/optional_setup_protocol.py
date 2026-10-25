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

Standard library only, and free of ``subprocess``, ``socket``, ``urllib``, ``http``, ``ssl`` and ``tkinter`` at import
time: the first-run setup imports it in a base interpreter before the app's environment exists. Starting the worker
imports ``subprocess`` and ``threading`` when it is asked to, not before.
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
ERROR_CODES: tuple[str, ...] = (MALFORMED, UNSUPPORTED_VERSION, UNKNOWN_COMPONENT, DUPLICATE_COMPONENT, BAD_CONSENT,
                                STALE_REQUEST, WRONG_SESSION, UNSAFE_PATH, ALREADY_ANSWERED, WRONG_INTERPRETER,
                                CONSENT_STALE, ACQUISITION_UNAVAILABLE, CANCELLED, NO_RESULT, INTERNAL)


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
PROTOCOL_VERSION = 1
ACTION_PLAN = "plan"  # report readiness and the plan; acquires nothing
ACTION_INSTALL = "install"  # acquire under consent (P05B); this build answers it without acquiring anything
ACTIONS: tuple[str, ...] = (ACTION_PLAN, ACTION_INSTALL)

REQUEST_KEYS = frozenset({"protocol", "version", "request_id", "session", "issued_utc", "action", "components",
                          "consent", "options"})
CONSENT_KEYS = frozenset({"scope", "components", "units", "download_bytes", "plan_fingerprint"})
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
    """What a person agreed to: a scope, the components, every plan unit that may be acquired, and the most it may
    download (the known part; a unit whose size is unknown is covered only by being listed)."""

    scope: str
    components: tuple[str, ...]
    units: tuple[str, ...]
    download_bytes: int
    plan_fingerprint: str

    def to_json(self) -> dict:
        return {"scope": self.scope, "components": list(self.components), "units": list(self.units),
                "download_bytes": self.download_bytes, "plan_fingerprint": self.plan_fingerprint}


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


def _decode_consent(value: object, components: tuple[str, ...]) -> Consent:
    if type(value) is not dict or set(value) != CONSENT_KEYS:
        raise ProtocolError(BAD_CONSENT, f"consent must have exactly the keys {sorted(CONSENT_KEYS)}")
    raw = value
    if raw["scope"] not in SCOPES:
        raise ProtocolError(BAD_CONSENT, "the consent scope is not install or repair")
    consented = _wire_selection(raw["components"], allow_empty=False)
    if consented != components:
        raise ProtocolError(BAD_CONSENT, "the consent does not name exactly the requested components")
    units = raw["units"]
    if type(units) is not list or any(type(u) is not str or not _UNIT.fullmatch(u) for u in units) \
            or len(set(units)) != len(units):
        raise ProtocolError(BAD_CONSENT, "the consented plan units are not a list of distinct unit ids")
    if type(raw["download_bytes"]) is not int or raw["download_bytes"] < 0:
        raise ProtocolError(BAD_CONSENT, "the consented download size is not a byte count")
    if type(raw["plan_fingerprint"]) is not str or not _FINGERPRINT.fullmatch(raw["plan_fingerprint"]):
        raise ProtocolError(BAD_CONSENT, "the consent does not carry the fingerprint of the plan that was shown")
    return Consent(raw["scope"], consented, tuple(units), raw["download_bytes"], raw["plan_fingerprint"])


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


def consent_covers(consent: Consent, plan: dict) -> tuple[bool, str]:
    """Whether *consent* still covers *plan* (as :func:`tts.optional_setup.plan_to_json` writes it).

    Every component that needs work needs exactly the consented scope; every unit to be acquired was listed; the known
    download is no larger than was agreed. Anything more is new scope, which needs a fresh, visible confirmation.
    """
    components = {c["id"]: c for c in plan.get("components", [])}
    for name in consent.components:
        entry = components.get(name)
        if entry is None or not entry.get("selected"):
            return False, f"{name} is not part of the current plan"
        scope = entry.get("consent_scope")
        if scope is None and entry.get("readiness") != READY:
            return False, f"{name} is {entry.get('readiness')}; nothing may be acquired for it"
        if scope is not None and scope != consent.scope:
            return False, f"{name} now needs {scope} consent, not {consent.scope}"
    extra = sorted(set(plan.get("acquire_units", [])) - set(consent.units))
    if extra:
        return False, "the plan now acquires more than was agreed: " + ", ".join(extra)
    download = (plan.get("totals") or {}).get("download") or {}
    if download.get("bytes") is None or download["bytes"] > consent.download_bytes:
        return False, "the download is now larger than was agreed (or no longer known)"
    return True, "ok"


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
RESULT_KEYS = frozenset({"protocol", "version", "request_id", "state", "error", "plan", "forced"})
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
                forced: bool = False) -> dict:
    if state not in TERMINAL_STATES:
        raise ValueError(f"unknown terminal state {state!r}")
    if (state == SUCCEEDED) == (error is not None):
        raise ValueError("a success carries no error, and anything else carries one")
    if error is not None and error[0] not in ERROR_CODES:
        raise ValueError(f"unknown error code {error[0]!r}")
    return {"protocol": PROTOCOL, "version": PROTOCOL_VERSION, "request_id": request_id, "state": state,
            "error": None if error is None else {"code": error[0], "message": str(error[1])[:2000]},
            "plan": plan, "forced": forced}


def decode_result(raw: bytes, *, request_id: str) -> dict:
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
    return result


def publish_once(path: Path, data: bytes) -> bool:
    """Publish *data* at *path* atomically, only if nothing is there yet. ``False`` when something already was.

    Written beside the target, then hard-linked into place: the link either appears complete or fails because the name
    is taken, so a reader never sees half a result and a second writer can never replace the first.
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
        except OSError:  # a volume without hard links: an exclusive create is the next best thing
            try:
                with open(path, "xb") as handle:
                    handle.write(data)
            except FileExistsError:
                return False
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
_EXCHANGE_NAMES = (REQUEST_NAME, RESULT_NAME, CANCEL_NAME)


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


#: How long a cancelled worker is given to stop by itself before the known child is ended.
CANCEL_GRACE_S = 10.0


class WorkerRun:
    """One worker process for one request: start it, follow its events, cancel it, and get its one terminal result.

    The result file is the authority. If the worker exits (or is ended) without publishing one, this publishes the
    terminal result in its place -- ``cancelled`` when it was asked to stop, ``failed`` otherwise -- through the same
    exclusive publication, so whichever comes first is the only result there will ever be.
    """

    def __init__(self, repo_root: Path, spec: LaunchSpec, request: Request, *,
                 on_event: Optional[Callable[[dict], None]] = None, popen: Optional[Callable] = None):
        self.repo_root = Path(repo_root)
        self.spec = spec
        self.request = request
        self.on_event = on_event
        self._popen = popen
        self.process = None
        self.events: list[dict] = []
        self.protocol_errors: list[str] = []
        self.output: list[str] = []
        self.cancel_sent = False
        self._reader = None

    def start(self) -> None:
        import subprocess
        import threading

        if self.process is not None:
            raise RuntimeError("this worker run was already started")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        popen = self._popen or subprocess.Popen
        self.process = popen(list(self.spec.argv), cwd=str(self.spec.cwd), env=self.spec.env,
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding="utf-8", errors="replace", creationflags=flags)
        self._reader = threading.Thread(target=self._read, name="optional-setup-events", daemon=True)
        self._reader.start()

    def _read(self) -> None:
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
            if self.on_event is not None:
                self.on_event(event)

    def cancel(self) -> None:
        """Ask the worker to stop at its next checkpoint (a flag file in the request's own folder)."""
        folder = exchange_dir(self.repo_root, self.request.request_id)
        path, _ = check_exchange_path(self.repo_root, str(folder / CANCEL_NAME), CANCEL_NAME)
        publish_once(path, b"cancel\n")
        self.cancel_sent = True

    def wait(self, timeout_s: float, *, cancel_grace_s: float = CANCEL_GRACE_S) -> dict:
        """Wait at most *timeout_s* (then cancel, wait *cancel_grace_s*, then end the child); return the one result."""
        import subprocess

        try:
            self.process.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            self.cancel()
            try:
                self.process.wait(timeout=cancel_grace_s)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=30)
        if self._reader is not None:
            self._reader.join(timeout=5)
        return self.result()

    def result(self) -> dict:
        path = self.spec.result_path
        if not os.path.lexists(path):
            state, code = (CANCELLED_STATE, CANCELLED) if self.cancel_sent else (FAILED, NO_RESULT)
            text = (f"The setup worker stopped without reporting a result (exit status {self.process.returncode}).")
            publish_once(path, encode(make_result(self.request.request_id, state, error=(code, text), forced=True)))
        return decode_result(read_message_file(path), request_id=self.request.request_id)
