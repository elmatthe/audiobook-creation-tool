"""v0.8.x P5-I-R3, remediation 3: the independent review of 6a8ff15 (REJECTED, 13 findings).

Each test reproduces the reviewer's interleaving (its probes, ``remed-3/`` in the evidence folder) with real processes
and its fault injection, and asserts the fixed outcome:

1. the guardian's sweep matches an exact environment entry only -- never argv, never a substring of a value;
2. a Qwen3 worker whose group cannot be ended (``kill_tree``) is handed over, never reaped, and its run names it;
3. a helper that left the worker's group (``setsid``) is ended with the worker (its leader token);
4. a local-engine retirement still in progress makes the TTS run FAILED, never CANCELLED;
5. a process created by a ``Popen`` that then raised is kept, retired, and reported;
6. an observed guardian loss is repaired at once: the app's death still ends a stopped class-A worker;
7. no program executes after the closing latch, even with its grant held at the last moment;
8. closing never reads a descriptor number the launch already closed (an unrelated socket keeps its data);
9. a stalled file-system call never holds the Cancel latch (the permit is made before the counted start; revocation's
   file-system steps are bounded);
10. Cancel during a worker's finalization (its output already ended) is acted on within the route's grace;
11. the Converter stops a contained encoder and its decoder in one stop window;
12. an unreadable identity is never taken for an exit: the stop goes on to signal;
13. the gate executes the program with the caller's exact environment, and the uncontained Converter keeps the
    released cancelled-before-unreaped order.
macOS only.
"""

from __future__ import annotations
#: C1, Cancel acknowledgment: about one second (owner decision 2026-11-20; was 0.5 s).
C1_ACK_S = 1.0

import contextlib
import errno
import os
import queue
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from shared import child_guardian as cg
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


def stopped(pid) -> bool:
    info = co._darwin_kinfo(pid)
    return info is not None and info[co._P_STAT_OFFSET] == 4


