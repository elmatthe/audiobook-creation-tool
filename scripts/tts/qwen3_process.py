"""qwen3_process.py — start a child process so that it, and everything it starts, can always be stopped.

The Qwen3 worker runs under the engine's own environment. On Windows that environment's ``python.exe`` is a small *launcher* that
starts the real interpreter as a child. Killing only the launcher leaves inference (and GPU memory) running, and
``taskkill /T`` cannot find the child once the launcher has exited, because the tree is discovered through the parent
link. So the worker is started **suspended**, placed in a Windows *Job Object* configured to kill every member when it
is closed, and only then allowed to run. From that moment every descendant is a member, whatever happens to its
parent, and ``TerminateJobObject`` stops all of them at once. If the Job Object cannot be created the worker is simply
started without one and the older ``taskkill /T`` route remains.

Other platforms get a new process group instead (the Qwen3 voices are Windows-only for now; this keeps the module
honest if that changes). On macOS (v0.8.x P1B) an ACT Python child of the app window, or of one of its own class-A
children, is started through its owner (``shared.child_ownership``): its own group, tied to the owner's lifeline.

**A leader's exit proves nothing about its group** (v0.8.x P5-D, POSIX). A worker can exit -- normally, on Cancel, or
by crashing -- while something it started in its group runs on, and can still hold its output open. So a process
started here carries the kernel start time recorded at spawn (``act_start_time``), its group is ended while its id is
proved its own (``child_ownership.end_led_group``: waitpid lock held, unreaped, same start time, signalled until the
kernel says nothing is left), and only then is it reaped. Nothing here polls it first: a ``poll()`` that reaps a leader
which has already exited loses the only proof of its group's id.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import signal
import subprocess
import sys
from ctypes import wintypes
from typing import Optional

from shared import subprocess_utils

CREATE_SUSPENDED = 0x00000004
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_TERMINATE_EXIT_CODE = 1


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimits), ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


_JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION_CLASS = 1


class _BasicAccounting(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_int64), ("TotalKernelTime", ctypes.c_int64),
        ("ThisPeriodTotalUserTime", ctypes.c_int64), ("ThisPeriodTotalKernelTime", ctypes.c_int64),
        ("TotalPageFaultCount", wintypes.DWORD), ("TotalProcesses", wintypes.DWORD),
        ("ActiveProcesses", wintypes.DWORD), ("TotalTerminatedProcesses", wintypes.DWORD)]


def _kernel32():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateJobObjectW.restype = wintypes.HANDLE
    k.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    k.SetInformationJobObject.restype = wintypes.BOOL
    k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k.AssignProcessToJobObject.restype = wintypes.BOOL
    k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k.TerminateJobObject.restype = wintypes.BOOL
    k.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    k.QueryInformationJobObject.restype = wintypes.BOOL
    k.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                            ctypes.POINTER(wintypes.DWORD)]
    k.CloseHandle.restype = wintypes.BOOL
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    return k


class ProcessJob:
    """A Windows Job Object that kills all of its members when terminated or closed."""

    def __init__(self) -> None:
        self._k = _kernel32()
        self.handle = self._k.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self._k.SetInformationJobObject(self.handle, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                                               ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.get_last_error()
            self.close()
            raise OSError(error, "SetInformationJobObject failed")

    def assign(self, proc: subprocess.Popen) -> None:
        if not self._k.AssignProcessToJobObject(self.handle, int(proc._handle)):  # type: ignore[attr-defined]
            raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject failed")

    def terminate(self) -> None:
        if self.handle:
            self._k.TerminateJobObject(self.handle, _TERMINATE_EXIT_CODE)

    def accounting(self) -> tuple[int, int]:
        """``(members alive now, members ever)``: how a caller confirms that ending the job really ended everything."""
        if not self.handle:
            raise OSError("the job is already closed")
        info = _BasicAccounting()
        if not self._k.QueryInformationJobObject(self.handle, _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION_CLASS,
                                                 ctypes.byref(info), ctypes.sizeof(info), None):
            raise OSError(ctypes.get_last_error(), "QueryInformationJobObject failed")
        return int(info.ActiveProcesses), int(info.TotalProcesses)

    def close(self) -> None:
        """Closing the last handle kills any member still alive (KILL_ON_JOB_CLOSE)."""
        if self.handle:
            self._k.CloseHandle(self.handle)
            self.handle = None


def _resume(proc: subprocess.Popen) -> None:
    ntdll = ctypes.WinDLL("ntdll")
    ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
    ntdll.NtResumeProcess(int(proc._handle))  # type: ignore[attr-defined]


class ContainmentUnavailable(RuntimeError):
    """The process could not be placed under the app's control, so it was never allowed to run."""


#: The thread ``shared/child_entry.py`` starts in a class-A child to watch its owner's lifeline.
_LIFELINE_THREAD = "act-lifeline"


