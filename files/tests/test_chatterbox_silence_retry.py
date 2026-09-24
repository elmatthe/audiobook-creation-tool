"""v0.6.5 Phase 8 macOS blocker — bounded retry for a pathological internal
silence in one raw Chatterbox draw.

The defect these tests exist for
---------------------------------

The Mac bounded-validation run (2026-09-24) flagged two of sixteen final
voices: Chatterbox Male 1 (13.75 s internal silence) and Chatterbox Male 3
(7.98 s). The same exact-zero-vs-model-floor technique the v0.6.1 Plan 4
Phase 12 chunking investigation used (see ``test_chatterbox_chunking.py``)
showed neither silence sat at a configured chunk/colon-pause boundary — both
were entirely inside a single ``model.generate()`` draw's own PCM. A bounded
reproduction (4 repeated draws of each flagged text, same voice/reference/
settings, no seed) showed the defect is **stochastic, not deterministic**:
Male 1's flagged text reproduced 0/4, Male 3's reproduced 2/4. Unlike the
Phase 12 defect, no structural newline or other text pattern was implicated
— this is a rare/occasional Chatterbox Turbo sampling artifact, not a
chunking bug, so the fix is a mechanical detect-and-retry safety net around
one ``generate()`` draw, not a text/chunking change.

What these tests hold the implementation to
---------------------------------------------

1. ``_has_pathological_silence`` flags an internal near-silent run of at
   least ``PATHOLOGICAL_SILENCE_S`` and nothing shorter.
2. ``_generate_checked`` retries a defective draw, keeps the first clean one,
   never exceeds ``PATHOLOGICAL_SILENCE_MAX_ATTEMPTS`` calls, and — if every
   attempt is still defective — returns the last attempt rather than empty
   audio or a crash (text/audio is never silently dropped, P8/P9).
3. ``_synthesize_chunk`` reaches every ``generate()`` draw (the whole-chunk
   path and each colon-segment path) through ``_generate_checked`` — no call
   site may bypass the retry.
4. The retry is silence-triggered only: a normal draw is never retried
   (bounded by call-count assertions), so this cannot become a hidden
   quality knob (P1, P3).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent
                       / "scripts" / "Universal"))

from tts import chatterbox_synth as cbx  # noqa: E402

SR = 24000


def _tone(seconds: float, amplitude: float = 0.2) -> np.ndarray:
    n = int(SR * seconds)
    return (amplitude * np.ones(n, dtype="float32"))


def _silence(seconds: float) -> np.ndarray:
    return np.zeros(int(SR * seconds), dtype="float32")


def _with_interior_silence(speech_s: float, silence_s: float) -> np.ndarray:
    """A short tone, a near-silent (not exact-zero) run, then more tone."""
    near_zero = np.full(int(SR * silence_s), 1e-6, dtype="float32")
    return np.concatenate([_tone(speech_s / 2), near_zero, _tone(speech_s / 2)])


# --------------------------------------------------------------------------- #
# 1. _has_pathological_silence
# --------------------------------------------------------------------------- #
def test_flags_an_interior_run_at_or_past_the_threshold():
    arr = _with_interior_silence(2.0, cbx.PATHOLOGICAL_SILENCE_S)
    assert cbx._has_pathological_silence(arr, SR)


def test_does_not_flag_a_shorter_interior_run():
    arr = _with_interior_silence(2.0, cbx.PATHOLOGICAL_SILENCE_S - 1.0)
    assert not cbx._has_pathological_silence(arr, SR)


def test_does_not_flag_ordinary_speech():
    arr = _tone(3.0)
    assert not cbx._has_pathological_silence(arr, SR)


def test_empty_array_is_not_flagged():
    assert not cbx._has_pathological_silence(np.zeros(0, dtype="float32"), SR)


# --------------------------------------------------------------------------- #
# 2. _generate_checked — retry behaviour
# --------------------------------------------------------------------------- #
class _QueuedModel:
    """Returns each of ``draws`` in order, one per ``generate()`` call."""

    def __init__(self, draws: list[np.ndarray]) -> None:
        self.sr = SR
        self._draws = list(draws)
        self.calls = 0

    def generate(self, text, **kwargs):
        self.calls += 1
        return self._draws[min(self.calls - 1, len(self._draws) - 1)]


def test_a_clean_first_draw_is_kept_with_exactly_one_call():
    model = _QueuedModel([_tone(3.0)])
    out = cbx._generate_checked(model, "hello", log=lambda *_: None)
    assert model.calls == 1
    assert out.size == int(SR * 3.0)


def test_a_defective_draw_is_retried_and_the_clean_one_kept():
    defective = _with_interior_silence(2.0, cbx.PATHOLOGICAL_SILENCE_S + 1.0)
    clean = _tone(3.0)
    model = _QueuedModel([defective, clean])
    logs: list[str] = []
    out = cbx._generate_checked(model, "hello", log=logs.append)
    assert model.calls == 2
    assert out.size == clean.size
    assert any("retrying" in line for line in logs)


def test_retries_are_bounded_and_the_last_attempt_survives():
    always_defective = _with_interior_silence(2.0, cbx.PATHOLOGICAL_SILENCE_S + 1.0)
    model = _QueuedModel([always_defective])  # same defective draw every call
    logs: list[str] = []
    out = cbx._generate_checked(model, "hello", log=logs.append)
    assert model.calls == cbx.PATHOLOGICAL_SILENCE_MAX_ATTEMPTS
    assert out.size == always_defective.size, "last attempt is kept, never dropped"
    assert any("every retry" in line for line in logs)


def test_an_empty_draw_is_not_treated_as_pathological_and_is_kept():
    """An empty draw is the pre-existing 'no audio' path (_synthesize_chunk
    already skips it) — the retry must not loop on it or mask it."""
    model = _QueuedModel([np.zeros(0, dtype="float32")])
    out = cbx._generate_checked(model, "hello", log=lambda *_: None)
    assert model.calls == 1
    assert out.size == 0


# --------------------------------------------------------------------------- #
# 3. _synthesize_chunk reaches every draw through _generate_checked
# --------------------------------------------------------------------------- #
def test_single_segment_chunk_retries_through_generate_checked():
    defective = _with_interior_silence(2.0, cbx.PATHOLOGICAL_SILENCE_S + 1.0)
    clean = _tone(2.0)
    model = _QueuedModel([defective, clean])
    out = cbx._synthesize_chunk(model, "No colon here.", log=lambda *_: None)
    assert model.calls == 2
    assert out.size == clean.size


def test_each_colon_segment_is_independently_retried():
    """Two colon segments; the second segment's first draw is defective."""
    seg1_clean = _tone(1.5)
    seg2_defective = _with_interior_silence(2.0, cbx.PATHOLOGICAL_SILENCE_S + 1.0)
    seg2_clean = _tone(1.5)
    model = _QueuedModel([seg1_clean, seg2_defective, seg2_clean])
    out = cbx._synthesize_chunk(model, "First part: second part.",
                                log=lambda *_: None)
    assert model.calls == 3
    gap = int(SR * cbx.COLON_PAUSE_MS / 1000.0)
    assert out.size == seg1_clean.size + gap + seg2_clean.size
