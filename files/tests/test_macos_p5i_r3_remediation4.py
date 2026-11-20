"""v0.8.x P5-I-R3, remediation 4: what the two (content-filtered, verdict-less) reviews of d1b8b8c were probing.

Both review attempts were stopped by the reviewer's content filter before a verdict; their probes (``remed-4/`` in the
evidence folder) were run against d1b8b8c and six defects reproduced. Each test below is that probe with the fixed
outcome asserted, with real processes:

1. the owner's own retirement of a Python worker also ends its tagged descendants that left its session (a run was
   settled clean while one ran);
2. the start-up record is parsed exactly: an empty first argument no longer shifts the arguments into the environment;
3. the orderly end stays inside its 5 s when removing the permit folder stalls;
4. a cancelled TTS run begins its local-engine retirement itself, so it is never reported CANCELLED before the panel's
   own call; a retirement published but not yet started is waited for, never an error;
5. launch parity: a missing ``cwd`` raises ``FileNotFoundError`` as ``Popen`` does, ``PATH`` is read as ``Popen`` reads
   it (``bytes`` key), and a ``#!`` program sees the path it was started by as ``$0``;
6. a Python child stalled between fork and exec is announced at once and ended by the orderly end -- which tells the
   guardian on its registry, since such a child still holds the lifeline -- and when its owner dies.
macOS only.
"""

from __future__ import annotations

import contextlib
import os
import queue
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


# --------------------------------------------------------------------------- 1

def test_the_owners_own_retirement_ends_a_tagged_descendant_that_left_the_session():
    owner = co.Owner()
    run = lambda: True  # noqa: E731 - a run already cancelled
    helper = start = None
    try:
        with patch.object(sp, "_owner", owner):
            leader = ('import subprocess, sys, time; '
                      'p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"], '
                      'start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); '
                      'print(p.pid, flush=True); time.sleep(20)')
            proc = owner.popen_python([sys.executable, "-c", leader], run=run, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL)
            helper = int(proc.stdout.readline())
            start = co.process_start_time(helper)
            tag = f"{co.LEADER_TOKEN_ENV}_{proc.act_leader_token}=1".encode()
            assert until(lambda: tag in cg._environment(helper), 2)
            assert os.getsid(helper) == helper, "it left the worker's session"
            problem = sp.containment_problem(run)
            assert not live(helper, start), "the owner's retirement ended the tagged descendant"
            assert problem is None
            proc.stdout.close()
    finally:
        if helper is not None and live(helper, start):
            os.kill(helper, signal.SIGKILL)
        owner.shutdown()


# --------------------------------------------------------------------------- 2

@pytest.mark.parametrize("argv0", ["py", "", "a-longer-first-argument-name"])
def test_the_start_up_record_is_parsed_exactly_with_any_first_argument(argv0):
    python = os.path.realpath(sys.executable)  # not an Apple platform binary: its environment is in the record
    with subprocess.Popen([argv0, "-c", "import time; time.sleep(5)", "", "ARG=1"], executable=python,
                          env={"K": "1", "S": "2"}) as child:
        try:
            assert until(lambda: cg._environment(child.pid), 3)
            entries = cg._environment(child.pid)
            # The environment first; the kernel's own "apple" strings (pfz=, executable_path=, ...) may follow.
            assert entries[:2] == [b"K=1", b"S=2"], entries
            assert b"ARG=1" not in entries, "an argument is never an environment entry"
        finally:
            child.kill()


# --------------------------------------------------------------------------- 3

def test_the_orderly_end_stays_inside_its_bound_when_removing_the_permit_folder_stalls():
    owner = co.Owner()
    owner.ensure_guardian()
    with patch.object(sp, "_owner", owner):
        child = owner.popen_external(["/bin/sleep", "15"])
        permits = owner._permits
        real = co.shutil.rmtree
        release = threading.Event()

        def stalled(path, *args, **kwargs):
            if path == permits:
                release.wait(8)
            return real(path, *args, **kwargs)

        began = time.monotonic()
        try:
            with patch.object(co.shutil, "rmtree", stalled):
                sp.begin_closing()
                sp.shutdown_containment()
                took = time.monotonic() - began
        finally:
            release.set()
            sp._closing_deadline = None
    assert took <= sp.ORDERLY_END_S, f"{took:.3f}s"
    assert child.returncode is not None


# --------------------------------------------------------------------------- 4

def test_a_cancelled_run_begins_the_local_engine_retirement_itself():
    from shared.job_control import RunResult
    from tts import epub2tts_gui as gui
    from tts import local_engine_host as hosts

    owner = co.Owner()
    host = hosts.WorkerHost("kokoro", sample_rate=24000,
                            argv=[sys.executable, "-I", "-B", str(HERE / "local_engine_stub.py"), "kokoro"], owner=owner)
    terminal: list = []
    with patch.object(sp, "_owner", owner), patch.object(hosts, "_HOST", host), \
            patch.object(hosts, "_CANCEL_RETIREMENT", None), patch.object(RunResult, "settle", return_value=object()):
        try:
            host.ensure_started()
            worker = host._proc
            ctl = JobController("local", cancel_clock=time.monotonic)
            ctl.start()
            ctx = gui._RunContext.__new__(gui._RunContext)
            ctx.cancel_check, ctx.controller, ctx.cancelled = ctl.cancel_check, ctl, True
            ctx.unstopped, ctx.completed, ctx.failures = [], [], []
            ctx.snapshot = SimpleNamespace(snapshot_id="local", tool_options={"backend": "kokoro"})
            ctx.log_q = queue.Queue()
            ctx.stopped, ctx.not_started = 0, 1
            ctx.publisher = SimpleNamespace(cancelled=lambda final: terminal.append(("CANCELLED", worker.returncode)))
            ctx.settle_fatal = lambda exc: terminal.append(("FAILED", str(exc)))
            ctl.request_cancel()  # the panel is descheduled here: its own cancel_requested() has not run yet
            ctx.settle()
            assert terminal, "settled"
            state, detail = terminal[0]
            assert state == "FAILED" or detail is not None, f"CANCELLED with the worker still running: {terminal}"
            assert not host.alive()
        finally:
            host.close("test over")
            owner.shutdown()


