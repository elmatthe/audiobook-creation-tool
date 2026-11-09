"""Closing the first-run setup window — v0.7.2 Phase 6, ACT72-038 and ACT72-039.

**ACT72-039.** Closing the window during the base install ended the process with no close handler: the pip child that
``bootstrap._pip`` had started with a bare ``Popen`` kept running, owned by nobody, still writing into the app's
environment. Now the running pip is registered, the window asks "Stop setup?" first, and Yes ends exactly that pip and
everything it started (``taskkill /T`` from its own process id, which cannot be reused while its handle is held), no later
step starts, and the window closes once the setup's worker has reported.

**ACT72-038.** After the base install, answering No to "Stop setup?" still cancelled the optional-voice check or
install: the panel's cancel flag was set before the question was asked, and the cancelled outcome then launched the app
and closed the window. Now No leaves the running step alone.

The window is the real one (``run_with_gui``: its widgets, its worker thread, its queue and poll), made a Toplevel of
the suite's one interpreter whose main loop is this test's script, as ``test_setup_log_follow.py`` does. The window's
own close handler is invoked through the protocol command the window registered, which is what the window manager
calls when the X is clicked; the question's answer is supplied by replacing ``messagebox.askyesno``. No OS dialog or
mouse click is driven here. "pip" is a stand-in Python that prints the way pip does and starts a grandchild, so a real
process tree is stopped; nothing is installed. An unrelated Python process started by the test must survive.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")
from tkinter import messagebox, ttk  # noqa: E402  (run_with_gui imports this module's functions)

from shared import bootstrap  # noqa: E402
from shared import optional_setup_panel  # noqa: E402
from shared import optional_setup_protocol as proto  # noqa: E402
from shared import work_area  # noqa: E402

from test_setup_log_follow import (  # noqa: E402,F401  (fixtures are collected by name)
    WAIT,
    descendants,
    native_theme,
    run_as_toplevel,
    settle,
    setup_log,
    tk_root,
)

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

#: Says who it really is (the venv's python.exe is a launcher), starts a grandchild that says the same, then prints
#: pip-like lines until it is stopped.
PIP_STANDIN = r"""
import json, os, subprocess, sys, time
from pathlib import Path
barrier, scripts = sys.argv[1], sys.argv[2]
sys.path.insert(0, scripts)
from shared import work_area
GRANDCHILD = ("import json, os, sys, time; sys.path.insert(0, sys.argv[2]); from shared import work_area; "
              "from pathlib import Path; p = Path(sys.argv[1]); "
              "p.with_suffix('.new').write_text(json.dumps({'pid': os.getpid(), 'created': work_area._own_creation_time()})); "
              "os.replace(p.with_suffix('.new'), p); time.sleep(300)")
child = subprocess.Popen([sys.executable, "-c", GRANDCHILD, barrier + ".grandchild", scripts])
deadline = time.monotonic() + 60
while not Path(barrier + ".grandchild").exists() and time.monotonic() < deadline:
    time.sleep(0.02)
me = {"pid": os.getpid(), "created": work_area._own_creation_time(),
      "grandchild": json.loads(Path(barrier + ".grandchild").read_text())}
Path(barrier + ".new").write_text(json.dumps(me))
os.replace(barrier + ".new", barrier)
i = 0
while True:
    print(f"Collecting package-{i}==1.0", flush=True)
    i += 1
    time.sleep(0.2)
"""


@pytest.fixture(autouse=True)
def no_leftover_stop():
    """The stop request is the setup process's own; each test starts and ends without one."""
    bootstrap.clear_setup_stop()
    yield
    bootstrap.clear_setup_stop()


