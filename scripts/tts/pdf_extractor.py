"""Extract plain text from PDF files using PyMuPDF.

**What is taken out, and on what evidence** (v0.7.2 Phase 9, review finding P9-01). A page's text is narrated; only its
furniture is not: the printed page number and a short running head. Until this phase a line was taken for furniture by
its shape alone, wherever it stood: any line of digits, any line of one to four capitals, and the first or last line of a
page when it was a number. That deleted text: the year a sentence ended a page with, an acronym or an emphasised "NOT"
that wrapped onto a line of its own. Shape is no longer enough. A line is furniture only when all of this holds:

* *where it is*: it stands on the top or bottom line of its page, clear of the page's other text by more than a line and
  a half of that text's own spacing (or it is the only line on the page), and it is set no larger than that text;
* *what repeats*: for a page number, another page carries one too and the two differ by exactly the distance between
  the pages; for a short running head, the same word stands at the same height on another page.

Anything that fails either test is text and is kept, a number or capitals included. The rule can still be wrong in one
direction only by design: page furniture that is on one page alone, or that the PDF does not place where it looks, is
read out. ``files/tests/test_pdf_text_cleaning.py`` states each such case by name.
"""

import re
import statistics
import threading
from collections import defaultdict
from typing import NamedTuple

import fitz

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


_HYPHEN_AT_A_LINE_END = re.compile(r"(?<=(\S))-[ \t]*\r?\n\s*(\S)")


def _mend(before: str, after: str) -> str | None:
    """What stands between *before* and *after* when a hyphen ended the line (or the page) between them: nothing for a
    word broken there, the hyphen itself when it is the text's own, ``None`` when the hyphen is no word's at all.

    A broken word carries on in a small letter ("impor-" / "tant"). A hyphen followed by a capital or with a digit on
    either side was written by the author: a compound with a name ("Anglo-" / "Saxon"), a range ("1939-" / "1945"). Until
    v0.7.2 Phase 9 every line-end hyphen was dropped, so that range was read as the one number 19391945.
    """
    if before.isalpha() and after.isalpha() and not after.isupper():
        return ""
    if before.isalnum() and after.isalnum():
        return "-"
    return None


def _dehyphenate(text: str) -> str:
    """Merge words broken across lines with a hyphen (impor-\\ntant → important); keep a hyphen that is the text's own."""
    def join(match: re.Match) -> str:
        between = _mend(match.group(1), match.group(2))
        return match.group(0) if between is None else between + match.group(2)

    return _HYPHEN_AT_A_LINE_END.sub(join, text)


def _rejoin_soft_wrapped_lines(text: str) -> str:
    """
    Join lines that are mid-sentence; keep paragraph breaks after real sentence endings.

    A line that looks like a heading (capitals, title case) is kept on its own, unless the sentence visibly runs through
    it: the line before it is unfinished and the line after it carries on in a small letter. Then it is a word of that
    sentence which the page's layout put on a line of its own ("The signal is" / "NOT" / "a command to open it."), and
    it is joined like any other (v0.7.2 Phase 9).
    """
    lines = [line.strip() for line in text.split("\n")]
    rejoined: list[str] = []
    for index, stripped in enumerate(lines):
        if not stripped:
            rejoined.append("")
            continue
        if rejoined and rejoined[-1] != "":
            prev = rejoined[-1]
            if _looks_like_heading_line(prev):
                rejoined.append(stripped)
                continue
            prev_ends_sentence = bool(re.search(r'[.!?:)"\'—]\s*$', prev))
            runs_on = index + 1 < len(lines) and lines[index + 1][:1].islower()
            looks_like_heading = _looks_like_heading_line(stripped) and not runs_on
            if prev_ends_sentence or looks_like_heading:
                rejoined.append(stripped)
            else:
                rejoined[-1] = prev + " " + stripped
        else:
            rejoined.append(stripped)
    return "\n".join(rejoined)


#: A block ending in one of these has finished; the next block does not continue it.
_ENDS_A_BLOCK = frozenset('.!?:)"\'—')


