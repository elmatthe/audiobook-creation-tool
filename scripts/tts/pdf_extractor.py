"""Extract plain text from PDF files using PyMuPDF."""

import re
import threading

import fitz

# Line that is only digits (page numbers)
_DIGITS_ONLY_LINE = re.compile(r"(?m)^\s*\d+\s*$")
# Tiny all-caps tokens (running heads like "CH", "IV") — avoid broad 1–4 char removal (hits "No.")
_SHORT_CAPS_TOKEN = re.compile(r"(?m)^\s*[A-Z]{1,4}\s*$")
# "Chapter 52: Minefield" is NOT str.istitle() in Python (colon/digits); still must stay a standalone heading.
_CHAPTERISH_HEAD = re.compile(
    r"^(chapter|prologue|epilogue|part|book|section)\s+\d+",
    re.IGNORECASE,
)


def _looks_like_heading_line(stripped: str) -> bool:
    """True if this line should not be soft-merged with the following line (titles, chapter heads)."""
    if not stripped or len(stripped) >= 80:
        return False
    if re.search(r"[.!?]$", stripped):
        return False
    if stripped.istitle() or stripped.isupper():
        return True
    return bool(_CHAPTERISH_HEAD.match(stripped))


def _dehyphenate(text: str) -> str:
    """Merge words broken across lines with a hyphen (impor-\\ntant → important)."""
    text = re.sub(r"-\s*\r?\n\s*(\S)", r"\1", text)
    return text


def _rejoin_soft_wrapped_lines(text: str) -> str:
    """
    Join lines that are mid-sentence; keep paragraph breaks after real sentence endings.
    """
    lines = text.split("\n")
    rejoined: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            rejoined.append("")
            continue
        if rejoined and rejoined[-1] != "":
            prev = rejoined[-1]
            if _looks_like_heading_line(prev):
                rejoined.append(stripped)
                continue
            prev_ends_sentence = bool(re.search(r'[.!?:)"\'—]\s*$', prev))
            looks_like_heading = _looks_like_heading_line(stripped)
            if prev_ends_sentence or looks_like_heading:
                rejoined.append(stripped)
            else:
                rejoined[-1] = prev + " " + stripped
        else:
            rejoined.append(stripped)
    return "\n".join(rejoined)


def _strip_noise_lines(text: str) -> str:
    """Remove digit-only lines and tiny all-caps noise lines."""
    text = _DIGITS_ONLY_LINE.sub("", text)
    text = _SHORT_CAPS_TOKEN.sub("", text)
    return text


def _merge_blocks_across_page_gaps(text: str) -> str:
    """
    Join \\n\\n-separated blocks when the first block does not end a sentence
    and the next block does not look like a heading (fixes page-boundary splits).
    """
    blocks = [b.strip() for b in re.split(r"\n\s*\n+", text) if b.strip()]
    if len(blocks) < 2:
        return text
    out: list[str] = []
    for b in blocks:
        if not out:
            out.append(b)
            continue
        prev = out[-1]
        if _looks_like_heading_line(prev):
            out.append(b)
            continue
        prev_ends = bool(re.search(r'[.!?:)"\'—]\s*$', prev))
        looks_heading = _looks_like_heading_line(b)
        if prev_ends or looks_heading:
            out.append(b)
        else:
            out[-1] = prev + " " + b
    return "\n\n".join(out)


def _clean_page_text(text: str) -> str:
    text = _dehyphenate(text)
    text = _rejoin_soft_wrapped_lines(text)
    text = _strip_noise_lines(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


#: PyMuPDF "does not support running on multiple threads - doing so may cause incorrect behaviour or even crash
#: Python itself" (its own documentation). Several files can convert at once (folder workers, and since v0.7.1
#: directly added files too), so every PyMuPDF call in this process goes through this one lock. Reading the text is
#: fast next to narrating it (about 0.2 s for a 230-page volume), so this serializes extraction only.
_PYMUPDF_LOCK = threading.Lock()


def extract_text_from_pdf(pdf_path: str) -> str:
    parts: list[str] = []
    with _PYMUPDF_LOCK:
        doc = fitz.open(pdf_path)
        try:
            for page in doc:
                raw = page.get_text("text") or ""
                if not raw.strip():
                    continue
                cleaned = _clean_page_text(raw)
                if cleaned:
                    parts.append(cleaned)
        finally:
            doc.close()

    if not parts:
        raise ValueError("No readable text found in PDF. File may be scanned/image-based.")

    full = "\n\n".join(parts)
    full = full.replace("\x0c", "\n")
    full = _merge_blocks_across_page_gaps(full)
    full = re.sub(r"\n{3,}", "\n\n", full)
    full = _strip_noise_lines(full)
    full = re.sub(r"\n{3,}", "\n\n", full)
    return full.strip()


#: Above this many characters a page is not given the conversion's line cleaning when sizing: that cost grows with the
#: square of the page's lines (tens of seconds on one abnormal page), and a dense but ordinary page is well below it.
SIZING_CLEAN_CHARS = 16_000
_SINGLE_LINE_BREAK = re.compile(r"(?<!\n)\n(?!\n)")


def pdf_text_sample(pdf_path: str, max_pages: int, keep_reading=None):
    """``(page count, pages read, text)`` for sizing a run's workers, or ``None`` when the PDF cannot be opened.

    Every page of a PDF up to ``max_pages`` long, and otherwise ``max_pages`` pages spread evenly through it, stopping
    early when ``keep_reading()`` says so; it is asked before each page, so the time spent here has a bound: the limit
    given, plus one page. Each ordinary page gets the same cleaning a conversion gives it; the joins across pages that
    ``extract_text_from_pdf`` makes afterwards only remove paragraph breaks, so this never under-counts them.
    """
    with _PYMUPDF_LOCK:
        try:
            doc = fitz.open(pdf_path)
        except Exception:  # noqa: BLE001 - an unreadable file simply has no size to offer
            return None
        try:
            pages = doc.page_count
            wanted = min(pages, max(1, int(max_pages)))
            read = 0
            parts: list[str] = []
            for index in range(wanted):
                if keep_reading is not None and not keep_reading():
                    break
                raw = doc[index * pages // wanted].get_text("text") or ""
                read += 1
                if raw.strip():
                    parts.append(_clean_page_text(raw) if len(raw) <= SIZING_CLEAN_CHARS
                                 else _SINGLE_LINE_BREAK.sub(" ", raw))
            return pages, read, "\n\n".join(parts)
        except Exception:  # noqa: BLE001 - a damaged page table: the conversion will say so properly
            return None
        finally:
            doc.close()


def pdf_to_txt(pdf_path: str, output_txt_path: str) -> str:
    text = extract_text_from_pdf(pdf_path)
    with open(output_txt_path, "w", encoding="utf-8") as f:
        f.write(text)
    return output_txt_path
