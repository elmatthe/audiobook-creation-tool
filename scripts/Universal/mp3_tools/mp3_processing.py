"""MP3 processing: the FFmpeg helpers and the Write ID3 engine — v0.6.3 focused
MP3 redesign, Phase 7.

Three things live here, and nothing that touches a widget, a thread or a
controller.

**The proven FFmpeg helpers** the MP3 Tool has always used — ``run_ff``, the
UTF-8 concat list and its escaping, duration probing, ``seconds_to_hms``, the
FAST MP3 concat, WAV normalisation and concat, silence generation, and the
signed-time append and trim — moved here verbatim from ``mp3_tool.py`` so the
processing engine and the panel share one copy. The panel re-exports them under
the names its tests and callers already use.

**The Write ID3 engine** (focused plan section 23) runs one frozen Phase 5
``RunPlan`` and reads nothing else — no widget, no live workspace. For every
Book in frozen order, every track becomes a **new clean staged copy** with the
frozen signed Time applied (zero still copies, positive appends, negative trims,
an excessive trim fails safely before FFmpeg runs), the source is never written,
and the copy then carries exactly the whitelisted frames the plan intends:

    TIT2 Title              always
    TPE1 Artist             when populated
    TPE2 Album Artist       when populated
    TALB Album              when populated
    TRCK Track Number       when Auto-number is on, as an ordinary integer
    APIC front cover        exactly the frozen artwork, through mp3_artwork

Every other source frame — year, genre, composer, comment, TXXX, old artwork,
a stale track number — is gone, because the tag is written from a clean state
rather than by deleting frames one at a time. Blank frozen scalars are absent
tags; nothing falls back to source metadata.

A Book is the publication boundary (section 21). Every staged track is
validated — present, non-empty, a sensible duration, exactly the intended frames
and artwork — and the Book is published through the Phase 5 boundary only when
every track passed. One failed track means the Book publishes nothing; its
successful pieces stay in private staging for the exact failed-item retry the
Plan 3 ``RunResult`` describes; later Books still run.

Failures are Plan 3 ``FailureRecord`` values against the Book's own
``RunSnapshot``: a track failure carries the real occurrence id and is
retryable; a Book-level failure (artwork that will not decode, a publication
that failed) carries no item id and is not — no identity is ever invented.

**The Combine engine** (focused plan section 24) runs a frozen Combine plan
the same way, one combined MP3 per Book and never across Books. Every
constituent is staged with the frozen signed Time first — the final one too —
through the very same per-track staging as Write ID3. FAST concat is tried
automatically when the staged constituents share one codec, sample rate and
channel count; otherwise, or when FAST fails, the Safe path normalises each to
WAV and concatenates those, and the reason is emitted as a technical event.
The combined file's tag is written from a clean state — Title = effective
Album only, Artist / Album Artist / Album when populated, the frozen artwork,
no Track Number, no chapter frames — and ``combined_time-stamps.txt`` lists
the final frozen Titles at their adjusted offsets. Both are validated, then the
Book is published whole through the Phase 5 boundary. A constituent that could
not be prepared is a retryable failure against its real occurrence; a concat,
tag, timestamp or publication failure is the Book's own, item-less.
"""

from __future__ import annotations

import shlex
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from shared import ffmpeg_utils
from shared import subprocess_utils as sp
from shared.job_control import FailureLog, FailureRecord, JobState, RunResult
from mp3_tools import mp3_artwork
from mp3_tools import mp3_plan

__all__ = [
    "ProcessingError",
    "ProcessingEvent",
    "BookReport",
    "RunReport",
    "WriteId3Report",
    "CombineReport",
    "write_id3_run",
    "write_id3_book",
    "validate_staged_track",
    "combine_run",
    "combine_book",
    "validate_combined_book",
    "fast_eligibility",
    "ffprobe_audio_stream",
    "timestamp_lines",
    "ensure_ffmpeg_available",
    "run_ff",
    "save_error_log",
    "ffmpeg_escape_listfile_path",
    "write_concat_listfile",
    "ffprobe_duration_seconds",
    "seconds_to_hms",
    "concat_mp3s_fast",
    "normalize_to_wav",
    "make_silence_wav",
    "concat_wavs_to_mp3",
    "add_silence_to_mp3",
    "trim_from_end_mp3",
]


# ---------------------------
# Utilities (moved verbatim from mp3_tool.py)
# ---------------------------


def ensure_ffmpeg_available() -> bool:
    """True only when a proved, pinned pair is active.

    Every FFmpeg-backed operation in this tool -- concat, duration probing,
    normalisation, silence generation, time edits -- is gated on this. A merely
    discovered pair is not enough: it was never executed.
    """
    return ffmpeg_utils.verified_ffmpeg()


def run_ff(args: List[str]) -> Tuple[int, str, str]:
    """Run ffmpeg/ffprobe and return (code, stdout, stderr) as text."""
    try:
        from subprocess import PIPE

        p = sp.run(args, stdout=PIPE, stderr=PIPE, text=True)
        return p.returncode, p.stdout, p.stderr
    except Exception as e:
        return 999, "", f"Subprocess failed: {e}"


