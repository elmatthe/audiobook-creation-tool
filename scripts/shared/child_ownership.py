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
has: the loss is recorded once, at once, by whoever sees it first (the guardian's own watch, or a start that finds it
gone) -- every class-B child of that guardian is marked ``lost_containment`` before anything waits, so its caller
reports a failure -- and those still running are retired together under one shared deadline (identity-checked, SIGTERM
then SIGKILL) without holding up whoever noticed; the next class-B spawn starts a new guardian first. No class-B child is
ever started without a guardian that answered ``ready`` and whose identity was read. The residual: a class-B child whose
guardian died *and* whose owner died (or was stopped) before the loss was recorded is not contained; see Decisions (P1A).

**One ledger, one lifecycle (v0.8.x P5-I).** Every process the owner must still clean up -- a start in progress, a
registered child, a guardian getting ready, a child whose registration failed, a lost guardian's child, one whose end is
not confirmed -- is an entry of one ledger, from its admission until its reaping. The owner is ACTIVE, CLOSING or CLOSED;
admission, adoption and the closing latch are decided under one short lock that is never held across a spawn, a wait or
a signal (:class:`Owner` documents the lock order). Ending is one retirement mechanism with one shared deadline per
batch; a process not confirmed ended by its deadline is reported, kept and still ended -- never dropped or called clean.

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

import contextlib
import os
import queue
import select
import selectors
import signal
import struct
import subprocess
import sys
import threading
import time
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

ENTRY = Path(__file__).resolve().with_name("child_entry.py")
GUARDIAN = Path(__file__).resolve().with_name("child_guardian.py")
LIFELINE_ENV = "ACT_LIFELINE_FD"

CLASS_A = "A"
CLASS_B = "B"

#: How long a new guardian has to say ``ready``.
GUARDIAN_READY_TIMEOUT_S = 10.0
#: How many times an unprepared class-B start has a guardian before it gives up, should each end as it is had.
GUARDIAN_ATTEMPTS = 3
#: How often a wait for a guardian (its own readiness, or another thread making it) looks at a Cancel and the orderly end.
GUARDIAN_POLL_S = 0.05
#: The look an unowned process is given after SIGKILL before it is left to a reaping thread (never a caller's wait).
STRAY_LOOK_S = 0.05
#: SIGTERM -> SIGKILL grace for one child in an orderly end.
TERM_GRACE_S = 1.0
#: Bound on the whole orderly shutdown.
SHUTDOWN_BOUND_S = 5.0

#: Interpreter options that take a value as the next argument (``python -X dev -W error ...``).
_OPTIONS_WITH_VALUE = frozenset({"-X", "-W", "--check-hash-based-pycs"})


class GuardianChanged(RuntimeError):
    """v0.8.x P5-H-R1: the guardian a start was prepared for is gone or replaced. Raised at once instead of starting a new
    guardian where the start may not wait (inside the run's Cancel ordering); the caller prepares again and retries."""


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
#  Owned children: one ownership record, one lifecycle (v0.8.x P5-I)
# --------------------------------------------------------------------------- #
#: The kind of a ledger entry that is a guardian (class A and class B are :data:`CLASS_A` and :data:`CLASS_B`).
GUARDIAN_KIND = "G"

# The owner's phases. ACTIVE -> CLOSING (``begin_closing``/``shutdown``) -> CLOSED (``shutdown`` has returned).
ACTIVE = "active"
CLOSING = "closing"
CLOSED = "closed"

# A ledger entry's states.
SPAWNING = "spawning"  # admitted; its ``Popen`` is in progress, so there is no handle yet
STARTED = "started"  # created; not yet registered (or its registration failed)
LIVE = "live"  # registered; its caller runs it
PENDING = "pending"  # guardian only: created, not yet ready and adopted
ADOPTED = "adopted"  # guardian only: the one class-B children join
RETIRING = "retiring"  # being ended by the owner, under one shared deadline
UNCONFIRMED = "unconfirmed"  # its deadline passed and its end is not confirmed: still owned, still being ended
DONE = "done"  # its exit is confirmed (reaped); no longer in the ledger

#: How long the owner's closing (``begin_closing``/``shutdown``) and a run's settlement wait for spawns already admitted to
#: produce their processes. A spawn takes milliseconds; one that takes longer is not waited for: its process, once it
#: exists, is never registered or adopted and is stopped at once. (A run's Cancel waits only for admissions, never spawns.)
START_SETTLE_S = 0.2
#: After SIGKILL, how long a retirement has to confirm the end (reap the process) before it is reported unconfirmed.
KILL_CONFIRM_S = 1.0
#: How often a retirement in progress is looked at; how often SIGKILL is repeated to a process that has not ended.
RETIRE_POLL_S = 0.02
KILL_REPEAT_S = 0.1
#: How often an unconfirmed process is killed again until it ends.
UNCONFIRMED_POLL_S = 0.25
#: How long a retirement may wait for a child's waitpid lock in one look (it looks again at the next).
RETIRE_LOCK_WAIT_S = 0.02
#: The part of the orderly end's bound kept for the guardian: lifeline end-of-file, its own 1 s grace, its reaping.
GUARDIAN_END_S = 1.5
#: How long the thread that made a guardian it then did not adopt looks for that guardian's end.
UNADOPTED_LOOK_S = 0.5
#: The most a run's settlement waits for its own processes still owed cleanup (each has its own, shorter, deadline).
SETTLE_BOUND_S = 4.0

_CLOSING_TEXT = "the application is closing; nothing was started"
_CHANGED_TEXT = "the ACT guardian changed after this start was prepared; nothing was started"


@dataclass(eq=False)
class OwnedChild:
    """One process this owner is responsible for, from its admission until its exit is confirmed (v0.8.x P5-I).

    Class A and class B children and the guardians are all entries of the one ledger. An entry leaves it only when its
    process has been reaped (``proc.returncode`` set); a wait, poll or signal that fails proves nothing and leaves it."""

    proc: Optional[subprocess.Popen]
    kind: str
    pid: int
    pgid: int
    start_time: Optional[tuple[int, int]]
    generation: int = 0
    lost_containment: bool = False
    label: str = ""
    run: Any = None  # the run that started it (its cancel check), or None
    state: str = LIVE
    spawns: int = 0  # guardian only: class-B starts in progress into its group (it is not reaped while there are any)
    kill_at: Optional[float] = None
    confirm_by: Optional[float] = None
    term_wanted: bool = False
    termed: bool = False
    last_kill: float = 0.0
    group_ended: bool = False

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def resolved(self) -> bool:
        """No cleanup is owed any more: it is out of the ledger, or (a child) its caller has reaped it."""
        return self.state == DONE or (self.kind != GUARDIAN_KIND and self.proc is not None
                                      and self.proc.returncode is not None)


@dataclass(eq=False)
class Admission:
    """A class-B start admitted into a guardian and not yet spawned (v0.8.x P5-I): what a run admits inside its Cancel
    ordering and spawns after it (:meth:`Owner.popen_external` with ``admission=``), or gives back (:meth:`Owner.release`).
    Its entry is in the ledger, SPAWNING, until one of those happens."""

    entry: "OwnedChild"
    guardian: "OwnedChild"
    used: bool = False


