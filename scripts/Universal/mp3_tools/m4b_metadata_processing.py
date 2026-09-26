"""M4B Metadata Editor processing: one frozen Book, from private staging to
atomic publication — v0.6.4 Phase 9.

The per-Book transaction the Editor panel has always run — copy the source,
then clear / write / strip / retitle *the copy* — moved behind the frozen
Phase 8 :class:`~mp3_tools.m4b_metadata_plan.BookPlan` so the batch runner and
the Phase 10 panel share one copy that reads **nothing live**: no widget, no
Tk variable, no workspace, no observation store. One thing changed
deliberately: the copy now lands in the Book's **private staging directory**
under the run's ``.work`` area and is published onto its planned final path
only after every step and the validation succeeded. The old panel copied
straight to the destination, so a tag write that failed after the copy left a
visible, half-done file behind; here a failed or cancelled Book publishes
nothing and leaves no operation-owned state (plan section 6.13).

The three actions, each through the shared authorities and nothing else:

- **Save Tags** — ``metadata.write_m4b_tags`` with exactly the plan's frozen
  ``writes`` (Shared over Book; nothing when there are none), then the
  explicit cover (``m4b_artwork.embed_cover``) and the positional chapter
  edits (``metadata.apply_chapter_titles``). No write → the copy's tags are
  the source's; the source cover and titles stay unless replaced.
- **Clear All Tags (keep chapters)** — ``metadata.clear_metadata_keep_chapters``
  first, then the same frozen writes / cover / chapter edits reapplied, so a
  prefilled-but-unchanged value cannot survive the clear by accident and the
  cover stays removed unless one was explicitly chosen.
- **Remove Series Numbering** — ``metadata.clear_series_numbering`` with
  ``keep_series_name=True``: every numbering surface goes (``trkn``, the
  movement index/count, every vendor ``…:PART`` / ``…:SERIES-PART`` atom) and
  the Series Name stays on whichever surface carried it. Nothing else is
  written: the plan froze no edits for this action.

The audio is never re-encoded: tag edits are mutagen atom rewrites, the cover
is a ``covr`` rewrite, and the chapter retitle is the shared ``-c copy`` remux.
The source file is never opened for writing.

Validation reads the chapter *structure* back, not only the titles. ffprobe
merges a file's Nero ``chpl`` list with its QuickTime chapter text track by
chapter id, so a text track that lost samples can still read back the planned
titles: on 2026-09-20 FFmpeg 9's mov muxer dropped every chapter longer than
~487 s from the track it rebuilt and re-keyed the short survivors onto chapters
0..k-1, and a Book whose short chapters happened to lead would have passed a
titles-only check with a one-sample track. :func:`validate_staged` therefore
requires the staged copy to keep the source's chapter count and boundaries,
and — when the chapter remux ran — a text track holding one sample per
chapter (plan section 6.13: a failed Book publishes nothing).

Auto-number is the batch's business (plan section 6.9): with Auto-number on
the batch proposes a success-driven Series Part, writes it onto the **staged**
candidate with the same shared writer, re-validates, and commits only after
publication. This module offers :func:`validate_staged` the ``series_part``
it should expect; it allocates and consumes nothing.

Staging and publication are the shared M4B pattern (``m4b_staging``): the
staging directory is exactly ``<work root>/<final stem>``; publication refuses
an already-present destination and moves atomically; discard removes the
staging directory and nothing outside it.
"""

from __future__ import annotations

import shutil
import traceback
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from shared import ffmpeg_utils, metadata
from shared.cancellation import ConversionCancelled, raise_if_cancelled
from mp3_tools import m4b_artwork
from mp3_tools import m4b_staging
from mp3_tools.m4b_metadata_plan import BookPlan, EditorAction

__all__ = [
    "ProcessingError",
    "ProcessingEvent",
    "BookOutcome",
    "prepare_staging",
    "discard_staging",
    "publish_book",
    "expected_chapter_titles",
    "chapter_titles_retitled",
    "validate_chapter_structure",
    "validate_staged",
    "stage_book",
    "build_book",
]


class ProcessingError(Exception):
    """One Book could not be processed. Carries the stage it failed at."""

    def __init__(self, message: str, *, stage: str = "processing", detail: str = "") -> None:
        super().__init__(message)
        self.stage = stage
        self.detail = detail


