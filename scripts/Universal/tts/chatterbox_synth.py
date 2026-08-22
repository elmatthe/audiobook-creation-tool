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
import re
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

#: The most text one ``ChatterboxTurboTTS.generate()`` call may ever receive.
#:
#: **This is not a tuning knob and it must never be raised.** Three independent
#: pieces of evidence fix it, two of them read off the pinned artifact itself:
#:
#: 1. ``chatterbox/models/t3/t3.py`` caps generation at
#:    ``inference_turbo(..., max_gen_len=1000)`` speech tokens, and
#:    ``chatterbox/models/s3tokenizer`` runs at ``S3_TOKEN_RATE = 25`` tokens per
#:    second. **One call can emit at most 40 seconds of audio, ever**, and
#:    ``generate()`` never overrides that cap.
#: 2. ``chatterbox/tts_turbo.py`` tokenizes with ``truncation=True``, so text past
#:    the limit is dropped in silence rather than refused — the failure is
#:    invisible to the caller, which is exactly how it reached a shipped run.
#: 3. Upstream's own Turbo demo (``gradio_tts_turbo_app.py`` on
#:    resemble-ai/chatterbox master) labels its input box
#:    *"Text to synthesize (max chars 300)"*, and ``example_tts_turbo.py`` uses a
#:    240-character string.
#:
#: Measured on HOME-PC against the real Female 1 reference, healthy synthesis runs
#: at ~16 characters per audio-second, so 300 characters is ~19 seconds — about
#: half the 40-second hard cap, leaving headroom for unusually dense text.
#:
#: v0.6.1 Plan 4 Phase 10 routed this engine through
#: ``kokoro_synth.split_into_chunks`` and its 3,000-character default. The Phase 12
#: manual matrix converted three real chapters that way: all three reported
#: success and all three were unintelligible. A 2,889-character chunk produced
#: **3.84 seconds** of audio where its text needed ~181 — 2.1% of the content,
#: silently. Kokoro's 3,000 is correct for Kokoro and is deliberately unchanged.
CHATTERBOX_MAX_CHUNK_CHARS = 300

# --------------------------------------------------------------------------- #
# Generation tuning — one place, explicit values
#
# Added by the v0.6.1 Plan 4 Phase 12 manual-feedback pass. Until now every call
# site was a bare ``model.generate(text)``, so the effective parameters were
# whatever the pinned wheel happened to default to and were invisible in this
# repository. The values below are **byte-identical to those defaults** (a test
# asserts that against the installed signature), so this centralization changes
# no behaviour — it only makes the settings visible and adjustable in one place.
#
# What Turbo actually honours, read off ``chatterbox/tts_turbo.py``:
#
#   generate() ignores ``exaggeration``, ``cfg_weight`` and ``min_p`` outright —
#   it logs "CFG, min_p and exaggeration are not supported by Turbo version and
#   will be ignored" if any is non-zero. They are therefore NOT tuning knobs here
#   and are deliberately absent below.
#
#   **Exaggeration is inert on Turbo by both routes.** It is tempting to assume the
#   expressiveness control simply moved to ``prepare_conditionals(exaggeration=…)``
#   -> ``T3Cond.emotion_adv``. It did not. ``tts_turbo.py`` builds its T3 config
#   with ``hp.emotion_adv = False``, so ``cond_enc.py``'s ``if self.hp.emotion_adv``
#   branch never runs and the value is dropped from the conditioning entirely —
#   ``prepare_conditionals`` still stores it, but nothing consumes it. Measured
#   directly during the Phase 12 manual-feedback pass: rebuilding Female 1's
#   conditional at 0.35 instead of 0.5 and regenerating the same text under a fixed
#   seed produced **byte-identical audio** (max absolute sample difference 0.0).
#
#   So **temperature is the only working expressiveness/stability lever** on this
#   model. Do not offer exaggeration as a knob; it would be a placebo.
# --------------------------------------------------------------------------- #

