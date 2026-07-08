"""Batch convert a folder of PDFs and/or TXT files to one MP3 per file.

Nested input subfolders are mirrored under the output folder (a PDF at
``input/Book 1/Chapter 1.pdf`` becomes ``output/Book 1/Chapter 1.mp3``), so
same-named files in different subfolders never overwrite each other. Files
directly in the input folder keep the original flat output layout.
"""

from __future__ import annotations

import argparse
import asyncio
import re as _re
import shutil
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

import edge_tts
from pydub import AudioSegment
from tqdm import tqdm

# Ensure the scripts/ root is importable so `tts.*` resolves when this module
# is run directly as a script (python scripts/tts/batch_convert.py).
import sys as _sys
from pathlib import Path as _Path

_SCRIPTS_ROOT = _Path(__file__).resolve().parent.parent
if str(_SCRIPTS_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_SCRIPTS_ROOT))

from tts.pdf_extractor import extract_text_from_pdf

DEFAULT_SPEAKER = "en-US-SteffanNeural"
CHUNK_TARGET = 3000
CHUNK_PAUSE_MS = 50
INTER_CHUNK_DELAY_SEC = 0.8
END_RECORDING_SILENCE_MS = 3000
CHUNK_MAX_RETRIES = 5
PDF_MAX_RETRIES = 2


def _natural_sort_key(path: Path) -> list[object]:
    """
    Split the filename stem into alternating string / integer segments so that
    embedded numbers sort numerically rather than lexicographically.
    e.g. "Chapter 9" < "Chapter 10" instead of "Chapter 10" < "Chapter 9".
    """
    parts = _re.split(r"(\d+)", path.stem)
    return [int(p) if p.isdigit() else p.lower() for p in parts]


def split_into_chunks(text: str, max_chars: int = CHUNK_TARGET) -> list[str]:
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


async def chunk_to_mp3(text: str, path: str, voice: str, rate: str) -> None:
    comm = edge_tts.Communicate(text=text, voice=voice, rate=rate)
    await comm.save(path)


def synthesize_chunk_mp3(text: str, path: str, voice: str, rate: str) -> None:
    asyncio.run(chunk_to_mp3(text, path, voice, rate))


def merge_mp3s(chunk_paths: list[str], output_mp3_path: str) -> None:
    combined = AudioSegment.empty()
    silence = AudioSegment.silent(duration=CHUNK_PAUSE_MS)
    for chunk_path in chunk_paths:
        combined += AudioSegment.from_mp3(chunk_path) + silence
    if END_RECORDING_SILENCE_MS > 0:
        combined += AudioSegment.silent(duration=END_RECORDING_SILENCE_MS)
    combined.export(output_mp3_path, format="mp3")


