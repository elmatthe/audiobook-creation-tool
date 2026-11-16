"""macos_p4a_omnivoice_worker.py -- ACT v0.8.x macOS P4A: the OmniVoice engine side of the bounded feasibility campaign.

Developer only: never shipped, never imported by the application, not the production worker. It runs ONLY inside the
disposable P4A environment (``files/dev-work/omnivoice-feasibility/venv``)::

    <venv python> -I macos_p4a_omnivoice_worker.py <job.json>

It reads the PRODUCTION job format (``tts.omnivoice_synth.build_job``: the chunks, seeds, generation settings, reference
and transcript exactly as ACT plans them) with the device and dtype under test, and answers in the production protocol
(``@@EVENT`` lines: ``loaded``, ``chunk``, then exactly one of ``done``/``failed``/``canceled``), so ACT's own supervisor
(``omnivoice_synth.run_worker``), chunk reader and assembly run unchanged. What differs from ``tts/omnivoice_worker.py`` is
only what P4A tests: the device (``cpu`` or ``mps``) and dtype (``float32`` or ``float16``) instead of CUDA float16.

Reused from ``tts/omnivoice_worker.py`` itself (loaded by file path, not copied): the network audit hook, the reference
proof (SHA-256, format, length) and the speech-recognizer refusal. Added guards:

* no silent CPU fallback: ``PYTORCH_ENABLE_MPS_FALLBACK`` must be unset, MPS must really be available when asked for, and
  every parameter of the backbone must sit on the requested device after loading;
* the clone prompt is always built from the verified recording (no cache is read or written);
* every chunk WAV is written under a temporary name and renamed only when complete;
* a lifeline: the worker ends itself if its parent dies (no orphan if the harness is killed);
* an optional footprint ceiling (``p4a.safety_footprint_bytes``): crossing it ends the run as ``failed``/``memory-safety``.

Extra P4A modes (``job["p4a"]["mode"]``): ``probe`` (load, plus an optional one-line smoke generation, then stop) and
``soak`` (``calls`` back-to-back generations of the first chunk, with memory per call).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("act_omnivoice_worker", REPO / "scripts" / "tts" / "omnivoice_worker.py")
ow = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ow)  # stdlib-only at module level

emit = ow.emit
DEVICES = {"cpu", "mps"}
DTYPES = {"float32", "float16"}


def lifeline() -> None:
    """End this process if the harness that started it is gone (re-parented)."""
    parent = os.getppid()

    def watch() -> None:
        while True:
            time.sleep(0.5)
            if os.getppid() != parent:
                os._exit(137)

    threading.Thread(target=watch, daemon=True).start()


def footprint() -> dict:
    """This process's physical footprint now and its lifetime peak (macOS ``rusage_info_v4``)."""
    try:
        import ctypes
        import struct

        libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        buffer = ctypes.create_string_buffer(512)
        if libproc.proc_pid_rusage(os.getpid(), 4, buffer) != 0:
            return {}
        now = struct.unpack_from("=Q", buffer.raw, 16 + 7 * 8)[0]
        peak = struct.unpack_from("=Q", buffer.raw, 16 + 28 * 8)[0]
        return {"footprint": int(now), "peak_footprint": int(peak)}
    except (OSError, AttributeError, ValueError):
        return {}


def memory(torch, device: str) -> dict:
    found = footprint()
    if device == "mps":
        found["mps_current"] = int(torch.mps.current_allocated_memory())
        found["mps_driver"] = int(torch.mps.driver_allocated_memory())
    return found


def sync(torch, device: str) -> None:
    if device == "mps":
        torch.mps.synchronize()


def problems(job: dict) -> list[str]:
    found = [f"{k} is not {v}" for k, v in ow.REQUIRED_OFFLINE.items() if os.environ.get(k) != v]
    if os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK"):
        found.append("PYTORCH_ENABLE_MPS_FALLBACK is set (an unsupported op would silently run on the CPU)")
    if job.get("kind") != "synth" or job.get("schema") != 1:
        found.append("not a synth job")
    missing = sorted(ow.SYNTH_KEYS - set(job))
    if missing:
        found.append("missing " + ", ".join(missing))
        return found
    if job["device"] not in DEVICES or job["dtype"] not in DTYPES:
        found.append(f"device/dtype {job['device']}/{job['dtype']} is not a P4A configuration")
    model = Path(job["model_dir"])
    if not (model / "config.json").is_file() or not (model / "audio_tokenizer" / "config.json").is_file():
        found.append("the model folder is incomplete (OmniVoice would fetch)")
    if set(job["generation"]) - ow.GENERATION_KEYS:
        found.append("unknown generation settings")
    if not isinstance(job.get("ref_text"), str) or not job["ref_text"].strip():
        found.append("the reference transcript is blank")
    chunks = job.get("chunks")
    if not isinstance(chunks, list) or not chunks or not all(
            isinstance(c, dict) and type(c.get("index")) is int and isinstance(c.get("text"), str) and c["text"].strip()
            and type(c.get("seed")) is int for c in chunks):
        found.append("the chunks are not indexed, seeded, non-blank texts")
    return found


