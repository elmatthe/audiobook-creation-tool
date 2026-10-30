"""qwen3_synth.py — Qwen3-TTS conversion for ACT: plan the text, supervise a worker, assemble, encode once.

This is the application-side half of the Qwen3 engine. The model itself runs in ``qwen3_worker.py`` inside the
isolated ``.venv-qwen3`` (see ``qwen3_runtime`` for why), as **one subprocess per source file**. This module imports
numpy, soundfile and pydub (all already application dependencies) and nothing from torch or Qwen, so the GUI process
never loads the model stack.

What happens for one file (``qwen3_file_to_mp3``, deliberately the same shape as ``chatterbox_file_to_mp3``):

1. The same text preparation the other local engines use (``Title:``/``Author:`` lines skipped, ``#`` markers removed),
   with one addition: a heading line stays its own paragraph so a title transition survives chunking.
2. The text is planned into chunks of whole sentences (at most 600 characters, never across a paragraph), each carrying
   its exact source span; the plan is verified against the source before anything runs.
3. A job file is written and the worker is started. Its ``@@EVENT`` lines are read; cancellation asks politely (a flag
   file) and then, after a short grace period, kills the whole process tree.
4. The chunk waveforms are read back, validated, joined in PCM with ACT's existing pause policy (the voice preset's
   paragraph pause after every chunk, its end pause once at the end, exactly as Kokoro and Chatterbox do) and encoded
   **once** to the MP3 — written under a temporary name and moved into place only when complete, so a failed or
   cancelled run never leaves a partial file and never damages an existing one.
5. The job folder (which holds the user's text) is always removed.

Nothing falls back: a missing model, transcript or reference raises ``Qwen3Unavailable`` with a sentence for the user;
a GPU that fails fails the file; a worker that dies fails the file.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import soundfile as sf

from shared import ffmpeg_utils
from shared.cancellation import ConversionCancelled
from tts import audio_tail
from tts import qwen3_process
from tts import qwen3_runtime as rt
from tts.qwen3_runtime import Qwen3Unavailable
from tts.speech.document import HEADING_PARAGRAPH_STRUCTURE, parse_structure, read_source_text
from tts.speech.pipeline import PreparedText, prepare
from tts.speech.profiles import QWEN3 as QWEN3_ROUTE

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
#: Qwen3 is planned in whole sentences up to this many characters. The evaluation measured this ceiling (peak VRAM
#: 4.7 GB, the longest chunk used about 8% of the generation cap); Chatterbox keeps its own 300 and Kokoro its own.
QWEN3_MAX_CHUNK_CHARS = 600

#: Bump deliberately whenever a change can alter generated audio (planning, seeding, generation calls, assembly).
#: This is the revision of the pipeline itself with speech preparation off -- unchanged by Plan 01B, as the A0
#: characterization proves. A run with speech preparation on is revision :data:`SPEECH_PREP_PIPELINE_REVISION`.
PIPELINE_REVISION = 1
#: Plan 01B A5: speech preparation v1 changes the text Qwen3 is given (and so its chunks, seeds and audio) wherever an
#: approved cell edits it.
SPEECH_PREP_PIPELINE_REVISION = 2


def pipeline_revision(speech_prep=None) -> int:
    """The revision that produced a run's audio: 2 when its speech-preparation snapshot is on, otherwise 1."""
    return SPEECH_PREP_PIPELINE_REVISION if speech_prep is not None and speech_prep.enabled else PIPELINE_REVISION
SEED_BASE = 20261019

#: Owner preference (2026-10-20): the six cloned voices narrate calmly and evenly, with less pitch, intensity and pace
#: variation than the Base model's own sampling gives. Sampling temperature is the model's own control for that: a clone is
#: generated at a lower main ``temperature`` (the model default is 0.9) and a slightly lower ``subtalker_temperature`` (the
#: acoustic-detail stage; also 0.9 by default). Every other sampling control (top_p, top_k, repetition_penalty, max_new_tokens)
#: stays the Base model's own, and each chunk's seed is unchanged. Preset voices (Aiden, Ryan) are never given this profile.
CLONE_GENERATION = {"temperature": 0.70, "subtalker_temperature": 0.80}
#: Identifies :data:`CLONE_GENERATION`; bump it with any change to that profile. It is separate from
#: :data:`PIPELINE_REVISION` on purpose: that one describes the planner/seed/assembly code the immutable A0 characterization
#: pins at 1, and the profile changes neither the text, nor the chunks, nor the seeds.
CLONE_GENERATION_REVISION = 1
#: A clone continues from its reference recording. Several of the bundled references were cut at a fixed length and end mid-sound
#: (the Female 1, Female 2 and Male 4 recordings), and a clone conditioned on one opens every chunk with a stray leftover of that sound
#: (or loses its first word). The copy of the reference handed to the worker therefore gets this much silence appended after it has
#: been proved to be the approved recording; the recording itself, its hash and its transcript are untouched (silence adds no words).
CLONE_REFERENCE_TAIL_SILENCE_S = 0.6

LANGUAGE = "English"  # the only language the evaluation proved
DTYPE = "bfloat16"
ATTENTION = "sdpa"

