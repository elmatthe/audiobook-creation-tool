"""Generate one short MP3 sample per registered voice for manual listening QA.

Writes to files/test-for-manual-listen-elmatthe/<backend>_<voice_id>.mp3.
Dev/QA helper — never imported by the app. Edge samples need network; Kokoro
samples need the local model (~300 MB); Chatterbox samples need the local
package, the local model and the maintainer's reference recordings, which exist
on one machine only. A missing dependency fails that voice's row and the run
continues — the application itself is unaffected either way.

Usage:
    python generate_voice_samples.py                 # every registered voice
    python generate_voice_samples.py Jenny           # only voices matching "Jenny"
    python generate_voice_samples.py Jenny Michelle  # any voice matching either
    python generate_voice_samples.py --chatterbox-eval   # the four eval WAVs

Filters are case-insensitive substrings matched against the voice_id and the
display label — handy after adding a voice, so one new sample can be produced
without re-synthesizing (and overwriting) the existing set.

``--chatterbox-eval`` is a separate, deliberately opt-in mode (v0.6.1 Plan 4
Phase 9). It ignores the registry — no Chatterbox voice is registered until a
human has listened — and instead renders one WAV per maintainer-supplied
reference recording, for exactly that listening decision. It is gated behind its
own flag because it is expensive: it loads a ~3.9 GiB local model and clones four
voices, which an ordinary sample refresh must never trigger by accident.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

_SCRIPTS_ROOT = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ROOT))

from shared import ffmpeg_utils, paths  # noqa: E402
from tts.voice_registry import VOICES  # noqa: E402

SAMPLE_TEXT = (
    "The quick brown fox jumps over the lazy dog. "
    "This is a short sample of this voice reading two sentences aloud."
)

# --------------------------------------------------------------------------- #
# Chatterbox listening evaluation (v0.6.1 Plan 4 Phase 9)
# --------------------------------------------------------------------------- #
#: The maintainer-approved evaluation sentence, identical for all four outputs.
#: Every voice reads the same words so the comparison is about the voice.
CHATTERBOX_EVAL_TEXT = (
    "Welcome to the audiobook creation tool. This is a sample test evaluating "
    "Chatterbox for clarity, pacing, and emotional depth."
)

#: The closed set, in reporting order. Four references in, four outputs out —
#: no fifth speaker, no variants, no parameter sweep.
CHATTERBOX_EVAL_VOICE_IDS: tuple[str, ...] = (
    "chatterbox-female-1",
    "chatterbox-female-2",
    "chatterbox-male-1",
    "chatterbox-male-2",
)

#: A subfolder of the existing manual-listen folder, which .gitignore already
#: covers — so the audio cannot reach the repository.
CHATTERBOX_EVAL_SUBDIR = "chatterbox-eval"


def _out_dir() -> Path:
    d = paths.REPO_ROOT / "files" / "test-for-manual-listen-elmatthe"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _chatterbox_eval_dir(create: bool = True) -> Path:
    """Where the four evaluation WAVs go — inside the already-ignored parent."""
    d = _out_dir() / CHATTERBOX_EVAL_SUBDIR
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def _matches(v, pattern: str) -> bool:
    # An exact backend name selects that whole group ("edge" / "kokoro");
    # anything else is a substring of the voice_id or the display label.
    if pattern == v.backend:
        return True
    return pattern in v.voice_id.lower() or pattern in v.display_label.lower()


def _select(patterns: list[str]) -> list:
    """Voices matching any pattern (case-insensitive). A pattern equal to a
    backend name selects that entire backend. No patterns means every voice."""
    if not patterns:
        return list(VOICES)
    lowered = [p.lower() for p in patterns]
    return [v for v in VOICES if any(_matches(v, p) for p in lowered)]


def _synthesize_for_voice(v, text: str, dest: Path, log: Callable[[str], None] = print) -> None:
    """Dispatch synthesis to voice ``v``'s backend. The one place backend
    dispatch lives, shared by the ordinary per-voice loop and the
    ``--quality-suite`` harness so the two cannot drift apart."""
    if v.backend == "kokoro":
        from tts.kokoro_synth import synthesize_text_to_mp3

        synthesize_text_to_mp3(text, str(dest), voice_id=v.voice_id)
    elif v.backend == "chatterbox":
        from tts.chatterbox_synth import CHATTERBOX_MAX_CHUNK_CHARS

        if len(text) > CHATTERBOX_MAX_CHUNK_CHARS:
            # synthesize_text_to_mp3 below is a single model.generate() call
            # with no chunking — correct only for a short one-shot sample
            # (its one caller before this harness was the fixed, short
            # SAMPLE_TEXT). Text past the chunk ceiling must go through the
            # real chunked production path instead, or the model silently
            # returns a few hundred milliseconds of near-silent audio with
            # no error (discovered running this harness's own sustained/
            # longer corpus items — a harness bug, not a production one:
            # nothing production-side ever called the single-shot function
            # with long text).
            import tempfile

            from tts.chatterbox_synth import chatterbox_file_to_mp3

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False, encoding="utf-8",
            ) as tmp:
                tmp.write(text)
                tmp_path = tmp.name
            try:
                chatterbox_file_to_mp3(tmp_path, str(dest), voice_id=v.voice_id, log=log)
            finally:
                Path(tmp_path).unlink(missing_ok=True)
        else:
            from tts.chatterbox_synth import (
                synthesize_text_to_mp3 as chatterbox_text_to_mp3,
            )

            chatterbox_text_to_mp3(text, str(dest), voice_id=v.voice_id, log=log)
    elif v.backend == "edge":
        import asyncio

        import edge_tts

        async def _speak() -> None:
            await edge_tts.Communicate(text, v.voice_id).save(str(dest))

        asyncio.run(_speak())
    else:
        raise ValueError(f"No sample path for backend {v.backend!r} ({v.voice_id}).")


@dataclass
class ChatterboxEvalResult:
    """One row of the Phase 9 listening table — success or failure, never dropped."""

    voice_id: str
    label: str
    source_path: str = ""
    source_sha256: str = ""
    derivative_path: str = ""
    conditional_path: str = ""
    conditional_state: str = "not reached"
    output_path: str = ""
    device: str = ""
    parameters: dict = field(default_factory=dict)
    audio_seconds: float | None = None
    wall_seconds: float | None = None
    rtf: float | None = None
    ok: bool = False
    detail: str = ""


def _wav_seconds(path: Path) -> float:
    """Read the duration back off the written file rather than trusting the model."""
    with wave.open(str(path), "rb") as handle:
        frames = handle.getnframes()
        if frames == 0:
            raise ValueError(f"{path.name} contains no audio frames")
        return frames / float(handle.getframerate())


def _format_parameters(parameters: dict) -> str:
    """One cell's worth of what was actually used. No pipes — it lives in a table."""
    reference = parameters.get("reference", {})
    generation = parameters.get("generation") or {}
    rendered = ", ".join(f"{k}={v}" for k, v in generation.items()) or "engine defaults"
    return (
        f"{parameters.get('model', '?')}; "
        f"ref {reference.get('window_seconds', '?')}s "
        f"{reference.get('window_position', '?')} mono "
        f"{reference.get('sample_rate', '?')} Hz; {rendered}"
    )


