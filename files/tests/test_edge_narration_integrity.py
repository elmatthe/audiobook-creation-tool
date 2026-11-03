"""v0.7.1 — every word the author wrote reaches Edge, and the "blank" placeholder is an identity, not a word.

The direct Edge engine names a chapter that has no heading of its own ``"blank"`` (a placeholder kept for M4B chapter
metadata). Until v0.7.1 ``read_book`` decided whether to speak a chapter's title by comparing its *text* with
``"blank"``/``"Title"``, so an author's own ``# blank`` or ``# Title`` heading was silently dropped, and of two
consecutive headings the first was dropped. Ordinary sentences were never filtered and must stay that way.

These tests run the real ``get_book`` (decode, speech preparation, structure, sentence splitting) and ``read_book``
(chunking, pauses, assembly) and record the exact text of every request sent to Edge; the network call alone is
replaced. No word is suppressed anywhere: what the author wrote is what is sent, in order.
"""

from __future__ import annotations

import io
import re
from contextlib import redirect_stdout
from pathlib import Path

import pytest
from pydub.generators import Sine

from shared import ffmpeg_utils
from tts.epub2tts_edge import epub2tts_edge as engine

pytestmark = pytest.mark.skipif(not ffmpeg_utils.have_ffmpeg(), reason="requires a real ffmpeg/ffprobe pair")

MANDATORY = [
    "She had a blank expression on her face.",
    "The page was completely blank.",
    "He drew a blank when asked the question.",
    "Blank pages fluttered in the wind.",
    "The blank expression disappeared when she recognized him.",
]

_CLIP: dict[str, bytes] = {}


def _clip() -> bytes:
    if "mp3" not in _CLIP:
        ffmpeg_utils.configure_pydub()
        buf = io.BytesIO()
        Sine(440, sample_rate=24000).to_audio_segment(duration=60, volume=-20).export(buf, format="mp3")
        _CLIP["mp3"] = buf.getvalue()
    return _CLIP["mp3"]


@pytest.fixture(autouse=True)
def _clean_tokenizer(monkeypatch):
    monkeypatch.setattr(engine, "_SENTENCE_TOKENIZER", None, raising=False)