#: After asking a worker to stop, how long it gets to stop on its own before its process tree is killed.
CANCEL_GRACE_S = 3.0
#: After the process tree has been killed, how long the supervisor still waits for the output pipe to close before it
#: stops waiting altogether. This is the final deadline: nothing below can hang the conversion thread past it.
KILL_WAIT_S = 10.0
#: No event for this long is a stalled worker (a cold model load on a slow disk or CPU is the longest legitimate gap).
EVENT_TIMEOUT_S = 1800.0
#: After a worker reports its result it gets this long to exit; a worker that hangs in shutdown is killed and the
#: file is treated as failed (a result is only believed from a worker that also exited cleanly).
EXIT_GRACE_S = 20.0
#: Job folders older than this are crash leftovers and are removed before the next run.
STALE_JOB_AGE_S = 24 * 3600.0
STDERR_TAIL_CHARS = 1500


class Qwen3Failed(RuntimeError):
    """The worker ran but this file could not be produced. The message is fit to show a user."""


# --------------------------------------------------------------------------- #
# Source text preparation (the other local engines' rules, plus title-as-paragraph)
# --------------------------------------------------------------------------- #
def prepare_text(raw_text: str) -> str:
    """The text a local engine speaks: metadata lines dropped, heading markers removed.

    ``Title:``/``Author:`` lines are skipped and ``#`` markers stripped, exactly as ``kokoro_file_to_mp3`` and
    ``chatterbox_file_to_mp3`` do. A heading line additionally becomes a paragraph of its own (blank lines around
    it), so a title is never fused with the first sentence after it and earns the paragraph pause.
    """
    return parse_structure(raw_text, HEADING_PARAGRAPH_STRUCTURE).text


# --------------------------------------------------------------------------- #
# Chunk plan with ordered source spans (ported from the evaluation's verified planner)
# --------------------------------------------------------------------------- #
class ChunkPlanError(RuntimeError):
    """The plan could not be built or did not preserve its source text."""


@dataclass(frozen=True)
class Chunk:
    index: int
    start: int  # offset of the first source character in the prepared text
    end: int  # exclusive
    text: str  # what the engine speaks: the source words, single-space separated
    boundary: str  # what follows this chunk: sentence | clause | word | paragraph | end
    paragraph: int

    def to_dict(self) -> dict:
        return asdict(self)


_CLOSERS = "\"'”’)]"
_OPENERS = "\"'“‘(["
_TERMINATOR = re.compile(r"([.!?…]+)([" + re.escape(_CLOSERS) + r"]*)$")
_DOTTED = re.compile(r"^(?:[A-Za-z]\.)+[A-Za-z]$")
_INITIAL = re.compile(r"^[A-Z]$")
_ABBREVIATIONS = frozenset({
    "dr", "mr", "mrs", "ms", "prof", "st", "capt", "col", "gen", "lt", "sgt", "jr", "sr", "mt", "ft",
    "vs", "no", "hon", "rev", "gov", "sen", "rep", "dept", "inc", "ltd", "co",
})
# Tried in order, and only for a sentence that is already over the ceiling.
_CLAUSE_LEVELS = ((";",), (":",), ("—", "–"), (",",))


def _is_sentence_end(word: str, next_word: Optional[str]) -> bool:
    match = _TERMINATOR.search(word)
    if not match:
        return False
    if next_word is None:
        return True
    core = word[:match.start()].lstrip(_OPENERS)
    if match.group(1) == ".":
        # Mr. / Dr. / St. ..., initials (J. R.), dotted forms (e.g., i.e.) never end a sentence.
        if core.lower() in _ABBREVIATIONS or _INITIAL.match(core) or _DOTTED.match(core):
            return False
    following = next_word.lstrip(_OPENERS)
    return not (following and following[0].islower())


def _joined_len(words: list[str], lo: int, hi: int) -> int:
    return sum(len(w) for w in words[lo:hi]) + max(0, hi - lo - 1)


def _ends_with(word: str, marks: tuple[str, ...]) -> bool:
    return word.rstrip(_CLOSERS).endswith(marks)


def _split_units(words: list[str], lo: int, hi: int, max_chars: int, level: int) -> list[list]:
    """Word range [lo, hi) into [lo, hi, boundary_after] units of at most ``max_chars``."""
    if _joined_len(words, lo, hi) <= max_chars:
        return [[lo, hi, None]]
    if level < len(_CLAUSE_LEVELS):
        marks = _CLAUSE_LEVELS[level]
        cuts = [i + 1 for i in range(lo, hi - 1) if _ends_with(words[i], marks)]
        if cuts:
            units: list[list] = []
            start = lo
            for cut in cuts + [hi]:
                piece = _split_units(words, start, cut, max_chars, level + 1)
                if cut != hi and piece[-1][2] is None:
                    piece[-1][2] = "clause"
                units.extend(piece)
                start = cut
            return units
        return _split_units(words, lo, hi, max_chars, level + 1)
    units, start, current = [], lo, 0
    for i in range(lo, hi):
        size = len(words[i])
        if size > max_chars:
            raise ChunkPlanError(f"a single word of {size} characters exceeds the {max_chars}-character ceiling")
        added = size if i == start else size + 1
        if current + added > max_chars:
            units.append([start, i, "word"])
            start, current = i, size
        else:
            current += added
    units.append([start, hi, None])
    return units