def spawn_call(fn):
    result: list = []

    def run():
        try:
            result.append(fn())
        except BaseException as exc:  # noqa: BLE001 - the outcome is the assertion
            result.append(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, result


@contextlib.contextmanager
def setup(name):
    owner = co.Owner()
    owner.ensure_guardian()
    controller = JobController(name, cancel_clock=time.monotonic)
    controller.start()
    with tempfile.TemporaryDirectory() as work, patch.object(sp, "_owner", owner):
        try:
            yield owner, controller, Path(work).resolve()
        finally:
            owner.shutdown()


# --------------------------------------------------------------------------- 1

def test_the_sweep_matches_an_exact_environment_entry_only():
    token = uuid.uuid4().hex
    key = f"{co.CHILD_TOKEN_ENV}_{token}"
    sleeper = [sys.executable, "-c", "import time; time.sleep(15)"]
    children = [
        subprocess.Popen(sleeper + [key + "=1"], start_new_session=True),  # argv only
        subprocess.Popen(sleeper, env={**os.environ, "QA_TEXT": f"prefix_{key}=1_suffix"}, start_new_session=True),
        subprocess.Popen(sleeper, env={**os.environ, key: "1"}, start_new_session=True),  # the control: marked
    ]
    try:
        assert until(lambda: all(cg._environment(c.pid) for c in children))
        with patch.object(cg, "_all_pids", lambda: [c.pid for c in children]):
            cg._sweep(token)
        assert children[2].wait(3) == -signal.SIGKILL, "the marked process is swept"
        time.sleep(0.2)
        assert children[0].poll() is None, "a token in argv is not a mark"
        assert children[1].poll() is None, "a token inside another variable's value is not a mark"
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait(3)


# --------------------------------------------------------------------------- 2, 3, 10 (worker routes)

def _route(tmp_path, mode, *, omni=False):
    """The reviewer's route probe: a stand-in worker run through the real ``run_worker`` and its real ``kill_tree``."""
    from tts import ffmpeg_watch, omnivoice_synth, qwen3_synth

    synth = omnivoice_synth if omni else qwen3_synth
    ctl = JobController("route", cancel_clock=time.monotonic)
    ctl.start()
    owner = co.Owner()
    records: queue.Queue = queue.Queue()
    root = tmp_path.resolve()
    worker, ready, flag, leave = root / "worker.py", root / "ready", root / "cancel", root / "leave"
    worker.write_text(f"""
import os, pathlib, subprocess, sys, time
ready, flag, leave = map(pathlib.Path, ({str(ready)!r}, {str(flag)!r}, {str(leave)!r}))
mode = {mode!r}
if mode == 'eof':
    os.close(1)
    ready.write_text(str(os.getpid()))
    time.sleep(14)
else:
    p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)'], start_new_session=mode == 'escape',
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ready.write_text(f'{{os.getpid()}} {{p.pid}}')
    while not (leave if mode == 'refused' else flag).exists():
        time.sleep(0.01)
""")
    settling = threading.Event()
    real_settle = synth._settle_led_worker
    group_kill = os.killpg
    leader = helper = leader_start = helper_start = None

    def signal_group(pid, sig):
        if mode == "refused" and pid == leader:
            leave.touch()
            raise OSError(errno.EIO, "injected group-signal refusal")
        return group_kill(pid, sig)

    def settle(*args, **kwargs):
        settling.set()
        return real_settle(*args, **kwargs)

    def run():
        try:
            records.put(synth.run_worker({"cancel_file": str(flag)}, root, python=Path(sys.executable),
                                         script=worker, env=os.environ.copy(), cancel_check=ctl.cancel_check,
                                         grace_s=0.15 if mode == "refused" else 3,
                                         **({"name": "probe"} if omni else {})))
        except BaseException as exc:  # noqa: BLE001 - the outcome is the assertion
            records.put(exc)

    thread = threading.Thread(target=run, daemon=True)
    outcome = {}
    try:
        with patch.object(sp, "_owner", owner), patch.object(os, "killpg", signal_group), \
                patch.object(synth, "_settle_led_worker", settle):
            thread.start()
            assert until(lambda: ready.exists() and ready.stat().st_size, 10)
            pids = [int(x) for x in ready.read_text().split()]
            leader, *rest = pids
            leader_start = co.process_start_time(leader)
            helper = rest[0] if rest else None
            helper_start = co.process_start_time(helper) if helper else None
            if mode == "eof":
                assert settling.wait(5)
            ctl.request_cancel()
            if mode == "eof":
                thread.join((4.0 if omni else 5.0) + 0.05)
                outcome.update(after_s=time.monotonic() - ctl.cancel_clicked_at, worker_alive=live(leader, leader_start),
                               flag=flag.exists(), result=records.get(timeout=1) if not thread.is_alive() else None)
            else:
                outcome.update(result=records.get(timeout=8))
                outcome.update(leader_reaped=co.process_start_time(leader) is None,
                               helper_alive=live(helper, helper_start) if helper else False)
            outcome["settlement"] = ffmpeg_watch.settle_children(ctl.cancel_check)
            outcome["leader"] = leader
        return outcome
    finally:
        if helper is not None and live(helper, helper_start):
            os.kill(helper, signal.SIGKILL)
        if leader is not None and live(leader, leader_start):
            os.kill(leader, signal.SIGKILL)
        thread.join(5)
        owner.shutdown()


@pytest.mark.parametrize("omni", [False, True], ids=["qwen3", "omnivoice"])
def test_a_worker_whose_group_cannot_be_ended_is_handed_over_never_reaped(tmp_path, omni):
    out = _route(tmp_path, "refused", omni=omni)
    assert type(out["result"]).__name__ in ("Qwen3Failed", "OmniVoiceFailed"), out
    assert "could not be confirmed stopped" in str(out["result"])
    assert out["leader_reaped"] is False, "its id keeps the group reserved"
    assert out["leader"] in out["settlement"], "the run's settlement names the worker"


def test_a_helper_that_left_the_workers_group_ends_with_the_worker(tmp_path):
    out = _route(tmp_path, "escape")
    assert type(out["result"]).__name__ == "ConversionCancelled", out
    assert out["helper_alive"] is False, "the leader token reaches a setsid helper"
    assert out["settlement"] == []


@pytest.mark.parametrize("omni", [False, True], ids=["qwen3", "omnivoice"])
def test_cancel_during_a_workers_finalization_is_acted_on_within_the_route_grace(tmp_path, omni):
    out = _route(tmp_path, "eof", omni=omni)
    assert out["worker_alive"] is False, out
    assert out["flag"], "the worker was told"
    assert out["after_s"] <= (4.0 if omni else 5.0), out
    assert type(out["result"]).__name__ == "ConversionCancelled", out
    assert out["settlement"] == []


def test_a_contained_worker_spawn_carries_its_run():
    from tts import qwen3_process

    owner = co.Owner()
    check = lambda: False  # noqa: E731 - the run's identity only
    try:
        with patch.object(sp, "_owner", owner), patch.object(qwen3_process, "_posix_owner", lambda cmd: owner):
            proc = qwen3_process.spawn([sys.executable, "-c", "import time; time.sleep(5)"], require_job=True,
                                       run=check, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        assert owner.child(proc).run is check
        assert owner.outstanding(check), "the run's settlement sees it"
    finally:
        owner.shutdown()


# --------------------------------------------------------------------------- 4

def test_a_local_engine_retirement_in_progress_makes_the_run_failed():
    from shared.job_control import RunResult
    from tts import epub2tts_gui as gui
    from tts import local_engine_host as hosts

    owner = co.Owner()
    stub = HERE / "local_engine_stub.py"
    host = hosts.WorkerHost("kokoro", sample_rate=24000, argv=[sys.executable, "-I", "-B", str(stub), "kokoro"],
                            owner=owner)
    controller = JobController("idle", cancel_clock=time.monotonic)
    controller.start()
    began, release = threading.Event(), threading.Event()
    real_end = co.end_led_group
    terminal: list = []
    ctx = gui._RunContext.__new__(gui._RunContext)
    ctx.cancel_check, ctx.controller, ctx.cancelled = controller.cancel_check, controller, True
    ctx.unstopped, ctx.completed, ctx.failures = [], [], []
    ctx.snapshot, ctx.log_q = SimpleNamespace(snapshot_id="idle"), queue.Queue()
    ctx.stopped, ctx.not_started = 0, 1
    ctx.publisher = SimpleNamespace(cancelled=lambda final: terminal.append("CANCELLED"))
    ctx.settle_fatal = lambda exc: terminal.append(("FAILED", str(exc)))
    worker = None

    def end(proc, start, **kwargs):
        if proc is worker:
            began.set()
            assert release.wait(5)
        return real_end(proc, start, **kwargs)

    saved = hosts._HOST
    try:
        with patch.object(sp, "_owner", owner), patch.object(gui, "LOCAL_ENGINE_STOP_S", 0.3):
            host.ensure_started()
            worker = host._proc
            hosts._HOST = host
            controller.request_cancel()
            with patch.object(co, "end_led_group", end), patch.object(RunResult, "settle", return_value=object()):
                try:
                    hosts.cancel_requested("kokoro")
                    assert began.wait(3)
                    ctx.settle()
                finally:
                    release.set()
        assert terminal and terminal[0][0] == "FAILED", terminal
    finally:
        hosts._HOST = saved
        host.close("test over")
        owner.shutdown()


# --------------------------------------------------------------------------- 5

def test_a_process_created_by_a_popen_that_raised_is_kept_retired_and_reported(tmp_path):
    owner = co.Owner()
    owner.ensure_guardian()
    marker = (tmp_path / "pid").resolve()
    made: list = []
    execute = subprocess.Popen._execute_child

    def partial_exec(self, args, *a, **k):
        execute(self, args, *a, **k)
        if str(co.ENTRY) in args:
            made.append(self)
            assert until(marker.exists)
            raise OSError(errno.EIO, "injected parent-side failure after creation")

    try:
        with patch.object(subprocess.Popen, "_execute_child", partial_exec):
            with pytest.raises(co.ContainmentUnavailable, match="after its process was created"):
                owner.popen_python([sys.executable, "-c", "import os, pathlib, sys, time; "
                                    "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(15)",
                                    str(marker)])
        child = made[0]
        start = co.process_start_time(child.pid)
        assert until(lambda: not live(child.pid, start), 4), "it was retired"
        assert [e for e in owner.outstanding() if e.pid == child.pid] or child.returncode is not None
    finally:
        for child in made:
            if child.poll() is None:
                child.kill()
            child.wait(3)
        owner.shutdown()


# --------------------------------------------------------------------------- 6

def test_a_lost_guardian_is_replaced_at_once_while_class_a_children_run():
    app_source = """
import sys, time
from shared import child_ownership as co
o = co.Owner()
worker = o.popen_python([sys.executable, '-c', 'import time; time.sleep(16)'])
print(worker.pid, o.guardian_pid(), flush=True)
until = time.monotonic() + 10
while not o.degraded and time.monotonic() < until:
    time.sleep(0.01)
replaced = time.monotonic() + 3
while o.guardian_pid() in (None,) and time.monotonic() < replaced:
    time.sleep(0.01)
print('loss', o.degraded, flush=True)
time.sleep(16)
"""
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT / "scripts"), os.environ.get("PYTHONPATH", "")]))
    with subprocess.Popen([sys.executable, "-B", "-c", app_source], env=env, stdout=subprocess.PIPE, text=True,
                          start_new_session=True) as app:
        worker, guardian = map(int, app.stdout.readline().split())
        worker_start, guardian_start = co.process_start_time(worker), co.process_start_time(guardian)
        try:
            os.kill(worker, signal.SIGSTOP)  # it cannot act on its own lifeline
            assert until(lambda: stopped(worker))
            os.kill(guardian, signal.SIGKILL)
            assert app.stdout.readline().startswith("loss True")
            time.sleep(0.5)  # the replacement is started off the loss handler's thread
            app.kill()
            app.wait(3)
            assert until(lambda: not live(worker, worker_start), 5), "the replacement guardian ended the worker"
        finally:
            if live(worker, worker_start):
                os.kill(worker, signal.SIGKILL)
            if app.poll() is None:
                app.kill()


