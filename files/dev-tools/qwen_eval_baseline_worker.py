"""Chatterbox / Kokoro baseline worker for the Plan 01 evaluation (dev-only).

Runs under the repository's ROOT interpreter (``.venv``), one engine per subprocess, calling the
real production file paths unchanged:

* Chatterbox: ``chatterbox_file_to_mp3`` (300-character chunks, temperature 0.72, retry policy).
* Kokoro:     ``kokoro_file_to_mp3`` with the exact voice id and ``speed=1.0``.

The only addition is a harness-only wrapper around each engine's ``_export_mp3`` PCM seam: it keeps
the exact array handed to the encoder (native-rate WAV evidence), then calls the original exporter
unchanged for the MP3. The wrapper lives inside a context manager and is restored even on failure;
production source is never patched on disk.

    python qwen_eval_baseline_worker.py <job.json>

Nothing here registers a voice, changes a default or downloads a model: the orchestrator starts this
process with Hugging Face offline mode on, so a missing asset fails its own row.
"""
from __future__ import annotations

import contextlib
import json
import platform
import sys
import time
import traceback
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qwen_eval_core as core  # noqa: E402

UNIVERSAL = core.REPO_ROOT / "scripts" / "Universal"
if str(UNIVERSAL) not in sys.path:
    sys.path.insert(0, str(UNIVERSAL))

SKIP_MARKERS = ("produced no audio, skipping", "pathological internal silence", "unusable")


class PcmCapture:
    """Keep the PCM an engine hands to its MP3 exporter, then export exactly as before."""

    def __init__(self, module):
        self.module = module
        self.original = None
        self.arrays: list[tuple[np.ndarray, int]] = []

    def __enter__(self):
        self.original = self.module._export_mp3

        def wrapper(arr, sample_rate, output_path, bitrate=None):
            self.arrays.append((np.array(arr, dtype="float32", copy=True), int(sample_rate)))
            return self.original(arr, sample_rate, output_path, bitrate)

        self.module._export_mp3 = wrapper
        return self

    def __exit__(self, *exc):
        self.module._export_mp3 = self.original
        return False


def _cancel_check(job: dict):
    """True once the orchestrator has created the job's cancel file (checked between chunks and rows)."""
    flag = job.get("cancel_file")
    return lambda: bool(flag) and Path(flag).exists()


def _snapshot_identity(repo_id: str) -> dict:
    """Revision and file list of the locally cached snapshot, read without any network call."""
    import os

    hub = Path(os.environ.get("HF_HOME", "")) / "hub" / ("models--" + repo_id.replace("/", "--"))
    ref = hub / "refs" / "main"
    return {"repo": repo_id, "revision": ref.read_text(encoding="utf-8").strip() if ref.is_file() else None,
            "cache": hub.relative_to(core.REPO_ROOT).as_posix() if hub.is_relative_to(core.REPO_ROOT) else None}


def _write_outputs(row: dict, run_dir: Path, pcm: np.ndarray, rate: int, mp3_path: Path) -> dict:
    wav = core.write_wav(run_dir / row["out_dir"] / (row["stem"] + ".wav"), pcm, rate, base=run_dir)
    mp3 = {"path": mp3_path.relative_to(run_dir).as_posix(), "bytes": mp3_path.stat().st_size,
           "sha256": core.sha256_file(mp3_path)}
    return {"wav": wav, "mp3": mp3}


def run_chatterbox(job: dict) -> int:
    from tts import chatterbox_synth as cs

    run_dir, text_file = Path(job["run_dir"]), Path(job["text_file"])
    text = text_file.read_text(encoding="utf-8")
    expected_chunks = len(cs.split_for_chatterbox(text))
    device = cs.select_device()
    import importlib.metadata as md

    import torch

    core.emit({"event": "engine", "engine": "chatterbox", "device": device, "package": cs.PACKAGE_REQUIREMENT,
               "torch": torch.__version__, "chatterbox_tts": md.version("chatterbox-tts"),
               "python": platform.python_version(),
               "model": _snapshot_identity(cs.MODEL_REPO_ID), "temperature": cs.GENERATION_TEMPERATURE,
               "max_chunk_chars": cs.CHATTERBOX_MAX_CHUNK_CHARS, "expected_chunks": expected_chunks,
               "generation_params": cs.generation_params()})
    cancel = _cancel_check(job)
    for row in job["rows"]:
        if cancel():
            break
        if _run_one(row, run_dir, text_file, cs, expected_chunks,
                    lambda log, mp3, cs=cs, row=row: cs.chatterbox_file_to_mp3(
                        str(text_file), str(mp3), voice_id=row["voice_id"], log=log, cancel_check=cancel),
                    chunk_wrapper=True):
            return 130
    core.emit({"event": "worker_done"})
    return 0