#: Softmax temperature — **the only generation control Turbo actually honours**
#: that affects delivery. Lower is steadier: less prosodic variation and more
#: consistent pronunciation of unusual proper nouns, at the cost of some liveliness.
#: Upstream documents the useful range as 0.5–1.5.
#:
#: **0.72 is the maintainer's chosen value**, picked on 2026-08-16 from a
#: fixed-seed A/B/C set at 0.8 / 0.72 / 0.65 on real chapter text — *"best
#: sounding one in my opinion"* — and the value at which they confirmed
#: ``Ascended`` is pronounced correctly. It is deliberately a small step down from
#: the 0.8 the wheel defaults to, because the request was for slightly calmer
#: delivery, not a flat read.
GENERATION_TEMPERATURE = 0.72

#: The temperature the four **approved Phase 9 listening WAVs** were produced at.
#:
#: Those files are the evidence the four registered voices were approved on, and
#: they were generated before the Phase 12 tuning existed. ``--chatterbox-eval``
#: reproduces that historical contract rather than current production, so a later
#: re-run can still be compared against the approved audio. Ordinary QA samples
#: deliberately do *not* use this — they follow :data:`GENERATION_TEMPERATURE` so
#: they describe the engine as actually shipped.
PHASE9_EVALUATION_TEMPERATURE = 0.8

#: Nucleus sampling. Lower trims the improbable tail.
GENERATION_TOP_P = 0.95

#: Top-k filtering.
GENERATION_TOP_K = 1000

#: Penalty against token repetition.
GENERATION_REPETITION_PENALTY = 1.2

#: The ``exaggeration`` passed to ``prepare_conditionals``. Kept explicit only so
#: the value is visible and matches the wheel's own default.
#:
#: **This is NOT a working control on Turbo** — see the block above:
#: ``hp.emotion_adv = False`` means the conditioning encoder discards it, and
#: changing it was measured to produce byte-identical audio. It is recorded here
#: so a future reader does not rediscover that the hard way.
#:
#: NOTE: :func:`identity_digest` does **not** include this value. That is
#: currently harmless because the value is inert and has never varied. If a later
#: Chatterbox release makes it meaningful, it MUST be added to the digest —
#: otherwise a conditional cached at the old value would be silently reused and
#: the change would appear to do nothing.
REFERENCE_EXAGGERATION = 0.5


def generation_params(**overrides) -> dict:
    """The generation keywords current production passes to ``generate()``.

    One dict, so no call site can quietly drift — the Phase 12 investigation had
    to prove the evaluation path and the audiobook path matched, and that is only
    cheap to prove while there is exactly one source of truth.
    """
    params = {
        "temperature": GENERATION_TEMPERATURE,
        "top_p": GENERATION_TOP_P,
        "top_k": GENERATION_TOP_K,
        "repetition_penalty": GENERATION_REPETITION_PENALTY,
    }
    params.update(overrides)
    return params


def phase9_evaluation_params() -> dict:
    """Current production settings, but at the historical Phase 9 temperature.

    Only the temperature differs (a test enforces that), so the historical
    listening contract is reproduced without freezing an entire stale parameter
    set that would silently miss a future correction to the others.
    """
    return generation_params(temperature=PHASE9_EVALUATION_TEMPERATURE)


# --------------------------------------------------------------------------- #
# Prose colons
#
# The maintainer heard "Chapter 3008: Beautiful Dream." read too hurriedly and
# asked for "only a fraction of a second" more after the colon.
#
# A text-only fix is impossible, and that was proven rather than assumed:
# ``chatterbox.tts.punc_norm`` replaces EVERY ":" with "," before tokenisation,
# so the model never sees a colon at all. Spacing variants
# ("3008 :", "3008:  ", "3008:\n\n") all normalise to the identical comma string.
# The pause therefore has to come from assembly.
#
# A prose colon is defined as **a colon followed by whitespace**. That single rule
# excludes every non-prose form by construction, because none of them has
# whitespace after the colon: "12:30", "01:02:03", "3:1", "10:9", "https://",
# "ftp://". No URL scheme list and no digit lookaround is needed, which is why
# this rule is preferred over anything cleverer.
# --------------------------------------------------------------------------- #

#: Extra silence inserted at a prose colon, in milliseconds.
#:
#: **75 ms is the maintainer's chosen value**, picked on 2026-08-16 from a
#: 0 / 75 / 125 ms listening set. 125 ms was explicitly not selected. This is
#: additional to nothing — it is the whole pause, inserted inside a chunk, so it
#: does not interact with ``chunk_pause_ms`` between chunks.
COLON_PAUSE_MS = 75

