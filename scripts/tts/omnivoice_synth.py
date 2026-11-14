"""omnivoice_synth.py — OmniVoice conversion for ACT: prepare the text once, supervise bounded workers, assemble, encode once.

The application-side half of the OmniVoice engine (plan section 4). The model runs in ``omnivoice_worker.py`` inside the
engine's own environment (``.venv/engines/omnivoice``); this module imports numpy and soundfile (application dependencies) and nothing of torch or
OmniVoice, so the GUI process never loads the model stack. It reuses the Qwen3 engine's engine-neutral parts -- the
verified sentence planner and its source spans, the local-engine assembly, the shared final-tail policy, the one encode
and the atomic publication, and the Job Object process containment -- and keeps its own words, limits and supervision.

What happens for one file (``omnivoice_file_to_mp3``, the same shape as ``qwen3_file_to_mp3``):

1. The run's frozen ``SpeechPrepSnapshot`` is applied ONCE, here in the app, by ``speech.pipeline.prepare`` on the decoded
   source (``utf-8-sig``) with the OmniVoice route, before any chunking or worker. The worker receives exactly the
   prepared text, split into chunks; it never normalizes again (``normalize_text`` is off).
2. The prepared text is planned into whole-sentence chunks of at most :data:`OMNIVOICE_MAX_CHUNK_CHARS`, never across a
   paragraph or title, each with its exact source span, verified against the text before anything runs.
3. The voice's own owner-curated recording is verified -- its SHA-256, format, exact length and the 10-second maximum
   (one hash-bound owner exception; ``omnivoice_runtime``) -- and handed to the worker whole and unchanged, with its
   owner-written transcript and a cache identity that binds every input of the clone prompt. Nothing is cropped or
   copied; OmniVoice resamples the reference in memory.
4. The chunks go to the worker in batches of at most :data:`CHUNKS_PER_WORKER`: each batch is a fresh worker process, so
   no file, however long, accumulates GPU state in one process (upstream issue #199). Cancellation asks politely (a flag
   file) and then, after a short grace period, kills the whole process tree.
5. The chunk waveforms are read back in plan order, validated, joined with the voice preset's paragraph pause between
   chunks (the local-engine policy) and encoded **once** to the MP3, published under a temporary name and moved into
   place only when complete. The job folder (which holds the user's text) is always removed.

Nothing falls back: an unavailable engine, model or reference raises ``OmniVoiceUnavailable``; a GPU that fails, a worker
that dies, or a chunk that is wrong fails the file with a plain sentence.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import soundfile as sf

from shared.cancellation import ConversionCancelled
from tts import omnivoice_runtime as ov
from tts import qwen3_process
from tts import qwen3_synth as _local  # the engine-neutral planner, assembly, encode and publication
from tts.omnivoice_runtime import OmniVoiceUnavailable
from tts.speech.document import read_source_text
from tts.speech.pipeline import prepare
from tts.speech.profiles import OMNIVOICE as OMNIVOICE_ROUTE

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
#: OmniVoice is planned in whole sentences up to this many characters. Upstream splits any text whose estimated speech
#: exceeds ``audio_chunk_threshold`` (30 s) into its own sub-chunks; the six reference speakers speak about 12-14
#: characters a second, so 300 characters (about 21-26 s) keeps every chunk one upstream generation, under ACT's own
#: plan and pauses.
OMNIVOICE_MAX_CHUNK_CHARS = 300
#: The most chunks one worker process renders before it exits and a fresh one takes over (bounded lifetime: GPU memory
#: cannot accumulate across a long book). Reloading costs a few seconds per batch; the clone prompt is reused from cache.
CHUNKS_PER_WORKER = 48
#: Bump deliberately whenever a change can alter generated audio (planning, seeding, generation, assembly).
PIPELINE_REVISION = 1
SEED_BASE = 20261113

LANGUAGE = "English"
DTYPE = "float16"
DEVICE = "cuda"
#: The pinned generation baseline: ``OmniVoiceGenerationConfig``'s own defaults in omnivoice 0.2.1, written out so a run
#: states exactly what it used (plan section 3: 32 steps). ``preprocess_prompt`` trims the reference's leading and
#: trailing silence to 100/200 ms and its inner pauses to 200 ms, in memory; it never adds audio. Not user controls.
GENERATION = {
    "num_step": 32, "guidance_scale": 2.0, "t_shift": 0.1, "layer_penalty_factor": 5.0, "position_temperature": 5.0,
    "class_temperature": 0.0, "denoise": True, "preprocess_prompt": True, "postprocess_output": True,
    "audio_chunk_duration": 15.0, "audio_chunk_threshold": 30.0, "pad_duration": 0.1, "fade_duration": 0.1,
}

#: After asking a worker to stop, how long it gets to stop on its own before its process tree is killed.
CANCEL_GRACE_S = 2.0
#: After the kill, how long the supervisor still waits for the output pipe to close (the final deadline).
KILL_WAIT_S = 10.0
#: No protocol event for this long is a stalled worker (a cold model load from a slow disk is the longest real gap).
EVENT_TIMEOUT_S = 900.0
#: After its result, how long a worker gets to exit; one that will not is killed and its result distrusted.
EXIT_GRACE_S = 20.0
STALE_JOB_AGE_S = 24 * 3600.0
STDERR_TAIL_CHARS = 1500


class OmniVoiceFailed(RuntimeError):
    """The worker ran but this file could not be produced. The message is fit to show a user."""


# --------------------------------------------------------------------------- #
# Planning and the job
# --------------------------------------------------------------------------- #
def plan_chunks(text: str) -> list[_local.Chunk]:
    """Whole-sentence chunks of the prepared text, each with its exact span, verified (the shared local planner)."""
    return _local.plan_chunks(text, OMNIVOICE_MAX_CHUNK_CHARS)


def derive_seed(voice_id: str, chunk: _local.Chunk) -> int:
    """Stable per-chunk seed: the same voice, position and words always give the same seed, so a retry renders the same
    text the same way."""
    text_hash = hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
    digest = hashlib.sha256(f"{SEED_BASE}|{voice_id}|{chunk.index}|{text_hash}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF


def batches(chunks: list, size: int = CHUNKS_PER_WORKER) -> list[list]:
    if size < 1:
        raise ValueError("a worker renders at least one chunk")
    return [chunks[i:i + size] for i in range(0, len(chunks), size)]


def build_job(voice: ov.OmniVoiceVoice, spec: ov.ReferenceSpec, chunks: list, *, job_dir: Path, reference: dict,
              model_dir: Path, omnivoice_version: str, prompt_cache: Optional[dict]) -> dict:
    """Everything one worker needs, as plain data. Pure: touches no disk.

    *reference* is :func:`omnivoice_runtime.verify_reference`'s answer: the voice's own recording, its SHA-256, frame
    count, rate and the most frames it may have. The worker proves the file again before it uses it.
    """
    return {
        "schema": 1, "kind": "synth", "voice_id": voice.voice_id, "model_dir": str(model_dir),
        "omnivoice_version": omnivoice_version, "language": LANGUAGE, "dtype": DTYPE, "device": DEVICE,
        "out_dir": str(job_dir / "chunks"), "cancel_file": str(job_dir / "cancel"),
        "engine_lock": str(ov.engine_lock_path()),
        "reference": {key: reference[key] for key in ("wav", "wav_sha256", "frames", "sample_rate", "max_frames")},
        "ref_text": spec.text, "prompt_cache": prompt_cache, "generation": dict(GENERATION),
        "chunks": [{"index": c.index, "text": c.text, "seed": derive_seed(voice.voice_id, c)} for c in chunks],
    }


def prompt_cache_entry(spec: ov.ReferenceSpec, *, model_revision: str, omnivoice_version: str,
                       prompts_root: Optional[Path] = None) -> dict:
    key, identity = ov.prompt_identity(spec, model_revision=model_revision, omnivoice_version=omnivoice_version,
                                       preprocess_prompt=GENERATION["preprocess_prompt"], dtype=DTYPE)
    root = ov.ensure_runtime_dir(ov.prompts_root()) if prompts_root is None else Path(prompts_root)
    return {"path": str(root / ov.prompt_cache_path(spec.voice_id, key).name), "key": key, "identity": identity}


# --------------------------------------------------------------------------- #
# Running one worker under supervision
# --------------------------------------------------------------------------- #
def _tail(path: Path, limit: int = STDERR_TAIL_CHARS) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-limit:].strip()
    except OSError:
        return ""


def _detail(text: str) -> str:
    return f" {text}" if text else ""


@dataclass
class WorkerRun:
    terminal: dict
    chunk_events: list[dict]
    loaded: dict
    returncode: int


def run_worker(job: dict, job_dir: Path, *, name: str, python: Path, script: Path, env: dict,
               cancel_check: Optional[Callable[[], bool]] = None, log: Callable[[str], None] = print,
               on_chunk: Optional[Callable[[dict], None]] = None, grace_s: float = CANCEL_GRACE_S,
               event_timeout_s: float = EVENT_TIMEOUT_S, exit_grace_s: float = EXIT_GRACE_S,
               kill_wait_s: float = KILL_WAIT_S,
               kill: Callable[[subprocess.Popen], None] = qwen3_process.kill_tree) -> WorkerRun:
    """Run one worker (one batch) to completion under supervision.

    The contract is the Qwen3 worker's: exactly one terminal event (``done``, ``failed`` or ``canceled``) and, for
    ``done``, a clean exit. Anything else -- an exit without a result, a malformed or repeated result, a stall, a
    ``done`` followed by a crash or a hang -- fails the file with the worker's own stderr tail. Every deadline is checked
    on every pass, so a worker flooding its output cannot postpone being stopped; only protocol events count as progress.
    A cancel request becomes ``ConversionCancelled`` once the worker has stopped or been killed.
    """
    job_path = job_dir / f"{name}.json"
    job_path.write_text(json.dumps(job), encoding="utf-8")
    stderr_path = job_dir / f"{name}-stderr.txt"
    cancel_flag = Path(job["cancel_file"])
    cancel_flag.unlink(missing_ok=True)
    lines: "queue.Queue[Optional[str]]" = queue.Queue()
    with open(stderr_path, "w", encoding="utf-8") as stderr_file:
        try:
            proc = qwen3_process.spawn(
                [str(python), "-I", str(script), str(job_path)], require_job=True, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=stderr_file, text=True, encoding="utf-8", errors="replace", env=env,
                cwd=str(job_dir))
        except qwen3_process.ContainmentUnavailable as exc:
            raise OmniVoiceFailed("The OmniVoice voice engine was not started: Windows would not let this app keep "
                                  f"control of it, so it could not be stopped safely if you cancelled. ({exc})") from exc

        def pump() -> None:
            try:
                for line in proc.stdout:  # type: ignore[union-attr]
                    lines.put(line.rstrip("\r\n"))
            finally:
                lines.put(None)

        reader = threading.Thread(target=pump, daemon=True)
        reader.start()
        loaded: dict = {}
        chunk_events: list[dict] = []
        terminal: Optional[dict] = None
        terminal_at = cancel_requested_at = killed_at = None
        last_progress = time.monotonic()
        try:
            while True:
                now = time.monotonic()
                if cancel_requested_at is not None:
                    if killed_at is None and now - cancel_requested_at > grace_s:
                        kill(proc)
                        killed_at = now
                elif terminal_at is not None:
                    if killed_at is None and now - terminal_at > exit_grace_s:
                        kill(proc)
                        killed_at = now
                elif now - last_progress > event_timeout_s:
                    kill(proc)
                    raise OmniVoiceFailed(
                        f"The OmniVoice voice engine stopped responding and was stopped. {_tail(stderr_path)}".strip())
                if killed_at is not None and now - killed_at > kill_wait_s:
                    break
                try:
                    line = lines.get(timeout=0.2)
                except queue.Empty:
                    line = ""
                if line is None:
                    break
                if line:
                    event = _local.parse_event(line)
                    if event is None:
                        log(f"  [omnivoice] {line[:300]}")
                    else:
                        last_progress = time.monotonic()
                        kind = event["event"]
                        if kind == "_malformed":
                            raise OmniVoiceFailed("The OmniVoice voice engine sent an unreadable message and was stopped.")
                        if kind == "loaded":
                            loaded = event
                            log(f"OmniVoice is running on the GPU: {event.get('device_name') or 'unknown device'} "
                                f"(model {event.get('load_s')} s, clone prompt {event.get('prompt')} in "
                                f"{event.get('prompt_s')} s).")
                        elif kind == "chunk":
                            chunk_events.append(event)
                            if on_chunk is not None:
                                on_chunk(event)
                        elif kind in ("done", "failed", "canceled"):
                            if terminal is not None:
                                raise OmniVoiceFailed("The OmniVoice voice engine reported more than one result.")
                            terminal, terminal_at = event, time.monotonic()
                if cancel_requested_at is None and cancel_check is not None and cancel_check():
                    cancel_requested_at = time.monotonic()
                    cancel_flag.write_text("cancel", encoding="utf-8")
        except BaseException:
            kill(proc)
            raise
        finally:
            if proc.poll() is None:
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    kill(proc)
            reader.join(timeout=5)
            if reader.is_alive():
                kill(proc)
                reader.join(timeout=5)
            if not reader.is_alive() and proc.stdout is not None:
                proc.stdout.close()
            qwen3_process.release(proc)
    returncode = proc.returncode if proc.returncode is not None else -1
    if cancel_requested_at is not None:
        raise ConversionCancelled("Conversion cancelled by user.")
    if terminal is None:
        raise OmniVoiceFailed(f"The OmniVoice voice engine ended unexpectedly (exit code {returncode})."
                              f"{_detail(_tail(stderr_path))}")
    if terminal["event"] == "done" and returncode != 0:
        raise OmniVoiceFailed("The OmniVoice voice engine reported success but then did not exit cleanly "
                              f"(exit code {returncode}), so its audio was discarded.{_detail(_tail(stderr_path))}")
    return WorkerRun(terminal=terminal, chunk_events=chunk_events, loaded=loaded, returncode=returncode)


def failure_message(terminal: dict) -> str:
    """A user-fit sentence for a worker ``failed`` event."""
    stage = terminal.get("stage")
    detail = str(terminal.get("message") or "no further detail")
    if stage in ("engine", "job"):
        return detail if stage == "engine" else f"The OmniVoice voice engine refused the job: {detail}"
    if terminal.get("oom"):
        return ("The OmniVoice voice ran out of GPU memory. Close other programs that use the graphics card and try "
                f"again. ({detail})")
    if terminal.get("gpu") is False:
        return ov.NO_GPU_MESSAGE
    where = {"load": "loading the model and the voice", "generate": "generating speech",
             "import": "starting the voice engine", "network": "starting (it tried to use the network)",
             "worker": "running"}.get(stage, "running")
    message = f"The OmniVoice voice engine failed while {where}: {detail}"
    if stage == "import" or detail.startswith(("ImportError", "ModuleNotFoundError")):
        message += " The engine's installed packages look damaged; repair it from the optional voice setup."
    return message


# --------------------------------------------------------------------------- #
# Job folders
# --------------------------------------------------------------------------- #
def new_job_dir(root: Optional[Path] = None) -> Path:
    base = ov.ensure_runtime_dir(ov.jobs_root()) if root is None else Path(root)
    path = base / f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def remove_job_dir(path: Path) -> None:
    """The job folder holds the user's text; it never outlives the run. Best effort (a file may be briefly locked)."""
    for attempt in range(3):
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return
        time.sleep(0.2 * (attempt + 1))