@pytest.fixture
def sentinel():
    """An unrelated Python process. Nothing here may stop it."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"], creationflags=NO_WINDOW)
    yield proc
    proc.kill()
    proc.wait(30)


def wait_for(path: Path) -> dict:
    deadline = time.monotonic() + WAIT
    while not path.exists():
        assert time.monotonic() < deadline, f"never appeared: {path}"
        time.sleep(0.02)
    return json.loads(path.read_text())


def state(identity: dict) -> str:
    return work_area.owner_state({"pid": identity["pid"], "created": identity["created"]})


def end_standin(ids: dict) -> None:
    """Whatever this test's stand-in left (only if the code under test failed): exactly those two processes, each by
    its process id *and* creation time, never a process found by name."""
    for identity in (ids, ids["grandchild"]):
        if state(identity) == work_area.ALIVE:
            subprocess.run(["taskkill", "/PID", str(identity["pid"]), "/F"], capture_output=True, timeout=30)


def standin(tmp_path: Path) -> tuple[list[str], Path]:
    barrier = tmp_path / "pip-barrier"
    return [sys.executable, "-c", PIP_STANDIN, str(barrier), str(SCRIPTS)], barrier


# --------------------------------------------------------------------------- the pip step itself (ACT72-039)


@pytest.mark.skipif(os.name != "nt", reason="the identity checks read Windows process creation times")
def test_a_stop_request_ends_the_running_pip_and_everything_it_started_and_nothing_else(tmp_path, sentinel):
    command, barrier = standin(tmp_path)
    lines: list[str] = []
    result: dict = {}
    # A daemon, and a bounded join: a stop that fails must fail this test, not hang the suite on a pipe that stays open.
    worker = threading.Thread(target=lambda: result.setdefault("code", bootstrap._pip(command, dict(os.environ), lines.append)),
                              daemon=True)
    worker.start()
    ids = wait_for(barrier)
    try:
        assert state(ids) == work_area.ALIVE and state(ids["grandchild"]) == work_area.ALIVE
        began = time.monotonic()
        assert bootstrap.request_setup_stop() is True, "a running pip was told to stop"
        worker.join(20)
        assert not worker.is_alive(), "the stop did not end pip's tree"
    finally:
        end_standin(ids)
    assert time.monotonic() - began < 10, "bounded: the job is ended, not waited out"
    assert result["code"] == bootstrap.PIP_STOPPED
    assert state(ids) == work_area.GONE, "the pip process itself"
    assert state(ids["grandchild"]) == work_area.GONE, "and what it started"
    assert sentinel.poll() is None, "an unrelated Python process is untouched"
    assert any("Collecting package-" in line for line in lines), "its output was streamed as before"
    assert any("stopped" in line for line in lines)


def test_after_a_stop_no_pip_is_started(tmp_path, monkeypatch):
    command, barrier = standin(tmp_path)
    spawned: list = []
    real_popen = bootstrap.subprocess.Popen
    monkeypatch.setattr(bootstrap.subprocess, "Popen", lambda *a, **k: spawned.append(a) or real_popen(*a, **k))
    bootstrap.request_setup_stop()
    lines: list[str] = []
    assert bootstrap._pip(command, dict(os.environ), lines.append) == bootstrap.PIP_STOPPED
    time.sleep(0.5)
    assert spawned == [], "no process was even created"
    assert not barrier.exists(), "nothing was launched"


def test_a_stop_during_the_packages_step_starts_no_later_step(monkeypatch, setup_log):
    """run_setup checks between its steps: after a stop, FFmpeg and the sentence data are not even begun."""
    calls: list[str] = []
    monkeypatch.setattr(bootstrap, "install_path_problem", lambda: None)
    monkeypatch.setattr(bootstrap, "_take_engine_lease", lambda log, refusal: (None, None))
    monkeypatch.setattr(bootstrap, "recover_interrupted_replacement", lambda log, require_tk: None)
    monkeypatch.setattr(bootstrap, "find_suitable_python", lambda log, prefer_tk: ["python"])
    monkeypatch.setattr(bootstrap, "_interp_version_argv", lambda argv: (3, 12))
    monkeypatch.setattr(bootstrap, "preflight_report", lambda argv, log: None)
    monkeypatch.setattr(bootstrap, "_create_validated_venv", lambda argv, log, headless: True)

    def reconcile(log):
        calls.append("packages")
        bootstrap.request_setup_stop()      # the person said Yes while pip ran
        return False, "pip"

    monkeypatch.setattr(bootstrap, "reconcile_requirements", reconcile)
    monkeypatch.setattr(bootstrap, "ensure_ffmpeg", lambda log: calls.append("ffmpeg") or True)
    monkeypatch.setattr(bootstrap, "fetch_sentence_data", lambda log: calls.append("sentence data") or True)
    ok, message = bootstrap.run_setup(lambda step, text: None, setup_log)
    assert (ok, message) == (False, bootstrap.SETUP_STOPPED_MESSAGE)
    assert calls == ["packages"], calls


# --------------------------------------------------------------------------- the window (ACT72-039 and ACT72-038)


def close_window(window) -> None:
    """What the window manager does when the X is clicked: call the protocol command the window registered."""
    command = window.protocol("WM_DELETE_WINDOW")
    assert command, "the window registered a close handler"
    window.tk.call(command)


def pump_for(window, seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end and window.winfo_exists():
        settle(window)
        time.sleep(0.01)


def press(window, label: str) -> None:
    button = next(w for w in descendants(window) if isinstance(w, ttk.Button) and str(w.cget("text")) == label)
    button.invoke()


@pytest.mark.skipif(os.name != "nt", reason="the identity checks read Windows process creation times")
def test_closing_during_the_base_install_asks_and_no_keeps_pip_running_then_yes_stops_it(
        monkeypatch, tk_root, setup_log, native_theme, tmp_path, sentinel):
    command, barrier = standin(tmp_path)
    seen = {"launched": 0, "questions": [], "errors": [], "answer": False}

    def run_setup(on_progress, log):
        on_progress(2, "Installing packages (largest step — please wait)…")
        if bootstrap._pip(command, dict(os.environ), log.line) == bootstrap.PIP_STOPPED:
            return False, bootstrap.SETUP_STOPPED_MESSAGE
        return True, "Setup complete."

    monkeypatch.setattr(bootstrap, "run_setup", run_setup)
    monkeypatch.setattr(bootstrap, "optional_estimates", lambda: {})
    monkeypatch.setattr(bootstrap, "launch_gui", lambda log: seen.__setitem__("launched", seen["launched"] + 1))
    monkeypatch.setattr(messagebox, "askyesno",
                        lambda title, text, **kw: seen["questions"].append((title, text)) or seen["answer"])
    monkeypatch.setattr(messagebox, "showerror", lambda *a, **k: seen["errors"].append(a))

    def script(window):
        press(window, "Begin Setup")
        deadline = time.monotonic() + WAIT
        while not barrier.exists():
            assert time.monotonic() < deadline, "pip never started"
            settle(window)
            time.sleep(0.02)
        seen["ids"] = json.loads(barrier.read_text())
        close_window(window)                              # No: setup goes on
        pump_for(window, 1.0)
        seen["after_no"] = (window.winfo_exists(), state(seen["ids"]), bootstrap.setup_stop_requested())
        seen["answer"] = True
        close_window(window)                              # Yes: setup stops; the window closes when the worker has

    run_as_toplevel(monkeypatch, tk_root, script)
    code = bootstrap.run_with_gui(skip_kokoro_default=True)
    try:
        assert seen["after_no"] == (True, work_area.ALIVE, False), "No changed nothing: pip still running, no stop asked"
        assert [title for title, _text in seen["questions"]] == ["Stop setup?", "Stop setup?"]
        assert state(seen["ids"]) == work_area.GONE and state(seen["ids"]["grandchild"]) == work_area.GONE
        assert sentinel.poll() is None
        assert code == 1, "an install stopped part-way is incomplete, not cancelled (setup_exit_code)"
        assert seen["launched"] == 0 and seen["errors"] == [], "no app launch and no 'did not complete' dialog for a stop"
        assert "stopped before it finished" in setup_log.path.read_text(encoding="utf-8"), "the log says what happened"
    finally:
        if "ids" in seen:
            end_standin(seen["ids"])


class GatedPanel(optional_setup_panel.OptionalSetupPanel):
    """The real panel, with its read-only check replaced by a gate the test releases. Records whether Cancel reached it."""

    gate = None

    def __init__(self, *args, **kwargs):
        gate = GatedPanel.gate

        def run_plan(repo_root, components, cancelled):
            gate["started"].set()
            while not gate["release"].wait(0.05):
                if cancelled():
                    gate["cancelled"] = True
                    return {"state": proto.CANCELLED_STATE}
            return {"state": proto.SUCCEEDED, "plan": None}

        super().__init__(*args, run_plan=run_plan, run_install=lambda *a, **k: pytest.fail("nothing is installed"),
                         **kwargs)


def continue_button(window):
    """The panel's way on once the check has ended ("Continue", or "Continue without them" when nothing was planned)."""
    return next((w for w in descendants(window) if isinstance(w, ttk.Button)
                 and str(w.cget("text")).startswith("Continue")), None)


