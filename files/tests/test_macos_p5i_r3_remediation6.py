"""v0.8.x P5-I-R3, remediation 6: what the (content-filtered, verdict-less) review of 6c1724a was probing.

Its probes (``remed-6/`` in the evidence folder) reproduced on 6c1724a:

1. a second Cancel request arriving between the start and the publication of the panel's retirement started its own,
   which found the worker's lock taken and ended at once: CANCELLED with the worker alive;
2. a run's settlement reported a start of the run stalled between fork and exec (-1) but never ended it;
3. the orderly end did the same when the guardian had been lost before the fork (nothing heard the early identity);
4. the Converter's contained streaming step, with its forced stops refused, returned 5.06 s after the click (C2: 4 s).
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


def until(predicate, timeout=5.0):
    end = time.monotonic() + timeout
    while not predicate() and time.monotonic() < end:
        time.sleep(0.005)
    return predicate()


def live(pid, start) -> bool:
    return start is not None and co.process_start_time(pid) == start and not co._has_exited(pid)


# --------------------------------------------------------------------------- 1

def test_a_cancel_request_between_start_and_publication_reuses_the_retirement():
    from shared.job_control import RunResult
    from tts import epub2tts_gui as gui
    from tts import local_engine_host as hosts

    owner = co.Owner()
    host = hosts.WorkerHost("kokoro", sample_rate=24000,
                            argv=[sys.executable, "-I", "-B", str(HERE / "local_engine_stub.py"), "kokoro"], owner=owner)
    in_kill, release_kill = threading.Event(), threading.Event()
    started, publish = threading.Event(), threading.Event()
    real_kill, real_start = host.kill, threading.Thread.start
    created: list = []
    terminal: list = []

    def held_kill(reason=""):
        if reason == "cancel":
            in_kill.set()
            release_kill.wait(6)
        return real_kill(reason)

    def start(thread):
        real_start(thread)
        if thread.name == "local-engine-cancel":
            created.append(thread)
            if len(created) == 1:  # the panel's: held between its start and its publication
                assert in_kill.wait(3)
                started.set()
                publish.wait(0.4)

    with patch.object(sp, "_owner", owner), patch.object(hosts, "_HOST", host), \
            patch.object(hosts, "_CANCEL_RETIREMENT", None), patch.object(RunResult, "settle", return_value=object()), \
            patch.object(gui, "LOCAL_ENGINE_STOP_S", 0.5):
        try:
            host.ensure_started()
            worker = host._proc
            start_time = co.process_start_time(worker.pid)
            ctl = JobController("race", cancel_clock=time.monotonic)
            ctl.start()
            ctx = gui._RunContext.__new__(gui._RunContext)
            ctx.cancel_check, ctx.controller, ctx.cancelled = ctl.cancel_check, ctl, True
            ctx.unstopped, ctx.completed, ctx.failures = [], [], []
            ctx.snapshot = SimpleNamespace(snapshot_id="race", tool_options={"backend": "kokoro"})
            ctx.log_q = queue.Queue()
            ctx.stopped, ctx.not_started = 0, 1
            ctx.publisher = SimpleNamespace(cancelled=lambda final: terminal.append(
                ("CANCELLED", live(worker.pid, start_time))))
            ctx.settle_fatal = lambda exc: terminal.append(("FAILED", str(exc)))
            ctl.request_cancel()
            panel = threading.Thread(target=hosts.cancel_requested, args=("kokoro",), daemon=True)
            with patch.object(host, "kill", held_kill), patch.object(threading.Thread, "start", start):
                panel.start()
                assert started.wait(4)
                ctx.settle()
            assert len(created) == 1, "the run's request reused the retirement in progress"
            assert terminal and (terminal[0][0] == "FAILED" or terminal[0][1] is False), terminal
        finally:
            publish.set()
            release_kill.set()
            for thread in created:
                thread.join(6)
            host.close("test over")
            owner.shutdown()


# --------------------------------------------------------------------------- 2, 3

def _stalled(owner, **kwargs):
    """A Python child that stops itself between fork and exec; returns its launching thread and early identity."""
    def stall():
        os.kill(os.getpid(), signal.SIGSTOP)

    out: list = []

    def launch():
        try:
            out.append(owner.popen_python([sys.executable, "-c", "pass"], label="stalled", preexec_fn=stall, **kwargs))
        except BaseException as exc:  # noqa: BLE001 - the outcome is checked by the caller
            out.append(exc)

    thread = threading.Thread(target=launch, daemon=True)
    thread.start()
    assert until(lambda: any(e.label == "stalled" and e.early for e in owner._entries), 4)
    early = next(e.early for e in owner._entries if e.label == "stalled")
    return thread, early, out


def test_a_runs_settlement_ends_its_start_stalled_between_fork_and_exec():
    owner = co.Owner()
    owner.ensure_guardian()
    ctl = JobController("pending", cancel_clock=time.monotonic)
    ctl.start()
    thread = None
    try:
        thread, (pid, start), out = _stalled(owner, run=ctl.cancel_check)
        ctl.request_cancel()
        result = owner.settle_run(ctl.cancel_check, bound_s=2.0)
        assert not live(pid, start), "the stalled start was ended"
        assert until(lambda: not thread.is_alive(), 3), "its Popen returned"
        assert result in ([], [pid]), result
    finally:
        if thread is not None:
            thread.join(3)
        owner.shutdown()


def test_the_orderly_end_ends_a_start_stalled_after_its_guardian_was_lost():
    owner = co.Owner()
    owner.ensure_guardian()
    guardian = owner._guardian
    before_fork, allow_fork = threading.Event(), threading.Event()
    execute = subprocess.Popen._execute_child

    def hook(proc, args, *rest, **kwargs):
        if str(co.ENTRY) in args:
            before_fork.set()
            assert allow_fork.wait(5)
        return execute(proc, args, *rest, **kwargs)

    thread = None
    pid = start = None
    try:
        with patch.object(subprocess.Popen, "_execute_child", hook):
            box: list = []
            launcher = threading.Thread(target=lambda: box.append(_stalled(owner)), daemon=True)
            launcher.start()
            assert before_fork.wait(4)
            guardian.kill()
            assert until(lambda: guardian.poll() is not None, 3)
            allow_fork.set()
            launcher.join(6)
            thread, (pid, start), _ = box[0]
        result = owner.shutdown()
        assert until(lambda: not live(pid, start), 3), "the orderly end ended the stalled start"
        assert result in ([], [-1]), result
    finally:
        allow_fork.set()
        if pid is not None and live(pid, start):
            os.kill(pid, signal.SIGKILL)
        if thread is not None:
            thread.join(3)
        owner.shutdown()


# --------------------------------------------------------------------------- 4

def test_the_converters_contained_step_returns_within_c2_when_forced_stops_are_refused(tmp_path):
    from m4b import m4b_continuous as mc
    from m4b import m4b_execution as ex

    root = tmp_path.resolve()

    def standin(name):
        (root / name).mkdir()
        program, ready = root / name / "ffmpeg", root / name / "ready"
        program.write_text(f"#!/bin/sh\ntrap '' TERM\nprintf ready > '{ready}'\nexec /bin/sleep 20\n")
        program.chmod(0o700)
        return program, ready

    enc, enc_ready = standin("enc")
    dec, dec_ready = standin("dec")
    owner, ctl = co.Owner(), JobController("c2", cancel_clock=time.monotonic)
    ctl.start()
    decoder = mc.ContinuousDecoder(SimpleNamespace(frame_bytes=4, sample_rate=100), ffmpeg=str(dec),
                                   source=root / "source", workspace=root)
    results: dict = {}
    refused = threading.Event()
    saved = owner._deliver

    def deliver(entry, sig):
        if not refused.is_set() and entry.kind == co.CLASS_B and sig == signal.SIGKILL:
            return False
        return saved(entry, sig)

    def work():
        with sp.run_context(ctl.cancel_check):
            decoder.start()
            results["step"] = ex.run_argv_streaming(
                [str(enc)], feed=lambda write: write(decoder._proc.stdout.read(4)), cancelled=ctl.cancel_check,
                workspace=root, on_stop=decoder.close)
            results["step_s"] = time.monotonic() - ctl.cancel_clicked_at
            results["problem"] = sp.containment_problem(ctl.cancel_check)

    with patch.object(sp, "_owner", owner), patch.object(owner, "_deliver", deliver):
        try:
            thread = threading.Thread(target=work, daemon=True)
            thread.start()
            assert until(lambda: enc_ready.exists() and dec_ready.exists(), 10)
            ctl.request_cancel()
            thread.join(8)
            assert not thread.is_alive()
            assert results["step_s"] < ex.C2_STEP_S, f"{results['step_s']:.3f}s"
            assert results["step"].unreaped and results["problem"], "reported, never a clean stop"
        finally:
            refused.set()
            owner.shutdown()


# --------------------------------------------------------------------------- 5

def test_a_worker_handed_over_is_given_to_the_owner_that_started_it():
    """Found while bisecting an order-dependent failure: ``qwen3_process.hand_over`` asked only the app window's owner,
    so a worker of another owner (OmniVoice's command-line route has its own) whose group was not confirmed ended was
    handed to nobody -- never reaped, and every later run of the process stayed unsettled."""
    from tts import qwen3_process

    owner = co.Owner()
    try:
        with patch.object(sp, "_owner", None), patch.object(qwen3_process, "_posix_owner", lambda cmd: owner):
            proc = qwen3_process.spawn([sys.executable, "-c", "import time; time.sleep(30)"], require_job=True,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        assert proc.act_owner is owner
        os.kill(proc.pid, signal.SIGKILL)
        assert until(lambda: co._has_exited(proc.pid), 3)
        with patch.object(sp, "_owner", None):  # no app window here: the worker's own owner must be asked
            qwen3_process.hand_over(proc)
        assert until(lambda: proc.returncode is not None, 4), "its own owner retired and reaped it"
        assert owner.child(proc) is None
    finally:
        owner.shutdown()
