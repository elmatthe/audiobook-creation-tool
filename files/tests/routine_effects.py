"""The routine verification guard for pytest processes (v0.8.2; simplified 2026-11-27, GATE.md).

``conftest.py`` calls :func:`install` before any test module is imported, and the gate starts every pytest stage with the
same environment already applied. The guard is deliberately small:

* **Marker.** ``ACT_VERIFY_CONTEXT=routine`` (``helpers/routine_context.py``) is set in this process's environment, so every
  ordinary child inherits it; the real heavyweight entrypoints check it themselves and refuse.
* **Scrub.** Ambient real-engine opt-ins (``ACT_*_REAL``) and destination overrides never reach a test or a child.
* **In-process refusals** through one audit hook: a non-loopback network connection or lookup, a model library reading a
  weight file outside the session's disposable roots, resolving a native input function outside the gate's input adapter,
  and ``os.startfile``.
* **Declared boundaries.** :func:`require` is called by a test immediately before real heavyweight work; nothing grants it
  (:func:`admitted` is always False until owner-authorized heavyweight admission exists).

A refusal raises :class:`EffectRefused` and is recorded in this process; ``conftest.py`` fails the test that caused one even
if the test caught it, unless the test declared it with :func:`expected_refusals`. Child processes are not intercepted or
accounted: a test asserts its own child's behaviour, and the gate supervises each stage's process tree, deadline and cleanup.
It is accident prevention for cooperating tests, not a sandbox.
"""

from __future__ import annotations

import contextlib
import importlib.util
import os
import re
import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_PY = ".py"
CONTEXT_PATH = REPO_ROOT / "files" / "dev-work" / "verification-gate" / "helpers" / ("routine_context" + _PY)


def _load_context():
    name = "act_gate_routine_context"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, CONTEXT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


context = _load_context()
EFFECTS = context.EFFECTS
CONTEXT_ENV, ROOT_ENV, DISPOSABLE_ENV = context.CONTEXT_ENV, context.ROOT_ENV, context.DISPOSABLE_ENV
ROUTINE, REFUSED_EXIT = context.ROUTINE, context.REFUSED_EXIT
OPT_IN = re.compile(r"^ACT_[A-Z0-9_]*_REAL(_[A-Z0-9_]+)?$")
#: Ambient destination and executable overrides a test must never inherit (v0.8.x P2 and P1A tools).
OVERRIDES = frozenset({"ACT_P2_EVIDENCE", "ACT_XHE_PROOF_APPLE_CAF", "ACT_MAC_FFMPEG"})
#: The files a copied runner in another tree (a synthetic gate fixture) needs beside it to install this same guard.
RUNNER_SUPPORT = ("files/tests/routine_effects" + _PY, "files/dev-work/verification-gate/helpers/routine_context" + _PY)
WEIGHTS = (".pt", ".pth", ".safetensors", ".onnx", ".ckpt", ".gguf")
#: Libraries whose reading of a weight file is model initialization.
MODEL_LIBRARIES = ("torch", "transformers", "huggingface_hub", "safetensors", "onnxruntime", "kokoro", "chatterbox",
                   "diffusers", "accelerate", "qwen_tts", "omnivoice", "spacy", "thinc", "librosa")
NATIVE_INPUT = frozenset({"SendInput", "keybd_event", "mouse_event", "SetCursorPos", "CGEventPost", "CGEventPostToPid",
                          "CGWarpMouseCursorPosition"})
NATIVE_INPUT_OWNER = "files/dev-work/verification-gate/adapters/windows/native_input" + _PY
LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost", None, ""})


class EffectRefused(PermissionError):
    """A heavyweight effect asked for in routine verification. Refused before the operation; recorded either way."""


_lock = threading.RLock()
_local = threading.local()
_refusals: list[dict] = []
_disposable_roots: list[str] = []
_installed = False


def scrub(environ=None) -> list[str]:
    """Remove ambient real-engine opt-ins and destination/executable overrides. Returns the names removed."""
    environ = os.environ if environ is None else environ
    removed = sorted(name for name in list(environ) if OPT_IN.match(name.upper()) or name.upper() in OVERRIDES)
    for name in removed:
        environ.pop(name, None)
    return removed


def _check(effect: str) -> None:
    if effect not in EFFECTS:
        raise ValueError(f"unknown effect {effect!r}; the vocabulary is {sorted(EFFECTS)}")


def admitted(effect: str) -> bool:
    """Whether this process may perform ``effect`` for real. Always False: heavyweight work needs owner authorization and
    runs outside routine verification (GATE.md)."""
    _check(effect)
    return False


def require(effect: str, detail: str) -> None:
    """Call immediately before a real heavyweight operation. Refuses (and records the refusal) unless admitted."""
    _check(effect)
    if admitted(effect):  # pragma: no cover - unreachable while nothing grants admission
        return
    refuse(effect, detail, origin="declared boundary")


def _scopes() -> list:
    if not hasattr(_local, "scopes"):
        _local.scopes = []
    return _local.scopes


def refuse(effect: str, detail: str, *, origin: str):
    scopes = _scopes()
    row = {"effect": effect, "detail": str(detail)[:500], "origin": origin, "pid": os.getpid(),
           "test": os.environ.get("PYTEST_CURRENT_TEST", "collection/session"),
           "expected": bool(scopes) and (not scopes[-1] or effect in scopes[-1])}
    with _lock:
        _refusals.append(row)
    raise EffectRefused(f"refused in routine verification: {effect}: {detail} (needs owner authorization; GATE.md)")


