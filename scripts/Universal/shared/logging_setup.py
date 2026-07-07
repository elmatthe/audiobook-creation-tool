"""Per-session file logging for the Audiobook Creation Tool.

Writes a timestamped log under ``files/runtime-data/logs/`` so a non-technical user can
attach a log file when reporting a bug. Old session logs are pruned to keep the
most recent ``MAX_SESSIONS``.
"""

from __future__ import annotations

import logging
from datetime import datetime

from . import paths

MAX_SESSIONS = 30
_LOGGER_NAME = "audiobook_tool"
_configured = False


def _prune_old_logs(keep: int = MAX_SESSIONS) -> None:
    logs = sorted(paths.LOGS_DIR.glob("session_*.log"))
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
