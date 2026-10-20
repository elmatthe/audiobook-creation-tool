"""v0.6.7 CP6 — the Qwen3 conversion path, against a fake worker.

The real worker needs a 4.5 GB model and a second Python environment; these tests need neither. A small stand-in
script speaks the same ``@@EVENT`` protocol (and misbehaves on request), so every guarantee of the supervising side is
exercised with the real subprocess, pipe and kill machinery: progress, cancellation, escalation to a process-tree
kill, failure recovery, partial-output cleanup, text privacy, and the existing narration pause policy (Q6).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from shared.cancellation import ConversionCancelled
from tts import qwen3_runtime as rt
from tts import qwen3_synth as qs

RATE = 24000

FAKE_WORKER = r'''
import json, os, sys, time
from pathlib import Path

import numpy as np
import soundfile as sf

plan = json.loads(os.environ.get("FAKE_QWEN3", "{}"))
job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
behavior = plan.get("behavior", "ok")


def emit(event):
    print("@@EVENT " + json.dumps(event), flush=True)


def tone(seconds, rate=24000):
    n = int(rate * seconds)
    return (0.1 * np.sin(2 * np.pi * 220 * np.arange(n) / rate)).astype("float32")


print("a library banner that is not an event", flush=True)
ref_hash = None
if job.get("reference_wav") and os.path.exists(job["reference_wav"]):
    import hashlib
    ref_hash = hashlib.sha256(open(job["reference_wav"], "rb").read()).hexdigest()
if "FAKE_QWEN3_LOG" in os.environ:
    Path(os.environ["FAKE_QWEN3_LOG"]).write_text(json.dumps({**job, "_reference_sha256": ref_hash}), encoding="utf-8")
if behavior == "noise_stall":
    while True:  # chatty but making no progress: library output must not count as being alive
        print("downloading something... 37%", flush=True)
        time.sleep(0.05)
if behavior == "exit_early":
    sys.stderr.write("Traceback (most recent call last):\n  CUDA error: no kernel image\n")
    sys.exit(3)
if behavior == "malformed":
    print("@@EVENT {this is not json", flush=True)
    time.sleep(30)
out = Path(job["out_dir"])
out.mkdir(parents=True, exist_ok=True)
if behavior == "stall":
    emit({"event": "loaded", "device": "cuda:0", "device_name": "Fake GPU"})
    time.sleep(60)
emit({"event": "loaded", "device": plan.get("device", "cuda:0"), "device_name": plan.get("name", "Fake GPU"),
      "chunks": len(job["chunks"])})
for position, chunk in enumerate(job["chunks"]):
    if os.path.exists(job["cancel_file"]) and behavior != "ignore_cancel":
        emit({"event": "canceled", "completed": position})
        sys.exit(130)
    if behavior == "hang" and position == plan.get("at", 0):
        time.sleep(120)
    if behavior == "ignore_cancel":
        time.sleep(0.3)
    if behavior == "flood":  # a flood of library output while ignoring the cancel flag
        for _ in range(400):
            print("progress bar frame", flush=True)
            time.sleep(0.02)
    if behavior == "fail" and position == plan.get("at", 0):
        emit({"event": "failed", "stage": plan.get("stage", "generate"), "index": position,
              "message": plan.get("message", "kaboom"), "oom": bool(plan.get("oom"))})
        sys.exit(2)
    seconds = plan.get("seconds", 0.2) + 0.1 * position  # different lengths, so order is checkable
    wave = tone(seconds) * (position + 1)  # amplitude 0.1, 0.2, 0.3 ... so the order of chunks is observable
    rate = plan.get("rate_at", {}).get(str(position), 24000)
    if behavior == "nan" and position == plan.get("at", 0):
        wave[5] = float("nan")
    if behavior == "stereo" and position == plan.get("at", 0):
        wave = np.stack([wave, wave], axis=1)
    name = f"chunk-{position + 1:04d}.wav"
    sf.write(str(out / name), wave, rate, subtype="FLOAT")
    emit({"event": "chunk", "index": chunk["index"], "of": len(job["chunks"]), "wav": name,
          "audio_s": round(len(wave) / rate, 3), "gen_s": 0.01, "sample_rate": rate})
    if behavior == "slow":
        time.sleep(plan.get("delay", 0.4))
if behavior == "no_terminal":
    sys.exit(0)
if behavior == "missing_file":
    (out / f"chunk-{len(job['chunks']):04d}.wav").unlink()
if behavior == "double_terminal":
    emit({"event": "done"})
if behavior == "orphan":  # the real interpreter's stand-in: a child that keeps the output pipe open after we exit
    import subprocess
    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    emit({"event": "done", "chunks": len(job["chunks"]), "sample_rate": 24000, "device": "cuda:0"})
    sys.exit(0)
emit({"event": "done", "chunks": len(job["chunks"]), "sample_rate": 24000, "device": "cuda:0"})
if behavior == "done_then_crash":
    sys.stderr.write("Fatal Python error: Segmentation fault during shutdown\n")
    sys.exit(9)
if behavior == "done_then_hang":
    time.sleep(120)
'''


@pytest.fixture()
def fake(tmp_path, monkeypatch):
    """A fake worker plus the keyword seams that point ``qwen3_file_to_mp3`` at it."""
    script = tmp_path / "fake_qwen3_worker.py"
    script.write_text(FAKE_WORKER, encoding="utf-8")
    jobs = tmp_path / "jobs"
    exported = {}
    # The failure diagnostic goes under runtime_dir(); keep it (and anything else derived from it) in the sandbox.
    monkeypatch.setattr(rt, "runtime_dir", lambda: tmp_path / "runtime")

    def fake_encoder(wav, mp3, bitrate, *, work_dir, cancel_check=None):
        data, rate = sf.read(str(wav), dtype="float32")
        exported.update(arr=data, rate=rate, staged=str(mp3), work_dir=str(work_dir), bitrate=bitrate)
        Path(mp3).write_bytes(b"MP3-BYTES")

    class Harness:
        def __init__(self):
            self.script, self.jobs, self.exported, self.logs = script, jobs, exported, []
            self.tmp = tmp_path

        def env(self, **plan):
            env = dict(os.environ)
            env["FAKE_QWEN3"] = json.dumps(plan)
            return env

        def convert(self, text="One sentence here. Another sentence follows.", voice="qwen3-aiden", name="story.mp3",
                    plan=None, **kwargs):
            source = tmp_path / "story.txt"
            source.write_text(text, encoding="utf-8")
            kwargs.setdefault("grace_s", 1.0)
            kwargs.setdefault("event_timeout_s", 60.0)
            kwargs.setdefault("availability", lambda v: (True, "ok"))
            kwargs.setdefault("encoder", fake_encoder)
            return qs.qwen3_file_to_mp3(
                str(source), str(tmp_path / name), voice, log=self.logs.append, python=Path(sys.executable),
                script=script, jobs_root=jobs, env=self.env(**(plan or {})), **kwargs)

        def job_folders(self):
            return list(jobs.iterdir()) if jobs.is_dir() else []

    return Harness()


MANY = "\n\n".join(f"Paragraph number {i} says something quite different from the rest." for i in range(4))


# --------------------------------------------------------------------------- #
# Text preparation and the chunk planner
# --------------------------------------------------------------------------- #
def test_prepare_text_matches_the_other_engines_and_keeps_a_heading_as_its_own_paragraph():
    raw = "﻿Title: A Book\nAuthor: Someone\n# Chapter One\nIt began.\n\nSecond paragraph."
    text = qs.prepare_text(raw.lstrip("﻿"))
    assert "Title:" not in text and "Author:" not in text and "#" not in text
    chunks = qs.plan_chunks(text)
    assert [c.text for c in chunks] == ["Chapter One", "It began.", "Second paragraph."]
    assert [c.boundary for c in chunks] == ["paragraph", "paragraph", "end"]  # the title earns a paragraph pause
    assert qs.prepare_text("# \n\n") == ""  # an empty heading marker contributes nothing


def test_chunks_never_cross_a_paragraph_and_preserve_every_character_in_order():
    text = qs.prepare_text(MANY)
    chunks = qs.plan_chunks(text)
    assert len(chunks) == 4 and [c.paragraph for c in chunks] == [0, 1, 2, 3]
    assert [c.boundary for c in chunks] == ["paragraph"] * 3 + ["end"]
    assert "".join("".join(c.text.split()) for c in chunks) == "".join(text.split())
    assert all(a.end <= b.start for a, b in zip(chunks, chunks[1:]))  # ordered, non-overlapping source spans
    for c in chunks:
        assert "".join(text[c.start:c.end].split()) == "".join(c.text.split())


def test_sentences_pack_up_to_the_ceiling_and_an_overlong_sentence_splits_at_clauses_then_words():
    sentence = "This is a sentence of moderate length. "
    paragraph = (sentence * 40).strip()  # ~1,560 characters in 40 sentences
    chunks = qs.plan_chunks(paragraph, 600)
    assert len(chunks) == 3 and all(len(c.text) <= 600 for c in chunks)
    assert [c.boundary for c in chunks] == ["sentence", "sentence", "end"]  # cut only at whole sentences

    clauses = "alpha beta gamma, " * 80
    chunks = qs.plan_chunks(clauses.strip().rstrip(",") + ".", 600)
    assert len(chunks) >= 2 and all(len(c.text) <= 600 for c in chunks)
    assert chunks[0].boundary == "clause"  # a long sentence is cut at punctuation first

    words = " ".join(["word"] * 400) + "."
    chunks = qs.plan_chunks(words, 600)
    assert all(len(c.text) <= 600 for c in chunks) and chunks[0].boundary == "word"

    with pytest.raises(qs.ChunkPlanError, match="single word"):
        qs.plan_chunks("x" * 700, 600)
    with pytest.raises(qs.ChunkPlanError, match="no chunks"):
        qs.plan_chunks("   ")
    with pytest.raises(ValueError):
        qs.plan_chunks("text", 10)


@pytest.mark.parametrize("token", ["Dr.", "Mr.", "St.", "J.", "U.S."])
def test_an_abbreviation_never_ends_a_sentence_where_it_would_change_the_chunking(token):
    """Built at the ceiling so a wrongly detected boundary visibly moves text from one chunk to the next.

    A 585-character sentence leaves room for exactly the abbreviation (but not for the sentence after it) in the
    first chunk. If ``Dr.``/``J.``/``e.g.`` were taken for a sentence end, greedy packing would glue it onto the END of
    the first chunk and strand the name that belongs to it at the start of the second.
    """
    lead = " ".join(["aaaa"] * 117) + "."  # exactly 585 characters
    assert len(lead) == 585
    chunks = qs.plan_chunks(f"{lead} {token} Smith went home.", 600)
    assert [c.text for c in chunks] == [lead, f"{token} Smith went home."]


def test_a_blank_line_made_of_a_non_breaking_space_is_still_a_paragraph_break():
    text = qs.prepare_text("First paragraph.\n\u00a0\nSecond paragraph.\n \t \nThird.\r\n\r\nFourth.")
    chunks = qs.plan_chunks(text)
    assert [c.text for c in chunks] == ["First paragraph.", "Second paragraph.", "Third.", "Fourth."]
    assert [c.boundary for c in chunks] == ["paragraph", "paragraph", "paragraph", "end"]  # each earns a paragraph pause


def test_verify_plan_rejects_a_plan_that_lost_or_reordered_text():
    text = "First sentence here. Second sentence here."
    chunks = qs.plan_chunks(text)
    broken = [qs.Chunk(0, chunks[0].start, chunks[0].end, "First sentence", "end", 0)]
    with pytest.raises(qs.ChunkPlanError):
        qs.verify_plan(text, broken)
    with pytest.raises(qs.ChunkPlanError, match="out of order"):
        qs.verify_plan(text, [qs.Chunk(0, 10, 20, text[10:20], "x", 0), qs.Chunk(1, 0, 8, text[0:8], "x", 0)])


def test_seeds_are_stable_per_voice_position_and_words_but_differ_otherwise():
    a = qs.Chunk(0, 0, 5, "Hello", "end", 0)
    assert qs.derive_seed("qwen3-aiden", a) == qs.derive_seed("qwen3-aiden", a)
    assert qs.derive_seed("qwen3-aiden", a) != qs.derive_seed("qwen3-ryan", a)
    assert qs.derive_seed("qwen3-aiden", a) != qs.derive_seed("qwen3-aiden", qs.Chunk(1, 0, 5, "Hello", "end", 0))
    assert qs.derive_seed("qwen3-aiden", a) != qs.derive_seed("qwen3-aiden", qs.Chunk(0, 0, 5, "Hullo", "end", 0))
    assert 0 <= qs.derive_seed("qwen3-aiden", a) <= 0x7FFFFFFF


# --------------------------------------------------------------------------- #
# Assembly and the existing pause policy (Q6)
# --------------------------------------------------------------------------- #
def tone(seconds: float) -> np.ndarray:
    return np.full(int(RATE * seconds), 0.25, dtype="float32")


def test_assembly_follows_the_local_engine_policy_exactly():
    audio = [tone(0.5), tone(1.0), tone(0.25)]
    pcm, report = qs.assemble(audio, RATE, chunk_pause_ms=700, end_silence_ms=3000)
    gap, end = int(RATE * 0.7), int(RATE * 3.0)
    assert pcm.size == sum(a.size for a in audio) + 3 * gap + end  # a gap after EVERY chunk (the last too), then the end
    assert report == {"sample_rate": RATE, "chunks": 3, "speech_samples": sum(a.size for a in audio),
                      "gap_samples": gap, "end_silence_samples": end, "total_samples": pcm.size}
    first = audio[0].size
    assert np.all(pcm[:first] == 0.25) and np.all(pcm[first:first + gap] == 0.0)  # speech, then silence, in order
    assert np.all(pcm[first + gap:first + gap + audio[1].size] == 0.25)
    assert np.all(pcm[-end:] == 0.0) and pcm[-end - 1] == 0.0  # the final chunk's own pause leads into the end pause


def test_zero_pauses_add_no_samples_and_negative_values_are_treated_as_zero():
    audio = [tone(0.1), tone(0.1)]
    pcm, report = qs.assemble(audio, RATE, chunk_pause_ms=0, end_silence_ms=0)
    assert pcm.size == sum(a.size for a in audio) and report["gap_samples"] == report["end_silence_samples"] == 0
    pcm, _ = qs.assemble(audio, RATE, chunk_pause_ms=-5, end_silence_ms=-5)
    assert pcm.size == sum(a.size for a in audio)


def test_assembly_takes_its_pauses_from_the_voice_preset_the_gui_freezes():
    """The GUI passes the voice's paragraph pause as the chunk pause and its end pause as the end silence."""
    from tts import voice_registry

    entry = next(v for v in voice_registry.VOICES if v.voice_id == "chatterbox-female-1")
    preset = entry.timing_preset
    pcm, report = qs.assemble([tone(0.2)], RATE, chunk_pause_ms=int(preset["paragraphpause"]),
                              end_silence_ms=int(preset["end_pause"]))
    assert report["gap_samples"] == int(RATE * 0.7) and report["end_silence_samples"] == int(RATE * 3.0)


