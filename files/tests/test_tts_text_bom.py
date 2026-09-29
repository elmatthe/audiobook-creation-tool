"""A UTF-8 byte-order mark must not change what the TTS engines read.

v0.6.6 Phase 10 defect. Windows writes a leading BOM (``EF BB BF``) for Notepad's
"UTF-8 with BOM" and PowerShell 5's ``Out-File -Encoding utf8``. Every direct-file
engine read ``.txt`` as plain ``utf-8``, which keeps the BOM as ``\\ufeff`` on the
first line. ``str.strip`` does not remove it, so the ``Title:`` / ``Author:`` / ``#``
prefix checks on that line all missed:

- **Edge** (``get_book``) spoke the ``Title:`` and ``Author:`` lines aloud as a
  paragraph, under an extra ``blank`` chapter, and lost the book's title and author.
- **Kokoro** and **Chatterbox** spoke the ``Title:`` line aloud.

A file without a BOM decodes byte-for-byte as before; ``utf-8-sig`` only drops a
leading BOM.
"""

from __future__ import annotations

import pytest

import tts.chatterbox_synth as cbx
import tts.kokoro_synth as ks
from tts.epub2tts_edge import epub2tts_edge as edge

BODY = "Title: My Book\nAuthor: Jane Doe\n\n# Chapter One\n\nIt was a dark night.\n"


def _write(tmp_path, name: str, encoding: str):
    path = tmp_path / f"{name}.txt"
    path.write_bytes(BODY.encode(encoding))
    return path


@pytest.fixture(params=("utf-8", "utf-8-sig"), ids=("plain", "bom"))
def source(request, tmp_path):
    return _write(tmp_path, request.param, request.param)


def test_the_fixture_really_carries_a_bom(tmp_path):
    assert _write(tmp_path, "bom", "utf-8-sig").read_bytes().startswith(b"\xef\xbb\xbf")


def test_edge_reads_the_header_and_chapters_the_same_with_or_without_a_bom(source):
    edge.ensure_punkt()
    contents, title, author, chapters = edge.get_book(str(source))
    assert (title, author) == ("My Book", "Jane Doe")
    assert chapters == ["Chapter One"]
    assert [c["paragraphs"] for c in contents] == [["It was a dark night."]]


class _Parsed(Exception):
    """Stops the engine once it has handed its parsed text to the splitter."""


def _captured_text(monkeypatch, module, splitter: str, run) -> str:
    seen: list[str] = []

    def capture(text, *args, **kwargs):
        seen.append(text)
        raise _Parsed

    monkeypatch.setattr(module, splitter, capture)
    with pytest.raises(_Parsed):
        run()
    return seen[0]


def test_kokoro_skips_the_header_with_or_without_a_bom(source, tmp_path, monkeypatch):
    text = _captured_text(
        monkeypatch, ks, "split_into_chunks",
        lambda: ks.kokoro_file_to_mp3(str(source), str(tmp_path / "out.mp3"),
                                      voice_id="af_heart", log=lambda _m: None))
    assert text == "Chapter One\n\nIt was a dark night."


def test_chatterbox_skips_the_header_with_or_without_a_bom(source, tmp_path, monkeypatch):
    text = _captured_text(
        monkeypatch, cbx, "split_for_chatterbox",
        lambda: cbx.chatterbox_file_to_mp3(str(source), str(tmp_path / "out.mp3"),
                                           voice_id=next(iter(cbx.REFERENCE_VOICES)),
                                           log=lambda _m: None))
    assert text == "Chapter One\n\nIt was a dark night."
