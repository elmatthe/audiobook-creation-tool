"""v0.8.x P5-I-R3, remediation 2: the independent re-review of c371695 (REJECTED: 3 BLOCKER, 6 HIGH, 3 MEDIUM).

Each test reproduces the reviewer's interleaving (its probes, ``remed-2/`` in the evidence folder) with real processes
and its fault injection, and asserts the fixed outcome:

1. TTS settles FAILED, never CANCELLED, after a recorded uncontained start (``subprocess_utils.run_faults``);
2. a Qwen3 worker whose group cannot be confirmed ended is never reaped (its id keeps the group reserved) and the run
   is never settled clean;
3. a class-A child the owner never announced -- stopped, owner killed -- is ended by the guardian's token sweep, and
   so is a descendant that left its group with ``setsid``;
4. a concurrent fork holding the go writer never holds the Cancel latch (socket-pair take-back, MSG_DONTWAIT);
5. a grant whose G is already written cannot execute after the closing latch (closing cuts at once);
6. a start refused by the Cancel ordering is acknowledged: M4B Maker ends CANCELLED, not stuck;
7. the Converter's contained stop follows the C2 schedule (inside 4 s), and the packet scan finds the click;
8. a contained decoder not confirmed ended never blocks ``close()`` on its pipe;
9. a reaped child pruned at another admission keeps its lost-containment evidence;
10. the guardian works with descendants above 1024;
12. the packet scan on the released (Windows / uncontained) path is the released code.
macOS only.
"""

from __future__ import annotations
#: C1, Cancel acknowledgment: about one second (owner decision 2026-11-20; was 0.5 s).
C1_ACK_S = 1.0

import contextlib
import errno
import os
import signal
import subprocess
import sys
import tempfile
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


def until(predicate, timeout=5.0):
    end = time.monotonic() + timeout
    while not predicate() and time.monotonic() < end:
        time.sleep(0.005)
    return predicate()


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
            yield owner, controller, Path(work)
        finally:
            owner.shutdown()


def program(work: Path, body: str) -> Path:
    path = work / "ffmpeg"
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o700)
    return path


def stopped(pid) -> bool:
    info = co._darwin_kinfo(pid)
    return info is not None and info[co._P_STAT_OFFSET] == 4


def live(pid, start) -> bool:
    return start is not None and co.process_start_time(pid) == start and not co._has_exited(pid)


# --------------------------------------------------------------------------- 1 (BLOCKER)

def test_tts_settles_failed_after_a_recorded_uncontained_start():
    import queue

    import test_macos_p5i_r3_remediation as earlier
    from shared.job_control import RunResult
    from tts import epub2tts_gui as gui

    with setup("tts-fault") as (owner, ctl, work):
        marker = work / "ran"
        path = earlier._marker_program(work / "bin", marker)
        gate, _, _ = earlier._stopped_gate_with_everything_refused(owner, ctl, path, take_back=False)
        raw = owner._deliver
        with patch.object(owner, "_deliver", lambda e, s: False if e is gate else raw(e, s)):
            os.kill(gate.pid, signal.SIGCONT)
            assert until(marker.exists)
            assert until(lambda: gate.proc.poll() is not None)
        assert sp.run_faults(ctl.cancel_check), "the uncontained start is on record"
        ctx = gui._RunContext.__new__(gui._RunContext)
        ctx.cancel_check, ctx.controller, ctx.cancelled = ctl.cancel_check, ctl, True
        ctx.unstopped, ctx.completed, ctx.failures = [], [], []
        ctx.snapshot, ctx.log_q = SimpleNamespace(snapshot_id="tts-fault"), queue.Queue()
        ctx.stopped, ctx.not_started = 1, 0
        terminal = []
        ctx.publisher = SimpleNamespace(cancelled=lambda final: terminal.append("CANCELLED"))
        ctx.settle_fatal = lambda exc: terminal.append(("FAILED", str(exc)))
        with patch.object(RunResult, "settle", return_value=object()):
            ctx.settle()
        assert terminal and terminal[0][0] == "FAILED" and "uncontained" in terminal[0][1], terminal


# --------------------------------------------------------------------------- 2 (BLOCKER)

