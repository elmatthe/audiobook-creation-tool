"""A window that dies as it starts is reported, not hidden (v0.7.2 Phase 8, ACT72-055).

``bootstrap.launch_gui`` starts the application detached, with its output captured in ``launch_<date>.log``, then
watches the new process for a short grace window. If it has already exited with an error the launch is reported as
failed, with the last lines of what the window said. Every earlier test replaced ``subprocess.Popen`` with a process
that never exits, so that branch had never run.

Here the child is real: a real interpreter running a real script, started by the production ``Popen`` call with its
production flags (no console, detached) and its real output redirection, and watched for the production grace. Only
which script is started, with which interpreter, and where the log folder is are given to it, so nothing is started
from or written to the real installation.
"""

from __future__ import annotations

import re
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from shared import bootstrap


class _Log:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def line(self, text: str) -> None:
        self.lines.append(text)


@pytest.fixture()
def launch(monkeypatch, tmp_path):
    """``launch_gui`` as production runs it, pointed at a script of the test's own. Returns (start, log, logs, children)."""
    target = tmp_path / "launcher.py"
    logs = tmp_path / "logs"
    children: list[subprocess.Popen] = []
    real_popen = subprocess.Popen

    def recording_popen(argv, **kwargs):
        child = real_popen(argv, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(bootstrap, "venv_python", lambda windowed=False: Path(sys.executable))
    monkeypatch.setattr(bootstrap, "_launch_target", lambda: target)
    monkeypatch.setattr(bootstrap, "LOGS_DIR", logs)
    monkeypatch.setattr(bootstrap, "SCRIPTS_DIR", tmp_path)
    monkeypatch.setattr(bootstrap, "_ffmpeg_in_bin", lambda: None)
    monkeypatch.setattr(bootstrap, "stale_layout_notice", lambda *a, **k: None)
    monkeypatch.setattr(bootstrap.subprocess, "Popen", recording_popen)
    log = _Log()

    def start(script: str) -> bool:
        target.write_text(textwrap.dedent(script), encoding="utf-8")
        return bootstrap.launch_gui(log)

    yield start, log, logs, children
    for child in children:
        if child.poll() is None:
            child.kill()
        child.wait(30)


def _launch_log(logs: Path) -> Path:
    found = list(logs.glob("launch_*.log"))
    assert len(found) == 1 and re.fullmatch(r"launch_\d{4}-\d{2}-\d{2}\.log", found[0].name), found
    return found[0]


def test_the_grace_window_is_the_documented_one_and_a_half_seconds():
    assert bootstrap._LAUNCH_GRACE_SECONDS == 1.5


@pytest.mark.parametrize("code", [1, 57], ids=["an-ordinary-error", "another-exit-code"])
def test_a_window_that_dies_at_once_is_a_failed_launch_that_says_what_the_window_said(launch, code):
    start, log, logs, children = launch
    began = time.monotonic()
    started = start(f"""
        import sys
        print("starting the window")
        sys.stderr.write("Traceback (most recent call last):\\n")
        sys.stderr.write("ModuleNotFoundError: No module named 'tkinter'\\n")
        sys.stderr.flush()
        raise SystemExit({code})
        """)
    took = time.monotonic() - began
    assert started is False, "a launch whose window is already dead must not be reported as started"
    assert bootstrap._LAUNCH_GRACE_SECONDS <= took < bootstrap._LAUNCH_GRACE_SECONDS + 5
    child, = children
    assert child.returncode == code

    launch_log = _launch_log(logs)
    text = "\n".join(log.lines)
    assert f"  ERROR: the app window failed to start (exited with code {code})." in log.lines
    assert f"  --- last lines of {launch_log.name} ---" in log.lines and "  --- end ---" in log.lines
    assert "    ModuleNotFoundError: No module named 'tkinter'" in log.lines, text
    assert "    starting the window" in log.lines, "what it printed before it died is quoted too"
    assert f"  Full launch log: {launch_log}" in log.lines
    assert log.lines.index(f"  --- last lines of {launch_log.name} ---") < log.lines.index("  --- end ---")

    captured = launch_log.read_text(encoding="utf-8")
    assert re.search(r"===== Launch \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} : .*launcher\.py =====", captured)
    assert "ModuleNotFoundError: No module named 'tkinter'" in captured and "starting the window" in captured


def test_only_the_end_of_a_long_crash_is_quoted_and_the_log_file_keeps_all_of_it(launch):
    start, log, logs, _children = launch
    assert start("""
        import sys
        for number in range(1, 61):
            print(f"line {number:02d} of the crash")
        sys.exit(2)
        """) is False
    quoted = [line.strip() for line in log.lines if "of the crash" in line]
    assert quoted == [f"line {number:02d} of the crash" for number in range(36, 61)], "the last 25 lines, in order"
    kept = _launch_log(logs).read_text(encoding="utf-8")
    assert all(f"line {number:02d} of the crash" in kept for number in range(1, 61))


def test_a_window_still_running_after_the_grace_is_a_started_launch(launch):
    start, log, logs, children = launch
    assert start("""
        import time
        print("window is up", flush=True)
        time.sleep(120)
        """) is True
    child, = children
    assert child.poll() is None, "the launch left the window running; it never waits for it or stops it"
    assert not any("ERROR" in line for line in log.lines), log.lines
    assert any(line.startswith("Launching launcher.py via ") and _launch_log(logs).name in line for line in log.lines)
    assert "window is up" in _launch_log(logs).read_text(encoding="utf-8")


def test_a_window_that_closes_cleanly_inside_the_grace_is_not_called_a_crash(launch):
    """Exit code 0 is a person closing the window at once (or a script with nothing to do), never a failure."""
    start, log, _logs, children = launch
    assert start("print('nothing to do')") is True
    child, = children
    assert child.returncode == 0
    assert not any("ERROR" in line for line in log.lines)


def test_a_crash_after_the_grace_is_outside_what_the_launch_can_report(launch, monkeypatch):
    """The grace is a window, not a watch: the launching process has gone by then. What the window said is still in
    the launch log, which is where a later failure is found."""
    monkeypatch.setattr(bootstrap, "_LAUNCH_GRACE_SECONDS", 0.5)
    start, log, logs, children = launch
    assert start("""
        import sys, time
        time.sleep(1.5)
        print("late failure", flush=True)
        sys.exit(9)
        """) is True
    child, = children
    assert child.wait(30) == 9
    assert not any("ERROR" in line for line in log.lines)
    assert "late failure" in _launch_log(logs).read_text(encoding="utf-8")


def test_a_missing_window_script_or_interpreter_is_a_failed_launch_before_anything_starts(launch, monkeypatch, tmp_path):
    _start, log, logs, children = launch
    assert bootstrap.launch_gui(log) is False, "no launcher.py was written for this test"
    assert any("no GUI to launch" in line for line in log.lines)
    (tmp_path / "launcher.py").write_text("print('never run')", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "venv_python", lambda windowed=False: tmp_path / "no-such-python.exe")
    assert bootstrap.launch_gui(log) is False
    assert any("venv interpreter missing" in line for line in log.lines)
    assert children == [] and not logs.exists(), "nothing was started and no log was opened"
