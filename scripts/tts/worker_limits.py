"""How many source files one TTS run converts at once, and when one of them may assemble its audio (v0.7.1).

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
* **Memory.** See below.

**Memory has two layers, because a plan made from text can be wrong, and because a file needs little until the end.**
While a file is being synthesised it holds at most :data:`SYNTHESIS_HELD_PCM_BYTES` of audio in memory (the rest is on
disk); then its whole narration is decoded into memory for the one MP3 encode, if it fits.

*During the run, measurements.* A long paragraph is written out as it grows, and a clip too long to hold is never decoded
into memory at all (``epub2tts_edge.read_book``), so synthesis stays small whatever the plan believed. Immediately before
a narration is assembled, :data:`ASSEMBLY_GATE` is given its real size, read from the finished audio files' headers, and
reads what is free now. It decides, first come first served:

* **It fits** in what is usable now (:func:`memory_usable`: physical memory and commit, process and job limits), with what is
  reserved and not yet visible in those readings counted: assemble in memory, as ever.
* **It does not fit, and other files are assembling in memory:** wait for them, while synthesis on every other worker
  carries on. Their memory comes back.
* **It does not fit, and nothing here will free any:** assemble on disk (:mod:`tts.disk_assembly`). The same audio, the
  same bytes, for :data:`DISK_ASSEMBLY_BYTES`. Being the only assembly says nothing about the memory that synthesis,
  FFmpeg, other programs and Windows are using, so no assembly is ever let into memory for being first.
* **Not even that much is free:** wait for it, then fail with a reason (:class:`AssemblyMemoryError`). The wait,
  :data:`ASSEMBLY_MEMORY_WAIT_SECONDS`, belongs to the gate and not to each file: a whole queue of waiters ends together, not one
  after another. Nothing has been written to a destination and Retry Failed can run each one again; it is not retried by itself,
  because the same machine in the same state would only fail again.

*An answer is not a promise.* Memory can go after the gate has said yes, and a reading cannot see every limit. So :func:`assemble`
treats an allocation failure in memory as one more route decision: it gives back the reservation, and the same finished audio is
assembled on disk, once, without asking the service for anything again. If even that runs out, the file fails with a reason. Every
FFmpeg on these routes is one this program can stop (:mod:`tts.ffmpeg_watch`), so none of this can end in a hang.

*Cancel.* (v0.7.2) Cancel wins at every step: a file waiting at the gate stops waiting at once, whether or not its synthesis is
complete; an assembly under way is killed by :mod:`tts.ffmpeg_watch` within one look; nothing falls back to disk, tries again or is
published after the latch. Finished narration is not an exception: the person asked for the work to stop, and it stops. What was
already published before the Cancel stays. :meth:`AssemblyGate.wake` lets a Cancel reach a waiter before its next poll.

*Before the run, a model.* Each queued file's narration is estimated from its real text and the run's frozen settings
(:func:`estimate_text_seconds`). The run keeps ``max(1 GiB, 25 % of physical memory)`` free for Windows and other
programs, and admits as many files as fit in the rest with **the largest single assembly** on top of **each file's
synthesis memory**: the gate is what keeps several assemblies from being added together. So a queue of whole novels runs
side by side and takes turns to assemble, while a machine that could not hold even one of those assemblies, or a source
with no paragraph breaks (counted whole, though synthesis now writes it out as it goes), is held back. The model is an upper
estimate, not a measurement of the file, and it stays bounded: a source is never synthesised, a PDF is read for at most
:data:`PDF_SCAN_PAGES` pages, and the whole queue for at most :data:`PLAN_SCAN_SECONDS`, checked between pages, after
which a source is sized from its length and the log says so. A fully read PDF is sized from the text a conversion will
speak, its pages joined the same way; a longer one's longest paragraph is scaled up with its sample.

*What cannot be bounded in advance.* Nothing says a PDF's text can be known without reading it, a sample cannot see a
page it did not read, and a source can change after planning. That is why the plan is not what keeps memory safe: the
measurements above hold whatever the plan believed.

**What each number is.** *Measured on HOME-PC, Windows 11:* Edge audio is 24 kHz mono 16-bit, 48,000 PCM bytes per second,
for all five voices; the peak was 144-150 KB per narration second on the direct route, pause-heavy files included, and
115 KB/s on the folder route (:data:`PEAK_BYTES_PER_NARRATION_SECOND` rounds up); FFmpeg children 22-24 MB. Speech (real
Edge, ``Steffan``, ``Andrew``, ``Aria``, ``Ava``, ``Jenny``; ``files/dev-work/act071-remediation/logs/``, ignored): assembling
on disk added 31-32 MB to the process tree, children included, on narrations of 2 and 4.6 hours (680 MB and 2,297 MB in
memory; ``files/dev-work/act071-rem2/logs/``, ignored); prose at
worst 17.2 characters per second; a one-letter word at most 0.40 s; a digit at most 0.41 s; a spoken symbol at most 0.51 s;
up to 1.47 s of padding on a clip nobody trims; on the folder route, where the service chooses its own pauses, 0.70 s
after a sentence, 0.28 s at a comma or dash, 0.89 s at an ellipsis. Ten real narrations came out at 1.42-1.58 x below the
model. *Conservative assumptions:* the constants below, each above its measurement. *Known to run below the model:* text
made only of URLs (8.6 s measured, 6.5 modelled), all-capital acronyms (2.7, 2.0) and one-word sentences (0.62 s against
0.40 for the word alone); the margin is on ordinary prose, and the gate covers the rest. *Not measured:* every voice
Microsoft offers (a voice given to ``batch_convert --speaker`` may be slower), other machines, and memory the allocator
keeps after a peak. Expansion by speech preparation is not assumed: when it is on, the planner runs the run's own frozen
preparation on the text it sizes.

Where free memory cannot be read, a cautious :data:`UNKNOWN_MEMORY_PLAN_BYTES` is assumed for the plan and
:data:`UNKNOWN_MEMORY_ASSEMBLY_BYTES` for the gate, and the log says so: assumptions, stated as such.

**What the readings mean, and what is counted against them.** All in bytes. *Physical* (``ullAvailPhys``) less
:func:`memory_reserve`, because Windows and other programs need room to run. *Commit* (``ullAvailPageFile``: what this process can
still commit; Windows counts every allocation against it when it is made, whether or not it is ever touched, and a process can run out
of it with plenty of physical memory free) less :data:`COMMIT_RESERVE_BYTES`, because at zero every program on the computer starts
failing. *A Job Object's* limit on this process or its job, where one applies and can be read, less :data:`LIMIT_MARGIN_BYTES`: nothing
else depends on that room. A reading that is not available is left out, and the others decide. To disk only the bare amount is required:
it is the way to stay small, and those margins are there for a route that needs far more.

An allocation shows up in those readings as soon as it is made, so a reservation must not be counted against them a second time.
What is counted (:meth:`AssemblyGate._claimed`) is what has been reserved less what this process has allocated since the first
reservation was made: the part of each reservation still to come. That difference is an estimate, and errs both ways by small
amounts: FFmpeg's own memory is in the readings and not in this process's growth, and a synthesising worker's growth looks like an
assembly's. The first is about 24 MB per FFmpeg, and the second is far below every margin above; and if it ever matters, an
allocation failure is handled. Where this process's own usage cannot be read, the whole reservation is counted, which only waits longer.

Standard library and ``shared.cancellation`` at import time; ``mutagen`` and ``pdf_extractor`` are imported when used, so
PyMuPDF stays behind its lock.
"""