#: Split points: whitespace that immediately follows a colon.
_PROSE_COLON = re.compile(r"(?<=:)\s+")


def split_at_prose_colon(text: str) -> list[str]:
    """Split ``text`` at prose colons, keeping every colon and every word.

    Returns ``[text]`` unchanged when there is no prose colon, so the ordinary
    case costs one regex and allocates nothing extra. The colon stays attached to
    the end of the segment before it — it is never deleted, and the model renders
    it as the comma-length break it always did; the inserted silence supplies the
    rest.
    """
    parts = [part for part in _PROSE_COLON.split(text) if part.strip()]
    return parts if len(parts) > 1 else [text]


# --------------------------------------------------------------------------- #
# Text boundaries
#
# Added by the v0.6.1 Plan 4 Phase 12 uncontrolled-silence remediation.
#
# **The defect.** A real chapter narrated by Male 1 held an 8.73-second silence at
# 2:36.9 and five more between 2.2 s and 2.5 s. Measurement showed every configured
# pause was correct — the 25 inter-chunk gaps were the configured 700 ms, the
# terminal gap the configured end silence — and that *none* of the long silences
# sat at a chunk join. Every one was inside a single ``generate()`` call.
#
# The old sentence rule was ``(?<=[.!?])\s+``: the character immediately before the
# whitespace had to be a terminator. Dialogue does not look like that. A spoken line
# ends ``."`` / ``?"`` / ``!"`` — **the closing quote comes after the terminator** —
# so a line break after dialogue was not a sentence boundary, and a single ``\n`` is
# not a paragraph boundary either. In that chapter **17 raw newlines** were handed
# straight to the model, which renders one as a pause of no fixed length.
#
# **The rule now.** A sentence ends at a terminator, optionally followed by closing
# quotes or brackets, followed by whitespace, followed by something that does not
# continue the sentence. The closing-punctuation idea is taken from the Web Novel
# Editor's ``rules/spacing_cleanup.py`` (``[.!?…]["'’”)\]]*$``), which faces the same
# corpus. That repository was read as a **design reference only** — no code is
# shared, imported or vendored, and there is no dependency on it.
#
# The lower-case lookahead is the same repository's paragraph-reconstruction
# heuristic. It stops ``"My job here... is done?"`` from being cut at the ellipsis:
# a boundary there would put a 700 ms inter-chunk pause in the middle of a spoken
# sentence, which is the very artefact this remediation exists to remove.
# --------------------------------------------------------------------------- #

#: Closing punctuation allowed between a terminator and the whitespace after it.
_CLOSERS = "\"'’”‘“)\\]»"

#: A sentence boundary: terminator, optional closers, whitespace, and a next
#: character that does not continue the sentence. Matched rather than used in a
#: lookbehind because Python requires those to be fixed width.
_SENTENCE_BOUNDARY = re.compile(
    rf"[.!?…][{_CLOSERS}]*\s+(?=[^a-z\s])")

#: A blank line — the paragraph boundary a narrator would honour anyway.
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")

#: Level 3. Tried in order, and only ever on a sentence that is *already* over the
#: ceiling — an ordinary sentence is never cut at a comma. Each pattern consumes
#: the delimiter and the whitespace after it, so the delimiter stays attached to
#: the clause it closes and nothing is deleted.
#:
#: The colon sits below the semicolon deliberately. A colon that survives *inside*
#: a chunk still reaches :func:`split_at_prose_colon` and still earns its
#: :data:`COLON_PAUSE_MS`; promoting it here would turn that 75 ms into the 700 ms
#: inter-chunk pause. At this level the sentence is over 300 characters and has no
#: semicolon, so the trade is worth taking — but only there.
_CLAUSE_BOUNDARIES = (
    re.compile(r";\s+"),
    re.compile(r":\s+"),
    re.compile(r"[—–]\s*"),
    re.compile(r",\s+"),
)


class ChunkPlanError(RuntimeError):
    """A chunk plan did not preserve its source text.

    Raised rather than returned. Narration that silently loses a clause is worse
    than a run that stops and says so — the Phase 10 lesson, where a 2,889-character
    chunk was truncated to 2.1% of its content *and reported success*.
    """


