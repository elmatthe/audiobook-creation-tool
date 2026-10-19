"""Qwen3-TTS / Whisper worker for the Plan 01 evaluation (dev-only).

Runs ONLY under the isolated evaluation interpreter (``files/dev-work/qwen3-eval/.venv``), as one
subprocess per model so GPU memory is released when the process exits. The orchestrator writes a
job file, starts this script with an argument list, and reads ``@@EVENT`` lines from stdout.

    python qwen_eval_worker.py <job.json>

Job kinds: ``synth`` (custom_voice or clone rows), ``transcribe`` (Whisper drafts), ``probe``
(load the model offline and report inventory/effective defaults, synthesising nothing).

All torch/qwen/transformers imports are lazy: importing this module in the root interpreter (as the
offline tests do) needs neither. Nothing here picks, ranks or tunes a voice.
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qwen_eval_core as core  # noqa: E402

EXPECTED_SPEAKERS = tuple(sorted(name.lower() for name, _ in core.QWEN_PRESETS))
CODEC_FRAMES_PER_SECOND = 12.5  # 12Hz tokenizer; used only for the cap-headroom estimate


def _versions() -> dict:
    import importlib.metadata as md

    out = {"python": sys.version.split()[0]}
    for pkg in ("torch", "torchaudio", "transformers", "accelerate", "qwen-tts", "huggingface-hub",
                "safetensors", "numpy", "librosa", "soundfile"):
        try:
            out[pkg] = md.version(pkg)
        except md.PackageNotFoundError:
            out[pkg] = None
    return out


def _gpu_state(torch) -> dict:
    if not torch.cuda.is_available():
        return {"device": "cpu"}
    free, total = torch.cuda.mem_get_info()
    props = torch.cuda.get_device_properties(0)
    return {"device": props.name, "capability": list(torch.cuda.get_device_capability(0)),
            "total_mib": total // 2**20, "free_mib": free // 2**20,
            "allocated_mib": torch.cuda.memory_allocated() // 2**20,
            "reserved_mib": torch.cuda.memory_reserved() // 2**20}


def _sync(torch) -> None:
    if torch.cuda.is_available():
        torch.cuda.synchronize()


def _cancelled(job: dict) -> bool:
    flag = job.get("cancel_file")
    return bool(flag) and Path(flag).exists()


def _load_model(job: dict, torch):
    from qwen_tts import Qwen3TTSModel

    profile = job["profile"]
    dtype = getattr(torch, profile["dtype"])
    started = time.perf_counter()
    model = Qwen3TTSModel.from_pretrained(
        job["model_dir"], device_map=profile["device"], dtype=dtype, attn_implementation=profile["attn"])
    _sync(torch)
    return model, round(time.perf_counter() - started, 2)


def _effective_generation(model) -> dict:
    """The values the wrapper will actually pass to ``generate()``: snapshot config over hard defaults."""
    merged = model._merge_generate_kwargs()
    return {k: merged[k] for k in sorted(merged)}


def _upsample_rate(model) -> int:
    for owner in (getattr(model.model, "speech_tokenizer", None), model.model):
        for attr in ("decode_upsample_rate", "get_decode_upsample_rate"):
            value = getattr(owner, attr, None)
            if callable(value):
                try:
                    return int(value())
                except Exception:  # noqa: BLE001 - estimate only
                    continue
            if isinstance(value, (int, float)) and value > 0:
                return int(value)
    return 1920  # 24 kHz / 12.5 frames per second


def run_probe(job: dict) -> int:
    import torch

    model, load_s = _load_model(job, torch)
    speakers = model.get_supported_speakers()
    languages = model.get_supported_languages()
    core.emit({
        "event": "probe", "load_s": load_s, "versions": _versions(), "gpu": _gpu_state(torch),
        "tts_model_type": model.model.tts_model_type, "tts_model_size": model.model.tts_model_size,
        "speakers": speakers, "languages": languages, "effective_generation": _effective_generation(model),
        "upsample_rate": _upsample_rate(model), "sdpa": job["profile"]["attn"],
    })
    return 0


def _fail_all(rows: list[dict], reason: str) -> None:
    for row in rows:
        core.emit({"event": "row_failed", "row_id": row["row_id"], "reason": reason})


def run_synth(job: dict) -> int:
    import torch

    rows = job["rows"]
    profile = job["profile"]
    run_dir = Path(job["run_dir"])
    started_job = time.perf_counter()
    try:
        model, load_s = _load_model(job, torch)
    except Exception as exc:  # noqa: BLE001
        core.emit({"event": "load_failed", "error": f"{type(exc).__name__}: {exc}",
                   "trace": traceback.format_exc()[-1500:]})
        _fail_all(rows, f"model load failed: {type(exc).__name__}: {exc}")
        return 2

    speakers = model.get_supported_speakers()
    effective = _effective_generation(model)
    upsample = _upsample_rate(model)
    cap = int(effective.get("max_new_tokens", 0))
    core.emit({"event": "model_loaded", "load_s": load_s, "versions": _versions(), "gpu": _gpu_state(torch),
               "mode": job["mode"], "speakers": speakers, "effective_generation": effective,
               "upsample_rate": upsample, "eos_capture": "unavailable: Qwen3TTSModel.generate_* discards "
               "the stop reason; cap headroom is estimated from output length"})
    if job["mode"] == "custom_voice" and speakers is not None and tuple(sorted(speakers)) != EXPECTED_SPEAKERS:
        reason = f"unexpected speaker inventory {sorted(speakers)}; refusing to substitute voices"
        core.emit({"event": "inventory_mismatch", "found": speakers, "expected": list(EXPECTED_SPEAKERS)})
        _fail_all(rows, reason)
        return 3

    clone_prompts: dict[str, object] = {}
    language = profile["language"]
    sample_rate = None
    for row in rows:
        row_id, out_dir = row["row_id"], Path(row["out_dir"])
        chunks = [core.Chunk(c["index"], c["start"], c["end"], c["text"], c["boundary"], c["paragraph"])
                  for c in row["chunks"]]
        chunk_dir = run_dir / "chunks" / row_id
        core.emit({"event": "row_start", "row_id": row_id, "chunks": len(chunks)})
        row_started = time.perf_counter()
        audio: list[np.ndarray] = []
        results: list[dict] = []
        failed: str | None = None
        sample_rate = None  # per recording: every chunk of one recording must share one rate
        try:
            if job["mode"] == "custom_voice":
                if row["speaker"].lower() not in {s.lower() for s in (speakers or [])}:
                    raise RuntimeError(f"speaker {row['speaker']!r} not in the loaded model's inventory")
            else:
                t0 = time.perf_counter()
                clone_prompts[row_id] = model.create_voice_clone_prompt(
                    ref_audio=row["reference_wav"], ref_text=row["reference_text"], x_vector_only_mode=False)
                _sync(torch)
                core.emit({"event": "clone_prompt", "row_id": row_id,
                           "prompt_s": round(time.perf_counter() - t0, 2), "x_vector_only_mode": False})
            for chunk in chunks:
                if _cancelled(job):
                    failed = "canceled"
                    break
                seed = core.derive_seed(row_id, chunk.index, row.get("attempt", 1), profile["seed_base"])
                torch.manual_seed(seed)
                if torch.cuda.is_available():
                    torch.cuda.manual_seed_all(seed)
                    torch.cuda.reset_peak_memory_stats()
                _sync(torch)
                t0 = time.perf_counter()
                try:
                    if job["mode"] == "custom_voice":
                        wavs, rate = model.generate_custom_voice(
                            text=chunk.text, language=language, speaker=row["speaker"])
                    else:
                        wavs, rate = model.generate_voice_clone(
                            text=chunk.text, language=language, voice_clone_prompt=clone_prompts[row_id])
                    _sync(torch)
                    # Mono and one consistent rate, or this chunk fails: nothing is flattened or reinterpreted.
                    wav = core.validate_chunk_audio(wavs[0], rate, sample_rate)
                    sample_rate = int(rate)
                except Exception as exc:  # noqa: BLE001 - retain the failed chunk as diagnostics
                    results.append({"index": chunk.index, "seed": seed, "error": f"{type(exc).__name__}: {exc}"})
                    failed = f"chunk {chunk.index} failed: {type(exc).__name__}: {exc}"
                    if "out of memory" in str(exc).lower() and torch.cuda.is_available():
                        torch.cuda.empty_cache()
                    break
                gen_s = time.perf_counter() - t0
                saved = core.write_wav(chunk_dir / f"chunk-{chunk.index + 1:03d}.wav", wav, sample_rate,
                                       float_chunk=True, base=run_dir)
                seconds = wav.size / sample_rate
                frames = int(round(wav.size / upsample)) if upsample else None
                info = {
                    "index": chunk.index, "seed": seed, "gen_s": round(gen_s, 3), "audio_s": round(seconds, 3),
                    "rtf": round(gen_s / seconds, 3) if seconds else None, "wav": saved,
                    "est_codec_frames": frames, "cap_headroom": round(frames / cap, 3) if (frames and cap) else None,
                }
                if torch.cuda.is_available():
                    info["peak_alloc_mib"] = torch.cuda.max_memory_allocated() // 2**20
                    info["peak_reserved_mib"] = torch.cuda.max_memory_reserved() // 2**20
                results.append(info)
                audio.append(wav)
                core.emit({"event": "chunk_done", "row_id": row_id, "chunk": chunk.index, "of": len(chunks),
                           "gen_s": info["gen_s"], "audio_s": info["audio_s"]})
        except Exception as exc:  # noqa: BLE001
            failed = f"{type(exc).__name__}: {exc}"
            core.emit({"event": "trace", "row_id": row_id, "trace": traceback.format_exc()[-1500:]})

        if failed or len(audio) != len(chunks):
            event = "row_canceled" if failed == "canceled" else "row_failed"
            core.emit({"event": event, "row_id": row_id, "reason": failed or "incomplete",
                       "completed_chunks": len(audio), "chunk_results": results})
            if failed == "canceled":
                return 130
            continue

        full, report = core.assemble(audio, sample_rate, [c.boundary for c in chunks],
                                     profile["gap_ms"], profile["end_silence_ms"])
        final = core.write_wav(out_dir / row["file_name"], full, sample_rate, base=run_dir)
        join_path = run_dir / "chunks" / row_id / "joins.json"
        join_path.write_text(json.dumps({"joins": report["joins"], "chunks": [c.to_dict() for c in chunks]},
                                        indent=1), encoding="utf-8")
        measurements = core.measure_samples(full, sample_rate)
        warnings = core.mechanical_warnings(chunks, audio, sample_rate, tuple(row["target_seconds"]) if
                                            row.get("target_seconds") else None)
        peak_alloc = max((r.get("peak_alloc_mib", 0) for r in results), default=None)
        capped = [r["index"] for r in results if (r.get("cap_headroom") or 0) >= 0.9]
        if capped:
            warnings.append(f"chunks {capped} used >=90% of the generation cap (possible cap hit)")
        core.emit({
            "event": "row_done", "row_id": row_id, "wav": final, "measurements": measurements,
            "warnings": warnings, "joins": {k: v for k, v in report.items() if k != "joins"},
            "join_file": join_path.relative_to(run_dir).as_posix(), "chunk_results": results,
            "wall_s": round(time.perf_counter() - row_started, 2),
            "gen_s": round(sum(r["gen_s"] for r in results), 2),
            "audible_s": round(report["speech_samples"] / sample_rate, 3),  # speech only: inserted silence excluded
            "total_s": measurements["duration_s"],
            "peak_alloc_mib": peak_alloc,
            "peak_reserved_mib": max((r.get("peak_reserved_mib", 0) for r in results), default=None),
        })
    core.emit({"event": "worker_done", "wall_s": round(time.perf_counter() - started_job, 2), "load_s": load_s})
    return 0


# --------------------------------------------------------------------------- #
# Whisper: draft transcripts for owner verification only
# --------------------------------------------------------------------------- #
def run_transcribe(job: dict) -> int:
    import librosa
    import torch
    from transformers import WhisperForConditionalGeneration, WhisperProcessor

    model_dir = job["model_dir"]
    processor = WhisperProcessor.from_pretrained(model_dir)
    started = time.perf_counter()
    model = WhisperForConditionalGeneration.from_pretrained(model_dir, torch_dtype=torch.float32).eval()
    core.emit({"event": "model_loaded", "load_s": round(time.perf_counter() - started, 2), "versions": _versions(),
               "device": "cpu"})
    for ref in job["references"]:
        try:
            t0 = time.perf_counter()
            audio, rate = core.read_wav(Path(ref["wav"]))  # source bytes are only read
            mono = audio if audio.ndim == 1 else audio.mean(axis=1)
            speech = librosa.resample(mono.astype("float32"), orig_sr=rate, target_sr=16000)
            features = processor(speech, sampling_rate=16000, return_tensors="pt")
            with torch.inference_mode():
                ids = model.generate(features.input_features, max_new_tokens=200)
            text = processor.batch_decode(ids, skip_special_tokens=True)[0].strip()
            core.emit({"event": "draft", "name": ref["name"], "text": text, "duration_s": round(len(mono) / rate, 3),
                       "source_rate": rate, "asr_rate": 16000, "wall_s": round(time.perf_counter() - t0, 2)})
        except Exception as exc:  # noqa: BLE001
            core.emit({"event": "draft_failed", "name": ref["name"], "error": f"{type(exc).__name__}: {exc}"})
    core.emit({"event": "worker_done"})
    return 0


def run_asr_check(job: dict) -> int:
    """Whisper read-back of finished recordings, cut at silences (never mid-word). Advisory evidence only."""
    import librosa
    import torch
    from transformers import pipeline

    use_cuda = torch.cuda.is_available()
    started = time.perf_counter()
    asr = pipeline("automatic-speech-recognition", model=job["model_dir"], device=0 if use_cuda else -1,
                   dtype=torch.float16 if use_cuda else torch.float32)
    core.emit({"event": "model_loaded", "load_s": round(time.perf_counter() - started, 2), "versions": _versions(),
               "device": "cuda" if use_cuda else "cpu", "method": core.ASR_METHOD})
    for item in job["rows"]:
        try:
            t0 = time.perf_counter()
            audio, rate = core.read_wav(Path(item["wav"]))
            mono = audio if audio.ndim == 1 else audio.mean(axis=1)
            speech = librosa.resample(mono.astype("float32"), orig_sr=rate, target_sr=16000)
            parts = [asr({"raw": speech[a:b], "sampling_rate": 16000})["text"].strip()
                     for a, b in core.silence_split(speech, 16000)]
            core.emit({"event": "asr_row", "row_id": item["row_id"], "text": " ".join(p for p in parts if p),
                       "segments": len(parts), "wall_s": round(time.perf_counter() - t0, 2)})
        except Exception as exc:  # noqa: BLE001 - one recording failing must not stop the rest
            core.emit({"event": "asr_failed", "row_id": item["row_id"], "error": f"{type(exc).__name__}: {exc}"})
    core.emit({"event": "worker_done"})
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: qwen_eval_worker.py <job.json>", file=sys.stderr)
        return 64
    job = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    handler = {"synth": run_synth, "probe": run_probe, "transcribe": run_transcribe,
               "asr-check": run_asr_check}.get(job["kind"])
    if handler is None:
        print(f"unknown job kind {job['kind']!r}", file=sys.stderr)
        return 64
    return handler(job)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