from __future__ import annotations

import contextlib
import errno
import math
import os
import re
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, NamedTuple, Optional, Sequence

from shared.cancellation import ConversionCancelled

EDGE = "edge"
#: Simultaneous Edge files, whatever the machine (see the module docstring).
EDGE_SERVICE_CEILING = 32
#: The local engines: one file at a time, always.
LOCAL_ENGINE_CEILINGS = {"kokoro": 1, "chatterbox": 1, "qwen3": 1}
ENGINE_NAMES = {EDGE: "Edge", "kokoro": "Kokoro", "chatterbox": "Chatterbox Turbo", "qwen3": "Qwen3-TTS"}
#: Used when the processor count cannot be read.
FALLBACK_CPUS = 4

EDGE_PCM_BYTES_PER_SECOND = 48_000
PEAK_BYTES_PER_NARRATION_SECOND = 150_000
FILE_BASE_BYTES = 64 * 1024 ** 2
MIN_MEMORY_RESERVE = 1024 ** 3
MEMORY_RESERVE_FRACTION = 0.25

# How long speech lasts. Assumptions rounded up from the measurements in the module docstring.
NARRATION_CHARS_PER_SECOND = 12  # characters of ordinary text, spaces included (measured at worst 17.2)
DIGIT_SECONDS = 0.45             # a digit is read out (measured at most 0.41)
SYMBOL_SECONDS = 0.55            # %, &, /, and so on are read out (measured at most 0.51)
MIN_WORD_SECONDS = 0.40          # no word is shorter than this (measured at most 0.40 for "A")
CLIP_PADDING_SECONDS = 1.6       # the service's own silence around a clip nobody trims (measured at most 1.47)

# The pauses the direct route inserts. These first four are the engine's defaults, for a caller with no frozen values;
# the last three are the engine's constants. ``test_worker_limits`` keeps every one equal to ``epub2tts_edge``.
DEFAULT_SENTENCE_PAUSE_MS = 800
DEFAULT_PARAGRAPH_PAUSE_MS = 850
DEFAULT_TITLE_PAUSE_MS = 1200
DEFAULT_CHAPTER_PAUSE_MS = 2000
COMMA_PAUSE_MS = 300
ELLIPSIS_PAUSE_MS = 600
EM_DASH_PAUSE_MS = 400

# The pauses the service makes by itself on the folder route, rounded up.
NATURAL_SENTENCE_SECONDS = 0.75
NATURAL_COMMA_SECONDS = 0.30
NATURAL_ELLIPSIS_SECONDS = 0.90
NATURAL_DASH_SECONDS = 0.30
#: ``batch_convert``: 3000 characters to a chunk, 50 ms between chunks.
FOLDER_CHUNK_CHARS = 3000
FOLDER_CHUNK_PAUSE_SECONDS = 0.05

# The bounds on planning.
PLAN_SCAN_SECONDS = 5.0              # looking at a whole queue's text; after this a source is sized from its length
TXT_SCAN_BYTES = 16 * 1024 ** 2      # more of one TXT than this is scaled up from what was read: about 12 days of speech
PDF_SCAN_PAGES = 400                 # a longer PDF is read at this many pages spread through it, and scaled up
PREPARE_SCAN_CHARS = 2_000_000       # speech preparation on more than this is not worth the wait: digits are weighted
#: A shorter line cannot hold enough pause or speech to matter next to :data:`FILE_BASE_BYTES`.
LONG_PARAGRAPH_CHARS = 1000
# When nothing can be read in time: only a length, and how much speech that could be. Rounder than the text model.
ROUGH_CHARS_PER_SECOND = 8
ROUGH_CHARS_PER_PARAGRAPH = 40

#: Below this much PCM (about 5.5 minutes of narration) a join takes no slot: ordinary paragraphs never touch the gate.
ASSEMBLY_GATE_MIN_PCM_BYTES = 16 * 1024 ** 2
#: The most audio a file holds in memory while it is being synthesised (about 5.5 minutes): at this much, a paragraph
#: writes what it has to disk and carries on, and a clip this long is never decoded into memory.
SYNTHESIS_HELD_PCM_BYTES = 16 * 1024 ** 2
#: What assembling on disk needs, whatever the narration's length: small read and write buffers, the last moments of the
#: audio for the final tail, and one FFmpeg at a time (measured at 32 MB at most). See :mod:`tts.disk_assembly`.
DISK_ASSEMBLY_BYTES = 64 * 1024 ** 2
#: What this process itself needs of :data:`DISK_ASSEMBLY_BYTES` (measured at 14 MB at most, the rest being FFmpeg's): the amount
#: compared with a limit that applies to each process separately, FFmpeg having a limit of its own.
DISK_ASSEMBLY_PROCESS_BYTES = 24 * 1024 ** 2
#: How long the gate goes on with too little free even for that, with nothing of this run's to wait for, before every file
#: waiting fails: one deadline for the whole queue.
ASSEMBLY_MEMORY_WAIT_SECONDS = 300
#: Before the disk route's one further attempt, at least this long: what took the memory may have been a moment's peak.
DISK_RETRY_PAUSE_SECONDS = 2
#: Commit left for everything else on the computer. At zero, every program's next allocation fails, not just this one's.
COMMIT_RESERVE_BYTES = 1024 ** 3
#: Room left under a Job Object's limit, which only this process depends on.
LIMIT_MARGIN_BYTES = 32 * 1024 ** 2
#: What the plan assumes is usable where free memory cannot be read. An assumption, not a measurement: enough for a
#: queue of ordinary files, and too little for several sources that hold whole books in memory.
UNKNOWN_MEMORY_PLAN_BYTES = 4 * 1024 ** 3
#: How much may assemble in memory at once where free memory cannot be read. An assumption too: beyond it, files take
#: turns, and one too large for this on its own assembles on disk.
UNKNOWN_MEMORY_ASSEMBLY_BYTES = 2 * 1024 ** 3
#: PCM per stored byte for an audio file whose header cannot be read: no ordinary compression of speech goes beyond it.
UNREADABLE_AUDIO_EXPANSION = 32
#: pydub encodes through a WAV file, and a WAV's sizes are 32-bit: about 24.85 hours of Edge audio is the most one MP3 can
#: hold on this route (``publication.check_narration``).
LONGEST_NARRATION_SECONDS = 2 ** 32 / EDGE_PCM_BYTES_PER_SECOND