#: How long the orderly end waits for a child's waitpid lock before it leaves that child unsignalled (v0.8.x P5-C). The
#: lock is held only for a moment -- a ``poll`` or a bounded ``wait`` -- or by a thread that is reaping the child now.
_LOCK_WAIT_S = 1.0


def _signal_proved(child: OwnedChild, sig: int, *, wait_s: float = _LOCK_WAIT_S, group: Optional[bool] = None) -> bool:
    """:func:`signal_if_same` under *child*'s own ``Popen`` waitpid lock (v0.8.x P5-C): delivered only while nobody has
    reaped the child (``returncode`` is None, and nobody can until the lock is released) and its kernel start time
    still matches -- so neither its id nor, class A, its group's id can be handed on between the check and the signal.
    Waiting for the lock is bounded by *wait_s*; a child whose lock cannot be had in time, or that has none, is left
    unsignalled (its lifeline or guardian still ends it with this owner). True when a signal was delivered. *group*:
    signal the group it leads (default: class A)."""
    lock = getattr(child.proc, "_waitpid_lock", None)
    if lock is None or child.start_time is None:
        return False
    if not lock.acquire(timeout=max(0.0, wait_s)):
        return False
    try:
        if child.proc.returncode is not None:
            return False
        return signal_if_same(child.pid, child.start_time, sig, group=child.kind == CLASS_A if group is None else group)
    finally:
        lock.release()


def _signal_own(proc: subprocess.Popen, sig: int, *, wait_s: float = RETIRE_LOCK_WAIT_S) -> bool:
    """Signal this process's own child *proc* whose kernel start time could not be read (v0.8.x P5-I): under its
    waitpid lock, only while it is unreaped -- the kernel keeps an unreaped child's id reserved, so the id is still its
    own (CPython's ``send_signal`` guard, bpo-38630). The process only, never a group. True when delivered."""
    lock = getattr(proc, "_waitpid_lock", None)
    if lock is None or not lock.acquire(timeout=max(0.0, wait_s)):
        return False
    try:
        if proc.returncode is not None:
            return False
        os.kill(proc.pid, sig)
        return True
    except OSError:
        return False
    finally:
        lock.release()


def _end_group_once(proc: subprocess.Popen, start_time: Optional[tuple[int, int]], *,
                    wait_s: float = RETIRE_LOCK_WAIT_S) -> str:
    """One look of :func:`end_led_group` (v0.8.x P5-I): SIGKILL to the group *proc* leads, under the same three-part proof,
    and the kernel's answer -- :data:`GROUP_ENDED` once nothing it may signal is left, :data:`GROUP_REMAINING` while a
    member still answers (or the lock is busy: look again), :data:`GROUP_UNPROVED` when the id is no longer provably
    its own, :data:`GROUP_SIGNALLED` where emptiness cannot be read (Linux, development only). Never waits."""
    lock = getattr(proc, "_waitpid_lock", None)
    if start_time is None or lock is None:
        return GROUP_UNPROVED
    if not lock.acquire(timeout=max(0.0, wait_s)):
        return GROUP_REMAINING
    try:
        if proc.returncode is not None or process_start_time(proc.pid) != start_time:
            return GROUP_UNPROVED
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            return GROUP_ENDED
        except PermissionError:
            return GROUP_ENDED if sys.platform == "darwin" else GROUP_REMAINING
        except OSError:
            return GROUP_REMAINING
        return GROUP_REMAINING if sys.platform == "darwin" else GROUP_SIGNALLED
    finally:
        lock.release()


def _wait_for_exit(proc: subprocess.Popen) -> None:
    """Return once this process's child *proc* has exited -- WITHOUT reaping it (v0.8.x P5-I): a guardian's exit is seen
    while its id, and so its group's, stays reserved. macOS: a kqueue ``NOTE_EXIT`` watch, with a look every half second
    as well; elsewhere a look every :data:`GUARDIAN_POLL_S`."""
    kq = None
    if sys.platform == "darwin" and hasattr(select, "kqueue"):
        with contextlib.suppress(OSError):
            kq = select.kqueue()
    try:
        if kq is not None:
            event = select.kevent(proc.pid, filter=select.KQ_FILTER_PROC,
                                  flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT, fflags=select.KQ_NOTE_EXIT)
            try:
                kq.control([event], 0, 0)
            except OSError:
                kq.close()
                kq = None  # already a zombie or gone (ESRCH): the looks below see it at once
        while not has_exited(proc):
            if kq is not None:
                with contextlib.suppress(OSError):
                    kq.control(None, 1, 0.5)
            else:
                time.sleep(GUARDIAN_POLL_S)
    finally:
        if kq is not None:
            with contextlib.suppress(OSError):
                kq.close()


def _communicate_bounded(proc: subprocess.Popen, timeout: Optional[float], input=None):
    """``proc.communicate(input, timeout)`` taken in short slices (v0.8.x P5-I), so this thread never sits in a blocking
    ``waitpid`` holding the child's waitpid lock: the owner's retirement can always take that lock to prove and signal
    the child. Raises ``TimeoutExpired`` as ``communicate`` does once *timeout* has passed."""
    deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
    while True:
        remaining = None if deadline is None else deadline - time.monotonic()
        step = 0.1 if remaining is None else max(0.0, min(0.1, remaining))
        try:
            return proc.communicate(input, timeout=step)
        except subprocess.TimeoutExpired:
            input = None  # sent once; a later call may not send it again
            if remaining is not None and remaining <= step:
                raise subprocess.TimeoutExpired(proc.args, timeout) from None


