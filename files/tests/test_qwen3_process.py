"""v0.6.7 CP6 — a worker and everything it starts can always be stopped (Windows Job Object).

These run real processes. The Windows venv ``python.exe`` is a launcher that starts the real interpreter as a child; the
cases below model that arrangement and the harder one Codex raised: the launcher exits while its child lives on holding
the output pipe.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from tts import qwen3_process as qp

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Job Objects are a Windows mechanism")


def pid_alive(pid: int) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
    return str(pid) in out


def wait_for(path: Path, timeout: float = 20.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.read_text().strip():
            return path.read_text().strip()
        time.sleep(0.1)
    raise AssertionError(f"{path} was never written")


def wait_dead(pid: int, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.2)
    return False


PARENT_THEN_CHILD = (
    "import subprocess, sys, time\n"
    "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
    "open(sys.argv[1], 'w').write(str(child.pid))\n"
    "{tail}")


@windows_only
def test_killing_the_tree_takes_a_living_parents_child_too(tmp_path):
    marker = tmp_path / "child.pid"
    proc = qp.spawn([sys.executable, "-c", PARENT_THEN_CHILD.format(tail="time.sleep(120)\n"), str(marker)])
    try:
        pid = int(wait_for(marker))
        assert pid_alive(pid) and proc.poll() is None
        qp.kill_tree(proc)
        assert proc.poll() is not None and wait_dead(pid)
    finally:
        qp.release(proc)


@windows_only
def test_killing_the_tree_still_reaches_a_child_whose_parent_already_exited(tmp_path):
    """The launcher can be gone while the real interpreter keeps running with the output pipe open."""
    marker = tmp_path / "child.pid"
    proc = qp.spawn([sys.executable, "-c", PARENT_THEN_CHILD.format(tail=""), str(marker)],
                    stdout=subprocess.PIPE, text=True)
    try:
        pid = int(wait_for(marker))
        proc.wait(timeout=20)  # the parent is gone...
        assert proc.poll() is not None and pid_alive(pid)  # ...and its child is not
        qp.kill_tree(proc)  # taskkill /T could not find this child; the job can
        assert wait_dead(pid)
    finally:
        qp.release(proc)


@windows_only
def test_the_pipe_reaches_eof_once_the_whole_tree_is_killed(tmp_path):
    """A reader blocked on the worker's stdout must be released by the kill, not wait for a grandchild."""
    marker = tmp_path / "child.pid"
    code = PARENT_THEN_CHILD.format(tail="").replace("subprocess.Popen([sys.executable,",
                                                     "subprocess.Popen([sys.executable,") + "\n"
    proc = qp.spawn([sys.executable, "-c", code, str(marker)], stdout=subprocess.PIPE, text=True)
    try:
        wait_for(marker)
        proc.wait(timeout=20)
        qp.kill_tree(proc)
        started = time.monotonic()
        assert proc.stdout.read() == ""  # EOF arrives: no process holds the pipe any more
        assert time.monotonic() - started < 10
    finally:
        qp.release(proc)


@windows_only
def test_releasing_the_job_kills_any_straggler(tmp_path):
    marker = tmp_path / "child.pid"
    proc = qp.spawn([sys.executable, "-c", PARENT_THEN_CHILD.format(tail="time.sleep(120)\n"), str(marker)])
    pid = int(wait_for(marker))
    qp.release(proc)  # KILL_ON_JOB_CLOSE: closing the last handle is enough
    assert wait_dead(pid) and wait_dead(proc.pid)
    assert getattr(proc, "act_job") is None
    qp.release(proc)  # idempotent


@windows_only
def test_a_spawned_process_runs_normally_and_is_not_left_suspended(tmp_path):
    proc = qp.spawn([sys.executable, "-c", "print('hello from the worker')"], stdout=subprocess.PIPE, text=True)
    try:
        out, _ = proc.communicate(timeout=30)
        assert out.strip() == "hello from the worker" and proc.returncode == 0
        assert proc.act_job is not None  # it really was placed in a job
    finally:
        qp.release(proc)


