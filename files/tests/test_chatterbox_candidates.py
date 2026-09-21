"""v0.6.5 Phase 2 — the Chatterbox Male-3/Male-4 candidate-evaluation path.

Section 5 of the plan requires candidates to be evaluated on a **separate**
path from the historical four-voice evaluation, under **current production**
settings (not the historical Phase 9 temperature), with **no GUI registry
change before approval**. This file pins exactly those three requirements,
plus the P8 contract (hash-bound, never substituted) the two candidates share
with the four approved voices.

Nothing here loads real weights, reads a real recording, or reaches the
network: the engine is stubbed at the same seams
``test_chatterbox_evaluation.py`` already stubs, and every audio fixture is
generated into ``tmp_path``. The real local recordings at
files/Chatterbox-Voice-Uploads/Male-3.mp3 and Male-4.mp3 are verified by hand
once per Phase 2 checkpoint (recorded in Handoff.md) — never by a tracked
test, which must run identically on a machine that has never seen them.
"""
from __future__ import annotations

import wave
from pathlib import Path

import pytest

from tts import chatterbox_synth as cbx
from tts import generate_voice_samples as gvs
from tts import voice_registry

CANDIDATE_VOICE_IDS = ("chatterbox-male-3", "chatterbox-male-4")


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


# --------------------------------------------------------------------------- #
# A. Registry isolation — no GUI registry change before approval (Section 5)
# --------------------------------------------------------------------------- #
def test_candidates_are_not_registered_voices():
    ids = {v.voice_id for v in voice_registry.VOICES}
    assert "chatterbox-male-3" not in ids
    assert "chatterbox-male-4" not in ids


def test_the_registry_still_holds_exactly_four_chatterbox_rows():
    chatterbox = [v for v in voice_registry.VOICES if v.backend == "chatterbox"]
    assert len(chatterbox) == 4


def test_running_the_candidate_evaluation_registers_nothing(candidate_engine):
    before = list(voice_registry.VOICES)
    gvs.run_chatterbox_candidate_evaluation(log=lambda _m: None)
    assert voice_registry.VOICES == before


# --------------------------------------------------------------------------- #
# B. The historical four-voice evaluation stays exactly as it was (Section 5)
# --------------------------------------------------------------------------- #
def test_the_production_reference_set_stays_at_exactly_four():
    assert len(cbx.REFERENCE_VOICES) == 4
    assert set(CANDIDATE_VOICE_IDS).isdisjoint(cbx.REFERENCE_VOICES)


def test_the_historical_evaluation_ids_are_untouched():
    assert gvs.CHATTERBOX_EVAL_VOICE_IDS == (
        "chatterbox-female-1", "chatterbox-female-2",
        "chatterbox-male-1", "chatterbox-male-2",
    )
    assert set(gvs.CHATTERBOX_EVAL_VOICE_IDS).isdisjoint(CANDIDATE_VOICE_IDS)


def test_candidate_and_historical_outputs_use_different_subfolders():
    assert gvs.CHATTERBOX_CANDIDATE_SUBDIR != gvs.CHATTERBOX_EVAL_SUBDIR


# --------------------------------------------------------------------------- #
# C. Reference identity — hash-bound like the four approved voices (P8)
# --------------------------------------------------------------------------- #
def test_candidate_reference_voices_are_exactly_male_3_and_4():
    assert set(cbx.CANDIDATE_REFERENCE_VOICES) == set(CANDIDATE_VOICE_IDS)
    assert cbx.CANDIDATE_REFERENCE_VOICES["chatterbox-male-3"].source_name == "Male-3.mp3"
    assert cbx.CANDIDATE_REFERENCE_VOICES["chatterbox-male-4"].source_name == "Male-4.mp3"


def test_candidate_hashes_are_real_sha256_strings():
    for voice in cbx.CANDIDATE_REFERENCE_VOICES.values():
        assert len(voice.source_sha256) == 64
        int(voice.source_sha256, 16)  # a hex string


def test_get_reference_voice_finds_candidates_via_fallback():
    assert cbx.get_reference_voice("chatterbox-male-3").source_name == "Male-3.mp3"
    assert cbx.get_reference_voice("chatterbox-male-4").source_name == "Male-4.mp3"