def _normalize_whitespace(text: str) -> str:
    """Collapse every whitespace run to one space.

    This is where the newline contract is actually enforced. A line break that
    survived sentence splitting is a layout wrap inside one continuing sentence —
    formatting, not an instruction — so it becomes the space a narrator would read.
    After this, no structural newline can reach ``generate()``.
    """
    return " ".join(text.split())


def _split_after(text: str, pattern: re.Pattern[str]) -> list[str]:
    """Split at each match, keeping the matched delimiter on the left piece."""
    pieces: list[str] = []
    start = 0
    for match in pattern.finditer(text):
        piece = text[start:match.end()].strip()
        if piece:
            pieces.append(piece)
        start = match.end()
    tail = text[start:].strip()
    if tail:
        pieces.append(tail)
    return pieces


def _split_sentences(paragraph: str) -> list[str]:
    """One paragraph into whitespace-normalised sentences."""
    return [_normalize_whitespace(piece)
            for piece in _split_after(paragraph, _SENTENCE_BOUNDARY)]


def _hard_slice(token: str, max_chars: int) -> list[str]:
    """Last resort for text with no usable break at all.

    Concatenating the result reproduces the input exactly, so a pathological
    unbroken string still loses nothing.
    """
    return [token[i:i + max_chars] for i in range(0, len(token), max_chars)]


def _pack_words(sentence: str, max_chars: int) -> list[str]:
    """Split one over-long sentence on whitespace, then on nothing if it must."""
    pieces: list[str] = []
    current = ""
    for word in sentence.split():
        if len(word) > max_chars:
            if current:
                pieces.append(current)
                current = ""
            pieces.extend(_hard_slice(word, max_chars))
            continue
        candidate = f"{current} {word}" if current else word
        if len(candidate) <= max_chars:
            current = candidate
        else:
            pieces.append(current)
            current = word
    if current:
        pieces.append(current)
    return pieces


def _split_oversized(text: str, max_chars: int, level: int = 0) -> list[str]:
    """One over-long sentence into units, descending the hierarchy as forced.

    Level 3 (clause) is tried one delimiter at a time, then level 4 (whitespace)
    and level 5 (hard slice) via :func:`_pack_words`. Descent stops the moment a
    piece fits, so an ordinary sentence is never chopped at a comma.
    """
    if len(text) <= max_chars:
        return [text]
    if level < len(_CLAUSE_BOUNDARIES):
        parts = _split_after(text, _CLAUSE_BOUNDARIES[level])
        if len(parts) > 1:
            units: list[str] = []
            for part in parts:
                units.extend(_split_oversized(part, max_chars, level + 1))
            return units
        return _split_oversized(text, max_chars, level + 1)
    return _pack_words(text, max_chars)


def _assert_content_preserved(source: str, chunks: list[str]) -> None:
    """Every non-whitespace character, in order, or the plan is refused.

    The invariant is borrowed in principle from the Web Novel Editor's
    ``ai/chunking.py``, which refuses to return a plan whose pieces cannot rebuild
    its input. Byte-exact reassembly is the wrong test here — this splitter is
    *allowed* to normalise structural whitespace, and must, because that is how the
    newline contract is kept. So whitespace is disregarded and everything else is
    compared exactly: a dropped word, a duplicated clause, a lost full stop or a
    reordered paragraph all fail.

    It also guards the boundary code specifically. Repeated ``strip()`` is the
    ordinary way punctuation quietly disappears at a chunk edge.
    """
    planned = "".join("".join(chunk.split()) for chunk in chunks)
    original = "".join(source.split())
    if planned != original:
        raise ChunkPlanError(
            "the Chatterbox chunk plan did not preserve its source text "
            f"({len(original)} characters in, {len(planned)} out)")


