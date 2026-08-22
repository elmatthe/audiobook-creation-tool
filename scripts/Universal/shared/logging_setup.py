"""Per-session file logging for the Audiobook Creation Tool.

Writes a timestamped log under ``files/runtime-data/logs/`` so a non-technical user can
attach a log file when reporting a bug. Old session logs are pruned to keep the
most recent ``logging.max_sessions`` sessions, which is configurable in the
committed root ``config.toml``.

**Why the configuration import is inside the function.** ``shared.config``
produces diagnostics that callers log, so if this module imported it at module
scope the two would depend on each other in a circle. Retention therefore reads
the configuration lazily, and any failure at all — a missing file, a malformed
one, an import problem — falls back to :data:`DEFAULT_MAX_SESSIONS` rather than
letting logging fail to start. Logging must always come up.
"""

from __future__ import annotations

import faulthandler
import logging
from datetime import datetime
from pathlib import Path

from . import paths

#: The floor used whenever configuration cannot be consulted.
DEFAULT_MAX_SESSIONS = 30

#: Kept as the historical public name for the code default. The value actually
#: applied at runtime comes from the effective configuration.
MAX_SESSIONS = DEFAULT_MAX_SESSIONS

_LOGGER_NAME = "audiobook_tool"
_configured = False

#: This session's log file, remembered so the fatal-diagnostics handle below can
#: append to the very same file the user is asked to attach to a bug report.
_session_log_path: Path | None = None

#: Deliberately process-lifetime state. ``faulthandler`` writes through a raw file
#: descriptor at the moment of a fatal fault, so the handle it is given must still
#: be open then — which means *not* the logging handler's stream, because
#: ``logging.shutdown()`` closes that at interpreter exit.
_fatal_stream = None


def configured_max_sessions() -> int:
    """Retention from the effective configuration, or the safe default.

    Never raises: logging startup must not depend on configuration succeeding.
    """
    try:
        from . import config  # local import — see the module docstring

        return config.get_effective().logging.max_sessions
    except Exception:
        return DEFAULT_MAX_SESSIONS


def _prune_old_logs(keep: int | None = None, logs_dir: Path | None = None) -> None:
    if keep is None:
        keep = configured_max_sessions()
    directory = paths.LOGS_DIR if logs_dir is None else Path(logs_dir)
    logs = sorted(directory.glob("session_*.log"))
    for old in logs[:-keep] if len(logs) > keep else []:
        try:
            old.unlink()
        except OSError:
            pass


def session_log_path() -> Path | None:
    """This session's log file, or ``None`` before :func:`get_logger` has run."""
    return _session_log_path


def get_logger() -> logging.Logger:
    """Return the shared application logger, configuring it on first call."""
    global _configured, _session_log_path
    logger = logging.getLogger(_LOGGER_NAME)
    if _configured:
        return logger

    paths.logs_dir()  # ensure the directory exists
    log_file = paths.LOGS_DIR / f"session_{datetime.now():%Y-%m-%d_%H%M%S}.log"
    _session_log_path = log_file

    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    _prune_old_logs()
    _configured = True
    logger.debug("Logging initialised -> %s", log_file)
    return logger


def fatal_diagnostics_armed() -> bool:
    """Whether a fatal-fault dump is currently wired to this session's log."""
    return _fatal_stream is not None


def enable_fatal_diagnostics(*, faulthandler_module=None) -> bool:
    """Make a *native* crash leave a Python traceback in this session's log.

    A fatal fault inside a native extension — the access violation inside
    ``torch_cpu.dll`` recorded in Phase 12 is the real example — kills the process
    outright. No ``except`` clause runs, no handler flushes, and the session log
    simply stops mid-sentence, which is exactly what made that crash so expensive
    to investigate. ``faulthandler`` is the standard library's answer: it installs
    handlers (including, on Windows, one for structured exceptions such as an
    access violation) that dump every thread's Python frames before the process
    dies. That names the engine call that was in flight.

    This is **observation only**. It changes no engine, no threading, no torch
    setting and nothing a user can see — it only means the next occurrence arrives
    with evidence attached.

    Called once during GUI start-up, after logging exists and long before any
    conversion worker can run. Safe to call again: the second call is a no-op
    rather than a second open handle, so nothing stacks and nothing leaks.

    Returns ``True`` when armed. **Never raises** — diagnostics that could stop the
    application from opening would be worse than no diagnostics at all, so any
    failure is reported through the logger and swallowed.

    ``faulthandler_module`` exists so the suite can prove the wiring without a test
    that has to kill the interpreter to observe it.
    """
    global _fatal_stream

    if _fatal_stream is not None:
        return True

    module = faulthandler if faulthandler_module is None else faulthandler_module
    logger = get_logger()
    try:
        destination = _session_log_path
        if destination is None:  # pragma: no cover - get_logger always sets it
            raise RuntimeError("no session log file to write fatal diagnostics to")
        # Our own append handle, not the logging handler's stream: line-buffered so
        # ordinary log lines around it stay readable, and never closed, because the
        # descriptor has to survive until the process really ends.
        stream = open(destination, "a", buffering=1, encoding="utf-8")
        try:
            module.enable(file=stream, all_threads=True)
        except Exception:
            stream.close()
            raise
        _fatal_stream = stream
        logger.debug("Fatal-fault diagnostics armed -> %s", destination)
        return True
    except Exception as exc:  # noqa: BLE001 - startup must survive this
        try:
            logger.warning(
                "configuration: [warning] fatal-fault diagnostics could not be "
                "armed (%r); the application continues without them", exc)
        except Exception:  # pragma: no cover - logging itself is broken
            pass
        return False


def disable_fatal_diagnostics() -> None:
    """Undo :func:`enable_fatal_diagnostics`, closing the one handle it opened.

    The application does not call this — the handle is meant to outlive everything
    else in the process — but it keeps arming symmetrical and lets the suite return
    to a clean state.
    """
    global _fatal_stream

    stream, _fatal_stream = _fatal_stream, None
    if stream is None:
        return
    try:
        faulthandler.disable()
    finally:
        try:
            stream.close()
        except Exception:  # pragma: no cover - nothing useful to do
            pass
