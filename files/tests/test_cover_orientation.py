"""Cover Image honours a photo's EXIF orientation: output, preview and Details.

v0.6.6 Phase 10 defect. Phones store a portrait photo as landscape pixels with
an EXIF ``Orientation`` tag, and every viewer turns it upright. ``resize_for_audiobook``
read the raw pixels and saved without the tag. So the cover came out turned 90° or
180° from the photo the user chose, and in source-side replace mode it overwrote the
original that way. The Medium Thumbnail and the Details dimensions showed the raw
pixels too.

HEIC/HEIF needs nothing extra: ``pillow-heif`` rotates on decode and resets the tag
to 1, so the same call leaves it alone.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image, ImageOps

from mp3_tools import cover_resizer as cr

ORIENTATION = 0x0112
RED = (255, 0, 0)
BLUE = (0, 0, 255)


def _photo(path: Path, orientation: int | None) -> Path:
    """400×200 stored pixels, left half red, right half blue, with the given tag."""
    image = Image.new("RGB", (400, 200), BLUE)
    image.paste(Image.new("RGB", (200, 200), RED), (0, 0))
    exif = Image.Exif()
    if orientation is not None:
        exif[ORIENTATION] = orientation
    image.save(path, quality=95, exif=exif.tobytes())
    return path


def _upright(path: Path) -> Image.Image:
    """The photo as every viewer shows it."""
    with Image.open(path) as opened:
        return ImageOps.exif_transpose(opened).convert("RGB")


def _close(pixel, colour) -> bool:
    return all(abs(a - b) <= 40 for a, b in zip(pixel, colour))


def _layout(image: Image.Image) -> str:
    """Where the red half is, read at the centre of each edge band."""
    w, h = image.size
    probes = {"top": (w // 2, h // 3), "bottom": (w // 2, 2 * h // 3),
              "left": (w // 3, h // 2), "right": (2 * w // 3, h // 2)}
    red = sorted(side for side, xy in probes.items() if _close(image.getpixel(xy), RED))
    return "+".join(red)


@pytest.mark.parametrize("orientation", (3, 6, 8))
@pytest.mark.parametrize("letterbox", (True, False), ids=("letterbox", "crop"))
def test_the_output_is_the_photo_as_the_user_sees_it(tmp_path, orientation, letterbox):
    source = _photo(tmp_path / "phone.jpg", orientation)
    expected_red = _layout(_upright(source))
    out = cr.resize_for_audiobook(source, tmp_path / "out.jpg", 300, letterbox)
    with Image.open(out) as written:
        assert written.size == (300, 300)
        assert written.getexif().get(ORIENTATION) in (None, 1)
        assert _layout(written.convert("RGB")) == expected_red


def test_a_photo_without_a_tag_is_unchanged(tmp_path):
    source = _photo(tmp_path / "plain.jpg", None)
    out = cr.resize_for_audiobook(source, tmp_path / "out.jpg", 300, True)
    with Image.open(out) as written:
        assert _layout(written.convert("RGB")) == "left"


def test_the_preview_is_upright(tmp_path):
    source = _photo(tmp_path / "phone.jpg", 6)
    data = cr.encode_thumbnail(source, 128)
    with Image.open(io.BytesIO(data)) as preview:
        assert preview.size[1] > preview.size[0]
        assert _layout(preview.convert("RGB")) == _layout(_upright(source))


@pytest.mark.parametrize("orientation,shown", ((1, "400 × 200"), (3, "400 × 200"),
                                               (6, "200 × 400"), (8, "200 × 400")))
def test_details_report_the_dimensions_the_user_sees(tmp_path, orientation, shown):
    facts = cr.read_image_facts(_photo(tmp_path / "phone.jpg", orientation))
    assert facts.dimensions == shown


def test_a_heic_is_not_turned_twice(tmp_path):
    from shared import image_capabilities

    if not image_capabilities.heif_capability().encode:
        pytest.skip("HEIF cannot be encoded on this machine")
    stored = Image.new("RGB", (400, 200), BLUE)
    stored.paste(Image.new("RGB", (200, 200), RED), (0, 0))
    exif = Image.Exif()
    exif[ORIENTATION] = 6
    source = tmp_path / "phone.heic"
    stored.save(source, format="HEIF", exif=exif.tobytes())
    expected_red = _layout(_upright(source))
    out = cr.resize_for_audiobook(source, tmp_path / "out.heic", 300, True)
    with Image.open(out) as written:
        assert _layout(written.convert("RGB")) == expected_red == "top"
