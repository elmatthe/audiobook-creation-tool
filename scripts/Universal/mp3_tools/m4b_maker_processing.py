"""M4B Maker processing: one frozen Book, from staging to atomic publication —
v0.6.4 Phase 4.

The proven Maker engine the panel has always run, moved here behind the frozen
Phase 3 plan so the panel (Phase 6) and the batch runner (Phase 5) share one
copy that reads **nothing live**: no widget, no Tk variable, no workspace.
Everything an execution needs arrives as a :class:`~mp3_tools.m4b_maker_plan.BookPlan`
plus explicit dependencies — the work root it may stage under, the frozen
Fast-first option, a cancellation checkpoint and an event listener.

What moved verbatim from ``m4b_maker.py``: the ffmetadata builder with its
chapter lead-in and minimum length, the concat-list writer, WAV normalisation,
silence generation, the two duration probes and the two start/total
calculations, and the FAST and Safe concat commands. Two things changed
deliberately:

- **Artwork is no longer an FFmpeg input.** The cover is applied to the
  *staged* M4B afterwards through the Phase 1 ``m4b_artwork`` service (mutagen
  ``covr``), which is what lets HEIC/HEIF be converted in memory and leaves the
  encoded audio stream untouched (plan sections 5.11 and Phase 4).
- **Nothing is ever encoded to the published path.** The Book builds in its
  private staging directory, is validated there, and is published only when
  every step succeeded; a failed or cancelled Book leaves no visible partial
  M4B (section 5.13).

The path decision is the panel's, preserved: inserted silence forces the Safe
workflow (normalise every track to WAV, put one silence WAV between adjacent
tracks, never after the last); otherwise FAST is tried when Fast-first is on
and a FAST failure falls back to Safe automatically with the reason emitted;
Fast-first off means Safe. Chapter starts are computed from the sources'
durations (FAST) or the normalised WAVs (Safe), and the final frozen titles are
written through the ffmetadata file. Core metadata rides the same ffmetadata
header; the manual Series Name / Series Part are written to the staged file
with the shared ``metadata.write_m4b_tags``. **No success-driven series number
is proposed, consumed or written here** — a plan whose Series Part is ``None``
(Auto-number on) gets its Series Name only, and Phase 5 finalises the part on
the staged file before publication.

Staging and publication
-----------------------
:func:`prepare_staging` creates the Book's own directory directly under the
operation's work root and nowhere else; :func:`publish_book` moves the staged
M4B onto its already-planned final path with ``os.replace`` — or, when the
custom work root lives on another filesystem, through a plan-owned temporary
sibling in the destination folder followed by the same atomic replace — and
refuses if the destination already exists; :func:`discard_staging` removes the
Book's staging directory and nothing outside it, never following a link.
"""

from __future__ import annotations

import contextlib
import json
import os
import traceback
import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from subprocess import CalledProcessError

from shared import ffmpeg_utils, metadata, output_paths
from shared import subprocess_utils as sp
from shared.cancellation import ConversionCancelled, raise_if_cancelled
from mp3_tools import m4b_artwork
from mp3_tools import m4b_staging
from mp3_tools.m4b_maker_plan import BookPlan

__all__ = [
    "ProcessingError",
    "ProcessingEvent",
    "BookOutcome",
    "LEADIN_MS",
    "WAV_SR",
    "WAV_CH",
    "WAV_FMT",
    "DEFAULT_BITRATE",
    "build_ffmetadata_from_starts",
    "write_concat_list",
    "ffprobe_duration_ms",
    "normalize_to_wav",
    "create_silence_wav",
    "wav_duration_ms",
    "compute_starts_total_fast",
    "compute_audio_starts_with_silence",
    "fast_concat_args",
    "safe_concat_args",
    "run_ffmpeg",
    "prepare_staging",
    "stage_book",
    "validate_staged_m4b",
    "publish_book",
    "discard_staging",
    "build_book",
]

# -------- tuning (moved from the panel) --------
LEADIN_MS = 250
WAV_SR = 44100
WAV_CH = 2
WAV_FMT = "s16"

#: The panel's AAC bitrate, spelled once.
DEFAULT_BITRATE = "128k"


class ProcessingError(Exception):
    """One Book could not be processed. Carries the stage it failed at."""

    def __init__(self, message: str, *, stage: str = "processing", detail: str = "") -> None:
        super().__init__(message)
        self.stage = stage
        self.detail = detail