def _under_a_lifeline() -> bool:
    """True in a class-A child: a process whose own end is tied to its owner's (macOS)."""
    import threading

    return any(thread.name == _LIFELINE_THREAD for thread in threading.enumerate())


def _posix_owner(cmd: list):
    """The containment owner to start the Python program *cmd* under, or ``None`` to start it as before (POSIX).

    The app window is an owner (``subprocess_utils.enable_containment``). A class-A child becomes one the first time it
    starts an ACT Python child of its own, so that child is tied to it in turn. Anything else -- a program that is not
    Python, a process that is neither -- starts in a new process group as before."""
    if not os.path.basename(str(cmd[0])).lower().startswith("python"):
        return None
    owner = subprocess_utils.containment_owner()
    if owner is None and _under_a_lifeline():
        owner = subprocess_utils.enable_containment()
    return owner


def spawn(cmd: list, *, require_job: bool = False, **kwargs) -> subprocess.Popen:
    """``subprocess.Popen`` (hidden console) that returns a process whose whole tree can be stopped.

    The returned object carries the job as ``proc.act_job`` (``None`` when there is none). Pass it to
    :func:`kill_tree` to stop everything and :func:`release` once the run is over.

    ``require_job=True`` is for commands that start children of their own (the Qwen3 worker's launcher, pip): if
    containment cannot be established the command is **not run** -- a process that was created suspended is killed
    before it executes a single instruction -- and :class:`ContainmentUnavailable` is raised, because an uncontained
    worker could outlive a Cancel and keep the GPU. A single-process command such as ffmpeg may go without.
    """
    if sys.platform != "win32":
        owner = _posix_owner(cmd)
        if owner is not None:
            # v0.8.x P1B (plan section 11.2.2): an ACT-authored Python child of the app window (the optional-setup
            # worker), or of such a child (the pip and the probes that worker runs), is class A -- its own process
            # group, started through ``child_entry.py`` whose first statements watch its owner's lifeline, so it and
            # everything it started end with its owner however the owner ends; the window's end therefore reaches
            # the worker's pip through the worker. Once the window is closing nothing new starts.
            try:
                proc = owner.popen_python([str(part) for part in cmd], label=os.path.basename(str(cmd[0])),
                                          **kwargs)
            except RuntimeError as exc:
                if type(exc).__name__ != "ContainmentUnavailable":
                    raise
                raise ContainmentUnavailable(str(exc)) from exc
        else:
            proc = subprocess_utils.popen(cmd, start_new_session=True, **kwargs)
        proc.act_job = None  # type: ignore[attr-defined]
        proc.act_start_time = leader_start_time(proc, owner)  # type: ignore[attr-defined]
        return proc
    job: Optional[ProcessJob] = None
    try:
        job = ProcessJob()
    except OSError as exc:
        if require_job:
            raise ContainmentUnavailable(f"a Windows Job Object could not be created ({exc})") from exc
    flags = kwargs.pop("creationflags", 0) | subprocess.CREATE_NO_WINDOW | (CREATE_SUSPENDED if job else 0)
    try:
        proc = subprocess_utils.popen(cmd, creationflags=flags, **kwargs)
    except BaseException:
        if job is not None:
            job.close()  # the job handle must not outlive a launch that never happened
        raise
    if job is not None:
        try:
            job.assign(proc)
        except OSError as exc:
            job.close()
            job = None
            if require_job:
                proc.kill()  # still suspended: it has not run a single instruction
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:  # pragma: no cover
                    pass
                raise ContainmentUnavailable(
                    f"the process could not be placed under the app's control ({exc})") from exc
        _resume(proc)  # a process left suspended would hang the caller
    proc.act_job = job  # type: ignore[attr-defined]
    return proc


#: POSIX (v0.8.x P5-D): how long ending a group may take before it counts as not confirmed ended. A SIGKILLed group is
#: empty within milliseconds; the bound keeps a caller's own stop bound (OmniVoice's 4 s Cancel) honest when it is not.
GROUP_END_BOUND_S = 1.5


def leader_start_time(proc: subprocess.Popen, owner=None) -> Optional[tuple[int, int]]:
    """POSIX: the kernel start time of *proc*, just started by :func:`spawn` as the leader of its own process group --
    the one its owner recorded, or read now (nobody can have reaped it yet, so its id is still its own)."""
    from shared import child_ownership

    child = owner.child(proc) if owner is not None else None
    if child is not None and child.start_time is not None:
        return child.start_time
    return child_ownership.process_start_time(proc.pid)


def leads_proved_group(proc: subprocess.Popen) -> bool:
    """True for a POSIX process :func:`spawn` started as the leader of its own group, its start time recorded: its group
    can be ended -- whether or not it is still running -- until it is reaped (v0.8.x P5-D)."""
    return sys.platform != "win32" and isinstance(getattr(proc, "act_start_time", None), tuple)


