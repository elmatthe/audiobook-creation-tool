"""omnivoice_synth.py — OmniVoice conversion for ACT: prepare the text once, supervise bounded workers, assemble, encode once.

The application-side half of the OmniVoice engine (plan section 4). The model runs in ``omnivoice_worker.py`` inside the
engine's own environment (``.venv-engines/omnivoice``; ``omnivoice_runtime.venv_dir``); this module imports numpy and soundfile (application dependencies) and nothing of torch or
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
4. The chunks go to the worker in batches of at most :data:`CHUNKS_PER_WORKER` (:data:`MPS_CHUNKS_PER_WORKER` on a Mac's
   GPU): each batch is a fresh worker process, so
   no file, however long, accumulates GPU state in one process (upstream issue #199). Cancellation asks politely (a flag
   file) and then, after a short grace period, kills the whole process tree.
5. The chunk waveforms are read back in plan order, validated, joined with the voice preset's paragraph pause between
   chunks (the local-engine policy) and encoded **once** to the MP3, published under a temporary name and moved into
   place only when complete. The job folder (which holds the user's text) is always removed.

Nothing falls back: an unavailable engine, model or reference raises ``OmniVoiceUnavailable``; a GPU that fails, a worker
that dies, or a chunk that is wrong fails the file with a plain sentence.

**On a Mac (macOS P4B).** The device and dtype come from ``omnivoice_runtime.device_policy`` once per file -- the Mac's
GPU (MPS) in float32 by default, the CPU in float32 by explicit choice -- are logged, go into the job and into the clone
prompt's identity, and are never changed on the way: a GPU that cannot be used fails the file, it does not move to the
CPU. The worker is a class-A child (``shared.child_ownership``): its own process group, started through
``child_entry.py`` so its owner's lifeline ends it however the owner ends; the owner is the app window's, or this
process's own when there is none (a command-line tool). Cancel keeps its released shape (flag file, 2 s grace, the
whole group killed and reaped), within the macOS contract's OmniVoice bound (plan section 11.2.1: 4 s). On the Mac's
GPU a worker renders at most :data:`MPS_CHUNKS_PER_WORKER` chunks (the P4B memory checkpoint); the processor keeps 48.
However a worker ends -- ``done``, Cancel, a crash -- it is never reaped before its whole group has been ended (v0.8.x
P5-D): what it left in its group ends with it, output held open by such a leftover no longer keeps the run waiting, and
a group that cannot be confirmed ended makes the file a failure, never a success or a clean Cancel.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import queue
import shutil
import subprocess
import sys
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
from tts.omnivoice_worker import speakable  # the worker's own rule (stdlib only; no model stack is imported)
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
#: Windows (CUDA) and a Mac's processor, as released.
CHUNKS_PER_WORKER = 48
#: The bound on a Mac's GPU (MPS; macOS P4B memory checkpoint, 2026-11-16; owner accepted with its memory exception).
#: There a worker's footprint grows with every chunk of a new shape while its live tensors stay flat, and only the
#: process's end gives the memory back. ``torch.mps.empty_cache()`` does not stop the growth (P4B option B): it frees
#: one chunk's working space, which the next chunk takes back, while the GPU memory outside PyTorch's free pool and the
#: CPU heap keep growing. Per-shape MPSGraph resources (executables compiled for each new chunk shape) are the likely
#: cause; that is inferred, not proven. On long, all-different chunks one worker passed 13 GB after 48 (about 120 MiB a
#: chunk), so a fresh worker starts three times as often. The audio is bit-identical; each extra worker costs about
#: 4 s. No cache clearing is done.
MPS_CHUNKS_PER_WORKER = 16
#: Bump deliberately whenever a change can alter generated audio (planning, seeding, generation, assembly).
PIPELINE_REVISION = 1
SEED_BASE = 20261113
#: v0.8.2: the most renderings a chunk with words gets while each comes back empty -- its own seed, then the further
#: seeds :func:`rendering_seeds` derives. On the real engine a cut-off word in a thought (``'Wh...'``, the Shadow Slave
#: failures) came back empty on 26 seeds in 40; 24 renderings leave that about a 3-in-100,000 chance, and a chunk that
#: stays silent on every one costs about 16 s before its file fails as before. A chunk that speaks at once is rendered
#: exactly as it always was (so PIPELINE_REVISION is unchanged: every file that could be made before is identical).
SPEECH_RENDERINGS = 24

LANGUAGE = "English"
#: Windows' device and dtype, as released. Every run asks ``omnivoice_runtime.device_policy`` (these on Windows; the
#: Mac's accepted configuration on a Mac).
DTYPE = ov.WINDOWS_DTYPE
DEVICE = ov.WINDOWS_DEVICE
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
#: POSIX (v0.8.x P5-D): once a worker's process group has been ended, every writer in it is gone, so what it wrote
#: reaches its end at once; output that stays silent this long without ending is held open by something outside that
#: group, and the worker cannot be vouched for.
OUTPUT_DRAIN_S = 2.0
STALE_JOB_AGE_S = 24 * 3600.0
STDERR_TAIL_CHARS = 1500
#: v0.8.1 C1: every failure's technical record, one JSON line each, beside ``last-failure.txt`` (which keeps only the
#: last). Past this size the file is moved to ``failures.previous.jsonl`` (replacing an older one) and begun again.
FAILURE_HISTORY = "failures.jsonl"
FAILURE_HISTORY_PREVIOUS = "failures.previous.jsonl"
FAILURE_HISTORY_CAP_BYTES = 1 << 20


class OmniVoiceFailed(RuntimeError):
    """The worker ran but this file could not be produced. The message is fit to show a user; *details*, when given,
    is the technical record :func:`record_failure` keeps (never the text being narrated)."""

    def __init__(self, message: str, *, details: Optional[dict] = None) -> None:
        super().__init__(message)
        self.details = details


# --------------------------------------------------------------------------- #
# Planning and the job
# --------------------------------------------------------------------------- #
def plan_chunks(text: str) -> list[_local.Chunk]:
    """Whole-sentence chunks of the prepared text, each with its exact span, verified (the shared local planner)."""
    return _local.plan_chunks(text, OMNIVOICE_MAX_CHUNK_CHARS)


def derive_seed(voice_id: str, chunk: _local.Chunk, attempt: int = 0) -> int:
    """Stable per-chunk seed: the same voice, position and words always give the same seed, so a retry renders the same
    text the same way. *attempt* > 0 (v0.8.2) is the seed of that further rendering of a chunk whose earlier ones came
    back empty; attempt 0 is the seed every chunk has always had."""
    text_hash = hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
    key = f"{SEED_BASE}|{voice_id}|{chunk.index}|{text_hash}" + (f"|rendering {attempt + 1}" if attempt else "")
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF


def rendering_seeds(voice_id: str, chunk: _local.Chunk) -> list[int]:
    """Every seed *chunk* may be rendered with, in order (v0.8.2): :data:`SPEECH_RENDERINGS` for a chunk with words,
    only its own for a chunk with nothing to say (whose empty rendering is a pause, v0.8.1 C1)."""
    count = SPEECH_RENDERINGS if speakable(chunk.text) else 1
    return [derive_seed(voice_id, chunk, attempt) for attempt in range(count)]


def chunks_per_worker_for(policy: ov.DevicePolicy) -> int:
    """How many chunks one worker renders for a run on *policy*'s device: 16 on a Mac's GPU, 48 everywhere else
    (Windows' CUDA and a Mac's processor exactly as released)."""
    return MPS_CHUNKS_PER_WORKER if policy.device == ov.DEVICE_MPS else CHUNKS_PER_WORKER


def batches(chunks: list, size: int = CHUNKS_PER_WORKER) -> list[list]:
    if size < 1:
        raise ValueError("a worker renders at least one chunk")
    return [chunks[i:i + size] for i in range(0, len(chunks), size)]


def build_job(voice: ov.OmniVoiceVoice, spec: ov.ReferenceSpec, chunks: list, *, job_dir: Path, reference: dict,
              model_dir: Path, omnivoice_version: str, prompt_cache: Optional[dict],
              policy: Optional[ov.DevicePolicy] = None) -> dict:
    """Everything one worker needs, as plain data. Pure: touches no disk.

    *reference* is :func:`omnivoice_runtime.verify_reference`'s answer: the voice's own recording, its SHA-256, frame
    count, rate and the most frames it may have. The worker proves the file again before it uses it. *policy* is the
    run's device and dtype (:func:`omnivoice_runtime.device_policy` when not given).
    """
    policy = ov.device_policy() if policy is None else policy
    return {
        "schema": 1, "kind": "synth", "voice_id": voice.voice_id, "model_dir": str(model_dir),
        "omnivoice_version": omnivoice_version, "language": LANGUAGE, "dtype": policy.dtype, "device": policy.device,
        "out_dir": str(job_dir / "chunks"), "cancel_file": str(job_dir / "cancel"),
        "engine_lock": str(ov.engine_lock_path()),
        "reference": {key: reference[key] for key in ("wav", "wav_sha256", "frames", "sample_rate", "max_frames")},
        "ref_text": spec.text, "prompt_cache": prompt_cache, "generation": dict(GENERATION),
        "chunks": [_job_chunk(voice.voice_id, c) for c in chunks],
    }


def _job_chunk(voice_id: str, chunk: _local.Chunk) -> dict:
    seed, *further = rendering_seeds(voice_id, chunk)
    return {"index": chunk.index, "text": chunk.text, "seed": seed, "retry_seeds": further}


def prompt_cache_entry(spec: ov.ReferenceSpec, *, model_revision: str, omnivoice_version: str,
                       prompts_root: Optional[Path] = None, policy: Optional[ov.DevicePolicy] = None) -> dict:
    """Where the voice's reusable clone prompt is filed, under an identity that binds its dtype and (off CUDA) its
    device, so a prompt made on one device is never reused on another."""
    policy = ov.device_policy() if policy is None else policy
    key, identity = ov.prompt_identity(spec, model_revision=model_revision, omnivoice_version=omnivoice_version,
                                       preprocess_prompt=GENERATION["preprocess_prompt"], dtype=policy.dtype,
                                       device=policy.device)
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


_PRIVATE_OWNER = None


def _private_owner():
    """This process's own containment owner, for a run started where the app window's is not (a command-line tool):
    the worker is still a class-A child tied to a lifeline, so it ends with this process however it ends."""
    global _PRIVATE_OWNER
    if _PRIVATE_OWNER is None:
        from shared import child_ownership

        _PRIVATE_OWNER = child_ownership.Owner()
    return _PRIVATE_OWNER


def spawn_worker(cmd: list, **kwargs) -> subprocess.Popen:
    """Start one worker so that its whole tree can always be stopped. Windows: a Job Object, as released
    (``qwen3_process.spawn`` with ``require_job``). A Mac: a class-A child of the app window's containment owner
    (``qwen3_process.spawn`` finds it), or of this process's own when there is none -- never a worker without a
    lifeline."""
    if sys.platform != "win32" and qwen3_process._posix_owner(cmd) is None:
        owner = _private_owner()
        try:
            proc = owner.popen_python([str(part) for part in cmd], label="omnivoice-worker", **kwargs)  # incl. run
        except RuntimeError as exc:  # child_ownership.ContainmentUnavailable: nothing was started
            raise qwen3_process.ContainmentUnavailable(str(exc)) from exc
        proc.act_job = None  # type: ignore[attr-defined]
        proc.act_start_time = qwen3_process.leader_start_time(proc, owner)  # type: ignore[attr-defined]
        proc.act_owner = owner  # type: ignore[attr-defined]  # qwen3_process.hand_over gives it back to this owner
        return proc
    return qwen3_process.spawn(cmd, require_job=True, **kwargs)


def _running_on(event: dict) -> str:
    """The log's words for where a worker said it loaded (CUDA wording as released)."""
    device = str(event.get("device") or "")
    name = event.get("device_name") or "unknown device"
    if device == "mps":
        return f"OmniVoice is running on the Mac's GPU: {name}, float32"
    if device == "cpu":
        return f"OmniVoice is running on the processor: {name}, float32"
    return f"OmniVoice is running on the GPU: {name}"