@dataclass(frozen=True)
class MemoryInfo:
    available: int  # bytes the OS can hand out now without paging
    total: int      # physical memory
    commit_available: Optional[int] = None  # what this process can still commit (Windows); None: not read
    process_headroom: Optional[int] = None  # a Job Object's per-process limit, less what this process has committed
    job_headroom: Optional[int] = None      # a Job Object's limit on its whole job, less what the job has committed


@dataclass(frozen=True)
class FileBudget:
    """What one queued file is estimated to need."""

    working: int   # while it is being synthesised: its share of the program, and its longest paragraph
    assembly: int  # while its whole narration is decoded for the one encode


@dataclass(frozen=True)
class WorkerPlan:
    requested: int
    effective: int
    reasons: tuple[str, ...] = ()  # the limits that set ``effective`` (shown only when it is below the request)
    notes: tuple[str, ...] = ()    # what could not be measured or read (shown whenever it could have mattered)

    def log_lines(self) -> list[str]:
        lines = [f"Requested workers: {self.requested} | Effective workers: {self.effective}"]
        if self.effective < self.requested and self.reasons:
            lines.append("Worker limit: " + "; ".join(self.reasons) + ".")
        if self.notes:
            lines.append("Worker note: " + "; ".join(self.notes) + ".")
        return lines


def peak_bytes_for_seconds(seconds: float) -> int:
    """The most memory holding this much narration is budgeted to need."""
    return FILE_BASE_BYTES + math.ceil(max(0.0, seconds)) * PEAK_BYTES_PER_NARRATION_SECOND


def peak_bytes_for_pcm(pcm_bytes: int) -> int:
    """The same budget for a narration whose decoded size is known."""
    return peak_bytes_for_seconds(max(0, pcm_bytes) / EDGE_PCM_BYTES_PER_SECOND)


def budget_for_seconds(total_seconds: float, longest_paragraph_seconds: float = 0.0) -> FileBudget:
    return FileBudget(peak_bytes_for_seconds(longest_paragraph_seconds), peak_bytes_for_seconds(total_seconds))


def _gb(value: int) -> str:
    return f"{value / 1024 ** 3:.1f} GB"


def memory_reserve(memory: MemoryInfo) -> int:
    """What stays free for Windows, the app's own window and other programs."""
    return max(MIN_MEMORY_RESERVE, int(MEMORY_RESERVE_FRACTION * memory.total))


def memory_usable(memory: MemoryInfo) -> int:
    """How much of what is free may be used for an assembly in memory: the tightest of what was read, each less its own margin."""
    usable = memory.available - memory_reserve(memory)
    if memory.commit_available is not None:
        usable = min(usable, memory.commit_available - COMMIT_RESERVE_BYTES)
    for headroom in (memory.process_headroom, memory.job_headroom):
        if headroom is not None:
            usable = min(usable, headroom - LIMIT_MARGIN_BYTES)
    return usable


def _memory_ceiling(budgets: Sequence[FileBudget], usable: int) -> int:
    """How many files can synthesise at once with the largest single assembly on top. The gate adds up the rest."""
    used = max(budget.assembly for budget in budgets)
    fitted = 0
    for working in sorted((budget.working for budget in budgets), reverse=True):
        if used + working > usable:
            break
        used += working
        fitted += 1
    return max(1, fitted)


def plan_workers(requested, backend: str, budgets: Sequence[FileBudget], *, cpu_count: Optional[int],
                 memory: Optional[MemoryInfo], notes: Sequence[str] = ()) -> WorkerPlan:
    """The pure decision. ``budgets`` holds each queued file's estimate; ``notes`` what could not be read about them."""
    requested = int(requested)
    queued = len(budgets)
    limits: list[tuple[int, str]] = [
        (queued, f"only {queued} file{' is' if queued == 1 else 's are'} queued"),
    ]
    stated = list(notes)
    memory_limit: Optional[tuple[int, str]] = None
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
            usable = UNKNOWN_MEMORY_PLAN_BYTES
            situation = f"it could not be measured, so {_gb(usable)} was assumed"
            stated.insert(0, f"free memory could not be measured, so {_gb(usable)} was assumed, and large files "
                             "assemble one at a time")
        else:
            reserve = memory_reserve(memory)
            usable = memory_usable(memory)
            situation = f"{_gb(memory.available)} free, {_gb(reserve)} kept for Windows and other programs"
            if usable < memory.available - reserve:
                situation += f", and at most {_gb(max(0, usable))} can be committed"
        if budgets:
            ceiling = _memory_ceiling(budgets, usable)
            if ceiling < queued:  # memory limits only when it cannot hold every queued file at once
                largest = max(budget.assembly for budget in budgets)
                memory_limit = (ceiling, f"memory ({situation}, and the largest queued file is estimated to need up to "
                                         f"{_gb(largest)} while it is assembled)")
    without_memory = max(1, min([requested] + [ceiling for ceiling, _ in limits]))
    if memory_limit is not None:
        limits.append(memory_limit)
    effective = max(1, min([requested] + [ceiling for ceiling, _ in limits]))
    reasons = tuple(reason for ceiling, reason in limits if ceiling == effective and ceiling < requested)
    # When something else already holds the run to one file, nothing about memory or sizes could have changed that.
    return WorkerPlan(requested, effective, reasons, tuple(stated) if without_memory > 1 else ())