def _paragraph_spans(text: str) -> list[tuple[int, int]]:
    spans, pos = [], 0
    for match in re.finditer(r"\n[^\S\n]*\n\s*", text):  # a blank line is any line of whitespace, NBSP included
        spans.append((pos, match.start()))
        pos = match.end()
    spans.append((pos, len(text)))
    return [(s, e) for s, e in spans if text[s:e].strip()]


def plan_chunks(text: str, max_chars: int = QWEN3_MAX_CHUNK_CHARS) -> list[Chunk]:
    """Ordered chunks of whole sentences, never crossing a paragraph or title boundary.

    Every chunk carries the exact source span it came from. Sentences are packed greedily up to ``max_chars``; an
    over-long sentence is cut at clause punctuation, then at a word boundary, and only there. The plan is verified
    against the source before it is returned.
    """
    if max_chars < 50:
        raise ValueError("max_chars is unreasonably small")
    chunks: list[Chunk] = []
    paragraphs = _paragraph_spans(text)
    for p_index, (p_start, p_end) in enumerate(paragraphs):
        matches = list(re.finditer(r"\S+", text[p_start:p_end]))
        words = [m.group(0) for m in matches]
        spans = [(p_start + m.start(), p_start + m.end()) for m in matches]
        units: list[list] = []
        lo = 0
        for i, word in enumerate(words):
            last = i == len(words) - 1
            if last or _is_sentence_end(word, words[i + 1]):
                sentence = _split_units(words, lo, i + 1, max_chars, 0)
                if sentence[-1][2] is None:
                    sentence[-1][2] = "sentence"
                units.extend(sentence)
                lo = i + 1
        merged: list[list] = []
        for unit in units:
            if merged and _joined_len(words, merged[-1][0], unit[1]) <= max_chars:
                merged[-1][1], merged[-1][2] = unit[1], unit[2]
            else:
                merged.append(list(unit))
        merged[-1][2] = "end" if p_index == len(paragraphs) - 1 else "paragraph"
        for u_lo, u_hi, boundary in merged:
            chunks.append(Chunk(
                index=len(chunks), start=spans[u_lo][0], end=spans[u_hi - 1][1],
                text=" ".join(words[u_lo:u_hi]), boundary=boundary, paragraph=p_index))
    verify_plan(text, chunks)
    return chunks


def verify_plan(text: str, chunks: list[Chunk]) -> None:
    """Every non-whitespace source character, once, in order; spans ordered and non-overlapping."""
    if not chunks:
        raise ChunkPlanError("the plan has no chunks")
    previous_end = 0
    for chunk in chunks:
        if not chunk.text.strip():
            raise ChunkPlanError(f"chunk {chunk.index} is empty")
        if chunk.start < previous_end or chunk.end <= chunk.start:
            raise ChunkPlanError(f"chunk {chunk.index} span {chunk.start}-{chunk.end} is out of order")
        if "".join(text[chunk.start:chunk.end].split()) != "".join(chunk.text.split()):
            raise ChunkPlanError(f"chunk {chunk.index} text does not match its source span")
        previous_end = chunk.end
    if "".join("".join(c.text.split()) for c in chunks) != "".join(text.split()):
        raise ChunkPlanError("the chunk plan did not preserve its source text")


def chunk_source_spans(prepared: PreparedText, chunks: list[Chunk]) -> list[tuple[int, int]]:
    """Each chunk's span in the decoded source text (Plan 01B 4.4), ordered and non-overlapping.

    ``Chunk.start``/``end`` keep indexing the spoken (prepared) text, and seeds keep hashing the spoken chunk text, so a
    document without edits keeps identical chunks and seeds. The source span is derived through the verified structure
    and normalization maps; a span that runs backwards or outside the source is a defect and fails the plan.
    """
    source_map = prepared.source_map()
    spans = [source_map.source_span(chunk.start, chunk.end) for chunk in chunks]
    previous_end, limit = 0, len(prepared.normalized.source)
    for chunk, (start, end) in zip(chunks, spans):
        if start < previous_end or end <= start or end > limit:
            raise ChunkPlanError(f"chunk {chunk.index} maps to source span {start}-{end}, out of order")
        previous_end = end
    return spans


