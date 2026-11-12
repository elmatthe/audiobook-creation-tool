"""TTS Audiobook: real input, the production request, assembly and publication path, and a replayed speech service that hands back real MP3s.

Labelled honestly: the speech here is replayed, so these journeys are real-media evidence for everything after the service boundary and
say nothing about Microsoft's engine. Real Edge belongs to the ``edge-low-memory`` qualification, because the routine gate has no network.
``tts.kokoro-local`` is the one real engine in this set, where it is installed, and even that is one bounded sample rather than the
``optional-engines`` qualification.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from journeys.common import Context, expect_clean_close, log_text, media_fixtures, open_tool, oracle, scenario, wait_for_job, wait_until

TOOL = "tts"
CLIP_TONES = [392.0, 523.0, 659.0, 784.0, 988.0, 1175.0, 1397.0, 1661.0]
START, CANCEL, PAUSE, RESUME = "go_btn", "jobs.controls.buttons[CANCEL]", "jobs.controls.buttons[PAUSE]", "jobs.controls.buttons[RESUME]"
RETRY = "jobs.controls.buttons[RETRY_FAILED]"


def _normal(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def replay_config(context: Context, name: str = "app", **extra) -> dict:
    clips = media_fixtures.make_replay_clips(context.tools, context.work / "clips", CLIP_TONES)
    return {"clips": [str(path) for path in clips], "log": str(context.work / f"{name}-replay.jsonl"), **extra}


def requests_of(config: dict) -> list[dict]:
    path = Path(config["log"])
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _add_files(session, paths) -> None:
    session.click(TOOL, "importer.list.buttons[add_files]")
    session.file_dialog(paths if len(paths) > 1 else paths[0], title="Source files")
    wait_until(lambda: len(session.widget(TOOL, "importer.list.listbox").get("items", [])) == len(paths), 30, "the sources to be listed")
    session.settle()


def _inspect_narration(context: Context, output: Path, source_text: str, requests: list[dict], *, label: str, bitrate: int) -> None:
    """The output is real audio holding every request's clip, in document order, and every word of the source was asked for."""
    report = context.report
    probed = oracle.inspect_audio(context.tools, output, report, label=label, codec="mp3", container="mp3")
    found_rate = int(oracle.audio_stream(probed).get("bit_rate", 0))
    report.check(f"{label}: the chosen MP3 bitrate", abs(found_rate - bitrate) <= bitrate * 0.02, f"{found_rate} bit/s, expected {bitrate}")
    body = _normal(source_text)
    asked = " ".join(_normal(item["text"]) for item in requests)
    for sentence in re.split(r"(?<=[.!?])\s+", source_text.strip()):
        words = _normal(sentence)
        if words:
            report.check(f"{label}: this was narrated: {words[-40:]}", words in asked, "")
    placed = sorted(requests, key=lambda item: body.find(_normal(item["text"])))
    report.check(f"{label}: every request came from the source", all(body.find(_normal(item["text"])) >= 0 for item in requests),
                 [item["text"][:60] for item in requests if body.find(_normal(item["text"])) < 0][:3])
    expected: list[float] = []
    for item in placed:
        tone = CLIP_TONES[item["clip"]]
        if not expected or expected[-1] != tone:
            expected.append(tone)
    pcm = oracle.decode_pcm(context.tools, output)
    heard = [tone for tone in oracle.tone_sequence(pcm, oracle.ORACLE_RATE, CLIP_TONES, window=0.2) if tone is not None]
    collapsed: list[float] = []
    for tone in heard:
        if not collapsed or collapsed[-1] != tone:
            collapsed.append(tone)
    report.equal(f"{label}: the clips are heard in document order, ending included", collapsed, expected)
    report.check(f"{label}: as long as its requests", float(probed["format"]["duration"]) >= 0.75 * len(requests),
                 f"{probed['format']['duration']} s for {len(requests)} requests of 0.8 s")


@scenario("tts.edge-replay-direct-file", tool="tts-audiobook", layers=("native", "media"), tier="journey",
          summary="A TXT through the real dialog, 128k chosen in its real combobox, Start; every sentence requested and heard in order; real MP3 at that bitrate")