@pytest.mark.parametrize("bad, message", [
    (np.zeros(0, dtype="float32"), "empty"),
    (np.array([0.0, np.nan], dtype="float32"), "non-finite"),
    (np.zeros((4, 2), dtype="float32"), "mono"),
])
def test_bad_chunk_audio_stops_assembly_instead_of_producing_audio_that_merely_looks_complete(bad, message):
    with pytest.raises(qs.AssemblyError, match=message):
        qs.validate_chunk_audio(bad, RATE, None)
    with pytest.raises(qs.AssemblyError, match="sample rate changed"):
        qs.validate_chunk_audio(tone(0.1), 16000, RATE)
    with pytest.raises(qs.AssemblyError):
        qs.assemble([], RATE, chunk_pause_ms=1, end_silence_ms=1)


FAKE_FFMPEG = r"""
import json, os, sys, time
args = sys.argv[1:]
mode = os.environ.get("FAKE_FFMPEG_MODE", "ok")
out = args[-1]
if mode == "fail":
    open(out, "wb").write(b"HALF AN MP3")  # a failing encoder that had already started writing
    sys.stderr.write("[libmp3lame] Error initializing output stream: simulated\n")
    sys.exit(1)
if mode == "slow":
    time.sleep(60)
open(out, "wb").write(json.dumps({"args": args, "cwd": os.getcwd()}).encode())
"""