def _settle_led_worker(proc: subprocess.Popen, reader: threading.Thread,
                       kill: Callable[[subprocess.Popen], None], *, output_open: bool,
                       must_stop: Optional[Callable[[], bool]] = None) -> Optional[str]:
    """POSIX (v0.8.x P5-D): end a finished worker run in the only safe order -- its group ended while its id is proved
    its own (``qwen3_process.end_group``), its output handed on to its end (bounded), and only then is it reaped -- and
    say why it cannot be vouched for, or None when its group was confirmed ended, its output ended and it was reaped.

    A worker still running here (its output ended or the run was left early) gets the released 10 s to exit, observed
    without reaping it, and is then ended with its whole group (*kill*). Never raises."""
    if proc.returncode is None and not qwen3_process.leader_exited(proc):
        qwen3_process.await_leader_exit(proc, kill, must_stop)  # Cancel is still acted on here (finding 10)
    qwen3_process.end_group(proc)  # whatever it left in its group ends now, before it is reaped
    reader.join(timeout=0.0 if output_open else OUTPUT_DRAIN_S)
    output_open = reader.is_alive()
    if qwen3_process.group_confirmed_ended(proc):
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
    else:  # v0.8.x P5-I-R3 remediation 2: never reaped with its group not confirmed ended; the owner keeps ending it
        qwen3_process.hand_over(proc)
    if not output_open and proc.stdout is not None:  # never closed under a reader still blocked on it
        proc.stdout.close()
    return qwen3_process.containment_problem(proc, output_open=output_open)