def save_error_log(folder: Path, title: str, args: List[str], stderr: str):
    """Write (append) a minimal ffmpeg_log.txt only on error."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
        log = folder / "ffmpeg_log.txt"
        with log.open("a", encoding="utf-8") as f:
            f.write(f"\n--- {title} ---\n")
            f.write("CMD: " + " ".join(shlex.quote(a) for a in args) + "\n")
            if stderr:
                f.write(stderr.strip() + "\n")
    except Exception:
        pass


def ffmpeg_escape_listfile_path(p: Path) -> str:
    """Serialise one path as a concat-demuxer ``file`` directive.

    These are **not** shell rules. Per ffmpeg's documented syntax ("Quoting and
    escaping"), every character between single quotes is literal — a backslash
    inside them escapes nothing. So a quote cannot be written ``\\'``: ffmpeg
    would read it as the closing quote and silently truncate the path at that
    point. The documented form closes the quote, emits an escaped quote outside
    it, and reopens::

        file '/mnt/share/file 3'\\''.wav'

    Because everything else inside the quotes is literal, Windows backslashes,
    spaces and non-ASCII characters need no treatment at all. The previous
    version doubled backslashes as well; that survived only because Windows
    collapses repeated path separators, and it corrupted any real backslash.

    A newline cannot be represented — the demuxer parses one directive per line.
    Windows forbids newlines in names outright, so this only rejects a pathological
    POSIX name rather than writing a listfile ffmpeg would misread.
    """
    text = str(p)
    if "\n" in text or "\r" in text:
        raise ValueError(f"a line break cannot appear in a concat list entry: {text!r}")
    return "file '" + text.replace("'", "'\\''") + "'"


def write_concat_listfile(paths: List[Path], listfile: Path):
    """Write the concat list as UTF-8 — ffmpeg reads these names as UTF-8."""
    with listfile.open("w", encoding="utf-8", newline="\n") as f:
        for p in paths:
            f.write(ffmpeg_escape_listfile_path(p) + "\n")


def ffprobe_duration_seconds(path: Path) -> Optional[float]:
    code, out, _ = run_ff(
        [
            ffmpeg_utils.ffprobe_cmd(),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
    )
    if code == 0:
        try:
            return float(out.strip())
        except Exception:
            return None
    return None


def seconds_to_hms(sec: float) -> str:
    sec = max(0.0, float(sec))
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec - h * 3600 - m * 60
    return f"{h:02d}:{m:02d}:{s:06.3f}" if h > 0 else f"{m:02d}:{s:06.3f}"


# ---------------------------
# FAST PATH (metadata stripped)
# ---------------------------


def _fast_concat_args(listfile: Path, out_mp3: Path) -> List[str]:
    """One-pass concat-demuxer encode of like constituents, metadata stripped."""
    return [
        ffmpeg_utils.ffmpeg_cmd(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(listfile),
        "-map_metadata",
        "-1",
        "-c:a",
        "libmp3lame",
        "-q:a",
        "2",
        str(out_mp3),
    ]


def concat_mp3s_fast(listfile: Path, out_mp3: Path, log_dir: Path) -> bool:
    args = _fast_concat_args(listfile, out_mp3)
    code, _, err = run_ff(args)
    if code != 0:
        save_error_log(log_dir, "FAST PATH concat_mp3s_fast", args, err)
    return code == 0


# ---------------------------
# SAFE PATH (WAV normalize + optional gaps)
# ---------------------------


def _normalize_args(in_path: Path, out_wav: Path) -> List[str]:
    """Decode one constituent to 44.1 kHz stereo 16-bit WAV for the Safe concat."""
    return [
        ffmpeg_utils.ffmpeg_cmd(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(in_path),
        "-vn",
        "-sn",
        "-dn",
        "-ac",
        "2",
        "-ar",
        "44100",
        "-sample_fmt",
        "s16",
        str(out_wav),
    ]


def normalize_to_wav(in_path: Path, out_wav: Path, log_dir: Path) -> bool:
    args = _normalize_args(in_path, out_wav)
    code, _, err = run_ff(args)
    if code != 0:
        save_error_log(log_dir, f"normalize_to_wav: {in_path.name}", args, err)
    return code == 0


def make_silence_wav(seconds: float, out_wav: Path, log_dir: Path) -> bool:
    seconds = max(0.0, float(seconds))
    args = [
        ffmpeg_utils.ffmpeg_cmd(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=44100:cl=stereo",
        "-t",
        f"{seconds:.6f}",
        "-ac",
        "2",
        "-ar",
        "44100",
        "-sample_fmt",
        "s16",
        str(out_wav),
    ]
    code, _, err = run_ff(args)
    if code != 0:
        save_error_log(log_dir, "make_silence_wav", args, err)
    return code == 0


def _safe_concat_args(listfile: Path, out_mp3: Path) -> List[str]:
    """Concat the normalised WAVs into one MP3, metadata stripped."""
    return [
        ffmpeg_utils.ffmpeg_cmd(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(listfile),
        "-map_metadata",
        "-1",
        "-c:a",
        "libmp3lame",
        "-q:a",
        "2",
        str(out_mp3),
    ]


def concat_wavs_to_mp3(listfile: Path, out_mp3: Path, log_dir: Path) -> bool:
    args = _safe_concat_args(listfile, out_mp3)
    code, _, err = run_ff(args)
    if code != 0:
        save_error_log(log_dir, "SAFE PATH concat_wavs_to_mp3", args, err)
    return code == 0


# ---------------------------
# Time edit helpers (always strip metadata)
# ---------------------------


def _append_silence_args(in_mp3: Path, seconds: float, out_mp3: Path) -> List[str]:
    """Append *seconds* of silence to the end of one MP3, metadata stripped."""
    seconds = max(0.0, float(seconds))
    return [
        ffmpeg_utils.ffmpeg_cmd(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(in_mp3),
        "-f",
        "lavfi",
        "-t",
        f"{seconds:.6f}",
        "-i",
        "anullsrc=r=44100:cl=stereo",
        "-filter_complex",
        "[0:a][1:a]concat=n=2:v=0:a=1[a]",
        "-map",
        "[a]",
        "-map_metadata",
        "-1",
        "-ac",
        "2",
        "-ar",
        "44100",
        "-c:a",
        "libmp3lame",
        "-q:a",
        "2",
        str(out_mp3),
    ]


def add_silence_to_mp3(in_mp3: Path, seconds: float, out_mp3: Path, log_dir: Path) -> bool:
    args = _append_silence_args(in_mp3, seconds, out_mp3)
    code, _, err = run_ff(args)
    if code != 0:
        save_error_log(log_dir, f"add_silence_to_mp3: {in_mp3.name}", args, err)
    return code == 0


def _trim_args(in_mp3: Path, new_duration: float, out_mp3: Path) -> List[str]:
    """Keep the first *new_duration* seconds of one MP3, metadata stripped.

    ``-map 0:a:0`` keeps an attached source picture out of the output: without
    it ffmpeg would carry the old cover as a video stream into the new file,
    which is the opposite of "always strip metadata".
    """
    return [
        ffmpeg_utils.ffmpeg_cmd(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(in_mp3),
        "-map",
        "0:a:0",
        "-t",
        f"{max(0.0, float(new_duration)):.6f}",
        "-map_metadata",
        "-1",
        "-ac",
        "2",
        "-ar",
        "44100",
        "-c:a",
        "libmp3lame",
        "-q:a",
        "2",
        str(out_mp3),
    ]


def trim_from_end_mp3(in_mp3: Path, seconds_to_remove: float, out_mp3: Path, log_dir: Path) -> bool:
    seconds_to_remove = max(0.0, float(seconds_to_remove))
    dur = ffprobe_duration_seconds(in_mp3) or 0.0
    new_dur = max(0.0, dur - seconds_to_remove)
    args = _trim_args(in_mp3, new_dur, out_mp3)
    code, _, err = run_ff(args)
    if code != 0:
        save_error_log(log_dir, f"trim_from_end_mp3: {in_mp3.name}", args, err)
    return code == 0


# ---------------------------
# The Write ID3 engine (Phase 7)
# ---------------------------

#: A negative Time may not leave less than this much of a track. Below it the
#: result would be silence-length noise or an empty file, so the track fails
#: before FFmpeg runs rather than manufacturing an invalid output.
MIN_REMAINING_SECONDS = 0.1

#: How far a staged track's duration may drift from what the plan expects.
DURATION_TOLERANCE_SECONDS = 0.25
DURATION_TOLERANCE_RATIO = 0.02

Checkpoint = Callable[[], None]


class ProcessingError(Exception):
    """One track (or one Book) could not be processed. Carries the stage."""

    def __init__(self, message: str, *, stage: str = "processing", detail: str = "") -> None:
        super().__init__(message)
        self.stage = stage
        self.detail = detail


@dataclass(frozen=True)
class ProcessingEvent:
    """One line of what the engine is doing — the narrow seam a log can render.

    ``kind`` says what the line *is*, so a consumer can project it into the
    shared job-event vocabulary without parsing the message: ``book`` (a Book
    started), ``track`` (a track started), ``kept`` (a retained staged track
    reused on a retry), ``failure`` (a track failure with its real occurrence,
    or a Book-level one without), ``completed`` / ``failed`` (how the Book
    ended), ``warning`` and ``technical``. The engine still knows nothing of
    reporters, streams or widgets.
    """

    book_id: str
    occurrence_id: str | None
    stage: str
    message: str
    detail: str = ""
    kind: str = "technical"


Listener = Callable[[ProcessingEvent], object]
BookListener = Callable[["BookReport"], object]


@dataclass(frozen=True)
class BookReport:
    """One Book's outcome: the Plan 3 result, what was published, what is staged."""

    book_id: str
    result: RunResult
    published: tuple[Path, ...]
    staged_ok: tuple[str, ...]

    @property
    def succeeded(self) -> bool:
        return self.result.state is JobState.SUCCEEDED


