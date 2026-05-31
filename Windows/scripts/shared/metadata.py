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
# These are the canonical atoms we *write* to; on read we accept them first, then
# any other vendor's freeform series atom, then the native movement atoms (below).
SERIES_ATOM = "----:com.apple.iTunes:SERIES"
SERIES_PART_ATOM = "----:com.apple.iTunes:SERIES-PART"

# Native MP4 "movement" atoms — Audiobookshelf's documented fallback for series
# (©mvn = movement/series name, mvin = movement/series index, ©mvc = count). Some
# taggers store the series here instead of a freeform atom; we read them as a last
# resort but never write them (writes stay canonical freeform — see write_m4b_tags).
MOVEMENT_NAME_ATOM = "\xa9mvn"
MOVEMENT_INDEX_ATOM = "mvin"
MOVEMENT_COUNT_ATOM = "\xa9mvc"

# Album / grouping atoms. Real tagger output (e.g. tone / "Chapter and Verse"
# rips of the Trials of Apollo books) stores the *series name* in the album (and
# grouping) and the book's position only in the track number — carrying no SERIES
# or movement atom at all. We use the album as an *album-implied* series name and
# the grouping as an extra gate when deciding a track number looks series-like.
ALBUM_ATOM = "\xa9alb"
GROUPING_ATOM = "\xa9grp"

# Native MP4 track atom (``[(number, total)]``). Used as the lowest-priority,
# *implied* series-part source: surfaced only when it looks series-like (see
# _resolve_series) and never written (writes stay canonical freeform).
TRACK_ATOM = "trkn"

# Freeform-atom suffixes (the segment after the last ':') that hold a series name
# or part on real files. Audible rips tagged with Libation/tone, for example, use
# the ``----:com.pilabor.tone:SERIES`` / ``:PART`` namespace rather than Apple's.
_SERIES_NAME_SUFFIXES = ("SERIES",)
_SERIES_PART_SUFFIXES = ("SERIES-PART", "PART")

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


def _decode_atom_value(raw: Any) -> str:
    """Decode one raw MP4 atom value to a stripped string.

    Handles freeform ``bytes`` / ``MP4FreeForm`` (UTF-8), plain ``str`` text atoms,
    and ``int`` values (e.g. a movement index). Returns ``""`` for None/blank.
    """
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", "replace").strip()
    return str(raw).strip()


def _freeform_namespace(key: str) -> str:
    """Return a freeform atom's ``mean`` namespace segment, e.g.
    ``com.pilabor.tone`` from ``----:com.pilabor.tone:SERIES`` (``""`` if absent)."""
    parts = key.split(":")
    return parts[1] if len(parts) >= 3 else ""


def _movement_index(mp4tags) -> int | None:
    """Parse the native movement index (``mvin``) to an int, or ``None``.

    Handles the ``int`` / ``[int]`` / ``[(idx, total)]`` shapes mutagen may hand
    back for the movement-index atom.
    """
    mvals = mp4tags.get(MOVEMENT_INDEX_ATOM) if mp4tags else None
    if not mvals:
        return None
    raw = mvals[0]
    if isinstance(raw, (list, tuple)):
        raw = raw[0] if raw else None
    try:
        return int(raw)
    except (ValueError, TypeError):
        return None


def _track_number(mp4tags) -> tuple[int | None, int | None]:
    """Return ``(track_number, track_total)`` ints from the ``trkn`` atom.

    Either element is ``None`` if absent or unparseable. ``trkn`` is stored as
    ``[(number, total)]`` on MP4, but we tolerate a bare int just in case.
    """
    tvals = mp4tags.get(TRACK_ATOM) if mp4tags else None
    if not tvals:
        return None, None
    raw = tvals[0]
    num = total = None
    if isinstance(raw, (list, tuple)):
        if len(raw) >= 1:
            num = raw[0]
        if len(raw) >= 2:
            total = raw[1]
    else:
        num = raw

    def _int(x):
        try:
            return int(x)
        except (ValueError, TypeError):
            return None

    return _int(num), _int(total)