def run_worker(job: dict, job_dir: Path, *, name: str, python: Path, script: Path, env: dict,
               cancel_check: Optional[Callable[[], bool]] = None, log: Callable[[str], None] = print,
               on_chunk: Optional[Callable[[dict], None]] = None, grace_s: float = CANCEL_GRACE_S,
               event_timeout_s: float = EVENT_TIMEOUT_S, exit_grace_s: float = EXIT_GRACE_S,
               kill_wait_s: float = KILL_WAIT_S,
               kill: Callable[[subprocess.Popen], None] = qwen3_process.kill_tree,
               spawn: Optional[Callable[..., subprocess.Popen]] = None) -> WorkerRun:
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
            proc = (spawn or spawn_worker)(
                [str(python), "-I", str(script), str(job_path)], stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=stderr_file, text=True, encoding="utf-8", errors="replace", env=env,
                cwd=str(job_dir), **({"run": cancel_check} if spawn is None and cancel_check is not None else {}))
            if qwen3_process.identity_unrecorded(proc):
                # v0.8.x P5-D-R1 (POSIX): a worker whose identity could not be recorded at spawn is never admitted --
                # neither ended by a guess at its group nor supervised the released way, which reaps it first and can
                # report success or a clean Cancel with nothing vouching for what it left behind.
                qwen3_process.end_unadmitted(proc)
                raise qwen3_process.ContainmentUnavailable(
                    "its identity could not be recorded when it started, so it was stopped before it could run")
        except qwen3_process.ContainmentUnavailable as exc:
            who = "Windows would not let this app" if sys.platform == "win32" else "the app could not"
            raise OmniVoiceFailed(f"The OmniVoice voice engine was not started: {who} keep control of it, so it could "
                                  f"not be stopped safely if you cancelled. ({exc})") from exc

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
        last_progress = last_output = time.monotonic()
        # v0.8.x P5-D (POSIX): a worker that leads its own group, with its identity recorded at spawn. Its exit -- seen
        # without reaping it -- ends the wait as much as the end of its output does: something it left in its group can
        # hold that output open for as long as it runs. Its group is ended before it is ever reaped, and a group that
        # cannot be proved or confirmed ended, or output held open past it, makes the run a failure, never a success
        # or a clean Cancel.
        led = qwen3_process.leads_proved_group(proc)
        group_ended_at: Optional[float] = None
        output_open = raising = False
        containment: Optional[str] = None
        controller = getattr(cancel_check, "__self__", None)

        def must_stop() -> bool:
            # The finishing worker's Cancel (v0.8.x P5-I-R3 remediation 3, finding 10): noticed, flagged, and its grace
            # counted from the click when the run's controller recorded one.
            nonlocal cancel_requested_at
            if cancel_requested_at is None and cancel_check is not None and cancel_check():
                cancel_requested_at = time.monotonic()
                with contextlib.suppress(OSError):
                    cancel_flag.write_text("cancel", encoding="utf-8")
            if cancel_requested_at is None:
                return False
            began = getattr(controller, "cancel_clicked_at", None)
            return time.monotonic() - (began if isinstance(began, (int, float)) else cancel_requested_at) > grace_s

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
                if group_ended_at is not None and now - max(group_ended_at, last_output) > OUTPUT_DRAIN_S:
                    output_open = True  # every writer in its group is gone, yet its output has not ended
                    break
                try:
                    line = lines.get(timeout=0.2)
                except queue.Empty:
                    line = ""
                    if led and group_ended_at is None and (killed_at is not None or qwen3_process.leader_exited(proc)):
                        qwen3_process.end_group(proc)  # never reaps; what it wrote is still handed on below
                        group_ended_at = time.monotonic()
                if line is None:
                    break
                if line:
                    last_output = time.monotonic()
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
                            log(f"{_running_on(event)} (model {event.get('load_s')} s, clone prompt "
                                f"{event.get('prompt')} in {event.get('prompt_s')} s).")
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
            raising = True
            kill(proc)
            raise
        finally:
            if led:
                containment = _settle_led_worker(proc, reader, kill, output_open=output_open, must_stop=must_stop)
                if containment is not None and raising:  # the file is failing already: say why it was not vouched for
                    log(f"  [omnivoice] the worker could not be confirmed stopped: {containment}")
            else:
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
    if containment is not None:
        log(f"  [omnivoice] the worker could not be confirmed stopped: {containment}")
        with contextlib.suppress(Exception):  # v0.8.x P5-I-R3: no run settles clean while it may still run
            from shared import subprocess_utils

            subprocess_utils.note_unresolved(proc.pid, getattr(proc, "act_start_time", None), "OmniVoice worker")
        if cancel_requested_at is not None:
            raise OmniVoiceFailed(f"The OmniVoice voice engine was asked to stop, but it could not be confirmed stopped: "
                                  f"{containment}.")
        raise OmniVoiceFailed(f"The OmniVoice voice engine could not be confirmed stopped, so its audio was discarded: "
                              f"{containment}.")
    if cancel_requested_at is not None:
        raise ConversionCancelled("Conversion cancelled by user.")
    if terminal is None:
        raise OmniVoiceFailed(f"The OmniVoice voice engine ended unexpectedly (exit code {returncode})."
                              f"{_detail(_tail(stderr_path))}")
    if terminal["event"] == "done" and returncode != 0:
        raise OmniVoiceFailed("The OmniVoice voice engine reported success but then did not exit cleanly "
                              f"(exit code {returncode}), so its audio was discarded.{_detail(_tail(stderr_path))}")
    return WorkerRun(terminal=terminal, chunk_events=chunk_events, loaded=loaded, returncode=returncode)