@dataclass(frozen=True)
class RunReport:
    """One operation's outcome: a ``BookReport`` per attempted Book, in order."""

    plan: mp3_plan.RunPlan
    books: tuple[BookReport, ...]

    @property
    def failed_book_ids(self) -> tuple[str, ...]:
        return tuple(entry.book_id for entry in self.books if not entry.succeeded)


#: Both engines report the same shape; the names say which one ran.
WriteId3Report = RunReport
CombineReport = RunReport


def _check(checkpoint: Checkpoint | None) -> None:
    if checkpoint is not None:
        checkpoint()


def _emit(listener: Listener | None, event: ProcessingEvent) -> None:
    if listener is not None:
        listener(event)


def _settled(listener: BookListener | None, report: BookReport) -> BookReport:
    if listener is not None:
        listener(report)
    return report


RetryItems = Mapping[str, Collection[str]]


def _retry_subset(retry_items: RetryItems | None, book: mp3_plan.BookPlan):
    """Which of *book*'s tracks a retry re-runs: ``None`` on a first attempt.

    A retry names its Books and, per Book, the occurrence ids that failed —
    exactly what Plan 6's ``retry_failed_books`` derived from the frozen
    result. A Book the retry does not name is skipped whole: it was published,
    or it failed in a way no retry can repair. An occurrence the plan does not
    hold is refused rather than silently ignored.
    """
    if retry_items is None:
        return None
    wanted = retry_items.get(book.book_id)
    if wanted is None:
        return ()
    known = {track.occurrence_id for track in book.tracks}
    subset = frozenset(str(item) for item in wanted)
    unknown = subset - known
    if unknown:
        raise ProcessingError(
            f"retry names occurrences not in Book {book.number}'s frozen plan: "
            f"{sorted(unknown)!r}", stage="retry")
    return subset


