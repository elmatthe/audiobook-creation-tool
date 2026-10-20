"""Integrity proofs for speech preparation (Plan 01B section 4.4).

All offsets index the decoded or extracted source text (the TXT as read with ``utf-8-sig``, or what ``pdf_extractor``
produced); nothing here claims to reconstruct a PDF's layout. ``verify`` runs on every normalization: it proves the
spoken text rebuilds the source byte for byte and that the runtime invariants I2-I5, I7 and I8 hold. The engine-side
proofs (Chatterbox ``_assert_content_preserved``, Qwen3 ``verify_plan``) keep running on the spoken text unchanged.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import re
from typing import Iterable, Sequence

#: Spoken form of a rule or glossary edit: letters and apostrophes in words separated by single spaces (I5).
SPOKEN_FORM = re.compile(r"[A-Za-z']+(?: [A-Za-z']+)*")
#: Hygiene may delete a character, turn it into one space, or spell out a ligature.
HYGIENE_FORM = re.compile(r"(?:|[ ]|[A-Za-z]+)")
#: Kokoro's inline phoneme markup, produced only from a glossary entry when the engine profile allows it.
PHONEME_MARKUP = re.compile(r"\[[^\[\]\n]+\]\(/[^()/\[\]\n]+/\)")
_MARKER = re.compile(r"[^\S\n]*(?:Title:|Author:|#+)")


class IntegrityError(RuntimeError):
    """The normalizer produced output that violates an invariant: a defect, never a property of the book."""


def content_hash(data: object) -> str:
    """SHA-256 of a canonical JSON encoding: equal content, equal hash, on every platform."""
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def apply_edits(source: str, edits: Sequence) -> str:
    """The spoken text: ``source`` with every (ordered, non-overlapping) edit substituted."""
    parts: list[str] = []
    cursor = 0
    for edit in edits:
        parts.append(source[cursor:edit.source_start])
        parts.append(edit.spoken)
        cursor = edit.source_end
    parts.append(source[cursor:])
    return "".join(parts)


def reconstruct_source(spoken: str, edits: Sequence) -> str:
    """Rebuild the decoded source from the spoken text and the edits alone (invariant I2)."""
    parts: list[str] = []
    source_cursor = spoken_cursor = 0
    for edit in edits:
        gap = edit.source_start - source_cursor
        parts.append(spoken[spoken_cursor:spoken_cursor + gap])
        spoken_cursor += gap
        if spoken[spoken_cursor:spoken_cursor + len(edit.spoken)] != edit.spoken:
            raise IntegrityError(f"spoken text does not contain edit {edit.rule_id} at {spoken_cursor}")
        parts.append(edit.original)
        spoken_cursor += len(edit.spoken)
        source_cursor = edit.source_end
    parts.append(spoken[spoken_cursor:])
    return "".join(parts)


def _marker(line: str) -> str:
    m = _MARKER.match(line)
    return m.group() if m else ""


def verify(source: str, spoken: str, edits: Sequence, protected: Iterable, *, phoneme_markup: bool = False) -> None:
    """Raise ``IntegrityError`` on the first violated invariant."""
    previous_end = 0
    for edit in edits:
        if not (previous_end <= edit.source_start < edit.source_end <= len(source)):
            raise IntegrityError(f"I3: edit {edit.rule_id} at {edit.source_start} is out of order, overlapping or outside")
        if source[edit.source_start:edit.source_end] != edit.original:
            raise IntegrityError(f"I3: edit {edit.rule_id} at {edit.source_start} does not record the source text")
        if "\n" in edit.original or "\n" in edit.spoken:
            raise IntegrityError(f"I8: edit {edit.rule_id} at {edit.source_start} crosses a line")
        if edit.cls == "HYG":
            valid = HYGIENE_FORM.fullmatch(edit.spoken)
        else:
            valid = SPOKEN_FORM.fullmatch(edit.spoken) or (
                phoneme_markup and edit.cls == "GLOSS" and PHONEME_MARKUP.fullmatch(edit.spoken))
        if not valid:
            raise IntegrityError(f"I5: edit {edit.rule_id} at {edit.source_start} has spoken form {edit.spoken!r}")
        previous_end = edit.source_end
    spans = sorted(protected, key=lambda s: s.start)
    starts = [s.start for s in spans]
    reach: list[int] = []  # furthest protected end among spans[:i + 1]
    for span in spans:
        reach.append(max(span.end, reach[-1] if reach else 0))
    for edit in edits:
        i = bisect.bisect_left(starts, edit.source_end) - 1
        if i >= 0 and reach[i] > edit.source_start:
            raise IntegrityError(f"I4: edit {edit.rule_id} at {edit.source_start} touches a protected span")
    if apply_edits(source, edits) != spoken:
        raise IntegrityError("I2: spoken text is not the source with its edits applied")
    if reconstruct_source(spoken, edits) != source:
        raise IntegrityError("I2: the source cannot be reconstructed from the spoken text")
    source_lines, spoken_lines = source.split("\n"), spoken.split("\n")
    if len(source_lines) != len(spoken_lines):
        raise IntegrityError("I8: line count changed")
    for number, (before, after) in enumerate(zip(source_lines, spoken_lines), start=1):
        if before.strip() and not after.strip():
            raise IntegrityError(f"I7: line {number} became empty")
        if _marker(before) != _marker(after):
            raise IntegrityError(f"I8: structural marker changed on line {number}")
