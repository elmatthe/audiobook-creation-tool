"""v0.8.x P5-B -- the first-run setup window owns its optional-setup workers (POSIX).

**Reproduced at ``a88f3fb``** (``files/dev-work/macos-p5b/repro/before/``, real processes): the first-run window
(``bootstrap.run_with_gui``) never made its setup process a containment owner, so ``qwen3_process.spawn`` started the
optional-setup worker in a session of its own without a lifeline, and the worker -- not under a lifeline itself --
started its pip and engine probes the same way. A forced Cancel or time-out ended the worker's process group (the run
said ``GROUP_ENDED``, a clean ``cancelled``) while pip's helper, in pip's own group, kept running; closing the window,
SIGKILL or a crash of the setup process left the worker, pip and the helper running. The app window's Install &
Continue never had the defect: ``launcher.main`` makes the app an owner (``subprocess_utils.enable_containment``).

**Now** ``optional_phase`` calls ``bootstrap.own_optional_setup()`` before the panel's first check, and ``run_with_gui``
calls ``bootstrap.settle_optional_setup()`` once the window is gone: every run ends and reaps its own worker first, then
the orderly end runs.

Real, disposable processes: a stand-in worker (the real one cannot be made to block in pip) starts its "pip" exactly as
the real worker starts pip and the engine probes -- ``tts.qwen3_setup.run_command`` -> ``qwen3_process.spawn`` -- under
the real window, panel, client, ``WorkerRun`` and ``child_ownership``, in a disposable copy of the app with its own base
Python and ``.venv``. Each process records its own pid and kernel start time; a process is "gone" only when that pid no
longer has that start time. Nothing is found by name or by a scan, and whatever a failing test leaves is ended by the
same identity. An unrelated process started by each test must survive it.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from shared import bootstrap, child_ownership
from shared import optional_setup_client as client
from shared import optional_setup_protocol as proto
from shared import subprocess_utils

tk = pytest.importorskip("tkinter")
from tkinter import messagebox, ttk  # noqa: E402

from test_optional_tts_setup import make_venv, own_base_python  # noqa: E402
from test_setup_log_follow import (  # noqa: E402,F401  (fixtures are collected by name)
    descendants,
    native_theme,
    run_as_toplevel,
    settle,
    setup_log,
    tk_root,
)

REPO = Path(__file__).resolve().parents[2]
K = proto.KOKORO
POSIX_ONLY = pytest.mark.skipif(os.name == "nt", reason="POSIX first-run ownership (Windows ends its Job Object)")
#: How long the lifeline may take to end a separately grouped process once its owner is gone (it is asynchronous).
LIFELINE_S = 5.0
#: Every test: a fresh owner for this process (none left behind), and the setup log in a temporary folder.
pytestmark = pytest.mark.usefixtures("fresh_containment_owner", "setup_log")

# --------------------------------------------------------------------------- #
#  The stand-in worker and the "pip" / "probe" it starts
# --------------------------------------------------------------------------- #
#: A pip or engine probe: starts a helper in its own process group (a build backend), waits for the helper's record,
#: then records itself -- so its own record means both exist; wait for that one, never the helper's -- and runs until
#: it is ended.
CHILD = r"""
import json, os, subprocess, sys, threading, time
from pathlib import Path
from shared import child_ownership as co
ev, name = Path(sys.argv[1]), sys.argv[2]
HELPER = ("import json, os, sys, time; from pathlib import Path; from shared import child_ownership as co; "
          "ev, name = Path(sys.argv[1]), sys.argv[2]; "
          "d = {'pid': os.getpid(), 'start': co.process_start_time(os.getpid()), 'pgid': os.getpgrp(), "
          "'sid': os.getsid(0)}; (ev / (name + '.json.new')).write_text(json.dumps(d)); "
          "os.replace(ev / (name + '.json.new'), ev / (name + '.json')); time.sleep(300)")
subprocess.Popen([sys.executable, "-c", HELPER, str(ev), name + "-helper"], stdout=subprocess.DEVNULL,
                 stderr=subprocess.DEVNULL)
deadline = time.monotonic() + 30
while not (ev / (name + "-helper.json")).exists() and time.monotonic() < deadline:
    time.sleep(0.02)
d = {"pid": os.getpid(), "start": co.process_start_time(os.getpid()), "pgid": os.getpgrp(), "sid": os.getsid(0),
     "lifeline": any(t.name == "act-lifeline" for t in threading.enumerate())}
(ev / (name + ".json.new")).write_text(json.dumps(d))
os.replace(ev / (name + ".json.new"), ev / (name + ".json"))
while True:
    print("Collecting package==1.0", flush=True)
    time.sleep(0.5)