@dataclass(frozen=True)
class ProcessingEvent:
    """One line of what the engine is doing — the narrow seam a log can render.

    ``stage`` names the step (``artwork``, ``normalize``, ``silence``, ``fast``,
    ``fallback``, ``safe``, ``series``, ``cover``, ``validate``, ``publish``,
    ``completed``, ``failed``, ``cancelled``); ``kind`` is ``technical``,
    ``failure`` or ``completed`` so a consumer can project it without parsing.
    """

    book_id: str
    stage: str
    message: str
    detail: str = ""
    kind: str = "technical"


@dataclass(frozen=True)
class BookOutcome:
    """How one Book's execution ended. A value; nothing live inside."""

    book_id: str
    succeeded: bool
    published: Path | None = None
    staged: Path | None = None
    path_used: str | None = None
    cancelled: bool = False
    failure_stage: str | None = None
    failure_message: str = ""
    failure_detail: str = ""


Checkpoint = Callable[[], None]
Listener = Callable[[ProcessingEvent], object]


# --------------------------------------------------------------------------- #
# Helpers moved verbatim from the panel
# --------------------------------------------------------------------------- #


def ffprobe_duration_ms(p: Path) -> int:
    data = sp.check_output(
        [
            ffmpeg_utils.ffprobe_cmd(),
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=duration",
            "-of",
            "json",
            str(p),
        ]
    )
    j = json.loads(data)
    dur = j["streams"][0].get("duration") if j.get("streams") else None
    if dur is None:
        data = sp.check_output(
            [
                ffmpeg_utils.ffprobe_cmd(),
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nk=1:nw=1",
                str(p),
            ]
        )
        dur = data.decode().strip()
    return max(int(round(float(dur) * 1000)), 0)


def build_ffmetadata_from_starts(titles, starts_ms, meta, total_ms):
    """Create ffmetadata with proper chapter ends (last chapter ends at total_ms-1)."""
    lines = [";FFMETADATA1"]
    lines += metadata.ffmetadata_header_lines(
        {
            "title": meta.get("title"),
            "artist": meta.get("artist"),
            "album_artist": meta.get("album_artist"),
            "album": meta.get("album"),
        }
    )

    n = len(titles)
    for i in range(n):
        start = max(starts_ms[i] - LEADIN_MS, 0)
        end = (starts_ms[i + 1] - 1) if (i + 1 < n) else (total_ms - 1)
        end = max(min(end, total_ms - 1), start + 100)  # >=100ms
        lines += [
            "",
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={start}",
            f"END={end}",
            f"title={metadata.ffmetadata_escape(titles[i])}",
        ]
    return "\n".join(lines)


def write_concat_list(paths, dest: Path):
    with open(dest, "w", encoding="utf-8") as f:
        for p in paths:
            pp = str(p).replace("'", r"'\'\'")
            f.write(f"file '{pp}'\n")


def normalize_to_wav(inputs, tmp_dir: Path, cancel_check=None):
    wav_dir = tmp_dir / "wav"
    wav_dir.mkdir(parents=True, exist_ok=True)
    wavs = []
    for i, src in enumerate(inputs, 1):
        raise_if_cancelled(cancel_check)
        dst = wav_dir / f"{i:04d}.wav"
        cmd = [
            ffmpeg_utils.ffmpeg_cmd(),
            "-hide_banner",
            "-y",
            "-i",
            str(src),
            "-vn",
            "-ac",
            str(WAV_CH),
            "-ar",
            str(WAV_SR),
            "-sample_fmt",
            WAV_FMT,
            "-af",
            "asetpts=N/SR/TB,aresample=async=1:first_pts=0",
            "-fflags",
            "+genpts",
            "-avoid_negative_ts",
            "make_zero",
            "-map_metadata",
            "-1",
            str(dst),
        ]
        run_ffmpeg(cmd)
        wavs.append(dst)
    return wavs


def create_silence_wav(seconds: float, tmp_dir: Path) -> Path:
    dst = tmp_dir / f"silence_{seconds:.3f}s.wav"
    cmd = [
        ffmpeg_utils.ffmpeg_cmd(),
        "-hide_banner",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=r={WAV_SR}:cl=stereo",
        "-t",
        f"{seconds:.6f}",
        "-ar",
        str(WAV_SR),
        "-ac",
        str(WAV_CH),
        "-sample_fmt",
        WAV_FMT,
        str(dst),
    ]
    run_ffmpeg(cmd)
    return dst