def run_chatterbox_evaluation(
    log: Callable[[str], None] = print,
    device: str | None = None,
) -> list[ChatterboxEvalResult]:
    """Render exactly one evaluation WAV per approved reference recording.

    Two stages, deliberately separate. **First** every source is proved — hash
    verified and its conditioning derivative prepared — and a single failure there
    is a hard stop that generates nothing at all, because a mismatched or missing
    recording invalidates the comparison the maintainer is about to make. **Then**
    the four voices are synthesized; a failure at that point is recorded as a FAIL
    row and the remaining voices continue, so the table always has four rows.

    Nothing here decides anything. It produces evidence and stops.
    """
    from tts import chatterbox_synth as cbx

    resolved_device = device or cbx.select_device()
    # The HISTORICAL Phase 9 contract, not current production. The four approved
    # listening WAVs were rendered before the Phase 12 tuning existed, so this
    # command must keep reproducing them at that temperature; ordinary samples
    # (``generate`` below) follow current production instead. Reporting the values
    # actually used beats reporting the wheel's defaults, which production no
    # longer matches.
    try:
        generation = cbx.phase9_evaluation_params()
    except Exception as exc:  # engine absent, or the seam moved
        log(f"Could not read the evaluation generation parameters: {exc!r}")
        generation = {}
    parameters = {
        "package": cbx.PACKAGE_REQUIREMENT,
        "model": cbx.MODEL_REPO_ID,
        "device": resolved_device,
        "reference": cbx.derivative_spec(),
        "generation": generation,
    }

    results = [
        ChatterboxEvalResult(
            voice_id=voice_id,
            label=cbx.REFERENCE_VOICES[voice_id].label,
            source_sha256=cbx.REFERENCE_VOICES[voice_id].source_sha256,
            device=resolved_device,
            parameters=parameters,
        )
        for voice_id in CHATTERBOX_EVAL_VOICE_IDS
    ]

    # --- stage one: prove all four sources before generating any audio ------- #
    stopped = ""
    for result in results:
        if stopped:
            result.detail = f"Not attempted — evaluation stopped at {stopped}."
            continue
        try:
            source = cbx.resolve_reference(result.voice_id)
            derivative = cbx.prepare_reference_clip(result.voice_id, log=log)
        except Exception as exc:
            result.detail = str(exc)
            stopped = result.voice_id
            log(f"HARD STOP {result.label}: {exc}")
            continue
        cached = cbx.conditionals_path(result.voice_id, result.source_sha256)
        result.source_path = str(source)
        result.derivative_path = str(derivative)
        result.conditional_path = str(cached)
        result.conditional_state = "reused" if cached.is_file() else "computed"

    if stopped:
        log("Reference verification failed — no audio was generated. "
            "Every row below is reported.")
        return results

    # --- stage two: exactly one generation per voice ------------------------ #
    out_dir = _chatterbox_eval_dir()
    for result in results:
        dest = out_dir / f"{result.voice_id}.wav"
        result.output_path = str(dest)
        log(f"Chatterbox evaluation: {result.label} -> {dest.name}")
        started = time.perf_counter()
        try:
            cbx.synthesize_text_to_wav(
                CHATTERBOX_EVAL_TEXT, str(dest), result.voice_id,
                log=log, device=resolved_device,
                generation=generation or None,
            )
            result.wall_seconds = time.perf_counter() - started
            result.audio_seconds = _wav_seconds(dest)
            result.rtf = result.wall_seconds / result.audio_seconds
            result.ok = True
            result.detail = "OK"
        except Exception as exc:
            # Reported, never retried: a second attempt with different settings
            # would make the listening comparison meaningless.
            result.wall_seconds = time.perf_counter() - started
            result.detail = str(exc) or repr(exc)
            log(f"FAIL {result.label}: {exc!r}")

    return results


