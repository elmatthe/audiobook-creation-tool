"""How many source files one TTS run converts at once (v0.7.1).

Workers are whole files: one file's own chapters and sentences always stay in order on one worker. The person asks
for a number (1-100 in the panel); the run uses

    effective = max(1, min(requested, queued files, engine ceiling, Edge service ceiling, processors, memory))

and the run log says ``Requested workers: N | Effective workers: M`` plus, when M < N, which limit applied.

* **Engine.** Kokoro, Chatterbox Turbo and Qwen3-TTS convert one file at a time (shared, non-reentrant model state;
  see ``epub2tts_gui``). Only Edge, a network service, runs files side by side.
* **Edge service.** Microsoft's Edge read-aloud service is unofficial and documents no limit. Hardware capacity is
  not service capacity, so Edge is capped at :data:`EDGE_SERVICE_CEILING` simultaneous files whatever the machine.
* **Processors.** One Edge file per logical processor: a file's own local work (decoding each clip, trimming,
  encoding) is short bursts between network waits, so this leaves room for the window and Windows.
* **Memory.** A file's peak memory grows with its narration length, because the whole narration is assembled in
  memory before the one MP3 encode. Measured on HOME-PC (v0.7.1 plan, F12-F14): Edge audio is 48,000 PCM bytes per
  second; the peak was about 144 KB per narration second on the direct route and 115 KB/s on the folder route
  (:data:`PEAK_BYTES_PER_NARRATION_SECOND` rounds up); each file's FFmpeg child peaked at 22-24 MB
  (:data:`FILE_BASE_BYTES` adds room for the file's own Python objects); Steffan narrated 14.7-15.1 source characters
  per second (:data:`NARRATION_CHARS_PER_SECOND` leaves room for slower voices and pause-dense text); light-novel
  PDFs held 1,580-1,740 characters per page (:data:`PDF_CHARS_PER_PAGE`). The run keeps
  ``max(1 GiB, 25 % of physical memory)`` free for Windows, the app and other programs and admits as many of the
  **largest** queued files as fit in the rest. Where free memory cannot be read (macOS), it is not guessed: the
  memory limit is not applied and the log says so.

Standard library only; PDFs are sized through ``pdf_extractor`` (imported lazily) so PyMuPDF stays behind its lock.
"""

from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

EDGE = "edge"
#: Simultaneous Edge files, whatever the machine (see the module docstring).
EDGE_SERVICE_CEILING = 32
#: The local engines: one file at a time, always.
LOCAL_ENGINE_CEILINGS = {"kokoro": 1, "chatterbox": 1, "qwen3": 1}
ENGINE_NAMES = {EDGE: "Edge", "kokoro": "Kokoro", "chatterbox": "Chatterbox Turbo", "qwen3": "Qwen3-TTS"}
#: Used when the processor count cannot be read.
FALLBACK_CPUS = 4

PEAK_BYTES_PER_NARRATION_SECOND = 150_000
FILE_BASE_BYTES = 64 * 1024 ** 2
NARRATION_CHARS_PER_SECOND = 12
PDF_CHARS_PER_PAGE = 3_000
MIN_MEMORY_RESERVE = 1024 ** 3
MEMORY_RESERVE_FRACTION = 0.25


@dataclass(frozen=True)
class MemoryInfo:
    available: int  # bytes the OS can hand out now without paging
    total: int      # physical memory


@dataclass(frozen=True)
class WorkerPlan:
    requested: int
    effective: int
    reasons: tuple[str, ...] = ()  # the limits that set ``effective`` (shown only when it is below the request)
    notes: tuple[str, ...] = ()    # what could not be measured

    def log_lines(self) -> list[str]:
        lines = [f"Requested workers: {self.requested} | Effective workers: {self.effective}"]
        if self.effective < self.requested:
            lines.append("Worker limit: " + "; ".join(self.reasons + self.notes) + ".")
        return lines


def file_peak_bytes(chars: int) -> int:
    """The most memory one in-flight file of ``chars`` source characters is budgeted to need."""
    seconds = math.ceil(max(0, int(chars)) / NARRATION_CHARS_PER_SECOND)
    return FILE_BASE_BYTES + seconds * PEAK_BYTES_PER_NARRATION_SECOND


def _gb(value: int) -> str:
    return f"{value / 1024 ** 3:.1f} GB"