def wav_duration_ms(wav_path: Path) -> int:
    with contextlib.closing(wave.open(str(wav_path), "rb")) as w:
        return int(round(w.getnframes() * 1000.0 / w.getframerate()))


def compute_starts_total_fast(files):
    starts = []
    t = 0
    for p in files:
        starts.append(t)
        t += ffprobe_duration_ms(p)
    return starts, t


def compute_audio_starts_with_silence(wavs, silence_ms):
    """Return (chapter_starts_ms_for_audio_only, total_ms_including_silence)."""
    starts = []
    t = 0
    for i, w in enumerate(wavs):
        starts.append(t)
        t += wav_duration_ms(w)
        if i < len(wavs) - 1:
            t += silence_ms
    return starts, t


# --------------------------------------------------------------------------- #
# The two concat commands, as the panel runs them, minus the cover input
# --------------------------------------------------------------------------- #


def safe_concat_args(audio_list_path, ffmeta_path, out_path, bitrate) -> list[str]:
    cmd = [
        ffmpeg_utils.ffmpeg_cmd(),
        "-hide_banner",
        "-y",
        "-xerror",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(audio_list_path),
        "-i",
        str(ffmeta_path),
    ]
    maps = ["-map_metadata", "1", "-map_chapters", "1", "-map", "0:a:0"]
    cmd += maps + [
        "-c:a",
        "aac",
        "-b:a",
        bitrate,
        "-ar",
        str(WAV_SR),
        "-ac",
        str(WAV_CH),
        "-movflags",
        "+faststart",
        str(out_path),
    ]
    return cmd


def fast_concat_args(audio_list_path, ffmeta_path, out_path, bitrate) -> list[str]:
    # IMPORTANT: declare ALL inputs first, then output options. ffmpeg scopes an
    # option to the next file token, so an output-only option placed before an
    # input is wrongly parsed as an input option. ``-fflags +genpts`` stays an
    # input option on the concat demuxer (before its ``-i``); ``-filter:a`` and
    # ``-avoid_negative_ts`` are output options.
    cmd = [
        ffmpeg_utils.ffmpeg_cmd(),
        "-hide_banner",
        "-y",
        "-xerror",
        "-fflags",
        "+genpts",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(audio_list_path),
        "-i",
        str(ffmeta_path),
    ]
    maps = ["-map_metadata", "1", "-map_chapters", "1", "-map", "0:a:0"]
    cmd += maps
    cmd += ["-filter:a", "asetpts=N/SR/TB,aresample=async=1:first_pts=0"]
    cmd += [
        "-c:a",
        "aac",
        "-b:a",
        bitrate,
        "-avoid_negative_ts",
        "make_zero",
        "-movflags",
        "+faststart",
        str(out_path),
    ]
    return cmd


def run_ffmpeg(args) -> None:
    """Run one FFmpeg command, raising ``CalledProcessError`` with its stderr."""
    from subprocess import PIPE

    sp.run(list(args), check=True, stdout=PIPE, stderr=PIPE)


def _stderr_of(exc: CalledProcessError) -> str:
    stderr = getattr(exc, "stderr", None)
    if not stderr:
        return str(exc)
    try:
        return stderr.decode("utf-8", "replace") if isinstance(stderr, bytes) else str(stderr)
    except Exception:
        return str(exc)


# --------------------------------------------------------------------------- #
# Staging boundaries
# --------------------------------------------------------------------------- #


def _require_plan(book: object) -> BookPlan:
    if not isinstance(book, BookPlan):
        raise ProcessingError(f"book must be a BookPlan, got {type(book).__name__}",
                              stage="plan")
    return book


def _staging(call, book: BookPlan, work_root: Path):
    """Run one shared staging operation, re-raising its refusal as this engine's."""
    try:
        return call(book, work_root=work_root)
    except m4b_staging.StagingError as exc:
        raise ProcessingError(str(exc), stage=exc.stage, detail=exc.detail) from exc


def _require_owned(book: BookPlan, work_root: Path) -> Path:
    """The staging directory must be ``<work_root>/<name>``, exactly."""
    try:
        return m4b_staging.require_owned(book, work_root)
    except m4b_staging.StagingError as exc:
        raise ProcessingError(str(exc), stage=exc.stage) from exc


