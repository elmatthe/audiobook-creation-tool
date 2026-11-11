"""Windows Job Object accounting for one benchmark process tree, and per-child times/peaks (ctypes, stdlib only).

Promoted unchanged in substance from Phase 7A's evidence tools for the m4b-scaling qualification (v0.7.2 Phase 7B).

The harness puts itself in a new job, so every FFmpeg/ffprobe it starts is counted: total processes, CPU, I/O bytes and
the peak commit of the whole tree. KILL_ON_JOB_CLOSE means no child can outlive the harness.

**What the job's peak commit counts** (measured, v0.7.2 Phase 8 remediation). Windows keeps charging a job for a process
that has exited for as long as anyone holds a handle to it: about 77 KB each on the qualification machine, gone the
moment the handle is closed. A harness that keeps every child's ``Popen`` object therefore adds that much per child to
the figure it is trying to read (155 MB of 236 MB on the 1,000-chapter book), and the sum is not the same twice.
``bench_run.py`` reads a child's figures when it ends and lets it go; nothing here keeps a handle either.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as w

_k = ctypes.WinDLL("kernel32", use_last_error=True)
_ps = ctypes.WinDLL("psapi", use_last_error=True)
_k.CreateJobObjectW.restype = w.HANDLE
_k.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
_k.GetCurrentProcess.restype = w.HANDLE
_k.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
_k.QueryInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p]
_k.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
_k.GetProcessTimes.argtypes = [w.HANDLE] + [ctypes.POINTER(w.FILETIME)] * 4
_ps.GetProcessMemoryInfo.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD]
_k.GetProcessIoCounters.argtypes = [w.HANDLE, ctypes.c_void_p]


class _IO(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                                                  "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _Basic(ctypes.Structure):
    _fields_ = [("TotalUserTime", ctypes.c_longlong), ("TotalKernelTime", ctypes.c_longlong),
                ("ThisPeriodTotalUserTime", ctypes.c_longlong), ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
                ("TotalPageFaultCount", w.DWORD), ("TotalProcesses", w.DWORD), ("ActiveProcesses", w.DWORD),
                ("TotalTerminatedProcesses", w.DWORD)]


class _BasicIO(ctypes.Structure):
    _fields_ = [("Basic", _Basic), ("Io", _IO)]


class _Limits(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", w.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", w.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", w.DWORD), ("SchedulingClass", w.DWORD)]


class _Extended(ctypes.Structure):
    _fields_ = [("Basic", _Limits), ("Io", _IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]


class _PMC(ctypes.Structure):
    _fields_ = [("cb", w.DWORD), ("PageFaultCount", w.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]


JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000


class Job:
    def __init__(self) -> None:
        self.handle = _k.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW")
        limits = _Extended()
        limits.Basic.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not _k.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise OSError(ctypes.get_last_error(), "SetInformationJobObject")
        if not _k.AssignProcessToJobObject(self.handle, _k.GetCurrentProcess()):
            raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject")

    def snapshot(self) -> dict:
        basic = _BasicIO()
        _k.QueryInformationJobObject(self.handle, 8, ctypes.byref(basic), ctypes.sizeof(basic), None)
        ext = _Extended()
        _k.QueryInformationJobObject(self.handle, 9, ctypes.byref(ext), ctypes.sizeof(ext), None)
        return {
            "user_s": basic.Basic.TotalUserTime / 1e7, "kernel_s": basic.Basic.TotalKernelTime / 1e7,
            "processes": basic.Basic.TotalProcesses, "active": basic.Basic.ActiveProcesses,
            "read_bytes": basic.Io.ReadTransferCount, "write_bytes": basic.Io.WriteTransferCount,
            "peak_process_commit": ext.PeakProcessMemoryUsed, "peak_job_commit": ext.PeakJobMemoryUsed,
        }


    def process_ids(self) -> list[int]:
        """The processes in the job right now (``JobObjectBasicProcessIdList``)."""
        listed = _IdList()
        if not _k.QueryInformationJobObject(self.handle, 3, ctypes.byref(listed), ctypes.sizeof(listed), None):
            return []
        return [int(listed.ProcessIdList[index]) for index in range(listed.NumberOfProcessIdsInList)]

    def children_of(self, parent: int) -> list[dict]:
        """Every process in the job whose parent is *parent*, each with a query handle the caller must close.

        Windows gives a hidden console program its own console host (``conhost.exe``), started as that program's child:
        this is how the harness finds the one that belongs to the continuous decoder (v0.7.2 Phase 8 remediation).
        """
        found = []
        for pid in self.process_ids():
            if pid == parent:
                continue
            handle = _k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                continue
            info = _BasicInformation()
            if _nt.NtQueryInformationProcess(handle, 0, ctypes.byref(info), ctypes.sizeof(info), None) == 0 \
                    and int(info.InheritedFromUniqueProcessId or 0) == parent:
                found.append({"pid": pid, "image": image_name(handle), "handle": int(handle)})
            else:
                _k.CloseHandle(handle)
        return found


class _IdList(ctypes.Structure):
    _fields_ = [("NumberOfAssignedProcesses", w.DWORD), ("NumberOfProcessIdsInList", w.DWORD),
                ("ProcessIdList", ctypes.c_size_t * 1024)]


class _BasicInformation(ctypes.Structure):
    _fields_ = [(name, ctypes.c_void_p) for name in ("ExitStatus", "PebBaseAddress", "AffinityMask", "BasePriority",
                                                     "UniqueProcessId", "InheritedFromUniqueProcessId")]


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_nt = ctypes.WinDLL("ntdll")
_nt.NtQueryInformationProcess.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p]
_k.OpenProcess.restype = w.HANDLE
_k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
_k.CloseHandle.argtypes = [w.HANDLE]
_k.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]


def image_name(handle: int) -> str:
    """The file name of a process's image, lower case, or ``?``."""
    buffer = ctypes.create_unicode_buffer(1024)
    size = w.DWORD(1024)
    if not _k.QueryFullProcessImageNameW(w.HANDLE(handle), 0, buffer, ctypes.byref(size)):
        return "?"
    return buffer.value.replace("/", "\\").rsplit("\\", 1)[-1].lower()


