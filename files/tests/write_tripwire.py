"""A write boundary for tests: refuse, before it happens, any write-capable filesystem operation on protected paths.

v0.7.0 P05B Stage 2, Task A. ``conftest._no_production_state_writes`` notices a production change *after* a test, by
fingerprint. That cannot undo a write. In P05B Stage 1 a test called ``monkeypatch.undo()``, which also undid the
sandbox's ``rt.repo_root`` redirect, and its next line ran ``mkdir`` on the real ``.venv/engines/qwen3`` -- refused only
because the folder already existed. Tests that drive real acquisition code (downloads, pip, model records) need the
refusal at the write itself.

An audit hook (``sys.addaudithook``, installed once per process and inert unless armed) sees every ``open`` with a
write, create, truncate or append flag, and every ``mkdir``, ``rename``/``replace``, ``remove``/``unlink``, ``rmdir``,
``link``, ``symlink``, ``truncate``, ``utime``, ``chmod``, ``shutil.rmtree`` and ``shutil.copyfile`` destination. When
armed, an operation whose target -- lexically, or after resolving links on its way -- lies inside a protected root
raises ``PermissionError`` before it runs and is recorded. Reads are never refused. Python's own bytecode caching
treats that ``PermissionError`` as "cannot write the cache" and carries on, as it does on a read-only folder; such a
refusal is retained raw. Only calls from CPython's frozen bytecode writer are classified as bytecode; a directory
named ``__pycache__`` is not evidence of a Python bytecode write (Numba also uses it).
"""

from __future__ import annotations

import os
import sys
import threading
import traceback
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator

_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
#: event -> positions of the path arguments that are written to
_PATH_EVENTS = {
    "os.mkdir": (0,), "os.rename": (0, 1), "os.replace": (0, 1), "os.remove": (0,), "os.rmdir": (0,),
    "os.link": (1,), "os.symlink": (1,), "os.truncate": (0,), "os.utime": (0,), "os.chmod": (0,),
    "shutil.rmtree": (0,), "shutil.copyfile": (1,), "shutil.copymode": (1,), "shutil.copystat": (1,),
}

_state = threading.local()
_armed: list[tuple[str, ...]] = []  # a stack of protected-root sets (normalised)
refusals: list[tuple[str, str]] = []
bytecode_refusals: set[int] = set()
refusal_details: list[dict] = []
_installed = False


def _norm(path: str) -> str:
    return os.path.normcase(os.path.abspath(path)).rstrip("\\/")


def _inside(path: str, roots: tuple[str, ...]) -> bool:
    return any(path == root or path.startswith(root + os.sep) for root in roots)


def _resolved(path: str) -> str:
    """*path* with links resolved on the part of it that exists (a junction in a sandbox pointing at production)."""
    probe, tail = path, []
    while probe and not os.path.lexists(probe):
        probe, name = os.path.split(probe)
        if not name:
            break
        tail.append(name)
    try:
        real = os.path.realpath(probe) if probe else probe
    except OSError:
        real = probe
    return _norm(os.path.join(real, *reversed(tail)))


def _check(event: str, target) -> None:
    if isinstance(target, int) or target is None:
        return  # a file descriptor: its open was already checked
    try:
        text = os.fsdecode(os.fspath(target))
    except TypeError:
        return
    roots = tuple(root for layer in _armed for root in layer)
    lexical = _norm(text)
    resolved = _resolved(lexical)
    if _inside(lexical, roots) or _inside(resolved, roots):
        bytecode = is_bytecode_cache(text) and _python_bytecode_writer()
        if bytecode:
            bytecode_refusals.add(len(refusals))
        refusals.append((event, text))
        # Capture the resolved path now: a junction may disappear before reporting.
        refusal_details.append({"event": event, "path": text, "lexical": lexical, "resolved": resolved,
                                "bytecode": bytecode, "test": os.environ.get("PYTEST_CURRENT_TEST", "collection/session"),
                                "stack": traceback.format_stack(limit=24)})
        raise PermissionError(f"write tripwire: {event} on protected path {text}")


def is_bytecode_cache(path: str) -> bool:
    """Candidate only: callers must also prove the frozen CPython writer on the stack."""
    return "__pycache__" in Path(path).parts and (Path(path).name == "__pycache__" or ".pyc" in Path(path).name)


def _python_bytecode_writer() -> bool:
    frame = sys._getframe(1)
    while frame is not None:
        if frame.f_code.co_filename == "<frozen importlib._bootstrap_external>" and \
                frame.f_code.co_name in ("_write_atomic", "set_data"):
            return True
        frame = frame.f_back
    return False


def _hook(event: str, args) -> None:
    if not _armed or getattr(_state, "busy", False):
        return
    _state.busy = True  # realpath and friends must not re-enter the hook
    try:
        if event == "open":
            path, mode, flags = (tuple(args) + (None, None, None))[:3]
            writes = (isinstance(flags, int) and flags & _WRITE_FLAGS) or \
                (isinstance(mode, str) and any(c in mode for c in "wax+"))
            if writes:
                _check(event, path)
        elif event in _PATH_EVENTS:
            for index in _PATH_EVENTS[event]:
                if index < len(args):
                    _check(event, args[index])
    finally:
        _state.busy = False


def install() -> None:
    global _installed
    if not _installed:
        sys.addaudithook(_hook)
        _installed = True


@contextmanager
def armed(roots: Iterable[Path]) -> Iterator[list[tuple[str, str]]]:
    """Refuse writes under *roots* for the duration; yields (filled in at the end) the refusals of writes under *these*
    roots -- a nested layer's own deliberate refusals (a synthetic negative control) are not this layer's."""
    install()
    layer = tuple(_norm(str(root)) for root in roots)
    start = len(refusals)
    _armed.append(layer)
    seen: list[tuple[str, str]] = []
    try:
        yield seen
    finally:
        _armed.remove(layer)

        def mine(path: str) -> bool:
            lexical = _norm(path)
            return _inside(lexical, layer) or _inside(_resolved(lexical), layer)
        seen.extend(item for index, item in enumerate(refusals[start:], start)
                    if index not in bytecode_refusals and mine(item[1]))
