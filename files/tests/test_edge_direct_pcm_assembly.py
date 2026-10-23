"""v0.6.5 Phase 6 — Edge direct/rich path audio-quality integration.

Two Phase 5 candidates were approved by the maintainer's listening verdicts
(``md-instructions/Decisions.md``, 2026-09-21 entries) and are integrated by
this drop:

1. **PCM-domain assembly** (iteration 1/4): trim/intra-pause/sentence-pause
   work for ``read_book``'s per-sentence/per-sub-chunk audio now stays in
   memory as pydub ``AudioSegment`` objects from the raw Edge network bytes
   all the way to each paragraph's own (already-lossless) FLAC export --
   before this integration, every multi-sub sentence round-tripped through
   3-5 avoidable lossy MP3 re-encodes (trim, intra-pause, sub-merge,
   sentence/paragraph pause) first.
2. **NLTK/Punkt ``abbrev_types`` extension** (iteration 2/4): "i.e"/"e.g"
   added to the tokenizer's own abbreviation set, fixing a false
   sentence-boundary split that inserted an unwanted mid-sentence pause.

These tests exercise ``epub2tts_edge.read_book``/``sent_tokenize`` directly
with a stubbed ``run_edgespeak`` (no network) -- network-independent, per
this project's own Edge-test mocking convention.
"""

from __future__ import annotations

import io
from pathlib import Path

import nltk
import pytest
from pydub import AudioSegment

from shared import ffmpeg_utils
from tts import quality_corpus as qc
from tts.epub2tts_edge import epub2tts_edge as engine


def _ensure_punkt() -> None:
    for resource in ("tokenizers/punkt", "tokenizers/punkt_tab"):
        try:
            nltk.data.find(resource)
        except LookupError:
            nltk.download(resource.split("/")[-1])


_ensure_punkt()


@pytest.fixture(autouse=True)
def _reset_sentence_tokenizer_cache(monkeypatch):
    """Every test starts from a clean cache, so mutating/inspecting the
    tokenizer in one test cannot leak into another."""
    monkeypatch.setattr(engine, "_SENTENCE_TOKENIZER", None, raising=False)


def _squeeze(text: str) -> str:
    return "".join(text.split())


# --------------------------------------------------------------------------- #
# A. PCM-domain assembly -- no avoidable intermediate MP3 encode
# --------------------------------------------------------------------------- #

pytestmark_ffmpeg = pytest.mark.skipif(
    not ffmpeg_utils.have_ffmpeg(), reason="requires a real ffmpeg/ffprobe pair"
)


def _stub_mp3_bytes() -> bytes:
    """A short, real, decodable MP3 standing in for Edge's network audio.

    Built with the real (not-yet-monkeypatched) ``AudioSegment.export`` --
    callers that go on to monkeypatch ``export`` to count calls must build
    this first, so building the stub is never itself counted.
    """
    buf = io.BytesIO()
    AudioSegment.silent(duration=120).export(buf, format="mp3")
    return buf.getvalue()


@pytestmark_ffmpeg
def test_read_book_performs_no_intermediate_mp3_encode(monkeypatch, tmp_path):
    ffmpeg_utils.configure_pydub()
    stub_bytes = _stub_mp3_bytes()

    def fake_run_edgespeak(sentence, speaker, filename):
        Path(filename).write_bytes(stub_bytes)

    monkeypatch.setattr(engine, "run_edgespeak", fake_run_edgespeak)

    export_calls: list[str] = []
    real_export = AudioSegment.export

    def counting_export(self, out_f=None, format="mp3", **kwargs):
        export_calls.append(format)
        return real_export(self, out_f, format=format, **kwargs)

    monkeypatch.setattr(AudioSegment, "export", counting_export)
    monkeypatch.chdir(tmp_path)

    book_contents = [{
        "title": "blank",
        "paragraphs": [
            "This is one sentence, with a comma pause, and another clause. "
            "Here is a second sentence for the pause boundary."
        ],
    }]
    files = engine.read_book(book_contents, "en-US-SteffanNeural", 850, 800)

    assert files == ["part1.flac"]
    assert "mp3" not in export_calls, (
        f"read_book performed an avoidable intermediate MP3 encode: {export_calls}")
    assert export_calls.count("flac") >= 1


@pytestmark_ffmpeg
def test_read_book_output_is_still_a_valid_decodable_file(monkeypatch, tmp_path):
    ffmpeg_utils.configure_pydub()
    stub_bytes = _stub_mp3_bytes()

    def fake_run_edgespeak(sentence, speaker, filename):
        Path(filename).write_bytes(stub_bytes)

    monkeypatch.setattr(engine, "run_edgespeak", fake_run_edgespeak)
    monkeypatch.chdir(tmp_path)

    book_contents = [{
        "title": "blank",
        "paragraphs": ["A short paragraph with one plain sentence."],
    }]
    files = engine.read_book(book_contents, "en-US-SteffanNeural", 850, 800)
    produced = Path(files[0])
    assert produced.is_file()
    seg = AudioSegment.from_file(produced)
    assert len(seg) > 0


def _stub_frames(stub_bytes: bytes) -> tuple[int, int]:
    """(frames, frame rate) of one decoded stub sentence, the unit every expectation below counts in."""
    stub = AudioSegment.from_file(io.BytesIO(stub_bytes))
    return int(stub.frame_count()), stub.frame_rate


