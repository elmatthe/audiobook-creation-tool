"""omnivoice_p1_worker.py -- runs ONLY inside ``.venv-omnivoice`` (ACT v0.8.0 Phase 1, developer only).

(Phase 1 qualification record. Since the owner decision of 2026-11-13 the application's engine lives at
``.venv/engines/omnivoice`` and its worker is ``scripts/tts/omnivoice_worker.py``; the app never uses the sibling.)

    <.venv-omnivoice\\Scripts\\python.exe> -I omnivoice_p1_worker.py <job.json>

Started by ``omnivoice_p1.py``. Before anything heavy is imported it installs an audit hook that refuses every network
name lookup and every connection that is not to this computer's own loopback address, and records each attempt: the
proof is that the model and its audio tokenizer load from the verified local snapshot with the network closed, not
merely that an offline flag was set. It also refuses to start unless the Hub's offline switches are on.

Modes: ``probe`` imports the stack and reports versions and the GPU (no model); ``clone`` loads the pinned snapshot,
builds a voice-clone prompt from the 10-second excerpt and its excerpt transcript (so OmniVoice never loads Whisper),
narrates one fixed text and writes one WAV. The report is written to the job's ``report`` path; stdout carries
``@@EVENT <json>`` lines and exactly one terminal event, ``done`` or ``failed``.

Standard library only at import time, so the app's own interpreter can import it to test the pure parts.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import traceback
import warnings
from pathlib import Path
from typing import Optional

EVENT_PREFIX = "@@EVENT "
EXIT_OK, EXIT_FAILED = 0, 2
REQUIRED_OFFLINE = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
NETWORK_EVENTS = frozenset({"socket.connect", "socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyname_ex",
                            "socket.gethostbyaddr", "socket.sendto", "socket.sendmsg"})
GENERATION_KEYS = frozenset({"num_step", "guidance_scale", "t_shift", "layer_penalty_factor", "position_temperature",
                             "class_temperature", "denoise", "preprocess_prompt", "postprocess_output",
                             "audio_chunk_duration", "audio_chunk_threshold", "pad_duration", "fade_duration"})
CLONE_KEYS = frozenset({"mode", "model_dir", "excerpt_wav", "excerpt_frames", "sample_rate", "ref_text", "text",
                        "language", "generation", "dtype", "device", "seed", "output_wav", "prompt_path",
                        "prompt_identity", "report"})
PACKAGES = ("torch", "torchaudio", "transformers", "accelerate", "omnivoice", "huggingface-hub", "numpy", "soundfile",
            "librosa", "safetensors", "tokenizers")


class NetworkRefused(PermissionError):
    """A network name lookup or connection was attempted inside the proof worker."""


def emit(event: dict) -> None:
    sys.stdout.write(EVENT_PREFIX + json.dumps(event, ensure_ascii=True) + "\n")
    sys.stdout.flush()


# --------------------------------------------------------------------------- #
# The network guard
# --------------------------------------------------------------------------- #
def is_loopback(host: object) -> bool:
    text = str(host or "").strip("[]").lower()
    return text in ("localhost", "::1") or text.startswith("127.")


def network_target(event: str, args: tuple) -> Optional[str]:
    """The host an audited network event is aimed at, or ``None`` when it cannot be told (treated as remote)."""
    try:
        if event in ("socket.connect", "socket.sendto", "socket.sendmsg"):
            address = args[1]
            return str(address[0]) if isinstance(address, tuple) else str(address)
        return str(args[0])
    except (IndexError, TypeError):
        return None


def install_network_guard(log: list) -> None:
    """Refuse (and record) every non-loopback lookup or connection, and every ``urllib`` request, for good.

    Loopback stays open: Windows builds an event loop's self-pipe from a connected loopback pair. An audit hook cannot
    be removed, so nothing later in the process can switch this off.
    """
    def hook(event: str, args: tuple) -> None:
        if event in NETWORK_EVENTS:
            host = network_target(event, args)
            if host is None or not is_loopback(host):
                log.append({"event": event, "target": host})
                raise NetworkRefused(f"network access is closed in the OmniVoice proof worker ({event} {host})")
        elif event == "urllib.Request":
            log.append({"event": event, "target": str(args[0])[:200] if args else None})
            raise NetworkRefused("network access is closed in the OmniVoice proof worker (urllib)")

    sys.addaudithook(hook)


def record_subprocesses(log: list) -> None:
    def hook(event: str, args: tuple) -> None:
        if event == "subprocess.Popen":
            log.append(str(args[0])[:200] if args else "?")

    sys.addaudithook(hook)


# --------------------------------------------------------------------------- #
# The job
# --------------------------------------------------------------------------- #
def job_problems(job: dict, environ: Optional[dict] = None) -> list[str]:
    """Why this job may not run here, checked before anything heavy is imported."""
    environ = os.environ if environ is None else environ
    problems = [f"{name} is not {value}" for name, value in REQUIRED_OFFLINE.items() if environ.get(name) != value]
    if not environ.get("HF_HOME"):
        problems.append("HF_HOME is not set to the proof's own empty cache")
    mode = job.get("mode")
    if mode == "probe":
        return problems + ([] if job.get("report") else ["no report path"])
    if mode != "clone":
        return problems + [f"unknown mode {mode!r}"]
    missing = sorted(CLONE_KEYS - set(job))
    if missing:
        return problems + [f"missing {', '.join(missing)}"]
    model = Path(job["model_dir"])
    if not (model / "config.json").is_file():
        problems.append("the model folder has no config.json")
    if not (model / "audio_tokenizer" / "config.json").is_file():
        problems.append("the model folder has no audio_tokenizer (OmniVoice would fetch one from the Hub)")
    if not Path(job["excerpt_wav"]).is_file():
        problems.append("the excerpt WAV is missing")
    frames, rate = job.get("excerpt_frames"), job.get("sample_rate")
    if type(frames) is not int or type(rate) is not int or not 0 < frames <= 10 * rate:
        problems.append("the excerpt is not a whole number of frames inside the first 10 seconds")
    for key in ("ref_text", "text"):
        if not isinstance(job.get(key), str) or not job[key].strip():
            problems.append(f"{key} is blank (a clone without its excerpt transcript would load Whisper)")
    if not isinstance(job.get("generation"), dict) or set(job["generation"]) - GENERATION_KEYS:
        problems.append("the generation settings name something OmniVoiceGenerationConfig does not have")
    if not str(job.get("device", "")).startswith("cuda"):
        problems.append("the proof runs on the GPU only")
    return problems


def _versions() -> dict:
    import importlib.metadata as md

    found = {"python": sys.version.split()[0], "executable": sys.executable, "prefix": sys.prefix}
    for name in PACKAGES:
        try:
            found[name] = md.version(name)
        except md.PackageNotFoundError:
            found[name] = None
    return found


def _gpu(torch) -> dict:
    info = {"cuda_available": bool(torch.cuda.is_available()), "torch_cuda": torch.version.cuda,
            "cudnn": torch.backends.cudnn.version() if torch.backends.cudnn.is_available() else None}
    if info["cuda_available"] and torch.cuda.device_count() > 0:
        props = torch.cuda.get_device_properties(0)
        info.update({"device_name": props.name, "capability": list(torch.cuda.get_device_capability(0)),
                     "total_mib": props.total_memory // 2**20, "arch_list": list(torch.cuda.get_arch_list())})
    return info


def probe(job: dict, report: dict) -> None:
    import torch  # noqa: F401  (imported first on purpose: its DLLs are what Smart App Control evaluates)
    import numpy  # noqa: F401
    import soundfile  # noqa: F401  (libsndfile: the clone reads the excerpt and writes the WAV with it)
    import omnivoice
    import transformers  # noqa: F401
    from omnivoice import OmniVoice, OmniVoiceGenerationConfig  # noqa: F401  (everything clone imports, loaded once here)
    from transformers import HiggsAudioV2TokenizerModel  # noqa: F401  (the tokenizer class OmniVoice needs, >= 5.3.0)

    report.update({"versions": _versions(), "gpu": _gpu(torch), "omnivoice_version": omnivoice.__version__})
    if report["gpu"]["cuda_available"]:
        # Real kernels, not just a device query; cuBLAS and cuDNN load lazily, so they are touched here too.
        sample = torch.ones(1024, device="cuda:0").sum().item()
        x = torch.ones(64, 64, device="cuda:0", dtype=torch.float16)
        matmul = (x @ x).float().sum().item()
        conv = torch.nn.functional.conv1d(torch.ones(1, 4, 32, device="cuda:0"), torch.ones(2, 4, 3, device="cuda:0"))
        torch.cuda.synchronize()
        report["gpu"]["kernel_ok"] = sample == 1024.0 and matmul == 64.0 ** 3 and float(conv.sum().item()) == 720.0


def clone(job: dict, report: dict) -> None:
    import numpy as np
    import soundfile as sf
    import torch
    from omnivoice import OmniVoice, OmniVoiceGenerationConfig, __version__ as omnivoice_version

    report.update({"versions": _versions(), "gpu": _gpu(torch), "omnivoice_version": omnivoice_version})
    if not report["gpu"]["cuda_available"]:
        raise RuntimeError("PyTorch reports no usable CUDA device")
    torch.manual_seed(int(job["seed"]))
    torch.cuda.reset_peak_memory_stats(0)
    emit({"event": "progress", "stage": "load", "message": "loading the model and audio tokenizer from local files"})
    started = time.perf_counter()
    model = OmniVoice.from_pretrained(job["model_dir"], device_map=job["device"], dtype=getattr(torch, job["dtype"]))
    torch.cuda.synchronize()
    report["load_s"] = round(time.perf_counter() - started, 2)
    report["audio_tokenizer_from_snapshot"] = os.path.isdir(os.path.join(job["model_dir"], "audio_tokenizer"))
    report["sampling_rate"] = int(model.sampling_rate)
    report["after_load_allocated_mib"] = torch.cuda.memory_allocated(0) // 2**20

    audio, rate = sf.read(job["excerpt_wav"], dtype="float32", always_2d=True)
    if rate != job["sample_rate"] or audio.shape[0] != job["excerpt_frames"]:
        raise RuntimeError(f"the excerpt read back as {audio.shape[0]} frames at {rate} Hz, not as the job says")
    waveform = torch.from_numpy(np.ascontiguousarray(audio.T))
    emit({"event": "progress", "stage": "prompt", "message": "building the clone prompt from the 10-second excerpt"})
    started = time.perf_counter()
    prompt = model.create_voice_clone_prompt(ref_audio=(waveform, rate), ref_text=job["ref_text"],
                                             preprocess_prompt=bool(job["generation"].get("preprocess_prompt", True)))
    report["prompt_s"] = round(time.perf_counter() - started, 2)
    report["asr_loaded"] = getattr(model, "_asr_pipe", None) is not None
    report["prompt"] = {"ref_text_used": prompt.ref_text, "ref_rms": float(prompt.ref_rms),
                        "ref_audio_tokens_shape": list(prompt.ref_audio_tokens.shape)}
    Path(job["prompt_path"]).parent.mkdir(parents=True, exist_ok=True)
    prompt.save(job["prompt_path"])
    Path(job["prompt_path"] + ".identity.json").write_text(json.dumps(job["prompt_identity"], indent=1, sort_keys=True),
                                                           encoding="utf-8")

    emit({"event": "progress", "stage": "generate", "message": "narrating the fixed proof text"})
    config = OmniVoiceGenerationConfig(**job["generation"])
    started = time.perf_counter()
    outputs = model.generate(text=job["text"], language=job["language"], voice_clone_prompt=prompt,
                             generation_config=config)
    torch.cuda.synchronize()
    report["generate_s"] = round(time.perf_counter() - started, 2)
    waveform_out = np.asarray(outputs[0], dtype=np.float32)
    sf.write(job["output_wav"], waveform_out, model.sampling_rate, subtype="PCM_16")
    seconds = waveform_out.shape[-1] / model.sampling_rate
    report.update({
        "output_seconds": round(seconds, 3), "real_time_factor": round(report["generate_s"] / seconds, 3) if seconds else None,
        "output_peak_abs": float(np.abs(waveform_out).max()) if waveform_out.size else 0.0,
        "peak_allocated_mib": torch.cuda.max_memory_allocated(0) // 2**20,
        "peak_reserved_mib": torch.cuda.max_memory_reserved(0) // 2**20,
    })


def main(argv: list[str]) -> int:
    network: list = []
    subprocesses: list = []
    install_network_guard(network)
    record_subprocesses(subprocesses)
    report: dict = {"status": "failed", "network_attempts": network, "subprocesses": subprocesses}
    job: dict = {}
    captured: list[str] = []

    class _Keep(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(f"{record.levelname} {record.name}: {record.getMessage()}"[:500])

    try:
        job = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        problems = job_problems(job)
        if problems:
            raise RuntimeError("the job cannot run: " + "; ".join(problems))
        logging.getLogger().addHandler(_Keep(level=logging.WARNING))
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            (probe if job["mode"] == "probe" else clone)(job, report)
        report["warnings"] = sorted({f"{w.category.__name__}: {w.message}"[:500] for w in caught})
        report["log_warnings"] = captured
        report["status"] = "done"
    except BaseException as exc:  # noqa: BLE001 - every failure is reported, then the process ends
        report["error"] = f"{type(exc).__name__}: {exc}"[:2000]
        report["traceback"] = traceback.format_exc()[-6000:]
        report["log_warnings"] = captured
    finally:
        if job.get("report"):
            Path(job["report"]).write_text(json.dumps(report, indent=1, sort_keys=True, default=str), encoding="utf-8")
    if report["status"] == "done":
        emit({"event": "done", "stage": "done", "message": job.get("mode", "")})
        return EXIT_OK
    emit({"event": "failed", "stage": "failed", "message": report.get("error", "")[:300]})
    return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main(sys.argv))