# --------------------------------------------------------------------------- 7

def test_no_program_executes_after_the_closing_latch_with_its_grant_held_at_the_last_moment():
    with setup("close") as (owner, ctl, work):
        marker = work / "ran"
        target = work / "ffmpeg"
        target.write_text(f"#!/bin/sh\nprintf ran > '{marker}'\n")
        target.chmod(0o700)
        at_last_look, resume = threading.Event(), threading.Event()
        real_outcome_flag = {"held": False}
        real_lock_enter = None

        class HeldLock:
            """The grant's go_lock, held open at the moment it would write G (the reviewer's interleaving)."""

            def __init__(self, lock):
                self._lock = lock

            def __enter__(self):
                if not real_outcome_flag["held"] and threading.current_thread().name.startswith("act-launch"):
                    real_outcome_flag["held"] = True
                    at_last_look.set()
                    assert resume.wait(4)
                return self._lock.__enter__()

            def __exit__(self, *exc):
                return self._lock.__exit__(*exc)

        real_launch = co._Launch.__init__

        def launch_init(self, *args, **kwargs):
            real_launch(self, *args, **kwargs)
            self.go_lock = HeldLock(self.go_lock)

        in_cut, release_cut = threading.Event(), threading.Event()
        real_cut = owner._cut_grants

        def cut():  # the reviewer's interleaving: the closer is between publishing the latch and cutting grants
            in_cut.set()
            assert release_cut.wait(4)
            return real_cut()

        with patch.object(co._Launch, "__init__", launch_init), patch.object(owner, "_cut_grants", cut):
            launcher, result = spawn_call(lambda: owner.popen_external([str(target)],
                                                                       **sp._launch_kwargs(ctl.cancel_check)))
            assert at_last_look.wait(4)
            closer, _ = spawn_call(owner.begin_closing)
            try:
                assert in_cut.wait(4) and owner.closing
                resume.set()  # the grant reaches its G with the latch published and the cut not yet run
                launcher.join(4)
            finally:
                resume.set()
                release_cut.set()
                closer.join(4)
        time.sleep(0.2)
        assert not marker.exists(), "nothing executes once the orderly end is pending"
        assert isinstance(result[0], co.ContainmentUnavailable), result