@pytest.fixture()
def fake_ffmpeg(tmp_path, monkeypatch):
    """A stand-in ffmpeg: a .cmd wrapper around a Python script, so the real spawn/poll/kill code runs."""
    script = tmp_path / "fake_ffmpeg.py"
    script.write_text(FAKE_FFMPEG, encoding="utf-8")
    wrapper = tmp_path / "fake_ffmpeg.cmd"
    wrapper.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    return str(wrapper)


windows_only = pytest.mark.skipif(sys.platform != "win32", reason="the stand-in ffmpeg is a Windows .cmd wrapper")


@windows_only
def test_encode_runs_the_pinned_ffmpeg_with_the_shared_contract_and_keeps_every_scratch_file_in_the_job_folder(
        tmp_path, fake_ffmpeg, monkeypatch):
    import tempfile

    stray = tmp_path / "system-temp"
    stray.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(stray))  # anything written to "the system temp folder" lands here
    work = tmp_path / "work"
    work.mkdir()
    wav, mp3 = work / "in.wav", work / "out.mp3"
    sf.write(str(wav), tone(0.1), RATE)
    qs.encode_mp3(wav, mp3, "320k", work_dir=work, ffmpeg=fake_ffmpeg)
    seen = json.loads(mp3.read_bytes())
    assert seen["args"] == ["-y", "-nostdin", "-loglevel", "error", "-f", "wav", "-i", str(wav), "-f", "mp3",
                            "-codec:a", "libmp3lame", "-b:a", "320k", str(mp3)]
    assert Path(seen["cwd"]) == work
    assert list(stray.iterdir()) == []  # nothing outside the job folder, unlike pydub's own temporary files
    qs.encode_mp3(wav, mp3, None, work_dir=work, ffmpeg=fake_ffmpeg)
    assert json.loads(mp3.read_bytes())["args"][-2] == "192k"  # the shared default when the run names no bitrate


@windows_only
def test_a_failed_encode_reports_ffmpegs_own_message_and_leaves_no_partial_file(tmp_path, fake_ffmpeg, monkeypatch):
    monkeypatch.setenv("FAKE_FFMPEG_MODE", "fail")
    work = tmp_path / "work"
    work.mkdir()
    destination = tmp_path / "out" / "book.mp3"
    destination.parent.mkdir()
    destination.write_bytes(b"OLD GOOD FILE")

    def encoder(wav, mp3, bitrate, *, work_dir, cancel_check=None):
        qs.encode_mp3(wav, mp3, bitrate, work_dir=work_dir, cancel_check=cancel_check, ffmpeg=fake_ffmpeg)

    with pytest.raises(qs.Qwen3Failed, match=r"ffmpeg exit code 1\).*Error initializing output stream"):
        qs.publish_mp3(tone(0.1), RATE, destination, work_dir=work, encoder=encoder)
    assert destination.read_bytes() == b"OLD GOOD FILE"  # a failed run never damages an existing output
    assert [p.name for p in destination.parent.iterdir()] == ["book.mp3"]  # and leaves no .part behind


