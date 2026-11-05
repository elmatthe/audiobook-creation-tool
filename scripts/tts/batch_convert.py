"""Batch convert a folder of PDFs and/or TXT files to one MP3 per file.

Nested input subfolders are mirrored under the output folder (a PDF at
``input/Book 1/Chapter 1.pdf`` becomes ``output/Book 1/Chapter 1-<voice label>.mp3``),
so same-named files in different subfolders never overwrite each other. Files
directly in the input folder keep the original flat output layout.

v0.7.0 P02B: the standalone helper names its files like the app does,
``<source-stem>-<display label>.mp3`` (:mod:`tts.output_names`), through the
shared collision planner — so a PDF and a TXT with one stem, or an output left by
an earlier run, get ``-1``/``-2`` instead of being overwritten.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import re as _re
import secrets
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

from shared import ffmpeg_utils, output_paths
from shared.cancellation import ConversionCancelled
from tts import audio_tail, edge_failures, ffmpeg_watch, output_names, publication, worker_limits
from tts.edge_requests import await_unless_cancelled, run_request, wait_unless_cancelled
from tts.pdf_extractor import extract_text_from_pdf
from tts.speech.document import read_source_text
from tts.speech.pipeline import prepare
from tts.speech.profiles import EDGE_FOLDER

ffmpeg_watch.install()  # every FFmpeg pydub starts for this route can be stopped, and cannot hang it

DEFAULT_SPEAKER = "en-US-SteffanNeural"
CHUNK_TARGET = 3000
CHUNK_PAUSE_MS = 50  # between two chunks only; v0.7.0 (Q1) removed the 3000 ms closing silence after the last
INTER_CHUNK_DELAY_SEC = 0.8
CHUNK_MAX_RETRIES = 5
PDF_MAX_RETRIES = 2
#: A source's scratch folder gets a new chunk every few seconds while it is synthesising, so one untouched for this long
#: is not busy, unless the process named in it is alive and assembling.
STALE_CHUNK_FOLDER_SECONDS = 3600
_CHUNK_FOLDER_NAME = _re.compile(r"([0-9a-f]{8})-[0-9a-f]{8}")


def _new_chunk_folder_name() -> str:
    """Private to one conversion, so two runs sharing an output folder can never read each other's audio, and short,
    so a deep output tree does not push the scratch paths past what the platform allows."""
    return f"{os.getpid() & 0xFFFFFFFF:08x}-{secrets.token_hex(4)}"


def _is_stale_chunk_folder(folder: Path) -> bool:
    try:
        if not folder.is_dir() or time.time() - folder.stat().st_mtime <= STALE_CHUNK_FOLDER_SECONDS:
            return False
    except OSError:  # gone already: another run finished with it
        return False
    owner = _CHUNK_FOLDER_NAME.fullmatch(folder.name)
    return owner is None or not publication.process_is_alive(int(owner.group(1), 16))


def sweep_stale_chunk_folders(root: Path) -> list[Path]:
    """Remove what an interrupted run left in its chunk folders, anywhere below ``root``. Only a folder named as this tool names
    them, directly inside a ``.tmp_chunks``, whose owner is gone and which has lain untouched (:func:`_is_stale_chunk_folder`): nothing
    in one can be resumed, and an unfinished assembly's working WAV can be as large as the whole narration."""
    removed: list[Path] = []
    for folder, subfolders, _names in os.walk(root, followlinks=False):
        subfolders[:] = [sub for sub in subfolders if not output_paths._is_link(Path(folder) / sub)]
        if Path(folder).name == ".tmp_chunks":
            for sub in list(subfolders):
                candidate = Path(folder) / sub
                if _CHUNK_FOLDER_NAME.fullmatch(sub) and _is_stale_chunk_folder(candidate):
                    shutil.rmtree(candidate, ignore_errors=True)
                    if not candidate.exists():
                        removed.append(candidate)
            subfolders[:] = []
    return removed


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


async def chunk_to_mp3(text: str, path: str, voice: str, rate: str, cancel_check: Callable[[], bool] | None = None) -> None:
    """One chunk from the service. The conversion's Cancel (v0.7.2) abandons the request in flight; the chunk file, if anything
    was written, goes with it. ``cancel_check`` defaults to that of the :func:`ffmpeg_watch.controlled` block this conversion
    runs inside, so the call sites, and the test doubles that stand in for them, keep their shape."""
    if cancel_check is None:
        cancel_check = ffmpeg_watch.current_cancel_check()
    comm = edge_tts.Communicate(text=text, voice=voice, rate=rate)
    try:
        await await_unless_cancelled(comm.save(path), cancel_check)
    except ConversionCancelled:
        # A request that would not stop still holds it open, and that is no reason to report anything but the Cancel: the
        # item's working folder goes at the end of the attempt, by which time the request has been dropped.
        with contextlib.suppress(OSError):
            Path(path).unlink(missing_ok=True)
        raise


