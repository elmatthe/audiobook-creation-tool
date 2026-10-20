"""Structure stage: decode a source text and turn its ``Title:``/``Author:``/``#`` markers into typed blocks.

Plan 01B checkpoint A1 -- a pure refactor. Kokoro, Chatterbox and Qwen3 each carried a private copy of the same loop;
this module is the one implementation, and ``StructureOptions`` selects the behaviour each engine has today, so nothing
a person hears changes. Later stages (hygiene, normalization) build on the ``SpeechDocument`` produced here and must not
alter the markers; the typed ``blocks`` keep what was a header, a heading or body, so a stage can leave structure alone.

Standard library only. It imports nothing from ``tts.*`` engines or ``shared.job_ui``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: Block kinds. ``metadata`` is a ``Title:``/``Author:`` line (never spoken by the local engines), ``heading`` a ``#`` line,
#: ``line`` an ordinary line (kept exactly, indentation included), ``blank`` a paragraph separator the structure stage added,
#: ``raw`` the whole untouched text when markers are not honoured.
METADATA, HEADING, LINE, BLANK, RAW = "metadata", "heading", "line", "blank", "raw"


@dataclass(frozen=True)
class StructureOptions:
    """How an engine reads structure today.

    ``honour_header_markers``: skip ``Title:``/``Author:`` lines and strip ``#`` markers. False hands the text over untouched.
    ``heading_as_paragraph``: a heading becomes a paragraph of its own (blank lines around it) and an empty heading
    disappears; otherwise the heading text stays in line, and an empty heading leaves an empty line.
    """

    heading_as_paragraph: bool = False
    honour_header_markers: bool = True


#: Kokoro and Chatterbox: markers handled, heading text left in line.
LOCAL_ENGINE_STRUCTURE = StructureOptions()
#: Qwen3: a heading is a paragraph of its own, so a title is never fused with the first sentence after it.
HEADING_PARAGRAPH_STRUCTURE = StructureOptions(heading_as_paragraph=True)
#: Edge folder mode: the whole text goes to the splitter unchanged (its ``Title:``/``#`` lines are spoken as written today).
RAW_STRUCTURE = StructureOptions(honour_header_markers=False)


@dataclass(frozen=True)
class Block:
    kind: str
    text: str


@dataclass(frozen=True)
class SpeechDocument:
    """The structured source: ``blocks`` in order, and ``text`` -- exactly what the engine receives."""

    blocks: tuple[Block, ...]
    text: str


def read_source_text(path) -> str:
    """Decode a source ``.txt``. ``utf-8-sig``: a leading BOM is a signature, not text (it would hide a ``Title:`` line)."""
    return Path(path).read_text(encoding="utf-8-sig")


def parse_structure(raw_text: str, options: StructureOptions = LOCAL_ENGINE_STRUCTURE) -> SpeechDocument:
    """Apply the structure rules to already-decoded text."""
    if not options.honour_header_markers:
        return SpeechDocument((Block(RAW, raw_text),), raw_text)

    blocks: list[Block] = []
    for line in raw_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Title:") or stripped.startswith("Author:"):
            blocks.append(Block(METADATA, stripped))
        elif stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            if options.heading_as_paragraph:
                if heading:
                    blocks.extend((Block(BLANK, ""), Block(HEADING, heading), Block(BLANK, "")))
            else:
                blocks.append(Block(HEADING, heading))
        else:
            blocks.append(Block(LINE, line))
    text = "\n".join(b.text for b in blocks if b.kind != METADATA).strip()
    return SpeechDocument(tuple(blocks), text)


def structure_segments(raw_text: str, options: StructureOptions = LOCAL_ENGINE_STRUCTURE) -> tuple[tuple[int, int, int], ...]:
    """Where each run of ``parse_structure(raw_text, options).text`` came from: ``(text_start, raw_start, length)``.

    The joining newlines and the blank lines a heading gains are not in any segment. Mirrors ``parse_structure`` line for
    line without changing it; a test proves every segment's text equals its raw slice and that the segments cover every
    non-whitespace character of the structured text.
    """
    if not options.honour_header_markers:
        return ((0, 0, len(raw_text)),) if raw_text else ()
    pieces: list[tuple[int | None, str]] = []
    position = 0
    for line_with_end in raw_text.splitlines(keepends=True):
        line = (line_with_end.splitlines() or [""])[0]
        stripped = line.strip()
        if stripped.startswith("Title:") or stripped.startswith("Author:"):
            pass
        elif stripped.startswith("#"):
            after_marks = stripped.lstrip("#")
            heading = after_marks.strip()
            offset = (len(line) - len(line.lstrip())) + (len(stripped) - len(after_marks)) \
                + (len(after_marks) - len(after_marks.lstrip()))
            if options.heading_as_paragraph:
                if heading:
                    pieces.extend(((None, ""), (position + offset, heading), (None, "")))
            else:
                pieces.append((position + offset, heading))
        else:
            pieces.append((position, line))
        position += len(line_with_end)
    joined = "\n".join(text for _, text in pieces)
    lead = len(joined) - len(joined.lstrip())
    total = len(joined.strip())
    segments: list[tuple[int, int, int]] = []
    cursor = 0
    for raw_start, text in pieces:
        if raw_start is not None and text:
            start, end = max(cursor, lead), min(cursor + len(text), lead + total)
            if end > start:
                segments.append((start - lead, raw_start + (start - cursor), end - start))
        cursor += len(text) + 1
    return tuple(segments)


def load_speech_text(path, options: StructureOptions = LOCAL_ENGINE_STRUCTURE) -> SpeechDocument:
    """Decode ``path`` and structure it for one engine."""
    return parse_structure(read_source_text(path), options)
