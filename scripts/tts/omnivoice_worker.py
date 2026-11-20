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

**On a Mac (macOS P4B).** The job names one of the two configurations the owner accepted after P4A: the Apple GPU
(``mps``) or the CPU (``cpu``), both float32; anything else -- MPS float16 included -- is refused before anything heavy
is imported, and so is a job started with ``PYTORCH_ENABLE_MPS_FALLBACK`` set (an operation MPS cannot run would then
run on the CPU unseen). After loading, the model's backbone must be entirely on the asked device (the audio tokenizer
stays on the CPU under MPS, where upstream places it), or the run fails: never a silent CPU fallback. Memory is the
process's physical footprint (``proc_pid_rusage``) and, on MPS, PyTorch's own allocator figures; the peaks are the
lifetime footprint and the largest per-chunk samples (MPS has no peak counter). Windows runs exactly as released (CUDA,
float16). When the app starts the worker on a Mac, ``shared/child_entry.py`` has already started its owner's lifeline
before this file runs, so it ends with its owner however that ends.
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
#: macOS P4B: the device and dtype pairs a job may name on a Mac -- the two configurations the owner accepted after the
#: P4A experiment (2026-11-16). MPS float16 was an experiment only and is refused.
MAC_CONFIGURATIONS = frozenset({("mps", "float32"), ("cpu", "float32")})


def device_problems(job: dict, environ: Optional[dict] = None, system: Optional[str] = None) -> list[str]:
    """Why the job's device and dtype may not run here. Windows: the released check, the GPU (CUDA) only. A Mac: one of
    :data:`MAC_CONFIGURATIONS`, and never with the MPS fallback switch set."""
    environ = os.environ if environ is None else environ
    system = sys.platform if system is None else system
    if system != "darwin":
        return [] if job.get("device") == "cuda" else ["the OmniVoice voices run on the GPU only"]
    problems = []
    if (job.get("device"), job.get("dtype")) not in MAC_CONFIGURATIONS:
        problems.append(f"on a Mac the OmniVoice voices run only on the Apple GPU (mps) or the CPU, in float32, not "
                        f"{job.get('device')!r}/{job.get('dtype')!r}")
    if environ.get("PYTORCH_ENABLE_MPS_FALLBACK"):
        problems.append("PYTORCH_ENABLE_MPS_FALLBACK is set (an operation the GPU cannot run would run on the CPU "
                        "unseen)")
    return problems


def probe_problems(job: dict, environ: Optional[dict] = None, system: Optional[str] = None) -> list[str]:
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
    problems += device_problems(job, environ, system)
    packages = job.get("packages")
    if not isinstance(packages, dict) or not packages or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in packages.items()):
        problems.append("the pinned package set is not a name-to-version mapping")
    if not isinstance(job.get("foreign"), list) or not all(isinstance(p, str) for p in job["foreign"]):
        problems.append("the other environments to stay apart from are not a list of folders")
    return problems


def job_problems(job: dict, environ: Optional[dict] = None, system: Optional[str] = None) -> list[str]:
    """Why this job may not run here, checked before anything heavy is imported. *system* is ``sys.platform`` unless a
    test asks as another platform (macOS P4B: the device rules differ between Windows and a Mac)."""
    environ = os.environ if environ is None else environ
    problems = [f"{name} is not {value}" for name, value in REQUIRED_OFFLINE.items() if environ.get(name) != value]
    if job.get("kind") == "probe" and job.get("schema") == 1:
        return problems + probe_problems(job, environ, system)
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
    problems += device_problems(job, environ, system)
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


def _device_usable(torch, device: str) -> bool:
    """Whether PyTorch can run on *device* here: CUDA as released; the Mac's GPU as MPS reports it; the CPU always."""
    if device == "cuda":
        return _cuda_usable(torch)
    if device == "mps":
        try:
            return bool(torch.backends.mps.is_available())
        except Exception:  # noqa: BLE001 - an MPS that cannot even answer is not usable
            return False
    return device == "cpu"


def _device_map(device: str) -> str:
    return "cuda:0" if device == "cuda" else device


def _sync(torch, device: str) -> None:
    """Wait for the device's queued work (timings and memory figures mean nothing before it). The CPU has no queue."""
    if device == "cuda":
        torch.cuda.synchronize()
    elif device == "mps":
        torch.mps.synchronize()


def _empty_cache(torch, device: str) -> None:
    if device == "cuda":
        torch.cuda.empty_cache()
    elif device == "mps":
        torch.mps.empty_cache()


