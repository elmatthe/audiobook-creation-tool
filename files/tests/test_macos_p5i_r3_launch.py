"""v0.8.x P5-I-R3: the permit-gated launch of contained third-party programs, and the guardian's second trigger.

Real processes, deterministic fault injection (barriers and recorded events, never a sleep as an assertion), judged by
the process table and by marker files the program writes as its first action:

* a program begins executing only inside its run's counted start, through a one-time permit revoked before that
  counted start ends -- with the gate stopped, its acknowledgement lost and the kill refused, the gate resumed after
  the latch gets ``ENOENT`` and the program never runs (the one-way GO the P5-I-R1 review broke is the control);
* revocation the file system refuses holds the counted start only until the gate is seen ended, bounded;
* a ``Popen`` that raises after creating its process, or stalls, never loses the process and never holds its caller;
* the owner's death is contained even when its lifeline's write end survives in a stopped child, when a class-A
  leader was stopped before its lifeline ran, and when it dies with a permit outstanding.
macOS only.
"""

from __future__ import annotations

import contextlib
import os
import random
import signal
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from shared import child_ownership
from shared.cancellation import ConversionCancelled
from shared.job_control import JobController

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="POSIX containment is the Mac's")

SCRIPTS = Path(child_ownership.__file__).resolve().parents[1]


def _wait_for(predicate, seconds=10.0, step=0.01) -> bool:
    stop = time.monotonic() + seconds
    while time.monotonic() < stop:
        if predicate():
            return True
        time.sleep(step)
    return bool(predicate())


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    info = child_ownership._darwin_kinfo(pid)
    return info is not None and info[child_ownership._P_STAT_OFFSET] != child_ownership._SZOMB


def _state(pid: int) -> str:
    """``T`` for a stopped process, ``Z`` a zombie, ``R`` otherwise, read from the kernel (``sysctl``; no ``ps``, which
    a sandbox may refuse)."""
    info = child_ownership._darwin_kinfo(pid)
    if info is None:
        return ""
    return {4: "T", 5: "Z"}.get(info[child_ownership._P_STAT_OFFSET], "R")