def _unconfirmed_text(entry: "OwnedChild") -> str:
    return (f"Containment: {entry.label or entry.pid} (pid {entry.pid}) was told to end and is not confirmed ended; it is "
            "still owned and is still being ended.")


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
    """The children of one owning process, its lifeline, and its guardian (v0.8.x P5-I: one ledger, one lifecycle).

    **Lock order.** ``_state`` (a plain lock under a condition) guards the phase, the ledger and the guardian record. It
    is held only to read and change them: never across ``Popen``, a wait for a process, a guardian's readiness, a signal
    or a log line. A ``Popen``'s waitpid lock is taken (bounded) only with ``_state`` let go. ``_step_lock`` is taken
    without blocking, never inside ``_state``. A run's controller lock is never held when this owner is called (a counted
    start lets it go before its body), and this owner never calls a controller holding ``_state``.

    **Spawn admission.** A start is admitted under ``_state`` (refused once closing has begun; a class-B start only into
    the adopted guardian it was prepared for) and its entry is in the ledger from that moment, in state SPAWNING. The
    ``Popen`` runs with no owner lock held. The entry then holds the process (STARTED) before anything else can fail,
    and is registered (LIVE) -- or, if anything went wrong, retired: a created process is never dropped from the ledger.

    **Retirement.** Ending is one mechanism with one shared deadline per batch: SIGTERM to all at once (when a grace is
    given), SIGKILL to whatever is left when the grace ends, and confirmation -- the process reaped -- by the batch's
    deadline. A process not confirmed ended by then becomes UNCONFIRMED: still owned, still killed again, reaped when it
    ends, and reported as such. One reaper thread of this owner drives retirements nobody waits for; a caller that must
    know (a run's settlement, the orderly end, ``stop_external``) drives the same steps itself.

    **Guardian lifecycle.** One guardian is made at a time (``_creating``). Its spawn is admitted like any child; its
    exit is watched from birth without reaping it; it is adopted only after it said ``ready``, its identity was read,
    the owner is still ACTIVE and -- inside the run's Cancel ordering -- the run was not cancelled. A guardian that
    ends while adopted is a *loss*, recorded once under ``_state``: every class-B child of its generation is marked
    ``lost_containment`` at that moment, before anything waits, and handed to retirement; the caller that noticed goes
    on. A guardian is reaped only while no start is joining its group, so its group's id cannot be handed on meanwhile.
    """

    def __init__(self, log: Optional[Callable[[str], None]] = None, *, lifeline: bool = True,
                 python: Optional[str] = None) -> None:
        # ``lifeline=False`` exists only for the containment tests' negative control (KX-7); production never passes it.
        self._log = log or (lambda _text: None)
        self._lifeline = lifeline
        self._python = python or sys.executable
        self._state = threading.Condition(threading.Lock())
        self._phase = ACTIVE
        self._entries: list[OwnedChild] = []
        self._current: Optional[OwnedChild] = None  # the adopted guardian
        self._creating = False  # a thread is making a guardian
        self._creating_run: Any = None  # the run that guardian is being made for
        self._generation = 0
        self._lost_generations: set[int] = set()
        self._lost_procs: "weakref.WeakSet[subprocess.Popen]" = weakref.WeakSet()  # outlives their ledger entries
        self._read: Optional[int] = None
        self._write: Optional[int] = None
        self._reaping = False
        self._step_lock = threading.Lock()
        self.events: list[str] = []
        self.degraded = False

    # -- diagnostics (read-only views of the ledger) ---------------------------
    @property
    def _guardian(self) -> Optional[subprocess.Popen]:
        current = self._current
        return current.proc if current is not None else None

    @property
    def _guardian_start(self) -> Optional[tuple[int, int]]:
        current = self._current
        return current.start_time if current is not None else None

    @property
    def _pending_guardian(self) -> Optional[subprocess.Popen]:
        with self._state:
            return next((e.proc for e in self._entries
                         if e.kind == GUARDIAN_KIND and e.state in (STARTED, PENDING) and e.proc is not None), None)

    @property
    def _strays(self) -> list[subprocess.Popen]:
        """Processes this owner created that no caller runs any more and that are not yet confirmed ended."""
        with self._state:
            return [e.proc for e in self._entries if e.kind != GUARDIAN_KIND and e.proc is not None
                    and e.state in (STARTED, RETIRING, UNCONFIRMED)]

    @property
    def _retiring(self) -> bool:
        return self._phase != ACTIVE

    @property
    def phase(self) -> str:
        return self._phase

    def retiring(self) -> list[OwnedChild]:
        """Entries being ended, or whose end is not confirmed."""
        with self._state:
            return [e for e in self._entries if e.state in (RETIRING, UNCONFIRMED)]

    def unconfirmed(self) -> list[OwnedChild]:
        """Entries whose retirement deadline passed with their end not confirmed (still owned, still being ended)."""
        with self._state:
            return [e for e in self._entries if e.state == UNCONFIRMED]

    # -- lifeline ------------------------------------------------------------
    def _ensure_lifeline(self) -> int:
        with self._state:
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

    # -- the ledger -------------------------------------------------------------
    def _entry_locked(self, proc: subprocess.Popen) -> Optional[OwnedChild]:
        return next((e for e in self._entries if e.proc is proc and e.kind != GUARDIAN_KIND), None)

    def _remove_locked(self, entry: OwnedChild) -> None:
        entry.state = DONE
        with contextlib.suppress(ValueError):
            self._entries.remove(entry)
        self._state.notify_all()

    def _prune_locked(self) -> None:
        """Children their callers have reaped leave the ledger: an app that runs thousands of FFmpeg steps keeps a
        ledger of what is running. Nothing whose end is not confirmed ever leaves it."""
        done = [e for e in self._entries if e.kind != GUARDIAN_KIND and e.proc is not None
                and e.proc.returncode is not None and e.state in (STARTED, LIVE)]
        for entry in done:
            self._remove_locked(entry)

    def _admit(self, kind: str, *, label: str, run: Any = None, guardian: Optional[OwnedChild] = None) -> OwnedChild:
        """Admit one start, ordered against closing (and, class B, against its guardian's replacement): its entry is in
        the ledger from here on. Raises :class:`ContainmentUnavailable` once closing has begun, :class:`GuardianChanged`
        when *guardian* is no longer the adopted one. Nothing is spawned here."""
        with self._state:
            if self._phase != ACTIVE:
                raise ContainmentUnavailable(_CLOSING_TEXT)
            if guardian is not None and (guardian is not self._current or guardian.state != ADOPTED):
                raise GuardianChanged(_CHANGED_TEXT)
            entry = OwnedChild(proc=None, kind=kind, pid=0, pgid=guardian.pid if guardian is not None else 0,
                               start_time=None, generation=guardian.generation if guardian is not None else 0,
                               label=label, run=run, state=SPAWNING)
            self._entries.append(entry)
            if kind == GUARDIAN_KIND:
                self._generation += 1
                entry.generation = self._generation
            if guardian is not None:
                guardian.spawns += 1
            return entry

    def _spawn(self, entry: OwnedChild, argv: list, kwargs: dict, guardian: Optional[OwnedChild] = None,
               spawn_check: Optional[Callable[[], None]] = None) -> subprocess.Popen:
        """The ``Popen`` of an admitted entry, with no owner lock held. ``spawn_check`` (a run's Cancel) gets the last
        look immediately before it and raises to refuse it. On failure nothing was created and the entry leaves the
        ledger; on success the entry holds the process before anything else is done."""
        try:
            if self._phase != ACTIVE:  # the closing latch, at the last look before the process exists
                raise ContainmentUnavailable(_CLOSING_TEXT)
            if spawn_check is not None:
                spawn_check()
            proc = subprocess.Popen(argv, **kwargs)
        except BaseException:
            with self._state:
                self._remove_locked(entry)
                if guardian is not None:
                    guardian.spawns -= 1
            self._kick()
            raise
        with self._state:
            entry.proc = proc
            entry.pid = proc.pid
            if entry.kind != CLASS_B:
                entry.pgid = proc.pid
            entry.state = STARTED
            if guardian is not None:
                guardian.spawns -= 1
            self._state.notify_all()
        if guardian is not None and guardian.state != ADOPTED:
            self._kick()  # a lost guardian is reaped once no start is joining its group
        return proc

    def _drop_unspawned(self, entry: OwnedChild) -> None:
        with self._state:
            if entry.state == SPAWNING:
                self._remove_locked(entry)

    def _take_on(self, entry: OwnedChild, proc: subprocess.Popen,
                 guardian: Optional[OwnedChild] = None) -> subprocess.Popen:
        """After the spawn: the child's identity, then its registration -- or, if closing began or its guardian was
        lost meanwhile, or anything fails, its retirement (it stays in the ledger until its end is confirmed)."""
        try:
            start = process_start_time(proc.pid)
            with self._state:
                entry.start_time = start
                closing = self._phase != ACTIVE
                lost = guardian is not None and guardian.state != ADOPTED
            if guardian is not None and not lost and has_exited(guardian.proc, guardian.start_time):
                self._guardian_lost(guardian.proc, guardian.generation)
                lost = True
            if closing or lost:
                if lost:
                    entry.lost_containment = True
                self._retire_now([entry], STRAY_LOOK_S)
                if lost:
                    raise GuardianChanged("the ACT guardian ended while this start joined its group; the child was "
                                          "stopped")
                raise ContainmentUnavailable(_CLOSING_TEXT)
            self._register(proc, entry.kind, entry.pgid, entry.label)
        except BaseException:
            if entry.state in (STARTED, LIVE):
                self._retire_now([entry], STRAY_LOOK_S)
            raise
        return proc

    def _register(self, proc: subprocess.Popen, kind: str, pgid: int, label: str) -> OwnedChild:
        """Registration: the entry admitted for *proc* becomes LIVE (one is made if *proc* was never admitted)."""
        start = None
        if self.child(proc) is None:
            start = process_start_time(proc.pid)
        with self._state:
            self._prune_locked()
            entry = self._entry_locked(proc)
            if entry is None:
                current = self._current
                entry = OwnedChild(proc=proc, kind=kind, pid=proc.pid, pgid=pgid, start_time=start,
                                   generation=current.generation if kind == CLASS_B and current is not None else 0,
                                   label=label, state=LIVE)
                self._entries.append(entry)
            elif entry.state == STARTED:
                entry.state = LIVE
            return entry

    def child(self, proc: subprocess.Popen) -> Optional[OwnedChild]:
        with self._state:
            return self._entry_locked(proc)

    def forget(self, proc: subprocess.Popen) -> None:
        """Its caller is done with *proc*. Reaped: it leaves the ledger. Not reaped: the owner keeps it and ends it --
        a child is never dropped while it may still run (v0.8.x P5-I)."""
        with self._state:
            entry = self._entry_locked(proc)
            if entry is None:
                return
            if proc.returncode is not None:
                self._remove_locked(entry)
                return
            if entry.state in (RETIRING, UNCONFIRMED):
                return
            self._schedule_locked([entry], grace=0.0)
        self._kick()

    def children(self) -> list[OwnedChild]:
        with self._state:
            return [e for e in self._entries if e.kind != GUARDIAN_KIND and e.proc is not None]

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
        """Start a registered class-A child (pip in setup; the optional-setup worker in the app). Admitted under the
        owner's state lock, spawned with none held (v0.8.x P5-I)."""
        command = python_argv(argv)
        kw = self.class_a_kwargs(kwargs)
        entry = self._admit(CLASS_A, label=label or Path(str(argv[0])).name)
        proc = self._spawn(entry, command, kw)
        return self._take_on(entry, proc)

    # -- closing -----------------------------------------------------------------
    def _refuse_if_closing(self) -> None:
        """Once the orderly end has begun nothing new starts: a worker thread that asks for another program while the
        app is closing gets an error, never a child that the closing owner would no longer see (v0.8.x P1B)."""
        if self._phase != ACTIVE:
            raise ContainmentUnavailable(_CLOSING_TEXT)

    def _wait_spawns_locked(self, until: float) -> None:
        while any(e.state == SPAWNING for e in self._entries):
            remaining = until - time.monotonic()
            if remaining <= 0:
                return
            self._state.wait(remaining)

    def begin_closing(self) -> None:
        """The orderly end's latch (window close, Cmd+Q, SIGTERM/SIGHUP/SIGINT): from now on nothing new is admitted --
        no child, no guardian, no adoption (v0.8.x P5-I: set under the same lock that admits them). Starts admitted
        before it are waited for at most :data:`START_SETTLE_S`; one still in progress then is stopped as soon as its
        process exists, never registered, and the orderly end sees it in the ledger."""
        with self._state:
            if self._phase == ACTIVE:
                self._phase = CLOSING
            self._state.notify_all()
            self._wait_spawns_locked(time.monotonic() + START_SETTLE_S)

    @property
    def closing(self) -> bool:
        return self._phase != ACTIVE

    # -- class B ---------------------------------------------------------------
    @staticmethod
    def _entry_alive(entry: Optional[OwnedChild]) -> bool:
        """A guardian entry whose process is running and still the one recorded (never reaps)."""
        return (entry is not None and entry.proc is not None and entry.start_time is not None
                and not has_exited(entry.proc, entry.start_time))

    def _guardian_alive(self) -> bool:
        return self._entry_alive(self._current)

    def guardian_pid(self) -> Optional[int]:
        current = self._current
        return current.pid if self._entry_alive(current) else None

    def _await_ready(self, proc: subprocess.Popen, checkpoint: Optional[Callable[[], None]]) -> None:
        """Wait for a new guardian's ``ready``, looking every :data:`GUARDIAN_POLL_S` at the orderly end and at
        ``checkpoint`` (a run's Cancel, which raises), through a selector (a busy application's pipe can be numbered
        past ``select``'s limit)."""
        ready = b""
        deadline = time.monotonic() + GUARDIAN_READY_TIMEOUT_S
        assert proc.stdout is not None
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            while not ready.endswith(b"\n"):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._refuse_if_closing()
                if checkpoint is not None:
                    checkpoint()
                if not selector.select(min(GUARDIAN_POLL_S, remaining)):
                    continue
                block = os.read(proc.stdout.fileno(), 64)
                if not block:
                    break
                ready += block
        if ready.strip() != b"ready":
            raise ContainmentUnavailable("the ACT guardian did not start (no ready signal); nothing was started")

    def _start_guardian(self, spawn_context: Optional[Callable[[], Any]] = None,
                        checkpoint: Optional[Callable[[], None]] = None) -> int:
        """Make the guardian and adopt it (v0.8.x P5-I). Called by the one thread making a guardian (``_creating``),
        holding no lock.

        Its admission is ordered inside ``spawn_context`` (a run's Cancel ordering: no guardian is admitted for a
        cancelled run); its spawn follows outside it, after a last look at the run's Cancel (``checkpoint``) and at
        closing, so a slow spawn never holds a Cancel. Its exit is watched from birth, never reaped by the watch. Its readiness is
        waited for outside any ordering, looking at the orderly end and at ``checkpoint`` (a run's Cancel). It is adopted
        only with its identity read, the owner still ACTIVE and -- inside ``spawn_context`` again -- the run still not
        cancelled. A guardian not adopted, for whatever reason, is retired (it stays in the ledger until it has ended)."""
        fd = self._ensure_lifeline()
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PYTHON")}
        env[LIFELINE_ENV] = str(fd)
        ordering = spawn_context if spawn_context is not None else contextlib.nullcontext
        entry: Optional[OwnedChild] = None
        proc: Optional[subprocess.Popen] = None
        adopted = False
        try:
            with ordering():  # the admission alone is ordered against the run's Cancel; the spawn is not held in it
                entry = self._admit(GUARDIAN_KIND, label="guardian", run=self._creating_run)
            try:
                proc = self._spawn(entry, [self._python, "-I", str(GUARDIAN)],
                                   dict(process_group=0, pass_fds=(fd,), env=env, stdin=subprocess.DEVNULL,
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, close_fds=True),
                                   spawn_check=checkpoint)
            except OSError as exc:
                raise ContainmentUnavailable(f"the ACT guardian could not be started: {exc}") from exc
            with self._state:
                if entry.state == STARTED:
                    entry.state = PENDING
            threading.Thread(target=self._watch_guardian, args=(proc, entry.generation), name="act-guardian-watch",
                             daemon=True).start()
            self._await_ready(proc, checkpoint)
            start = process_start_time(proc.pid)
            if start is None:
                raise ContainmentUnavailable("the ACT guardian's identity could not be read, so it was not used; "
                                             "nothing was started")
            with self._state:
                entry.start_time = start
            with ordering():
                with self._state:
                    if self._phase != ACTIVE:
                        raise ContainmentUnavailable(_CLOSING_TEXT)
                    if entry.state != PENDING:  # it ended (its watch saw it) or was retired by the orderly end
                        raise ContainmentUnavailable("the ACT guardian ended as soon as it was ready; nothing was "
                                                     "started")
                    entry.state = ADOPTED
                    self._current = entry
                    adopted = True
                    self._state.notify_all()
        finally:
            if proc is not None and proc.stdout is not None:
                with contextlib.suppress(OSError):
                    proc.stdout.close()
            if not adopted and entry is not None:
                if proc is None:
                    self._drop_unspawned(entry)
                else:
                    self._retire_now([entry], UNADOPTED_LOOK_S)
        return proc.pid

    def _watch_guardian(self, proc: subprocess.Popen, generation: int) -> None:
        _wait_for_exit(proc)
        self._guardian_lost(proc, generation)

    def _guardian_lost(self, proc: subprocess.Popen, generation: int) -> None:
        """A guardian has ended (v0.8.x P5-I). If it was the adopted one and the owner is ACTIVE, this is a loss,
        recorded once and at once under ``_state``: every class-B child of its generation is marked ``lost_containment``
        now, before anything waits, and those still running are handed to retirement together (one shared deadline).
        Nothing here waits: whoever noticed goes on. The guardian itself is reaped once no start is joining its group."""
        orphans: list[OwnedChild] = []
        loss = False
        with self._state:
            entry = next((e for e in self._entries if e.kind == GUARDIAN_KIND and e.proc is proc), None)
            if entry is None or entry.state == DONE:
                return
            if entry.state == ADOPTED and self._phase == ACTIVE and generation not in self._lost_generations:
                loss = True
                self._lost_generations.add(generation)
                entry.lost_containment = True
                self.degraded = True
                orphans = [e for e in self._entries if e.kind == CLASS_B and e.generation == generation
                           and e.proc is not None and e.state != DONE]
                for orphan in orphans:
                    orphan.lost_containment = True
                    self._lost_procs.add(orphan.proc)
                self._schedule_locked([o for o in orphans if o.proc.returncode is None], grace=TERM_GRACE_S)
            if self._current is entry:
                self._current = None
            if entry.state in (STARTED, PENDING, ADOPTED):
                self._schedule_locked([entry], grace=0.0)
        if loss:
            running = [o for o in orphans if o.proc.returncode is None]
            self._note(f"Containment: the ACT guardian (pid {proc.pid}) ended on its own (exit {proc.returncode}); "
                       f"{len(running)} running external program(s) in its group are being stopped, and a new guardian "
                       "is started before the next one.")
        self._kick()

    def _guardian_gone(self, guardian: OwnedChild) -> bool:
        """The guardian a start was admitted into is no longer the adopted, running one (its loss is recorded)."""
        if guardian.state != ADOPTED:
            return True
        if has_exited(guardian.proc, guardian.start_time):
            self._guardian_lost(guardian.proc, guardian.generation)
            return True
        return False

    def _current_guardian(self, spawn_context: Optional[Callable[[], Any]] = None,
                          checkpoint: Optional[Callable[[], None]] = None, run: Any = None) -> tuple[int, int]:
        """The running guardian's pid and generation, making (or replacing) it first if need be. One thread makes it at
        a time; the others wait on ``_state`` (let go while waiting), looking at the orderly end and at ``checkpoint``
        (a run's Cancel, which raises) every :data:`GUARDIAN_POLL_S`. A lost guardian is recorded and the caller goes
        on at once: its children's retirement is never waited for here."""
        while True:
            self._refuse_if_closing()
            if checkpoint is not None:
                checkpoint()
            with self._state:
                if self._phase != ACTIVE:
                    raise ContainmentUnavailable(_CLOSING_TEXT)
                current = self._current
                if current is None:
                    if self._creating:
                        self._state.wait(GUARDIAN_POLL_S)
                        continue
                    self._creating, self._creating_run = True, run
            if current is not None:
                if self._entry_alive(current):
                    return current.pid, current.generation
                self._guardian_lost(current.proc, current.generation)
                continue
            try:
                self._start_guardian(spawn_context, checkpoint)
            finally:
                with self._state:
                    self._creating, self._creating_run = False, None
                    self._state.notify_all()
            with self._state:
                current = self._current
                if current is None:
                    raise ContainmentUnavailable("the ACT guardian ended as soon as it was ready; nothing was started")
                return current.pid, current.generation

    def _guardian_group(self, spawn_context: Optional[Callable[[], Any]] = None) -> int:
        return self._current_guardian(spawn_context)[0]

    def ensure_guardian(self, spawn_context: Optional[Callable[[], Any]] = None,
                        checkpoint: Optional[Callable[[], None]] = None, run: Any = None) -> int:
        """Have the guardian running now, starting (or replacing) it if need be, and return its generation, so that a
        following :meth:`popen_external` with ``require_generation`` starts nothing but its child (v0.8.x P5-H-R1: a start
        made inside the run's Cancel ordering must never wait for a guardian). ``spawn_context`` and ``checkpoint``: as
        for :meth:`_start_guardian`. ``run``: the run a guardian made now is made for (its retirement is that run's to
        account for). Raises :class:`ContainmentUnavailable` exactly as :meth:`popen_external` would."""
        self._refuse_if_closing()
        return self._current_guardian(spawn_context, checkpoint, run)[1]

    def popen_external(self, argv: Sequence[str], *, label: str = "", **kwargs) -> subprocess.Popen:
        """Start a registered class-B child inside the guardian's group. Raises :class:`ContainmentUnavailable`
        (nothing started) when no guardian can be had.

        v0.8.x P5-I: the guardian is had first (made if need be); the start is then admitted into exactly that guardian
        and spawned with no owner lock held. With ``require_generation`` nothing is made: a guardian gone or replaced
        since the start was prepared -- or one found gone when the child's join of its group fails, or once the child
        exists -- raises :class:`GuardianChanged` (any child made is stopped). Unprepared, that is retried, bounded.
        ``owner_run``: the run the child belongs to (its settlement accounts for it). ``spawn_check``: called immediately
        before the spawn, raising to refuse it (a run's Cancel latched meanwhile). ``admission``: an
        :meth:`admit_external` ticket -- the start was admitted inside the run's Cancel ordering, and this spawns it,
        outside that ordering, so a slow spawn never holds a Cancel. A child whose registration fails is retired, never
        dropped, and the caller is not held."""
        if "start_new_session" in kwargs or "process_group" in kwargs:
            raise ValueError("a class-B child always joins the guardian's group")
        required = kwargs.pop("require_generation", None)
        run = kwargs.pop("owner_run", None)
        spawn_check = kwargs.pop("spawn_check", None)
        admission = kwargs.pop("admission", None)
        label = label or Path(str(argv[0])).name
        command = [str(a) for a in argv]
        if admission is not None:
            return self._spawn_admitted(admission, command, kwargs, spawn_check)
        self._refuse_if_closing()
        for _attempt in range(1 if required is not None else GUARDIAN_ATTEMPTS):
            try:
                if required is not None:
                    expected = required
                else:
                    expected = self.ensure_guardian(**({"run": run} if run is not None else {}))
                ticket = self.admit_external(label=label, run=run, require_generation=expected)
                return self._spawn_admitted(ticket, command, kwargs, spawn_check)
            except GuardianChanged:
                if required is not None:
                    raise
        raise ContainmentUnavailable("the ACT guardian kept ending as it was started; nothing was started")

    def admit_external(self, *, label: str, run: Any = None, require_generation: int) -> Admission:
        """Admit one class-B start into exactly the guardian of ``require_generation`` (v0.8.x P5-I): under ``_state``
        only, never waiting on anything else -- the part of a start that a run's Cancel is ordered against. Raises
        :class:`GuardianChanged` (that guardian is gone or replaced) or :class:`ContainmentUnavailable` (closing). Spawn
        it with ``popen_external(..., admission=)``, or give it back with :meth:`release`."""
        with self._state:
            guardian = self._current
            usable = guardian is not None and guardian.generation == require_generation
        if not usable or self._guardian_gone(guardian):
            raise GuardianChanged(_CHANGED_TEXT)
        return Admission(self._admit(CLASS_B, label=label, run=run, guardian=guardian), guardian)

    def release(self, admission: Optional[Admission]) -> None:
        """Give back an admission that was never spawned (nothing to do once its spawn was attempted)."""
        if admission is None or admission.used:
            return
        admission.used = True
        with self._state:
            if admission.entry.state == SPAWNING:
                self._remove_locked(admission.entry)
                admission.guardian.spawns -= 1
        self._kick()

    def _spawn_admitted(self, admission: Admission, command: list, kwargs: dict,
                        spawn_check: Optional[Callable[[], None]]) -> subprocess.Popen:
        """Spawn an admitted class-B start in its guardian's group (no owner lock held), then take it on. A failed join
        because that guardian has died is its loss (:class:`GuardianChanged`, the start is prepared again); any other
        spawn error is the caller's."""
        if admission.used:
            raise RuntimeError("an admission is spawned once")
        admission.used = True
        entry, guardian = admission.entry, admission.guardian
        try:
            proc = self._spawn(entry, command, dict(process_group=guardian.pid, close_fds=True, **kwargs), guardian,
                               spawn_check)
        except OSError as exc:
            if self._guardian_gone(guardian):  # its group could not be joined because it had ended
                raise GuardianChanged(_CHANGED_TEXT) from exc
            raise
        return self._take_on(entry, proc, guardian)

    def containment_held(self, proc: subprocess.Popen) -> bool:
        """False when *proc* (a class-B child) lost its guardian -- recorded now if its guardian is found gone -- or
        its guardian is not the adopted, running one: a run of it is then never a success (v0.8.x P5-I)."""
        with self._state:
            if proc in self._lost_procs:
                return False
            entry = self._entry_locked(proc)
            if entry is None or entry.kind != CLASS_B:
                return True
            if entry.lost_containment or entry.generation in self._lost_generations:
                return False
            guardian = self._current
            if guardian is None or guardian.generation != entry.generation:
                return False
        if self._guardian_gone(guardian):
            return False
        return not entry.lost_containment

    def run_external(self, argv: Sequence[str], *, timeout: Optional[float] = None, label: str = "",
                     **kwargs) -> subprocess.CompletedProcess:
        """A bounded class-B run with captured text output. A child that lost its guardian while running -- or whose
        guardian is found gone once it has ended -- is reported by a non-zero return code and ``lost containment`` in
        stderr, never as a success. Its output is collected in short slices, never in a blocking wait."""
        kwargs.setdefault("stdout", subprocess.PIPE)
        kwargs.setdefault("stderr", subprocess.PIPE)
        kwargs.setdefault("text", True)
        proc = self.popen_external(argv, label=label, **kwargs)
        try:
            try:
                out, err = _communicate_bounded(proc, timeout)
            except subprocess.TimeoutExpired:
                self.end(proc)
                out = err = None
                with contextlib.suppress(subprocess.TimeoutExpired):
                    out, err = _communicate_bounded(proc, KILL_CONFIRM_S)
                raise subprocess.TimeoutExpired(proc.args, timeout, output=out, stderr=err) from None
            held = self.containment_held(proc)
        finally:
            self.forget(proc)
        code = proc.returncode
        if not held:
            err = (err or "") + "\n[lost containment: its guardian ended, so it was stopped]"
            code = code if code else -int(signal.SIGTERM)
        return subprocess.CompletedProcess(proc.args, code, out, err)

    @staticmethod
    def communicate(proc: subprocess.Popen, input=None, timeout: Optional[float] = None):
        """``proc.communicate(input, timeout)`` for a contained child, in short slices (:func:`_communicate_bounded`)."""
        return _communicate_bounded(proc, timeout, input)

    # -- retirement ---------------------------------------------------------------
    def _schedule_locked(self, entries: Sequence[OwnedChild], *, grace: float,
                         confirm_by: Optional[float] = None) -> None:
        """Hand *entries* to retirement as one batch: SIGTERM now when *grace* > 0, SIGKILL to what is left once it has
        passed, the end confirmed by ``confirm_by`` (default: :data:`KILL_CONFIRM_S` after the SIGKILL). An entry
        already retiring keeps the earlier of its deadlines: a deadline is never extended."""
        now = time.monotonic()
        kill_at = now + max(0.0, grace)
        by = kill_at + KILL_CONFIRM_S if confirm_by is None else max(now, confirm_by)
        for entry in entries:
            if entry.state == DONE or entry.proc is None:
                continue
            if entry.state in (RETIRING, UNCONFIRMED):
                entry.kill_at = min(entry.kill_at if entry.kill_at is not None else kill_at, kill_at)
                if entry.state == RETIRING:
                    entry.confirm_by = min(entry.confirm_by if entry.confirm_by is not None else by, by)
                continue
            entry.state = RETIRING
            entry.term_wanted = grace > 0
            entry.kill_at = kill_at
            entry.confirm_by = by
        self._state.notify_all()

    def _retire_now(self, entries: Sequence[OwnedChild], look_s: float) -> None:
        """Retire *entries* at once (SIGKILL, no grace): signalled from this thread now, then looked at for at most
        *look_s*; whatever has not ended by then stays in the ledger, retired by the owner's reaper."""
        with self._state:
            self._schedule_locked(entries, grace=0.0)
        self._retire_step()
        self._kick()
        if look_s > 0:
            self._await(entries, until=time.monotonic() + look_s)

    def _deliver(self, entry: OwnedChild, sig: int) -> bool:
        if entry.start_time is not None:
            return _signal_proved(entry, sig, wait_s=RETIRE_LOCK_WAIT_S)
        return _signal_own(entry.proc, sig)  # identity never read: the process only, under its waitpid lock

    def _advance(self, entry: OwnedChild, now: float, notes: list[str]) -> None:
        """One look at one entry being retired. Never waits; signals with no owner lock held."""
        proc = entry.proc
        if proc.returncode is not None and entry.kind == CLASS_A and not entry.group_ended:
            # Reaped by its own caller first: its group's id can no longer be proved its own, so nothing is signalled.
            entry.group_ended = True
            notes.append(f"Containment: {entry.label or entry.pid} (pid {entry.pid}) was reaped before its process group "
                         "was confirmed ended; that group could not be proved its own and was not signalled.")
        exited = proc.returncode is not None or has_exited(proc, entry.start_time)
        if exited:
            if entry.kind == CLASS_A and not entry.group_ended and proc.returncode is None:
                answer = _end_group_once(proc, entry.start_time)
                if answer != GROUP_REMAINING:
                    entry.group_ended = True
                    if answer == GROUP_UNPROVED:
                        notes.append(f"Containment: {entry.label or entry.pid} (pid {entry.pid}): its process group "
                                     "could not be proved its own, so nothing was signalled to it.")
            may_reap = entry.kind != CLASS_A or entry.group_ended
            if entry.kind == GUARDIAN_KIND and entry.spawns > 0:
                may_reap = False  # a start is joining its group: its id stays reserved until that is over
            if may_reap and proc.returncode is None:
                with contextlib.suppress(Exception):  # noqa: BLE001 - a failed reap proves nothing; looked at again
                    proc.poll()
            if may_reap and proc.returncode is not None:
                with self._state:
                    was = entry.state
                    self._remove_locked(entry)
                if entry.lost_containment and entry.kind == CLASS_B:
                    notes.append(f"Containment: stopped {entry.label or entry.pid} (pid {entry.pid}): it had lost its "
                                 "guardian.")
                if was == UNCONFIRMED:
                    notes.append(f"Containment: {entry.label or entry.pid} (pid {entry.pid}) has now ended.")
                return
        else:
            if entry.term_wanted and not entry.termed:
                self._deliver(entry, signal.SIGTERM)
                entry.termed = True
            if entry.kill_at is not None and now >= entry.kill_at and now - entry.last_kill >= KILL_REPEAT_S:
                self._deliver(entry, signal.SIGKILL)
                entry.last_kill = now
        if entry.state == RETIRING and entry.confirm_by is not None and now >= entry.confirm_by:
            with self._state:
                marked = entry.state == RETIRING
                if marked:
                    entry.state = UNCONFIRMED
                    self._state.notify_all()
            if marked:
                notes.append(_unconfirmed_text(entry))

    def _retire_step(self) -> None:
        """One look at every entry being retired (whoever calls it: the reaper, a settlement, the orderly end). Only
        one thread looks at a time; another simply returns and waits on ``_state`` for the result."""
        if not self._step_lock.acquire(blocking=False):
            return
        notes: list[str] = []
        try:
            with self._state:
                work = [e for e in self._entries if e.state in (RETIRING, UNCONFIRMED) and e.proc is not None]
            now = time.monotonic()
            for entry in work:
                try:
                    self._advance(entry, now, notes)
                except Exception:  # noqa: BLE001 - a look that fails proves nothing; the entry stays and is looked at again
                    pass
        finally:
            self._step_lock.release()
        for text in notes:
            self._note(text)

    def _kick(self) -> None:
        """Have the owner's one reaper running while anything is being retired (started on demand; it ends when
        nothing is left). If no thread can be started, the entries stay in the ledger and whoever waits drives them."""
        with self._state:
            self._state.notify_all()
            if self._reaping or not any(e.state in (RETIRING, UNCONFIRMED) for e in self._entries):
                return
            self._reaping = True
        try:
            threading.Thread(target=self._reap_loop, name="act-owner-reaper", daemon=True).start()
        except Exception:  # noqa: BLE001 - the ledger keeps them; settlement and the orderly end drive retirement
            with self._state:
                self._reaping = False

    def _reap_loop(self) -> None:
        try:
            while True:
                self._retire_step()
                with self._state:
                    work = [e for e in self._entries if e.state in (RETIRING, UNCONFIRMED)]
                    if not work:
                        self._reaping = False
                        return
                    pause = RETIRE_POLL_S if any(e.state == RETIRING for e in work) else UNCONFIRMED_POLL_S
                    self._state.wait(pause)
        except BaseException:  # noqa: BLE001 - the ledger keeps the entries; the next kick starts another reaper
            with self._state:
                self._reaping = False

    def _await(self, entries: Sequence[OwnedChild], until: float) -> list[OwnedChild]:
        """Drive retirement until every one of *entries* is confirmed ended, or *until* passes, or every one left is past
        its own deadline. Returns those not confirmed. Bounded by *until*."""
        while True:
            self._retire_step()
            now = time.monotonic()
            notes: list[str] = []
            with self._state:
                left = [e for e in entries if not e.resolved()]
                done = (not left or now >= until
                        or all(e.state == UNCONFIRMED or (e.confirm_by is not None and now >= e.confirm_by)
                               for e in left))
                if done:
                    for entry in left:  # past its deadline: said so now, not at the reaper's next look
                        if entry.state == RETIRING and entry.confirm_by is not None and now >= entry.confirm_by:
                            entry.state = UNCONFIRMED
                            notes.append(_unconfirmed_text(entry))
                else:
                    self._state.wait(max(0.0, min(RETIRE_POLL_S, until - now)))
            if done:
                for text in notes:
                    self._note(text)
                return left

    def _retire_and_wait(self, entries: Sequence[OwnedChild], *, grace: float) -> list[OwnedChild]:
        with self._state:
            self._schedule_locked(entries, grace=grace)
            until = max([e.confirm_by for e in entries if e.confirm_by is not None], default=time.monotonic())
        self._kick()
        return self._await(entries, until=until)

    def _end(self, child: OwnedChild, *, grace: float) -> None:
        """SIGTERM, at most ``grace`` seconds, SIGKILL, confirmed reaped by the shared deadline -- or reported
        unconfirmed and kept. Identity-checked: class A its whole group (signalled only while provably its own)."""
        if child.proc is None or child.proc.returncode is not None:
            return
        self._retire_and_wait([child], grace=grace)

    def end(self, proc: subprocess.Popen, *, grace: float = TERM_GRACE_S) -> None:
        child = self.child(proc)
        if child is not None:
            self._end(child, grace=grace)

    def _end_many(self, children: Sequence[OwnedChild], *, grace: float) -> list[OwnedChild]:
        """:meth:`_end` for several children at once, under one shared deadline: the bound does not grow with their
        number. Returns those not confirmed ended."""
        live = [c for c in children if c.proc is not None and c.proc.returncode is None]
        if not live:
            return []
        return self._retire_and_wait(live, grace=grace)

    def stop_external(self, labels: Optional[Sequence[str]] = None, *, grace: float = TERM_GRACE_S) -> list[int]:
        """End this owner's running class-B children (only those whose label is in ``labels``, when given) and return
        their pids: the POSIX ``stop_media_children``. Identity-checked, bounded (``grace`` plus the confirmation
        window, shared), quiet; it reads this owner's ledger only -- never a process listing, never a name."""
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

    # -- a run's settlement ----------------------------------------------------------
    def outstanding(self, run: Any = None) -> list[OwnedChild]:
        """Every entry still owed cleanup -- starting, running, being ended or unconfirmed -- of *run* (all runs when
        None). An adopted guardian is the owner's, not a run's."""
        with self._state:
            return [e for e in self._entries if not e.resolved() and not (e.kind == GUARDIAN_KIND and e.state == ADOPTED)
                    and (run is None or e.run == run)]

    def settle_run(self, run: Any, bound_s: float = SETTLE_BOUND_S) -> list[int]:
        """What a run's settlement must know before it may report a clean end (v0.8.x P5-I): its processes still owed
        cleanup are accounted for. A start still in progress is waited for (at most :data:`START_SETTLE_S`); a process
        of the run still running under nobody is retired at once; each is waited for until it is confirmed ended or
        its own retirement deadline passes (never past *bound_s*). Returns the pids NOT confirmed ended -- they stay
        owned and keep being ended; the run must then not report success or a clean Cancel."""
        if run is None:
            return []
        began = time.monotonic()
        until = began + max(0.0, bound_s)
        with self._state:
            spawn_until = min(until, began + START_SETTLE_S)
            while any(e.state == SPAWNING and e.run == run for e in self._entries):
                remaining = spawn_until - time.monotonic()
                if remaining <= 0:
                    break
                self._state.wait(remaining)
            mine = [e for e in self._entries if not e.resolved() and e.run == run
                    and not (e.kind == GUARDIAN_KIND and e.state == ADOPTED)]
            self._schedule_locked([e for e in mine if e.state in (STARTED, LIVE, PENDING)], grace=0.0)
        if not mine:
            return []
        self._kick()
        left = self._await(mine, until=until)
        return sorted({e.pid or -1 for e in left})

    # -- orderly shutdown ---------------------------------------------------------
    def shutdown(self) -> list[int]:
        """Orderly end, bounded by :data:`SHUTDOWN_BOUND_S` from its call, every wait against that one deadline (v0.8.x
        P5-I): nothing new is admitted; starts in progress get at most :data:`START_SETTLE_S`; every process in the
        ledger but the adopted guardian -- children, guardians never adopted, children whose registration failed, a
        lost guardian's children -- is retired as one batch (SIGTERM, one shared grace, SIGKILL), confirmed by the
        deadline less :data:`GUARDIAN_END_S`; then the lifeline is closed (the guardian ends its group and itself) and
        the guardian reaped, SIGKILLed with its group (proved) if it has not ended in time. Returns the pids NOT
        confirmed ended (recorded in :attr:`events`); they stay in the ledger. Crash containment never depends on this."""
        began = time.monotonic()
        deadline = began + SHUTDOWN_BOUND_S
        children_by = deadline - GUARDIAN_END_S
        with self._state:
            if self._phase == ACTIVE:
                self._phase = CLOSING
            self._state.notify_all()
            self._wait_spawns_locked(min(children_by, began + START_SETTLE_S))
            in_flight = sum(1 for e in self._entries if e.state == SPAWNING)
            owned = [e for e in self._entries if e.proc is not None and not e.resolved()
                     and not (e.kind == GUARDIAN_KIND and e.state == ADOPTED)]
            grace = min(TERM_GRACE_S, max(0.0, children_by - time.monotonic() - KILL_CONFIRM_S))
            self._schedule_locked(owned, grace=grace, confirm_by=children_by)
        if in_flight:
            self._note(f"Containment: {in_flight} start(s) admitted before the orderly end were still in progress; each "
                       "process is stopped, never registered, as soon as it exists.")
        self._kick()
        left = self._await(owned, until=children_by) if owned else []
        with self._state:
            write, self._write = self._write, None
            guardians = [e for e in self._entries if e.kind == GUARDIAN_KIND and e.proc is not None
                         and not e.resolved() and e not in owned]
        if write is not None:
            with contextlib.suppress(OSError):
                os.close(write)
        give_up = deadline - 0.25
        while any(not has_exited(g.proc, g.start_time) for g in guardians) and time.monotonic() < give_up:
            time.sleep(RETIRE_POLL_S)
        for guardian in guardians:
            if not has_exited(guardian.proc, guardian.start_time):
                if guardian.start_time is not None:
                    _signal_proved(guardian, signal.SIGKILL, wait_s=RETIRE_LOCK_WAIT_S, group=True)
                else:
                    _signal_own(guardian.proc, signal.SIGKILL)
        with self._state:
            self._current = None
            self._schedule_locked(guardians, grace=0.0, confirm_by=deadline)
        self._kick()
        # Looked at once more, together: a child the guardian ended with its group (after its own retirement's deadline)
        # is reaped and counted as ended, not reported.
        left = self._await([*left, *guardians], until=deadline) if (left or guardians) else []
        with self._state:
            if self._phase == CLOSING:
                self._phase = CLOSED
            self._state.notify_all()
        unconfirmed = sorted({e.pid for e in left if not e.resolved()})
        if unconfirmed:
            self._note(f"Containment: the orderly end could not confirm that {len(unconfirmed)} process(es) ended "
                       f"(pid {', '.join(map(str, unconfirmed))}); they are still being ended.")
        return unconfirmed


_OWNER: Optional[Owner] = None
_OWNER_LOCK = threading.Lock()


def owner(log: Optional[Callable[[str], None]] = None) -> Owner:
    """This process's owner (created on first use)."""
    global _OWNER
    with _OWNER_LOCK:
        if _OWNER is None:
            _OWNER = Owner(log)
        return _OWNER