@windows_only
def test_cancelling_during_the_encode_stops_ffmpeg_and_leaves_the_destination_alone(tmp_path, fake_ffmpeg, monkeypatch):
    monkeypatch.setenv("FAKE_FFMPEG_MODE", "slow")
    work = tmp_path / "work"
    work.mkdir()
    destination = tmp_path / "book.mp3"
    destination.write_bytes(b"OLD GOOD FILE")
    started = time.monotonic()

    def encoder(wav, mp3, bitrate, *, work_dir, cancel_check=None):
        qs.encode_mp3(wav, mp3, bitrate, work_dir=work_dir, cancel_check=cancel_check, ffmpeg=fake_ffmpeg)

    with pytest.raises(ConversionCancelled):
        qs.publish_mp3(tone(0.1), RATE, destination, work_dir=work, encoder=encoder,
                       cancel_check=lambda: time.monotonic() - started > 0.5)
    assert time.monotonic() - started < 15  # the fake would run for 60 s
    assert destination.read_bytes() == b"OLD GOOD FILE"


def test_a_missing_ffmpeg_is_a_failed_encode_with_the_reason(tmp_path, monkeypatch):
    def unavailable():
        raise qs.ffmpeg_utils.FFmpegUnavailable("No verified FFmpeg is available on this computer yet.")

    monkeypatch.setattr(qs.ffmpeg_utils, "ffmpeg_cmd", unavailable)
    with pytest.raises(qs.Qwen3Failed, match="No verified FFmpeg"):
        qs.encode_mp3(tmp_path / "a.wav", tmp_path / "a.mp3", None, work_dir=tmp_path)


