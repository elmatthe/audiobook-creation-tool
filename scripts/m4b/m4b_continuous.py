"""One continuous decode per eligible split book (v0.7.2 Phase 7B, ACT72-012).

**Why.** The seeking route (``m4b_commands.segment_argv``) puts ``-ss`` after ``-i`` on purpose: FFmpeg decodes the book
from its first sample and throws away everything before the chapter, so every kept sample is fully reconstructed. The
price is that chapter *k* decodes chapters 1..k-1 again: about 1.3-1.6 s of discarded decoding per hour of book before
each chapter, measured in Phase 7A, so a split costs chapters x book length. A 12-hour book in 24 chapters spent about
215 s of a 470 s run decoding audio it then discarded.

**What this route does instead.** One FFmpeg decodes the whole book once, to the AAC decoder's own float samples
(``pcm_f32le``: exact, nothing rounded), and the worker hands each chapter's encoder exactly the samples the seeking
route would have kept, through the pipe seam the Windows xHE route already uses (``m4b_commands.pcm_argv`` and
``m4b_execution.run_argv_streaming``). Everything after the audio pass is the seeking route's: the same encoder and
quality, the separate cover pass, the ffprobe measurement and drift guard, staging, refusal and publication. Phase 7A
measured the result byte-identical to the seeking route on every eligible book, and that is the contract: where this
route applies, every output byte is the same.

**Which samples.** Phase 7A measured what the output-side seek selects, on 226 chapters of six books, by exact sample
equality: chapter *k* is decoded samples ``[half_up(S * rate), half_up(S * rate) + half_up(D * rate))``, where ``S`` and
``D`` are the integer microseconds in the ``-ss`` and ``-t`` strings the seeking route writes (``segment_times``) and
``half_up`` rounds a half upwards. Each chapter is cut at its own absolute position, never by adding up rounded
durations, which would drift. Rounding can make neighbours overlap or leave a gap of a sample: an overlap is served from
the last samples already read, a gap is read and dropped, exactly as the seeking route does.

**When.** Only when the one preflight probe proves the book is the kind Phase 7A qualified, a packet scan proves its
timestamps are the sample count, the FFmpeg build is one the route is qualified on, and the estimated saving is large
enough (``qualify``). Anything else keeps the seeking route, byte for byte, including its pinned command line: a sample
rate LAME does not take (the seeking route resamples before it cuts), more than two channels, an unknown layout, HE-AAC,
the Windows decoder, a non-zero start, an edit list other than one AAC frame of priming, a timestamp that is not the
running sample count, another FFmpeg build, or a book with too little prefix for its length. The choice is frozen into
the plan at preflight and never changes during the run or a retry.

**Bounded.** At most one 256 KiB block and one second of already-read samples are held (well under 1 MiB at 48 kHz
stereo); nothing is written to disk; the pipes are the back-pressure. The decoder is one more owned process: Cancel
stops it as well as the encoder, every route out of a book closes and reaps it, and a retry starts a fresh one.

**Never a quiet shortfall.** End of stream counts only if the decoder exited 0 having produced exactly the number of
samples the book declares; a short feed before the end, a stream ending part-way through a sample, a decoder that
failed or was killed, all fail the chapter, which takes its book back as any failed chapter does. Nothing falls back to
the seeking route part-way through a book.
"""

from __future__ import annotations

import collections
import contextlib
import functools
import hashlib
import shutil
import subprocess
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from shared import ffmpeg_utils
from shared import output_paths
from shared import subprocess_utils as sp

from m4b import m4b_commands
from m4b.m4b_chapters import ChapterUsability, plan_timeline, validate_chapters
from m4b.m4b_execution import tail_of

#: Sample rates libmp3lame takes as they are. At any other rate FFmpeg resamples the *continuous* stream before the
#: seeking route cuts it, which this route cannot reproduce (Phase 7A: a 96 kHz book differed at -100 dB), so such a
#: book keeps the seeking route.
LAME_RATES = frozenset({8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000})

