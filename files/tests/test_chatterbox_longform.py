"""v0.6.1 Plan 4 Phase 12 remediation — the Chatterbox long-form contract.

**Why this file exists.** Phase 10 wired Chatterbox audiobook conversion through
``kokoro_synth.split_into_chunks``, whose default ceiling is 3,000 characters.
That is right for Kokoro and catastrophically wrong for Chatterbox Turbo, and the
Phase 12 manual matrix is what exposed it: three real chapters converted, all three
reported success, and all three were unintelligible.

The failure is measurable without listening to anything. Evidence gathered on
HOME-PC against the pinned ``chatterbox-tts==0.1.7`` wheel and the real Female 1
reference:

===========================  =======  ==========  ====================
probe                          chars      audio    chars / audio-second
===========================  =======  ==========  ====================
Phase 9 evaluation sentence      125     7.88 s                    15.9
first production chunk today   2,889     3.84 s                   752.3
sentence-aware piece, <=300      275    17.92 s                    15.3
sentence-aware piece, <=300      294    18.20 s                    16.2
===========================  =======  ==========  ====================

At the healthy ~16 characters per audio-second, 2,889 characters needs about 181
seconds of speech. It produced 3.84 — **2.1%** of the text. The model does not
report an error; it silently collapses.

Two facts in the pinned wheel explain it, and both are read off the installed
artifact rather than documentation:

* ``chatterbox/models/t3/t3.py`` — ``inference_turbo(..., max_gen_len=1000)``, a
  hard cap ``generate()`` never overrides, against
  ``S3_TOKEN_RATE = 25`` tokens per second in
  ``chatterbox/models/s3tokenizer/s3tokenizer.py``. **One ``generate()`` call can
  emit at most 1000/25 = 40 seconds of audio, ever.** A 3,000-character chunk
  needs ~190 s, so it could never have been rendered whole.
* ``chatterbox/tts_turbo.py:271`` tokenizes with ``truncation=True``, so text past
  the tokenizer's limit is dropped in silence rather than refused.

Upstream agrees: ``resemble-ai/chatterbox`` master ships
``gradio_tts_turbo_app.py`` whose input box is labelled
``"Text to synthesize (max chars 300)"``, and its own ``example_tts_turbo.py``
uses a 240-character string.

Hence :data:`chatterbox_synth.CHATTERBOX_MAX_CHUNK_CHARS` = 300. At the measured
rate that is ~19 seconds of audio — roughly half the 40-second hard cap, so the
ceiling holds even for unusually dense text.

**Kokoro is deliberately untouched.** Its 3,000-character behaviour is correct for
it and is asserted here so this fix cannot quietly shrink it.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

from shared.cancellation import ConversionCancelled  # noqa: E402
from tts import chatterbox_synth as cbx  # noqa: E402
from tts.kokoro_synth import split_into_chunks as kokoro_split  # noqa: E402

from test_chatterbox_engine import _StubModel, stub_engine  # noqa: E402,F401


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _prose(sentences: int, *, words: int = 12) -> str:
    """Ordinary narration: many sentences, none of them pathological."""
    body = " ".join(
        f"Sentence {i} runs on for {' '.join(['a little further'] * (words // 3))}."
        for i in range(sentences)
    )
    return body


def _source(tmp_path: Path, text: str, name: str = "source.txt") -> Path:
    path = tmp_path / name
    path.write_text(f"Title: Sample\nAuthor: Nobody\n{text}\n", encoding="utf-8")
    return path


@pytest.fixture
def synth_ready(monkeypatch, stub_engine):  # noqa: F811
    monkeypatch.setattr(cbx, "load_conditionals",
                        lambda model, voice_id, log=print, device=None: None)
    return stub_engine


CEILING = 300


# --------------------------------------------------------------------------- #
# A. The ceiling itself
# --------------------------------------------------------------------------- #
def test_the_engine_declares_a_named_chunk_ceiling():
    """A magic number buried in a call site is what caused this defect."""
    assert isinstance(cbx.CHATTERBOX_MAX_CHUNK_CHARS, int)


def test_the_ceiling_matches_the_upstream_turbo_limit_and_is_never_raised():
    """300 is upstream's own demo limit. Going above it re-opens the bug."""
    assert cbx.CHATTERBOX_MAX_CHUNK_CHARS <= CEILING


def test_the_ceiling_is_not_kokoros_ceiling():
    kokoro_default = inspect.signature(kokoro_split).parameters["max_chars"].default
    assert cbx.CHATTERBOX_MAX_CHUNK_CHARS < kokoro_default


