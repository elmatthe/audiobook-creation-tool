"""What metadata and artwork each conversion mode writes — decided, never executed.

Three batch-wide modes (Preserve / Replace / Strip) times two scopes (whole book /
split segment) give six cells, and this module is the single place each cell's
answer lives.

**Why Preserve is an explicit allowlist and not ``-map_metadata 0``.** That was
measured, not assumed. Blanket-copying a real audiobook's metadata into the MP3
put 23 format tags and 25 ID3 frames into the output, and among them were
statements that are simply false about the file that was produced:

* ``AUDIBLE_DRM_TYPE=Adrm`` — declaring DRM on a DRM-free MP3;
* ``major_brand=isom``, ``minor_version=512``, ``compatible_brands=…M4A M4B`` —
  **MP4 container brands stamped onto an MPEG audio file**;
* ``AUDIBLE_ACR`` / ``AUDIBLE_ASIN`` / ``AUDIBLE_LOCALE`` — identifiers for the
  Audible product, not for this file;
* ``creation_time`` — the M4B's encode date;
* replaygain values computed for the AAC stream, invalid once re-encoded;
* AAC ``Encoding Params``, meaningless in an MP3.

Twelve of those frames were ``TXXX:`` freeform junk. So Preserve carries the
fields the Converter's own vocabulary can vouch for and drops the rest.

**Fields that are true but still dropped.** The real fixtures also carry
narrator, publisher, series, subtitle, copyright, comment, genre, year, language
and description. Those are accurate about the book, and they are *still* dropped,
because §15 locks the Converter's encode-time vocabulary to what
``shared.metadata`` already supports. Widening it is a decision for a later plan,
not something this module may do quietly.

**The one tag nobody can remove.** ffmpeg stamps its own ``encoder`` / ``TSSE``
marker on everything it muxes. It appears even in Strip. It is the muxer
describing itself, not source metadata leaking, and it is left alone.

Pure: values in, values out. Nothing here probes a file, runs a process, touches
the filesystem or reads configuration. The source facts arrive already known.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

from shared.metadata import ffmpeg_metadata_args

from . import m4b_commands


class MetadataMode(Enum):
    """The batch-wide metadata mode, frozen into a run."""

    PRESERVE = "preserve"
    REPLACE = "replace"
    STRIP = "strip"


#: The only source fields the Converter is allowed to carry. Deliberately the
#: same names ``shared.metadata.ffmpeg_metadata_args`` understands, so there is
#: exactly one field-name-to-ffmpeg-key mapping in the repository.
BOOK_FIELDS: tuple[str, ...] = ("title", "artist", "album_artist", "album")

#: What a *fragment* may inherit from the book it came from. ``title`` is absent
#: on purpose: a split output is not the book, so it must never claim the book's
#: title. Its own title and track are regenerated instead (§16).
FRAGMENT_INHERITED: tuple[str, ...] = ("artist", "album_artist", "album")


@dataclass(frozen=True, slots=True)
class SourceTags:
    """The compatible subset of one source's metadata, already read.

    Only the approved vocabulary is representable here, which is the point: an
    atom this class cannot hold is an atom the Converter cannot accidentally
    write. ``track`` is a bare number — a source ``3/9`` contributes ``3`` and
    the total is discarded, because a total describes a set rather than this
    file.
    """

    title: str = ""
    artist: str = ""
    album_artist: str = ""
    album: str = ""
    track: int | None = None

    def as_dict(self) -> dict[str, object]:
        values: dict[str, object] = {name: getattr(self, name) for name in BOOK_FIELDS}
        if self.track is not None:
            values["track"] = self.track
        return values


@dataclass(frozen=True, slots=True)
class AttachedPicture:
    """One positively identified embedded cover.

    ``stream_index`` is the **absolute** ffprobe stream index, not a
    ``v:``-relative one. That matters: a source can carry ordinary video ahead of
    its cover, and ``-map 0:v:0`` would then select the wrong stream.
    """

    stream_index: int
    codec_name: str = ""


class ArtworkSelectionError(Exception):
    """A source carries more than one embedded cover, so the choice is ambiguous.

    Follows the repository's existing error shape: ``message`` is written for a
    person and ``detail`` keeps the technical remainder for a log or a later
    preflight Details pane.

    **Why this is not simply ``None``.** ``None`` means *this book has no cover*,
    which is an ordinary, valid state that Preserve and Replace handle by
    attaching nothing. Several covers is the opposite situation — artwork exists
    and something must be kept — and collapsing the two would silently discard a
    cover the user has. They are different facts and must stay different.

    **Why no cover is picked.** Preferring the lowest index, the first, the
    largest, or JPEG over PNG would all be inventions: §17 requires artwork to be
    positively identified, and none of the real fixtures inspected during Phase 6
    carried more than one attached picture, so there is no evidence to derive a
    rule from. Guessing here would quietly put the wrong picture on a book. The
    rule stays unwritten until it is decided as product, and until then this
    fails closed.
    """

    def __init__(self, candidates: Sequence[AttachedPicture]):
        #: Sorted for a stable diagnostic only. This ordering is never a
        #: preference — nothing selects from it.
        self.candidates: tuple[AttachedPicture, ...] = tuple(
            sorted(candidates, key=lambda picture: picture.stream_index)
        )
        self.message = (
            "This file contains more than one embedded cover, so there is no "
            "single correct one to keep."
        )
        self.detail = "attached-picture streams: " + ", ".join(
            f"#{picture.stream_index} {picture.codec_name or 'unknown'}"
            for picture in self.candidates
        )
        super().__init__(self.message)


def attached_pictures(streams: Sequence[Mapping]) -> tuple[AttachedPicture, ...]:
    """Every stream positively identified as an embedded cover, in stream order.

    Selection is by **disposition** — ``attached_pic`` must be truthy. Being a
    video stream is not enough, and neither is being the first one: an ordinary
    video track is not artwork, and mapping it would put a moving picture where a
    cover belongs.

    Reads the descriptors and copies out of them; the caller's stream mappings
    are never modified.
    """
    found: list[AttachedPicture] = []
    for stream in streams:
        if stream.get("codec_type") != "video":
            continue
        if not (stream.get("disposition") or {}).get("attached_pic"):
            continue
        found.append(
            AttachedPicture(int(stream["index"]), str(stream.get("codec_name") or ""))
        )
    return tuple(sorted(found, key=lambda picture: picture.stream_index))


def select_attached_picture(streams: Sequence[Mapping]) -> AttachedPicture | None:
    """The one cover among already-probed streams.

    Three outcomes, and they are deliberately distinct:

    * **no attached picture** → ``None``. A book without a cover is valid and
      must not fail; Preserve and Replace simply attach nothing.
    * **exactly one** → that :class:`AttachedPicture`, identified by its absolute
      ffprobe stream index.
    * **more than one** → :class:`ArtworkSelectionError`. See that class for why
      nothing is guessed.
    """
    found = attached_pictures(streams)
    if not found:
        return None
    if len(found) > 1:
        raise ArtworkSelectionError(found)
    return found[0]


def _clean_overrides(values: Mapping | None, allowed: Sequence[str]) -> dict[str, str]:
    """Non-blank user values, restricted to the approved names."""
    if not values:
        return {}
    out: dict[str, str] = {}
    for name in allowed:
        raw = values.get(name)
        text = "" if raw is None else str(raw).strip()
        if text:
            out[name] = text
    return out


def whole_book_tags(
    mode: MetadataMode,
    *,
    source: SourceTags | None = None,
    replacement: Mapping | None = None,
    track: int | None = None,
) -> dict[str, object]:
    """The tags one whole-book output carries.

    Preserve starts from the source's approved fields and lets a non-blank user
    value override its own field. Replace starts from nothing, so a field the
    user left blank stays absent rather than falling back to the source. Strip
    writes nothing at all.
    """
    if mode is MetadataMode.STRIP:
        return {}

    tags: dict[str, object] = {}
    if mode is MetadataMode.PRESERVE and source is not None:
        tags.update(source.as_dict())
    tags.update(_clean_overrides(replacement, BOOK_FIELDS))
    if track is not None:
        tags["track"] = track
    return {name: value for name, value in tags.items() if value not in ("", None)}


def segment_tags(
    mode: MetadataMode,
    *,
    title: str,
    order: int,
    source: SourceTags | None = None,
    replacement: Mapping | None = None,
) -> dict[str, object]:
    """The tags one split output carries.

    A fragment inherits only book-level identity — artist, album artist, album —
    and regenerates the two fields that describe *it*: its own title and its
    structural position. Those two always win, which is Decision 47A's narrow
    exception: a Replace run may supply a whole-book title, and it must not
    become the segment's title.

    Strip regenerates nothing, deliberately unlike the other two modes.
    """
    if mode is MetadataMode.STRIP:
        return {}

    tags: dict[str, object] = {}
    if mode is MetadataMode.PRESERVE and source is not None:
        for name in FRAGMENT_INHERITED:
            tags[name] = getattr(source, name)
    tags.update(_clean_overrides(replacement, FRAGMENT_INHERITED))
    tags["title"] = title
    tags["track"] = order
    return {name: value for name, value in tags.items() if value not in ("", None)}


def retains_chapters(mode: MetadataMode, *, split: bool) -> bool:
    """Whether the source chapter map survives (Decision 6A).

    A whole-book output *is* the whole book and its timeline is unchanged, so the
    map still describes it accurately — under Replace as much as under Preserve,
    because replacing text does not invalidate navigation. A split output is a
    fragment and the book's map would describe something it is not.
    """
    if split:
        return False
    return mode is not MetadataMode.STRIP


def wants_artwork(mode: MetadataMode) -> bool:
    """Preserve and Replace keep the cover; Strip removes it (Decision 2)."""
    return mode is not MetadataMode.STRIP


def metadata_args(tags: Mapping, *, keep_chapters: bool,
                  chapter_titles: Sequence[str] = ()) -> list[str]:
    """Output-side arguments carrying a decided tag set.

    ``-map_metadata -1`` is unconditional and is what makes every cell an
    allowlist: nothing reaches the output unless it was named above. The
    ``-metadata`` pairs come from ``shared.metadata.ffmpeg_metadata_args`` so the
    friendly-name-to-ffmpeg-key mapping exists in exactly one place.

    **Chapter titles have to be named too, and that is not obvious.**
    ``-map_metadata -1`` silences *chapter* metadata as well as global metadata,
    so ``-map_chapters 0`` on its own copies the boundaries and drops every
    title: v0.6.2 Plan 5 Phase 16 measured a real 7.3-hour Whole+Preserve output
    that kept all 17 timing spans to the millisecond and carried **zero** TIT2
    subframes, so a reader showed seventeen anonymous points. Removing the
    ``-map_metadata -1`` firewall does restore the titles, and was rejected: the
    same measurement showed it also leaking ``comment`` and ``genre`` past the
    §16 allowlist. So each retained title is written back explicitly, per output
    chapter, which keeps the firewall absolute and still lands the text.

    The titles arrive already frozen in the plan -- this asks the source nothing
    and re-probes nothing -- and an untitled source chapter is passed over rather
    than being given an invented name. ``-metadata:c:N`` names the *output*
    chapter, so it is independent of which input supplied the map; the Windows
    xHE route can strip ``-map_chapters`` from these args and still keep every
    title.
    """
    args = ["-map_metadata", "-1", "-map_chapters", "0" if keep_chapters else "-1"]
    args += ffmpeg_metadata_args(dict(tags))
    if keep_chapters:
        for index, title in enumerate(chapter_titles):
            # Built through the same shared mapping as every other tag and then
            # re-aimed at one chapter, rather than spelling ``title=`` again
            # here: this module deliberately holds no second friendly-name to
            # ffmpeg-key table, and ``test_the_shared_mapping_is_consumed_not_
            # reimplemented`` fails if one appears.
            pair = ffmpeg_metadata_args({"title": title})
            if pair:
                args += [f"-metadata:c:{index}", pair[1]]
    return args


@dataclass(frozen=True, slots=True)
class ConversionCommands:
    """The ffmpeg invocations one output needs, in order.

    Split Preserve/Replace on a source that has a cover need two: the audio pass
    cannot carry the artwork, because the cover frame sits at timestamp zero and
    the approved output-side ``-ss`` discards everything before the segment
    start. Every other case needs one.

    This is a command list, not a run plan — it owns no paths, no temp names and
    no lifecycle. Phase 11 must treat ``audio`` plus an optional ``artwork`` as a
    single transaction for one segment, including cleanup when the first
    succeeds and the second does not.
    """

    audio: tuple[str, ...]
    artwork: tuple[str, ...] | None = None

    @property
    def passes(self) -> tuple[tuple[str, ...], ...]:
        return (self.audio,) if self.artwork is None else (self.audio, self.artwork)

    @property
    def needs_artwork_pass(self) -> bool:
        return self.artwork is not None


def whole_book_commands(
    mode: MetadataMode,
    *,
    ffmpeg: str,
    source,
    destination: str,
    quality: int,
    tags: Mapping,
    decoder_args: Sequence[str] = (),
    picture: AttachedPicture | None = None,
    chapter_titles: Sequence[str] = (),
) -> ConversionCommands:
    """One whole-book output. Always a single pass.

    Artwork rides along in the same encode here — there is no seek to discard it.

    *chapter_titles* are the source's own, already frozen by the plan; they are
    written back explicitly because ``-map_metadata -1`` would otherwise strip
    them off the copied map. See :func:`metadata_args`.
    """
    keep = picture if wants_artwork(mode) else None
    argv = m4b_commands.whole_book_argv(
        ffmpeg=ffmpeg,
        source=source,
        destination=destination,
        quality=quality,
        decoder_args=decoder_args,
        output_args=metadata_args(tags,
                                  keep_chapters=retains_chapters(mode, split=False),
                                  chapter_titles=chapter_titles),
        attached_picture=None if keep is None else keep.stream_index,
    )
    return ConversionCommands(tuple(argv))


def segment_commands(
    mode: MetadataMode,
    *,
    ffmpeg: str,
    source,
    destination: str,
    quality: int,
    start: float,
    end: float,
    tags: Mapping,
    decoder_args: Sequence[str] = (),
    picture: AttachedPicture | None = None,
    staged: str | None = None,
) -> ConversionCommands:
    """One split output — one pass, or two when a cover has to be attached.

    *staged* is where the audio pass writes when a second pass will follow; the
    second reads it back and writes *destination*. Naming and placing that file
    belongs to the execution phase, so it is supplied rather than invented here.
    """
    keep = picture if wants_artwork(mode) else None
    first_target = destination if keep is None else staged
    if keep is not None and not first_target:
        raise ValueError("a staged path is required when an artwork pass will follow")

    audio = m4b_commands.segment_argv(
        ffmpeg=ffmpeg,
        source=source,
        destination=first_target,
        quality=quality,
        start=start,
        end=end,
        decoder_args=decoder_args,
        output_args=metadata_args(tags, keep_chapters=retains_chapters(mode, split=True)),
    )
    if keep is None:
        return ConversionCommands(tuple(audio))

    attach = m4b_commands.attach_artwork_argv(
        ffmpeg=ffmpeg,
        audio=first_target,
        artwork_source=source,
        artwork_stream=keep.stream_index,
        destination=destination,
    )
    return ConversionCommands(tuple(audio), tuple(attach))