#: Said once a damaged engine has been recorded as such (``ov.reject_ready_engine``): the repair is now really offered.
REPAIR_OFFERED_NOTE = (" The engine's installed files are damaged. Start the conversion again and choose Install & "
                       "Continue: the app builds and checks a fresh one (an environment it did not make is moved aside, never "
                       "deleted).")


def failure_message(terminal: dict, *, repair_offered: bool = False) -> str:
    """A user-fit sentence for a worker ``failed`` event. *repair_offered*: the engine was just recorded as damaged, so
    the next Create offers its repair -- said in place of the general hint."""
    stage = terminal.get("stage")
    detail = str(terminal.get("message") or "no further detail")
    if stage in ("engine", "job"):
        return detail if stage == "engine" else f"The OmniVoice voice engine refused the job: {detail}"
    mac = ov._system() == "darwin"
    if terminal.get("oom"):
        if mac:
            return ("The OmniVoice voice ran out of memory (on a Mac the GPU shares the computer's memory). Close other "
                    f"programs and try again. ({detail})")
        return ("The OmniVoice voice ran out of GPU memory. Close other programs that use the graphics card and try "
                f"again. ({detail})")
    if terminal.get("gpu") is False:
        return ov.MPS_UNAVAILABLE_MESSAGE if mac else ov.NO_GPU_MESSAGE
    if stage == "memory":
        who = "this Mac" if mac else "Windows"
        return (f"The OmniVoice voice engine could not start because {who} did not have enough memory to load it. "
                f"Close other programs and try again; the engine itself is unchanged. ({detail})")
    where = {"load": "loading the model and the voice", "generate": "generating speech",
             "import": "starting the voice engine", "network": "starting (it tried to use the network)",
             "worker": "running"}.get(stage, "running")
    message = f"The OmniVoice voice engine failed while {where}: {detail}"
    if repair_offered:
        message += REPAIR_OFFERED_NOTE
    elif (stage == "import" or detail.startswith(("ImportError", "ModuleNotFoundError"))) \
            and ov.APPLICATION_CONTROL_MARK not in detail:  # Smart App Control's refusal is not damage
        message += " The engine's installed packages look damaged; repair it from the optional voice setup."
    return message