def run_kokoro(job: dict) -> int:
    from tts import kokoro_synth as ks

    run_dir, text_file = Path(job["run_dir"]), Path(job["text_file"])
    text = text_file.read_text(encoding="utf-8")
    expected_chunks = len(ks.split_into_chunks(text))
    import torch

    import importlib.metadata as md

    core.emit({"event": "engine", "engine": "kokoro", "device": "cuda" if torch.cuda.is_available() else "cpu",
               "torch": torch.__version__, "kokoro": md.version("kokoro"), "misaki": md.version("misaki"),
               "python": platform.python_version(), "model": _snapshot_identity("hexgrad/Kokoro-82M"),
               "expected_chunks": expected_chunks, "speed": 1.0})
    cancel = _cancel_check(job)
    for row in job["rows"]:
        if cancel():
            break
        voice_id = row["voice_id"]
        lang = ks._lang_code_for_voice(voice_id)
        if lang != row["lang_code"]:
            core.emit({"event": "row_failed", "row_id": row["row_id"],
                       "reason": f"language routing {lang!r} differs from the expected {row['lang_code']!r}"})
            continue
        asset = _kokoro_voice_asset(voice_id)
        if asset is None:
            core.emit({"event": "row_failed", "row_id": row["row_id"],
                       "reason": f"official voice asset voices/{voice_id}.pt is not in the local cache "
                                 "(run the prepare stage; offline mode forbids an implicit download)"})
            continue
        row["asset"] = asset
        if _run_one(row, run_dir, text_file, ks, expected_chunks,
                    lambda log, mp3, ks=ks, row=row: ks.kokoro_file_to_mp3(
                        str(text_file), str(mp3), voice_id=row["voice_id"], speed=1.0, log=log, cancel_check=cancel),
                    chunk_wrapper=False):
            return 130
    core.emit({"event": "worker_done"})
    return 0


def _kokoro_voice_asset(voice_id: str) -> dict | None:
    """The exact file Kokoro's own loader will open: ``hf_hub_download`` resolves ``refs/main`` of the local
    cache (offline), so the recorded hash is of the voice that is synthesised, never of an older snapshot."""
    from huggingface_hub import hf_hub_download

    try:
        path = Path(hf_hub_download(repo_id="hexgrad/Kokoro-82M", filename=f"voices/{voice_id}.pt",
                                    local_files_only=True))
    except Exception:  # noqa: BLE001 - absent asset is reported by the caller as a blocked row
        return None
    return {"snapshot": path.parent.parent.name, "bytes": path.stat().st_size, "sha256": core.sha256_file(path)}


def _inserted_silence_s(fn, expected_chunks: int) -> float:
    """Silence the engine adds itself (a pause after every chunk plus the end pause), read from its own
    signature defaults rather than copied, so the audible-content estimate cannot drift from the engine."""
    import inspect

    params = inspect.signature(fn).parameters
    return params["chunk_pause_ms"].default * expected_chunks / 1000.0 + params["end_silence_ms"].default / 1000.0


