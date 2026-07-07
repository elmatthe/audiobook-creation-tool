"""Behaviour preservation: MP3 Tool pure helpers (no ffmpeg spawned)."""

from __future__ import annotations

from pathlib import Path

from mp3_tools import mp3_tool


def test_seconds_to_hms_formats():
    assert mp3_tool.seconds_to_hms(0) == "00:00.000"
    assert mp3_tool.seconds_to_hms(61.5) == "01:01.500"
    assert mp3_tool.seconds_to_hms(3661.25) == "01:01:01.250"
    # Negative input clamps to zero rather than producing nonsense.
    assert mp3_tool.seconds_to_hms(-5) == "00:00.000"


def test_concat_listfile_escaping(tmp_path):
    tricky = tmp_path / "it's a song.mp3"
    line = mp3_tool.ffmpeg_escape_listfile_path(tricky)
    assert line.startswith("file '") and line.endswith("'")
    assert "\\'" in line  # apostrophe escaped for the concat demuxer

    listfile = tmp_path / "list.txt"
    mp3_tool.write_concat_listfile([tricky, tmp_path / "b.mp3"], listfile)
    content = listfile.read_text(encoding="utf-8")
    assert content.count("file '") == 2
    assert content.endswith("\n")


def test_next_available_folder_increments(tmp_path):
    base = tmp_path / "out"
    first = mp3_tool.next_available_folder(base)
    assert first == base and first.is_dir()
    second = mp3_tool.next_available_folder(base)
    assert second == Path(f"{base}-1") and second.is_dir()
