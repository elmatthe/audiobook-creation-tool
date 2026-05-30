"""Run conversion in an isolated temp working directory; optionally place output in output_dir."""

from __future__ import annotations

import logging
import os
import re
import unicodedata
import shutil
import tempfile
from pathlib import Path

from ebooklib import epub as epub_mod

from .epub2tts_edge import (
    DEFAULT_CHAPTER_PAUSE_MS,
    DEFAULT_END_OF_BOOK_PAUSE_MS,
    DEFAULT_PARAGRAPH_PAUSE_MS,
    DEFAULT_SENTENCE_PAUSE_MS,
    DEFAULT_SPEAKER,
    DEFAULT_TITLE_PAUSE_MS,
    DEFAULT_TRIM_SILENCE_DB,
    add_cover,
    export,
    generate_metadata,
    get_book,
    make_m4b,
    make_mp3,
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
    epub_convert: bool = False,
    cancel_check=None,
) -> str:
    """
    Convert EPUB (with epub_convert), PDF, or TXT to M4B or MP3.
    Returns the path to the final audio file.
    """
    sourcefile = os.path.abspath(sourcefile)
    if not os.path.isfile(sourcefile):
        raise FileNotFoundError(sourcefile)

    stem = Path(sourcefile).stem
    suffix = Path(sourcefile).suffix.lower()
    if suffix not in (".epub", ".pdf", ".txt"):
        raise ValueError(f"Unsupported input type: {suffix}")

    if suffix == ".epub" and not epub_convert:
        raise ValueError("EPUB input requires epub_convert=True for audio output")

    tmp = tempfile.mkdtemp(prefix="epub2tts_")
    old_cwd = os.getcwd()
    try:
        os.chdir(tmp)
        work_txt = os.path.join(tmp, f"{stem}.txt")

        if suffix == ".epub":
            epub_name = os.path.basename(sourcefile)
            local_epub = os.path.join(tmp, epub_name)
            shutil.copy2(sourcefile, local_epub)
            book = epub_mod.read_epub(local_epub)
            export(book, local_epub, overwrite=True)
            work_txt = local_epub.replace(".epub", ".txt")
        elif suffix == ".pdf":
            from tts.pdf_extractor import pdf_to_txt

            pdf_to_txt(sourcefile, work_txt)
            _ensure_pdf_txt_has_chapter_heading(work_txt)
        else:
            shutil.copy2(sourcefile, work_txt)

        book_contents, book_title, book_author, chapter_titles = get_book(work_txt)
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
        )

        cover_local = None
        if cover and os.path.isfile(cover):
            cbase = os.path.basename(cover)
            cover_local = os.path.join(tmp, cbase)
            shutil.copy2(cover, cover_local)

        if audio_format == "m4b":
            generate_metadata(files, book_author, book_title, chapter_titles)
            artifact = make_m4b(files, work_txt, speaker)
            if cover_local:
                add_cover(cover_local, artifact)
        elif audio_format == "mp3":
            artifact = make_mp3(files, work_txt, speaker, bitrate=mp3_bitrate)
        else:
            raise ValueError(f"Unknown audio_format: {audio_format}")

        dest_dir = Path(output_dir).resolve() if output_dir else Path(old_cwd)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / os.path.basename(artifact)
        if dest.exists():
            if overwrite:
                dest.unlink()
            else:
                raise FileExistsError(str(dest))
        shutil.move(artifact, str(dest))
        print(f"Saved: {dest}")
        return str(dest)
    finally:
        os.chdir(old_cwd)
        shutil.rmtree(tmp, ignore_errors=True)
