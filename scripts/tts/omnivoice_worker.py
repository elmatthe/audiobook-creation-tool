"""omnivoice_worker.py — the OmniVoice worker. Runs ONLY inside ``.venv/engines/omnivoice``, never in the app's own interpreter.

``omnivoice_synth`` writes a job file and starts, for at most a bounded batch of one file's chunks::

    <.venv/engines/omnivoice python> -I omnivoice_worker.py <job.json>

then reads ``@@EVENT <json>`` lines from stdout. Everything else the libraries print is ignored by the reader.

Before anything heavy is imported the worker

* installs an audit hook that refuses every network name lookup and every connection not to this computer's own loopback
  address: the model and its audio tokenizer load from the verified local snapshot with the network closed, so a run can
  never acquire a model, a tokenizer, Whisper or a dependency implicitly;
* refuses to start unless the Hub's offline switches are on and the job is well formed;
* takes the job's ``engine_lock`` and holds it until it exits, so an install or repair sees an engine in use.

Then it loads the pinned snapshot on the GPU, builds (or reloads, from this app's own identity-checked cache) one voice
clone prompt from the voice's own approved recording -- read once, its bytes proved against the approved SHA-256 and
given to OmniVoice whole at its own rate (OmniVoice resamples it in memory) -- and the owner-written transcript, so
OmniVoice never loads its speech recognizer, which is also switched off outright; then it renders each chunk, as given,
to its own float WAV. ``normalize_text`` is always off: the text arrives already prepared by the app's one
speech-preparation pass.

A ``probe`` job (v0.8.0 Phase 3) is the optional installer's proof, run under the same guards: the pinned package
versions, the environment's isolation, an import of the stack, a CUDA kernel and an offline model load -- no audio, no
reference, nothing written; it ends with one ``probe`` or ``failed`` event.

Terminal events (exactly one per run): ``done``, ``failed``, ``canceled``. Cancellation is a flag file checked before the
load and before each chunk; the parent also kills the whole process tree if the worker does not stop promptly. Nothing
falls back: no CPU, no other voice, no other recording.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Optional

EVENT_PREFIX = "@@EVENT "
EXIT_OK, EXIT_FAILED, EXIT_CANCELED = 0, 2, 130
REQUIRED_OFFLINE = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
NETWORK_EVENTS = frozenset({"socket.connect", "socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyname_ex",
                            "socket.gethostbyaddr", "socket.sendto", "socket.sendmsg"})
#: The ``OmniVoiceGenerationConfig`` fields a job may set (omnivoice 0.2.1); anything else is refused.
GENERATION_KEYS = frozenset({"num_step", "guidance_scale", "t_shift", "layer_penalty_factor", "position_temperature",
                             "class_temperature", "denoise", "preprocess_prompt", "postprocess_output",
                             "audio_chunk_duration", "audio_chunk_threshold", "pad_duration", "fade_duration"})
SYNTH_KEYS = frozenset({"schema", "kind", "voice_id", "model_dir", "omnivoice_version", "language", "dtype", "device",
                        "out_dir", "cancel_file", "engine_lock", "reference", "ref_text", "prompt_cache", "generation",
                        "chunks"})
#: v0.8.0 Phase 3: the installer's proof -- the pinned versions, isolation, the GPU and an offline model load, no audio.
PROBE_KEYS = frozenset({"schema", "kind", "model_dir", "omnivoice_version", "dtype", "device", "engine_lock",
                        "packages", "environment", "foreign"})

ENGINE_BUSY_MESSAGE = ("The OmniVoice voice engine is in use by another conversion, or is being installed or repaired, "
                       "right now. Try again when that has finished.")
NO_ENGINE_LOCK_MESSAGE = ("This job does not name the OmniVoice engine lock, so the engine was not started: it never runs "
                          "where an install or repair could not see it.")

_engine_fd: Optional[int] = None


class NetworkRefused(PermissionError):
    """A network name lookup or connection was attempted inside the worker."""


class SpeechRecognizerRefused(RuntimeError):
    """OmniVoice tried to load its speech recognizer; the six voices always carry their reference transcript."""


def emit(event: dict) -> None:
    sys.stdout.write(EVENT_PREFIX + json.dumps(event, ensure_ascii=True) + "\n")
    sys.stdout.flush()


# --------------------------------------------------------------------------- #
# The network guard (Phase 1's proof guard, now in production)
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
    """Refuse (and record) every non-loopback lookup or connection and every ``urllib`` request, for good. Loopback stays
    open (Windows builds an event loop's self-pipe from a loopback pair). An audit hook cannot be removed."""
    def hook(event: str, args: tuple) -> None:
        if event in NETWORK_EVENTS:
            host = network_target(event, args)
            if host is None or not is_loopback(host):
                log.append({"event": event, "target": host})
                raise NetworkRefused(f"network access is closed in the OmniVoice worker ({event} {host})")
        elif event == "urllib.Request":
            log.append({"event": event, "target": str(args[0])[:200] if args else None})
            raise NetworkRefused("network access is closed in the OmniVoice worker (urllib)")

    sys.addaudithook(hook)


# --------------------------------------------------------------------------- #
# The engine lock (the same OS-owned protocol as tts.qwen3_runtime.FileLock)
# --------------------------------------------------------------------------- #
def claim_engine(job: dict) -> Optional[str]:
    """Take this run's engine lock and keep it until :func:`release_engine` or the process ends; the reason not, or None."""
    global _engine_fd
    if _engine_fd is not None:
        return None
    path = job.get("engine_lock")
    if not path:
        return NO_ENGINE_LOCK_MESSAGE
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_RDWR)
    except OSError as exc:
        return f"The OmniVoice voice engine could not check that it is free to run ({exc.strerror or exc})."
    try:
        if sys.platform == "win32":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return ENGINE_BUSY_MESSAGE
    _engine_fd = fd
    return None


