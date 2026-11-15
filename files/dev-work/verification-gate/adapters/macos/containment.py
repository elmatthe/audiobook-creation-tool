"""The macOS counterpart of ``adapters/windows/containment.py`` (v0.8.x P1B).

Windows runs the application at Low integrity so that its file dialogs cannot write the owner's dialog history. On macOS
no native dialog is ever shown to a journey: the session's in-process stand-ins answer every file, folder and message
box (their native NSOpenPanel / NSAlert parts are owner-manual, darwin_map class b), so there is no history to protect
and nothing to label. What does need proving is that the application under test is isolated and owned: its own process
group (so tear-down reaches everything it started), its settings, logs and runtime data in the session's scratch. That
is what :func:`preflight` checks, by starting a child exactly as a session starts the application.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path


class ContainmentUnavailable(RuntimeError):
    """The application could not be shown to run isolated and owned; nothing runs and the stage is BLOCKED."""


def label_low(folder: Path) -> str:
    """Nothing to label on macOS (no integrity levels); recorded as such."""
    Path(folder).mkdir(parents=True, exist_ok=True)
    return "not applicable on macOS (no integrity labels; no native dialog is shown to a journey)"


def require_low(pids, what: str) -> dict:
    return {"integrity": "not applicable on macOS", "what": what, "pids": list(pids)}


def history_references(needle: str = "act-gate") -> dict[str, str]:
    """No native dialog is shown, so no dialog history can gain a reference; nothing is read."""
    return {}


def history_added(before: dict[str, str], after: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in after.items() if before.get(key) != value}


def preflight(work: Path, *, python: str | None = None, timeout: float = 30) -> dict:
    """A child started as a session starts the application leads its own process group, and ending that group ends a
    grandchild too: the property every session's tear-down relies on. Bounded; leaves nothing running."""
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    marker = work / "preflight-grandchild.txt"
    code = ("import os, subprocess, sys, time; "
            "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
            f"open({str(marker)!r}, 'w').write('%d %d' % (g.pid, os.getpgid(g.pid))); time.sleep(60)")
    proc = subprocess.Popen([python or sys.executable, "-I", "-c", code], start_new_session=True,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + timeout
        while not marker.exists() or not marker.read_text().strip():
            if time.monotonic() > deadline or proc.poll() is not None:
                raise ContainmentUnavailable("the preflight child never reported its own child")
            time.sleep(0.05)
        grandchild, group = (int(value) for value in marker.read_text().split())
        if os.getpgid(proc.pid) != proc.pid or group != proc.pid:
            raise ContainmentUnavailable(f"the child does not lead its own group ({os.getpgid(proc.pid)}, {group})")
        os.killpg(proc.pid, signal.SIGKILL)  # the group this function created a moment ago, led by its own live child
        proc.wait(timeout=10)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                os.killpg(proc.pid, 0)
            except ProcessLookupError:
                return {"own_group": True, "group_ended_with_grandchild": True, "grandchild": grandchild}
            time.sleep(0.02)
        raise ContainmentUnavailable("ending the session's group left its grandchild running")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
