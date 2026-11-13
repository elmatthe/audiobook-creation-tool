"""v0.8.0 Phase 2 -- the OmniVoice conversion path, against a fake worker.

The real worker needs a 3.3 GB model, a GPU and a second Python environment; these tests need none of them. A stand-in
script speaks the same ``@@EVENT`` protocol (and misbehaves on request), so the supervising side is exercised with the
real subprocess, pipe, Job Object and kill machinery: the text it is given (prepared once, never again), the reviewed
excerpt and transcript it is conditioned on, chunk order across bounded workers, Cancel at every stage, failures,
no-clobber publication and retry determinism.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import wave
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from shared.cancellation import ConversionCancelled
from tts import omnivoice_runtime as ov
from tts import omnivoice_synth as osy
from tts import qwen3_runtime as rt
from tts.speech import pipeline
from tts.speech.pipeline import OFF, SETTING_V1, build_snapshot

pytestmark = pytest.mark.usefixtures("production_writes_refused")

RATE = 24000

FAKE_WORKER = r'''
import hashlib, json, os, sys, time, wave
from pathlib import Path

import numpy as np
import soundfile as sf

plan = json.loads(os.environ.get("FAKE_OMNIVOICE", "{}"))
job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
behavior = plan.get("behavior", "ok")


def emit(event):
    print("@@EVENT " + json.dumps(event), flush=True)


with wave.open(job["excerpt"]["wav"], "rb") as w:
    excerpt_pcm_sha256 = hashlib.sha256(w.readframes(w.getnframes())).hexdigest()
log = os.environ.get("FAKE_OMNIVOICE_LOG")
if log:
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({**job, "_excerpt_pcm_sha256": excerpt_pcm_sha256, "_argv": sys.argv[1:],
                                 "_isolated": bool(sys.flags.isolated)}) + "\n")
print("a library banner that is not an event", flush=True)
if behavior == "exit_early":
    sys.stderr.write("CUDA error: no kernel image is available\n")
    sys.exit(3)
if behavior == "malformed":
    print("@@EVENT {not json", flush=True)
    time.sleep(30)
if behavior == "no_gpu":
    emit({"event": "failed", "stage": "load", "message": "PyTorch reports no usable CUDA GPU", "gpu": False})
    sys.exit(2)
out = Path(job["out_dir"])
out.mkdir(parents=True, exist_ok=True)
emit({"event": "loaded", "device": "cuda:0", "device_name": "Fake GPU", "load_s": 0.01, "prompt": "built",
      "prompt_s": 0.01, "chunks": len(job["chunks"])})
for position, chunk in enumerate(job["chunks"]):
    if os.path.exists(job["cancel_file"]) and behavior != "ignore_cancel":
        emit({"event": "canceled", "completed": position})
        sys.exit(130)
    if behavior == "ignore_cancel":
        time.sleep(0.3)
    if behavior == "hang" and chunk["index"] == plan.get("at", 0):
        time.sleep(120)
    if behavior == "fail" and chunk["index"] == plan.get("at", 0):
        emit({"event": "failed", "stage": "generate", "index": chunk["index"], "message": plan.get("message", "kaboom"),
              "oom": bool(plan.get("oom"))})
        sys.exit(2)
    index = chunk["index"]
    n = int(24000 * (0.2 + 0.05 * index))
    wave_ = (0.05 * (index + 1) * np.sin(2 * np.pi * 220 * np.arange(n) / 24000)).astype("float32")
    if behavior == "nan" and index == plan.get("at", 0):
        wave_[3] = float("nan")
    name = f"chunk-{index + 1:04d}.wav"
    if not (behavior == "missing_file" and index == plan.get("at", 0)):
        sf.write(str(out / name), wave_, 24000, subtype="FLOAT")
    emit({"event": "chunk", "index": index, "of": len(job["chunks"]), "wav": name, "audio_s": round(n / 24000, 3),
          "gen_s": 0.01, "sample_rate": 24000, "peak": 0.1})
    if behavior == "slow":
        time.sleep(plan.get("delay", 0.4))
if behavior == "no_terminal":
    sys.exit(0)
emit({"event": "done", "chunks": len(job["chunks"]), "sample_rate": 24000, "device": "cuda:0"})
if behavior == "done_then_crash":
    sys.stderr.write("Fatal Python error during shutdown\n")
    sys.exit(9)
'''


@pytest.fixture()
def fake(tmp_path, monkeypatch):
    """A fake worker plus the keyword seams that point ``omnivoice_file_to_mp3`` at it; runtime state in the sandbox."""
    script = tmp_path / "fake_omnivoice_worker.py"
    script.write_text(FAKE_WORKER, encoding="utf-8")
    monkeypatch.setattr(ov, "runtime_dir", lambda: tmp_path / "runtime")
    jobs, prompts, log = tmp_path / "jobs", tmp_path / "prompts", tmp_path / "jobs.log"
    exported: dict = {}

    def fake_encoder(wav, mp3, bitrate, *, work_dir, cancel_check=None):
        data, rate = sf.read(str(wav), dtype="float32")
        exported.update(arr=data, rate=rate, work_dir=str(work_dir), bitrate=bitrate)
        Path(mp3).write_bytes(b"MP3-BYTES")

    class Harness:
        def __init__(self):
            self.tmp, self.jobs, self.logs, self.exported = tmp_path, jobs, [], exported

        def convert(self, text="One sentence here. Another sentence follows.", voice="omnivoice-male-2",
                    name="story.mp3", plan=None, **kwargs):
            source = tmp_path / "story.txt"
            source.write_text(text, encoding="utf-8")
            env = dict(os.environ)
            env["FAKE_OMNIVOICE"] = json.dumps(plan or {})
            env["FAKE_OMNIVOICE_LOG"] = str(log)
            kwargs.setdefault("grace_s", 1.0)
            kwargs.setdefault("event_timeout_s", 60.0)
            kwargs.setdefault("availability", lambda v: (True, "ok"))
            kwargs.setdefault("encoder", fake_encoder)
            return osy.omnivoice_file_to_mp3(
                str(source), str(tmp_path / name), voice, log=self.logs.append, python=Path(sys.executable),
                script=script, jobs_root=jobs, prompts_root=prompts, env=env, **kwargs)

        def jobs_seen(self) -> list[dict]:
            if not log.exists():
                return []
            return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]

        def leftovers(self) -> list[Path]:
            return [p for p in jobs.iterdir() if p.is_dir()] if jobs.is_dir() else []

    return Harness()


PARAGRAPHS = "\n\n".join(f"Paragraph number {i} says something quite different from the rest." for i in range(5))


# --------------------------------------------------------------------------- #
# The happy path: the text, the excerpt, the order, the pauses
# --------------------------------------------------------------------------- #
def test_a_conversion_runs_one_worker_assembles_with_the_local_policy_and_cleans_up(fake):
    fake.convert(text=PARAGRAPHS, chunk_pause_ms=700, bitrate="128k")
    assert (fake.tmp / "story.mp3").read_bytes() == b"MP3-BYTES"
    arr = fake.exported["arr"]
    speech = sum(int(RATE * (0.2 + 0.05 * i)) for i in range(5))
    assert abs(arr.size - (speech + 4 * int(RATE * 0.7))) <= int(RATE * 0.35)  # the tail policy may trim the end only
    assert fake.exported["bitrate"] == "128k"
    assert fake.leftovers() == [], "the job folder holds the user's text and never outlives the run"
    assert any("OmniVoice is running on the GPU: Fake GPU" in line for line in fake.logs)
    assert any("[omnivoice] a library banner" in line for line in fake.logs)


def test_the_worker_is_conditioned_only_on_the_reviewed_excerpt_and_its_own_transcript(fake):
    fake.convert(voice="omnivoice-female-2")
    (job,) = fake.jobs_seen()
    spec = ov.load_excerpts()["omnivoice-female-2"]
    assert job["excerpt"]["frames"] == spec.crop_end_frame <= 10 * RATE
    assert job["_excerpt_pcm_sha256"] == job["excerpt"]["pcm_sha256"] == spec.excerpt_pcm_sha256
    assert job["ref_text"] == spec.text != rt.load_bundle()["Female-2"]
    assert "Cloned-Voice-Uploads" not in json.dumps(job), "the worker never sees the full-length recording"
    key, identity = ov.prompt_identity(spec, model_revision=ov.load_manifest()["model"]["revision"],
                                       omnivoice_version="0.2.1", preprocess_prompt=True, dtype="float16")
    assert job["prompt_cache"]["key"] == key and job["prompt_cache"]["identity"] == identity
    assert Path(job["prompt_cache"]["path"]).name == f"omnivoice-female-2__{key[:24]}.pt"
    assert job["generation"] == osy.GENERATION and job["generation"]["num_step"] == 32
    assert (job["device"], job["dtype"], job["language"], job["omnivoice_version"]) == ("cuda", "float16", "English",
                                                                                         "0.2.1")
    assert job["engine_lock"] == str(ov.engine_lock_path()) and job["_isolated"] is True


def test_chunks_are_rendered_by_bounded_workers_and_assembled_in_plan_order(fake):
    progress: list[tuple[int, int]] = []
    fake.convert(text=PARAGRAPHS, chunks_per_worker=2, chunk_pause_ms=0, progress_callback=lambda d, t: progress.append((d, t)))
    jobs = fake.jobs_seen()
    assert [[c["index"] for c in job["chunks"]] for job in jobs] == [[0, 1], [2, 3], [4]], "a fresh worker per batch"
    assert progress == [(i, 5) for i in range(1, 6)]
    arr = fake.exported["arr"]
    starts = np.cumsum([0] + [int(RATE * (0.2 + 0.05 * i)) for i in range(4)])
    peaks = [float(np.abs(arr[s:s + 2400]).max()) for s in starts]
    assert peaks == sorted(peaks), "chunk k is amplitude 0.05*(k+1): the order is plan order"


def test_the_text_is_prepared_once_and_the_worker_speaks_exactly_that(fake, monkeypatch):
    calls: list[str] = []
    real_prepare = osy.prepare

    def counting(raw, snapshot, route):
        calls.append(route)
        return real_prepare(raw, snapshot, route)

    monkeypatch.setattr(osy, "prepare", counting)
    text = "Title: Book\n# Chapter 5\n\nDr. Smith paid $5 on March 5, 2024.\n\n" + PARAGRAPHS
    v1 = build_snapshot(SETTING_V1, user_dir=None)
    fake.convert(text=text, speech_prep=v1, chunks_per_worker=2)
    assert calls == ["omnivoice"], "one preparation per file, however many workers render it"
    spoken = [c["text"] for job in fake.jobs_seen() for c in job["chunks"]]
    expected = pipeline.prepare(text, v1, "omnivoice").text
    assert "".join("".join(spoken).split()) == "".join(expected.split())
    assert spoken[0] == "Chapter five" and "Doctor Smith paid five dollars on March fifth twenty twenty four." in spoken
    assert "Title" not in " ".join(spoken) and "$" not in " ".join(spoken) and "Book" not in " ".join(spoken)


def test_off_hands_the_source_text_through_structure_only(fake):
    fake.convert(text="# Chapter 5\n\nDr. Smith paid $5.", speech_prep=OFF)
    spoken = [c["text"] for c in fake.jobs_seen()[0]["chunks"]]
    assert spoken == ["Chapter 5", "Dr. Smith paid $5."]


def test_a_retry_renders_the_same_chunks_with_the_same_seeds(fake):
    v1 = build_snapshot(SETTING_V1, user_dir=None)
    fake.convert(text=PARAGRAPHS, speech_prep=v1)
    fake.convert(text=PARAGRAPHS, speech_prep=v1)
    first, second = fake.jobs_seen()
    assert first["chunks"] == second["chunks"] and len({c["seed"] for c in first["chunks"]}) == len(first["chunks"])
    other = osy.derive_seed("omnivoice-male-3", osy.plan_chunks(PARAGRAPHS)[0])
    assert other != first["chunks"][0]["seed"], "the voice is part of the seed"


def test_the_v1_chunks_map_back_to_the_decoded_source_in_order(monkeypatch, fake):
    seen = []
    real = osy._local.chunk_source_spans
    monkeypatch.setattr(osy._local, "chunk_source_spans", lambda prepared, chunks: seen.append(real(prepared, chunks)))
    fake.convert(text="﻿# Chapter IV\n\nIt cost $12.50 in 1999.\n\nPages 12-15 at 7:15 p.m.",
                 speech_prep=build_snapshot(SETTING_V1, user_dir=None))
    (spans,) = seen
    assert spans == sorted(spans) and all(a < b for a, b in spans)


def test_the_chunk_ceiling_is_the_omnivoice_profiles_and_never_crosses_a_paragraph():
    from tts.speech import profiles

    assert profiles.PROFILES["omnivoice"].max_chunk_chars == osy.OMNIVOICE_MAX_CHUNK_CHARS == 300
    long = " ".join(f"Sentence number {i} keeps the narration moving along steadily." for i in range(40))
    chunks = osy.plan_chunks(long + "\n\nA new paragraph.")
    assert max(len(c.text) for c in chunks) <= 300 and chunks[-1].text == "A new paragraph."
    assert osy.batches(list(range(100)), 48) == [list(range(48)), list(range(48, 96)), list(range(96, 100))]


# --------------------------------------------------------------------------- #
# Cancel: inference, encoding, publication
# --------------------------------------------------------------------------- #
def test_cancel_between_chunks_stops_the_worker_and_publishes_nothing(fake):
    def cancel_after_first_chunk() -> bool:
        return len([line for line in fake.logs if "OmniVoice chunk" in line]) >= 1

    with pytest.raises(ConversionCancelled):
        fake.convert(text=PARAGRAPHS, plan={"behavior": "slow", "delay": 0.5}, cancel_check=cancel_after_first_chunk)
    assert not (fake.tmp / "story.mp3").exists() and fake.leftovers() == []
    assert sum("OmniVoice chunk" in line for line in fake.logs) < 5, "stopped before the file was finished"


def test_a_worker_that_ignores_cancel_is_killed_after_the_grace_period(fake):
    started = time.monotonic()
    with pytest.raises(ConversionCancelled):
        fake.convert(text=PARAGRAPHS, plan={"behavior": "hang", "at": 1}, cancel_check=lambda: time.monotonic() - started > 1.5,
                     grace_s=0.5)
    assert time.monotonic() - started < 20 and not (fake.tmp / "story.mp3").exists() and fake.leftovers() == []


def test_cancel_during_the_encode_leaves_the_destination_alone(fake):
    destination = fake.tmp / "story.mp3"
    destination.write_bytes(b"THE OWNER'S EARLIER FILE")
    state = {"encoding": False}

    def slow_encoder(wav, mp3, bitrate, *, work_dir, cancel_check=None):
        state["encoding"] = True
        Path(mp3).write_bytes(b"HALF")
        while not cancel_check():
            time.sleep(0.01)
        raise ConversionCancelled("Conversion cancelled by user.")

    with pytest.raises(ConversionCancelled):
        fake.convert(encoder=slow_encoder, cancel_check=lambda: state["encoding"])
    assert destination.read_bytes() == b"THE OWNER'S EARLIER FILE" and fake.leftovers() == []
    assert not list(fake.tmp.glob("story.mp3.*.part"))


def test_a_cancel_at_the_instant_of_publication_still_wins(fake):
    destination = fake.tmp / "story.mp3"
    destination.write_bytes(b"THE OWNER'S EARLIER FILE")
    state = {"encoded": False}

    def encoder(wav, mp3, bitrate, *, work_dir, cancel_check=None):
        Path(mp3).write_bytes(b"NEW")
        state["encoded"] = True

    with pytest.raises(ConversionCancelled):
        fake.convert(encoder=encoder, cancel_check=lambda: state["encoded"])
    assert destination.read_bytes() == b"THE OWNER'S EARLIER FILE"
    assert not list(fake.tmp.glob("story.mp3.*.part"))


# --------------------------------------------------------------------------- #
# Failures: a plain sentence, nothing published, nothing clobbered
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("plan, message", [
    ({"behavior": "fail", "at": 0, "message": "RuntimeError: kaboom"}, "failed while generating speech: RuntimeError: kaboom"),
    ({"behavior": "fail", "at": 0, "message": "CUDA out of memory", "oom": True}, "ran out of GPU memory"),
    ({"behavior": "no_gpu"}, "need an NVIDIA graphics card"),
    ({"behavior": "exit_early"}, "ended unexpectedly \\(exit code 3\\). CUDA error"),
    ({"behavior": "no_terminal"}, "ended unexpectedly"),
    ({"behavior": "done_then_crash"}, "did not exit cleanly"),
    ({"behavior": "malformed"}, "unreadable message"),
    ({"behavior": "missing_file", "at": 1}, "chunk 2 was reported but its audio file is missing"),
    ({"behavior": "nan", "at": 0}, "chunk 1 could not be used"),
], ids=["generate", "oom", "no-gpu", "exit-early", "no-terminal", "done-then-crash", "malformed", "missing-file", "nan"])
def test_a_failed_file_says_why_publishes_nothing_and_keeps_an_existing_output(fake, plan, message):
    destination = fake.tmp / "story.mp3"
    destination.write_bytes(b"THE OWNER'S EARLIER FILE")
    with pytest.raises(osy.OmniVoiceFailed, match=message):
        fake.convert(text=PARAGRAPHS, plan=plan)
    assert destination.read_bytes() == b"THE OWNER'S EARLIER FILE" and fake.leftovers() == []
    assert (fake.jobs / "last-failure.txt").is_file(), "the diagnostic, without the job text"


def test_an_unavailable_voice_stops_before_anything_is_prepared_or_started(fake):
    with pytest.raises(ov.OmniVoiceUnavailable, match="not installed"):
        fake.convert(availability=lambda v: (False, ov.NOT_INSTALLED_MESSAGE))
    assert fake.jobs_seen() == [] and not fake.jobs.exists()


def test_a_busy_engine_is_refused_not_waited_for(fake):
    with ov.inference_lease():
        with pytest.raises(ov.OmniVoiceUnavailable, match="installed or repaired, or another conversion"):
            fake.convert()
    fake.convert()  # released, by the block's end


def test_the_worker_refuses_a_job_that_could_reach_the_network_or_load_whisper(tmp_path):
    from tts import omnivoice_worker as w

    model = tmp_path / "model"
    (model / "audio_tokenizer").mkdir(parents=True)
    (model / "config.json").write_text("{}", encoding="utf-8")
    (model / "audio_tokenizer" / "config.json").write_text("{}", encoding="utf-8")
    excerpt = tmp_path / "e.wav"
    with wave.open(str(excerpt), "wb") as out:
        out.setnchannels(1), out.setsampwidth(2), out.setframerate(RATE), out.writeframes(b"\0\0" * 100)
    good = {"schema": 1, "kind": "synth", "voice_id": "omnivoice-male-1", "model_dir": str(model),
            "omnivoice_version": "0.2.1", "language": "English", "dtype": "float16", "device": "cuda",
            "out_dir": str(tmp_path / "o"), "cancel_file": str(tmp_path / "c"), "engine_lock": str(tmp_path / "l"),
            "excerpt": {"wav": str(excerpt), "frames": 100, "sample_rate": RATE, "pcm_sha256": "0" * 64},
            "ref_text": "Zeth,", "prompt_cache": None, "generation": dict(osy.GENERATION),
            "chunks": [{"index": 0, "text": "Hello.", "seed": 1}]}
    offline = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    assert w.job_problems(good, offline) == []
    for change, expected in [({"ref_text": " "}, "speech recognizer"), ({"device": "cpu"}, "GPU only"),
                             ({"generation": {"num_step": 32, "asr": True}}, "OmniVoiceGenerationConfig"),
                             ({"excerpt": {**good["excerpt"], "frames": 10 * RATE + 1}}, "first 10 seconds"),
                             ({"chunks": []}, "chunks")]:
        assert any(expected in p for p in w.job_problems({**good, **change}, offline)), change
    (model / "audio_tokenizer" / "config.json").unlink()
    assert any("would fetch one" in p for p in w.job_problems(good, offline))
    assert w.job_problems(good, {})[0] == "HF_HUB_OFFLINE is not 1"


def test_a_cached_prompt_is_loaded_only_when_it_is_this_apps_own_for_exactly_this_identity(tmp_path):
    from tts import omnivoice_worker as w

    class Prompt:
        def __init__(self, ref_text):
            self.ref_text = ref_text

        @classmethod
        def load(cls, path, map_location="cpu"):
            return cls(Path(path).read_text(encoding="utf-8"))

        def save(self, path):
            Path(path).write_text(self.ref_text, encoding="utf-8")

    cache = {"path": str(tmp_path / "p" / "voice.pt"), "key": "k" * 64, "identity": {"crop": [0, 100, RATE]}}
    assert w.load_cached_prompt(cache, Prompt) is None  # nothing there yet
    w.save_prompt(Prompt("Zeth, Sun Sun."), cache)
    assert w.load_cached_prompt(cache, Prompt).ref_text == "Zeth, Sun Sun."
    assert w.load_cached_prompt({**cache, "identity": {"crop": [0, 99, RATE]}}, Prompt) is None
    assert w.load_cached_prompt({**cache, "key": "x" * 64}, Prompt) is None
    Path(cache["path"]).write_text("planted", encoding="utf-8")  # bytes that are not the recorded ones
    assert w.load_cached_prompt(cache, Prompt) is None
    assert sorted(p.name for p in (tmp_path / "p").iterdir()) == ["voice.pt", "voice.pt.identity.json"]


# --------------------------------------------------------------------------- #
# The panel's route: the snapshot only when on, publication never over an existing file
# --------------------------------------------------------------------------- #
def test_the_panel_routes_omnivoice_through_publication_and_refuses_to_clobber(tmp_path, monkeypatch):
    from tts import epub2tts_gui as gui
    from tts import publication

    calls: list[dict] = []

    def engine(text_path, output_path, **kwargs):
        calls.append(kwargs)
        Path(output_path).write_bytes(b"mp3")

    monkeypatch.setattr(osy, "omnivoice_file_to_mp3", engine)
    source = tmp_path / "a.txt"
    source.write_text("Words.", encoding="utf-8")
    destination = tmp_path / "out" / "a-OmniVoice - Male 1.mp3"
    item = {"item_id": "1", "source": source, "destination": destination}
    params = {"voice_id": "omnivoice-male-1", "end_pause": 0, "paragraph_pause": 700, "bitrate": "128k",
              "speech_prep": OFF, "overwrite": False}
    gui.convert_with_omnivoice(item, params, None, lambda m: None, lambda: False)
    assert destination.read_bytes() == b"mp3"
    assert calls[0]["voice_id"] == "omnivoice-male-1" and calls[0]["chunk_pause_ms"] == 700
    assert "speech_prep" not in calls[0]
    with pytest.raises(publication.DestinationExists):  # the same name again, overwrite off: refused before the engine
        gui.convert_with_omnivoice(item, params, None, lambda m: None, lambda: False)
    assert len(calls) == 1 and destination.read_bytes() == b"mp3"


def test_the_panel_asks_the_omnivoice_seam_and_never_crashes_on_it(monkeypatch):
    from tts import epub2tts_gui as gui

    monkeypatch.setattr(ov, "voice_availability", lambda voice_id: (False, f"why {voice_id}"))
    assert gui.omnivoice_status("omnivoice-male-4") == (False, "why omnivoice-male-4")

    def broken(voice_id):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(ov, "voice_availability", broken)
    ok, reason = gui.omnivoice_status("omnivoice-male-4")
    assert not ok and "disk on fire" in reason and "Every other voice is unaffected" in reason
