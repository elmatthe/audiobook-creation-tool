"""v0.6.5 Phase 8: the ``--final-acceptance`` harness's pure logic.

No synthesis, no network, no audio: the workload selection, the mechanical
checks over measured evidence, the protected-reference comparison and the
manifest round trip. The real runs are an explicit manual QA step (plan
Section 8), never a hidden pytest dependency.
"""
from __future__ import annotations

import json

from tts import generate_voice_samples as gvs
from tts import quality_corpus as qc
from tts.voice_registry import VOICES


def _clean(**overrides) -> dict:
    measured = {
        "decode_ok": True, "decode_errors": "", "container_s": 60.0,
        "decoded_s": 60.0, "clipped_fraction": 0.0,
        "silences": [(0.0, 0.2), (30.0, 30.8), (59.1, 60.0)],
    }
    measured.update(overrides)
    return measured


def test_every_voice_gets_short_and_sustained_and_one_per_backend_gets_stress():
    stress = {v.voice_id for v in VOICES
              if qc.LONGER_STRESS in gvs.final_items_for(v.voice_id)}
    assert stress == {"en-US-SteffanNeural", "af_heart", "chatterbox-male-1"}
    assert {next(v.backend for v in VOICES if v.voice_id == s) for s in stress} == {
        "edge", "kokoro", "chatterbox"}
    for v in VOICES:
        items = gvs.final_items_for(v.voice_id)
        assert items[:2] == (qc.DIFFICULT_SHORT, qc.SUSTAINED_NARRATION)


def test_a_clean_artifact_has_no_problems():
    problems, derived = gvs.judge_final_artifact(_clean(), chars=900)
    assert problems == []
    assert derived["chars_per_s"] == 15.0
    assert derived["longest_internal_silence_s"] == 0.8
    assert derived["longest_internal_silence_at_s"] == 30.0


def test_leading_and_trailing_silence_is_not_internal():
    problems, derived = gvs.judge_final_artifact(
        _clean(silences=[(0.0, 5.0), (52.0, 60.0)]), chars=900)
    assert problems == [] and derived["longest_internal_silence_s"] == 0.0


def test_each_mechanical_failure_is_reported():
    cases = {
        "does not fully decode": _clean(decode_ok=False, decode_errors="Invalid data"),
        "disagrees with decoded": _clean(container_s=75.0),
        "implausible duration": _clean(decoded_s=10.0, container_s=10.0, silences=[]),
        "clipping": _clean(clipped_fraction=0.01),
        "pathological silence": _clean(silences=[(20.0, 26.5)]),
    }
    for expected, measured in cases.items():
        problems, _ = gvs.judge_final_artifact(measured, chars=900)
        assert any(expected in p for p in problems), (expected, problems)


def test_empty_audio_is_a_problem_not_a_crash():
    problems, _ = gvs.judge_final_artifact(
        _clean(decoded_s=0.0, container_s=0.0, silences=[]), chars=900)
    assert "empty audio" in problems


def test_reference_comparison_flags_mismatch_change_and_absence():
    good = {"path": "p", "registered_sha256": "a", "sha256": "a", "mtime_ns": 1}
    assert gvs.compare_reference_state({"v": good}, {"v": dict(good)}) == []
    touched = dict(good, mtime_ns=2)
    assert any("changed during" in p
               for p in gvs.compare_reference_state({"v": good}, {"v": touched}))
    wrong = dict(good, sha256="b")
    problems = gvs.compare_reference_state({"v": wrong}, {"v": wrong})
    assert any("differs from the registered" in p for p in problems)
    missing = dict(good, sha256=None, mtime_ns=None)
    assert any("missing" in p
               for p in gvs.compare_reference_state({"v": good}, {"v": missing}))


def test_manifest_round_trips_and_orders_by_registry(tmp_path):
    first, last = VOICES[0], VOICES[-1]
    rows = [
        gvs.FinalArtifact(voice_id=last.voice_id, display_label=last.display_label,
                          backend=last.backend, corpus_item="sustained_narration",
                          chars=5050, source_path="s", source_sha256="h",
                          problems=["pathological silence: 6.00s starting at 20.00s"]),
        gvs.FinalArtifact(voice_id=first.voice_id, display_label=first.display_label,
                          backend=first.backend, corpus_item="difficult_short",
                          chars=836, source_path="s", source_sha256="h", ok=True,
                          measurements={"decoded_s": 60.0}, derived={"chars_per_s": 13.9}),
    ]
    gvs._write_final_manifest(tmp_path, rows, [])
    lines = (tmp_path / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["voice_id"] for line in lines] == [
        first.voice_id, last.voice_id]
    assert [r.voice_id for r in gvs._load_final_manifest(tmp_path)] == [
        first.voice_id, last.voice_id]
    table = (tmp_path / "manifest.md").read_text(encoding="utf-8")
    assert "PROBLEM: pathological silence" in table
    assert "references: intact" in table


def test_an_unfinished_run_does_not_claim_the_references_are_intact(tmp_path):
    gvs._write_final_manifest(tmp_path, [], None)
    table = (tmp_path / "manifest.md").read_text(encoding="utf-8")
    assert "not yet checked" in table and "intact" not in table
