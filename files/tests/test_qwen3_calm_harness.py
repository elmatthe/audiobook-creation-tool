"""v0.6.7 — the development-only Qwen3 calm-narration comparison harness (``files/dev-tools/qwen3_calm_*.py``).

Offline and deterministic: no model is loaded and no clone audio is generated. What is pinned:

* the experiment replaces only ``temperature`` and/or ``subtalker_temperature`` in a clone ``synth`` job, nothing else;
* the baseline is the application's own clone profile (0.70 / 0.80) on the PRODUCTION worker with no override;
* a clone is refused unless the app's own rules say it can run, i.e. an owner-approved transcript bound to the original recording;
* the recording used is the registered original, the voice asked for is the voice made, presets and other engines are refused;
* nothing in production (worker, synth, job format, pins) knows the experiment exists, and its output stays under ignored dev-work.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "files" / "dev-tools"))

import qwen3_calm_experiment as exp  # noqa: E402
import qwen3_calm_worker as cw  # noqa: E402
from tts import qwen3_runtime as rt  # noqa: E402
from tts import qwen3_synth  # noqa: E402

from source_probe import application_python_files  # noqa: E402

CLONES = ["qwen3-female-1", "qwen3-female-2", "qwen3-male-1", "qwen3-male-2", "qwen3-male-3", "qwen3-male-4"]


# --------------------------------------------------------------------------- #
# The dev worker: one argument forwarded, nothing else
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw, expected", [
    (None, {}), ("", {}), ("   ", {}), ("{}", {}),
    ('{"temperature": 0.8}', {"temperature": 0.8}), ('{"temperature": 1}', {"temperature": 1.0}),
    ('{"temperature": 0.1}', {"temperature": 0.1}), ('{"temperature": 1.5}', {"temperature": 1.5}),
    ('{"subtalker_temperature": 0.9}', {"subtalker_temperature": 0.9}),
    ('{"temperature": 0.9, "subtalker_temperature": 0.9}', {"temperature": 0.9, "subtalker_temperature": 0.9})])
def test_a_valid_override_parses_and_an_empty_one_is_no_override(raw, expected):
    assert cw.parse_override(raw) == expected


@pytest.mark.parametrize("raw", [
    "not json", "[0.8]", '"0.8"', '{"temperature": "0.8"}', '{"temperature": true}', '{"temperature": 0.05}',
    '{"temperature": 3}', '{"temperature": null}',
    '{"subtalker_temperature": 9}', '{"top_p": 0.9}', '{"top_k": 10}', '{"repetition_penalty": 1.0}',
    '{"max_new_tokens": 100}', '{"do_sample": false}', '{"temperature": 0.8, "top_p": 0.9}'])
def test_anything_but_a_temperature_in_range_is_refused(raw):
    with pytest.raises(cw.ExperimentError):
        cw.parse_override(raw)


class FakeModel:
    """Stands in for ``Qwen3TTSModel``: records the call a production worker would make."""

    calls: list = []

    def generate_voice_clone(self, text, language=None, voice_clone_prompt=None, **kwargs):
        type(self).calls.append({"text": text, "language": language, "prompt": voice_clone_prompt, "kwargs": kwargs})
        return ["wav"], 24000


@pytest.fixture()
def model_class():
    class Model(FakeModel):
        calls = []

    return Model


def test_the_override_adds_only_temperature_to_the_production_call(model_class):
    cw.install_override(model_class, {"temperature": 0.7})
    model_class().generate_voice_clone(text="hello", language="English", voice_clone_prompt="PROMPT")
    assert model_class.calls == [{"text": "hello", "language": "English", "prompt": "PROMPT", "kwargs": {"temperature": 0.7}}]


def test_no_override_leaves_the_method_the_very_same_object(model_class):
    before = model_class.generate_voice_clone
    cw.install_override(model_class, {})
    assert model_class.generate_voice_clone is before  # baseline behaviour: not even wrapped
    model_class().generate_voice_clone(text="hello", language="English", voice_clone_prompt="P")
    assert model_class.calls[0]["kwargs"] == {}


def test_the_override_replaces_the_production_profile_value_and_leaves_the_other_settings_alone(model_class):
    cw.install_override(model_class, {"temperature": 0.9})
    model_class().generate_voice_clone(text="x", temperature=0.7, subtalker_temperature=0.8)
    assert model_class.calls[0]["kwargs"] == {"temperature": 0.9, "subtalker_temperature": 0.8}


class FakeWorker:
    """Stands in for the production worker module."""

    EXIT_OK, EXIT_FAILED = 0, 2

    def __init__(self):
        self.events, self.mains = [], []

    def emit(self, event):
        self.events.append(event)

    def main(self, argv):
        self.mains.append(argv)
        return self.EXIT_OK


def job_file(tmp_path, **job):
    path = tmp_path / "job.json"
    path.write_text(json.dumps(job), encoding="utf-8")
    return ["worker", str(path)]


def explode_if_asked():
    raise AssertionError("the model library was imported for a run with no override")


def test_with_no_override_the_dev_worker_is_exactly_the_production_worker(tmp_path):
    worker = FakeWorker()
    argv = job_file(tmp_path, kind="synth", mode="clone")
    assert cw.main(argv, {}, worker=worker, model_class=None) == 0
    assert worker.mains == [argv] and worker.events == []
    # and the model class is never even requested: a factory that raises is not called
    cw.main(argv, {}, worker=worker, model_class=explode_if_asked)


def test_an_override_patches_the_model_then_runs_the_unchanged_production_worker(tmp_path, model_class):
    worker = FakeWorker()
    argv = job_file(tmp_path, kind="synth", mode="clone")
    assert cw.main(argv, {cw.ENV_VAR: '{"temperature": 0.8}'}, worker=worker, model_class=model_class) == 0
    assert worker.mains == [argv] and worker.events == []
    model_class().generate_voice_clone(text="t")
    assert model_class.calls[0]["kwargs"] == {"temperature": 0.8}


@pytest.mark.parametrize("job", [{"kind": "synth", "mode": "custom_voice"}, {"kind": "probe"}, {"kind": "synth"}])
def test_an_override_is_refused_for_a_preset_voice_or_any_other_job(tmp_path, model_class, job):
    worker = FakeWorker()
    argv = job_file(tmp_path, **job)
    before = model_class.generate_voice_clone
    assert cw.main(argv, {cw.ENV_VAR: '{"temperature": 0.8}'}, worker=worker, model_class=model_class) == FakeWorker.EXIT_FAILED
    assert worker.mains == [] and worker.events[0]["event"] == "failed" and "clone synthesis only" in worker.events[0]["message"]
    assert model_class.generate_voice_clone is before  # Aiden and Ryan are never touched


def test_a_bad_override_gives_the_parent_a_terminal_failure_and_runs_nothing(tmp_path, model_class):
    worker = FakeWorker()
    argv = job_file(tmp_path, kind="synth", mode="clone")
    assert cw.main(argv, {cw.ENV_VAR: '{"top_p": 0.5}'}, worker=worker, model_class=model_class) == 2
    assert worker.mains == [] and worker.events[0]["event"] == "failed" and "top_p" in worker.events[0]["message"]


def test_the_dev_worker_loads_the_production_worker_file_itself():
    module = cw.load_production_worker()
    assert Path(module.__file__).resolve() == (REPO_ROOT / "scripts" / "tts" / "qwen3_worker.py").resolve()
    assert callable(module.main) and module.EXIT_OK == 0


# --------------------------------------------------------------------------- #
# Production does not know the experiment exists
# --------------------------------------------------------------------------- #
PRODUCTION_QWEN3 = ["qwen3_worker.py", "qwen3_synth.py", "qwen3_runtime.py", "qwen3_process.py", "qwen3_setup.py",
                    "qwen3_install_ui.py", "qwen3_models.json"]


@pytest.mark.parametrize("name", PRODUCTION_QWEN3)
def test_production_qwen3_code_has_no_link_to_the_experiment(name):
    text = (REPO_ROOT / "scripts" / "tts" / name).read_text(encoding="utf-8")
    for needle in ("ACT_QWEN3_EXPERIMENT", "qwen3_calm", "calm-narration"):
        assert needle not in text, (name, needle)


def test_production_forwards_only_the_two_temperatures_never_top_p_top_k_or_the_penalty():
    text = (REPO_ROOT / "scripts" / "tts" / "qwen3_worker.py").read_text(encoding="utf-8")
    for needle in ("top_p", "top_k", "repetition_penalty", "max_new_tokens", "do_sample"):
        assert needle not in text, needle  # those stay the Base model's own values


def test_no_application_source_imports_a_dev_tool():
    offenders = []
    for path in application_python_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        if "qwen3_calm" in text or "qwen3_transcript_review" in text:
            offenders.append(path.name)
    assert offenders == []


def test_the_production_clone_job_carries_the_profile_and_no_other_sampling_control(tmp_path):
    voice = rt.get_voice("qwen3-female-1")
    chunks = qwen3_synth.plan_chunks("Hello there. This is a short test of the job format.")
    job = qwen3_synth.build_job(voice, chunks, job_dir=tmp_path, model_dir=tmp_path, reference_text="ref", device="auto",
                                reference_wav=tmp_path / "reference.wav")
    assert job["generation"] == {"temperature": 0.7, "subtalker_temperature": 0.8}
    flat = json.dumps({k: v for k, v in job.items() if k != "generation"})
    for name in ("temperature", "top_p", "top_k", "repetition_penalty", "sampling", "experiment"):
        assert name not in flat


def test_the_pinned_qwen_tts_version_is_unchanged():
    pins = (REPO_ROOT / "scripts" / "qwen3-requirements.txt").read_text(encoding="utf-8")
    assert any(line.startswith("qwen-tts==0.1.1") for line in pins.splitlines())


# --------------------------------------------------------------------------- #
# The driver
# --------------------------------------------------------------------------- #
def test_temperatures_always_start_with_the_baseline_and_stay_in_range():
    assert exp.normalise_temperatures([0.9, 0.8]) == [0.9, 0.8, 0.7]
    assert exp.normalise_temperatures([0.6, 0.8, 0.9, 0.8, 0.7]) == [0.9, 0.8, 0.7, 0.6]
    assert exp.normalise_temperatures([]) == [0.7]
    for bad in (0.05, 2.0, "0.8", True):
        with pytest.raises(exp.ExperimentError):
            exp.normalise_temperatures([bad])
    assert exp.is_baseline(0.7) and not exp.is_baseline(0.9)
    assert [exp.label_for(t) for t in (0.9, 0.8, 0.7, 0.6)] == ["T0.90", "T0.80", "production-T0.70", "T0.60"]
    assert exp.label_for(0.9, 0.9) == "T0.90-S0.90" and exp.production_profile() == {"temperature": 0.7, "subtalker_temperature": 0.8}


def test_the_comparison_passage_has_prose_dialogue_punctuation_and_paragraphs_and_never_changes():
    text = exp.comparison_text()
    assert text == exp.comparison_text() and len(text) >= exp.COMPARISON_MIN_CHARS
    assert text.count("\n\n") >= 4  # paragraph transitions
    assert text.count("“") + text.count('"') >= 4  # dialogue
    assert any(mark in text for mark in (";", "...", ":", "(", "?")) and not text.startswith("The Ninth Bell of Kaerthellin")


def test_the_baseline_is_the_production_worker_and_a_candidate_overrides_only_what_it_names():
    assert exp.synth_kwargs(0.7) == {}
    kwargs = exp.synth_kwargs(0.9)
    assert set(kwargs) == {"script", "env"} and kwargs["script"] == exp.DEV_WORKER
    env = dict(kwargs["env"])
    assert json.loads(env.pop(exp.ENV_VAR)) == {"temperature": 0.9}  # the sub-talker stays the production profile's
    assert env == dict(rt.worker_environment())  # nothing else about the worker's environment differs
    legacy = exp.synth_kwargs(0.9, 0.9)  # the Base model's own defaults: how clones sounded before the profile
    assert json.loads(legacy["env"][exp.ENV_VAR]) == {"temperature": 0.9, "subtalker_temperature": 0.9}


class Recorder:
    """A fake for ``qwen3_file_to_mp3``: records the call, then does what the engine does with the seam encoder."""

    def __init__(self):
        self.calls = []

    def __call__(self, source, output, voice_id, **kwargs):
        self.calls.append((source, output, voice_id, kwargs))
        tone = (0.1 * np.sin(2 * np.pi * 150 * np.arange(24000 * 3) / 24000)).astype("float32")
        wav = Path(output).with_name("encode.wav")
        sf.write(str(wav), tone, 24000)
        kwargs["encoder"](wav, Path(output).with_name("encode.mp3"), None, work_dir=Path(output).parent)
        Path(output).with_name("encode.mp3").replace(output)
        wav.unlink()


ALLOWED_SEAMS = {"end_silence_ms", "chunk_pause_ms", "log", "encoder", "script", "env"}


def test_each_clip_goes_through_the_production_entry_for_exactly_the_requested_voice(tmp_path):
    rec = Recorder()
    text = tmp_path / "n.txt"
    text.write_text("Hello.", encoding="utf-8")
    exp.run_one("qwen3-male-2", 0.9, text, tmp_path / "out.wav", gap_ms=700, synth=rec, log=lambda m: None)
    (source, output, voice_id, kwargs), = rec.calls
    assert voice_id == "qwen3-male-2" and source == str(text) and output == str(tmp_path / "out.wav")
    assert set(kwargs) <= ALLOWED_SEAMS  # no `availability`, `python`, `jobs_root` or `speech_prep` override
    assert kwargs["end_silence_ms"] == 0 and kwargs["chunk_pause_ms"] == 700
    assert sf.info(str(tmp_path / "out.wav")).format == "WAV"
    rec.calls.clear()
    exp.run_one("qwen3-male-2", 0.7, text, tmp_path / "base.wav", gap_ms=700, synth=rec, log=lambda m: None)
    assert "script" not in rec.calls[0][3] and "env" not in rec.calls[0][3]  # the baseline IS production


@pytest.mark.parametrize("voice_id", ["qwen3-aiden", "qwen3-ryan", "af_heart", "chatterbox-male-1", "en-US-AriaNeural", "qwen3-nobody", ""])
def test_a_preset_another_engine_or_an_unknown_voice_is_refused_never_substituted(voice_id, tmp_path):
    with pytest.raises(exp.ExperimentError):
        exp.check_ready(voice_id, availability=lambda v: (True, "ok"))
    with pytest.raises(exp.ExperimentError):
        exp.run([voice_id], [0.8], availability=lambda v: (True, "ok"), synth=pytest.fail, run_root=tmp_path / "runs")
    assert not (tmp_path / "runs").exists()


@pytest.mark.parametrize("voice_id", ["qwen3-aiden", "qwen3-ryan"])
def test_the_presets_are_refused_for_being_presets_not_by_accident(voice_id):
    with pytest.raises(exp.ExperimentError, match="preset voice"):
        exp.check_ready(voice_id, availability=lambda v: (True, "ok"))


@pytest.fixture()
def approved(tmp_path, monkeypatch):
    """A local transcripts file approving all six clones with synthetic words, bound to the registered recordings."""
    path = tmp_path / "transcripts.json"
    entries = {}
    for voice_id in CLONES:
        voice = rt.get_voice(voice_id)
        entries[voice.reference_name] = {"text": f"Synthetic words for {voice.reference_name}.", "approved": True,
                                         "wav_sha256": voice.reference_sha256}
    path.write_text(json.dumps(entries), encoding="utf-8")
    monkeypatch.setenv(rt.TRANSCRIPTS_ENV, str(path))
    return path


@pytest.fixture()
def engine_ready(monkeypatch):
    """Only the machine-dependent parts (venv, model files) are assumed present; reference and transcript rules stay real."""
    monkeypatch.setattr(rt, "environment_status", lambda: (True, "ok"))
    monkeypatch.setattr(rt, "model_status", lambda key: (True, "ok"))


def test_a_clone_without_an_approved_transcript_is_refused_for_the_apps_own_reason(tmp_path, monkeypatch, engine_ready):
    path = tmp_path / "t.json"
    voice = rt.get_voice("qwen3-female-1")
    monkeypatch.setenv(rt.TRANSCRIPTS_ENV, str(path))
    with pytest.raises(exp.ExperimentError, match="no approved reference transcript"):
        exp.check_ready("qwen3-female-1")  # no file at all
    for entry, reason in (({"text": "draft", "approved": False, "wav_sha256": voice.reference_sha256}, "not been approved"),
                          ({"text": "x", "approved": "true", "wav_sha256": voice.reference_sha256}, "not been approved"),
                          ({"text": "x", "approved": True, "wav_sha256": "0" * 64}, "not bound to the current reference")):
        path.write_text(json.dumps({voice.reference_name: entry}), encoding="utf-8")
        with pytest.raises(exp.ExperimentError, match=reason):
            exp.check_ready("qwen3-female-1")
    path.write_text(json.dumps({voice.reference_name: {"text": "Words.", "approved": True, "wav_sha256": voice.reference_sha256}}),
                    encoding="utf-8")
    assert exp.check_ready("qwen3-female-1").voice_id == "qwen3-female-1"


def test_the_reference_must_be_the_registered_original(monkeypatch, tmp_path, approved, engine_ready):
    other = tmp_path / "Chatterbox - Female 1.wav"
    other.write_bytes(b"not the approved recording")
    monkeypatch.setattr(rt, "reference_path", lambda voice: other)
    with pytest.raises(exp.ExperimentError, match="not the one the app registered"):
        exp.check_ready("qwen3-female-1")


def test_the_six_original_recordings_are_the_registered_ones_and_stay_that_way():
    for voice_id in CLONES:
        voice = rt.get_voice(voice_id)
        path = rt.reference_path(voice)
        assert path.parent.name == "Chatterbox-Voice-Uploads" and path.name == f"Chatterbox - {voice.label.removeprefix('Qwen3 - ')}.wav"
        assert rt.sha256_file(path) == voice.reference_sha256


def test_a_run_refuses_before_any_audio_when_a_clone_is_not_ready(tmp_path):
    rec = Recorder()
    root = tmp_path / "runs"
    with pytest.raises(exp.ExperimentError, match="not ready"):
        exp.run(["qwen3-female-1", "qwen3-male-1"], [0.8], synth=rec, availability=lambda v: (v != "qwen3-male-1", "no transcript"),
                run_root=root)
    assert rec.calls == [] and not root.exists()  # all or nothing: not even a folder


def test_a_run_makes_baseline_then_candidates_with_identical_seeds_and_records_what_it_did(tmp_path, approved):
    rec = Recorder()
    root = tmp_path / "runs"
    previews_before = sorted(p.name for p in (REPO_ROOT / "files" / "voice-previews").iterdir())
    run_dir = exp.run(["qwen3-female-1", "qwen3-male-1"], [0.9, 0.8], run_id="r1", run_root=root, synth=rec,
                      availability=lambda v: (True, "ok"), log=lambda m: None, measure=False)
    assert run_dir == root / "r1"
    assert [(c[2], c[3].get("env", {}).get(exp.ENV_VAR)) for c in rec.calls] == [
        ("qwen3-female-1", '{"temperature": 0.9}'), ("qwen3-female-1", '{"temperature": 0.8}'), ("qwen3-female-1", None),
        ("qwen3-male-1", '{"temperature": 0.9}'), ("qwen3-male-1", '{"temperature": 0.8}'), ("qwen3-male-1", None)]
    manifest = json.loads((run_dir / "manifest.json").read_text("utf-8"))
    assert manifest["temperatures"] == [0.9, 0.8, 0.7]
    assert manifest["production_profile"] == {"temperature": 0.7, "subtalker_temperature": 0.8}
    for voice_id in ("qwen3-female-1", "qwen3-male-1"):
        clips = [c for c in manifest["clips"] if c["voice_id"] == voice_id]
        assert [c["label"] for c in clips] == ["T0.90", "T0.80", "production-T0.70"]
        assert len({tuple(c["chunk_seeds"]) for c in clips}) == 1  # deterministic: the same seeds for every candidate
        assert len(clips[0]["chunk_seeds"]) >= 3 and clips[-1]["worker"] == "production" and clips[0]["worker"] != "production"
        assert all(c["reference_sha256"] == rt.get_voice(voice_id).reference_sha256 for c in clips)
        assert all((run_dir / c["file"]).is_file() and c["file"].startswith(voice_id + "/") for c in clips)
        assert len({c["transcript_sha256"] for c in clips}) == 1
    assert "Synthetic words" not in json.dumps(manifest)  # only a hash of the transcript is recorded, never its text
    assert sorted(p.name for p in (REPO_ROOT / "files" / "voice-previews").iterdir()) == previews_before


def test_a_run_never_overwrites_another_run(tmp_path, approved):
    kwargs = dict(run_id="same", run_root=tmp_path, synth=Recorder(), availability=lambda v: (True, "ok"),
                  log=lambda m: None, measure=False)
    exp.run(["qwen3-female-1"], [0.8], **kwargs)
    with pytest.raises(exp.ExperimentError, match="already exists"):
        exp.run(["qwen3-female-1"], [0.8], **kwargs)


def test_experimental_audio_lives_only_under_ignored_dev_work():
    assert exp.RUN_ROOT.relative_to(REPO_ROOT).parts[:2] == ("files", "dev-work")
    result = subprocess.run(["git", "check-ignore", "-q", str(exp.RUN_ROOT / "x" / "clip.wav")], cwd=REPO_ROOT)
    assert result.returncode == 0
    assert "voice-previews" not in str(exp.RUN_ROOT)


def test_the_real_library_merges_an_explicit_baseline_identically_and_temperature_alone_changes_one_value():
    """Against the pinned qwen_tts in .venv-qwen3 (no model, no audio). Skipped where that environment is absent."""
    try:
        venv, model_dir = rt.venv_python(), rt.model_spec("base").directory
    except Exception:  # noqa: BLE001
        pytest.skip("no Qwen3 environment")
    if not Path(venv).is_file() or not (Path(model_dir) / "generation_config.json").is_file():
        pytest.skip("no Qwen3 environment or Base model on this machine")
    result = subprocess.run([str(venv), "-I", str(exp.VENV_TOOLS), "selfcheck", str(model_dir)], capture_output=True, text=True,
                            env=rt.worker_environment())
    report = json.loads(result.stdout[result.stdout.find("{"):])
    assert report["qwen_tts"] == "0.1.1" and report["generate_voice_clone_forwards_kwargs"] is True
    assert report["explicit_0.9_equals_default"] is True and "subtalker_temperature" in report["sampling_arguments_accepted"]
    assert report["temperature_0.8_changes_only"] == ["temperature"] and report["subtalker_temperature_at_0.8"] == 0.9
    assert report["effective_default"]["temperature"] == 0.9 and report["effective_default"]["top_p"] == 1.0


# --------------------------------------------------------------------------- #
# Measurements
# --------------------------------------------------------------------------- #
def tone(path, segments, rate=24000):
    """Speech-like test audio: [(seconds, hz, vibrato_semitones)] separated by nothing; use (s, 0, 0) for silence."""
    parts = []
    for seconds, hz, vibrato in segments:
        t = np.arange(int(seconds * rate)) / rate
        if hz == 0:
            parts.append(np.zeros_like(t))
            continue
        phase = 2 * np.pi * np.cumsum(hz * 2 ** ((vibrato * np.sin(2 * np.pi * 5 * t)) / 12)) / rate
        parts.append(0.2 * np.sin(phase))
    sf.write(str(path), np.concatenate(parts).astype("float32"), rate)
    return path


def test_a_wobbling_pitch_measures_wider_than_a_steady_one(tmp_path):
    pytest.importorskip("librosa")
    steady = exp.analyze_audio(tone(tmp_path / "a.wav", [(4, 150, 0.1)]))
    wobbly = exp.analyze_audio(tone(tmp_path / "b.wav", [(4, 150, 3.0)]))
    assert wobbly["f0_sd_st"] > 3 * steady["f0_sd_st"] and steady["f0_sd_st"] < 0.5
    assert abs(steady["f0_median_hz"] - 150) < 3


def test_chunks_are_found_by_their_long_gaps_and_adjacent_steps_are_measured(tmp_path):
    pytest.importorskip("librosa")
    path = tone(tmp_path / "c.wav", [(2, 150, 0), (1.0, 0, 0), (2, 150 * 2 ** (3 / 12), 0), (1.0, 0, 0), (2, 150, 0)])
    result = exp.analyze_audio(path, gap_ms=700, chunk_words=[5, 5, 5])
    assert result["segments"] == 3 and result["segments_match_chunks"] is True
    assert 2.5 < result["adjacent_f0_delta_max_st"] < 3.5  # a 3-semitone step between neighbouring chunks
    shorter = exp.analyze_audio(path, gap_ms=700, chunk_words=[5, 5])
    assert shorter["segments_match_chunks"] is False  # an unexpected number of pieces is reported, not hidden


def test_read_back_helpers():
    text = "The captain set down the spyglass. Through the window the harbor lay black and flat."
    assert exp.word_error_rate(text, text.upper()) == 0
    assert 0.2 < exp.word_error_rate(text, "The captain set down the spyglass.") < 0.9
    assert exp.tail_present(text, text) and not exp.tail_present(text, "The captain set down the spyglass.")


def test_the_listening_page_is_labelled_and_escapes_what_it_shows():
    manifest = {"text_chars": 10, "text_sha256": "a" * 64, "clips": [
        {"voice_id": "qwen3-female-1", "label": "production-T0.70", "temperature": 0.7, "file": "qwen3-female-1/production-T0.70.wav"},
        {"voice_id": "qwen3-female-1", "label": "T0.80", "temperature": 0.8, "file": "qwen3-female-1/T0.80.wav"}]}
    page = exp.render_listening_page(manifest, {"qwen3-female-1/T0.80": {"f0_sd_st": 1.23}}, "<b>passage</b> & more")
    assert "production-T0.70" in page and "T0.80" in page and 'src="qwen3-female-1/T0.80.wav"' in page
    assert "1.23" in page and "&lt;b&gt;passage&lt;/b&gt; &amp; more" in page and "<b>passage</b>" not in page
