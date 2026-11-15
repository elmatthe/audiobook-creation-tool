"""child_ownership.py -- POSIX ownership and parent-death containment of ACT's child processes (v0.8.x P1A).

Windows ends a setup's or the app's children through Job Objects (kill-on-close). macOS has no such object and no
``PR_SET_PDEATHSIG``, and ``atexit`` does not run when a process is SIGKILLed, crashes, is force-quit or loses its
Terminal window. This module is the macOS mechanism (plan section 11.2.2). A process that starts children is their
*owner* (in P1A: the setup process, ``bootstrap.py``) and holds one :class:`Owner`.

**Class A -- ACT-authored Python children** (pip with its build backends, ``python -m venv``, setup probes and proofs).
Each leads its own process group (``start_new_session``) and starts through ``child_entry.py``, whose first statements
start a thread blocked on the read end of the owner's *lifeline* pipe. The write end exists only in the owner: it is
non-inheritable (PEP 446), never passed to a child, and the owner never forks without exec. When the owner is gone --
however it went -- the kernel closes the write end, the read returns end-of-file, and the thread ends the child's whole
group.

**Class B -- third-party executables** (``codesign`` here; FFmpeg in the GUI owner, P1B). They cannot run that thread,
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

**Deliberately detached children** (class D: the GUI started by setup, the Finder ``open``, ``close_terminal.py``) do
not come here; ``files/tests`` pins that list.

Standard library only: bootstrap runs it on the app's base Python before the environment exists. Nothing here is used
on Windows; :func:`supported` is False there and the Windows spawn paths are unchanged.
"""

from __future__ import annotations

import os
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

    def run_python(self, argv: Sequence[str], **kwargs) -> subprocess.CompletedProcess:
        """``subprocess.run`` of an ACT-authored Python child, contained. Used for bounded single-process probes,
        proofs and ``-m venv``; a timeout ends the child as ``subprocess.run`` does, and the owner's exit ends it and
        everything it started through the lifeline."""
        return subprocess.run(python_argv(argv), **self.class_a_kwargs(kwargs))

    def popen_python(self, argv: Sequence[str], *, label: str = "", **kwargs) -> subprocess.Popen:
        """Start a registered class-A child (pip)."""
        proc = subprocess.Popen(python_argv(argv), **self.class_a_kwargs(kwargs))
        self._register(proc, CLASS_A, proc.pid, label or Path(str(argv[0])).name)
        return proc

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

    def popen_external(self, argv: Sequence[str], *, label: str = "", **kwargs) -> subprocess.Popen:
        """Start a registered class-B child inside the guardian's group. Raises :class:`ContainmentUnavailable`
        (nothing started) when no guardian can be had."""
        if "start_new_session" in kwargs or "process_group" in kwargs:
            raise ValueError("a class-B child always joins the guardian's group")
        with self._lock:
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
        for child in [c for c in self.children() if c.running()]:
            remaining = deadline - time.monotonic()
            self._end(child, grace=min(TERM_GRACE_S, max(0.0, remaining - 1.0)))
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
