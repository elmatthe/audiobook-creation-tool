"""Subprocess wrappers that suppress console windows on Windows.

Every external-binary call in the application (ffmpeg, ffprobe, etc.) must go
through :func:`run` or :func:`popen` so that no console window flashes when the
app is launched from the GUI (under ``pythonw.exe``).

On non-Windows platforms these are thin pass-throughs to ``subprocess``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def _hidden_kwargs() -> dict[str, Any]:
    """Return kwargs that hide the console window on Windows; empty elsewhere."""
    if sys.platform != "win32":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "startupinfo": startupinfo,
        "creationflags": subprocess.CREATE_NO_WINDOW,
    }


def run(cmd, **kwargs) -> subprocess.CompletedProcess:
    """Drop-in replacement for ``subprocess.run`` with hidden console on Windows.

    Caller-supplied kwargs win over the hidden-window defaults so that explicit
    ``startupinfo``/``creationflags`` are still honoured if ever needed.
    """
    return subprocess.run(cmd, **{**_hidden_kwargs(), **kwargs})


def popen(cmd, **kwargs) -> subprocess.Popen:
    """Drop-in replacement for ``subprocess.Popen`` with hidden console on Windows."""
    return subprocess.Popen(cmd, **{**_hidden_kwargs(), **kwargs})


def check_output(cmd, **kwargs) -> bytes | str:
    """Drop-in replacement for ``subprocess.check_output`` with hidden console."""
    return subprocess.check_output(cmd, **{**_hidden_kwargs(), **kwargs})


_POPEN_PATCHED = False


def install_no_window_guard() -> None:
    """Force *every* child process on Windows to spawn without a console window.

    The app's own ffmpeg/ffprobe calls already go through :func:`run` /
    :func:`popen`, but pydub and edge-tts spawn ffmpeg through their *own*
    internal ``subprocess.Popen`` calls, which bypass those wrappers. During the
    TTS combine stage pydub exports/concatenates dozens of segments, flashing a
    console window for each one. This wraps ``subprocess.Popen`` itself so those
    internal spawns also inherit the hidden-window flags from
    :func:`_hidden_kwargs` — the one chokepoint every child process passes
    through, regardless of who calls it.

    No-op on non-Windows. Idempotent. Must be called once at startup, *before*
    pydub/edge-tts are imported, so a ``from subprocess import Popen`` inside
    those libraries binds to the wrapped class.
    """
    global _POPEN_PATCHED
    if _POPEN_PATCHED or sys.platform != "win32":
        return

    _original_popen = subprocess.Popen

    class _NoWindowPopen(_original_popen):  # type: ignore[valid-type, misc]
        def __init__(self, *args, **kwargs):
            hidden = _hidden_kwargs()
            # OR our hidden-window creationflags into anything the caller passed
            # so an explicit flag is preserved rather than clobbered.
            kwargs["creationflags"] = (
                kwargs.get("creationflags", 0) | hidden["creationflags"]
            )
            # Only inject the hidden STARTUPINFO when the caller supplied none;
            # our own wrappers already pass one.
            if kwargs.get("startupinfo") is None:
                kwargs["startupinfo"] = hidden["startupinfo"]
            super().__init__(*args, **kwargs)

    subprocess.Popen = _NoWindowPopen  # type: ignore[misc]
    _POPEN_PATCHED = True


def reveal_in_file_manager(path) -> None:
    """Open ``path`` in the OS file manager without flashing a console window.

    Uses ``os.startfile`` on Windows (no console), ``open`` on macOS, and
    ``xdg-open`` on Linux. Never raises — opening a folder is a convenience, not
    a critical operation.
    """
    target = str(Path(path))
    try:
        if sys.platform == "win32":
            os.startfile(target)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            popen(["open", target])
        else:
            popen(["xdg-open", target])
    except Exception:
        pass