def _merge_blocks_across_page_gaps(text: str) -> str:
    """
    Join \\n\\n-separated blocks when the first block does not end a sentence
    and the next block does not look like a heading (fixes page-boundary splits).
    """
    blocks = [b.strip() for b in re.split(r"\n\s*\n+", text) if b.strip()]
    if len(blocks) < 2:
        return text
    # Each entry is the pieces of one joined block, and only ever its last piece is looked at for how it ends (blocks are
    # stripped): joining as it goes costs the square of the block's length, and prose that continues across every page of
    # a book is one block. Worker sizing reads this too (``pdf_text_sample``), so it has to stay linear.
    out: list[list[str]] = []
    joined_length = 0
    for b in blocks:
        if not out:
            out.append([b])
            joined_length = len(b)
            continue
        # ``_looks_like_heading_line`` is False from 80 characters up: only a short block needs joining to be asked.
        if joined_length < 80 and _looks_like_heading_line(" ".join(out[-1])):
            out.append([b])
            joined_length = len(b)
            continue
        if out[-1][-1][-1] in _ENDS_A_BLOCK or _looks_like_heading_line(b):
            out.append([b])
            joined_length = len(b)
        else:
            out[-1].append(b)
            joined_length += 1 + len(b)
    return "\n\n".join(" ".join(pieces) for pieces in out)


# --------------------------------------------------------------------------- #
# Page furniture: found by where a line stands and by what repeats, never by its shape alone
# --------------------------------------------------------------------------- #

#: A printed page number: digits and nothing else. Six are more than any book has pages.
_PAGE_NUMBER = re.compile(r"\d{1,6}")
#: A short running head: a chapter numeral or an abbreviation ("IV", "CH").
_SHORT_HEAD = re.compile(r"[A-Z]{1,4}")
#: Two lines whose baselines are this close (points) stand on one line of the page.
_SAME_LINE = 2.0
#: Furniture stands clear of the page's text by more than this many of that text's own line spacings.
_CLEAR_BY = 1.5
#: ...and is set no larger than that text, within this many points: a larger line is a title.
_SIZE_SLACK = 0.5


class _EdgeLine(NamedTuple):
    """A line that stands alone at the top or the bottom of its page: where page furniture is printed, and so the only
    kind of line that can be taken for it. Whether it is furniture is decided across pages (:func:`_furniture`)."""

    page: int       # the page's index in the document
    line: int       # the line's index among the lines of the page's text
    text: str
    at: float       # its baseline, in points from the top of the page


def _edge_lines(page_index: int, raw: str, layout: dict | None) -> list[_EdgeLine]:
    """The lines of one page that stand clear at its top or bottom edge, from the page's own geometry.

    *layout* is PyMuPDF's ``dict`` of the same text page *raw* came from. Its lines must be *raw*'s lines, one for one:
    if they are not (or there is no layout), nothing on this page is called an edge line and all of its text is kept.
    """
    if not layout:
        return []
    rows = []  # one per line of the raw text, in its order: (text, baseline, box top, box bottom, size, level)
    for block in layout.get("blocks") or ():
        if block.get("type") != 0:
            continue
        for line in block.get("lines") or ():
            spans = line.get("spans") or ()
            text = "".join(span.get("text") or "" for span in spans)
            if not text:
                continue  # the plain text holds nothing for a line with no characters
            box = line.get("bbox") or (0.0, 0.0, 0.0, 0.0)
            origin = spans[0].get("origin")
            direction = line.get("dir") or (1.0, 0.0)
            rows.append((text, float(origin[1]) if origin else float(box[3]), float(box[1]), float(box[3]),
                         max(float(span.get("size") or 0.0) for span in spans),
                         direction[0] > 0.99 and abs(direction[1]) < 0.01))
    if any("\n" in row[0] for row in rows) or "".join(row[0] + "\n" for row in rows) != raw:
        return []
    written = [(number, row[0].strip(), *row[1:5]) for number, row in enumerate(rows) if row[0].strip() and row[5]]
    if not written:
        return []
    highest, lowest = min(row[2] for row in written), max(row[2] for row in written)

    def on(level: float, row) -> bool:
        return abs(row[2] - level) <= _SAME_LINE

    inner = [row for row in written if not on(highest, row) and not on(lowest, row)]
    found: dict[int, _EdgeLine] = {}
    for level in (highest, lowest):
        others = [row for row in written if not on(level, row)]
        if others:
            nearest = min(others, key=lambda row: abs(row[2] - level))
            baselines = sorted(row[2] for row in inner)
            steps = [b - a for a, b in zip(baselines, baselines[1:]) if b - a > _SAME_LINE]
            spacing = statistics.median(steps) if steps else nearest[4] - nearest[3]
            if abs(nearest[2] - level) <= _CLEAR_BY * spacing:
                continue  # in the run of the page's text: a line of it, whatever it says
            text_size = statistics.median(row[5] for row in (inner or [nearest]))
        else:
            text_size = None  # nothing else on the page: a leaf that holds only its number, or only one line
        for row in written:
            if on(level, row) and (text_size is None or row[5] <= text_size + _SIZE_SLACK):
                found[row[0]] = _EdgeLine(page_index, row[0], row[1], row[2])
    return list(found.values())