#: ``rusage_info_v4`` (``<sys/resource.h>``): after the 16-byte UUID, 64-bit fields; ``ri_phys_footprint`` is the 8th
#: and ``ri_lifetime_max_phys_footprint`` the 29th (the reader ``tts.local_engine_worker`` uses).
_RUSAGE_INFO_V4 = 4
_PHYS_FOOTPRINT_OFFSET = 16 + 7 * 8
_LIFETIME_MAX_FOOTPRINT_OFFSET = 16 + 28 * 8


def _footprint() -> dict:
    """This process's physical footprint now and its lifetime peak, in MiB (macOS), or ``{}``."""
    try:
        import ctypes
        import struct

        libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        buffer = ctypes.create_string_buffer(512)
        if libproc.proc_pid_rusage(os.getpid(), _RUSAGE_INFO_V4, buffer) != 0:
            return {}
        now = struct.unpack_from("=Q", buffer.raw, _PHYS_FOOTPRINT_OFFSET)[0]
        peak = struct.unpack_from("=Q", buffer.raw, _LIFETIME_MAX_FOOTPRINT_OFFSET)[0]
        return {"footprint_mib": int(now) // 2**20, "peak_footprint_mib": int(peak) // 2**20}
    except (OSError, AttributeError, ValueError):
        return {}


def _memory(torch, device: str = "cuda") -> dict:
    """Memory now: the GPU's allocator figures on CUDA (as released); on a Mac the process footprint and, on MPS,
    PyTorch's allocated and driver figures (the GPU shares the Mac's memory)."""
    if device == "cuda":
        return {"vram_allocated_mib": torch.cuda.memory_allocated(0) // 2**20,
                "vram_reserved_mib": torch.cuda.memory_reserved(0) // 2**20}
    found = _footprint()
    if device == "mps":
        found["mps_allocated_mib"] = int(torch.mps.current_allocated_memory()) // 2**20
        found["mps_driver_mib"] = int(torch.mps.driver_allocated_memory()) // 2**20
    return found


def _sysctl(name: str, kind: str):
    """One macOS ``sysctlbyname`` value (``"int"`` or ``"text"``), or ``None``."""
    try:
        import ctypes
        import ctypes.util

        libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.dylib", use_errno=True)
        size = ctypes.c_size_t(0)
        if libc.sysctlbyname(name.encode(), None, ctypes.byref(size), None, 0) != 0 or not size.value:
            return None
        buffer = ctypes.create_string_buffer(size.value)
        if libc.sysctlbyname(name.encode(), buffer, ctypes.byref(size), None, 0) != 0:
            return None
        if kind == "text":
            return buffer.raw[:size.value].split(b"\0", 1)[0].decode("utf-8", "replace").strip()
        return int.from_bytes(buffer.raw[:size.value], sys.byteorder)
    except (OSError, AttributeError, ValueError):
        return None


def _device_facts(torch, device: str) -> dict:
    """The device a run is on, by name, and its memory: the CUDA GPU's own properties (as released), or the Mac's chip
    and its unified memory (``machdep.cpu.brand_string``, ``hw.memsize``)."""
    if device == "cuda":
        props = torch.cuda.get_device_properties(0)
        return {"device": "cuda:0", "device_name": props.name, "total_mib": props.total_memory // 2**20}
    chip = _sysctl("machdep.cpu.brand_string", "text") or "Apple Silicon"
    where = "GPU (MPS)" if device == "mps" else "CPU"
    return {"device": device, "device_name": f"{chip} {where}", "total_mib": (_sysctl("hw.memsize", "int") or 0) // 2**20}


def placement_problem(model, device: str, dtype: str) -> str:
    """Why the loaded model is not where the job asked (macOS P4B; never a silent fallback), or ``""``.

    Every backbone parameter must be on *device* in *dtype*. The audio tokenizer, registered under the model, is checked
    apart: under MPS upstream places it on the CPU itself ("higgs-audio-v2-tokenizer does not support MPS"), and on the
    CPU everything is on the CPU."""
    backbone, tokenizer = [], []
    for name, parameter in model.named_parameters():
        (tokenizer if name.startswith("audio_tokenizer.") else backbone).append(parameter)
    placed = sorted({p.device.type for p in backbone})
    if placed != [device]:
        return f"the model's backbone is on {placed}, not only on {device} (no silent fallback is allowed)"
    dtypes = sorted({str(p.dtype).replace("torch.", "") for p in backbone if p.is_floating_point()})
    if dtypes != [dtype]:
        return f"the model's backbone is in {dtypes}, not only in {dtype}"
    expected = "cpu" if device in ("mps", "cpu") else device
    placed_tokenizer = sorted({p.device.type for p in tokenizer})
    if tokenizer and placed_tokenizer != [expected]:
        return f"the audio tokenizer is on {placed_tokenizer}, not where upstream places it ({expected})"
    return ""


def _is_oom(exc: BaseException) -> bool:
    return "out of memory" in str(exc).lower()


def speakable(text: str) -> bool:
    """Whether a chunk has anything to say: a letter or a digit, in any script (v0.8.1 C1). A paragraph of only
    punctuation or symbols -- ``...``, ``......``, a lone U+FFFD -- is its own chunk (the planner never crosses a
    paragraph) and asks the model for a pause, nothing else."""
    return any(ch.isalnum() for ch in text)


def pause_samples(generation: dict, rate: int) -> int:
    """The silence that stands for a chunk with nothing to say whose whole rendering was silence: the edge padding
    OmniVoice's own post-processing puts around every rendering (``pad_duration`` each side; 0.2 s as released)."""
    return max(1, int(2 * float(generation.get("pad_duration", 0.0)) * rate))


def failure_memory(torch, device: str) -> dict:
    """The memory figures for a ``failed`` event (v0.8.1 C1): :func:`_memory` and, on CUDA, the worker's peaks so far.
    Diagnostic only, so it never raises: a device too broken to answer gives ``{}``."""
    try:
        found = _memory(torch, device)
        if device == "cuda":
            found["peak_allocated_mib"] = torch.cuda.max_memory_allocated(0) // 2**20
            found["peak_reserved_mib"] = torch.cuda.max_memory_reserved(0) // 2**20
        return found
    except Exception:  # noqa: BLE001 - a diagnostic must never replace the failure it describes
        return {}


#: Windows error numbers with which a library load says the COMPUTER is short of memory, not that a file is wrong:
#: ERROR_NOT_ENOUGH_MEMORY, ERROR_OUTOFMEMORY and ERROR_COMMITMENT_LIMIT ("The paging file is too small for this
#: operation to complete", which PyTorch's CUDA libraries meet when Windows' commit charge is near its limit).
MEMORY_WINERRORS = frozenset({8, 14, 1455})


def _caused_by(exc: BaseException, kind: type) -> bool:
    """Whether *exc*, or anything it was raised from or while handling, is a *kind* (a library may wrap the cause)."""
    seen: set[int] = set()
    current: Optional[BaseException] = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, kind):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return False


def import_failure(exc: BaseException) -> dict:
    """The terminal event for a failure raised while the worker imports its stack (NumPy, soundfile, PyTorch, OmniVoice).

    Stage ``import`` -- the engine's own installed files do not import -- for a missing or broken module and for a
    native library Windows will not load. That last one arrives as ``OSError`` (PyTorch's own loader raises
    ``ctypes.WinError``: ``[WinError 193]`` for a damaged image, ``[WinError 126]`` for a missing one), not as
    ``ImportError``, so the exception's kind alone cannot be the test: WHERE it was raised is (v0.8.0 independent
    review R1). Two things raised there say nothing against the files and are told apart:

    * the computer ran out of memory while loading a library (``MemoryError``, or an ``OSError`` carrying one of
      :data:`MEMORY_WINERRORS`): stage ``memory``, so a rebuild is never offered for it;
    * Smart App Control's refusal keeps stage ``import`` with Windows' own words, which
      ``omnivoice_runtime.failure_needs_rebuild`` excludes (as the installer's proof does).

    The network guard's refusal is never classified here: the callers re-raise it, and :func:`main` reports it as stage
    ``network``. The original exception's type opens the message; a bounded traceback goes with it."""
    winerror = getattr(exc, "winerror", None)
    memory = isinstance(exc, MemoryError) or (isinstance(winerror, int) and winerror in MEMORY_WINERRORS)
    event = {"event": "failed", "stage": "memory" if memory else "import", "message": f"{type(exc).__name__}: {exc}",
             "trace": traceback.format_exc()[-1500:]}
    if isinstance(winerror, int):
        event["winerror"] = winerror
    return event


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
    try:
        import numpy as np
        import soundfile as sf
        import torch
        from omnivoice import OmniVoice, OmniVoiceGenerationConfig, VoiceClonePrompt, __version__ as omnivoice_version
    except Exception as exc:  # noqa: BLE001 - only these imports: what they raise is about the installed stack
        if _caused_by(exc, NetworkRefused):
            raise  # the network guard, not the files: main() reports it as stage "network"
        emit(import_failure(exc))
        return EXIT_FAILED

    started = time.perf_counter()
    out_dir = Path(job["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    chunks = job["chunks"]
    if omnivoice_version != job["omnivoice_version"]:
        emit({"event": "failed", "stage": "import", "message": f"omnivoice {omnivoice_version} is installed, not the "
              f"pinned {job['omnivoice_version']}"})
        return EXIT_FAILED
    device = job["device"]
    if not _device_usable(torch, device):
        message = ("PyTorch reports no usable CUDA GPU" if device == "cuda" else
                   "PyTorch reports that this Mac's GPU (MPS) cannot be used")
        emit({"event": "failed", "stage": "load", "message": message, "gpu": False})
        return EXIT_FAILED
    if _cancelled(job):
        emit({"event": "canceled", "completed": 0})
        return EXIT_CANCELED
    try:
        load_started = time.perf_counter()
        model = OmniVoice.from_pretrained(job["model_dir"], device_map=_device_map(device),
                                          dtype=getattr(torch, job["dtype"]))
        model.load_asr_model = _refuse_speech_recognizer
        _sync(torch, device)
        load_s = round(time.perf_counter() - load_started, 2)
        if device != "cuda":
            misplaced = placement_problem(model, device, job["dtype"])
            if misplaced:
                raise RuntimeError(misplaced)
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
        _sync(torch, device)
    except Exception as exc:  # noqa: BLE001
        emit({"event": "failed", "stage": "load", "message": f"{type(exc).__name__}: {exc}", "oom": _is_oom(exc),
              "trace": traceback.format_exc()[-1500:]})
        return EXIT_FAILED
    facts = _device_facts(torch, device)
    loaded = {"event": "loaded", **facts,
              "load_s": load_s, "prompt": prompt_source, "prompt_s": round(time.perf_counter() - prompt_started, 2),
              "ref_text_used": prompt.ref_text, "sampling_rate": int(model.sampling_rate), "versions": _versions(),
              "chunks": len(chunks), **_memory(torch, device)}
    if device != "cuda":
        loaded["dtype"] = job["dtype"]
    emit(loaded)

    done = 0
    rate = int(model.sampling_rate)
    peaks: dict = {}  # a Mac: the largest per-chunk samples (MPS has no peak counter of its own)
    for position, chunk in enumerate(chunks):
        if _cancelled(job):
            emit({"event": "canceled", "completed": done})
            return EXIT_CANCELED
        t0 = time.perf_counter()
        shape = None
        silent = False
        try:
            torch.manual_seed(int(chunk["seed"]))  # seeds the CPU and MPS generators as well
            if device == "cuda":
                torch.cuda.manual_seed_all(int(chunk["seed"]))
            outputs = model.generate(text=chunk["text"], language=job["language"], voice_clone_prompt=prompt,
                                     generation_config=config, normalize_text=False)
            _sync(torch, device)
            wav = np.asarray(outputs[0], dtype=np.float32)
            shape = list(wav.shape)
            # v0.8.1 C1: for a chunk with nothing to say ("..."), the model renders under a second of near-silence;
            # about one seed in five keeps it all below -50 dBFS, upstream's post-processing then removes all of it as
            # silence and returns no samples. That is the right answer, not a failure: the chunk becomes the pause
            # upstream puts around every rendering. A chunk with words that comes back empty still fails below.
            if wav.ndim == 1 and wav.size == 0 and not speakable(chunk["text"]):
                wav, silent = np.zeros(pause_samples(job["generation"], rate), dtype=np.float32), True
            if wav.ndim != 1 or wav.size == 0 or not np.isfinite(wav).all():
                raise RuntimeError(f"the model returned unusable audio (shape {wav.shape})")
            name = f"chunk-{int(chunk['index']) + 1:04d}.wav"
            sf.write(str(out_dir / name), wav, rate, subtype="FLOAT")
        except Exception as exc:  # noqa: BLE001
            # v0.8.1 C1: where in this worker's batch it failed, how long it had run, what came back and the memory
            # then, so a failure in a long run can be found again (the parent adds the file, chunk and batch).
            failed = {"event": "failed", "stage": "generate", "index": chunk["index"], "position": position,
                      "of": len(chunks), "oom": _is_oom(exc), "message": f"{type(exc).__name__}: {exc}",
                      "trace": traceback.format_exc()[-1500:], "gen_s": round(time.perf_counter() - t0, 3),
                      **failure_memory(torch, device)}
            if shape is not None:
                failed["audio_shape"] = shape
            emit(failed)
            return EXIT_FAILED
        done += 1
        memory = _memory(torch, device)
        for key in ("footprint_mib", "mps_allocated_mib", "mps_driver_mib"):
            if key in memory:
                peaks[key] = max(peaks.get(key, 0), memory[key])
        emit({"event": "chunk", "index": chunk["index"], "of": len(chunks), "wav": name,
              "audio_s": round(wav.size / rate, 3), "gen_s": round(time.perf_counter() - t0, 3), "sample_rate": rate,
              "peak": round(float(np.abs(wav).max()), 5), **({"silent": True} if silent else {}), **memory})
    if device == "cuda":
        emit({"event": "done", "chunks": done, "sample_rate": rate, "device": "cuda:0",
              "wall_s": round(time.perf_counter() - started, 2), "load_s": load_s,
              "peak_allocated_mib": torch.cuda.max_memory_allocated(0) // 2**20,
              "peak_reserved_mib": torch.cuda.max_memory_reserved(0) // 2**20})
        return EXIT_OK
    emit({"event": "done", "chunks": done, "sample_rate": rate, "device": device, "dtype": job["dtype"],
          "wall_s": round(time.perf_counter() - started, 2), "load_s": load_s,
          "peak_footprint_mib": _footprint().get("peak_footprint_mib"),
          **{f"max_{key}": value for key, value in peaks.items()}})
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
    stage: ``versions``, ``isolation`` or ``import`` speak against the environment itself; ``gpu``, ``load`` and
    ``memory`` (the computer ran out of memory while a library loaded: :func:`import_failure`) do not."""
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
        if _caused_by(exc, NetworkRefused):
            raise  # the network guard, not the files (the same rule as a conversion's imports)
        emit(import_failure(exc))
        return EXIT_FAILED
    if omnivoice_version != job["omnivoice_version"]:
        emit({"event": "failed", "stage": "versions", "message": f"omnivoice {omnivoice_version} is installed, not the "
              f"pinned {job['omnivoice_version']}"})
        return EXIT_FAILED
    device = job["device"]
    if not _device_usable(torch, device):
        message = ("PyTorch reports no usable CUDA GPU" if device == "cuda" else
                   "PyTorch reports that this Mac's GPU (MPS) cannot be used")
        emit({"event": "failed", "stage": "gpu", "message": message, "gpu": False})
        return EXIT_FAILED
    try:
        if device == "cuda":
            check = (torch.ones(1024, device="cuda", dtype=torch.float16) * 2).sum().item()
        else:  # a Mac: the same small kernel on the asked device, in the float32 the engine runs in
            check = (torch.ones(1024, device=device, dtype=getattr(torch, job["dtype"])) * 2).sum().item()
        _sync(torch, device)
        if check != 2048:
            raise RuntimeError(f"a {device.upper()} kernel returned {check}, not 2048")
    except Exception as exc:  # noqa: BLE001
        emit({"event": "failed", "stage": "gpu", "message": f"{type(exc).__name__}: {exc}"})
        return EXIT_FAILED
    try:
        load_started = time.perf_counter()
        model = OmniVoice.from_pretrained(job["model_dir"], device_map=_device_map(device),
                                          dtype=getattr(torch, job["dtype"]))
        model.load_asr_model = _refuse_speech_recognizer
        _sync(torch, device)
        load_s = round(time.perf_counter() - load_started, 2)
        if device != "cuda":
            misplaced = placement_problem(model, device, job["dtype"])
            if misplaced:
                raise RuntimeError(misplaced)
    except Exception as exc:  # noqa: BLE001
        emit({"event": "failed", "stage": "load", "message": f"{type(exc).__name__}: {exc}", "oom": _is_oom(exc),
              "trace": traceback.format_exc()[-1500:]})
        return EXIT_FAILED
    facts = _device_facts(torch, device)
    memory = _memory(torch, device)
    report = {"event": "probe", "versions": _versions(), "device_name": facts["device_name"],
              "total_mib": facts["total_mib"], "load_s": load_s, "sampling_rate": int(model.sampling_rate),
              "isolation": "ok", "network_attempts": len(network), "wall_s": round(time.perf_counter() - started, 2),
              **memory}
    if device != "cuda":
        report.update(device=device, dtype=job["dtype"])
    emit(report)
    del model
    _empty_cache(torch, device)
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
