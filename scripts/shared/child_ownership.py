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
import errno
import itertools
import os
import queue
import select
import selectors
import shutil
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import weakref
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

ENTRY = Path(__file__).resolve().with_name("child_entry.py")
GUARDIAN = Path(__file__).resolve().with_name("child_guardian.py")
LAUNCH = Path(__file__).resolve().with_name("child_launch.py")
LIFELINE_ENV = "ACT_LIFELINE_FD"
PERMIT_ENV = "ACT_PERMIT_ROOT"
OWNER_ENV = "ACT_OWNER_PID"
#: P5-I-R3 remediation 2 (finding 3, escaping descendants): every class-A child carries ``ACT_CHILD_TOKEN_<token>=1`` in
#: its environment (its descendants inherit it); the guardian, told the token as ``ACT_SWEEP_TOKEN``, ends every process
#: of this account whose kernel-recorded environment carries it once the owner is gone -- registered or not, stopped or
#: not, in the leader's group or one of its own.
CHILD_TOKEN_ENV = "ACT_CHILD_TOKEN"
#: P5-I-R3 remediation 3 (finding 3): each class-A child also carries ``ACT_LEADER_TOKEN_<token>=1``, its own; when its
#: group is ended (:func:`end_led_group`) every process of this account carrying it -- a descendant that left the group
#: or the session -- is ended too, so a worker's Cancel leaves none of them running.
LEADER_TOKEN_ENV = "ACT_LEADER_TOKEN"
SWEEP_TOKEN_ENV = "ACT_SWEEP_TOKEN"

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


class LaunchRevoked(ContainmentUnavailable):
    """v0.8.x P5-I-R3: a pending Cancel (or the orderly end) revoked a start before its program ran."""


class _Relaunch(RuntimeError):
    """Internal: a gate looked its program up too late with nothing asking it to stop (a slow machine); start again."""


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
        if info is not None:
            return info[_P_STAT_OFFSET] == _SZOMB
        # Unreadable (P5-I-R3 remediation 3, finding 12): only "no such process" counts as an exit; anything else is
        # treated as still running, so a stop goes on to signal it (identity-checked) rather than wait for a reap.
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except OSError:
            return False
        return False
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
                return _swept(proc, deadline)
            except PermissionError:
                return _swept(proc, deadline) if sys.platform == "darwin" else GROUP_REMAINING
            except OSError:
                return GROUP_REMAINING
            if sys.platform != "darwin":
                return GROUP_SIGNALLED  # a zombie leader is still a signalled member there: emptiness cannot be read
            if time.monotonic() >= deadline:
                return GROUP_REMAINING
            time.sleep(0.02)
    finally:
        lock.release()


def _swept(proc: subprocess.Popen, deadline: float) -> str:
    """The group *proc* leads is gone; now every process of this account that carries *proc*'s own leader token (a
    descendant that left the group or the session, P5-I-R3 remediation 3) is SIGKILLed -- each one's start time read
    before its environment is looked at and again right before the signal -- until none is left or *deadline*.
    ``GROUP_ENDED`` when none is left; ``GROUP_REMAINING`` otherwise."""
    token = getattr(proc, "act_leader_token", None)
    if not token:
        return GROUP_ENDED
    try:
        from . import child_guardian as sweep
    except ImportError:  # pragma: no cover - imported bare off scripts/shared
        import child_guardian as sweep  # type: ignore[no-redef]
    marker = f"{LEADER_TOKEN_ENV}_{token}=1".encode("ascii")
    while True:
        found = 0
        for pid in sweep._all_pids():
            if pid in (os.getpid(), proc.pid):
                continue
            before = sweep._start_time(pid)
            if before is None or marker not in sweep._environment(pid):
                continue
            found += 1
            with contextlib.suppress(OSError):
                if os.getpgid(pid) == pid and sweep._start_time(pid) == before:
                    os.killpg(pid, signal.SIGKILL)
            with contextlib.suppress(OSError):
                if sweep._start_time(pid) == before:
                    os.kill(pid, signal.SIGKILL)
        if not found:
            return GROUP_ENDED
        if time.monotonic() >= deadline:
            return GROUP_REMAINING
        time.sleep(0.02)


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
GRANTING = "granting"  # class B (P5-I-R3): its gate may execute the program now, inside the run's counted start

# The permit-gated launch (v0.8.x P5-I-R3; ``child_launch.py``).
#: How long a new gate has to identify itself (outside any ordering; a caller's Cancel stops the wait).
HELLO_TIMEOUT_S = 10.0
#: How long a gate that was told to go has to execute its program while nothing asks it to stop.
EXEC_WAIT_S = 2.0
#: ... and once a Cancel is pending, the owner is closing, or the caller left: then its permit is revoked.
EXEC_CUT_S = 0.02
#: How often the counted start looks for that evidence.
EXEC_LOOK_S = 0.002
#: After revocation, how long an execution already past its lookup has to show itself.
POST_REVOKE_S = 0.02
#: How long a gate killed inside the counted start has to be seen ended.
KILL_CONFIRM_LAUNCH_S = 0.1
#: The most a refused revocation holds the counted start (and so the Cancel latch).
REVOKE_HOLD_S = 0.3
# The orderly end's wait for grants already past their last look (P5-I-R3 remediation 3, finding 7): each one ends
# on its own bounds (cut exec wait, revoke, kill confirm) well inside this; one that does not is cut and reported.
CLOSE_GRANT_WAIT_S = 0.6
# How long a revocation waits for a file-system call once its G was taken back (only tidiness is left then).
REVOKE_FS_WAIT_S = 0.05
#: Starts made for one request: a guardian that changed, or a gate too slow with nothing asking it to stop.
LAUNCH_ATTEMPTS = 3
#: How often a caller waiting for its launch looks at its Cancel and at the orderly end.
CALLER_POLL_S = 0.02
_LAUNCH_TOKENS = itertools.count(1)

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
    exec_unknown: bool = False  # class B (P5-I-R3): its gate was killed with its execution neither seen nor excluded
    announced: bool = False  # class A (P5-I-R3): registered with the guardian
    launch: Any = None  # class B (P5-I-R3): its launch while that is in progress (the orderly end may cut it)

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def resolved(self) -> bool:
        """No cleanup is owed any more: it is out of the ledger, or (a child) its caller has reaped it."""
        return self.state == DONE or (self.kind != GUARDIAN_KIND and self.proc is not None
                                      and self.proc.returncode is not None)