def format_chatterbox_table(results: list[ChatterboxEvalResult]) -> str:
    """The four-row Markdown summary the maintainer listens against."""
    lines = [
        "| Voice | Reference source | Output path | Duration | Parameters | Result |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        source = Path(r.source_path).name if r.source_path else "—"
        output = r.output_path or "—"
        duration = f"{r.audio_seconds:.2f} s" if r.audio_seconds is not None else "—"
        verdict = "OK" if r.ok else f"FAIL — {r.detail}"
        lines.append(
            f"| {r.voice_id} | {source} | {output} | {duration} | "
            f"{_format_parameters(r.parameters)} | {verdict} |"
        )
    return "\n".join(lines)


def _report_chatterbox_evaluation(results: list[ChatterboxEvalResult],
                                  log: Callable[[str], None] = print) -> int:
    log("")
    log(format_chatterbox_table(results))
    log("")
    for r in results:
        wall = f"{r.wall_seconds:.2f} s" if r.wall_seconds is not None else "—"
        audio = f"{r.audio_seconds:.2f} s" if r.audio_seconds is not None else "—"
        rtf = f"{r.rtf:.3f}" if r.rtf is not None else "—"
        log(f"{r.voice_id}: wall {wall}, audio {audio}, RTF {rtf}, "
            f"conditional {r.conditional_state}")
    ok = sum(1 for r in results if r.ok)
    log("")
    log(f"Successes: {ok}   Failures: {len(results) - ok}   "
        f"Device: {results[0].device if results else 'unknown'}")
    log("Listening decision belongs to the maintainer. Nothing was registered.")
    return 0 if ok == len(results) else 1


# --------------------------------------------------------------------------- #
# Chatterbox candidate evaluation (v0.6.5 Phase 2 — plan Sections 4/5)
# --------------------------------------------------------------------------- #
#: Same evaluation sentence as the historical four-voice command, so the
#: maintainer compares candidates against the same reference recording used
#: for the four already-approved voices, not a different one.
CHATTERBOX_CANDIDATE_TEXT = CHATTERBOX_EVAL_TEXT

#: Still-pending candidates only (plan Section 3), not merged with
#: CHATTERBOX_EVAL_VOICE_IDS. A `NO` from the maintainer leaves a voice_id
#: here forever; there is no automatic substitute (plan Section 5). Male-4
#: was approved 2026-09-20 and removed from this tuple — it is now a
#: registered production voice (voice_registry.VOICES,
#: chatterbox_synth.REFERENCE_VOICES), not a candidate.
CHATTERBOX_CANDIDATE_VOICE_IDS: tuple[str, ...] = (
    "chatterbox-male-3",
)

#: A separate subfolder from CHATTERBOX_EVAL_SUBDIR — candidates are not the
#: historical evaluation and must not be mistaken for it or overwrite it.
CHATTERBOX_CANDIDATE_SUBDIR = "chatterbox-candidates"


def _chatterbox_candidate_dir(create: bool = True) -> Path:
    d = _out_dir() / CHATTERBOX_CANDIDATE_SUBDIR
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def run_chatterbox_candidate_evaluation(
    log: Callable[[str], None] = print,
    device: str | None = None,
) -> list[ChatterboxEvalResult]:
    """Render one evaluation WAV per Male-3/Male-4 candidate (plan Sections 4/5).

    Deliberately **not** a variant of ``run_chatterbox_evaluation`` — that
    function's four-voice, Phase-9-temperature contract must stay exactly
    reproducible, untouched by anything this function does. The two
    differences from it, both required by the plan: **current production**
    generation settings (``generation_params()``, not the historical Phase 9
    temperature — Section 5), and a separate closed pair of candidate voice
    ids that never appear in ``voice_registry.VOICES`` unless and until the
    maintainer approves one (Section 5's manual gate; no GUI registry change
    before that).

    Same two-stage shape as the historical evaluation: sources are proved
    (hash-verified, derivative prepared) before anything is generated, and a
    generation failure is recorded as a FAIL row rather than stopping the
    other candidate.
    """
    from tts import chatterbox_synth as cbx

    resolved_device = device or cbx.select_device()
    generation = cbx.generation_params()
    parameters = {
        "package": cbx.PACKAGE_REQUIREMENT,
        "model": cbx.MODEL_REPO_ID,
        "device": resolved_device,
        "reference": cbx.derivative_spec(),
        "generation": generation,
    }

    results = [
        ChatterboxEvalResult(
            voice_id=voice_id,
            label=cbx.get_reference_voice(voice_id).label,
            source_sha256=cbx.get_reference_voice(voice_id).source_sha256,
            device=resolved_device,
            parameters=parameters,
        )
        for voice_id in CHATTERBOX_CANDIDATE_VOICE_IDS
    ]

    # --- stage one: prove both sources before generating any audio ---------- #
    for result in results:
        try:
            source = cbx.resolve_reference(result.voice_id)
            derivative = cbx.prepare_reference_clip(result.voice_id, log=log)
        except Exception as exc:
            result.detail = str(exc)
            log(f"Setup required for {result.label}: {exc}")
            continue
        cached = cbx.conditionals_path(result.voice_id, result.source_sha256)
        result.source_path = str(source)
        result.derivative_path = str(derivative)
        result.conditional_path = str(cached)
        result.conditional_state = "reused" if cached.is_file() else "computed"

    # --- stage two: one generation per candidate whose source proved out ---- #
    out_dir = _chatterbox_candidate_dir()
    for result in results:
        if not result.source_path:
            result.detail = result.detail or "Setup required — see above."
            continue
        dest = out_dir / f"{result.voice_id}.wav"
        result.output_path = str(dest)
        log(f"Chatterbox candidate: {result.label} -> {dest.name}")
        started = time.perf_counter()
        try:
            cbx.synthesize_text_to_wav(
                CHATTERBOX_CANDIDATE_TEXT, str(dest), result.voice_id,
                log=log, device=resolved_device, generation=generation,
            )
            result.wall_seconds = time.perf_counter() - started
            result.audio_seconds = _wav_seconds(dest)
            result.rtf = result.wall_seconds / result.audio_seconds
            result.ok = True
            result.detail = "OK"
        except Exception as exc:
            result.wall_seconds = time.perf_counter() - started
            result.detail = str(exc) or repr(exc)
            log(f"FAIL {result.label}: {exc!r}")

    return results


def _report_chatterbox_candidate_evaluation(
    results: list[ChatterboxEvalResult], log: Callable[[str], None] = print,
) -> int:
    log("")
    log(format_chatterbox_table(results))
    log("")
    for r in results:
        wall = f"{r.wall_seconds:.2f} s" if r.wall_seconds is not None else "—"
        audio = f"{r.audio_seconds:.2f} s" if r.audio_seconds is not None else "—"
        rtf = f"{r.rtf:.3f}" if r.rtf is not None else "—"
        log(f"{r.voice_id}: wall {wall}, audio {audio}, RTF {rtf}, "
            f"conditional {r.conditional_state}")
    ok = sum(1 for r in results if r.ok)
    log("")
    log(f"Successes: {ok}   Failures: {len(results) - ok}   "
        f"Device: {results[0].device if results else 'unknown'}")
    log("Approval decision belongs to the maintainer, per voice, by listening "
        "(plan Section 5). Nothing was registered in voice_registry.VOICES.")
    return 0 if ok == len(results) else 1


# --------------------------------------------------------------------------- #
# Male-3 §14 bounded pitch retry (v0.6.5 Phase 2 remediation, 2026-09-20)
# --------------------------------------------------------------------------- #
#: The maintainer's verdict: "otherwise good, make it ever so slightly
#: deeper... only a very small timbre/pitch reduction. Do not otherwise
#: change its pacing, generation settings, clarity, or character." ~3% lower
#: (roughly half a semitone) is the single bounded adjustment tried here, per
#: instruction not to build a ladder of variants unless this one proves
#: mechanically unusable.
MALE3_RETRY_PITCH_RATIO = 0.97

MALE3_RETRY_SUBDIR = "male-3-pitch-retry"


def _pitch_shift_preserve_tempo(source: Path, dest: Path, pitch_ratio: float) -> None:
    """Shift ``source``'s pitch by ``pitch_ratio`` (1.0 = unchanged, <1.0 =
    lower/deeper) while preserving its tempo/duration, via ffmpeg's standard
    ``asetrate`` + ``atempo`` pair. No new dependency: ffmpeg is already a
    project requirement and this is the same binary
    ``chatterbox_synth.build_reference_clip`` already shells out to for the
    ordinary reference-window extraction.

    ``asetrate=rate*pitch_ratio`` relabels the existing samples' playback
    rate, which shifts pitch by exactly ``pitch_ratio`` but also **stretches**
    duration by ``1/pitch_ratio`` (a lower declared rate means the same
    sample count now spans more wall-clock time); ``atempo=1/pitch_ratio``
    then speeds playback back up by that same factor, restoring the original
    duration without touching pitch a second time (atempo is a time-domain
    algorithm that never touches pitch). ``aresample`` returns the stream to
    the original sample rate label afterward so the file plays at the same
    rate every other derivative uses.
    """
    import subprocess

    with wave.open(str(source), "rb") as handle:
        rate = handle.getframerate()

    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_utils.ffmpeg_cmd(), "-y", "-loglevel", "error",
        "-i", str(source),
        "-filter:a",
        f"asetrate={rate * pitch_ratio},atempo={1.0 / pitch_ratio},aresample={rate}",
        "-ac", "1",
        str(dest),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not dest.is_file():
        raise RuntimeError(
            f"ffmpeg pitch-shift failed: {(result.stderr or '').strip() or 'no output produced'}")


def render_male3_pitch_retry(
    pitch_ratio: float = MALE3_RETRY_PITCH_RATIO,
    log: Callable[[str], None] = print,
    device: str | None = None,
) -> ChatterboxEvalResult:
    """One bounded plan-§14 remediation retry for the rejected Male-3
    candidate (maintainer verdict, 2026-09-20 — see module docstring above
    for the exact wording).

    Applies the pitch shift to a **scratch copy** of the standard 15-second
    reference-conditioning clip — never to ``Male-3.mp3`` itself, and never
    to the cached production derivative
    (``chatterbox_synth.derivative_path``) any other call might reuse — then
    conditions the model on that copy directly and generates one new WAV
    under the exact same current-production ``generation_params()`` and
    evaluation text as the original candidate render. Nothing else about
    Male-3's evaluation changes: same text, same
    temperature/top_p/top_k/repetition_penalty, same device selection, same
    reference-conditioning exaggeration.

    This is a one-off remediation tool, not new production voice-processing
    machinery: the pitch shift is a single ffmpeg filter, applied once, to
    one temporary file, for one voice, on this one retry call. It is not
    wired into ``voice_registry``, the production derivative/identity-digest
    cache, or any other voice's synthesis path, and it changes nothing about
    ``chatterbox_synth.build_reference_clip`` or any global generation
    parameter.
    """
    from tts import chatterbox_synth as cbx

    voice_id = "chatterbox-male-3"
    resolved_device = device or cbx.select_device()
    generation = cbx.generation_params()
    voice = cbx.get_reference_voice(voice_id)

    result = ChatterboxEvalResult(
        voice_id=voice_id,
        label=f"{voice.label} (pitch retry x{pitch_ratio})",
        source_sha256=voice.source_sha256,
        device=resolved_device,
        parameters={
            "package": cbx.PACKAGE_REQUIREMENT,
            "model": cbx.MODEL_REPO_ID,
            "device": resolved_device,
            "reference": cbx.derivative_spec(),
            "generation": generation,
            "retry_pitch_ratio": pitch_ratio,
        },
    )

    retry_dir = paths.REPO_ROOT / "files" / "dev-work" / MALE3_RETRY_SUBDIR
    base_clip = retry_dir / "reference_clip_original.wav"
    shifted_clip = retry_dir / f"reference_clip_pitch{pitch_ratio:.2f}.wav"
    dest = _chatterbox_candidate_dir() / "chatterbox-male-3-pitch-retry.wav"

    try:
        source = cbx.resolve_reference(voice_id)  # hash-verified, read-only
        result.source_path = str(source)

        # Same 15s leading-window extraction the production path uses,
        # written to a scratch copy — never the cached production derivative.
        cbx.build_reference_clip(source, base_clip)
        _pitch_shift_preserve_tempo(base_clip, shifted_clip, pitch_ratio)
        result.derivative_path = str(shifted_clip)

        model = cbx._get_model(resolved_device)
        model.prepare_conditionals(str(shifted_clip), exaggeration=cbx.REFERENCE_EXAGGERATION)

        started = time.perf_counter()
        arr = cbx._audio_array(model.generate(CHATTERBOX_CANDIDATE_TEXT, **generation))
        if arr.size == 0:
            raise cbx.ChatterboxUnavailable(
                "Chatterbox produced no audio for the Male-3 pitch retry.")
        import soundfile as sf

        dest.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(dest), arr, model.sr)
        result.output_path = str(dest)
        result.wall_seconds = time.perf_counter() - started
        result.audio_seconds = _wav_seconds(dest)
        result.rtf = result.wall_seconds / result.audio_seconds
        result.ok = True
        result.detail = "OK"
    except Exception as exc:
        result.detail = str(exc) or repr(exc)
        log(f"FAIL Male-3 pitch retry: {exc!r}")

    return result