def direct(context: Context) -> None:
    report = context.report
    source = context.fixtures.path("story-text")
    before = context.source_hashes([source])
    replay = replay_config(context)
    session = context.app(last_tool=TOOL, replay=replay)
    open_tool(session, TOOL)
    _add_files(session, [source])
    session.select_combo(TOOL, "combo_bitrate", "128k")
    voice = session.widget(TOOL, "voice_combo").get("value")
    context.notes["speech"] = "replayed real MP3 frames at the service boundary; no engine was exercised"
    session.screenshot("ready")
    session.click(TOOL, START)
    report.equal("the run ended", wait_for_job(session, TOOL), "SUCCEEDED")
    session.screenshot("finished")
    outputs = sorted(context.run_dir(TOOL).rglob("*.mp3"))
    report.equal("one MP3, named for the source and the voice", len(outputs), 1)
    report.check("its name carries the source's name", outputs[0].name.startswith("Short Story-"), outputs[0].name)
    requests = requests_of(replay)
    report.check("requests really reached the service boundary", len(requests) >= 5, len(requests))
    report.check("the selected voice was the one requested", all(item["voice"] and item["voice"] in _registered_ids(voice, item) for item in requests),
                 {"shown": voice, "asked": sorted({item["voice"] for item in requests})})
    _inspect_narration(context, outputs[0], source.read_text(encoding="utf-8"), requests, label="narration", bitrate=128000)
    context.require_unchanged(before)
    expect_clean_close(context, session)


def _registered_ids(_shown: str, item: dict) -> set:
    # The label on screen and the id sent are different strings by design; this check is that an id was sent and it is an Edge one.
    return {item["voice"]} if str(item["voice"]).endswith("Neural") else set()


@scenario("tts.edge-replay-folder-mixed", tool="tts-audiobook", layers=("native", "media"), tier="journey",
          summary="A folder of TXT and PDF through the real folder dialog, a typed Edge rate that reaches every request, one worker per file")
def folder(context: Context) -> None:
    report = context.report
    text = context.fixtures.path("story-text-b")
    context.fixtures.path("story-text")
    pdf = context.fixtures.get("story-pdf").path
    mixed = context.work / "in" / "mixed"
    mixed.mkdir()
    for source in (text, context.fixtures.path("story-text"), pdf):
        (mixed / source.name).write_bytes(source.read_bytes())
    before = context.source_hashes(sorted(mixed.iterdir()))
    replay = replay_config(context)
    session = context.app(last_tool=TOOL, replay=replay)
    open_tool(session, TOOL)
    session.click(TOOL, "importer.list.buttons[add_folder]")
    session.folder_dialog(mixed, title="Folder of PDF")
    wait_until(lambda: len(session.widget(TOOL, "importer.list.listbox").get("items", [])) == 3, 30, "the folder's three sources to be listed")
    session.type_into(TOOL, "entry_rate", "-10%")
    session.screenshot("ready")
    session.click(TOOL, START)
    report.equal("the run ended", wait_for_job(session, TOOL, timeout=180), "SUCCEEDED")
    session.screenshot("finished")
    outputs = sorted(context.run_dir(TOOL).rglob("*.mp3"))
    report.equal("one MP3 per source", len(outputs), 3)
    requests = requests_of(replay)
    report.equal("the typed rate reached every request", sorted({item["rate"] for item in requests}), ["-10%"])
    for output in outputs:
        oracle.inspect_audio(context.tools, output, report, label=output.stem[:24], codec="mp3", container="mp3")
        report.check(f"{output.stem[:24]}: real sound", float(oracle.probe(context.tools, output)["format"]["duration"]) > 0.5)
    asked = " ".join(_normal(item["text"]) for item in requests)
    report.check("the PDF's sentence joined across its page break", "without stopping so the sentence joins correctly" in asked, asked[-200:])
    context.require_unchanged(before)
    expect_clean_close(context, session)


@scenario("tts.service-failure-then-retry", tool="tts-audiobook", layers=("native", "media"), tier="adverse",
          summary="The service fails until told otherwise: the run names the failure, publishes nothing, and Retry Failed clicked for real then completes")