@dataclass(eq=False)
class _Launch:
    """One class-B start in progress (v0.8.x P5-I-R3): what its launch thread and its waiting caller share."""

    entry: "OwnedChild"
    guardian: "OwnedChild"
    program: str
    argv: list
    kwargs: dict
    ordering: Optional[Callable[[], Any]] = None
    pending: Optional[Callable[[], bool]] = None
    cancel_error: Optional[Callable[[], BaseException]] = None
    args: Optional[list] = None  # what the caller asked for (the Popen's public ``args``)
    proc: Optional[subprocess.Popen] = None
    directory: str = ""
    permit: str = ""
    environment: str = ""  # the program's exact environment, for the gate's execve (remediation 3, finding 13)
    status_r: Optional[int] = None
    status_w: Optional[int] = None
    go_r: Optional[int] = None
    go_w: Optional[int] = None
    kq: Any = None
    done: threading.Event = field(default_factory=threading.Event)
    result: Optional[subprocess.Popen] = None
    error: Optional[BaseException] = None
    abandoned: bool = False
    finished: bool = False
    cut: bool = False
    exited: bool = False
    status_eof: bool = False
    revoked: bool = False
    revoked_first: bool = False
    unrevoked_but_dead: bool = False
    stdio: list = field(default_factory=list)  # the launch's own duplicates of the caller's stdio descriptors
    #: The owner's own copy of the go pipe's read end (P5-I-R3 remediation 1): a ``G`` the gate has not read yet is
    #: taken back out of the pipe on revocation -- a gate that never read it can never execute.
    go_back: Optional[int] = None
    go_taken_back: bool = False
    go_lock: threading.Lock = field(default_factory=threading.Lock)  # the ``G`` write vs. its take-back
    closing_cut: bool = False  # the orderly end cut this grant (``_cut_grants``)

    @property
    def label(self) -> str:
        return self.entry.label or os.path.basename(self.program)


def _own_stdio(kwargs: dict) -> tuple[dict, list]:
    """The launch's own duplicates of the descriptors the caller hands ``Popen`` as stdin/stdout/stderr (v0.8.x
    P5-I-R3): a caller that leaves a start in progress (its Cancel) closes its files at once, and a descriptor number
    it closed may be reused by an unrelated file before the launch thread's ``Popen`` runs -- the program would then
    read or write that file. The duplicates are the launch's, closed once its ``Popen`` has returned (or failed).
    ``PIPE``/``DEVNULL``/``STDOUT``/``None`` are left as they are."""
    owned: list = []
    out = dict(kwargs)
    try:
        for key in ("stdin", "stdout", "stderr"):
            value = out.get(key)
            if value is None or (isinstance(value, int) and value < 0):
                continue
            fd = value if isinstance(value, int) else value.fileno()
            dup = os.dup(fd)  # not inheritable; Popen dup2s it onto the child's 0/1/2
            owned.append(dup)
            out[key] = dup
    except (OSError, ValueError, AttributeError) as exc:
        _close_fds(owned)
        raise ContainmentUnavailable(f"the program's standard streams could not be taken over ({exc}); nothing ran") \
            from exc
    return out, owned


def _close_fds(fds: list) -> None:
    while fds:
        with contextlib.suppress(OSError):
            os.close(fds.pop())


def _resolve_program(name: str, env: Optional[dict], cwd: Any) -> str:
    """The program ``Popen`` would execute for *name* (``PATH`` of *env*, or relative to *cwd*), resolved to its real
    file. ``FileNotFoundError`` / ``PermissionError`` exactly where ``Popen`` would raise them; nothing is created."""
    if os.path.dirname(name):
        path = name if os.path.isabs(name) else os.path.join(os.fspath(cwd) if cwd else os.getcwd(), name)
    else:
        search = (os.environ if env is None else env).get("PATH", os.defpath)
        if cwd:  # the child searches after its chdir: a relative entry is relative to *cwd*, as for Popen
            search = os.pathsep.join(entry if os.path.isabs(entry) else os.path.join(os.fspath(cwd), entry or ".")
                                     for entry in search.split(os.pathsep))
        found = shutil.which(name, path=search)
        if found is None:
            raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), name)
        path = found
    path = os.path.realpath(path)
    if not os.path.isfile(path):
        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), name)
    if not os.access(path, os.X_OK):
        raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), name)
    return path


def _interpreted(program: str, argv: list) -> tuple[str, list]:
    """What the kernel would execute for *program*: itself, or -- a ``#!`` script -- its interpreter, given the
    script's real path (as ``execve`` does: interpreter, its one optional argument, the script, the remaining
    arguments). The permit then gates the interpreter, and the script is read from its own path, never through the
    permit (which is revoked as soon as the interpreter runs)."""
    try:
        with open(program, "rb") as handle:
            head = handle.read(512)
    except OSError:
        return program, argv
    if not head.startswith(b"#!"):
        return program, argv
    line = head[2:].split(b"\n", 1)[0].strip()
    if not line:
        return program, argv
    parts = line.split(None, 1)
    interpreter = os.fsdecode(parts[0])
    if not os.path.isabs(interpreter) or not os.path.isfile(interpreter):
        return program, argv
    extra = [os.fsdecode(parts[1].strip())] if len(parts) > 1 and parts[1].strip() else []
    return os.path.realpath(interpreter), [interpreter, *extra, program, *argv[1:]]


def proc_placeholder():
    """Something with no child behind it (a Popen stand-in that raised before handing one back)."""
    return type("NoChild", (), {"_child_created": False, "pid": None})()


def _write_environment(path: str, env: Any) -> None:
    """The environment the program is to get, exactly as ``Popen`` would give it (*env*, or this process's own when
    None), as NUL-separated ``KEY=VALUE`` entries in a new 0600 file (P5-I-R3 remediation 3, finding 13): the gate
    executes the program with these, never with its own interpreter's environment (which Python and the system amend,
    e.g. ``LC_CTYPE`` and ``__CF_USER_TEXT_ENCODING``)."""
    if env is None:
        entries = [k + b"=" + v for k, v in os.environb.items()]
    else:
        entries = []
        for key, value in env.items():
            key, value = os.fsencode(key), os.fsencode(value)
            if b"=" in key or b"\0" in key or b"\0" in value:
                raise ValueError("illegal environment variable name or value")
            entries.append(key + b"=" + value)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0), 0o600)
    try:
        data = b"\0".join(entries)
        while data:
            data = data[os.write(fd, data):]
    finally:
        os.close(fd)


def _bounded_call(fn: Callable[[], Any], wait_s: float) -> tuple[bool, Any]:
    """Run *fn* on its own daemon thread and wait for it at most *wait_s* (P5-I-R3 remediation 3, finding 9): returns
    (finished, result); an exception counts as finished with result None. A call still running is left to finish."""
    done = threading.Event()
    box: list[Any] = [None]

    def run() -> None:
        try:
            box[0] = fn()
        except BaseException:  # noqa: BLE001 - the caller acts on "not established"
            box[0] = None
        finally:
            done.set()

    try:
        threading.Thread(target=run, name="act-bounded-fs", daemon=True).start()
    except RuntimeError:
        return False, None
    finished = done.wait(max(0.0, wait_s))
    return finished, box[0] if finished else None


def _readable(fd: int, wait_s: float) -> bool:
    """*fd* is readable (or at end-of-file) within *wait_s*: ``poll``, which -- unlike ``select`` -- takes any
    descriptor number (a process with more than 1024 open files)."""
    poller = select.poll()
    poller.register(fd, select.POLLIN | select.POLLHUP | select.POLLERR)
    return bool(poller.poll(max(0, int(wait_s * 1000))))


