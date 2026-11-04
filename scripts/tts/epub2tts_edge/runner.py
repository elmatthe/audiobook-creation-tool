"""Run one conversion in its own private working folder; optionally place output in output_dir.

Safe to call from several threads at once (v0.7.1): each call has its own folder and never changes the
process-wide current folder.
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata
import shutil
import tempfile
import traceback
from pathlib import Path

from .epub2tts_edge import (
    DEFAULT_CHAPTER_PAUSE_MS,
    DEFAULT_END_OF_BOOK_PAUSE_MS,
    DEFAULT_PARAGRAPH_PAUSE_MS,
    DEFAULT_SENTENCE_PAUSE_MS,
    DEFAULT_SPEAKER,
    DEFAULT_TITLE_PAUSE_MS,
    DEFAULT_TRIM_SILENCE_DB,
    _ensure_shared_on_path,
    add_cover,
    generate_metadata,
    get_book,
    make_m4b,
    make_mp3,
    make_mp3_on_disk,
    read_book,
)


def _normalize_for_match(s: str) -> str:
    """Collapse Unicode variants to ASCII-friendly form for reliable title-line removal."""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\u00a0", " ")
    s = s.replace("\u2013", "-").replace("\u2014", "-")
    return s


def _ensure_pdf_txt_has_chapter_heading(work_txt: str) -> None:
    """
    If the extracted PDF text has no '#' heading, inject one.

    The spoken chapter title is taken only from document text: the first non-empty
    line of the extract. The PDF filename is never used for TTS.
    """
    with open(work_txt, encoding="utf-8") as f:
        body = f.read()

    if re.search(r"(?m)^#", body):
        return

    lines = body.splitlines()
    non_empty = [(i, l.strip()) for i, l in enumerate(lines) if l.strip()]

    if not non_empty:
        heading_text = "Document"
        clean_body = body
    else:
        heading_text = non_empty[0][1]
        title_norm = _normalize_for_match(heading_text)
        body_norm = _normalize_for_match(body)
        escaped = re.escape(title_norm)
        clean_body = re.sub(
            rf"(?m)^[ \t]*{escaped}[ \t]*\r?\n(\r?\n)*",
            "",
            body_norm,
            count=1,
        ).lstrip("\n")

    # Real chapter title only on the # line; Title metadata is generic so it is never echoed as speech.
    prepended = (
        f"Title: Unknown\n"
        f"Author: Unknown\n"
        f"# {heading_text}\n\n"
        f"{clean_body}"
    )
    with open(work_txt, "w", encoding="utf-8") as f:
        f.write(prepended)

    with open(work_txt, encoding="utf-8") as f:
        written = f.read()
    body_section = written.split("\n\n", 1)[-1]
    first_body_line = next(
        (l.strip() for l in body_section.splitlines() if l.strip()), ""
    )
    if _normalize_for_match(first_body_line) == _normalize_for_match(heading_text):
        logging.warning(
            "epub2tts: title line removal fallback triggered for: %s", heading_text
        )
        hn = _normalize_for_match(heading_text)
        clean_body = re.sub(
            rf"(?m)^[ \t]*{re.escape(hn)}[ \t]*\r?\n",
            "",
            _normalize_for_match(clean_body),
            count=1,
        ).lstrip("\n")
        prepended = (
            f"Title: Unknown\n"
            f"Author: Unknown\n"
            f"# {heading_text}\n\n"
            f"{clean_body}"
        )
        with open(work_txt, "w", encoding="utf-8") as f:
            f.write(prepended)


#: v0.7.1: every conversion gets its own private folder (``tempfile.mkdtemp``) and hands it to the engine as
#: ``workdir``; nothing here changes the process-wide current folder. Until v0.7.1 this function ``os.chdir``'d into
#: that folder (the engine wrote bare relative scratch names) and a process-wide lock had to serialize every direct
#: Edge conversion, so several directly added files never truly converted at once.


def run_conversion_job(
    sourcefile: str,
    *,
    output_dir: str | None = None,
    speaker: str = DEFAULT_SPEAKER,
    audio_format: str = "m4b",
    mp3_bitrate: str = "192k",
    cover: str | None = None,
    paragraphpause: int = DEFAULT_PARAGRAPH_PAUSE_MS,
    sentencepause: int = DEFAULT_SENTENCE_PAUSE_MS,
    title_trailing_pause: int = DEFAULT_TITLE_PAUSE_MS,
    chapter_trailing_pause: int = DEFAULT_CHAPTER_PAUSE_MS,
    end_of_book_pause: int = DEFAULT_END_OF_BOOK_PAUSE_MS,
    trim_tts_padding: bool = True,
    trim_silence_db: float = DEFAULT_TRIM_SILENCE_DB,
    overwrite: bool = False,
    cancel_check=None,
    progress_callback=None,
    speech_prep=None,
) -> str:
    """
    Convert PDF or TXT to M4B or MP3.
    Returns the path to the final audio file.

    ``speech_prep`` is the run's frozen speech-preparation snapshot (Plan 01B A3), handed to ``get_book``; None means off.

    ``progress_callback(done, total)`` reports paragraph-level progress from
    ``read_book`` on the calling (worker) thread — GUI callers must enqueue
    from it, never touch Tk widgets directly.

    The result reaches ``output_dir`` only through :mod:`tts.publication`: complete, all at once, and (unless
    ``overwrite``) never over a file that is already there, however late that file appeared. :class:`FileExistsError`
    otherwise, with that file untouched.
    """
    _ensure_shared_on_path()
    from tts import ffmpeg_watch, worker_limits

    try:
        with ffmpeg_watch.controlled(cancel_check):
            return _convert(
                sourcefile, output_dir=output_dir, speaker=speaker, audio_format=audio_format, mp3_bitrate=mp3_bitrate,
                cover=cover, paragraphpause=paragraphpause, sentencepause=sentencepause,
                title_trailing_pause=title_trailing_pause, chapter_trailing_pause=chapter_trailing_pause,
                end_of_book_pause=end_of_book_pause, trim_tts_padding=trim_tts_padding, trim_silence_db=trim_silence_db,
                overwrite=overwrite, cancel_check=cancel_check, progress_callback=progress_callback, speech_prep=speech_prep)
    except Exception as exc:  # noqa: BLE001 - only an allocation failure is changed, into one that says what happened
        if not worker_limits.is_memory_failure(exc):
            raise
        detail = f"{type(exc).__name__}: {exc}"[:200]
    raise worker_limits.AssemblyMemoryError(worker_limits.out_of_memory_text(detail))


def _convert(sourcefile, *, output_dir, speaker, audio_format, mp3_bitrate, cover, paragraphpause, sentencepause,
             title_trailing_pause, chapter_trailing_pause, end_of_book_pause, trim_tts_padding, trim_silence_db, overwrite,
             cancel_check, progress_callback, speech_prep) -> str:
    from tts import publication, worker_limits

    sourcefile = os.path.abspath(sourcefile)
    if not os.path.isfile(sourcefile):
        raise FileNotFoundError(sourcefile)

    stem = Path(sourcefile).stem
    suffix = Path(sourcefile).suffix.lower()
    if suffix not in (".pdf", ".txt"):
        raise ValueError(f"Unsupported input type: {suffix}")

    # A conversion cancelled before it started (queued behind other files) does no work at all.
    if cancel_check is not None and cancel_check():
        from shared.cancellation import ConversionCancelled

        raise ConversionCancelled("Conversion cancelled by user.")
    # Read once, never changed: the default destination when no output_dir is given.
    caller_dir = Path.cwd()
    tmp = tempfile.mkdtemp(prefix="epub2tts_")
    try:
        work_txt = os.path.join(tmp, f"{stem}.txt")

        if suffix == ".pdf":
            from tts.pdf_extractor import pdf_to_txt

            pdf_to_txt(sourcefile, work_txt)
            _ensure_pdf_txt_has_chapter_heading(work_txt)
        else:
            shutil.copy2(sourcefile, work_txt)

        # Off (None): exactly the call this route always made.
        book_contents, book_title, book_author, chapter_titles = (
            get_book(work_txt) if speech_prep is None else get_book(work_txt, speech_prep))
        # Nothing speakable (empty, header-only, heading-only or punctuation-only)
        # used to publish a silent MP3 as a success. Fail the item instead, with
        # the local engines' own message, as the folder path already did
        # (v0.6.6 Phase 10).
        if not book_contents:
            raise ValueError("No text content found after parsing source file.")
        files = read_book(
            book_contents,
            speaker,
            paragraphpause,
            sentencepause,
            title_trailing_pause=title_trailing_pause,
            chapter_trailing_pause=chapter_trailing_pause,
            end_of_book_pause=end_of_book_pause,
            trim_tts_padding=trim_tts_padding,
            trim_silence_db=trim_silence_db,
            cancel_check=cancel_check,
            progress_callback=progress_callback,
            workdir=tmp,
        )

        cover_local = None
        if cover and os.path.isfile(cover):
            cbase = os.path.basename(cover)
            cover_local = os.path.join(tmp, cbase)
            shutil.copy2(cover, cover_local)

        if audio_format == "m4b":
            generate_metadata(files, book_author, book_title, chapter_titles, workdir=tmp)
            artifact = make_m4b(files, work_txt, speaker, workdir=tmp)
            if cover_local:
                add_cover(cover_local, artifact)
        elif audio_format == "mp3":
            # The whole narration is about to be assembled: in memory if it fits, after a wait if other files need that
            # memory first, and on disk if it does not or if memory runs out on the way. It is finished work by now, so a Cancel
            # sends it to disk, not away, and the deadlines after Cancel are ffmpeg_watch's.
            artifact = worker_limits.assemble(
                worker_limits.decoded_size(files),
                lambda: make_mp3(files, work_txt, speaker, bitrate=mp3_bitrate),
                lambda: make_mp3_on_disk(files, work_txt, speaker, bitrate=mp3_bitrate),
                finishing_check=cancel_check, note=print)
        else:
            raise ValueError(f"Unknown audio_format: {audio_format}")

        # Created before it is resolved: on Windows, resolving a folder that does not exist yet while another
        # conversion creates its parent can come back as a "\\?\" path; an existing folder resolves one way.
        dest_dir = Path(output_dir) if output_dir else caller_dir
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_dir = dest_dir.resolve()
        dest = dest_dir / os.path.basename(artifact)
        publication.publish_file(artifact, dest, overwrite=overwrite)
        print(f"Saved: {dest}")
        return str(dest)
    except BaseException as exc:
        # A failed pydub export is still holding its output open in a frame of this traceback, and Windows will not delete an open
        # file: without this the whole folder below stays. Those frames have finished, so their locals can go now.
        traceback.clear_frames(exc.__traceback__)
        raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
