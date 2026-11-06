"""What a pytest session actually did, recorded from inside it, for the verification gate to reconcile.

Inert unless the gate names a file in ``ACT_GATE_PROBE``. The gate cannot see inside its child: an exit status can be
masked and a JUnit file can be stale or thin. This writes a second, independent record as the session runs: the session's
own identity, what was collected and deselected, every setup/call/teardown result, the exit status pytest itself decided,
and the Windows error mode at each test boundary.

The variable is removed as soon as it is read, so a pytest started by a test never writes into the gate's record, and the
file is opened for exclusive creation, so a stale record cannot be appended to or mistaken for this session's.

The error mode is re-raised here because the mode is one word that code in this process saves and restores around calls,
without any atomic update (``helpers/winproc.py`` in the gate explains how a run came to lose a flag for good). A drift is
recorded and repaired at the next boundary. Loading only the conftest, not the gate, keeps this usable under the guarded
runner, whose isolated interpreter never sees the gate's own directory.
"""

from __future__ import annotations

import json
import os
import sys

PROBE_ENV = "ACT_GATE_PROBE"
TOKEN_ENV = "ACT_GATE_TOKEN"
REQUIRED_ERROR_MODE = 0x8003
_PLUGIN_NAME = "act-gate-session-probe"


def _mode_functions():
    if sys.platform != "win32":
        return None, None
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32")
    return kernel32.GetErrorMode, kernel32.SetErrorMode


class SessionProbe:
    def __init__(self, path: str, token: str) -> None:
        self._sink = open(path, "x", encoding="utf-8", newline="\n")
        self._get_mode, self._set_mode = _mode_functions()
        self._write({"e": "session-start", "token": token, "pid": os.getpid(), "ppid": os.getppid(),
                     "argv": sys.argv[1:], "python": sys.version.split()[0], "mode": self._mode_text()})

    def _write(self, row: dict) -> None:
        self._sink.write(json.dumps(row, ensure_ascii=False) + "\n")
        self._sink.flush()

    def _mode_text(self) -> str | None:
        return None if self._get_mode is None else hex(self._get_mode())

    def _check_mode(self, where: str) -> None:
        if self._get_mode is None:
            return
        found = int(self._get_mode())
        if found & REQUIRED_ERROR_MODE != REQUIRED_ERROR_MODE:
            self._set_mode(found | REQUIRED_ERROR_MODE)
            self._write({"e": "mode-drift", "where": where, "found": hex(found), "restored": hex(self._get_mode())})

    def pytest_collectreport(self, report) -> None:
        if report.failed:
            self._write({"e": "collect-error", "id": report.nodeid, "detail": str(report.longrepr)[-2000:]})
        elif report.skipped:
            self._write({"e": "collect-skip", "id": report.nodeid, "reason": _skip_reason(report)})

    def pytest_deselected(self, items) -> None:
        self._write({"e": "deselected", "ids": [item.nodeid for item in items]})

    def pytest_collection_finish(self, session) -> None:
        self._write({"e": "collected", "ids": [item.nodeid for item in session.items]})

    def pytest_runtest_logstart(self, nodeid, location) -> None:
        self._check_mode(nodeid)

    def pytest_runtest_logreport(self, report) -> None:
        row = {"e": "r", "id": report.nodeid, "w": report.when, "o": report.outcome, "d": round(report.duration, 3)}
        if report.skipped:
            row["reason"] = _skip_reason(report)
        if hasattr(report, "wasxfail"):
            row["xfail"] = str(report.wasxfail)[:500]
        self._write(row)

    def pytest_sessionfinish(self, session, exitstatus) -> None:
        self._check_mode("session-finish")
        self._write({"e": "session-finish", "exit": int(exitstatus), "mode": self._mode_text()})

    def pytest_unconfigure(self, config) -> None:
        self._sink.close()


def _skip_reason(report) -> str:
    longrepr = report.longrepr
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        return str(longrepr[2]).removeprefix("Skipped: ")
    return str(longrepr)


def register(config) -> None:
    """Called once from conftest's ``pytest_configure``. Does nothing outside a gate stage."""
    path = os.environ.pop(PROBE_ENV, None)
    token = os.environ.pop(TOKEN_ENV, "")
    if path and not config.pluginmanager.has_plugin(_PLUGIN_NAME):
        config.pluginmanager.register(SessionProbe(path, token), _PLUGIN_NAME)