#: The only layouts this route takes: the encoder is told ``-ac N`` and FFmpeg's default layout for N must be the one
#: the decoder reported.
LAYOUTS = {1: "mono", 2: "stereo"}

#: Samples in one AAC-LC frame. Every packet but the last must hold exactly this many for its timestamp to be the
#: running sample count.
AAC_FRAME_SAMPLES = 1024

#: Which books gain, decided by an estimate in seconds of audio. The seeking route decodes every chapter's start again
#: (the prefix, P: every chapter's start added up); the continuous route instead moves the whole book (its duration, D)
#: through a pipe as float samples, which costs more per second than a decode: measured 1.9-2.4 times a decode on the
#: qualification machine (Phase 7B, k-measurement.json), so the continuous route saves work only where P exceeds about
#: 1.4 x D. This constant is that figure rounded up, so the estimate is conservative.
PREFIX_PER_BOOK_SECOND = 2.0

#: The smallest estimated saving, P - PREFIX_PER_BOOK_SECOND x D, for which a book takes the continuous route; below it
#: the seeking route is kept. Byte-identical either way, so this is purely a speed choice: a book's extra decoder and
#: packet scan cost more than a short book saves (Phase 7A: +24 % on 10 chapters of 1.5 s), and a book of a few long
#: chapters has little prefix to save for its length. Calibrated and frozen in Phase 7B from measured small books before
#: final qualification, and not to be moved to rescue a failed qualification run (record section 13; budget T2).
MIN_SAVED_PREFIX_SECONDS = 600.0

#: The FFmpeg/ffprobe pairs the route is qualified on. Byte identity between the two routes is established per build
#: (the m4b-scaling qualification and its pinned reference, files/dev-work/verification-gate/scaling/reference.json); on
#: any other build every book keeps the seeking route until that build is qualified and added here. Each executable is
#: named by a fingerprint, the SHA-256 of its size and its first and last MiB, which tells builds apart without reading
#: 200 MB per run; the reference records the full SHA-256 of the same files beside it. The one entry is FFmpeg 9.0.1
#: full_build from gyan.dev: the application's portable pin (shared/ffmpeg_portable.py) and the winget Gyan.FFmpeg 9.0.1
#: package, which is the same archive.
QUALIFIED_BUILDS = frozenset({
    ("5e36fdd9b6cf697710a7781db3e84f26c4bb141a08ef53b5d3373eb326aa9f24",
     "d5b42dc3f9cc71cec401c6ce5346b8ab556ac55fe79643804ebbdb98b05b7353"),
})

#: How much decoded audio is read from the decoder at once.
READ_BLOCK_BYTES = 1 << 18  # 256 KiB
#: How much already-read audio is kept for a chapter that starts before the previous one ended (rounding: a sample).
TAIL_SECONDS = 1
#: The route never holds more audio than this, whatever the book's length (Phase 7A budget T4).
MAX_BUFFERED_BYTES = 1 << 20

#: How long the packet scan may take before it is given up as unproven: a fixed allowance plus some per hour of audio.
#: Measured about 0.45 s per hour on the qualification machine; generous so a slow disk is not mistaken for a defect.
SCAN_BASE_SECONDS = 30.0
SCAN_SECONDS_PER_HOUR = 20.0

_POLL_SECONDS = 0.05
_GRACE_SECONDS = 2.0


class ContinuousDecodeError(RuntimeError):
    """The decoder's audio cannot be trusted for this chapter. Never a silent shortfall."""


@dataclass(frozen=True, slots=True)
class ContinuousRoute:
    """The frozen facts a book's continuous decode is cut by. Decided once, at preflight."""

    sample_rate: int
    channels: int
    #: The samples the book declares (the stream's ``duration_ts``), proven equal to the packet timeline's total.
    total_samples: int

    @property
    def frame_bytes(self) -> int:
        return 4 * self.channels

    def pcm_args(self) -> tuple[str, ...]:
        """How the encoder reads the pipe: the decoder's own float samples, interleaved."""
        return ("-f", "f32le", "-ar", str(self.sample_rate), "-ac", str(self.channels))


