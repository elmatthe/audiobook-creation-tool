"""v0.6.5 Phase 2 — the Chatterbox candidate-evaluation path.

Section 5 of the plan requires candidates to be evaluated on a **separate**
path from the historical four-voice evaluation, under **current production**
settings (not the historical Phase 9 temperature), with **no GUI registry
change before approval**. This file pins exactly those three requirements,
plus the P8 contract (hash-bound, never substituted) every candidate shares
with the approved voices.

**Final Phase 2 ruling (2026-09-20):** both Male-3 and Male-4 are approved
and registered. Male-4 is the original candidate sample. Male-3 is *also*
the original candidate sample — a separate bounded §14 pitch-retry variant
was tried and rejected ("I prefer the original voice exactly as it was
before the retry"), so no pitch/timbre adjustment reached its registration,
and the retry mechanism (``render_male3_pitch_retry``,
``_pitch_shift_preserve_tempo``, the ``--chatterbox-male3-pitch-retry`` CLI
flag) was removed from ``generate_voice_samples.py`` entirely — it no
longer represents supported behavior. The rejected retry is documented in
``Decisions.md`` and the superseded blocks of ``Handoff.md`` per the
project's append/supersede convention, not here.

``CANDIDATE_REFERENCE_VOICES`` is therefore currently empty, and
``CHATTERBOX_CANDIDATE_VOICE_IDS`` is an empty tuple — both are left in
place as reusable infrastructure for whatever future candidate a later
phase introduces, and this file's tests below use a synthetic candidate
(monkeypatched in) to keep that infrastructure under real regression
coverage without hardcoding a voice_id that no longer exists as a
candidate.

Nothing here loads real weights, reads a real recording, or reaches the
network: the engine is stubbed at the same seams
``test_chatterbox_evaluation.py`` already stubs, and every audio fixture is
generated into ``tmp_path``. The real local recordings at
files/Chatterbox-Voice-Uploads/Male-3.mp3 and Male-4.mp3 are verified by
hand once per Phase 2 checkpoint (recorded in Handoff.md) — never by a
tracked test, which must run identically on a machine that has never seen
them.
"""
from __future__ import annotations

import wave
from pathlib import Path

import pytest

from tts import chatterbox_synth as cbx
from tts import generate_voice_samples as gvs
from tts import voice_registry


def _write_wav(path: Path, seconds: float = 1.5, rate: int = 24000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))