def _memory_ceiling(sizes: Sequence[int], memory: MemoryInfo) -> tuple[int, str]:
    reserve = max(MIN_MEMORY_RESERVE, int(MEMORY_RESERVE_FRACTION * memory.total))
    usable = memory.available - reserve
    peaks = sorted((file_peak_bytes(size) for size in sizes), reverse=True)
    fitted = used = 0
    for peak in peaks:
        if used + peak > usable:
            break
        used += peak
        fitted += 1
    largest = peaks[0] if peaks else FILE_BASE_BYTES
    reason = (f"memory ({_gb(memory.available)} free, {_gb(reserve)} kept for Windows and other programs, "
              f"and the largest queued file can need up to {_gb(largest)} while it is assembled)")
    return max(1, fitted), reason


def plan_workers(requested, backend: str, sizes: Sequence[int], *, cpu_count: Optional[int],
                 memory: Optional[MemoryInfo]) -> WorkerPlan:
    """The pure decision. ``sizes`` holds each queued file's estimated characters (:func:`estimate_source_chars`)."""
    requested = int(requested)
    queued = len(sizes)
    limits: list[tuple[int, str]] = [
        (queued, f"only {queued} file{' is' if queued == 1 else 's are'} queued"),
    ]
    notes: list[str] = []
    if backend != EDGE:
        name = ENGINE_NAMES.get(backend, backend)
        limits.append((LOCAL_ENGINE_CEILINGS.get(backend, 1), f"{name} converts one file at a time"))
    else:
        limits.append((EDGE_SERVICE_CEILING,
                       f"the Edge online service ceiling ({EDGE_SERVICE_CEILING} files at once)"))
        if cpu_count and cpu_count > 0:
            limits.append((int(cpu_count), f"this computer has {int(cpu_count)} logical processors "
                                            "(one file per processor)"))
        else:
            limits.append((FALLBACK_CPUS, f"the processor count could not be read ({FALLBACK_CPUS} files at once)"))
        if memory is None:
            notes.append("free memory could not be measured, so it was not used to limit workers")
        elif sizes:
            ceiling, reason = _memory_ceiling(sizes, memory)
            if ceiling < queued:  # memory limits only when it cannot hold every queued file at once
                limits.append((ceiling, reason))
    effective = max(1, min([requested] + [ceiling for ceiling, _ in limits]))
    reasons = tuple(reason for ceiling, reason in limits if ceiling == effective and ceiling < requested)
    return WorkerPlan(requested, effective, reasons, tuple(notes))


# --------------------------------------------------------------------------- the machine and the workload


def logical_cpus() -> Optional[int]:
    """Logical processors this process may use, or ``None`` when they cannot be read."""
    counter = getattr(os, "process_cpu_count", None)  # Python 3.13+
    if counter is not None:
        return counter()
    affinity = getattr(os, "sched_getaffinity", None)  # Linux
    if affinity is not None:
        try:
            return len(affinity(0)) or None
        except OSError:
            pass
    return os.cpu_count()


def memory_info() -> Optional[MemoryInfo]:
    """Free and total physical memory where the OS reports it reliably (Windows, Linux); ``None`` elsewhere."""
    try:
        if sys.platform == "win32":
            return _windows_memory()
        if sys.platform.startswith("linux"):
            return _linux_memory()
    except (OSError, ValueError, AttributeError):
        return None
    return None


def _windows_memory() -> Optional[MemoryInfo]:
    import ctypes
    import ctypes.wintypes as wt

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", wt.DWORD), ("dwMemoryLoad", wt.DWORD), ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return MemoryInfo(int(status.ullAvailPhys), int(status.ullTotalPhys))


def _linux_memory() -> Optional[MemoryInfo]:
    fields: dict[str, int] = {}
    with open("/proc/meminfo", encoding="ascii") as handle:
        for line in handle:
            key, _, rest = line.partition(":")
            parts = rest.split()
            if parts:
                fields[key] = int(parts[0]) * 1024
    if "MemAvailable" not in fields or "MemTotal" not in fields:
        return None
    return MemoryInfo(fields["MemAvailable"], fields["MemTotal"])


def estimate_source_chars(path) -> int:
    """A source's narration size in characters, without extracting it: a TXT's bytes; a PDF's pages x
    :data:`PDF_CHARS_PER_PAGE` (its file size if the pages cannot be counted). A missing file counts as 0."""
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError:
        return 0
    if path.suffix.lower() == ".pdf":
        from tts.pdf_extractor import pdf_page_count

        pages = pdf_page_count(str(path))
        return size if pages is None else pages * PDF_CHARS_PER_PAGE
    return size


def plan_for_sources(requested, backend: str, sources: Iterable) -> WorkerPlan:
    """:func:`plan_workers` for real files on this machine."""
    sizes = [estimate_source_chars(source) for source in sources] if backend == EDGE else [0 for _ in sources]
    return plan_workers(requested, backend, sizes,
                        cpu_count=logical_cpus() if backend == EDGE else None,
                        memory=memory_info() if backend == EDGE else None)
