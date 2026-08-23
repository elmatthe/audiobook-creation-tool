"""The M4B Converter's own chapter vocabulary — pure values, no I/O, no Tk.

**Why this lives here and not in ``shared/``.** ``shared/ffmpeg_utils.py`` resolves
binaries and probes an *audio stream*; it has no chapter vocabulary and no other
consumer needs one. ``shared.metadata.read_chapter_titles`` answers a different
question — the ordered *titles* the M4B Metadata Editor renders — and is left
exactly as it is. Putting a chapter model into either would create a shared
abstraction with one caller, so the model is Converter-local until a second tool
genuinely needs it (v0.6.2 Plan 5 §11.1).

**What this module is.** The probe result types, the structural verdict on them,
and the complete-timeline partition computed from a verdict that passed. Nothing
here runs ffprobe, opens a file, imports Tk or reaches the network, which is what
lets the whole chapter contract be tested without media. Reading a real file is a
later phase's job; this module fixes the shape of the answer, decides whether
that answer is usable, and turns a usable one into spans.

The three layers are kept apart deliberately. The types record what the source
*said*; :func:`validate_chapters` decides whether what it said can be used; and
:func:`plan_timeline` partitions only what passed. Making a malformed map
impossible to construct would leave nowhere to represent a real, broken file, and
the tool has to describe one truthfully in order to refuse it.

**The one distinction this module exists to make.** A source that probes cleanly
and simply has no chapters is a *success* — :data:`ProbeStatus.OK` with an empty
``chapters`` tuple — and Decision 18A's chapterless fallback is built on it. An
ffprobe that failed, or whose output could not be parsed, is
:data:`ProbeStatus.PROBE_FAILED`. Collapsing the two into "no chapters" would let
an operational failure quietly become a one-file conversion of a book the tool
never actually read, so the statuses are kept apart at the type level rather than
by a convention callers must remember.

**What is deliberately not done anywhere here.** Nothing is ever repaired. A
negative start, a duplicate start, a non-monotonic sequence or a start beyond the
duration are all representable by the types and are *refused* by the validator —
never sorted, clamped, dropped, deduplicated or renamed into something that would
pass. A materially contradictory chapter structure stays a failure rather than
being silently rewritten into a different semantic book (§11.2).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class ProbeStatus(Enum):
    """How a chapter probe ended.

    Every member is a distinct operational outcome, never a description of the
    chapters themselves — the absence of chapters is :data:`OK`, not a failure.
    """

    #: The probe ran and its output was understood. ``chapters`` may be empty.
    OK = "ok"
    #: ffprobe failed to run, returned an error, or emitted output that could
    #: not be parsed. Never conflated with a legitimately chapterless source.
    PROBE_FAILED = "probe_failed"
    #: The probe ran but yielded no usable source duration.
    NO_DURATION = "no_duration"
    #: The source carries no usable audio stream.
    NO_AUDIO = "no_audio"


@dataclass(frozen=True, slots=True)
class SourceChapter:
    """One chapter exactly as the source declared it.

    ``index`` is the chapter's own position in the source, ``start`` its start
    time in seconds, and ``title`` whatever the source supplied — including an
    empty string, which is preserved rather than replaced. Naming a chapter that
    has no title is a filename concern and belongs to the naming phase.

    **There is no end time on purpose.** The complete-timeline plan is a partition
    over chapter *starts* and the source duration (§11.3), so an end time would be
    an unused second source of truth that could disagree with the starts.
    """

    index: int
    start: float
    title: str


@dataclass(frozen=True, slots=True)
class ChapterProbe:
    """The complete, immutable answer to "what chapters does this source have?".

    ``duration`` is the source duration in seconds when one is known and ``None``
    when it is not, which is the state :data:`ProbeStatus.NO_DURATION` describes.
    ``detail`` carries the technical remainder for a log or a failure report and
    is empty when there is nothing to say.
    """

    status: ProbeStatus
    duration: float | None
    chapters: tuple[SourceChapter, ...] = ()
    detail: str = ""

    def __post_init__(self) -> None:
        # Only the container is normalised, never its contents: a caller that
        # builds the list first still gets the immutable tuple this type
        # promises, while every chapter value it holds is left exactly as the
        # source declared it for Phase 2 to judge.
        if not isinstance(self.chapters, tuple):
            object.__setattr__(self, "chapters", tuple(self.chapters))

    @property
    def ok(self) -> bool:
        """True only when the probe itself succeeded.

        Deliberately not "has chapters": a chapterless source probed correctly and
        is usable, and the fallback that converts it whole depends on being able to
        tell that apart from a probe that never read the file at all.
        """
        return self.status is ProbeStatus.OK


# --------------------------------------------------------------------------- #
# Structural validation (§11.2)
#
# The verdict layer, kept separate from the model above on purpose. Phase 1's
# types record what the source *said*; this decides whether what it said can be
# used. Collapsing the two — making a malformed map impossible to construct —
# would leave nowhere to represent a real, broken file, and the tool has to be
# able to describe one truthfully in order to refuse it.
#
# Validation reads chapter **starts** and the source **duration**, and nothing
# else. Chapter end times are never consulted, so every end-time anomaly is
# structurally irrelevant and there is no "repair" to consider.
#
# Nothing here sorts, clamps, drops, deduplicates, merges or renames. A
# materially contradictory chapter structure stays a failure rather than being
# quietly rewritten into a different book.
# --------------------------------------------------------------------------- #


class ChapterUsability(Enum):
    """The three outcomes a probe can have once it has been judged."""

    #: ``OK``, a usable duration, and at least one structurally valid start.
    CHAPTERED = "chaptered"
    #: ``OK``, a usable duration, and no chapters at all — Decision 18A's
    #: legitimate chapterless source. A success, never corruption.
    CHAPTERLESS = "chapterless"
    #: Anything else. The item fails; nothing is written.
    UNUSABLE = "unusable"


class InvalidReason(Enum):
    """Why a probe was judged unusable. One member per distinct defect.

    Kept finer-grained than the pass/fail answer so a failure report can say what
    was actually wrong with the file rather than only that something was.
    """

    #: The probe never succeeded — ffprobe failed or its output was unparseable.
    PROBE_FAILED = "probe_failed"
    #: No usable source duration. Also covers an otherwise-``OK`` probe whose
    #: duration cannot describe a real ``[0, D]`` span, which is the same defect
    #: reached by a different route rather than a new product rule.
    NO_DURATION = "no_duration"
    #: The source carries no usable audio stream.
    NO_AUDIO = "no_audio"
    #: A start that is NaN or infinite. Caught explicitly because NaN compares
    #: false against everything, so it would otherwise slip past every range and
    #: ordering test below.
    START_NOT_FINITE = "start_not_finite"
    #: A start before the beginning of the source.
    START_BEFORE_ZERO = "start_before_zero"
    #: A start at or past the end of the source. Equality fails too: a chapter
    #: beginning exactly at ``D`` has no audio after it.
    START_AT_OR_BEYOND_DURATION = "start_at_or_beyond_duration"
    #: Two chapters beginning at the same instant, which would later ask for a
    #: zero-length output.
    DUPLICATE_START = "duplicate_start"
    #: A chapter beginning before the one it follows.
    STARTS_OUT_OF_ORDER = "starts_out_of_order"


_STATUS_REASONS = {
    ProbeStatus.PROBE_FAILED: InvalidReason.PROBE_FAILED,
    ProbeStatus.NO_DURATION: InvalidReason.NO_DURATION,
    ProbeStatus.NO_AUDIO: InvalidReason.NO_AUDIO,
}

_STATUS_MESSAGES = {
    InvalidReason.PROBE_FAILED: "This file could not be read, so it was not converted.",
    InvalidReason.NO_DURATION: "This file does not report a usable length, so it was not converted.",
    InvalidReason.NO_AUDIO: "This file contains no audio, so it was not converted.",
}

#: Shown for every malformed-chapter-map rejection. One sentence, no numbers: the
#: specifics belong in ``detail``, which the Summary structurally cannot read.
_MALFORMED_MESSAGE = (
    "This file's chapter list is not usable, so it was not converted. "
    "Converting it as a whole book instead will still work."
)


@dataclass(frozen=True, slots=True)
class ChapterValidation:
    """The verdict on one :class:`ChapterProbe`. Immutable, and a value only.

    It deliberately does **not** carry the chapters back. It is an answer about a
    probe, not a transformed copy of one, so there is no second, possibly
    divergent copy of the chapter list for a later phase to read by mistake.

    ``message`` is written for a person and is safe to show; ``detail`` keeps the
    technical remainder for a log or failure record, matching the split the rest
    of the project already uses.
    """

    usability: ChapterUsability
    reason: InvalidReason | None = None
    message: str = ""
    detail: str = ""

    @property
    def usable(self) -> bool:
        """True when the source can be converted at all — chaptered or not."""
        return self.usability is not ChapterUsability.UNUSABLE

    @property
    def chaptered(self) -> bool:
        return self.usability is ChapterUsability.CHAPTERED

    @property
    def chapterless(self) -> bool:
        return self.usability is ChapterUsability.CHAPTERLESS


def _usable_duration(duration: float | None) -> bool:
    """Whether *duration* can describe a real ``[0, D]`` source span.

    ``None`` is unusable, and so are NaN, the infinities and anything at or below
    zero: none of them bounds a timeline, and accepting one would hand a later
    phase a span it cannot honour.
    """
    if duration is None:
        return False
    return math.isfinite(duration) and duration > 0.0


def _invalid(reason: InvalidReason, detail: str) -> ChapterValidation:
    message = _STATUS_MESSAGES.get(reason, _MALFORMED_MESSAGE)
    return ChapterValidation(ChapterUsability.UNUSABLE, reason, message, detail)


def validate_chapters(probe: ChapterProbe) -> ChapterValidation:
    """Judge *probe* structurally. Pure: no I/O, no ffprobe, no clock, no Tk.

    Deterministic from its input, and the input is left exactly as it was — this
    reads the probe and returns a verdict, and never builds a corrected one.

    The ordering rule is a single exact comparison: starts must be **strictly
    increasing**. That one test covers both defects §11.2 names — equal starts
    are duplicates, decreasing starts are out of order — and the two are reported
    separately only so a failure can say which it was. **No tolerance is used.**
    ffprobe emits millisecond-quantised starts, so two genuinely distinct
    chapters are never within rounding distance of one another, and inventing an
    epsilon here would create exactly the kind of threshold that could later be
    mistaken for permission to move a boundary.
    """
    if probe.status is not ProbeStatus.OK:
        reason = _STATUS_REASONS[probe.status]
        return _invalid(reason, f"probe status {probe.status.value}"
                                + (f": {probe.detail}" if probe.detail else ""))

    duration = probe.duration
    if not _usable_duration(duration):
        # An OK probe whose duration cannot bound a timeline is the same defect
        # NO_DURATION already names, reached by a different route.
        return _invalid(InvalidReason.NO_DURATION,
                        f"probe reported status ok with unusable duration {duration!r}")

    if not probe.chapters:
        return ChapterValidation(ChapterUsability.CHAPTERLESS)

    previous: SourceChapter | None = None
    for chapter in probe.chapters:
        start = chapter.start
        if not math.isfinite(start):
            return _invalid(
                InvalidReason.START_NOT_FINITE,
                f"chapter index {chapter.index} starts at {start!r}")
        if start < 0.0:
            return _invalid(
                InvalidReason.START_BEFORE_ZERO,
                f"chapter index {chapter.index} starts at {start}, before zero")
        if start >= duration:
            return _invalid(
                InvalidReason.START_AT_OR_BEYOND_DURATION,
                f"chapter index {chapter.index} starts at {start}, "
                f"at or beyond the source duration {duration}")
        if previous is not None and start <= previous.start:
            reason = (InvalidReason.DUPLICATE_START if start == previous.start
                      else InvalidReason.STARTS_OUT_OF_ORDER)
            return _invalid(
                reason,
                f"chapter index {chapter.index} starts at {start}, "
                f"which does not follow chapter index {previous.index} "
                f"at {previous.start}")
        previous = chapter

    return ChapterValidation(ChapterUsability.CHAPTERED)


# --------------------------------------------------------------------------- #
# Complete-timeline partition (Decision 46A, §11.3)
#
# The planner turns a validated chaptered source into spans that tile the whole
# source, from exactly 0.0 to exactly the reported duration, with no gap and no
# overlap. Decision 46A is absolute: no positive source duration may disappear.
#
# **The partition is over chapter starts, not chapter regions.** For N chapters
# with starts s1..sN and duration D:
#
#     bounds   = [0.0, s2, s3, ..., sN, D]
#     segment i = [bounds[i], bounds[i + 1])
#
# The first chapter's own s1 is deliberately **not** a boundary. That single
# choice is what makes the whole thing lossless without a special case:
#
#   * pre-roll before chapter 1 falls inside chapter 1's span, so no synthetic
#     "Opening" output is invented for audio the source never named;
#   * unchaptered time between chapters falls into the preceding span, because
#     the next boundary is the next chapter's start and nothing else;
#   * trailing audio falls into the last span, whose end is D itself.
#
# Chapter end times are never consulted — they are not even carried by
# :class:`SourceChapter` — so no end-time anomaly can move a boundary.
#
# **No arithmetic is performed on any boundary.** Every value in ``bounds`` is
# either the literal ``0.0``, a chapter start copied verbatim, or the duration
# copied verbatim. Nothing is added, subtracted, rounded or nudged, so floating
# point cannot drift a boundary and there is no epsilon anywhere in this layer to
# be mistaken later for permission to trim the beginning or end of a book.
# --------------------------------------------------------------------------- #


class TimelinePlanError(RuntimeError):
    """A partition was asked for on a source that cannot be split.

    Carries the :class:`ChapterValidation` that refused it, so a caller that
    reached here by mistake still has the specific reason rather than a bare
    failure. Raised rather than returned because a validated caller cannot
    encounter it: the chaptered / chapterless / unusable decision is made once,
    by :func:`validate_chapters`, before a partition is ever requested.
    """

    def __init__(self, validation: ChapterValidation):
        self.validation = validation
        detail = validation.detail or validation.usability.value
        super().__init__(f"cannot partition this source: {detail}")


@dataclass(frozen=True, slots=True)
class ChapterSpan:
    """One span of the source timeline, and the chapter it is named for.

    Pure geometry and identity — deliberately **not** §9's ``SegmentPlan``, which
    additionally carries a destination path and the final track policy. Those are
    output decisions and belong to the phase that assembles the conversion plan;
    keeping them out of here means there is exactly one timeline representation
    and nothing mutable to fall out of step with it.

    ``order`` is the span's 1-based position in the plan, which is the structural
    order later phases number by. ``source_index`` is what the source itself
    called the chapter, kept separate because the two are not the same fact and a
    source is free to index from anywhere. ``title`` is raw: not flattened, not
    sanitised, not defaulted. Turning a title into a filename is the naming
    seam's job.
    """

    order: int
    source_index: int
    start: float
    end: float
    title: str

    @property
    def duration(self) -> float:
        """Length of this span. Derived, never stored, so it cannot disagree."""
        return self.end - self.start


def plan_timeline(probe: ChapterProbe) -> tuple[ChapterSpan, ...]:
    """Partition a chaptered source into spans tiling ``[0.0, duration]``.

    Pure and deterministic: no I/O, no ffprobe, no clock, no Tk. The input probe
    is read and never modified.

    **Validation is not repeated here.** This calls :func:`validate_chapters`,
    which stays the single authority on whether a probe is usable, and refuses
    anything that is not :data:`ChapterUsability.CHAPTERED` — including a
    legitimately chapterless source, which has no chapter partition to compute
    and whose one-file fallback belongs to the run-plan layer, not to this
    function. Re-validating rather than trusting the caller means a malformed
    probe cannot produce spans by any route.

    Raises :class:`TimelinePlanError` when the source cannot be partitioned.
    """
    validation = validate_chapters(probe)
    if validation.usability is not ChapterUsability.CHAPTERED:
        raise TimelinePlanError(validation)

    chapters = probe.chapters
    # Every bound is a verbatim value: the literal start of the source, each
    # chapter start after the first, and the duration itself. Note the deliberate
    # omission of chapters[0].start — pre-roll belongs to chapter 1.
    bounds: list[float] = [0.0]
    bounds.extend(chapter.start for chapter in chapters[1:])
    bounds.append(probe.duration)  # type: ignore[arg-type]  # validated non-None

    return tuple(
        ChapterSpan(
            order=position + 1,
            source_index=chapter.index,
            start=bounds[position],
            end=bounds[position + 1],
            title=chapter.title,
        )
        for position, chapter in enumerate(chapters)
    )
