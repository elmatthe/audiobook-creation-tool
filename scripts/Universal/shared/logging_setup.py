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


def get_logger() -> logging.Logger:
    """Return the shared application logger, configuring it on first call."""
    global _configured
    logger = logging.getLogger(_LOGGER_NAME)
    if _configured:
        return logger

    paths.logs_dir()  # ensure the directory exists
    log_file = paths.LOGS_DIR / f"session_{datetime.now():%Y-%m-%d_%H%M%S}.log"

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