# --------------------------------------------------------------------------- 8

def test_closing_never_reads_a_descriptor_number_the_launch_already_closed():
    owner = co.Owner()
    owner.ensure_guardian()
    ready, release_grant, close_at_cut, release_close = (threading.Event() for _ in range(4))
    state: dict = {}
    look, take = owner._exec_outcome, owner._take_back_go

    def outcome(launch, wait_s, *, cut):
        result = look(launch, wait_s, cut=cut)
        if cut and result == "exec":
            state["launch"] = launch
            ready.set()
            assert release_grant.wait(4)
        return result

    def take_back(launch):
        if threading.current_thread().name == "test-close":
            state["fd"] = launch.go_back
            close_at_cut.set()
            assert release_close.wait(4)
        return take(launch)

    starter, _ = spawn_call(lambda: owner.popen_external(["/bin/sleep", "8"]))
    closer = threading.Thread(target=owner.begin_closing, daemon=True, name="test-close")
    reader = sender = None
    extra = None
    try:
        with patch.object(owner, "_exec_outcome", outcome), patch.object(owner, "_take_back_go", take_back):
            assert ready.wait(4)
            closer.start()
            assert close_at_cut.wait(4)
            release_grant.set()
            assert state["launch"].done.wait(4)
            old = state["fd"]
            reader, sender = socket.socketpair()
            if sender.fileno() == old:
                reader, sender = sender, reader
            elif reader.fileno() != old:
                try:
                    os.fstat(old)
                except OSError:
                    os.dup2(reader.fileno(), old, inheritable=False)
                    extra = old
                else:
                    pytest.skip("the descriptor number was reused before the controlled setup")
            sender.sendall(b"X")
            release_close.set()
            closer.join(4)
            assert not closer.is_alive()
            assert reader.recv(1, socket.MSG_DONTWAIT) == b"X", "the unrelated socket keeps its data"
    finally:
        release_grant.set()
        release_close.set()
        if extra is not None:
            os.close(extra)
        for s in (reader, sender):
            if s is not None:
                s.close()
        starter.join(4)
        closer.join(4)
        owner.shutdown()