def synthesize_chunk_mp3(text: str, path: str, voice: str, rate: str, cancel_check: Callable[[], bool] | None = None) -> None:
    # Called with the four arguments it always took unless a check is given explicitly: the offline probes stand in for
    # ``chunk_to_mp3`` with that shape, and the production route finds its check in the controlled context anyway.
    request = chunk_to_mp3(text, path, voice, rate) if cancel_check is None else chunk_to_mp3(text, path, voice, rate, cancel_check)
    run_request(request, note=print)


def merge_mp3s(chunk_paths: list[str], output_mp3_path: str,
               bitrate: str | None = None) -> audio_tail.FinalTail:
    """Join the per-chunk MP3s the Edge service returned into one file.

    Unlike the local engines this genuinely cannot avoid a second generation —
    the chunks arrive from the network already encoded, so merging them means
    decoding and re-encoding. What it *can* do is stop leaving the final encode
    to ffmpeg's defaults, which is what produced files whose advertised duration
    was half their real length (see ``shared.ffmpeg_utils``).

    The ``CHUNK_PAUSE_MS`` join goes *between* chunks only, and the v0.7.0
    final-tail policy (:mod:`tts.audio_tail`) shortens the last chunk's own
    network padding on the decoded PCM, inside this one encode. The padding
    closing every earlier chunk is pacing and stays. Returns the tail facts
    for the caller's log.
    """
    combined = AudioSegment.empty()
    silence = AudioSegment.silent(duration=CHUNK_PAUSE_MS)
    for index, chunk_path in enumerate(chunk_paths):
        if index:
            combined += silence
        combined += AudioSegment.from_mp3(chunk_path)
    combined, tail = audio_tail.apply_final_tail_policy_to_segment(combined)
    publication.check_narration(combined)
    combined.export(output_mp3_path, **ffmpeg_utils.mp3_export_options(bitrate))
    publication.verify_finished_mp3(output_mp3_path, len(combined))
    return tail


def merge_mp3s_on_disk(chunk_paths: list[str], output_mp3_path: str, bitrate: str | None, spool_path) -> str:
    """:func:`merge_mp3s`, to the byte, for a narration that does not fit in memory (:mod:`tts.disk_assembly`).
    Returns the final tail's summary for the caller's log."""
    from tts import disk_assembly

    silence = AudioSegment.silent(duration=CHUNK_PAUSE_MS)
    parts = [part for index, chunk in enumerate(chunk_paths) for part in ((silence, chunk) if index else (chunk,))]
    options = ffmpeg_utils.mp3_export_options(bitrate)
    return disk_assembly.encode_mp3(parts, output_mp3_path, spool_path, format="mp3", codec=options["codec"],
                                    bitrate=options["bitrate"])