def _resolve_series(mp4tags) -> dict:
    """Resolve the series name/part from every source Audiobookshelf might use.

    Name and part are resolved on **independent** tracks — a part found without a
    name (or vice-versa) is still returned; part is never gated on name.

    Series **name** priority:
      1. a freeform ``…:SERIES`` atom (canonical ``----:com.apple.iTunes:SERIES``
         first, then any other vendor namespace, e.g. ``----:com.pilabor.tone:SERIES``);
      2. the native movement name atom ``©mvn``;
      3. *album-implied* — if no name was found but a part was, and the file has an
         album, the album is used as the series name (Audiobookshelf groups
         part-only books by their album). This is flagged ``"album-implied"`` so the
         write path never silently persists it.

    Series **part** priority:
      1. a freeform ``…:SERIES-PART`` / ``…:PART`` atom (any namespace);
      2. the native movement index atom ``mvin``;
      3. *track-implied* — the track number (``trkn``), surfaced ONLY when it looks
         series-like (the track total > 1, or an album/grouping name is present) so
         an incidental track number on a standalone book is not turned into a fake
         part. Flagged ``"track-implied"`` and, like album-implied, never written.

    Returns a dict carrying ``series`` / ``series_part`` **only when found**
    (non-empty), plus the always-present provenance keys ``series_source`` /
    ``series_part_source`` (``"freeform:<ns>"`` | ``"movement"`` | ``"album-implied"``
    | ``"track-implied"`` | ``None``) and ``series_atom`` / ``series_part_atom`` (the
    exact atom key the value came from, or ``None`` for an implied value) so the GUI
    can show the user what is really on the file.
    """
    out: dict[str, Any] = {
        "series_source": None,
        "series_part_source": None,
        "series_atom": None,
        "series_part_atom": None,
    }
    if not mp4tags:
        return out

    freeform = [k for k in mp4tags.keys() if k.startswith("----:")]

    def _val(key) -> str:
        vals = mp4tags.get(key)
        return _decode_atom_value(vals[0]) if vals else ""

    def _find_freeform(suffixes):
        """First non-empty freeform atom matching ``suffixes`` (canonical first)."""
        for suf in suffixes:
            canonical = f"----:com.apple.iTunes:{suf}"
            if canonical in mp4tags:
                v = _val(canonical)
                if v:
                    return canonical, v
            for key in freeform:
                if key.rsplit(":", 1)[-1].upper() == suf:
                    v = _val(key)
                    if v:
                        return key, v
        return None, ""

    # --- series name: freeform …SERIES -> ©mvn (album-implied handled below) ---
    atom, val = _find_freeform(_SERIES_NAME_SUFFIXES)
    if val:
        out["series"] = val
        out["series_atom"] = atom
        out["series_source"] = f"freeform:{_freeform_namespace(atom)}"
    else:
        mv = _val(MOVEMENT_NAME_ATOM)
        if mv:
            out["series"] = mv
            out["series_atom"] = MOVEMENT_NAME_ATOM
            out["series_source"] = "movement"

    # --- series part: freeform …SERIES-PART/…PART -> mvin -> trkn (implied) ---
    atom, val = _find_freeform(_SERIES_PART_SUFFIXES)
    if val:
        out["series_part"] = val
        out["series_part_atom"] = atom
        out["series_part_source"] = f"freeform:{_freeform_namespace(atom)}"
    else:
        mv_idx = _movement_index(mp4tags)
        if mv_idx is not None:
            out["series_part"] = str(mv_idx)
            out["series_part_atom"] = MOVEMENT_INDEX_ATOM
            out["series_part_source"] = "movement"
        else:
            tnum, ttotal = _track_number(mp4tags)
            if tnum:  # non-zero track number
                album = _val(ALBUM_ATOM) or _val(GROUPING_ATOM)
                series_like = (ttotal is not None and ttotal > 1) or bool(album)
                if series_like:
                    out["series_part"] = str(tnum)
                    out["series_part_atom"] = TRACK_ATOM
                    out["series_part_source"] = "track-implied"

    # --- album-implied name: a part with no real name, but an album to group by ---
    if not out.get("series") and out.get("series_part"):
        album = _val(ALBUM_ATOM)
        if album:
            out["series"] = album
            out["series_atom"] = None
            out["series_source"] = "album-implied"

    return out


