"""Generate one short MP3 sample per registered voice for manual listening QA.

Writes to files/test-for-manual-listen-elmatthe/<backend>_<voice_id>.mp3.
Dev/QA helper — never imported by the app. Edge samples need network; Kokoro
samples need the local model (~300 MB).

Usage:
    python generate_voice_samples.py                 # every registered voice
    python generate_voice_samples.py Jenny           # only voices matching "Jenny"
    python generate_voice_samples.py Jenny Michelle  # any voice matching either

Filters are case-insensitive substrings matched against the voice_id and the
display label — handy after adding a voice, so one new sample can be produced
without re-synthesizing (and overwriting) the existing set.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPTS_ROOT = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ROOT))

from shared import ffmpeg_utils, paths  # noqa: E402
from tts.voice_registry import VOICES  # noqa: E402

SAMPLE_TEXT = (
    "The quick brown fox jumps over the lazy dog. "
    "This is a short sample of this voice reading two sentences aloud."
)


def _out_dir() -> Path:
    d = paths.REPO_ROOT / "files" / "test-for-manual-listen-elmatthe"
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "patterns",
        nargs="*",
        help="optional voice filters (substring of voice_id or display label)",
    )
    args = ap.parse_args()

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