def test_publishing_is_atomic_and_cancel_wins_until_the_instant_of_the_move(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    destination = tmp_path / "out" / "book.mp3"
    destination.parent.mkdir()
    destination.write_bytes(b"OLD GOOD FILE")
    wavs = []

    def encoder(wav, mp3, bitrate, *, work_dir, cancel_check=None):
        wavs.append((wav.name, sf.info(str(wav)).subtype))
        mp3.write_bytes(b"NEW ENCODED FILE")

    qs.publish_mp3(tone(0.1), RATE, destination, work_dir=work, encoder=encoder)
    assert destination.read_bytes() == b"NEW ENCODED FILE" and wavs == [("encode.wav", "PCM_16")]
    assert [p.name for p in destination.parent.iterdir()] == ["book.mp3"]

    calls = {"n": 0}

    def cancel_on_the_third_look():
        calls["n"] += 1
        return calls["n"] >= 2  # look 1 follows the encode; look 2 is the last one, immediately before the move

    destination.write_bytes(b"OLD GOOD FILE")
    calls["n"] = 0
    with pytest.raises(ConversionCancelled):
        qs.publish_mp3(tone(0.1), RATE, destination, work_dir=work, encoder=encoder,
                       cancel_check=cancel_on_the_third_look)
    assert destination.read_bytes() == b"OLD GOOD FILE" and [p.name for p in destination.parent.iterdir()] == ["book.mp3"]


# --------------------------------------------------------------------------- #
# The job
# --------------------------------------------------------------------------- #
def test_the_job_for_a_preset_names_the_speaker_and_for_a_clone_the_reference_and_transcript(tmp_path):
    chunks = qs.plan_chunks("One chunk of text.")
    preset = qs.build_job(rt.get_voice("qwen3-ryan"), chunks, job_dir=tmp_path, model_dir=tmp_path / "m")
    assert preset["mode"] == "custom_voice" and preset["speaker"] == "Ryan" and "reference_wav" not in preset
    assert preset["language"] == "English" and preset["dtype"] == "bfloat16" and preset["attn"] == "sdpa"
    assert preset["device"] == "auto" and preset["cancel_file"] == str(tmp_path / "cancel")
    assert preset["chunks"][0]["seed"] == qs.derive_seed("qwen3-ryan", chunks[0])

    clone = qs.build_job(rt.get_voice("qwen3-male-2"), chunks, job_dir=tmp_path, model_dir=tmp_path / "m",
                         reference_text="the approved words", device="cpu")
    assert clone["mode"] == "clone" and clone["reference_text"] == "the approved words"
    assert clone["reference_wav"].endswith("Male-2.wav") and clone["device"] == "cpu" and "speaker" not in clone


# --------------------------------------------------------------------------- #
# A whole conversion through the real subprocess machinery
# --------------------------------------------------------------------------- #
def test_a_conversion_runs_the_worker_assembles_with_the_policy_and_cleans_up(fake):
    progress = []
    fake.convert(MANY, plan={"seconds": 0.2}, chunk_pause_ms=700, end_silence_ms=3000, bitrate="192k",
                 progress_callback=lambda done, total: progress.append((done, total)))
    assert progress == [(1, 4), (2, 4), (3, 4), (4, 4)]  # one tick per chunk, in order
    speech = sum(int(RATE * (0.2 + 0.1 * i)) for i in range(4))
    assert fake.exported["rate"] == RATE and fake.exported["bitrate"] == "192k"
    assert fake.exported["arr"].size == speech + 4 * int(RATE * 0.7) + int(RATE * 3.0)
    assert (fake.tmp / "story.mp3").read_bytes() == b"MP3-BYTES"  # published at the destination...
    assert not Path(fake.exported["staged"]).exists() and fake.job_folders() == []  # ...and the job folder is gone
    text = "\n".join(fake.logs)
    assert "synthesizing 4 chunk(s) in Qwen3 - Aiden" in text and "running on the GPU: Fake GPU" in text
    assert "Qwen3 chunk 4/4" in text and "a library banner that is not an event" in text  # noise is logged, not parsed


def test_chunks_are_assembled_in_plan_order(fake):
    fake.convert(MANY, plan={"seconds": 0.2}, chunk_pause_ms=0, end_silence_ms=0)
    arr = fake.exported["arr"]
    lengths = [int(RATE * (0.2 + 0.1 * i)) for i in range(4)]
    assert arr.size == sum(lengths)
    start = 0
    for position, length in enumerate(lengths):  # the fake's amplitude grows with position: 0.1, 0.2, 0.3, 0.4
        segment = arr[start:start + length]
        assert abs(float(np.max(np.abs(segment))) - 0.1 * (position + 1)) < 0.002, position
        start += length


def test_collector_reads_by_plan_index_not_by_event_arrival(tmp_path):
    import soundfile as sf

    for index, seconds in enumerate((0.1, 0.2, 0.3)):
        sf.write(str(tmp_path / f"c{index}.wav"), tone(seconds), RATE, subtype="FLOAT")
    events = [{"index": 2, "wav": "c2.wav"}, {"index": 0, "wav": "c0.wav"}, {"index": 1, "wav": "c1.wav"}]  # shuffled
    audio, rate = qs._collect_chunks(tmp_path, events, 3)
    assert rate == RATE and [a.size for a in audio] == [int(RATE * s) for s in (0.1, 0.2, 0.3)]
    with pytest.raises(qs.Qwen3Failed, match="2 of 3 chunks"):
        qs._collect_chunks(tmp_path, events[:2], 3)


def test_a_clone_job_carries_the_approved_transcript_and_nothing_else_about_it_survives(fake, monkeypatch, tmp_path):
    seen = tmp_path / "job-seen.json"
    monkeypatch.setattr(rt, "load_transcript", lambda voice_id: rt.Transcript(True, "approved fixture words", "ok"))
    env = fake.env()
    env["FAKE_QWEN3_LOG"] = str(seen)
    source = tmp_path / "clone.txt"
    source.write_text("Some text to read aloud.", encoding="utf-8")
    qs.qwen3_file_to_mp3(str(source), str(tmp_path / "clone.mp3"), "qwen3-male-3", python=Path(sys.executable),
                         script=fake.script, jobs_root=fake.jobs, env=env, availability=lambda v: (True, "ok"))
    job = json.loads(seen.read_text("utf-8"))
    assert job["mode"] == "clone" and job["reference_text"] == "approved fixture words"
    assert Path(job["reference_wav"]).name == "reference.wav"  # the worker is given the verified copy (see the TOCTOU test)
    assert fake.job_folders() == []  # neither the text nor the transcript outlives the run


def test_a_clone_without_an_approved_transcript_never_starts_a_worker(fake, monkeypatch):
    monkeypatch.setattr(rt, "load_transcript", lambda voice_id: rt.Transcript(False, "", "the approved transcript is empty"))
    with pytest.raises(rt.Qwen3Unavailable, match="Setup required for Qwen3 - Male 1: the approved transcript is empty"):
        fake.convert(voice="qwen3-male-1")
    assert fake.job_folders() == [] and fake.logs == []  # nothing was started, nothing created


def test_an_unavailable_voice_stops_before_anything_is_planned_or_started(fake):
    with pytest.raises(rt.Qwen3Unavailable, match="not installed"):
        fake.convert(availability=lambda v: (False, "The Qwen3 voice engine is not installed."))
    assert fake.job_folders() == [] and fake.logs == []
    with pytest.raises(FileNotFoundError):
        qs.qwen3_file_to_mp3("missing.txt", "x.mp3", "qwen3-aiden", availability=lambda v: (True, "ok"))
    with pytest.raises(rt.Qwen3Unavailable, match="Unknown Qwen3 voice"):
        qs.qwen3_file_to_mp3(str(fake.tmp / "story.txt"), "x.mp3", "qwen3-nobody")


def test_blank_text_is_refused(fake):
    with pytest.raises(ValueError, match="No text content"):
        fake.convert("Title: only metadata\nAuthor: nobody\n")


# --------------------------------------------------------------------------- #
# Failure recovery and output preservation
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("plan, expected", [
    ({"behavior": "fail", "at": 1, "message": "RuntimeError: kaboom"}, "failed while generating speech: RuntimeError: kaboom"),
    ({"behavior": "fail", "stage": "load", "message": "no file"}, "failed while loading the model: no file"),
    ({"behavior": "fail", "oom": True, "message": "CUDA out of memory"}, "ran out of memory"),
])
def test_a_reported_failure_fails_the_file_with_a_plain_message_and_no_output(fake, plan, expected):
    destination = fake.tmp / "story.mp3"
    destination.write_bytes(b"PREVIOUS GOOD OUTPUT")
    with pytest.raises(qs.Qwen3Failed, match=expected):
        fake.convert(MANY, plan=plan)
    assert destination.read_bytes() == b"PREVIOUS GOOD OUTPUT"  # an existing file is never damaged by a failed run
    assert fake.exported == {} and fake.job_folders() == []


def test_a_worker_that_dies_without_a_result_is_a_failed_file_with_its_own_error_text(fake):
    with pytest.raises(qs.Qwen3Failed) as info:
        fake.convert(plan={"behavior": "exit_early"})
    message = str(info.value)
    assert "ended unexpectedly" in message and "exit code 3" in message and "CUDA error: no kernel image" in message
    assert fake.exported == {} and fake.job_folders() == []


def test_exiting_cleanly_without_a_terminal_event_is_still_a_failure(fake):
    with pytest.raises(qs.Qwen3Failed, match="ended unexpectedly"):
        fake.convert(plan={"behavior": "no_terminal"})
    assert fake.exported == {}


def test_a_malformed_event_is_a_failure_and_stops_the_worker_promptly(fake):
    started = time.monotonic()
    with pytest.raises(qs.Qwen3Failed, match="unreadable message"):
        fake.convert(plan={"behavior": "malformed"})
    assert time.monotonic() - started < 20  # the fake sleeps 30 s; it was killed, not waited for
    assert fake.job_folders() == []


def test_two_terminal_events_are_a_failure(fake):
    with pytest.raises(qs.Qwen3Failed, match="more than one result"):
        fake.convert(plan={"behavior": "double_terminal"})
    assert fake.exported == {}


def test_a_chunk_reported_but_missing_on_disk_fails_the_file(fake):
    with pytest.raises(qs.Qwen3Failed, match="audio file is missing"):
        fake.convert(MANY, plan={"behavior": "missing_file"})
    assert fake.exported == {}


@pytest.mark.parametrize("plan, message", [
    ({"behavior": "nan", "at": 1}, "non-finite"),
    ({"behavior": "stereo", "at": 0}, "mono"),
    ({"rate_at": {"2": 16000}}, "sample rate changed"),
])
def test_unusable_chunk_audio_fails_the_file_instead_of_being_repaired(fake, plan, message):
    with pytest.raises(qs.Qwen3Failed, match=message):
        fake.convert(MANY, plan=plan)
    assert fake.exported == {} and fake.job_folders() == []


def test_a_stalled_worker_is_stopped_and_reported(fake):
    started = time.monotonic()
    with pytest.raises(qs.Qwen3Failed, match="stopped responding"):
        fake.convert(plan={"behavior": "stall"}, event_timeout_s=1.5)
    assert time.monotonic() - started < 25 and fake.job_folders() == []


def test_a_failed_run_leaves_a_diagnostic_without_the_job_folder(fake, monkeypatch, tmp_path):
    monkeypatch.setattr(rt, "runtime_dir", lambda: tmp_path / "rt")
    with pytest.raises(qs.Qwen3Failed):
        fake.convert(plan={"behavior": "exit_early"})
    record = (tmp_path / "rt" / "last-failure.txt").read_text("utf-8")
    assert "ended unexpectedly" in record and "no kernel image" in record


# --------------------------------------------------------------------------- #
# Cancellation (Q1: verified, bounded)
# --------------------------------------------------------------------------- #
def test_cancel_is_honoured_between_chunks_by_a_worker_that_cooperates(fake):
    seen = []

    def cancel_after_two():
        return len([m for m in fake.logs if "Qwen3 chunk" in m]) >= 2

    with pytest.raises(ConversionCancelled):
        fake.convert(MANY, plan={"behavior": "slow", "delay": 0.5}, cancel_check=cancel_after_two,
                     progress_callback=lambda d, t: seen.append(d))
    assert 2 <= len(seen) < 4  # it stopped early, at a chunk boundary
    assert fake.exported == {} and fake.job_folders() == []
    assert not (fake.tmp / "story.mp3").exists()  # no partial output


def test_a_worker_that_ignores_the_flag_is_killed_after_the_grace_period(fake):
    started = time.monotonic()
    first_chunk = lambda: any("Qwen3 chunk 1/" in m for m in fake.logs)  # noqa: E731
    with pytest.raises(ConversionCancelled):
        fake.convert(MANY * 3, plan={"behavior": "ignore_cancel"}, cancel_check=first_chunk, grace_s=0.5)
    elapsed = time.monotonic() - started
    assert elapsed < 20  # 12 chunks at 0.3 s would otherwise run for several seconds more; it was cut off
    assert fake.exported == {} and fake.job_folders() == []


def test_a_worker_stuck_inside_one_chunk_is_killed_not_waited_for(fake):
    started = time.monotonic()
    with pytest.raises(ConversionCancelled):
        fake.convert(plan={"behavior": "hang", "at": 0}, cancel_check=lambda: any("running on" in m for m in fake.logs),
                     grace_s=0.5)
    assert time.monotonic() - started < 20  # the fake would sleep for 120 s
    assert fake.job_folders() == []


def test_cancelling_before_anything_starts_still_cancels(fake):
    with pytest.raises(ConversionCancelled):
        fake.convert(cancel_check=lambda: True, grace_s=0.3)
    assert fake.exported == {} and fake.job_folders() == []


def test_a_cancel_that_arrives_as_the_worker_finishes_is_still_a_cancel(fake):
    """The caller asked to stop; delivering the finished file anyway would contradict the Cancel button."""
    with pytest.raises(ConversionCancelled):
        fake.convert(plan={"behavior": "ignore_cancel"}, cancel_check=lambda: bool(fake.logs), grace_s=30)
    assert fake.exported == {}


# --------------------------------------------------------------------------- #
# Process tree and housekeeping
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(sys.platform != "win32", reason="the launcher/child arrangement is the Windows venv's")
def test_killing_a_worker_takes_its_children_too(tmp_path):
    """The Windows venv python.exe is a launcher that starts the real interpreter; both must die."""
    child_pid = tmp_path / "child.pid"
    code = (
        "import subprocess, sys, time\n"
        f"child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        f"open(r'{child_pid}', 'w').write(str(child.pid))\n"
        "time.sleep(120)\n")
    proc = subprocess.Popen([sys.executable, "-c", code])
    deadline = time.monotonic() + 20
    while not child_pid.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    pid = int(child_pid.read_text())
    assert _pid_alive(pid)
    qs.kill_process_tree(proc)
    deadline = time.monotonic() + 15
    while _pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.2)
    assert proc.poll() is not None and not _pid_alive(pid)