def split_for_chatterbox(
    text: str, max_chars: int = CHATTERBOX_MAX_CHUNK_CHARS,
) -> list[str]:
    """Split ``text`` into pieces no longer than ``max_chars``, for Turbo.

    Deliberately **not** ``kokoro_synth.split_into_chunks``. The two engines have
    incompatible input scales — see :data:`CHATTERBOX_MAX_CHUNK_CHARS` — and
    sharing one splitter is what produced the Phase 12 unintelligibility defect.
    Kokoro's splitter and its 3,000-character ceiling stay exactly as they are.

    **The hierarchy**, descended only as far as the ceiling forces:

    1. **paragraph** — a blank line. Never crossed, even when two paragraphs would
       fit together, because a paragraph break is meaning rather than layout.
    2. **sentence** — a terminator, optional closing quotes or brackets, then
       whitespace. This is the level the Phase 12 silence defect lived at.
    3. **clause** — semicolon, colon, dash, comma, in that order, and *only* for a
       single sentence that is already over the ceiling.
    4. **whitespace** — the nearest word boundary.
    5. **hard limit** — only for a single token with no boundary in it at all.

    **Units are then packed**, not emitted one per sentence. Each chunk boundary
    earns a configured inter-chunk pause, so one sentence per chunk would read as
    machine-gun narration with a gap after every full stop. Consecutive units are
    joined up to the ceiling instead, and a new chunk starts only when the next
    unit would not fit or a paragraph ends.

    **The newline contract.** No structural newline reaches ``generate()``: a break
    after a completed sentence becomes a boundary, and one inside a continuing
    sentence becomes an ordinary space. Nothing is dropped, nothing is duplicated,
    order is preserved, no empty chunk is emitted, and the plan is checked against
    its source before it is returned.
    """
    if not text.strip():
        return []

    chunks: list[str] = []
    for paragraph in _PARAGRAPH_BREAK.split(text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        units: list[str] = []
        for sentence in _split_sentences(paragraph):
            units.extend(_split_oversized(sentence, max_chars))

        current = ""
        for unit in units:
            candidate = f"{current} {unit}" if current else unit
            if len(candidate) <= max_chars:
                current = candidate
                continue
            if current:
                chunks.append(current)
            current = unit
        if current:
            chunks.append(current)

    _assert_content_preserved(text, chunks)
    return chunks


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


#: Memo for :func:`voice_availability` **only**. Keyed by voice id, holding the
#: source recording's identity as the filesystem reports it. Never consulted by
#: anything on the conversion path.
_AVAILABILITY_MEMO: dict[str, tuple[object, bool, str]] = {}


def _source_stamp(path: Path):
    """``(size, mtime_ns)`` for a source recording, or ``None`` if it is not there.

    Cheap enough to ask on every dropdown refresh, and it changes whenever the file
    is replaced, edited, truncated or removed — which is exactly when the memo below
    must be discarded.
    """
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_size, stat.st_mtime_ns)


def voice_availability(voice_id: str) -> tuple[bool, str]:
    """``(ok, reason)`` cheap enough for a GUI to ask on every voice selection.

    The same answer :func:`engine_status` gives, memoised per process against the
    source recording's ``(size, mtime_ns)``. Added in Phase 10 as the *one* seam a
    GUI needs: without it a dropdown refresh would re-hash a 33 MB recording every
    time, and with it the panel still needs to know nothing about hashes,
    derivative filenames, the manifest format or conditionals.

    Deliberately does none of the expensive or destructive things: it loads no
    model, downloads no weights, synthesizes nothing, writes nothing and creates no
    derivative. It is also **not** a substitute for verification — every real use
    still goes through :func:`resolve_reference`, which re-checks the full SHA-256
    on the conversion path exactly as it always has. A memo miss simply means the
    full check runs again.
    """
    ok, reason = package_status()
    if not ok:
        return False, reason
    try:
        get_reference_voice(voice_id)
    except ChatterboxUnavailable as exc:
        return False, str(exc)

    stamp = _source_stamp(reference_source_path(voice_id))
    cached = _AVAILABILITY_MEMO.get(voice_id)
    if cached is not None and cached[0] == stamp:
        return cached[1], cached[2]
    ok, reason = reference_status(voice_id)
    _AVAILABILITY_MEMO[voice_id] = (stamp, ok, reason)
    return ok, reason


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
    """Trace label → source → full source SHA-256 → derivative → parameters.

    The conditional cache path is recorded alongside them even before that file
    exists: it is derived deterministically from the same identity digest, so
    naming it here keeps one manifest that accounts for every artefact a voice
    produces, rather than a second one listing the other half.
    """
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
        "conditionals_path": str(
            conditionals_path(voice.voice_id, voice.source_sha256)),
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
    if not dest.is_file():
        log(f"Chatterbox: preparing a {REFERENCE_WINDOW_SECONDS}s reference clip "
            f"for {voice.label}…")
        build_reference_clip(source, dest)
    # Recorded on every call, not only on a rebuild: a derivative cached by an
    # earlier run would otherwise leave the manifest permanently incomplete.
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
    model.prepare_conditionals(str(clip), exaggeration=REFERENCE_EXAGGERATION)
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