def _spawned_on_posix(proc: subprocess.Popen) -> bool:
    """True for a POSIX process :func:`spawn` (or a caller recording its identity the same way) started as the leader of
    its own group -- whether or not its start time could be recorded (``act_start_time`` present, perhaps None)."""
    return sys.platform != "win32" and hasattr(proc, "act_start_time")


def identity_unrecorded(proc: subprocess.Popen) -> bool:
    """POSIX (v0.8.x P5-D-R1): True for a process started as the leader of its own group whose kernel start time could
    not be recorded at spawn. Its group can never be proved its own, so it can neither be ended on Cancel nor retired
    before it is reaped: a caller never admits it (:func:`end_unadmitted`). A process started any other way (Windows; a
    test's own ``Popen``) carries no ``act_start_time`` and is not this."""
    return _spawned_on_posix(proc) and not leads_proved_group(proc)


#: POSIX (v0.8.x P5-D-R1): how long a refused process may take to be reaped once it has been killed.
UNADMITTED_REAP_S = 1.0


def end_unadmitted(proc: subprocess.Popen, bound_s: float = UNADMITTED_REAP_S) -> None:
    """POSIX (v0.8.x P5-D-R1): end a process just started that is not admitted (:func:`identity_unrecorded`).

    Its group is NEVER signalled: that needs the proof it lacks. The leader alone is killed through ``Popen``'s own
    guarded ``kill`` -- delivered only while ``poll()`` finds it this process's own unexited child -- before it has run
    anything of its program, then reaped (bounded) and its pipes closed (no reader was started). Never raises."""
    with contextlib.suppress(OSError):
        proc.kill()
    with contextlib.suppress(subprocess.TimeoutExpired, ChildProcessError):
        proc.wait(timeout=bound_s)
    for stream in (proc.stdin, proc.stdout, proc.stderr):
        with contextlib.suppress(OSError, ValueError, AttributeError):
            if stream is not None:
                stream.close()


def leader_exited(proc: subprocess.Popen) -> bool:
    """POSIX: True once *proc* has exited -- observed, NEVER reaped, so its id and its group's stay reserved."""
    from shared import child_ownership

    return child_ownership.has_exited(proc, proc.act_start_time)  # type: ignore[attr-defined]


def end_group(proc: subprocess.Popen, bound_s: float = GROUP_END_BOUND_S) -> str:
    """POSIX (v0.8.x P5-D): SIGKILL every process in the group *proc* leads and confirm that none is left -- only while
    its id is proved *proc*'s own (``child_ownership.end_led_group``). Never reaps; never raises. The answer
    (``child_ownership.GROUP_*``) is kept as ``proc.act_group_end``; once *proc* has been reaped the group can no longer
    be ended, and the answer given before stands (none at all: ``GROUP_UNPROVED``)."""
    from shared import child_ownership

    if proc.returncode is None:
        proc.act_group_end = child_ownership.end_led_group(  # type: ignore[attr-defined]
            proc, proc.act_start_time, bound_s=bound_s)  # type: ignore[attr-defined]
    return getattr(proc, "act_group_end", None) or child_ownership.GROUP_UNPROVED


def containment_problem(proc: subprocess.Popen, *, output_open: bool = False) -> Optional[str]:
    """POSIX: why nothing can vouch that *proc* and everything in its group have ended, or None when its group was
    confirmed ended (:func:`end_group`), its output reached its end and it was reaped (``child_ownership.Retired``)."""
    from shared import child_ownership

    group = getattr(proc, "act_group_end", None) or child_ownership.GROUP_UNPROVED
    return child_ownership.Retired(returncode=proc.returncode, group=group, output_open=output_open).problem()


def kill_tree(proc: subprocess.Popen, wait_s: float = 15.0) -> None:
    """Stop the process and every descendant, whether or not the process itself is still running.

    POSIX, for a process :func:`spawn` started (v0.8.x P5-D): its group is ended while its id is proved its own
    (:func:`end_group`), then it is reaped; it is never polled first. One whose start time was not recorded never falls
    back to the older ``poll()``/``killpg()`` route (v0.8.x P5-D-R1): nothing is signalled (``GROUP_UNPROVED``)."""
    job: Optional[ProcessJob] = getattr(proc, "act_job", None)
    if job is not None:
        job.terminate()
    elif _spawned_on_posix(proc):
        end_group(proc, min(wait_s, GROUP_END_BOUND_S))
    elif proc.poll() is None:
        if sys.platform == "win32":
            subprocess_utils.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        else:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
    try:
        proc.wait(timeout=wait_s)
    except subprocess.TimeoutExpired:  # pragma: no cover - the OS refused; nothing more can be done from here
        pass


def release(proc: subprocess.Popen) -> None:
    """End-of-run cleanup: close the job (which kills any straggler) and forget it."""
    job: Optional[ProcessJob] = getattr(proc, "act_job", None)
    if job is not None:
        job.close()
        proc.act_job = None  # type: ignore[attr-defined]