def _marker_program(folder: Path, marker: Path, *, then: str = "exit 0") -> Path:
    """A stand-in third-party program whose first action records that it ran."""
    path = folder / "ffmpeg"
    path.write_text(f"#!/bin/sh\necho ran >> {marker}\n{then}\n", encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture()
def owner():
    made = child_ownership.Owner(lifeline=False)
    yield made
    made.shutdown()


@pytest.fixture()
def program(tmp_path):
    folder = tmp_path / "bin"
    folder.mkdir()
    marker = tmp_path / "ran"
    return _marker_program(folder, marker), marker


def _ordered(controller):
    return dict(ordering=lambda: controller.starting("Cancelled."), pending=lambda: controller.cancel_pending,
                owner_run=controller.cancel_check, cancel_error=lambda: ConversionCancelled("Cancelled."),
                checkpoint=None)


def _stop_gate_before_grant(owner, monkeypatch, box):
    """Fault: the gate is SIGSTOPped after it identified itself and before it is told to go (it will read the go byte
    whenever it is resumed)."""
    real = owner._grant

    def grant(launch):
        os.kill(launch.entry.pid, signal.SIGSTOP)
        assert _wait_for(lambda: _state(launch.entry.pid).startswith("T"), 5)
        box["gate"] = launch.entry.pid
        inner = launch.ordering
        if inner is None:
            box["entered"].set()
        else:
            @contextlib.contextmanager
            def ordering():  # "entered" once inside the run's counted start (the permit is made before it since
                with inner():  # remediation 3, so a Cancel pressed earlier would simply refuse the start)
                    box["entered"].set()
                    yield

            launch.ordering = ordering
        return real(launch)

    monkeypatch.setattr(owner, "_grant", grant)


# =========================================================================== the C1 revocation

def test_a_pending_cancel_revokes_a_stopped_gate_with_its_ack_lost_and_its_kill_refused(owner, program, monkeypatch):
    """The P5-I-R1 review's counterexample, against the permit: the gate is stopped, no acknowledgement can come, and
    the owner's SIGKILL is refused. The counted start revokes the permit and ends; Cancel latches inside C1; the gate,
    resumed after the latch, consumes its go byte, finds no program and exits 126. The program never runs."""
    ffmpeg, marker = program
    controller = JobController("r3-revoke")
    controller.start()
    box = {"entered": threading.Event()}
    _stop_gate_before_grant(owner, monkeypatch, box)
    monkeypatch.setattr(owner, "_deliver", lambda entry, sig: False)  # every signal the owner sends is refused
    out = {}

    def start():
        try:
            out["proc"] = owner.popen_external([str(ffmpeg)], **_ordered(controller))
        except BaseException as exc:  # noqa: BLE001 - read below
            out["error"] = exc

    worker = threading.Thread(target=start, name="worker", daemon=True)
    worker.start()
    assert box["entered"].wait(10)
    began = time.monotonic()
    controller.request_cancel()
    latched_in = time.monotonic() - began
    worker.join(10)
    assert controller.cancel_check() and latched_in < 0.5, f"C1: {latched_in:.3f} s"
    assert isinstance(out.get("error"), ConversionCancelled), out
    gate = box["gate"]
    os.kill(gate, signal.SIGCONT)  # the adversary resumes the gate after the latch
    monkeypatch.undo()
    assert _wait_for(lambda: not _alive(gate), 5), "the gate ended by itself"
    assert not marker.exists(), "the program never ran"
    entry = next((e for e in owner._entries if e.pid == gate), None)
    assert entry is None or entry.exec_unknown is False or entry.state in (child_ownership.RETIRING,
                                                                           child_ownership.UNCONFIRMED)


def test_control_a_one_way_go_without_revocation_runs_the_program_after_the_latch(owner, program, monkeypatch):
    """Negative control (the rejected P5-I-R1 design): the same fault with the permit never removed -- a one-way go.
    The program runs after the latch, so the test above can fail."""
    ffmpeg, marker = program
    controller = JobController("r3-control")
    controller.start()
    box = {"entered": threading.Event()}
    _stop_gate_before_grant(owner, monkeypatch, box)
    monkeypatch.setattr(owner, "_deliver", lambda entry, sig: False)
    monkeypatch.setattr(owner, "_revoke", lambda launch: True)  # "revoked" without removing anything

    def close_only(launch):  # nor is the unread go byte taken back (P5-I-R3 remediation 1): the end is only closed
        if launch.go_w is not None:
            os.close(launch.go_w)
            launch.go_w = None
        return False

    monkeypatch.setattr(owner, "_take_back_go", close_only)
    real_unlink = os.unlink

    def keep_permits(path, *args, **kwargs):  # nor is the permit tidied away when the launch ends (remediation 3)
        if "ACT-permits" in os.fspath(path):
            return None
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", keep_permits)
    worker = threading.Thread(target=lambda: _quiet(lambda: owner.popen_external([str(ffmpeg)], **_ordered(controller))),
                              daemon=True)
    worker.start()
    assert box["entered"].wait(10)
    controller.request_cancel()
    worker.join(10)
    assert controller.cancel_check()
    os.kill(box["gate"], signal.SIGCONT)
    assert _wait_for(marker.exists, 5), "with a one-way go the program does run after the latch"
    monkeypatch.undo()


def _quiet(fn):
    with contextlib.suppress(BaseException):
        return fn()


def test_revocation_refused_by_the_file_system_holds_only_until_the_gate_is_seen_ended(owner, program, monkeypatch):
    """``unlink`` and ``rename`` both refused (EPERM): the counted start kills the gate and counts the revocation only
    once the gate is seen ended (a gate that has ended can execute nothing). Cancel still latches inside C1 and the
    program never runs."""
    ffmpeg, marker = program
    controller = JobController("r3-refused")
    controller.start()
    box = {"entered": threading.Event()}
    _stop_gate_before_grant(owner, monkeypatch, box)
    real_unlink, real_rename = os.unlink, os.rename

    def unlink(path, *a, **k):
        if "ACT-permits" in str(path):
            raise PermissionError(1, "injected", str(path))
        return real_unlink(path, *a, **k)

    def rename(src, dst, *a, **k):
        if "ACT-permits" in str(src):
            raise PermissionError(1, "injected", str(src))
        return real_rename(src, dst, *a, **k)

    monkeypatch.setattr(child_ownership.os, "unlink", unlink)
    monkeypatch.setattr(child_ownership.os, "rename", rename)
    out = {}
    worker = threading.Thread(target=lambda: out.setdefault("r", _quiet(
        lambda: owner.popen_external([str(ffmpeg)], **_ordered(controller)))), daemon=True)
    worker.start()
    assert box["entered"].wait(10)
    began = time.monotonic()
    controller.request_cancel()
    latched_in = time.monotonic() - began
    worker.join(10)
    monkeypatch.undo()
    assert latched_in < 0.5, f"C1: {latched_in:.3f} s"
    assert _wait_for(lambda: not _alive(box["gate"]), 3)
    assert not marker.exists()


def test_revocation_and_kill_both_refused_is_still_definitive_through_the_unread_go_byte(owner, program, monkeypatch):
    """The OS-refusal case: the permit can be neither removed nor renamed nor made unsearchable, AND the gate cannot be
    killed. The gate waits for its go in ``poll`` (it has not read the byte), so the owner takes the ``G`` back out of
    the pipe: Cancel latches inside C1, and the gate, resumed after the latch, reads end-of-file and exits 125 without
    executing anything (P5-I-R3 remediation 1; before it, this case was only reported). The case where even that is
    impossible -- the gate already read its G -- is test_macos_p5i_r3_remediation's control: reported, never clean."""
    ffmpeg, marker = program
    controller = JobController("r3-double-refusal")
    controller.start()
    box = {"entered": threading.Event()}
    _stop_gate_before_grant(owner, monkeypatch, box)
    refuse = lambda *a, **k: (_ for _ in ()).throw(PermissionError(1, "x"))  # noqa: E731
    monkeypatch.setattr(child_ownership.os, "unlink", refuse)
    monkeypatch.setattr(child_ownership.os, "rename", refuse)
    monkeypatch.setattr(child_ownership.os, "chmod", refuse)
    monkeypatch.setattr(owner, "_deliver", lambda entry, sig: False)
    worker = threading.Thread(target=lambda: _quiet(lambda: owner.popen_external([str(ffmpeg)], **_ordered(controller))),
                              daemon=True)
    worker.start()
    assert box["entered"].wait(10)
    began = time.monotonic()
    controller.request_cancel()
    latched_in = time.monotonic() - began
    worker.join(10)
    monkeypatch.undo()
    assert latched_in < 0.5, f"C1: the latch took {latched_in:.3f} s"
    entry = next(e for e in owner._entries if e.pid == box["gate"])
    assert not entry.exec_unknown and owner.faults(controller.cancel_check) == []
    os.kill(box["gate"], signal.SIGCONT)
    assert _wait_for(lambda: entry.proc.poll() is not None, 5)
    assert entry.proc.returncode == 125, "no go: it read end-of-file"
    time.sleep(0.2)
    assert not marker.exists()


def test_cancel_racing_the_execution_never_lets_the_program_begin_after_the_latch(owner, tmp_path, monkeypatch):
    """Cancel pressed at random moments around the go: every start either returned a running program whose execution
    the kernel reported (``NOTE_EXEC``) BEFORE the latch completed, or was refused/revoked and its program never runs,
    even after waiting."""
    results = {"ran": 0, "revoked": 0}
    seen_exec: list = []
    real_outcome = owner._exec_outcome

    def outcome(launch, wait_s, *, cut):
        answer = real_outcome(launch, wait_s, cut=cut)
        if answer == "exec":
            seen_exec.append(time.monotonic())
        return answer

    monkeypatch.setattr(owner, "_exec_outcome", outcome)
    for attempt in range(25):
        marker = tmp_path / f"ran-{attempt}"
        folder = tmp_path / f"bin-{attempt}"
        folder.mkdir()
        ffmpeg = _marker_program(folder, marker)
        controller = JobController(f"r3-race-{attempt}")
        controller.start()
        out = {}
        worker = threading.Thread(target=lambda: out.update(r=_launch_or_error(owner, ffmpeg, controller)),
                                  daemon=True)
        seen_exec.clear()
        worker.start()
        time.sleep(random.uniform(0.005, 0.03))
        controller.request_cancel()
        latched_at = time.monotonic()
        worker.join(10)
        result = out["r"]
        if isinstance(result, subprocess.Popen):
            assert seen_exec and seen_exec[0] < latched_at, f"attempt {attempt}: executed after the latch"
            result.wait(5)
            owner.forget(result)
            results["ran"] += 1
        else:
            assert isinstance(result, ConversionCancelled), result
            time.sleep(0.05)
            assert not marker.exists(), f"attempt {attempt}: a refused start ran its program"
            results["revoked"] += 1
    assert results["ran"] + results["revoked"] == 25


def _launch_or_error(owner, ffmpeg, controller):
    try:
        return owner.popen_external([str(ffmpeg)], **_ordered(controller))
    except BaseException as exc:  # noqa: BLE001 - the caller judges it
        return exc


# =========================================================================== creation

def test_a_popen_that_raises_after_creating_its_process_never_loses_it(owner, program, monkeypatch):
    """CPython's parent read of the exec error pipe fails (``EIO``) after ``fork``: ``Popen`` raises with the process
    created. The pre-attached handle keeps it: it is killed and reaped through its own ``Popen``, nothing runs."""
    ffmpeg, marker = program
    real = subprocess.Popen._execute_child
    made = []

    def execute_child(self, *args, **kwargs):
        real(self, *args, **kwargs)
        if any(str(child_ownership.LAUNCH) == str(a) for a in args[0]):
            made.append(self.pid)
            raise OSError(5, "injected EIO after fork")

    monkeypatch.setattr(subprocess.Popen, "_execute_child", execute_child)
    with pytest.raises(child_ownership.ContainmentUnavailable, match="after its process was created"):
        owner.popen_external([str(ffmpeg)])
    monkeypatch.undo()
    assert made and _wait_for(lambda: not _alive(made[0]), 3), "killed and reaped through its Popen"
    assert not marker.exists()
    assert _wait_for(lambda: owner.outstanding() == [] or all(
        e.kind == child_ownership.GUARDIAN_KIND for e in owner.outstanding()), 3)


def test_a_stalled_popen_never_holds_its_caller_and_its_process_is_retired_when_it_appears(owner, program, monkeypatch):
    """``Popen`` stalls after creating the gate. The caller's Cancel abandons the start at once (C2 is not held by an
    uncancellable call); settlement accounts for the start in flight; when ``Popen`` returns, the gate is never allowed
    to run and is retired."""
    ffmpeg, marker = program
    controller = JobController("r3-stall")
    controller.start()
    held, release = threading.Event(), threading.Event()
    real = subprocess.Popen._execute_child

    def execute_child(self, *args, **kwargs):
        real(self, *args, **kwargs)
        if any(str(child_ownership.LAUNCH) == str(a) for a in args[0]):
            held.set()
            assert release.wait(20)

    monkeypatch.setattr(subprocess.Popen, "_execute_child", execute_child)
    kwargs = _ordered(controller)
    kwargs["checkpoint"] = lambda: (_ for _ in ()).throw(ConversionCancelled("Cancelled.")) if controller.cancel_check() \
        else None
    out = {}
    worker = threading.Thread(target=lambda: out.update(r=_launch_kw(owner, ffmpeg, kwargs)), daemon=True)
    worker.start()
    assert held.wait(10)
    began = time.monotonic()
    controller.request_cancel()
    worker.join(5)
    left_in = time.monotonic() - began
    assert not worker.is_alive() and left_in < 0.5, f"the caller left after {left_in:.3f} s"
    assert isinstance(out["r"], ConversionCancelled)
    pending = owner.settle_run(controller.cancel_check, 0.2)
    assert pending, "the start still in progress is accounted for, never a clean settlement"
    release.set()
    monkeypatch.undo()
    assert _wait_for(lambda: owner.outstanding(controller.cancel_check) == [], 5), owner.outstanding()
    assert not marker.exists()



def test_a_caller_leaving_a_stalled_start_cannot_hand_the_program_a_reused_descriptor(owner, program, tmp_path,
                                                                                    monkeypatch):
    """Descriptor ownership: the caller passes its own descriptor as stdout, abandons a stalled start (its Cancel),
    closes that file, and the number is reused by an unrelated file before the launch thread's ``Popen`` runs. The
    launch hands the gate the caller's ORIGINAL file (its own duplicate), never the unrelated one."""
    ffmpeg, marker = program
    controller = JobController("r3-fds")
    controller.start()
    held, release, seen = threading.Event(), threading.Event(), {}
    real = subprocess.Popen.__init__

    def init(self, args, *rest, **kw):
        if any(str(child_ownership.LAUNCH) == str(a) for a in args):
            held.set()
            assert release.wait(20)
            with contextlib.suppress(OSError):
                seen["inode"] = os.fstat(kw["stdout"]).st_ino
        return real(self, args, *rest, **kw)

    monkeypatch.setattr(subprocess.Popen, "__init__", init)
    mine = open(tmp_path / "mine.log", "wb")
    fd, mine_inode = mine.fileno(), os.fstat(mine.fileno()).st_ino
    kwargs = _ordered(controller)
    kwargs["checkpoint"] = lambda: (_ for _ in ()).throw(ConversionCancelled("Cancelled.")) if controller.cancel_check() \
        else None
    kwargs["stdout"] = fd
    out = {}
    worker = threading.Thread(target=lambda: out.update(r=_launch_kw(owner, ffmpeg, kwargs)), daemon=True)
    worker.start()
    assert held.wait(10)
    controller.request_cancel()
    worker.join(5)
    assert not worker.is_alive() and isinstance(out["r"], ConversionCancelled)
    mine.close()  # the caller has left: it closes its file, and the number is reused
    other = open(tmp_path / "other.log", "wb")
    if other.fileno() != fd:  # usually the very number is handed out again; make sure of it
        os.dup2(other.fileno(), fd)
    try:
        release.set()
        assert _wait_for(lambda: "inode" in seen, 10)
        assert seen["inode"] == mine_inode != os.fstat(fd).st_ino, "the gate got an unrelated file as its stdout"
        monkeypatch.undo()
        assert _wait_for(lambda: owner.outstanding(controller.cancel_check) == [], 5), owner.outstanding()
        assert not marker.exists()
    finally:
        if other.fileno() != fd:
            os.close(fd)
        other.close()

def _launch_kw(owner, ffmpeg, kwargs):
    try:
        return owner.popen_external([str(ffmpeg)], **kwargs)
    except BaseException as exc:  # noqa: BLE001
        return exc


# =========================================================================== identity

def test_kill_now_after_a_concurrent_reap_sends_no_signal(owner, program, monkeypatch):
    """P5-I HIGH 6: the proof and the signal are under the child's waitpid lock; once reaped, nothing is sent."""
    ffmpeg, _marker = program
    proc = owner.popen_external([str(ffmpeg)])
    proc.wait(5)
    sent = []
    real_kill, real_killpg = os.kill, os.killpg
    monkeypatch.setattr(child_ownership.os, "kill", lambda pid, sig: sent.append(pid) or real_kill(pid, sig))
    monkeypatch.setattr(child_ownership.os, "killpg", lambda pid, sig: sent.append(-pid) or real_killpg(pid, sig))
    assert owner.kill_now(proc) is False and sent == []


# =========================================================================== parity

def test_the_program_sees_what_popen_would_have_given_it(owner, tmp_path):
    """Environment, working directory, process group (the guardian's), stdin/stdout pipes, argv[0], exit status and
    default SIGPIPE/SIGXFSZ dispositions are what a direct Popen gives; ``args`` is what the caller asked for."""
    probe = tmp_path / "ffprobe"
    probe.write_text(textwrap.dedent(f"""\
        #!{sys.executable} -I
        import os, signal, sys
        data = sys.stdin.read()
        print(os.environ.get("R3_PARITY"), os.getcwd(), os.getpgrp(), sys.argv[0].rsplit("/", 1)[-1], data,
              signal.getsignal(signal.SIGPIPE) == signal.SIG_DFL, signal.getsignal(signal.SIGXFSZ) == signal.SIG_DFL)
        sys.exit(7)
        """), encoding="utf-8")
    probe.chmod(0o755)
    env = dict(os.environ, R3_PARITY="yes")
    proc = owner.popen_external([str(probe)], env=env, cwd=str(tmp_path), stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, text=True)
    out, _ = proc.communicate("hello", timeout=10)
    owner.forget(proc)
    value, cwd, group, name, data, _pipe, _xfsz = out.split()
    assert (value, Path(cwd).resolve(), int(group), name, data) == ("yes", tmp_path.resolve(), owner.guardian_pid(),
                                                                    "ffprobe", "hello")
    assert proc.returncode == 7 and proc.args == [str(probe)]


def test_the_program_inherits_default_sigpipe_and_sigxfsz_as_popen_gives_them(owner, tmp_path):
    """The gate's own interpreter ignores SIGPIPE and SIGXFSZ; it restores both before it executes the program, as
    ``Popen(restore_signals=True)`` does for a direct start (perl reports an inherited ignore as IGNORE)."""
    probe = tmp_path / "ffmpeg"
    probe.write_text('#!/usr/bin/perl\nprint(($SIG{PIPE} // "DEFAULT"), " ", ($SIG{XFSZ} // "DEFAULT"), "\\n");\n',
                     encoding="utf-8")
    probe.chmod(0o755)
    direct = subprocess.run([str(probe)], capture_output=True, text=True, timeout=10).stdout.split()
    proc = owner.popen_external([str(probe)], stdout=subprocess.PIPE, text=True)
    gated = proc.communicate(timeout=10)[0].split()
    owner.forget(proc)
    assert gated == direct and "IGNORE" not in gated, (gated, direct)


def test_a_missing_program_creates_nothing(owner, monkeypatch):
    made = []
    real = subprocess.Popen._execute_child
    monkeypatch.setattr(subprocess.Popen, "_execute_child",
                        lambda self, *a, **k: made.append(a) or real(self, *a, **k))
    with pytest.raises(FileNotFoundError):
        owner.popen_external(["/nonexistent/ffmpeg", "-version"])
    assert made == []


# =========================================================================== the owner's death

OWNER_SCRIPT = r'''
import os, signal, subprocess, sys, time
sys.path.insert(0, sys.argv[1])
from shared import child_ownership
mode, work = sys.argv[2], sys.argv[3]
owner = child_ownership.Owner()
if mode == "class-a-stopped":
    proc = owner.popen_python([sys.executable, "-c", "import time; time.sleep(60)"])
    os.kill(proc.pid, signal.SIGSTOP)  # stopped: its lifeline thread can never run
    print("CHILD", proc.pid, flush=True)
elif mode == "lifeline-held":
    proc = owner.popen_external([sys.argv[4]], stdin=subprocess.DEVNULL)
    pid = os.fork()  # a child of the owner caught between fork and exec: it holds the lifeline's write end
    if pid == 0:
        os.kill(os.getpid(), signal.SIGSTOP)
        os._exit(0)
    print("CHILD", proc.pid, flush=True)
    print("HOLDER", pid, flush=True)
elif mode == "mid-grant":
    real = owner._grant
    def grant(launch):
        os.kill(launch.entry.pid, signal.SIGSTOP)
        os.symlink(launch.program, launch.permit)  # permit outstanding, go sent, then the owner dies
        os.write(launch.go_w, b"G")
        print("CHILD", launch.entry.pid, flush=True)
        time.sleep(60)
    owner._grant = grant
    owner.popen_external([sys.argv[4]], stdin=subprocess.DEVNULL)
time.sleep(60)
'''


def _owner_dies(tmp_path, mode, *extra):
    script = tmp_path / "owner.py"
    script.write_text(OWNER_SCRIPT, encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "-I", str(script), str(SCRIPTS), mode, str(tmp_path), *extra],
                            stdout=subprocess.PIPE, text=True, start_new_session=True)
    pids = {}
    while "CHILD" not in pids or (mode == "lifeline-held" and "HOLDER" not in pids):
        line = proc.stdout.readline()
        assert line, "the owner ended before it reported"
        key, value = line.split()
        pids[key] = int(value)
    os.kill(proc.pid, signal.SIGKILL)
    proc.wait(5)
    return pids


