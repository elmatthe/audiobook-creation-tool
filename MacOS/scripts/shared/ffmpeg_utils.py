"""Locating ffmpeg/ffprobe and wiring them into pydub.

The bootstrap may install ffmpeg system-wide (winget / Homebrew) or drop a
portable build into ``resources/bin/``. This module resolves whichever is
available, preferring the bundled portable build so the app behaves the same
regardless of what is on the user's PATH.

It also configures :mod:`pydub` to use the resolved binaries. pydub shells out
to ffmpeg/ffprobe internally; pointing it at an explicit path means it never
depends on PATH and (combined with running the launcher under ``pythonw.exe``)
does not flash a console window on Windows.
"""

from __future__ import annotations

import shutil
import sys
from functools import lru_cache
from pathlib import Path

from . import paths

_EXE = ".exe" if sys.platform == "win32" else ""


def _find(binary: str) -> str | None:
    """Return a path to ``binary``, preferring the bundled portable build.

    Order: ``resources/bin/`` (bundled) → system PATH. Returns ``None`` if the
    binary cannot be found anywhere.
    """
    bundled = paths.BIN_DIR / f"{binary}{_EXE}"
    if bundled.exists():
        return str(bundled)
    found = shutil.which(binary)
    return found


@lru_cache(maxsize=None)
def ffmpeg_path() -> str | None:
    """Resolved path to the ffmpeg binary, or ``None`` if unavailable."""
    return _find("ffmpeg")


@lru_cache(maxsize=None)
def ffprobe_path() -> str | None:
    """Resolved path to the ffprobe binary, or ``None`` if unavailable."""
    return _find("ffprobe")


def have_ffmpeg() -> bool:
    """True when both ffmpeg and ffprobe are resolvable."""
    return ffmpeg_path() is not None and ffprobe_path() is not None


def ffmpeg_cmd() -> str:
    """ffmpeg path for building command lists; falls back to the bare name."""
    return ffmpeg_path() or "ffmpeg"


def ffprobe_cmd() -> str:
    """ffprobe path for building command lists; falls back to the bare name."""
    return ffprobe_path() or "ffprobe"


_pydub_configured = False


def configure_pydub() -> None:
    """Point pydub at the resolved ffmpeg/ffprobe binaries.

    Safe to call repeatedly and safe to call when pydub is not installed (it
    simply does nothing). Call this once at tool/launcher startup, before any
    ``AudioSegment`` operation.
    """
    global _pydub_configured
    if _pydub_configured:
        return
    ff = ffmpeg_path()
    fp = ffprobe_path()
    try:
        from pydub import AudioSegment
        from pydub import utils as pydub_utils

        if ff:
            AudioSegment.converter = ff
            AudioSegment.ffmpeg = ff
        if fp:
            AudioSegment.ffprobe = fp
            # pydub probes media via ffprobe; pin the name so it does not
            # re-scan PATH (and so it uses our bundled copy when present).
            pydub_utils.get_prober_name = lambda: fp  # type: ignore[assignment]
    except Exception:
        # pydub not importable (e.g. running a non-TTS tool) — nothing to do.
        pass
    _pydub_configured = True