def _synthesize_chunk(model, chunk: str, cancel_check=None) -> np.ndarray:
    """Render one chunk, honouring prose colons with a short explicit pause.

    **The chunk stays one unit of work.** A colon is punctuation, not a source
    file and not a progress step, so splitting here must not change the run's
    accounting: the caller still sees exactly one chunk, reports one progress
    tick for it, and the frozen queue is untouched. All that changes is that the
    chunk may take more than one ``generate()`` call internally, joined by
    :data:`COLON_PAUSE_MS` of silence.

    The join is plain PCM concatenation before the chunk is ever encoded, so the
    existing WAV→MP3→merge assembly is completely unchanged — no extra encode
    generation is introduced by this feature.

    ``cancel_check`` is consulted between colon segments as well as between
    chunks. That can only make cancellation more responsive, never less.
    """
    segments = split_at_prose_colon(chunk)
    if len(segments) == 1:
        return _audio_array(model.generate(chunk, **generation_params()))

    gap = np.zeros(int(model.sr * COLON_PAUSE_MS / 1000.0), dtype="float32")
    rendered: list[np.ndarray] = []
    for segment in segments:
        if cancel_check is not None and cancel_check():
            from shared.cancellation import ConversionCancelled

            raise ConversionCancelled("Conversion cancelled by user.")
        piece = _audio_array(model.generate(segment, **generation_params()))
        if piece.size == 0:
            continue
        if rendered:
            rendered.append(gap)
        rendered.append(piece)
    return np.concatenate(rendered) if rendered else np.zeros(0, dtype="float32")


def _export_mp3(arr: np.ndarray, sample_rate: int, output_path: str,
                bitrate: str | None = None) -> None:
    """Write assembled PCM out as the one and only lossy generation.

    The contract comes from :func:`shared.ffmpeg_utils.mp3_export_options` rather
    than from ffmpeg's defaults — see that module for why a defaulted export
    produced files whose advertised duration was half their real length.
    """
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_wav:
        tmp_wav_path = tmp_wav.name
    try:
        sf.write(tmp_wav_path, arr, sample_rate)
        AudioSegment.from_wav(tmp_wav_path).export(
            output_path, **ffmpeg_utils.mp3_export_options(bitrate))
    finally:
        Path(tmp_wav_path).unlink(missing_ok=True)


def generation_defaults() -> dict:
    """The pinned wheel's own ``generate()`` defaults, read off its signature.

    Reported, never overridden: this module passes no generation keyword at all,
    so these *are* the effective parameters. Introspecting beats transcribing —
    a value copied into a docstring would drift silently on the next pin.
    """
    import inspect

    from chatterbox.tts_turbo import ChatterboxTurboTTS

    return {
        name: parameter.default
        for name, parameter in inspect.signature(
            ChatterboxTurboTTS.generate).parameters.items()
        if parameter.default is not inspect.Parameter.empty
    }


def synthesize_text_to_wav(
    text: str,
    output_path: str,
    voice_id: str,
    log: Callable[[str], None] = print,
    device: str | None = None,
    generation: dict | None = None,
) -> int:
    """Synthesize ``text`` in the cloned voice ``voice_id`` straight to a WAV.

    The same path as ``synthesize_text_to_mp3`` up to the point of writing, minus
    the lossy encode: the returned waveform is written at the model's own sample
    rate. Returns that sample rate so a caller can report what was actually used
    rather than assuming it. Added for the Phase 9 listening evaluation, which
    must not judge the engine through an MP3 encoder.

    ``generation`` defaults to current production settings. The Phase 9
    evaluation command passes :func:`phase9_evaluation_params` instead, so it
    keeps reproducing the historical contract the approved WAVs were made under
    rather than silently re-rendering the approval evidence at a newer
    temperature.
    """
    _assert_writable_destination(output_path)
    model = _get_model(device)
    load_conditionals(model, voice_id, log=log, device=device)
    arr = _audio_array(model.generate(
        text, **(generation_params() if generation is None else generation)))
    if arr.size == 0:
        raise ChatterboxUnavailable(
            f"Chatterbox produced no audio for voice '{voice_id}'.")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    sf.write(output_path, arr, model.sr)
    return model.sr