def prepare_staging(book: BookPlan, *, work_root: Path) -> Path:
    """Create the Book's private staging directory. Idempotent. Nothing visible."""
    return _staging(m4b_staging.prepare_staging, _require_plan(book), work_root)


def discard_staging(book: BookPlan, *, work_root: Path) -> int:
    """Delete the Book's staging area and everything inside it, and nothing else."""
    return _staging(m4b_staging.discard_staging, _require_plan(book), work_root)


def publish_book(book: BookPlan, *, work_root: Path) -> Path:
    """Make a fully staged Book visible, atomically, at its planned path.

    The shared M4B staging pattern (``m4b_staging.publish_staged``): refuses an
    already-present destination, moves with ``os.replace``, and takes the
    temporary-sibling route when the work root is on another filesystem.
    """
    return _staging(m4b_staging.publish_staged, _require_plan(book), work_root)


# --------------------------------------------------------------------------- #
# Validation of the staged candidate
# --------------------------------------------------------------------------- #


def validate_staged_m4b(book: BookPlan, staged: Path) -> None:
    """Prove the staged file is the usable M4B the plan intends, or raise.

    Bounded to what the plan can be checked against: a regular, non-empty file;
    an audio stream with a positive duration; exactly the planned chapter
    titles, in order; the planned Title; and a cover present exactly when one
    was planned. Read through the shared ffprobe and metadata authorities.
    """
    if staged.is_symlink() or not staged.is_file() or staged.stat().st_size == 0:
        raise ProcessingError(f"{staged.name} was not produced", stage="validate")
    try:
        duration_ms = ffprobe_duration_ms(staged)
    except Exception as exc:
        raise ProcessingError(f"{staged.name} has no readable audio stream",
                              stage="validate", detail=repr(exc)) from exc
    if duration_ms <= 0:
        raise ProcessingError(f"{staged.name} has no audio", stage="validate")
    try:
        titles = tuple(metadata.read_chapter_titles(staged))
        tags = metadata.read_m4b_tags(staged)
    except Exception as exc:
        raise ProcessingError(f"{staged.name} could not be read back",
                              stage="validate", detail=repr(exc)) from exc
    if titles != tuple(book.chapter_titles):
        raise ProcessingError(
            f"{staged.name} carries {len(titles)} chapter(s), the plan has "
            f"{len(book.chapter_titles)}", stage="validate",
            detail=f"found {titles!r}, planned {tuple(book.chapter_titles)!r}")
    if str(tags.get("title", "")) != book.title:
        raise ProcessingError(f"{staged.name} carries the wrong title", stage="validate",
                              detail=f"found {tags.get('title')!r}, planned {book.title!r}")
    if bool(tags.get("has_cover")) != (book.artwork is not None):
        raise ProcessingError(f"{staged.name} artwork does not match the plan", stage="validate")


# --------------------------------------------------------------------------- #
# One Book
# --------------------------------------------------------------------------- #


def _emit(listener: Listener | None, event: ProcessingEvent) -> None:
    if listener is not None:
        listener(event)


def _failed(book: BookPlan, stage: str, message: str, detail: str,
            listener: Listener | None) -> BookOutcome:
    _emit(listener, ProcessingEvent(book.book_id, stage, message, detail, kind="failure"))
    _emit(listener, ProcessingEvent(book.book_id, "failed", f"{book.filename}: {message}",
                                    detail, kind="failure"))
    return BookOutcome(book_id=book.book_id, succeeded=False, failure_stage=stage,
                       failure_message=message, failure_detail=detail or message)