def test_a_qwen3_worker_whose_group_cannot_be_ended_is_never_reaped_or_settled_clean():
    from tts import ffmpeg_watch
    from tts import qwen3_synth as qs

    with setup("qwen-group") as (owner, ctl, work):
        stub = work / "worker.py"
        stub.write_text("import os, subprocess, time\nfrom pathlib import Path\nwork = Path.cwd()\n"
                        "child = subprocess.Popen(['/bin/sleep', '15'], stdout=subprocess.DEVNULL, "
                        "stderr=subprocess.DEVNULL)\n(work / 'ready').write_text(f'{os.getpid()} {child.pid}')\n"
                        "while not (work / 'cancel').exists(): time.sleep(0.01)\n", encoding="utf-8")
        thread, result = spawn_call(lambda: qs.run_worker(
            {"cancel_file": str(work / "cancel")}, work, python=Path(sys.executable), script=stub,
            env=os.environ.copy(), cancel_check=ctl.cancel_check))
        assert until(lambda: (work / "ready").exists(), 20)
        leader, helper = map(int, (work / "ready").read_text().split())
        helper_start = co.process_start_time(helper)
        saved = os.killpg

        def refuse(pid, sig):
            if pid == leader:
                raise OSError(errno.EIO, "injected group signal refusal")
            saved(pid, sig)

        try:
            with patch.object(os, "killpg", refuse):
                ctl.request_cancel()
                thread.join(20)
                assert result and isinstance(result[0], qs.Qwen3Failed), result
                assert co.process_start_time(leader) is not None, "the leader was reaped with its group unconfirmed"
                assert leader in ffmpeg_watch.settle_children(ctl.cancel_check), "never a clean settlement"
            # Group signals work again: the owner ends the group, and only then reaps the leader.
            assert until(lambda: not live(helper, helper_start), 15), "the owner kept ending the group"
            assert until(lambda: co.process_start_time(leader) is None, 15)
        finally:
            if live(helper, helper_start):
                os.kill(helper, signal.SIGKILL)


# --------------------------------------------------------------------------- 3 (BLOCKER)

OWNER_SCRIPT = """import os, signal, subprocess, sys, time
from shared import child_ownership as co
owner = co.Owner()
owner.ensure_guardian()
mode = sys.argv[1]
if mode == "unannounced":
    def pause_before_announcement():
        child = next(c for c in owner.children() if c.kind == co.CLASS_A)
        os.kill(child.pid, signal.SIGSTOP)
        print(child.pid, owner.guardian_pid(), flush=True)
        while True:
            time.sleep(1)
    owner._announce_leaders = pause_before_announcement
    owner.popen_python([sys.executable, "-c", "import time; time.sleep(30)"])
else:  # "escaped": a descendant that leaves its group and session
    proc = owner.popen_python([sys.executable, "-c",
        "import os, subprocess, sys, time; "
        "p = subprocess.Popen([sys.executable, '-c', 'import os, time; os.setsid(); time.sleep(30)']); "
        "print(p.pid, flush=True); time.sleep(30)"], stdout=subprocess.PIPE, text=True)
    escaped = int(proc.stdout.readline())
    print(escaped, owner.guardian_pid(), flush=True)
    time.sleep(30)
"""


@pytest.mark.parametrize("mode", ["unannounced", "escaped"])
def test_the_guardian_ends_every_python_descendant_of_a_dead_owner(tmp_path, mode):
    scripts = Path(co.__file__).resolve().parents[1]
    src = tmp_path / "owner.py"
    src.write_text(OWNER_SCRIPT, encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(scripts))
    owner_proc = subprocess.Popen([sys.executable, "-B", str(src), mode], stdout=subprocess.PIPE, text=True, env=env)
    child, guardian = map(int, owner_proc.stdout.readline().split())
    child_start = co.process_start_time(child)
    try:
        if mode == "unannounced":
            assert until(lambda: stopped(child))
        else:
            assert until(lambda: os.getsid(child) == child), "it left its group and session"
        owner_proc.kill()
        owner_proc.wait(5)
        assert until(lambda: co._has_exited(guardian), 10)
        assert until(lambda: not live(child, child_start), 5), f"{mode} child outlived its dead owner"
    finally:
        if live(child, child_start):
            os.kill(child, signal.SIGKILL)
        owner_proc.stdout.close()


# --------------------------------------------------------------------------- 4 (HIGH)

def test_a_concurrent_fork_holding_the_go_writer_never_holds_the_cancel_latch():
    with setup("concurrent-popen") as (owner, ctl, work):
        path = program(work, "exit 0\n")
        r, w = os.pipe()
        entered = threading.Event()
        original_write = os.write
        forks: list = []

        def pre_exec():
            original_write(w, b"R")
            time.sleep(1.15)

        def write(fd, data):
            if data == b"G" and not forks:
                forks.append(spawn_call(lambda: subprocess.Popen(["/bin/sleep", "0"], preexec_fn=pre_exec)))
                assert os.read(r, 1) == b"R"
                answer = original_write(fd, data)
                entered.set()
                return answer
            return original_write(fd, data)

        try:
            with patch.object(os, "write", write):
                launch, _ = spawn_call(lambda: owner.popen_external([str(path)], **sp._launch_kwargs(ctl.cancel_check)))
                assert entered.wait(5)
                ctl.request_cancel()
                held = time.monotonic() - ctl.cancel_clicked_at
                launch.join(5)
            assert held < C1_ACK_S, f"C1: the latch took {held:.3f} s"
        finally:
            for thread, result in forks:
                thread.join(5)
                if result and isinstance(result[0], subprocess.Popen):
                    result[0].wait(5)
            os.close(r)
            os.close(w)


