"""Generate one short MP3 sample per registered voice for manual listening QA.

Writes to files/test-for-manual-listen-elmatthe/<backend>_<voice_id>.mp3.
Dev/QA helper — never imported by the app. Edge samples need network; Kokoro
samples need the local model (~300 MB).

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
import sys
import time
import wave
from dataclasses import dataclass, field
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
    try:
        generation = cbx.generation_defaults()
    except Exception as exc:  # engine absent, or the signature moved
        log(f"Could not read the engine's generation defaults: {exc!r}")
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
    return ap


def main() -> int:
    args = _build_parser().parse_args()

    if args.chatterbox_eval:
        ffmpeg_utils.configure_pydub()
        return _report_chatterbox_evaluation(run_chatterbox_evaluation())

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
            if v.backend == "kokoro":
                from tts.kokoro_synth import synthesize_text_to_mp3

                synthesize_text_to_mp3(SAMPLE_TEXT, str(dest), voice_id=v.voice_id)
            else:
                import asyncio

                import edge_tts

                async def _speak() -> None:
                    await edge_tts.Communicate(SAMPLE_TEXT, v.voice_id).save(str(dest))

                asyncio.run(_speak())
            print(f"OK   {v.display_label} -> {dest.name}")
            ok += 1
        except Exception as e:  # keep going; QA wants the survivors
            print(f"FAIL {v.display_label}: {e!r}")
            fail += 1
    print(f"\nDone: {ok} ok, {fail} failed. Samples in: {out}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
