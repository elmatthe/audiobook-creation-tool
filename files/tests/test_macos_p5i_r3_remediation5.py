"""v0.8.x P5-I-R3, remediation 5: what the (content-filtered, verdict-less) review of 16c78c6 was probing.

Its two probes (``remed-5/`` in the evidence folder) reproduced on 16c78c6:

1. a Python child stalled between fork and exec, announced early to a guardian that was then lost, was never announced
   to the replacement -- the app's death left it running;
2. a cancelled run's own local-engine retirement replaced the panel's while that one was still running; finding the
   worker's lock taken it ended at once, and the run was reported CANCELLED with the worker alive.
macOS only.
"""

from __future__ import annotations

import os
import queue
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from shared import child_ownership as co
from shared import subprocess_utils as sp
from shared.job_control import JobController

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="POSIX containment is the Mac's")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def until(predicate, timeout=5.0):
    end = time.monotonic() + timeout
    while not predicate() and time.monotonic() < end:
        time.sleep(0.005)
    return predicate()


def live(pid, start) -> bool:
    return start is not None and co.process_start_time(pid) == start and not co._has_exited(pid)


def test_a_child_stalled_before_exec_is_announced_to_a_replacement_guardian(tmp_path):
    app = f"""
import os, signal, sys, threading, time
from pathlib import Path
from shared import child_ownership as co
root = Path({str(tmp_path)!r})
owner = co.Owner()
owner.ensure_guardian()
def stall():
    (root / 'pid').write_text(str(os.getpid()))
    os.kill(os.getpid(), signal.SIGSTOP)
threading.Thread(target=lambda: owner.popen_python([sys.executable, '-c', 'pass'], preexec_fn=stall),
                 daemon=True).start()
def wait(pred):
    deadline = time.monotonic() + 5
    while not pred():
        assert time.monotonic() < deadline
        time.sleep(0.01)
wait(lambda: any(e.kind == co.CLASS_A and e.announced for e in owner._entries))
first = owner._guardian
first.kill()
wait(lambda: owner.guardian_pid() not in (None, first.pid))
entry = next(e for e in owner._entries if e.kind == co.CLASS_A)
wait(lambda: entry.announced)
(root / 'ready').write_text(f'{{owner.guardian_pid()}} {{entry.state}}')
time.sleep(20)
"""
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT / "scripts"), os.environ.get("PYTHONPATH", "")]))
    child = start = None
    with subprocess.Popen([sys.executable, "-B", "-c", app], env=env) as owner_proc:
        try:
            assert until(lambda: (tmp_path / "ready").exists(), 10), "the guardian was replaced and told"
            child = int((tmp_path / "pid").read_text())
            start = co.process_start_time(child)
            replacement, state = (tmp_path / "ready").read_text().split()
            assert state == co.SPAWNING
            owner_proc.kill()
            owner_proc.wait(5)
            assert until(lambda: not live(child, start), 5), "the replacement guardian ended the stalled child"
        finally:
            if owner_proc.poll() is None:
                owner_proc.kill()
                owner_proc.wait(5)
            if child is None and (tmp_path / "pid").exists():  # failed before reading it: still ended here
                child = int((tmp_path / "pid").read_text())
                start = co.process_start_time(child)
            if child is not None and live(child, start):
                os.kill(child, signal.SIGKILL)


def test_a_second_cancel_request_never_replaces_a_retirement_still_running():
    from shared.job_control import RunResult
    from tts import epub2tts_gui as gui
    from tts import local_engine_host as hosts

    owner = co.Owner()
    host = hosts.WorkerHost("kokoro", sample_rate=24000,
                            argv=[sys.executable, "-I", "-B", str(HERE / "local_engine_stub.py"), "kokoro"], owner=owner)
    entered, release = threading.Event(), threading.Event()
    real_kill = host.kill
    terminal: list = []

    def held_kill(reason=""):
        if reason == "cancel":
            entered.set()
            assert release.wait(6)
        return real_kill(reason)

    first = None
    with patch.object(sp, "_owner", owner), patch.object(hosts, "_HOST", host), \
            patch.object(hosts, "_CANCEL_RETIREMENT", None), patch.object(RunResult, "settle", return_value=object()), \
            patch.object(gui, "LOCAL_ENGINE_STOP_S", 0.3):
        try:
            host.ensure_started()
            worker = host._proc
            start = co.process_start_time(worker.pid)
            ctl = JobController("duplicate", cancel_clock=time.monotonic)
            ctl.start()
            ctx = gui._RunContext.__new__(gui._RunContext)
            ctx.cancel_check, ctx.controller, ctx.cancelled = ctl.cancel_check, ctl, True
            ctx.unstopped, ctx.completed, ctx.failures = [], [], []
            ctx.snapshot = SimpleNamespace(snapshot_id="duplicate", tool_options={"backend": "kokoro"})
            ctx.log_q = queue.Queue()
            ctx.stopped, ctx.not_started = 0, 1
            ctx.publisher = SimpleNamespace(cancelled=lambda final: terminal.append(
                ("CANCELLED", live(worker.pid, start))))
            ctx.settle_fatal = lambda exc: terminal.append(("FAILED", str(exc)))
            ctl.request_cancel()
            with patch.object(host, "kill", held_kill):
                hosts.cancel_requested("kokoro")  # the panel's retirement: held inside its kill
                assert entered.wait(3)
                first = hosts._CANCEL_RETIREMENT
                ctx.settle()  # the run's own request: must reuse it, not replace it
                assert hosts._CANCEL_RETIREMENT is first
            assert terminal and terminal[0][0] == "FAILED", terminal
        finally:
            release.set()
            if first is not None:
                first.join(6)
            host.close("test over")
            owner.shutdown()
