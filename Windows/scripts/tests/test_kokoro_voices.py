"""test_kokoro_voices.py — one-shot 5-voice Kokoro verification harness.

Confirms all five Kokoro voices work end-to-end after the self-healing bootstrap
fix lands. Run from the repo root with the project venv's Python (Python 3.12 —
Kokoro's wheel requires <3.13):

    Windows:  Windows\\.venv\\Scripts\\python.exe Windows\\scripts\\tests\\test_kokoro_voices.py
    macOS:    MacOS/.venv/bin/python  MacOS/scripts/tests/test_kokoro_voices.py

Three stages, each printing PASS/FAIL lines and contributing to the exit code:

  A. Smoke  — synthesize a short line with each of the 5 voices and probe the MP3.
  B. E2E    — run `Chapter 20_ Outcast Once Again.pdf` end-to-end with each voice.
  C. Batch  — run the full 10-PDF folder with bf_emma (the exact scenario that
              failed in the user's log) and assert 0 failures.

Exit code is 0 only if every stage passes.

NOTE ON CODE PATHS (intentional deviation from the spec markdown):
  The plan sketched Tests B/C as `run_conversion_job(engine="kokoro")` and
  `run_batch_convert(engine="kokoro")`. Those two functions are **Edge-TTS only**
  in the actual codebase — they call `edge_tts.Communicate` and have no `engine`
  parameter. The real Kokoro path the GUI uses (and the one that failed in the
  user's log) is `pdf_extractor.pdf_to_txt` -> `kokoro_synth.kokoro_file_to_mp3`.
  This harness drives that real path so it genuinely exercises Kokoro, mirroring
  `tts/epub2tts_gui.py`'s Kokoro single-file and batch loops.

The HuggingFace cache is redirected into the project tree by `kokoro_synth` on
import (and by bootstrap/launcher in normal runs), so importing it first keeps the
~300 MB model out of ~/.cache/huggingface/.
"""

from __future__ import annotations

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# --- Make scripts/ importable so `tts.*` / `shared.*` resolve regardless of cwd.
_THIS = Path(__file__).resolve()
SCRIPTS_ROOT = _THIS.parent.parent          # <os_root>/scripts
OS_ROOT = SCRIPTS_ROOT.parent               # <os_root> (Windows/ or MacOS/)
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

# Import kokoro_synth early: its module-load HF_HOME redirect points the model
# cache at <os_root>/resources/models/huggingface/ before kokoro is ever imported.
from tts.kokoro_synth import kokoro_file_to_mp3, synthesize_text_to_mp3  # noqa: E402
from tts.pdf_extractor import pdf_to_txt  # noqa: E402
from shared import ffmpeg_utils  # noqa: E402

# Pin pydub's ffmpeg/ffprobe to the resolved binary (bundled bin/ or PATH) so the
# MP3 export inside Kokoro synthesis works the same way the launched app does.
ffmpeg_utils.configure_pydub()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
VOICES = [
    ("af_heart", "Heart"),
    ("af_bella", "Bella"),
    ("am_michael", "Michael"),
    ("bf_emma", "Emma"),
    ("bm_george", "George"),
]

# The user's real chapter-PDF folder. Set it here, or override at run time with
# the KOKORO_TEST_PDF_FOLDER environment variable. Tests B and C are skipped (not
# failed) if this points at the unfilled placeholder or a missing folder.
INPUT_PDF_FOLDER = Path(
    os.environ.get(
        "KOKORO_TEST_PDF_FOLDER",
        r"C:\Users\ematthew\Desktop\Apps\Coding\Repository_Workspaces\MyProjects\Home-PC\Audiobook-Creation-Tool\test-files\webscraped_shadow_slave-1",
    )
)
TEST_PDF_NAME = "Chapter 20_ Outcast Once Again.pdf"
BATCH_VOICE = "bf_emma"

# All outputs go under the project tree (gitignored), never the user's home.
TEST_LOGS_DIR = OS_ROOT / "resources" / "test-logs"


def _input_folder_ready() -> bool:
    return (
        str(INPUT_PDF_FOLDER) != "<INPUT_PDF_FOLDER>"
        and INPUT_PDF_FOLDER.is_dir()
    )


def probe_mp3(path: Path) -> float:
    """Return the duration in seconds of an MP3 via ffprobe (0.0 on any error)."""
    try:
        r = subprocess.run(
            [
                ffmpeg_utils.ffprobe_cmd(), "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(path),
            ],
            capture_output=True, text=True,
        )
        return float((r.stdout or "").strip() or 0.0)
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Test A — smoke-test all 5 voices with short synthetic text
# ---------------------------------------------------------------------------
SMOKE_TEXT = (
    "The quick brown fox jumps over the lazy dog. "
    "Testing Kokoro voice synthesis."
)


def smoke() -> list[tuple[str, str]]:
    out_dir = TEST_LOGS_DIR / "voice_smoke"
    out_dir.mkdir(parents=True, exist_ok=True)
    failures: list[tuple[str, str]] = []
    for code, name in VOICES:
        out = out_dir / f"smoke_{code}.mp3"
        try:
            # Actual signature: synthesize_text_to_mp3(text, output_path, voice_id, speed, log)
            synthesize_text_to_mp3(SMOKE_TEXT, str(out), code, speed=1.0)
            dur = probe_mp3(out)
            size = out.stat().st_size if out.exists() else 0
            ok = (dur >= 2.0) and (size >= 20_000)
            print(f"{'PASS' if ok else 'FAIL'} {name:8s} ({code}) -> "
                  f"{out.name} {size}B {dur:.2f}s")
            if not ok:
                failures.append((code, f"dur={dur} size={size}"))
        except Exception as exc:
            print(f"FAIL {name:8s} ({code}) -> {exc!r}")
            failures.append((code, repr(exc)))
    return failures