def _pid_alive(pid: int) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
    return str(pid) in out


@windows_only
def test_a_worker_that_reports_success_then_crashes_in_shutdown_publishes_nothing(fake):
    with pytest.raises(qs.Qwen3Failed, match=r"did not exit cleanly \(exit code 9\).*Segmentation fault"):
        fake.convert(MANY, plan={"behavior": "done_then_crash"})
    assert fake.exported == {} and not (fake.tmp / "story.mp3").exists() and fake.job_folders() == []


def test_a_worker_that_reports_success_then_hangs_is_killed_and_distrusted(fake):
    started = time.monotonic()
    with pytest.raises(qs.Qwen3Failed, match="did not exit cleanly"):
        fake.convert(plan={"behavior": "done_then_hang"}, exit_grace_s=1.0)
    assert time.monotonic() - started < 25 and fake.exported == {} and fake.job_folders() == []


@windows_only
def test_a_leftover_child_holding_the_pipe_is_cleaned_up_and_does_not_hang_the_run(fake):
    """The worker exits 0 after its result, but a child it started keeps stdout open: bounded, killed, still a success."""
    started = time.monotonic()
    fake.convert(plan={"behavior": "orphan"}, exit_grace_s=1.0)
    assert time.monotonic() - started < 25
    assert (fake.tmp / "story.mp3").read_bytes() == b"MP3-BYTES"  # the result was complete and the worker exited 0


def test_output_flooding_cannot_postpone_the_cancel_deadline(fake):
    started = time.monotonic()
    with pytest.raises(ConversionCancelled):
        fake.convert(MANY, plan={"behavior": "flood"}, grace_s=0.5,
                     cancel_check=lambda: any("running on" in m for m in fake.logs))
    assert time.monotonic() - started < 15  # 4 chunks x 400 frames x 20 ms would be ~32 s without the kill


def test_library_output_does_not_count_as_the_worker_being_alive(fake):
    started = time.monotonic()
    with pytest.raises(qs.Qwen3Failed, match="stopped responding"):
        fake.convert(plan={"behavior": "noise_stall"}, event_timeout_s=1.5)
    assert time.monotonic() - started < 25 and fake.job_folders() == []


@pytest.mark.parametrize("stage", ["worker", "collect", "assemble", "encode"])
def test_a_cancel_pressed_after_the_worker_finished_wins_at_the_next_stage_and_does_no_further_work(
        fake, monkeypatch, stage):
    """Codex finding: cancellation used to stop being looked at once the worker returned.

    The cancel is raised at the END of the named stage. Everything after that stage must then be skipped (not merely
    undone at the last moment), and nothing may be published over the existing file.
    """
    destination = fake.tmp / "story.mp3"
    destination.write_bytes(b"PREVIOUS GOOD OUTPUT")
    state = {"cancel": False}
    later = {"worker": ["_collect_chunks", "assemble", "encode"], "collect": ["assemble", "encode"],
             "assemble": ["encode"], "encode": []}[stage]

    def refuse(name):
        def run(*args, **kwargs):
            pytest.fail(f"{name} ran after the user cancelled")
        return run

    def cancel_after(function):
        def run(*args, **kwargs):
            result = function(*args, **kwargs)
            state["cancel"] = True
            return result
        return run

    def encoder(wav, mp3, bitrate, *, work_dir, cancel_check=None):
        if "encode" in later:
            pytest.fail("encode ran after the user cancelled")
        state["cancel"] = True
        mp3.write_bytes(b"MP3-BYTES")

    with monkeypatch.context() as m:
        if stage == "worker":
            m.setattr(qs, "run_worker", cancel_after(qs.run_worker))
        if stage == "collect":
            m.setattr(qs, "_collect_chunks", cancel_after(qs._collect_chunks))
        if stage == "assemble":
            m.setattr(qs, "assemble", cancel_after(qs.assemble))
        if "_collect_chunks" in later:
            m.setattr(qs, "_collect_chunks", refuse("collecting chunks"))
        if "assemble" in later:
            m.setattr(qs, "assemble", refuse("assembly"))
        with pytest.raises(ConversionCancelled):
            fake.convert(MANY, cancel_check=lambda: state["cancel"], encoder=encoder)
    assert destination.read_bytes() == b"PREVIOUS GOOD OUTPUT"  # nothing was published over it
    assert [p.name for p in fake.tmp.glob("story.mp3*")] == ["story.mp3"]  # and no .part file was left
    assert fake.job_folders() == []