def _strip_conflicting_series_atoms(mp4tags, suffixes, movement_atom) -> None:
    """Remove freeform/movement atoms that would shadow a freshly written series.

    ffprobe (and so Audiobookshelf) surface a freeform atom under the segment after
    its last ``:`` — so a leftover ``----:com.pilabor.tone:SERIES`` would keep
    shadowing a value we write to ``----:com.apple.iTunes:SERIES`` (they both
    surface as ``SERIES``). When the user actually writes a series value we delete
    every freeform atom whose suffix is in ``suffixes`` (the canonical one is
    re-added by the caller) and the native movement atom, so the write is
    authoritative and the old value cannot win. Only ever called when writing a
    non-empty value — a blank field never reaches here (preserve-by-default).
    """
    if not mp4tags:
        return
    for key in list(mp4tags.keys()):
        if key.startswith("----:") and key.rsplit(":", 1)[-1].upper() in suffixes:
            del mp4tags[key]
    if movement_atom and movement_atom in mp4tags:
        del mp4tags[movement_atom]


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
    ``series`` / ``series_part`` (strings — resolved independently; name from a
    freeform ``…SERIES`` atom → ``©mvn`` → the album (album-implied); part from a
    freeform ``…SERIES-PART``/``…PART`` atom → ``mvin`` → the track number
    (track-implied, gated); present only when found), and ``has_cover`` (bool,
    always present). Always includes the series provenance keys ``series_source`` /
    ``series_part_source`` (``"freeform:<ns>"`` | ``"movement"`` | ``"album-implied"``
    | ``"track-implied"`` | ``None``) and ``series_atom`` / ``series_part_atom`` (the
    exact source atom, or ``None`` for an implied value). An ``"album-implied"`` name
    and a ``"track-implied"`` part are display-only and must never be written back.
    Missing text tags are simply absent from the returned dict.
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

    # Series can live in several atoms on real files; resolve from all of them.
    out.update(_resolve_series(mp4.tags))
    out["has_cover"] = bool(mp4.tags and mp4.tags.get("covr"))
    return out


def describe_series_atoms(path) -> list[tuple[str, str]]:
    """Return ``[(atom_key, decoded_value), ...]`` for every series-relevant atom
    present on the file, for the GUI's read-back display.

    Checks the freeform ``----:…:SERIES`` / ``SERIES-PART`` / ``PART`` atoms (any
    vendor namespace) and the native movement atoms ``©mvn`` / ``mvin`` / ``©mvc``.
    Returns ``[]`` when none are present. Never raises on a missing/odd atom.
    """
    from mutagen.mp4 import MP4

    try:
        tags = MP4(str(Path(path))).tags
    except Exception:
        return []
    if not tags:
        return []

    found: list[tuple[str, str]] = []
    wanted = set(_SERIES_NAME_SUFFIXES) | set(_SERIES_PART_SUFFIXES)
    for key in tags.keys():
        if key.startswith("----:") and key.rsplit(":", 1)[-1].upper() in wanted:
            vals = tags.get(key)
            found.append((key, _decode_atom_value(vals[0]) if vals else ""))
    for atom in (MOVEMENT_NAME_ATOM, MOVEMENT_INDEX_ATOM, MOVEMENT_COUNT_ATOM):
        if atom in tags:
            vals = tags.get(atom)
            raw = vals[0] if vals else None
            if isinstance(raw, (list, tuple)):
                raw = raw[0] if raw else None
            found.append((atom, _decode_atom_value(raw)))
    return found