def derive_seed(voice_id: str, chunk: Chunk) -> int:
    """Stable per-chunk seed: the same voice, position and words always give the same seed, on any machine."""
    text_hash = hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
    digest = hashlib.sha256(f"{SEED_BASE}|{voice_id}|{chunk.index}|{text_hash}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF


# --------------------------------------------------------------------------- #
# Assembly: native-rate PCM joined with the configured pauses, then ONE encode
# --------------------------------------------------------------------------- #
class AssemblyError(RuntimeError):
    pass


def validate_chunk_audio(audio, sample_rate: int, expected_rate: Optional[int]) -> np.ndarray:
    """One chunk as mono float32, or an error: nothing is flattened, resampled or guessed."""
    arr = np.asarray(audio)
    if arr.ndim != 1:
        raise AssemblyError(f"a chunk has shape {arr.shape}; a mono waveform is required")
    if arr.size == 0:
        raise AssemblyError("a chunk is empty")
    if not np.isfinite(arr).all():
        raise AssemblyError("a chunk contains non-finite samples")
    if int(sample_rate) <= 0:
        raise AssemblyError(f"a chunk has an invalid sample rate {sample_rate!r}")
    if expected_rate is not None and int(sample_rate) != int(expected_rate):
        raise AssemblyError(f"the sample rate changed within one file ({expected_rate} -> {sample_rate})")
    return arr.astype("float32", copy=False)


def assemble(chunk_audio: list[np.ndarray], sample_rate: int, *, chunk_pause_ms: int,
             end_silence_ms: int) -> tuple[np.ndarray, dict]:
    """Join the chunks and return the PCM plus an exact accounting.

    The policy is the local-engine one (v0.7.0 Q1): the paragraph pause goes *between* rendered chunks and nothing
    follows the last one. Silence is built at the model's own rate, so the configured pauses are exact sample counts.
    No normalisation, crossfade, trimming or denoise here; the final-tail policy runs at publication.

    ``end_silence_ms`` is a retained internal/diagnostic argument: production (:func:`qwen3_file_to_mp3`) always passes
    0, so no closing pause can reach a published MP3 through this function.
    """
    if not chunk_audio:
        raise AssemblyError("there is nothing to assemble")
    gap = np.zeros(int(sample_rate * max(chunk_pause_ms, 0) / 1000.0), dtype="float32")
    end = np.zeros(int(sample_rate * max(end_silence_ms, 0) / 1000.0), dtype="float32")
    pieces: list[np.ndarray] = []
    for i, arr in enumerate(chunk_audio):
        if i and gap.size:
            pieces.append(gap)
        pieces.append(arr)
    if end.size:
        pieces.append(end)
    out = np.concatenate(pieces)
    speech = sum(int(a.size) for a in chunk_audio)
    report = {
        "sample_rate": int(sample_rate), "chunks": len(chunk_audio), "speech_samples": speech,
        "gap_samples": int(gap.size), "end_silence_samples": int(end.size), "total_samples": int(out.size),
    }
    if out.size != speech + gap.size * (len(chunk_audio) - 1) + end.size:  # internal consistency, never expected to fire
        raise AssemblyError("the assembled length does not match the planned length")
    return out, report


def _raise_if_cancelled(cancel_check: Optional[Callable[[], bool]]) -> None:
    if cancel_check is not None and cancel_check():
        raise ConversionCancelled("Conversion cancelled by user.")


def encode_mp3(wav_path: Path, mp3_path: Path, bitrate: Optional[str], *, work_dir: Path,
               cancel_check: Optional[Callable[[], bool]] = None, ffmpeg: Optional[str] = None) -> None:
    """Encode one WAV to MP3 with the app's pinned ffmpeg and the shared MP3 contract (format, codec, bitrate).

    ffmpeg is run directly, not through pydub, for two reasons that both come from keeping the user's narration
    contained: pydub makes its own temporary files in the system temp folder and leaves them behind when an encode
    fails, and it holds the output file open inside a traceback, so a failed encode cannot even remove its own
    partial file on Windows. Here every scratch file lives in ``work_dir`` and a cancel request stops the encode.
    """
    options = ffmpeg_utils.mp3_export_options(bitrate)  # one definition of the MP3 contract, shared with every engine
    try:
        executable = ffmpeg or ffmpeg_utils.ffmpeg_cmd()
    except ffmpeg_utils.FFmpegUnavailable as exc:
        raise Qwen3Failed(f"The MP3 could not be encoded: {exc}") from exc
    command = [executable, "-y", "-nostdin", "-loglevel", "error", "-f", "wav", "-i", str(wav_path),
               "-f", options["format"], "-codec:a", options["codec"], "-b:a", options["bitrate"], str(mp3_path)]
    stderr_path = work_dir / "ffmpeg-stderr.txt"
    with open(stderr_path, "w", encoding="utf-8") as stderr_file:
        proc = qwen3_process.spawn(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=stderr_file, cwd=str(work_dir))
        try:
            while proc.poll() is None:
                _raise_if_cancelled(cancel_check)
                time.sleep(0.1)
        except BaseException:
            qwen3_process.kill_tree(proc)
            raise
        finally:
            qwen3_process.release(proc)
    if proc.returncode != 0:
        raise Qwen3Failed(f"The MP3 could not be encoded (ffmpeg exit code {proc.returncode}). "
                          f"{_tail(stderr_path)}".strip())


def publish_mp3(arr: np.ndarray, sample_rate: int, output_path: str | Path, bitrate: Optional[str] = None, *,
                work_dir: Path, cancel_check: Optional[Callable[[], bool]] = None,
                encoder: Callable = encode_mp3, log: Optional[Callable[[str], None]] = None) -> None:
    """Write the assembled PCM as the one and only lossy generation, and publish it atomically.

    The WAV and the MP3 are made inside ``work_dir`` (the job folder, which is always removed). The finished MP3 is
    copied beside the destination under a temporary name and moved into place only when complete, so a failure never
    leaves a partial file and never damages one that was already there. Cancellation is checked after the encode and
    again immediately before the move: a Cancel pressed at any point before the file is published wins.

    The v0.7.0 final-tail policy (:mod:`tts.audio_tail`) runs first, on the finished PCM, exactly as it does in the
    other local engines' one encode.
    """
    destination = Path(output_path)
    wav, mp3 = work_dir / "encode.wav", work_dir / "encode.mp3"
    tail = audio_tail.apply_final_tail_policy(arr, sample_rate)
    if log is not None:
        log(f"  {tail.summary()}")
    sf.write(str(wav), tail.pcm, sample_rate)  # 16-bit PCM, what the other local engines hand to their encoder
    encoder(wav, mp3, bitrate, work_dir=work_dir, cancel_check=cancel_check)
    _raise_if_cancelled(cancel_check)
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_name(destination.name + f".{uuid.uuid4().hex[:8]}.part")
    try:
        shutil.copyfile(mp3, part)
        _raise_if_cancelled(cancel_check)
        os.replace(part, destination)
    finally:
        part.unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# The job and the worker run
# --------------------------------------------------------------------------- #
def build_job(voice: rt.Qwen3Voice, chunks: list[Chunk], *, job_dir: Path, model_dir: Path,
              reference_text: str = "", device: str = "auto", reference_wav: Optional[Path] = None) -> dict:
    """Everything the worker needs, as plain data. Pure: touches no disk.

    ``reference_wav`` is the verified snapshot of the clone's reference recording inside the job folder
    (:func:`snapshot_reference`); it defaults to the bundled path only so the job shape can be inspected in tests.
    """
    job = {
        "schema": 1, "kind": "synth", "voice_id": voice.voice_id, "mode": voice.kind,
        "model_dir": str(model_dir), "language": LANGUAGE, "dtype": DTYPE, "attn": ATTENTION, "device": device,
        "out_dir": str(job_dir / "chunks"), "cancel_file": str(job_dir / "cancel"),
        "engine_lock": str(rt.engine_lock_path()),
        "chunks": [{"index": c.index, "text": c.text, "seed": derive_seed(voice.voice_id, c)} for c in chunks],
    }
    if voice.kind == rt.KIND_PRESET:
        job["speaker"] = voice.speaker
    else:
        job["reference_wav"] = str(reference_wav if reference_wav is not None else rt.reference_path(voice))
        job["reference_text"] = reference_text
        job["generation"] = dict(CLONE_GENERATION)  # the worker forwards exactly these to generate_voice_clone
    return job


#: Stop a worker and everything it started, even when its launcher has already exited (see ``qwen3_process``).
kill_process_tree = qwen3_process.kill_tree


def snapshot_reference(voice: rt.Qwen3Voice, job_dir: Path) -> Path:
    """Copy a clone's reference recording into the job folder and prove the COPY is the approved recording.

    The worker is handed the copy, never the pathname into the repository, so the bytes it clones from are exactly
    the bytes that were verified: replacing the bundled file while the model loads cannot substitute a different voice
    under the old approval. The copy lives in the job folder and is removed with it.
    """
    source = rt.reference_path(voice)
    snapshot = job_dir / "reference.wav"
    try:
        shutil.copyfile(source, snapshot)
    except OSError as exc:
        raise Qwen3Unavailable(f"Setup required for {voice.label}: its reference recording could not be read ({exc}).") from exc
    if rt.sha256_file(snapshot) != voice.reference_sha256:
        raise Qwen3Unavailable(
            f"The reference recording '{rt.reference_path(voice).name}' does not match the one {voice.label} was approved "
            "against, so it will not be used.")
    try:
        pad_reference_tail(snapshot)  # only after the copy has been proved to be the approved recording
    except (OSError, RuntimeError) as exc:
        raise Qwen3Unavailable(f"Setup required for {voice.label}: its reference recording could not be prepared ({exc}).") from exc
    return snapshot


def pad_reference_tail(path: Path, seconds: float = CLONE_REFERENCE_TAIL_SILENCE_S) -> None:
    """Append ``seconds`` of digital silence to a WAV in place, keeping its sample rate, channels and sample format."""
    info = sf.info(str(path))
    audio, rate = sf.read(str(path), dtype="float32", always_2d=True)
    padded = np.concatenate([audio, np.zeros((int(round(rate * seconds)), audio.shape[1]), dtype="float32")])
    sf.write(str(path), padded, rate, subtype=info.subtype, format=info.format)


def _tail(path: Path, limit: int = STDERR_TAIL_CHARS) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-limit:].strip()
    except OSError:
        return ""