# ---------------------------------------------------------------------------
# Test B — end-to-end one real PDF with each voice
# ---------------------------------------------------------------------------
def _kokoro_pdf_to_mp3(pdf: Path, out_mp3: Path, voice_id: str,
                       speed: float = 1.0) -> None:
    """Replicate the GUI's Kokoro single-file path: PDF -> text -> Kokoro MP3."""
    import tempfile
    with tempfile.TemporaryDirectory(prefix="kk_e2e_") as td:
        txt_path = str(Path(td) / f"{pdf.stem}.txt")
        pdf_to_txt(str(pdf), txt_path)
        kokoro_file_to_mp3(
            txt_path,
            str(out_mp3),
            voice_id=voice_id,
            speed=speed,
            end_silence_ms=3000,
            log=lambda s: None,
        )


def end_to_end() -> list[tuple[str, str]]:
    test_pdf = INPUT_PDF_FOLDER / TEST_PDF_NAME
    if not test_pdf.exists():
        print(f"SKIP E2E — test PDF not found: {test_pdf}")
        return []
    out_dir = TEST_LOGS_DIR / "voice_e2e"
    out_dir.mkdir(parents=True, exist_ok=True)
    failures: list[tuple[str, str]] = []
    for code, name in VOICES:
        out_mp3 = out_dir / f"ch20_{code}.mp3"
        try:
            _kokoro_pdf_to_mp3(test_pdf, out_mp3, code, speed=1.0)
            dur = probe_mp3(out_mp3) if out_mp3.exists() else 0.0
            size = out_mp3.stat().st_size if out_mp3.exists() else 0
            ok = (dur >= 60.0) and (size >= 200_000)
            print(f"{'PASS' if ok else 'FAIL'} E2E {name:8s} -> "
                  f"{out_mp3.name} {size}B {dur:.1f}s")
            if not ok:
                failures.append((code, f"dur={dur} size={size}"))
        except Exception as exc:
            print(f"FAIL E2E {name:8s} -> {exc!r}")
            failures.append((code, repr(exc)))
    return failures


# ---------------------------------------------------------------------------
# Test C — full 10-PDF batch with the default Kokoro voice (Emma)
# ---------------------------------------------------------------------------
def batch_smoke() -> list[str]:
    """Mirror the GUI's inline Kokoro batch loop (tts/epub2tts_gui.py): a
    ThreadPoolExecutor of PDF -> text -> Kokoro MP3 jobs. This is the exact
    scenario from the user's failure log; it must finish with 0 failures."""
    import re
    import tempfile

    out_dir = TEST_LOGS_DIR / "voice_batch"
    out_dir.mkdir(parents=True, exist_ok=True)

    def _natural_sort_key(p: Path) -> list:
        parts = re.split(r"(\d+)", p.stem)
        return [int(x) if x.isdigit() else x.lower() for x in parts]

    pdfs = sorted(INPUT_PDF_FOLDER.rglob("*.pdf"), key=_natural_sort_key)
    total = len(pdfs)
    print(f"Kokoro batch: {total} PDFs to process with {BATCH_VOICE}.")
    if total == 0:
        print("SKIP batch — no PDFs found in input folder.")
        return []

    def _do_one(pdf: Path) -> tuple[str, str]:
        out_mp3 = out_dir / f"{pdf.stem}.mp3"
        try:
            with tempfile.TemporaryDirectory(prefix=f"kk_{pdf.stem[:8]}_") as td:
                txt_path = str(Path(td) / f"{pdf.stem}.txt")
                pdf_to_txt(str(pdf), txt_path)
                kokoro_file_to_mp3(
                    txt_path, str(out_mp3), voice_id=BATCH_VOICE, speed=1.0,
                    log=lambda s: None,
                )
            return "completed", ""
        except Exception as exc:
            return "FAILED", str(exc)

    log_lines: list[str] = []
    done = 0
    with ThreadPoolExecutor(max_workers=3) as ex:  # match the GUI screenshot (3 workers)
        futs = {ex.submit(_do_one, p): p for p in pdfs}
        for fut in as_completed(futs):
            pdf = futs[fut]
            status, msg = fut.result()
            done += 1
            line = f"[{done}/{total}] {pdf.name} — {status}"
            if msg:
                line += f": {msg}"
            log_lines.append(line)

    for line in log_lines:
        print(line)
    return [l for l in log_lines if "FAILED" in l or "ABORTED" in l]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    print(f"Project tree : {OS_ROOT}")
    print(f"HF_HOME      : {os.environ.get('HF_HOME')}")
    print(f"Input folder : {INPUT_PDF_FOLDER}"
          + ("" if _input_folder_ready() else "  (NOT SET / missing — B & C skip)"))

    print("=== Test A: Smoke ===")
    fa = smoke()

    if not _input_folder_ready():
        print("=== Test B & C skipped (set KOKORO_TEST_PDF_FOLDER or "
              "INPUT_PDF_FOLDER to the real chapter-PDF folder) ===")
        return 1 if fa else 0

    print("=== Test B: End-to-end per voice ===")
    fb = end_to_end()
    print("=== Test C: Full batch (Emma) ===")
    fc = batch_smoke()

    print("=== Summary ===")
    print(f"  A smoke failures : {len(fa)}")
    print(f"  B e2e failures   : {len(fb)}")
    print(f"  C batch failures : {len(fc)}")
    return 0 if not (fa or fb or fc) else 1


if __name__ == "__main__":
    raise SystemExit(main())