@dataclass(frozen=True, slots=True)
class RouteDecision:
    """Which audio route one book takes, and why. ``route`` is ``None`` for the seeking route."""

    route: ContinuousRoute | None
    reason: str
    scan_seconds: float = 0.0

    @property
    def continuous(self) -> bool:
        return self.route is not None


# --------------------------------------------------------------------------- #
# Which samples a chapter is
# --------------------------------------------------------------------------- #


def micros(text: str) -> int:
    """The integer microseconds FFmpeg parses from a ``-ss``/``-t`` string written fixed-point to six places."""
    whole, _, fraction = text.partition(".")
    if not whole.isdigit() or len(fraction) != 6 or not fraction.isdigit():
        raise ValueError(f"not a fixed-point microsecond time: {text!r}")
    return int(whole) * 1_000_000 + int(fraction)


def half_up(numerator: int, denominator: int) -> int:
    """``numerator / denominator`` rounded to the nearest integer, a half upwards (both non-negative)."""
    return (2 * numerator + denominator) // (2 * denominator)


def chapter_frames(start: float, end: float, sample_rate: int) -> tuple[int, int]:
    """The first sample and the sample count the seeking route keeps for ``[start, end)``."""
    begin, span = m4b_commands.segment_times(start, end)
    return (half_up(micros(begin) * sample_rate, 1_000_000),
            half_up(micros(span) * sample_rate, 1_000_000))


def prefix_seconds(starts: Iterable[float]) -> float:
    """The audio the seeking route would decode and discard for a book: every chapter's start, added up."""
    return float(sum(float(start) for start in starts))


def saved_seconds(starts: Iterable[float], duration: float) -> float:
    """The estimated saving of the continuous route, in seconds of audio: the prefix it does not decode again, less the
    cost of moving the whole book through a pipe (``PREFIX_PER_BOOK_SECOND`` per second of book)."""
    return prefix_seconds(starts) - PREFIX_PER_BOOK_SECOND * float(duration)


# --------------------------------------------------------------------------- #
# Eligibility, decided at preflight
# --------------------------------------------------------------------------- #


def executable_fingerprint(path) -> str:
    """The SHA-256 of a file's size and its first and last MiB: a build's identity, read in a few milliseconds."""
    path = Path(path)
    size = path.stat().st_size
    digest = hashlib.sha256(str(size).encode("ascii") + b"\0")
    with open(path, "rb") as handle:
        digest.update(handle.read(1 << 20))
        handle.seek(max(0, size - (1 << 20)))
        digest.update(handle.read(1 << 20))
    return digest.hexdigest()


@functools.lru_cache(maxsize=8)
def _cached_fingerprint(path: str, size: int, modified: int) -> str:
    return executable_fingerprint(path)


def _identity(command: str) -> str | None:
    found = shutil.which(command) or command
    try:
        stat = Path(found).stat()
        return _cached_fingerprint(str(Path(found).resolve()), stat.st_size, stat.st_mtime_ns)
    except OSError:
        return None


def build_refusal(ffmpeg: str | None = None, ffprobe: str | None = None) -> str | None:
    """Why this machine's FFmpeg pair is not one the route is qualified on, or ``None``. Asked only for a book that has
    already passed every other test; each executable's fingerprint is remembered while its size and time are unchanged."""
    pair = (_identity(ffmpeg or ffmpeg_utils.ffmpeg_cmd()), _identity(ffprobe or ffmpeg_utils.ffprobe_cmd()))
    if None in pair:
        return "the FFmpeg executables could not be identified"
    if pair not in QUALIFIED_BUILDS:
        return f"FFmpeg build {pair[0][:12]}/{pair[1][:12]} is not qualified for this route"
    return None