def write_id3_run(plan: mp3_plan.RunPlan, *, checkpoint: Checkpoint | None = None,
                  on_event: Listener | None = None, on_book: BookListener | None = None,
                  retry_items: RetryItems | None = None) -> RunReport:
    """Run every planned Book in frozen order. A failed Book never stops the next.

    ``on_book`` hears each Book's report the moment it settles, in order, on
    the calling thread. ``retry_items`` turns the run into an exact failed-item
    retry of the **same** plan: only the named Books run, only their named
    occurrences are re-staged, every other staged piece of theirs is reused,
    and each is published whole from the same ``BookPlan``. Nothing is
    re-planned, re-reserved or re-captured.
    """
    if not isinstance(plan, mp3_plan.RunPlan):
        raise ProcessingError(f"plan must be a RunPlan, got {type(plan).__name__}")
    if plan.operation is not mp3_plan.MP3Operation.WRITE_ID3:
        raise ProcessingError(
            f"write_id3_run runs a Write ID3 plan, not {plan.operation.value}")
    reports: list[BookReport] = []
    for book in plan.books:
        only = _retry_subset(retry_items, book)
        if only == ():
            continue
        _check(checkpoint)
        reports.append(_settled(on_book, write_id3_book(
            book, checkpoint=checkpoint, on_event=on_event, only=only)))
    mp3_plan.discard_run_staging(plan)
    return RunReport(plan=plan, books=tuple(reports))


def write_id3_book(book: mp3_plan.BookPlan, *, checkpoint: Checkpoint | None = None,
                   on_event: Listener | None = None,
                   only: Collection[str] | None = None) -> BookReport:
    """Stage, tag and validate every track of one Book, then publish it whole.

    Reads the frozen plan and nothing else. Track failures are recorded
    against the real occurrence id and the Book goes on to its remaining
    tracks, so the retry has as much staged work to reuse as possible; the
    Book is published only if nothing failed.

    ``only`` is the retry's subset: a track outside it whose staged copy is
    still there is reused as it was validated — and re-made if it is not, so a
    Book is never published with a piece missing.
    """
    if not isinstance(book, mp3_plan.BookPlan):
        raise ProcessingError(f"book must be a BookPlan, got {type(book).__name__}")
    if book.operation is not mp3_plan.MP3Operation.WRITE_ID3:
        raise ProcessingError(
            f"write_id3_book runs a Write ID3 Book, not {book.operation.value}")
    snapshot_id = book.snapshot.snapshot_id
    failures: list[FailureRecord] = []
    staged_ok: list[str] = []

    def fatal(stage: str, message: str, detail: str = "") -> BookReport:
        failures.append(FailureRecord(item_id=None, stage=stage, display_message=message,
                                      technical_detail=detail or message,
                                      retryable=False, snapshot_id=snapshot_id))
        _emit(on_event, ProcessingEvent(book.book_id, None, stage, message, detail,
                                        kind="failure"))
        return _settle(book, failures, staged_ok, ())

    _emit(on_event, ProcessingEvent(
        book.book_id, None, "book",
        f"Book {book.number} — started: {len(book.tracks)} track(s)"
        + (f", retrying {len(only)}" if only else ""), kind="book"))
    if not ensure_ffmpeg_available():
        return fatal("ffmpeg", "ffmpeg/ffprobe is not available; run the setup launcher")
    try:
        artwork = mp3_artwork.artwork_for(book)
    except mp3_artwork.ArtworkError as exc:
        return fatal("artwork", f"Book Artwork: {exc}")
    try:
        mp3_plan.prepare_staging(book)
    except (mp3_plan.PlanError, OSError) as exc:
        return fatal("staging", f"the private staging folder could not be created: {exc}")

    for track in book.tracks:
        _check(checkpoint)
        if _kept(book, track, only, on_event):
            staged_ok.append(track.occurrence_id)
            continue
        _emit(on_event, ProcessingEvent(
            book.book_id, track.occurrence_id, "track",
            f"Book {book.number} — track {track.position} of {len(book.tracks)}: "
            f"{track.filename}", kind="track"))
        try:
            expected = _stage_clean_copy(book, track)
            _write_whitelist(book, track, artwork)
            validate_staged_track(book, track, artwork, expected_duration=expected)
        except ProcessingError as exc:
            _discard_staged(track.staged)
            failures.append(FailureRecord(
                item_id=track.occurrence_id, stage=exc.stage, display_message=str(exc),
                technical_detail=exc.detail or str(exc), retryable=True,
                snapshot_id=snapshot_id))
            _emit(on_event, ProcessingEvent(book.book_id, track.occurrence_id, exc.stage,
                                            f"{track.filename}: {exc}", exc.detail,
                                            kind="failure"))
            continue
        staged_ok.append(track.occurrence_id)

    published: tuple[Path, ...] = ()
    if not failures:
        try:
            published = mp3_plan.publish_book(book)
        except (mp3_plan.PlanError, OSError) as exc:
            return fatal("publish", f"the finished Book could not be published: {exc}")
        _emit(on_event, ProcessingEvent(book.book_id, None, "book",
                                        f"Book {book.number} — completed: "
                                        f"{len(book.tracks)} track(s)", kind="completed"))
    else:
        _emit(on_event, ProcessingEvent(
            book.book_id, None, "book",
            f"Book {book.number} — failed: {len(failures)} track(s); nothing published",
            kind="failed"))
    return _settle(book, failures, staged_ok, published)


def _kept(book: mp3_plan.BookPlan, track: mp3_plan.TrackPlan,
          only: Collection[str] | None, on_event: Listener | None) -> bool:
    """On a retry, reuse a track outside the subset whose staged copy survived."""
    if only is None or track.occurrence_id in only:
        return False
    if not (track.staged.is_file() and not track.staged.is_symlink()):
        return False
    _emit(on_event, ProcessingEvent(
        book.book_id, track.occurrence_id, "track",
        f"Book {book.number} — track {track.position} of {len(book.tracks)}: "
        f"{track.filename} kept from the earlier attempt", kind="kept"))
    return True