def cancelled(job: dict) -> bool:
    flag = job.get("cancel_file")
    return bool(flag) and Path(flag).exists()


def write_wav(sf, path: Path, wav, rate: int) -> None:
    part = path.with_name(path.name + ".part")
    sf.write(str(part), wav, rate, subtype="FLOAT", format="WAV")
    os.replace(part, path)


def run(job: dict, network: list) -> int:
    p4a = job.get("p4a") or {}
    mode = p4a.get("mode", "synth")
    device, dtype_name = job["device"], job["dtype"]
    try:
        import numpy as np
        import soundfile as sf
        import torch
        from omnivoice import OmniVoice, OmniVoiceGenerationConfig, __version__ as omnivoice_version
    except Exception as exc:  # noqa: BLE001
        if ow._caused_by(exc, ow.NetworkRefused):
            raise
        emit(ow.import_failure(exc))
        return ow.EXIT_FAILED
    started = time.perf_counter()
    if omnivoice_version != job["omnivoice_version"]:
        emit({"event": "failed", "stage": "import", "message": f"omnivoice {omnivoice_version} is installed"})
        return ow.EXIT_FAILED
    if device == "mps" and not torch.backends.mps.is_available():
        emit({"event": "failed", "stage": "mps-unavailable", "message": "PyTorch reports MPS unavailable here",
              "mps_built": bool(torch.backends.mps.is_built())})
        return ow.EXIT_FAILED
    if cancelled(job):
        emit({"event": "canceled", "completed": 0})
        return ow.EXIT_CANCELED
    ceiling = p4a.get("safety_footprint_bytes")
    try:
        t0 = time.perf_counter()
        model = OmniVoice.from_pretrained(job["model_dir"], device_map=device, dtype=getattr(torch, dtype_name))
        model.load_asr_model = ow._refuse_speech_recognizer
        sync(torch, device)
        load_s = round(time.perf_counter() - t0, 3)
        # The audio tokenizer is registered under the model; upstream itself places it on the CPU under MPS
        # ("higgs-audio-v2-tokenizer does not support MPS"), so the backbone and the tokenizer are checked apart.
        backbone = [(n, p) for n, p in model.named_parameters() if not n.startswith("audio_tokenizer.")]
        tokenizer = [p for n, p in model.named_parameters() if n.startswith("audio_tokenizer.")]
        placed = sorted({p.device.type for _, p in backbone})
        dtypes = sorted({str(p.dtype).replace("torch.", "") for _, p in backbone if p.is_floating_point()})
        tokenizer_device = sorted({p.device.type for p in tokenizer})
        expected_tokenizer = ["cpu"] if device == "mps" else [device]
        if placed != [device]:
            raise RuntimeError(f"the backbone is on {placed}, not only on {device} (no silent fallback is allowed)")
        if tokenizer_device != expected_tokenizer:
            raise RuntimeError(f"the audio tokenizer is on {tokenizer_device}, not where upstream places it "
                               f"({expected_tokenizer})")
    except Exception as exc:  # noqa: BLE001
        emit({"event": "failed", "stage": "load", "message": f"{type(exc).__name__}: {exc}", "oom": ow._is_oom(exc),
              "trace": traceback.format_exc()[-1500:]})
        return ow.EXIT_FAILED
    rate = int(model.sampling_rate)
    loaded = {"event": "loaded", "device": device, "device_name": f"{device} ({dtype_name})", "dtype": dtype_name,
              "parameter_devices": placed, "parameter_dtypes": dtypes, "tokenizer_device": tokenizer_device,
              "tokenizer_dtype": str(next(model.audio_tokenizer.parameters()).dtype).replace("torch.", ""),
              "load_s": load_s, "sampling_rate": rate, "versions": ow._versions(),
              "torch_threads": torch.get_num_threads(), **memory(torch, device)}
    try:
        config = OmniVoiceGenerationConfig(**job["generation"])
        t1 = time.perf_counter()
        waveform, ref_rate = ow.read_reference(job)
        prompt = model.create_voice_clone_prompt(ref_audio=(torch.from_numpy(waveform), ref_rate),
                                                 ref_text=job["ref_text"], preprocess_prompt=config.preprocess_prompt)
        sync(torch, device)
        loaded.update(prompt="built", prompt_s=round(time.perf_counter() - t1, 3), ref_text_used=prompt.ref_text)
    except Exception as exc:  # noqa: BLE001
        emit({"event": "failed", "stage": "load", "message": f"{type(exc).__name__}: {exc}", "oom": ow._is_oom(exc),
              "trace": traceback.format_exc()[-1500:]})
        return ow.EXIT_FAILED
    emit(loaded)
    out_dir = Path(job["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    def generate(chunk: dict):
        torch.manual_seed(int(chunk["seed"]))
        t = time.perf_counter()
        outputs = model.generate(text=chunk["text"], language=job["language"], voice_clone_prompt=prompt,
                                 generation_config=config, normalize_text=False)
        sync(torch, device)
        gen_s = time.perf_counter() - t
        wav = np.asarray(outputs[0], dtype=np.float32)
        finite = bool(wav.ndim == 1 and wav.size > 0 and np.isfinite(wav).all())
        return wav, gen_s, finite

    if mode == "probe":
        smoke = p4a.get("smoke_text")
        record = {"event": "done", "chunks": 0, "mode": "probe", "load_s": load_s,
                  "network_attempts": len(network), "wall_s": round(time.perf_counter() - started, 3)}
        if smoke:
            try:
                emit({"event": "generating", "index": -1})
                wav, gen_s, finite = generate({"text": smoke, "seed": 1})
                record.update(smoke_finite=finite, smoke_audio_s=round(wav.size / rate, 3), smoke_gen_s=round(gen_s, 3))
            except Exception as exc:  # noqa: BLE001
                emit({"event": "failed", "stage": "generate", "message": f"{type(exc).__name__}: {exc}",
                      "oom": ow._is_oom(exc), "trace": traceback.format_exc()[-1500:]})
                return ow.EXIT_FAILED
        emit({**record, **memory(torch, device)})
        return ow.EXIT_OK

    if mode == "soak":
        chunk = job["chunks"][0]
        calls = int(p4a.get("calls", 1))
        for call in range(calls):
            if cancelled(job):
                emit({"event": "canceled", "completed": call})
                return ow.EXIT_CANCELED
            try:
                emit({"event": "generating", "index": call})
                wav, gen_s, finite = generate(chunk)
            except Exception as exc:  # noqa: BLE001
                emit({"event": "failed", "stage": "generate", "index": call, "oom": ow._is_oom(exc),
                      "message": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-1500:]})
                return ow.EXIT_FAILED
            mem = memory(torch, device)
            name = None
            if call in (0, calls - 1):
                name = f"soak-{call + 1:03d}.wav"
                write_wav(sf, out_dir / name, wav, rate)
            emit({"event": "call", "index": call, "of": calls, "finite": finite, "audio_s": round(wav.size / rate, 3),
                  "gen_s": round(gen_s, 3), "sha256": __import__("hashlib").sha256(wav.tobytes()).hexdigest(),
                  "wav": name, **mem})
            if not finite:
                emit({"event": "failed", "stage": "generate", "index": call, "message": "non-finite audio"})
                return ow.EXIT_FAILED
            if ceiling and mem.get("footprint", 0) > ceiling:
                emit({"event": "failed", "stage": "memory-safety", "index": call,
                      "message": f"footprint {mem['footprint']} crossed the safety ceiling {ceiling}"})
                return ow.EXIT_FAILED
        emit({"event": "done", "chunks": calls, "mode": "soak", "load_s": load_s, "network_attempts": len(network),
              "wall_s": round(time.perf_counter() - started, 3), **memory(torch, device)})
        return ow.EXIT_OK

    done = 0
    for chunk in job["chunks"]:
        if cancelled(job):
            emit({"event": "canceled", "completed": done})
            return ow.EXIT_CANCELED
        try:
            emit({"event": "generating", "index": chunk["index"]})
            wav, gen_s, finite = generate(chunk)
            if not finite:
                raise RuntimeError(f"the model returned unusable audio (shape {wav.shape}, non-finite or empty)")
            name = f"chunk-{int(chunk['index']) + 1:04d}.wav"
            write_wav(sf, out_dir / name, wav, rate)
        except Exception as exc:  # noqa: BLE001
            emit({"event": "failed", "stage": "generate", "index": chunk["index"], "oom": ow._is_oom(exc),
                  "message": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-1500:]})
            return ow.EXIT_FAILED
        done += 1
        mem = memory(torch, device)
        emit({"event": "chunk", "index": chunk["index"], "of": len(job["chunks"]), "wav": name,
              "audio_s": round(wav.size / rate, 3), "gen_s": round(gen_s, 3), "sample_rate": rate,
              "peak": round(float(np.abs(wav).max()), 5), **mem})
        if ceiling and mem.get("footprint", 0) > ceiling:
            emit({"event": "failed", "stage": "memory-safety", "index": chunk["index"],
                  "message": f"footprint {mem['footprint']} crossed the safety ceiling {ceiling}"})
            return ow.EXIT_FAILED
    emit({"event": "done", "chunks": done, "sample_rate": rate, "device": device, "dtype": dtype_name,
          "wall_s": round(time.perf_counter() - started, 3), "load_s": load_s, "network_attempts": len(network),
          **memory(torch, device)})
    return ow.EXIT_OK


def main(argv: list[str]) -> int:
    network: list = []
    ow.install_network_guard(network)
    lifeline()
    if len(argv) != 2:
        sys.stderr.write("usage: macos_p4a_omnivoice_worker.py <job.json>\n")
        return 64
    try:
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
        job = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        found = problems(job)
        if found:
            emit({"event": "failed", "stage": "job", "message": "the job cannot run: " + "; ".join(found)})
            return ow.EXIT_FAILED
        return run(job, network)
    except Exception as exc:  # noqa: BLE001
        emit({"event": "failed", "stage": "network" if network else "worker", "message": f"{type(exc).__name__}: {exc}",
              "network": network[:5], "trace": traceback.format_exc()[-1500:]})
        return ow.EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main(sys.argv))