def refusals() -> list[dict]:
    with _lock:
        return [dict(row) for row in _refusals]


def unexpected() -> list[dict]:
    return [row for row in refusals() if not row.get("expected")]


@contextlib.contextmanager
def expected_refusals(*effects: str):
    """For synthetic negative controls only: refusals of ``effects`` (any effect when none is named) made on this thread
    inside the block are recorded as expected. It grants nothing; the operation is still refused."""
    for effect in effects:
        _check(effect)
    scope = frozenset(effects)
    _scopes().append(scope)
    try:
        yield scope
    finally:
        _scopes().pop()


def _norm(path) -> str:
    return os.path.normcase(os.path.realpath(os.fspath(path)))


def own_disposable(path) -> None:
    """A disposable root of this session (its basetemp): model files there are fixtures, and a synthetic gate fixture tree
    must lie inside one. Exported to children through the environment."""
    folded = _norm(path)
    with _lock:
        if folded not in _disposable_roots:
            _disposable_roots.append(folded)
        value = os.pathsep.join(_disposable_roots)
    os.environ[DISPOSABLE_ENV] = value


def disposable(path) -> bool:
    try:
        folded = _norm(path)
    except (OSError, ValueError, TypeError):
        return False
    with _lock:
        roots = list(_disposable_roots)
    return any(folded == root or folded.startswith(root.rstrip(os.sep) + os.sep) for root in roots)


def _external(event: str, args) -> str | None:
    """The non-loopback network target of a socket audit event, or None."""
    if event == "socket.getaddrinfo":
        host = args[0]
    elif event in ("socket.connect", "socket.sendto", "socket.bind"):
        address = args[1]
        if not isinstance(address, tuple):
            return None  # an AF_UNIX path or an address family the hook cannot judge
        host = address[0] if address else None
    else:
        return None
    if isinstance(host, (bytes, bytearray)):
        host = host.decode("ascii", "replace")
    return None if host in LOOPBACK else str(host)


def _frames_match(predicate) -> bool:
    frame = sys._getframe(2)  # 0 this function, 1 the hook, 2 the frame whose operation raised the audit event
    while frame is not None:
        if predicate(frame.f_code.co_filename):
            return True
        frame = frame.f_back
    return False


def _model_loader(filename: str) -> bool:
    folded = filename.replace("\\", "/").lower()
    return any(f"/site-packages/{library}/" in folded for library in MODEL_LIBRARIES)


_AUDITED = frozenset({"open", "ctypes.dlsym", "socket.connect", "socket.getaddrinfo", "socket.sendto", "socket.bind",
                      "os.startfile"})


def _hook(event: str, args) -> None:
    if event not in _AUDITED:
        return
    if event == "open":
        path = args[0]
        if isinstance(path, str) and path.lower().endswith(WEIGHTS):
            mode = args[1] if len(args) > 1 and isinstance(args[1], str) else "r"
            if not any(flag in mode for flag in "wax+") and not disposable(path) and _frames_match(_model_loader):
                refuse("real-engine", f"a model library reading real weights ({os.path.basename(path)})", origin=event)
    elif event.startswith("socket."):
        target = _external(event, args)
        if target is not None:
            refuse("external-network", f"{event} to {target[:120]}", origin=event)
    elif event == "ctypes.dlsym":
        name = args[1] if len(args) > 1 else None
        owner = os.path.normcase(str(REPO_ROOT / NATIVE_INPUT_OWNER))
        if isinstance(name, str) and name in NATIVE_INPUT and \
                not _frames_match(lambda filename: os.path.normcase(filename) == owner):
            refuse("native-desktop", f"resolving the native input function {name}", origin=event)
    elif event == "os.startfile":
        refuse("native-desktop", f"os.startfile({str(args[0])[:200]!r}) hands a file to the desktop", origin=event)


def install() -> None:
    """Make this process a routine verification process. Idempotent; called before test modules are imported."""
    global _installed
    scrub()
    if not (os.environ.get(CONTEXT_ENV) == ROUTINE and os.environ.get(ROOT_ENV)):
        os.environ[ROOT_ENV] = os.path.realpath(REPO_ROOT)  # a nested session keeps the outermost marked checkout
    os.environ[CONTEXT_ENV] = ROUTINE
    with _lock:
        if _installed:
            return
        _installed = True
    sys.modules.setdefault("routine_effects", sys.modules.get(__name__))
    sys.addaudithook(_hook)


def in_routine_context(environ=None) -> bool:
    return context.in_routine(environ)


def refuse_under_routine(entry: str, argv=None, *, data_only=frozenset(), origin=None) -> None:
    """For a real test driver's ``__main__``: refuse to start inside routine verification, wherever it lies. Data-only
    shapes stay usable. Exits ``REFUSED_EXIT``."""
    origin = sys.argv[0] if origin is None else origin
    role = context.launch_role(origin) if origin else None
    context.refuse_under_routine(entry, role[1] if role else "real-app-launch", argv, data_only=data_only, origin=origin,
                                 root=REPO_ROOT)
