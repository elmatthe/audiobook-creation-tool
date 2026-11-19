"""child_ownership.py -- POSIX ownership and parent-death containment of ACT's child processes (v0.8.x P1A).

Windows ends a setup's or the app's children through Job Objects (kill-on-close). macOS has no such object and no
``PR_SET_PDEATHSIG``, and ``atexit`` does not run when a process is SIGKILLed, crashes, is force-quit or loses its
Terminal window. This module is the macOS mechanism (plan section 11.2.2). A process that starts children is their
*owner* (P1A: the setup process, ``bootstrap.py``; P1B: the app window, ``launcher.py``) and holds one
:class:`Owner`.

**Class A -- ACT-authored Python children** (pip with its build backends, ``python -m venv``, setup probes and proofs).
Each leads its own process group (``start_new_session``) and starts through ``child_entry.py``, whose first statements
start a thread blocked on the read end of the owner's *lifeline* pipe. The write end exists only in the owner: it is
non-inheritable (PEP 446), never passed to a child, and the owner never forks without exec. When the owner is gone --
however it went -- the kernel closes the write end, the read returns end-of-file, and the thread ends the child's whole
group.

**Class B -- third-party executables** (``codesign`` in setup; FFmpeg and ffprobe in the app, P1B). They cannot run that thread,
so each joins the owner's *guardian* group at spawn (``process_group=``; the child joins before it executes). The
guardian (``child_guardian.py``) holds the lifeline's read end and ends its group when it reads end-of-file.

**If the guardian dies on its own** (killed by hand), the owner fails closed rather than claim containment it no longer
has: a thread waiting on the guardian ends every class-B child still running in that guardian's group (identity-checked,
SIGTERM then SIGKILL), marks each one ``lost_containment`` so its caller reports a failure, records the event, and the
next class-B spawn starts a new guardian first. No class-B child is ever started without a guardian that answered
``ready``. The residual: a class-B child whose guardian died *and* whose owner died (or was stopped) before that thread
ran is not contained; see Decisions (P1A).

**Termination is identity-checked.** Every registered child records its pid, process group and kernel start time
(``sysctl kern.proc.pid``). A signal goes only to a process whose start time still matches; a group is signalled only
while its leader is an unreaped child of this owner, so neither id can have been reused. Never by name, never a scan.

**A leader's normal exit proves nothing about its group** (v0.8.x P5-C). pip or a probe can exit while a helper it
started -- in its group -- runs on, and can hold its output open. So a class-A child is never reaped before its group
has been ended (:func:`end_led_group`), and its caller waits for the leader's exit, not for the end of its output
(:func:`follow_lines`, :func:`communicate_led`); a group that cannot be proved the leader's own, or not confirmed ended,
is reported as a failure, never as a success.

**Deliberately detached children** (class D: the GUI started by setup, the Finder ``open``, ``close_terminal.py``) do
not come here; ``files/tests`` pins that list.

Standard library only: bootstrap runs it on the app's base Python before the environment exists. Nothing here is used
on Windows; :func:`supported` is False there and the Windows spawn paths are unchanged.
"""

from __future__ import annotations

import os
import queue
import select
import signal
import struct
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

ENTRY = Path(__file__).resolve().with_name("child_entry.py")
GUARDIAN = Path(__file__).resolve().with_name("child_guardian.py")
LIFELINE_ENV = "ACT_LIFELINE_FD"

CLASS_A = "A"
CLASS_B = "B"

#: How long a new guardian has to say ``ready``.
GUARDIAN_READY_TIMEOUT_S = 10.0
#: SIGTERM -> SIGKILL grace for one child in an orderly end.
TERM_GRACE_S = 1.0
#: Bound on the whole orderly shutdown.
SHUTDOWN_BOUND_S = 5.0

#: Interpreter options that take a value as the next argument (``python -X dev -W error ...``).
_OPTIONS_WITH_VALUE = frozenset({"-X", "-W", "--check-hash-based-pycs"})


class ContainmentUnavailable(RuntimeError):
    """A contained spawn could not be made (no guardian could be started). Nothing was started."""


def supported(platform: Optional[str] = None) -> bool:
    """True where this module is the containment mechanism (POSIX). Windows keeps Job Objects."""
    return (sys.platform if platform is None else platform) != "win32" and os.name == "posix"


# --------------------------------------------------------------------------- #
#  Process identity
# --------------------------------------------------------------------------- #
_CTL_KERN, _KERN_PROC, _KERN_PROC_PID = 1, 14, 1


#: ``struct extern_proc`` (the first member of ``kinfo_proc``): ``p_starttime`` is the ``timeval`` at offset 0 and
#: ``p_stat`` the byte at offset 36 (after the 16-byte union, two pointers and ``p_flag``); SZOMB = 5.
_P_STAT_OFFSET = 36
_SZOMB = 5


def _darwin_kinfo(pid: int) -> Optional[bytes]:
    """``sysctl({CTL_KERN, KERN_PROC, KERN_PROC_PID, pid})``: the process's ``kinfo_proc``, or None if there is none."""
    try:
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        mib = (ctypes.c_int * 4)(_CTL_KERN, _KERN_PROC, _KERN_PROC_PID, int(pid))
        size = ctypes.c_size_t(0)
        if libc.sysctl(mib, 4, None, ctypes.byref(size), None, 0) != 0 or size.value <= _P_STAT_OFFSET:
            return None
        buffer = ctypes.create_string_buffer(size.value)
        if libc.sysctl(mib, 4, buffer, ctypes.byref(size), None, 0) != 0 or size.value <= _P_STAT_OFFSET:
            return None  # size 0: no such process
        return buffer.raw[: size.value]
    except (OSError, AttributeError, ValueError):
        return None


