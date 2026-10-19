"""Evaluation core for the Plan 01 voice comparison (dev-only; never imported by the app).

Pure Python plus numpy and no engine import, so the orchestrator (root interpreter), the Qwen
worker (isolated evaluation interpreter) and the Chatterbox/Kokoro baseline worker (root
interpreter) all share one definition of a row ID, a chunk plan, a join and a manifest.

Everything here is mechanical evidence. Nothing in this module judges a voice: human listening
is the only authority, and a technically clean recording is never "approved".
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
WORK_DIR = REPO_ROOT / "files" / "dev-work" / "qwen3-eval"
DEFAULT_RUN_ID = "qwen3-initial"

# --------------------------------------------------------------------------- #
# Identities: the closed inventory the plan requires (27 short rows, 4 long rows)
# --------------------------------------------------------------------------- #
GROUP_QWEN_PRESET = "qwen-preset"
GROUP_QWEN_CLONE = "qwen-clone"
GROUP_CHATTERBOX = "chatterbox"
GROUP_KOKORO = "kokoro"
GROUPS = (GROUP_QWEN_PRESET, GROUP_QWEN_CLONE, GROUP_CHATTERBOX, GROUP_KOKORO)

# (display name, upstream native language). Synthesised in English, no style instruction.
QWEN_PRESETS: tuple[tuple[str, str], ...] = (
    ("Aiden", "English"),
    ("Dylan", "Chinese (Beijing dialect)"),
    ("Eric", "Chinese (Sichuan dialect)"),
    ("Ono_Anna", "Japanese"),
    ("Ryan", "English"),
    ("Serena", "Chinese"),
    ("Sohee", "Korean"),
    ("Uncle_Fu", "Chinese"),
    ("Vivian", "Chinese"),
)

# Verbatim from the pinned CustomVoice model card (Apache-2.0), shown only to help the listener choose.
# "female"/"male" below is the card's own wording, not a judgement made here.
QWEN_PRESET_DESCRIPTIONS: dict[str, str] = {
    "Vivian": "Bright, slightly edgy young female voice.",
    "Serena": "Warm, gentle young female voice.",
    "Uncle_Fu": "Seasoned male voice with a low, mellow timbre.",
    "Dylan": "Youthful Beijing male voice with a clear, natural timbre.",
    "Eric": "Lively Chengdu male voice with a slightly husky brightness.",
    "Ryan": "Dynamic male voice with strong rhythmic drive.",
    "Aiden": "Sunny American male voice with a clear midrange.",
    "Ono_Anna": "Playful Japanese female voice with a light, nimble timbre.",
    "Sohee": "Warm Korean female voice with rich emotion.",
}
assert {n for n, _ in QWEN_PRESETS} == set(QWEN_PRESET_DESCRIPTIONS)


def is_female_preset(display: str) -> bool:
    """Per the model card's own description of the preset."""
    return " female " in f" {QWEN_PRESET_DESCRIPTIONS.get(display, '').lower()} "


# (display name, production Chatterbox voice_id, source file). The reference path and SHA-256
# are read from chatterbox_synth.REFERENCE_VOICES at run time, never duplicated here.
REFERENCE_VOICE_IDS: tuple[tuple[str, str], ...] = (
    ("Female-1", "chatterbox-female-1"),
    ("Female-2", "chatterbox-female-2"),
    ("Male-1", "chatterbox-male-1"),
    ("Male-2", "chatterbox-male-2"),
    ("Male-3", "chatterbox-male-3"),
    ("Male-4", "chatterbox-male-4"),
)

# (voice id, ACT status, Kokoro pipeline lang_code). A closed set: not every upstream voice.
KOKORO_VOICES: tuple[tuple[str, str, str], ...] = (
    ("am_michael", "existing", "a"),
    ("bm_george", "existing", "b"),
    ("am_fenrir", "candidate", "a"),
    ("am_puck", "candidate", "a"),
    ("am_onyx", "candidate", "a"),
    ("bm_daniel", "candidate", "b"),
)

