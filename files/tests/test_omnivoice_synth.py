"""v0.8.0 Phase 2 -- the OmniVoice conversion path, against a fake worker.

The real worker needs a 3.3 GB model, a GPU and a second Python environment; these tests need none of them. A stand-in
script speaks the same ``@@EVENT`` protocol (and misbehaves on request), so the supervising side is exercised with the
real subprocess, pipe, Job Object and kill machinery: the text it is given (prepared once, never again), the voice's
own approved recording (whole, 44.1 kHz) and owner-written transcript it is conditioned on, chunk order across
bounded workers, Cancel at every stage, failures,
no-clobber publication and retry determinism.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
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


reference_sha256 = hashlib.sha256(Path(job["reference"]["wav"]).read_bytes()).hexdigest()
log = os.environ.get("FAKE_OMNIVOICE_LOG")
if log:
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({**job, "_reference_sha256": reference_sha256, "_argv": sys.argv[1:],
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
if behavior == "stubborn":  # CX-2: ignores SIGTERM and the cancel flag, blocked as if inside a native call
    import signal
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    group = os.getpgrp() if hasattr(os, "getpgrp") else None
    Path(plan["pidfile"]).write_text(json.dumps({"pid": os.getpid(), "pgid": group}), encoding="utf-8")
    emit({"event": "loaded", "device": "cuda:0", "device_name": "Fake GPU", "load_s": 0.01, "prompt": "built",
          "prompt_s": 0.01, "chunks": len(job["chunks"])})
    time.sleep(120)
if behavior == "import_error":  # as the real worker reports a package that does not import during a conversion
    emit({"event": "failed", "stage": plan.get("stage", "worker"), "message": plan.get("message", "ImportError: cannot "
          "import name 'OmniVoice' from 'omnivoice' (unknown location)")})
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
            kwargs.setdefault("script", script)  # R1: the real worker beside a stand-in stack (stack_worker) instead
            return osy.omnivoice_file_to_mp3(
                str(source), str(tmp_path / name), voice, log=self.logs.append, python=Path(sys.executable),
                jobs_root=jobs, prompts_root=prompts, env=env, **kwargs)

        def jobs_seen(self) -> list[dict]:
            if not log.exists():
                return []
            return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]

        def leftovers(self) -> list[Path]:
            return [p for p in jobs.iterdir() if p.is_dir()] if jobs.is_dir() else []

    return Harness()


PARAGRAPHS = "\n\n".join(f"Paragraph number {i} says something quite different from the rest." for i in range(5))


# --------------------------------------------------------------------------- #
# The happy path: the text, the reference, the order, the pauses
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


def test_the_worker_is_conditioned_on_the_voices_own_whole_recording_and_its_owner_transcript(fake, monkeypatch):
    monkeypatch.setattr(ov, "_system", lambda: "win32")  # the released Windows job, asked on any host (macOS P4B seam)
    fake.convert(voice="omnivoice-female-2")
    (job,) = fake.jobs_seen()
    voice, spec = ov.get_voice("omnivoice-female-2"), ov.load_references()["omnivoice-female-2"]
    assert job["reference"] == {"wav": str(ov.reference_path(voice)), "wav_sha256": voice.reference_sha256,
                                "frames": 320414, "sample_rate": 44100, "max_frames": 10 * 44100}
    assert job["_reference_sha256"] == voice.reference_sha256, "the worker read exactly the approved bytes"
    assert Path(job["reference"]["wav"]).parent.name == "OmniVoice", "never the Chatterbox or Qwen3 recording"
    assert "excerpt" not in job and not any("excerpt" in line for line in fake.logs), "no second crop, no copy"
    assert job["ref_text"] == spec.text == ("Vice Chancellor Cloud Legan Barth, his direct superior, the Lord "
                                            "Chancellor Marquess Joric Reclentos")
    assert not rt.load_bundle()["Female-2"].startswith(job["ref_text"]), "its own text, not the Qwen3 transcript"
    key, identity = ov.prompt_identity(spec, model_revision=ov.load_manifest()["model"]["revision"],
                                       omnivoice_version="0.2.1", preprocess_prompt=True, dtype="float16")
    assert job["prompt_cache"]["key"] == key and job["prompt_cache"]["identity"] == identity
    assert Path(job["prompt_cache"]["path"]).name == f"omnivoice-female-2__{key[:24]}.pt"
    assert job["generation"] == osy.GENERATION and job["generation"]["num_step"] == 32
    assert (job["device"], job["dtype"], job["language"], job["omnivoice_version"]) == ("cuda", "float16", "English",
                                                                                         "0.2.1")
    assert job["engine_lock"] == str(ov.engine_lock_path()) and job["_isolated"] is True


def test_the_one_longer_reference_reaches_the_worker_with_its_own_exact_limit(fake):
    """OmniVoice - Male 1 (owner exception, 10.227 s) goes to the worker whole; every other voice is capped at 10 s."""
    fake.convert(voice="omnivoice-male-1")
    (job,) = fake.jobs_seen()
    assert (job["reference"]["frames"], job["reference"]["max_frames"], job["reference"]["sample_rate"]) == (
        451022, 451022, 44100)
    assert any("reference 10.227 s at 44100 Hz, used whole" in line for line in fake.logs)


def test_a_changed_recording_is_refused_before_any_worker_starts(fake, monkeypatch):
    changed = fake.tmp / "changed.wav"
    data = bytearray(ov.reference_path(ov.get_voice("omnivoice-male-3")).read_bytes())
    data[-10] ^= 0xFF
    changed.write_bytes(bytes(data))
    monkeypatch.setattr(ov, "reference_path", lambda voice: changed)
    with pytest.raises(ov.OmniVoiceUnavailable, match="its reference recording cannot be used"):
        fake.convert(voice="omnivoice-male-3")
    assert fake.jobs_seen() == [] and fake.leftovers() == []


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


def test_the_worker_bound_is_the_released_48_except_on_a_mac_s_gpu():
    """macOS P4B memory checkpoint: on MPS a worker's footprint grows with every chunk of a new shape (the allocator's
    kept GPU buffers and per-shape heap state; the live tensors stay flat), so a Mac's GPU hands over to a fresh worker
    after 16 chunks. Windows (CUDA) and a Mac's processor keep the released 48."""
    assert osy.CHUNKS_PER_WORKER == 48 and osy.MPS_CHUNKS_PER_WORKER == 16
    assert osy.chunks_per_worker_for(ov.DevicePolicy(ov.WINDOWS_DEVICE, ov.WINDOWS_DTYPE, "windows")) == 48
    assert osy.chunks_per_worker_for(ov.DevicePolicy(ov.DEVICE_MPS, ov.MAC_DTYPE, "default")) == 16
    assert osy.chunks_per_worker_for(ov.DevicePolicy(ov.DEVICE_CPU, ov.MAC_DTYPE, "config.toml")) == 48


