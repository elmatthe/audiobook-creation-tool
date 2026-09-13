"""M4B artwork: what a selected image becomes in an MP4 ``covr`` atom — v0.6.4
Phase 1, shared by the M4B Maker and the M4B Metadata Editor.

One Tk-free service, consumed by both M4B panels' artwork controls and by
their processing pipelines from a frozen plan value. It answers the same three
questions the MP3 Tool's service answers — *may this file be chosen*, *what
bytes go into the container*, and *what does the preview show* — for the MP4
container instead of an ID3 tag.

The rules (v0.6.4 plan sections 4.6, 5.11, 6.12 and Phase 1):

- **Which files may be chosen** is the shared capability probe's answer —
  :func:`shared.image_capabilities.decodable_suffixes` — never a list of this
  module's own. JPG/JPEG and PNG are always offered; HEIC/HEIF only when the
  probe says this machine can decode them.
- **Decoding is the one proved path.** Validation, source-byte preservation for
  JPG/PNG, the in-memory HEIC/HEIF → PNG conversion (pixel dimensions kept, no
  file written) and the preview thumbnail are :mod:`mp3_tools.mp3_artwork`'s,
  reused rather than reimplemented — that module already routes every decode
  through the shared probe. What is M4B-specific, and lives here, is only the
  container representation: an :class:`M4BCover` carrying the bytes together
  with mutagen's ``MP4Cover`` image format, and the two functions that put it
  on (or take it off) an MP4 container.
- **The container is edited in place by mutagen**, so embedding a cover on a
  staged M4B rewrites only its metadata atoms; the audio stream is never
  re-encoded. There is exactly one ``covr`` entry afterwards, or none.
- **The source is read-only.** Nothing here opens it for writing, resizes or
  crops it, or writes a converted copy beside it.

What deliberately does not live here: the ID3 ``APIC`` implementation
(``mp3_artwork.apply_artwork``, which must not be forced into MP4 containers),
any panel state, any chooser dialog, and any decision about *which* cover a
Book gets — Shared-versus-Book precedence is the workspace model's.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mp3_tools import mp3_artwork
from mp3_tools.mp3_artwork import Artwork, ArtworkError, artwork_filetypes, preview_image

__all__ = [
    "ArtworkError",
    "M4BCover",
    "artwork_filetypes",
    "load_cover",
    "cover_for",
    "apply_cover",
    "embed_cover",
    "preview_image",
]

#: The MP4 ``covr`` atom key, spelled once.
_COVER_ATOM = "covr"

#: Pillow format name used only to look up the PNG MIME in Pillow's registry,
#: so this module carries no MIME or suffix literal of its own.
_PNG_FORMAT = "PNG"


@dataclass(frozen=True)
class M4BCover:
    """What the container will carry, resolved from one selected source file."""

    source: Path
    #: ``MP4Cover.FORMAT_JPEG`` or ``MP4Cover.FORMAT_PNG``.
    image_format: int
    data: bytes
    width: int
    height: int
    #: True when the bytes are an in-memory PNG made from a HEIC/HEIF source.
    converted: bool = False


def _cover_format(mime: str) -> int:
    """mutagen's cover format for the MIME the shared loader resolved."""
    from PIL import Image
    from mutagen.mp4 import MP4Cover

    if mime == Image.MIME.get(_PNG_FORMAT):
        return MP4Cover.FORMAT_PNG
    return MP4Cover.FORMAT_JPEG


def _from_artwork(loaded: Artwork) -> M4BCover:
    return M4BCover(source=loaded.source, image_format=_cover_format(loaded.mime),
                    data=loaded.data, width=loaded.width, height=loaded.height,
                    converted=loaded.converted)


def load_cover(path: object) -> M4BCover:
    """Resolve one selected file into the bytes the ``covr`` atom will carry.

    Reads the source through the shared decode path; never writes it, and
    writes nothing else. Raises :class:`ArtworkError` for anything the machine
    cannot decode, a file whose content does not match its name, or a missing
    or unsupported file.
    """
    return _from_artwork(mp3_artwork.load_artwork(path))


def cover_for(book_plan) -> M4BCover | None:
    """The cover a frozen plan carries, or ``None`` when it has none.

    Reads only the plan's ``artwork`` value — never a widget, never the live
    workspace — so a retry embeds exactly what the original run planned.
    """
    loaded = mp3_artwork.artwork_for(book_plan)
    return None if loaded is None else _from_artwork(loaded)


def apply_cover(tags, cover: M4BCover | None) -> None:
    """Make *tags* carry exactly the intended cover: one ``covr`` entry, or none.

    Edits a mutagen ``MP4Tags`` mapping in place and touches no other atom;
    saving it is the caller's. Any existing cover entries are replaced whole,
    so the container's artwork is precisely what this run intends.
    """
    from mutagen.mp4 import MP4Cover

    if cover is None:
        if _COVER_ATOM in tags:
            del tags[_COVER_ATOM]
        return
    if not isinstance(cover, M4BCover):
        raise ArtworkError(
            f"cover must be an M4BCover or None, got {type(cover).__name__}")
    tags[_COVER_ATOM] = [MP4Cover(cover.data, imageformat=cover.image_format)]


def embed_cover(path: object, cover: M4BCover | None) -> None:
    """Put *cover* on the MP4 container at *path* (or remove its cover for ``None``).

    A metadata-only rewrite: mutagen rewrites the container's atoms and leaves
    the audio stream as it was. Intended for a **staged** copy — the pipelines
    own which file that is; this function never chooses one.
    """
    from mutagen import MutagenError
    from mutagen.mp4 import MP4

    target = Path(str(path))
    try:
        container = MP4(str(target))
        if container.tags is None:
            container.add_tags()
        apply_cover(container.tags, cover)
        container.save()
    except (MutagenError, OSError, ValueError) as exc:
        raise ArtworkError(
            f"{target.name}: the cover could not be written to this file ({exc})") from exc
