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
While a file is being synthesised it holds about one paragraph in memory (the rest is on disk); then its whole narration
is decoded into memory for the one MP3 encode.

*During the run, a measurement.* Immediately before a narration is decoded into memory, :data:`ASSEMBLY_GATE` is given
its real size, read from the finished audio files' headers. Assemblies overlap only while everything reserved fits in
what is usable now; otherwise a file waits its turn, first come first served, while synthesis on every other worker
carries on. A single assembly always runs: however large, it is the job.

*Before the run, a model.* Each queued file's narration is estimated from its real text and the run's frozen settings
(:func:`estimate_text_seconds`). The run keeps ``max(1 GiB, 25 % of physical memory)`` free for Windows and other
programs, and admits as many files as fit in the rest with **the largest single assembly** on top of **each file's
synthesis memory**: the gate is what keeps several assemblies from being added together. So a queue of whole novels runs
side by side and takes turns to assemble, while a machine that could not hold even one of those assemblies, or a source
with no paragraph breaks (its whole narration is in memory during synthesis), is held back. The model is an upper
estimate, not a measurement of the file, and it stays bounded: a source is never synthesised, a PDF is read for at most
:data:`PDF_SCAN_PAGES` pages, and the whole queue for at most :data:`PLAN_SCAN_SECONDS`, checked between pages, after
which a source is sized from its length and the log says so.

*What cannot be bounded in advance.* Nothing says a PDF's text can be known without reading it, a sample cannot see a
page it did not read, and a source can change after planning. The gate covers what such a source does at assembly. It
cannot cover a long paragraph the model did not see: that one's memory builds up during synthesis and is reserved only
when it is joined.

**What each number is.** *Measured on HOME-PC, Windows 11:* Edge audio is 24 kHz mono 16-bit, 48,000 PCM bytes per second,
for all five voices; the peak was 144-150 KB per narration second on the direct route, pause-heavy files included, and
115 KB/s on the folder route (:data:`PEAK_BYTES_PER_NARRATION_SECOND` rounds up); FFmpeg children 22-24 MB. Speech (real
Edge, ``Steffan``, ``Andrew``, ``Aria``, ``Ava``, ``Jenny``; ``files/dev-work/act071-remediation/logs/``, ignored): prose at
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

Standard library and ``shared.cancellation`` at import time; ``mutagen`` and ``pdf_extractor`` are imported when used, so
PyMuPDF stays behind its lock.
"""

from __future__ import annotations

import contextlib
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
#: What the plan assumes is usable where free memory cannot be read. An assumption, not a measurement: enough for a
#: queue of ordinary files, and too little for several sources that hold whole books in memory.
UNKNOWN_MEMORY_PLAN_BYTES = 4 * 1024 ** 3
#: How much may assemble at once where free memory cannot be read. An assumption too: beyond it, files take turns.
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
            usable = memory.available - reserve
            situation = f"{_gb(memory.available)} free, {_gb(reserve)} kept for Windows and other programs"
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


class AssemblyGate:
    """Admits whole-narration assemblies by their real size, one process's worth, first come first served."""

    def __init__(self, memory_reader: Optional[Callable[[], Optional[MemoryInfo]]] = None, poll_seconds: float = 0.25):
        self._reader = memory_reader
        self._poll = poll_seconds
        self._condition = threading.Condition()
        self._in_use = 0
        self._queue: deque = deque()

    def _read(self) -> Optional[MemoryInfo]:
        return memory_info() if self._reader is None else self._reader()

    def _fits(self, need: int) -> bool:
        if self._in_use == 0:  # one assembly always runs: it is the job, and nothing else competes for the memory
            return True
        memory = self._read()
        if memory is None:
            return self._in_use + need <= UNKNOWN_MEMORY_ASSEMBLY_BYTES
        # All that is reserved is counted against what is free now, though what has been allocated is already gone from
        # it: there is no telling which has been, and a wrongly counted assembly only makes this one wait a little.
        return self._in_use + need <= memory.available - memory_reserve(memory)

    @contextlib.contextmanager
    def reserve(self, need: int, *, cancel_check: Optional[Callable[[], bool]] = None,
                note: Optional[Callable[[str], None]] = None):
        """Hold ``need`` bytes of assembly budget for the duration of the ``with`` block. Waits while it does not fit.

        ``cancel_check`` is for a file with more synthesis still to come, which a Cancel would stop anyway: it raises
        :class:`ConversionCancelled` from the wait. A finished narration passes none, and is assembled in its turn.
        """
        ticket = object()
        told = False
        with self._condition:
            self._queue.append(ticket)
            try:
                while not (self._queue[0] is ticket and self._fits(need)):
                    if cancel_check is not None and cancel_check():
                        raise ConversionCancelled("Conversion cancelled by user.")
                    if not told and note is not None:
                        told = True
                        note(f"Waiting for memory: this file's narration needs about {_gb(need)} to assemble, and "
                             "other files are assembling. Synthesis of other files continues.")
                    self._condition.wait(self._poll)
            finally:
                self._queue.remove(ticket)
                self._condition.notify_all()
            alone = self._in_use == 0
            self._in_use += need
        try:
            if alone and note is not None:
                memory = self._read()
                if memory is not None and need > memory.available - memory_reserve(memory):
                    note(f"This file's narration needs about {_gb(need)} to assemble, more than this computer has "
                         "free now, so this step may be slow. Closing other programs would help.")
            yield
        finally:
            with self._condition:
                self._in_use -= need
                self._condition.notify_all()


#: The one gate for this process (one run at a time; a second process's use shows up in the memory reading).
ASSEMBLY_GATE = AssemblyGate()


@contextlib.contextmanager
def assembly_slot(pcm_bytes: int, *, cancel_check: Optional[Callable[[], bool]] = None,
                  note: Optional[Callable[[str], None]] = None):
    """A place at :data:`ASSEMBLY_GATE` for joining this much decoded audio in memory, when it is enough to matter."""
    if pcm_bytes < ASSEMBLY_GATE_MIN_PCM_BYTES:
        yield
        return
    with ASSEMBLY_GATE.reserve(peak_bytes_for_pcm(pcm_bytes), cancel_check=cancel_check, note=note):
        yield


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
    longest = _longest_paragraph_seconds(spoken, settings) if source.direct else 0.0  # the folder route's chunks are on disk
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
