"""Kokoro timing wiring: end_silence_ms / chunk_pause_ms must reach the output.

_get_pipeline is monkeypatched to a fake yielding fixed audio, so neither the
kokoro package nor the 300 MB model is touched. Output duration is measured
with pydub, so a local ffmpeg is required — the module skips cleanly without one.
"""

from __future__ import annotations

import numpy as np
import pytest

from shared import ffmpeg_utils

if not ffmpeg_utils.have_ffmpeg():  # pragma: no cover - environment guard
    pytest.skip("ffmpeg not available for pydub", allow_module_level=True)

ffmpeg_utils.configure_pydub()

from pydub import AudioSegment  # noqa: E402

import tts.kokoro_synth as ks  # noqa: E402

# 0.25 s of silence at Kokoro's fixed 24 kHz sample rate, per pipeline call.
_FAKE_AUDIO = np.zeros(6000, dtype=np.float32)


class _FakePipeline:
    def __call__(self, text, voice=None, speed=1.0, split_pattern=None):
        yield ("graphemes", "phonemes", _FAKE_AUDIO)


@pytest.fixture
def fake_pipeline(monkeypatch):
    monkeypatch.setattr(ks, "_get_pipeline", lambda lang_code: _FakePipeline())


# Long enough to split into exactly two chunks (split_into_chunks max is 3000
# chars), so chunk_pause_ms is applied twice and its effect is measurable.
_TWO_CHUNK_TEXT = ("This is a sentence that fills the chunk. " * 90).strip()


def _duration_ms(tmp_path, name: str, *, end_silence_ms: int, chunk_pause_ms: int) -> int:
    src = tmp_path / f"{name}.txt"
    src.write_text(_TWO_CHUNK_TEXT, encoding="utf-8")
    out = tmp_path / f"{name}.mp3"
    ks.kokoro_file_to_mp3(
        str(src),
        str(out),
        voice_id="af_heart",
        end_silence_ms=end_silence_ms,
        chunk_pause_ms=chunk_pause_ms,
        log=lambda s: None,
    )
    return len(AudioSegment.from_mp3(str(out)))


def test_text_splits_into_two_chunks():
    assert len(ks.split_into_chunks(_TWO_CHUNK_TEXT)) == 2


def test_end_silence_ms_extends_output(tmp_path, fake_pipeline):
    base = _duration_ms(tmp_path, "end0", end_silence_ms=0, chunk_pause_ms=50)
    longer = _duration_ms(tmp_path, "end2000", end_silence_ms=2000, chunk_pause_ms=50)
    delta = longer - base
    assert 1800 <= delta <= 2200, f"end_silence_ms not applied (delta={delta}ms)"


def test_chunk_pause_ms_extends_output(tmp_path, fake_pipeline):
    base = _duration_ms(tmp_path, "pause50", end_silence_ms=0, chunk_pause_ms=50)
    longer = _duration_ms(tmp_path, "pause1050", end_silence_ms=0, chunk_pause_ms=1050)
    # Two chunks -> the +1000 ms pause is appended after each of them.
    delta = longer - base
    assert 1600 <= delta <= 2400, f"chunk_pause_ms not applied (delta={delta}ms)"