def _settle(book: mp3_plan.BookPlan, failures, staged_ok, published) -> BookReport:
    log = FailureLog(snapshot_id=book.snapshot.snapshot_id, records=tuple(failures))
    result = RunResult.settle(book.snapshot, log, completed_ids=tuple(staged_ok))
    return BookReport(book_id=book.book_id, result=result, published=tuple(published),
                      staged_ok=tuple(staged_ok))


def _discard_staged(path: Path) -> None:
    """A failed track leaves no half-made output behind."""
    try:
        if path.is_file() and not path.is_symlink():
            path.unlink()
    except OSError:
        pass


# -- one track: stage, tag, validate ----------------------------------------- #


def _stage_clean_copy(book: mp3_plan.BookPlan, track: mp3_plan.TrackPlan) -> float:
    """Create the track's staged copy with the frozen signed Time applied.

    Returns the duration the copy is expected to have. The source is only ever
    an FFmpeg input; every output path is the plan's staged path.
    """
    source_duration = ffprobe_duration_seconds(track.source)
    if source_duration is None:
        raise ProcessingError("the source could not be read by ffprobe", stage="probe",
                              detail=str(track.source))
    delta = float(book.time_delta)
    if delta > 0:
        args = _append_silence_args(track.source, delta, track.staged)
        expected = source_duration + delta
        stage = "append"
    elif delta < 0:
        remaining = source_duration - abs(delta)
        if remaining < MIN_REMAINING_SECONDS:
            raise ProcessingError(
                f"trimming {abs(delta):g} s from the end would leave nothing of a "
                f"{source_duration:.2f} s track", stage="trim",
                detail=f"source={track.source} duration={source_duration:.3f} delta={delta}")
        args = _trim_args(track.source, remaining, track.staged)
        expected = remaining
        stage = "trim"
    else:
        args = _clean_copy_args(track.source, track.staged)
        expected = source_duration
        stage = "copy"
    code, _out, err = run_ff(args)
    if code != 0:
        _discard_staged(track.staged)
        raise ProcessingError(
            "FFmpeg could not create the track", stage=stage,
            detail="CMD: " + " ".join(shlex.quote(a) for a in args) + "\n" + err.strip())
    return expected


def _clean_copy_args(source: Path, staged: Path) -> List[str]:
    """Zero Time: the audio stream copied, every source tag and picture left behind."""
    return [
        ffmpeg_utils.ffmpeg_cmd(), "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source), "-map", "0:a:0", "-map_metadata", "-1", "-c", "copy",
        str(staged),
    ]


def _write_whitelist(book: mp3_plan.BookPlan, track: mp3_plan.TrackPlan,
                     artwork: mp3_artwork.Artwork | None) -> None:
    """The tag, from a clean state: exactly the frozen values and nothing old."""
    from mutagen.id3 import ID3, TALB, TIT2, TPE1, TPE2, TRCK
    from mutagen.id3 import delete as delete_tags

    try:
        # Whatever ffmpeg's muxer wrote (an encoder frame, a v1 tag) goes too:
        # the whitelist starts from nothing rather than from a partial cleanup.
        delete_tags(str(track.staged))
        tags = ID3()
        tags.add(TIT2(encoding=3, text=[track.title]))
        if book.artist:
            tags.add(TPE1(encoding=3, text=[book.artist]))
        if book.album_artist:
            tags.add(TPE2(encoding=3, text=[book.album_artist]))
        if book.album:
            tags.add(TALB(encoding=3, text=[book.album]))
        if track.track_number is not None:
            tags.add(TRCK(encoding=3, text=[str(int(track.track_number))]))
        mp3_artwork.apply_artwork(tags, artwork)
        tags.save(str(track.staged), v2_version=3)
    except (OSError, ValueError, mp3_artwork.ArtworkError) as exc:
        raise ProcessingError(f"the ID3 tag could not be written: {exc}", stage="tag",
                              detail=str(track.staged)) from exc


def _expected_frames(book: mp3_plan.BookPlan, track: mp3_plan.TrackPlan,
                     artwork: mp3_artwork.Artwork | None) -> set[str]:
    expected = {"TIT2"}
    if book.artist:
        expected.add("TPE1")
    if book.album_artist:
        expected.add("TPE2")
    if book.album:
        expected.add("TALB")
    if track.track_number is not None:
        expected.add("TRCK")
    if artwork is not None:
        expected.add("APIC")
    return expected


def validate_staged_track(book: mp3_plan.BookPlan, track: mp3_plan.TrackPlan,
                          artwork: mp3_artwork.Artwork | None, *,
                          expected_duration: float) -> None:
    """Is the staged copy the output the plan intends? Reads the copy only."""
    from mutagen.id3 import ID3, ID3NoHeaderError

    staged = track.staged
    if not staged.is_file() or staged.is_symlink():
        raise ProcessingError("the staged track is missing", stage="validate",
                              detail=str(staged))
    if staged.stat().st_size == 0:
        raise ProcessingError("the staged track is empty", stage="validate",
                              detail=str(staged))
    actual = ffprobe_duration_seconds(staged)
    if actual is None:
        raise ProcessingError("the staged track has no readable duration", stage="validate",
                              detail=str(staged))
    tolerance = max(DURATION_TOLERANCE_SECONDS, DURATION_TOLERANCE_RATIO * expected_duration)
    if abs(actual - expected_duration) > tolerance:
        raise ProcessingError(
            f"the staged track lasts {actual:.2f} s, expected {expected_duration:.2f} s",
            stage="validate", detail=str(staged))
    try:
        tags = ID3(str(staged))
    except ID3NoHeaderError as exc:
        raise ProcessingError("the staged track carries no ID3 tag", stage="validate",
                              detail=str(staged)) from exc
    present = {key.split(":")[0] for key in tags.keys()}
    expected = _expected_frames(book, track, artwork)
    if present != expected:
        raise ProcessingError(
            f"the staged track carries frames {sorted(present)}, expected {sorted(expected)}",
            stage="validate", detail=str(staged))
    wanted_text = {"TIT2": track.title, "TPE1": book.artist, "TPE2": book.album_artist,
                   "TALB": book.album,
                   "TRCK": "" if track.track_number is None else str(int(track.track_number))}
    for frame_id, value in wanted_text.items():
        if frame_id in expected:
            actual_text = "/".join(str(t) for t in tags[frame_id].text)
            if actual_text != value:
                raise ProcessingError(
                    f"{frame_id} reads {actual_text!r}, expected {value!r}", stage="validate",
                    detail=str(staged))
    if artwork is not None:
        pictures = [frame for key, frame in tags.items() if key.startswith("APIC")]
        if len(pictures) != 1 or pictures[0].data != artwork.data \
                or pictures[0].mime != artwork.mime or int(pictures[0].type) != mp3_artwork.FRONT_COVER:
            raise ProcessingError("the staged artwork is not the planned front cover",
                                  stage="validate", detail=str(staged))


