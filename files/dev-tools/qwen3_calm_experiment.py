"""Calm-narration comparison for the six Qwen3 Base clones (v0.6.7). Dev-only: never shipped, never imported by the app.

Question: does a lower sampling ``temperature`` make a clone narrate more evenly (less pitch, loudness and pace fluctuation,
fewer dramatic endings, less drift between adjacent chunks) without losing its identity or its words? The owner decides by
listening; the numbers here only support that.

    python files/dev-tools/qwen3_calm_experiment.py selfcheck            # prove the pinned library's sampling API (no model, no audio)
    python files/dev-tools/qwen3_calm_experiment.py plan                 # what would run, and whether each clone is ready
    python files/dev-tools/qwen3_calm_experiment.py run [--voices ...] [--temps 0.8 0.7 [0.6]]
    python files/dev-tools/qwen3_calm_experiment.py report RUN_DIR       # re-measure and rebuild the listening page

How it stays honest:

* Every clip goes through the PRODUCTION entry point ``qwen3_synth.qwen3_file_to_mp3`` with its own availability check, so a clone
  with no owner-approved, reference-bound transcript is refused exactly as in the app. Nothing is approved or bypassed here.
* The baseline (temperature 0.9, the Base model's own default) runs on the PRODUCTION worker with no override at all. A candidate
  runs the same production worker through ``qwen3_calm_worker.py``, which forwards one extra argument, ``temperature``. Every
  other control (top_p, top_k, repetition_penalty, the sub-talker's temperature 0.9, max_new_tokens), the reference recording,
  the transcript, the text, the chunking and each chunk's seed are identical across candidates.
* Only the six clone voices are accepted; Aiden, Ryan and every other voice are refused, and the voice asked for is the voice made.
* Audio, measurements and the listening page go under ignored ``files/dev-work/`` only, never into ``files/voice-previews/``.
"""
from __future__ import annotations

import argparse
import datetime
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parents[1]
SCRIPTS = ROOT / "scripts"
RUN_ROOT = ROOT / "files" / "dev-work" / "qwen3-eval" / "calm-narration"
WHISPER_DIR = ROOT / "files" / "dev-work" / "qwen3-eval" / "models" / "whisper-small.en"
DEV_WORKER = TOOLS / "qwen3_calm_worker.py"
VENV_TOOLS = TOOLS / "qwen3_calm_venv_tools.py"

BASELINE_TEMPERATURE = 0.9  # the Base model's own default; what production uses
CANDIDATE_TEMPERATURES = (0.8, 0.7)
OPTIONAL_TEMPERATURES = (0.6,)
TEMPERATURE_RANGE = (0.1, 1.5)
DEFAULT_VOICES = ("qwen3-female-1", "qwen3-male-1")
COMPARISON_MIN_CHARS = 2200  # about four 600-character chunks: enough for adjacent-chunk drift
ENV_VAR = "ACT_QWEN3_EXPERIMENT"


class ExperimentError(RuntimeError):
    pass


def _import_app():
    sys.path.insert(0, str(SCRIPTS))
    sys.path.insert(0, str(TOOLS))
    from tts import qwen3_runtime, qwen3_synth, voice_registry

    return qwen3_runtime, qwen3_synth, voice_registry


# --------------------------------------------------------------------------- #
# What is compared
# --------------------------------------------------------------------------- #
def comparison_text() -> str:
    """One fixed, copyright-safe passage with prose, dialogue, punctuation and paragraph transitions (the Qwen3 evaluation's own)."""
    sys.path.insert(0, str(TOOLS))
    from qwen_eval_corpus import EVAL_LONG

    paragraphs = EVAL_LONG.text.split("\n\n")[1:]  # without the title line
    chosen, total = [], 0
    for paragraph in paragraphs:
        chosen.append(paragraph)
        total += len(paragraph) + 2
        if total >= COMPARISON_MIN_CHARS:
            break
    return "\n\n".join(chosen) + "\n"