"""

#: The worker. Its behaviour per request action comes from ``plan=...,install=...``:
#:   block    -- pip through ``qwen3_setup.run_command`` that never ends; the cancel flag is never read
#:   complete -- a probe through ``qwen3_process.spawn`` left running, then a trustworthy success, then exit
#:   exit     -- a probe left running, then exit with no result
#:   bare     -- as exit, but without the worker's own plain child (see the after-exit owner-death test)
STANDIN = r"""
import json, os, subprocess, sys, threading, time
from pathlib import Path
from shared import child_ownership as co
from shared import optional_setup_protocol as proto
from tts import qwen3_process, qwen3_setup
ev, behaviours, request_path, result_path = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4])
CHILD = (ev / "child.py").read_text()
request = json.loads(request_path.read_text())
tag = request["action"]
how = dict(item.split("=") for item in behaviours.split(","))[tag]
env = {k: v for k, v in os.environ.items() if k != "ACT_LIFELINE_FD"}
own = None
if how != "bare":
    own = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
d = {"pid": os.getpid(), "start": co.process_start_time(os.getpid()), "pgid": os.getpgrp(), "sid": os.getsid(0),
     "lifeline": any(t.name == "act-lifeline" for t in threading.enumerate()),
     "own": None if own is None else {"pid": own.pid, "start": co.process_start_time(own.pid)}}
(ev / (tag + "-worker.json.new")).write_text(json.dumps(d))
os.replace(ev / (tag + "-worker.json.new"), ev / (tag + "-worker.json"))
if how == "block":
    qwen3_setup.run_command([sys.executable, "-c", CHILD, str(ev), tag + "-pip"], env=env, cwd=Path.cwd(),
                            on_line=lambda line: None, cancel_check=None)
    raise SystemExit(0)
qwen3_process.spawn([sys.executable, "-c", CHILD, str(ev), tag + "-probe"], require_job=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
deadline = time.monotonic() + 30
while not (ev / (tag + "-probe.json")).exists() and time.monotonic() < deadline:
    time.sleep(0.02)
if how == "complete":
    rid = request["request_id"]
    if tag == proto.ACTION_PLAN:
        from tts import optional_setup  # a real plan: the engine proved, its files missing -> Install is offered
        facts = optional_setup.Facts(health={c: True for c in request["components"]},
                                     package_version={"spacy": "3.8.16"}.get)
        result = proto.make_result(rid, proto.SUCCEEDED, plan=optional_setup.plan_to_json(
            optional_setup.plan(request["components"], facts=facts)))
    else:
        result = proto.make_result(rid, proto.SUCCEEDED, verified=request["components"])
    proto.publish_once(result_path, proto.encode(result))
raise SystemExit(0)
"""


@pytest.fixture(scope="module")
def app_copy(tmp_path_factory):
    """A disposable copy of the app: the checkout's ``scripts/shared`` and ``scripts/tts``, its own base Python where
    setup's stage 0 puts it, and a pip-less ``.venv`` made from that, as setup makes the app's."""
    if os.name == "nt":
        pytest.skip("POSIX first-run ownership (Windows ends its Job Object)")
    root = tmp_path_factory.mktemp("first-run-copy")
    for package in ("shared", "tts"):
        shutil.copytree(REPO / "scripts" / package, root / "scripts" / package,
                        ignore=shutil.ignore_patterns("__pycache__"))
    (root / "files").mkdir()
    make_venv(own_base_python(root), root / ".venv")
    return root


@pytest.fixture
def ev(tmp_path):
    folder = tmp_path / "evidence"
    folder.mkdir()
    (folder / "child.py").write_text(CHILD, encoding="utf-8")
    return folder


@pytest.fixture
def sentinel():
    """An unrelated process of this account, in a session of its own: no test may touch it."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"], start_new_session=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    identity = (proc.pid, child_ownership.process_start_time(proc.pid))
    yield identity
    child_ownership.signal_if_same(*identity, signal.SIGKILL)
    proc.wait(10)


def launch_with(ev: Path, behaviours: str):
    """``proto.worker_launch`` for the stand-in: the copy's own ``.venv/bin/python``, its ``scripts`` folder, the
    request and result paths the client made. Only the worker *program* differs from production."""
    def launch(root, path, session, **_kwargs):
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PYTHON")}
        result = Path(path).with_name(proto.RESULT_NAME)
        return proto.LaunchSpec((str(proto.main_console_python(root)), "-c", STANDIN, str(ev), behaviours, str(path),
                                 str(result)), Path(root) / "scripts", env, Path(path), result)
    return launch


class Runs:
    """Every ``WorkerRun`` the client makes, kept for the assertions (how its group ended, its one outcome)."""

    def __init__(self, monkeypatch):
        self.made: list = []
        made = self.made

        class Recorded(proto.WorkerRun):
            def start(self):
                made.append(self)
                super().start()

        monkeypatch.setattr(proto, "WorkerRun", Recorded)


