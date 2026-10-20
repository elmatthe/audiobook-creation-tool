"""v0.6.7 CP6 — the Qwen3 worker's own logic, with fake ``torch`` and ``qwen_tts`` modules.

The worker normally runs only inside ``.venv-qwen3``. Its decisions (which device, what is refused, when it stops, what
it writes, what it tells the parent) do not need a GPU or a 4.5 GB model to be tested: the heavy imports are lazy, so
two small stand-ins in ``sys.modules`` are enough to drive every branch.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from tts import qwen3_worker as worker


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class FakeCuda:
    def __init__(self, available: bool):
        self.available = available
        self.seeds = []

    def is_available(self):
        return self.available

    def synchronize(self):
        pass

    def manual_seed_all(self, seed):
        self.seeds.append(seed)

    def empty_cache(self):
        pass

    def get_device_properties(self, index):
        return types.SimpleNamespace(name="Fake RTX", total_memory=12 * 2**30)

    def get_device_capability(self, index):
        return (12, 0)


def install_fakes(monkeypatch, *, cuda: bool = False, speakers=("Aiden", "Ryan"), model_factory=None):
    torch = types.ModuleType("torch")
    torch.bfloat16 = "bf16-marker"
    torch.cuda = FakeCuda(cuda)
    torch.seeds = []
    torch.manual_seed = torch.seeds.append
    torch.version = types.SimpleNamespace(cuda="12.8" if cuda else None)

    class FakeModel:
        def __init__(self):
            self.model = types.SimpleNamespace(tts_model_type="fake")
            self.calls = []

        def get_supported_speakers(self):
            return list(speakers) if speakers is not None else None

        def _wave(self, text):
            return (np.full(2400 + 100 * len(text), 0.1, dtype="float32"), 24000)

        def create_voice_clone_prompt(self, ref_audio, ref_text, x_vector_only_mode):
            assert x_vector_only_mode is False  # a transcript-free clone is never requested
            self.calls.append(("prompt", ref_audio, ref_text))
            return {"prompt": ref_text}

        def generate_custom_voice(self, text, language, speaker):
            self.calls.append(("custom", text, language, speaker))
            wave, rate = self._wave(text)
            return [wave], rate

        def generate_voice_clone(self, text, language, voice_clone_prompt, **kwargs):
            self.calls.append(("clone", text, language, voice_clone_prompt, kwargs))
            wave, rate = self._wave(text)
            return [wave], rate

    holder = {}

    class FakeQwen3TTSModel:
        @staticmethod
        def from_pretrained(model_dir, device_map, dtype, attn_implementation):
            holder["args"] = (model_dir, device_map, dtype, attn_implementation)
            if model_factory is not None:
                return model_factory()
            holder["model"] = FakeModel()
            return holder["model"]

    qwen = types.ModuleType("qwen_tts")
    qwen.Qwen3TTSModel = FakeQwen3TTSModel
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "qwen_tts", qwen)
    return torch, holder


def job_for(tmp_path, mode="custom_voice", chunks=("Hello there.", "A second chunk."), **extra):
    job = {"kind": "synth", "mode": mode, "model_dir": str(tmp_path / "model"), "language": "English",
           "dtype": "bfloat16", "attn": "sdpa", "device": "auto", "out_dir": str(tmp_path / "chunks"),
           "cancel_file": str(tmp_path / "cancel"),
           "chunks": [{"index": i, "text": t, "seed": 1000 + i} for i, t in enumerate(chunks)], "speaker": "Aiden"}
    job.update(extra)
    return job


def events(capsys) -> list[dict]:
    out = capsys.readouterr().out
    return [json.loads(line[len(worker.EVENT_PREFIX):]) for line in out.splitlines() if line.startswith(worker.EVENT_PREFIX)]


# --------------------------------------------------------------------------- #
# Device choice
# --------------------------------------------------------------------------- #
def test_auto_uses_the_gpu_only_when_one_is_reported_and_otherwise_the_cpu():
    assert worker.choose_device("auto", True) == "cuda:0"
    assert worker.choose_device("auto", False) == "cpu"
    assert worker.choose_device("cpu", True) == "cpu"
    assert worker.choose_device("cuda", True) == "cuda:0"


def test_an_explicit_gpu_request_without_a_gpu_is_refused_rather_than_downgraded():
    with pytest.raises(RuntimeError, match="no CUDA device"):
        worker.choose_device("cuda", False)
    with pytest.raises(RuntimeError, match="unknown device"):
        worker.choose_device("tpu", False)


# --------------------------------------------------------------------------- #
# Synthesis
# --------------------------------------------------------------------------- #
def test_a_preset_job_loads_offline_in_bf16_renders_each_chunk_and_reports_in_order(tmp_path, monkeypatch, capsys):
    torch, holder = install_fakes(monkeypatch, cuda=True)
    assert worker.run_synth(job_for(tmp_path)) == worker.EXIT_OK
    got = events(capsys)
    assert [e["event"] for e in got] == ["loaded", "chunk", "chunk", "done"]
    assert holder["args"] == (str(tmp_path / "model"), "cuda:0", "bf16-marker", "sdpa")
    assert got[0]["device"] == "cuda:0" and got[0]["device_name"] == "Fake RTX"
    assert [e["wav"] for e in got[1:3]] == ["chunk-0001.wav", "chunk-0002.wav"]
    assert got[3] == {**got[3], "chunks": 2, "sample_rate": 24000, "device": "cuda:0"}
    assert torch.seeds == [1000, 1001] and torch.cuda.seeds == [1000, 1001]  # the parent's seeds, per chunk
    assert [c[3] for c in holder["model"].calls] == ["Aiden", "Aiden"] and holder["model"].calls[0][2] == "English"
    data, rate = sf.read(str(tmp_path / "chunks" / "chunk-0001.wav"), dtype="float32")
    assert rate == 24000 and data.ndim == 1 and data.size == 2400 + 100 * len("Hello there.")
    assert sf.info(str(tmp_path / "chunks" / "chunk-0001.wav")).subtype == "FLOAT"  # nothing quantised or clipped


def test_with_no_gpu_the_worker_runs_on_the_cpu_and_says_so(tmp_path, monkeypatch, capsys):
    _, holder = install_fakes(monkeypatch, cuda=False)
    assert worker.run_synth(job_for(tmp_path)) == worker.EXIT_OK
    loaded = events(capsys)[0]
    assert loaded["device"] == "cpu" and loaded["device_name"] == "CPU" and holder["args"][1] == "cpu"


def test_a_clone_job_builds_a_transcript_conditioned_prompt_once_and_reuses_it(tmp_path, monkeypatch, capsys):
    _, holder = install_fakes(monkeypatch)
    job = job_for(tmp_path, mode="clone", reference_wav="ref.wav", reference_text="approved words")
    assert worker.run_synth(job) == worker.EXIT_OK
    calls = holder["model"].calls
    assert calls[0] == ("prompt", "ref.wav", "approved words")  # x_vector_only_mode=False asserted by the fake
    assert [c[0] for c in calls] == ["prompt", "clone", "clone"]
    assert calls[1][3] == calls[2][3] == {"prompt": "approved words"}  # one prompt for the whole file
    assert events(capsys)[-1]["event"] == "done"


def test_an_unknown_speaker_is_refused_not_substituted(tmp_path, monkeypatch, capsys):
    install_fakes(monkeypatch, speakers=("Dylan", "Eric"))
    assert worker.run_synth(job_for(tmp_path)) == worker.EXIT_FAILED
    failed = events(capsys)[-1]
    assert failed["event"] == "failed" and failed["stage"] == "prepare"
    assert "refusing to substitute another voice" in failed["message"]
    assert not (tmp_path / "chunks" / "chunk-0001.wav").exists()


def test_cancel_flag_is_checked_before_the_load_and_before_every_chunk(tmp_path, monkeypatch, capsys):
    _, holder = install_fakes(monkeypatch)
    (tmp_path / "cancel").write_text("x", encoding="utf-8")
    assert worker.run_synth(job_for(tmp_path)) == worker.EXIT_CANCELED
    assert [e["event"] for e in events(capsys)] == ["canceled"] and "args" not in holder  # the model was never loaded

    (tmp_path / "cancel").unlink()
    install_fakes(monkeypatch)

    first = {"done": False}  # the flag is raised from inside the first generate() call, like Cancel pressed mid-file
    original = sys.modules["qwen_tts"].Qwen3TTSModel.from_pretrained

    def factory(*a, **k):
        model = original(*a, **k)
        real = model.generate_custom_voice

        def generate(**kw):
            result = real(**kw)
            if not first["done"]:
                first["done"] = True
                (tmp_path / "cancel").write_text("x", encoding="utf-8")
            return result

        model.generate_custom_voice = generate
        return model

    sys.modules["qwen_tts"].Qwen3TTSModel.from_pretrained = staticmethod(factory)
    assert worker.run_synth(job_for(tmp_path)) == worker.EXIT_CANCELED
    got = events(capsys)
    assert [e["event"] for e in got] == ["loaded", "chunk", "canceled"] and got[-1]["completed"] == 1


@pytest.mark.parametrize("error, oom", [("CUDA out of memory. Tried to allocate 2 GiB", True), ("RuntimeError: boom", False)])
def test_a_generation_failure_is_reported_with_its_stage_and_chunk_and_stops_the_file(tmp_path, monkeypatch, capsys, error, oom):
    def factory():
        model = types.SimpleNamespace(model=types.SimpleNamespace(tts_model_type="x"))
        model.get_supported_speakers = lambda: ["Aiden"]

        def generate(**kwargs):
            raise RuntimeError(error)

        model.generate_custom_voice = generate
        return model

    install_fakes(monkeypatch, cuda=True, model_factory=factory)
    assert worker.run_synth(job_for(tmp_path)) == worker.EXIT_FAILED
    failed = events(capsys)[-1]
    assert failed["event"] == "failed" and failed["stage"] == "generate" and failed["index"] == 0
    assert failed["oom"] is oom and error in failed["message"] and "trace" in failed
    assert not list((tmp_path / "chunks").glob("*.wav"))  # nothing half-written is reported


def test_a_load_failure_is_a_load_stage_failure(tmp_path, monkeypatch, capsys):
    def factory():
        raise OSError("model.safetensors is corrupt")

    install_fakes(monkeypatch, model_factory=factory)
    assert worker.run_synth(job_for(tmp_path)) == worker.EXIT_FAILED
    failed = events(capsys)[-1]
    assert failed["stage"] == "load" and "corrupt" in failed["message"]


def test_audio_that_is_not_mono_finite_and_consistent_fails_the_chunk(tmp_path, monkeypatch, capsys):
    def make(wave, rate=24000):
        def factory():
            model = types.SimpleNamespace(model=types.SimpleNamespace(tts_model_type="x"))
            model.get_supported_speakers = lambda: ["Aiden"]
            model.generate_custom_voice = lambda **kw: ([wave], rate)
            return model
        return factory

    for wave, rate, message in [(np.zeros((10, 2), dtype="float32"), 24000, "mono"),
                                (np.zeros(0, dtype="float32"), 24000, "empty"),
                                (np.array([np.nan, 0.0], dtype="float32"), 24000, "non-finite"),
                                (np.zeros(10, dtype="float32"), 0, "invalid sample rate")]:
        install_fakes(monkeypatch, model_factory=make(wave, rate))
        assert worker.run_synth(job_for(tmp_path)) == worker.EXIT_FAILED
        assert message in events(capsys)[-1]["message"]

    rates = iter([24000, 22050])

    def changing():
        model = types.SimpleNamespace(model=types.SimpleNamespace(tts_model_type="x"))
        model.get_supported_speakers = lambda: ["Aiden"]
        model.generate_custom_voice = lambda **kw: ([np.zeros(100, dtype="float32")], next(rates))
        return model

    install_fakes(monkeypatch, model_factory=changing)
    assert worker.run_synth(job_for(tmp_path)) == worker.EXIT_FAILED
    assert "sample rate changed" in events(capsys)[-1]["message"]


# --------------------------------------------------------------------------- #
# Probe and entry point
# --------------------------------------------------------------------------- #
def test_probe_reports_the_stack_and_optionally_loads_a_model(tmp_path, monkeypatch, capsys):
    for name in ("soundfile", "transformers"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    install_fakes(monkeypatch, cuda=True)
    assert worker.run_probe({"kind": "probe"}) == worker.EXIT_OK
    got = events(capsys)
    assert got[0]["event"] == "probe" and got[0]["cuda_available"] is True and got[0]["torch_cuda"] == "12.8"
    assert "load_s" not in got[0] and got[-1]["event"] == "done"

    assert worker.run_probe({"kind": "probe", "model_dir": str(tmp_path / "model")}) == worker.EXIT_OK
    loaded = events(capsys)[0]
    assert loaded["loaded_on"] == "cuda:0" and loaded["speakers"] == ["Aiden", "Ryan"] and "load_s" in loaded


def test_probe_reports_a_broken_install_as_an_import_failure(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "torch", None)  # import torch -> ImportError
    assert worker.run_probe({"kind": "probe"}) == worker.EXIT_FAILED
    failed = events(capsys)[-1]
    assert failed["event"] == "failed" and failed["stage"] == "import"


def test_main_validates_its_arguments_and_always_ends_with_a_terminal_event(tmp_path, monkeypatch, capsys):
    assert worker.main(["worker"]) == 64
    capsys.readouterr()

    job = tmp_path / "job.json"
    job.write_text(json.dumps({"kind": "dance"}), encoding="utf-8")
    assert worker.main(["worker", str(job)]) == worker.EXIT_FAILED
    assert "unknown job kind" in events(capsys)[-1]["message"]

    job.write_text("{not json", encoding="utf-8")
    assert worker.main(["worker", str(job)]) == worker.EXIT_FAILED  # even an unreadable job gets a failed event
    assert events(capsys)[-1]["event"] == "failed"

    install_fakes(monkeypatch)
    job.write_text(json.dumps(job_for(tmp_path)), encoding="utf-8")
    assert worker.main(["worker", str(job)]) == worker.EXIT_OK
    assert events(capsys)[-1]["event"] == "done"


def test_the_worker_module_imports_without_the_model_stack():
    code = ("import sys; sys.path.insert(0, r'%s'); import tts.qwen3_worker; "
            "sys.exit(1 if any(m in sys.modules for m in ('torch', 'qwen_tts', 'transformers')) else 0)"
            % Path(worker.__file__).resolve().parents[1])
    import subprocess

    assert subprocess.run([sys.executable, "-c", code], capture_output=True).returncode == 0


# --------------------------------------------------------------------------- #
# The clone narration profile (owner preference, 2026-10-20): calmer sampling for the six clones only
# --------------------------------------------------------------------------- #
PROFILE = {"temperature": 0.7, "subtalker_temperature": 0.8}


def test_a_clone_job_forwards_exactly_its_generation_settings_to_every_chunk(tmp_path, monkeypatch, capsys):
    _, holder = install_fakes(monkeypatch)
    job = job_for(tmp_path, mode="clone", reference_wav="ref.wav", reference_text="approved words", generation=PROFILE)
    assert worker.run_synth(job) == worker.EXIT_OK
    clones = [c for c in holder["model"].calls if c[0] == "clone"]
    assert [c[4] for c in clones] == [PROFILE, PROFILE]  # both controls, as floats, and nothing else (no top_p, top_k, ...)
    assert events(capsys)[-1]["event"] == "done"


def test_a_clone_job_without_generation_settings_passes_none_so_older_jobs_behave_as_before(tmp_path, monkeypatch, capsys):
    _, holder = install_fakes(monkeypatch)
    job = job_for(tmp_path, mode="clone", reference_wav="ref.wav", reference_text="approved words")
    assert worker.run_synth(job) == worker.EXIT_OK
    assert [c[4] for c in holder["model"].calls if c[0] == "clone"] == [{}, {}]


def test_a_preset_voice_is_never_given_the_clone_profile(tmp_path, monkeypatch, capsys):
    """Aiden and Ryan: even a stray `generation` in the job is not forwarded (the fake's preset method accepts no extras)."""
    _, holder = install_fakes(monkeypatch)
    assert worker.run_synth(job_for(tmp_path, generation=PROFILE)) == worker.EXIT_OK
    assert [c[0] for c in holder["model"].calls] == ["custom", "custom"]
    assert events(capsys)[-1]["event"] == "done"


@pytest.mark.parametrize("generation", [
    {"top_p": 0.9}, {"top_k": 10}, {"repetition_penalty": 1.0}, {"max_new_tokens": 5}, {"do_sample": False},
    {"temperature": 0.05}, {"temperature": 1.6}, {"temperature": "0.7"}, {"temperature": True}, {"subtalker_temperature": None},
    ["temperature"], "temperature=0.7"])
def test_an_unsupported_or_out_of_range_setting_fails_the_file_before_any_audio(tmp_path, monkeypatch, capsys, generation):
    _, holder = install_fakes(monkeypatch)
    job = job_for(tmp_path, mode="clone", reference_wav="ref.wav", reference_text="approved words", generation=generation)
    assert worker.run_synth(job) == worker.EXIT_FAILED
    got = events(capsys)
    assert got[-1]["event"] == "failed" and got[-1]["stage"] == "prepare"
    assert not [c for c in holder["model"].calls if c[0] == "clone"]  # no chunk was generated with a setting nobody approved


def test_clone_generation_accepts_the_two_temperatures_as_floats_and_nothing_else():
    assert worker.clone_generation({}) == {} and worker.clone_generation({"generation": None}) == {}
    assert worker.clone_generation({"generation": {"temperature": 1, "subtalker_temperature": 0.8}}) == {
        "temperature": 1.0, "subtalker_temperature": 0.8}
    assert set(worker.GENERATION_LIMITS) == {"temperature", "subtalker_temperature"}


@pytest.mark.parametrize("name", ["top_p", "top_k", "repetition_penalty", "max_new_tokens", "do_sample", "subtalker_top_p"])
def test_any_other_sampling_control_is_refused_by_name_not_by_accident(name):
    with pytest.raises(RuntimeError, match="unsupported generation setting"):
        worker.clone_generation({"generation": {name: 1}})