# --------------------------------------------------------------------------- the runtime gate


class AssemblyMemoryError(MemoryError):
    """Not even assembling on disk has the memory it needs. Nothing was published; the file can be run again."""


def is_memory_failure(exc: BaseException) -> bool:
    """Did this fail because this computer ran out of memory, however it surfaced? :class:`AssemblyMemoryError` is the
    answer to that question and not another occurrence of it."""
    if isinstance(exc, AssemblyMemoryError):
        return False
    if isinstance(exc, MemoryError):
        return True
    if isinstance(exc, OSError):
        # ERROR_NOT_ENOUGH_MEMORY, ERROR_OUTOFMEMORY, ERROR_NO_SYSTEM_RESOURCES, ERROR_COMMITMENT_LIMIT
        return getattr(exc, "winerror", None) in (8, 14, 1450, 1455) or exc.errno == errno.ENOMEM
    text = str(exc).lower()
    if isinstance(exc, RuntimeError):
        return "can't start new thread" in text
    # FFmpeg's own allocation failed: it says so, or dies with STATUS_NO_MEMORY / STATUS_COMMITMENT_LIMIT.
    if type(exc).__name__ in ("CouldntDecodeError", "CouldntEncodeError"):
        return any(mark in text for mark in ("cannot allocate memory", "out of memory", "not enough memory",
                                             "error code: 3221225495", "error code: 3221225773"))
    return False


class AssemblyPlace:
    """One admitted assembly's place at the gate, for as long as it lasts."""

    def __init__(self, gate: Optional["AssemblyGate"], in_memory: bool, held: int) -> None:
        self._gate, self.in_memory, self._held = gate, in_memory, held

    def to_disk(self) -> None:
        """This assembly now needs only the disk route's memory: the rest of its reservation goes back, and whoever waits for it
        is told. It keeps its place, so falling back never has to wait for anything."""
        if self.in_memory and self._gate is not None:
            self._gate._give_back(self)
        self.in_memory = False

    def wait_for_room(self, stop: Optional[Callable[[], bool]] = None) -> None:
        """Before trying again on disk: until no other file here is holding a narration in memory (their peak may be all that
        was in the way), for at most the gate's wait, and at least :data:`DISK_RETRY_PAUSE_SECONDS`. ``stop`` ends it early."""
        if self._gate is not None:
            self._gate._wait_for_memory_holders(stop)
            return
        deadline = time.monotonic() + DISK_RETRY_PAUSE_SECONDS
        while time.monotonic() < deadline:
            if stop is not None and stop():
                return
            time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))


def _say(note: Optional[Callable[[str], None]], text: str) -> None:
    """Saying something must never be what stops the work: the log may well be out of memory too."""
    if note is not None:
        with contextlib.suppress(Exception):
            note(text)