def close_handle(handle: int) -> None:
    _k.CloseHandle(w.HANDLE(handle))


def _ft(value: w.FILETIME) -> float:
    return ((value.dwHighDateTime << 32) | value.dwLowDateTime) / 1e7


def process_facts(handle: int) -> dict:
    """CPU, memory peaks and I/O bytes of one (possibly exited, still referenced) process.

    The I/O bytes count every read and write the process issued, pipes included (Windows counts a pipe write like a file
    write), so they are not disk traffic on their own (v0.7.2 Phase 7B, qualification attempt 2).
    """
    created, exited, kernel, user = (w.FILETIME() for _ in range(4))
    facts: dict = {}
    if _k.GetProcessTimes(w.HANDLE(handle), ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel),
                          ctypes.byref(user)):
        facts.update(user_s=_ft(user), kernel_s=_ft(kernel), wall_s=max(0.0, _ft(exited) - _ft(created)))
    counters = _PMC()
    counters.cb = ctypes.sizeof(counters)
    if _ps.GetProcessMemoryInfo(w.HANDLE(handle), ctypes.byref(counters), counters.cb):
        facts.update(peak_ws=counters.PeakWorkingSetSize, peak_commit=counters.PeakPagefileUsage)
    io = _IO()
    if _k.GetProcessIoCounters(w.HANDLE(handle), ctypes.byref(io)):
        facts.update(read_bytes=io.ReadTransferCount, write_bytes=io.WriteTransferCount)
    return facts


def self_facts() -> dict:
    return process_facts(int(_k.GetCurrentProcess()))


class _Times(ctypes.Structure):
    _fields_ = [("idle", w.FILETIME), ("kernel", w.FILETIME), ("user", w.FILETIME)]


def system_times() -> tuple[int, int, int]:
    """The machine's idle, kernel and user time so far (100 ns units), for load over an interval."""
    idle, kernel, user = w.FILETIME(), w.FILETIME(), w.FILETIME()
    _k.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
    value = lambda f: (f.dwHighDateTime << 32) | f.dwLowDateTime  # noqa: E731
    return value(idle), value(kernel), value(user)


def load_between(before: tuple[int, int, int], after: tuple[int, int, int]) -> float:
    """Percent of all cores busy between two ``system_times`` readings."""
    idle = after[0] - before[0]
    total = (after[1] - before[1]) + (after[2] - before[2])
    return round(100.0 * (1 - idle / total), 1) if total else 0.0
