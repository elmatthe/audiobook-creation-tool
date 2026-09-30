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


# --------------------------------------------------------------------------- #
# v0.6.6 Phase 11: the Edge *folder* path, and the documented TXT contract
# --------------------------------------------------------------------------- #
#
# The supported ``.txt`` encodings are UTF-8 and UTF-8 with a BOM (maintainer
# ruling, 2026-09-29; broader encodings are deferred to v0.6.7). Phase 10 fixed
# the three direct-file engines; a folder-derived Edge item goes through
# ``batch_convert.convert_single_pdf`` instead, which still read plain ``utf-8``
# and sent the BOM to Edge as the first character of the first chunk -- and a
# BOM-only file became one ``"\ufeff"`` chunk instead of "no text".

import tts.batch_convert as bc  # noqa: E402


def _run_folder_path(monkeypatch, tmp_path, source):
    spoken: list[str] = []

    def synth(text, path, voice, rate):
        spoken.append(text)
        with open(path, "wb") as fh:
            fh.write(b"\x00")

    def merge(chunk_paths, out, bitrate=None):
        with open(out, "wb") as fh:
            fh.write(b"\x00")

    monkeypatch.setattr(bc, "synthesize_chunk_mp3", synth)
    monkeypatch.setattr(bc, "merge_mp3s", merge)
    monkeypatch.setattr(bc, "INTER_CHUNK_DELAY_SEC", 0)
    monkeypatch.setattr(bc.time, "sleep", lambda _s: None)
    status, _path, message = bc.convert_single_pdf(
        source, tmp_path / "run", "en-US-AriaNeural", "+0%", log=lambda _m: None)
    return status, message, spoken


def test_the_edge_folder_path_speaks_the_same_text_with_or_without_a_bom(
        source, tmp_path, monkeypatch):
    status, _message, spoken = _run_folder_path(monkeypatch, tmp_path, source)
    assert status == "success"
    assert spoken == [BODY.strip()]
    assert not any("\ufeff" in chunk for chunk in spoken)


def test_a_bom_only_file_on_the_edge_folder_path_is_no_text(tmp_path, monkeypatch):
    source = tmp_path / "empty.txt"
    source.write_bytes(b"\xef\xbb\xbf\r\n")
    status, message, spoken = _run_folder_path(monkeypatch, tmp_path, source)
    assert spoken == []
    assert status == "failed"
    assert "No text chunks" in message


CP1252 = "Title: Caf\u00e9\n\n# Chapter One\n\nNa\u00efve r\u00e9sum\u00e9.\n".encode("cp1252")


def test_a_non_utf8_txt_is_refused_on_every_read_path_never_misread(tmp_path, monkeypatch):
    """The documented limitation, pinned: an "ANSI"/cp1252 file with non-ASCII
    bytes fails its item; no path guesses an encoding and speaks mojibake."""
    source = tmp_path / "ansi.txt"
    source.write_bytes(CP1252)
    with pytest.raises(UnicodeDecodeError):
        edge.get_book(str(source))
    with pytest.raises(UnicodeDecodeError):
        ks.kokoro_file_to_mp3(str(source), str(tmp_path / "k.mp3"),
                              voice_id="af_heart", log=lambda _m: None)
    with pytest.raises(UnicodeDecodeError):
        cbx.chatterbox_file_to_mp3(str(source), str(tmp_path / "c.mp3"),
                                   voice_id=next(iter(cbx.REFERENCE_VOICES)),
                                   log=lambda _m: None)
    status, message, spoken = _run_folder_path(monkeypatch, tmp_path, source)
    assert (status, spoken) == ("failed", [])
    assert "UnicodeDecodeError" in message