def _read_line(fd: int, timeout: float) -> str:
    """One line from *fd* within *timeout* (without its newline), or what arrived before end-of-file or the timeout."""
    until = time.monotonic() + max(0.0, timeout)
    data = b""
    while not data.endswith(b"\n"):
        remaining = until - time.monotonic()
        if remaining <= 0:
            break
        try:
            if not _readable(fd, min(0.05, remaining)):
                continue
            block = os.read(fd, 64 - len(data) if len(data) < 64 else 1)
        except InterruptedError:
            continue
        except (OSError, ValueError):
            break
        if not block:
            break
        data += block
    return data.decode("ascii", "replace").strip()


def _exec_watch(pid: int):
    """A kqueue watching *pid* for ``NOTE_EXEC`` and ``NOTE_EXIT`` (never reaping), or None where none can be had."""
    if not hasattr(select, "kqueue"):
        return None
    try:
        kq = select.kqueue()
    except OSError:
        return None
    try:
        kq.control([select.kevent(pid, select.KQ_FILTER_PROC, select.KQ_EV_ADD,
                                  select.KQ_NOTE_EXEC | select.KQ_NOTE_EXIT)], 0, 0)
    except OSError:
        kq.close()
        return None
    return kq


def _asks(predicate: Callable[[], bool]) -> bool:
    try:
        return bool(predicate())
    except Exception:  # noqa: BLE001 - a question that cannot be answered asks nothing
        return False


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
        self._closing_pending = False  # set before CLOSING: no new G; grants in progress finish first
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
        self._permits: Optional[str] = None  # P5-I-R3: this owner's start-permit folder (made on first use)
        self._faults: list = []  # P5-I-R3: (run, text) of starts that could not be kept contained
        self._child_token = os.urandom(16).hex()  # P5-I-R3: carried by every class-A child and its descendants
        self._registry: Optional[int] = None  # P5-I-R3: write end of the adopted guardian's class-A registry
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
    def _admitting(self) -> bool:
        """Nothing new is admitted, granted or released once the orderly end is pending (P5-I-R3 remediation 3)."""
        return self._phase == ACTIVE and not self._closing_pending

    def _latch_closing(self, until: float) -> None:
        """Publish CLOSING only after every grant in progress has ended (finding 7): first no new ``G`` is written (the
        pending flag, looked at under each launch's ``go_lock``) and every grant in progress is cut at once -- its
        unread ``G`` taken back, its permit removed, its gate killed (finding 5 of remediation 2); then the grant
        threads are waited for, at most :data:`CLOSE_GRANT_WAIT_S`, and only then is CLOSING published. A grant still
        in progress then is cut again and, if its gate is not confirmed ended, reported."""
        with self._state:
            if self._phase == ACTIVE:
                self._closing_pending = True
            self._state.notify_all()
        # At once, before any wait (remediation 2, finding 5): a G already written but not yet read is taken back, its
        # permit removed and its gate killed -- a stalled grant thread cannot leave it queued while this waits.
        self._cut_grants()
        with self._state:
            end = min(until, time.monotonic() + CLOSE_GRANT_WAIT_S)
            while any(e.state == GRANTING for e in self._entries):
                remaining = end - time.monotonic()
                if remaining <= 0:
                    break
                self._state.wait(remaining)
            if self._phase == ACTIVE:
                self._phase = CLOSING
            self._state.notify_all()
        self._cut_grants()

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
        self._unannounce_locked(entry)
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
            if entry.kind == CLASS_B and self._lost_locked(entry):
                self._lost_procs.add(entry.proc)  # remediation 2, finding 9: the evidence outlives the entry
            self._remove_locked(entry)

    def _lost_locked(self, entry: OwnedChild) -> bool:
        """Under ``_state``: *entry* (class B) lost its guardian -- recorded, or its guardian seen gone now (never
        waits; the loss itself is recorded by the guardian's watcher)."""
        if entry.lost_containment or entry.generation in self._lost_generations:
            return True
        guardian = self._current
        if guardian is None or guardian.generation != entry.generation:
            return True
        return has_exited(guardian.proc, guardian.start_time)

    def _admit(self, kind: str, *, label: str, run: Any = None, guardian: Optional[OwnedChild] = None) -> OwnedChild:
        """Admit one start, ordered against closing (and, class B, against its guardian's replacement): its entry is in
        the ledger from here on. Raises :class:`ContainmentUnavailable` once closing has begun, :class:`GuardianChanged`
        when *guardian* is no longer the adopted one. Nothing is spawned here."""
        with self._state:
            self._prune_locked()  # children their callers reaped leave the ledger (P5-I-R3: at every admission)
            if not self._admitting:
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
        attached = None
        try:
            if not self._admitting:  # the closing latch, at the last look before the process exists
                raise ContainmentUnavailable(_CLOSING_TEXT)
            if spawn_check is not None:
                spawn_check()
            factory = subprocess.Popen
            if isinstance(factory, type):
                # P5-I-R3 remediation 3 (finding 5): the handle is attached before __init__ runs -- CPython publishes
                # the pid right after fork, before reading the exec error pipe -- so a Popen that raises (or stalls)
                # after creating the process never loses it.
                attached = factory.__new__(factory)
                attached.__init__(argv, **kwargs)
                proc = attached
            else:  # a test's recording stand-in for Popen
                proc = factory(argv, **kwargs)
        except BaseException as exc:
            created = (attached is not None and bool(getattr(attached, "_child_created", False))
                       and isinstance(getattr(attached, "pid", None), int))
            with self._state:
                if created:
                    entry.proc, entry.pid, entry.state = attached, attached.pid, STARTED
                    if entry.kind != CLASS_B:
                        entry.pgid = attached.pid
                else:
                    self._remove_locked(entry)
                if guardian is not None:
                    guardian.spawns -= 1
                self._state.notify_all()
            if created:  # it exists: owned, retired at once (its group, the P5-A way), reported if not confirmed
                entry.start_time = process_start_time(attached.pid)
                self._retire_now([entry], 0.0)
                raise ContainmentUnavailable(f"starting {entry.label} failed after its process was created ({exc}); it "
                                             "was stopped and is still owned until its end is confirmed") from exc
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
                closing = not self._admitting
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
        a child is never dropped while it may still run (v0.8.x P5-I).

        P5-I-R3 remediation 4: a class-B child leaving the ledger has its containment judged first (its guardian found
        gone is recorded as lost now), so :meth:`containment_held` asked afterwards still says so -- never a success
        because the guardian's loss had not been recorded yet when the child was forgotten."""
        if proc.returncode is not None:
            with contextlib.suppress(Exception):
                if not self.containment_held(proc):
                    with self._state:
                        self._lost_procs.add(proc)
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
            # One variable per owner (an owner's class-A child may become an owner itself; both sweeps must find it).
            env[f"{CHILD_TOKEN_ENV}_{self._child_token}"] = "1"  # the guardian's sweep finds it and its descendants
            leader = os.urandom(12).hex()
            env[f"{LEADER_TOKEN_ENV}_{leader}"] = "1"  # its own: end_led_group's sweep finds its descendants
            kw["env"] = env
            kw["_act_leader_token"] = leader
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

    def popen_python(self, argv: Sequence[str], *, label: str = "", run: Any = None, **kwargs) -> subprocess.Popen:
        """Start a registered class-A child (pip in setup; the optional-setup worker in the app). Admitted under the
        owner's state lock, spawned with none held (v0.8.x P5-I)."""
        command = python_argv(argv)
        kw = self.class_a_kwargs(kwargs)
        if self._lifeline:
            # P5-I-R3: the guardian also ends class-A leaders when this owner dies (a leader stopped before its lifeline
            # thread runs cannot end itself). Best effort: without one the leader's own lifeline still applies.
            try:
                self._current_guardian()
            except (ContainmentUnavailable, GuardianChanged) as exc:
                self._note(f"Containment: no ACT guardian for {label or Path(str(argv[0])).name}: {exc}")
        leader_token = kw.pop("_act_leader_token", None)
        entry = self._admit(CLASS_A, label=label or Path(str(argv[0])).name, run=run)
        proc = self._spawn(entry, command, kw)
        proc.act_leader_token = leader_token  # type: ignore[attr-defined]
        proc = self._take_on(entry, proc)
        self._announce_leaders()
        return proc

    # -- closing -----------------------------------------------------------------
    def _refuse_if_closing(self) -> None:
        """Once the orderly end has begun nothing new starts: a worker thread that asks for another program while the
        app is closing gets an error, never a child that the closing owner would no longer see (v0.8.x P1B)."""
        if not self._admitting:
            raise ContainmentUnavailable(_CLOSING_TEXT)

    def _wait_spawns_locked(self, until: float) -> None:
        while any(e.state in (SPAWNING, GRANTING) for e in self._entries):
            remaining = until - time.monotonic()
            if remaining <= 0:
                return
            self._state.wait(remaining)

    def _cut_grants(self) -> None:
        """The orderly end's latch against starts still being granted (P5-I-R3 remediation 3): each one's ``G`` is
        refused if not yet written, taken back if not yet read, its permit removed, and its gate (or the program it
        became) SIGKILLed, identity-checked -- so no program begins executing after the closing latch. A gate that
        cannot be confirmed ended is reported."""
        with self._state:
            launches = [e.launch for e in self._entries if e.state == GRANTING and e.launch is not None]
        for launch in launches:
            with launch.go_lock:
                launch.closing_cut = True
            taken = self._take_back_go(launch)
            _bounded_call(lambda: os.unlink(launch.permit), REVOKE_FS_WAIT_S)
            if not taken and launch.entry.pid:
                self._deliver(launch.entry, signal.SIGKILL)
                if not _wait_exited(launch.entry.pid, KILL_CONFIRM_LAUNCH_S):
                    self._fault(launch.entry, f"the launch gate of {launch.label} (pid {launch.entry.pid}) was being "
                                              "granted when the app began closing and could not be confirmed ended")

    def begin_closing(self) -> None:
        """The orderly end's latch (window close, Cmd+Q, SIGTERM/SIGHUP/SIGINT): from now on nothing new is admitted --
        no child, no guardian, no adoption (v0.8.x P5-I: set under the same lock that admits them). Starts admitted
        before it are waited for at most :data:`START_SETTLE_S`; one still in progress then is stopped as soon as its
        process exists, never registered, and the orderly end sees it in the ledger."""
        self._latch_closing(time.monotonic() + CLOSE_GRANT_WAIT_S)  # never waits out a settle period (finding 5)
        with self._state:
            self._wait_spawns_locked(time.monotonic() + START_SETTLE_S)

    @property
    def closing(self) -> bool:
        return not self._admitting

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
        env[OWNER_ENV] = str(os.getpid())
        env[SWEEP_TOKEN_ENV] = self._child_token
        with contextlib.suppress(ContainmentUnavailable, OSError):
            env[PERMIT_ENV] = self._permit_root()
        ordering = spawn_context if spawn_context is not None else contextlib.nullcontext
        entry: Optional[OwnedChild] = None
        proc: Optional[subprocess.Popen] = None
        adopted = False
        try:
            with ordering():  # the admission alone is ordered against the run's Cancel; the spawn is not held in it
                entry = self._admit(GUARDIAN_KIND, label="guardian", run=self._creating_run)
            try:
                proc = self._spawn(entry, [self._python, "-I", str(GUARDIAN)],
                                   dict(process_group=0, pass_fds=(fd,), env=env, stdin=subprocess.PIPE,
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
                    if not self._admitting:
                        raise ContainmentUnavailable(_CLOSING_TEXT)
                    if entry.state != PENDING:  # it ended (its watch saw it) or was retired by the orderly end
                        raise ContainmentUnavailable("the ACT guardian ended as soon as it was ready; nothing was "
                                                     "started")
                    entry.state = ADOPTED
                    self._current = entry
                    adopted = True
                    self._adopt_registry_locked(proc)
                    self._state.notify_all()
            self._announce_leaders()
        finally:
            if proc is not None and proc.stdout is not None:
                with contextlib.suppress(OSError):
                    proc.stdout.close()
            if not adopted and proc is not None and proc.stdin is not None:
                with contextlib.suppress(OSError):
                    proc.stdin.close()
            if not adopted and entry is not None:
                if proc is None:
                    self._drop_unspawned(entry)
                else:
                    self._retire_now([entry], UNADOPTED_LOOK_S)
        return proc.pid

    def _adopt_registry_locked(self, proc: subprocess.Popen) -> None:
        """The adopted guardian's class-A registry (its stdin) becomes the one leaders are announced on (P5-I-R3).
        Non-blocking: a guardian that stops reading can never hold this owner up."""
        old, self._registry = self._registry, None
        if old is not None:
            with contextlib.suppress(OSError):
                os.close(old)
        if proc.stdin is None:
            return
        try:
            fd = os.dup(proc.stdin.fileno())
            os.set_blocking(fd, False)
        except OSError:
            return
        with contextlib.suppress(OSError):
            proc.stdin.close()
        self._registry = fd
        for entry in self._entries:  # leaders started before this guardian are announced to it
            entry.announced = False

    def _announce_leaders(self) -> None:
        """Tell the guardian every running class-A leader not yet announced to it (pid and kernel start time), so it
        can end them if this owner dies -- even one stopped before its own lifeline could run (P5-I-R3)."""
        with self._state:
            fd = self._registry
            if fd is None:
                return
            todo = [e for e in self._entries if e.kind == CLASS_A and not e.announced and e.start_time is not None
                    and e.proc is not None and e.proc.returncode is None]
            for entry in todo:
                line = f"A {entry.pid} {entry.start_time[0]} {entry.start_time[1]}\n".encode()
                try:
                    os.write(fd, line)
                    entry.announced = True
                except BlockingIOError:
                    self.degraded = True
                    break
                except OSError:
                    break

    def _unannounce_locked(self, entry: "OwnedChild") -> None:
        if entry.kind != CLASS_A or not entry.announced or self._registry is None:
            return
        entry.announced = False
        with contextlib.suppress(OSError):
            os.write(self._registry, f"a {entry.pid}\n".encode())

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
            self._replace_for_leaders()
        self._kick()

    def _replace_for_leaders(self) -> None:
        """P5-I-R3 remediation 3 (finding 6): with class-A children running, a lost guardian is replaced now (off this
        thread), and the running leaders are announced to the new one -- so this owner's death still ends a worker
        that is stopped and cannot act on its own lifeline, and the new guardian's sweep finds their descendants."""
        with self._state:
            wanted = self._lifeline and self._phase == ACTIVE and any(
                e.kind == CLASS_A and e.proc is not None and e.proc.returncode is None for e in self._entries)
        if not wanted:
            return

        def replace() -> None:
            with contextlib.suppress(Exception):  # best effort: the next start replaces it anyway
                self._current_guardian()
                self._announce_leaders()

        with contextlib.suppress(Exception):
            threading.Thread(target=replace, name="act-guardian-replace", daemon=True).start()

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
                if not self._admitting:
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

    # -- class B: the permit-gated launch (v0.8.x P5-I-R3) ---------------------
    def popen_external(self, argv: Sequence[str], *, label: str = "", owner_run: Any = None,
                       ordering: Optional[Callable[[], Any]] = None, checkpoint: Optional[Callable[[], None]] = None,
                       pending: Optional[Callable[[], bool]] = None,
                       cancel_error: Optional[Callable[[], BaseException]] = None, **kwargs) -> subprocess.Popen:
        """Start a contained class-B child: the program runs in the guardian's group, and it begins executing only
        inside *ordering* (a run's counted start, :meth:`JobController.starting`), through a one-time permit that is
        revoked before that counted start ends (v0.8.x P5-I-R3; ``child_launch.py`` documents the gate).

        * *owner_run*: the run the child belongs to (its settlement accounts for it).
        * *ordering*: a zero-argument callable returning the run's Cancel ordering context; ``None`` for a start that
          belongs to no run (it is still ordered against the orderly end).
        * *checkpoint*: called every :data:`CALLER_POLL_S` while this caller waits; raising (a run's Cancel) abandons
          the start -- the caller leaves at once and the owner keeps whatever was created.
        * *pending*: True once a Cancel has been requested and is waiting to latch: an execution not yet confirmed is
          then given at most :data:`EXEC_CUT_S` before its permit is revoked.
        * *cancel_error*: what to raise when a pending Cancel revoked the start (default :class:`LaunchRevoked`).

        Returns the ``Popen`` of the running program (its ``args`` are *argv*). Raises ``FileNotFoundError`` for a
        program that does not exist (nothing is created), :class:`ContainmentUnavailable` when the start could not be
        contained, or what *ordering*/*checkpoint* raise. Whatever was created stays in the ledger until its end is
        confirmed."""
        for key in ("start_new_session", "process_group", "preexec_fn", "executable", "pass_fds"):
            if kwargs.get(key) not in (None, (), False):
                raise ValueError(f"a contained external program cannot be started with {key}=")
        if kwargs.get("shell"):
            raise ValueError("a contained external program cannot be started through a shell")
        if kwargs.get("restore_signals") is False:
            raise ValueError("a contained external program always has its signals restored")
        for key in ("start_new_session", "process_group", "preexec_fn", "executable", "pass_fds", "shell",
                    "restore_signals", "close_fds"):
            kwargs.pop(key, None)
        command = [os.fspath(a) for a in argv]
        program = _resolve_program(command[0], kwargs.get("env"), kwargs.get("cwd"))
        label = label or os.path.basename(command[0])
        self._refuse_if_closing()
        last: Optional[BaseException] = None
        for _attempt in range(LAUNCH_ATTEMPTS):
            self._current_guardian(ordering, checkpoint, owner_run)
            with self._state:
                guardian = self._current
            if guardian is None:
                continue
            try:
                executable, exec_argv = _interpreted(program, command)
                stdio_kwargs, stdio = _own_stdio(kwargs)
                try:
                    entry = self._admit(CLASS_B, label=label, run=owner_run, guardian=guardian)
                except BaseException:
                    _close_fds(stdio)
                    raise
                launch = _Launch(entry=entry, guardian=guardian, program=executable, argv=exec_argv,
                                 kwargs=stdio_kwargs, ordering=ordering, pending=pending, cancel_error=cancel_error,
                                 args=command, stdio=stdio)
                entry.launch = launch
                return self._dispatch(launch, checkpoint)
            except (GuardianChanged, _Relaunch) as exc:
                last = exc
                continue
        raise ContainmentUnavailable(f"{label} could not be started in a contained way ({last}); nothing ran")

    def _dispatch(self, launch: "_Launch", checkpoint: Optional[Callable[[], None]]) -> subprocess.Popen:
        """Run *launch* on its own thread and wait for it here, looking at *checkpoint* and the orderly end every
        :data:`CALLER_POLL_S`. A stalled ``Popen`` therefore never holds this caller past its Cancel: it abandons the
        start and leaves; the launch thread finishes whatever it can and the ledger keeps the rest."""
        try:
            threading.Thread(target=self._launch_thread, args=(launch,), daemon=True,
                             name=f"act-launch:{threading.current_thread().name}").start()
        except BaseException as exc:
            _close_fds(launch.stdio)
            with self._state:
                self._remove_locked(launch.entry)
                launch.guardian.spawns -= 1
            raise ContainmentUnavailable(f"no thread could be started for the launch: {exc}") from exc
        try:
            while not launch.done.wait(CALLER_POLL_S):
                if self._phase != ACTIVE:
                    raise ContainmentUnavailable(_CLOSING_TEXT)
                if checkpoint is not None:
                    checkpoint()
        except BaseException:
            self._abandon(launch)
            raise
        if launch.error is not None:
            raise launch.error
        return launch.result

    def _abandon(self, launch: "_Launch") -> None:
        """Its caller has gone. A launch still in progress refuses to start the program (or, already started, its
        program is retired by the launch thread when it finishes); a finished one's program is retired now."""
        with self._state:
            launch.abandoned = True
            finished = launch.finished
            entry = launch.entry
            if finished and launch.result is not None and entry.state not in (DONE, RETIRING, UNCONFIRMED):
                self._schedule_locked([entry], grace=0.0)
        if finished:
            self._kick()

    def _launch_thread(self, launch: "_Launch") -> None:
        try:
            launch.result = self._launch_steps(launch)
        except BaseException as exc:  # noqa: BLE001 - handed to the caller (or to nobody: the ledger keeps the process)
            launch.error = exc
        finally:
            _close_fds(launch.stdio)
            with launch.go_lock:  # never closed under a take-back that is reading it (finding 8)
                go_w, go_back, launch.go_w, launch.go_back = launch.go_w, launch.go_back, None, None
            for fd in (launch.status_r, launch.status_w, launch.go_r, go_w, go_back):
                if fd is not None:
                    with contextlib.suppress(OSError):
                        os.close(fd)
            if launch.kq is not None:
                with contextlib.suppress(OSError):
                    launch.kq.close()
            for leftover in (launch.permit, launch.environment):  # e.g. a grant refused before its ordering's try
                if leftover:
                    with contextlib.suppress(OSError):
                        os.unlink(leftover)
            with contextlib.suppress(OSError):
                os.rmdir(launch.directory)
            with self._state:
                launch.finished = True
                launch.entry.launch = None
                orphaned = launch.abandoned and launch.result is not None
                if orphaned and launch.entry.state not in (DONE, RETIRING, UNCONFIRMED):
                    self._schedule_locked([launch.entry], grace=0.0)
            if orphaned:
                self._kick()
            launch.done.set()

    def _launch_steps(self, launch: "_Launch") -> subprocess.Popen:
        entry, guardian = launch.entry, launch.guardian
        try:  # P5-I-R3 remediation 8: a failure here (no space, no descriptors) withdraws the admission like any other
            root = self._permit_root()
            launch.directory = os.path.join(root, f"{os.getpid()}-{next(_LAUNCH_TOKENS)}-{os.urandom(6).hex()}")
            os.mkdir(launch.directory, 0o700)  # never reused: a fresh name per launch
            launch.permit = os.path.join(launch.directory, os.path.basename(launch.program))
            launch.environment = os.path.join(launch.directory, ".environment")
            _write_environment(launch.environment, launch.kwargs.get("env"))
            launch.status_r, launch.status_w = os.pipe()
            # A socket pair, not a pipe (remediation 2, finding 4): the owner takes an unread G back with
            # recv(MSG_DONTWAIT) -- a per-call flag, so it never blocks (a fork of another thread's Popen may still hold
            # the writer) and never changes the gate's own descriptor.
            ours, gates = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
            launch.go_w, launch.go_r = ours.detach(), gates.detach()
            launch.go_back = os.dup(launch.go_r)
        except BaseException:
            with self._state:
                guardian.spawns -= 1
                self._remove_locked(entry)
                self._state.notify_all()
            raise
        gate = [self._python, "-I", "-S", str(LAUNCH), str(launch.status_w), str(launch.go_r), launch.permit,
                launch.environment, "--", *launch.argv]
        kw = dict(launch.kwargs, process_group=guardian.pid, close_fds=True, pass_fds=(launch.status_w, launch.go_r))
        factory = subprocess.Popen
        try:
            if isinstance(factory, type):
                proc = factory.__new__(factory)
                launch.proc = proc  # reachable before __init__ returns: _fork_exec publishes its pid before the error pipe
                proc.__init__(gate, **kw)
            else:  # a test's recording stand-in for Popen: called as Popen is (no handle before it returns)
                proc = factory(gate, **kw)
                launch.proc = proc
        except BaseException as exc:
            proc = launch.proc if launch.proc is not None else proc_placeholder()
            created = bool(getattr(proc, "_child_created", False)) and isinstance(getattr(proc, "pid", None), int)
            with self._state:
                guardian.spawns -= 1
                if created:
                    entry.proc, entry.pid, entry.state = proc, proc.pid, STARTED
                else:
                    self._remove_locked(entry)
            if created:  # it exists and nobody may reap it but its Popen: owned, retired, reported if not confirmed
                entry.start_time = process_start_time(proc.pid)
                self._retire_now([entry], 0.0)
                raise ContainmentUnavailable(f"starting {launch.label} failed after its process was created ({exc}); "
                                             "it was stopped and is still owned until its end is confirmed") from exc
            self._kick()
            if self._guardian_gone(guardian):
                raise GuardianChanged(_CHANGED_TEXT) from exc
            raise
        for name in ("status_w", "go_r"):  # the child's ends: only the gate holds them now
            with contextlib.suppress(OSError):
                os.close(getattr(launch, name))
            setattr(launch, name, None)
        _close_fds(launch.stdio)  # the gate has its own copies now
        with self._state:
            entry.proc, entry.pid, entry.state = proc, proc.pid, STARTED
            guardian.spawns -= 1
            self._state.notify_all()
        hello = _read_line(launch.status_r, HELLO_TIMEOUT_S)
        start = process_start_time(proc.pid)
        with self._state:
            entry.start_time = start
        if hello != f"P{proc.pid}" or start is None:
            self._retire_now([entry], 0.0)  # it never got a go: it ends by itself on end-of-file, and is killed
            if self._guardian_gone(guardian):  # its guardian's loss ended it: nothing ran, start again under the next
                raise GuardianChanged(_CHANGED_TEXT)
            raise ContainmentUnavailable(f"the launch gate of {launch.label} did not identify itself; nothing ran")
        launch.kq = _exec_watch(proc.pid)
        try:
            outcome = self._grant(launch)
        except BaseException:
            self._retire_now([entry], 0.0)  # refused or failed before it ran: the gate ends on end-of-file, and is killed
            raise
        if outcome == "exec":
            proc.args = list(launch.args if launch.args is not None else launch.argv)
            try:
                self._register(proc, entry.kind, entry.pgid, entry.label)  # LIVE: its caller runs it from here
            except BaseException:
                self._retire_now([entry], 0.0)  # running and not registered: owned, ended, reported if not confirmed
                raise
            return proc
        self._retire_now([entry], 0.0)
        if outcome.startswith("E") and not launch.revoked_first:
            code = int(outcome[1:] or 0)
            raise OSError(code, os.strerror(code), launch.program)
        if launch.cut:
            raise launch.cancel_error() if launch.cancel_error is not None else LaunchRevoked(
                f"{launch.label} was not started: the start was cancelled before it ran")
        if outcome in ("revoked", "unconfirmed"):
            raise _Relaunch(f"{launch.label} did not begin in time")
        if outcome == "exit" and self._guardian_gone(guardian):  # ended with its lost guardian's group; nothing ran
            raise GuardianChanged(_CHANGED_TEXT)
        raise ContainmentUnavailable(f"the launch gate of {launch.label} ended before it ran the program ({outcome})")

    def _grant(self, launch: "_Launch") -> str:
        """Let the gate execute the program, inside the run's Cancel ordering, and revoke its permit before that ordering
        ends, whatever happens in between. Returns ``exec`` (the program is running), ``E<errno>`` (execve failed),
        ``exit`` (the gate ended first), ``revoked`` (it looked too late), or ``unconfirmed``."""
        entry, guardian = launch.entry, launch.guardian
        ordering = launch.ordering if launch.ordering is not None else contextlib.nullcontext
        # The permit is made before the counted start (P5-I-R3 remediation 3, finding 9): a file-system call that stalls
        # here holds no Cancel latch, and the permit alone runs nothing -- the gate executes only on its G, written only
        # inside the ordering below.
        try:
            os.symlink(launch.program, launch.permit)
        except OSError as exc:
            raise ContainmentUnavailable(f"the start permit of {launch.label} could not be made ({exc}); nothing ran")
        with ordering():
            with self._state:
                if not self._admitting:
                    raise ContainmentUnavailable(_CLOSING_TEXT)
                if launch.abandoned:
                    raise ContainmentUnavailable("its caller left before it ran; nothing ran")
                if guardian is not self._current or guardian.state != ADOPTED:
                    raise GuardianChanged(_CHANGED_TEXT)
                entry.state = GRANTING
            outcome: Optional[str] = None
            try:
                if has_exited(guardian.proc, guardian.start_time):
                    self._guardian_lost(guardian.proc, guardian.generation)
                    raise GuardianChanged(_CHANGED_TEXT)
                with launch.go_lock:  # a one-byte write to an empty pipe: never blocks
                    # The closing latch looked at under go_lock (remediation 3, finding 7): once the orderly end is
                    # pending no G is written; one written before it is waited for before CLOSING is published.
                    if launch.closing_cut or launch.go_w is None or not self._admitting:
                        raise ContainmentUnavailable(_CLOSING_TEXT)
                    try:
                        os.write(launch.go_w, b"G")
                    except OSError:
                        outcome = "exit"  # the gate is gone (EPIPE)
                if outcome is None:
                    outcome = self._exec_outcome(launch, EXEC_WAIT_S, cut=True)
            finally:
                launch.revoked = self._revoke(launch)  # every path out, exceptions included
                if outcome is None:
                    launch.revoked_first = True
                    outcome = self._exec_outcome(launch, POST_REVOKE_S, cut=False)
                    if outcome is not None and outcome.startswith("E"):
                        outcome = "revoked"
                if outcome is None or not launch.revoked:
                    # Neither ran nor ended: the gate is stopped or starved. It is killed (identity-checked) and its end
                    # looked for, inside the ordering; whatever is not confirmed stays owned and is reported.
                    self._deliver(entry, signal.SIGKILL)
                    if _wait_exited(entry.pid, KILL_CONFIRM_LAUNCH_S):
                        outcome = outcome or "exit"
                    else:
                        if outcome is None and not launch.go_taken_back:
                            self._fault(entry, f"the launch gate of {launch.label} (pid {entry.pid}) was neither seen "
                                               "to execute nor confirmed ended inside its run's ordering")
                        outcome = outcome or "unconfirmed"
                self._take_back_go(launch)  # closes the write end in every case
                with self._state:
                    if entry.state == GRANTING:
                        entry.state = STARTED
                    self._state.notify_all()
        return outcome

    def _exec_outcome(self, launch: "_Launch", wait_s: float, *, cut: bool) -> Optional[str]:
        """Evidence of what the gate did: ``exec`` (kqueue ``NOTE_EXEC``, or the status pipe closed by a successful
        exec while the process lives), ``E<errno>``, ``exit``; None when nothing was seen within *wait_s*. With *cut*,
        the wait shrinks to :data:`EXEC_CUT_S` once a Cancel is pending, the owner is closing, or the caller left."""
        now = time.monotonic()
        until = now + max(0.0, wait_s)
        shortened = False
        buffer = b""
        while True:
            if cut and not shortened and (not self._admitting or launch.abandoned
                                          or (launch.pending is not None and _asks(launch.pending))):
                shortened = launch.cut = True
                until = min(until, time.monotonic() + EXEC_CUT_S)
            if launch.kq is not None:
                try:
                    for event in launch.kq.control(None, 4, 0):
                        if event.fflags & select.KQ_NOTE_EXEC:
                            return "exec"
                        if event.fflags & select.KQ_NOTE_EXIT:
                            launch.exited = True
                except OSError:
                    launch.kq = None
            try:
                ready = [] if launch.status_eof else ([launch.status_r] if _readable(launch.status_r, 0) else [])
            except (OSError, ValueError):
                ready = []
            if ready:
                try:
                    block = os.read(launch.status_r, 64)
                except OSError:
                    block = b""
                if block:
                    buffer += block
                    if buffer.startswith(b"E") and buffer.endswith(b"\n"):
                        return buffer.strip().decode("ascii", "replace")
                elif launch.kq is None:
                    # No kqueue: end-of-file from close-on-exec, with the process still there a moment later, is the
                    # evidence (a gate that is dying also closes it, so it is looked at again first).
                    time.sleep(EXEC_LOOK_S)
                    if has_exited(launch.entry.proc):
                        launch.exited = True
                    else:
                        return "exec"
                else:
                    launch.status_eof = True
            if launch.exited:
                return "exit"
            remaining = until - time.monotonic()
            if remaining <= 0:
                return None
            time.sleep(min(EXEC_LOOK_S, remaining))

    @staticmethod
    def _take_back_go(launch: "_Launch") -> bool:
        """Close the owner's write end of the go pipe, then read what is left in it through the owner's own copy of the
        read end: ``G`` back means the gate never read it -- it gets end-of-file and exits without executing anything,
        whatever state it is in (stopped, starved). Never blocks (no writer is left). Idempotent."""
        with launch.go_lock:
            go_w, launch.go_w = launch.go_w, None
            if go_w is not None:
                with contextlib.suppress(OSError):
                    os.close(go_w)
            # Duplicated under go_lock, which the launch thread holds to close it (remediation 3, finding 8): the number
            # is never looked at after the launch closed it -- it could by then name an unrelated descriptor.
            back = launch.go_back
            if back is None or launch.go_taken_back:
                return launch.go_taken_back
            try:
                back = os.dup(back)
            except OSError:
                return False
        try:
            reader = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM, fileno=back)
        except OSError:
            with contextlib.suppress(OSError):
                os.close(back)
            return False
        try:
            taken = reader.recv(1, socket.MSG_DONTWAIT) == b"G"
        except (BlockingIOError, InterruptedError):
            taken = False  # nothing unread (the gate has it), and some process still holds the writer
        except OSError:
            taken = False
        finally:
            reader.close()
        if taken:
            launch.go_taken_back = True
        return taken

    def _revoke(self, launch: "_Launch") -> bool:
        """Make the permit unusable before the counted start ends, and confirm it. In order: the ``G`` not yet read is
        taken back (definitive, P5-I-R3 remediation 1); the permit is removed and confirmed gone (``lstat``); if the
        file system refuses, the folder is renamed aside, then made unsearchable (``chmod 000``: a lookup through it
        fails); if all of that is refused, the gate is killed and the revocation counts only once it is seen ended.
        Held at most :data:`REVOKE_HOLD_S` (the counted start, and so the Cancel latch, waits for it); False when
        nothing could be established -- the run's start is then recorded as uncontained and reported."""
        until = time.monotonic() + REVOKE_HOLD_S
        taken = self._take_back_go(launch)
        # File-system steps run on their own thread, waited for only until the hold ends (finding 9): a stalled call
        # (network home, slow disk) cannot hold the Cancel latch; the kill below needs no file system.
        finished, unusable = _bounded_call(lambda: self._make_permit_unusable(launch),
                                           REVOKE_FS_WAIT_S if taken
                                           else max(0.0, until - time.monotonic() - KILL_CONFIRM_LAUNCH_S))
        if taken or (finished and unusable):
            return True  # taken back: the gate never got its go and can execute nothing, permit or not
        while True:
            self._deliver(launch.entry, signal.SIGKILL)
            if launch.entry.pid and _has_exited(launch.entry.pid):
                launch.unrevoked_but_dead = True
                return True
            if time.monotonic() >= until:
                self._fault(launch.entry, f"the start permit of {launch.label} (pid {launch.entry.pid}) could not be "
                                          "revoked and its gate could not be confirmed ended: the start is uncontained")
                return False
            time.sleep(0.01)

    @staticmethod
    def _make_permit_unusable(launch: "_Launch") -> bool:
        """The permit removed and confirmed gone (``lstat``); if refused, its folder renamed aside, then made
        unsearchable (``chmod 000``). True once no lookup of the permit can succeed."""
        moved = locked = False
        while True:
            with contextlib.suppress(FileNotFoundError, OSError):
                os.unlink(launch.permit)
            try:
                os.lstat(launch.permit)
            except FileNotFoundError:
                return True
            except OSError:
                if locked:
                    return True  # the folder is unsearchable: no lookup of the permit can succeed
            if not moved:
                with contextlib.suppress(OSError):
                    os.rename(launch.directory, launch.directory + ".revoked")
                    launch.directory += ".revoked"
                    launch.permit = os.path.join(launch.directory, os.path.basename(launch.permit))
                    moved = True
                    continue
            if not locked:
                with contextlib.suppress(OSError):
                    os.chmod(launch.directory, 0)
                    locked = not os.access(launch.directory, os.X_OK)
                    if locked:
                        continue
            return False

    def _fault(self, entry: "OwnedChild", text: str) -> None:
        """Record a start of *entry*'s run that could not be kept inside its ordering (P5-I-R3 remediation 1): the run
        is reported FAILED with this text whatever happens to the process afterwards (:meth:`faults`)."""
        entry.exec_unknown = True
        with self._state:
            self._faults.append((entry.run, text))
        self._note(f"Containment: {text}.")

    def faults(self, run: Any) -> list[str]:
        """What could not be kept contained for *run* (uncontained starts), kept after the processes are gone."""
        if run is None:
            return []
        with self._state:
            return [text for owner_run, text in self._faults if owner_run == run]

    def _permit_root(self) -> str:
        """This owner's private folder of start permits (0700, every component checked to be a real folder owned by
        this account): ``<temp>/ACT-permits-<uid>/<pid>-<start sec>-<start usec>``. Created once; the guardian removes
        it when the owner dies, :meth:`shutdown` when it closes."""
        with self._state:
            if self._permits is not None:
                return self._permits
        base = os.path.join(os.path.realpath(tempfile.gettempdir()), f"ACT-permits-{os.getuid()}")
        with contextlib.suppress(FileExistsError):
            os.mkdir(base, 0o700)
        info = os.lstat(base)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise ContainmentUnavailable(f"the start-permit folder {base} is not a private folder of this account")
        own = process_start_time(os.getpid()) or (0, 0)
        root = os.path.join(base, f"{os.getpid()}-{own[0]}-{own[1]}")
        with contextlib.suppress(FileExistsError):
            os.mkdir(root, 0o700)
        info = os.lstat(root)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise ContainmentUnavailable(f"the start-permit folder {root} is not a private folder of this account")
        with self._state:
            if self._permits is None:
                self._permits = root
            return self._permits

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
        if entry.start_time is None and entry.proc is not None and entry.proc.returncode is None:
            entry.start_time = process_start_time(entry.pid)  # read again now (remediation 2, finding 11)
        if entry.start_time is not None:
            return _signal_proved(entry, sig, wait_s=RETIRE_LOCK_WAIT_S)
        # Identity still unreadable: the process only, through its own Popen under its waitpid lock with it unreaped --
        # the kernel reserves an unreaped child's id, so no other process can carry it (the bpo-38630 guard).
        return _signal_own(entry.proc, sig)

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
                if entry.kind == CLASS_A:
                    # P5-I-R3 remediation 7: the guardian hears it is no longer a leader to end BEFORE its id is freed.
                    with self._state:
                        self._unannounce_locked(entry)
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

    def _await(self, entries: Sequence[OwnedChild], until: float, *, patient: bool = False) -> list[OwnedChild]:
        """Drive retirement until every one of *entries* is confirmed ended, or *until* passes, or every one left is past
        its own deadline. Returns those not confirmed. Bounded by *until*. *patient* (P5-I-R3: an explicit stop of a
        child already UNCONFIRMED, a run's settlement): every child is looked at -- and killed again -- until *until*,
        never given up earlier because its own confirmation deadline passed."""
        while True:
            self._retire_step()
            now = time.monotonic()
            notes: list[str] = []
            with self._state:
                left = [e for e in entries if not e.resolved()]
                done = (not left or now >= until
                        or (not patient and all(e.state == UNCONFIRMED
                                                or (e.confirm_by is not None and now >= e.confirm_by)
                                                for e in left)))
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
            until = max([e.confirm_by for e in entries if e.confirm_by is not None and e.state == RETIRING],
                        default=time.monotonic())
            # P5-I-R3: one already UNCONFIRMED (its deadline passed earlier) gets this request's own bounded look.
            again = [e for e in entries if e.state == UNCONFIRMED]
            if again:
                until = max(until, time.monotonic() + max(0.0, grace) + KILL_CONFIRM_S)
        self._kick()
        return self._await(entries, until=until, patient=bool(again))

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
        if child is None:
            return False
        # P5-I-R3: the check and the signal under one waitpid lock (a reap between them can no longer hand the id on).
        return _signal_proved(child, signal.SIGKILL, wait_s=RETIRE_LOCK_WAIT_S)

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
        # P5-I-R3 remediation 6: retirement is driven (and SIGKILL repeated) until the run's own bound, never given up
        # earlier because one entry's internal confirmation deadline passed.
        left = self._await(mine, until=until, patient=True)
        return sorted({e.pid or -1 for e in left})

    # -- orderly shutdown ---------------------------------------------------------
    def shutdown(self, deadline: Optional[float] = None) -> list[int]:
        """Orderly end, bounded by :data:`SHUTDOWN_BOUND_S` from its call, every wait against that one deadline (v0.8.x
        P5-I): nothing new is admitted; starts in progress get at most :data:`START_SETTLE_S`; every process in the
        ledger but the adopted guardian -- children, guardians never adopted, children whose registration failed, a
        lost guardian's children -- is retired as one batch (SIGTERM, one shared grace, SIGKILL), confirmed by the
        deadline less :data:`GUARDIAN_END_S`; then the lifeline is closed (the guardian ends its group and itself) and
        the guardian reaped, SIGKILLed with its group (proved) if it has not ended in time. Returns the pids NOT
        confirmed ended (recorded in :attr:`events`); they stay in the ledger. Crash containment never depends on this.

        *deadline* (``time.monotonic``; v0.8.x P5-I-R3): the orderly end's own deadline, started at the close request;
        never waited past, even when what came before it used most of it (what is left is then SIGKILLed at once)."""
        began = time.monotonic()
        deadline = began + SHUTDOWN_BOUND_S if deadline is None else min(began + SHUTDOWN_BOUND_S, deadline)
        children_by = deadline - GUARDIAN_END_S
        self._latch_closing(min(children_by, began + CLOSE_GRANT_WAIT_S))  # before any settle wait (finding 5)
        with self._state:
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
            permits, self._permits = self._permits, None
            registry, self._registry = self._registry, None
        if registry is not None:
            with contextlib.suppress(OSError):
                os.close(registry)
        if permits is not None:
            shutil.rmtree(permits, ignore_errors=True)
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