def is_baseline(temperature: float) -> bool:
    return abs(temperature - BASELINE_TEMPERATURE) < 1e-9


def label_for(temperature: float) -> str:
    return "baseline-T0.90" if is_baseline(temperature) else f"T{temperature:.2f}"


def normalise_temperatures(candidates) -> list[float]:
    """The baseline first, then each distinct candidate from highest to lowest. A value outside the allowed range is an error."""
    low, high = TEMPERATURE_RANGE
    out = {BASELINE_TEMPERATURE}
    for value in candidates:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
            raise ExperimentError(f"temperature must be a number from {low} to {high}, not {value!r}")
        out.add(round(float(value), 4))
    return sorted(out, reverse=True)


# --------------------------------------------------------------------------- #
# Readiness: the app's own rules, never a shortcut
# --------------------------------------------------------------------------- #
def clone_voice(voice_id: str):
    rt, _synth, _registry = _import_app()
    try:
        voice = rt.get_voice(voice_id)
    except Exception as exc:  # noqa: BLE001 - an unknown id is a refusal, not a guess
        raise ExperimentError(f"{voice_id!r} is not a Qwen3 voice") from exc
    if voice.kind != rt.KIND_CLONE:
        raise ExperimentError(f"{voice_id} is a preset voice; this experiment covers the six cloned voices only")
    return voice


def check_ready(voice_id: str, availability=None):
    """The clone, once it is a registered clone, its reference is the approved recording, and the app says it can run."""
    rt, _synth, _registry = _import_app()
    voice = clone_voice(voice_id)
    reference = rt.reference_path(voice)
    if not reference.is_file() or rt.sha256_file(reference) != voice.reference_sha256:
        raise ExperimentError(f"{voice.label}: the reference recording is not the one the app registered")
    ok, reason = (availability or rt.voice_availability)(voice_id)
    if not ok:
        raise ExperimentError(f"{voice.label} is not ready: {reason}")
    return voice


def readiness(voice_ids, availability=None) -> dict:
    out = {}
    for voice_id in voice_ids:
        try:
            check_ready(voice_id, availability)
            out[voice_id] = "ready"
        except ExperimentError as exc:
            out[voice_id] = str(exc)
    return out


# --------------------------------------------------------------------------- #
# Generating one clip through the production entry point
# --------------------------------------------------------------------------- #
def wav_encoder(wav, mp3, bitrate, *, work_dir, cancel_check=None):
    shutil.copyfile(wav, mp3)  # keep the lossless WAV; the "mp3" name is only the hand-off path


def synth_kwargs(temperature: float) -> dict:
    """The seam arguments for one candidate. The baseline passes none: it IS the production worker."""
    rt, _synth, _registry = _import_app()
    if is_baseline(temperature):
        return {}
    env = dict(rt.worker_environment())
    env[ENV_VAR] = json.dumps({"temperature": float(temperature)})
    return {"script": DEV_WORKER, "env": env}


def chunk_plan(voice_id: str, text_path: Path):
    """Each chunk's production seed and word count for this text, computed the way the engine plans it."""
    _rt, synth, _registry = _import_app()
    from tts.speech.document import read_source_text

    prepared = synth.prepare(read_source_text(text_path), None, synth.QWEN3_ROUTE)
    chunks = synth.plan_chunks(prepared.text)
    return [synth.derive_seed(voice_id, c) for c in chunks], [len(c.text.split()) for c in chunks]


def run_one(voice_id: str, temperature: float, text_path: Path, out_wav: Path, *, gap_ms: int, synth=None, log=print) -> dict:
    _rt, qwen3_synth, _registry = _import_app()
    call = synth or qwen3_synth.qwen3_file_to_mp3
    started = time.perf_counter()
    # No `availability`, `python` or `encoder`-of-the-engine override: the app's own readiness and transcript rules apply.
    call(str(text_path), str(out_wav), voice_id, end_silence_ms=0, chunk_pause_ms=gap_ms, log=log, encoder=wav_encoder,
         **synth_kwargs(temperature))
    return {"wall_s": round(time.perf_counter() - started, 1)}


