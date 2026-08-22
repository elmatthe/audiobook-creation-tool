"""v0.6.1 Plan 4 Phase 12 — natural text-chunk boundaries for Chatterbox.

The defect these tests exist for
--------------------------------

A real chapter narrated by ``Chatterbox - Male 1`` contained an **8.73-second**
silence at 2:36.9, and five more between 2.2 s and 2.5 s. Measurement of the file
showed every configured pause was correct — the 25 inter-chunk gaps were the
configured 700 ms and the terminal gap was the configured end silence — and that
*none* of the long silences sat at a chunk join. They were all inside a single
``model.generate()`` call.

The cause was a sentence-boundary blind spot. The old ``_SENTENCE_END`` was
``(?<=[.!?])\\s+``: the character immediately before the whitespace had to be a
terminator. Dialogue does not look like that. A spoken line ends ``."`` / ``?"`` /
``!"`` — the **closing quote comes after the terminator** — so a line break
following dialogue was neither a sentence boundary nor (single ``\\n``) a paragraph
boundary, and it survived into the string handed to the model. Chatterbox renders an
embedded newline as a pause of no fixed length.

What these tests hold the implementation to
-------------------------------------------

1. **The newline contract.** No raw structural newline reaches ``model.generate()``.
   A line break after a completed sentence becomes a boundary; a line break inside a
   continuing sentence becomes an ordinary space. Neither survives as a literal
   ``\\n``.
2. **Natural boundaries, in priority order** — paragraph, sentence, clause,
   whitespace, hard limit — descending only as far as the ceiling forces.
3. **Packing, not fragmenting.** Consecutive units are packed up to the ceiling, so
   one sentence does **not** become one chunk. Making every sentence its own chunk
   would insert a configured pause after every sentence and read as machine-gun
   narration.
4. **Content integrity.** Nothing lost, nothing duplicated, order unchanged — the
   invariant borrowed in principle (not in code) from the Web Novel Editor's
   ``ai/chunking.py``, which refuses to return a plan that cannot rebuild its input.

Nothing here contains chapter text from the maintainer's sources. Every fixture is
synthetic prose written for this file.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent
                       / "scripts" / "Universal"))

from tts import chatterbox_synth as cbx  # noqa: E402

CEILING = cbx.CHATTERBOX_MAX_CHUNK_CHARS


def plan(text: str) -> list[str]:
    return cbx.split_for_chatterbox(text)


def generated_segments(text: str) -> list[str]:
    """Exactly the strings production would hand to ``model.generate()``.

    ``_synthesize_chunk`` splits a chunk again at prose colons, so the real model
    input is the colon segments of each chunk — not the chunks themselves.
    """
    return [segment for chunk in plan(text)
            for segment in cbx.split_at_prose_colon(chunk)]


def squeeze(text: str) -> str:
    """Every non-whitespace character, in order. Whitespace is not content."""
    return "".join(text.split())


# --------------------------------------------------------------------------- #
# A. The newline contract — the actual defect
# --------------------------------------------------------------------------- #
DIALOGUE_FORMS = [
    pytest.param('"Something happened."', id="straight-double-period"),
    pytest.param('"Really?"', id="straight-double-question"),
    pytest.param('"Stop!"', id="straight-double-exclamation"),
    pytest.param("“Something happened.”", id="curly-double"),
    pytest.param("‘Really?’", id="curly-single"),
    pytest.param("'Stop!'", id="straight-single"),
    pytest.param("(Something happened.)", id="parenthesised"),
]


@pytest.mark.parametrize("line", DIALOGUE_FORMS)
def test_a_line_break_after_quoted_dialogue_never_reaches_the_model(line):
    """The exact defect: `."` + newline used to survive into generate()."""
    text = f"{line}\nMorrow glanced at him and said nothing."
    assert not any("\n" in segment for segment in generated_segments(text))


@pytest.mark.parametrize("line", DIALOGUE_FORMS)
def test_quoted_dialogue_followed_by_a_line_break_is_a_completed_sentence(line):
    text = f"{line}\nMorrow glanced at him and said nothing."
    chunks = plan(text)
    assert len(chunks) == 1, "both lines fit; they belong in one chunk"
    assert "\n" not in chunks[0]
    assert line in chunks[0]


def test_several_dialogue_lines_separated_by_single_newlines_carry_no_newline():
    text = ('"Well, I will be going, then."\n'
            '"Go."\n'
            '"Are you certain about that?"\n'
            "The thrall was of no use to her anymore.")
    assert not any("\n" in segment for segment in generated_segments(text))


def test_a_line_break_inside_one_continuing_sentence_becomes_a_space():
    """A layout wrap is formatting, not an instruction to the model."""
    text = ("The lantern guttered once and then\n"
            "went out completely in the draught.")
    chunks = plan(text)
    assert chunks == ["The lantern guttered once and then went out "
                      "completely in the draught."]


def test_no_raw_newline_survives_a_long_mixed_passage():
    text = "\n\n".join(
        f'Paragraph {n} opened quietly.\n"Line {n} of dialogue."\n'
        f"A narrator sentence closed it out."
        for n in range(30))
    segments = generated_segments(text)
    assert segments, "fixture must produce work"
    assert not any("\n" in segment or "\r" in segment for segment in segments)


def test_the_invariant_holds_for_every_terminator_and_closer_combination():
    closers = ["", '"', "'", "’", "”", ")", "]", '"’']
    for terminator in ".!?":
        for closer in closers:
            text = f"She spoke{terminator}{closer}\nThen she left."
            assert not any("\n" in s for s in generated_segments(text)), (
                f"newline survived for {terminator!r} + {closer!r}")


# --------------------------------------------------------------------------- #
# B. Packing — units, not one-sentence-per-chunk
# --------------------------------------------------------------------------- #
def test_a_short_sentence_is_never_split_for_no_reason():
    text = "The gate stood open."
    assert plan(text) == [text]


def test_short_consecutive_sentences_are_packed_into_one_chunk():
    text = ("One sentence here. Two sentences here. Three sentences here. "
            "Four sentences here.")
    assert plan(text) == [text]


def test_short_dialogue_lines_are_packed_rather_than_one_chunk_each():
    """The anti-machine-gun test: dialogue must not become one chunk per line."""
    text = '"Yes."\n"No."\n"Perhaps."\n"Certainly not."\n"We shall see."'
    chunks = plan(text)
    assert len(chunks) == 1, f"expected packing, got {len(chunks)} chunks"


def test_a_paragraph_of_short_sentences_splits_only_between_whole_sentences():
    sentence = "The corridor turned left and then it turned right again. "
    text = (sentence * 12).strip()
    chunks = plan(text)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.endswith("."), chunk
        assert len(chunk) <= CEILING


def test_packing_fills_the_ceiling_rather_than_stopping_early():
    """A chunk must not be left far short while the next unit would have fit."""
    sentence = "Alpha beta gamma delta epsilon zeta eta theta. "
    text = (sentence * 20).strip()
    chunks = plan(text)
    unit = len(sentence)
    for chunk in chunks[:-1]:
        assert len(chunk) + unit > CEILING, (
            f"chunk of {len(chunk)} chars stopped early under a {CEILING} ceiling")


# --------------------------------------------------------------------------- #
# C. The hierarchy — paragraph, sentence, clause, whitespace, hard limit
# --------------------------------------------------------------------------- #
def test_paragraphs_that_would_fit_together_are_still_kept_apart():
    a = "Alpha sentence one. Alpha sentence two."
    b = "Beta sentence one. Beta sentence two."
    chunks = plan(f"{a}\n\n{b}")
    assert not any("Alpha" in c and "Beta" in c for c in chunks)


def test_paragraph_order_is_preserved():
    text = "\n\n".join(f"Paragraph {n} said its piece." for n in range(40))
    chunks = plan(text)
    seen = [int(m.group(1))
            for c in chunks for m in re.finditer(r"Paragraph (\d+)", c)]
    assert seen == list(range(40))


def test_an_oversized_sentence_prefers_a_semicolon_to_a_comma():
    left = "The first clause runs on for a while " + "and on " * 20
    right = "the second clause also runs on for a while " + "and on " * 20
    chunks = plan(f"{left.strip()}; {right.strip()}.")
    assert len(chunks) > 1
    assert chunks[0].endswith(";"), chunks[0]


def test_an_oversized_sentence_falls_back_to_commas_when_there_is_nothing_better():
    piece = "a stretch of words that simply keeps going onward " * 3
    chunks = plan(f"{piece.strip()}, {piece.strip()}, {piece.strip()}.")
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= CEILING


def test_a_single_clauseless_sentence_falls_back_to_whitespace():
    text = " ".join(["word"] * 400) + "."
    chunks = plan(text)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= CEILING
        assert not chunk.startswith(" ") and not chunk.endswith(" ")


def test_a_pathological_token_still_obeys_the_ceiling_and_loses_nothing():
    blob = "x" * 2500
    chunks = plan(blob)
    for chunk in chunks:
        assert len(chunk) <= CEILING
    assert "".join(chunks) == blob


def test_a_word_is_never_split_when_a_whitespace_boundary_exists():
    words = ["consequential"] * 200
    for chunk in plan(" ".join(words) + "."):
        for token in chunk.split():
            assert token.rstrip(".") == "consequential", token


def test_every_chunk_respects_the_production_ceiling():
    text = "\n\n".join(
        " ".join(f"Sentence {i} of paragraph {p} carries some weight."
                 for i in range(25))
        for p in range(12))
    for chunk in plan(text):
        assert len(chunk) <= CEILING, f"{len(chunk)} > {CEILING}"


# --------------------------------------------------------------------------- #
# D. Content integrity — nothing lost, duplicated or reordered
# --------------------------------------------------------------------------- #
INTEGRITY_CASES = [
    pytest.param('"Go."\nHe went.', id="dialogue"),
    pytest.param("First.\n\nSecond.\n\n\nThird.", id="paragraphs"),
    pytest.param("Wait... what happened here...?", id="ellipses"),
    pytest.param("Warning: the gate is closed.", id="colon"),
    pytest.param("  leading and trailing  \n\n  spaces  ", id="stray-space"),
    pytest.param("A’s reply was “no”.\nShe left.", id="curly-marks"),
    pytest.param("Mixed\r\nline\r\nendings here.", id="crlf"),
    pytest.param("x" * 900, id="pathological"),
    pytest.param(" ".join(["word"] * 500) + ".", id="long-sentence"),
]


@pytest.mark.parametrize("text", INTEGRITY_CASES)
def test_the_plan_preserves_every_character_in_order(text):
    """Structural integrity: whitespace may be normalised, content may not."""
    assert squeeze("".join(plan(text))) == squeeze(text)


@pytest.mark.parametrize("text", INTEGRITY_CASES)
def test_nothing_is_duplicated(text):
    chunks = plan(text)
    assert sum(len(squeeze(c)) for c in chunks) == len(squeeze(text))


def test_word_order_is_exactly_preserved_across_a_large_document():
    text = "\n\n".join(
        " ".join(f"Marker{p:02d}x{i:03d} stands here." for i in range(40))
        for p in range(15))
    markers = [m.group(0) for c in plan(text)
               for m in re.finditer(r"Marker\d+x\d+", c)]
    expected = [m.group(0) for m in re.finditer(r"Marker\d+x\d+", text)]
    assert markers == expected


def test_punctuation_is_never_dropped_at_a_boundary():
    """Repeated stripping is the classic way a full stop disappears."""
    text = " ".join(f'"Line {n} spoke!"' for n in range(120))
    joined = "".join(plan(text))
    assert joined.count("!") == text.count("!")
    assert joined.count('"') == text.count('"')


def test_no_empty_chunk_is_ever_emitted():
    text = "One.\n\n\n\n   \n\nTwo.\n\n\n"
    chunks = plan(text)
    assert chunks and all(chunk.strip() for chunk in chunks)


def test_empty_text_yields_no_chunks():
    assert plan("   \n\n  ") == []


def test_the_splitter_refuses_to_return_a_plan_that_lost_text(monkeypatch):
    """The safety net itself is tested, not just trusted."""
    monkeypatch.setattr(cbx, "_pack_words",
                        lambda sentence, max_chars: ["dropped"])
    with pytest.raises(cbx.ChunkPlanError):
        plan(" ".join(["word"] * 400) + ".")


# --------------------------------------------------------------------------- #
# E. The surrounding Plan 4 contract must not move
# --------------------------------------------------------------------------- #
def test_the_production_ceiling_is_unchanged():
    assert cbx.CHATTERBOX_MAX_CHUNK_CHARS == 300


def test_the_production_temperature_is_unchanged():
    assert cbx.GENERATION_TEMPERATURE == 0.72
    assert cbx.PHASE9_EVALUATION_TEMPERATURE == 0.8


def test_the_colon_pause_is_unchanged():
    assert cbx.COLON_PAUSE_MS == 75


def test_a_short_colon_sentence_is_still_one_chunk_with_two_colon_segments():
    """The +75 ms prose-colon contract, exactly as Phase 12 settled it."""
    text = "Warning: the gate is closed."
    assert plan(text) == [text]
    assert cbx.split_at_prose_colon(text) == ["Warning:", "the gate is closed."]


def test_a_dialogue_lead_in_colon_still_reaches_the_colon_pause():
    """`awkwardly:\\n"Well…"` must keep its colon segment once the newline goes."""
    text = 'He cleared his throat awkwardly:\n"Well, I will be going, then."'
    segments = generated_segments(text)
    assert len(segments) == 2
    assert segments[0].endswith(":")
    assert not any("\n" in segment for segment in segments)


def test_the_splitter_is_still_chatterboxs_own_and_not_kokoros():
    from tts import kokoro_synth
    assert cbx.split_for_chatterbox is not kokoro_synth.split_into_chunks
    assert "kokoro" not in cbx.split_for_chatterbox.__module__


def test_kokoro_is_not_given_the_chatterbox_ceiling():
    from tts import kokoro_synth
    import inspect
    default = inspect.signature(kokoro_synth.split_into_chunks).parameters[
        "max_chars"].default
    assert default == 3000