def test_get_reference_voice_still_rejects_a_truly_unknown_id():
    with pytest.raises(cbx.ChatterboxUnavailable):
        cbx.get_reference_voice("chatterbox-nonexistent")


def test_a_hash_mismatch_is_reported_without_stopping_the_other_candidate(candidate_engine):
    candidate_engine.fail_hash_for = "chatterbox-male-3"
    results = gvs.run_chatterbox_candidate_evaluation(log=lambda _m: None)
    by_id = {r.voice_id: r for r in results}
    assert by_id["chatterbox-male-3"].ok is False
    assert "sha256" in by_id["chatterbox-male-3"].detail.lower()
    assert by_id["chatterbox-male-4"].ok is True


# --------------------------------------------------------------------------- #
# D. Current production settings, not the historical Phase 9 temperature
# --------------------------------------------------------------------------- #
def test_the_candidate_evaluation_uses_current_production_settings(candidate_engine):
    gvs.run_chatterbox_candidate_evaluation(log=lambda _m: None)
    assert candidate_engine.generation_used == cbx.generation_params()
    assert candidate_engine.generation_used["temperature"] == cbx.GENERATION_TEMPERATURE
    assert candidate_engine.generation_used["temperature"] != cbx.PHASE9_EVALUATION_TEMPERATURE


def test_the_candidate_text_matches_the_historical_evaluation_sentence():
    """Same sentence as the four approved voices, so the comparison is about
    the voice, not a different script."""
    assert gvs.CHATTERBOX_CANDIDATE_TEXT == gvs.CHATTERBOX_EVAL_TEXT


# --------------------------------------------------------------------------- #
# E. Entry point, CLI flag, and evidence shape
# --------------------------------------------------------------------------- #
def test_the_generator_exposes_a_dedicated_candidate_entry_point():
    assert callable(gvs.run_chatterbox_candidate_evaluation)


def test_the_candidate_flag_is_distinct_from_the_historical_eval_flag():
    parser = gvs._build_parser()
    assert parser.parse_args([]).chatterbox_candidates is False
    ns = parser.parse_args(["--chatterbox-candidates"])
    assert ns.chatterbox_candidates is True
    assert ns.chatterbox_eval is False


def test_the_candidate_evaluation_covers_exactly_the_two_candidates_in_order(candidate_engine):
    results = gvs.run_chatterbox_candidate_evaluation(log=lambda _m: None)
    assert [r.voice_id for r in results] == list(CANDIDATE_VOICE_IDS)


def test_candidate_outputs_land_only_in_their_own_subfolder(candidate_engine):
    results = gvs.run_chatterbox_candidate_evaluation(log=lambda _m: None)
    for r in results:
        assert gvs.CHATTERBOX_CANDIDATE_SUBDIR in r.output_path
        assert gvs.CHATTERBOX_EVAL_SUBDIR not in r.output_path
        assert r.output_path.endswith(f"{r.voice_id}.wav")


def test_the_report_function_returns_zero_only_when_both_succeed(candidate_engine):
    results = gvs.run_chatterbox_candidate_evaluation(log=lambda _m: None)
    assert gvs._report_chatterbox_candidate_evaluation(results, log=lambda _m: None) == 0


def test_the_report_function_returns_nonzero_on_any_failure(candidate_engine):
    candidate_engine.fail_generation_for = "chatterbox-male-4"
    results = gvs.run_chatterbox_candidate_evaluation(log=lambda _m: None)
    assert gvs._report_chatterbox_candidate_evaluation(results, log=lambda _m: None) == 1


def test_a_missing_local_recording_reports_setup_required_not_a_crash(
    candidate_engine, monkeypatch,
):
    """P8: a missing/unreadable reference reports 'setup required', never a
    substitution or an unhandled exception."""
    def _missing(voice_id: str) -> Path:
        raise cbx.ChatterboxUnavailable(
            f"Setup required for {voice_id}: the reference recording is not present.")

    monkeypatch.setattr(cbx, "resolve_reference", _missing)
    results = gvs.run_chatterbox_candidate_evaluation(log=lambda _m: None)
    assert all(not r.ok for r in results)
    assert all("setup required" in r.detail.lower() for r in results)