#: The worker's memory figures a ``failed`` event may carry (CUDA as released; a Mac's footprint and MPS figures).
_MEMORY_KEYS = ("vram_allocated_mib", "vram_reserved_mib", "peak_allocated_mib", "peak_reserved_mib", "footprint_mib",
                "peak_footprint_mib", "mps_allocated_mib", "mps_driver_mib")


def failed_chunk(terminal: dict, group: list) -> Optional[_local.Chunk]:
    """The chunk of *group* a ``failed`` event names by its ``index``, or ``None`` (a failure outside the chunk loop)."""
    index = terminal.get("index")
    if type(index) is not int:
        return None
    return next((c for c in group if c.index == index), None)


def failure_location(chunk: _local.Chunk, total: int, batch: int, batches: int) -> str:
    """Where a chunk failure happened, for the message a person sees and the session log keeps (v0.8.1 C1)."""
    return f" (chunk {chunk.index + 1} of {total}, worker batch {batch} of {batches})"


def failure_details(terminal: dict, chunk: Optional[_local.Chunk], *, source: Path, voice_id: str, total: int,
                    batch: int, batches: int, group_size: int, completed: int, loaded: dict,
                    policy: ov.DevicePolicy, model_revision: str, omnivoice_version: str) -> dict:
    """The technical record of one failed worker run (v0.8.1 C1). Pure apart from hashing *source*.

    It identifies the source by name and SHA-256 and the chunk by its global index, worker batch and place in it, its
    prepared length, SHA-256 and seed -- never by its words -- and keeps the worker's own stage, exception, traceback,
    timing and memory, the device it ran on and the exact engine, model and generation settings."""
    try:
        source_sha256: Optional[str] = hashlib.sha256(source.read_bytes()).hexdigest()
    except OSError:
        source_sha256 = None
    record: dict = {
        "recorded": time.strftime("%Y-%m-%d %H:%M:%S"), "source": {"name": source.name, "sha256": source_sha256},
        "voice_id": voice_id, "stage": terminal.get("stage"), "message": terminal.get("message"),
        "oom": terminal.get("oom"), "trace": terminal.get("trace"), "chunks": total, "batch": batch,
        "batches": batches, "batch_size": group_size, "completed_before": completed,
        "gpu": {key: terminal[key] for key in _MEMORY_KEYS if key in terminal},
        "device": {key: loaded.get(key) for key in ("device", "device_name", "total_mib", "load_s", "prompt",
                                                    "vram_allocated_mib", "vram_reserved_mib") if key in loaded},
        "versions": loaded.get("versions"),
        "engine": {"omnivoice": omnivoice_version, "model_revision": model_revision, "dtype": policy.dtype,
                   "device": policy.device, "language": LANGUAGE, "generation": dict(GENERATION),
                   "pipeline_revision": PIPELINE_REVISION, "max_chunk_chars": OMNIVOICE_MAX_CHUNK_CHARS},
    }
    if chunk is not None:
        record["chunk"] = {"index": chunk.index, "number": chunk.index + 1, "position": terminal.get("position"),
                           "chars": len(chunk.text), "sha256": hashlib.sha256(chunk.text.encode("utf-8")).hexdigest(),
                           "seed": derive_seed(voice_id, chunk), "boundary": chunk.boundary,
                           "gen_s": terminal.get("gen_s"), "audio_shape": terminal.get("audio_shape")}
        if "renderings" in terminal:  # v0.8.2: how many seeds were tried before the chunk failed for good
            record["chunk"]["renderings"] = terminal["renderings"]
    return record


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


