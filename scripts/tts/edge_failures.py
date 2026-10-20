"""What went wrong with an Edge read-aloud request, and what to tell the user.

Edge TTS is Microsoft's unofficial online service: nothing guarantees it is available, and it has
refused ACT's client before (``edge-tts`` 7.2.8 got HTTP 403 at the WebSocket handshake). Both Edge
routes -- the direct engine (``epub2tts_edge.run_edgespeak``) and the folder worker
(``batch_convert.convert_single_pdf``) -- call the same ``edge_tts.Communicate.save`` and used to retry
every exception the same way, so a permanent refusal was retried 3 x 5 x 3 times and ended as a bare
"Giving up" or a traceback. This module is the one place that decides, from the exception's real type
and attributes, whether another attempt can help, and the one place that words the answer.

It changes no request: voice, text, chunking, rate and every successful result are untouched. It only
classifies a failure after it happened.

Standard library only at import time; ``aiohttp``, ``edge_tts`` and ``shared.cancellation`` are imported
lazily so the module loads (and the classifier degrades to ``UNKNOWN``) on a machine where they are absent.
"""

from __future__ import annotations

import asyncio
import enum
import re
import socket

#: The edge-tts version the requirements file pins. ``test_edge_failures`` keeps it equal to that pin; it
#: exists only so an install that has drifted from the pin can be named in the advice.
EXPECTED_EDGE_TTS = "7.3.1"

#: Separates the one-line advice from the technical detail inside an :class:`EdgeServiceError` message, so
#: a panel can show the advice alone and still keep the detail for the log.
GUIDANCE_SEPARATOR = " | Technical detail: "

_DETAIL_LIMIT = 300
_URL = re.compile(r"(?:wss?|https?)://[^\s'\"<>]+")
_TOKEN = re.compile(r"(?i)\b(TrustedClientToken|Sec-MS-GEC(?:-Version)?|ConnectionId)=[^\s&'\"]+")


class EdgeFailureKind(enum.Enum):
    """The recovery-relevant classes of failure. ``retryable`` is whether another attempt can plausibly help."""

    CANCELLED = ("cancelled", False)
    SERVICE_REFUSED = ("service refused the connection", False)  # HTTP 401/403, clock-skew handshake failure
    PROTOCOL = ("unexpected service response", False)  # the service speaks something this client does not
    NETWORK = ("network or temporary service problem", True)
    LOCAL = ("local problem", False)  # a file, folder or argument problem: asking Microsoft again cannot help
    UNKNOWN = ("unexpected failure", True)  # not understood: keep the old bounded retry

    def __init__(self, label: str, retryable: bool) -> None:
        self.label = label
        self.retryable = retryable


_REFUSED_STATUSES = frozenset({401, 403})
_TRANSIENT_STATUSES = frozenset({408, 425, 429})


def _aiohttp():
    try:
        import aiohttp
    except ImportError:  # pragma: no cover - aiohttp ships with edge-tts
        return None
    return aiohttp


def _edge_exceptions():
    try:
        from edge_tts import exceptions
    except ImportError:  # pragma: no cover - edge-tts is a pinned requirement
        return None
    return exceptions


def _conversion_cancelled():
    try:
        from shared.cancellation import ConversionCancelled
    except ImportError:  # pragma: no cover - scripts/ is always on the path for the callers
        return ()
    return ConversionCancelled


def _status_kind(status: int | None) -> EdgeFailureKind:
    if status in _REFUSED_STATUSES:
        return EdgeFailureKind.SERVICE_REFUSED
    if status is not None and (status in _TRANSIENT_STATUSES or status >= 500):
        return EdgeFailureKind.NETWORK
    return EdgeFailureKind.PROTOCOL  # 400, 404, 426, ... or a non-upgrade answer: the handshake itself changed


def classify(exc: BaseException) -> EdgeFailureKind:
    """Classify one exception raised by an Edge synthesis attempt."""
    if isinstance(exc, EdgeServiceError):
        return exc.kind
    if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
        return EdgeFailureKind.CANCELLED
    cancelled = _conversion_cancelled()
    if cancelled and isinstance(exc, cancelled):
        return EdgeFailureKind.CANCELLED

    aiohttp = _aiohttp()
    if aiohttp is not None and isinstance(exc, aiohttp.ClientResponseError):
        return _status_kind(exc.status)  # includes WSServerHandshakeError

    edge = _edge_exceptions()
    if edge is not None:
        if isinstance(exc, edge.SkewAdjustmentError):
            return EdgeFailureKind.SERVICE_REFUSED
        if isinstance(exc, (edge.UnknownResponse, edge.UnexpectedResponse)):
            return EdgeFailureKind.PROTOCOL
        if isinstance(exc, edge.WebSocketError):
            return EdgeFailureKind.NETWORK
        if isinstance(exc, edge.EdgeTTSException):  # NoAudioReceived and anything new
            return EdgeFailureKind.UNKNOWN

    if aiohttp is not None and isinstance(exc, aiohttp.ClientError):
        return EdgeFailureKind.NETWORK  # connector, disconnect, payload and timeout errors
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError, ConnectionError, socket.gaierror)):
        return EdgeFailureKind.NETWORK  # before OSError: these are OSError subclasses
    if isinstance(exc, (OSError, ValueError, TypeError)):
        return EdgeFailureKind.LOCAL
    return EdgeFailureKind.UNKNOWN