def parse_event(line: str) -> Optional[dict]:
    """A worker event, or ``None`` for any other line (library noise) and for a malformed event."""
    if not line.startswith("@@EVENT "):
        return None
    try:
        event = json.loads(line[len("@@EVENT "):])
    except ValueError:
        return {"event": "_malformed", "raw": line[:200]}
    return event if isinstance(event, dict) and isinstance(event.get("event"), str) else {
        "event": "_malformed", "raw": line[:200]}


@dataclass
class WorkerRun:
    terminal: dict
    chunk_events: list[dict]
    loaded: dict
    returncode: int


def run_worker(job: dict, job_dir: Path, *, python: Path, script: Path, env: dict,
               cancel_check: Optional[Callable[[], bool]] = None, log: Callable[[str], None] = print,
               on_chunk: Optional[Callable[[int, int], None]] = None,
               grace_s: float = CANCEL_GRACE_S, event_timeout_s: float = EVENT_TIMEOUT_S,
               exit_grace_s: float = EXIT_GRACE_S, kill_wait_s: float = KILL_WAIT_S,
               kill: Callable[[subprocess.Popen], None] = qwen3_process.kill_tree) -> WorkerRun:
    """Run one worker to completion under supervision.

    Contract: the worker emits exactly one terminal event (``done``, ``failed`` or ``canceled``) and, for ``done``,
    then exits with status 0. Anything else — an exit without a result, a malformed or repeated result, a stall, a
    ``done`` followed by a crash or a hang in shutdown — is a failed file with a message and the worker's own stderr
    tail. A cancel request becomes ``ConversionCancelled`` after the worker has stopped or been killed.

    Every deadline (the stall watchdog, the cancel grace period, the shutdown window) is evaluated on **every** pass of
    the loop, so a worker that floods its output cannot postpone being stopped, and only protocol events — not
    ordinary library output — count as progress.
    """
    job_path = job_dir / "job.json"
    job_path.write_text(json.dumps(job), encoding="utf-8")
    stderr_path = job_dir / "worker-stderr.txt"
    cancel_flag = Path(job["cancel_file"])
    cancel_flag.unlink(missing_ok=True)

    lines: "queue.Queue[Optional[str]]" = queue.Queue()
    with open(stderr_path, "w", encoding="utf-8") as stderr_file:
        try:
            proc = qwen3_process.spawn(
                [str(python), str(script), str(job_path)], require_job=True, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=stderr_file, text=True, encoding="utf-8", errors="replace", env=env,
                cwd=str(job_dir))
        except qwen3_process.ContainmentUnavailable as exc:
            raise Qwen3Failed(
                "The Qwen3 voice engine was not started: Windows would not let this app keep control of it, so it "
                f"could not be stopped safely if you cancelled. ({exc})") from exc

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
        terminal_at: Optional[float] = None
        cancel_requested_at: Optional[float] = None
        last_progress = time.monotonic()
        killed_at: Optional[float] = None
        try:
            while True:
                now = time.monotonic()
                if cancel_requested_at is not None:
                    if killed_at is None and now - cancel_requested_at > grace_s:
                        kill(proc)
                        killed_at = now
                elif terminal_at is not None:
                    if killed_at is None and now - terminal_at > exit_grace_s:
                        kill(proc)  # it reported a result but will not exit: do not wait forever, and do not trust it
                        killed_at = now
                elif now - last_progress > event_timeout_s:
                    kill(proc)
                    raise Qwen3Failed(
                        f"The Qwen3 voice engine stopped responding and was stopped. {_tail(stderr_path)}".strip())
                if killed_at is not None and now - killed_at > kill_wait_s:
                    break  # the final deadline: the pipe never closed after the kill, so stop waiting for it
                try:
                    line = lines.get(timeout=0.2)
                except queue.Empty:
                    line = ""
                if line is None:
                    break
                if line:
                    event = parse_event(line)
                    if event is None:
                        log(f"  [qwen3] {line[:300]}")  # library output: shown, but not proof the worker is alive
                    else:
                        last_progress = time.monotonic()
                        if event["event"] == "_malformed":
                            raise Qwen3Failed("The Qwen3 voice engine sent an unreadable message and was stopped.")
                        if event["event"] == "loaded":
                            loaded = event
                            log(_loaded_message(event))
                        elif event["event"] == "chunk":
                            chunk_events.append(event)
                            log(f"  Qwen3 chunk {int(event.get('index', 0)) + 1}/{event.get('of')} "
                                f"({event.get('audio_s')} s of audio in {event.get('gen_s')} s)")
                            if on_chunk is not None:
                                on_chunk(len(chunk_events), int(event.get("of") or len(chunk_events)))
                        elif event["event"] in ("done", "failed", "canceled"):
                            if terminal is not None:
                                raise Qwen3Failed("The Qwen3 voice engine reported more than one result.")
                            terminal, terminal_at = event, time.monotonic()
                if cancel_requested_at is None and cancel_check is not None and cancel_check():
                    cancel_requested_at = time.monotonic()
                    cancel_flag.write_text("cancel", encoding="utf-8")
        except BaseException:
            kill(proc)
            raise
        finally:
            # Bounded shutdown: nothing below can wait forever on a worker or on the pipe it holds.
            if proc.poll() is None:
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    kill(proc)
            reader.join(timeout=5)
            if reader.is_alive():  # something still holds the pipe open: stop the whole tree so the read ends
                kill(proc)
                reader.join(timeout=5)
            if not reader.is_alive() and proc.stdout is not None:
                proc.stdout.close()
            qwen3_process.release(proc)
    returncode = proc.returncode if proc.returncode is not None else -1
    if cancel_requested_at is not None:
        raise ConversionCancelled("Conversion cancelled by user.")
    if terminal is None:
        raise Qwen3Failed(
            "The Qwen3 voice engine ended unexpectedly "
            f"(exit code {returncode}).{_detail(_tail(stderr_path))}")
    if terminal["event"] == "done" and returncode != 0:
        raise Qwen3Failed(
            "The Qwen3 voice engine reported success but then did not exit cleanly "
            f"(exit code {returncode}), so its audio was discarded.{_detail(_tail(stderr_path))}")
    return WorkerRun(terminal=terminal, chunk_events=chunk_events, loaded=loaded, returncode=returncode)