@pytest.mark.parametrize("system, device, sizes", [
    ("win32", None, [48, 2]),  # Windows, as released
    ("darwin", "mps", [16, 16, 16, 2]),
    ("darwin", "cpu", [48, 2]),
])
def test_without_the_seam_each_run_uses_its_device_s_worker_bound_in_plan_order(fake, monkeypatch, system, device,
                                                                                  sizes):
    """The entry point's default asks the run's own device policy (once per file): 50 chunks go to fresh workers in
    batches of that bound, every chunk exactly once and in plan order across each hand-over."""
    monkeypatch.setattr(ov, "_system", lambda: system)
    if device is not None:
        monkeypatch.setattr(ov, "configured_mac_device", lambda: (device, "default"))
    text = "\n\n".join(f"Paragraph number {i} says something quite different from the rest." for i in range(50))
    fake.convert(text=text, speech_prep=OFF)
    jobs = fake.jobs_seen()
    assert [len(job["chunks"]) for job in jobs] == sizes
    assert [c["index"] for job in jobs for c in job["chunks"]] == list(range(50))
    assert {job["device"] for job in jobs} == {device or ov.WINDOWS_DEVICE}
    assert fake.leftovers() == []


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


def test_a_cancel_after_the_commit_point_keeps_the_whole_file_and_reports_it(fake):
    """CX-8, the other order (plan section 11.2.3): a Cancel that arrives once the rename has happened finds the whole
    file published; it is kept and reported as saved, never half-removed and never left as a temporary."""
    destination = fake.tmp / "story.mp3"
    fake.convert(cancel_check=destination.exists)
    assert destination.read_bytes() == b"MP3-BYTES"
    assert any("OmniVoice: saved ->" in line for line in fake.logs)
    assert not list(fake.tmp.glob("story.mp3.*.part")) and fake.leftovers() == []


def test_a_worker_that_ignores_sigterm_and_the_flag_is_ended_within_the_omnivoice_bound(fake, tmp_path):
    """CX-2 (macOS P4B): a worker that ignores the cancel flag and SIGTERM, blocked as if in a native call, is ended by
    the supervisor's kill after the production 2 s grace, within the OmniVoice T_stop of 4 s (plan section 11.2.1),
    through the platform's own containment (on a Mac a class-A child in its own group, which is then empty)."""
    pidfile = tmp_path / "stubborn.json"
    latched: dict = {}

    def cancel_once_running() -> bool:
        if "at" not in latched and pidfile.exists():
            latched["at"] = time.monotonic()
        return "at" in latched

    with pytest.raises(ConversionCancelled):
        fake.convert(plan={"behavior": "stubborn", "pidfile": str(pidfile)}, cancel_check=cancel_once_running,
                     grace_s=osy.CANCEL_GRACE_S)
    stopped = time.monotonic() - latched["at"]
    assert stopped <= 4.0, f"stopped {stopped:.2f} s after the Cancel (bound 4 s)"
    worker = json.loads(pidfile.read_text(encoding="utf-8"))
    if sys.platform != "win32":
        assert worker["pgid"] == worker["pid"], "a class-A child leads its own process group"
        with pytest.raises(ProcessLookupError):
            os.killpg(worker["pgid"], 0)  # nothing of the worker's group is left
    assert not (fake.tmp / "story.mp3").exists() and fake.leftovers() == []


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
def test_a_failed_file_says_why_publishes_nothing_and_keeps_an_existing_output(fake, plan, message, monkeypatch):
    monkeypatch.setattr(ov, "_system", lambda: "win32")  # Windows' sentences, as released (a Mac's: the test below)
    destination = fake.tmp / "story.mp3"
    destination.write_bytes(b"THE OWNER'S EARLIER FILE")
    with pytest.raises(osy.OmniVoiceFailed, match=message):
        fake.convert(text=PARAGRAPHS, plan=plan)
    assert destination.read_bytes() == b"THE OWNER'S EARLIER FILE" and fake.leftovers() == []
    assert (fake.jobs / "last-failure.txt").is_file(), "the diagnostic, without the job text"