@dataclass(frozen=True)
class ProcessingEvent:
    """One line of what the engine is doing — the narrow seam a log can render.

    ``stage`` names the step (``source``, ``artwork``, ``copy``, ``clear``,
    ``tags``, ``cover``, ``chapters``, ``series``, ``validate``, ``publish``,
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
    cancelled: bool = False
    failure_stage: str | None = None
    failure_message: str = ""
    failure_detail: str = ""


Checkpoint = Callable[[], None]
Listener = Callable[[ProcessingEvent], object]

#: The text fields the Editor edits, in the shared writer's vocabulary.
_TEXT_FIELDS = ("title", "artist", "album", "year", "genre", "comment", "series")


# --------------------------------------------------------------------------- #
# Staging boundaries (the shared M4B pattern, re-raised as this engine's)
# --------------------------------------------------------------------------- #


def _require_plan(book: object) -> BookPlan:
    if not isinstance(book, BookPlan):
        raise ProcessingError(f"book must be an Editor BookPlan, got {type(book).__name__}",
                              stage="plan")
    return book


def _staging(call, book: BookPlan, work_root: Path):
    try:
        return call(book, work_root=work_root)
    except m4b_staging.StagingError as exc:
        raise ProcessingError(str(exc), stage=exc.stage, detail=exc.detail) from exc


def _require_owned(book: BookPlan, work_root: Path) -> Path:
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

    Refuses an already-present destination — the planner reserved the name and
    anything there now is someone else's — and never overwrites.
    """
    return _staging(m4b_staging.publish_staged, _require_plan(book), work_root)


# --------------------------------------------------------------------------- #
# Validation of the staged candidate
# --------------------------------------------------------------------------- #


#: Chapter boundaries are compared in seconds after a ``-c copy`` remux may have
#: rescaled them (a 1/44100 source lands on the pinned 1/1000 movie timescale,
#: at most half a millisecond away). Ten milliseconds is far below any chapter
#: the remux could mislay and far above any honest rescale.
CHAPTER_BOUNDARY_TOLERANCE = 0.01


def chapter_titles_retitled(book: BookPlan) -> bool:
    """Whether :func:`stage_book` runs the chapter remux for this plan — the
    same predicate, so validation asks for a rebuilt text track exactly when
    one was built."""
    if book.action is EditorAction.REMOVE_SERIES_NUMBERING:
        return False
    return any(edit is not None for edit in book.chapter_edits)


def _same_instant(a: float, b: float) -> bool:
    """Equal within the tolerance; two unreadable (NaN) instants count as the same."""
    if a != a and b != b:
        return True
    return abs(a - b) <= CHAPTER_BOUNDARY_TOLERANCE


def validate_chapter_structure(book: BookPlan, staged: Path, *,
                               source: metadata.ChapterStructure,
                               found: metadata.ChapterStructure) -> None:
    """Prove the staged copy kept the source's chapter structure, or raise.

    Count and boundaries must match the source (the remux is told the source's
    own ``[CHAPTER]`` list and changes titles only). When the remux ran, the
    QuickTime chapter text track it rebuilt must hold one sample per chapter;
    when it did not, the track is whatever the source had — a ``chpl``-only
    source stays ``chpl``-only — and must simply be unchanged. Nothing here
    judges the source: an odd but valid file passes as long as its copy is
    structurally the same file.
    """
    if found.count != source.count:
        raise ProcessingError(f"{staged.name} chapter count changed", stage="validate",
                              detail=f"found {found.count}, source {source.count}")
    for index, (kept, had) in enumerate(zip(found.boundaries, source.boundaries)):
        if not all(_same_instant(a, b) for a, b in zip(kept, had)):
            raise ProcessingError(f"{staged.name} chapter {index + 1} boundaries moved",
                                  stage="validate", detail=f"found {kept!r}, source {had!r}")
    if chapter_titles_retitled(book):
        if found.track_samples != found.count:
            raise ProcessingError(
                f"{staged.name} chapter track is incomplete", stage="validate",
                detail=f"text track holds {found.track_samples!r} samples for "
                       f"{found.count} chapters")
    elif found.track_samples != source.track_samples:
        raise ProcessingError(f"{staged.name} chapter track changed", stage="validate",
                              detail=f"found {found.track_samples!r} samples, "
                                     f"source {source.track_samples!r}")


def expected_chapter_titles(book: BookPlan) -> tuple[str, ...]:
    """The titles the finished copy must carry: the source's, with the plan's
    positional edits applied (an edit past the source's count is ignored)."""
    titles = list(book.observation.chapter_titles)
    for index, edit in enumerate(book.chapter_edits):
        if index < len(titles) and edit is not None:
            titles[index] = edit
    return tuple(titles)


def _text(tags: Mapping, name: str) -> str:
    return str(tags.get(name) or "")


