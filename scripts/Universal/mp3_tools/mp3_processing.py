"""MP3 processing: the FFmpeg helpers and the Write ID3 engine — v0.6.3 focused
MP3 redesign, Phase 7.

Two things live here, and nothing that touches a widget, a thread or a
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
"""

from __future__ import annotations

import shlex
from collections.abc import Callable
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
    "WriteId3Report",
    "write_id3_run",
    "write_id3_book",
    "validate_staged_track",
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


def concat_mp3s_fast(listfile: Path, out_mp3: Path, log_dir: Path) -> bool:
    args = [
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
    code, _, err = run_ff(args)
    if code != 0:
        save_error_log(log_dir, "FAST PATH concat_mp3s_fast", args, err)
    return code == 0


# ---------------------------
# SAFE PATH (WAV normalize + optional gaps)
# ---------------------------


def normalize_to_wav(in_path: Path, out_wav: Path, log_dir: Path) -> bool:
    args = [
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


def concat_wavs_to_mp3(listfile: Path, out_mp3: Path, log_dir: Path) -> bool:
    args = [
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
    """One line of what the engine is doing — the narrow seam a log can render."""

    book_id: str
    occurrence_id: str | None
    stage: str
    message: str
    detail: str = ""


Listener = Callable[[ProcessingEvent], object]


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
class WriteId3Report:
    plan: mp3_plan.RunPlan
    books: tuple[BookReport, ...]

    @property
    def failed_book_ids(self) -> tuple[str, ...]:
        return tuple(entry.book_id for entry in self.books if not entry.succeeded)


def _check(checkpoint: Checkpoint | None) -> None:
    if checkpoint is not None:
        checkpoint()


def _emit(listener: Listener | None, event: ProcessingEvent) -> None:
    if listener is not None:
        listener(event)


def write_id3_run(plan: mp3_plan.RunPlan, *, checkpoint: Checkpoint | None = None,
                  on_event: Listener | None = None) -> WriteId3Report:
    """Run every planned Book in frozen order. A failed Book never stops the next."""
    if not isinstance(plan, mp3_plan.RunPlan):
        raise ProcessingError(f"plan must be a RunPlan, got {type(plan).__name__}")
    if plan.operation is not mp3_plan.MP3Operation.WRITE_ID3:
        raise ProcessingError(
            f"write_id3_run runs a Write ID3 plan, not {plan.operation.value}")
    reports: list[BookReport] = []
    for book in plan.books:
        _check(checkpoint)
        reports.append(write_id3_book(book, checkpoint=checkpoint, on_event=on_event))
    return WriteId3Report(plan=plan, books=tuple(reports))


def write_id3_book(book: mp3_plan.BookPlan, *, checkpoint: Checkpoint | None = None,
                   on_event: Listener | None = None) -> BookReport:
    """Stage, tag and validate every track of one Book, then publish it whole.

    Reads the frozen plan and nothing else. Track failures are recorded
    against the real occurrence id and the Book goes on to its remaining
    tracks, so the retry has as much staged work to reuse as possible; the
    Book is published only if nothing failed.
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
        _emit(on_event, ProcessingEvent(book.book_id, None, stage, message, detail))
        return _settle(book, failures, staged_ok, ())

    _emit(on_event, ProcessingEvent(book.book_id, None, "book",
                                    f"Book {book.number} — started: {len(book.tracks)} track(s)"))
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
        _emit(on_event, ProcessingEvent(
            book.book_id, track.occurrence_id, "track",
            f"Book {book.number} — track {track.position} of {len(book.tracks)}: "
            f"{track.filename}"))
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
                                            f"{track.filename}: {exc}", exc.detail))
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
                                        f"{len(book.tracks)} track(s)"))
    else:
        _emit(on_event, ProcessingEvent(
            book.book_id, None, "book",
            f"Book {book.number} — failed: {len(failures)} track(s); nothing published"))
    return _settle(book, failures, staged_ok, published)


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