def write_m4b_tags(path, tags: dict) -> None:
    """Write/update the given tags on an M4B/MP4 file, preserving all others.

    Only keys present in ``tags`` are touched. Recognised keys: ``title``,
    ``artist``, ``album_artist``, ``album``, ``comment``, ``genre``, ``year``
    (text), ``track`` (int), ``series`` / ``series_part`` (written as the
    freeform Audiobookshelf atoms, UTF-8 bytes), and ``cover_path`` (path to a
    JPEG/PNG image to embed as the front cover). A text/series key whose value
    is empty/None clears that tag; an empty ``cover_path`` clears the cover.

    Writing a non-empty ``series`` / ``series_part`` also strips any *other*
    vendor freeform atom (e.g. ``----:com.pilabor.tone:SERIES``) or movement atom
    that ffprobe/Audiobookshelf would surface under the same name, so the new
    value is authoritative rather than shadowed by a leftover atom. A blank series
    field is never written, so this never disturbs an existing tag (preserve-by-default).
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

    for friendly, atom, suffixes, movement_atom in (
        ("series", SERIES_ATOM, _SERIES_NAME_SUFFIXES, MOVEMENT_NAME_ATOM),
        ("series_part", SERIES_PART_ATOM, _SERIES_PART_SUFFIXES, MOVEMENT_INDEX_ATOM),
    ):
        if friendly in tags:
            val = _clean(tags[friendly])
            if val:
                # Drop any vendor freeform atom (e.g. ----:com.pilabor.tone:SERIES)
                # or movement atom that surfaces under the same ffprobe/ABS name,
                # then write our canonical atom — otherwise the old value shadows
                # the new one and the overwrite silently fails to take effect.
                _strip_conflicting_series_atoms(mp4.tags, suffixes, movement_atom)
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


# --------------------------------------------------------------------------- #
# Chapter-title editing (Phase D) — ffmpeg ffmetadata round-trip
# --------------------------------------------------------------------------- #
#
# mutagen does not expose MP4/QuickTime chapter-track titles for editing, so
# chapter titles are edited with an ffmpeg ffmetadata round-trip: dump the file's
# metadata (global tags + [CHAPTER] blocks with exact START/END), rewrite only
# the chapter title= lines positionally, then re-mux with ``-c copy`` taking the
# audio + cover + global metadata from the original file and the chapters from
# the edited dump. ``-c copy`` keeps the audio and chapter timestamps byte-stable
# — only the title strings change. (Chosen over mutagen because mutagen cannot
# edit chapter titles; verified empirically that timestamps and other metadata
# are preserved.)


def _ffmeta_escape(value: str) -> str:
    """Escape a value for an ffmetadata file (``=``, ``;``, ``#``, ``\\`` and newlines)."""
    out = []
    for ch in value:
        if ch in "=;#\\" or ch == "\n":
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def read_chapter_titles(path) -> list[str]:
    """Return the ordered list of chapter titles from an M4B.

    Each entry is the chapter's title (``""`` for an untitled chapter). The list
    length equals the file's chapter count.
    """
    import json

    from . import ffmpeg_utils
    from . import subprocess_utils as sp

    out = sp.check_output(
        [
            ffmpeg_utils.ffprobe_cmd(),
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_chapters",
            str(Path(path)),
        ]
    )
    data = json.loads(out)
    return [str(ch.get("tags", {}).get("title", "")) for ch in data.get("chapters", [])]


def apply_chapter_titles(path, new_titles) -> None:
    """Positionally overwrite chapter titles on the M4B at ``path`` (a COPY).

    ``new_titles[i]`` replaces chapter ``i``'s title. Rules:
      - entries past the file's chapter count are ignored;
      - a blank/empty entry leaves that chapter's title unchanged;
      - chapters, their count, order and timestamps, the audio, the cover art,
        and all global metadata are left untouched — only the title strings of
        the supplied positions change.

    Does nothing if ``new_titles`` is empty or every supplied entry is blank.
    Operate on a COPY only — never on an imported original.
    """
    import os
    import shutil
    import tempfile

    from mutagen.mp4 import MP4

    from . import ffmpeg_utils
    from . import subprocess_utils as sp

    path = Path(path)
    if not any((t or "").strip() for t in new_titles):
        return

    # ffmpeg's mov muxer drops freeform iTunes atoms (e.g. the Audiobookshelf
    # ----:com.apple.iTunes:SERIES / SERIES-PART) on a -c copy re-mux, so snapshot
    # every freeform atom now and restore it with mutagen afterwards.
    _src = MP4(str(path))
    freeform = {
        k: list(v) for k, v in (_src.tags or {}).items() if k.startswith("----:")
    }

    work = Path(tempfile.mkdtemp(prefix="chaptitles_"))
    try:
        # 1) Dump the file's ffmetadata (global tags + [CHAPTER] blocks).
        meta_in = work / "in.ffmeta"
        sp.run(
            [ffmpeg_utils.ffmpeg_cmd(), "-hide_banner", "-loglevel", "error",
             "-y", "-i", str(path), "-f", "ffmetadata", str(meta_in)],
            check=True,
        )
        lines = meta_in.read_text(encoding="utf-8").splitlines()

        # 2) Split into the global preamble + one list of lines per [CHAPTER].
        first = next((i for i, ln in enumerate(lines) if ln.strip() == "[CHAPTER]"), None)
        if first is None:
            return  # no chapters — nothing to do
        preamble = lines[:first]
        blocks: list[list[str]] = []
        cur: list[str] | None = None
        for ln in lines[first:]:
            if ln.strip() == "[CHAPTER]":
                if cur is not None:
                    blocks.append(cur)
                cur = []
            else:
                cur.append(ln)
        if cur is not None:
            blocks.append(cur)

        # 3) Apply the new titles positionally (skip blanks; only non-blank wins).
        changed = False
        for i, block in enumerate(blocks):
            if i >= len(new_titles):
                break
            nt = (new_titles[i] or "").strip()
            if not nt:
                continue
            block[:] = [b for b in block if not b.startswith("title=")]
            block.append("title=" + _ffmeta_escape(nt))
            changed = True
        if not changed:
            return

        # 4) Reassemble the edited ffmetadata.
        out_lines = list(preamble)
        for block in blocks:
            out_lines.append("[CHAPTER]")
            out_lines.extend(block)
        meta_out = work / "out.ffmeta"
        meta_out.write_text("\n".join(out_lines) + "\n", encoding="utf-8")

        # 5) Re-mux: take the audio and (optional) cover-art video from the file
        #    plus its global metadata, and a freshly built chapter track from the
        #    edited dump. We deliberately map only ``0:a`` + ``0:v?`` and NOT the
        #    file's existing chapter text/data stream — copying that stream makes
        #    the ipod/mov muxer reject it ("Tag text incompatible…"); -map_chapters
        #    rebuilds the chapter track instead. ``-c copy`` keeps audio + chapter
        #    timestamps byte-stable. A temp output beside the file keeps os.replace
        #    on the same filesystem (avoids cross-drive errors).
        tmp_out = path.with_name(path.stem + ".retitle.tmp" + path.suffix)
        sp.run(
            [ffmpeg_utils.ffmpeg_cmd(), "-hide_banner", "-loglevel", "error", "-y",
             "-i", str(path), "-i", str(meta_out),
             "-map", "0:a", "-map", "0:v?", "-map_metadata", "0", "-map_chapters", "1",
             "-c", "copy", str(tmp_out)],
            check=True,
        )
        os.replace(tmp_out, path)

        # Restore the freeform atoms the re-mux dropped.
        if freeform:
            dst = MP4(str(path))
            if dst.tags is None:
                dst.add_tags()
            for key, value in freeform.items():
                dst.tags[key] = value
            dst.save()
    finally:
        shutil.rmtree(work, ignore_errors=True)
