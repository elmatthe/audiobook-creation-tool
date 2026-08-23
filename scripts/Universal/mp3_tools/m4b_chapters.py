"""The M4B Converter's own chapter vocabulary — pure values, no I/O, no Tk.

**Why this lives here and not in ``shared/``.** ``shared/ffmpeg_utils.py`` resolves
binaries and probes an *audio stream*; it has no chapter vocabulary and no other
consumer needs one. ``shared.metadata.read_chapter_titles`` answers a different
question — the ordered *titles* the M4B Metadata Editor renders — and is left
exactly as it is. Putting a chapter model into either would create a shared
abstraction with one caller, so the model is Converter-local until a second tool
genuinely needs it (v0.6.2 Plan 5 §11.1).

**What this module is.** Result types only. Nothing here runs ffprobe, opens a
file, imports Tk or reaches the network, which is what lets the whole chapter
contract be tested without media. Reading a real file is a later phase's job;
this phase fixes the shape of the answer.

**The one distinction this module exists to make.** A source that probes cleanly
and simply has no chapters is a *success* — :data:`ProbeStatus.OK` with an empty
``chapters`` tuple — and Decision 18A's chapterless fallback is built on it. An
ffprobe that failed, or whose output could not be parsed, is
:data:`ProbeStatus.PROBE_FAILED`. Collapsing the two into "no chapters" would let
an operational failure quietly become a one-file conversion of a book the tool
never actually read, so the statuses are kept apart at the type level rather than
by a convention callers must remember.

**What this module deliberately does not do.** It does not judge the chapters it
carries. A negative start, a duplicate start, a non-monotonic sequence or a start
beyond the duration are all representable here and are *not* rejected, sorted,
clamped or dropped. Structural validation is Phase 2's, and it is deliberately
separate so the model can faithfully represent a malformed source rather than
silently rewriting one into a different book (§11.2).
"""

from __future__ import annotations

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
