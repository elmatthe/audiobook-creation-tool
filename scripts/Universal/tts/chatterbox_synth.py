"""
chatterbox_synth.py — Local Chatterbox Turbo voice cloning for the TTS tool.

Structured to match ``kokoro_synth.py`` so the GUI worker can treat every local
engine alike: the same module-load HuggingFace cache redirect, the same lazy
imports, the same single-first-load allowance for Windows Application Control, and
the same ``(log, cancel_check, progress_callback, end_silence_ms, chunk_pause_ms)``
worker signature.

**Engine facts, verified against the exact published wheel (chatterbox-tts 0.1.7).**
The Turbo model lives at ``chatterbox.tts_turbo.ChatterboxTurboTTS``; it is *not*
exported from the package root, so the import shown in the upstream configuration
docs does not work against this release. Weights are ``ResembleAI/chatterbox-turbo``
(~3.86 GiB), fetched on demand into the in-tree cache below — never bundled.

**Reference audio.** The model conditions on a short excerpt: it slices the leading
``[:DEC_COND_LEN]`` (10 s at 24 kHz) for the decoder and the leading
``[:ENC_COND_LEN]`` (15 s at 16 kHz) for the speech tokenizer, and it asserts the
input is longer than 5 seconds. Derivatives here are therefore a deterministic
**leading 15-second window**, mono, 24 kHz — the widest window the model actually
consults. It also normalises loudness itself (to about -27 LUFS), so this module
must not pre-normalise; doing it twice would be wrong.

**Local reference assets.** ``files/Chatterbox-Voice-Uploads/`` holds
maintainer-supplied local reference recordings, authorized by the maintainer for
use by this local Chatterbox integration. They are strictly read-only inputs: this
module verifies each one's SHA-256 before use, never writes into that directory,
and puts every derivative and cached conditional under the ignored
``files/runtime-data/`` tree. A missing or altered recording degrades to a truthful
"setup required" status — it never substitutes another voice and never fetches a
replacement.

PerTh watermarking is applied by the model itself during generation and is left
exactly as shipped.
"""

from __future__ import annotations

import os
from pathlib import Path

# Belt-and-suspenders, identical to kokoro_synth: if no parent process set HF_HOME
# (e.g. this module is run directly for debugging), point the HuggingFace cache at
# the project tree *before* chatterbox or torch is ever imported. Those imports are
# lazy, inside the functions below, so this module-load setup always runs first.
# This is the same cache Kokoro uses — there is deliberately no second one.
if "HF_HOME" not in os.environ:
    _here = Path(__file__).resolve()
    for _parent in _here.parents:
        if (_parent / "scripts").is_dir() and (_parent / "files").is_dir():
            _hf = _parent / "files" / "runtime-data" / "models" / "huggingface"
            os.environ["HF_HOME"] = str(_hf)
            os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(_hf / "hub"))
            break

import hashlib
import importlib.util
import json
import subprocess
import tempfile
import time
import wave
from dataclasses import dataclass
from typing import Callable

import numpy as np
import soundfile as sf
from pydub import AudioSegment

from shared import ffmpeg_utils
from tts.kokoro_synth import split_into_chunks

# --------------------------------------------------------------------------- #
# Engine identity — the exact release this module was written against
# --------------------------------------------------------------------------- #
PACKAGE_REQUIREMENT = "chatterbox-tts==0.1.7"
MODEL_REPO_ID = "ResembleAI/chatterbox-turbo"
MODEL_MODULE = "chatterbox.tts_turbo"
MODEL_CLASS = "ChatterboxTurboTTS"

# Modules that must resolve for the engine to run at all. Probed with find_spec,
# which locates without executing, so a health check stays cheap.
_RUNTIME_MODULES = ("chatterbox", "torch", "torchaudio", "librosa")

# Derivative specification, taken from the model's own conditioning constants
# rather than from documentation. ENC_COND_LEN = 15 * 16000, DEC_COND_LEN =
# 10 * 24000, and both are plain leading slices of the loaded waveform.
REFERENCE_WINDOW_SECONDS = 15
REFERENCE_SAMPLE_RATE = 24000
REFERENCE_CHANNELS = 1
REFERENCE_MIN_SECONDS = 5.0