def _detail(text: str) -> str:
    return f" {text}" if text else ""


def _loaded_message(event: dict) -> str:
    device = str(event.get("device", ""))
    name = event.get("device_name") or "unknown device"
    if device.startswith("cuda"):
        return f"Qwen3 is running on the GPU: {name}."
    return "Qwen3 is running on the CPU (no usable NVIDIA GPU), which is much slower."


def failure_message(terminal: dict) -> str:
    """A user-fit sentence for a worker ``failed`` event."""
    stage = terminal.get("stage")
    detail = str(terminal.get("message") or "no further detail")
    if stage == "engine":  # the worker refused to start (in use, or moved with a repair); its sentence is the message
        return detail
    if terminal.get("oom"):
        return ("The Qwen3 voice ran out of memory. Close other programs that use the GPU (or memory) and try "
                f"again. ({detail})")
    where = {"load": "loading the model", "prepare": "preparing the voice", "generate": "generating speech",
             "import": "starting the voice engine", "worker": "running"}.get(stage, "running")
    message = f"The Qwen3 voice engine failed while {where}: {detail}"
    if stage == "import" or detail.startswith(("ImportError", "ModuleNotFoundError")):
        # A package of the engine will not import: a damaged install, not a passing problem. Readiness is decided from
        # the engine's identity and install record, so only the engine's own check finds this; say where it is.
        message += (" The engine's installed packages look damaged: choose \"Install / repair Qwen3 voices...\" "
                    "and then \"Check and repair\".")
    return message


