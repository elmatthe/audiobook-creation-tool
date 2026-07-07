"""Behaviour preservation: shared metadata helpers used by the M4B Maker /
Converter / Metadata Editor (pure — no files, no ffmpeg)."""

from __future__ import annotations

from shared import metadata


def test_ffmpeg_metadata_args_emits_only_nonempty_fields():
    args = metadata.ffmpeg_metadata_args(
        {"title": "Book", "artist": "", "album": None, "track": 3}
    )
    assert args == ["-metadata", "title=Book", "-metadata", "track=3"]


def test_ffmetadata_header_lines_stable_order():
    tags = {"album": "Set", "title": "Book", "artist": "Narrator"}
    lines = metadata.ffmetadata_header_lines(tags)
    # Deterministic field order, only non-empty fields, key=value shape.
    assert lines == [f"{k}={v}" for k, v in
                     [(l.split("=", 1)[0], l.split("=", 1)[1]) for l in lines]]
    assert set(lines) == {"title=Book", "artist=Narrator", "album=Set"}
    assert metadata.ffmetadata_header_lines({}) == []


def test_freeform_namespace_parsing():
    assert metadata._freeform_namespace("----:com.apple.iTunes:SERIES") == "com.apple.iTunes"
    assert metadata._freeform_namespace("----:com.pilabor.tone:SERIES-PART") == "com.pilabor.tone"
    assert metadata._freeform_namespace("©nam") == ""


def test_series_atom_constants_match_audiobookshelf_contract():
    # Audiobookshelf's ffprobe scanner reads these exact freeform atoms —
    # regression-guard the constants the whole series feature hangs on.
    assert metadata.SERIES_ATOM == "----:com.apple.iTunes:SERIES"
    assert metadata.SERIES_PART_ATOM == "----:com.apple.iTunes:SERIES-PART"
