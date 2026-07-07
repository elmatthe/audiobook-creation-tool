"""Behaviour preservation: Cover Image Converter core resize logic (real PIL,
no GUI)."""

from __future__ import annotations

import pytest

Image = pytest.importorskip("PIL.Image")

from mp3_tools.cover_resizer import next_version_path, resize_for_audiobook


@pytest.fixture()
def tall_cover(tmp_path):
    p = tmp_path / "cover.jpg"
    Image.new("RGB", (200, 400), color=(200, 30, 30)).save(p, format="JPEG")
    return p


def test_letterbox_keeps_whole_image_on_square_canvas(tall_cover, tmp_path):
    out = tmp_path / "letterboxed.jpg"
    resize_for_audiobook(tall_cover, out, size=256, letterbox=True)
    with Image.open(out) as img:
        assert img.size == (256, 256)
        # Tall source letterboxed on black: the side bars are black.
        assert img.getpixel((2, 128)) == (0, 0, 0)
        # The image content sits in the centre.
        r, g, b = img.getpixel((128, 128))
        assert r > 150 and g < 90 and b < 90


def test_center_crop_fills_square(tall_cover, tmp_path):
    out = tmp_path / "cropped.jpg"
    resize_for_audiobook(tall_cover, out, size=256, letterbox=False)
    with Image.open(out) as img:
        assert img.size == (256, 256)
        # Crop fills the frame — corners are image, not bars.
        r, g, b = img.getpixel((2, 2))
        assert r > 150 and g < 90 and b < 90


def test_unknown_extension_falls_back_to_jpg(tall_cover, tmp_path):
    out = tmp_path / "cover.webp"
    resize_for_audiobook(tall_cover, out, size=64, letterbox=True)
    assert (tmp_path / "cover.jpg").exists()


def test_next_version_path_skips_existing(tmp_path):
    p = tmp_path / "art.png"
    p.write_bytes(b"x")
    first = next_version_path(p)
    assert first.name == "art-1.png"
    first.write_bytes(b"x")
    assert next_version_path(p).name == "art-2.png"