# ---------------------------
# The Combine engine (Phase 8)
# ---------------------------

#: Every constituent is FAST-eligible only when these stream facts agree
#: across the Book, because the concat demuxer joins one stream shape.
_STREAM_FACTS = ("codec_name", "sample_rate", "channels")


def ffprobe_audio_stream(path: Path) -> Optional[Tuple[str, str, str]]:
    """``(codec_name, sample_rate, channels)`` of the first audio stream, or None."""
    code, out, _ = run_ff([
        ffmpeg_utils.ffprobe_cmd(), "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=" + ",".join(_STREAM_FACTS),
        "-of", "default=noprint_wrappers=1", str(path),
    ])
    if code != 0:
        return None
    facts = {}
    for line in out.splitlines():
        key, _, value = line.partition("=")
        facts[key.strip()] = value.strip()
    if not all(facts.get(key) for key in _STREAM_FACTS):
        return None
    return tuple(facts[key] for key in _STREAM_FACTS)  # type: ignore[return-value]


def fast_eligibility(staged: List[Path]) -> Tuple[bool, str]:
    """Whether FAST concat is valid for these staged constituents, and why not.

    FAST hands the concat demuxer the adjusted constituents in one pass; it
    is valid only when every one of them has the same codec, sample rate and
    channel count. Anything else goes straight to Safe, with the reason.
    """
    shapes = []
    for path in staged:
        shape = ffprobe_audio_stream(path)
        if shape is None:
            return False, f"{path.name}: the audio stream could not be probed"
        shapes.append((path.name, shape))
    distinct = {shape for _name, shape in shapes}
    if len(distinct) > 1:
        described = "; ".join(f"{name}: codec={s[0]} sample_rate={s[1]} channels={s[2]}"
                              for name, s in shapes)
        return False, f"constituents differ in codec, sample rate or channels ({described})"
    return True, ""


def combine_run(plan: mp3_plan.RunPlan, *, checkpoint: Checkpoint | None = None,
                on_event: Listener | None = None, on_book: BookListener | None = None,
                retry_items: RetryItems | None = None) -> RunReport:
    """Run every planned Book in frozen order. A failed Book never stops the next.

    ``on_book`` and ``retry_items`` mean what they mean for
    :func:`write_id3_run`: a retry re-stages only the named constituents,
    reuses the rest, and redoes the whole finalisation — concat, tag,
    timestamps, validation, publication — from the same ``BookPlan``.
    """
    if not isinstance(plan, mp3_plan.RunPlan):
        raise ProcessingError(f"plan must be a RunPlan, got {type(plan).__name__}")
    if plan.operation is not mp3_plan.MP3Operation.COMBINE:
        raise ProcessingError(f"combine_run runs a Combine plan, not {plan.operation.value}")
    reports: list[BookReport] = []
    for book in plan.books:
        only = _retry_subset(retry_items, book)
        if only == ():
            continue
        _check(checkpoint)
        reports.append(_settled(on_book, combine_book(
            book, checkpoint=checkpoint, on_event=on_event, only=only)))
    mp3_plan.discard_run_staging(plan)
    return RunReport(plan=plan, books=tuple(reports))