def record_failure(job_dir: Path, message: str, runtime: Optional[Path] = None,
                   details: Optional[dict] = None) -> None:
    """Keep the last failure's worker stderr for diagnosis (no job text beyond what a traceback quotes) and, when there
    is one, its technical record (:func:`failure_details`): in ``last-failure.txt`` and as one more line of the bounded
    :data:`FAILURE_HISTORY`, so each failure of a long run can still be found after later ones."""
    try:
        target = (ov.runtime_dir() if runtime is None else Path(runtime)) / "last-failure.txt"
        stderr = "\n".join(_tail(p, 6000) for p in sorted(job_dir.glob("*-stderr.txt")))
        target.parent.mkdir(parents=True, exist_ok=True)
        record = f"\n{json.dumps(details, indent=1, sort_keys=True, default=str)}\n" if details else ""
        target.write_text(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\n{message}\n{record}\n{stderr}\n", encoding="utf-8")
        if details:
            history = target.with_name(FAILURE_HISTORY)
            if history.is_file() and history.stat().st_size > FAILURE_HISTORY_CAP_BYTES:
                os.replace(history, target.with_name(FAILURE_HISTORY_PREVIOUS))
            with open(history, "a", encoding="utf-8") as handle:
                handle.write(json.dumps({**details, "shown": message}, sort_keys=True, default=str) + "\n")
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
    chunks_per_worker: Optional[int] = None,
    grace_s: float = CANCEL_GRACE_S,
    event_timeout_s: float = EVENT_TIMEOUT_S,
    exit_grace_s: float = EXIT_GRACE_S,
    kill_wait_s: float = KILL_WAIT_S,
) -> None:
    """Read plain text from a file -> OmniVoice workers -> one MP3. The same shape as ``qwen3_file_to_mp3``.

    ``progress_callback(done, total)`` fires after each chunk on the calling (worker) thread. Cancellation raises
    ``ConversionCancelled`` and is honoured at every stage up to the instant the file is published; no partial MP3 is
    left and an existing destination is not touched until the new file is complete. No closing pause (v0.7.0 Q1):
    ``end_silence_ms`` is accepted for callers and ignored. The keyword-only seams exist for the offline tests;
    ``chunks_per_worker`` left at None is the run's device's own bound (:func:`chunks_per_worker_for`).
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
        policy = ov.device_policy()  # once per file: every batch and the prompt's identity use exactly this
        cache = prompt_cache_entry(spec, model_revision=model_revision, omnivoice_version=version,
                                   prompts_root=prompts_root, policy=policy)
        py = Path(python) if python is not None else ov.venv_python()
        worker = Path(script) if script is not None else ov.worker_script()
        cleanup_stale_jobs(jobs_root)
        job_dir = new_job_dir(jobs_root)
        try:
            log(f"OmniVoice: synthesizing {len(chunks)} chunk(s) in {voice.label} (pipeline revision "
                f"{PIPELINE_REVISION}; reference {spec.duration_s:.3f} s at {spec.sample_rate} Hz, used whole; "
                f"{GENERATION['num_step']} steps)...")
            if policy.device != ov.DEVICE_CUDA:  # a Mac: say where it runs and who chose it (Windows' log unchanged)
                chosen = "the default" if policy.source == "default" else f"chosen in {policy.source}"
                log(f"OmniVoice device: {policy.label} ({chosen}).")
            env = ov.worker_environment() if env is None else env
            events: list[dict] = []
            bound = chunks_per_worker_for(policy) if chunks_per_worker is None else chunks_per_worker
            groups = batches(chunks, bound)
            for number, group in enumerate(groups, start=1):
                _local._raise_if_cancelled(cancel_check)

                def chunk_done(event: dict) -> None:
                    events.append(event)
                    log(f"  OmniVoice chunk {int(event.get('index', 0)) + 1}/{len(chunks)} ({event.get('audio_s')} s "
                        f"of audio in {event.get('gen_s')} s)"
                        + (" -- no words to speak and its rendering was silent, so it is a pause" if event.get("silent")
                           else "")
                        + (f" -- rendered {event['renderings']} times: the earlier renderings came back silent"
                           if type(event.get("renderings")) is int and event["renderings"] > 1 else ""))
                    if progress_callback is not None:
                        progress_callback(len(events), len(chunks))

                job = build_job(voice, spec, group, job_dir=job_dir, reference=reference, model_dir=ov.model_dir(),
                                omnivoice_version=version, prompt_cache=cache, policy=policy)
                run = run_worker(job, job_dir, name=f"job-{number:03d}", python=py, script=worker, env=env,
                                 cancel_check=cancel_check, log=log, on_chunk=chunk_done, grace_s=grace_s,
                                 event_timeout_s=event_timeout_s, exit_grace_s=exit_grace_s, kill_wait_s=kill_wait_s)
                if run.terminal["event"] == "canceled":
                    raise ConversionCancelled("Conversion cancelled by user.")
                if run.terminal["event"] == "failed":
                    # A failure that only a rebuild can mend is recorded, so the engine stops being called ready and
                    # the repair is offered (this conversion holds inference.lock: no installer is changing it).
                    damaged = (ov.failure_needs_rebuild(run.terminal)
                               and ov.reject_ready_engine(str(run.terminal.get("message") or run.terminal.get("stage"))))
                    failing = failed_chunk(run.terminal, group)
                    where = "" if failing is None else failure_location(failing, len(chunks), number, len(groups))
                    details = failure_details(run.terminal, failing, source=src, voice_id=voice_id, total=len(chunks),
                                              batch=number, batches=len(groups), group_size=len(group),
                                              completed=len(events), loaded=run.loaded, policy=policy,
                                              model_revision=model_revision, omnivoice_version=version)
                    raise OmniVoiceFailed(failure_message(run.terminal, repair_offered=damaged) + where,
                                          details=details)
                if sorted(int(e["index"]) for e in run.chunk_events) != [c.index for c in group]:
                    raise OmniVoiceFailed(f"The OmniVoice voice engine rendered other chunks than it was given "
                                          f"(batch {number} of {len(groups)}).")
                worded_pauses = sorted({int(e["index"]) for e in run.chunk_events if e.get("silent")}
                                       & {c.index for c in group if speakable(c.text)})
                if worded_pauses:  # v0.8.1 C1: only a chunk with nothing to say may become a pause; words never vanish
                    raise OmniVoiceFailed(f"The OmniVoice voice engine returned silence for chunk "
                                          f"{worded_pauses[0] + 1} of {len(chunks)}, which has words to speak, so its "
                                          f"audio was discarded (worker batch {number} of {len(groups)}).")
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
            record_failure(job_dir, str(exc), None if jobs_root is None else Path(jobs_root), details=exc.details)
            raise
        finally:
            remove_job_dir(job_dir)