def release_engine() -> None:
    global _engine_fd
    if _engine_fd is None:
        return
    fd, _engine_fd = _engine_fd, None
    try:
        if sys.platform == "win32":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    except OSError:
        pass
    finally:
        os.close(fd)


# --------------------------------------------------------------------------- #
# The job
# --------------------------------------------------------------------------- #
def probe_problems(job: dict) -> list[str]:
    """Why a ``probe`` job (v0.8.0 Phase 3: the installer's proof) may not run, checked before anything heavy."""
    missing = sorted(PROBE_KEYS - set(job))
    if missing:
        return [f"missing {', '.join(missing)}"]
    problems = []
    model = Path(job["model_dir"])
    if not (model / "config.json").is_file():
        problems.append("the model folder has no config.json")
    if not (model / "audio_tokenizer" / "config.json").is_file():
        problems.append("the model folder has no audio_tokenizer (OmniVoice would fetch one)")
    if job.get("device") != "cuda":
        problems.append("the OmniVoice voices run on the GPU only")
    packages = job.get("packages")
    if not isinstance(packages, dict) or not packages or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in packages.items()):
        problems.append("the pinned package set is not a name-to-version mapping")
    if not isinstance(job.get("foreign"), list) or not all(isinstance(p, str) for p in job["foreign"]):
        problems.append("the other environments to stay apart from are not a list of folders")
    return problems