@pytest.mark.parametrize("plan, message", [
    ({"behavior": "fail", "at": 0, "message": "MPS backend out of memory", "oom": True},
     "ran out of memory \\(on a Mac the GPU shares the computer's memory\\)"),
    ({"behavior": "no_gpu"}, "never moves to the processor on its own"),
], ids=["oom", "no-gpu"])
def test_on_a_mac_a_failed_file_says_why_in_the_mac_s_words(fake, plan, message, monkeypatch):
    """macOS P4B: the Mac's sentences -- memory the GPU shares, and a GPU that cannot be used, which is never answered by
    moving to the processor -- with the same guarantees: nothing published, nothing clobbered."""
    monkeypatch.setattr(ov, "_system", lambda: "darwin")
    destination = fake.tmp / "story.mp3"
    destination.write_bytes(b"THE OWNER'S EARLIER FILE")
    with pytest.raises(osy.OmniVoiceFailed, match=message) as failed:
        fake.convert(text=PARAGRAPHS, plan=plan)
    assert "NVIDIA" not in str(failed.value) and "graphics card" not in str(failed.value)
    assert destination.read_bytes() == b"THE OWNER'S EARLIER FILE" and fake.leftovers() == []


@pytest.mark.parametrize("choice, device", [(None, "mps"), ("cpu", "cpu")])
def test_on_a_mac_the_job_and_the_prompt_identity_carry_the_accepted_device(fake, monkeypatch, choice, device):
    """macOS P4B: the run's device comes from the policy once per file -- the Mac's GPU by default, the processor by
    explicit choice, both float32 -- and goes into the job and into the clone prompt's identity, so a prompt made on one
    device is never reused on another or as a CUDA prompt. The log says where it runs and who chose it."""
    monkeypatch.setattr(ov, "_system", lambda: "darwin")
    if choice is not None:
        monkeypatch.setattr(ov, "configured_mac_device", lambda: (choice, "config.toml"))
    else:
        monkeypatch.setattr(ov, "configured_mac_device", lambda: ("mps", "default"))
    fake.convert(voice="omnivoice-female-2")
    (job,) = fake.jobs_seen()
    assert (job["device"], job["dtype"]) == (device, "float32")
    spec = ov.load_references()["omnivoice-female-2"]
    key, identity = ov.prompt_identity(spec, model_revision=ov.load_manifest()["model"]["revision"],
                                       omnivoice_version="0.2.1", preprocess_prompt=True, dtype="float32",
                                       device=device)
    assert job["prompt_cache"]["key"] == key and job["prompt_cache"]["identity"]["device"] == device
    cuda_key, _ = ov.prompt_identity(spec, model_revision=ov.load_manifest()["model"]["revision"],
                                     omnivoice_version="0.2.1", preprocess_prompt=True, dtype="float32")
    assert key != cuda_key, "a Mac prompt never collides with a CUDA prompt"
    said = "the default" if choice is None else "chosen in config.toml"
    assert any(line.startswith("OmniVoice device: ") and said in line for line in fake.logs), fake.logs


def test_on_a_mac_a_refused_device_choice_stops_before_any_worker_starts(fake, monkeypatch):
    """No guess and no fallback: a device the owner did not accept (MPS float16 is not even a value) stops the file
    before a job folder or a worker exists."""
    monkeypatch.setattr(ov, "_system", lambda: "darwin")
    monkeypatch.setattr(ov, "configured_mac_device", lambda: ("cuda", "config.toml"))
    with pytest.raises(ov.OmniVoiceUnavailable, match="runs only on mps or cpu"):
        fake.convert()
    assert fake.jobs_seen() == [] and fake.leftovers() == []


def test_a_worker_whose_packages_do_not_import_has_the_engine_recorded_as_damaged_and_says_how_to_repair(fake, monkeypatch):
    """Unified .venv layout acceptance, 2026-11-13: on a real copy with one package file deleted the engine stayed
    "ready", every conversion failed and nothing offered a repair. The conversion now records such a failure."""
    recorded: list[str] = []
    answer = {"recorded": True}

    def reject(reason):
        recorded.append(reason)
        return answer["recorded"]

    monkeypatch.setattr(ov, "reject_ready_engine", reject)
    with pytest.raises(osy.OmniVoiceFailed) as failed:
        fake.convert(plan={"behavior": "import_error"})
    assert recorded == ["ImportError: cannot import name 'OmniVoice' from 'omnivoice' (unknown location)"]
    assert str(failed.value).endswith(osy.REPAIR_OFFERED_NOTE) and "Install & Continue" in str(failed.value)
    assert "failed while running: ImportError" in str(failed.value)
    with pytest.raises(osy.OmniVoiceFailed, match="failed while starting the voice engine: ModuleNotFoundError") as failed:
        fake.convert(plan={"behavior": "import_error", "stage": "import", "message": "ModuleNotFoundError: No module "
                                                                                     "named 'torch'"})
    assert recorded[-1].startswith("ModuleNotFoundError") and str(failed.value).endswith(osy.REPAIR_OFFERED_NOTE)
    with pytest.raises(osy.OmniVoiceFailed, match="failed while running: RuntimeError"):
        fake.convert(plan={"behavior": "import_error", "message": "RuntimeError: something else entirely"})
    assert len(recorded) == 2, "a worker failure that is not an import failure condemns nothing"

    answer["recorded"] = False  # the engine was not this app's ready one (or the record could not be written)
    with pytest.raises(osy.OmniVoiceFailed) as failed:
        fake.convert(plan={"behavior": "import_error"})
    assert osy.REPAIR_OFFERED_NOTE not in str(failed.value) and "look damaged" in str(failed.value)

    del recorded[:]
    for plan in ({"behavior": "fail", "at": 0, "message": "RuntimeError: kaboom"}, {"behavior": "no_gpu"},
                 {"behavior": "fail", "at": 0, "message": "CUDA out of memory", "oom": True}, {"behavior": "exit_early"},
                 {"behavior": "import_error", "message": "ImportError: DLL load failed while importing _C: An "
                                                         "Application Control policy has blocked this file."}):
        with pytest.raises(osy.OmniVoiceFailed):
            fake.convert(plan=plan)
    assert recorded == [], "a GPU, memory, generation or Smart App Control failure never condemns the environment"