def process_start_time(pid: int) -> Optional[tuple[int, int]]:
    """The kernel's start time of ``pid`` as ``(seconds, microseconds)``, or None when there is no such process.

    macOS: ``kinfo_proc.kp_proc.p_starttime``. A zombie keeps its entry, so an unreaped child still answers. Linux
    (development only): field 22 of ``/proc/<pid>/stat``.
    """
    if pid <= 0:
        return None
    if sys.platform == "darwin":
        info = _darwin_kinfo(pid)
        if info is None:
            return None
        seconds, micros = struct.unpack_from("=qi", info, 0)
        return (int(seconds), int(micros))
    try:
        with open(f"/proc/{int(pid)}/stat", "rb") as handle:
            fields = handle.read().rsplit(b")", 1)[1].split()
        return (int(fields[19]), 0)
    except (OSError, IndexError, ValueError):
        return None


def signal_if_same(pid: int, start_time: Optional[tuple[int, int]], sig: int, *, group: bool = False) -> bool:
    """Send ``sig`` to ``pid`` (or to the group it leads) only if it is still the process recorded at spawn.

    Returns True when a signal was delivered. A process that is gone, or whose start time differs (the id now belongs
    to someone else), is left alone and counts as ended. Never raises.
    """
    if start_time is None or process_start_time(pid) != start_time:
        return False
    try:
        if group:
            os.killpg(pid, sig)
        else:
            os.kill(pid, sig)
        return True
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return False


def _has_exited(pid: int) -> bool:
    """True when this process's child ``pid`` has exited, WITHOUT reaping it: it is a zombie or gone. CPython has no
    ``os.waitid`` on macOS, so the kernel's process state is read instead (``p_stat == SZOMB``)."""
    if sys.platform == "darwin":
        info = _darwin_kinfo(pid)
        return info is None or info[_P_STAT_OFFSET] == _SZOMB
    waitid = getattr(os, "waitid", None)
    if waitid is None:
        return False
    try:
        return waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None
    except OSError:
        return True


def _wait_exited(pid: int, timeout: float) -> bool:
    """Wait up to ``timeout`` for this process's child ``pid`` to exit, without reaping it. True once it has."""
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        if _has_exited(pid):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.02)


# --------------------------------------------------------------------------- #
#  A group whose leader has exited (v0.8.x P5-A)
# --------------------------------------------------------------------------- #
#: :func:`end_led_group`'s answers.
GROUP_ENDED = "ended"  # the kernel says no member this account can signal is left (macOS)
#: SIGKILL sent; this platform cannot say whether the group is empty (Linux, development only).
GROUP_SIGNALLED = "signalled"
GROUP_REMAINING = "remaining"  # a member still answered when the bound ran out, or the signal was refused
GROUP_UNPROVED = "unproved"  # the group's id could not be proved to be the leader's own: nothing was signalled


def has_exited(proc: subprocess.Popen, start_time: Optional[tuple[int, int]] = None) -> bool:
    """True when the child *proc* has exited -- WITHOUT reaping it (v0.8.x P5-A).

    Exited means: reaped already (``returncode`` is set), a zombie or gone (:func:`_has_exited`), or -- when
    *start_time* is given -- no longer the process recorded at spawn. Because nothing is reaped, a child that exited
    stays a zombie, and the kernel keeps its id -- which is also the id of the group it leads -- reserved until its
    owner reaps it, so :func:`end_led_group` can still end what it left behind.
    """
    if proc.returncode is not None or _has_exited(proc.pid):
        return True
    return start_time is not None and process_start_time(proc.pid) != start_time


def wait_exited(proc: subprocess.Popen, timeout: float, start_time: Optional[tuple[int, int]] = None, *,
                interval: float = 0.05) -> bool:
    """Wait at most *timeout* seconds for :func:`has_exited`, never reaping. True once it has."""
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        if has_exited(proc, start_time):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(interval, remaining))


def end_led_group(proc: subprocess.Popen, start_time: Optional[tuple[int, int]], *,
                  bound_s: float = SHUTDOWN_BOUND_S) -> str:
    """SIGKILL every process in the group *proc* leads and confirm that none is left -- only while the group's id is
    proved to be *proc*'s own (v0.8.x P5-A: a setup worker that exited normally while a grandchild lived on).

    *proc* must have started its own session (``start_new_session``), as every class-A child and the setup worker do:
    a group's id is the id of the process that created it, and every member of that session's group descends from it.
    The proof, held for the whole check-and-signal, never relaxed:

    1. *proc*'s own waitpid lock is held. Every ``Popen.wait``/``poll`` reaps only under it (CPython's guard against
       signalling a recycled id, bpo-38630), so *proc* cannot be reaped through its ``Popen`` meanwhile. Waiting for
       the lock is bounded; an object without one is never signalled.
    2. ``proc.returncode`` is None: nobody has reaped it, so the kernel still reserves its id (a zombie keeps it), no
       other process can have that id, and no other group can carry it.
    3. Its kernel start time equals *start_time*, recorded at spawn: no reap outside ``Popen`` handed the id on.

    Then ``killpg(SIGKILL)`` is repeated until the kernel says no member it may signal is left -- on macOS ``EPERM``
    while the leader is still an unreaped zombie (zombies are not signalled), ``ESRCH`` once the group is gone -- or
    *bound_s* runs out. A member that belongs to another account would also make the kernel answer ``EPERM``; ACT runs
    no setuid program, so none can be in the group. The leader is not reaped here: its caller does that afterwards.

    Returns one of :data:`GROUP_ENDED`, :data:`GROUP_SIGNALLED`, :data:`GROUP_REMAINING`, :data:`GROUP_UNPROVED`. Never
    raises.
    """
    lock = getattr(proc, "_waitpid_lock", None)
    if start_time is None or lock is None:
        return GROUP_UNPROVED
    deadline = time.monotonic() + max(0.0, bound_s)
    if not lock.acquire(timeout=max(0.0, bound_s)):
        return GROUP_UNPROVED  # another thread may be reaping it right now
    try:
        if proc.returncode is not None or process_start_time(proc.pid) != start_time:
            return GROUP_UNPROVED
        while True:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                return GROUP_ENDED
            except PermissionError:
                return GROUP_ENDED if sys.platform == "darwin" else GROUP_REMAINING
            except OSError:
                return GROUP_REMAINING
            if sys.platform != "darwin":
                return GROUP_SIGNALLED  # a zombie leader is still a signalled member there: emptiness cannot be read
            if time.monotonic() >= deadline:
                return GROUP_REMAINING
            time.sleep(0.02)
    finally:
        lock.release()