def job_problems(job: dict, environ: Optional[dict] = None) -> list[str]:
    """Why this job may not run here, checked before anything heavy is imported."""
    environ = os.environ if environ is None else environ
    problems = [f"{name} is not {value}" for name, value in REQUIRED_OFFLINE.items() if environ.get(name) != value]
    if job.get("kind") == "probe" and job.get("schema") == 1:
        return problems + probe_problems(job)
    if job.get("kind") != "synth" or job.get("schema") != 1:
        return problems + [f"unknown job kind {job.get('kind')!r}"]
    missing = sorted(SYNTH_KEYS - set(job))
    if missing:
        return problems + [f"missing {', '.join(missing)}"]
    model = Path(job["model_dir"])
    if not (model / "config.json").is_file():
        problems.append("the model folder has no config.json")
    if not (model / "audio_tokenizer" / "config.json").is_file():
        problems.append("the model folder has no audio_tokenizer (OmniVoice would fetch one)")
    reference = job.get("reference") if isinstance(job.get("reference"), dict) else {}
    frames, rate, limit = reference.get("frames"), reference.get("sample_rate"), reference.get("max_frames")
    if not Path(str(reference.get("wav", ""))).is_file():
        problems.append("the reference recording is missing")
    if any(type(v) is not int for v in (frames, rate, limit)) or rate <= 0 or not 0 < frames <= limit:
        problems.append("the reference recording is not a whole number of frames within its approved length")
    sha = reference.get("wav_sha256")
    if not isinstance(sha, str) or len(sha) != 64 or any(ch not in "0123456789abcdef" for ch in sha):
        problems.append("the reference recording has no approved SHA-256 to be proved against")
    if not isinstance(job.get("ref_text"), str) or not job["ref_text"].strip():
        problems.append("the reference transcript is blank (OmniVoice would load a speech recognizer)")
    generation = job.get("generation")
    if not isinstance(generation, dict) or set(generation) - GENERATION_KEYS:
        problems.append("the generation settings name something OmniVoiceGenerationConfig does not have")
    if job.get("device") != "cuda":
        problems.append("the OmniVoice voices run on the GPU only")
    chunks = job.get("chunks")
    if not isinstance(chunks, list) or not chunks or not all(
            isinstance(c, dict) and type(c.get("index")) is int and isinstance(c.get("text"), str) and c["text"].strip()
            and type(c.get("seed")) is int for c in chunks):
        problems.append("the chunks are not a list of indexed, seeded, non-blank texts")
    return problems


def _cancelled(job: dict) -> bool:
    flag = job.get("cancel_file")
    return bool(flag) and Path(flag).exists()


def _versions() -> dict:
    import importlib.metadata as md

    found = {"python": sys.version.split()[0]}
    for name in ("torch", "transformers", "omnivoice", "numpy", "soundfile"):
        try:
            found[name] = md.version(name)
        except md.PackageNotFoundError:
            found[name] = None
    return found


def _cuda_usable(torch) -> bool:
    try:
        return bool(torch.cuda.is_available()) and torch.cuda.device_count() > 0
    except Exception:  # noqa: BLE001 - a broken driver is "no usable GPU", not a crash
        return False