def validate_staged(book: BookPlan, staged: Path, *, series_part: int | None = None) -> None:
    """Prove the staged copy is what the frozen plan intends, or raise.

    Bounded to what the plan can be checked against: a regular, non-empty
    file with a readable audio stream; every frozen write present exactly;
    for a Clear, every text field that was not written absent; for a Remove,
    no Series Part left and the observed Series Name still there; the cover
    present exactly when the action leaves one; the expected chapter titles in
    order; the source's chapter count and boundaries, with a complete chapter
    text track whenever the remux rebuilt one; and, when the batch numbered the
    Book, that Series Part. Read through the shared ffprobe and metadata
    authorities only.
    """
    if staged.is_symlink() or not staged.is_file() or staged.stat().st_size == 0:
        raise ProcessingError(f"{staged.name} was not produced", stage="validate")
    info = ffmpeg_utils.probe_audio_stream(staged)
    if info is None or not info.get("codec_name"):
        raise ProcessingError(f"{staged.name} has no readable audio stream", stage="validate")
    duration = info.get("duration")
    if duration is not None and duration <= 0:
        raise ProcessingError(f"{staged.name} has no audio", stage="validate")
    try:
        tags = metadata.read_m4b_tags(staged)
        titles = tuple(metadata.read_chapter_titles(staged))
        structure = metadata.read_chapter_structure(staged)
    except Exception as exc:
        raise ProcessingError(f"{staged.name} could not be read back", stage="validate",
                              detail=repr(exc)) from exc
    try:
        source_structure = metadata.read_chapter_structure(book.source)
    except Exception as exc:
        raise ProcessingError(f"{book.source.name} could not be read for comparison",
                              stage="validate", detail=repr(exc)) from exc

    observed = book.observation
    action = book.action
    for name, value in book.writes.items():
        if _text(tags, name) != value:
            raise ProcessingError(f"{staged.name} does not carry the {name} that was written",
                                  stage="validate",
                                  detail=f"found {tags.get(name)!r}, planned {value!r}")
    if action is EditorAction.CLEAR_ALL_TAGS:
        for name in _TEXT_FIELDS:
            if name not in book.writes and _text(tags, name):
                raise ProcessingError(f"{staged.name} still carries {name} after the clear",
                                      stage="validate", detail=repr(tags.get(name)))
        if series_part is None and _text(tags, "series_part"):
            raise ProcessingError(f"{staged.name} still carries a Series Part after the clear",
                                  stage="validate", detail=repr(tags.get("series_part")))
        cover_expected = book.artwork is not None
    elif action is EditorAction.REMOVE_SERIES_NUMBERING:
        if _text(tags, "series_part"):
            raise ProcessingError(f"{staged.name} still carries a Series Part",
                                  stage="validate", detail=repr(tags.get("series_part")))
        if observed.series and _text(tags, "series") != observed.series:
            raise ProcessingError(f"{staged.name} lost its Series Name", stage="validate",
                                  detail=f"found {tags.get('series')!r}, "
                                         f"observed {observed.series!r}")
        for name in _TEXT_FIELDS:
            if name != "series" and _text(tags, name) != observed.source_value(name):
                raise ProcessingError(f"{staged.name} changed its {name}", stage="validate",
                                      detail=f"found {tags.get(name)!r}, "
                                             f"observed {observed.source_value(name)!r}")
        cover_expected = observed.has_cover
    else:
        cover_expected = book.artwork is not None or observed.has_cover
    if series_part is not None and _text(tags, "series_part") != str(series_part):
        raise ProcessingError(f"{staged.name} does not carry Series Part {series_part}",
                              stage="validate", detail=repr(tags.get("series_part")))
    if bool(tags.get("has_cover")) != cover_expected:
        raise ProcessingError(f"{staged.name} artwork does not match the plan", stage="validate",
                              detail=f"has_cover={tags.get('has_cover')!r}, "
                                     f"expected {cover_expected}")
    expected = expected_chapter_titles(book)
    if titles != expected:
        raise ProcessingError(f"{staged.name} chapter titles do not match the plan",
                              stage="validate", detail=f"found {titles!r}, planned {expected!r}")
    validate_chapter_structure(book, staged, source=source_structure, found=structure)


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


def _step(stage: str, message: str, call, *args, **kwargs):
    """Run one shared-authority call; anything it raises becomes this stage's failure."""
    try:
        return call(*args, **kwargs)
    except ProcessingError:
        raise
    except ConversionCancelled:
        raise
    except Exception as exc:
        raise ProcessingError(message, stage=stage,
                              detail=f"{type(exc).__name__}: {exc}") from exc