# --------------------------------------------------------------------------- #
# Job folders
# --------------------------------------------------------------------------- #
def new_job_dir(root: Optional[Path] = None) -> Path:
    base = rt.ensure_runtime_dir(rt.jobs_root()) if root is None else Path(root)
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
    """Remove job folders left behind by a crash. Returns how many were removed."""
    base = rt.ensure_runtime_dir(rt.jobs_root()) if root is None else Path(root)  # never walk (and delete in) a link
    if not base.is_dir():
        return 0
    removed = 0
    cutoff = time.time() - max_age_s
    for child in base.iterdir():
        try:
            if child.is_dir() and child.stat().st_mtime < cutoff:
                remove_job_dir(child)
                removed += 1
        except OSError:
            continue
    return removed


def record_failure(job_dir: Path, message: str) -> None:
    """Keep the last failure's worker stderr for diagnosis. Holds no job text beyond what a traceback quotes."""
    try:
        target = rt.runtime_dir() / "last-failure.txt"
        rt.ensure_runtime_dir(target.parent)
        stderr = _tail(job_dir / "worker-stderr.txt", 6000)
        rt.atomic_write_text(target, f"{time.strftime('%Y-%m-%d %H:%M:%S')}\n{message}\n\n{stderr}\n")
    except (OSError, rt.Qwen3Unavailable):
        pass


