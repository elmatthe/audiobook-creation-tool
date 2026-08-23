"""The M4B Converter's own chapter vocabulary — pure values, no I/O, no Tk.

**Why this lives here and not in ``shared/``.** ``shared/ffmpeg_utils.py`` resolves
binaries and probes an *audio stream*; it has no chapter vocabulary and no other
consumer needs one. ``shared.metadata.read_chapter_titles`` answers a different
question — the ordered *titles* the M4B Metadata Editor renders — and is left
exactly as it is. Putting a chapter model into either would create a shared
abstraction with one caller, so the model is Converter-local until a second tool
genuinely needs it (v0.6.2 Plan 5 §11.1).

**What this module is.** The probe result types, and the structural verdict on
them. Nothing here runs ffprobe, opens a file, imports Tk or reaches the network,
which is what lets the whole chapter contract be tested without media. Reading a
real file is a later phase's job; this module fixes the shape of the answer and
decides whether that answer is usable.

The two halves are kept apart deliberately. The types record what the source
*said*; :func:`validate_chapters` decides whether what it said can be used.
Making a malformed map impossible to construct would leave nowhere to represent
a real, broken file, and the tool has to describe one truthfully in order to
refuse it.

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