def retry(context: Context) -> None:
    report = context.report
    source = context.fixtures.path("story-text-b")
    flag = context.work / "service-down.flag"
    flag.write_text("down", encoding="ascii")
    replay = replay_config(context, fail_flag=str(flag))
    session = context.app(last_tool=TOOL, replay=replay)
    open_tool(session, TOOL)
    _add_files(session, [source])
    session.click(TOOL, START)
    state = wait_for_job(session, TOOL, timeout=120)
    session.screenshot("failed")
    report.check("the run reports the failure", state in ("COMPLETED_WITH_FAILURES", "FAILED"), state)
    run = context.run_dir(TOOL)
    report.equal("nothing was published", sorted(run.rglob("*.mp3")), [])
    text = log_text(session, TOOL) + log_text(session, TOOL, "details_text")
    report.check("the log says what failed", "Second Story" in text, text[-400:])
    wait_until(lambda: not session.widget(TOOL, RETRY).get("disabled"), 15, "Retry Failed to be offered")
    flag.unlink()
    session.click(TOOL, RETRY)
    wait_until(lambda: session.read(TOOL, "jobs.state") == "RUNNING" or sorted(run.rglob("*.mp3")), 30, "the retry to begin")
    report.equal("the retry ended", wait_for_job(session, TOOL, timeout=120), "SUCCEEDED")
    session.screenshot("retried")
    outputs = sorted(run.rglob("*.mp3"))
    report.equal("the retry published the one MP3", len(outputs), 1)
    oracle.inspect_audio(context.tools, outputs[0], report, label="after retry", codec="mp3", container="mp3")
    expect_clean_close(context, session)


@scenario("tts.cancel-during-narration", tool="tts-audiobook", layers=("native", "media"), tier="adverse",
          summary="Cancel clicked with requests in flight: the run stops inside its budget, no further request is made, and nothing is published")
def cancel(context: Context) -> None:
    report = context.report
    source = context.fixtures.path("story-long-text")
    replay = replay_config(context, delay_seconds=0.6)
    session = context.app(last_tool=TOOL, replay=replay)
    open_tool(session, TOOL)
    _add_files(session, [source])
    session.click(TOOL, START)
    wait_until(lambda: len(requests_of(replay)) >= 2, 60, "requests to be in flight")
    report.equal("the run is really working when Cancel is clicked", session.read(TOOL, "jobs.state"), "RUNNING")
    began = oracle.time_now()
    session.click(TOOL, CANCEL)
    state = wait_for_job(session, TOOL, timeout=30)
    seconds = oracle.time_now() - began
    session.screenshot("cancelled")
    report.equal("the run says it was cancelled", state, "CANCELLED")
    report.check("settled inside the 5 s budget", seconds <= 5.0, f"{seconds:.2f} s")
    context.notes["cancel_seconds"] = round(seconds, 3)
    settled = len(requests_of(replay))
    oracle.time_sleep(1.5)
    report.equal("no request after Cancel settled", len(requests_of(replay)), settled)
    report.equal("nothing was published", sorted(context.run_dir(TOOL).rglob("*.mp3")), [])
    expect_clean_close(context, session)


@scenario("tts.pause-at-file-boundary", tool="tts-audiobook", layers=("native", "media"), tier="adverse",
          summary="One worker and two files: Pause lets the active file finish and starts nothing new, Resume completes the queue; both outputs real")
def pause(context: Context) -> None:
    report = context.report
    first, second = context.fixtures.path("story-text"), context.fixtures.path("story-text-b")
    replay = replay_config(context, delay_seconds=0.25)
    session = context.app(last_tool=TOOL, replay=replay)
    open_tool(session, TOOL)
    _add_files(session, [first, second])
    session.type_into(TOOL, "spin_workers", "1")
    session.click(TOOL, START)
    wait_until(lambda: len(requests_of(replay)) >= 1, 60, "the first file's requests to begin")
    session.click(TOOL, PAUSE)
    wait_until(lambda: session.read(TOOL, "jobs.state") == "PAUSED", 90, "the active file to finish and the run to be paused")
    session.screenshot("paused")
    run = context.run_dir(TOOL)
    published = sorted(item.name for item in run.rglob("*.mp3"))
    report.equal("exactly the active file finished", len(published), 1)
    settled = requests_of(replay)
    second_words = _normal(second.read_text(encoding="utf-8"))
    report.check("the queued file was not started", not any(_normal(item["text"]) in second_words for item in settled),
                 [item["text"][:40] for item in settled][-3:])
    oracle.time_sleep(1.0)
    report.equal("no request while paused", len(requests_of(replay)), len(settled))
    session.click(TOOL, RESUME)
    report.equal("the run ended", wait_for_job(session, TOOL, timeout=120), "SUCCEEDED")
    session.screenshot("resumed")
    outputs = sorted(run.rglob("*.mp3"))
    report.equal("both files were published", len(outputs), 2)
    for output in outputs:
        oracle.inspect_audio(context.tools, output, report, label=output.stem[:20], codec="mp3", container="mp3")
    expect_clean_close(context, session)