# --------------------------------------------------------------------------- 5 (HIGH)

def test_a_grant_whose_go_is_already_written_never_executes_after_the_closing_latch():
    with setup("close-late") as (owner, ctl, work):
        marker = work / "ran"
        path = program(work, 'printf ran > "$1"\n')
        ready, resume_grant = threading.Event(), threading.Event()
        orig_write, orig_outcome = os.write, owner._exec_outcome
        gate: list = []

        def write(fd, data):
            if data == b"G" and not gate:
                entry = owner.outstanding(ctl.cancel_check)[0]
                gate.append(entry)
                os.kill(entry.pid, signal.SIGSTOP)
                assert until(lambda: stopped(entry.pid))
                answer = orig_write(fd, data)
                ready.set()
                return answer
            return orig_write(fd, data)

        def outcome(*args, **kwargs):
            assert resume_grant.wait(5)
            return orig_outcome(*args, **kwargs)

        with patch.object(os, "write", write), patch.object(owner, "_exec_outcome", outcome):
            launcher, _ = spawn_call(lambda: owner.popen_external([str(path), str(marker)],
                                                                  **sp._launch_kwargs(ctl.cancel_check)))
            assert ready.wait(5)
            closer, _ = spawn_call(owner.begin_closing)
            try:
                assert until(lambda: owner.closing)
                os.kill(gate[0].pid, signal.SIGCONT)
                assert not until(marker.exists, 0.5), "the program ran after the closing latch"
            finally:
                resume_grant.set()
                launcher.join(5)
                closer.join(5)


# --------------------------------------------------------------------------- 6 (HIGH)

def test_a_maker_run_cancelled_before_its_first_grant_ends_cancelled():
    import test_ffmpeg_cancel as maker_tests
    from shared import ffmpeg_utils
    from shared.job_control import JobState

    if not ffmpeg_utils.have_ffmpeg():
        pytest.skip("requires the app's verified FFmpeg")
    with setup("maker-ack") as (owner, _ctl, work):
        _made, run, _sources = maker_tests._maker_run(work)
        attempt = run.start()
        ready, resumed = threading.Event(), threading.Event()
        original = owner._grant
        first: list = []

        def grant(launch):
            if not first:
                first.append(launch)
                ready.set()
                assert resumed.wait(5)
            return original(launch)

        with patch.object(owner, "_grant", grant):
            thread, result = spawn_call(attempt.run)
            assert ready.wait(10)
            run.cancel()
            resumed.set()
            thread.join(10)
        assert attempt.controller.state is JobState.CANCELLED, (attempt.controller.state, result)
        assert owner.outstanding(attempt.controller.cancel_check) == []


# --------------------------------------------------------------------------- 7 (HIGH)

def test_the_converters_contained_stop_follows_the_c2_schedule():
    from m4b import m4b_execution as ex

    with setup("converter-bound") as (owner, ctl, work):
        path = program(work, 'trap "" TERM\nprintf ready > "$1"\nexec /bin/sleep 20\n')
        marker = work / "ready"

        def run():
            with sp.run_context(ctl.cancel_check):
                return ex.run_argv([str(path), str(marker)], cancelled=ctl.cancel_check, workspace=work)

        thread, result = spawn_call(run)
        assert until(marker.exists)
        ctl.request_cancel()
        thread.join(10)
        took = time.monotonic() - ctl.cancel_clicked_at
        assert result and result[0].cancelled and not result[0].unreaped, result
        assert took < 4.0, f"C2: {took:.3f} s from the click"


def test_settle_bound_finds_the_click_through_a_wrapping_check():
    controller = JobController("wrapped", cancel_clock=time.monotonic)
    controller.start()

    def asked_to_stop() -> bool:
        return controller.cancel_check()

    asked_to_stop.controller = controller
    controller.request_cancel()
    assert sp.settle_bound(asked_to_stop, 4.0) <= 4.0
    time.sleep(0.3)
    assert sp.settle_bound(asked_to_stop, 4.0) < 3.8, "measured from the click, not from now"