# --------------------------------------------------------------------------- #
#  A class-A child that exits normally (v0.8.x P5-C)
# --------------------------------------------------------------------------- #
#: How long the output of a child whose group has been ended may stay silent before it is judged still held open by
#: something outside that group. Every writer in the group is gone by then, so only what is already in the pipe is left.
DRAIN_IDLE_S = 5.0
#: The most time handing on that output may take in all, however much of it is left.
DRAIN_LIMIT_S = 30.0
#: How often a followed child's exit (observed, never reaped) and its caller's stop request are looked at.
FOLLOW_POLL_S = 0.1


@dataclass
class Retired:
    """How a class-A child -- the leader of its own process group -- was retired (v0.8.x P5-C).

    A leader that exits normally is no proof that what it started has ended: a build backend or helper in its group can
    outlive it, and can hold its output open. So the leader is reaped only after its group has been ended the P5-A way
    (:func:`end_led_group`); this records how that went."""

    returncode: Optional[int]  # the leader's exit status; None when it could not be reaped within the bound
    group: str  # the :func:`end_led_group` answer for the group it led
    output_open: bool = False  # its output had not reached end-of-file once its group had ended (the drain bounds)
    stopped: bool = False  # its caller asked it to stop: its group was ended at once
    timed_out: bool = False  # still running at its caller's deadline: its group was ended then

    def problem(self) -> Optional[str]:
        """Why nothing can vouch that the child and everything it started have ended -- or None, when the kernel
        confirmed its group empty, its output ended and it was reaped. A caller never reports success while this says
        something."""
        if self.group == GROUP_UNPROVED:
            return ("its process group's id could not be proved to still be its own (it had already been reaped or "
                    "replaced), so nothing was signalled; something it started may still be running")
        if self.group == GROUP_REMAINING:
            return "a process in its group had not ended in time (or could not be told to); it may still be running"
        if self.group == GROUP_SIGNALLED:
            return "its process group was told to end, but this system cannot confirm that none of it is left"
        if self.group != GROUP_ENDED:
            return f"ending its process group gave no known answer ({self.group!r})"
        if self.output_open:
            return ("its output was still held open after its process group had ended, so a process outside that group "
                    "may still be running")
        if self.returncode is None:
            return "it did not exit in time to be reaped"
        return None


def _reap(proc: subprocess.Popen, bound_s: float) -> Optional[int]:
    """Reap *proc*, waiting at most *bound_s*: its exit status, or None when it has not exited. Never raises."""
    try:
        return proc.wait(timeout=max(0.0, bound_s))
    except subprocess.TimeoutExpired:
        return None
    except ChildProcessError:  # reaped outside its ``Popen``: the status is lost
        return proc.returncode


def retire_led_group(proc: subprocess.Popen, start_time: Optional[tuple[int, int]], *,
                     bound_s: float = SHUTDOWN_BOUND_S) -> tuple[str, Optional[int]]:
    """End the group *proc* leads -- proved, signalled, confirmed (:func:`end_led_group`) -- and only then reap *proc*.
    Returns ``(the group answer, the exit status or None)``. Bounded by twice *bound_s*; never raises.

    For a leader that has exited it ends what the leader left behind; for one still running (a stop, a deadline, an
    error in its caller) it ends the leader together with its group, at once."""
    answer = end_led_group(proc, start_time, bound_s=bound_s)
    return answer, _reap(proc, bound_s)


def _wait_leader(proc: subprocess.Popen, start_time: Optional[tuple[int, int]], poll_s: float, *,
                 stop: Optional[Callable[[], bool]] = None, deadline: Optional[float] = None) -> str:
    """Wait, never reaping, until *proc* has exited (``"exited"``), *stop* says so (``"stopped"``) or the monotonic
    *deadline* passes (``"timed-out"``)."""
    while True:
        if stop is not None and stop():
            return "stopped"
        if has_exited(proc, start_time):
            return "exited"
        if deadline is not None and time.monotonic() >= deadline:
            return "timed-out"
        time.sleep(poll_s)