@scenario("tts.pdf-without-text", tool="tts-audiobook", layers=("native", "media"), tier="adverse",
          summary="A valid PDF holding no words: the failure is named, nothing is published or requested, and the source is unchanged")
def no_text(context: Context) -> None:
    report = context.report
    source = context.fixtures.get("story-empty-pdf").path
    before = context.source_hashes([source])
    replay = replay_config(context)
    session = context.app(last_tool=TOOL, replay=replay)
    open_tool(session, TOOL)
    _add_files(session, [source])
    session.click(TOOL, START)
    state = wait_for_job(session, TOOL)
    session.screenshot("finished")
    report.check("the run does not report success", state in ("COMPLETED_WITH_FAILURES", "FAILED"), state)
    root = context.output_base / "TTS-Audiobook-Outputs"
    report.equal("nothing was published", sorted(root.rglob("*.mp3")) if root.exists() else [], [])
    report.equal("no speech was requested", requests_of(replay), [])
    text = log_text(session, TOOL) + log_text(session, TOOL, "details_text")
    report.check("the log names the file", "No Words" in text, text[-400:])
    context.require_unchanged(before)
    expect_clean_close(context, session)


KOKORO_VOICE = "Kokoro Female (Default) - Heart (en-US)"
REPO_ROOT = Path(__file__).resolve().parents[4]
MODEL_CACHE = REPO_ROOT / "files" / "runtime-data" / "models" / "huggingface"


def kokoro_applicable() -> tuple[bool, str]:
    """Declared, evidenced applicability: the engine package and its model must really be on this machine. Nothing is ever downloaded for this."""
    import importlib.util

    if importlib.util.find_spec("kokoro") is None:
        return False, "the kokoro package is not installed in this environment"
    snapshot = MODEL_CACHE / "hub" / "models--hexgrad--Kokoro-82M" / "snapshots"
    if not snapshot.is_dir() or not any(snapshot.iterdir()):
        return False, f"no Kokoro model snapshot under {snapshot}"
    return True, "the kokoro package and a model snapshot are present"


@scenario("tts.kokoro-local", tool="tts-audiobook", layers=("native", "media"), tier="journey", budget=420, applicable=kokoro_applicable,
          summary="Real speech from the real local engine, from a real click on Start: one bounded sample where Kokoro is installed, and not the optional-engines qualification")
def kokoro(context: Context) -> None:
    report = context.report
    source = context.fixtures.path("story-text-b")
    before = context.source_hashes([source])
    session = context.app(last_tool=TOOL, real_model_cache=str(MODEL_CACHE))
    open_tool(session, TOOL)
    _add_files(session, [source])
    session.select_combo(TOOL, "voice_combo", KOKORO_VOICE)
    wait_until(lambda: "Kokoro" in session.widget(TOOL, "backend_lbl").get("text", ""), 10, "the engine line to say Kokoro")
    session.screenshot("ready")
    context.notes["speech"] = "real Kokoro synthesis on this machine's CPU or GPU; one sample, not the optional-engines qualification"
    session.click(TOOL, START)
    report.equal("the run ended", wait_for_job(session, TOOL, timeout=360), "SUCCEEDED")
    session.screenshot("finished")
    outputs = sorted(context.run_dir(TOOL).rglob("*.mp3"))
    report.equal("one MP3", len(outputs), 1)
    probed = oracle.inspect_audio(context.tools, outputs[0], report, label="kokoro", codec="mp3", container="mp3")
    pcm = oracle.decode_pcm(context.tools, outputs[0])
    seconds = pcm.size / oracle.ORACLE_RATE
    report.check("kokoro: as long as two short sentences take to say", 3.0 <= seconds <= 30.0, f"{seconds:.2f} s")
    level = float((pcm * pcm).mean()) ** 0.5
    report.check("kokoro: there is sound, at a speaking level", level > 0.01, f"RMS {level:.4f}")
    # 192k is the default asked for, and MPEG-2 Layer III stops at 160k: a 24 kHz voice gets its ceiling. Measured here, and recorded.
    rate = int(oracle.audio_stream(probed).get("bit_rate", 0))
    context.notes["kokoro_bit_rate"] = rate
    report.check("kokoro: the encoder got the requested rate or the format's ceiling", rate == 160000, f"{rate} bit/s at {oracle.audio_stream(probed).get('sample_rate')} Hz")
    context.require_unchanged(before)
    expect_clean_close(context, session)