# --------------------------------------------------------------------------- #
# The entry point
# --------------------------------------------------------------------------- #
def qwen3_file_to_mp3(
    source_path: str,
    output_mp3_path: str,
    voice_id: str,
    end_silence_ms: int = 0,
    chunk_pause_ms: int = 700,
    log: Callable[[str], None] = print,
    cancel_check: Optional[Callable[[], bool]] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    bitrate: Optional[str] = None,
    device: str = "auto",
    *,
    speech_prep=None,
    availability: Callable[[str], tuple[bool, str]] = rt.voice_availability,
    python: Optional[Path] = None,
    script: Optional[Path] = None,
    jobs_root: Optional[Path] = None,
    env: Optional[dict] = None,
    encoder: Callable = encode_mp3,
    grace_s: float = CANCEL_GRACE_S,
    event_timeout_s: float = EVENT_TIMEOUT_S,
    exit_grace_s: float = EXIT_GRACE_S,
    kill_wait_s: float = KILL_WAIT_S,
) -> None:
    """Read plain text from a file -> Qwen3 worker -> one MP3.

    Same shape as ``chatterbox_file_to_mp3`` so the GUI treats every local engine alike. ``progress_callback(done,
    total)`` fires after each chunk on the calling (worker) thread. Cancellation raises ``ConversionCancelled`` and is
    honoured at every stage up to the instant the file is published; no partial MP3 is left and an existing
    destination is not touched until the new file is complete.

    The keyword-only seams (``python``, ``script``, ``jobs_root``, ``env``, ``encoder``, ``availability``) exist for
    the offline tests; production passes none of them.

    **No closing pause (v0.7.0 Q1).** ``chunk_pause_ms`` separates chunks and nothing follows the last one.
    ``end_silence_ms`` is retained only so existing callers keep working; whatever is passed, no closing silence is
    added. The final-tail policy then shortens the model's own trailing near-silence.
    """
    src = Path(source_path)
    if not src.exists():
        raise FileNotFoundError(f"Source text file not found: {source_path}")
    voice = rt.get_voice(voice_id)

    ok, reason = availability(voice_id)  # authoritative, asked again here: the answer can change after selection
    if not ok:
        raise Qwen3Unavailable(reason)

    # Held for the whole conversion: an install or repair of this copy cannot replace the environment or models under a
    # running worker (this installation's file lock), and no other copy of the app on the computer can load a Qwen3
    # model at the same time (the machine-wide named mutex, rt.MachineGuard).
    with rt.inference_lease():
        # Speech preparation (Plan 01B A3) runs on the decoded source before the structure stage. ``speech_prep`` is the
        # run's frozen snapshot; None or "off" leaves the text, the plan and every seed exactly as before.
        prepared = prepare(read_source_text(src), speech_prep, QWEN3_ROUTE)
        for line in prepared.details():
            log(line)
        if prepared.enabled:
            log(f"Qwen3 pipeline revision {pipeline_revision(speech_prep)}")
        text = prepared.text
        if not text:
            raise ValueError("No text content found after parsing source file.")
        chunks = plan_chunks(text)
        if prepared.enabled:
            chunk_source_spans(prepared, chunks)  # proves every chunk maps back to the decoded source, in order

        reference_text = ""
        if voice.kind == rt.KIND_CLONE:
            transcript = rt.load_transcript(voice_id)
            if not transcript.ok:  # re-checked at the moment of use; there is no transcript-free fallback
                raise Qwen3Unavailable(f"Setup required for {voice.label}: {transcript.reason}.")
            reference_text = transcript.text

        model_dir = rt.model_spec(voice.model_key).directory
        py = Path(python) if python is not None else rt.venv_python()
        worker = Path(script) if script is not None else rt.worker_script()
        cleanup_stale_jobs(jobs_root)
        job_dir = new_job_dir(jobs_root)
        try:
            reference = snapshot_reference(voice, job_dir) if voice.kind == rt.KIND_CLONE else None
            log(f"Qwen3: synthesizing {len(chunks)} chunk(s) in {voice.label}...")
            if voice.kind == rt.KIND_CLONE:
                log(f"Qwen3 clone generation profile {CLONE_GENERATION_REVISION}: temperature {CLONE_GENERATION['temperature']:.2f}, "
                    f"sub-talker {CLONE_GENERATION['subtalker_temperature']:.2f}, reference tail silence "
                    f"{CLONE_REFERENCE_TAIL_SILENCE_S:.1f} s")
            job = build_job(voice, chunks, job_dir=job_dir, model_dir=model_dir, reference_text=reference_text,
                            device=device, reference_wav=reference)
            run = run_worker(job, job_dir, python=py, script=worker,
                             env=rt.worker_environment() if env is None else env, cancel_check=cancel_check, log=log,
                             on_chunk=progress_callback, grace_s=grace_s, event_timeout_s=event_timeout_s,
                             exit_grace_s=exit_grace_s, kill_wait_s=kill_wait_s)
            terminal = run.terminal
            if terminal["event"] == "canceled":
                raise ConversionCancelled("Conversion cancelled by user.")
            if terminal["event"] == "failed":
                raise Qwen3Failed(failure_message(terminal))
            _raise_if_cancelled(cancel_check)

            audio, rate = _collect_chunks(job_dir / "chunks", run.chunk_events, len(chunks))
            _raise_if_cancelled(cancel_check)
            log("  Assembling Qwen3 audio...")
            pcm, report = assemble(audio, rate, chunk_pause_ms=chunk_pause_ms, end_silence_ms=0)
            _raise_if_cancelled(cancel_check)
            publish_mp3(pcm, rate, output_mp3_path, bitrate, work_dir=job_dir, cancel_check=cancel_check, encoder=encoder,
                        log=log)
            log(f"Qwen3: saved -> {output_mp3_path} ({report['speech_samples'] / rate:.1f} s of speech)")
        except Qwen3Failed as exc:
            record_failure(job_dir, str(exc))
            raise
        finally:
            remove_job_dir(job_dir)


def _collect_chunks(chunk_dir: Path, chunk_events: list[dict], expected: int) -> tuple[list[np.ndarray], int]:
    """Read every chunk back in plan order and validate it; the files, not the events, are the evidence."""
    by_index = {int(e["index"]): e for e in chunk_events if "index" in e}
    if sorted(by_index) != list(range(expected)):
        raise Qwen3Failed(f"The Qwen3 voice engine reported {len(by_index)} of {expected} chunks.")
    audio: list[np.ndarray] = []
    rate: Optional[int] = None
    for index in range(expected):
        path = chunk_dir / str(by_index[index].get("wav", ""))
        if not path.is_file():
            raise Qwen3Failed(f"Qwen3 chunk {index + 1} was reported but its audio file is missing.")
        try:
            data, file_rate = sf.read(str(path), dtype="float32", always_2d=False)
            audio.append(validate_chunk_audio(data, file_rate, rate))
        except (AssemblyError, RuntimeError, OSError, ValueError) as exc:
            raise Qwen3Failed(f"Qwen3 chunk {index + 1} could not be used: {exc}") from exc
        rate = int(file_rate)
    return audio, int(rate)