# --------------------------------------------------------------------------- #
# v0.8.0 independent review R1: the REAL worker's startup imports, classified where they fail
# --------------------------------------------------------------------------- #
#: Stand-ins for PyTorch and OmniVoice, loaded by a copy of the REAL worker (:func:`stack_worker`): nothing heavy is
#: ever imported and no real library is touched. ``ACT_FAKE_STACK`` says where they fail and how. PyTorch's own Windows
#: loader reports a library it cannot load with ``ctypes.WinError``: an ``OSError`` carrying the Windows error number.
FAKE_TORCH = r'''
import json, os, socket

PLAN = json.loads(os.environ.get("ACT_FAKE_STACK", "{}"))


def fail(plan=PLAN):
    kind, text = plan["kind"], plan.get("text", "")
    if kind == "oserror":
        error = OSError(None, text, None, plan["winerror"])  # what ctypes.WinError(code) builds on Windows
        if getattr(error, "winerror", None) != plan["winerror"]:
            error.winerror = plan["winerror"]  # elsewhere OSError has no such member
        raise error
    if kind == "importerror":
        raise ImportError(text)
    if kind == "modulenotfound":
        raise ModuleNotFoundError(text)
    if kind == "memoryerror":
        raise MemoryError()
    if kind == "runtimeerror":
        raise RuntimeError(text)
    if kind == "network":  # a library that reaches for the network while it is imported
        socket.getaddrinfo("download.pytorch.org", 443)
    if kind == "wrapped-network":  # ... and one that wraps what it met, as lazy importers do
        try:
            socket.getaddrinfo("download.pytorch.org", 443)
        except Exception as exc:
            raise RuntimeError("Failed to import a submodule because of the following error") from exc
    raise AssertionError(f"unknown failure {kind!r}")


if PLAN.get("at") == "torch":
    fail()

float16 = "float16"
float32 = "float32"


class _Properties:
    name, total_memory = "Stand-in GPU", 12 * 2**30


class cuda:
    is_available = staticmethod(lambda: PLAN.get("gpu", True))
    device_count = staticmethod(lambda: 1 if PLAN.get("gpu", True) else 0)
    synchronize = staticmethod(lambda: None)
    manual_seed_all = staticmethod(lambda seed: None)
    memory_allocated = memory_reserved = max_memory_allocated = max_memory_reserved = staticmethod(lambda i=0: 0)
    get_device_properties = staticmethod(lambda i: _Properties())


class backends:  # macOS P4B: the Mac's GPU, as MPS reports it
    class mps:
        is_available = staticmethod(lambda: PLAN.get("gpu", True))
        is_built = staticmethod(lambda: True)


class mps:
    synchronize = staticmethod(lambda: None)
    empty_cache = staticmethod(lambda: None)
    current_allocated_memory = driver_allocated_memory = staticmethod(lambda: 0)


def manual_seed(seed):
    pass


def from_numpy(array):
    return array
'''
FAKE_OMNIVOICE = r'''
import torch

if torch.PLAN.get("at") == "omnivoice":
    torch.fail()

__version__ = "0.2.1"


class OmniVoiceGenerationConfig:
    def __init__(self, **settings):
        self.preprocess_prompt = settings.get("preprocess_prompt", True)


class VoiceClonePrompt:
    def __init__(self, ref_text):
        self.ref_text = ref_text


class _Device:
    def __init__(self, kind):
        self.type = kind


class _Parameter:
    def __init__(self, device, dtype):
        self.device, self.dtype = _Device(device), "torch." + dtype

    def is_floating_point(self):
        return True


class OmniVoice:
    sampling_rate = 24000

    @classmethod
    def from_pretrained(cls, *args, **kwargs):
        if torch.PLAN.get("at") == "load":
            torch.fail()
        model = cls()
        model.device = str(kwargs.get("device_map", "cuda:0")).split(":")[0]
        model.dtype = str(kwargs.get("dtype"))
        return model

    def named_parameters(self):
        """Where upstream places the weights: the backbone on the asked device, the audio tokenizer on the CPU under
        MPS (``torch.PLAN["misplaced"]`` puts the backbone on the CPU instead: a silent fallback)."""
        backbone = "cpu" if torch.PLAN.get("misplaced") else self.device
        tokenizer = "cpu" if self.device == "mps" else self.device
        yield "llm.weight", _Parameter(backbone, self.dtype)
        yield "audio_tokenizer.weight", _Parameter(tokenizer, self.dtype)

    def create_voice_clone_prompt(self, ref_audio, ref_text, preprocess_prompt):
        return VoiceClonePrompt(ref_text)

    def generate(self, **kwargs):
        if torch.PLAN.get("at") == "generate":
            torch.fail()
        import numpy as np
        return [np.full(2400, 0.01, dtype="float32")]
'''
#: ``-I`` (as production starts the worker) does not put the script's own folder on ``sys.path`` (Python 3.11+), so the
#: launcher puts the stand-ins there explicitly -- otherwise the app environment's real PyTorch would be imported.
STACK_LAUNCHER = r'''
import os, runpy, sys
STACK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stack")
sys.path.insert(0, STACK)
sys.argv[0] = os.path.join(STACK, "omnivoice_worker.py")
runpy.run_path(sys.argv[0], run_name="__main__")
'''
OFFLINE = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
#: macOS P4B: the real worker in its subprocess sees the real platform, so the stand-in jobs name this host's own
#: configuration -- Windows' CUDA float16 as released, a Mac's accepted MPS float32. Each platform runs its own branch.
HOST_DEVICE, HOST_DTYPE = ("mps", "float32") if sys.platform == "darwin" else ("cuda", "float16")
DLL_193 = {"at": "torch", "kind": "oserror", "winerror": 193,
           "text": 'Error loading "torch\\lib\\torch_cpu.dll" or one of its dependencies.'}
