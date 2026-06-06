"""
kokoro_synth.py — Local Kokoro TTS synthesis helpers for epub2tts-edge v1.1.

Kokoro-82M model is downloaded automatically (~300 MB) from HuggingFace on
first use. The bootstrap/launcher redirect the HuggingFace cache into the project
tree (``resources/models/huggingface/``); the fallback below covers the standalone
CLI/debug path where neither set ``HF_HOME`` first, so the model still stays in the
project folder rather than ``~/.cache/huggingface/``.
"""

from __future__ import annotations

import os
from pathlib import Path

# Belt-and-suspenders: if no parent process set HF_HOME (e.g. this module is run
# directly for debugging), point the HuggingFace cache at the project tree before
# kokoro is ever imported (the kokoro import is lazy, inside the functions below,
# so this module-load-time setup runs first). Walk up to the OS-root folder that
# contains 'resources/'.
if "HF_HOME" not in os.environ:
    _here = Path(__file__).resolve()
    for _parent in _here.parents:
        if (_parent / "resources").is_dir():
            _hf = _parent / "resources" / "models" / "huggingface"
            os.environ["HF_HOME"] = str(_hf)
            os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(_hf / "hub"))
            break

import tempfile
import time
from typing import Callable

import numpy as np
import soundfile as sf
from pydub import AudioSegment

# Fires the single first-load retry (below) only once per process. The first
# KPipeline load can be transiently blocked while Windows Smart App Control / WDAC
# evaluates Kokoro's unsigned native DLLs; subsequent in-process loads that fail
# are real errors and must not be retried/swallowed.
_first_pipeline_load_attempted = False

_KOKORO_LANG_MAP: dict[str, str] = {
    "af_": "a",
    "am_": "a",
    "bf_": "b",
    "bm_": "b",
}


def _lang_code_for_voice(voice_id: str) -> str:
    """Derive the Kokoro pipeline lang_code from the voice prefix."""
    for prefix, code in _KOKORO_LANG_MAP.items():
        if voice_id.startswith(prefix):
            return code
    return "a"


def _instantiate_pipeline(lang_code: str):
    """Lazy-import kokoro and build a KPipeline (defers loading torch to first use)."""
    from kokoro import KPipeline  # type: ignore

    return KPipeline(lang_code=lang_code)


def _get_pipeline(lang_code: str):
    """Import and instantiate a KPipeline, with a single retry on the first load.

    On a fresh Windows install, the very first attempt to load Kokoro's native
    extensions can fail while Smart App Control / WDAC evaluates the unsigned DLLs
    — surfacing as an ``ImportError`` ("DLL load failed while importing
    sparselinear: An Application Control policy has blocked this file"), or
    occasionally an ``OSError``/``RuntimeError``. The OS typically allows the DLL
    on the immediate retry, so we sleep briefly and try once more. The retry only
    fires on the first load per process (guarded by the module flag); any later
    failure is a real error and propagates immediately.
    """
    global _first_pipeline_load_attempted
    if not _first_pipeline_load_attempted:
        _first_pipeline_load_attempted = True
        try:
            return _instantiate_pipeline(lang_code)
        except (OSError, RuntimeError, ImportError) as exc:
            print(
                "Kokoro pipeline load blocked on first attempt (likely Windows "
                "Application Control evaluating unsigned native DLLs) — retrying in 2s"
            )
            time.sleep(2)
            try:
                return _instantiate_pipeline(lang_code)
            except (OSError, RuntimeError, ImportError) as exc2:
                raise exc2 from exc
    return _instantiate_pipeline(lang_code)


def synthesize_text_to_mp3(
    text: str,
    output_path: str,
    voice_id: str,
    speed: float = 1.0,
    log: Callable[[str], None] = print,
) -> None:
    """Synthesize `text` using Kokoro and save the result as an MP3 file at `output_path`."""
    lang_code = _lang_code_for_voice(voice_id)
    try:
        pipeline = _get_pipeline(lang_code)
    except Exception as e:
        raise RuntimeError(
            f"Could not load Kokoro pipeline. Make sure 'kokoro' is installed "
            f"('pip install kokoro soundfile scipy'). Error: {e}"
        ) from e

    audio_chunks: list[np.ndarray] = []
    generator = pipeline(text, voice=voice_id, speed=speed, split_pattern=r"\n+")
    for _, _, audio in generator:
        if audio is not None:
            arr = audio.numpy() if hasattr(audio, "numpy") else np.array(audio)
            audio_chunks.append(arr)

    if not audio_chunks:
        raise RuntimeError(f"Kokoro produced no audio for voice '{voice_id}'.")

    combined = np.concatenate(audio_chunks)
    sample_rate = 24000

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_wav:
        tmp_wav_path = tmp_wav.name

    try:
        sf.write(tmp_wav_path, combined, sample_rate)
        seg = AudioSegment.from_wav(tmp_wav_path)
        seg.export(output_path, format="mp3")
    finally:
        Path(tmp_wav_path).unlink(missing_ok=True)