class ChatterboxUnavailable(RuntimeError):
    """The engine, its model, or a reference recording is not usable right now.

    Always carries a message fit to show a non-technical user. Raised instead of
    quietly falling back, so no broken or substituted voice is ever offered.
    """


@dataclass(frozen=True)
class ReferenceVoice:
    voice_id: str
    label: str
    source_name: str
    source_sha256: str


# The closed set of four (drop §5.7). These are engine-internal identifiers: they
# are deliberately NOT VoiceEntry rows, so nothing reaches the GUI dropdown until
# Phase 10 registers them.
REFERENCE_VOICES: dict[str, ReferenceVoice] = {
    "chatterbox-female-1": ReferenceVoice(
        voice_id="chatterbox-female-1",
        label="Chatterbox — Female 1",
        source_name="Female-1.mp3",
        source_sha256="a047d77fe191c1a957d36b1e9f9af8e67756a63672686c55731b30534bb8bde2",
    ),
    "chatterbox-female-2": ReferenceVoice(
        voice_id="chatterbox-female-2",
        label="Chatterbox — Female 2",
        source_name="Female-2.mp3",
        source_sha256="4bad0d3845199eae723aceb7a864b419fe553cd9d23799ee6390f54df08d3140",
    ),
    "chatterbox-male-1": ReferenceVoice(
        voice_id="chatterbox-male-1",
        label="Chatterbox — Male 1",
        source_name="Male-1.mp3",
        source_sha256="6258dde294a91b0c2e965e8579aafde10e9cff48957c2138432be4c6c80165ae",
    ),
    "chatterbox-male-2": ReferenceVoice(
        voice_id="chatterbox-male-2",
        label="Chatterbox — Male 2",
        source_name="Male-2.mp3",
        source_sha256="7b8fd74dfb262740476fba8317c0b7483a9f8b290e58c1d7e496e48b048d6ab2",
    ),
}