STATUSES = ("pending", "blocked", "running", "succeeded", "failed", "canceled")
TERMINAL_STATUSES = ("succeeded", "failed", "canceled", "blocked")


def _row(row_id: str, suite: str, group: str, engine: str, display: str, voice_id: str, **extra) -> dict:
    row = {
        "row_id": row_id, "suite": suite, "group": group, "engine": engine,
        "display": display, "voice_id": voice_id, "status": "pending", "status_reason": "",
        "human_review": "needs-listening", "attempts": [],
    }
    row.update(extra)
    return row


def preset_row_id(display: str, suite: str = "short") -> str:
    prefix = "" if suite == "short" else "long-"
    return f"{prefix}qwen-preset-{display.lower().replace('_', '-')}"


def clone_row_id(display: str, suite: str = "short") -> str:
    prefix = "" if suite == "short" else "long-"
    return f"{prefix}qwen-clone-{display.lower()}"


def short_rows() -> list[dict]:
    """The exactly-27 predeclared short rows, in listening-index order."""
    rows: list[dict] = []
    for display, native in QWEN_PRESETS:
        rows.append(_row(preset_row_id(display), "short", GROUP_QWEN_PRESET, "qwen3-tts-customvoice",
                         display, display.lower(), language="English", native_language=native))
    for display, voice_id in REFERENCE_VOICE_IDS:
        rows.append(_row(clone_row_id(display), "short", GROUP_QWEN_CLONE, "qwen3-tts-base",
                         display, voice_id, language="English", reference_name=display,
                         paired_with=voice_id))
    for display, voice_id in REFERENCE_VOICE_IDS:
        rows.append(_row(voice_id, "short", GROUP_CHATTERBOX, "chatterbox-turbo", display, voice_id,
                         paired_with=clone_row_id(display)))
    for voice_id, act_status, lang in KOKORO_VOICES:
        rows.append(_row(f"kokoro-{voice_id}", "short", GROUP_KOKORO, "kokoro-82m", voice_id, voice_id,
                         act_status=act_status, lang_code=lang, speed=1.0))
    assert len(rows) == 27 and len({r["row_id"] for r in rows}) == 27
    return rows


def long_row(group: str, display: str) -> dict:
    """One sustained row; only built from a recorded owner selection (or the required two presets)."""
    if group == GROUP_QWEN_PRESET:
        native = dict(QWEN_PRESETS).get(display)
        if native is None:
            raise ValueError(f"unknown Qwen preset {display!r}")
        return _row(preset_row_id(display, "long"), "long", group, "qwen3-tts-customvoice", display,
                    display.lower(), language="English", native_language=native)
    if group == GROUP_QWEN_CLONE:
        voice_id = dict(REFERENCE_VOICE_IDS).get(display)
        if voice_id is None:
            raise ValueError(f"unknown clone reference {display!r}")
        return _row(clone_row_id(display, "long"), "long", group, "qwen3-tts-base", display, voice_id,
                    language="English", reference_name=display)
    raise ValueError(f"no long-form row for group {group!r}")


# --------------------------------------------------------------------------- #
# Seeds and identity hashes
# --------------------------------------------------------------------------- #
SEED_BASE = 20261018

#: Bump deliberately whenever a change can alter generated audio (chunking, seeding, generation calls, assembly,
#: joins). It is part of every result's identity, so a bump makes finished rows stale; edits to reporting, the ASR
#: check or the index deliberately do not.
PIPELINE_REVISION = 1