def follow_lines(proc: subprocess.Popen, start_time: Optional[tuple[int, int]], on_line: Callable[[str], None], *,
                 stop: Optional[Callable[[], bool]] = None, poll_s: float = FOLLOW_POLL_S,
                 drain_idle_s: float = DRAIN_IDLE_S, drain_limit_s: float = DRAIN_LIMIT_S,
                 bound_s: float = SHUTDOWN_BOUND_S) -> Retired:
    """Hand each line *proc* writes to *on_line* until *proc* exits, then retire it (v0.8.x P5-C, POSIX).

    *proc* is a class-A child (the leader of its own process group) whose stdout is a pipe -- pip, or an engine probe,
    streamed. What ends the wait is the LEADER's exit, observed without reaping it (:func:`has_exited`), never the end
    of its output alone: a helper left in its group can hold that pipe open for as long as it runs, and a reader that
    waited for end-of-file would wait as long. Once the leader has exited -- or *stop* says so, or *on_line* raises --
    its group is ended the P5-A way (:func:`end_led_group`); after a normal exit what was already written is still
    handed on (until end-of-file, bounded by *drain_idle_s* of silence and *drain_limit_s* in all); only then is the
    leader reaped. Lines are handed on from the calling thread; *stop* is asked about every *poll_s*.
    """
    lines: "queue.Queue[Optional[str]]" = queue.Queue()
    stream = proc.stdout

    def pump() -> None:
        try:
            if stream is not None:
                for line in stream:
                    lines.put(line)
        except (OSError, ValueError):  # the pipe broke or was closed
            pass
        finally:
            lines.put(None)

    reader = threading.Thread(target=pump, name="act-child-output", daemon=True)
    reader.start()
    stopped = eof = False
    try:
        while True:
            if stop is not None and stop():
                stopped = True
                break
            if has_exited(proc, start_time):  # never reaps: its id, and so its group's, stays reserved
                break
            try:
                line = lines.get(timeout=poll_s)
            except queue.Empty:
                continue
            if line is None:
                eof = True
                # Its output ended first: the leader is still waited for (unreaped) before anything is judged.
                stopped = _wait_leader(proc, start_time, poll_s / 2, stop=stop) == "stopped"
                break
            on_line(line)
    except BaseException:
        retire_led_group(proc, start_time, bound_s=bound_s)
        raise
    answer = end_led_group(proc, start_time, bound_s=bound_s)
    output_open = False
    if not stopped and not eof:
        try:
            output_open = not _drain(lines, on_line, drain_idle_s, drain_limit_s)
        except BaseException:
            _reap(proc, bound_s)
            raise
    code = _reap(proc, bound_s)
    if not reader.is_alive() and stream is not None:
        try:  # never closed under a reader still blocked on it: its descriptor could be reused under that read
            stream.close()
        except (OSError, ValueError):
            pass
    return Retired(returncode=code, group=answer, output_open=output_open, stopped=stopped)


def _drain(lines: "queue.Queue[Optional[str]]", on_line: Callable[[str], None], idle_s: float, limit_s: float) -> bool:
    """Hand on what is left in *lines* up to its end-of-file mark: True once it came; False when the output stayed
    silent for *idle_s* without ending, or *limit_s* ran out first."""
    limit = time.monotonic() + max(0.0, limit_s)
    while True:
        remaining = limit - time.monotonic()
        if remaining <= 0:
            return False
        try:
            line = lines.get(timeout=min(max(0.0, idle_s), remaining))
        except queue.Empty:
            return False
        if line is None:
            return True
        on_line(line)


#: The exit status :meth:`Owner.run_python` reports for a child that exited 0 (or was not reaped) while its process
#: group could not be confirmed ended (v0.8.x P5-C): never 0, so no caller can take it for a success.
UNCONFIRMED_RETURNCODE = -1


def _decoded(proc: subprocess.Popen, name: str, data: Optional[bytes]):
    """What ``communicate`` gives for the stream *name*: the bytes, or in text mode the text -- decoded with that
    stream's own encoding and errors, newlines translated -- exactly as CPython's ``Popen._translate_newlines`` does."""
    if data is None or not getattr(proc, "text_mode", False):
        return data
    stream = getattr(proc, name)
    return data.decode(stream.encoding, stream.errors).replace("\r\n", "\n").replace("\r", "\n")