def stage_book(book: BookPlan, *, work_root: Path, checkpoint: Checkpoint | None = None,
               on_event: Listener | None = None) -> BookOutcome:
    """Copy, act on, cover, retitle and validate one Book **in staging**.
    Publishes nothing.

    On success the finished copy is at ``book.staged``; on failure or
    cancellation the whole staging directory is removed and the outcome says
    why. Reads the frozen plan and nothing else; never writes the source.
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

    staging_dir: Path | None = None
    keep = False
    try:
        raise_if_cancelled(cancel_check)
        source = book.source
        if source.is_symlink() or not source.is_file():
            return _failed(book, "source", f"{source.name} is no longer available",
                           str(source), on_event)

        # The cover is resolved before anything is copied: an unusable image
        # is a cheap early answer, and the conversion is in memory only.
        cover = None
        if book.artwork is not None:
            _emit(on_event, ProcessingEvent(book.book_id, "artwork",
                                            f"Reading artwork {Path(book.artwork).name}"))
            try:
                cover = m4b_artwork.load_cover(book.artwork)
            except m4b_artwork.ArtworkError as exc:
                return _failed(book, "artwork", str(exc), repr(exc), on_event)

        staging_dir = prepare_staging(book, work_root=work)
        staged = book.staged
        _emit(on_event, ProcessingEvent(book.book_id, "copy",
                                        f"Copying {source.name} to staging"))
        _step("copy", f"{source.name} could not be copied", shutil.copy2, source, staged)
        raise_if_cancelled(cancel_check)

        writes = dict(book.writes)
        if book.action is EditorAction.REMOVE_SERIES_NUMBERING:
            _emit(on_event, ProcessingEvent(book.book_id, "series",
                                            "Removing series numbering (keeping the name)"))
            _step("series", "the series numbering could not be removed",
                  metadata.clear_series_numbering, staged, keep_series_name=True)
        else:
            if book.action is EditorAction.CLEAR_ALL_TAGS:
                _emit(on_event, ProcessingEvent(book.book_id, "clear",
                                                "Clearing all tags (keeping chapters)"))
                _step("clear", "the tags could not be cleared",
                      metadata.clear_metadata_keep_chapters, staged)
            if writes:
                _emit(on_event, ProcessingEvent(book.book_id, "tags",
                                                "Writing " + ", ".join(sorted(writes))))
                _step("tags", "the tags could not be written",
                      metadata.write_m4b_tags, staged, writes)
            if book.artwork is not None:
                _emit(on_event, ProcessingEvent(book.book_id, "cover", "Embedding the cover"))
                _step("cover", "the cover could not be embedded",
                      m4b_artwork.embed_cover, staged, cover)
            if chapter_titles_retitled(book):
                _emit(on_event, ProcessingEvent(book.book_id, "chapters",
                                                "Applying chapter titles"))
                _step("chapters", "the chapter titles could not be applied",
                      metadata.apply_chapter_titles, staged,
                      [edit or "" for edit in book.chapter_edits])

        _emit(on_event, ProcessingEvent(book.book_id, "validate", "Validating the copy"))
        validate_staged(book, staged)
        raise_if_cancelled(cancel_check)
        keep = True
        return BookOutcome(book_id=book.book_id, succeeded=True, staged=staged)

    except ConversionCancelled:
        _emit(on_event, ProcessingEvent(book.book_id, "cancelled",
                                        f"{book.filename}: cancelled", kind="failure"))
        return BookOutcome(book_id=book.book_id, succeeded=False, cancelled=True,
                           failure_stage="cancelled", failure_message="cancelled")
    except ProcessingError as exc:
        return _failed(book, exc.stage, str(exc), exc.detail, on_event)
    except Exception as exc:
        return _failed(book, "processing", f"{type(exc).__name__}: {exc}",
                       traceback.format_exc(), on_event)
    finally:
        # A staged candidate survives only a fully successful staging; a
        # failed or cancelled Book keeps nothing.
        if staging_dir is not None and not keep:
            _discard_quietly(book, work)


def build_book(book: BookPlan, *, work_root: Path, checkpoint: Checkpoint | None = None,
               on_event: Listener | None = None) -> BookOutcome:
    """Stage one Book and, if everything succeeded, publish it atomically.

    The whole single-Book contract of plan section 6.13: the finished copy
    becomes visible only after the copy, the action, the cover, the chapter
    titles and the validation all succeeded. Cancellation or failure at any
    step publishes nothing and leaves no operation-owned state behind.
    """
    book = _require_plan(book)
    work = _require_owned(book, work_root)
    staged = stage_book(book, work_root=work, checkpoint=checkpoint, on_event=on_event)
    if not staged.succeeded:
        return staged
    try:
        _emit(on_event, ProcessingEvent(book.book_id, "publish", f"Publishing {book.filename}…"))
        published = publish_book(book, work_root=work)
    except ProcessingError as exc:
        outcome = _failed(book, exc.stage, str(exc), exc.detail, on_event)
        _discard_quietly(book, work)
        return outcome
    _discard_quietly(book, work)
    _emit(on_event, ProcessingEvent(book.book_id, "completed", f"✓ {published.name}",
                                    str(published), kind="completed"))
    return BookOutcome(book_id=book.book_id, succeeded=True, published=published)


def _discard_quietly(book: BookPlan, work: Path) -> None:
    """Drop the Book's staging, then the work root **if it is now empty**."""
    try:
        discard_staging(book, work_root=work)
    except Exception:
        pass
    m4b_staging.prune_work_root(work)