def narrate(tmp_path: Path, monkeypatch, text: str):
    """Run the real parse + narration; return (texts sent to Edge, chapters, metadata titles, engine output)."""
    sent: list[str] = []

    def request(sentence, speaker, filename):
        sent.append(sentence)
        Path(filename).write_bytes(_clip())

    monkeypatch.setattr(engine, "run_edgespeak", request)
    source = tmp_path / "source.txt"
    source.write_text(text, encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    out = io.StringIO()
    with redirect_stdout(out):
        chapters, _title, _author, metadata = engine.get_book(str(source))
        engine.read_book(chapters, "en-US-SteffanNeural", 850, 800, workdir=str(work))
    return sent, chapters, metadata, out.getvalue()


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


# --------------------------------------------------------------------------- #
# Ordinary narration keeps every "blank"
# --------------------------------------------------------------------------- #


def test_the_five_mandatory_sentences_are_sent_exactly(tmp_path, monkeypatch):
    sent, _chapters, _meta, _out = narrate(tmp_path, monkeypatch, "\n\n".join(MANDATORY) + "\n")
    assert sent == MANDATORY
    assert sum(words(s).count("blank") for s in sent) == 5


def test_blank_inside_one_paragraph_of_several_sentences_is_kept(tmp_path, monkeypatch):
    sent, _c, _m, _o = narrate(tmp_path, monkeypatch, " ".join(MANDATORY) + "\n")
    assert sent == MANDATORY


# --------------------------------------------------------------------------- #
# Headings: author-written headings are spoken, by identity, whatever they say
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("heading", ["Blank", "blank", "BLANK", "Title", "title"])
def test_an_author_heading_is_spoken_whatever_its_text(tmp_path, monkeypatch, heading):
    sent, chapters, metadata, _out = narrate(tmp_path, monkeypatch, f"# {heading}\n\n{MANDATORY[0]}\n")
    assert sent == [heading, MANDATORY[0]]
    assert chapters[0]["narrate_title"] is True
    assert metadata == [heading]


def test_text_before_any_heading_has_no_spoken_title(tmp_path, monkeypatch):
    sent, chapters, metadata, out = narrate(tmp_path, monkeypatch, f"{MANDATORY[1]}\n")
    assert sent == [MANDATORY[1]]
    assert chapters[0]["narrate_title"] is False
    assert metadata == ["blank"], "the placeholder still names the chapter for M4B metadata"
    assert 'The word "blank" will not be read' not in out
    assert "no heading" in out


@pytest.mark.parametrize("decoration", ["#", "# ***", "#  —  "])
def test_a_heading_with_nothing_speakable_adds_nothing(tmp_path, monkeypatch, decoration):
    sent, chapters, _m, _o = narrate(tmp_path, monkeypatch, f"{decoration}\n{MANDATORY[2]}\n")
    assert sent == [MANDATORY[2]]
    assert chapters[0]["narrate_title"] is False


def test_a_final_heading_with_nothing_after_it_is_not_spoken(tmp_path, monkeypatch):
    """A characterization of inherited behaviour, not an endorsement (independent review, INFORMATIONAL-004).

    A chapter exists only once a paragraph follows its heading, so a last heading with no text is dropped from the
    audio. The word is in the source and is not spoken. It is pinned here so a change to it is a decision, not an
    accident: changing what a heading narrates needs the owner's authorization. Its title stays in the M4B title list,
    where nothing reads it, because each chapter reads its own title by position.
    """
    sent, chapters, metadata, _out = narrate(tmp_path, monkeypatch, "# First\nBody text.\n# Last\n")
    assert sent == ["First", "Body text."]
    assert [chapter["title"] for chapter in chapters] == ["First"]
    assert metadata == ["First", "Last"]


def test_a_source_of_nothing_but_headings_has_no_chapters_and_so_is_refused(tmp_path, monkeypatch):
    """The same rule from the other side: the runner fails such a file ("No text content"), as it always has."""
    _sent, chapters, metadata, _out = narrate(tmp_path, monkeypatch, "# Only\n# Headings\n")
    assert chapters == []
    assert metadata == ["Only. Headings"]


def test_two_consecutive_headings_are_both_spoken(tmp_path, monkeypatch):
    sent, chapters, metadata, _o = narrate(tmp_path, monkeypatch, "# Part One\n# Chapter 1\nThe road begins.\n")
    assert sent[0] == "Part One. Chapter 1"
    assert sent[1:] == ["The road begins."]
    assert len(chapters) == 1 and metadata == ["Part One. Chapter 1"], "one chapter, one metadata title"


def test_a_heading_ending_in_punctuation_joins_without_an_extra_stop(tmp_path, monkeypatch):
    sent, _c, _m, _o = narrate(tmp_path, monkeypatch, "# Book Two:\n# The Ember Gate\nIt opened.\n")
    assert sent[0] == "Book Two: The Ember Gate"


def test_a_decorative_heading_after_a_real_one_keeps_the_real_one(tmp_path, monkeypatch):
    sent, _c, metadata, _o = narrate(tmp_path, monkeypatch, "# Chapter Nine\n# ***\nRain fell.\n")
    assert sent == ["Chapter Nine", "Rain fell."]
    assert metadata == ["Chapter Nine"]


def test_a_real_heading_after_a_decorative_one_is_spoken_alone(tmp_path, monkeypatch):
    sent, _c, metadata, _o = narrate(tmp_path, monkeypatch, "# ***\n# Chapter Ten\nWind rose.\n")
    assert sent == ["Chapter Ten", "Wind rose."]
    assert metadata == ["Chapter Ten"]


# --------------------------------------------------------------------------- #
# The whole narration, word for word, for a mixed document
# --------------------------------------------------------------------------- #


MIXED = (
    "Title: The Thornwild Ledger\nAuthor: Nobody\n\n"
    "Kaelith stared at the blank map. Nothing on it moved.\n\n"
    "# Blank\n\n" + "\n\n".join(MANDATORY) + "\n\n"
    "# blank\n\nA second chapter, named by its author, begins here.\n\n"
    "# Part Two\n# The Return\n\n\"Is the page still blank?\" asked Serin. \"Yes!\"\n"
)


def test_a_mixed_document_reaches_edge_word_for_word_in_order(tmp_path, monkeypatch):
    sent, chapters, metadata, _o = narrate(tmp_path, monkeypatch, MIXED)
    body = "\n".join(line.lstrip("#").strip() for line in MIXED.splitlines()[3:])
    assert words(" ".join(sent)) == words(body), "nothing omitted, nothing duplicated, nothing reordered"
    assert sum(words(s).count("blank") for s in sent) == words(body).count("blank") == 9
    assert [c["narrate_title"] for c in chapters] == [False, True, True, True]
    assert metadata == ["blank", "Blank", "blank", "Part Two. The Return"]


# --------------------------------------------------------------------------- #
# Older callers that build chapter dicts themselves keep their behaviour
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("title,spoken", [("blank", False), ("Title", False), ("", False), ("Chapter", True)])
def test_a_chapter_without_the_flag_keeps_the_historical_rule(tmp_path, monkeypatch, title, spoken):
    sent: list[str] = []

    def request(sentence, speaker, filename):
        sent.append(sentence)
        Path(filename).write_bytes(_clip())

    monkeypatch.setattr(engine, "run_edgespeak", request)
    with redirect_stdout(io.StringIO()):
        engine.read_book([{"title": title, "paragraphs": ["One line."]}], "en-US-SteffanNeural", 850, 800,
                         workdir=str(tmp_path))
    assert sent == ([title] if spoken else []) + ["One line."]