# --------------------------------------------------------------------------- 9

def test_a_stalled_permit_creation_never_holds_the_cancel_latch():
    with setup("c1") as (owner, ctl, work):
        target = work / "ffmpeg"
        target.write_text("#!/bin/sh\nexit 0\n")
        target.chmod(0o700)
        creating, allow = threading.Event(), threading.Event()
        real_link = os.symlink

        def stalled_symlink(*args, **kwargs):
            real_link(*args, **kwargs)
            creating.set()
            assert allow.wait(4)

        with patch.object(os, "symlink", stalled_symlink):
            launcher, result = spawn_call(lambda: owner.popen_external([str(target)],
                                                                       **sp._launch_kwargs(ctl.cancel_check)))
            try:
                assert creating.wait(4)
                clicked = time.monotonic()
                ctl.request_cancel()
                assert time.monotonic() - clicked <= 0.5
                assert ctl.cancel_check(), "the latch is acknowledged"
            finally:
                allow.set()
                launcher.join(4)
        from shared.cancellation import ConversionCancelled

        assert isinstance(result[0], ConversionCancelled), result


def test_a_stalled_revocation_holds_the_counted_start_at_most_its_hold():
    with setup("revoke") as (owner, ctl, work):
        target = work / "ffmpeg"
        target.write_text("#!/bin/sh\nexec /bin/sleep 8\n")
        target.chmod(0o700)
        stall = threading.Event()
        granted = threading.Event()
        look = owner._exec_outcome

        def outcome(launch, wait_s, *, cut):
            if cut:
                granted.set()
                assert until(lambda: ctl.cancel_pending, 4)
            return look(launch, wait_s, cut=cut)

        with patch.object(owner, "_exec_outcome", outcome), \
                patch.object(co.Owner, "_make_permit_unusable", staticmethod(lambda launch: stall.wait(6))):
            launcher, result = spawn_call(lambda: owner.popen_external([str(target)],
                                                                       **sp._launch_kwargs(ctl.cancel_check)))
            try:
                assert granted.wait(4)
                clicked = time.monotonic()
                ctl.request_cancel()
                held = time.monotonic() - clicked
            finally:
                stall.set()
                launcher.join(4)
        assert held <= C1_ACK_S, f"the Cancel latch waited {held:.3f}s on a stalled file system"


def test_bounded_call_returns_by_its_bound():
    gate = threading.Event()
    began = time.monotonic()
    assert co._bounded_call(lambda: gate.wait(5), 0.1) == (False, None)
    assert time.monotonic() - began < 0.5
    gate.set()
    assert co._bounded_call(lambda: 7, 1.0) == (True, 7)
    assert co._bounded_call(lambda: 1 / 0, 1.0) == (True, None)


# --------------------------------------------------------------------------- 11