def test_a_clone_is_made_from_a_verified_snapshot_not_from_the_pathname(fake, monkeypatch, tmp_path):
    """Codex finding (TOCTOU): the recording that is hashed must be the recording that is cloned."""
    import hashlib
    from dataclasses import replace

    original = b"RIFF the approved reference recording"
    voice = replace(rt.get_voice("qwen3-male-4"), reference_sha256=hashlib.sha256(original).hexdigest())
    monkeypatch.setitem(rt._VOICE_BY_ID, "qwen3-male-4", voice)
    reference = tmp_path / "Male-4.wav"
    reference.write_bytes(original)
    monkeypatch.setattr(rt, "reference_path", lambda v: reference)
    monkeypatch.setattr(rt, "load_transcript", lambda voice_id: rt.Transcript(True, "approved fixture words", "ok"))
    seen = tmp_path / "job-seen.json"
    env = fake.env()
    env["FAKE_QWEN3_LOG"] = str(seen)
    source = tmp_path / "clone.txt"
    source.write_text("Some text to read aloud.", encoding="utf-8")

    qs.qwen3_file_to_mp3(str(source), str(tmp_path / "clone.mp3"), "qwen3-male-4", python=Path(sys.executable),
                         script=fake.script, jobs_root=fake.jobs, env=env, availability=lambda v: (True, "ok"),
                         encoder=lambda *a, **k: Path(a[1]).write_bytes(b"MP3"))
    job = json.loads(seen.read_text("utf-8"))
    assert Path(job["reference_wav"]).parent.parent == fake.jobs  # the copy inside the job folder, not the repository path
    assert job["_reference_sha256"] == voice.reference_sha256  # and the worker read exactly the approved bytes

    reference.write_bytes(b"RIFF a substituted recording")  # replaced after approval, before the run reads it
    with pytest.raises(rt.Qwen3Unavailable, match="does not match the one Qwen3 - Male 4 was approved against"):
        qs.qwen3_file_to_mp3(str(source), str(tmp_path / "clone2.mp3"), "qwen3-male-4", python=Path(sys.executable),
                             script=fake.script, jobs_root=fake.jobs, env=env, availability=lambda v: (True, "ok"))
    assert fake.job_folders() == [] and not (tmp_path / "clone2.mp3").exists()


def test_stale_job_folders_are_removed_but_a_fresh_one_is_kept(tmp_path):
    old, fresh = tmp_path / "old-job", tmp_path / "fresh-job"
    for folder in (old, fresh):
        (folder / "chunks").mkdir(parents=True)
        (folder / "job.json").write_text("{}", encoding="utf-8")
    two_days_ago = time.time() - 2 * 86400
    os.utime(old, (two_days_ago, two_days_ago))
    assert qs.cleanup_stale_jobs(tmp_path) == 1
    assert not old.exists() and fresh.exists()
    assert qs.cleanup_stale_jobs(tmp_path / "nowhere") == 0


def test_event_parsing_distinguishes_noise_events_and_garbage():
    assert qs.parse_event("Loading weights...") is None
    assert qs.parse_event('@@EVENT {"event": "chunk", "index": 1}') == {"event": "chunk", "index": 1}
    assert qs.parse_event("@@EVENT {broken")["event"] == "_malformed"
    assert qs.parse_event('@@EVENT ["a list"]')["event"] == "_malformed"
    assert qs.parse_event('@@EVENT {"no_event_key": 1}')["event"] == "_malformed"


def test_failure_messages_name_the_stage_and_give_oom_its_own_advice():
    assert "ran out of memory" in qs.failure_message({"oom": True, "message": "CUDA out of memory", "stage": "generate"})
    assert "Close other programs" in qs.failure_message({"oom": True, "message": "x"})
    assert "while loading the model" in qs.failure_message({"stage": "load", "message": "bad file"})
    assert "while running: no further detail" in qs.failure_message({})


def test_the_gui_process_never_imports_the_model_stack():
    """Importing the orchestrator must not pull torch or qwen_tts into the application's interpreter."""
    code = ("import sys; sys.path.insert(0, r'%s'); import tts.qwen3_synth, tts.qwen3_runtime; "
            "bad = [m for m in ('torch', 'qwen_tts', 'transformers') if m in sys.modules]; "
            "sys.exit(1 if bad else 0)" % (Path(rt.__file__).resolve().parents[1]))
    assert subprocess.run([sys.executable, "-c", code], capture_output=True).returncode == 0


@windows_only
def test_a_worker_that_cannot_be_contained_is_not_started_and_the_user_is_told_why(fake, monkeypatch):
    """Codex finding: failed Job Object containment must fail the launch, not run an uncontained worker."""
    def refuse(*args, **kwargs):
        raise qs.qwen3_process.ContainmentUnavailable("the process could not be placed under the app's control")

    monkeypatch.setattr(qs.qwen3_process, "spawn", refuse)
    with pytest.raises(qs.Qwen3Failed, match=r"was not started: Windows would not let this app keep control"):
        fake.convert()
    assert fake.exported == {} and fake.job_folders() == []


def test_the_supervisor_gives_up_waiting_after_a_kill_that_never_closes_the_pipe(fake, tmp_path):
    """Codex finding: once killed, nothing bounded the wait for EOF. The final deadline now does."""
    chunks = qs.plan_chunks("One sentence. Another sentence.")
    job_dir = qs.new_job_dir(fake.jobs)
    job = qs.build_job(rt.get_voice("qwen3-aiden"), chunks, job_dir=job_dir, model_dir=tmp_path)
    killed = []
    logs = []
    started = time.monotonic()
    try:
        with pytest.raises(ConversionCancelled):
            qs.run_worker(job, job_dir, python=Path(sys.executable), script=fake.script,
                          env=fake.env(behavior="hang", at=0), log=logs.append, grace_s=0.3,
                          kill=killed.append, kill_wait_s=0.5,
                          cancel_check=lambda: any("running on" in m for m in logs))
        assert time.monotonic() - started < 60  # bounded, instead of waiting out the fake's 120 s sleep
        assert killed, "the supervisor did try to kill it"
    finally:
        for proc in killed:  # the stand-in kill did nothing, so end the real process ourselves
            qs.kill_process_tree(proc)
        qs.remove_job_dir(job_dir)


