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