def _run_one(row: dict, run_dir: Path, text_file: Path, module, expected_chunks: int, call, chunk_wrapper: bool) -> bool:
    """Run one voice through the production file path. Returns True when the run was canceled."""
    from shared.cancellation import ConversionCancelled

    row_id = row["row_id"]
    log_lines: list[str] = []
    chunk_info: list[dict] = []
    core.emit({"event": "row_start", "row_id": row_id, "chunks": expected_chunks})
    mp3_path = run_dir / row["out_dir"] / (row["stem"] + ".mp3")
    mp3_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()

    def log(message: str) -> None:
        log_lines.append(str(message))
        core.emit({"event": "log", "row_id": row_id, "line": str(message)[:300]})

    original_chunk = getattr(module, "_synthesize_chunk", None) if chunk_wrapper else None
    original_generate = getattr(module, "_generate_checked", None) if chunk_wrapper else None
    segments: list[dict] = []
    outputs = None
    if chunk_wrapper and not (callable(original_chunk) and callable(original_generate)):
        # Fail closed: without both hooks a silently dropped segment could not be seen at all.
        core.emit({"event": "row_failed", "row_id": row_id,
                   "reason": "the harness instrumentation contract changed: production no longer exposes "
                             "_synthesize_chunk and _generate_checked, so omissions cannot be detected"})
        return False
    try:
        with PcmCapture(module) as capture:
            if original_chunk is not None:
                def timed_chunk(model, chunk, cancel_check=None, log=print):
                    t0 = time.perf_counter()
                    arr = original_chunk(model, chunk, cancel_check, log=log)
                    chunk_info.append({"chars": len(chunk), "samples": int(arr.size),
                                       "gen_s": round(time.perf_counter() - t0, 3)})
                    return arr

                def tracked_generate(model, text, log=print):
                    # Production silently drops an empty colon segment of a chunk (no log line); record every
                    # underlying generation so a partial chunk can never pass as complete.
                    arr = original_generate(model, text, log)
                    segments.append({"chars": len(text), "samples": int(arr.size)})
                    return arr

                module._synthesize_chunk = timed_chunk
                module._generate_checked = tracked_generate
            try:
                call(log, mp3_path)
            finally:
                if original_chunk is not None:
                    module._synthesize_chunk = original_chunk
                    module._generate_checked = original_generate
        wall_s = round(time.perf_counter() - started, 2)
        if len(capture.arrays) != 1:
            raise RuntimeError(f"expected exactly one PCM hand-off to the exporter, saw {len(capture.arrays)}")
        pcm, rate = capture.arrays[0]
        skipped = [ln for ln in log_lines if any(m in ln for m in SKIP_MARKERS)]
        empty_segments = [s for s in segments if s["samples"] == 0]
        outputs = _write_outputs(row, run_dir, pcm, rate, mp3_path)
        if skipped and any("no audio, skipping" in ln for ln in skipped):
            core.emit({"event": "row_failed", "row_id": row_id, "outputs": outputs, "diagnostic": True,
                       "reason": f"{sum('no audio, skipping' in ln for ln in skipped)} chunk(s) produced no audio and "
                                 "were skipped; the partial audio is retained for diagnostics only"})
            return False
        if empty_segments:
            core.emit({"event": "row_failed", "row_id": row_id, "outputs": outputs, "diagnostic": True,
                       "reason": f"{len(empty_segments)} generated segment(s) were empty and silently dropped by the "
                                 "engine; the partial audio is retained for diagnostics only"})
            return False
        if chunk_wrapper and (len(chunk_info) != expected_chunks or len(segments) < expected_chunks):
            core.emit({"event": "row_failed", "row_id": row_id, "outputs": outputs, "diagnostic": True,
                       "reason": f"{len(chunk_info)} of {expected_chunks} planned chunks were rendered and "
                                 f"{len(segments)} generations were observed; the audio is retained for diagnostics "
                                 "only (a short count means chunks were lost or the instrumentation missed them)"})
            return False
        retries = [ln.strip() for ln in log_lines if "retrying this segment" in ln]
        measurements = core.measure_samples(pcm, rate)
        file_fn = getattr(module, "chatterbox_file_to_mp3", None) or getattr(module, "kokoro_file_to_mp3")
        audible = round(max(0.0, measurements["duration_s"] - _inserted_silence_s(file_fn, expected_chunks)), 3)
        warnings = [f"engine log: {ln.strip()}" for ln in skipped if "retrying" not in ln]
        extra = {}
        if chunk_info:
            extra["chunk_results"] = chunk_info
            extra["engine_retries"] = retries
        core.emit({"event": "row_done", "row_id": row_id, "outputs": outputs, "measurements": measurements,
                   "warnings": warnings, "wall_s": wall_s, "audible_s": audible,
                   "sample_rate": rate, "expected_chunks": expected_chunks, "asset": row.get("asset"),
                   "log_lines": len(log_lines), "segments_generated": len(segments), **extra})
    except ConversionCancelled:
        core.emit({"event": "row_canceled", "row_id": row_id, "reason": "canceled between chunks",
                   "completed_chunks": len(chunk_info)})
        return True
    except Exception as exc:  # noqa: BLE001 - one voice failing must not end the run
        failure = {"event": "row_failed", "row_id": row_id, "reason": f"{type(exc).__name__}: {exc}",
                   "trace": traceback.format_exc()[-1500:]}
        if outputs is not None:  # already written: keep it tracked so a retry archives it
            failure.update(outputs=outputs, diagnostic=True)
        core.emit(failure)
    return False


def run_kokoro_assets(job: dict) -> int:
    """Fetch only the named official voice files through the same call Kokoro's own loader makes."""
    from huggingface_hub import hf_hub_download

    for voice_id in job["voices"]:
        try:
            # Pinned to the revision of the already-cached model, never to whatever upstream main is today.
            path = Path(hf_hub_download(repo_id=job["repo"], filename=f"voices/{voice_id}.pt",
                                        revision=job["revision"]))
            core.emit({"event": "asset", "voice_id": voice_id, "snapshot": path.parent.parent.name,
                       "bytes": path.stat().st_size, "sha256": core.sha256_file(path)})
        except Exception as exc:  # noqa: BLE001 - reported per voice; the others still run
            core.emit({"event": "asset_failed", "voice_id": voice_id, "error": f"{type(exc).__name__}: {exc}"})
    core.emit({"event": "worker_done"})
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: qwen_eval_baseline_worker.py <job.json>", file=sys.stderr)
        return 64
    job = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    with contextlib.suppress(Exception):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    handler = {"chatterbox": run_chatterbox, "kokoro": run_kokoro,
               "kokoro-assets": run_kokoro_assets}.get(job["engine"])
    if handler is None:
        print(f"unknown engine {job['engine']!r}", file=sys.stderr)
        return 64
    try:
        from shared import ffmpeg_utils

        ffmpeg_utils.configure_pydub()
    except Exception as exc:  # noqa: BLE001 - reported per row by the export step if it matters
        core.emit({"event": "warning", "message": f"ffmpeg configuration: {exc}"})
    return handler(job)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