def _silence_frames(ms: int, rate: int) -> int:
    return int(AudioSegment.silent(duration=ms, frame_rate=rate).frame_count())


@pytestmark_ffmpeg
def test_read_book_still_applies_the_configured_pause_values(monkeypatch, tmp_path):
    """The configured pause still separates two rendered paragraphs, frame for frame.

    v0.7.0 P01C (Q1) replaced the v0.6.5 single-sentence check, which expected the
    paragraph pause *after* the book's only sentence: that closing pause is exactly
    what Q1 removed. An explicit end-of-book pause is still accepted and adds
    nothing. Phase 5's own evidence (Decisions.md, 2026-09-21) measured the
    in-memory assembly against the old one on real network audio.
    """
    ffmpeg_utils.configure_pydub()
    stub_bytes = _stub_mp3_bytes()
    stub, rate = _stub_frames(stub_bytes)

    def fake_run_edgespeak(sentence, speaker, filename):
        Path(filename).write_bytes(stub_bytes)

    monkeypatch.setattr(engine, "run_edgespeak", fake_run_edgespeak)
    monkeypatch.chdir(tmp_path)

    book_contents = [{
        "title": "blank",
        "paragraphs": ["One sentence only in this paragraph.", "A second paragraph ends the book."],
    }]
    files = engine.read_book(
        book_contents, "en-US-SteffanNeural",
        paragraphpause=850, sentencepause=800, trim_tts_padding=False,
        chapter_trailing_pause=0, end_of_book_pause=3000,
    )
    seg = AudioSegment.from_file(files[0])
    # sentence, the 850 ms paragraph pause, the final sentence -- and nothing after it
    # (v0.6.6: another 850 ms paragraph pause plus the 3000 ms end-of-book pause).
    assert int(seg.frame_count()) == 2 * stub + _silence_frames(850, rate)


@pytestmark_ffmpeg
def test_the_chapter_pause_separates_chapters_and_nothing_follows_the_last(monkeypatch, tmp_path):
    """v0.7.0 P01C (Q1): the chapter pause stays between chapters; the final chapter ends with its last word."""
    ffmpeg_utils.configure_pydub()
    stub_bytes = _stub_mp3_bytes()
    stub, rate = _stub_frames(stub_bytes)

    def fake_run_edgespeak(sentence, speaker, filename):
        Path(filename).write_bytes(stub_bytes)

    monkeypatch.setattr(engine, "run_edgespeak", fake_run_edgespeak)
    monkeypatch.chdir(tmp_path)

    book_contents = [{"title": "blank", "paragraphs": ["Chapter one has one sentence."]},
                     {"title": "blank", "paragraphs": ["Chapter two ends the book."]}]
    files = engine.read_book(
        book_contents, "en-US-SteffanNeural",
        paragraphpause=850, sentencepause=800, trim_tts_padding=False,
        chapter_trailing_pause=2000, end_of_book_pause=3000,
    )
    first, last = (int(AudioSegment.from_file(f).frame_count()) for f in files)
    assert first == stub + _silence_frames(850, rate) + _silence_frames(2000, rate)
    assert last == stub  # v0.6.6: + 850 paragraph + 2000 chapter + 3000 end of book


# --------------------------------------------------------------------------- #
# B. NLTK/Punkt abbrev_types extension -- the i.e./e.g. false-split fix
# --------------------------------------------------------------------------- #


def test_production_sentence_tokenizer_no_longer_splits_at_ie_or_eg():
    sentences = engine.sent_tokenize(qc.DIFFICULT_SHORT.text)
    for marker in ("i.e.", "e.g."):
        hits = [s for s in sentences if s.rstrip().endswith(marker)]
        assert not hits, f"false boundary at {marker!r} was not fixed: {hits!r}"


def test_production_sentence_tokenizer_does_not_regress_any_other_marker():
    """Every other false-boundary case in the same corpus item must still be
    handled exactly as before -- this is an abbreviation-set addition, not a
    different tokenizer."""
    sentences = engine.sent_tokenize(qc.DIFFICULT_SHORT.text)
    joined = " ".join(sentences)
    for marker in (
        "Dr. Elena", "Mr. Okafor", "Mrs. Yates", "Prof. Whitfield",
        "J. R. Alvarez", "vs. gone out entirely",
    ):
        assert marker in joined, f"{marker!r} regressed: {sentences!r}"


def test_production_sentence_tokenizer_preserves_every_character():
    sentences = engine.sent_tokenize(qc.DIFFICULT_SHORT.text)
    assert _squeeze("".join(sentences)) == _squeeze(qc.DIFFICULT_SHORT.text)


def test_production_tokenizer_does_not_mutate_nltks_own_shared_tokenizer():
    """The candidate must be a deep copy, not an in-place mutation of NLTK's
    own cached Punkt tokenizer -- otherwise this fix would silently change
    the abbreviation set for every other caller of
    ``nltk.tokenize.sent_tokenize`` in the same process."""
    from nltk.tokenize import sent_tokenize as stock_sent_tokenize

    probe = "Prof. Whitfield's theory, i.e. two turns."
    engine.sent_tokenize(probe)  # builds/caches this module's own tokenizer
    stock_sentences = stock_sent_tokenize(probe)
    assert any(s.rstrip().endswith("i.e.") for s in stock_sentences), (
        "NLTK's own stock sent_tokenize was affected by this module's "
        "abbrev_types extension -- the tokenizer was mutated in place "
        "rather than deep-copied")