def is_retryable(exc: BaseException) -> bool:
    return classify(exc).retryable


def scrub(text: str) -> str:
    """Remove the query string (handshake tokens) from any URL and any bare token parameter."""
    text = _URL.sub(lambda match: match.group(0).split("?", 1)[0], text)
    return _TOKEN.sub(r"\1=<removed>", text)


def describe(exc: BaseException) -> str:
    """One short, single-line, token-free description: type, HTTP status if any, and the message."""
    status = _status_of(exc)
    head = type(exc).__name__ + (f" (HTTP {status})" if status else "")
    message = getattr(exc, "message", None) if status else None  # aiohttp's own str() carries the full URL
    text = message if isinstance(message, str) and message else str(exc)
    text = " ".join(scrub(text).split())[:_DETAIL_LIMIT]
    return f"{head}: {text}" if text else head


def _status_of(exc: BaseException) -> int | None:
    status = getattr(exc, "status", None)
    return status if isinstance(status, int) else None


def installed_edge_tts() -> str | None:
    try:
        import edge_tts
    except ImportError:  # pragma: no cover
        return None
    return getattr(edge_tts, "__version__", None)


def _repair_hint() -> str:
    installed = installed_edge_tts()
    if installed is None or installed == EXPECTED_EDGE_TTS:
        return ""
    return (f" The installed Edge voice component ({installed}) is not the version ACT expects "
            f"({EXPECTED_EDGE_TTS}): run Setup_and_Run to repair it.")


def guidance(kind: EdgeFailureKind, status: int | None = None) -> str:
    """The one-line, nontechnical advice for a failure kind. Never promises that a remote refusal can be fixed here."""
    if kind is EdgeFailureKind.SERVICE_REFUSED:
        where = f" (HTTP {status})" if status else ""
        return (f"Microsoft's online Edge Read Aloud service refused the connection{where}. That is decided by "
                "Microsoft's service, so trying again, reinstalling or updating may not fix it. Check your internet "
                "connection and that your PC's date and time are correct, then try again later. If it keeps failing, "
                "please report it; you can also choose an offline voice such as Kokoro yourself." + _repair_hint())
    if kind is EdgeFailureKind.PROTOCOL:
        where = f" (HTTP {status})" if status else ""
        return (f"Microsoft's online Edge Read Aloud service answered in a way this version of ACT does not "
                f"understand{where}, which usually means the service has changed. Trying again will not fix it. "
                "Please report it so ACT can be updated; you can choose an offline voice such as Kokoro yourself "
                "in the meantime." + _repair_hint())
    if kind is EdgeFailureKind.NETWORK:
        return ("ACT could not get a reply from Microsoft's online Edge Read Aloud service after several tries. "
                "Check your internet connection (and any VPN or firewall), then use Retry Failed; the service may "
                "also be busy for a while.")
    return ("The Edge Read Aloud voice service failed unexpectedly after several tries. Use Retry Failed to try "
            "again, and if it keeps happening please report it with the technical detail from the log."
            + _repair_hint())


class EdgeServiceError(RuntimeError):
    """An Edge synthesis failure that is final: retries are exhausted, or none could help.

    ``str()`` is ``<one-line advice> | Technical detail: <scrubbed detail>`` so the same text reads well in a
    log and can be split by :func:`split_failure_text` for a one-line panel message.
    """

    def __init__(self, kind: EdgeFailureKind, advice: str, technical: str) -> None:
        super().__init__(f"{advice}{GUIDANCE_SEPARATOR}{technical}")
        self.kind = kind
        self.advice = advice
        self.technical = technical


def final_error(exc: BaseException, attempts: int) -> BaseException:
    """What to raise once an attempt loop has ended on ``exc``.

    Cancellation and local problems are returned unchanged (they are not about the service, and must keep
    their type for the callers that already handle them); everything else becomes an :class:`EdgeServiceError`
    carrying advice and a scrubbed diagnosis, including how many attempts were made.
    """
    kind = classify(exc)
    if kind in (EdgeFailureKind.CANCELLED, EdgeFailureKind.LOCAL) or isinstance(exc, EdgeServiceError):
        return exc
    technical = f"{describe(exc)}; {attempts} attempt{'s' if attempts != 1 else ''}"
    installed = installed_edge_tts()
    if installed:
        technical += f"; edge-tts {installed}"
    return EdgeServiceError(kind, guidance(kind, _status_of(exc)), technical)


def split_failure_text(text: str) -> str | None:
    """The one-line advice inside a failure text produced from an :class:`EdgeServiceError`, else ``None``.

    Accepts the bare message or the panel's ``"EdgeServiceError: <message>"`` form, and looks only at the
    first line, so a traceback appended after it (the folder route) does not matter.
    """
    first = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    prefix = "EdgeServiceError: "
    if first.startswith(prefix):
        first = first[len(prefix):]
    if GUIDANCE_SEPARATOR not in first:
        return None
    advice = first.split(GUIDANCE_SEPARATOR, 1)[0].strip()
    return advice or None
