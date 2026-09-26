"""v0.6.5 Phase 4 — source-span coverage and false-boundary evidence.

Phase 4's charter (plan Section 7 / Section 15) is to *prove* that every
current segmentation path preserves its source text exactly (no omission,
duplication or reordering) and to document, mechanically, how each false-
boundary case (abbreviations, initials, decimals, times, ratios, URLs,
ellipses, dialogue closing punctuation, parentheticals) is actually handled
today. This file adds no dictionary replacement, no per-word pronunciation
hack and no special case keyed to any one exact string — every check here is
a structural property of the corpus text quality_corpus.py already carries,
never modified to make an example pass.

Two backends already had a runtime content-preservation guard before this
file existed: ``chatterbox_synth.split_for_chatterbox`` raises
``ChunkPlanError`` internally, and its own dedicated
``test_chatterbox_chunking.py`` already covers it with synthetic fixtures.
This file adds the same proof, against the real QA corpus text (not just
synthetic fixtures), for the two paths that previously had **no such guard
at all**: ``batch_convert.split_into_chunks`` (Edge folder/batch) and
``kokoro_synth.split_into_chunks`` (Kokoro) — plus the Edge direct/rich
path's own pipeline (NLTK ``sent_tokenize`` + ``intra_sentence_chunks``),
which is not a single function but the composition ``read_book`` actually
calls.

The NLTK/Punkt false-split section originally documented a **found, not
fixed** defect in the same spirit as the existing Ascended/Tamar Chatterbox
pronunciation guards (P9): evidence for a later phase's decision, not a
correctness assertion. **As of v0.6.5 Phase 6, the fix landed**: production's
``epub2tts_edge.sent_tokenize`` extends the stock tokenizer's own
``abbrev_types`` set with "i.e"/"e.g" (approved by the maintainer's Phase 5
iteration 2/4 verdict) and no longer false-splits at this boundary. The
section below is kept as a **stock-NLTK regression baseline** — it exercises
``nltk.tokenize.sent_tokenize`` directly, not production's own tokenizer, and
documents the behavior that motivated the fix. See
``test_edge_direct_pcm_assembly.py`` for tests against the integrated
production tokenizer.
"""

from __future__ import annotations

import nltk
import pytest
from nltk.tokenize import sent_tokenize

from tts import batch_convert
from tts import chatterbox_synth as cbx
from tts import kokoro_synth
from tts import quality_corpus as qc
from tts.epub2tts_edge.epub2tts_edge import intra_sentence_chunks


def _ensure_punkt() -> None:
    for resource in ("tokenizers/punkt", "tokenizers/punkt_tab"):
        try:
            nltk.data.find(resource)
        except LookupError:
            nltk.download(resource.split("/")[-1])


_ensure_punkt()


def squeeze(text: str) -> str:
    """Every non-whitespace character, in order. Whitespace is not content."""
    return "".join(text.split())


def edge_direct_units(text: str) -> list[str]:
    """A content-preservation baseline for the Edge direct/rich path's
    two-stage pipeline: sentence splitting, then ``intra_sentence_chunks``
    per sentence for the comma/ellipsis/dash intra-sentence sub-splits.

    Uses NLTK's stock ``sent_tokenize`` rather than ``read_book``'s own
    sentence tokenizer (as of v0.6.5 Phase 6, ``epub2tts_edge.sent_tokenize``
    -- the same Punkt model extended with "i.e"/"e.g" in its
    ``abbrev_types`` set; see ``test_edge_direct_pcm_assembly.py`` for the
    integrated production behavior). Content preservation (section A below)
    holds under either tokenizer, since resegmenting sentences never drops or
    duplicates characters -- this baseline is retained rather than switched,
    so this file's proof does not depend on the production tokenizer's
    current abbreviation set. Every corpus item here is a single physical
    line (no embedded ``\\n``), matching how ``get_book`` would hand each of
    them to ``read_book`` as one paragraph.
    """
    units: list[str] = []
    for sentence in sent_tokenize(text):
        for sub_text, _pause_ms in intra_sentence_chunks(sentence):
            units.append(sub_text)
    return units


# --------------------------------------------------------------------------- #
# A. Content preservation — no omission, duplication or reordering.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("item", qc.ALL_ITEMS, ids=lambda i: i.name)
def test_chatterbox_preserves_every_corpus_item(item):
    """Belt-and-suspenders on the real QA corpus; the engine's own assertion
    already enforces this in production (``ChunkPlanError``)."""
    chunks = cbx.split_for_chatterbox(item.text)
    assert squeeze("".join(chunks)) == squeeze(item.text)


@pytest.mark.parametrize("item", qc.ALL_ITEMS, ids=lambda i: i.name)
def test_edge_folder_batch_preserves_every_corpus_item(item):
    """``batch_convert.split_into_chunks`` had no content-preservation guard
    before this Phase 4 test — it is a plain character-window splitter with
    no runtime assertion of its own."""
    chunks = batch_convert.split_into_chunks(item.text)
    assert squeeze("".join(chunks)) == squeeze(item.text)


@pytest.mark.parametrize("item", qc.ALL_ITEMS, ids=lambda i: i.name)
def test_kokoro_preserves_every_corpus_item(item):
    """``kokoro_synth.split_into_chunks`` had no content-preservation guard
    before this Phase 4 test either."""
    chunks = kokoro_synth.split_into_chunks(item.text)
    assert squeeze("".join(chunks)) == squeeze(item.text)


@pytest.mark.parametrize("item", qc.ALL_ITEMS, ids=lambda i: i.name)
def test_edge_direct_rich_preserves_every_corpus_item(item):
    """The Edge direct/rich path's own two-stage pipeline (NLTK sent_tokenize
    then intra_sentence_chunks) had no content-preservation proof at all —
    it is not one function but a composition ``read_book`` performs inline."""
    units = edge_direct_units(item.text)
    assert squeeze("".join(units)) == squeeze(item.text)