def run(voices, candidates, *, run_id: str | None = None, run_root: Path = RUN_ROOT, synth=None, availability=None,
        log=print, measure=True) -> Path:
    rt, _synth, registry = _import_app()
    temperatures = normalise_temperatures(candidates)
    voices = list(dict.fromkeys(voices))
    if not voices:
        raise ExperimentError("no voice was chosen")
    not_ready = {v: r for v, r in readiness(voices, availability).items() if r != "ready"}
    if not_ready:  # all or nothing, before any audio is made
        raise ExperimentError("; ".join(f"{r}" for r in not_ready.values()))
    entries = {e.voice_id: e for e in registry.VOICES}
    run_dir = Path(run_root) / (run_id or datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    if run_dir.exists():
        raise ExperimentError(f"{run_dir.name} already exists; a run never overwrites another")
    run_dir.mkdir(parents=True)
    text = comparison_text()
    text_path = run_dir / "narration.txt"
    text_path.write_text(text, encoding="utf-8")
    manifest = {"schema": 1, "created": datetime.datetime.now().isoformat(timespec="seconds"), "temperatures": temperatures,
                "baseline": BASELINE_TEMPERATURE, "subtalker_temperature": "unchanged (0.9, the model's own)",
                "text_sha256": rt.sha256_file(text_path), "text_chars": len(text), "clips": []}
    for voice_id in voices:
        voice = clone_voice(voice_id)
        gap_ms = int(entries[voice_id].timing_preset["paragraphpause"])
        seeds, words = chunk_plan(voice_id, text_path)
        transcript = rt.load_transcript(voice_id)
        for temperature in temperatures:
            out = run_dir / voice_id / f"{label_for(temperature)}.wav"
            out.parent.mkdir(parents=True, exist_ok=True)
            log(f"== {voice.label}  {label_for(temperature)}")
            info = run_one(voice_id, temperature, text_path, out, gap_ms=gap_ms, synth=synth, log=log)
            manifest["clips"].append({
                "voice_id": voice_id, "label": label_for(temperature), "temperature": temperature,
                "worker": "production" if is_baseline(temperature) else "dev wrapper (temperature only)",
                "file": out.relative_to(run_dir).as_posix(), "gap_ms": gap_ms, "chunk_seeds": seeds, "chunk_words": words,
                "reference_sha256": voice.reference_sha256, "transcript_sha256": rt.transcript_sha256(transcript.text),
                **info})
            (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    if measure:
        report(run_dir, log=log)
    return run_dir


# --------------------------------------------------------------------------- #
# Measurements (they support the owner's listening; they do not replace it)
# --------------------------------------------------------------------------- #
FRAME_MS = 10
SILENCE_DB = -50.0
PHRASE_GAP_S = 0.25  # a pause at least this long ends a phrase


def _runs(mask: np.ndarray, value: bool, min_len: int) -> list[tuple[int, int]]:
    """[start, end) frame ranges where ``mask == value`` for at least ``min_len`` frames."""
    out, start = [], None
    for i, flag in enumerate(np.append(mask, not value)):
        if flag == value and start is None:
            start = i
        elif flag != value and start is not None:
            if i - start >= min_len:
                out.append((start, i))
            start = None
    return out


def _st(f0: np.ndarray, ref: float) -> np.ndarray:
    return 12.0 * np.log2(f0 / ref)


def analyze_audio(path, *, gap_ms: int = 700, chunk_words: list[int] | None = None) -> dict:
    """Pitch, loudness and pace steadiness of one clip. Pitch is in semitones around the clip's own median."""
    import librosa

    audio, rate = sf.read(str(path), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    hop = int(rate * FRAME_MS / 1000)
    rms = librosa.feature.rms(y=audio, frame_length=int(rate * 0.025), hop_length=hop, center=True)[0]
    db = 20 * np.log10(np.maximum(rms, 1e-9))
    active = db > SILENCE_DB
    f0, voiced, _ = librosa.pyin(audio, fmin=60, fmax=450, sr=rate, frame_length=2048, hop_length=hop)
    n = min(len(f0), len(db))
    f0, active, db = f0[:n], active[:n], db[:n]
    ok = np.isfinite(f0)
    median_hz = float(np.median(f0[ok])) if ok.any() else float("nan")
    st = np.full(n, np.nan)
    st[ok] = _st(f0[ok], median_hz)
    st[np.abs(st) > 12] = np.nan  # octave-tracking errors are not intonation

    pause_frames = int(PHRASE_GAP_S * 1000 / FRAME_MS)
    chunk_gap_frames = int(0.6 * gap_ms / FRAME_MS)
    quiet = _runs(active, False, pause_frames)
    inner = [(a, b) for a, b in quiet if a > 0 and b < n]  # drop leading and trailing silence

    def spans(gaps):
        edges = [0, *[x for g in gaps for x in g], n]
        return [(edges[i], edges[i + 1]) for i in range(0, len(edges), 2) if edges[i + 1] - edges[i] > 5]

    phrases = spans(inner)
    segments = spans([g for g in inner if g[1] - g[0] >= chunk_gap_frames])

    ranges, endings = [], []
    for a, b in phrases:
        values = st[a:b][np.isfinite(st[a:b])]
        if values.size >= 20:
            ranges.append(float(np.percentile(values, 90) - np.percentile(values, 10)))
            tail = max(5, values.size // 5)
            endings.append(float(np.median(values[-tail:]) - np.median(values[:-tail])))

    def seg_median(series, a, b):
        values = series[a:b]
        values = values[np.isfinite(values)]
        return float(np.median(values)) if values.size else float("nan")

    seg_f0 = [seg_median(f0, a, b) for a, b in segments]
    seg_db = [seg_median(np.where(active, db, np.nan), a, b) for a, b in segments]
    speech_s = float(np.sum(active)) * FRAME_MS / 1000.0
    long_pauses_s = sum(b - a for a, b in quiet) * FRAME_MS / 1000.0
    duration = audio.size / rate
    out = {
        "duration_s": round(duration, 1), "peak": round(float(np.max(np.abs(audio))), 3),
        "f0_median_hz": round(median_hz, 1),
        "f0_sd_st": round(float(np.nanstd(st)), 2),
        "f0_p5_p95_st": round(float(np.nanpercentile(st, 95) - np.nanpercentile(st, 5)), 2),
        "phrase_pitch_range_mean_st": round(float(np.mean(ranges)), 2) if ranges else None,
        "phrase_pitch_range_max_st": round(float(np.max(ranges)), 2) if ranges else None,
        "ending_fall_mean_st": round(float(np.mean(endings)), 2) if endings else None,
        "loudness_sd_db": round(float(np.std(db[active])), 2) if active.any() else None,
        "pace_wps": None, "segments": len(segments), "phrases": len(phrases),
        "segment_f0_hz": [round(x, 1) for x in seg_f0], "segment_level_db": [round(x, 1) for x in seg_db],
        "adjacent_f0_delta_max_st": None, "adjacent_level_delta_max_db": None, "adjacent_pace_delta_max_wps": None,
        "segments_match_chunks": None,
    }
    if len(seg_f0) > 1:
        deltas = [abs(_st(np.array([y]), x)[0]) for x, y in zip(seg_f0, seg_f0[1:]) if np.isfinite(x) and np.isfinite(y)]
        out["adjacent_f0_delta_max_st"] = round(max(deltas), 2) if deltas else None
        levels = [abs(y - x) for x, y in zip(seg_db, seg_db[1:]) if np.isfinite(x) and np.isfinite(y)]
        out["adjacent_level_delta_max_db"] = round(max(levels), 2) if levels else None
    if chunk_words:
        total_words = sum(chunk_words)
        out["pace_wps"] = round(total_words / max(duration - long_pauses_s, 1e-6), 2)
        match = len(segments) == len(chunk_words)
        out["segments_match_chunks"] = match
        if match and len(segments) > 1:
            paces = [w / max((b - a) * FRAME_MS / 1000.0 - 0.0, 1e-6) for w, (a, b) in zip(chunk_words, segments)]
            out["adjacent_pace_delta_max_wps"] = round(max(abs(y - x) for x, y in zip(paces, paces[1:])), 2)
    return out


def words_of(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def word_error_rate(reference: str, heard: str) -> float:
    r, h = words_of(reference), words_of(heard)
    d = np.zeros((len(r) + 1, len(h) + 1), dtype=int)
    d[:, 0], d[0, :] = range(len(r) + 1), range(len(h) + 1)
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1, d[i - 1, j - 1] + (r[i - 1] != h[j - 1]))
    return float(d[-1, -1]) / max(1, len(r))


def tail_present(reference: str, heard: str, n: int = 8) -> bool:
    """Whether the last ``n`` words of the text were spoken (a cut-off ending would lose them)."""
    tail = words_of(reference)[-n:]
    spoken = set(words_of(heard)[-(n + 6):])
    return sum(w in spoken for w in tail) >= max(1, int(0.75 * len(tail)))


def read_back(wavs: list[Path], log=print) -> dict:
    """Transcribe the clips with the local whisper-small.en inside ``.venv-qwen3``; ``{}`` when that is not available."""
    rt, _synth, _registry = _import_app()
    if not WHISPER_DIR.is_dir():
        log("(no local whisper-small.en: completeness read-back skipped)")
        return {}
    out_json = Path(wavs[0]).parent.parent / "readback.json"
    result = subprocess.run([str(rt.venv_python()), "-I", str(VENV_TOOLS), "asr", str(WHISPER_DIR), str(out_json),
                             *[str(w) for w in wavs]], capture_output=True, text=True, env=rt.worker_environment())
    if result.returncode != 0 or not out_json.is_file():
        log("(completeness read-back failed: " + (result.stderr or "")[-300:].strip() + ")")
        return {}
    return json.loads(out_json.read_text(encoding="utf-8"))


def report(run_dir: Path, *, log=print, asr: bool = True) -> None:
    """Measure every clip in a run, write ``metrics.json`` and the labelled listening page."""
    run_dir = Path(run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    text = (run_dir / "narration.txt").read_text(encoding="utf-8")
    wavs = [run_dir / c["file"] for c in manifest["clips"]]
    heard = read_back(wavs, log) if asr and wavs else {}
    metrics = {}
    for clip in manifest["clips"]:
        path = run_dir / clip["file"]
        row = analyze_audio(path, gap_ms=clip["gap_ms"], chunk_words=clip["chunk_words"])
        transcript = heard.get(str(path))
        if transcript is not None:
            row["read_back_wer"] = round(word_error_rate(text, transcript), 3)
            row["ending_spoken"] = tail_present(text, transcript)
        metrics[f"{clip['voice_id']}/{clip['label']}"] = row
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=1), encoding="utf-8")
    (run_dir / "listen.html").write_text(render_listening_page(manifest, metrics, text), encoding="utf-8", newline="\n")
    log(f"Listening page: {run_dir / 'listen.html'}")


COLUMNS = (("f0_sd_st", "pitch spread (st)"), ("phrase_pitch_range_mean_st", "phrase pitch range (st)"),
           ("ending_fall_mean_st", "ending fall (st)"), ("loudness_sd_db", "loudness spread (dB)"),
           ("adjacent_f0_delta_max_st", "max chunk-to-chunk pitch step (st)"),
           ("adjacent_level_delta_max_db", "max chunk-to-chunk level step (dB)"), ("pace_wps", "words/s"),
           ("duration_s", "length (s)"), ("read_back_wer", "read-back WER"), ("ending_spoken", "ending spoken"))


def render_listening_page(manifest: dict, metrics: dict, text: str) -> str:
    sections = []
    for voice_id in dict.fromkeys(c["voice_id"] for c in manifest["clips"]):
        rows = []
        for clip in (c for c in manifest["clips"] if c["voice_id"] == voice_id):
            m = metrics.get(f"{voice_id}/{clip['label']}", {})
            cells = "".join(f"<td>{html.escape(str(m.get(key, '')))}</td>" for key, _ in COLUMNS)
            rows.append(f"<tr><th>{html.escape(clip['label'])}<br><small>temperature {clip['temperature']}</small></th>"
                        f"<td><audio controls preload=\"none\" src=\"{html.escape(clip['file'])}\"></audio></td>{cells}</tr>")
        head = "".join(f"<th>{html.escape(name)}</th>" for _, name in COLUMNS)
        sections.append(f"<h2>{html.escape(voice_id)}</h2><table><tr><th>Candidate</th><th>Listen</th>{head}</tr>{''.join(rows)}</table>")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Qwen3 clone calm-narration comparison</title><style>
body{{font:16px/1.5 system-ui,sans-serif;max-width:1100px;margin:0 auto;padding:16px;background:#fafaf7;color:#1d1d1b}}
table{{border-collapse:collapse;width:100%;margin:8px 0 24px}}th,td{{border:1px solid #d9d8d2;padding:6px 8px;text-align:left;font-size:.9rem}}
small{{color:#5d5d58}}audio{{width:260px}}@media (prefers-color-scheme:dark){{body{{background:#161614;color:#ecebe6}}th,td{{border-color:#38372f}}}}
</style></head><body>
<h1>Qwen3 clone calm-narration comparison</h1>
<p>The same passage, the same reference voice, transcript, seeds and every setting except <b>temperature</b>. <b>baseline-T0.90</b> is what the app does today.
Lower pitch spread, phrase pitch range, ending fall and chunk-to-chunk steps mean a calmer, more even delivery; the numbers only support your ears. Check the words and the ending too.</p>
{''.join(sections)}
<p><small>Passage ({manifest['text_chars']} characters, SHA-256 {html.escape(manifest['text_sha256'][:16])}...):</small></p>
<pre style="white-space:pre-wrap;font:.85rem system-ui">{html.escape(text)}</pre>
</body></html>
"""


# --------------------------------------------------------------------------- #
# Command line
# --------------------------------------------------------------------------- #
def selfcheck() -> int:
    rt, _synth, _registry = _import_app()
    model_dir = rt.model_spec("base").directory
    result = subprocess.run([str(rt.venv_python()), "-I", str(VENV_TOOLS), "selfcheck", str(model_dir)], capture_output=True,
                            text=True, env=rt.worker_environment())
    out = result.stdout[result.stdout.find("{"):] if "{" in result.stdout else result.stdout
    print(out or result.stderr[-500:])
    return result.returncode


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("selfcheck")
    for name in ("plan", "run"):
        p = sub.add_parser(name)
        p.add_argument("--voices", nargs="+", default=list(DEFAULT_VOICES))
        p.add_argument("--temps", nargs="+", type=float, default=list(CANDIDATE_TEMPERATURES),
                       help="candidate temperatures (the 0.9 baseline is always included); 0.6 is optional")
    sub.add_parser("report").add_argument("run_dir")
    args = parser.parse_args(argv)
    try:
        if args.command == "selfcheck":
            return selfcheck()
        if args.command == "report":
            report(Path(args.run_dir))
            return 0
        if args.command == "plan":
            temps = normalise_temperatures(args.temps)
            print("Temperatures:", ", ".join(label_for(t) for t in temps))
            print("Passage:", len(comparison_text()), "characters")
            for voice_id, state in readiness(args.voices).items():
                print(f"  {voice_id}: {state}")
            return 0
        print(f"Run folder: {run(args.voices, args.temps)}")
    except ExperimentError as exc:
        print("ERROR:", exc)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
