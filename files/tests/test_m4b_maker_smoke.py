"""Behaviour preservation: M4B Maker title/chapter helpers (no ffmpeg spawned)."""

from __future__ import annotations

from mp3_tools import m4b_maker


def test_natural_sort_orders_chapters_numerically():
    names = ["Chapter 10.mp3", "Chapter 2.mp3", "Chapter 1.mp3"]
    ordered = sorted(names, key=m4b_maker.natural_key)
    assert ordered == ["Chapter 1.mp3", "Chapter 2.mp3", "Chapter 10.mp3"]


def test_title_normalization():
    assert m4b_maker.strip_leading_numbers("01 - Intro") == "Intro"
    # Purely numeric stems fall back to themselves rather than emptying out.
    assert m4b_maker.strip_leading_numbers("42") == "42"
    # First underscore becomes a colon separator; possessive _s becomes ’s.
    assert m4b_maker.normalize_title("03 Book One_ The Beginning") == "Book One: The Beginning"
    # The first underscore becomes the colon; a later `_s` reads as a possessive.
    assert m4b_maker.compute_titles(["/x/01 Book_ A_s Tale.mp3"]) == ["Book: A’s Tale"]


def test_build_ffmetadata_chapters_are_well_formed():
    titles = ["One", "Two"]
    starts = [0, 60_000]
    total = 120_000
    text = m4b_maker.build_ffmetadata_from_starts(
        titles, starts, {"title": "Book", "artist": "Narrator"}, total
    )
    assert text.startswith(";FFMETADATA1")
    assert "title=Book" in text and "artist=Narrator" in text
    assert text.count("[CHAPTER]") == 2
    # Last chapter must end at total-1; every chapter >= 100 ms long.
    assert f"END={total - 1}" in text
    starts_found = [int(l.split("=")[1]) for l in text.splitlines() if l.startswith("START=")]
    ends_found = [int(l.split("=")[1]) for l in text.splitlines() if l.startswith("END=")]
    assert all(e - s >= 100 for s, e in zip(starts_found, ends_found))


def test_write_concat_list_quotes_apostrophes(tmp_path):
    dest = tmp_path / "list.txt"
    m4b_maker.write_concat_list([tmp_path / "it's.mp3"], dest)
    content = dest.read_text(encoding="utf-8")
    assert content.startswith("file '")
    assert "it" in content and content.endswith("'\n")