def convert_single_pdf(
    pdf_path: Path,
    output_dir: Path,
    speaker: str,
    rate: str,
    log=print,
    progress_report: Callable[[str, str], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    out_mp3: Path | None = None,
) -> tuple[str, Path, str | None]:
    """Convert one source file (.pdf or .txt) to MP3.

    ``out_mp3`` is the mirrored target computed by run_batch_convert; when
    omitted (direct callers) it falls back to the flat ``output_dir/<stem>.mp3``.
    """
    stem = pdf_path.stem
    if out_mp3 is None:
        out_mp3 = output_dir / f"{stem}.mp3"
    # Temp dir must be unique per SOURCE, not per stem — two same-named files in
    # different subfolders would otherwise share (and clobber) one chunk dir.
    try:
        tmp_key = "__".join(out_mp3.relative_to(output_dir).with_suffix("").parts)
    except ValueError:  # out_mp3 not under output_dir (direct caller)
        tmp_key = stem
    tmp_root = output_dir / ".tmp_chunks" / tmp_key
    last_err: str | None = None

    def _cancelled() -> bool:
        return cancel_check is not None and cancel_check()

    try:
        if _cancelled():
            return "cancelled", pdf_path, None
        for pdf_attempt in range(PDF_MAX_RETRIES + 1):
            chunk_paths: list[str] = []
            if pdf_attempt > 0:
                log(
                    f"  [PDF retry {pdf_attempt}/{PDF_MAX_RETRIES}] Cleaning and retrying: {pdf_path.name}"
                )
                shutil.rmtree(tmp_root, ignore_errors=True)
                tmp_root.mkdir(parents=True, exist_ok=True)
                time.sleep(5)

            try:
                if pdf_path.suffix.lower() == ".txt":
                    text = pdf_path.read_text(encoding="utf-8")
                else:
                    text = extract_text_from_pdf(str(pdf_path))
                chunks = split_into_chunks(text)
                if not chunks:
                    last_err = "No text chunks after split"
                    raise RuntimeError(last_err)

                tmp_root.mkdir(parents=True, exist_ok=True)
                for idx, chunk in enumerate(chunks, start=1):
                    if _cancelled():  # between chunks
                        return "cancelled", pdf_path, None
                    cpath = str(tmp_root / f"chunk_{idx:03d}.mp3")
                    for attempt in range(CHUNK_MAX_RETRIES):
                        try:
                            synthesize_chunk_mp3(chunk, cpath, speaker, rate)
                            break
                        except Exception as e:
                            if attempt < CHUNK_MAX_RETRIES - 1:
                                wait = 2 ** (attempt + 1)
                                log(
                                    f"  [retry {attempt+1}/{CHUNK_MAX_RETRIES-1}] "
                                    f"chunk {idx} of {pdf_path.name} — waiting {wait}s ({e})"
                                )
                                time.sleep(wait)
                                continue
                            raise
                    chunk_paths.append(cpath)
                    time.sleep(INTER_CHUNK_DELAY_SEC)

                out_mp3.parent.mkdir(parents=True, exist_ok=True)
                merge_mp3s(chunk_paths, str(out_mp3))
                if progress_report is not None:
                    progress_report(stem, "completed")
                return "success", pdf_path, None
            except Exception as e:
                last_err = f"{e}\n{traceback.format_exc()}"
                if pdf_attempt < PDF_MAX_RETRIES:
                    continue
                if progress_report is not None:
                    progress_report(stem, "failed")
                return "failed", pdf_path, last_err

        # Should be unreachable; retained as a safety net.
        if progress_report is not None:
            progress_report(stem, "failed")
        return "failed", pdf_path, last_err or "Unknown error"
    finally:
        if tmp_root.exists():
            shutil.rmtree(tmp_root, ignore_errors=True)


def run_batch_convert(
    input_dir: str | Path,
    output_dir: str | Path,
    *,
    speaker: str = DEFAULT_SPEAKER,
    workers: int = 2,
    rate: str = "+0%",
    resume: bool = False,
    use_tqdm: bool = True,
    log=print,
    progress_callback: Callable[[str, int, int, str], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> tuple[int, int, Path]:
    """Convert each PDF/TXT under input_dir to an MP3 in output_dir, mirroring
    any input subfolder structure. Returns (ok, fail, error_log_path)."""
    input_dir = Path(input_dir).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    tmp_chunks_root = output_dir / ".tmp_chunks"
    if tmp_chunks_root.exists():
        orphaned = [d for d in tmp_chunks_root.iterdir() if d.is_dir()]
        if orphaned:
            log(
                f"  Found {len(orphaned)} in-progress temp dir(s) from a previous interrupted run — cleaning up..."
            )
            for d in orphaned:
                shutil.rmtree(d, ignore_errors=True)
                log(f"    Removed: {d.name}")
            log("  Cleanup complete. These PDFs will be re-processed from scratch.")

    # Suffix check instead of rglob("*.pdf") so .pdf/.txt match on every
    # platform regardless of filename case.
    sources = sorted(
        (
            p
            for p in input_dir.rglob("*")
            if p.is_file() and p.suffix.lower() in (".pdf", ".txt")
        ),
        key=_natural_sort_key,
    )
    # Mirror each source's path relative to input_dir under output_dir; files
    # directly in input_dir keep the original flat layout (rel has no parent).
    jobs: list[tuple[Path, Path]] = [
        (p, output_dir / p.relative_to(input_dir).with_suffix(".mp3")) for p in sources
    ]
    if resume:
        kept: list[tuple[Path, Path]] = []
        for p, target in jobs:
            if target.exists():
                log(f"Skipping (already exists): {p.name}")
            else:
                kept.append((p, target))
        jobs = kept

    log("============================================")
    log("  Batch TTS Converter — Steffan Neural")
    log("============================================")
    log(f"  Input folder  : {input_dir}")
    log(f"  Output folder : {output_dir}")
    log(f"  Files found   : {len(jobs)}")
    log(f"  Workers       : {workers}")
    log("============================================")

    error_log = output_dir / "batch_errors.log"
    if not jobs:
        log("No PDF or TXT files to process.")
        return 0, 0, error_log

    t0 = time.perf_counter()
    ok = 0
    fail = 0
    total = len(jobs)
    completed_lock = threading.Lock()
    completed_so_far = [0]

    def _report_progress(pdf_name: str, status: str) -> None:
        if progress_callback is None:
            return
        with completed_lock:
            completed_so_far[0] += 1
            done = completed_so_far[0]
        progress_callback(pdf_name, done, total, status)

    cancelled = False
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {
            ex.submit(
                convert_single_pdf,
                p,
                output_dir,
                speaker,
                rate,
                log,
                _report_progress,
                cancel_check,
                target,
            ): p
            for p, target in jobs
        }
        iterator = as_completed(futures)
        if use_tqdm:
            iterator = tqdm(iterator, total=len(futures), desc="Converting files")
        for fut in iterator:
            status, path, msg = fut.result()
            if status == "success":
                ok += 1
            elif status == "cancelled":
                pass  # not counted as a failure
            else:
                fail += 1
                with open(error_log, "a", encoding="utf-8") as lf:
                    lf.write(f"{path}\n{msg}\n\n")
            if cancel_check is not None and cancel_check():
                # Stop dispatching: cancel queued (not-yet-started) PDFs; in-flight
                # workers bail at their own between-chunk checkpoint and return fast.
                cancelled = True
                for f in futures:
                    f.cancel()
                break

    tmp_chunks = output_dir / ".tmp_chunks"
    if tmp_chunks.exists():
        shutil.rmtree(tmp_chunks, ignore_errors=True)

    elapsed = time.perf_counter() - t0
    mins, sec = divmod(int(elapsed), 60)
    hrs, mins = divmod(mins, 60)
    log("============================================")
    if cancelled:
        log("  Cancelled.")
    log(f"  Completed : {ok}")
    log(f"  Failed    : {fail}" + (f"  (see {error_log})" if fail else ""))
    log(f"  Total time : {hrs}h {mins}m {sec}s")
    log("============================================")
    return ok, fail, error_log


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch PDF/TXT to MP3 (Edge TTS)")
    parser.add_argument("--input", required=True, help="Folder containing PDF/TXT files")
    parser.add_argument("--output", default="./output_mp3s/", help="Output folder for MP3s")
    parser.add_argument("--speaker", default=DEFAULT_SPEAKER, help="edge-tts voice name")
    parser.add_argument("--workers", type=int, default=2, help="Parallel file jobs")
    parser.add_argument("--rate", default="+0%", help="Speech rate, e.g. +10%%")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip files that already have a matching MP3 in the output folder",
    )
    args = parser.parse_args()
    run_batch_convert(
        args.input,
        args.output,
        speaker=args.speaker,
        workers=args.workers,
        rate=args.rate,
        resume=args.resume,
        use_tqdm=True,
    )


if __name__ == "__main__":
    main()