class AssemblyGate:
    """Decides where each whole-narration assembly happens, by its real size and what is free now, first come first
    served: in memory, on disk, or not until there is room (the module docstring has the rule)."""

    def __init__(self, memory_reader: Optional[Callable[[], Optional[MemoryInfo]]] = None, poll_seconds: float = 0.25,
                 wait_seconds: Optional[float] = None, clock: Callable[[], float] = time.monotonic,
                 private_reader: Optional[Callable[[], Optional[int]]] = None):
        self._reader = memory_reader
        # With a stated memory reading and no stated usage, nothing allocated can be seen, so all of a reservation is counted.
        self._private_reader = private_reader if private_reader is not None else (
            None if memory_reader is not None else lambda: own_private_bytes())
        self._poll = poll_seconds
        self._wait_seconds = wait_seconds
        self._clock = clock
        self._condition = threading.Condition()
        self._in_use = 0        # every reservation, in bytes
        self._in_memory = 0     # how many of them are whole narrations in memory, whose end will free real memory
        self._on_disk = 0       # how many are on disk
        self._private_base: Optional[int] = None  # this process's usage when the current reservations began
        self._starved_since: Optional[float] = None
        self._queue: deque = deque()

    def _read(self) -> Optional[MemoryInfo]:
        return memory_info() if self._reader is None else self._reader()

    def _private(self) -> Optional[int]:
        if self._private_reader is None:
            return None
        try:
            return self._private_reader()
        except (OSError, ValueError, AttributeError, MemoryError):
            return None

    def _allocated(self) -> int:
        """What this process has allocated since the current reservations began, and so is already in any reading."""
        now = self._private()
        if now is None or self._private_base is None:
            return 0
        return max(0, now - self._private_base)

    def _claimed(self) -> int:
        """What has been reserved and is not yet visible in what the operating system reports."""
        return max(0, self._in_use - self._allocated())

    def _disk_has_room(self, memory: Optional[MemoryInfo]) -> bool:
        if memory is None:
            return True
        room = [memory.available]
        room += [value for value in (memory.commit_available, memory.job_headroom) if value is not None]
        if self._claimed() + DISK_ASSEMBLY_BYTES > min(room):
            return False
        if memory.process_headroom is not None:
            # A per-process limit does not cover FFmpeg, which has its own: only this process's part counts against it.
            mine = self._in_use - self._on_disk * (DISK_ASSEMBLY_BYTES - DISK_ASSEMBLY_PROCESS_BYTES) - self._allocated()
            if max(0, mine) + DISK_ASSEMBLY_PROCESS_BYTES > memory.process_headroom:
                return False
        return True

    def _route(self, need: int) -> Optional[bool]:
        """True: assemble in memory. False: on disk. None: not yet."""
        memory = self._read()
        usable = UNKNOWN_MEMORY_ASSEMBLY_BYTES if memory is None else memory_usable(memory)
        if self._claimed() + need <= usable:
            return True
        if self._in_memory:
            return None  # their memory comes back when they finish
        return False if self._disk_has_room(memory) else None

    def _admit(self, need: int, in_memory: bool) -> AssemblyPlace:
        if not self._in_memory and not self._on_disk:
            self._private_base = self._private()
        held = need if in_memory else DISK_ASSEMBLY_BYTES
        self._in_use += held
        self._in_memory += in_memory
        self._on_disk += not in_memory
        self._starved_since = None
        return AssemblyPlace(self, in_memory, held)

    def _give_back(self, place: AssemblyPlace) -> None:
        with self._condition:
            self._in_use -= place._held - DISK_ASSEMBLY_BYTES
            place._held = DISK_ASSEMBLY_BYTES
            self._in_memory -= 1
            self._on_disk += 1
            self._condition.notify_all()

    def _release(self, place: AssemblyPlace) -> None:
        with self._condition:
            self._in_use -= place._held
            self._in_memory -= place.in_memory
            self._on_disk -= not place.in_memory
            if not self._in_memory and not self._on_disk:
                self._private_base = None
            self._condition.notify_all()

    def _nothing_will_change(self) -> bool:
        return not self._in_memory and not self._on_disk

    def _wait_for_memory_holders(self, stop: Optional[Callable[[], bool]] = None) -> None:
        start = self._clock()
        patience = ASSEMBLY_MEMORY_WAIT_SECONDS if self._wait_seconds is None else self._wait_seconds
        while True:
            if stop is not None and stop():
                return
            with self._condition:
                waited = self._clock() - start
                if waited >= patience or (not self._in_memory and waited >= min(patience, DISK_RETRY_PAUSE_SECONDS)):
                    return
                self._condition.wait(self._poll)

    def wake(self) -> None:
        """Wake every waiter now. The panel calls this when Cancel is pressed, so a file waiting at the gate re-reads its cancel
        check at once instead of at its next poll (v0.7.2). Harmless at any other time: a woken waiter that has no reason to
        leave simply waits again."""
        with self._condition:
            self._condition.notify_all()

    @contextlib.contextmanager
    def place(self, need: int, *, cancel_check: Optional[Callable[[], bool]] = None,
              note: Optional[Callable[[str], None]] = None):
        """A place for an assembly of ``need`` bytes for the duration of the ``with`` block: an :class:`AssemblyPlace`. Waits
        while neither route has room.

        ``cancel_check`` ends the wait at once with :class:`ConversionCancelled`, before any route is taken, whatever the file
        was waiting for (v0.7.2: finished narration has no route of its own past a Cancel). Raises :class:`AssemblyMemoryError`
        when, with nothing here left to wait for, too little stayed free for too long. ``note`` is never called with the gate's
        lock held.
        """
        ticket = object()
        told = False
        patience = ASSEMBLY_MEMORY_WAIT_SECONDS if self._wait_seconds is None else self._wait_seconds
        admitted: Optional[AssemblyPlace] = None
        with self._condition:
            self._queue.append(ticket)
        try:
            while admitted is None:
                # Asked with no lock held: it belongs to the run, and may take locks of its own.
                cancelled = cancel_check is not None and cancel_check()
                message = None
                with self._condition:
                    now = self._clock()
                    if cancelled:
                        raise ConversionCancelled("Conversion cancelled by user.")
                    if self._queue[0] is ticket:
                        route = self._route(need)
                        if route is not None:
                            admitted = self._admit(need, route)
                            break
                        if self._nothing_will_change():  # nothing of this run's is going to give memory back
                            self._starved_since = now if self._starved_since is None else self._starved_since
                            if now - self._starved_since >= patience:
                                raise AssemblyMemoryError(
                                    f"Too little memory is free to assemble this file's narration, even on disk (it needs "
                                    f"about {_gb(DISK_ASSEMBLY_BYTES)}), and that did not change for "
                                    f"{round(patience)} seconds. Nothing was saved for this file. Close other programs, "
                                    "then use Retry Failed.")
                        else:
                            self._starved_since = None
                    if not told and note is not None:
                        told = True
                        message = (f"Waiting for memory: this file's narration needs about {_gb(need)} to assemble, and "
                                   "other files are assembling or too little is free. Synthesis of other files continues.")
                    else:
                        self._condition.wait(self._poll)
                if message is not None:
                    _say(note, message)
        finally:
            with self._condition:
                self._queue.remove(ticket)
                if not self._queue:
                    self._starved_since = None
                self._condition.notify_all()
        try:
            if not admitted.in_memory and note is not None:
                why = "and free memory cannot be read here" if self._read() is None else "more than this computer has free now"
                _say(note, f"This file's narration needs about {_gb(need)} to assemble, {why}, so it is being assembled on disk: "
                           "the same audio, using little memory.")
            yield admitted
        finally:
            self._release(admitted)

    @contextlib.contextmanager
    def reserve(self, need: int, *, cancel_check: Optional[Callable[[], bool]] = None,
                note: Optional[Callable[[str], None]] = None):
        """:meth:`place`, for a caller with no use for falling back: yields ``True`` when it may be held in memory and ``False``
        when it must be assembled on disk."""
        with self.place(need, cancel_check=cancel_check, note=note) as admitted:
            yield admitted.in_memory


#: The one gate for this process (one run at a time; a second process's use shows up in the memory reading).
ASSEMBLY_GATE = AssemblyGate()


@contextlib.contextmanager
def assembly_place(pcm_bytes: int, *, cancel_check: Optional[Callable[[], bool]] = None,
                   note: Optional[Callable[[str], None]] = None):
    """A place at :data:`ASSEMBLY_GATE` for assembling this much decoded audio. Below :data:`ASSEMBLY_GATE_MIN_PCM_BYTES` it is
    too little to matter, and takes no reservation."""
    if pcm_bytes < ASSEMBLY_GATE_MIN_PCM_BYTES:
        yield AssemblyPlace(None, True, 0)
        return
    with ASSEMBLY_GATE.place(peak_bytes_for_pcm(pcm_bytes), cancel_check=cancel_check, note=note) as admitted:
        yield admitted


@contextlib.contextmanager
def assembly_slot(pcm_bytes: int, *, cancel_check: Optional[Callable[[], bool]] = None,
                  note: Optional[Callable[[str], None]] = None):
    """:func:`assembly_place` as an answer alone: ``False`` when it must be assembled on disk, ``True`` when it may be held in
    memory. A conversion uses :func:`assemble`, which also handles the answer turning out to be wrong."""
    with assembly_place(pcm_bytes, cancel_check=cancel_check, note=note) as admitted:
        yield admitted.in_memory