def convert_single_pdf(
    pdf_path: Path,
    output_dir: Path,
    speaker: str,
    rate: str,
    log=print,
    progress_report: Callable[[str, str], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    out_mp3: Path | None = None,
    bitrate: str | None = None,
    speech_prep=None,
    overwrite: bool = False,
) -> tuple[str, Path, str | None]:
    """Convert one source file (.pdf or .txt) to MP3.

    ``out_mp3`` is the mirrored target computed by run_batch_convert; when
    omitted (direct callers) it falls back to the flat ``output_dir/<stem>.mp3``.

    ``bitrate`` is the run's chosen MP3 bitrate, passed through to the final
    encode so this folder path and the Edge direct path agree on the output
    contract instead of one of them silently using ffmpeg's default.

    The MP3 reaches ``out_mp3`` only through :mod:`tts.publication`: complete, all at once, and (unless ``overwrite``)
    never over a file that is already there. A failed or cancelled attempt leaves that path exactly as it found it. Cancel
    is honoured everywhere (v0.7.2): during a request, between chunks, through every back-off, at the memory gate, during
    the assembly (:mod:`tts.ffmpeg_watch` kills the encoder) and up to the instant of publication. A narration with all its
    chunks is not finished work past a Cancel: nothing of it is saved.
    """
    with ffmpeg_watch.controlled(cancel_check):
        return _convert_single_pdf(pdf_path, output_dir, speaker, rate, log, progress_report, cancel_check, out_mp3, bitrate,
                                   speech_prep, overwrite)


def _convert_single_pdf(pdf_path, output_dir, speaker, rate, log, progress_report, cancel_check, out_mp3, bitrate, speech_prep,
                        overwrite) -> tuple[str, Path, str | None]:
    stem = pdf_path.stem
    if out_mp3 is None:
        out_mp3 = output_dir / f"{stem}.mp3"
    # The temp dir must be this conversion's alone: two same-named files in different subfolders, or two runs sharing
    # this output folder, would otherwise share (and clobber) one chunk dir, and a run could publish another's audio.
    tmp_root = output_dir / ".tmp_chunks" / _new_chunk_folder_name()
    last_err: str | None = None

    def _cancelled() -> bool:
        return cancel_check is not None and cancel_check()

    try:
        if _cancelled():
            return "cancelled", pdf_path, None
        try:
            publication.refuse_existing(out_mp3, overwrite)  # before hours of synthesis it could never publish
        except publication.DestinationExists as exc:
            if progress_report is not None:
                progress_report(stem, "failed")
            return "failed", pdf_path, str(exc)
        for pdf_attempt in range(PDF_MAX_RETRIES + 1):
            chunk_paths: list[str] = []
            if pdf_attempt > 0:
                log(
                    f"  [PDF retry {pdf_attempt}/{PDF_MAX_RETRIES}] Cleaning and retrying: {pdf_path.name}"
                )
                shutil.rmtree(tmp_root, ignore_errors=True)
                tmp_root.mkdir(parents=True, exist_ok=True)
                wait_unless_cancelled(5, cancel_check)

            try:
                if pdf_path.suffix.lower() == ".txt":
                    # utf-8-sig: a leading BOM is a signature, not text (the
                    # documented UTF-8 / UTF-8-with-BOM TXT contract).
                    text = read_source_text(pdf_path)
                else:
                    text = extract_text_from_pdf(str(pdf_path))
                # Speech preparation (Plan 01B A3) on the decoded or extracted text; this route reads no structure, so
                # the prepared text is the whole text. None or "off" leaves it unchanged.
                prepared = prepare(text, speech_prep, EDGE_FOLDER)
                if pdf_attempt == 0:
                    for detail in prepared.details():
                        log(f"  {detail}")
                text = prepared.text
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
                        except ConversionCancelled:
                            raise
                        except Exception as e:
                            # Only a failure another attempt can plausibly cure is retried (see edge_failures):
                            # a refused handshake or a changed protocol would fail identically every time.
                            if edge_failures.is_retryable(e) and attempt < CHUNK_MAX_RETRIES - 1:
                                wait = 2 ** (attempt + 1)
                                log(
                                    f"  [retry {attempt+1}/{CHUNK_MAX_RETRIES-1}] "
                                    f"chunk {idx} of {pdf_path.name} — waiting {wait}s ({edge_failures.describe(e)})"
                                )
                                wait_unless_cancelled(wait, cancel_check)  # never sit out a back-off the person has cancelled
                                continue
                            final = edge_failures.final_error(e, attempt + 1)
                            if final is e:
                                raise
                            raise final from e
                    chunk_paths.append(cpath)
                    wait_unless_cancelled(INTER_CHUNK_DELAY_SEC, cancel_check)

                with publication.Stage(out_mp3, overwrite=overwrite) as stage:
                    # The whole narration is about to be assembled: in memory if it fits, after a wait if other files need
                    # that memory first, and on disk if it does not or if memory runs out on the way. A Cancel at any point
                    # from here to the instant of publication stops it, and nothing of it is saved (v0.7.2).
                    def in_memory():
                        tail = merge_mp3s(chunk_paths, str(stage.path), bitrate)
                        return None if tail is None else tail.summary()  # test doubles of merge_mp3s return nothing

                    summary = worker_limits.assemble(
                        worker_limits.decoded_size(chunk_paths), in_memory,
                        lambda: merge_mp3s_on_disk(chunk_paths, str(stage.path), bitrate, tmp_root / "assembly.wav"),
                        cancel_check=cancel_check, note=log)
                    if summary is not None:
                        log(f"  {pdf_path.name}: {summary}")
                    stage.publish(cancel_check)
                if progress_report is not None:
                    progress_report(stem, "completed")
                return "success", pdf_path, None
            except ConversionCancelled:
                return "cancelled", pdf_path, None  # already said out loud, if it cost a finished narration
            except Exception as e:
                # The log may be shared for diagnosis: scrub handshake tokens out of the message and traceback.
                if worker_limits.is_memory_failure(e):  # however it surfaced, it says what happened
                    e = worker_limits.AssemblyMemoryError(worker_limits.out_of_memory_text(f"{type(e).__name__}: {e}"[:200]))
                last_err = edge_failures.scrub(f"{e}\n{traceback.format_exc()}")
                # Redoing the whole file cannot cure a permanent failure (refused/changed service, local problem).
                if pdf_attempt < PDF_MAX_RETRIES and edge_failures.is_retryable(e):
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
    label: str | None = None,
) -> tuple[int, int, Path]:
    """Convert each PDF/TXT under input_dir to an MP3 in output_dir, mirroring
    any input subfolder structure. Returns (ok, fail, error_log_path).

    Each file is ``<stem>-<label>.mp3``. ``label`` defaults to the registered
    display label of the Edge voice ``speaker``; an unregistered speaker needs an
    explicit one. Every name is planned before anything is synthesised, and a name
    that cannot fit is refused (:class:`shared.output_paths.OutputPathError`).
    ``resume`` skips a source whose planned file already exists; without it an
    existing file is never overwritten — the new one is numbered instead.
    """
    if label is None:
        from tts.voice_registry import voice_by_key

        entry = voice_by_key("edge", speaker)
        if entry is None:
            raise ValueError(f"{speaker} is not a registered Edge voice; give the output files a label "
                             "(run_batch_convert(label=...), or --label on the command line)")
        label = entry.display_label
    input_dir = Path(input_dir).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    for leftover in publication.sweep_orphans(output_dir):
        log(f"  Removed an unfinished file from an interrupted run: {leftover.name}")
    tmp_chunks_root = output_dir / ".tmp_chunks"
    if tmp_chunks_root.exists():
        orphaned = [d for d in tmp_chunks_root.iterdir() if _is_stale_chunk_folder(d)]
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
    # One shared planner names them all, so no two sources share a file. Resume
    # plans without looking at the disk, so an earlier run's file is found under
    # the very name it was given and skipped; otherwise the disk is consulted and
    # nothing that already exists is ever chosen.
    planner = output_paths.DestinationPlanner(output_dir, check_filesystem=not resume)
    plan = output_names.plan_named(output_paths.plan_mirrored, output_dir, sources, input_dir,
                                   label=label, planner=planner)
    jobs: list[tuple[Path, Path]] = [(item.source, item.destination) for item in plan.items]
    if resume:
        kept: list[tuple[Path, Path]] = []
        for p, target in jobs:
            if target.exists():
                log(f"Skipping (already exists): {p.name}")
            else:
                kept.append((p, target))
        jobs = kept

    # v0.7.1: the same worker policy as the app (queue, Edge service ceiling, processors, free memory).
    plan = worker_limits.plan_for_sources(workers, "edge",
                                          [worker_limits.QueuedSource(p, direct=False) for p, _target in jobs],
                                          settings=worker_limits.NarrationSettings(rate=rate),
                                          should_stop=cancel_check)
    workers = plan.effective

    log("============================================")
    log("  Batch TTS Converter — Steffan Neural")
    log("============================================")
    log(f"  Input folder  : {input_dir}")
    log(f"  Output folder : {output_dir}")
    log(f"  Files found   : {len(jobs)}")
    log(f"  Workers       : {workers}")
    for line in plan.log_lines():
        log(f"  {line}")
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

    try:
        (output_dir / ".tmp_chunks").rmdir()  # each source removed its own folder; another run's would still be here
    except OSError:
        pass

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
    parser.add_argument("--workers", type=int, default=2,
                        help="Parallel file jobs requested; held to what the queue, processors and free memory allow")
    parser.add_argument("--rate", default="+0%", help="Speech rate, e.g. +10%%")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip files that already have a matching MP3 in the output folder",
    )
    parser.add_argument(
        "--label",
        default=None,
        help="Voice name in the output file names (<stem>-<label>.mp3); "
             "defaults to the registered label of --speaker",
    )
    args = parser.parse_args()
    try:
        run_batch_convert(
            args.input,
            args.output,
            speaker=args.speaker,
            workers=args.workers,
            rate=args.rate,
            resume=args.resume,
            use_tqdm=True,
            label=args.label,
        )
    except (ValueError, output_paths.OutputPathError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