# --------------------------------------------------------------------------- #
# B. False-boundary survival — Chatterbox's final chunks (plan Section 7).
# --------------------------------------------------------------------------- #

#: Every false-boundary case quality_corpus.DIFFICULT_SHORT was built to pack
#: into one paragraph (module docstring there). Each must land inside exactly
#: one final Chatterbox chunk — sentence-level over-splitting is harmless by
#: itself (packing rejoins consecutive units with a plain space, no pause),
#: but a marker split *across* two final chunks would insert an unwanted
#: chunk_pause_ms boundary in the middle of it.
FALSE_BOUNDARY_MARKERS = [
    pytest.param("Dr. Elena", id="title-abbreviation"),
    pytest.param("J. R. Alvarez", id="initials"),
    pytest.param("6:45", id="time-1"),
    pytest.param("7:15", id="time-2"),
    pytest.param("3:1", id="ratio"),
    pytest.param("2.5 degrees", id="decimal"),
    pytest.param("Mr. Okafor", id="title-mr"),
    pytest.param("Mrs. Yates", id="title-mrs"),
    pytest.param("i.e.", id="abbrev-ie"),
    pytest.param("e.g.", id="abbrev-eg"),
    pytest.param("vs.", id="abbrev-vs"),
    pytest.param("https://example.com/lighthouse-log", id="url"),
    pytest.param("aside...", id="ellipsis"),
]


@pytest.mark.parametrize("marker", FALSE_BOUNDARY_MARKERS)
def test_chatterbox_final_chunks_never_split_a_false_boundary_marker(marker):
    chunks = cbx.split_for_chatterbox(qc.DIFFICULT_SHORT.text)
    assert any(marker in chunk for chunk in chunks), (
        f"{marker!r} was split across a Chatterbox chunk boundary "
        f"(chunk_pause_ms would land inside it): {chunks!r}")


def test_chatterbox_prose_colon_does_not_split_a_time_or_ratio():
    """Times/ratios reach the model as one literal string — confirms the
    Phase 4 conclusion that any cross-voice reading inconsistency for them is
    model-native sampling, not a segmentation split (plan Section 7's colon
    rule: no whitespace after the colon in "6:45"/"3:1", so
    ``split_at_prose_colon`` never touches them)."""
    for marker in ("6:45", "7:15", "3:1"):
        segments = cbx.split_at_prose_colon(marker)
        assert segments == [marker], (
            f"{marker!r} was split by the prose-colon rule: {segments!r}")


def test_chatterbox_prose_colon_does_not_split_a_url():
    """The URL reaches the model as one literal string too — confirms the
    Phase 4 conclusion that any HTTPS-reading inconsistency is model-native,
    not a segmentation split (the colon in "https:" is followed by "//", not
    whitespace, so the prose-colon rule never touches it)."""
    url = "https://example.com/lighthouse-log"
    segments = cbx.split_at_prose_colon(url)
    assert segments == [url], f"the URL was split by the prose-colon rule: {segments!r}"


def test_edge_folder_batch_never_splits_at_a_false_boundary_marker():
    """A single-chunk regression: DIFFICULT_SHORT is well under Edge's
    ~3,000-char ceiling, so none of these markers should ever be cut."""
    chunks = batch_convert.split_into_chunks(qc.DIFFICULT_SHORT.text)
    assert len(chunks) == 1
    for marker in FALSE_BOUNDARY_MARKERS:
        assert marker.values[0] in chunks[0]


# --------------------------------------------------------------------------- #
# C. NLTK/Punkt sentence-boundary gap — found, not fixed (Phase 4 evidence).
# --------------------------------------------------------------------------- #


def test_nltk_sent_tokenize_currently_splits_mid_sentence_at_ie_and_eg():
    """**Documents NLTK's own stock behavior; no longer what production uses.**

    This asserts ``nltk.tokenize.sent_tokenize`` (the stock, unextended Punkt
    model) incorrectly treats "i.e." and "e.g." as sentence-ending
    abbreviations, splitting what is written as one continuous sentence into
    three NLTK "sentences". It originally documented a live defect: before
    v0.6.5 Phase 6, the Edge direct/rich path (``read_book``) called this
    exact stock function, so each false boundary earned an unwanted 800 ms
    ``sentencepause`` mid-sentence.

    **As of Phase 6, production no longer calls this stock function.**
    ``epub2tts_edge.sent_tokenize`` wraps the same Punkt model with "i.e"/
    "e.g" added to its ``abbrev_types`` set (approved by the maintainer's
    Phase 5 iteration 2/4 listening verdict) and no longer false-splits here
    -- see ``test_edge_direct_pcm_assembly.py`` for that integrated
    production behavior. This test is kept as a stock-NLTK regression
    baseline: it is what motivated the fix, not a description of current
    production behavior, and it is expected to keep passing regardless of
    this project's own tokenizer, since it exercises NLTK's unextended
    default. "vs." and every title abbreviation (Dr./Mr./Mrs./Prof.) are
    handled correctly and do NOT split, on both the stock and the extended
    tokenizer.
    """
    sentences = sent_tokenize(qc.DIFFICULT_SHORT.text)
    joined = " ".join(sentences)
    assert "Prof. Whitfield's theory, i.e." in joined  # split point 1 (found)
    assert sentences[4].endswith("i.e."), sentences[4]
    assert sentences[5].endswith("e.g."), sentences[5]
    # Confirmed NOT split at these — no false positive there today.
    assert "vs. gone out entirely." in sentences[6]
    assert sentences[0].startswith("Dr. Elena")