def derive_seed(row_id: str, chunk_index: int, attempt: int = 1, base: int = SEED_BASE) -> int:
    """Stable per-row/per-chunk/per-attempt seed: same inputs, same seed, on any machine."""
    digest = hashlib.sha256(f"{base}|{row_id}|{chunk_index}|{attempt}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF


def identity_hash(parts: dict) -> str:
    """Hash of everything that must match for a recorded result to be reusable."""
    blob = json.dumps(parts, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def sha256_file(path: Path, block: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(block):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------------- #
# Qwen chunk plan with ordered source spans
# --------------------------------------------------------------------------- #
DEFAULT_MAX_CHARS = 600


class ChunkPlanError(RuntimeError):
    """The plan could not be built or did not preserve its source text."""


@dataclass(frozen=True)
class Chunk:
    index: int
    start: int  # offset of the first source character in the canonical text
    end: int  # exclusive
    text: str  # effective text handed to the engine: source words, single-space separated
    boundary: str  # what follows this chunk: sentence | clause | word | paragraph | end
    paragraph: int

    def to_dict(self) -> dict:
        d = asdict(self)
        d["chars"] = len(self.text)
        d["sha256"] = hashlib.sha256(self.text.encode("utf-8")).hexdigest()
        return d


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


def _is_sentence_end(word: str, next_word: str | None) -> bool:
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
            raise ChunkPlanError(f"unsplittable token of {size} characters exceeds the {max_chars}-character ceiling")
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
    for match in re.finditer(r"\n[ \t\r\f\v]*\n\s*", text):
        spans.append((pos, match.start()))
        pos = match.end()
    spans.append((pos, len(text)))
    return [(s, e) for s, e in spans if text[s:e].strip()]


def plan_chunks(text: str, max_chars: int = DEFAULT_MAX_CHARS) -> list[Chunk]:
    """Ordered chunks of whole sentences, never crossing a paragraph or title boundary.

    Every chunk carries the exact source span it came from. Sentences are packed greedily up to
    ``max_chars``; an over-long sentence is cut at clause punctuation, then at a word boundary,
    and only there. The plan is verified against the source before it is returned.
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
        is_last_paragraph = p_index == len(paragraphs) - 1
        merged[-1][2] = "end" if is_last_paragraph else "paragraph"
        for u_lo, u_hi, boundary in merged:
            chunks.append(Chunk(
                index=len(chunks), start=spans[u_lo][0], end=spans[u_hi - 1][1],
                text=" ".join(words[u_lo:u_hi]), boundary=boundary, paragraph=p_index,
            ))
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
    planned = "".join("".join(c.text.split()) for c in chunks)
    if planned != "".join(text.split()):
        raise ChunkPlanError("the chunk plan did not preserve its source text")


def plan_hash(chunks: list[Chunk]) -> str:
    blob = json.dumps([(c.start, c.end, c.text, c.boundary) for c in chunks], ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Assembly: native-rate PCM joined before the single MP3 encode
# --------------------------------------------------------------------------- #
GAP_MS = 50  # after every chunk, exactly as the local engines do
END_SILENCE_MS = 3000


class AssemblyError(RuntimeError):
    pass


def assemble(chunk_audio: list[np.ndarray], sample_rate: int, boundaries: list[str] | None = None,
             gap_ms: int = GAP_MS, end_silence_ms: int = END_SILENCE_MS) -> tuple[np.ndarray, dict]:
    """Concatenate chunks with the configured silence; return the PCM and an exact join report.

    No normalisation, crossfade, trimming or denoise. A chunk that is empty, non-finite or not
    one-dimensional stops the assembly instead of producing audio that merely looks complete.
    """
    if not chunk_audio:
        raise AssemblyError("no chunks to assemble")
    gap = np.zeros(int(sample_rate * gap_ms / 1000.0), dtype="float32")
    end = np.zeros(int(sample_rate * end_silence_ms / 1000.0), dtype="float32")
    pieces: list[np.ndarray] = []
    joins: list[dict] = []
    cursor = 0
    for index, audio in enumerate(chunk_audio):
        arr = np.asarray(audio, dtype="float32")
        if arr.ndim != 1 or arr.size == 0:
            raise AssemblyError(f"chunk {index} is empty or not mono (shape {arr.shape})")
        if not np.isfinite(arr).all():
            raise AssemblyError(f"chunk {index} contains non-finite samples")
        pieces.append(arr)
        joins.append({
            "chunk": index, "start_sample": cursor, "end_sample": cursor + arr.size,
            "start_s": round(cursor / sample_rate, 3), "end_s": round((cursor + arr.size) / sample_rate, 3),
            "gap_samples": int(gap.size), "boundary": boundaries[index] if boundaries else None,
        })
        cursor += arr.size
        if gap.size:
            pieces.append(gap)
            cursor += gap.size
    if end.size:
        pieces.append(end)
    out = np.concatenate(pieces)
    speech = sum(int(np.asarray(a).size) for a in chunk_audio)
    report = {
        "sample_rate": sample_rate, "gap_ms": gap_ms, "end_silence_ms": end_silence_ms,
        "gap_samples": int(gap.size), "end_silence_samples": int(end.size),
        "total_samples": int(out.size), "speech_samples": speech,
        "inserted_samples": int(out.size) - speech, "joins": joins,
    }
    verify_assembly(report, [int(np.asarray(a).size) for a in chunk_audio])
    return out, report


def verify_assembly(report: dict, chunk_lengths: list[int]) -> None:
    expected = sum(chunk_lengths) + report["gap_samples"] * len(chunk_lengths) + report["end_silence_samples"]
    if expected != report["total_samples"]:
        raise AssemblyError(f"assembled {report['total_samples']} samples, expected {expected}")
    if report["speech_samples"] != sum(chunk_lengths):
        raise AssemblyError("speech sample count does not match the chunks")


def write_wav(path: Path, arr: np.ndarray, sample_rate: int, float_chunk: bool = False,
              base: Path | None = None) -> dict:
    """Write native-rate lossless audio and return what was written.

    Final recordings are 16-bit PCM (what the local engines hand to the MP3 encoder). Raw chunks,
    and any recording that exceeds full scale, are written as 32-bit float so nothing is clipped
    or normalised to make a check pass.
    """
    import soundfile as sf

    data = np.asarray(arr, dtype="float32")
    over = bool(data.size and np.max(np.abs(data)) > 1.0)
    subtype = "FLOAT" if (float_chunk or over) else "PCM_16"
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), data, sample_rate, subtype=subtype)
    shown = path.relative_to(base).as_posix() if base is not None else path.name
    return {"path": shown, "subtype": subtype, "sample_rate": sample_rate, "samples": int(data.size),
            "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    import soundfile as sf

    data, rate = sf.read(str(path), dtype="float32", always_2d=False)
    return data, int(rate)


# --------------------------------------------------------------------------- #
# Measurement and mechanical warnings (never a verdict)
# --------------------------------------------------------------------------- #
SILENCE_DB = -50
SILENCE_WINDOW_S = 0.05
PATHOLOGICAL_SILENCE_S = 4.0
CHARS_PER_SECOND = (8.0, 25.0)  # same plausibility band as the repository's final-acceptance harness
CHUNK_CHARS_PER_SECOND = (5.0, 35.0)
FULL_SCALE = 32767 / 32768


def longest_silence(arr: np.ndarray, sample_rate: int, floor_db: float = SILENCE_DB) -> tuple[float, float]:
    """(duration_s, start_s) of the longest run of 50 ms windows below ``floor_db`` RMS."""
    window = max(1, int(sample_rate * SILENCE_WINDOW_S))
    count = arr.size // window
    if count == 0:
        return 0.0, 0.0
    frames = arr[: count * window].reshape(count, window).astype("float64")
    quiet = np.sqrt(np.mean(frames * frames, axis=1)) < 10 ** (floor_db / 20.0)
    best = run = best_start = start = 0
    for i, is_quiet in enumerate(quiet):
        if is_quiet:
            if run == 0:
                start = i
            run += 1
            if run > best:
                best, best_start = run, start
        else:
            run = 0
    return round(best * window / sample_rate, 3), round(best_start * window / sample_rate, 3)


def measure_samples(arr: np.ndarray, sample_rate: int) -> dict:
    a = np.asarray(arr, dtype="float32")
    if a.size == 0:
        return {"samples": 0, "duration_s": 0.0}
    peak = float(np.max(np.abs(a)))
    rms = float(np.sqrt(np.mean(a.astype("float64") ** 2)))
    silence_s, silence_at = longest_silence(a, sample_rate)
    return {
        "samples": int(a.size), "duration_s": round(a.size / sample_rate, 3),
        "peak": round(peak, 6), "peak_dbfs": round(20 * np.log10(peak), 2) if peak > 0 else None,
        "rms_dbfs": round(20 * np.log10(rms), 2) if rms > 0 else None,
        "clipped_samples": int(np.count_nonzero(np.abs(a) >= FULL_SCALE)),
        "over_full_scale_samples": int(np.count_nonzero(np.abs(a) > 1.0)),
        "longest_silence_s": silence_s, "longest_silence_at_s": silence_at,
    }


def mechanical_warnings(chunks: list[Chunk], chunk_audio: list[np.ndarray], sample_rate: int,
                        target_seconds: tuple[int, int] | None = None,
                        completed_chunks: int | None = None) -> list[str]:
    """Plain-language flags for a human to look at. An empty list means "nothing mechanical found"."""
    warnings: list[str] = []
    expected = len(chunks)
    done = len(chunk_audio) if completed_chunks is None else completed_chunks
    if done != expected:
        warnings.append(f"incomplete: {done} of {expected} chunks rendered")
    speech = 0
    for chunk, audio in zip(chunks, chunk_audio):
        seconds = len(audio) / sample_rate
        speech += len(audio)
        if seconds <= 0:
            warnings.append(f"chunk {chunk.index} is empty")
            continue
        cps = len(chunk.text) / seconds
        low, high = CHUNK_CHARS_PER_SECOND
        if not low <= cps <= high:
            warnings.append(f"chunk {chunk.index}: {cps:.1f} chars/s outside {low}-{high} (possible truncation or runaway)")
        silence_s, silence_at = longest_silence(np.asarray(audio, dtype="float32"), sample_rate)
        if silence_s >= PATHOLOGICAL_SILENCE_S:
            warnings.append(f"chunk {chunk.index}: {silence_s:.1f}s near-silence at {silence_at:.1f}s")
    speech_s = speech / sample_rate
    if speech_s > 0:
        cps = sum(len(c.text) for c in chunks) / speech_s
        low, high = CHARS_PER_SECOND
        if not low <= cps <= high:
            warnings.append(f"overall {cps:.1f} chars/s outside {low}-{high}")
        if target_seconds and not target_seconds[0] <= speech_s <= target_seconds[1]:
            warnings.append(f"audible duration {speech_s:.1f}s outside the {target_seconds[0]}-{target_seconds[1]}s target")
    clipped = sum(int(np.count_nonzero(np.abs(np.asarray(a)) >= FULL_SCALE)) for a in chunk_audio)
    if clipped:
        warnings.append(f"{clipped} samples at or above full scale (not normalised)")
    return warnings


# --------------------------------------------------------------------------- #
# ASR read-back comparison (advisory only: it can flag, it can never prove or approve)
# --------------------------------------------------------------------------- #
ASR_METHOD = "whisper-small.en/silence-aligned-28s"
ASR_SEGMENT_S = 28.0


def silence_split(samples: np.ndarray, sample_rate: int, max_s: float = ASR_SEGMENT_S,
                  search_s: float = 10.0) -> list[tuple[int, int]]:
    """Cut points for transcribing long audio: each piece <= ``max_s``, cut inside the quietest 20 ms window found
    in the last ``search_s`` seconds, so no word is split. Whisper's fixed 30 s windows drop words at their edges."""
    total, limit = int(samples.size), int(max_s * sample_rate)
    frame = max(1, int(0.02 * sample_rate))
    spans, start = [], 0
    while total - start > limit:
        lo = start + limit - int(search_s * sample_rate)
        hi = start + limit
        window = np.abs(np.asarray(samples[lo:hi], dtype="float32"))
        count = window.size // frame
        energy = window[: count * frame].reshape(count, frame).mean(axis=1)
        cut = lo + int(np.argmin(energy)) * frame + frame // 2
        spans.append((start, cut))
        start = cut
    spans.append((start, total))
    return spans


ASR_MIN_COVERAGE = 0.85
ASR_EDGE_WORDS = 12  # the first and last dozen words must be mostly heard: a clipped start or end
ASR_EDGE_MIN = 0.4  # names are often misheard, so only a mostly-missing edge is flagged
_WORD = re.compile(r"[a-z0-9']+")


def normalize_words(text: str) -> list[str]:
    return _WORD.findall(text.lower().replace("\u2019", "'"))


def asr_compare(reference: str, hypothesis: str) -> dict:
    """How much of the canonical text a speech recogniser heard back, plus head and tail checks.

    Invented names and numerals legitimately differ, so this only flags gross omissions; it never
    decides that narration is correct.
    """
    ref, hyp = normalize_words(reference), normalize_words(hypothesis)
    matcher = difflib.SequenceMatcher(None, ref, hyp, autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    missing = [" ".join(ref[i1:i2]) for tag, i1, i2, _, _ in matcher.get_opcodes() if tag in ("delete", "replace")]
    heard = [False] * len(ref)
    for block in matcher.get_matching_blocks():
        for k in range(block.a, block.a + block.size):
            heard[k] = True
    edge = ASR_EDGE_WORDS
    head_ok = bool(ref) and sum(heard[:edge]) / len(heard[:edge]) >= ASR_EDGE_MIN
    tail_ok = bool(ref) and sum(heard[-edge:]) / len(heard[-edge:]) >= ASR_EDGE_MIN
    coverage = round(matched / len(ref), 4) if ref else 0.0
    return {"coverage": coverage, "reference_words": len(ref), "heard_words": len(hyp), "head_ok": head_ok,
            "tail_ok": tail_ok, "missing_spans": missing[:25],
            "flagged": coverage < ASR_MIN_COVERAGE or not head_ok or not tail_ok}


# --------------------------------------------------------------------------- #
# Atomic manifest with retained attempts
# --------------------------------------------------------------------------- #
def atomic_write_text(path: Path, text: str, retries: int = 20) -> None:
    """Write beside the target then replace, so an interruption never leaves a half manifest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    for attempt in range(retries):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:  # a Windows viewer or scanner briefly holding the target
            if attempt == retries - 1:
                raise
            time.sleep(0.1)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


class Manifest:
    """``manifest.jsonl``: one JSON row per line, rewritten atomically after every change."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.rows: dict[str, dict] = {}
        if self.path.is_file():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    self.rows[row["row_id"]] = row

    def save(self) -> None:
        atomic_write_text(self.path, "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                                             for r in self.rows.values()))

    def declare(self, rows: list[dict]) -> None:
        """Add predeclared rows without disturbing any row that already has recorded state."""
        for row in rows:
            self.rows.setdefault(row["row_id"], row)
        self.save()

    def get(self, row_id: str) -> dict:
        return self.rows[row_id]

    def update(self, row_id: str, **fields) -> dict:
        row = self.rows[row_id]
        if "status" in fields and fields["status"] not in STATUSES:
            raise ValueError(f"unknown status {fields['status']!r}")
        row.update(fields)
        row["updated"] = now_iso()
        self.save()
        return row

    def retire_attempt(self, row_id: str, reason: str) -> None:
        """Move the current result into ``attempts`` so a rerun never overwrites its evidence."""
        row = self.rows[row_id]
        if row["status"] == "pending":
            return
        keep = {k: row.get(k) for k in ("status", "status_reason", "identity", "outputs", "warnings",
                                        "started", "finished", "wall_s") if k in row}
        keep["retired_because"] = reason
        row["attempts"].append(keep)
        for key in ("outputs", "warnings", "identity", "started", "finished", "wall_s", "measurements",
                    "joins", "chunk_results"):
            row.pop(key, None)
        row["status"], row["status_reason"] = "pending", ""
        self.save()


def outputs_intact(row: dict, base: Path) -> bool:
    """True when every recorded output still exists with its recorded size and hash."""
    outputs = row.get("outputs") or {}
    if not outputs:
        return False
    for info in outputs.values():
        path = base / info["path"]
        if not path.is_file() or path.stat().st_size != info["bytes"] or sha256_file(path) != info["sha256"]:
            return False
    return True


def can_resume(row: dict, identity: str, base: Path) -> bool:
    """A succeeded row is reused only when its identity matches and its files are intact."""
    return row.get("status") == "succeeded" and row.get("identity") == identity and outputs_intact(row, base)


# --------------------------------------------------------------------------- #
# Worker event protocol (stdout lines) and child environment
# --------------------------------------------------------------------------- #
EVENT_PREFIX = "@@EVENT "


def emit(event: dict) -> None:
    sys.stdout.write(EVENT_PREFIX + json.dumps(event, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def parse_event(line: str) -> dict | None:
    if not line.startswith(EVENT_PREFIX):
        return None
    try:
        event = json.loads(line[len(EVENT_PREFIX):])
    except json.JSONDecodeError:
        return None
    return event if isinstance(event, dict) and "event" in event else None


def eval_python(work_dir: Path = WORK_DIR) -> Path:
    """Absolute interpreter of the isolated evaluation venv (never resolved from PATH)."""
    scripts = work_dir / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    return scripts / ("python.exe" if os.name == "nt" else "python")


def root_python(repo_root: Path = REPO_ROOT) -> Path:
    """Absolute interpreter of the repository's root ``.venv`` (Chatterbox and Kokoro run here)."""
    scripts = repo_root / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    return scripts / ("python.exe" if os.name == "nt" else "python")


def child_env(kind: str, base: dict | None = None, work_dir: Path = WORK_DIR, offline: bool = False) -> dict:
    """Environment for a worker subprocess: every cache and temp path inside the repository.

    ``kind`` is ``"qwen"`` (isolated venv: caches under the evaluation work area) or ``"root"``
    (Chatterbox/Kokoro: the existing in-tree model cache is kept, only temp/analytics change).
    The user's global environment is never modified.
    """
    env = dict(os.environ if base is None else base)
    temp = str(work_dir / "temp")
    env.update(TEMP=temp, TMP=temp, TMPDIR=temp, PYTHONNOUSERSITE="1", PYTHONIOENCODING="utf-8",
               GRADIO_ANALYTICS_ENABLED="False", HF_HUB_DISABLE_TELEMETRY="1", DO_NOT_TRACK="1",
               PYTHONUNBUFFERED="1")
    if kind == "qwen":
        cache = work_dir / "cache"
        env.update(HF_HOME=str(cache / "hf"), TORCH_HOME=str(cache / "torch"),
                   NUMBA_CACHE_DIR=str(cache / "numba"), XDG_CACHE_HOME=str(cache / "xdg"),
                   XDG_CONFIG_HOME=str(cache / "xdg"))
        for stale in ("HUGGINGFACE_HUB_CACHE", "HF_HUB_CACHE", "TRANSFORMERS_CACHE"):
            env.pop(stale, None)
    elif kind != "root":
        raise ValueError(f"unknown child kind {kind!r}")
    if offline:
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    return env