def _furniture(edge_lines: list[_EdgeLine]) -> dict[int, set[int]]:
    """Which edge lines are page furniture, as ``{page: {line, ...}}``. Standing at the edge is necessary, never enough.

    * A page number: digits, and another page has an edge line of digits that differs from it by exactly the distance
      between the two pages. A book's pages count up together; two bare numbers of the text do not.
    * A short running head: one to four capitals, and the same word stands at the same height on another page. A
      chapter numeral printed once above its chapter is a heading, and is kept.
    """
    drop: dict[int, set[int]] = defaultdict(set)
    counted: dict[int, list[_EdgeLine]] = defaultdict(list)
    heads: dict[str, list[_EdgeLine]] = defaultdict(list)
    for line in edge_lines:
        if _PAGE_NUMBER.fullmatch(line.text):
            counted[int(line.text) - line.page].append(line)
        elif _SHORT_HEAD.fullmatch(line.text):
            heads[line.text].append(line)
    for run in counted.values():
        if len({line.page for line in run}) > 1:
            for line in run:
                drop[line.page].add(line.line)
    for same_word in heads.values():
        same_word.sort(key=lambda line: line.at)
        level: list[_EdgeLine] = []
        for line in [*same_word, None]:
            if line is not None and (not level or line.at - level[-1].at <= _SAME_LINE):
                level.append(line)
                continue
            if len({member.page for member in level}) > 1:
                for member in level:
                    drop[member.page].add(member.line)
            level = [] if line is None else [line]
    return drop


def _join_words_split_across_pages(parts: list[str]) -> list[str]:
    """A page that ends in a hyphen continues its last word on the next page: the same rule :func:`_dehyphenate`
    applies between two lines, applied between two pages (v0.7.2 Phase 8, ACT72-063). Each part is one cleaned page."""
    joined: list[str] = []
    for part in parts:
        if joined and len(joined[-1]) > 1 and joined[-1].endswith("-") and part[:1].strip():
            between = _mend(joined[-1][-2], part[0])
            if between is not None:
                joined[-1] = joined[-1][:-1] + between + part
                continue
        joined.append(part)
    return joined


