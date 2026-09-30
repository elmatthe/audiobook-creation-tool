"""Edge sources without book content fail; local engines reject empty parsed text.

v0.6.6 Phase 10 defect. With nothing speakable in it, Edge's direct path
(``runner.run_conversion_job``, which Add Files items take) published a
0-second MP3 and reported success. That covers an empty ``.txt``, one with only
``Title:``/``Author:`` lines or only a ``#`` heading, and one with only
punctuation. Empty parsed text also fails on Kokoro and Chatterbox ("No text
content found after parsing source file."). Their heading/body parsing differs:
the local-engine test below proves the empty/header-only case, not rejection of
all four Edge inputs. Edge's direct path now fails before any synthesis or
network call, and writes nothing.
"""

from __future__ import annotations

import pytest

import tts.chatterbox_synth as cbx
import tts.kokoro_synth as ks
from tts.epub2tts_edge import epub2tts_edge as edge
from tts.epub2tts_edge import runner

NO_CONTENT = "No text content found after parsing source file."

CONTENTLESS = {
    "empty": "",
    "header_only": "Title: X\nAuthor: Y\n",
    "heading_only": "# Chapter 1\n",
    "punctuation_only": "# Ch\n\n... --- !!!\n",
}


@pytest.fixture(params=sorted(CONTENTLESS))
def contentless(request, tmp_path):
    path = tmp_path / f"{request.param}.txt"
    path.write_text(CONTENTLESS[request.param], encoding="utf-8")
    return path


def test_edge_direct_fails_the_item_and_writes_nothing(contentless, tmp_path, monkeypatch):
    edge.ensure_punkt()

    def no_synthesis(*_args, **_kwargs):
        raise AssertionError("nothing should be synthesized")

    monkeypatch.setattr(runner, "read_book", no_synthesis)
    out = tmp_path / "out"
    with pytest.raises(ValueError, match=NO_CONTENT):
        runner.run_conversion_job(str(contentless), output_dir=str(out), audio_format="mp3")
    assert not out.exists() or not any(out.iterdir())


def test_edge_direct_still_converts_a_one_sentence_book(tmp_path, monkeypatch):
    """The guard is on content, not on size: one real paragraph passes it."""
    edge.ensure_punkt()
    reached = []

    def stop_at_synthesis(book_contents, *_args, **_kwargs):
        reached.append(book_contents)
        raise RuntimeError("stop before the network")

    monkeypatch.setattr(runner, "read_book", stop_at_synthesis)
    source = tmp_path / "one.txt"
    source.write_text("# One\n\nHello there.\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="stop before the network"):
        runner.run_conversion_job(str(source), output_dir=str(tmp_path / "out"),
                                  audio_format="mp3")
    assert reached and reached[0][0]["paragraphs"] == ["Hello there."]


def test_kokoro_and_chatterbox_already_fail_an_empty_source(tmp_path):
    """The parity the Edge fix restores, pinned so the three stay aligned."""
    source = tmp_path / "empty.txt"
    source.write_text("Title: X\nAuthor: Y\n", encoding="utf-8")
    with pytest.raises(ValueError, match=NO_CONTENT):
        ks.kokoro_file_to_mp3(str(source), str(tmp_path / "k.mp3"), voice_id="af_heart",
                              log=lambda _m: None)
    with pytest.raises(ValueError, match=NO_CONTENT):
        cbx.chatterbox_file_to_mp3(str(source), str(tmp_path / "c.mp3"),
                                   voice_id=next(iter(cbx.REFERENCE_VOICES)),
                                   log=lambda _m: None)
