"""Reading one source, once, on a worker thread — the act of asking.

``m4b_chapters`` fixed the *shape* of the answer and deliberately runs nothing:
it is stdlib-only and its purity is guarded. This module is the other half — the
one ffprobe call per source that produces that answer, plus the two other facts
preflight needs from the same read: the source's compatible metadata and its
embedded cover.

**Why one call rather than three.** The Converter already had
``ffmpeg_utils.probe_audio_stream`` for the decoder decision, and chapters,
format tags and stream dispositions each need their own ``-show_*``. Asking
three times per book means three process spawns on a queue that may hold
hundreds, and it means three chances for the answers to disagree about the same
file. One ``-print_format json`` read returns format, streams and chapters
together, and every fact below is derived from that single snapshot.

**Why the xHE-AAC decision is not re-derived here.** ``ffmpeg_utils`` already owns
which decoder an audio stream needs, and that logic is shared with the rest of
the application. This builds the small ``info`` mapping that helper expects out
of the JSON it already has and asks it — so there is still exactly one place in
the repository that knows what xHE-AAC requires.

**What this module refuses to do.** It never repairs. A failed process, an
unparseable payload, a missing duration and a missing audio stream are four
different answers and stay four different answers; none of them becomes "this
book has no chapters". It also never *decides* anything: whether a probe is
usable is ``validate_chapters``' job, and what to do about an ambiguous cover is
the plan layer's.

Tk-free and widget-free. It runs a subprocess, so it belongs on a worker thread;
:mod:`m4b_plan` consumes what it returns and touches no process at all.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from shared import ffmpeg_utils
from shared import subprocess_utils as sp

from .m4b_chapters import ChapterProbe, ProbeStatus, SourceChapter
from .m4b_metadata import (
    ArtworkSelectionError,
    AttachedPicture,
    SourceTags,
    select_attached_picture,
)

#: The one ffprobe question. ``-show_chapters`` is what the legacy audio-stream
#: probe never asked for, and the reason this module exists.
_ARGS = (
    "-v", "error",
    "-print_format", "json",
    "-show_format",
    "-show_streams",
    "-show_chapters",
)

#: Source metadata keys ffprobe may use for each approved field. A container is
#: free to spell these several ways, and the first non-blank match wins.
_TAG_KEYS: dict[str, tuple[str, ...]] = {
    "title": ("title",),
    "artist": ("artist", "author", "album_artist"),
    "album_artist": ("album_artist", "albumartist", "artist"),
    "album": ("album",),
}


@dataclass(frozen=True, slots=True)
class ArtworkProblem:
    """Why a cover could not be chosen, carried as data rather than as a raise.

    A live exception is not something a frozen plan may hold, and it is not
    something that should cross a thread boundary. The two strings
    :class:`~mp3_tools.m4b_metadata.ArtworkSelectionError` already writes -- one
    for a person, one for the Details pane -- are copied out here instead.
    """

    message: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class SourceReport:
    """Everything one preflight read of one source produced.

    Immutable, and free of anything live: no process, no handle, no stream
    mapping the caller could mutate. This is what crosses from the worker into
    the plan.
    """

    probe: ChapterProbe
    tags: SourceTags = field(default_factory=SourceTags)
    picture: AttachedPicture | None = None
    artwork: ArtworkProblem | None = None
    decoder_args: tuple[str, ...] = ()
    codec_name: str = ""
    #: True when the source is xHE-AAC and this build has no decoder for it. The
    #: existing conversion warning is raised from this rather than by asking
    #: ffmpeg_utils a second time during execution.
    undecodable_xhe: bool = False

    @property
    def ok(self) -> bool:
        return self.probe.ok


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _track(value: Any) -> int | None:
    """A bare track number. ``3/9`` contributes ``3``; the total is discarded."""
    text = _text(value)
    if not text:
        return None
    head = text.split("/", 1)[0].strip()
    try:
        number = int(head)
    except ValueError:
        return None
    return number if number > 0 else None


def _tags_from(format_block: dict) -> SourceTags:
    """The approved subset of the source's own metadata, and nothing else.

    Keys are matched case-insensitively because containers disagree about case,
    and an atom outside :data:`~mp3_tools.m4b_metadata.BOOK_FIELDS` is simply not
    representable here -- which is what stops an unknown freeform atom reaching
    an output by accident.
    """
    raw = format_block.get("tags") or {}
    lowered = {str(key).lower(): value for key, value in raw.items()}
    chosen: dict[str, str] = {}
    for name, candidates in _TAG_KEYS.items():
        for key in candidates:
            value = _text(lowered.get(key))
            if value:
                chosen[name] = value
                break
    return SourceTags(track=_track(lowered.get("track")), **chosen)


def _chapters_from(blocks: list) -> tuple[SourceChapter, ...]:
    """Every chapter the source declared, in the order it declared them.

    Nothing is sorted, deduplicated, clamped or dropped: a malformed map has to
    survive intact this far so ``validate_chapters`` can refuse the real thing
    rather than a tidied-up version of it. A chapter whose start cannot be read
    at all is recorded as NaN, which the validator rejects explicitly.
    """
    found: list[SourceChapter] = []
    for position, block in enumerate(blocks):
        start = _number(block.get("start_time"))
        index = block.get("id")
        try:
            index = int(index)
        except (TypeError, ValueError):
            index = position
        title = _text((block.get("tags") or {}).get("title"))
        found.append(SourceChapter(
            index=index,
            start=float("nan") if start is None else start,
            title=title,
        ))
    return tuple(found)


def _audio_stream(streams: list) -> dict | None:
    for stream in streams:
        if stream.get("codec_type") == "audio":
            return stream
    return None


def _failed(detail: str) -> SourceReport:
    return SourceReport(
        probe=ChapterProbe(status=ProbeStatus.PROBE_FAILED, duration=None, detail=detail))


def probe_source(path, *, runner: Callable[[list[str]], str] | None = None) -> SourceReport:
    """Read one source and report what it actually contains.

    *runner* is the seam the tests drive: it receives the finished argument list
    and returns ffprobe's stdout. Production passes nothing and the call goes
    through ``shared.subprocess_utils`` so no console window flashes on Windows.

    Never raises. Every failure route -- the process, the payload, the duration,
    the audio stream -- produces its own :class:`~mp3_tools.m4b_chapters.
    ProbeStatus`, because a caller that cannot tell them apart cannot report
    truthfully on what went wrong.
    """
    argv = [ffmpeg_utils.ffprobe_cmd(), *_ARGS, str(path)]
    try:
        raw = runner(argv) if runner is not None else sp.check_output(argv, text=True)
    except Exception as exc:
        return _failed(f"{type(exc).__name__}: {exc}")

    try:
        payload = json.loads(raw or "")
    except Exception as exc:
        return _failed(f"ffprobe output could not be parsed: {type(exc).__name__}: {exc}")
    if not isinstance(payload, dict):
        return _failed("ffprobe returned no object")

    streams = payload.get("streams") or []
    format_block = payload.get("format") or {}
    if not isinstance(streams, list) or not isinstance(format_block, dict):
        return _failed("ffprobe returned an unexpected shape")

    audio = _audio_stream(streams)
    if audio is None:
        return SourceReport(
            probe=ChapterProbe(
                status=ProbeStatus.NO_AUDIO, duration=None,
                detail="no audio stream was found"))

    # Format duration first: it describes the container, which is what a chapter
    # timeline is measured against. The audio stream's own duration is the
    # fallback for a container that does not report one.
    duration = _number(format_block.get("duration"))
    if duration is None:
        duration = _number(audio.get("duration"))

    # The decoder question is asked of the shared helper, in the shape it
    # already understands, so xHE-AAC is decided in exactly one place.
    info = {
        "codec_name": _text(audio.get("codec_name")) or None,
        "profile": _text(audio.get("profile")) or None,
        "sample_rate": None,
        "channels": None,
        "channel_layout": None,
        "duration": duration,
    }
    decoder_args = tuple(ffmpeg_utils.input_decoder_args(info))
    undecodable = bool(
        not decoder_args and ffmpeg_utils.needs_special_aac_decoder(info))

    picture: AttachedPicture | None = None
    artwork: ArtworkProblem | None = None
    try:
        picture = select_attached_picture(streams)
    except ArtworkSelectionError as exc:
        artwork = ArtworkProblem(exc.message, exc.detail)

    if duration is None:
        status = ProbeStatus.NO_DURATION
        detail = "no usable duration was reported"
    else:
        status = ProbeStatus.OK
        detail = ""

    return SourceReport(
        probe=ChapterProbe(
            status=status,
            duration=duration,
            chapters=_chapters_from(payload.get("chapters") or []),
            detail=detail,
        ),
        tags=_tags_from(format_block),
        picture=picture,
        artwork=artwork,
        decoder_args=decoder_args,
        codec_name=_text(audio.get("codec_name")),
        undecodable_xhe=undecodable,
    )


def probe_sources(paths, *, runner=None, checkpoint=None):
    """Probe each source in order, yielding ``(path, SourceReport)``.

    *checkpoint* is called **between** sources and may raise to abandon the run.
    It is deliberately not called during a probe: an ffprobe process is
    indivisible at this phase, exactly as an ffmpeg encode is, and pretending
    otherwise is the one thing the run controls must never do.
    """
    for entry in paths:
        if checkpoint is not None:
            checkpoint()
        yield Path(entry), probe_source(entry, runner=runner)