def static_refusal(report, *, split: bool) -> str | None:
    """Why the probe alone rules this book out of the continuous route, or ``None``. Pure: no process, no file."""
    if not split:
        return "whole-book output"
    if validate_chapters(report.probe).usability is not ChapterUsability.CHAPTERED:
        return "not a chaptered book"
    if report.undecodable_xhe:
        return "xHE-AAC: not decoded by FFmpeg here"
    if tuple(report.decoder_args):
        return "a decoder other than FFmpeg's own AAC decoder"
    if report.artwork is not None:
        return "artwork ambiguous"
    facts = report.stream
    if facts is None:
        return "the probe reported no stream facts"
    if facts.audio_streams != 1:
        return f"{facts.audio_streams} audio streams"
    if facts.codec_name != "aac" or facts.profile != "LC":
        return f"codec {facts.codec_name or '?'} profile {facts.profile or '?'}, not AAC-LC"
    if facts.sample_fmt != "fltp":
        return f"sample format {facts.sample_fmt or '?'}, not fltp"
    if facts.sample_rate not in LAME_RATES:
        return f"sample rate {facts.sample_rate}, which LAME does not take as it is"
    if facts.channels not in LAYOUTS or facts.channel_layout != LAYOUTS[facts.channels]:
        return f"{facts.channels} channels, layout {facts.channel_layout or '?'}"
    if facts.time_base != f"1/{facts.sample_rate}":
        return f"time base {facts.time_base or '?'}, not 1/{facts.sample_rate}"
    if facts.start_pts != 0:
        return f"start_pts {facts.start_pts}, not 0"
    if not facts.duration_ts or facts.duration_ts <= 0:
        return "no declared sample count"
    if facts.initial_padding not in (0, AAC_FRAME_SAMPLES):
        return f"initial padding {facts.initial_padding}, not 0 or one AAC frame"
    return None


def check_packet_lines(lines: Iterable[bytes], *, total: int, priming: int,
                       frame: int = AAC_FRAME_SAMPLES) -> str | None:
    """Whether the packet timeline proves that a sample's timestamp is its index. ``None`` when it does, else why not.

    *lines* are ffprobe's ``pts,duration,flags`` for the audio stream, in order. Proven means: at most one leading packet
    discarded as priming, exactly one AAC frame before sample 0, and present only when the stream declares that
    padding; then packets that start at 0 and follow each other with no gap and no overlap, every one a whole AAC frame
    except the last; none marked corrupt; and their durations adding up to the declared sample count. Then the decoded
    samples, counted from the first kept one, are the timeline the seeking route trims by.
    """
    expected = 0
    kept = 0
    total_kept = 0
    discarded = 0
    previous = None
    for raw in lines:
        text = raw.strip()
        if not text:
            continue
        parts = text.split(b",")
        if len(parts) < 3:
            return f"an unreadable packet line {text[:40]!r}"
        try:
            pts, duration = int(parts[0]), int(parts[1])
        except ValueError:
            return f"a packet without a timestamp or duration ({text[:40]!r})"
        flags = parts[2]
        if b"C" in flags:
            return f"a packet marked corrupt at {pts}"
        if b"D" in flags:
            if kept or discarded:
                return f"a discarded packet at {pts}, not only one before the start"
            if pts != -frame or duration != frame:
                return f"priming of {duration} samples at {pts}, not one AAC frame"
            discarded += 1
            continue
        if previous is not None and previous != frame:
            return f"a packet of {previous} samples before the last"
        if pts != expected:
            return f"packet timestamps are not the running sample count at {pts} (expected {expected})"
        if not 0 < duration <= frame:
            return f"a packet of {duration} samples"
        expected += duration
        total_kept += duration
        kept += 1
        previous = duration
    if not kept:
        return "no audio packets"
    if discarded != (1 if priming else 0):
        return f"{discarded} priming packet(s) for a declared padding of {priming}"
    if total_kept != total:
        return f"the packets hold {total_kept} samples; the stream declares {total}"
    return None