def communicate_led(proc: subprocess.Popen, start_time: Optional[tuple[int, int]], input=None,
                    timeout: Optional[float] = None, *, poll_s: float = 0.02, drain_s: float = DRAIN_IDLE_S,
                    bound_s: float = SHUTDOWN_BOUND_S) -> tuple[Optional[bytes], Optional[bytes], Retired]:
    """``Popen.communicate`` for a class-A child, ended by the LEADER's exit rather than by the end of its output
    (v0.8.x P5-C, POSIX): the probes, proofs, ``-m venv`` and offline pip of :meth:`Owner.run_python`.

    *input* is written to its stdin (when that is a pipe) and stdin is closed, as ``communicate`` does. Its stdout and
    stderr pipes are read on threads, as raw bytes, while the leader runs; once it has exited, or *timeout* has passed
    (``Retired.timed_out``; it is then still running), its group is ended the P5-A way, the output already written is
    collected (at most *drain_s*) and only then is the leader reaped. Returns ``(stdout bytes or None, stderr bytes or
    None, Retired)``; text decoding is the caller's (:meth:`Owner.run_python`). If waiting is interrupted (an exception
    in this thread), the group is ended and the leader reaped before it propagates.
    """
    chunks: dict = {}
    readers = []
    for name in ("stdout", "stderr"):
        stream = getattr(proc, name)
        if stream is None:
            continue
        chunks[name] = []

        def read_all(fd=stream.fileno(), into=chunks[name]) -> None:
            while True:
                try:
                    block = os.read(fd, 65536)
                except InterruptedError:
                    continue
                except OSError:
                    return
                if not block:
                    return
                into.append(block)

        reader = threading.Thread(target=read_all, name="act-child-output", daemon=True)
        reader.start()
        readers.append((name, reader))
    writer = None
    if proc.stdin is not None:
        def write_input() -> None:
            try:
                if input:
                    proc.stdin.write(input)
            except (OSError, ValueError):  # it exited (or closed its stdin) without reading everything
                pass
            try:
                proc.stdin.close()
            except (OSError, ValueError):
                pass

        writer = threading.Thread(target=write_input, name="act-child-input", daemon=True)
        writer.start()
    deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
    try:
        timed_out = _wait_leader(proc, start_time, poll_s, deadline=deadline) == "timed-out"
    except BaseException:
        retire_led_group(proc, start_time, bound_s=bound_s)
        raise
    answer = end_led_group(proc, start_time, bound_s=bound_s)
    drained_by = time.monotonic() + max(0.0, drain_s)
    output_open = False
    for _name, reader in readers:
        reader.join(max(0.0, drained_by - time.monotonic()))
        output_open = output_open or reader.is_alive()
    if writer is not None:
        writer.join(max(0.0, drained_by - time.monotonic()))
    code = _reap(proc, bound_s)
    for name, reader in readers:
        if not reader.is_alive():  # never closed under a reader still blocked on it (see :func:`follow_lines`)
            try:
                getattr(proc, name).close()
            except (OSError, ValueError):
                pass
    out = b"".join(list(chunks["stdout"])) if "stdout" in chunks else None  # a copy: a reader may still be appending
    err = b"".join(list(chunks["stderr"])) if "stderr" in chunks else None
    return out, err, Retired(returncode=code, group=answer, output_open=output_open, timed_out=timed_out)


# --------------------------------------------------------------------------- #
#  Owned children
# --------------------------------------------------------------------------- #
@dataclass
class OwnedChild:
    proc: subprocess.Popen
    kind: str
    pid: int
    pgid: int
    start_time: Optional[tuple[int, int]]
    generation: int = 0
    lost_containment: bool = False
    label: str = ""

    def running(self) -> bool:
        return self.proc.poll() is None


#: How long the orderly end waits for a child's waitpid lock before it leaves that child unsignalled (v0.8.x P5-C). The
#: lock is held only for a moment -- a ``poll`` or a bounded ``wait`` -- or by a thread that is reaping the child now.
_LOCK_WAIT_S = 1.0


def _signal_proved(child: OwnedChild, sig: int, *, wait_s: float = _LOCK_WAIT_S) -> bool:
    """:func:`signal_if_same` under *child*'s own ``Popen`` waitpid lock (v0.8.x P5-C): delivered only while nobody has
    reaped the child (``returncode`` is None, and nobody can until the lock is released) and its kernel start time
    still matches -- so neither its id nor, class A, its group's id can be handed on between the check and the signal.
    Waiting for the lock is bounded by *wait_s*; a child whose lock cannot be had in time, or that has none, is left
    unsignalled (its lifeline or guardian still ends it with this owner). True when a signal was delivered."""
    lock = getattr(child.proc, "_waitpid_lock", None)
    if lock is None or child.start_time is None:
        return False
    if not lock.acquire(timeout=max(0.0, wait_s)):
        return False
    try:
        if child.proc.returncode is not None:
            return False
        return signal_if_same(child.pid, child.start_time, sig, group=child.kind == CLASS_A)
    finally:
        lock.release()


def python_argv(argv: Sequence[str]) -> list[str]:
    """``[python, *options, -m|-c|script, ...]`` -> the same with ``child_entry.py`` before the program."""
    argv = [str(a) for a in argv]
    if not argv:
        raise ValueError("empty command")
    index = 1
    while index < len(argv) and argv[index].startswith("-") and argv[index] not in ("-m", "-c", "-"):
        index += 2 if argv[index] in _OPTIONS_WITH_VALUE else 1
    return [argv[0], *argv[1:index], str(ENTRY), *argv[index:]]