# --------------------------------------------------------------------------- #
# B. The splitter is Chatterbox's own
# --------------------------------------------------------------------------- #
def test_the_engine_exposes_its_own_splitter():
    assert callable(cbx.split_for_chatterbox)


def test_no_chunk_exceeds_the_ceiling_for_ordinary_prose():
    text = _prose(400)
    assert len(text) > 10_000, "fixture must be long enough to matter"
    for chunk in cbx.split_for_chatterbox(text):
        assert len(chunk) <= cbx.CHATTERBOX_MAX_CHUNK_CHARS


def test_sentence_boundaries_are_preferred():
    text = ("The first sentence ends here. The second sentence ends here. "
            "The third sentence ends here. The fourth sentence ends here.")
    for chunk in cbx.split_for_chatterbox(text):
        assert chunk.rstrip().endswith((".", "!", "?")), chunk


def test_paragraph_boundaries_are_respected_where_practical():
    """Two paragraphs that would comfortably fit together must not be merged."""
    para_a = "Alpha sentence one. Alpha sentence two."
    para_b = "Beta sentence one. Beta sentence two."
    chunks = cbx.split_for_chatterbox(f"{para_a}\n\n{para_b}")
    assert not any("Alpha" in c and "Beta" in c for c in chunks)


def test_a_single_sentence_longer_than_the_ceiling_falls_back_on_whitespace():
    long_sentence = " ".join(["word"] * 400) + "."
    chunks = cbx.split_for_chatterbox(long_sentence)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= cbx.CHATTERBOX_MAX_CHUNK_CHARS
    assert all(" " in chunk or len(chunk) <= cbx.CHATTERBOX_MAX_CHUNK_CHARS
               for chunk in chunks)


def test_a_pathological_unbroken_token_is_still_split_within_the_ceiling():
    """No whitespace anywhere — the ceiling must still hold."""
    blob = "x" * 2500
    chunks = cbx.split_for_chatterbox(blob)
    for chunk in chunks:
        assert len(chunk) <= cbx.CHATTERBOX_MAX_CHUNK_CHARS
    assert "".join(chunks) == blob


def test_no_source_text_is_silently_discarded():
    text = _prose(200)
    rejoined = " ".join(cbx.split_for_chatterbox(text))
    assert "".join(rejoined.split()) == "".join(text.split())


def test_no_source_text_is_duplicated():
    text = _prose(200)
    chunks = cbx.split_for_chatterbox(text)
    assert sum(len("".join(c.split())) for c in chunks) == len("".join(text.split()))


def test_chunk_ordering_is_exact():
    text = " ".join(f"Marker{i} is here." for i in range(300))
    chunks = cbx.split_for_chatterbox(text)
    seen = [int(tok[len("Marker"):])
            for chunk in chunks for tok in chunk.split()
            if tok.startswith("Marker")]
    assert seen == sorted(seen) == list(range(300))


def test_empty_chunks_are_never_generated():
    text = "One.\n\n\n\n   \n\nTwo.\n\n\n"
    assert all(chunk.strip() for chunk in cbx.split_for_chatterbox(text))


def test_empty_text_yields_no_chunks():
    assert cbx.split_for_chatterbox("   \n\n  ") == []


# --------------------------------------------------------------------------- #
# C. The audiobook path actually uses it
#
# This is the regression the manual matrix caught. Before the fix these two fail:
# the file path hands >300-character strings straight to model.generate().
# --------------------------------------------------------------------------- #
def test_file_synthesis_never_passes_more_than_the_ceiling_to_generate(
        synth_ready, tmp_path):
    cbx.chatterbox_file_to_mp3(
        str(_source(tmp_path, _prose(400))), str(tmp_path / "out.mp3"),
        "chatterbox-male-1", log=lambda _m: None)
    assert synth_ready.generated, "nothing was generated"
    longest = max(len(t) for t in synth_ready.generated)
    assert longest <= cbx.CHATTERBOX_MAX_CHUNK_CHARS, (
        f"a {longest}-character string reached ChatterboxTurboTTS.generate(); "
        f"the ceiling is {cbx.CHATTERBOX_MAX_CHUNK_CHARS}")