def combine_book(book: mp3_plan.BookPlan, *, checkpoint: Checkpoint | None = None,
                 on_event: Listener | None = None,
                 only: Collection[str] | None = None) -> BookReport:
    """Stage every constituent with the frozen Time, combine, tag, publish whole.

    Reads the frozen plan and nothing else. A constituent that cannot be
    staged is a retryable failure against its real occurrence and the Book
    cannot combine; the other constituents are still staged so the retry has
    them. FAST is tried when the staged constituents are alike, Safe otherwise
    or after a FAST failure, and the reason is emitted either way. Combine,
    tag, timestamp and publication failures are the Book's own — item-less.

    ``only`` is the retry's subset, as for :func:`write_id3_book`: a retained
    constituent is reused (its duration probed again), a missing one re-made.
    """
    if not isinstance(book, mp3_plan.BookPlan):
        raise ProcessingError(f"book must be a BookPlan, got {type(book).__name__}")
    if book.operation is not mp3_plan.MP3Operation.COMBINE:
        raise ProcessingError(
            f"combine_book runs a Combine Book, not {book.operation.value}")
    snapshot_id = book.snapshot.snapshot_id
    failures: list[FailureRecord] = []
    staged_ok: list[str] = []

    def fatal(stage: str, message: str, detail: str = "") -> BookReport:
        failures.append(FailureRecord(item_id=None, stage=stage, display_message=message,
                                      technical_detail=detail or message,
                                      retryable=False, snapshot_id=snapshot_id))
        _emit(on_event, ProcessingEvent(book.book_id, None, stage, message, detail,
                                        kind="failure"))
        return _settle(book, failures, staged_ok, ())

    _emit(on_event, ProcessingEvent(
        book.book_id, None, "book",
        f"Book {book.number} — started: combining {len(book.tracks)} track(s)"
        + (f", retrying {len(only)}" if only else ""), kind="book"))
    if not ensure_ffmpeg_available():
        return fatal("ffmpeg", "ffmpeg/ffprobe is not available; run the setup launcher")
    try:
        artwork = mp3_artwork.artwork_for(book)
    except mp3_artwork.ArtworkError as exc:
        return fatal("artwork", f"Book Artwork: {exc}")
    try:
        mp3_plan.prepare_staging(book)
    except (mp3_plan.PlanError, OSError) as exc:
        return fatal("staging", f"the private staging folder could not be created: {exc}")

    # 1. Every constituent, in frozen order, with the frozen Time applied —
    #    the final one included. The same staging as Write ID3 uses.
    durations: dict[str, float] = {}
    for track in book.tracks:
        _check(checkpoint)
        kept = _kept(book, track, only, on_event)
        if not kept:
            _emit(on_event, ProcessingEvent(
                book.book_id, track.occurrence_id, "track",
                f"Book {book.number} — preparing track {track.position} of "
                f"{len(book.tracks)}: {track.source.name}", kind="track"))
        try:
            if not kept:
                _stage_clean_copy(book, track)
            measured = ffprobe_duration_seconds(track.staged)
            if measured is None:
                raise ProcessingError("the prepared track has no readable duration",
                                      stage="probe", detail=str(track.staged))
        except ProcessingError as exc:
            _discard_staged(track.staged)
            failures.append(FailureRecord(
                item_id=track.occurrence_id, stage=exc.stage, display_message=str(exc),
                technical_detail=exc.detail or str(exc), retryable=True,
                snapshot_id=snapshot_id))
            _emit(on_event, ProcessingEvent(book.book_id, track.occurrence_id, exc.stage,
                                            f"{track.source.name}: {exc}", exc.detail,
                                            kind="failure"))
            continue
        durations[track.occurrence_id] = measured
        staged_ok.append(track.occurrence_id)
    if failures:
        _emit(on_event, ProcessingEvent(
            book.book_id, None, "book",
            f"Book {book.number} — failed: {len(failures)} track(s) could not be prepared; "
            "nothing combined, nothing published", kind="failed"))
        return _settle(book, failures, staged_ok, ())

    # 2. Combine: FAST when valid, Safe otherwise or after a FAST failure.
    _check(checkpoint)
    constituents = [track.staged for track in book.tracks]
    try:
        _combine_constituents(book, constituents, checkpoint=checkpoint, on_event=on_event)
    except ProcessingError as exc:
        _discard_staged(book.combined_staged)
        return fatal(exc.stage, f"the combined MP3 could not be created: {exc}", exc.detail)

    # 3. Tag, timestamps, validate, publish — the Book's own steps.
    try:
        _write_combined_tag(book, artwork)
        _write_timestamps(book, durations)
        validate_combined_book(book, artwork, durations)
    except ProcessingError as exc:
        return fatal(exc.stage, str(exc), exc.detail)
    _check(checkpoint)
    try:
        published = mp3_plan.publish_book(book)
    except (mp3_plan.PlanError, OSError) as exc:
        return fatal("publish", f"the finished Book could not be published: {exc}")
    # The adjusted constituents and any WAVs were only ever inputs to the
    # published file; a published Book keeps no private leftovers.
    try:
        mp3_plan.discard_staging(book)
    except (mp3_plan.PlanError, OSError):
        pass
    _emit(on_event, ProcessingEvent(book.book_id, None, "book",
                                    f"Book {book.number} — completed: {book.combined_filename}",
                                    kind="completed"))
    return _settle(book, failures, staged_ok, published)


def _combine_constituents(book: mp3_plan.BookPlan, constituents: List[Path], *,
                          checkpoint: Checkpoint | None, on_event: Listener | None) -> None:
    """FAST first when eligible; Safe on ineligibility or a FAST failure."""
    eligible, reason = fast_eligibility(constituents)
    if eligible:
        _emit(on_event, ProcessingEvent(book.book_id, None, "fast",
                                        f"Book {book.number} — trying FAST concat",
                                        kind="technical"))
        listfile = book.staging_dir / "inputs_fast.txt"
        write_concat_listfile(constituents, listfile)
        args = _fast_concat_args(listfile, book.combined_staged)
        code, _out, err = run_ff(args)
        if code == 0 and _plausible_output(book.combined_staged):
            return
        _discard_staged(book.combined_staged)
        _emit(on_event, ProcessingEvent(
            book.book_id, None, "fallback",
            f"Book {book.number} — FAST concat failed; switching to Safe",
            "CMD: " + " ".join(shlex.quote(a) for a in args) + "\n" + err.strip(),
            kind="warning"))
    else:
        _emit(on_event, ProcessingEvent(book.book_id, None, "ineligible",
                                        f"Book {book.number} — FAST concat is not valid here; "
                                        "using Safe", reason, kind="technical"))
    _check(checkpoint)
    _emit(on_event, ProcessingEvent(book.book_id, None, "safe",
                                    f"Book {book.number} — Safe concat (WAV normalisation)",
                                    kind="technical"))
    wav_dir = book.staging_dir / "wavs"
    wav_dir.mkdir(parents=True, exist_ok=True)
    wavs: List[Path] = []
    for index, constituent in enumerate(constituents, start=1):
        _check(checkpoint)
        wav = wav_dir / f"{index:04d}.wav"
        args = _normalize_args(constituent, wav)
        code, _out, err = run_ff(args)
        if code != 0:
            raise ProcessingError(
                f"{constituent.name} could not be normalised for the Safe concat", stage="safe",
                detail="CMD: " + " ".join(shlex.quote(a) for a in args) + "\n" + err.strip())
        wavs.append(wav)
    listfile = book.staging_dir / "inputs_safe.txt"
    write_concat_listfile(wavs, listfile)
    args = _safe_concat_args(listfile, book.combined_staged)
    code, _out, err = run_ff(args)
    if code != 0 or not _plausible_output(book.combined_staged):
        raise ProcessingError(
            "the Safe concat did not produce the combined MP3", stage="safe",
            detail="CMD: " + " ".join(shlex.quote(a) for a in args) + "\n" + err.strip())