def stage_book(book: BookPlan, *, work_root: Path, fast_first: bool,
               checkpoint: Checkpoint | None = None, on_event: Listener | None = None,
               bitrate: str = DEFAULT_BITRATE) -> BookOutcome:
    """Build, tag, cover and validate one Book **in staging**. Publishes nothing.

    On success the staged M4B is at ``book.staged`` and the intermediates are
    gone; on failure or cancellation the whole staging directory is removed
    and the outcome says why. Reads the frozen plan and nothing else.
    """
    book = _require_plan(book)
    work = _require_owned(book, work_root)
    cancel_check = None
    if checkpoint is not None:
        def cancel_check() -> bool:  # noqa: E306 - closure over the checkpoint
            try:
                checkpoint()
            except ConversionCancelled:
                return True
            return False

    if not ffmpeg_utils.verified_ffmpeg():
        return _failed(book, "ffmpeg", "FFmpeg is not ready on this computer",
                       ffmpeg_utils.status_line(), on_event)

    staging_dir: Path | None = None
    keep = False
    try:
        raise_if_cancelled(cancel_check)
        # The cover is resolved before any encoding: an unusable image is a
        # cheap early answer, and the conversion is in memory only.
        cover = None
        if book.artwork is not None:
            _emit(on_event, ProcessingEvent(book.book_id, "artwork",
                                            f"Reading artwork {book.artwork.name}"))
            try:
                cover = m4b_artwork.cover_for(book)
            except m4b_artwork.ArtworkError as exc:
                return _failed(book, "artwork", str(exc), repr(exc), on_event)

        staging_dir = prepare_staging(book, work_root=work)
        files = list(book.sources)
        titles = list(book.chapter_titles)
        silence_ms = int(round(book.silence * 1000))
        raise_if_cancelled(cancel_check)

        if silence_ms > 0:
            _emit(on_event, ProcessingEvent(
                book.book_id, "normalize", "Normalizing to WAV and inserting silence…",
                f"{book.silence:.3f}s between tracks forces the Safe workflow"))
            wavs = normalize_to_wav(files, staging_dir, cancel_check=cancel_check)
            _emit(on_event, ProcessingEvent(book.book_id, "silence",
                                            f"Inserting {book.silence:.3f}s of silence"))
            gap = create_silence_wav(book.silence, staging_dir)
            seq = []
            for i, w in enumerate(wavs):
                seq.append(w)
                if i < len(wavs) - 1:
                    seq.append(gap)
            starts_ms, total_ms = compute_audio_starts_with_silence(wavs, silence_ms)
            audio_for_build = seq
            use_safe = True
        else:
            audio_for_build = files
            starts_ms, total_ms = compute_starts_total_fast(files)
            use_safe = False

        raise_if_cancelled(cancel_check)
        meta = {"title": book.title, "artist": book.artist,
                "album_artist": book.album_artist, "album": book.album}
        ffmeta = staging_dir / "chapters.ffmeta.txt"
        ffmeta.write_text(build_ffmetadata_from_starts(titles, starts_ms, meta, total_ms),
                          encoding="utf-8")
        listfile = staging_dir / "inputs.txt"
        write_concat_list(audio_for_build, listfile)
        staged = book.staged

        path_used: str
        try:
            if not use_safe and fast_first:
                _emit(on_event, ProcessingEvent(book.book_id, "fast", "Trying FAST concat mode…"))
                path_used = "fast"
                run_ffmpeg(fast_concat_args(listfile, ffmeta, staged, bitrate))
            else:
                _emit(on_event, ProcessingEvent(
                    book.book_id, "safe", "Using SAFE concat mode…",
                    "inserted silence" if use_safe else "Fast-first is off"))
                path_used = "safe"
                run_ffmpeg(safe_concat_args(listfile, ffmeta, staged, bitrate))
        except CalledProcessError as exc:
            raise_if_cancelled(cancel_check)
            if use_safe:
                raise
            reason = _stderr_of(exc)
            _emit(on_event, ProcessingEvent(
                book.book_id, "fallback", "FAST concat failed — retrying in Safe Mode…",
                reason, kind="technical"))
            wavs = normalize_to_wav(files, staging_dir, cancel_check=cancel_check)
            write_concat_list(wavs, listfile)
            starts_ms, total_ms = compute_audio_starts_with_silence(wavs, 0)
            ffmeta.write_text(build_ffmetadata_from_starts(titles, starts_ms, meta, total_ms),
                              encoding="utf-8")
            _emit(on_event, ProcessingEvent(book.book_id, "safe", "Using SAFE concat mode…",
                                            "after FAST failure"))
            path_used = "safe"
            run_ffmpeg(safe_concat_args(listfile, ffmeta, staged, bitrate))

        raise_if_cancelled(cancel_check)
        # Series tags (freeform atoms) — ffmpeg cannot write these, so they go
        # on the staged file with mutagen. Manual part only: with Auto-number
        # on, the plan carries None and Phase 5 finalises the number.
        series_tags = {}
        if book.series.strip():
            series_tags["series"] = book.series
        if book.series_part is not None and book.series_part.strip():
            series_tags["series_part"] = book.series_part
        if series_tags:
            _emit(on_event, ProcessingEvent(book.book_id, "series", "Writing series tags…"))
            try:
                metadata.write_m4b_tags(staged, series_tags)
            except Exception as exc:
                return _failed(book, "series", "the series tags could not be written",
                               f"{type(exc).__name__}: {exc}", on_event)

        if cover is not None:
            _emit(on_event, ProcessingEvent(book.book_id, "cover", "Embedding cover artwork…",
                                            "in memory; the audio is not re-encoded"))
            try:
                m4b_artwork.embed_cover(staged, cover)
            except m4b_artwork.ArtworkError as exc:
                return _failed(book, "cover", str(exc), repr(exc), on_event)

        raise_if_cancelled(cancel_check)
        _emit(on_event, ProcessingEvent(book.book_id, "validate", "Validating the staged M4B…"))
        validate_staged_m4b(book, staged)

        # Only the candidate survives in staging; intermediates are this
        # operation's and go now.
        for intermediate in (ffmeta, listfile):
            intermediate.unlink(missing_ok=True)
        wav_dir = staging_dir / "wav"
        if wav_dir.is_dir() and not wav_dir.is_symlink():
            for entry in wav_dir.iterdir():
                if not entry.is_symlink():
                    output_paths.assert_contained(staging_dir, entry)
                entry.unlink()
            wav_dir.rmdir()
        for entry in staging_dir.iterdir():
            if entry != staged and entry.is_file() and not entry.is_symlink() \
                    and entry.suffix.lower() == ".wav":
                output_paths.assert_contained(staging_dir, entry)
                entry.unlink()
        keep = True
        return BookOutcome(book_id=book.book_id, succeeded=True, staged=staged,
                           path_used=path_used)

    except ConversionCancelled:
        _emit(on_event, ProcessingEvent(book.book_id, "cancelled",
                                        f"{book.filename}: cancelled", kind="failure"))
        return BookOutcome(book_id=book.book_id, succeeded=False, cancelled=True,
                           failure_stage="cancelled", failure_message="cancelled")
    except ProcessingError as exc:
        return _failed(book, exc.stage, str(exc), exc.detail, on_event)
    except CalledProcessError as exc:
        return _failed(book, "encode", "ffmpeg failed", _stderr_of(exc), on_event)
    except Exception as exc:
        return _failed(book, "processing", f"{type(exc).__name__}: {exc}",
                       traceback.format_exc(), on_event)
    finally:
        # A staged candidate survives only a fully successful staging; a
        # failed or cancelled Book keeps nothing.
        if staging_dir is not None and not keep:
            _discard_quietly(book, work)