def _clean_page_text(text: str, furniture=()) -> str:
    """One page's text as it is narrated. *furniture* holds the indices of the lines :func:`_furniture` found to be the
    page's number or running head; they are taken out whole, before the lines are joined, so the sentence a page number
    was printed under reads straight on (v0.7.2 Phase 8, ACT72-063). Nothing else is removed."""
    if furniture:
        text = "\n".join(line for index, line in enumerate(text.split("\n")) if index not in furniture)
    text = _dehyphenate(text)
    text = _rejoin_soft_wrapped_lines(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


#: PyMuPDF "does not support running on multiple threads - doing so may cause incorrect behaviour or even crash
#: Python itself" (its own documentation). Several files can convert at once (folder workers, and since v0.7.1
#: directly added files too), so every PyMuPDF call in this process goes through this one lock. Reading the text is
#: fast next to narrating it (about 0.2 s for a 230-page volume), so this serializes extraction only.
_PYMUPDF_LOCK = threading.Lock()


def _read_page(page, index: int, *, layout_up_to: int | None = None) -> tuple[str, list[_EdgeLine]]:
    """A page's text, exactly as ``get_text("text")`` gives it, and its edge lines. Call with :data:`_PYMUPDF_LOCK` held.

    Both come from one text page, so the geometry describes the very lines of the text. A page longer than
    *layout_up_to* characters is not measured (sizing does not clean such a page either); it then has no edge lines.
    """
    textpage = page.get_textpage(flags=fitz.TEXTFLAGS_TEXT)
    raw = page.get_text("text", textpage=textpage) or ""
    if not raw.strip() or (layout_up_to is not None and len(raw) > layout_up_to):
        return raw, []
    return raw, _edge_lines(index, raw, page.get_text("dict", textpage=textpage))


def extract_text_from_pdf(pdf_path: str) -> str:
    read: list[tuple[int, str]] = []
    edge_lines: list[_EdgeLine] = []
    with _PYMUPDF_LOCK:
        doc = fitz.open(pdf_path)
        try:
            for index, page in enumerate(doc):
                raw, edges = _read_page(page, index)
                if raw.strip():
                    read.append((index, raw))
                    edge_lines += edges
        finally:
            doc.close()

    furniture = _furniture(edge_lines)
    parts = [cleaned for index, raw in read if (cleaned := _clean_page_text(raw, furniture.get(index, ())))]
    if not parts:
        raise ValueError("No readable text found in PDF. File may be scanned/image-based.")

    return _join_pages(parts)


def _join_pages(parts: list[str]) -> str:
    """Cleaned pages as the one text a conversion speaks. Sizing reads pages through this too, so the two cannot disagree
    about where a paragraph ends: prose that continues across a page is one paragraph, in memory as one."""
    full = "\n\n".join(_join_words_split_across_pages(parts))
    full = full.replace("\x0c", "\n")
    full = _merge_blocks_across_page_gaps(full)
    full = re.sub(r"\n{3,}", "\n\n", full)
    return full.strip()


#: Above this many characters a page is not given the conversion's line cleaning when sizing: that cost grows with the
#: square of the page's lines (tens of seconds on one abnormal page), and a dense but ordinary page is well below it.
SIZING_CLEAN_CHARS = 16_000
_SINGLE_LINE_BREAK = re.compile(r"(?<!\n)\n(?!\n)")


def pdf_text_sample(pdf_path: str, max_pages: int, keep_reading=None):
    """``(page count, pages read, text)`` for sizing a run's workers, or ``None`` when the PDF cannot be opened.

    Every page of a PDF up to ``max_pages`` long, and otherwise ``max_pages`` pages spread evenly through it, stopping
    early when ``keep_reading()`` says so; it is asked before each page, so reading has a bound: the limit given, plus
    one page. Each ordinary page gets the same cleaning a conversion gives it, page furniture included (found among the
    pages read, by the same rule and from each page's real position in the document), and the pages are joined the way a
    conversion joins them (:func:`_join_pages`), so a paragraph that continues across pages is sized as the one paragraph
    it will be. When only some pages were read, a join between two of them stands for the pages between: the caller scales
    the result up.
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
            taken: list[tuple[int, str]] = []
            edge_lines: list[_EdgeLine] = []
            for index in range(wanted):
                if keep_reading is not None and not keep_reading():
                    break
                number = index * pages // wanted
                raw, edges = _read_page(doc[number], number, layout_up_to=SIZING_CLEAN_CHARS)
                read += 1
                if raw.strip():
                    taken.append((number, raw))
                    edge_lines += edges
            furniture = _furniture(edge_lines)
            parts = [_clean_page_text(raw, furniture.get(number, ())) if len(raw) <= SIZING_CLEAN_CHARS
                     else _SINGLE_LINE_BREAK.sub(" ", raw) for number, raw in taken]
            return pages, read, _join_pages(parts)
        except Exception:  # noqa: BLE001 - a damaged page table: the conversion will say so properly
            return None
        finally:
            doc.close()


def pdf_to_txt(pdf_path: str, output_txt_path: str) -> str:
    text = extract_text_from_pdf(pdf_path)
    with open(output_txt_path, "w", encoding="utf-8") as f:
        f.write(text)
    return output_txt_path
