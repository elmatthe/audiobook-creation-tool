"""Shared M4B/MP4 metadata helpers.

Two concerns live here so the MP3 tools don't each re-implement the same tag
mapping:

1. **ffmpeg tagging at encode time.** ``m4b_maker`` embeds metadata in an
   ffmetadata file it hands to ffmpeg; ``m4b_converter`` passes ``-metadata``
   flags on the ffmpeg command line. Both need the *same* set of fields written
   the *same* way, so the field list + key names live in one place here
   (:func:`ffmpeg_metadata_args`, :func:`ffmetadata_header_lines`).

2. **mutagen read/edit after the fact.** ffmpeg writes tags when it encodes, but
   editing an existing M4B without re-encoding (the Phase 6 Metadata Editor, and
   the Phase 6 series tags) needs mutagen. :func:`read_m4b_tags` /
   :func:`write_m4b_tags` are that canonical read/write pair. ``write_m4b_tags``
   only touches the keys you pass, leaving every other tag in the file intact.

Series tags follow the Audiobookshelf convention (Briefing §6): Audiobookshelf
scans with ffprobe, which does *not* surface the native MP4 movement atoms, so
the series name/part are written as the freeform atoms
``----:com.apple.iTunes:SERIES`` and ``----:com.apple.iTunes:SERIES-PART``
(UTF-8 bytes), which ffprobe exposes as ``series`` / ``series-part``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# Freeform MP4 atoms read by Audiobookshelf's ffprobe-based scanner (Briefing §6).
SERIES_ATOM = "----:com.apple.iTunes:SERIES"
SERIES_PART_ATOM = "----:com.apple.iTunes:SERIES-PART"

# Canonical text fields shared by both M4B tools, in the order they are written.
# These keys are the friendly names callers use; the values are the matching
# ffmpeg metadata key (ffmpeg uses the same spellings on the CLI and in an
# ffmetadata file).
_FFMPEG_TEXT_FIELDS = ("title", "artist", "album_artist", "album")

# Mapping of friendly tag name -> native MP4 atom, for mutagen read/write.
# The first four are also the ffmpeg-shared fields; the rest (comment, genre,
# year) are extra text fields the Phase 6 Metadata Editor edits after the fact.
_MP4_TEXT_ATOMS = {
    "title": "\xa9nam",
    "artist": "\xa9ART",
    "album_artist": "aART",
    "album": "\xa9alb",
    "comment": "\xa9cmt",
    "genre": "\xa9gen",
    "year": "\xa9day",
}


def _clean(value: Any) -> str:
    """Return ``value`` as a stripped string, or ``""`` for None/blank."""
    if value is None:
        return ""
    return str(value).strip()


# --------------------------------------------------------------------------- #
# ffmpeg encode-time helpers (used by m4b_maker and m4b_converter)
# --------------------------------------------------------------------------- #


def ffmpeg_metadata_args(tags: dict) -> list[str]:
    """Build ``-metadata key=value`` ffmpeg CLI args from a friendly tag dict.

    Only non-empty fields are emitted. Recognises the four shared text fields
    plus an optional integer ``track``. Order is stable so callers (and tests)
    get deterministic command lines.
    """
    args: list[str] = []
    for key in _FFMPEG_TEXT_FIELDS:
        val = _clean(tags.get(key))
        if val:
            args += ["-metadata", f"{key}={val}"]
    track = tags.get("track")
    if track not in (None, ""):
        args += ["-metadata", f"track={track}"]
    return args


def ffmetadata_header_lines(tags: dict) -> list[str]:
    """Build the global-metadata lines for an ffmetadata file.

    Returns ``key=value`` lines for the non-empty shared text fields (no
    ``;FFMETADATA1`` header, no chapters — the caller owns the file layout).
    """
    lines: list[str] = []
    for key in _FFMPEG_TEXT_FIELDS:
        val = _clean(tags.get(key))
        if val:
            lines.append(f"{key}={val}")
    return lines


# --------------------------------------------------------------------------- #
# mutagen read/edit-after helpers (canonical pair; used by the Phase 6 editor)
# --------------------------------------------------------------------------- #


def read_m4b_tags(path) -> dict:
    """Read tags from an M4B/MP4 file into a friendly dict.

    Returns keys ``title``, ``artist``, ``album_artist``, ``album``, ``comment``,
    ``genre``, ``year`` (strings), ``track`` (int track number, if present),
    ``series`` / ``series_part`` (strings, from the Audiobookshelf freeform
    atoms), and ``has_cover`` (bool, always present). Missing text tags are
    simply absent from the returned dict.
    """
    from mutagen.mp4 import MP4

    mp4 = MP4(str(Path(path)))
    out: dict[str, Any] = {}

    for friendly, atom in _MP4_TEXT_ATOMS.items():
        vals = mp4.tags.get(atom) if mp4.tags else None
        if vals:
            out[friendly] = str(vals[0])

    if mp4.tags:
        trkn = mp4.tags.get("trkn")
        if trkn:
            num = trkn[0][0] if isinstance(trkn[0], tuple) else trkn[0]
            if num:
                out["track"] = int(num)

        for friendly, atom in (("series", SERIES_ATOM), ("series_part", SERIES_PART_ATOM)):
            vals = mp4.tags.get(atom)
            if vals:
                raw = vals[0]
                out[friendly] = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)

    out["has_cover"] = bool(mp4.tags and mp4.tags.get("covr"))
    return out


def write_m4b_tags(path, tags: dict) -> None:
    """Write/update the given tags on an M4B/MP4 file, preserving all others.

    Only keys present in ``tags`` are touched. Recognised keys: ``title``,
    ``artist``, ``album_artist``, ``album``, ``comment``, ``genre``, ``year``
    (text), ``track`` (int), ``series`` / ``series_part`` (written as the
    freeform Audiobookshelf atoms, UTF-8 bytes), and ``cover_path`` (path to a
    JPEG/PNG image to embed as the front cover). A text/series key whose value
    is empty/None clears that tag; an empty ``cover_path`` clears the cover.
    """
    from mutagen.mp4 import MP4, MP4Cover

    mp4 = MP4(str(Path(path)))
    if mp4.tags is None:
        mp4.add_tags()

    for friendly, atom in _MP4_TEXT_ATOMS.items():
        if friendly in tags:
            val = _clean(tags[friendly])
            if val:
                mp4.tags[atom] = [val]
            elif atom in mp4.tags:
                del mp4.tags[atom]

    if "track" in tags:
        track = tags["track"]
        if track in (None, ""):
            if "trkn" in mp4.tags:
                del mp4.tags["trkn"]
        else:
            mp4.tags["trkn"] = [(int(track), 0)]

    for friendly, atom in (("series", SERIES_ATOM), ("series_part", SERIES_PART_ATOM)):
        if friendly in tags:
            val = _clean(tags[friendly])
            if val:
                mp4.tags[atom] = [val.encode("utf-8")]
            elif atom in mp4.tags:
                del mp4.tags[atom]

    if "cover_path" in tags:
        cover = _clean(tags["cover_path"])
        if cover:
            data = Path(cover).read_bytes()
            fmt = (
                MP4Cover.FORMAT_PNG
                if cover.lower().endswith(".png")
                else MP4Cover.FORMAT_JPEG
            )
            mp4.tags["covr"] = [MP4Cover(data, imageformat=fmt)]
        elif "covr" in mp4.tags:
            del mp4.tags["covr"]

    mp4.save()


def clear_metadata_keep_chapters(path) -> None:
    """Remove every standard + freeform iTunes metadata atom from an M4B while
    PRESERVING chapter markers, their titles, and any bookmark structure.

    Use this on a COPY only — never on an imported original (the Metadata Editor
    copies first, per Phase B).

    Implementation (verified empirically against a real multi-chapter M4B):
      - Chapter data in MP4/M4B lives in a dedicated chapter *track* (a ``trak``
        in ``moov``, referenced by a ``chap`` track reference), NOT in the
        ``ilst`` metadata atoms that ``mutagen.mp4.MP4Tags`` exposes. Clearing
        every ``MP4Tags`` key (title/artist/album/year/genre/comment/cover art,
        the freeform ``----:com.apple.iTunes:SERIES``/``SERIES-PART`` atoms, and
        anything else in ``ilst``) therefore leaves the chapter track — and so
        the chapter count, titles, and timestamps — untouched.
      - We delete keys individually (rather than rely on a full container
        rewrite) so no chapter track is ever dropped. mutagen's ``save`` only
        rewrites the ``ilst``/``udta`` metadata, not the chapter ``trak``.
    """
    from mutagen.mp4 import MP4

    mp4 = MP4(str(Path(path)))
    if mp4.tags:
        for key in list(mp4.tags.keys()):
            del mp4.tags[key]
        mp4.save()