def test_the_worker_is_always_started_with_mandatory_containment(fake, monkeypatch):
    """A worker that could outlive a Cancel must never be started: containment is required, not best effort."""
    seen = []
    real = qs.qwen3_process.spawn
    monkeypatch.setattr(qs.qwen3_process, "spawn", lambda cmd, **kwargs: seen.append(kwargs.get("require_job")) or real(cmd, **kwargs))
    fake.convert()
    assert seen == [True]


def test_the_ffmpeg_encode_may_go_without_a_job_because_it_starts_no_children(tmp_path, monkeypatch):
    seen = []

    class Done:
        returncode = 0
        act_job = None

        def poll(self):
            return 0

    monkeypatch.setattr(qs.qwen3_process, "spawn", lambda cmd, **kwargs: seen.append(kwargs.get("require_job")) or Done())
    monkeypatch.setattr(qs.qwen3_process, "release", lambda proc: None)
    qs.encode_mp3(tmp_path / "a.wav", tmp_path / "a.mp3", None, work_dir=tmp_path, ffmpeg="ffmpeg-for-the-test")
    assert seen == [None]


# --------------------------------------------------------------------------- #
# The conversion holds the machine-wide lease (Codex S3: setup and inference must exclude each other)
# --------------------------------------------------------------------------- #
def test_a_conversion_cannot_start_while_the_voices_are_being_installed_or_repaired(fake):
    from tts import qwen3_setup as su

    with su.InstallLock():
        with pytest.raises(rt.Qwen3Unavailable, match="being installed or repaired"):
            fake.convert()
    assert fake.exported == {} and fake.job_folders() == [] and fake.logs == []  # nothing was started


def test_the_conversion_holds_the_lease_for_its_whole_run_and_always_gives_it_back(fake):
    from tts import qwen3_setup as su

    during = []

    def watching_encoder(wav, mp3, bitrate, *, work_dir, cancel_check=None):
        try:
            su.InstallLock().acquire()
            during.append("install was allowed to start")
        except su.SetupError as exc:
            during.append(str(exc))
        mp3.write_bytes(b"MP3-BYTES")

    fake.convert(encoder=watching_encoder)
    assert during and "being used by a conversion right now" in during[0]
    for failure in ({"behavior": "fail"}, {"behavior": "exit_early"}):
        with pytest.raises(qs.Qwen3Failed):
            fake.convert(plan=failure)
    with pytest.raises(ConversionCancelled):
        fake.convert(cancel_check=lambda: True, grace_s=0.3)
    with su.InstallLock():  # free after success, failure, crash and cancel alike
        pass


# --------------------------------------------------------------------------- #
# The clone narration profile (owner preference, 2026-10-20)
# --------------------------------------------------------------------------- #
def test_the_clone_profile_is_the_owners_calmer_sampling_and_leaves_the_text_pipeline_revision_alone():
    assert qs.CLONE_GENERATION == {"temperature": 0.70, "subtalker_temperature": 0.80}
    assert qs.CLONE_GENERATION_REVISION == 1
    assert qs.PIPELINE_REVISION == 1  # the A0-characterized planner/seed/assembly revision is pinned by the immutable golden
    assert set(qs.CLONE_GENERATION) == {"temperature", "subtalker_temperature"}  # top_p, top_k, repetition_penalty stay the model's own


def test_only_a_clone_job_carries_the_profile_and_each_job_gets_its_own_copy(tmp_path):
    chunks = qs.plan_chunks("One chunk of text.")
    for voice_id in ("qwen3-female-1", "qwen3-female-2", "qwen3-male-1", "qwen3-male-2", "qwen3-male-3", "qwen3-male-4"):
        job = qs.build_job(rt.get_voice(voice_id), chunks, job_dir=tmp_path, model_dir=tmp_path / "m", reference_text="words")
        assert job["generation"] == {"temperature": 0.7, "subtalker_temperature": 0.8}, voice_id
        job["generation"]["temperature"] = 0.1  # a mutated job must not change the application's profile
        assert qs.CLONE_GENERATION["temperature"] == 0.70
    for voice_id in ("qwen3-aiden", "qwen3-ryan"):
        preset = qs.build_job(rt.get_voice(voice_id), chunks, job_dir=tmp_path, model_dir=tmp_path / "m")
        assert "generation" not in preset, voice_id  # Aiden and Ryan are not touched
    seeds = [c["seed"] for c in qs.build_job(rt.get_voice("qwen3-male-1"), chunks, job_dir=tmp_path, model_dir=tmp_path / "m")["chunks"]]
    assert seeds == [qs.derive_seed("qwen3-male-1", c) for c in chunks]  # the deterministic chunk seeds are unchanged


def test_a_clone_run_sends_the_worker_the_profile_and_logs_it_while_a_preset_run_does_neither(fake, monkeypatch, tmp_path):
    monkeypatch.setattr(rt, "load_transcript", lambda voice_id: rt.Transcript(True, "approved fixture words", "ok"))
    source = tmp_path / "t.txt"
    source.write_text("Some text to read aloud.", encoding="utf-8")
    seen, logs = {}, {}
    for voice_id in ("qwen3-male-3", "qwen3-ryan"):
        log_file = tmp_path / f"job-{voice_id}.json"
        env = fake.env()
        env["FAKE_QWEN3_LOG"] = str(log_file)
        logs[voice_id] = []
        qs.qwen3_file_to_mp3(str(source), str(tmp_path / f"{voice_id}.mp3"), voice_id, python=Path(sys.executable), script=fake.script,
                             jobs_root=fake.jobs, env=env, availability=lambda v: (True, "ok"), log=logs[voice_id].append)
        seen[voice_id] = json.loads(log_file.read_text("utf-8"))
    assert seen["qwen3-male-3"]["generation"] == {"temperature": 0.7, "subtalker_temperature": 0.8}
    assert "generation" not in seen["qwen3-ryan"]
    assert any("clone generation profile 1: temperature 0.70, sub-talker 0.80" in line for line in logs["qwen3-male-3"])
    assert not any("generation profile" in line for line in logs["qwen3-ryan"])