def test_file_synthesis_does_not_use_the_kokoro_chunker(synth_ready, tmp_path):
    """Retargets the Phase 8 test that asserted the opposite.

    ``test_file_synthesis_reuses_the_existing_chunker`` encoded the defect: it
    asserted the Chatterbox path produced exactly Kokoro's chunk count. That is
    now the bug, so the assertion is inverted rather than deleted — the file path
    must produce *more*, smaller chunks than Kokoro would.
    """
    text = _prose(400)
    cbx.chatterbox_file_to_mp3(
        str(_source(tmp_path, text)), str(tmp_path / "out.mp3"),
        "chatterbox-male-1", log=lambda _m: None)
    assert len(synth_ready.generated) > len(kokoro_split(text))


def test_the_engine_module_no_longer_imports_the_kokoro_chunker_for_generation():
    """The import may remain for reuse elsewhere, but generation must not call it."""
    import ast

    src = Path(cbx.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "chatterbox_file_to_mp3")
    called = {n.func.id for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "split_into_chunks" not in called
    assert "split_for_chatterbox" in called


def test_every_generated_string_is_non_empty(synth_ready, tmp_path):
    cbx.chatterbox_file_to_mp3(
        str(_source(tmp_path, _prose(150))), str(tmp_path / "out.mp3"),
        "chatterbox-male-1", log=lambda _m: None)
    assert all(t.strip() for t in synth_ready.generated)


def test_the_whole_source_reaches_the_engine_in_order(synth_ready, tmp_path):
    text = " ".join(f"Marker{i} is here." for i in range(200))
    cbx.chatterbox_file_to_mp3(
        str(_source(tmp_path, text)), str(tmp_path / "out.mp3"),
        "chatterbox-male-1", log=lambda _m: None)
    seen = [int(tok[len("Marker"):])
            for chunk in synth_ready.generated for tok in chunk.split()
            if tok.startswith("Marker")]
    assert seen == list(range(200))


# --------------------------------------------------------------------------- #
# D. Everything the smaller chunks must not break
# --------------------------------------------------------------------------- #
def test_progress_total_reflects_the_actual_chatterbox_chunk_count(
        synth_ready, tmp_path):
    seen: list[tuple[int, int]] = []
    text = _prose(300)
    cbx.chatterbox_file_to_mp3(
        str(_source(tmp_path, text)), str(tmp_path / "out.mp3"),
        "chatterbox-male-1", log=lambda _m: None,
        progress_callback=lambda done, total: seen.append((done, total)))
    total = seen[0][1]
    assert total == len(synth_ready.generated)
    assert total == len(cbx.split_for_chatterbox(
        "\n".join(line for line in _source_body(text))))
    assert [d for d, _t in seen] == list(range(1, total + 1))


def _source_body(text: str) -> list[str]:
    """Mirror of the module's Title:/Author:/# preprocessing, for the assertion above."""
    return [line for line in text.splitlines()
            if not line.strip().startswith(("Title:", "Author:"))]


def test_cancellation_is_still_checked_between_chatterbox_chunks(
        synth_ready, tmp_path):
    calls = {"n": 0}

    def cancel_after_two() -> bool:
        calls["n"] += 1
        return calls["n"] > 2

    with pytest.raises(ConversionCancelled):
        cbx.chatterbox_file_to_mp3(
            str(_source(tmp_path, _prose(300))), str(tmp_path / "out.mp3"),
            "chatterbox-male-1", log=lambda _m: None,
            cancel_check=cancel_after_two)
    assert len(synth_ready.generated) == 2


def test_a_short_source_still_produces_exactly_one_chunk(synth_ready, tmp_path):
    cbx.chatterbox_file_to_mp3(
        str(_source(tmp_path, "One short line of narration.")),
        str(tmp_path / "out.mp3"), "chatterbox-male-1", log=lambda _m: None)
    assert len(synth_ready.generated) == 1


# --------------------------------------------------------------------------- #
# E. Kokoro is untouched
# --------------------------------------------------------------------------- #
def test_kokoro_still_splits_at_three_thousand_characters():
    assert inspect.signature(kokoro_split).parameters["max_chars"].default == 3000


def test_kokoro_chunking_behaviour_is_unchanged_for_long_prose():
    text = _prose(400)
    chunks = kokoro_split(text)
    assert max(len(c) for c in chunks) > cbx.CHATTERBOX_MAX_CHUNK_CHARS
    assert chunks == kokoro_split(text)


def test_the_remediation_did_not_edit_the_kokoro_engine():
    """`kokoro_synth.py` must not have grown a Chatterbox-shaped constant."""
    src = (REPO_ROOT / "scripts" / "Universal" / "tts" / "kokoro_synth.py").read_text(
        encoding="utf-8")
    assert "CHATTERBOX" not in src.upper()