def cleanup_stale_jobs(root: Optional[Path] = None, max_age_s: float = STALE_JOB_AGE_S) -> int:
    base = ov.ensure_runtime_dir(ov.jobs_root()) if root is None else Path(root)
    if not base.is_dir():
        return 0
    removed, cutoff = 0, time.time() - max_age_s
    for child in base.iterdir():
        try:
            if child.is_dir() and not child.is_symlink() and child.stat().st_mtime < cutoff:
                remove_job_dir(child)
                removed += 1
        except OSError:
            continue
    return removed


def record_failure(job_dir: Path, message: str, runtime: Optional[Path] = None) -> None:
    """Keep the last failure's worker stderr for diagnosis (no job text beyond what a traceback quotes)."""
    try:
        target = (ov.runtime_dir() if runtime is None else Path(runtime)) / "last-failure.txt"
        stderr = "\n".join(_tail(p, 6000) for p in sorted(job_dir.glob("*-stderr.txt")))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\n{message}\n\n{stderr}\n", encoding="utf-8")
    except (OSError, OmniVoiceUnavailable):
        pass


# --------------------------------------------------------------------------- #
# Collecting, checking and publishing
# --------------------------------------------------------------------------- #
def collect_chunks(chunk_dir: Path, chunk_events: list[dict], expected: int) -> tuple[list[np.ndarray], int]:
    """Read every chunk back in plan order and validate it; the files, not the events, are the evidence."""
    by_index = {int(e["index"]): e for e in chunk_events if "index" in e}
    if sorted(by_index) != list(range(expected)) or len(chunk_events) != expected:
        raise OmniVoiceFailed(f"The OmniVoice voice engine reported {len(by_index)} of {expected} chunks.")
    audio: list[np.ndarray] = []
    rate: Optional[int] = None
    for index in range(expected):
        path = chunk_dir / str(by_index[index].get("wav", ""))
        if not path.is_file() or path.parent != chunk_dir:
            raise OmniVoiceFailed(f"OmniVoice chunk {index + 1} was reported but its audio file is missing.")
        try:
            data, file_rate = sf.read(str(path), dtype="float32", always_2d=False)
            audio.append(_local.validate_chunk_audio(data, file_rate, rate))
        except (_local.AssemblyError, RuntimeError, OSError, ValueError) as exc:
            raise OmniVoiceFailed(f"OmniVoice chunk {index + 1} could not be used: {exc}") from exc
        rate = int(file_rate)
    return audio, int(rate)