def synthesize_text_to_mp3(
    text: str,
    output_path: str,
    voice_id: str,
    log: Callable[[str], None] = print,
    device: str | None = None,
    bitrate: str | None = None,
) -> None:
    """Synthesize ``text`` in the cloned voice ``voice_id`` to an MP3.

    Generation parameters are left at the pinned release's own defaults. Turbo
    ignores ``cfg_weight``/``exaggeration``/``min_p`` (it warns if they are set), so
    this deliberately exposes no quality knobs the model does not honour.

    ``bitrate`` reaches the same single explicit encode the batch path uses, so
    this internal entry point cannot drift into producing a differently-shaped
    MP3 from the one an audiobook run produces.
    """
    model = _get_model(device)
    load_conditionals(model, voice_id, log=log, device=device)
    arr = _audio_array(model.generate(text, **generation_params()))
    if arr.size == 0:
        raise ChatterboxUnavailable(
            f"Chatterbox produced no audio for voice '{voice_id}'.")
    _export_mp3(arr, model.sr, output_path, bitrate)


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
    bitrate: str | None = None,
) -> None:
    """Read plain text from file → Chatterbox Turbo → single MP3.

    Same shape as ``kokoro_file_to_mp3`` so the GUI worker treats all engines alike.
    ``progress_callback(done, total)`` fires after each chunk on the calling
    (worker) thread — a GUI caller must enqueue from it, never touch Tk directly.
    Cancellation is honoured **between** chunks: a generation already in flight is
    allowed to finish rather than being torn down mid-inference.

    **Assembly happens in PCM and the file is encoded exactly once.** Until the
    v0.6.1 Plan 4 Phase 12 audio audit this wrote every chunk out as its own MP3,
    decoded them all back, merged, and encoded again — two lossy generations for
    audio that was a numpy array the whole time. Measured on this machine, that
    second generation cost **5.67 dB** of SNR against the source PCM at the
    bitrate it was actually using. Holding the chunks as arrays costs a few tens
    of MB for a chapter and removes the loss entirely.
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

    # Chatterbox Turbo's own ceiling, never Kokoro's — see
    # CHATTERBOX_MAX_CHUNK_CHARS for the evidence and the Phase 12 defect it fixes.
    chunks = split_for_chatterbox(text)
    if not chunks:
        raise ValueError("No text content found after parsing source file.")

    voice = get_reference_voice(voice_id)
    log(f"Chatterbox: synthesizing {len(chunks)} chunk(s) in {voice.label}…")

    model = _get_model(device)
    load_conditionals(model, voice_id, log=log, device=device)

    # Silence is built at the model's own rate, so the configured pauses are exact
    # sample counts rather than something resampled from another rate on the way in.
    gap = np.zeros(int(model.sr * chunk_pause_ms / 1000.0), dtype="float32")
    rendered: list[np.ndarray] = []
    for idx, chunk in enumerate(chunks, start=1):
        if cancel_check is not None and cancel_check():  # between chunks
            from shared.cancellation import ConversionCancelled

            raise ConversionCancelled("Conversion cancelled by user.")
        log(f"  Chatterbox chunk {idx}/{len(chunks)}…")

        arr = _synthesize_chunk(model, chunk, cancel_check)
        if arr.size == 0:
            log(f"  Warning: chunk {idx} produced no audio, skipping.")
            if progress_callback is not None:
                progress_callback(idx, len(chunks))
            continue

        # Same order as before: every rendered chunk is followed by the pause.
        rendered.append(arr)
        if gap.size:
            rendered.append(gap)
        if progress_callback is not None:
            progress_callback(idx, len(chunks))

    if not rendered:
        raise ChatterboxUnavailable("Chatterbox produced no audio segments.")

    log("  Assembling Chatterbox audio…")
    if end_silence_ms > 0:
        rendered.append(np.zeros(int(model.sr * end_silence_ms / 1000.0),
                                 dtype="float32"))
    _export_mp3(np.concatenate(rendered), model.sr, output_mp3_path, bitrate)

    log(f"Chatterbox: saved → {output_mp3_path}")