def _raise_if_cancelled(cancel_check: Optional[Callable[[], bool]]) -> None:
    if cancel_check is not None and cancel_check():
        raise ConversionCancelled("Conversion cancelled by user.")


def out_of_memory_text(detail: str) -> str:
    """The reason given when even the smallest way of doing this ran out."""
    return ("This computer ran out of memory while converting this file, even assembling it on disk, so nothing was saved for it. "
            f"Close other programs, then use Retry Failed. ({detail})")


def assemble(pcm_bytes: int, in_memory: Callable, on_disk: Callable, *, cancel_check: Optional[Callable[[], bool]] = None,
             note: Optional[Callable[[str], None]] = None):
    """Assemble this much finished audio where the gate says, and return what the route returned.

    If memory runs out on the way, the same parts are assembled on disk: ``in_memory`` and ``on_disk`` must both leave them where
    they were until they have succeeded. The disk route is tried at most twice, the second time after :meth:`AssemblyPlace.wait_for_room`,
    and if it runs out then too, :class:`AssemblyMemoryError` says so. Either way every reservation goes back.

    A Cancel wins at every step (v0.7.2): before the gate, before any fall back to disk and before any further attempt, it ends
    this with :class:`ConversionCancelled` and nothing more is tried; an assembly already running is killed by
    :mod:`tts.ffmpeg_watch`, which raises the same.
    """
    _raise_if_cancelled(cancel_check)
    with assembly_place(pcm_bytes, cancel_check=cancel_check, note=note) as admitted:
        if admitted.in_memory:
            try:
                return in_memory()
            except Exception as exc:  # noqa: BLE001 - only an allocation failure is taken further, below
                if not is_memory_failure(exc):
                    raise
            # A Cancel during the join: no fall back, nothing more is built.
            _raise_if_cancelled(cancel_check)
            # Out of that block, so the failed attempt's frames, and all it managed to build, have gone already. What it left on
            # disk goes too: the disk route is about to need that room.
            admitted.to_disk()
            from tts import ffmpeg_watch

            ffmpeg_watch.remove_temporaries()
            _say(note, "Memory ran out while assembling this file's narration, so it is being assembled on disk instead: the "
                       "same audio, using little memory. Nothing is being requested from the voice service again.")
        for attempt in range(2):
            _raise_if_cancelled(cancel_check)
            try:
                return on_disk()
            except Exception as exc:  # noqa: BLE001
                if not is_memory_failure(exc):
                    raise
                detail = f"{type(exc).__name__}: {exc}"[:200]
            if attempt == 0:
                admitted.wait_for_room(cancel_check)
        _raise_if_cancelled(cancel_check)
        raise AssemblyMemoryError(out_of_memory_text(detail))


def sample_rate(path) -> int:
    """The sample rate of a finished audio file, from its header."""
    import mutagen

    return mutagen.File(path).info.sample_rate


def decoded_size(paths: Iterable) -> int:
    """How many PCM bytes these finished audio files (FLAC, MP3) decode to, from their headers. Decodes nothing."""
    import mutagen

    total = 0
    for path in paths:
        try:
            info = mutagen.File(path).info
            width = max(2, math.ceil(getattr(info, "bits_per_sample", 16) / 8))
            total += math.ceil(info.length * info.sample_rate * info.channels * width)
        except Exception:  # noqa: BLE001 - not understood: size it from its bytes, generously
            try:
                total += os.path.getsize(path) * UNREADABLE_AUDIO_EXPANSION
            except OSError:
                pass
    return total


# --------------------------------------------------------------------------- the machine


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
    except (OSError, ValueError, AttributeError, MemoryError):
        return None
    return None


def own_private_bytes() -> Optional[int]:
    """What this process has committed (Windows) or holds in memory (Linux), or ``None`` where that cannot be read."""
    try:
        if sys.platform == "win32":
            return _windows_private_bytes()
        if sys.platform.startswith("linux"):
            with open("/proc/self/statm", encoding="ascii") as handle:
                return int(handle.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, AttributeError, MemoryError, IndexError):
        return None
    return None


def _windows_private_bytes() -> Optional[int]:
    import ctypes
    import ctypes.wintypes as wt

    class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
        _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD)] + [(name, ctypes.c_size_t) for name in (
            "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
            "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage", "PrivateUsage")]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wt.HANDLE
    kernel32.K32GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX), wt.DWORD]
    counters = PROCESS_MEMORY_COUNTERS_EX()
    counters.cb = ctypes.sizeof(counters)
    if not kernel32.K32GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        return None
    return int(counters.PrivateUsage)


