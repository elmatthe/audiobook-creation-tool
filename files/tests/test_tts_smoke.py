"""Behaviour preservation: TTS voice registry + PDF text extraction.

No network: never touches Edge TTS or the Kokoro model download.
"""

from __future__ import annotations

import pytest


def test_voice_registry_shape_and_lookup():
    from tts import voice_registry as vr

    labels = vr.display_labels()
    assert len(vr.VOICES) == 11, "6 Edge + 5 Kokoro voices"
    assert len(labels) == len(set(labels)) == 11

    edge = [v for v in vr.VOICES if v.backend == "edge"]
    kokoro = [v for v in vr.VOICES if v.backend == "kokoro"]
    assert len(edge) == 6 and len(kokoro) == 5
    assert {v.voice_id for v in kokoro} == {
        "af_heart", "af_bella", "am_michael", "bf_emma", "bm_george",
    }

    # Lookup round-trips and every voice carries a timing preset.
    for v in vr.VOICES:
        assert vr.get_voice(v.display_label) is v
        assert isinstance(v.timing_preset, dict) and v.timing_preset
    assert vr.get_voice("No Such Voice") is None
    assert vr.DEFAULT_VOICE_LABEL == labels[0]


def test_pdf_to_txt_extracts_text(tmp_path):
    fitz = pytest.importorskip("fitz")
    from tts.pdf_extractor import pdf_to_txt

    pdf = tmp_path / "sample.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        (72, 100),
        "The quick brown fox jumps over the lazy dog. "
        "It kept running through the quiet field.",
        fontsize=12,
    )
    doc.save(str(pdf))
    doc.close()

    out_txt = tmp_path / "sample.txt"
    txt_path = pdf_to_txt(str(pdf), str(out_txt))
    text = open(txt_path, encoding="utf-8").read()
    assert "quick brown fox" in text
    assert "quiet field" in text