# --------------------------------------------------------------------------- #
# Quality suite (v0.6.5 Phase 1 — plan Section 8)
# --------------------------------------------------------------------------- #
#: Baseline (plan Section 8): sustained/longer samples are captured for these
#: six voices at minimum. Every other retained voice still gets the short
#: difficult-text baseline below.
REPRESENTATIVE_VOICE_IDS: frozenset[str] = frozenset({
    "en-US-SteffanNeural",
    "en-US-JennyNeural",
    "af_heart",
    "am_michael",
    "chatterbox-female-1",
    "chatterbox-male-1",
})


def _quality_suite_dir() -> Path:
    """Local-only evidence: files/dev-work/ is repository-wide gitignored, so
    generated audio and manifests here never reach git (plan Section 8)."""
    d = paths.REPO_ROOT / "files" / "dev-work" / "quality-suite"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _git_commit_sha() -> str:
    import subprocess

    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(paths.REPO_ROOT),
            capture_output=True, text=True, timeout=10,
        )
        return out.stdout.strip() if out.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


@dataclass
class QualitySample:
    """One manifest row (P12): enough to redo or understand this one sample
    without keeping the audio itself in git. Mechanical fields only — never
    a pass/fail judgment; human listening is the only authority (P6)."""

    voice_id: str
    backend: str
    corpus_item: str
    assembly_path: str  # "standard" | "raw_chunk" | "folder_batch" | "direct"
    output_path: str
    commit_sha: str
    corpus_identity: str
    effective_settings: str
    sample_rate: int | None = None
    approx_bitrate_kbps: float | None = None
    duration_s: float | None = None
    wall_s: float | None = None
    rtf: float | None = None
    dbfs: float | None = None
    leading_silence_ms: int | None = None
    trailing_silence_ms: int | None = None
    ok: bool = False
    detail: str = ""

    def apply_evidence(self, evidence: dict) -> None:
        for key, value in evidence.items():
            setattr(self, key, value)


