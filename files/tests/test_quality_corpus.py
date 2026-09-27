"""v0.6.5 Phase 1: the QA corpus text is correct and reproducible.

No network, no synthesis, no model load — this only checks the text itself
(plan Section 8) and the manifest-writing helper. Real synthesis is an
explicit ``--quality-suite`` run, never a tracked test (plan Section 8's
network-independence rule).
"""
from __future__ import annotations

import json

from tts import quality_corpus as qc
from tts.chatterbox_synth import CHATTERBOX_MAX_CHUNK_CHARS
from tts.batch_convert import CHUNK_TARGET


def test_difficult_short_covers_every_false_boundary_case():
    text = qc.DIFFICULT_SHORT.text
    required = [
        "Mr.", "Mrs.", "Dr.", "Prof.",  # honorifics
        "e.g.", "i.e.", "vs.",          # abbreviations
        "J. R.",                        # initials
        "2.5",                          # decimal
        "6:45", "7:15",                 # times
        "3:1",                          # ratio
        "https://",                     # URL
        "...",                          # ellipsis
        "\"",                           # quoted dialogue
        "(",                            # parenthetical
    ]
    for token in required:
        assert token in text, f"missing required false-boundary case: {token!r}"

    # A closing quote immediately after sentence-ending punctuation.
    assert "?\"" in text or ".\"" in text


def test_structural_stress_items_cross_their_backends_chunk_ceilings():
    # Deliberately no convenient paragraph break near the ceiling, so a
    # chunker is forced into a mid-paragraph continuation split.
    assert qc.STRUCTURAL_STRESS_CHATTERBOX.char_count > CHATTERBOX_MAX_CHUNK_CHARS
    assert qc.STRUCTURAL_STRESS_KOKORO_EDGE.char_count > CHUNK_TARGET


def test_sustained_and_longer_are_a_consistent_pair():
    sustained = qc.SUSTAINED_NARRATION.text
    longer = qc.LONGER_STRESS.text

    # ~5,000 chars, adjustable per plan Section 8 — a wide but meaningful band.
    assert 4000 <= len(sustained) <= 6500

    # Longer must actually be longer, and a clean paragraph-aligned prefix of
    # the same story rather than an unrelated passage, so the two samples are
    # directly comparable for the same voice.
    assert len(longer) > len(sustained)
    assert longer.startswith(sustained)
    assert not sustained.endswith(" ")  # no mid-word/mid-space slice


def test_corpus_identity_is_deterministic_and_content_sensitive():
    first = qc.corpus_identity()
    second = qc.corpus_identity()
    assert first == second
    assert len(first) == 16
    int(first, 16)  # hex string

    # Changing any item's text must change the identity (P12: a manifest
    # entry's corpus_identity must mean "this exact wording").
    import dataclasses

    mutated = dataclasses.replace(qc.DIFFICULT_SHORT, text=qc.DIFFICULT_SHORT.text + " ")
    original_items = qc.ALL_ITEMS
    try:
        qc.ALL_ITEMS = (mutated,) + original_items[1:]
        assert qc.corpus_identity() != first
    finally:
        qc.ALL_ITEMS = original_items


def test_all_items_have_unique_names():
    names = [item.name for item in qc.ALL_ITEMS]
    assert len(names) == len(set(names))
    for name in names:
        assert qc.get_item(name).name == name


def test_manifest_writer_produces_valid_jsonl_and_markdown(tmp_path):
    from tts import generate_voice_samples as gvs

    rows = [
        gvs.QualitySample(
            voice_id="en-US-SteffanNeural", backend="edge",
            corpus_item="difficult_short", assembly_path="standard",
            output_path=str(tmp_path / "sample.mp3"), commit_sha="deadbeef",
            corpus_identity=qc.corpus_identity(), effective_settings="engine defaults",
            duration_s=1.23, wall_s=0.5, rtf=0.41, dbfs=-19.5,
            leading_silence_ms=100, trailing_silence_ms=200, ok=True, detail="OK",
        ),
        gvs.QualitySample(
            voice_id="chatterbox-female-1", backend="chatterbox",
            corpus_item="difficult_short", assembly_path="standard",
            output_path=str(tmp_path / "fail.mp3"), commit_sha="deadbeef",
            corpus_identity=qc.corpus_identity(), effective_settings="engine defaults",
            ok=False, detail="reference missing",
        ),
    ]

    gvs._write_manifest(tmp_path, rows)

    jsonl_lines = (tmp_path / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(jsonl_lines) == 2
    parsed = [json.loads(line) for line in jsonl_lines]
    assert parsed[0]["voice_id"] == "en-US-SteffanNeural"
    assert parsed[1]["ok"] is False

    md = (tmp_path / "manifest.md").read_text(encoding="utf-8")
    assert "en-US-SteffanNeural" in md
    assert "FAIL" in md and "reference missing" in md