def record(ev: Path, name: str, bound: float = 60.0) -> dict:
    deadline = time.monotonic() + bound
    while time.monotonic() < deadline:
        try:
            return json.loads((ev / f"{name}.json").read_text())
        except (OSError, ValueError):
            time.sleep(0.02)
    raise AssertionError(f"{name} never started")


def identities(ev: Path) -> dict:
    """Every process the stand-ins recorded so far, by name: ``(pid, start time)``."""
    out = {}
    for path in sorted(ev.glob("*.json")):
        data = json.loads(path.read_text())
        out[path.stem] = (data["pid"], tuple(data["start"]))
        if data.get("own"):
            out[path.stem + "-own"] = (data["own"]["pid"], tuple(data["own"]["start"]))
    return out


def alive(identity) -> bool:
    pid, start = identity
    return start is not None and child_ownership.process_start_time(pid) == tuple(start)


def left_running(ids: dict, bound: float = LIFELINE_S) -> list:
    """The recorded processes still running after at most *bound* seconds (the lifeline is asynchronous)."""
    deadline = time.monotonic() + bound
    while True:
        running = sorted(name for name, identity in ids.items() if alive(identity))
        if not running or time.monotonic() >= deadline:
            return running
        time.sleep(0.05)


def end_identified(ev: Path) -> None:
    """The test's own clean-up of anything a failing test left: by pid and start time, never by name."""
    for identity in identities(ev).values():
        child_ownership.signal_if_same(*identity, signal.SIGKILL)


def install_consent() -> proto.Consent:
    return proto.Consent(proto.new_token(), "main", (K,), {K: "install"}, ("kokoro-model",), (), 10, "f" * 64)


# --------------------------------------------------------------------------- #
#  Every platform: where the ownership is taken, and Windows unchanged
# --------------------------------------------------------------------------- #
def _function(tree: ast.AST, name: str) -> ast.FunctionDef:
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)