def _made(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


class _CandidateEngine:
    """Records every call the candidate evaluation makes into the engine."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.generated: list[tuple[str, str, str]] = []
        self.generation_used: dict | None = None
        self.fail_hash_for: str | None = None
        self.fail_generation_for: str | None = None

    def resolve_reference(self, voice_id: str) -> Path:
        if voice_id == self.fail_hash_for:
            raise cbx.ChatterboxUnavailable(
                f"The reference recording for {voice_id} does not match the "
                "expected sha256. Refusing to use it.")
        source = self.tmp_path / "uploads" / cbx.get_reference_voice(voice_id).source_name
        source.parent.mkdir(parents=True, exist_ok=True)
        if not source.exists():
            source.write_bytes(b"candidate recording for " + voice_id.encode())
        return source

    def prepare_reference_clip(self, voice_id: str, log=print) -> Path:
        clip = self.tmp_path / "runtime-data" / "reference-clips" / f"{voice_id}.wav"
        _write_wav(clip, seconds=15.0)
        return clip

    def conditionals_path(self, voice_id: str, source_sha256: str) -> Path:
        path = self.tmp_path / "runtime-data" / "conditionals" / f"{voice_id}.pt"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def synthesize_text_to_wav(self, text, output_path, voice_id, log=print,
                               device=None, generation=None) -> int:
        self.generation_used = generation
        if voice_id == self.fail_generation_for:
            raise cbx.ChatterboxUnavailable(
                f"Chatterbox produced no audio for voice '{voice_id}'.")
        self.generated.append((voice_id, text, str(output_path)))
        _write_wav(Path(output_path), seconds=1.5)
        return 24000


@pytest.fixture
def candidate_engine(monkeypatch, tmp_path):
    stub = _CandidateEngine(tmp_path)
    for name in ("resolve_reference", "prepare_reference_clip",
                 "conditionals_path", "synthesize_text_to_wav"):
        monkeypatch.setattr(cbx, name, getattr(stub, name), raising=False)
    monkeypatch.setattr(cbx, "select_device", lambda: "cpu")
    monkeypatch.setattr(gvs, "_out_dir", lambda: _made(tmp_path / "manual-listen"))
    return stub


@pytest.fixture
def synthetic_candidate(monkeypatch):
    """Inject one fake, throwaway candidate so the still-reusable
    candidate-evaluation machinery stays under regression coverage even
    though no real candidate is currently pending."""
    fake = cbx.ReferenceVoice(
        voice_id="chatterbox-synthetic-test-voice",
        label="Chatterbox — Synthetic Test Voice (candidate)",
        source_name="Synthetic-Test.mp3",
        source_sha256="0" * 64,
    )
    monkeypatch.setitem(cbx.CANDIDATE_REFERENCE_VOICES, fake.voice_id, fake)
    monkeypatch.setattr(gvs, "CHATTERBOX_CANDIDATE_VOICE_IDS", (fake.voice_id,))
    return fake


# --------------------------------------------------------------------------- #
# A. Final registration state (Section 5) — both candidates resolved
# --------------------------------------------------------------------------- #
def test_male_3_and_male_4_are_both_registered_voices():
    ids = {v.voice_id for v in voice_registry.VOICES}
    assert "chatterbox-male-3" in ids
    assert "chatterbox-male-4" in ids


def test_male_3_display_label_carries_no_pitch_or_retry_marker():
    """The registered Male 3 is the original candidate — nothing about its
    label, or any other column, reflects the rejected pitch-retry variant."""
    entry = voice_registry.get_voice("Chatterbox - Male 3")
    assert entry is not None
    assert entry.voice_id == "chatterbox-male-3"
    assert entry.timing_preset == voice_registry._chatterbox_preset()


def test_the_registry_holds_exactly_six_chatterbox_rows():
    chatterbox = [v for v in voice_registry.VOICES if v.backend == "chatterbox"]
    assert len(chatterbox) == 6


def test_the_registry_holds_exactly_sixteen_voices_total():
    assert len(voice_registry.VOICES) == 16


# --------------------------------------------------------------------------- #
# B. The historical four-voice evaluation stays exactly as it was (Section 5)
# --------------------------------------------------------------------------- #
def test_the_production_reference_set_now_holds_six():
    """Four at Phase 10, plus Male 3 and Male 4 both moved in on final
    approval — neither retains any candidate-only marker."""
    assert len(cbx.REFERENCE_VOICES) == 6
    assert cbx.REFERENCE_VOICES["chatterbox-male-3"].label == "Chatterbox — Male 3"
    assert cbx.REFERENCE_VOICES["chatterbox-male-4"].label == "Chatterbox — Male 4"


def test_the_candidate_pool_is_currently_empty():
    """Both prior candidates were resolved; nothing is pending."""
    assert cbx.CANDIDATE_REFERENCE_VOICES == {}
    assert gvs.CHATTERBOX_CANDIDATE_VOICE_IDS == ()


def test_the_historical_evaluation_ids_are_untouched():
    assert gvs.CHATTERBOX_EVAL_VOICE_IDS == (
        "chatterbox-female-1", "chatterbox-female-2",
        "chatterbox-male-1", "chatterbox-male-2",
    )
    assert set(gvs.CHATTERBOX_EVAL_VOICE_IDS).isdisjoint(cbx.CANDIDATE_REFERENCE_VOICES)


def test_candidate_and_historical_outputs_use_different_subfolders():
    assert gvs.CHATTERBOX_CANDIDATE_SUBDIR != gvs.CHATTERBOX_EVAL_SUBDIR


# --------------------------------------------------------------------------- #
# C. Reference identity — hash-bound like every approved voice (P8)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("voice_id,source_name,sha", [
    ("chatterbox-male-3", "Male-3.mp3",
     "0bb698d934515c690b97c85922dcfb61a0e2e07f07fd66b4e0b2e8ca13c292c4"),
    ("chatterbox-male-4", "Male-4.mp3",
     "1db9bb339748edede0b8d6a20171ea0672e59914516e49fd9b1b910cc6f028f5"),
])
def test_the_final_hashes_match_exactly_what_was_verified_during_candidacy(
    voice_id, source_name, sha,
):
    """The hash bound at final approval must be byte-for-byte the same one
    verified when the file was still a candidate — approval never
    recomputes or re-trusts a new hash."""
    voice = cbx.get_reference_voice(voice_id)
    assert voice.source_name == source_name
    assert voice.source_sha256 == sha


def test_get_reference_voice_finds_both_via_the_primary_production_set():
    assert cbx.get_reference_voice("chatterbox-male-3").source_name == "Male-3.mp3"
    assert cbx.get_reference_voice("chatterbox-male-4").source_name == "Male-4.mp3"
    assert "chatterbox-male-3" in cbx.REFERENCE_VOICES
    assert "chatterbox-male-4" in cbx.REFERENCE_VOICES


def test_get_reference_voice_still_rejects_a_truly_unknown_id():
    with pytest.raises(cbx.ChatterboxUnavailable):
        cbx.get_reference_voice("chatterbox-nonexistent")


def test_get_reference_voice_still_falls_back_to_a_real_pending_candidate(
    synthetic_candidate,
):
    """The fallback seam itself (Section 5's architecture) still works for
    whatever the next real candidate turns out to be."""
    voice = cbx.get_reference_voice(synthetic_candidate.voice_id)
    assert voice.source_name == synthetic_candidate.source_name
    assert synthetic_candidate.voice_id not in cbx.REFERENCE_VOICES


# --------------------------------------------------------------------------- #
# D. The candidate-evaluation machinery remains reusable, currently idle
# --------------------------------------------------------------------------- #
def test_the_generator_exposes_a_dedicated_candidate_entry_point():
    assert callable(gvs.run_chatterbox_candidate_evaluation)


def test_the_candidate_flag_is_distinct_from_the_historical_eval_flag():
    parser = gvs._build_parser()
    assert parser.parse_args([]).chatterbox_candidates is False
    ns = parser.parse_args(["--chatterbox-candidates"])
    assert ns.chatterbox_candidates is True
    assert ns.chatterbox_eval is False


def test_running_the_candidate_evaluation_with_nothing_pending_is_a_graceful_no_op(
    candidate_engine,
):
    results = gvs.run_chatterbox_candidate_evaluation(log=lambda _m: None)
    assert results == []
    assert gvs._report_chatterbox_candidate_evaluation(results, log=lambda _m: None) == 0


def test_running_the_candidate_evaluation_registers_nothing(candidate_engine):
    before = list(voice_registry.VOICES)
    gvs.run_chatterbox_candidate_evaluation(log=lambda _m: None)
    assert voice_registry.VOICES == before


def test_the_candidate_evaluation_uses_current_production_settings_for_a_real_candidate(
    candidate_engine, synthetic_candidate,
):
    gvs.run_chatterbox_candidate_evaluation(log=lambda _m: None)
    assert candidate_engine.generation_used == cbx.generation_params()
    assert candidate_engine.generation_used["temperature"] == cbx.GENERATION_TEMPERATURE
    assert candidate_engine.generation_used["temperature"] != cbx.PHASE9_EVALUATION_TEMPERATURE


def test_the_candidate_text_matches_the_historical_evaluation_sentence():
    """Same sentence as the four approved voices, so any future candidate's
    comparison is about the voice, not a different script."""
    assert gvs.CHATTERBOX_CANDIDATE_TEXT == gvs.CHATTERBOX_EVAL_TEXT


def test_a_future_candidates_output_lands_only_in_its_own_subfolder(
    candidate_engine, synthetic_candidate,
):
    results = gvs.run_chatterbox_candidate_evaluation(log=lambda _m: None)
    assert len(results) == 1
    assert gvs.CHATTERBOX_CANDIDATE_SUBDIR in results[0].output_path
    assert gvs.CHATTERBOX_EVAL_SUBDIR not in results[0].output_path
    assert results[0].output_path.endswith(f"{synthetic_candidate.voice_id}.wav")


def test_a_hash_mismatch_for_a_future_candidate_is_reported_not_crashed(
    candidate_engine, synthetic_candidate,
):
    candidate_engine.fail_hash_for = synthetic_candidate.voice_id
    results = gvs.run_chatterbox_candidate_evaluation(log=lambda _m: None)
    assert len(results) == 1
    assert results[0].ok is False
    assert "sha256" in results[0].detail.lower()


def test_a_missing_local_recording_reports_setup_required_not_a_crash(
    candidate_engine, synthetic_candidate, monkeypatch,
):
    """P8: a missing/unreadable reference reports 'setup required', never a
    substitution or an unhandled exception."""
    def _missing(voice_id: str) -> Path:
        raise cbx.ChatterboxUnavailable(
            f"Setup required for {voice_id}: the reference recording is not present.")

    monkeypatch.setattr(cbx, "resolve_reference", _missing)
    results = gvs.run_chatterbox_candidate_evaluation(log=lambda _m: None)
    assert len(results) == 1
    assert results[0].ok is False
    assert "setup required" in results[0].detail.lower()


# --------------------------------------------------------------------------- #
# E. The rejected pitch-retry machinery is gone, not merely unused
# --------------------------------------------------------------------------- #
def test_the_rejected_retry_machinery_no_longer_exists():
    """The maintainer rejected the pitch-retry variant and asked for the
    retry-only machinery to be removed, not just left dormant."""
    for symbol in ("render_male3_pitch_retry", "_pitch_shift_preserve_tempo",
                   "MALE3_RETRY_PITCH_RATIO", "MALE3_RETRY_SUBDIR"):
        assert not hasattr(gvs, symbol), f"{symbol} should have been removed"


def test_the_rejected_retry_cli_flag_no_longer_exists():
    parser = gvs._build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--chatterbox-male3-pitch-retry"])