DLL_126 = {"at": "torch", "kind": "oserror", "winerror": 126,
           "text": 'The specified module could not be found. Error loading "torch\\lib\\c10.dll" or one of its '
                   'dependencies.'}
PAGING_1455 = {"at": "torch", "kind": "oserror", "winerror": 1455,
               "text": 'The paging file is too small for this operation to complete. Error loading '
                       '"torch\\lib\\cudnn64_9.dll" or one of its dependencies.'}
SAC_4551 = {"at": "torch", "kind": "oserror", "winerror": 4551,
            "text": "An Application Control policy has blocked this file."}
NETWORK_AT_IMPORT = {"at": "torch", "kind": "network"}


def stack_worker(folder: Path) -> Path:
    """A byte-for-byte copy of the REAL worker beside the stand-in stack; returns the launcher to start it with."""
    from tts import omnivoice_worker

    stack = folder / "stack"
    stack.mkdir(parents=True, exist_ok=True)
    (stack / "omnivoice_worker.py").write_bytes(Path(omnivoice_worker.__file__).read_bytes())
    for name, source in (("torch", FAKE_TORCH), ("omnivoice", FAKE_OMNIVOICE)):
        (stack / name).mkdir(exist_ok=True)
        (stack / name / "__init__.py").write_text(source, encoding="utf-8")
    launcher = folder / "launch_worker.py"
    launcher.write_text(STACK_LAUNCHER, encoding="utf-8")
    return launcher


def synth_job(folder: Path) -> dict:
    """A well-formed synth job (``job_problems`` finds nothing) whose every file lives in *folder*."""
    model = folder / "model"
    (model / "audio_tokenizer").mkdir(parents=True, exist_ok=True)
    (model / "config.json").write_text("{}", encoding="utf-8")
    (model / "audio_tokenizer" / "config.json").write_text("{}", encoding="utf-8")
    reference = folder / "r.wav"
    with wave.open(str(reference), "wb") as out:
        out.setnchannels(1), out.setsampwidth(2), out.setframerate(44100), out.writeframes(b"\0\0" * 100)
    return {"schema": 1, "kind": "synth", "voice_id": "omnivoice-male-1", "model_dir": str(model),
            "omnivoice_version": "0.2.1", "language": "English", "dtype": HOST_DTYPE, "device": HOST_DEVICE,
            "out_dir": str(folder / "chunks"), "cancel_file": str(folder / "cancel"),
            "engine_lock": str(folder / "engine.lock"),
            "reference": {"wav": str(reference), "wav_sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
                          "frames": 100, "sample_rate": 44100, "max_frames": 441000},
            "ref_text": "Zeth,", "prompt_cache": None, "generation": dict(osy.GENERATION),
            "chunks": [{"index": 0, "text": "Hello.", "seed": 1}]}


def probe_job(folder: Path) -> dict:
    """A well-formed installer ``probe`` job for this very interpreter's environment (it passes the version and
    isolation checks, so the run reaches the imports)."""
    from importlib import metadata

    job = synth_job(folder)
    return {"schema": 1, "kind": "probe", "model_dir": job["model_dir"], "omnivoice_version": "0.2.1",
            "dtype": HOST_DTYPE, "device": HOST_DEVICE, "engine_lock": job["engine_lock"],
            "packages": {"numpy": metadata.version("numpy")}, "environment": sys.prefix, "foreign": []}


