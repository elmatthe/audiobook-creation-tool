"""Launching owned child processes for the gate: the Windows error mode, a kill-on-close Job Object, bounded supervision.

**The error mode.** The suite's ``pinned_ffmpeg`` fixture holds a deliberately invalid ``ffmpeg.exe``. Starting it with
SEM_FAILCRITICALERRORS clear makes Windows raise a modal "Unsupported 16-Bit Application" box and holds the calling thread
until someone answers (v0.7.2 Phase 1 lost 441.9 s and 2,343.6 s to it). With the flag set the same start fails at once
with WinError 216, which is what the suite expects. A child inherits its parent's mode unless a launcher resets it, so the
gate sets the mode on itself before it starts anything and then checks it in a real child rather than assuming it. Only
this process's own mode is touched: no registry, no machine setting.

**Why the mode is checked again during a run.** The error mode is one word for the whole process, with no atomic update,
and ordinary calls save and restore it. Measured here (v0.7.2 Phase 2, a watcher polling GetErrorMode with every thread's
stack): process creation goes through 0x8001 even on one thread, and CPython's extension-module loader through 0x1. Each is
harmless alone, but calls overlapping on two threads can restore each other's transient value, and then it stays: the
eight-worker assembly test ended its process at 0x8001 in 7 of 14 runs, which is the transition seen in a Phase 1 gate. All
of about 10,000 observed changes kept SEM_FAILCRITICALERRORS, so the invalid executable stays harmless. What goes is the
crash-dialog flag: a native crash in a child then goes through Windows Error Reporting, 1.5 to 2 s against 0.03 s here,
without holding the run on this machine. ``gate_session_probe`` therefore re-raises the flags at every test boundary and
records each drift; the gate treats a lost SEM_FAILCRITICALERRORS as a failure, and its stall limit bounds whatever else
could hold a child. JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION was tried and is not used: it changed neither the mode a
child reads nor the time a crash took.

**Ownership.** A child starts suspended and is assigned to the job before its first instruction, so nothing it starts can
escape; the venv's ``python.exe`` is a launcher stub whose real interpreter is a grandchild, which is why this matters.
Output goes straight to a file, never through a pipe, so a grandchild holding the handle open cannot block the gate. Nothing
is ever killed by name: only processes in this job, or on POSIX this process group.
"""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"

SEM_FAILCRITICALERRORS = 0x0001
SEM_NOGPFAULTERRORBOX = 0x0002
SEM_NOOPENFILEERRORBOX = 0x8000
REQUIRED_ERROR_MODE = SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX

CREATE_SUSPENDED = 0x00000004
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JobObjectBasicProcessIdList = 3
_JobObjectExtendedLimitInformation = 9
#: Exit status of everything a stop ends, so a stopped tree can be told from one that failed by itself.
STOPPED_EXIT_CODE = 0xAC70


def error_mode() -> int | None:
    """This process's error mode, or None where the concept does not exist."""
    if not IS_WINDOWS:
        return None
    return int(ctypes.WinDLL("kernel32").GetErrorMode())


def establish_error_mode() -> dict:
    """Raise the required flags on this process, keeping any already set, and say what was found and what holds now."""
    if not IS_WINDOWS:
        return {"applicable": False}
    kernel32 = ctypes.WinDLL("kernel32")
    before = int(kernel32.GetErrorMode())
    kernel32.SetErrorMode(before | REQUIRED_ERROR_MODE)
    after = int(kernel32.GetErrorMode())
    return {"applicable": True, "found": hex(before), "established": hex(after),
            "ok": after & REQUIRED_ERROR_MODE == REQUIRED_ERROR_MODE}


def interactive_desktop() -> bool | None:
    """Whether this process can open the input desktop: False on a locked or service session, None off Windows."""
    if not IS_WINDOWS:
        return None
    import ctypes.wintypes as w

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.OpenInputDesktop.restype = w.HANDLE
    user32.OpenInputDesktop.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    user32.CloseDesktop.argtypes = [w.HANDLE]
    desktop = user32.OpenInputDesktop(0, False, 0x0100)  # DESKTOP_SWITCHDESKTOP
    if not desktop:
        return False
    user32.CloseDesktop(desktop)
    return True


class JobUnavailable(OSError):
    """A kill-on-close Job Object could not be created or a child could not be assigned to it."""