def build_book(book: BookPlan, *, work_root: Path, fast_first: bool,
               checkpoint: Checkpoint | None = None, on_event: Listener | None = None,
               bitrate: str = DEFAULT_BITRATE) -> BookOutcome:
    """Stage one Book and, if everything succeeded, publish it atomically.

    The whole single-Book contract of plan section 5.13: a final M4B becomes
    visible only after audio, chapters, metadata, artwork, series data and
    validation all succeeded. Cancellation or failure at any step publishes
    nothing and leaves no operation-owned state behind.
    """
    book = _require_plan(book)
    work = _require_owned(book, work_root)
    staged = stage_book(book, work_root=work, fast_first=fast_first, checkpoint=checkpoint,
                        on_event=on_event, bitrate=bitrate)
    if not staged.succeeded:
        return staged
    try:
        _emit(on_event, ProcessingEvent(book.book_id, "publish",
                                        f"Publishing {book.filename}…"))
        published = publish_book(book, work_root=work)
    except ProcessingError as exc:
        outcome = _failed(book, exc.stage, str(exc), exc.detail, on_event)
        _discard_quietly(book, work)
        return outcome
    _discard_quietly(book, work)
    _emit(on_event, ProcessingEvent(book.book_id, "completed", f"✓ {published.name}",
                                    str(published), kind="completed"))
    return BookOutcome(book_id=book.book_id, succeeded=True, published=published,
                       path_used=staged.path_used)


def _discard_quietly(book: BookPlan, work: Path) -> None:
    """Drop the Book's staging, then the work root **if it is now empty**."""
    try:
        discard_staging(book, work_root=work)
    except Exception:
        pass
    m4b_staging.prune_work_root(work)