def test_owner_death_ends_a_class_a_leader_stopped_before_its_lifeline(tmp_path):
    """Sol P5-I-R2 blocker 4: a stopped class-A leader cannot run its lifeline thread. The guardian, told its pid and
    start time, SIGKILLs it (a stopped process dies of SIGKILL) within KX-1's 3 s."""
    pids = _owner_dies(tmp_path, "class-a-stopped")
    try:
        assert _wait_for(lambda: not _alive(pids["CHILD"]), 3), "the stopped class-A leader outlived its owner"
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pids["CHILD"], signal.SIGKILL)


def test_owner_death_is_seen_by_the_guardian_while_its_lifeline_is_held_open(tmp_path, program):
    """The fork-to-exec window: a stopped child of the owner still holds the lifeline's write end, so no end-of-file
    comes. The guardian's kqueue watch on its owner fires anyway and the contained program is ended within 3 s."""
    ffmpeg, _marker = program
    ffmpeg.write_text("#!/bin/sh\nexec sleep 60\n", encoding="utf-8")
    pids = _owner_dies(tmp_path, "lifeline-held", str(ffmpeg))
    try:
        assert _wait_for(lambda: not _alive(pids["CHILD"]), 3), "the contained program outlived its owner"
    finally:
        for pid in pids.values():
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)


def test_owner_death_with_a_permit_outstanding_never_runs_the_program(tmp_path, program):
    """The owner dies inside the counted start: the gate (stopped) was told to go and its permit exists. The guardian
    removes the permit folder and kills its group; the gate never runs the program."""
    ffmpeg, marker = program
    pids = _owner_dies(tmp_path, "mid-grant", str(ffmpeg))
    try:
        assert _wait_for(lambda: not _alive(pids["CHILD"]), 3), "the gate outlived its owner"
        with contextlib.suppress(ProcessLookupError):
            os.kill(pids["CHILD"], signal.SIGCONT)
        time.sleep(0.2)
        assert not marker.exists(), "the program ran after its owner's death"
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pids["CHILD"], signal.SIGKILL)