def test_a_retirement_published_before_it_started_is_waited_for_never_an_error():
    from tts import local_engine_host as hosts

    with patch.object(hosts, "_CANCEL_RETIREMENT", threading.Thread(target=lambda: None)):
        assert hosts.cancel_retirement_pending(0.05) is True


# --------------------------------------------------------------------------- 5

@pytest.fixture()
def owner():
    made = co.Owner()
    yield made
    made.shutdown()


def test_a_missing_working_folder_raises_what_popen_raises(owner, tmp_path):
    missing = tmp_path / "none"
    with pytest.raises(FileNotFoundError) as direct:
        subprocess.Popen(["/bin/echo", "x"], cwd=missing)
    with pytest.raises(FileNotFoundError) as gated:
        owner.popen_external(["/bin/echo", "x"], cwd=missing)
    assert gated.value.filename == direct.value.filename
    assert owner.outstanding() == []


def test_path_is_read_as_popen_reads_it_including_a_bytes_key(owner, tmp_path):
    folder = tmp_path / "bin"
    folder.mkdir()
    program = folder / "qa-program"
    program.write_text("#!/bin/sh\necho found\n")
    program.chmod(0o755)
    env = {b"PATH": os.fsencode(folder)}
    direct = subprocess.run(["qa-program"], env=env, capture_output=True, timeout=5)
    proc = owner.popen_external(["qa-program"], env=env, stdout=subprocess.PIPE)
    out, _ = proc.communicate(timeout=5)
    assert (out, proc.returncode) == (direct.stdout, direct.returncode) == (b"found\n", 0)


def test_a_script_sees_the_path_it_was_started_by(owner, tmp_path):
    real = tmp_path / "real"
    real.write_text('#!/bin/sh\nprintf "%s\\n" "$0" "$@"\n')
    real.chmod(0o755)
    link = tmp_path / "ffmpeg"
    link.symlink_to(real)
    direct = subprocess.run([str(link), "spaced arg"], capture_output=True, timeout=5, cwd=tmp_path)
    proc = owner.popen_external([str(link), "spaced arg"], stdout=subprocess.PIPE, cwd=tmp_path)
    out, _ = proc.communicate(timeout=5)
    assert out == direct.stdout == f"{link}\nspaced arg\n".encode()


# --------------------------------------------------------------------------- 6

def _stalled_spawn(owner, pid_file: Path):
    """A Python child that stops itself between fork and exec (in ``preexec_fn``), recording its pid."""
    def stall():
        pid_file.write_text(str(os.getpid()))
        os.kill(os.getpid(), signal.SIGSTOP)

    def start():
        with contextlib.suppress(Exception):
            owner.popen_python([sys.executable, "-c", "import time; time.sleep(15)"], run="stalled", preexec_fn=stall)

    thread = threading.Thread(target=start, daemon=True)
    thread.start()
    assert until(lambda: pid_file.exists() and pid_file.read_text(), 5)
    pid = int(pid_file.read_text())
    return thread, pid, co.process_start_time(pid)


def test_a_child_stalled_between_fork_and_exec_is_ended_by_the_orderly_end(tmp_path):
    owner = co.Owner()
    owner.ensure_guardian()
    thread, pid, start = _stalled_spawn(owner, tmp_path / "pid")
    try:
        assert until(lambda: any(e.kind == co.CLASS_A and e.announced for e in owner._entries), 2), "announced early"
        owner.shutdown()
        assert until(lambda: not live(pid, start), 3), "the guardian ended it on the orderly end's word"
    finally:
        if live(pid, start):
            os.kill(pid, signal.SIGKILL)
        thread.join(5)
        owner.shutdown()


def test_a_child_stalled_between_fork_and_exec_ends_with_its_owner(tmp_path):
    pid_file = tmp_path / "pid"
    app = f"""
import os, signal, sys, threading, time
from pathlib import Path
from shared import child_ownership as co
owner = co.Owner()
owner.ensure_guardian()
def stall():
    Path({str(pid_file)!r}).write_text(str(os.getpid()))
    os.kill(os.getpid(), signal.SIGSTOP)
threading.Thread(target=lambda: owner.popen_python([sys.executable, '-c', 'import time; time.sleep(15)'],
                 preexec_fn=stall), daemon=True).start()
time.sleep(30)
"""
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT / "scripts"), os.environ.get("PYTHONPATH", "")]))
    with subprocess.Popen([sys.executable, "-B", "-c", app], env=env) as owner_proc:
        pid = start = None
        try:
            assert until(lambda: pid_file.exists() and pid_file.read_text(), 10)
            pid = int(pid_file.read_text())
            start = co.process_start_time(pid)
            time.sleep(0.3)  # announced while Popen still waits for the exec
            owner_proc.kill()
            owner_proc.wait(5)
            assert until(lambda: not live(pid, start), 5), "the guardian ended the stalled child"
        finally:
            if pid is not None and live(pid, start):
                os.kill(pid, signal.SIGKILL)
            if owner_proc.poll() is None:
                owner_proc.kill()