def scan_argv(ffprobe: str, source) -> list[str]:
    return [ffprobe, "-v", "error", "-select_streams", "a:0", "-show_entries", "packet=pts,duration,flags",
            "-of", "csv=p=0", str(source)]


def scan_packets(source, *, total: int, priming: int, duration_seconds: float,
                 cancelled: Callable[[], bool], ffprobe: str | None = None, popen=None,
                 poll_seconds: float = _POLL_SECONDS, grace_seconds: float = _GRACE_SECONDS) -> str | None:
    """Run the packet scan as an owned child and judge it as it streams. ``None`` when proven, else why not.

    A watcher stops the child at once on Cancel or at its deadline, so a scan never holds the preflight longer than a
    poll; the child is always reaped. Nothing is written to disk: each line is judged and dropped.
    """
    spawn = sp.popen if popen is None else popen
    argv = scan_argv(ffprobe or ffmpeg_utils.ffprobe_cmd(), source)
    try:
        proc = spawn(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError as exc:
        return f"the packet scan could not start: {type(exc).__name__}: {exc}"
    deadline = time.monotonic() + SCAN_BASE_SECONDS + SCAN_SECONDS_PER_HOUR * max(0.0, duration_seconds) / 3600.0
    stopped: list[str] = []
    finished = threading.Event()

    def watch() -> None:
        while not finished.wait(poll_seconds):
            reason = "cancelled" if cancelled() else ("timed out" if time.monotonic() > deadline else "")
            if reason:
                stopped.append(reason)
                try:
                    proc.kill()
                except OSError:
                    pass
                return

    watcher = threading.Thread(target=watch, name="m4b-packet-scan-watch", daemon=True)
    watcher.start()
    try:
        verdict = check_packet_lines(proc.stdout, total=total, priming=priming)
    except (OSError, ValueError) as exc:
        verdict = f"the packet scan could not be read: {type(exc).__name__}: {exc}"
    finally:
        finished.set()
        if proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass
        try:
            proc.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:  # pragma: no cover - a child that will not die
            pass
        try:
            proc.stdout.close()
        except (OSError, ValueError):
            pass
        watcher.join(timeout=grace_seconds)
    if stopped:
        return f"the packet scan was {stopped[0]}"
    if proc.returncode != 0 and verdict is None:
        return f"the packet scan exited {proc.returncode}"
    return verdict


def qualify(source, report, *, split: bool, cancelled: Callable[[], bool] = lambda: False,
            scan=None, build=None) -> RouteDecision:
    """Decide one book's audio route at preflight. Never raises; anything unproven keeps the seeking route.

    *scan* and *build* are the seams the tests drive; production runs :func:`scan_packets` and :func:`build_refusal`.
    """
    try:
        refusal = static_refusal(report, split=split)
        if refusal is not None:
            return RouteDecision(None, refusal)
        starts = [span.start for span in plan_timeline(report.probe)]
        saved = saved_seconds(starts, float(report.probe.duration))
        if saved < MIN_SAVED_PREFIX_SECONDS:
            return RouteDecision(None, f"too little to gain: an estimated {saved:.0f} s of decoding saved, under the "
                                       f"{MIN_SAVED_PREFIX_SECONDS:.0f} s threshold")
        unqualified = (build or build_refusal)()
        if unqualified is not None:
            return RouteDecision(None, unqualified)
        facts = report.stream
        began = time.monotonic()
        verdict = (scan or scan_packets)(
            source, total=int(facts.duration_ts), priming=int(facts.initial_padding),
            duration_seconds=float(report.probe.duration or 0.0), cancelled=cancelled)
        took = time.monotonic() - began
        if verdict is not None:
            return RouteDecision(None, f"timestamps not proven: {verdict}", took)
        return RouteDecision(ContinuousRoute(sample_rate=int(facts.sample_rate), channels=int(facts.channels),
                                             total_samples=int(facts.duration_ts)),
                             "decoded once", took)
    except Exception as exc:  # noqa: BLE001 - an unexpected answer is an unproven one, never a crash of the preflight
        return RouteDecision(None, f"not proven: {type(exc).__name__}: {exc}")


# --------------------------------------------------------------------------- #
# The decoder, one per book attempt
# --------------------------------------------------------------------------- #


_owned = threading.local()


@contextlib.contextmanager
def owned_decoders():
    """Every decoder started on this thread inside the block is closed when the block ends, however it ends.

    The worker closes each book's decoder on every route out of that book; this is the backstop for a route it never
    reached (an unexpected error), so no decoder process can outlive the run that started it.
    """
    previous = getattr(_owned, "live", None)
    live: list = []
    _owned.live = live
    try:
        yield
    finally:
        _owned.live = previous
        for decoder in list(live):
            decoder.close()


def decoder_argv(ffmpeg: str, source) -> list[str]:
    """The whole book's first audio stream, decoded once, as interleaved float samples on stdout."""
    return [ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-i", str(source),
            "-map", "0:a:0", "-c:a", "pcm_f32le", "-f", "f32le", "pipe:1"]


class ContinuousDecoder:
    """One book attempt's decoder: started once, read strictly in order, cut by absolute sample positions.

    :meth:`feed` runs on the encoder's feeding thread; :meth:`start` and :meth:`close` on the worker. ``close`` is safe
    at any time and from the stop hook, and it is what makes a blocked feed return: it ends the decoder, so the pipe
    reaches its end.
    """

    def __init__(self, route: ContinuousRoute, *, ffmpeg: str, source, workspace: Path, popen=None,
                 grace_seconds: float = _GRACE_SECONDS) -> None:
        self.route = route
        self._ffmpeg = ffmpeg
        self._source = Path(source)
        self._workspace = Path(workspace)
        self._spawn = sp.popen if popen is None else popen
        self._grace = grace_seconds
        self._frame = route.frame_bytes
        self._proc = None
        self._diagnostics: Path | None = None
        self._recent: collections.deque[bytes] = collections.deque()
        self._recent_bytes = 0
        self._tail_limit = TAIL_SECONDS * route.sample_rate * self._frame
        self._ended = False
        self._closed = False
        self._registry: list | None = None
        #: The absolute index of the next sample not yet read from the decoder.
        self.position = 0
        #: The most audio held at any moment: the block in hand plus the kept tail (budget T4).
        self.peak_buffered = 0
        self.returncode: int | None = None

    # ---------------------------------------------------------------- life
    def start(self) -> list[str]:
        """Start the decoder. Returns its command line for the transcript. Raises ``OSError`` if it cannot start."""
        argv = decoder_argv(self._ffmpeg, self._source)
        self._diagnostics = output_paths.temporary_sibling(self._workspace / "decoder", suffix=".log")
        try:
            with open(self._diagnostics, "wb") as sink:
                self._proc = self._spawn(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=sink)
        except OSError:
            output_paths.discard_temporary(self._diagnostics)
            self._diagnostics = None
            raise
        self._registry = getattr(_owned, "live", None)
        if self._registry is not None:
            self._registry.append(self)
        return argv

    def close(self) -> bool:
        """Stop the decoder if it still runs and always reap it. Idempotent. True when it was reaped."""
        proc, self._closed = self._proc, True
        registry, self._registry = self._registry, None
        if registry is not None and self in registry:
            registry.remove(self)
        if proc is None:
            return True
        reaped = True
        if proc.poll() is None:
            for step in (proc.terminate, proc.kill):
                try:
                    step()
                except OSError:
                    pass
                try:
                    proc.wait(timeout=self._grace)
                    break
                except subprocess.TimeoutExpired:
                    continue
            else:  # pragma: no cover - a child that survives terminate and kill
                reaped = False
        else:
            proc.wait()
        self.returncode = proc.returncode if reaped else None
        try:
            proc.stdout.close()
        except (OSError, ValueError):
            pass
        if self._diagnostics is not None:
            output_paths.discard_temporary(self._diagnostics)
            self._diagnostics = None
        self._recent.clear()
        self._recent_bytes = 0
        return reaped

    def _detail(self) -> str:
        if self._diagnostics is None:
            return ""
        text = tail_of(self._diagnostics)
        return f"\n{text}" if text else ""

    # ---------------------------------------------------------------- reading
    def _read(self, size: int) -> bytes:
        if self._ended:
            return b""
        if self._proc is None or self._closed:
            raise ContinuousDecodeError("the decoder is not running")
        try:
            data = self._proc.stdout.read(size)
        except (OSError, ValueError) as exc:
            raise ContinuousDecodeError(f"the decoder's audio could not be read: {type(exc).__name__}: {exc}") from exc
        if len(data) % self._frame:
            raise ContinuousDecodeError(f"the decoder's audio ended part-way through a sample after sample {self.position}")
        if not data:
            self._ended = True
            self._finish()
            return b""
        self.position += len(data) // self._frame
        self._recent.append(data)
        self._recent_bytes += len(data)
        while self._recent and self._recent_bytes - len(self._recent[0]) >= self._tail_limit:
            self._recent_bytes -= len(self._recent.popleft())
        self.peak_buffered = max(self.peak_buffered, self._recent_bytes)
        return data

    def _finish(self) -> None:
        """At end of stream: the decoder must have exited 0 with exactly the samples the book declares."""
        try:
            code = self._proc.wait(timeout=self._grace)
        except subprocess.TimeoutExpired:
            raise ContinuousDecodeError("the decoder closed its output but did not exit") from None
        if self._closed:
            raise ContinuousDecodeError("the decoder was stopped")
        if code != 0:
            raise ContinuousDecodeError(f"the decoder exited {code} after {self.position} samples{self._detail()}")
        if self.position != self.route.total_samples:
            raise ContinuousDecodeError(f"the decoder produced {self.position} samples; the book declares "
                                        f"{self.route.total_samples}{self._detail()}")

    def _suffix(self, frames: int) -> bytes:
        """The last *frames* samples already read."""
        need = frames * self._frame
        if need > self._recent_bytes:
            raise ContinuousDecodeError(f"a chapter starts {frames} samples before the end of the last one; only "
                                        f"{self._recent_bytes // self._frame} are kept")
        pieces: list[bytes] = []
        have = 0
        for block in reversed(self._recent):
            pieces.append(block)
            have += len(block)
            if have >= need:
                break
        joined = b"".join(reversed(pieces))
        return joined[len(joined) - need:]

    def feed(self, write: Callable[[bytes], None], first: int, count: int, *, last: bool) -> int:
        """Write samples ``[first, first + count)`` into *write*; return how many were written.

        Short only on the book's last chapter, and only when the decoder ended cleanly having produced the whole book:
        then the seeking route would have kept just as few. A short feed anywhere else raises.
        """
        if first < 0 or count < 0:
            raise ContinuousDecodeError(f"an impossible span: first {first}, count {count}")
        sent = 0
        if first < self.position:
            back = self.position - first
            take = min(back, count)
            write(self._suffix(back)[:take * self._frame])
            sent = take
        while self.position < first:  # a gap the seeking route also skips
            if not self._read(min(READ_BLOCK_BYTES, (first - self.position) * self._frame)):
                break
        while sent < count:
            data = self._read(min(READ_BLOCK_BYTES, (count - sent) * self._frame))
            if not data:
                break
            write(data)
            sent += len(data) // self._frame
        if sent < count and not last:
            raise ContinuousDecodeError(f"the decoder ended after sample {self.position}, {count - sent} samples short of "
                                        "this chapter")
        if last:
            while self._read(READ_BLOCK_BYTES):  # past the last chapter's end: read, check, drop
                pass
        return sent