def peak_report(pcm: np.ndarray) -> tuple[float, int]:
    """``(peak dBFS, samples at or beyond full scale)`` of the assembled narration: diagnostic only, nothing is changed
    (16-bit PCM clips at full scale; no loudness processing is added for one engine)."""
    peak = float(np.abs(pcm).max()) if pcm.size else 0.0
    return (20 * np.log10(peak) if peak > 0 else float("-inf")), int(np.count_nonzero(np.abs(pcm) >= 1.0))


def _encoder(wav: Path, mp3: Path, bitrate: Optional[str], *, work_dir: Path,
             cancel_check: Optional[Callable[[], bool]] = None) -> None:
    """The shared one encode, with an OmniVoice failure type (its sentence is engine-neutral)."""
    try:
        _local.encode_mp3(wav, mp3, bitrate, work_dir=work_dir, cancel_check=cancel_check)
    except _local.Qwen3Failed as exc:
        raise OmniVoiceFailed(str(exc)) from exc


# --------------------------------------------------------------------------- #
# The entry point
# --------------------------------------------------------------------------- #
def omnivoice_file_to_mp3(
    source_path: str,
    output_mp3_path: str,
    voice_id: str,
    end_silence_ms: int = 0,
    chunk_pause_ms: int = 700,
    log: Callable[[str], None] = print,
    cancel_check: Optional[Callable[[], bool]] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    bitrate: Optional[str] = None,
    *,
    speech_prep=None,
    availability: Callable[[str], tuple[bool, str]] = ov.voice_availability,
    python: Optional[Path] = None,
    script: Optional[Path] = None,
    jobs_root: Optional[Path] = None,
    prompts_root: Optional[Path] = None,
    env: Optional[dict] = None,
    encoder: Callable = _encoder,
    chunks_per_worker: int = CHUNKS_PER_WORKER,
    grace_s: float = CANCEL_GRACE_S,
    event_timeout_s: float = EVENT_TIMEOUT_S,
    exit_grace_s: float = EXIT_GRACE_S,
    kill_wait_s: float = KILL_WAIT_S,
) -> None:
    """Read plain text from a file -> OmniVoice workers -> one MP3. The same shape as ``qwen3_file_to_mp3``.

    ``progress_callback(done, total)`` fires after each chunk on the calling (worker) thread. Cancellation raises
    ``ConversionCancelled`` and is honoured at every stage up to the instant the file is published; no partial MP3 is
    left and an existing destination is not touched until the new file is complete. No closing pause (v0.7.0 Q1):
    ``end_silence_ms`` is accepted for callers and ignored. The keyword-only seams exist for the offline tests.
    """
    src = Path(source_path)
    if not src.exists():
        raise FileNotFoundError(f"Source text file not found: {source_path}")
    voice = ov.get_voice(voice_id)
    ok, reason = availability(voice_id)  # authoritative, asked again here: the answer can change after selection
    if not ok:
        raise OmniVoiceUnavailable(reason)

    with ov.inference_lease():
        # Speech preparation runs ONCE per file, here, on the decoded source; None or "off" leaves the text as it is
        # (structure still applies). The worker is given exactly this text.
        prepared = prepare(read_source_text(src), speech_prep, OMNIVOICE_ROUTE)
        for line in prepared.details():
            log(line)
        text = prepared.text
        if not text:
            raise ValueError("No text content found after parsing source file.")
        chunks = plan_chunks(text)
        if prepared.enabled:
            _local.chunk_source_spans(prepared, chunks)  # every chunk maps back to the decoded source, in order

        spec = ov.reference_spec(voice_id)
        try:
            reference = ov.verify_reference(spec, ov.reference_path(voice))
        except ov.ReferenceAssetError as exc:
            raise OmniVoiceUnavailable(f"Setup required for {voice.label}: its reference recording cannot be used "
                                       f"({exc}).") from exc
        manifest = ov.load_manifest()
        model_revision, version = manifest["model"]["revision"], manifest["engine"]["omnivoice"]
        cache = prompt_cache_entry(spec, model_revision=model_revision, omnivoice_version=version,
                                   prompts_root=prompts_root)
        py = Path(python) if python is not None else ov.venv_python()
        worker = Path(script) if script is not None else ov.worker_script()
        cleanup_stale_jobs(jobs_root)
        job_dir = new_job_dir(jobs_root)
        try:
            log(f"OmniVoice: synthesizing {len(chunks)} chunk(s) in {voice.label} (pipeline revision "
                f"{PIPELINE_REVISION}; reference {spec.duration_s:.3f} s at {spec.sample_rate} Hz, used whole; "
                f"{GENERATION['num_step']} steps)...")
            env = ov.worker_environment() if env is None else env
            events: list[dict] = []
            groups = batches(chunks, chunks_per_worker)
            for number, group in enumerate(groups, start=1):
                _local._raise_if_cancelled(cancel_check)

                def chunk_done(event: dict) -> None:
                    events.append(event)
                    log(f"  OmniVoice chunk {int(event.get('index', 0)) + 1}/{len(chunks)} ({event.get('audio_s')} s "
                        f"of audio in {event.get('gen_s')} s)")
                    if progress_callback is not None:
                        progress_callback(len(events), len(chunks))

                job = build_job(voice, spec, group, job_dir=job_dir, reference=reference, model_dir=ov.model_dir(),
                                omnivoice_version=version, prompt_cache=cache)
                run = run_worker(job, job_dir, name=f"job-{number:03d}", python=py, script=worker, env=env,
                                 cancel_check=cancel_check, log=log, on_chunk=chunk_done, grace_s=grace_s,
                                 event_timeout_s=event_timeout_s, exit_grace_s=exit_grace_s, kill_wait_s=kill_wait_s)
                if run.terminal["event"] == "canceled":
                    raise ConversionCancelled("Conversion cancelled by user.")
                if run.terminal["event"] == "failed":
                    raise OmniVoiceFailed(failure_message(run.terminal))
                if sorted(int(e["index"]) for e in run.chunk_events) != [c.index for c in group]:
                    raise OmniVoiceFailed(f"The OmniVoice voice engine rendered other chunks than it was given "
                                          f"(batch {number} of {len(groups)}).")
            _local._raise_if_cancelled(cancel_check)
            audio, rate = collect_chunks(job_dir / "chunks", events, len(chunks))
            _local._raise_if_cancelled(cancel_check)
            log("  Assembling OmniVoice audio...")
            pcm, report = _local.assemble(audio, rate, chunk_pause_ms=chunk_pause_ms, end_silence_ms=0)
            peak_db, at_full_scale = peak_report(pcm)
            log(f"  OmniVoice peak {peak_db:.2f} dBFS" + (f"; {at_full_scale} sample(s) at full scale" if at_full_scale
                                                           else ""))
            _local._raise_if_cancelled(cancel_check)
            _local.publish_mp3(pcm, rate, output_mp3_path, bitrate, work_dir=job_dir, cancel_check=cancel_check,
                               encoder=encoder, log=log)
            log(f"OmniVoice: saved -> {output_mp3_path} ({report['speech_samples'] / rate:.1f} s of speech)")
        except OmniVoiceFailed as exc:
            record_failure(job_dir, str(exc), None if jobs_root is None else Path(jobs_root))
            raise
        finally:
            remove_job_dir(job_dir)