# --------------------------------------------------------------------------- #
# Locations
# --------------------------------------------------------------------------- #
def _repo_root() -> Path:
    """The folder containing both ``scripts/`` and ``files/``."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "scripts").is_dir() and (parent / "files").is_dir():
            return parent
    return Path(__file__).resolve().parents[3]


def _runtime_root() -> Path:
    """``files/runtime-data/`` — gitignored, the only place derivatives may live."""
    return _repo_root() / "files" / "runtime-data"


def protected_uploads_dir() -> Path:
    """The read-only source recordings. Nothing in this module ever writes here."""
    return _repo_root() / "files" / "Chatterbox-Voice-Uploads"


def reference_clips_dir() -> Path:
    return _runtime_root() / "chatterbox" / "reference-clips"


def conditionals_dir() -> Path:
    return _runtime_root() / "chatterbox" / "conditionals"


def _assert_writable_destination(path) -> None:
    """Refuse any write target inside the protected uploads folder."""
    target = Path(path).resolve()
    protected = protected_uploads_dir().resolve()
    if target == protected or protected in target.parents:
        raise ChatterboxUnavailable(
            f"Refusing to write inside the protected reference folder: {target}. "
            "The maintainer's recordings are read-only inputs; derivatives belong "
            f"under {_runtime_root()}."
        )


# --------------------------------------------------------------------------- #
# Availability — truthful, cheap, and never raising at import time
# --------------------------------------------------------------------------- #
def _find_spec(name: str):
    """``importlib.util.find_spec`` that answers None instead of raising."""
    try:
        return importlib.util.find_spec(name)
    except (ImportError, ValueError):
        return None


def package_status() -> tuple[bool, str]:
    """``(ok, reason)`` for the engine package. Locates only — imports nothing."""
    missing = [name for name in _RUNTIME_MODULES if _find_spec(name) is None]
    if missing:
        return False, (
            "The Chatterbox voice engine is not installed (missing: "
            f"{', '.join(missing)}). Run setup again, or install "
            f"{PACKAGE_REQUIREMENT} into this app's environment."
        )
    return True, "ok"


def get_reference_voice(voice_id: str) -> ReferenceVoice:
    try:
        return REFERENCE_VOICES[voice_id]
    except KeyError:
        raise ChatterboxUnavailable(
            f"Unknown Chatterbox voice '{voice_id}'. Known voices: "
            f"{', '.join(sorted(REFERENCE_VOICES))}."
        ) from None


def reference_source_path(voice_id: str) -> Path:
    return protected_uploads_dir() / get_reference_voice(voice_id).source_name


def sha256_of(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_reference(voice_id: str) -> Path:
    """Locate the source recording and prove it is the expected one.

    The hash is re-checked on every use, not cached: these files are local inputs
    the maintainer manages outside the repository, and a changed file must be
    caught rather than silently cloned.
    """
    voice = get_reference_voice(voice_id)
    path = reference_source_path(voice_id)
    if not path.is_file():
        raise ChatterboxUnavailable(
            f"Setup required for {voice.label}: the reference recording "
            f"'{voice.source_name}' is not present in {protected_uploads_dir()}. "
            "This voice is unavailable on this machine; Edge and Kokoro voices are "
            "unaffected."
        )
    actual = sha256_of(path)
    if actual != voice.source_sha256:
        raise ChatterboxUnavailable(
            f"The reference recording '{voice.source_name}' does not match the "
            f"expected sha256 for {voice.label} (expected {voice.source_sha256}, "
            f"found {actual}). Refusing to use it. The file has not been modified "
            "by this app — replace it with the original to restore this voice."
        )
    return path


def reference_status(voice_id: str) -> tuple[bool, str]:
    """``(ok, reason)`` for one voice's local assets. Never raises."""
    try:
        resolve_reference(voice_id)
    except ChatterboxUnavailable as exc:
        return False, str(exc)
    return True, "ok"


def engine_status(voice_id: str | None = None) -> tuple[bool, str]:
    """The single seam callers use to ask 'can this voice run right now?'.

    Never raises and never touches the network, so it is safe to call from a GUI
    build or a startup probe on a machine with nothing installed.
    """
    ok, reason = package_status()
    if not ok:
        return False, reason
    if voice_id is None:
        return True, "ok"
    return reference_status(voice_id)


# --------------------------------------------------------------------------- #
# Derivative identity
# --------------------------------------------------------------------------- #
def derivative_spec() -> dict:
    """Exactly what a derivative is — recorded in the manifest and the cache key."""
    return {
        "window_seconds": REFERENCE_WINDOW_SECONDS,
        "window_position": "leading",
        "sample_rate": REFERENCE_SAMPLE_RATE,
        "channels": REFERENCE_CHANNELS,
        "codec": "pcm_s16le",
        "loudness_normalized_by_caller": False,
    }