def test_the_window_owns_its_workers_before_the_first_check_and_settles_them_once_it_is_gone():
    source = (REPO / "scripts" / "shared" / "bootstrap.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    phase = ast.get_source_segment(source, _function(_function(tree, "run_with_gui"), "optional_phase"))
    assert phase.index("own_optional_setup()") < phase.index("OptionalSetupPanel(") < phase.index("panel.start()")
    body = ast.get_source_segment(source, _function(tree, "run_with_gui"))
    after = body[body.index("root.mainloop()"):]
    assert after.index("settle_optional_setup(") < after.index("LOG.close()"), \
        "the window's workers are settled as soon as the window is gone, before anything else"


def test_the_settle_bound_covers_a_runs_own_stop():
    """A run asked to stop gives its worker CANCEL_GRACE_S, then ends and confirms its group within TERMINATE_WAIT_S;
    the window's settle must outlast both, or the orderly end would reap a worker its run was still judging."""
    assert bootstrap.OPTIONAL_SETUP_SETTLE_S >= proto.CANCEL_GRACE_S + proto.TERMINATE_WAIT_S


def test_windows_first_run_window_takes_no_new_ownership(monkeypatch):
    """Deterministic, on any platform: with Windows' answer the first-run window changes nothing (Job Objects)."""
    monkeypatch.setattr(bootstrap, "IS_WINDOWS", True)

    def never(*args, **kwargs):
        raise AssertionError("the POSIX first-run ownership was consulted on Windows")

    monkeypatch.setattr(bootstrap, "_owner", never)
    monkeypatch.setattr(subprocess_utils, "enable_containment", never)
    assert bootstrap.own_optional_setup() is None
    assert subprocess_utils.containment_owner() is None


def test_the_app_windows_own_ownership_path_is_unchanged():
    """Install & Continue in the app window keeps its owner: the window makes itself one before Tk starts and ends it
    after the main loop. The first-run window's settle is not the app's."""
    source = (REPO / "scripts" / "launcher.py").read_text(encoding="utf-8")
    main = ast.get_source_segment(source, _function(ast.parse(source), "main"))
    assert main.index("sp.enable_containment(") < main.index("tk.Tk()") < main.index("root.mainloop()") \
        < main.index("sp.shutdown_containment()")
    assert "settle_optional_setup" not in source and "own_optional_setup" not in source


@POSIX_ONLY
def test_the_first_run_owner_is_setups_own_and_the_one_the_spawn_path_uses():
    owner = bootstrap.own_optional_setup()
    assert owner is not None
    assert owner is bootstrap._owner() is subprocess_utils.containment_owner() is child_ownership.owner()


# --------------------------------------------------------------------------- #
#  The real first-run window, in this process
# --------------------------------------------------------------------------- #
def drive_window(monkeypatch, tk_root, app_copy, ev, behaviours: str, script) -> tuple[int, dict]:
    """``run_with_gui`` with the base install already done, the copy as the app's folder and the stand-in as the
    worker; *script* drives the window. Returns the exit code and what was seen."""
    seen = {"launched": 0, "asked": [], "errors": []}
    monkeypatch.setattr(bootstrap, "run_setup", lambda on_progress, log: (True, "Setup complete."))
    monkeypatch.setattr(bootstrap, "optional_estimates", lambda: {})
    monkeypatch.setattr(bootstrap, "launch_gui", lambda log: seen.__setitem__("launched", seen["launched"] + 1))
    monkeypatch.setattr(bootstrap, "REPO_ROOT", app_copy)
    monkeypatch.setattr(proto, "worker_launch", launch_with(ev, behaviours))
    monkeypatch.setattr(messagebox, "askyesno", lambda title, text, **kw: seen["asked"].append(title) or True)
    monkeypatch.setattr(messagebox, "showerror", lambda *a, **k: seen["errors"].append(a))
    run_as_toplevel(monkeypatch, tk_root, lambda window: script(window, seen))
    code = bootstrap.run_with_gui(skip_kokoro_default=False)
    return code, seen


def pump_until(window, condition, what: str, bound: float = 60.0) -> None:
    deadline = time.monotonic() + bound
    while not condition():
        assert time.monotonic() < deadline, f"never happened: {what}"
        settle(window)
        time.sleep(0.02)


def shown_button(window, label: str):
    return next((w for w in descendants(window) if isinstance(w, ttk.Button) and str(w.cget("text")) == label
                 and w.winfo_ismapped()), None)


def press(window, label: str) -> None:
    pump_until(window, lambda: shown_button(window, label) is not None, f"the {label!r} button")
    shown_button(window, label).invoke()


def close_window(window) -> None:
    """What the window manager does on the close button: call the protocol command the window registered."""
    window.tk.call(window.protocol("WM_DELETE_WINDOW"))


def exists(ev: Path, name: str) -> bool:
    return (ev / f"{name}.json").exists()


def outcome_of(run, bound: float = 30.0) -> dict:
    """The run's one outcome, once its own thread has settled it (it reaps the worker just before)."""
    deadline = time.monotonic() + bound
    while run._outcome is None:
        assert time.monotonic() < deadline, "the run never settled its outcome"
        time.sleep(0.02)
    return run._outcome


@POSIX_ONLY
def test_a_first_run_check_and_install_that_complete_leave_no_worker_or_probe_running(
        monkeypatch, tk_root, setup_log, native_theme, app_copy, ev, sentinel):
    runs = Runs(monkeypatch)

    def script(window, seen):
        press(window, "Begin Setup")
        press(window, "Install Selected Components")       # the plan run completed: its review is shown
        press(window, "Continue")                          # the install run completed: "Installed"
        seen["ids"] = identities(ev)

    try:
        code, seen = drive_window(monkeypatch, tk_root, app_copy, ev, "plan=complete,install=complete", script)
        ids = seen["ids"]
        assert code == 0 and seen["launched"] == 1 and seen["errors"] == []
        assert [r.request.action for r in runs.made] == [proto.ACTION_PLAN, proto.ACTION_INSTALL]
        assert [outcome_of(r)["state"] for r in runs.made] == [proto.SUCCEEDED, proto.SUCCEEDED]
        assert [r.group_end for r in runs.made] == [child_ownership.GROUP_ENDED] * 2
        for tag in ("plan", "install"):
            worker, probe = record(ev, f"{tag}-worker"), record(ev, f"{tag}-probe")
            assert worker["lifeline"] and worker["pgid"] == worker["pid"] == worker["sid"], "the worker is class A"
            assert probe["lifeline"] and probe["sid"] == probe["pid"] != worker["sid"], \
                "its probe leads a session of its own, tied to the worker's lifeline"
        assert set(ids) >= {"plan-worker", "plan-worker-own", "plan-probe", "plan-probe-helper", "install-worker",
                            "install-worker-own", "install-probe", "install-probe-helper"}
        assert left_running(ids) == []
        assert alive(sentinel)
    finally:
        end_identified(ev)


def blocked_phase(phase: str) -> str:
    return "plan=block,install=block" if phase == "check" else "plan=complete,install=block"


def reach_blocked(window, phase: str, ev: Path) -> None:
    press(window, "Begin Setup")
    if phase == "install":
        press(window, "Install Selected Components")
    tag = "plan" if phase == "check" else "install"
    pump_until(window, lambda: exists(ev, f"{tag}-pip"), "the blocked pip and its helper")  # pip records last


@POSIX_ONLY
@pytest.mark.parametrize("phase", ["check", "install"])
def test_cancel_during_a_blocked_first_run_step_ends_the_worker_pip_and_its_helper(
        phase, monkeypatch, tk_root, setup_log, native_theme, app_copy, ev, sentinel):
    runs = Runs(monkeypatch)

    def script(window, seen):
        reach_blocked(window, phase, ev)
        seen["ids"] = identities(ev)
        press(window, "Cancel")                            # the panel's own Cancel; the stand-in never reads the flag
        pump_until(window, lambda: runs.made[-1]._outcome is not None, "the run's one outcome", bound=90)

    try:
        code, seen = drive_window(monkeypatch, tk_root, app_copy, ev, blocked_phase(phase), script)
        run = runs.made[-1]
        outcome = outcome_of(run)
        assert outcome["state"] == proto.CANCELLED_STATE and outcome["forced"] and run.terminated
        assert run.group_end == child_ownership.GROUP_ENDED
        tag = "plan" if phase == "check" else "install"
        assert {f"{tag}-worker", f"{tag}-worker-own", f"{tag}-pip", f"{tag}-pip-helper"} <= set(seen["ids"])
        assert left_running(seen["ids"]) == [], "the worker, its own child, pip and pip's helper all ended"
        assert code == 0 and seen["launched"] == 1, "a cancelled voice step still launches the app, as before"
        assert alive(sentinel)
    finally:
        end_identified(ev)


@POSIX_ONLY
@pytest.mark.parametrize("phase", ["check", "install"])
def test_closing_the_first_run_window_during_a_blocked_step_ends_everything_it_started(
        phase, monkeypatch, tk_root, setup_log, native_theme, app_copy, ev, sentinel):
    runs = Runs(monkeypatch)

    def script(window, seen):
        reach_blocked(window, phase, ev)
        seen["ids"] = identities(ev)
        seen["owner"] = subprocess_utils.containment_owner()
        seen["registered"] = seen["owner"] is not None and seen["owner"].child(runs.made[-1].process) is not None
        close_window(window)                               # "Stop installing the voices?" -> Yes

    try:
        code, seen = drive_window(monkeypatch, tk_root, app_copy, ev, blocked_phase(phase), script)
        run = runs.made[-1]
        assert seen["asked"] == ["Stop setup?"] and code == 1 and seen["launched"] == 0
        assert seen["registered"], "the worker was this process's own class-A child"
        # The run ended and judged its own worker before the orderly end: a clean, confirmed Cancel.
        assert run.process.returncode is not None and run.group_end == child_ownership.GROUP_ENDED
        assert outcome_of(run)["state"] == proto.CANCELLED_STATE
        tag = "plan" if phase == "check" else "install"
        assert {f"{tag}-worker", f"{tag}-worker-own", f"{tag}-pip", f"{tag}-pip-helper"} <= set(seen["ids"])
        assert left_running(seen["ids"]) == []
        assert seen["owner"].closing, "and nothing new may start in this process"
        assert alive(sentinel)
    finally:
        end_identified(ev)


# --------------------------------------------------------------------------- #
#  The client the panel calls, under the first-run window's ownership, in this process
# --------------------------------------------------------------------------- #
def run_owned(app_copy, ev, monkeypatch, behaviours: str, action: str, **kwargs) -> dict:
    monkeypatch.setattr(proto, "worker_launch", launch_with(ev, behaviours))
    consent = install_consent() if action == proto.ACTION_INSTALL else None
    return client.run(app_copy, action, [K], consent=consent, **kwargs)


@POSIX_ONLY
@pytest.mark.parametrize("action", [proto.ACTION_PLAN, proto.ACTION_INSTALL])
def test_a_timed_out_first_run_step_ends_the_worker_pip_and_its_helper(action, monkeypatch, app_copy, ev, sentinel):
    runs = Runs(monkeypatch)
    owner = bootstrap.own_optional_setup()
    try:
        result = run_owned(app_copy, ev, monkeypatch, f"{action}=block", action, timeout_s=8.0)
        ids = identities(ev)
        assert result["state"] == proto.FAILED and result["error"]["code"] == proto.TIMED_OUT
        assert runs.made[0].group_end == child_ownership.GROUP_ENDED
        assert {f"{action}-worker", f"{action}-pip", f"{action}-pip-helper"} <= set(ids)
        assert left_running(ids) == []
        assert bootstrap.settle_optional_setup(owner) is True
        assert alive(sentinel)
    finally:
        end_identified(ev)


@POSIX_ONLY
def test_a_worker_that_exits_leaving_a_probe_and_a_child_takes_both_with_it(monkeypatch, app_copy, ev, sentinel):
    runs = Runs(monkeypatch)
    bootstrap.own_optional_setup()
    try:
        result = run_owned(app_copy, ev, monkeypatch, "plan=exit", proto.ACTION_PLAN)
        ids = identities(ev)
        assert result["state"] == proto.FAILED and result["error"]["code"] == proto.NO_RESULT
        assert runs.made[0].group_end == child_ownership.GROUP_ENDED
        assert {"plan-worker-own", "plan-probe", "plan-probe-helper"} <= set(ids)
        assert left_running(ids) == [], "its own child by the group's end, the probe and its helper by its lifeline"
        assert alive(sentinel)
    finally:
        end_identified(ev)


@POSIX_ONLY
def test_after_the_window_closes_each_run_ends_its_own_worker_before_the_orderly_end(
        monkeypatch, app_copy, ev, sentinel):
    """The race between the owner's orderly end and a run still stopping its worker: settle waits for the run to end,
    judge and reap its worker, then ends what is left -- the orderly end never reaps a worker its run is judging."""
    runs = Runs(monkeypatch)
    owner = bootstrap.own_optional_setup()
    cancel = threading.Event()
    out = {}
    thread = threading.Thread(target=lambda: out.setdefault("result", run_owned(
        app_copy, ev, monkeypatch, "plan=block", proto.ACTION_PLAN, cancelled=cancel.is_set)), daemon=True)
    at_shutdown = []
    real_shutdown = owner.shutdown

    def spy():
        run = runs.made[0]
        at_shutdown.append((run.process.returncode is not None, run.group_end))
        real_shutdown()

    monkeypatch.setattr(owner, "shutdown", spy)
    try:
        thread.start()
        record(ev, "plan-pip")                         # pip records itself after its helper
        ids = identities(ev)
        assert {"plan-worker", "plan-worker-own", "plan-pip", "plan-pip-helper"} <= set(ids)
        cancel.set()                                   # what the window's close does to its panel
        assert bootstrap.settle_optional_setup(owner) is True
        thread.join(30)
        assert at_shutdown == [(True, child_ownership.GROUP_ENDED)], "reaped by its run, group confirmed ended"
        assert out["result"]["state"] == proto.CANCELLED_STATE
        assert left_running(ids) == []
        assert alive(sentinel)
    finally:
        end_identified(ev)


@POSIX_ONLY
def test_a_run_still_stopping_when_the_bound_runs_out_is_never_reported_clean(monkeypatch, app_copy, ev, sentinel):
    """Settle with no time left: the orderly end ends and may reap the worker while its run is still giving it the
    cancel grace. Whichever reaps first, everything ends, and the run's outcome is clean only if its own end of the
    group was confirmed; otherwise it is a containment failure, never a success or a clean Cancel."""
    runs = Runs(monkeypatch)
    owner = bootstrap.own_optional_setup()
    cancel = threading.Event()
    out = {}
    thread = threading.Thread(target=lambda: out.setdefault("result", run_owned(
        app_copy, ev, monkeypatch, "plan=block", proto.ACTION_PLAN, cancelled=cancel.is_set)), daemon=True)
    try:
        thread.start()
        record(ev, "plan-pip")                         # pip records itself after its helper
        ids = identities(ev)
        assert {"plan-worker", "plan-worker-own", "plan-pip", "plan-pip-helper"} <= set(ids)
        cancel.set()
        assert bootstrap.settle_optional_setup(owner, bound_s=0.0) is False
        thread.join(60)
        result, run = out["result"], runs.made[0]
        assert result["state"] != proto.SUCCEEDED
        if result["state"] == proto.CANCELLED_STATE:
            assert run.group_end == child_ownership.GROUP_ENDED
        else:
            assert result["state"] == proto.FAILED and result["error"]["code"] in (
                proto.CONTAINMENT_UNPROVED, proto.CONTAINMENT_INCOMPLETE), result
        assert left_running(ids) == []
        assert alive(sentinel)
    finally:
        end_identified(ev)


@POSIX_ONLY
def test_an_unconfirmed_end_under_the_first_run_owner_is_never_a_success(monkeypatch, app_copy, ev, sentinel):
    """P5-A-R1 still holds under the first-run window's ownership: a group that was signalled but not confirmed empty
    makes the run a containment failure, even for a worker that published its own success."""
    runs = Runs(monkeypatch)
    bootstrap.own_optional_setup()
    real_end = child_ownership.end_led_group

    def unconfirmed(proc, start_time, **kwargs):
        real_end(proc, start_time, **kwargs)
        return child_ownership.GROUP_REMAINING

    monkeypatch.setattr(child_ownership, "end_led_group", unconfirmed)
    try:
        result = run_owned(app_copy, ev, monkeypatch, "install=complete", proto.ACTION_INSTALL)
        assert result["state"] == proto.FAILED and result["error"]["code"] == proto.CONTAINMENT_INCOMPLETE
        assert result["verified"] == [K], "what the worker proved is kept; it is not a success"
        assert runs.made[0].group_end == child_ownership.GROUP_REMAINING
        assert left_running(identities(ev)) == []
        assert alive(sentinel)
    finally:
        end_identified(ev)


@POSIX_ONLY
def test_once_the_window_has_closed_no_worker_can_start(monkeypatch, app_copy, ev):
    owner = bootstrap.own_optional_setup()
    assert bootstrap.settle_optional_setup(owner) is True
    with pytest.raises(client.SetupUnavailable):
        run_owned(app_copy, ev, monkeypatch, "plan=block", proto.ACTION_PLAN)
    assert not exists(ev, "plan-worker") and owner.children() == []


# --------------------------------------------------------------------------- #
#  The setup process killed, crashed or force-quit: a separate owner process
# --------------------------------------------------------------------------- #
#: The setup process: the copy's own base Python and code, the ownership ``optional_phase`` takes, then the call the
#: panel makes. *case* says when it dies.
DRIVER = r"""
import json, os, signal, sys, threading, time
from pathlib import Path
copy, ev, behaviours, case = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4]
sys.path.insert(0, str(copy / "scripts"))
from shared import bootstrap, child_ownership, optional_setup_client as client, optional_setup_protocol as proto
STANDIN = (ev / "standin.py").read_text()

def note(name, data):
    (ev / (name + ".new")).write_text(json.dumps(data)); os.replace(ev / (name + ".new"), ev / name)

def launch(root, path, session, **kw):
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PYTHON")}
    result = Path(path).with_name(proto.RESULT_NAME)
    return proto.LaunchSpec((str(proto.main_console_python(root)), "-c", STANDIN, str(ev), behaviours, str(path),
                             str(result)), Path(root) / "scripts", env, Path(path), result)

proto.worker_launch = launch
assert bootstrap.own_optional_setup() is not None
if case == "before-start":
    def start(self):
        note("start-called", {})
        os.kill(os.getpid(), signal.SIGKILL)
    proto.WorkerRun.start = start
elif case == "during-start":
    real = child_ownership.Owner.popen_python
    def popen_python(self, argv, **kwargs):
        proc = real(self, argv, **kwargs)
        note("spawned", {"pid": proc.pid, "start": child_ownership.process_start_time(proc.pid)})
        os.kill(os.getpid(), signal.SIGKILL)
    child_ownership.Owner.popen_python = popen_python
elif case == "after-exit":
    def end_led_group(proc, start_time, **kwargs):
        note("worker-exited", {"pid": proc.pid})
        os.kill(os.getpid(), signal.SIGKILL)
    child_ownership.end_led_group = end_led_group
threading.Thread(target=lambda: client.run(copy, proto.ACTION_PLAN, [proto.KOKORO]), daemon=True).start()
if case in ("kill", "crash"):
    deadline = time.monotonic() + 60
    while not (ev / "plan-pip.json").exists() and time.monotonic() < deadline:  # pip records after its helper
        time.sleep(0.02)
    note("ready", {})
    if case == "crash":
        os.abort()
time.sleep(120)
"""


def start_driver(app_copy: Path, ev: Path, behaviours: str, case: str) -> subprocess.Popen:
    (ev / "standin.py").write_text(STANDIN, encoding="utf-8")
    base = app_copy / "files" / "runtime-data" / "python" / "bin" / "python3.12"
    return subprocess.Popen([str(base), "-I", "-c", DRIVER, str(app_copy), str(ev), behaviours, case],
                            start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)


def wait_note(ev: Path, name: str, driver: subprocess.Popen, bound: float = 60.0) -> dict:
    deadline = time.monotonic() + bound
    while not (ev / name).exists():
        if driver.poll() is not None or time.monotonic() >= deadline:
            if (ev / name).exists():
                break
            raise AssertionError(f"{name} never came (exit {driver.poll()}): "
                                 f"{driver.stderr.read() if driver.poll() is not None else 'still running'}")
        time.sleep(0.02)
    return json.loads((ev / name).read_text())


@POSIX_ONLY
@pytest.mark.parametrize("how", ["kill", "crash"])
def test_a_setup_process_killed_or_crashed_mid_check_takes_its_worker_pip_and_helper_with_it(
        how, app_copy, ev, sentinel):
    driver = start_driver(app_copy, ev, "plan=block", how)
    try:
        wait_note(ev, "ready", driver)
        ids = identities(ev)
        assert {"plan-worker", "plan-worker-own", "plan-pip", "plan-pip-helper"} <= set(ids)
        if how == "kill":
            os.kill(driver.pid, signal.SIGKILL)            # Force Quit: no code of the owner runs
        driver.wait(30)
        assert driver.returncode == (-signal.SIGKILL if how == "kill" else -signal.SIGABRT)
        assert left_running(ids) == []
        assert alive(sentinel)
    finally:
        if driver.poll() is None:
            driver.kill()
            driver.wait()
        end_identified(ev)


@POSIX_ONLY
def test_a_setup_process_killed_before_its_worker_starts_leaves_nothing(app_copy, ev, sentinel):
    driver = start_driver(app_copy, ev, "plan=block", "before-start")
    try:
        wait_note(ev, "start-called", driver)
        driver.wait(30)
        time.sleep(2.0)
        assert not exists(ev, "plan-worker") and identities(ev) == {}
        assert alive(sentinel)
    finally:
        if driver.poll() is None:
            driver.kill()
            driver.wait()
        end_identified(ev)


@POSIX_ONLY
def test_a_setup_process_killed_while_its_worker_is_starting_takes_the_worker_with_it(app_copy, ev, sentinel):
    driver = start_driver(app_copy, ev, "plan=block", "during-start")
    spawned = None
    try:
        spawned = wait_note(ev, "spawned", driver)
        driver.wait(30)
        worker = (spawned["pid"], tuple(spawned["start"]))
        assert left_running({"worker": worker}) == []
        time.sleep(1.0)
        assert left_running(identities(ev)) == [], "anything it reached before it ended has ended too"
        assert alive(sentinel)
    finally:
        if driver.poll() is None:
            driver.kill()
            driver.wait()
        if spawned is not None:
            child_ownership.signal_if_same(spawned["pid"], tuple(spawned["start"]), signal.SIGKILL)
        end_identified(ev)


@POSIX_ONLY
def test_a_setup_process_killed_just_after_its_worker_exited_still_ends_the_workers_probe(app_copy, ev, sentinel):
    """The owner dies after the worker exited, before its run ended the worker's group. The probe the worker started
    leads its own group on the worker's lifeline, so it ends with the worker whatever happens to the owner. (A plain
    child left in the worker's own group would not: P5-A's residual, recorded in Decisions; the real worker starts
    its children through ``qwen3_process.spawn`` only.)"""
    driver = start_driver(app_copy, ev, "plan=bare", "after-exit")
    try:
        wait_note(ev, "worker-exited", driver)
        driver.wait(30)
        ids = identities(ev)
        assert {"plan-worker", "plan-probe", "plan-probe-helper"} <= set(ids)
        assert left_running(ids) == []
        assert alive(sentinel)
    finally:
        if driver.poll() is None:
            driver.kill()
            driver.wait()
        end_identified(ev)


#: The real first-run window, in the setup process, until it is force-quit.
WINDOW_DRIVER = r"""
import os, sys, time
from pathlib import Path
copy, ev, behaviours = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
sys.path.insert(0, str(copy / "scripts"))
import tkinter as tk
from tkinter import ttk
from shared import bootstrap, optional_setup_protocol as proto
STANDIN = (ev / "standin.py").read_text()

def launch(root, path, session, **kw):
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PYTHON")}
    result = Path(path).with_name(proto.RESULT_NAME)
    return proto.LaunchSpec((str(proto.main_console_python(root)), "-c", STANDIN, str(ev), behaviours, str(path),
                             str(result)), Path(root) / "scripts", env, Path(path), result)

proto.worker_launch = launch
bootstrap.run_setup = lambda on_progress, log: (True, "Setup complete.")
bootstrap.optional_estimates = lambda: {}
bootstrap.launch_gui = lambda log: True
real_root = tk.Tk()
real_root.withdraw()

def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)

class Window(tk.Toplevel):
    def mainloop(self, n=0):
        deadline = time.monotonic() + 60
        while True:
            self.update()
            begin = [w for w in descendants(self) if isinstance(w, ttk.Button) and str(w.cget("text")) == "Begin Setup"
                     and w.winfo_ismapped()]
            if begin:
                begin[0].invoke()
                break
            assert time.monotonic() < deadline
            time.sleep(0.02)
        while not (ev / "plan-pip.json").exists():  # pip records itself after its helper
            assert time.monotonic() < deadline
            self.update()
            time.sleep(0.02)
        (ev / "ready").write_text("{}")
        while True:
            self.update()
            time.sleep(0.05)

tk.Tk = lambda *a, **k: Window(real_root)
bootstrap.run_with_gui(skip_kokoro_default=False)
"""


@POSIX_ONLY
def test_force_quitting_the_first_run_window_ends_its_worker_pip_and_helper(app_copy, ev, sentinel):
    (ev / "standin.py").write_text(STANDIN, encoding="utf-8")
    base = app_copy / "files" / "runtime-data" / "python" / "bin" / "python3.12"
    window = subprocess.Popen([str(base), "-I", "-c", WINDOW_DRIVER, str(app_copy), str(ev), "plan=block"],
                              start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    try:
        wait_note(ev, "ready", window)
        ids = identities(ev)
        worker = record(ev, "plan-worker")
        assert worker["lifeline"] and worker["sid"] == worker["pid"] != os.getsid(window.pid)
        os.kill(window.pid, signal.SIGKILL)
        window.wait(30)
        assert left_running(ids) == []
        assert alive(sentinel)
    finally:
        if window.poll() is None:
            window.kill()
            window.wait()
        end_identified(ev)