def test_the_converter_stops_a_contained_encoder_and_its_decoder_in_one_window(tmp_path):
    from m4b import m4b_continuous as mc
    from m4b import m4b_execution as ex

    owner = co.Owner()
    controller = JobController("stream", cancel_clock=time.monotonic)
    controller.start()
    results: queue.Queue = queue.Queue()
    root = tmp_path.resolve()

    def standin(name):
        folder = root / name
        folder.mkdir()
        command, marker = folder / "ffmpeg", folder / "ready"
        command.write_text(f"#!/bin/sh\ntrap '' TERM\nprintf ready > '{marker}'\nexec /bin/sleep 15\n")
        command.chmod(0o700)
        return command, marker

    try:
        with patch.object(sp, "_owner", owner):
            dec, dec_ready = standin("decoder")
            enc, enc_ready = standin("encoder")
            decoder = mc.ContinuousDecoder(SimpleNamespace(frame_bytes=4, sample_rate=100), ffmpeg=str(dec),
                                           source=root / "book.m4b", workspace=root)

            def work():
                with sp.run_context(controller.cancel_check):
                    decoder.start()
                    results.put(ex.run_argv_streaming(
                        [str(enc)], feed=lambda write: write(decoder._proc.stdout.read(4)),
                        cancelled=controller.cancel_check, workspace=root, on_stop=decoder.close))

            thread = threading.Thread(target=work, daemon=True)
            thread.start()
            assert until(lambda: dec_ready.exists() and enc_ready.exists(), 10)
            children = [e.proc for e in owner.children()]
            controller.request_cancel()
            result = results.get(timeout=8)
            elapsed = time.monotonic() - controller.cancel_clicked_at
            thread.join(3)
        assert result.cancelled
        assert [p.returncode for p in children] == [-9, -9]
        assert elapsed < ex.CONTAINED_TERM_GRACE_S + ex.CONTAINED_COLLECT_S, f"{elapsed:.3f}s: the stops ran serially"
    finally:
        owner.shutdown()


# --------------------------------------------------------------------------- 12

def test_an_unreadable_identity_is_never_taken_for_an_exit():
    owner = co.Owner()
    try:
        proc = owner.popen_external(["/bin/sleep", "12"])
        child = owner.child(proc)
        start = child.start_time
        child.start_time = None
        kinfo = co._darwin_kinfo
        with patch.object(co, "_darwin_kinfo", lambda pid: None if pid == proc.pid else kinfo(pid)), \
                patch.object(owner, "_deliver", wraps=owner._deliver) as delivered:
            assert co._has_exited(proc.pid) is False, "an unreadable record is not an exit"
            owner.end(proc, grace=0.0)
            assert delivered.call_count >= 1, "the stop signalled"
        assert not live(proc.pid, start)
    finally:
        owner.shutdown()


def test_a_process_that_is_gone_still_counts_as_exited_without_its_record():
    with patch.object(co, "_darwin_kinfo", lambda pid: None), patch.object(os, "kill",
                                                                           side_effect=ProcessLookupError):
        assert co._has_exited(123456) is True


# --------------------------------------------------------------------------- 13

@pytest.mark.parametrize("env", [{}, {"PATH": os.defpath, "QA_ENV": "yes"}, {"LC_ALL": "C", "QA_ENV": "yes"}],
                         ids=["empty", "path", "locale"])
def test_the_gate_executes_the_program_with_the_callers_exact_environment(env):
    owner = co.Owner()
    try:
        direct = subprocess.run(["/usr/bin/env"], env=env, capture_output=True, timeout=5)
        proc = owner.popen_external(["/usr/bin/env"], stdout=subprocess.PIPE, env=env)
        out, _ = proc.communicate(timeout=5)
        assert out == direct.stdout
    finally:
        owner.shutdown()


def test_the_gate_inherits_this_process_environment_when_none_is_given(monkeypatch):
    monkeypatch.setenv("ACT_QA_INHERITED", "kept")
    owner = co.Owner()
    try:
        proc = owner.popen_external(["/usr/bin/env"], stdout=subprocess.PIPE)
        out, _ = proc.communicate(timeout=5)
        assert b"ACT_QA_INHERITED=kept\n" in out
    finally:
        owner.shutdown()


def test_an_illegal_environment_is_refused_before_anything_starts():
    owner = co.Owner()
    try:
        with pytest.raises(ValueError):
            owner.popen_external(["/usr/bin/env"], env={"A=B": "x"})
        assert owner.outstanding() == []
    finally:
        owner.shutdown()


@pytest.mark.parametrize("contained", [False, True], ids=["uncontained-released-order", "contained"])
def test_the_converter_orders_cancelled_and_unreaped_by_containment(tmp_path, contained):
    from m4b import m4b_execution as ex
    from test_m4b_execution import book, whole_work

    book(tmp_path / "src", "Book.m4b")
    work = whole_work(tmp_path)
    outcome = ex.ProcessResult(None, cancelled=True, unreaped=True, killed=True)
    with patch.object(ex, "run_argv", return_value=outcome), \
            patch.object(sp, "containment_owner", return_value=object() if contained else None):
        result = ex.convert_segment(work, ffmpeg="ffmpeg", cancelled=lambda: False, measure=lambda _p: None)
    if contained:
        assert result.failed and not result.cancelled
    else:
        assert result.cancelled and not result.failed, "the released (Windows) order"