def _measure_audio(path: Path) -> dict:
    """Lightweight mechanical evidence only (plan Section 7): loudness,
    duration, and leading/trailing silence are diagnostic, not a mandate to
    refactor, and never decide anything on their own (P6)."""
    from pydub import AudioSegment
    from pydub.silence import detect_leading_silence

    seg = AudioSegment.from_file(path)
    duration_s = len(seg) / 1000.0
    leading_ms = detect_leading_silence(seg)
    trailing_ms = detect_leading_silence(seg.reverse())
    size_bytes = path.stat().st_size
    bitrate_kbps = (size_bytes * 8 / 1000.0) / duration_s if duration_s else None
    dbfs = seg.dBFS
    return {
        "sample_rate": seg.frame_rate,
        "duration_s": round(duration_s, 3),
        "dbfs": round(dbfs, 2) if dbfs != float("-inf") else None,
        "leading_silence_ms": leading_ms,
        "trailing_silence_ms": trailing_ms,
        "approx_bitrate_kbps": round(bitrate_kbps, 1) if bitrate_kbps else None,
    }


def _run_quality_sample(
    row: QualitySample, synth: Callable[[], str | None], dest: Path,
    log: Callable[[str], None], rows: list[QualitySample], out_root: Path,
) -> QualitySample:
    """Run one synthesis call, measure it, and record the row — success or
    failure, never dropped (mirrors ``ChatterboxEvalResult``'s contract).

    Appends to ``rows`` and rewrites the manifest immediately, so a long
    run interrupted partway (Chatterbox's sustained/longer samples can take
    tens of minutes) still leaves every sample completed so far as evidence
    instead of losing it to a manifest written only at the very end."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    log(f"[{row.assembly_path}] {row.voice_id} / {row.corpus_item} -> {dest}")
    started = time.perf_counter()
    try:
        produced = synth()
        row.wall_s = round(time.perf_counter() - started, 2)
        actual = Path(produced) if produced else dest
        row.output_path = str(actual)
        evidence = _measure_audio(actual)
        row.apply_evidence(evidence)
        row.rtf = round(row.wall_s / row.duration_s, 3) if row.duration_s else None
        row.ok = True
        row.detail = "OK"
    except Exception as exc:
        row.wall_s = round(time.perf_counter() - started, 2)
        row.detail = str(exc) or repr(exc)
        log(f"FAIL [{row.assembly_path}] {row.voice_id} / {row.corpus_item}: {exc!r}")
    rows.append(row)
    _write_manifest(out_root, rows)
    return row


def _capture_edge_path_evidence(
    v, out_root: Path, commit_sha: str, identity: str, log: Callable[[str], None],
) -> list[QualitySample]:
    """Matched raw-chunk / folder-batch / direct-file evidence for one Edge
    voice (plan Sections 6-8) — evidence only; the assembly investigation
    itself is Phase 3's job. The folder/batch call runs the confirmed-
    preferred original pipeline unchanged since v0.5.0 (Decisions.md,
    2026-07-19), so it doubles as that historical reference."""
    import tempfile

    from tts import batch_convert
    from tts import quality_corpus as qc
    from tts.epub2tts_edge import runner as edge_runner

    item = qc.STRUCTURAL_STRESS_KOKORO_EDGE
    edge_dir = out_root / "edge_path_comparison"
    edge_dir.mkdir(parents=True, exist_ok=True)
    rows: list[QualitySample] = []

    def _new_row(assembly_path: str, output_path: Path, settings: str) -> QualitySample:
        return QualitySample(
            voice_id=v.voice_id, backend=v.backend, corpus_item=item.name,
            assembly_path=assembly_path, output_path=str(output_path),
            commit_sha=commit_sha, corpus_identity=identity,
            effective_settings=settings,
        )

    # 1. Raw Edge chunk: one direct edge_tts.Communicate call, no assembly.
    raw_dest = edge_dir / "raw_chunk.mp3"
    _run_quality_sample(
        _new_row("raw_chunk", raw_dest, "rate=+0%"),
        lambda: batch_convert.synthesize_chunk_mp3(item.text, str(raw_dest), v.voice_id, "+0%"),
        raw_dest, log, rows, out_root,
    )

    with tempfile.TemporaryDirectory(prefix="qsuite_edge_src_") as tmp_src:
        src_txt = Path(tmp_src) / "structural_stress.txt"
        src_txt.write_text(item.text, encoding="utf-8")

        # 2. Folder/batch path.
        batch_out = edge_dir / "folder_batch"
        produced_batch = batch_out / "structural_stress.mp3"

        def _run_batch() -> str:
            ok, fail, _errlog = batch_convert.run_batch_convert(
                tmp_src, batch_out, speaker=v.voice_id, workers=1,
                rate="+0%", use_tqdm=False, log=log,
            )
            if ok != 1 or not produced_batch.is_file():
                raise RuntimeError(f"batch reported ok={ok} fail={fail}")
            return str(produced_batch)

        _run_quality_sample(
            _new_row("folder_batch", produced_batch, "workers=1, rate=+0%"),
            _run_batch, produced_batch, log, rows, out_root,
        )

        # 3. Direct/rich path.
        direct_out_dir = edge_dir / "direct"
        _run_quality_sample(
            _new_row("direct", direct_out_dir, "audio_format=mp3, engine defaults"),
            lambda: edge_runner.run_conversion_job(
                str(src_txt), output_dir=str(direct_out_dir),
                speaker=v.voice_id, audio_format="mp3", overwrite=True,
            ),
            direct_out_dir, log, rows, out_root,
        )

    return rows


def run_quality_suite(patterns: list[str], log: Callable[[str], None] = print) -> list[QualitySample]:
    """Phase 1 harness (plan Section 8): short difficult-text baseline for
    every selected voice, sustained/longer baselines for the representative
    voices, and matched Edge direct/folder/raw-chunk evidence. Produces
    evidence and stops — no production change, no subjective judgment (P1,
    P6, P12)."""
    from tts import batch_convert
    from tts import quality_corpus as qc

    # chatterbox_file_to_mp3's default logging prints a unicode arrow; a
    # non-UTF-8 Windows console (cp1252) raises UnicodeEncodeError on it
    # otherwise. Harness-side only — production callers supply their own
    # log sink (a GUI queue), so this never touches production code.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="replace")
            except Exception:
                pass

    selected = _select(patterns) if patterns else list(VOICES)
    commit_sha = _git_commit_sha()
    identity = qc.corpus_identity()
    out_root = _quality_suite_dir()
    rows: list[QualitySample] = []

    ffmpeg_utils.configure_pydub()

    for v in selected:
        dest_dir = out_root / f"{v.backend}_{v.voice_id}"
        difficult_dest = dest_dir / "difficult_short.mp3"
        _run_quality_sample(
            QualitySample(
                voice_id=v.voice_id, backend=v.backend,
                corpus_item=qc.DIFFICULT_SHORT.name, assembly_path="standard",
                output_path=str(difficult_dest), commit_sha=commit_sha,
                corpus_identity=identity, effective_settings="engine defaults",
            ),
            lambda v=v, d=difficult_dest: _synthesize_for_voice(v, qc.DIFFICULT_SHORT.text, d, log)
            or str(d),
            difficult_dest, log, rows, out_root,
        )
        if v.voice_id in REPRESENTATIVE_VOICE_IDS:
            for item in (qc.SUSTAINED_NARRATION, qc.LONGER_STRESS):
                dest = dest_dir / f"{item.name}.mp3"
                _run_quality_sample(
                    QualitySample(
                        voice_id=v.voice_id, backend=v.backend,
                        corpus_item=item.name, assembly_path="standard",
                        output_path=str(dest), commit_sha=commit_sha,
                        corpus_identity=identity, effective_settings="engine defaults",
                    ),
                    lambda v=v, t=item.text, d=dest: _synthesize_for_voice(v, t, d, log) or str(d),
                    dest, log, rows, out_root,
                )

    edge_selected = [v for v in selected if v.backend == "edge"]
    if edge_selected:
        v = next(
            (x for x in edge_selected if x.voice_id == batch_convert.DEFAULT_SPEAKER),
            edge_selected[0],
        )
        rows.extend(_capture_edge_path_evidence(v, out_root, commit_sha, identity, log))

    _write_manifest(out_root, rows)
    return rows


def _write_manifest(out_root: Path, rows: list[QualitySample]) -> None:
    manifest_path = out_root / "manifest.jsonl"
    with open(manifest_path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(asdict(row)) + "\n")

    lines = [
        "| Voice | Backend | Corpus item | Path | Duration | RTF | dBFS | "
        "Lead/Trail silence | Result |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        duration = f"{r.duration_s:.2f}s" if r.duration_s is not None else "—"
        rtf = f"{r.rtf:.3f}" if r.rtf is not None else "—"
        dbfs = f"{r.dbfs:.1f}" if r.dbfs is not None else "—"
        silence = (
            f"{r.leading_silence_ms}/{r.trailing_silence_ms} ms"
            if r.leading_silence_ms is not None else "—"
        )
        verdict = "OK" if r.ok else f"FAIL — {r.detail}"
        lines.append(
            f"| {r.voice_id} | {r.backend} | {r.corpus_item} | {r.assembly_path} | "
            f"{duration} | {rtf} | {dbfs} | {silence} | {verdict} |"
        )
    (out_root / "manifest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _report_quality_suite(rows: list[QualitySample], out_root: Path,
                          log: Callable[[str], None] = print) -> int:
    ok = sum(1 for r in rows if r.ok)
    log("")
    log(f"Quality suite: {ok}/{len(rows)} samples generated OK.")
    log(f"Manifest: {out_root / 'manifest.md'}")
    log(f"Audio + manifest under: {out_root}  (gitignored — local listening only)")
    log("")
    log("Listening decision belongs to the maintainer (P6). Nothing was "
        "registered or judged automatically.")
    return 0 if ok == len(rows) else 1


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "patterns",
        nargs="*",
        help="optional voice filters (substring of voice_id or display label)",
    )
    ap.add_argument(
        "--chatterbox-eval",
        dest="chatterbox_eval",
        action="store_true",
        help="render the four Chatterbox listening-evaluation WAVs and stop "
             "(expensive: loads the local model and clones four voices)",
    )
    ap.add_argument(
        "--chatterbox-candidates",
        dest="chatterbox_candidates",
        action="store_true",
        help="v0.6.5 Phase 2: render a listening WAV for each still-pending "
             "Chatterbox candidate (currently Male-3 only — Male-4 was "
             "approved 2026-09-20 and is now a registered production voice) "
             "and stop (current production settings, not the historical "
             "Phase 9 temperature; separate from --chatterbox-eval and never "
             "touches voice_registry.VOICES).",
    )
    ap.add_argument(
        "--chatterbox-male3-pitch-retry",
        dest="chatterbox_male3_pitch_retry",
        action="store_true",
        help="v0.6.5 Phase 2 Section 14 remediation: render one Male-3 "
             "listening WAV with a small pitch-only reduction applied to a "
             "scratch copy of its reference-conditioning clip (never to "
             "Male-3.mp3 or the cached production derivative), under "
             "otherwise unchanged current-production settings, and stop.",
    )
    ap.add_argument(
        "--quality-suite",
        dest="quality_suite",
        action="store_true",
        help="v0.6.5 Phase 1 baseline harness: short difficult-text sample "
             "for every selected voice, sustained/longer samples for the "
             "representative voices, and matched Edge direct/folder/"
             "raw-chunk evidence. Writes to files/dev-work/quality-suite/ "
             "(gitignored, local listening only).",
    )
    return ap


def main() -> int:
    args = _build_parser().parse_args()

    if args.chatterbox_eval:
        ffmpeg_utils.configure_pydub()
        return _report_chatterbox_evaluation(run_chatterbox_evaluation())

    if args.chatterbox_candidates:
        ffmpeg_utils.configure_pydub()
        return _report_chatterbox_candidate_evaluation(run_chatterbox_candidate_evaluation())

    if args.chatterbox_male3_pitch_retry:
        ffmpeg_utils.configure_pydub()
        result = render_male3_pitch_retry()
        print()
        print(format_chatterbox_table([result]))
        print()
        if result.ok:
            print(f"OK  wall {result.wall_seconds:.2f}s  audio {result.audio_seconds:.2f}s  "
                  f"RTF {result.rtf:.3f}")
        else:
            print(f"FAIL  {result.detail}")
        print("Approval decision belongs to the maintainer, by listening "
              "(plan Section 5). Nothing was registered in voice_registry.VOICES.")
        return 0 if result.ok else 1

    if args.quality_suite:
        rows = run_quality_suite(args.patterns)
        return _report_quality_suite(rows, _quality_suite_dir())

    selected = _select(args.patterns)
    if not selected:
        print(f"No voice matched: {' '.join(args.patterns)}")
        print("Registered voices:")
        for v in VOICES:
            print(f"  {v.voice_id:32} {v.display_label}")
        return 1
    if args.patterns:
        print(f"Filtered to {len(selected)} of {len(VOICES)} voices.\n")

    ffmpeg_utils.configure_pydub()
    out = _out_dir()
    ok = fail = 0
    for v in selected:
        dest = out / f"{v.backend}_{v.voice_id}.mp3"
        try:
            # The ordinary sample, not the Phase 9 listening evaluation: the
            # same SAMPLE_TEXT and the same <backend>_<voice_id>.mp3 name for
            # every voice. The four Chatterbox evaluation WAVs stay behind
            # their own flag.
            _synthesize_for_voice(v, SAMPLE_TEXT, dest)
            print(f"OK   {v.display_label} -> {dest.name}")
            ok += 1
        except Exception as e:  # keep going; QA wants the survivors
            print(f"FAIL {v.display_label}: {e!r}")
            fail += 1
    print(f"\nDone: {ok} ok, {fail} failed. Samples in: {out}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