class Owner:
    """The children of one owning process, its lifeline, and its guardian."""

    def __init__(self, log: Optional[Callable[[str], None]] = None, *, lifeline: bool = True,
                 python: Optional[str] = None) -> None:
        # ``lifeline=False`` exists only for the containment tests' negative control (KX-7); production never passes it.
        self._log = log or (lambda _text: None)
        self._lifeline = lifeline
        self._python = python or sys.executable
        self._lock = threading.RLock()
        self._read: Optional[int] = None
        self._write: Optional[int] = None
        self._children: list[OwnedChild] = []
        self._guardian: Optional[subprocess.Popen] = None
        self._guardian_start: Optional[tuple[int, int]] = None
        self._generation = 0
        self._handled_generations: set[int] = set()
        self._retiring = False
        self.events: list[str] = []
        self.degraded = False

    # -- lifeline ------------------------------------------------------------
    def _ensure_lifeline(self) -> int:
        with self._lock:
            if self._read is None:
                self._read, self._write = os.pipe()  # both non-inheritable (PEP 446)
            return self._read

    def lifeline_open(self) -> bool:
        return self._write is not None

    def _note(self, text: str) -> None:
        self.events.append(text)
        try:
            self._log(text)
        except Exception:  # noqa: BLE001 - a log sink never stops containment
            pass

    # -- class A ---------------------------------------------------------------
    def class_a_kwargs(self, kwargs: dict) -> dict:
        """Popen keyword arguments for a class-A child: its own session and the lifeline's read end."""
        if "process_group" in kwargs or kwargs.get("start_new_session") is False:
            raise ValueError("a class-A child always leads its own process group")
        self._refuse_if_closing()
        kw = dict(kwargs)
        kw["start_new_session"] = True
        kw["close_fds"] = True
        if self._lifeline:
            fd = self._ensure_lifeline()
            kw["pass_fds"] = tuple(kw.get("pass_fds", ())) + (fd,)
            env = dict(os.environ if kw.get("env") is None else kw["env"])
            env[LIFELINE_ENV] = str(fd)
            kw["env"] = env
        return kw

    def run_python(self, argv: Sequence[str], *, input=None, capture_output: bool = False,
                   timeout: Optional[float] = None, check: bool = False, **kwargs) -> subprocess.CompletedProcess:
        """``subprocess.run`` of an ACT-authored Python child, contained. Used for bounded single-process probes,
        proofs, ``-m venv`` and setup's offline pip; the owner's exit ends it and everything it started through the
        lifeline.

        v0.8.x P5-C: it is a registered class-A child while it runs, and it is never reaped before its group has been
        ended (:func:`communicate_led`): a helper it left behind when it exited normally ends with it, and one holding
        its output open no longer keeps this call waiting. ``subprocess.run``'s arguments and results are kept --
        *input*, *capture_output*, text decoding with universal newlines, ``check`` (``CalledProcessError``) and
        *timeout* (``TimeoutExpired``, now after its WHOLE group was ended, the child with it). When its group could not
        be proved its own, or not confirmed ended, the run is never a success: a zero exit status is reported as
        :data:`UNCONFIRMED_RETURNCODE`, the reason is added to a captured stderr and recorded in :attr:`events` (setup's
        log), as :meth:`run_external` reports a lost guardian."""
        if input is not None:
            if kwargs.get("stdin") is not None:
                raise ValueError("stdin and input arguments may not both be used.")
            kwargs["stdin"] = subprocess.PIPE
        if capture_output:
            if kwargs.get("stdout") is not None or kwargs.get("stderr") is not None:
                raise ValueError("stdout and stderr arguments may not be used with capture_output.")
            kwargs["stdout"] = kwargs["stderr"] = subprocess.PIPE
        proc = self.popen_python(argv, **kwargs)
        child = self.child(proc)
        try:
            out, err, retired = communicate_led(proc, child.start_time if child is not None else None, input, timeout)
        finally:
            if proc.returncode is not None:
                self.forget(proc)
        out, err = _decoded(proc, "stdout", out), _decoded(proc, "stderr", err)
        problem = retired.problem()
        note = None
        if problem is not None:
            note = f"[containment: {Path(str(argv[0])).name} (pid {proc.pid}) could not be confirmed ended: {problem}]"
            self._note(f"Containment: {Path(str(argv[0])).name} (pid {proc.pid}, exit status {retired.returncode}) "
                       f"could not be confirmed ended: {problem}.")
        if retired.timed_out:
            expired = subprocess.TimeoutExpired(proc.args, timeout, output=out, stderr=err)
            if note is not None:
                expired.add_note(note)
            raise expired
        code = retired.returncode
        if note is not None:
            code = code if code else UNCONFIRMED_RETURNCODE
            if isinstance(err, str):
                err = f"{err}\n{note}\n" if err else f"{note}\n"
            elif isinstance(err, bytes):
                err = err + b"\n" + note.encode("utf-8", "replace") + b"\n" if err else note.encode("utf-8", "replace")
        if check and code:
            raise subprocess.CalledProcessError(code, proc.args, output=out, stderr=err)
        return subprocess.CompletedProcess(proc.args, code, out, err)

    def popen_python(self, argv: Sequence[str], *, label: str = "", **kwargs) -> subprocess.Popen:
        """Start a registered class-A child (pip in setup; the optional-setup worker in the app)."""
        with self._lock:
            proc = subprocess.Popen(python_argv(argv), **self.class_a_kwargs(kwargs))
            self._register(proc, CLASS_A, proc.pid, label or Path(str(argv[0])).name)
        return proc

    def _refuse_if_closing(self) -> None:
        """Once the orderly end has begun nothing new starts: a worker thread that asks for another program while the
        app is closing gets an error, never a child that the closing owner would no longer see (v0.8.x P1B)."""
        if self._retiring:
            raise ContainmentUnavailable("the application is closing; nothing was started")

    def begin_closing(self) -> None:
        """The orderly end's latch (window close, Cmd+Q, SIGTERM/SIGHUP/SIGINT): from now on nothing new starts."""
        self._retiring = True

    @property
    def closing(self) -> bool:
        return self._retiring

    # -- class B ---------------------------------------------------------------
    def _guardian_alive(self) -> bool:
        g = self._guardian
        return g is not None and g.poll() is None and signal_if_same(g.pid, self._guardian_start, 0)

    def guardian_pid(self) -> Optional[int]:
        return self._guardian.pid if self._guardian is not None and self._guardian.poll() is None else None

    def _start_guardian(self) -> int:
        fd = self._ensure_lifeline()
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PYTHON")}
        env[LIFELINE_ENV] = str(fd)
        try:
            proc = subprocess.Popen([self._python, "-I", str(GUARDIAN)], process_group=0, pass_fds=(fd,), env=env,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    close_fds=True)
        except OSError as exc:
            raise ContainmentUnavailable(f"the ACT guardian could not be started: {exc}") from exc
        ready = b""
        deadline = time.monotonic() + GUARDIAN_READY_TIMEOUT_S
        assert proc.stdout is not None
        while not ready.endswith(b"\n") and time.monotonic() < deadline:
            readable, _, _ = select.select([proc.stdout], [], [], max(0.0, deadline - time.monotonic()))
            if not readable:
                break
            block = os.read(proc.stdout.fileno(), 64)
            if not block:
                break
            ready += block
        proc.stdout.close()
        if ready.strip() != b"ready":
            try:
                proc.kill()
            except OSError:
                pass
            proc.wait()
            raise ContainmentUnavailable("the ACT guardian did not start (no ready signal); nothing was started")
        self._generation += 1
        self._guardian = proc
        self._guardian_start = process_start_time(proc.pid)
        generation = self._generation
        threading.Thread(target=self._watch_guardian, args=(proc, generation), name="act-guardian-watch",
                         daemon=True).start()
        return proc.pid

    def _watch_guardian(self, proc: subprocess.Popen, generation: int) -> None:
        proc.wait()
        if self._retiring:
            return
        self._guardian_lost(proc, generation)

    def _guardian_lost(self, proc: subprocess.Popen, generation: int) -> None:
        """Fail closed: the class-B children of a guardian that is gone are ended, and recorded as uncontained."""
        with self._lock:
            if generation in self._handled_generations:
                return
            self._handled_generations.add(generation)
            if self._guardian is proc:
                self._guardian = None
                self._guardian_start = None
            self.degraded = True
            orphans = [c for c in self._children if c.kind == CLASS_B and c.generation == generation and c.running()]
        self._note(f"Containment: the ACT guardian (pid {proc.pid}) ended on its own (exit {proc.returncode}); "
                   f"{len(orphans)} running external program(s) in its group are being stopped, and a new guardian "
                   "is started before the next one.")
        for child in orphans:
            child.lost_containment = True
            self._end(child, grace=TERM_GRACE_S)
            self._note(f"Containment: stopped {child.label or child.pid} (pid {child.pid}): it had lost its guardian.")

    def _guardian_group(self) -> int:
        with self._lock:
            if self._guardian is not None and not self._guardian_alive():
                proc, generation = self._guardian, self._generation
                proc.wait()
                self._guardian_lost(proc, generation)
            if self._guardian is None:
                return self._start_guardian()
            return self._guardian.pid

    def ensure_guardian(self) -> None:
        """Have the guardian running now, starting it if there is none, so that a following :meth:`popen_external` does
        not (v0.8.x P5-H-R1: a start made under the run's Cancel lock must not wait for a guardian to start). Raises
        :class:`ContainmentUnavailable` exactly as :meth:`popen_external` would."""
        with self._lock:
            self._refuse_if_closing()
            self._guardian_group()

    def popen_external(self, argv: Sequence[str], *, label: str = "", **kwargs) -> subprocess.Popen:
        """Start a registered class-B child inside the guardian's group. Raises :class:`ContainmentUnavailable`
        (nothing started) when no guardian can be had."""
        if "start_new_session" in kwargs or "process_group" in kwargs:
            raise ValueError("a class-B child always joins the guardian's group")
        with self._lock:
            self._refuse_if_closing()
            group = self._guardian_group()
            proc = subprocess.Popen([str(a) for a in argv], process_group=group, close_fds=True, **kwargs)
            self._register(proc, CLASS_B, group, label or Path(str(argv[0])).name)
        return proc

    def run_external(self, argv: Sequence[str], *, timeout: Optional[float] = None, label: str = "",
                     **kwargs) -> subprocess.CompletedProcess:
        """A bounded class-B run with captured text output. A child that lost its guardian while running is reported
        by a non-zero return code and ``lost containment`` in stderr, never as a success."""
        kwargs.setdefault("stdout", subprocess.PIPE)
        kwargs.setdefault("stderr", subprocess.PIPE)
        kwargs.setdefault("text", True)
        proc = self.popen_external(argv, label=label, **kwargs)
        child = self.child(proc)
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.end(proc)
            out, err = proc.communicate()
            raise subprocess.TimeoutExpired(proc.args, timeout, output=out, stderr=err) from None
        finally:
            self.forget(proc)
        code = proc.returncode
        if child is not None and child.lost_containment:
            err = (err or "") + "\n[lost containment: its guardian ended, so it was stopped]"
            code = code if code else -int(signal.SIGTERM)
        return subprocess.CompletedProcess(proc.args, code, out, err)

    # -- registry ---------------------------------------------------------------
    def _register(self, proc: subprocess.Popen, kind: str, pgid: int, label: str) -> OwnedChild:
        child = OwnedChild(proc=proc, kind=kind, pid=proc.pid, pgid=pgid, start_time=process_start_time(proc.pid),
                           generation=self._generation if kind == CLASS_B else 0, label=label)
        with self._lock:
            # A child its caller has already reaped can never be signalled again (its id may now be someone else's),
            # so it is dropped here: an app that runs thousands of FFmpeg steps keeps a registry of what is running.
            self._children = [c for c in self._children if c.proc.returncode is None]
            self._children.append(child)
        return child

    def child(self, proc: subprocess.Popen) -> Optional[OwnedChild]:
        with self._lock:
            return next((c for c in self._children if c.proc is proc), None)

    def forget(self, proc: subprocess.Popen) -> None:
        with self._lock:
            self._children = [c for c in self._children if c.proc is not proc]

    def children(self) -> list[OwnedChild]:
        with self._lock:
            return list(self._children)

    def _end(self, child: OwnedChild, *, grace: float) -> None:
        """SIGTERM, at most ``grace`` seconds, SIGKILL, reap. Bounded, quiet, identity-checked.

        Class A: the whole group. The leader is observed with ``WNOWAIT`` and is reaped only after the group's SIGKILL,
        so the group is signalled only while its leader is this owner's unreaped child and its id cannot have been
        reused -- and a grandchild that ignored SIGTERM is still caught. Class B: the process only (it shares the
        guardian's group)."""
        if child.proc.returncode is not None:
            return
        group = child.kind == CLASS_A
        if grace > 0:
            signal_if_same(child.pid, child.start_time, signal.SIGTERM, group=group)
            _wait_exited(child.pid, grace)
        signal_if_same(child.pid, child.start_time, signal.SIGKILL, group=group)
        try:
            child.proc.wait(timeout=2.0)
        except (subprocess.TimeoutExpired, ChildProcessError):
            pass

    def end(self, proc: subprocess.Popen, *, grace: float = TERM_GRACE_S) -> None:
        child = self.child(proc)
        if child is not None:
            self._end(child, grace=grace)

    def _end_many(self, children: Sequence[OwnedChild], *, grace: float) -> None:
        """:meth:`_end` for several children at once, so the bound does not grow with their number: SIGTERM to each,
        one shared wait of at most ``grace`` seconds, SIGKILL to whatever is left, then each is reaped. The same
        identity rules hold: a class-A group is signalled only while its leader is still this owner's unreaped child (a
        leader that has exited but is not yet reaped still identifies its group, so a grandchild left behind is
        caught).

        v0.8.x P5-C: each check-and-signal is made under the child's own ``Popen`` waitpid lock
        (:func:`_signal_proved`), and a class-A group is ended the P5-A way (:func:`end_led_group`: signalled until the
        kernel says nothing is left). A run that reaps its own child at the same moment (a ``WorkerRun`` settling its
        worker, a pip's follower) therefore cannot have that child's id -- or its group's -- handed on between this
        check and this signal: once it has reaped the child, nothing is signalled here."""
        live = [c for c in children if c.proc.returncode is None]
        if not live:
            return
        if grace > 0:
            for child in live:
                _signal_proved(child, signal.SIGTERM)
            deadline = time.monotonic() + grace
            while time.monotonic() < deadline and not all(has_exited(c.proc, c.start_time) for c in live):
                time.sleep(0.02)
        for child in live:
            if child.kind == CLASS_A:
                answer = end_led_group(child.proc, child.start_time, bound_s=2 * TERM_GRACE_S)
                if answer != GROUP_ENDED and child.proc.returncode is None:
                    self._note(f"Containment: {child.label or child.pid} (pid {child.pid}): its process group was not "
                               f"confirmed ended at the orderly end ({answer}).")
            else:
                _signal_proved(child, signal.SIGKILL)
        for child in live:
            try:
                child.proc.wait(timeout=2.0)
            except (subprocess.TimeoutExpired, ChildProcessError):
                pass

    def stop_external(self, labels: Optional[Sequence[str]] = None, *, grace: float = TERM_GRACE_S) -> list[int]:
        """End this owner's running class-B children (only those whose label is in ``labels``, when given) and return
        their pids: the POSIX ``stop_media_children``. Identity-checked, bounded (``grace`` plus the reap), quiet; it
        reads this owner's registry only -- never a process listing, never a name on the system."""
        wanted = None if labels is None else frozenset(labels)
        targets = [c for c in self.children() if c.kind == CLASS_B and c.proc.returncode is None
                   and (wanted is None or c.label in wanted)]
        self._end_many(targets, grace=grace)
        return [c.pid for c in targets]

    def kill_now(self, proc: subprocess.Popen) -> bool:
        """End a registered child (and, for class A, its group) at once with SIGKILL. True if a signal was sent."""
        child = self.child(proc)
        if child is None or child.proc.poll() is not None:
            return False
        return signal_if_same(child.pid, child.start_time, signal.SIGKILL, group=child.kind == CLASS_A)

    # -- orderly shutdown ---------------------------------------------------------
    def shutdown(self) -> None:
        """Orderly end, bounded by :data:`SHUTDOWN_BOUND_S`: class-A groups, class-B children, then the lifeline
        (which retires the guardian), then the guardian is reaped. Crash containment never depends on this."""
        deadline = time.monotonic() + SHUTDOWN_BOUND_S
        self._retiring = True
        # Every child not yet reaped -- running, or exited with its group's leftovers still identifiable -- ended
        # together, so the bound holds whatever their number (v0.8.x P1B).
        unreaped = [c for c in self.children() if c.proc.returncode is None]
        self._end_many(unreaped, grace=min(TERM_GRACE_S, max(0.0, deadline - time.monotonic() - 1.0)))
        with self._lock:
            write, self._write = self._write, None
        if write is not None:
            try:
                os.close(write)
            except OSError:
                pass
        guardian = self._guardian
        if guardian is not None:
            try:
                guardian.wait(timeout=max(0.5, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                signal_if_same(guardian.pid, self._guardian_start, signal.SIGKILL, group=True)
                try:
                    guardian.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    pass


_OWNER: Optional[Owner] = None
_OWNER_LOCK = threading.Lock()


def owner(log: Optional[Callable[[str], None]] = None) -> Owner:
    """This process's owner (created on first use)."""
    global _OWNER
    with _OWNER_LOCK:
        if _OWNER is None:
            _OWNER = Owner(log)
        return _OWNER