def identity_digest(source_sha256: str) -> str:
    """Bind a cache entry to its source, the engine release, and the clip spec.

    Any of the three changing must miss the cache rather than reuse a stale
    conditional, so all three go into the digest.
    """
    payload = json.dumps(
        {
            "source_sha256": source_sha256,
            "package": PACKAGE_REQUIREMENT,
            "model": MODEL_REPO_ID,
            "spec": derivative_spec(),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _slug(voice_id: str) -> str:
    return voice_id.replace("chatterbox-", "", 1)


def derivative_path(voice_id: str, source_sha256: str) -> Path:
    return reference_clips_dir() / (
        f"{_slug(voice_id)}__{source_sha256[:16]}"
        f"__{identity_digest(source_sha256)[:12]}.wav"
    )


def conditionals_path(voice_id: str, source_sha256: str) -> Path:
    return conditionals_dir() / (
        f"{_slug(voice_id)}__{source_sha256[:16]}"
        f"__{identity_digest(source_sha256)[:12]}.pt"
    )


# --------------------------------------------------------------------------- #
# Reference preparation
# --------------------------------------------------------------------------- #
def _clip_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / float(handle.getframerate())


def build_reference_clip(source_path, dest_path) -> Path:
    """Decode a deterministic leading conditioning window from ``source_path``.

    ``-map 0:a:0`` plus ``-vn`` selects the first audio stream explicitly, so an
    embedded cover-art (mjpeg) stream can never be picked up as the audio. The
    source is opened read-only by ffmpeg and left byte-identical; if anything here
    fails, the source is untouched and no partial derivative survives.
    """
    source = Path(source_path)
    dest = Path(dest_path)
    _assert_writable_destination(dest)
    if not source.is_file():
        raise ChatterboxUnavailable(f"Reference source not found: {source}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".partial")
    cmd = [
        ffmpeg_utils.ffmpeg_cmd(), "-y", "-loglevel", "error",
        "-i", str(source),
        "-map", "0:a:0", "-vn",
        "-t", str(REFERENCE_WINDOW_SECONDS),
        "-ac", str(REFERENCE_CHANNELS),
        "-ar", str(REFERENCE_SAMPLE_RATE),
        "-c:a", "pcm_s16le",
        # Deterministic output: no encoder tag, no source metadata carried over.
        "-map_metadata", "-1", "-fflags", "+bitexact",
        "-f", "wav", str(tmp),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 or not tmp.exists():
            raise ChatterboxUnavailable(
                f"Could not decode a reference clip from {source.name}: "
                f"{(result.stderr or '').strip() or 'ffmpeg failed'}"
            )
        seconds = _clip_seconds(tmp)
        if seconds <= REFERENCE_MIN_SECONDS:
            raise ChatterboxUnavailable(
                f"The reference recording {source.name} yields only "
                f"{seconds:.1f}s of audio. Chatterbox requires more than "
                f"{REFERENCE_MIN_SECONDS:.0f} seconds to clone a voice."
            )
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)
    return dest


def _record_manifest(voice: ReferenceVoice, source: Path, derivative: Path) -> None:
    """Trace label → source → full source SHA-256 → derivative → parameters."""
    manifest_path = reference_clips_dir() / "manifest.json"
    _assert_writable_destination(manifest_path)
    try:
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        existing = {}
    existing[voice.voice_id] = {
        "label": voice.label,
        "source_path": str(source),
        "source_sha256": voice.source_sha256,
        "derivative_path": str(derivative),
        "parameters": derivative_spec(),
        "package": PACKAGE_REQUIREMENT,
        "model": MODEL_REPO_ID,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(existing, indent=2, sort_keys=True),
                             encoding="utf-8")


def prepare_reference_clip(voice_id: str,
                           log: Callable[[str], None] = print) -> Path:
    """Return the conditioning clip for ``voice_id``, building it once if needed."""
    voice = get_reference_voice(voice_id)
    source = resolve_reference(voice_id)
    dest = derivative_path(voice_id, voice.source_sha256)
    if dest.is_file():
        return dest
    log(f"Chatterbox: preparing a {REFERENCE_WINDOW_SECONDS}s reference clip for "
        f"{voice.label}…")
    build_reference_clip(source, dest)
    _record_manifest(voice, source, dest)
    return dest


# --------------------------------------------------------------------------- #
# Device selection and model loading
# --------------------------------------------------------------------------- #
def _torch_capabilities() -> tuple[bool, bool]:
    """``(cuda_available, mps_available)`` — the only hardware question asked."""
    import torch

    cuda = bool(torch.cuda.is_available())
    try:
        mps = bool(torch.backends.mps.is_available())
    except Exception:
        mps = False
    return cuda, mps


def select_device() -> str:
    """Resolve ``cuda`` → ``mps`` → ``cpu`` at runtime.

    Nothing here installs or requires an accelerator: the shipped PyTorch pin is
    the plain cross-platform build, so on most machines this simply answers "cpu".
    """
    try:
        cuda, mps = _torch_capabilities()
    except Exception:
        return "cpu"
    if cuda:
        return "cuda"
    if mps:
        return "mps"
    return "cpu"


# Fires the single first-load allowance (below) only once per process, exactly as
# kokoro_synth does. The first native-extension load on Windows can be transiently
# blocked while Smart App Control / WDAC evaluates unsigned DLLs; later failures
# are real errors and must propagate.
_first_model_load_attempted = False
_MODEL_CACHE: dict = {}


def _instantiate_model(device: str):
    """Lazy-import the engine and build the Turbo model for ``device``.

    Imports ``chatterbox.tts_turbo`` directly: the 0.1.7 package root exports only
    ChatterboxTTS / ChatterboxVC / ChatterboxMultilingualTTS, so importing the
    Turbo class from the root would raise ImportError.
    """
    from chatterbox.tts_turbo import ChatterboxTurboTTS

    return ChatterboxTurboTTS.from_pretrained(device)


def _conditionals_class():
    """The engine's serializable conditioning container."""
    from chatterbox.tts_turbo import Conditionals

    return Conditionals


def _get_model(device: str | None = None):
    """Load (once per device) the Turbo model, allowing one first-load re-attempt.

    The weights are ~3.86 GiB and are fetched into the in-tree HuggingFace cache on
    the first call, so this can be slow the first time and fast afterwards.
    """
    global _first_model_load_attempted

    resolved = device or select_device()
    cached = _MODEL_CACHE.get(resolved)
    if cached is not None:
        return cached

    if not _first_model_load_attempted:
        _first_model_load_attempted = True
        try:
            model = _instantiate_model(resolved)
        except (OSError, RuntimeError, ImportError) as exc:
            print(
                "Chatterbox model load blocked on first attempt (likely Windows "
                "Application Control evaluating unsigned native DLLs) — trying "
                "once more in 2s"
            )
            time.sleep(2)
            try:
                model = _instantiate_model(resolved)
            except (OSError, RuntimeError, ImportError) as exc2:
                raise exc2 from exc
    else:
        model = _instantiate_model(resolved)

    _MODEL_CACHE[resolved] = model
    return model


def load_conditionals(model, voice_id: str,
                      log: Callable[[str], None] = print,
                      device: str | None = None) -> None:
    """Attach ``voice_id``'s voice identity to ``model``, computing it at most once.

    Conditioning is the expensive part of cloning (~16s per voice on CPU here), and
    the engine's ``Conditionals`` container is serializable, so the result is cached
    under the ignored runtime tree. The cache key carries the source hash, the
    engine release and the clip spec, so a stale entry is missed rather than reused.
    """
    voice = get_reference_voice(voice_id)
    clip = prepare_reference_clip(voice_id, log=log)
    cache = conditionals_path(voice_id, voice.source_sha256)
    target = device or getattr(model, "device", "cpu")

    if cache.is_file():
        try:
            conds = _conditionals_class().load(cache, map_location=target)
            model.conds = conds.to(target)
            return
        except Exception as exc:
            log(f"Chatterbox: cached voice data for {voice.label} is unusable "
                f"({exc!r}) — rebuilding it.")
            cache.unlink(missing_ok=True)

    log(f"Chatterbox: analysing the reference voice for {voice.label} "
        "(one-time, about 15 seconds)…")
    model.prepare_conditionals(str(clip))
    try:
        _assert_writable_destination(cache)
        cache.parent.mkdir(parents=True, exist_ok=True)
        model.conds.save(cache)
    except Exception as exc:
        log(f"Chatterbox: could not cache voice data ({exc!r}) — it will be "
            "recomputed next time.")


# --------------------------------------------------------------------------- #
# Synthesis
# --------------------------------------------------------------------------- #
def _audio_array(wav) -> np.ndarray:
    """Flatten the engine's ``(1, N)`` float32 tensor into a mono numpy array."""
    if hasattr(wav, "detach"):
        wav = wav.detach()
    if hasattr(wav, "cpu"):
        wav = wav.cpu()
    arr = wav.numpy() if hasattr(wav, "numpy") else np.asarray(wav)
    arr = np.asarray(arr, dtype="float32")
    if arr.ndim > 1:
        arr = arr.reshape(-1)
    return arr


def _export_mp3(arr: np.ndarray, sample_rate: int, output_path: str) -> None:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_wav:
        tmp_wav_path = tmp_wav.name
    try:
        sf.write(tmp_wav_path, arr, sample_rate)
        AudioSegment.from_wav(tmp_wav_path).export(output_path, format="mp3")
    finally:
        Path(tmp_wav_path).unlink(missing_ok=True)


def synthesize_text_to_mp3(
    text: str,
    output_path: str,
    voice_id: str,
    log: Callable[[str], None] = print,
    device: str | None = None,
) -> None:
    """Synthesize ``text`` in the cloned voice ``voice_id`` to an MP3.

    Generation parameters are left at the pinned release's own defaults. Turbo
    ignores ``cfg_weight``/``exaggeration``/``min_p`` (it warns if they are set), so
    this deliberately exposes no quality knobs the model does not honour.
    """
    model = _get_model(device)
    load_conditionals(model, voice_id, log=log, device=device)
    arr = _audio_array(model.generate(text))
    if arr.size == 0:
        raise ChatterboxUnavailable(
            f"Chatterbox produced no audio for voice '{voice_id}'.")
    _export_mp3(arr, model.sr, output_path)


def chatterbox_file_to_mp3(
    source_path: str,
    output_mp3_path: str,
    voice_id: str,
    end_silence_ms: int = 3000,
    chunk_pause_ms: int = 50,
    log: Callable[[str], None] = print,
    cancel_check: Callable[[], bool] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
    device: str | None = None,
) -> None:
    """Read plain text from file → Chatterbox Turbo → single MP3.

    Same shape as ``kokoro_file_to_mp3`` so the GUI worker treats all engines alike.
    ``progress_callback(done, total)`` fires after each chunk on the calling
    (worker) thread — a GUI caller must enqueue from it, never touch Tk directly.
    Cancellation is honoured **between** chunks: a generation already in flight is
    allowed to finish rather than being torn down mid-inference.
    """
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

    voice = get_reference_voice(voice_id)
    log(f"Chatterbox: synthesizing {len(chunks)} chunk(s) in {voice.label}…")

    model = _get_model(device)
    load_conditionals(model, voice_id, log=log, device=device)

    segment_paths: list[str] = []
    with tempfile.TemporaryDirectory(prefix="epub2tts_chatterbox_") as tmpdir:
        for idx, chunk in enumerate(chunks, start=1):
            if cancel_check is not None and cancel_check():  # between chunks
                from shared.cancellation import ConversionCancelled

                raise ConversionCancelled("Conversion cancelled by user.")
            log(f"  Chatterbox chunk {idx}/{len(chunks)}…")
            chunk_wav = str(Path(tmpdir) / f"chunk_{idx:04d}.wav")
            chunk_mp3 = str(Path(tmpdir) / f"chunk_{idx:04d}.mp3")

            arr = _audio_array(model.generate(chunk))
            if arr.size == 0:
                log(f"  Warning: chunk {idx} produced no audio, skipping.")
                if progress_callback is not None:
                    progress_callback(idx, len(chunks))
                continue

            sf.write(chunk_wav, arr, model.sr)
            AudioSegment.from_wav(chunk_wav).export(chunk_mp3, format="mp3")
            segment_paths.append(chunk_mp3)
            if progress_callback is not None:
                progress_callback(idx, len(chunks))

        if not segment_paths:
            raise ChatterboxUnavailable("Chatterbox produced no audio segments.")

        log("  Merging Chatterbox segments…")
        merged = AudioSegment.empty()
        silence_chunk = AudioSegment.silent(duration=chunk_pause_ms)
        for sp in segment_paths:
            merged += AudioSegment.from_mp3(sp) + silence_chunk
        if end_silence_ms > 0:
            merged += AudioSegment.silent(duration=end_silence_ms)
        merged.export(output_mp3_path, format="mp3")

    log(f"Chatterbox: saved → {output_mp3_path}")
