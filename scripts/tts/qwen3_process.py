"""qwen3_process.py — start a child process so that it, and everything it starts, can always be stopped.

The Qwen3 worker runs under the engine's own environment. On Windows that environment's ``python.exe`` is a small *launcher* that
starts the real interpreter as a child. Killing only the launcher leaves inference (and GPU memory) running, and
``taskkill /T`` cannot find the child once the launcher has exited, because the tree is discovered through the parent
link. So the worker is started **suspended**, placed in a Windows *Job Object* configured to kill every member when it
is closed, and only then allowed to run. From that moment every descendant is a member, whatever happens to its
parent, and ``TerminateJobObject`` stops all of them at once. If the Job Object cannot be created the worker is simply
started without one and the older ``taskkill /T`` route remains.

Other platforms get a new process group instead (the Qwen3 voices are Windows-only for now; this keeps the module
honest if that changes).
"""

from __future__ import annotations

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
        proc = subprocess_utils.popen(cmd, start_new_session=True, **kwargs)
        proc.act_job = None  # type: ignore[attr-defined]
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


def kill_tree(proc: subprocess.Popen, wait_s: float = 15.0) -> None:
    """Stop the process and every descendant, whether or not the process itself is still running."""
    job: Optional[ProcessJob] = getattr(proc, "act_job", None)
    if job is not None:
        job.terminate()
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