@pytest.mark.parametrize("answer", [False, True], ids=["no", "yes"])
def test_stop_setup_during_the_optional_voices_check_honours_the_answer(
        answer, monkeypatch, tk_root, setup_log, native_theme):
    gate = {"started": threading.Event(), "release": threading.Event(), "cancelled": False}
    GatedPanel.gate = gate
    seen = {"launched": 0, "questions": []}
    monkeypatch.setattr(optional_setup_panel, "OptionalSetupPanel", GatedPanel)
    monkeypatch.setattr(bootstrap, "run_setup", lambda on_progress, log: (True, "Setup complete."))
    monkeypatch.setattr(bootstrap, "optional_estimates", lambda: {})
    monkeypatch.setattr(bootstrap, "launch_gui", lambda log: seen.__setitem__("launched", seen["launched"] + 1))
    monkeypatch.setattr(messagebox, "askyesno",
                        lambda title, text, **kw: seen["questions"].append(title) or answer)

    def script(window):
        press(window, "Begin Setup")
        deadline = time.monotonic() + WAIT
        while not gate["started"].is_set():
            assert time.monotonic() < deadline, "the voice check never started"
            settle(window)
            time.sleep(0.02)
        close_window(window)
        pump_for(window, 1.0)
        if answer:                                      # the check's own thread sees the Cancel at its next look
            deadline = time.monotonic() + WAIT
            while not gate["cancelled"] and time.monotonic() < deadline:
                time.sleep(0.02)
        seen["after"] = (bool(window.winfo_exists()), gate["cancelled"], seen["launched"])
        if not answer:
            gate["release"].set()                       # the check finishes by itself
            deadline = time.monotonic() + WAIT
            while not continue_button(window):
                assert time.monotonic() < deadline, "the check never finished"
                settle(window)
                time.sleep(0.02)
            continue_button(window).invoke()

    run_as_toplevel(monkeypatch, tk_root, script)
    code = bootstrap.run_with_gui(skip_kokoro_default=False)
    assert seen["questions"] == ["Stop setup?"]
    if answer:
        assert seen["after"][1] is True, "Yes stops the check"
        assert seen["launched"] == 0, "and nothing is launched as though setup had ended"
        assert code == 1
    else:
        assert seen["after"] == (True, False, 0), "No: the window stays, the check goes on, nothing is launched"
        assert seen["launched"] == 1, "the app launches once, after the check really finished"
        assert code == 0
