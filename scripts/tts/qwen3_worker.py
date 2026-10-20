"""qwen3_worker.py — the Qwen3-TTS worker. Runs ONLY inside ``.venv-qwen3``, never in the application's interpreter.

One subprocess per source file. ``qwen3_synth`` writes a job file, starts::

    <.venv-qwen3 python> qwen3_worker.py <job.json>

and reads ``@@EVENT <json>`` lines from stdout. Everything else the libraries print is ignored by the reader.

Job kinds
---------
``synth``  load the model from a local, pinned snapshot **offline**, then render every chunk to its own float WAV.
``probe``  import the stack and report versions and GPU/CPU state; with ``model_dir`` also load that model once, so an
           install can prove the files really load. Synthesises nothing.

Terminal events (exactly one per run): ``done``, ``failed``, ``canceled``. A run that ends without one is a failure the
reader reports as such. Cancellation is a flag file checked before the load, before each chunk and after it; the parent
also kills the process tree if the worker does not stop promptly, so nothing here has to be interruptible mid-chunk.

All torch/qwen imports are lazy: importing this module in the application's interpreter (as the offline tests do) needs
neither. The worker never picks, ranks or tunes a voice, never substitutes one, and never falls back to another device
after a failure — a GPU that fails fails the file with a clear message.
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

EVENT_PREFIX = "@@EVENT "
EXIT_OK, EXIT_FAILED, EXIT_CANCELED = 0, 2, 130


def emit(event: dict) -> None:
    sys.stdout.write(EVENT_PREFIX + json.dumps(event, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def _cancelled(job: dict) -> bool:
    flag = job.get("cancel_file")
    return bool(flag) and Path(flag).exists()


def _versions() -> dict:
    import importlib.metadata as md

    out = {"python": sys.version.split()[0]}
    for pkg in ("torch", "torchaudio", "transformers", "accelerate", "qwen-tts", "numpy", "soundfile"):
        try:
            out[pkg] = md.version(pkg)
        except md.PackageNotFoundError:
            out[pkg] = None
    return out


def _sync(torch) -> None:
    if torch.cuda.is_available():
        torch.cuda.synchronize()


def choose_device(preference: str, cuda_available: bool) -> str:
    """``auto`` is the GPU when torch reports one and the CPU otherwise; an explicit choice is honoured or refused."""
    if preference == "cpu":
        return "cpu"
    if preference == "cuda":
        if not cuda_available:
            raise RuntimeError("a GPU was requested but PyTorch reports no CUDA device")
        return "cuda:0"
    if preference == "auto":
        return "cuda:0" if cuda_available else "cpu"
    raise RuntimeError(f"unknown device preference {preference!r}")


def _device_state(torch, device: str) -> dict:
    if device.startswith("cuda") and torch.cuda.is_available():
        props = torch.cuda.get_device_properties(0)
        return {"device": device, "device_name": props.name, "total_mib": props.total_memory // 2**20,
                "capability": list(torch.cuda.get_device_capability(0))}
    return {"device": "cpu", "device_name": "CPU", "cuda_available": bool(torch.cuda.is_available())}


def _load_model(job: dict, torch):
    from qwen_tts import Qwen3TTSModel

    device = choose_device(job.get("device", "auto"), torch.cuda.is_available())
    started = time.perf_counter()
    model = Qwen3TTSModel.from_pretrained(
        job["model_dir"], device_map=device, dtype=getattr(torch, job.get("dtype", "bfloat16")),
        attn_implementation=job.get("attn", "sdpa"))
    _sync(torch)
    return model, device, round(time.perf_counter() - started, 2)


#: The only sampling controls a job may set, and the range each must be in. A clone job carries the application's clone narration
#: narration profile (``qwen3_synth.CLONE_GENERATION``); every control not named here keeps the Base model's own value.
GENERATION_LIMITS = {"temperature": (0.1, 1.5), "subtalker_temperature": (0.1, 1.5)}


def clone_generation(job: dict) -> dict:
    """The sampling arguments a clone job asks for, validated; ``{}`` when the job carries none. Preset jobs never use them."""
    generation = job.get("generation") or {}
    if not isinstance(generation, dict):
        raise RuntimeError("the job's generation settings are not an object")
    out = {}
    for name, value in generation.items():
        if name not in GENERATION_LIMITS:
            raise RuntimeError(f"unsupported generation setting {name!r}")
        low, high = GENERATION_LIMITS[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
            raise RuntimeError(f"generation setting {name} must be a number from {low} to {high}, not {value!r}")
        out[name] = float(value)
    return out


def _mono_float(audio, rate) -> "object":
    """One generated chunk as mono float32, or an error. Nothing is flattened, resampled or guessed."""
    import numpy as np

    arr = np.asarray(audio)
    if arr.ndim != 1:
        raise RuntimeError(f"the model returned audio of shape {arr.shape}; a mono waveform is required")
    if arr.size == 0:
        raise RuntimeError("the model returned an empty waveform")
    if not np.isfinite(arr).all():
        raise RuntimeError("the model returned non-finite samples")
    if not isinstance(rate, (int, np.integer)) or int(rate) <= 0:
        raise RuntimeError(f"the model returned an invalid sample rate {rate!r}")
    return arr.astype("float32", copy=False)


def run_probe(job: dict) -> int:
    try:
        import torch

        import qwen_tts  # noqa: F401 - the import itself is the check
        import soundfile  # noqa: F401
        import transformers  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        emit({"event": "failed", "stage": "import", "message": f"{type(exc).__name__}: {exc}"})
        return EXIT_FAILED
    info = {"event": "probe", "versions": _versions(), "cuda_available": bool(torch.cuda.is_available()),
            "torch_cuda": getattr(torch.version, "cuda", None)}
    info.update(_device_state(torch, "cuda:0" if torch.cuda.is_available() else "cpu"))
    if job.get("model_dir"):
        try:
            model, device, load_s = _load_model(job, torch)
        except Exception as exc:  # noqa: BLE001
            emit({"event": "failed", "stage": "load", "message": f"{type(exc).__name__}: {exc}",
                  "trace": traceback.format_exc()[-1500:]})
            return EXIT_FAILED
        info.update(load_s=load_s, loaded_on=device, model_type=getattr(model.model, "tts_model_type", None),
                    speakers=model.get_supported_speakers())
    emit(info)
    emit({"event": "done"})
    return EXIT_OK


def run_synth(job: dict) -> int:
    import numpy as np
    import soundfile as sf
    import torch

    started = time.perf_counter()
    out_dir = Path(job["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    chunks = job["chunks"]
    if _cancelled(job):
        emit({"event": "canceled", "completed": 0})
        return EXIT_CANCELED
    try:
        model, device, load_s = _load_model(job, torch)
    except Exception as exc:  # noqa: BLE001
        emit({"event": "failed", "stage": "load", "message": f"{type(exc).__name__}: {exc}",
              "oom": "out of memory" in str(exc).lower(), "trace": traceback.format_exc()[-1500:]})
        return EXIT_FAILED
    emit({"event": "loaded", "load_s": load_s, "versions": _versions(), "chunks": len(chunks),
          **_device_state(torch, device)})

    mode = job["mode"]
    try:
        if mode == "custom_voice":
            speakers = model.get_supported_speakers()
            if speakers is not None and job["speaker"].lower() not in {s.lower() for s in speakers}:
                raise RuntimeError(f"speaker {job['speaker']!r} is not in the loaded model's inventory; "
                                   "refusing to substitute another voice")
        elif mode == "clone":
            prompt = model.create_voice_clone_prompt(
                ref_audio=job["reference_wav"], ref_text=job["reference_text"], x_vector_only_mode=False)
            generation = clone_generation(job)
            _sync(torch)
        else:
            raise RuntimeError(f"unknown synthesis mode {mode!r}")
    except Exception as exc:  # noqa: BLE001
        emit({"event": "failed", "stage": "prepare", "message": f"{type(exc).__name__}: {exc}",
              "oom": "out of memory" in str(exc).lower(), "trace": traceback.format_exc()[-1500:]})
        return EXIT_FAILED

    rate = None
    done = 0
    for chunk in chunks:
        if _cancelled(job):
            emit({"event": "canceled", "completed": done})
            return EXIT_CANCELED
        try:
            torch.manual_seed(int(chunk["seed"]))
            if torch.cuda.is_available():
                torch.cuda.manual_seed_all(int(chunk["seed"]))
            t0 = time.perf_counter()
            if mode == "custom_voice":
                wavs, got_rate = model.generate_custom_voice(
                    text=chunk["text"], language=job.get("language", "English"), speaker=job["speaker"])
            else:
                wavs, got_rate = model.generate_voice_clone(
                    text=chunk["text"], language=job.get("language", "English"), voice_clone_prompt=prompt, **generation)
            _sync(torch)
            wav = _mono_float(wavs[0], got_rate)
            if rate is not None and int(got_rate) != rate:
                raise RuntimeError(f"the sample rate changed within one file ({rate} -> {got_rate})")
            rate = int(got_rate)
            gen_s = time.perf_counter() - t0
            name = f"chunk-{chunk['index'] + 1:04d}.wav"
            sf.write(str(out_dir / name), np.asarray(wav, dtype="float32"), rate, subtype="FLOAT")
        except Exception as exc:  # noqa: BLE001
            oom = "out of memory" in str(exc).lower()
            if oom and torch.cuda.is_available():
                torch.cuda.empty_cache()
            emit({"event": "failed", "stage": "generate", "index": chunk["index"], "oom": oom,
                  "message": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-1500:]})
            return EXIT_FAILED
        done += 1
        emit({"event": "chunk", "index": chunk["index"], "of": len(chunks), "wav": name,
              "audio_s": round(wav.size / rate, 3), "gen_s": round(gen_s, 3), "sample_rate": rate})
    emit({"event": "done", "chunks": done, "sample_rate": rate, "device": device,
          "wall_s": round(time.perf_counter() - started, 2), "load_s": load_s})
    return EXIT_OK


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.stderr.write("usage: qwen3_worker.py <job.json>\n")
        return 64
    try:
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
        job = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        kind = job.get("kind")
        if kind == "synth":
            return run_synth(job)
        if kind == "probe":
            return run_probe(job)
        emit({"event": "failed", "stage": "job", "message": f"unknown job kind {kind!r}"})
        return EXIT_FAILED
    except Exception as exc:  # noqa: BLE001 - the parent must always get a terminal event
        emit({"event": "failed", "stage": "worker", "message": f"{type(exc).__name__}: {exc}",
              "trace": traceback.format_exc()[-1500:]})
        return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main(sys.argv))