class _Job:
    """One kill-on-close Job Object over a child started suspended. Windows only."""

    def __init__(self) -> None:
        import ctypes.wintypes as w

        self._w = w
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = w.HANDLE
        kernel32.CreateJobObjectW.argtypes = [w.LPVOID, w.LPCWSTR]
        kernel32.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        kernel32.AssignProcessToJobObject.restype = w.BOOL
        kernel32.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD]
        kernel32.SetInformationJobObject.restype = w.BOOL
        kernel32.QueryInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD)]
        kernel32.QueryInformationJobObject.restype = w.BOOL
        kernel32.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
        kernel32.TerminateJobObject.restype = w.BOOL
        kernel32.CloseHandle.argtypes = [w.HANDLE]
        self._kernel32 = kernel32
        self._ntdll = ctypes.WinDLL("ntdll")
        self._ntdll.NtResumeProcess.argtypes = [w.HANDLE]
        self._ntdll.NtResumeProcess.restype = ctypes.c_long
        self._info_class = self._limit_information_type()
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise JobUnavailable(f"CreateJobObject failed: error {ctypes.get_last_error()}")
        self.handle = handle
        info = self._info_class()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(handle, _JobObjectExtendedLimitInformation, ctypes.byref(info),
                                                ctypes.sizeof(info)):
            error = ctypes.get_last_error()
            self.close()
            raise JobUnavailable(f"SetInformationJobObject failed: error {error}")

    def _limit_information_type(self):
        w = self._w

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", w.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", w.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", w.DWORD), ("SchedulingClass", w.DWORD)]

        class Io(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes",
                                                             "OtherBytes")]

        class Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", Io), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        return Extended

    def adopt_and_resume(self, proc: subprocess.Popen) -> None:
        """Assign the suspended child, then let it run. A failure here leaves the child stopped, never running free."""
        handle = int(proc._handle)
        if not self._kernel32.AssignProcessToJobObject(self.handle, handle):
            error = ctypes.get_last_error()
            proc.kill()
            proc.wait()
            raise JobUnavailable(f"AssignProcessToJobObject failed: error {error} (a nested-job restriction?)")
        status = self._ntdll.NtResumeProcess(handle)
        if status != 0:
            self.terminate()
            proc.wait()
            raise JobUnavailable(f"NtResumeProcess failed: status {status:#x}")

    def pids(self) -> list[int]:
        """Every process still in the job, read from the job itself."""
        w = self._w
        capacity = 4096

        class List(ctypes.Structure):
            _fields_ = [("NumberOfAssignedProcesses", w.DWORD), ("NumberOfProcessIdsInList", w.DWORD),
                        ("ProcessIdList", ctypes.c_size_t * capacity)]

        data = List()
        if not self._kernel32.QueryInformationJobObject(self.handle, _JobObjectBasicProcessIdList, ctypes.byref(data),
                                                        ctypes.sizeof(data), None):
            raise JobUnavailable(f"QueryInformationJobObject failed: error {ctypes.get_last_error()}")
        return [int(pid) for pid in data.ProcessIdList[:data.NumberOfProcessIdsInList]]

    def peak_memory(self) -> int | None:
        info = self._info_class()
        if not self._kernel32.QueryInformationJobObject(self.handle, _JobObjectExtendedLimitInformation, ctypes.byref(info),
                                                        ctypes.sizeof(info), None):
            return None
        return int(info.PeakJobMemoryUsed)

    def terminate(self) -> None:
        self._kernel32.TerminateJobObject(self.handle, STOPPED_EXIT_CODE)

    def close(self) -> None:
        if self.handle:
            self._kernel32.CloseHandle(self.handle)
            self.handle = None


def _image_name(pid: int) -> str:
    """The image path of a process, for the record. Best effort: a process may be gone by the time it is asked."""
    if not IS_WINDOWS:
        return "?"
    import ctypes.wintypes as w

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = w.HANDLE
    kernel32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel32.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
    kernel32.CloseHandle.argtypes = [w.HANDLE]
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return "?"
    try:
        buffer = ctypes.create_unicode_buffer(1024)
        size = w.DWORD(1024)
        return buffer.value if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)) else "?"
    finally:
        kernel32.CloseHandle(handle)


@dataclass
class ChildResult:
    """What one supervised child did. ``returncode`` is the child's own raw status, kept as it came."""

    argv: list[str]
    pid: int | None = None
    returncode: int | None = None
    ended: str = "not-started"  # exited | timeout | stall | interrupted | error | not-started
    started_at_monotonic: float = 0.0
    seconds: float = 0.0
    ownership: str = "none"  # job | process-group | none
    error_mode_at_launch: str | None = None
    #: Owned processes still alive when the child had exited and the drain budget had passed: a cleanup failure.
    remaining: list[dict] = field(default_factory=list)
    #: Owned processes still alive even after the bounded kill: never expected, reported as such.
    survivors: list[dict] = field(default_factory=list)
    peak_memory_bytes: int | None = None
    start_error: str | None = None

    @property
    def clean(self) -> bool:
        return not self.remaining and not self.survivors

    def record(self) -> dict:
        return {"argv": self.argv, "pid": self.pid, "returncode": self.returncode, "ended": self.ended,
                "seconds": round(self.seconds, 3), "ownership": self.ownership,
                "error_mode_at_launch": self.error_mode_at_launch, "owned_remaining": self.remaining,
                "owned_survivors": self.survivors, "peak_memory_bytes": self.peak_memory_bytes,
                "start_error": self.start_error}


