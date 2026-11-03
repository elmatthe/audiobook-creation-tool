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


def pdf_page_count(pdf_path: str):
    """The PDF's page count, or ``None`` when it cannot be opened (used to size a run's workers, v0.7.1)."""
    with _PYMUPDF_LOCK:
        try:
            doc = fitz.open(pdf_path)
        except Exception:  # noqa: BLE001 - any unreadable file simply has no page count
            return None
        try:
            return doc.page_count
        finally:
            doc.close()


def pdf_to_txt(pdf_path: str, output_txt_path: str) -> str:
    text = extract_text_from_pdf(pdf_path)
    with open(output_txt_path, "w", encoding="utf-8") as f:
        f.write(text)
    return output_txt_path