def _memory(torch) -> dict:
    return {"vram_allocated_mib": torch.cuda.memory_allocated(0) // 2**20,
            "vram_reserved_mib": torch.cuda.memory_reserved(0) // 2**20}


def _is_oom(exc: BaseException) -> bool:
    return "out of memory" in str(exc).lower()


def _refuse_speech_recognizer(*_args, **_kwargs):
    raise SpeechRecognizerRefused("the OmniVoice speech recognizer is never loaded: every voice has its reference "
                                  "transcript")


def read_reference(job: dict):
    """The approved recording's frames as a (1, frames) float array and its own rate, proved before use.

    The file is read ONCE: those bytes must hash to the approved SHA-256, and those same bytes must be the plain 16-bit
    mono PCM WAV of exactly the frame count and rate the job names, within its approved length. Nothing is cropped,
    resampled or written here; OmniVoice resamples the waveform to its own rate in memory.
    """
    import io
    import wave

    import numpy as np

    reference = job["reference"]
    data = Path(reference["wav"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != reference["wav_sha256"]:
        raise RuntimeError("the reference recording is not the approved one")
    with wave.open(io.BytesIO(data), "rb") as source:
        params = source.getparams()
        pcm = source.readframes(params.nframes)
    if (params.comptype, params.nchannels, params.sampwidth, params.framerate, params.nframes) != (
            "NONE", 1, 2, reference["sample_rate"], reference["frames"]) or len(pcm) != params.nframes * 2 \
            or params.nframes > reference["max_frames"]:
        raise RuntimeError("the reference recording is not in the format the job names")
    waveform = (np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0)[np.newaxis, :]
    return waveform, params.framerate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while block := handle.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def load_cached_prompt(cache: Optional[dict], prompt_class) -> Optional[object]:
    """A prompt this app's own worker saved under exactly this identity, or ``None``. A file whose identity record is
    missing, different or does not hash to the recorded bytes is never loaded (and is rebuilt over)."""
    if not cache:
        return None
    path = Path(cache["path"])
    record_path = path.with_name(path.name + ".identity.json")
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict) or record.get("identity") != cache["identity"] or record.get("key") != cache["key"]:
        return None
    if not path.is_file() or _sha256(path) != record.get("sha256"):
        return None
    prompt = prompt_class.load(str(path), map_location="cpu")  # torch.load(weights_only=True) upstream
    return prompt if prompt.ref_text == record.get("ref_text_used") else None


def save_prompt(prompt, cache: dict) -> None:
    """Publish the prompt and its identity record atomically (temporary file, then rename); best effort."""
    path = Path(cache["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    record_path = path.with_name(path.name + ".identity.json")
    record_tmp = record_path.with_name(f"{record_path.name}.{os.getpid()}.tmp")
    try:
        prompt.save(str(tmp))
        record_tmp.write_text(json.dumps({"key": cache["key"], "identity": cache["identity"], "sha256": _sha256(tmp),
                                          "ref_text_used": prompt.ref_text}, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
        os.replace(record_tmp, record_path)
    except OSError:
        pass
    finally:
        for leftover in (tmp, record_tmp):
            try:
                leftover.unlink()
            except OSError:
                pass


def run_synth(job: dict) -> int:
    import numpy as np
    import soundfile as sf
    import torch
    from omnivoice import OmniVoice, OmniVoiceGenerationConfig, VoiceClonePrompt, __version__ as omnivoice_version

    started = time.perf_counter()
    out_dir = Path(job["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    chunks = job["chunks"]
    if omnivoice_version != job["omnivoice_version"]:
        emit({"event": "failed", "stage": "import", "message": f"omnivoice {omnivoice_version} is installed, not the "
              f"pinned {job['omnivoice_version']}"})
        return EXIT_FAILED
    if not _cuda_usable(torch):
        emit({"event": "failed", "stage": "load", "message": "PyTorch reports no usable CUDA GPU", "gpu": False})
        return EXIT_FAILED
    if _cancelled(job):
        emit({"event": "canceled", "completed": 0})
        return EXIT_CANCELED
    try:
        load_started = time.perf_counter()
        model = OmniVoice.from_pretrained(job["model_dir"], device_map="cuda:0", dtype=getattr(torch, job["dtype"]))
        model.load_asr_model = _refuse_speech_recognizer
        torch.cuda.synchronize()
        load_s = round(time.perf_counter() - load_started, 2)
        config = OmniVoiceGenerationConfig(**job["generation"])
        prompt_started = time.perf_counter()
        prompt = load_cached_prompt(job.get("prompt_cache"), VoiceClonePrompt)
        prompt_source = "cache"
        if prompt is None:
            waveform, rate = read_reference(job)
            prompt = model.create_voice_clone_prompt(ref_audio=(torch.from_numpy(waveform), rate),
                                                     ref_text=job["ref_text"], preprocess_prompt=config.preprocess_prompt)
            prompt_source = "built"
            if job.get("prompt_cache"):
                save_prompt(prompt, job["prompt_cache"])
        torch.cuda.synchronize()
    except Exception as exc:  # noqa: BLE001
        emit({"event": "failed", "stage": "load", "message": f"{type(exc).__name__}: {exc}", "oom": _is_oom(exc),
              "trace": traceback.format_exc()[-1500:]})
        return EXIT_FAILED
    props = torch.cuda.get_device_properties(0)
    emit({"event": "loaded", "device": "cuda:0", "device_name": props.name, "total_mib": props.total_memory // 2**20,
          "load_s": load_s, "prompt": prompt_source, "prompt_s": round(time.perf_counter() - prompt_started, 2),
          "ref_text_used": prompt.ref_text, "sampling_rate": int(model.sampling_rate), "versions": _versions(),
          "chunks": len(chunks), **_memory(torch)})

    done = 0
    rate = int(model.sampling_rate)
    for chunk in chunks:
        if _cancelled(job):
            emit({"event": "canceled", "completed": done})
            return EXIT_CANCELED
        try:
            t0 = time.perf_counter()
            torch.manual_seed(int(chunk["seed"]))
            torch.cuda.manual_seed_all(int(chunk["seed"]))
            outputs = model.generate(text=chunk["text"], language=job["language"], voice_clone_prompt=prompt,
                                     generation_config=config, normalize_text=False)
            torch.cuda.synchronize()
            wav = np.asarray(outputs[0], dtype=np.float32)
            if wav.ndim != 1 or wav.size == 0 or not np.isfinite(wav).all():
                raise RuntimeError(f"the model returned unusable audio (shape {wav.shape})")
            name = f"chunk-{int(chunk['index']) + 1:04d}.wav"
            sf.write(str(out_dir / name), wav, rate, subtype="FLOAT")
        except Exception as exc:  # noqa: BLE001
            emit({"event": "failed", "stage": "generate", "index": chunk["index"], "oom": _is_oom(exc),
                  "message": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-1500:]})
            return EXIT_FAILED
        done += 1
        emit({"event": "chunk", "index": chunk["index"], "of": len(chunks), "wav": name,
              "audio_s": round(wav.size / rate, 3), "gen_s": round(time.perf_counter() - t0, 3), "sample_rate": rate,
              "peak": round(float(np.abs(wav).max()), 5), **_memory(torch)})
    emit({"event": "done", "chunks": done, "sample_rate": rate, "device": "cuda:0",
          "wall_s": round(time.perf_counter() - started, 2), "load_s": load_s,
          "peak_allocated_mib": torch.cuda.max_memory_allocated(0) // 2**20,
          "peak_reserved_mib": torch.cuda.max_memory_reserved(0) // 2**20})
    return EXIT_OK


def _canonical(name: str) -> str:
    import re

    return re.sub(r"[-_.]+", "-", name).lower()


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def _within(root: str, candidate: str) -> bool:
    root_n, cand_n = _norm(root), _norm(candidate)
    return cand_n == root_n or cand_n.startswith(root_n.rstrip(os.sep) + os.sep)


def version_problems(packages: dict) -> list[str]:
    """Pinned distributions installed here at another version, or missing (read from this interpreter's metadata)."""
    import importlib.metadata as md

    found = {}
    for dist in md.distributions():
        name = dist.metadata["Name"] if dist.metadata is not None else None
        if name:
            found[_canonical(name)] = dist.version
    return [f"{name} is {found.get(name) or 'missing'}, not {version}" for name, version in sorted(packages.items())
            if found.get(name) != version]


def isolation_problems(job: dict) -> list[str]:
    """What, in this interpreter's own view of itself, shows it reaching the app's ``.venv``, a Qwen3 engine, the user
    site or any site-packages outside the OmniVoice environment.

    The environment is held INSIDE the app's ``.venv`` (``.venv/engines/omnivoice``, v0.8.0), so a path inside the
    environment itself is its own even though it also lies inside that parent; everything else of the parent (its
    ``Lib/site-packages`` above all) is another environment. Its base interpreter must be outside every one of them:
    an engine built from the parent's interpreter would not be independent of it."""
    import site

    environment = job["environment"]
    problems = []
    if _norm(sys.prefix) != _norm(environment):
        problems.append("sys.prefix is not the OmniVoice environment")
    if _norm(sys.prefix) == _norm(sys.base_prefix):
        problems.append("it is not a virtual environment")
    if any(_within(other, sys.base_prefix) for other in job["foreign"]):
        problems.append("it was built from another environment's interpreter, not the app's base Python")
    for entry in sys.path:
        if not entry or _within(environment, entry):
            continue
        if any(_within(other, entry) for other in job["foreign"]):
            problems.append(f"sys.path reaches another environment: {entry}")
        elif "site-packages" in entry.lower():
            problems.append(f"sys.path holds a site-packages outside the OmniVoice environment: {entry}")
    if site.ENABLE_USER_SITE:
        problems.append("the user site-packages is enabled")
    return problems


def run_probe(job: dict, network: list) -> int:
    """The installer's proof (v0.8.0 Phase 3): the pinned versions, isolation, an import of the stack, a CUDA kernel and
    an offline load of the pinned model on the GPU. No audio is generated and nothing is written. Each failure names its
    stage: ``versions``, ``isolation`` or ``import`` speak against the environment itself; ``gpu`` and ``load`` do not."""
    started = time.perf_counter()
    wrong = version_problems(job["packages"])
    if wrong:
        emit({"event": "failed", "stage": "versions", "message": "the environment does not hold its pinned packages: "
              + "; ".join(wrong[:5])})
        return EXIT_FAILED
    isolation = isolation_problems(job)
    if isolation:
        emit({"event": "failed", "stage": "isolation", "message": "; ".join(isolation[:5])})
        return EXIT_FAILED
    try:
        import torch
        from omnivoice import OmniVoice, __version__ as omnivoice_version
    except Exception as exc:  # noqa: BLE001 - an environment whose packages do not import is broken
        emit({"event": "failed", "stage": "import", "message": f"{type(exc).__name__}: {exc}",
              "trace": traceback.format_exc()[-1500:]})
        return EXIT_FAILED
    if omnivoice_version != job["omnivoice_version"]:
        emit({"event": "failed", "stage": "versions", "message": f"omnivoice {omnivoice_version} is installed, not the "
              f"pinned {job['omnivoice_version']}"})
        return EXIT_FAILED
    if not _cuda_usable(torch):
        emit({"event": "failed", "stage": "gpu", "message": "PyTorch reports no usable CUDA GPU", "gpu": False})
        return EXIT_FAILED
    try:
        check = (torch.ones(1024, device="cuda", dtype=torch.float16) * 2).sum().item()
        torch.cuda.synchronize()
        if check != 2048:
            raise RuntimeError(f"a CUDA kernel returned {check}, not 2048")
    except Exception as exc:  # noqa: BLE001
        emit({"event": "failed", "stage": "gpu", "message": f"{type(exc).__name__}: {exc}"})
        return EXIT_FAILED
    try:
        load_started = time.perf_counter()
        model = OmniVoice.from_pretrained(job["model_dir"], device_map="cuda:0", dtype=getattr(torch, job["dtype"]))
        model.load_asr_model = _refuse_speech_recognizer
        torch.cuda.synchronize()
        load_s = round(time.perf_counter() - load_started, 2)
    except Exception as exc:  # noqa: BLE001
        emit({"event": "failed", "stage": "load", "message": f"{type(exc).__name__}: {exc}", "oom": _is_oom(exc),
              "trace": traceback.format_exc()[-1500:]})
        return EXIT_FAILED
    props = torch.cuda.get_device_properties(0)
    memory = _memory(torch)
    emit({"event": "probe", "versions": _versions(), "device_name": props.name,
          "total_mib": props.total_memory // 2**20, "load_s": load_s, "sampling_rate": int(model.sampling_rate),
          "isolation": "ok", "network_attempts": len(network), "wall_s": round(time.perf_counter() - started, 2),
          **memory})
    del model
    torch.cuda.empty_cache()
    return EXIT_OK


def main(argv: list[str]) -> int:
    network: list = []
    install_network_guard(network)
    if len(argv) != 2:
        sys.stderr.write("usage: omnivoice_worker.py <job.json>\n")
        return 64
    try:
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
        job = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        problems = job_problems(job)
        if problems:
            emit({"event": "failed", "stage": "job", "message": "the job cannot run: " + "; ".join(problems)})
            return EXIT_FAILED
        refusal = claim_engine(job)
        if refusal is not None:
            emit({"event": "failed", "stage": "engine", "message": refusal})
            return EXIT_FAILED
        if job["kind"] == "probe":
            return run_probe(job, network)
        return run_synth(job)
    except Exception as exc:  # noqa: BLE001 - the parent must always get a terminal event
        emit({"event": "failed", "stage": "network" if network else "worker", "message": f"{type(exc).__name__}: {exc}",
              "trace": traceback.format_exc()[-1500:]})
        return EXIT_FAILED
    finally:
        release_engine()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