def run_stack_worker(folder: Path, plan: dict, *, offline: bool = True, cancel: bool = False,
                     hold_lock: bool = False, probe: bool = False) -> tuple[int, list[dict]]:
    """Start the real worker (through :func:`stack_worker`) in a fresh ``-I`` interpreter; its exit code and events."""
    launcher, job = stack_worker(folder), (probe_job(folder) if probe else synth_job(folder))
    job_path = folder / "job.json"
    job_path.write_text(json.dumps(job), encoding="utf-8")
    if cancel:
        Path(job["cancel_file"]).write_text("cancel", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k.upper() not in OFFLINE}
    env.update(OFFLINE if offline else {})
    env["ACT_FAKE_STACK"] = json.dumps(plan)
    lock = rt.FileLock(Path(job["engine_lock"])) if hold_lock else None
    try:
        if lock is not None:
            assert lock.acquire()
        done = subprocess.run([sys.executable, "-I", str(launcher), str(job_path)], capture_output=True, text=True,
                              env=env, cwd=str(folder), timeout=120,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    finally:
        if lock is not None:
            lock.release()
    events = [json.loads(line[len("@@EVENT "):]) for line in done.stdout.splitlines() if line.startswith("@@EVENT ")]
    return done.returncode, events


def test_the_stand_in_stack_lets_the_real_worker_render_so_its_failures_are_not_for_a_wrong_reason(tmp_path):
    """The positive control for the R1 matrix below: with nothing failing, the real worker loads the stand-ins (never
    the app's real PyTorch), renders its chunk and ends ``done``."""
    code, events = run_stack_worker(tmp_path, {})
    assert code == 0 and [e["event"] for e in events] == ["loaded", "chunk", "done"], events
    if HOST_DEVICE == "cuda":
        assert events[0]["device_name"] == "Stand-in GPU"
    else:  # a Mac: the chip by name, the device and dtype said, and the memory the run used
        assert events[0]["device_name"].endswith("GPU (MPS)") and events[0]["device"] == "mps", events[0]
        assert events[0]["dtype"] == "float32" and events[-1]["device"] == "mps" and "peak_footprint_mib" in events[-1]
    assert (tmp_path / "chunks" / "chunk-0001.wav").is_file()


def test_on_a_mac_a_model_that_lands_anywhere_but_where_it_was_asked_is_refused_not_used():
    """macOS P4B, no silent fallback: the worker's placement guard (pure; the same check runs after every Mac load).
    The backbone must be entirely on the asked device in the asked dtype; the audio tokenizer stays on the CPU under MPS
    (where upstream places it) and is on the CPU on the CPU."""
    from tts import omnivoice_worker as w

    class Param:
        def __init__(self, device, dtype="torch.float32"):
            self.device, self.dtype = type("D", (), {"type": device})(), dtype

        def is_floating_point(self):
            return True

    class Model:
        def __init__(self, *pairs):
            self.pairs = pairs

        def named_parameters(self):
            return iter(self.pairs)

    good_mps = Model(("llm.w", Param("mps")), ("audio_tokenizer.w", Param("cpu")))
    good_cpu = Model(("llm.w", Param("cpu")), ("audio_tokenizer.w", Param("cpu")))
    assert w.placement_problem(good_mps, "mps", "float32") == "" and w.placement_problem(good_cpu, "cpu", "float32") == ""
    fallback = Model(("llm.w", Param("mps")), ("llm.v", Param("cpu")), ("audio_tokenizer.w", Param("cpu")))
    assert "not only on mps" in w.placement_problem(fallback, "mps", "float32")
    half = Model(("llm.w", Param("mps", "torch.float16")), ("audio_tokenizer.w", Param("cpu")))
    assert "not only in float32" in w.placement_problem(half, "mps", "float32")
    tokenizer_moved = Model(("llm.w", Param("mps")), ("audio_tokenizer.w", Param("mps")))
    assert "audio tokenizer" in w.placement_problem(tokenizer_moved, "mps", "float32")


@pytest.mark.parametrize("plan, stage, kind, condemns", [
    (DLL_193, "import", "OSError", True),         # the independent review's reproduction: a damaged torch_cpu.dll
    (DLL_126, "import", "OSError", True),         # a native library missing from the package
    ({"at": "omnivoice", "kind": "importerror", "text": "cannot import name 'OmniVoice' from 'omnivoice'"},
     "import", "ImportError", True),
    ({"at": "torch", "kind": "modulenotfound", "text": "No module named 'torch._C'"}, "import", "ModuleNotFoundError",
     True),
    ({"at": "omnivoice", "kind": "runtimeerror", "text": "a dependency of OmniVoice failed to initialise"},
     "import", "RuntimeError", True),
    (PAGING_1455, "memory", "OSError", False),    # Windows' commit limit while loading a CUDA library: not the files
    ({"at": "torch", "kind": "memoryerror"}, "memory", "MemoryError", False),
    (SAC_4551, "import", "OSError", False),       # Smart App Control: Windows' own refusal, which a rebuild cannot change
    (NETWORK_AT_IMPORT, "network", "NetworkRefused", False),
    ({"at": "omnivoice", "kind": "wrapped-network"}, "network", "RuntimeError", False),
], ids=["dll-193", "dll-126", "importerror", "modulenotfound", "init-runtimeerror", "paging-1455", "memoryerror",
        "smart-app-control", "network", "wrapped-network"])
def test_a_failure_of_the_real_worker_s_startup_imports_is_named_by_where_it_happened(tmp_path, plan, stage, kind,
                                                                                         condemns):
    """R1: a conversion's startup imports are classified as the installer's probe classifies its own -- by stage, not
    by the exception's kind -- so a native library Windows will not load (an ``OSError``) reaches the rebuild decision,
    while running out of memory, Smart App Control and the network guard never do. The original exception's type opens
    the message, its Windows error number travels with it and a bounded traceback is kept."""
    code, events = run_stack_worker(tmp_path, plan)
    assert code == 2 and len(events) == 1, events
    event = events[0]
    assert (event["event"], event["stage"]) == ("failed", stage), event
    assert event["message"].split(":", 1)[0] == kind, event["message"]
    if "winerror" in plan:
        assert event["winerror"] == plan["winerror"]
        if sys.platform == "win32":
            assert f"[WinError {plan['winerror']}]" in event["message"]
    if stage in ("import", "memory"):
        trace = event["trace"]
        assert 0 < len(trace) <= 1500 and trace.strip().splitlines()[-1].startswith(kind), trace[-300:]
    assert ov.failure_needs_rebuild(event) is condemns
    assert not (tmp_path / "chunks").exists(), "nothing was rendered"


@pytest.mark.parametrize("plan, options, terminal, stage", [
    ({"at": "load", "kind": "oserror", "winerror": 126, "text": "The specified module could not be found."}, {},
     "failed", "load"),
    ({"at": "generate", "kind": "oserror", "winerror": 5, "text": "Access is denied."}, {}, "failed", "generate"),
    ({"at": "generate", "kind": "runtimeerror", "text": "CUDA out of memory. Tried to allocate 2.00 GiB"}, {},
     "failed", "generate"),
    ({"gpu": False}, {}, "failed", "load"),
    ({}, {"cancel": True}, "canceled", None),
    ({}, {"hold_lock": True}, "failed", "engine"),
    ({}, {"offline": False}, "failed", "job"),
], ids=["load-oserror", "generate-oserror", "cuda-oom", "no-gpu", "cancel", "busy-engine", "job-refused"])
def test_failures_past_the_imports_keep_their_own_stage_and_never_condemn_the_engine(tmp_path, plan, options,
                                                                                    terminal, stage):
    """R1's exclusions, on the real worker: an ``OSError`` while the model loads or speech is generated, CUDA out of
    memory, no usable GPU, a cancellation, a busy engine and a refused job each keep their own answer."""
    code, events = run_stack_worker(tmp_path, plan, **options)
    event = events[-1]
    assert event["event"] == terminal and event.get("stage") == stage, events
    assert code == (130 if terminal == "canceled" else 2)
    if plan.get("kind") == "runtimeerror":
        assert event["oom"] is True
    if plan.get("gpu") is False:
        assert event["gpu"] is False
    assert not ov.failure_needs_rebuild(event), event


@pytest.mark.parametrize("plan, stage, damaging", [
    (DLL_193, "import", True),
    (PAGING_1455, "memory", False),
    (SAC_4551, "import", False),              # the installer retries it, then does not hold it against the files
    (NETWORK_AT_IMPORT, "network", False),
    ({}, "gpu", False),                       # past the imports: the stand-in has no CUDA kernel to run
], ids=["dll-193", "paging-1455", "smart-app-control", "network", "past-the-imports"])
def test_the_installer_s_proof_classifies_its_imports_with_the_same_rule(tmp_path, plan, stage, damaging):
    """R1, the probe side: the installer's proof (``run_probe``) uses the same ``import_failure`` as a conversion, so
    running out of memory or the network guard no longer condemns a freshly built engine, while a library Windows will
    not load still does."""
    from tts import omnivoice_setup as ovs

    code, events = run_stack_worker(tmp_path, plan, probe=True)
    (event,) = events
    assert code == 2 and (event["event"], event["stage"]) == ("failed", stage), event
    refused = ovs.ProofFailed(f"The OmniVoice voice engine did not pass its check: {event['message']}", stage=stage)
    assert ovs.speaks_against_environment(refused) is damaging


def test_a_native_library_that_will_not_load_at_conversion_is_recorded_and_publishes_nothing(fake, monkeypatch,
                                                                                            tmp_path):
    """R1 end to end: the conversion path with the REAL worker, whose PyTorch library fails to load as Windows' loader
    fails it (``OSError``, WinError 193). The engine is recorded as damaged, the person is told the repair is offered,
    and no MP3 is published -- an existing one is left alone. Out of memory, Smart App Control and the network guard
    fail the file too, with their own sentence, and record nothing."""
    model = tmp_path / "model"
    (model / "audio_tokenizer").mkdir(parents=True)
    (model / "config.json").write_text("{}", encoding="utf-8")
    (model / "audio_tokenizer" / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(ov, "model_dir", lambda: model)
    for name, value in OFFLINE.items():
        monkeypatch.setenv(name, value)
    recorded: list[str] = []
    monkeypatch.setattr(ov, "reject_ready_engine", lambda reason: recorded.append(reason) or True)
    launcher = stack_worker(tmp_path / "real-worker")
    destination = fake.tmp / "story.mp3"
    destination.write_bytes(b"THE OWNER'S EARLIER FILE")

    monkeypatch.setenv("ACT_FAKE_STACK", json.dumps(DLL_193))
    with pytest.raises(osy.OmniVoiceFailed) as failed:
        fake.convert(text=PARAGRAPHS, script=launcher)
    assert len(recorded) == 1 and recorded[0].startswith("OSError") and "torch_cpu.dll" in recorded[0]
    assert "failed while starting the voice engine: OSError" in str(failed.value)
    assert str(failed.value).endswith(osy.REPAIR_OFFERED_NOTE)

    for plan, words in ((PAGING_1455, "did not have enough memory"), (SAC_4551, "Application Control policy"),
                        (NETWORK_AT_IMPORT, "tried to use the network")):
        monkeypatch.setenv("ACT_FAKE_STACK", json.dumps(plan))
        with pytest.raises(osy.OmniVoiceFailed, match=words) as failed:
            fake.convert(text=PARAGRAPHS, script=launcher)
        assert osy.REPAIR_OFFERED_NOTE not in str(failed.value) and "look damaged" not in str(failed.value)
    assert len(recorded) == 1, "only the damaged library condemned the engine"
    assert destination.read_bytes() == b"THE OWNER'S EARLIER FILE" and fake.leftovers() == []
    assert sorted(p.name for p in fake.tmp.glob("story*")) == ["story.mp3", "story.txt"], "no partial output"


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
    reference = tmp_path / "r.wav"
    with wave.open(str(reference), "wb") as out:
        out.setnchannels(1), out.setsampwidth(2), out.setframerate(44100), out.writeframes(b"\0\0" * 100)
    sha = hashlib.sha256(reference.read_bytes()).hexdigest()
    good = {"schema": 1, "kind": "synth", "voice_id": "omnivoice-male-1", "model_dir": str(model),
            "omnivoice_version": "0.2.1", "language": "English", "dtype": "float16", "device": "cuda",
            "out_dir": str(tmp_path / "o"), "cancel_file": str(tmp_path / "c"), "engine_lock": str(tmp_path / "l"),
            "reference": {"wav": str(reference), "wav_sha256": sha, "frames": 100, "sample_rate": 44100,
                          "max_frames": 441000},
            "ref_text": "Zeth,", "prompt_cache": None, "generation": dict(osy.GENERATION),
            "chunks": [{"index": 0, "text": "Hello.", "seed": 1}]}
    offline = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    win = "win32"  # Windows' rules, asked on any host (macOS P4B seam); a Mac's follow
    assert w.job_problems(good, offline, win) == []
    for change, expected in [({"ref_text": " "}, "speech recognizer"), ({"device": "cpu"}, "GPU only"),
                             ({"generation": {"num_step": 32, "asr": True}}, "OmniVoiceGenerationConfig"),
                             ({"reference": {**good["reference"], "frames": 441001}}, "approved length"),
                             ({"reference": {**good["reference"], "wav_sha256": "x"}}, "approved SHA-256"),
                             ({"reference": {**good["reference"], "wav": str(tmp_path / "gone.wav")}}, "missing"),
                             ({"reference": None}, "missing"),
                             ({"chunks": []}, "chunks")]:
        assert any(expected in p for p in w.job_problems({**good, **change}, offline, win)), change
    # macOS P4B: a Mac takes exactly the two accepted configurations, both float32, and never the MPS fallback switch
    mac = "darwin"
    for device in ("mps", "cpu"):
        assert w.job_problems({**good, "device": device, "dtype": "float32"}, offline, mac) == [], device
    for device, dtype in (("mps", "float16"), ("cuda", "float16"), ("cpu", "float16"), ("mps", "bfloat16")):
        assert any("only on the Apple GPU (mps) or the CPU, in float32" in p
                   for p in w.job_problems({**good, "device": device, "dtype": dtype}, offline, mac)), (device, dtype)
    fallback = {**offline, "PYTORCH_ENABLE_MPS_FALLBACK": "1"}
    assert any("PYTORCH_ENABLE_MPS_FALLBACK" in p
               for p in w.job_problems({**good, "device": "mps", "dtype": "float32"}, fallback, mac))
    assert w.job_problems(good, fallback, win) == [], "Windows ignores the MPS switch, as before"
    (model / "audio_tokenizer" / "config.json").unlink()
    assert any("would fetch one" in p for p in w.job_problems(good, offline, win))
    assert w.job_problems(good, {}, win)[0] == "HF_HUB_OFFLINE is not 1"


def test_the_worker_reads_the_reference_once_proves_its_bytes_and_keeps_its_own_rate(tmp_path):
    from tts import omnivoice_worker as w

    path = tmp_path / "r.wav"
    samples = (np.sin(np.arange(4410) / 7.0) * 12000).astype("<i2")
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1), out.setsampwidth(2), out.setframerate(44100), out.writeframes(samples.tobytes())
    ref = {"wav": str(path), "wav_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "frames": 4410,
           "sample_rate": 44100, "max_frames": 441000}
    waveform, rate = w.read_reference({"reference": ref})
    assert rate == 44100 and waveform.shape == (1, 4410) and waveform.dtype == np.float32, "OmniVoice resamples it"
    assert np.allclose(waveform[0], samples / 32768.0)
    for change, message in [({"frames": 4409}, "format"), ({"sample_rate": 24000}, "format"),
                            ({"max_frames": 4409}, "format"), ({"wav_sha256": "0" * 64}, "not the approved one")]:
        with pytest.raises(RuntimeError, match=message):
            w.read_reference({"reference": {**ref, **change}})
    real = ov.verify_reference(ov.load_references()["omnivoice-male-1"], ov.reference_path(ov.get_voice("omnivoice-male-1")))
    waveform, rate = w.read_reference({"reference": real})
    assert (waveform.shape, rate) == ((1, 451022), 44100), "the excepted Male 1 recording reaches the model whole"


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


# --------------------------------------------------------------------------- #
# v0.8.0 Phase 4: the manual-listening sample helper's OmniVoice route
# --------------------------------------------------------------------------- #
def test_the_sample_helper_narrates_an_omnivoice_voice_through_the_production_path_with_v1(tmp_path, monkeypatch):
    from tts import generate_voice_samples as gvs
    from tts.voice_registry import VOICES

    voice = next(v for v in VOICES if v.voice_id == "omnivoice-female-2")
    calls: list = []

    def fake(source, output, voice_id, **kwargs):
        calls.append({"source": Path(source), "text": Path(source).read_text(encoding="utf-8"), "output": Path(output),
                      "voice_id": voice_id, **kwargs})
        Path(output).write_bytes(b"mp3")

    monkeypatch.setattr(osy, "omnivoice_file_to_mp3", fake)
    dest = tmp_path / "out" / "OmniVoice Female 2.mp3"
    dest.parent.mkdir()
    gvs._synthesize_for_voice(voice, "Built in 1905, restored by 1999.", dest, log=lambda m: None)
    (call,) = calls
    assert call["voice_id"] == "omnivoice-female-2" and call["output"] == dest and dest.read_bytes() == b"mp3"
    assert call["text"] == "Built in 1905, restored by 1999."
    assert call["source"].parent == dest.parent, "the source text stays inside the output folder, never the system temp"
    assert not call["source"].exists(), "the source text is removed afterwards"
    assert (call["chunk_pause_ms"], call["end_silence_ms"], call["bitrate"]) == (700, 0, "192k")
    snapshot = call["speech_prep"]
    assert snapshot.enabled and snapshot.setting == SETTING_V1, "a listening sample hears the prepared text, never 'off'"
    assert snapshot.modes_for("omnivoice") == build_snapshot(SETTING_V1, user_dir=None).modes_for("omnivoice")


def test_the_sample_helper_removes_its_source_text_when_the_engine_fails(tmp_path, monkeypatch):
    from tts import generate_voice_samples as gvs
    from tts.voice_registry import VOICES

    voice = next(v for v in VOICES if v.voice_id == "omnivoice-male-4")

    def failing(source, output, voice_id, **kwargs):
        raise ov.OmniVoiceUnavailable("not installed here")

    monkeypatch.setattr(osy, "omnivoice_file_to_mp3", failing)
    dest = tmp_path / "Male 4.mp3"
    with pytest.raises(ov.OmniVoiceUnavailable):
        gvs._synthesize_omnivoice(voice, "Text.", dest, log=lambda m: None)
    assert not list(tmp_path.iterdir()), "no source text and no MP3 are left behind"