@windows_only
def test_if_the_job_cannot_be_created_the_process_still_runs_and_the_older_kill_route_works(tmp_path, monkeypatch):
    def refuse():
        raise OSError(5, "access denied")

    monkeypatch.setattr(qp, "ProcessJob", refuse)
    marker = tmp_path / "child.pid"
    proc = qp.spawn([sys.executable, "-c", PARENT_THEN_CHILD.format(tail="time.sleep(120)\n"), str(marker)])
    try:
        pid = int(wait_for(marker))
        assert proc.act_job is None  # no job: the process was started normally, not left suspended
        qp.kill_tree(proc)  # falls back to taskkill /T, which works while the parent is alive
        assert proc.poll() is not None and wait_dead(pid)
    finally:
        qp.release(proc)


@windows_only
def test_a_failure_to_assign_the_job_does_not_leave_the_process_suspended(tmp_path, monkeypatch):
    real = qp.ProcessJob

    class FailsToAssign(real):
        def assign(self, proc):
            raise OSError(5, "already in a job that forbids nesting")

    monkeypatch.setattr(qp, "ProcessJob", FailsToAssign)
    proc = qp.spawn([sys.executable, "-c", "print('ran')"], stdout=subprocess.PIPE, text=True)
    try:
        out, _ = proc.communicate(timeout=30)
        assert out.strip() == "ran" and proc.act_job is None
    finally:
        qp.release(proc)


@windows_only
def test_a_command_that_must_be_contained_is_not_run_when_the_job_cannot_be_created(tmp_path, monkeypatch):
    def refuse():
        raise OSError(5, "access denied")

    monkeypatch.setattr(qp, "ProcessJob", refuse)
    ran = tmp_path / "ran.txt"
    with pytest.raises(qp.ContainmentUnavailable, match="Job Object could not be created"):
        qp.spawn([sys.executable, "-c", f"open(r'{ran}', 'w').write('ran')"], require_job=True)
    time.sleep(1.0)
    assert not ran.exists(), "an uncontained worker must never get to run"


@windows_only
def test_a_command_that_must_be_contained_is_killed_unstarted_when_the_job_refuses_it(tmp_path, monkeypatch):
    """Codex finding: a refused assignment used to resume the process uncontained, so Cancel could not stop it."""
    real = qp.ProcessJob

    class RefusesToAssign(real):
        def assign(self, proc):
            self.proc = proc
            raise OSError(5, "the process is already in a job that forbids nesting")

    monkeypatch.setattr(qp, "ProcessJob", RefusesToAssign)
    ran = tmp_path / "ran.txt"
    code = f"open(r'{ran}', 'w').write('ran'); import time; time.sleep(60)"
    spawned = []
    original_popen = qp.subprocess_utils.popen

    def tracking_popen(cmd, **kwargs):
        proc = original_popen(cmd, **kwargs)
        spawned.append(proc)
        return proc

    monkeypatch.setattr(qp.subprocess_utils, "popen", tracking_popen)
    with pytest.raises(qp.ContainmentUnavailable, match="could not be placed under the app's control"):
        qp.spawn([sys.executable, "-c", code], require_job=True)
    proc = spawned[0]
    assert proc.poll() is not None, "the suspended process was terminated"
    time.sleep(1.0)
    assert not ran.exists(), "it never executed a single instruction"


@windows_only
def test_a_failed_launch_does_not_leak_the_job_handle(tmp_path, monkeypatch):
    """Codex finding: Popen raising (the executable vanished, execution blocked) used to leak the new job."""
    real = qp.ProcessJob
    created = []

    class Tracked(real):
        def __init__(self):
            super().__init__()
            self.closed = False
            created.append(self)

        def close(self):
            self.closed = True
            super().close()

    monkeypatch.setattr(qp, "ProcessJob", Tracked)
    for _ in range(3):
        with pytest.raises(FileNotFoundError):
            qp.spawn([str(tmp_path / "no-such-program.exe")], require_job=True)
    assert len(created) == 3 and all(job.closed for job in created)


@windows_only
def test_a_single_process_command_may_go_without_a_job_but_is_still_resumed(tmp_path, monkeypatch):
    class RefusesToAssign(qp.ProcessJob):
        def assign(self, proc):
            raise OSError(5, "nested")

    monkeypatch.setattr(qp, "ProcessJob", RefusesToAssign)
    proc = qp.spawn([sys.executable, "-c", "print('ffmpeg-like')"], stdout=subprocess.PIPE, text=True)
    try:
        out, _ = proc.communicate(timeout=30)
        assert out.strip() == "ffmpeg-like" and proc.act_job is None
    finally:
        qp.release(proc)