def _windows_job_headroom() -> tuple[Optional[int], Optional[int]]:
    """``(process, job)``: what is left under a memory limit of the Job Object this process is in. ``None``: no such limit that
    can be read. A process in nested jobs is reported on by its innermost, which is what Windows answers with."""
    import ctypes
    import ctypes.wintypes as wt

    process_limit_flag, job_limit_flag = 0x100, 0x200
    extended_limit_information, memory_usage_information = 9, 28

    class BASIC(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", wt.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wt.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wt.DWORD), ("SchedulingClass", wt.DWORD)]

    class IO(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in ("r", "w", "o", "rb", "wb", "ob")]

    class EXTENDED(ctypes.Structure):
        _fields_ = [("Basic", BASIC), ("Io", IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    class USAGE(ctypes.Structure):
        _fields_ = [("JobMemory", ctypes.c_ulonglong), ("PeakJobMemoryUsed", ctypes.c_ulonglong)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    query = kernel32.QueryInformationJobObject
    query.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p]
    limits = EXTENDED()
    if not query(None, extended_limit_information, ctypes.byref(limits), ctypes.sizeof(limits), None):
        return None, None  # in no job, or one this process may not ask about
    process = job = None
    if limits.Basic.LimitFlags & process_limit_flag:
        private = _windows_private_bytes()
        if private is not None:
            process = int(limits.ProcessMemoryLimit) - private
    if limits.Basic.LimitFlags & job_limit_flag:
        usage = USAGE()
        if query(None, memory_usage_information, ctypes.byref(usage), ctypes.sizeof(usage), None):
            job = int(limits.JobMemoryLimit) - int(usage.JobMemory)
    return process, job


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
    process, job = _windows_job_headroom()
    return MemoryInfo(int(status.ullAvailPhys), int(status.ullTotalPhys), int(status.ullAvailPageFile), process, job)


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


# --------------------------------------------------------------------------- the workload


@dataclass(frozen=True)
class NarrationSettings:
    """The run's frozen settings that change how long a narration lasts."""

    sentence_pause_ms: int = DEFAULT_SENTENCE_PAUSE_MS
    paragraph_pause_ms: int = DEFAULT_PARAGRAPH_PAUSE_MS
    title_pause_ms: int = DEFAULT_TITLE_PAUSE_MS
    chapter_pause_ms: int = DEFAULT_CHAPTER_PAUSE_MS
    trim_padding: bool = True
    rate: str = "+0%"     # the folder route only: the direct route sends no rate
    speech_prep: object = None

    @classmethod
    def for_run(cls, pause_kw: dict, rate: str, speech_prep) -> "NarrationSettings":
        return cls(sentence_pause_ms=int(pause_kw.get("sentencepause", DEFAULT_SENTENCE_PAUSE_MS)),
                   paragraph_pause_ms=int(pause_kw.get("paragraphpause", DEFAULT_PARAGRAPH_PAUSE_MS)),
                   title_pause_ms=int(pause_kw.get("title_trailing_pause", DEFAULT_TITLE_PAUSE_MS)),
                   chapter_pause_ms=int(pause_kw.get("chapter_trailing_pause", DEFAULT_CHAPTER_PAUSE_MS)),
                   trim_padding=bool(pause_kw.get("trim_tts_padding", True)),
                   rate=str(rate), speech_prep=speech_prep)

    def speed(self) -> float:
        """The rate as a multiple of normal speed. Edge refuses a malformed rate; here that reads as normal speed."""
        match = re.fullmatch(r"\s*([+-]?\d+(?:\.\d+)?)\s*%\s*", self.rate or "")
        return max(0.1, 1 + float(match.group(1)) / 100) if match else 1.0


@dataclass(frozen=True)
class QueuedSource:
    path: Path
    direct: bool = True  # the route with inserted pauses; False is the folder route


class SourceEstimate(NamedTuple):
    seconds: float            # the whole narration
    longest_paragraph: float  # the part of it in memory at once during synthesis, when that is long enough to matter
    basis: str                # "text", "sampled", "length" (out of time, or not readable), or "unreadable"


_SPOKEN_SYMBOLS = "%&@#$+=/*\\~^|<>_"
_INNER_PUNCTUATION = re.compile(r"[.:?,](?=\w)")   # "3.14", "example.com": read out
_WORD = re.compile(r"\S+")
_SENTENCE_END = re.compile(r"[.?!]+(?!\w)")        # NLTK's Punkt can end a sentence only at one of these
# Tried only where a run of these begins, and never given back: otherwise a long run of dots inside a line costs the
# square of its length, and planning must stay bounded whatever a source holds.
_LINE_END = re.compile(r"(?<![.?!])[.?!]++[\"'”’)\]]*+[ \t]*+\r?$", re.MULTILINE)
_PARAGRAPH = re.compile(r"^(?![ \t]*#).*\w.*$", re.MULTILINE)
_HEADING = re.compile(r"^[ \t]*#.*\w", re.MULTILINE)
_COMMA = re.compile(r",(?!\d)\s")                  # epub2tts_edge.intra_sentence_chunks's own patterns, from here on
_ELLIPSIS = re.compile(r"\.\.\.")
_DASH = re.compile(r"—|--")
_LONG_LINE = re.compile(rf"^.{{{LONG_PARAGRAPH_CHARS},}}$", re.MULTILINE)


def _count(pattern: re.Pattern, text: str) -> int:
    return sum(1 for _ in pattern.finditer(text))  # never builds the list of matches a long text would make


def estimate_text_seconds(text: str, *, direct: bool = True, settings: NarrationSettings = NarrationSettings()) -> float:
    """How long this text's narration lasts at most, roughly: linear in the text, and it synthesises nothing.

    The counts are upper bounds on what the engine will do. Every sentence ``sent_tokenize`` finds ends at a character
    :data:`_SENTENCE_END` counts; abbreviations count too, and so add a pause the audio will not have.
    """
    digits = sum(text.count(digit) for digit in "0123456789")
    symbols = sum(text.count(symbol) for symbol in _SPOKEN_SYMBOLS) + _count(_INNER_PUNCTUATION, text)
    ordinary = max(0, len(text) - digits - symbols)
    speech = max(ordinary / NARRATION_CHARS_PER_SECOND + digits * DIGIT_SECONDS + symbols * SYMBOL_SECONDS,
                 _count(_WORD, text) * MIN_WORD_SECONDS)
    ends, commas, ellipses, dashes = (_count(pattern, text) for pattern in (_SENTENCE_END, _COMMA, _ELLIPSIS, _DASH))
    if not direct:
        natural = (ends * NATURAL_SENTENCE_SECONDS + commas * NATURAL_COMMA_SECONDS
                   + ellipses * NATURAL_ELLIPSIS_SECONDS + dashes * NATURAL_DASH_SECONDS)
        chunks = max(1, math.ceil(len(text) / FOLDER_CHUNK_CHARS))
        return ((speech + natural + chunks * CLIP_PADDING_SECONDS) / settings.speed()
                + chunks * FOLDER_CHUNK_PAUSE_SECONDS)
    paragraphs, headings = _count(_PARAGRAPH, text), _count(_HEADING, text)
    inner_ends = max(0, ends - _count(_LINE_END, text))  # a paragraph's last sentence takes the paragraph pause instead
    clips = paragraphs + inner_ends + commas + ellipses + dashes
    pauses_ms = (inner_ends * settings.sentence_pause_ms + paragraphs * settings.paragraph_pause_ms
                 + commas * COMMA_PAUSE_MS + ellipses * ELLIPSIS_PAUSE_MS + dashes * EM_DASH_PAUSE_MS
                 + headings * settings.title_pause_ms + max(0, headings - 1) * settings.chapter_pause_ms)
    padding = (headings + (0 if settings.trim_padding else clips)) * CLIP_PADDING_SECONDS  # a title clip is never trimmed
    return speech + pauses_ms / 1000 + padding


def _longest_paragraph_seconds(text: str, settings: NarrationSettings) -> float:
    """A direct paragraph stays in memory until it is whole. An ordinary line is too short to count against the base."""
    return max((estimate_text_seconds(match.group(), settings=settings) for match in _LONG_LINE.finditer(text)),
               default=0.0)


def _prepared(text: str, direct: bool, settings: NarrationSettings) -> str:
    """The text this route will really speak, under the run's own frozen speech preparation, when that is on."""
    snapshot = settings.speech_prep
    if snapshot is None or not getattr(snapshot, "enabled", False) or len(text) > PREPARE_SCAN_CHARS:
        return text
    from tts.speech.pipeline import prepare
    from tts.speech.profiles import EDGE_DIRECT, EDGE_FOLDER

    prepared = prepare(text, snapshot, EDGE_DIRECT if direct else EDGE_FOLDER)
    return prepared.spoken_source if direct else prepared.text


def _read_for_sizing(path: Path, size: int) -> tuple[str, float]:
    """A TXT's text and how much of the file it stands for. Bytes that do not decode still have a length to count, and a
    lone carriage return ends a line here as it does when the engine reads the file."""
    with open(path, "rb") as handle:
        data = handle.read(TXT_SCAN_BYTES)
    scale = size / len(data) if data and size > len(data) else 1.0
    return data.decode("utf-8-sig", "replace").replace("\r\n", "\n").replace("\r", "\n"), scale


def _rough_seconds(size: int, source: QueuedSource, settings: NarrationSettings) -> float:
    """All that is known is a length. For a PDF that is not even its text, which errs on the long side."""
    if source.direct:
        return size * (1 / ROUGH_CHARS_PER_SECOND + settings.paragraph_pause_ms / 1000 / ROUGH_CHARS_PER_PARAGRAPH)
    return size / ROUGH_CHARS_PER_SECOND / settings.speed()


def _from_text(text: str, scale: float, read_all: bool, source: QueuedSource, settings: NarrationSettings) -> SourceEstimate:
    spoken = _prepared(text, source.direct, settings)
    seconds = estimate_text_seconds(spoken, direct=source.direct, settings=settings)
    # The folder route's chunks are on disk. In a sample, a paragraph that continues from one page read to the next also
    # runs through the pages between them, so it is scaled up with everything else.
    longest = _longest_paragraph_seconds(spoken, settings) * scale if source.direct else 0.0
    return SourceEstimate(seconds * scale, longest, "text" if read_all else "sampled")


def _estimate_source(source: QueuedSource, settings: NarrationSettings,
                     keep_reading: Callable[[], bool] = lambda: True) -> SourceEstimate:
    """One source's narration estimate. Asks ``keep_reading`` before reading anything, and between a PDF's pages."""
    path = Path(source.path)
    try:
        size = path.stat().st_size
    except OSError:
        return SourceEstimate(0.0, 0.0, "unreadable")
    rough = _rough_seconds(size, source, settings)
    if not keep_reading():
        return SourceEstimate(rough, rough, "length")
    if path.suffix.lower() == ".pdf":
        from tts import pdf_extractor

        sample = pdf_extractor.pdf_text_sample(str(path), PDF_SCAN_PAGES, keep_reading)
        if sample is None:
            return SourceEstimate(0.0, 0.0, "unreadable")
        pages, read, text = sample
        if pages and not read:
            return SourceEstimate(rough, rough, "length")
        return _from_text(text, pages / read if read else 1.0, read >= pages, source, settings)
    try:
        text, scale = _read_for_sizing(path, size)
    except OSError:  # locked or refused for now: it has a length, and may be readable by the time its turn comes
        return SourceEstimate(rough, rough, "length")
    return _from_text(text, scale, scale <= 1.0, source, settings)


def plan_for_sources(requested, backend: str, sources: Iterable, *, settings: Optional[NarrationSettings] = None,
                     should_stop: Optional[Callable[[], bool]] = None,
                     clock: Callable[[], float] = time.monotonic) -> WorkerPlan:
    """:func:`plan_workers` for real files on this machine. ``sources`` holds :class:`QueuedSource` (a bare path means
    the direct route, whose pauses make it the longer of the two). Runs on the worker thread: it reads the queue's text,
    within :data:`PLAN_SCAN_SECONDS`, and stops as soon as ``should_stop`` says the run was cancelled."""
    queued = [source if isinstance(source, QueuedSource) else QueuedSource(source) for source in sources]
    empty = budget_for_seconds(0.0)
    if backend != EDGE:
        return plan_workers(requested, backend, [empty] * len(queued), cpu_count=None, memory=None)
    if min(int(requested), len(queued)) <= 1:  # one file at a time, whatever the files hold: there is nothing to read
        return plan_workers(requested, backend, [empty] * len(queued), cpu_count=logical_cpus(), memory=memory_info())
    settings = NarrationSettings() if settings is None else settings
    deadline = clock() + PLAN_SCAN_SECONDS
    stopped = (lambda: False) if should_stop is None else should_stop
    budgets: list[FileBudget] = []
    unmeasured: dict[str, int] = {}
    too_long = 0
    for source in queued:
        if stopped():  # the run is over: no file needs opening, or even looking at, to decide that
            budgets.append(empty)
            continue
        try:
            estimate = _estimate_source(source, settings, lambda: clock() < deadline and not stopped())
        except Exception:  # noqa: BLE001 - sizing must never cost a run: this file will succeed or fail on its own turn
            estimate = SourceEstimate(0.0, 0.0, "unreadable")
        budgets.append(budget_for_seconds(estimate.seconds, estimate.longest_paragraph))
        if estimate.basis != "text":
            unmeasured[estimate.basis] = unmeasured.get(estimate.basis, 0) + 1
        too_long += estimate.seconds >= LONGEST_NARRATION_SECONDS
    notes = []
    if unmeasured.get("sampled"):
        notes.append(f"{unmeasured['sampled']} very long file(s) were sized from a sample of their text")
    if unmeasured.get("length"):
        notes.append(f"{unmeasured['length']} file(s) could not be read in time and were sized from their length")
    if unmeasured.get("unreadable"):
        notes.append(f"{unmeasured['unreadable']} file(s) could not be opened, so their size is not counted")
    if notes:
        notes.append("each file's real size is checked again before it is assembled")
    if too_long:
        notes.append(f"{too_long} file(s) may be too long for one MP3 (the limit is about 24 hours of narration)")
    return plan_workers(requested, backend, budgets, cpu_count=logical_cpus(), memory=memory_info(), notes=notes)