def _progress_marker(paths) -> tuple:
    marker = []
    for path in paths:
        try:
            marker.append(os.stat(path).st_size)
        except OSError:
            marker.append(-1)
    return tuple(marker)


def _start(argv, sink, cwd, env) -> tuple[subprocess.Popen, _Job | None, str]:
    kwargs = {"cwd": str(cwd), "env": env, "stdin": subprocess.DEVNULL, "stdout": sink, "stderr": subprocess.STDOUT}
    if IS_WINDOWS:
        job = _Job()
        try:
            proc = subprocess.Popen(argv, creationflags=CREATE_SUSPENDED, **kwargs)
        except BaseException:
            job.close()
            raise
        try:
            job.adopt_and_resume(proc)
        except BaseException:
            job.close()
            raise
        return proc, job, "job"
    proc = subprocess.Popen(argv, start_new_session=True, **kwargs)
    return proc, None, "process-group"


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _alive_owned(proc, job) -> list[dict]:
    if job is not None:
        return [{"pid": pid, "image": _image_name(pid)} for pid in job.pids()]
    if proc.pid and _group_alive(proc.pid):
        return [{"pid": proc.pid, "image": "process group"}]
    return []


def _stop_tree(proc, job, *, kill_wait: float) -> None:
    """End every owned process: on Windows the job at once (no console to ask politely through), on POSIX TERM then KILL."""
    if job is not None:
        job.terminate()
    elif proc.pid and _group_alive(proc.pid):
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=kill_wait)
        except subprocess.TimeoutExpired:
            pass
        if _group_alive(proc.pid):
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    try:
        proc.wait(timeout=kill_wait)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=kill_wait)


def run_supervised(argv, *, log_path: Path, cwd, env, timeout: float, stall: float | None = None, progress_paths=(),
                   drain: float = 10.0, kill_wait: float = 10.0, on_start=None, poll: float = 0.25) -> ChildResult:
    """Run one child to its end under a whole-tree budget, with its output in ``log_path``, and report what is left over.

    ``stall`` ends the tree when neither the log nor any of ``progress_paths`` has grown for that long, which is what a
    modal dialog or a deadlock looks like from outside. A KeyboardInterrupt (or any other exception) stops the tree first
    and is then re-raised, so an interrupted run never leaves its children behind. Raises JobUnavailable when ownership
    cannot be established: the caller reports that as BLOCKED rather than running the child unowned.
    """
    result = ChildResult(argv=[str(arg) for arg in argv])
    mode = error_mode()
    result.error_mode_at_launch = None if mode is None else hex(mode)
    began = time.monotonic()
    result.started_at_monotonic = began
    with open(log_path, "xb") as sink:
        sink.write((" ".join(result.argv) + "\n").encode("utf-8", "replace"))
        sink.flush()
        try:
            proc, job, result.ownership = _start(argv, sink, cwd, env)
        except JobUnavailable:
            raise
        except OSError as exc:
            result.start_error = f"{type(exc).__name__}: {exc}"
            result.ended = "error"
            return result
    result.pid = proc.pid
    if on_start is not None:
        on_start(result)
    watched = [log_path, *progress_paths]
    last_marker, last_change = _progress_marker(watched), time.monotonic()
    try:
        try:
            while True:
                try:
                    result.returncode = proc.wait(timeout=poll)
                    result.ended = "exited"
                    break
                except subprocess.TimeoutExpired:
                    pass
                now = time.monotonic()
                marker = _progress_marker(watched)
                if marker != last_marker:
                    last_marker, last_change = marker, now
                if now - began > timeout:
                    result.ended = "timeout"
                    break
                if stall is not None and now - last_change > stall:
                    result.ended = "stall"
                    break
        except BaseException:
            result.ended = "interrupted"
            _stop_tree(proc, job, kill_wait=kill_wait)
            result.returncode = proc.returncode
            raise
        if result.ended != "exited":
            _stop_tree(proc, job, kill_wait=kill_wait)
            result.returncode = proc.returncode
        else:
            deadline = time.monotonic() + drain
            remaining = _alive_owned(proc, job)
            while remaining and time.monotonic() < deadline:
                time.sleep(min(poll, 0.1))
                remaining = _alive_owned(proc, job)
            if remaining:
                result.remaining = remaining
                _stop_tree(proc, job, kill_wait=kill_wait)
        if job is not None:
            deadline = time.monotonic() + kill_wait
            survivors = _alive_owned(proc, job)
            while survivors and time.monotonic() < deadline:
                time.sleep(min(poll, 0.1))
                survivors = _alive_owned(proc, job)
            result.survivors = survivors
            result.peak_memory_bytes = job.peak_memory()
        elif proc.pid and _group_alive(proc.pid):
            result.survivors = _alive_owned(proc, job)
    finally:
        result.seconds = time.monotonic() - began
        if job is not None:
            job.close()  # kill-on-close: nothing owned can outlive this, even if a step above raised
    return result
