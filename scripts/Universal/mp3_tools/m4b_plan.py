"""One run, decided completely, before anything is written.

Every earlier phase produced one piece of this: the probe model and its verdict,
the complete-timeline partition, the naming seam, the metadata/chapter/artwork
rules, and the provenance-aware destination planner. This module is where they
meet and become a single immutable answer to "what is this run going to do?".

**Why immutability is the whole point.** A run reads the imported queue and the
widgets once. Everything after that -- execution, reporting, and eventually a
retry -- reads *this* object. So a book cannot move because the user reordered
the list mid-run, an output cannot land somewhere new because a preference
changed, and a retry cannot quietly convert something different from what
failed. Nothing here is a live handle: no widget, no variable, no thread, no
queue, no logger, no controller, no process. It is values.

**Why probing is not done here.** ``m4b_probe`` runs ffprobe and returns
immutable reports; this module consumes them. That keeps the whole planning
contract testable without media, and it keeps the one place that spawns
processes clearly separated from the one place that decides what they mean.

**The three answers a source can get**, and they stay three:

* **chaptered** -- ``OK``, a usable duration, structurally valid starts. In split
  mode it becomes one output per chapter, tiling ``[0, D]``.
* **chapterless** -- ``OK``, a usable duration, genuinely no chapters. Decision
  18A: a success, one output covering the whole book, in either mode.
* **unusable** -- anything else, including a malformed chapter map. It fails
  before a directory is reserved, and it never becomes "chapterless".

**One derivation this module had to make explicit.** The drop pins the
chapterless split *filename* -- the whole-book name, no order prefix (§13, §14)
-- but not its tags. The answer follows from §16 rather than being invented: the
fragment rules exist because a split output "must never describe the unsplit
book", and a chapterless split output *is* the unsplit book -- one file covering
``[0, D]``. So it is not a fragment, and :attr:`ItemPlan.fragment` says so. That
one flag, rather than the run's mode, is what later phases ask when they decide
whether the source chapter map survives and whether a structural track is
written.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType

from shared.importing import ImportRoot
from shared.output_paths import assert_not_input

from . import m4b_destinations
from .m4b_chapters import ChapterUsability, plan_timeline, validate_chapters
from .m4b_metadata import BOOK_FIELDS, AttachedPicture, MetadataMode, SourceTags
from .m4b_naming import segment_filename
from .m4b_probe import SourceReport

#: The extension every Converter output carries.
_EXTENSION = ".mp3"

#: The reason recorded when a source carries several embedded covers. Not a
#: :class:`~mp3_tools.m4b_chapters.InvalidReason`: nothing is wrong with the
#: *chapter* map, so borrowing that vocabulary would misdescribe the defect.
ARTWORK_AMBIGUOUS = "artwork_ambiguous"
#: The source is xHE-AAC, ffmpeg cannot decode it completely, and this
#: machine has no decoder that can. v0.6.2 Plan 5 Phase 15: refusing here is
#: the whole point -- ffmpeg would exit 0 having silently dropped 23.91% of
#: the audio, and the person would wait out a full encode to be told so.
UNDECODABLE_SOURCE = "undecodable_source"

#: The reason recorded when an occurrence never produced a report at all. A
#: defensive route: preflight probes every frozen occurrence, so reaching this
#: means the two fell out of step, which must be visible rather than silent.
NOT_PROBED = "not_probed"


class ConversionMode(Enum):
    """The batch-wide output shape, frozen into a run (Decision 44A)."""

    WHOLE = "whole"
    SPLIT = "split"


@dataclass(frozen=True, slots=True)
class PlanOptions:
    """Every run-wide choice, read from the widgets once and never again.

    Built on the main thread and handed to the worker as a value. ``quality``,
    ``auto_number`` and ``start_number`` are carried even though this phase does
    not allocate a success number -- freezing the configuration is Decision 37A,
    and the allocator that consumes it arrives later.
    """

    mode: ConversionMode = ConversionMode.WHOLE
    metadata_mode: MetadataMode = MetadataMode.PRESERVE
    replacement: Mapping[str, str] = field(default_factory=dict)
    auto_number: bool = True
    start_number: int = 1
    quality: int = 2

    def __post_init__(self) -> None:
        if not isinstance(self.mode, ConversionMode):
            raise TypeError("mode must be a ConversionMode")
        if not isinstance(self.metadata_mode, MetadataMode):
            raise TypeError("metadata_mode must be a MetadataMode")
        # A fresh copy behind a read-only view: the caller keeps no reference
        # that could still edit what the run believes it was given.
        object.__setattr__(self, "replacement", MappingProxyType({
            name: str(self.replacement.get(name, "") or "").strip()
            for name in BOOK_FIELDS
            if str(self.replacement.get(name, "") or "").strip()
        }))
        object.__setattr__(self, "auto_number", bool(self.auto_number))
        object.__setattr__(self, "start_number", int(self.start_number))
        object.__setattr__(self, "quality", int(self.quality))

    @property
    def split(self) -> bool:
        return self.mode is ConversionMode.SPLIT


@dataclass(frozen=True, slots=True)
class SegmentPlan:
    """One output file, decided: where it comes from, and where it goes.

    ``order`` is 1-based **within its own item** and restarts for every book.
    ``track`` is the structural split track (Decision 19A/47A) and is ``None``
    for anything that is not a fragment -- a whole book's optional sequential
    number is a different concept entirely, allocated only on success, and is
    deliberately absent here.
    """

    order: int
    start: float
    end: float
    title: str
    destination: Path
    track: int | None = None

    @property
    def duration(self) -> float:
        """Length of this output. Derived, so it cannot disagree with the span."""
        return self.end - self.start


@dataclass(frozen=True, slots=True)
class ItemPlan:
    """One usable occurrence and everything its outputs need.

    Carries provenance rather than only a path: two deliberate duplicates of one
    file are two occurrences, and every decision below is keyed on the identity,
    never on where the file happens to live.
    """

    occurrence_id: str
    source: Path
    source_root: ImportRoot
    relative_path: str | None
    duration: float
    chaptered: bool
    fragment: bool
    tags: SourceTags
    picture: AttachedPicture | None
    decoder_args: tuple[str, ...]
    undecodable_xhe: bool
    codec_hint: str
    segments: tuple[SegmentPlan, ...]
    #: Decode this one through Windows Media Foundation rather than ffmpeg.
    #: Decided once, at preflight, from the probe and the machine's actual
    #: capability -- never from a filename, never re-derived after Start, and
    #: never true for a source ffmpeg decodes correctly.
    windows_decode: bool = False
    #: The source's own chapter titles, in source order, frozen here at preflight
    #: from the same probe every other field came from. They exist because
    #: ``-map_metadata -1`` strips the titles off a chapter map that
    #: ``-map_chapters 0`` copied, so a whole-book output has to name them again
    #: explicitly -- and execution must not re-open the source to find out what
    #: they were. Empty for a split run, whose outputs drop the map entirely.
    chapter_titles: tuple[str, ...] = ()

    @property
    def total_segments(self) -> int:
        return len(self.segments)


@dataclass(frozen=True, slots=True)
class ItemFailure:
    """One occurrence that will not be converted, and why.

    Typed rather than a string, and it keeps the occurrence identity so a report
    can point at the row the user actually chose. ``message`` is written for a
    person; ``detail`` holds the technical remainder that only Details reads.
    """

    occurrence_id: str
    source: Path
    reason: str
    message: str
    detail: str = ""
    #: **Not** a Retry Failed candidate, and the default says so (Phase 13).
    #:
    #: A preflight-unusable occurrence never obtains an executable ``ItemPlan``,
    #: so it has no frozen ``SegmentPlan``, no frozen destination, and -- once
    #: Start-time planning is over -- no retained collision planner either.
    #: Re-running it in place would therefore mean re-probing it, rebuilding the
    #: plan, or planning a destination after Start, and the frozen-plan retry
    #: contract forbids all three. The failure stays typed, stays visible and
    #: stays non-fatal; a corrected source is submitted through a **new run**,
    #: which probes and plans it normally.
    retryable: bool = False


@dataclass(frozen=True, slots=True)
class ConversionPlan:
    """The whole run, frozen. The only thing execution and reporting may read.

    ``run_directory`` is ``None`` when nothing is usable, because no directory is
    reserved for a run that will write nothing -- an empty numbered folder is a
    side effect, and preflight failures must leave none.
    """

    snapshot_id: str
    mode: ConversionMode
    metadata_mode: MetadataMode
    replacement: Mapping[str, str]
    auto_number: bool
    start_number: int
    quality: int
    run_directory: Path | None
    items: tuple[ItemPlan, ...] = ()
    unusable: tuple[ItemFailure, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "replacement", MappingProxyType(dict(self.replacement)))

    @property
    def total_segments(self) -> int:
        """The authoritative progress denominator, published once after preflight.

        Counts only outputs that will actually be attempted. An unusable
        occurrence contributes nothing: it has no segment, and inventing one so
        the bar could tick would be counting work that is never done.
        """
        return sum(len(item.segments) for item in self.items)

    @property
    def split(self) -> bool:
        return self.mode is ConversionMode.SPLIT

    @property
    def has_work(self) -> bool:
        return bool(self.items)

    def item_for(self, occurrence_id: str) -> ItemPlan | None:
        for item in self.items:
            if item.occurrence_id == occurrence_id:
                return item
        return None


def _failure(entry, reason: str, message: str, detail: str = "") -> ItemFailure:
    """The one place a source is classified unusable -- and it is not retryable.

    Stated here rather than left to a default, because this is the classification
    point: every caller of this helper is refusing a source *before* a plan entry
    or a destination exists for it, and that is exactly the condition that makes
    an in-place retry impossible.
    """
    return ItemFailure(
        occurrence_id=entry.occurrence_id,
        source=Path(entry.path),
        reason=reason,
        message=message,
        detail=detail,
        retryable=False,
    )


def _spans(entry, report: SourceReport, chaptered: bool, split: bool):
    """The (order, start, end, title, filename, track) tuples for one item.

    Three shapes, and the third is the one worth reading twice:

    * whole book -- one output over ``[0, D]``, named for the source;
    * split and chaptered -- one output per chapter, tiling ``[0, D]``, named
      with its structural order prefix and carrying that order as ``track``;
    * split and chapterless -- one output over ``[0, D]``. Decision 18A makes
      this a success, §13 gives it the whole-book name, and it is **not** a
      fragment, so it carries no regenerated track. See the module docstring.
    """
    duration = float(report.probe.duration)  # validated usable before we get here
    stem = Path(entry.path).stem

    if split and chaptered:
        timeline = plan_timeline(report.probe)
        total = len(timeline)
        return [
            (span.order, span.start, span.end, span.title,
             segment_filename(span.order, total, span.title), span.order)
            for span in timeline
        ]
    return [(1, 0.0, duration, "", f"{stem}{_EXTENSION}", None)]


def assemble_plan(
    *,
    snapshot_id: str,
    entries: Sequence,
    reports: Mapping[str, SourceReport],
    options: PlanOptions,
    reserve,
    windows_decoder=None,
) -> ConversionPlan:
    """Turn one frozen queue plus its probe reports into one immutable plan.

    *entries* is the committed ``ImportedFile`` snapshot, in its own order;
    *reports* maps each occurrence id to what preflight actually read.

    *reserve* is called **once, and only if at least one occurrence is usable**,
    and must return ``(run_directory, DestinationPlanner)``. That is the approved
    lifecycle in one line: sources are validated first, the run directory appears
    second, destinations are planned third, and nothing is written until all
    three are done. A run whose every item is unusable reserves nothing at all,
    so a failed preflight leaves no empty numbered folder behind.

    *windows_decoder* answers "can this machine decode what ffmpeg cannot?".
    It is a seam so both answers are testable and so this module still runs no
    process of its own; production passes
    :func:`mp3_tools.m4b_winaudio.available`.

    Runs no process, reads no file, creates no directory and touches no widget.
    """
    if windows_decoder is None:
        from . import m4b_winaudio

        windows_decoder = m4b_winaudio.available
    entries = tuple(entries)
    usable: list[tuple] = []
    failures: list[ItemFailure] = []

    for entry in entries:
        report = reports.get(entry.occurrence_id)
        if report is None:
            failures.append(_failure(
                entry, NOT_PROBED,
                "This file was not examined, so it was not converted.",
                "no probe report was produced for this occurrence"))
            continue

        # One authority on usability, consulted once. A malformed chapter map is
        # refused here and never routed to the chapterless fallback.
        validation = validate_chapters(report.probe)
        if validation.usability is ChapterUsability.UNUSABLE:
            reason = validation.reason.value if validation.reason else "unusable"
            failures.append(_failure(
                entry, reason, validation.message, validation.detail))
            continue

        # Several embedded covers is not a chapter defect, so it gets its own
        # reason. It fails closed in every mode: choosing between them would be
        # an invented preference, and Phase 6 refused to invent one.
        if report.artwork is not None:
            failures.append(_failure(
                entry, ARTWORK_AMBIGUOUS,
                report.artwork.message, report.artwork.detail))
            continue

        # xHE-AAC that ffmpeg cannot decode completely. On Windows the
        # built-in Media Foundation decoder handles it; with no such capability
        # the honest answer is to refuse now, before a run directory is
        # reserved, rather than hand back a 76%-complete audiobook.
        route = False
        if report.undecodable_xhe:
            if not windows_decoder():
                failures.append(_failure(
                    entry, UNDECODABLE_SOURCE,
                    "This audiobook uses xHE-AAC audio that this computer "
                    "cannot decode completely. No output was created.",
                    "ffmpeg's decoder drops a large fraction of xHE-AAC "
                    "(MPEG-D USAC) frames, and no Media Foundation decoder is "
                    "available here; the source was left unchanged"))
                continue
            route = True

        usable.append((entry, report, validation.usability is ChapterUsability.CHAPTERED,
                       route))

    if not usable:
        return ConversionPlan(
            snapshot_id=snapshot_id,
            mode=options.mode,
            metadata_mode=options.metadata_mode,
            replacement=options.replacement,
            auto_number=options.auto_number,
            start_number=options.start_number,
            quality=options.quality,
            run_directory=None,
            items=(),
            unusable=tuple(failures),
        )

    shapes = {
        entry.occurrence_id: _spans(entry, report, chaptered, options.split)
        for entry, report, chaptered, _route in usable
    }

    run_directory, planner = reserve()
    planned = m4b_destinations.plan_outputs(
        [entry for entry, _report, _chaptered, _route in usable],
        {occurrence: tuple(shape[4] for shape in shapes[occurrence])
         for occurrence in shapes},
        run_root=Path(run_directory),
        planner=planner,
    )
    destinations = {item.occurrence_id: item.destinations for item in planned}

    items: list[ItemPlan] = []
    for entry, report, chaptered, route in usable:
        shape = shapes[entry.occurrence_id]
        paths = destinations[entry.occurrence_id]
        if len(paths) != len(shape):
            raise ValueError(
                f"{entry.occurrence_id} planned {len(paths)} destinations "
                f"for {len(shape)} outputs")
        items.append(ItemPlan(
            occurrence_id=entry.occurrence_id,
            source=Path(entry.path),
            source_root=entry.source_root,
            relative_path=entry.relative_path,
            duration=float(report.probe.duration),
            chaptered=chaptered,
            fragment=bool(options.split and chaptered),
            tags=report.tags,
            picture=report.picture,
            decoder_args=tuple(report.decoder_args),
            undecodable_xhe=bool(report.undecodable_xhe),
            codec_hint=str(report.codec_name),
            windows_decode=bool(route),
            # Frozen from the probe that is already in hand. A whole-book output
            # keeps the map and therefore needs these; a split run drops the map,
            # so they are deliberately not carried into one.
            chapter_titles=(() if (options.split and chaptered) else
                            tuple(chapter.title for chapter in report.probe.chapters)),
            segments=tuple(
                SegmentPlan(
                    order=order,
                    start=start,
                    end=end,
                    title=title,
                    destination=path,
                    track=track,
                )
                for (order, start, end, title, _name, track), path in zip(shape, paths)
            ),
        ))

    # Checked against **every** source in the run, not only the usable ones: an
    # unusable book is still a file on disk that must not be written over.
    sources = tuple(Path(entry.path) for entry in entries)
    for item in items:
        for segment in item.segments:
            assert_not_input(segment.destination, sources)

    return ConversionPlan(
        snapshot_id=snapshot_id,
        mode=options.mode,
        metadata_mode=options.metadata_mode,
        replacement=options.replacement,
        auto_number=options.auto_number,
        start_number=options.start_number,
        quality=options.quality,
        run_directory=Path(run_directory),
        items=tuple(items),
        unusable=tuple(failures),
    )
