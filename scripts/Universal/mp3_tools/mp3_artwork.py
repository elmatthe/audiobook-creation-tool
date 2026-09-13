"""MP3 artwork: what a selected image becomes in an ID3 tag — Phase 6 of the
v0.6.3 focused MP3 redesign.

One service, consumed by the artwork controls now and by the Write ID3 and
Combine pipelines later, from the frozen ``BookPlan.artwork`` path. It answers
three questions and nothing else: *may this file be chosen*, *what bytes go
into the APIC frame*, and *what does the preview show*.

The rules (focused plan section 19):

- **Which files may be chosen** is the shared capability probe's answer —
  :func:`shared.image_capabilities.decodable_suffixes` — never a list of this
  module's own. JPG/JPEG and PNG are always offered; HEIC/HEIF only when the
  probe says this machine can decode them.
- **JPG/JPEG and PNG** are validated by decoding and embedded as the source's
  own bytes, with the matching MIME. No resize, no re-encode, and a file whose
  content does not match its extension is refused rather than mistagged.
- **HEIC/HEIF** is decoded through the same shared path (the probe registers
  the plugin exactly once) and converted to PNG **in memory** for the tag only,
  pixel dimensions preserved, MIME ``image/png``. No converted file is ever
  written and the source is never opened for writing.
- **APIC** is exactly one front-cover frame carrying the intended artwork, and
  the intended state *no artwork* leaves no APIC frame at all — old artwork
  never survives either way.
- **The preview** is a thumbnail scaled in memory for the screen. It changes
  neither the source nor what the tag will carry.

Nothing here writes an MP3. :func:`apply_artwork` edits a mutagen ``ID3`` tag
object; saving it to a staged copy is the processing pipelines' job.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from shared import image_capabilities

__all__ = [
    "ArtworkError",
    "Artwork",
    "artwork_filetypes",
    "load_artwork",
    "artwork_for",
    "apply_artwork",
    "preview_image",
    "FRONT_COVER",
]

#: ID3 picture type 3, "Cover (front)".
FRONT_COVER = 3

#: Pillow format names. Suffixes, MIME types and the suffix/format pairing all
#: come from Pillow's own registries so this module keeps no list of its own.
_PNG_FORMAT = "PNG"
_JPEG_FORMAT = "JPEG"


class ArtworkError(Exception):
    """A selected image cannot be used as MP3 artwork. Safe to show."""


@dataclass(frozen=True)
class Artwork:
    """What the tag will carry, resolved from one selected source file."""

    source: Path
    mime: str
    data: bytes
    width: int
    height: int
    #: True when the bytes are an in-memory PNG made from a HEIC/HEIF source.
    converted: bool = False


def artwork_filetypes() -> list[tuple[str, str]]:
    """The chooser filter, following the shared probe rather than a fixed list."""
    patterns = " ".join(f"*{suffix}" for suffix in image_capabilities.decodable_suffixes())
    return [("Images", patterns), ("All files", "*.*")]


def _require_source(path: object) -> Path:
    text = str(path or "").strip()
    if not text:
        raise ArtworkError("no artwork file was selected")
    source = Path(text)
    suffix = source.suffix.lower()
    if not image_capabilities.can_decode(suffix):
        offered = ", ".join(image_capabilities.decodable_suffixes())
        raise ArtworkError(
            f"{source.name}: {suffix or 'a file without an extension'} cannot be used as "
            f"artwork on this computer (accepted: {offered})")
    if not source.is_file():
        raise ArtworkError(f"{source.name}: the artwork file could not be found")
    return source


def _is_heif(suffix: str) -> bool:
    return suffix in image_capabilities.HEIF_SUFFIXES


def _open(source: Path):
    """Open through Pillow, registering the HEIF plugin via the shared probe."""
    from PIL import Image, UnidentifiedImageError

    if _is_heif(source.suffix.lower()):
        # The probe registers the plugin exactly once and is the only place
        # ``pillow_heif`` is imported; asking it here is what makes ``Image.open``
        # able to read the file at all.
        capability = image_capabilities.heif_capability()
        if not capability.decode:
            raise ArtworkError(f"{source.name}: HEIC/HEIF cannot be decoded here: "
                               f"{capability.detail}")
    try:
        opened = Image.open(source)
        opened.load()
        return opened
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ArtworkError(f"{source.name}: the image could not be decoded ({exc})") from exc


def load_artwork(path: object) -> Artwork:
    """Resolve one selected file into the bytes the tag will carry.

    Reads the source; never writes it, and writes nothing else.
    """
    source = _require_source(path)
    suffix = source.suffix.lower()
    with _open(source) as opened:
        width, height = opened.size
        detected = opened.format or ""
        if _is_heif(suffix):
            if detected != image_capabilities.HEIF_FORMAT:
                raise ArtworkError(
                    f"{source.name}: expected a HEIC/HEIF image, found {detected or 'unknown'}")
            buffer = io.BytesIO()
            # In memory only, same pixels, same size. RGBA survives; anything
            # exotic is normalised to RGB so PNG can carry it.
            image = opened if opened.mode in ("RGB", "RGBA") else opened.convert("RGB")
            image.save(buffer, format=_PNG_FORMAT)
            return Artwork(source=source, mime=_mime_of(_PNG_FORMAT),
                           data=buffer.getvalue(), width=width, height=height,
                           converted=True)
        if detected not in (_JPEG_FORMAT, _PNG_FORMAT) or _format_for(suffix) != detected:
            raise ArtworkError(
                f"{source.name}: the file content is {detected or 'not a recognised image'}, "
                f"which does not match its {suffix} name")
        mime = _mime_of(detected)
    return Artwork(source=source, mime=mime, data=source.read_bytes(),
                   width=width, height=height, converted=False)


def _format_for(suffix: str) -> str | None:
    """Pillow's own suffix -> format registry, so no pairing is spelled here."""
    from PIL import Image

    return Image.registered_extensions().get(suffix)


