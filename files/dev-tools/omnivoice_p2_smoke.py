"""omnivoice_p2_smoke.py -- ACT v0.8.0 Phase 2 technical smoke of the six OmniVoice voices (developer only, never shipped).

    .venv\\Scripts\\python.exe -I files\\dev-tools\\omnivoice_p2_smoke.py [--verify-model] [--voice ID ...]

Runs the PRODUCTION path (``tts.omnivoice_synth.omnivoice_file_to_mp3``) once per voice on one short fixed text with the
production ``v1`` speech-preparation snapshot, one chunk per worker (so the second worker reloads the model and the clone
prompt from the identity-checked cache), and writes the MP3s and a JSON report to ``files/dev-work/ov-p2/<stamp>-smoke/``.
``--verify-model`` first hashes the installed model snapshot and records the result (``omnivoice_runtime.verify_model_files``);
it reads the model and changes none of it. These are technical smokes, not listening approval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

from shared import ffmpeg_utils, subprocess_utils  # noqa: E402
from tts import omnivoice_runtime as ov  # noqa: E402
from tts import omnivoice_synth as osy  # noqa: E402
from tts.speech.pipeline import SETTING_V1, build_snapshot  # noqa: E402

#: Written for this project, so nobody else's text is read aloud. A heading and a paragraph: two chunks, two workers.
TEXT = ("# Chapter 3\n\nThe lighthouse keeper climbed 112 steps at 7:15 p.m. and opened the logbook from 1905. Below "
        "him, the harbor lights came on one by one, and far across the water a ferry answered with a long, low horn.")


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def protected() -> dict:
    """The six recordings and the 28 historical previews, by SHA-256."""
    roots = [REPO / "files" / "Cloned-Voice-Uploads", REPO / "files" / "voice-previews"]
    return {str(p.relative_to(REPO)): sha256(p) for root in roots for p in sorted(root.rglob("*.wav"))}


def hub_cache() -> list[str]:
    root = ov.cache_root() / "hf"
    return sorted(str(p.relative_to(root)) for p in root.rglob("*")) if root.is_dir() else []


def decoded_facts(mp3: Path, work: Path) -> dict:
    wav = work / (mp3.stem + ".decoded.wav")
    subprocess_utils.run([ffmpeg_utils.ffmpeg_cmd(), "-y", "-nostdin", "-loglevel", "error", "-i", str(mp3),
                          "-f", "wav", "-c:a", "pcm_f32le", str(wav)], capture_output=True, check=True)
    data, rate = sf.read(str(wav), dtype="float32", always_2d=True)
    wav.unlink()
    peak = float(np.abs(data).max())
    return {"seconds": round(data.shape[0] / rate, 3), "rate": rate, "channels": data.shape[1],
            "peak_dbfs": round(20 * np.log10(peak), 2) if peak > 0 else None,
            "samples_at_or_over_full_scale": int(np.count_nonzero(np.abs(data) >= 1.0)),
            "rms_dbfs": round(10 * np.log10(float(np.mean(data ** 2)) + 1e-12), 2)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-model", action="store_true")
    parser.add_argument("--voice", action="append", default=None)
    args = parser.parse_args(argv)
    out = REPO / "files" / "dev-work" / "ov-p2" / f"{time.strftime('%Y%m%d-%H%M%S')}-smoke"
    out.mkdir(parents=True)
    report: dict = {"text": TEXT, "protected_before": protected(), "hub_cache_before": hub_cache(), "voices": {}}
    if args.verify_model:
        started = time.perf_counter()
        report["verify_model"] = {"problems": ov.verify_model_files(), "seconds": round(time.perf_counter() - started, 1)}
        print("verify-model:", report["verify_model"], flush=True)
    report["readiness"] = {"environment": ov.environment_status(), "model": ov.model_status(),
                           "gpu": str(ov.detect_gpu())}
    snapshot = build_snapshot(SETTING_V1, user_dir=None)
    source = out / "smoke.txt"
    source.write_text(TEXT, encoding="utf-8")
    runs: list = []
    real_run_worker = osy.run_worker

    def recording_run_worker(*a, **k):
        run = real_run_worker(*a, **k)
        runs.append(run)
        return run

    osy.run_worker = recording_run_worker
    chunk_stats: list = []
    real_collect = osy.collect_chunks

    def recording_collect(*a, **k):
        audio, rate = real_collect(*a, **k)
        chunk_stats.extend({"peak": round(float(np.abs(c).max()), 5), "over_full_scale": int(np.count_nonzero(np.abs(c) >= 1.0)),
                            "at_or_over_0_99": int(np.count_nonzero(np.abs(c) >= 0.99))} for c in audio)
        return audio, rate

    osy.collect_chunks = recording_collect
    for voice_id in args.voice or [v.voice_id for v in ov.OMNIVOICE_VOICES]:
        runs.clear()
        chunk_stats.clear()
        spec = ov.excerpt_spec(voice_id)
        lines: list[str] = []
        mp3 = out / f"{voice_id}-smoke.mp3"
        entry: dict = {"excerpt": {"end_frame": spec.crop_end_frame, "seconds": spec.duration_s,
                                   "pcm_sha256": spec.excerpt_pcm_sha256, "wav_sha256": spec.excerpt_wav_sha256,
                                   "text": spec.text, "text_sha256": spec.text_sha256, "status": spec.status}}
        started = time.perf_counter()
        try:
            osy.omnivoice_file_to_mp3(str(source), str(mp3), voice_id, log=lines.append, speech_prep=snapshot,
                                      chunks_per_worker=1, bitrate="128k")
            entry["result"] = "PASS"
            entry["mp3"] = {"path": str(mp3.relative_to(REPO)), "sha256": sha256(mp3), "bytes": mp3.stat().st_size,
                            **decoded_facts(mp3, out)}
        except Exception as exc:  # noqa: BLE001 - recorded, and the next voice still runs
            entry["result"] = f"FAIL: {type(exc).__name__}: {exc}"
        entry["wall_s"] = round(time.perf_counter() - started, 2)
        entry["workers"] = [{"loaded": {k: r.loaded.get(k) for k in ("device_name", "load_s", "prompt", "prompt_s",
                                                                       "ref_text_used", "vram_allocated_mib",
                                                                       "vram_reserved_mib")},
                             "chunks": [{k: e.get(k) for k in ("index", "audio_s", "gen_s", "peak", "vram_allocated_mib",
                                                              "vram_reserved_mib")} for e in r.chunk_events],
                             "done": {k: r.terminal.get(k) for k in ("event", "wall_s", "load_s", "peak_allocated_mib",
                                                                      "peak_reserved_mib")}} for r in runs]
        entry["chunk_samples"] = list(chunk_stats)
        entry["log"] = lines
        report["voices"][voice_id] = entry
        print(voice_id, entry["result"], entry.get("mp3", {}).get("seconds"), entry.get("mp3", {}).get("peak_dbfs"),
              [w["loaded"]["prompt"] for w in entry["workers"]], flush=True)
    osy.run_worker, osy.collect_chunks = real_run_worker, real_collect
    report["protected_after"] = protected()
    report["protected_unchanged"] = report["protected_after"] == report["protected_before"]
    report["hub_cache_after"] = hub_cache()
    report["prompt_cache"] = sorted(p.name for p in ov.prompts_root().iterdir()) if ov.prompts_root().is_dir() else []
    report["jobs_left"] = sorted(p.name for p in ov.jobs_root().iterdir()) if ov.jobs_root().is_dir() else []
    (out / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print("report:", out / "report.json")
    return 0 if all(v["result"] == "PASS" for v in report["voices"].values()) and report["protected_unchanged"] else 1


if __name__ == "__main__":
    sys.exit(main())