# --------------------------------------------------------------------------- 8 (HIGH)

def test_a_contained_decoder_not_confirmed_ended_never_blocks_close_on_its_pipe():
    from m4b import m4b_continuous as mc

    with setup("decoder") as (owner, ctl, work):
        path = program(work, "exec /bin/sleep 20\n")
        with sp.run_context(ctl.cancel_check):
            decoder = mc.ContinuousDecoder(SimpleNamespace(frame_bytes=4, sample_rate=1), ffmpeg=str(path),
                                           source=work / "dummy", workspace=work)
            decoder.start()
        proc = decoder._proc
        feeder, _ = spawn_call(lambda: proc.stdout.read(4))  # holds the buffered pipe's lock in read
        time.sleep(0.05)
        original = owner._deliver
        try:
            with patch.object(owner, "_deliver", lambda e, s: False if e.pid == proc.pid else original(e, s)):
                ctl.request_cancel()
                began = time.monotonic()
                closer, result = spawn_call(decoder.close)
                closer.join(6)
                assert not closer.is_alive(), f"close() still blocked after {time.monotonic() - began:.2f} s"
                assert result == [False], "not confirmed ended: reported, never claimed"
        finally:
            with contextlib.suppress(OSError):
                os.kill(proc.pid, signal.SIGKILL)
            feeder.join(5)


# --------------------------------------------------------------------------- 9 (HIGH)

def test_a_reaped_child_pruned_at_another_admission_keeps_its_lost_containment():
    with setup("prune") as (owner, ctl, work):
        marker, start = work / "exit", work / "started"
        path = program(work, 'printf ready > "$2"\nwhile [ ! -f "$1" ]; do :; done\n')
        original_forget, original_admit = owner.forget, owner._admit
        check, forget, prepare, admit = (threading.Event() for _ in range(4))

        def before_forget(child):
            check.set()
            assert forget.wait(5)
            original_forget(child)

        def before_admit(*args, **kwargs):
            if kwargs.get("label") == "next":
                prepare.set()
                assert admit.wait(5)
            return original_admit(*args, **kwargs)

        def first():
            with sp.run_context(ctl.cancel_check):
                return sp.run_supervised([str(path), str(marker), str(start)])

        guardian = owner._current.proc
        with patch.object(owner, "_guardian_lost"), patch.object(owner, "forget", before_forget), \
                patch.object(owner, "_admit", before_admit):
            run, result = spawn_call(first)
            assert until(start.exists)
            nxt, _ = spawn_call(lambda: owner.popen_external(["/bin/echo", "next"], label="next"))
            assert prepare.wait(5)
            guardian.kill()
            assert until(lambda: co.has_exited(guardian))
            marker.touch()
            assert check.wait(5)
            admit.set()
            assert until(lambda: not any(e.label == "ffmpeg" for e in owner.children()))
            forget.set()
            run.join(5)
            nxt.join(5)
        assert result and result[0].returncode != 0 and b"lost containment" in result[0].stderr, result


# --------------------------------------------------------------------------- 10 (MEDIUM)

def test_a_guardian_started_with_descriptors_above_1024_works():
    import resource

    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if soft < 1100:
        if hard != resource.RLIM_INFINITY and hard < 1100:
            pytest.skip("the descriptor limit cannot be raised here")
        resource.setrlimit(resource.RLIMIT_NOFILE, (1100, hard))
    fds: list = []
    owner = co.Owner()
    try:
        while not fds or fds[-1] < 1030:
            fds.append(os.open(os.devnull, os.O_RDONLY))
        owner.ensure_guardian()  # its lifeline descriptor is above 1024
        proc = owner.popen_external(["/bin/echo", "ok"], stdout=subprocess.PIPE)
        assert proc.communicate(timeout=10) == (b"ok\n", None) and proc.returncode == 0
        assert not owner.degraded and not any("ended on its own" in e for e in owner.events), owner.events
    finally:
        owner.shutdown()
        for fd in fds:
            os.close(fd)
        resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))


# --------------------------------------------------------------------------- 12 (MEDIUM)

def test_the_released_packet_scan_runs_wherever_the_scan_is_not_contained(monkeypatch):
    from m4b import m4b_continuous as mc

    calls = []
    monkeypatch.setattr(mc, "_scan_packets_released", lambda *a, **k: calls.append(k) or "released")
    monkeypatch.setattr(sp, "_owner", None)
    assert mc.scan_packets("x.m4b", total=1, priming=0, duration_seconds=1, cancelled=lambda: False,
                           ffprobe="/bin/ffprobe") == "released"
    assert calls, "uncontained (Windows): the released scan"