def _mime_of(image_format: str) -> str:
    from PIL import Image

    mime = Image.MIME.get(image_format)
    if not mime:
        raise ArtworkError(f"no MIME type is registered for {image_format}")
    return mime


def artwork_for(book_plan) -> Artwork | None:
    """The artwork a frozen ``BookPlan`` carries, or ``None`` when it has none.

    Reads only the plan's ``artwork`` value — never a widget, never the live
    workspace — so a retry embeds exactly what the original run planned.
    """
    chosen = getattr(book_plan, "artwork", None)
    if chosen is None or str(chosen).strip() == "":
        return None
    return load_artwork(chosen)


def apply_artwork(tags, artwork: Artwork | None) -> None:
    """Make *tags* carry exactly the intended artwork: one front cover, or none.

    Every existing APIC frame is removed first, whatever its type or
    description, so the tag's artwork is precisely what this run intends.
    Edits the mutagen ``ID3`` object in place; saving it is the caller's.
    """
    from mutagen.id3 import APIC

    if artwork is not None and not isinstance(artwork, Artwork):
        raise ArtworkError(f"artwork must be an Artwork or None, got {type(artwork).__name__}")
    tags.delall("APIC")
    if artwork is None:
        return
    tags.add(APIC(encoding=3, mime=artwork.mime, type=FRONT_COVER, desc="Cover (front)",
                  data=artwork.data))


def preview_image(path: object, max_size: tuple[int, int]):
    """A display thumbnail, scaled in memory. Not what the tag will carry.

    Returns a new Pillow image no larger than *max_size*; the source file and
    the bytes :func:`load_artwork` embeds are untouched by this.
    """
    source = _require_source(path)
    with _open(source) as opened:
        thumb = opened.copy()
    thumb.thumbnail(tuple(int(value) for value in max_size))
    return thumb