def _plausible_output(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _write_combined_tag(book: mp3_plan.BookPlan,
                        artwork: mp3_artwork.Artwork | None) -> None:
    """Title = effective Album only; no Track Number; the frozen artwork."""
    from mutagen.id3 import ID3, TALB, TIT2, TPE1, TPE2
    from mutagen.id3 import delete as delete_tags

    try:
        delete_tags(str(book.combined_staged))
        tags = ID3()
        if book.album:
            tags.add(TIT2(encoding=3, text=[book.album]))
            tags.add(TALB(encoding=3, text=[book.album]))
        if book.artist:
            tags.add(TPE1(encoding=3, text=[book.artist]))
        if book.album_artist:
            tags.add(TPE2(encoding=3, text=[book.album_artist]))
        mp3_artwork.apply_artwork(tags, artwork)
        tags.save(str(book.combined_staged), v2_version=3)
    except (OSError, ValueError, mp3_artwork.ArtworkError) as exc:
        raise ProcessingError(f"the combined tag could not be written: {exc}", stage="tag",
                              detail=str(book.combined_staged)) from exc


def timestamp_lines(book: mp3_plan.BookPlan, durations: dict) -> List[str]:
    """The timestamp sheet, from the final frozen Titles and the adjusted
    constituent durations, in frozen order. Pure; deterministic."""
    width = max(2, len(str(len(book.tracks))))
    lines: List[str] = []
    start = 0.0
    for track in book.tracks:
        length = float(durations[track.occurrence_id])
        lines.append(f"{track.position:0{width}d}. {track.title} @ {seconds_to_hms(start)} "
                     f"(+{seconds_to_hms(length)})")
        start += length
    return lines


def _write_timestamps(book: mp3_plan.BookPlan, durations: dict) -> None:
    try:
        with book.timestamps_staged.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(timestamp_lines(book, durations)) + "\n")
    except OSError as exc:
        raise ProcessingError(f"the timestamp file could not be written: {exc}",
                              stage="timestamps", detail=str(book.timestamps_staged)) from exc


def _expected_combined_frames(book: mp3_plan.BookPlan,
                              artwork: mp3_artwork.Artwork | None) -> set[str]:
    expected = set()
    if book.album:
        expected |= {"TIT2", "TALB"}
    if book.artist:
        expected.add("TPE1")
    if book.album_artist:
        expected.add("TPE2")
    if artwork is not None:
        expected.add("APIC")
    return expected


def validate_combined_book(book: mp3_plan.BookPlan, artwork: mp3_artwork.Artwork | None,
                           durations: dict) -> None:
    """Is the staged combined result what the plan intends? Reads staging only."""
    from mutagen.id3 import ID3, ID3NoHeaderError

    combined = book.combined_staged
    if not _plausible_output(combined) or combined.is_symlink():
        raise ProcessingError("the combined MP3 is missing or empty", stage="validate",
                              detail=str(combined))
    actual = ffprobe_duration_seconds(combined)
    expected_total = sum(float(durations[t.occurrence_id]) for t in book.tracks)
    if actual is None:
        raise ProcessingError("the combined MP3 has no readable duration", stage="validate",
                              detail=str(combined))
    # Each encoded constituent may carry a few tens of milliseconds of
    # encoder padding across a join; allow for that per constituent.
    tolerance = max(DURATION_TOLERANCE_SECONDS,
                    DURATION_TOLERANCE_RATIO * expected_total + 0.05 * len(book.tracks))
    if abs(actual - expected_total) > tolerance:
        raise ProcessingError(
            f"the combined MP3 lasts {actual:.2f} s, expected {expected_total:.2f} s",
            stage="validate", detail=str(combined))
    try:
        tags = ID3(str(combined))
        present = {key.split(":")[0] for key in tags.keys()}
    except ID3NoHeaderError:
        tags, present = None, set()
    expected = _expected_combined_frames(book, artwork)
    if present != expected:
        raise ProcessingError(
            f"the combined MP3 carries frames {sorted(present)}, expected {sorted(expected)}",
            stage="validate", detail=str(combined))
    if tags is not None:
        for frame_id, value in (("TIT2", book.album), ("TALB", book.album),
                                ("TPE1", book.artist), ("TPE2", book.album_artist)):
            if frame_id in expected:
                actual_text = "/".join(str(t) for t in tags[frame_id].text)
                if actual_text != value:
                    raise ProcessingError(f"{frame_id} reads {actual_text!r}, expected {value!r}",
                                          stage="validate", detail=str(combined))
        if artwork is not None:
            pictures = [frame for key, frame in tags.items() if key.startswith("APIC")]
            if len(pictures) != 1 or pictures[0].data != artwork.data \
                    or pictures[0].mime != artwork.mime \
                    or int(pictures[0].type) != mp3_artwork.FRONT_COVER:
                raise ProcessingError("the combined artwork is not the planned front cover",
                                      stage="validate", detail=str(combined))
    sheet = book.timestamps_staged
    if not _plausible_output(sheet):
        raise ProcessingError("the timestamp file is missing or empty", stage="validate",
                              detail=str(sheet))
    lines = sheet.read_text(encoding="utf-8").splitlines()
    if lines != timestamp_lines(book, durations):
        raise ProcessingError("the timestamp file does not match the frozen titles and "
                              "adjusted durations", stage="validate", detail=str(sheet))