def split_into_chunks(text: str, max_chars: int = 3000) -> list[str]:
    """Split on sentence boundaries; falls back on whitespace."""
    if not text.strip():
        return []
    chunks: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if n - i <= max_chars:
            chunk = text[i:].strip()
            if chunk:
                chunks.append(chunk)
            break
        window_end = i + max_chars
        segment = text[i:window_end]
        break_at = None
        for punct in ".!?":
            idx = segment.rfind(punct)
            if idx == -1:
                continue
            after = i + idx + 1
            if after < n and text[after].isspace():
                break_at = after
        if break_at is None:
            break_at = window_end
            while break_at < n and not text[break_at - 1].isspace():
                break_at += 1
                if break_at - i > max_chars + 500:
                    break_at = i + max_chars
                    break
        chunk = text[i:break_at].strip()
        if chunk:
            chunks.append(chunk)
        i = break_at
        while i < n and text[i].isspace():
            i += 1
    return chunks


def kokoro_file_to_mp3(
    source_path: str,
    output_mp3_path: str,
    voice_id: str,
    speed: float = 1.0,
    end_silence_ms: int = 3000,
    chunk_pause_ms: int = 50,
    log: Callable[[str], None] = print,
    cancel_check: Callable[[], bool] | None = None,
) -> None:
    """Read plain text from file → Kokoro TTS → single MP3."""
    src = Path(source_path)
    if not src.exists():
        raise FileNotFoundError(f"Source text file not found: {source_path}")

    raw_text = src.read_text(encoding="utf-8")

    lines = raw_text.splitlines()
    content_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("Title:") or stripped.startswith("Author:"):
            continue
        if stripped.startswith("#"):
            content_lines.append(stripped.lstrip("#").strip())
        else:
            content_lines.append(line)
    text = "\n".join(content_lines).strip()

    chunks = split_into_chunks(text)
    if not chunks:
        raise ValueError("No text content found after parsing source file.")

    log(f"Kokoro: synthesizing {len(chunks)} chunk(s) with voice '{voice_id}' speed={speed}...")

    lang_code = _lang_code_for_voice(voice_id)
    try:
        pipeline = _get_pipeline(lang_code)
    except Exception as e:
        raise RuntimeError(
            f"Could not load Kokoro pipeline. Install with: pip install kokoro soundfile scipy\n{e}"
        ) from e

    segment_paths: list[str] = []
    with tempfile.TemporaryDirectory(prefix="epub2tts_kokoro_") as tmpdir:
        for idx, chunk in enumerate(chunks, start=1):
            if cancel_check is not None and cancel_check():  # between chunks
                from shared.cancellation import ConversionCancelled

                raise ConversionCancelled("Conversion cancelled by user.")
            log(f"  Kokoro chunk {idx}/{len(chunks)}...")
            chunk_wav = str(Path(tmpdir) / f"chunk_{idx:04d}.wav")
            chunk_mp3 = str(Path(tmpdir) / f"chunk_{idx:04d}.mp3")

            audio_chunks: list[np.ndarray] = []
            generator = pipeline(chunk, voice=voice_id, speed=speed, split_pattern=r"\n+")
            for _, _, audio in generator:
                if audio is not None:
                    arr = audio.numpy() if hasattr(audio, "numpy") else np.array(audio)
                    audio_chunks.append(arr)

            if not audio_chunks:
                log(f"  Warning: chunk {idx} produced no audio, skipping.")
                continue

            combined = np.concatenate(audio_chunks)
            sf.write(chunk_wav, combined, 24000)
            seg = AudioSegment.from_wav(chunk_wav)
            seg.export(chunk_mp3, format="mp3")
            segment_paths.append(chunk_mp3)

        if not segment_paths:
            raise RuntimeError("Kokoro produced no audio segments.")

        log("  Merging Kokoro segments...")
        merged = AudioSegment.empty()
        silence_chunk = AudioSegment.silent(duration=chunk_pause_ms)
        for sp in segment_paths:
            merged += AudioSegment.from_mp3(sp) + silence_chunk
        if end_silence_ms > 0:
            merged += AudioSegment.silent(duration=end_silence_ms)
        merged.export(output_mp3_path, format="mp3")

    log(f"Kokoro: saved → {output_mp3_path}")
