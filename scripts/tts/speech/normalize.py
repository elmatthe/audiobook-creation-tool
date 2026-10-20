"""The normalization stage: protected spans, then the glossary, then the class rules, in one non-recursive pass.

``normalize(source)`` returns a ``NormalizedText``: the spoken text, the ordered edits that produced it, the edits a mode
withheld, the tokens left unchanged as ambiguous, the protected spans, and offset maps in both directions. The output is
verified (``integrity.verify``) before it is returned.

Resolution (Plan 01B 4.3): every rule scans the original text once. Levels are resolved in order; within a level the
longest candidate wins, then the earlier rule, then the earlier position. A resolved candidate *claims* its span, so no
later rule can rewrite part of it -- including an ambiguous token or an edit whose class is not set to ``expand``, which
is therefore left exactly as written for the engine to read natively.

Modes, per class (the per-engine table lives in the engine profiles):
* ``expand``        -- the class's rule edits are applied;
* ``glossary_only`` -- rule edits are withheld; an owner glossary entry may still change such a token;
* ``native``        -- the engine reads the token itself; neither rule edits nor glossary entries change it.
A glossary entry on ordinary words (no class claims them) applies whenever its engine scope matches.

Standard library only; deterministic (no clock, no randomness, no network): equal input, equal output.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from typing import Iterable, Mapping

from . import classes, glossary as glossary_mod, integrity
from .classes import AmbiguousToken, Edit, ProtectedSpan

#: Bump on ANY change to a rule, a data table or the verbalizer, and record it in the Changelog.
RULESET_VERSION = 1

EXPAND, NATIVE, GLOSSARY_ONLY = "expand", "native", "glossary_only"
MODES = (EXPAND, NATIVE, GLOSSARY_ONLY)


def ruleset_fingerprint() -> str:
    """Hash of the ruleset version and every data table the rules read; a test pins it to ``RULESET_VERSION``."""
    return integrity.content_hash({"ruleset": RULESET_VERSION, "lexicon": classes.LEXICON, "units": classes.UNIT_TABLE,
                                   "rules": [(r.rule_id, r.level, r.version) for r in classes.RULES]})


def resolve_modes(modes: Mapping[str, str] | None) -> dict[str, str]:
    """Every rule class mapped to a mode. ``None`` means every class expands (the core's own default, not production's)."""
    resolved = {cls: EXPAND for cls in classes.RULE_CLASSES}
    for cls, mode in (modes or {}).items():
        if cls not in resolved:
            raise ValueError(f"unknown normalization class {cls!r}")
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode!r} for {cls}")
        resolved[cls] = mode
    return resolved


class _Claims:
    """Disjoint claimed intervals, kept sorted; overlap tests by binary search."""

    def __init__(self) -> None:
        self.starts: list[int] = []
        self.ends: list[int] = []

    def overlaps(self, start: int, end: int) -> bool:
        i = bisect.bisect_right(self.starts, start) - 1
        if i >= 0 and self.ends[i] > start:
            return True
        return i + 1 < len(self.starts) and self.starts[i + 1] < end

    def add(self, start: int, end: int) -> None:
        i = bisect.bisect_left(self.starts, start)
        self.starts.insert(i, start)
        self.ends.insert(i, end)

    def add_merged(self, spans: Iterable[tuple[int, int]]) -> None:
        merged: list[list[int]] = []
        for start, end in sorted(spans):
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        for start, end in merged:
            self.add(start, end)


@dataclass(frozen=True)
class NormalizedText:
    source: str
    spoken: str
    edits: tuple[Edit, ...]
    withheld: tuple[Edit, ...]
    ambiguities: tuple[AmbiguousToken, ...]
    protected: tuple[ProtectedSpan, ...]
    ruleset_version: int = RULESET_VERSION
    _source_starts: tuple[int, ...] = field(default=(), repr=False, compare=False)
    _spoken_starts: tuple[int, ...] = field(default=(), repr=False, compare=False)

    @property
    def changed(self) -> bool:
        return bool(self.edits)

    def spoken_span(self, index: int) -> tuple[int, int]:
        """Where edit ``index`` sits in the spoken text."""
        start = self._spoken_starts[index]
        return start, start + len(self.edits[index].spoken)

    def source_to_spoken(self, offset: int) -> int:
        """Monotone map; an offset inside an edited token maps to the start of its spoken form."""
        i = bisect.bisect_right(self._source_starts, offset) - 1
        if i < 0:
            return offset
        edit, spoken_start = self.edits[i], self._spoken_starts[i]
        if offset < edit.source_end:
            return spoken_start
        return spoken_start + len(edit.spoken) + (offset - edit.source_end)

    def spoken_to_source(self, offset: int, *, end: bool = False) -> int:
        """Monotone map. Inside a spoken form: the token's source start, or its source end with ``end=True``."""
        if end:
            i = bisect.bisect_left(self._spoken_starts, offset) - 1
        else:
            i = bisect.bisect_right(self._spoken_starts, offset) - 1
        if i < 0:
            return offset
        edit, spoken_start = self.edits[i], self._spoken_starts[i]
        spoken_end = spoken_start + len(edit.spoken)
        if end and offset <= spoken_end:
            return edit.source_end
        if not end and offset < spoken_end:
            return edit.source_start
        return edit.source_end + (offset - spoken_end)


class _ClassIndex:
    """Which classes' candidates overlap a span (used to decide whether a glossary entry may touch a token)."""

    def __init__(self, raw: list[tuple[int, classes.Rule, object]]) -> None:
        items = sorted((_start(r), _start(r) + _length(r), (r.cls,) if isinstance(r, Edit) else r.candidates)
                       for _, _, r in raw)
        self.items = items
        self.starts = [item[0] for item in items]
        self.reach: list[int] = []
        for _, end, _ in items:
            self.reach.append(max(end, self.reach[-1] if self.reach else 0))

    def classes_over(self, start: int, end: int) -> set[str]:
        found: set[str] = set()
        i = bisect.bisect_left(self.starts, end) - 1
        while i >= 0 and self.reach[i] > start:
            if self.items[i][1] > start:
                found.update(self.items[i][2])
            i -= 1
        return found


def normalize(source: str, *, glossary: Iterable[glossary_mod.GlossaryEntry] = (), engine: str = glossary_mod.ALL_ENGINES,
              modes: Mapping[str, str] | None = None, phoneme_markup: bool = False) -> NormalizedText:
    """Normalize decoded source text for one engine. ``glossary`` is in precedence order (user entries first)."""
    resolved = resolve_modes(modes)
    protected = classes.find_protected(source)
    claims = _Claims()
    claims.add_merged((p.start, p.end) for p in protected)

    raw = [(index, rule, result) for index, rule in enumerate(classes.RULES) for result in rule.scan(source)]
    applied: list[Edit] = []
    withheld: list[Edit] = []
    ambiguous: list[AmbiguousToken] = []
    class_index = _ClassIndex(raw)

    for start, end, entry in glossary_mod.find_matches(source, glossary, engine):
        if claims.overlaps(start, end):
            continue
        matched = source[start:end]
        edit = Edit(start, end, matched, glossary_mod.spoken_for(entry, matched, phoneme_markup),
                    f"GLOSS.{entry.source}.{entry.id}", 1, classes.GLOSS, "glossary")
        claims.add(start, end)
        governed = class_index.classes_over(start, end)
        (withheld if any(resolved[c] == NATIVE for c in governed) else applied).append(edit)

    for level in sorted({rule.level for rule in classes.RULES}):
        candidates = [(index, result) for index, rule, result in raw if rule.level == level]
        candidates.sort(key=lambda item: (-_length(item[1]), item[0], _start(item[1])))
        for _, result in candidates:
            start, end = _start(result), _start(result) + _length(result)
            if claims.overlaps(start, end):
                continue
            claims.add(start, end)
            if isinstance(result, AmbiguousToken):
                ambiguous.append(result)
            elif resolved[result.cls] == EXPAND:
                applied.append(result)
            else:
                withheld.append(result)

    applied.sort(key=lambda e: e.source_start)
    spoken = integrity.apply_edits(source, applied)
    integrity.verify(source, spoken, applied, protected, phoneme_markup=phoneme_markup)
    spoken_starts: list[int] = []
    shift = 0
    for edit in applied:
        spoken_starts.append(edit.source_start + shift)
        shift += len(edit.spoken) - (edit.source_end - edit.source_start)
    return NormalizedText(source=source, spoken=spoken, edits=tuple(applied),
                          withheld=tuple(sorted(withheld, key=lambda e: e.source_start)),
                          ambiguities=tuple(sorted(ambiguous, key=lambda a: a.start)),
                          protected=tuple(sorted(protected, key=lambda p: (p.start, p.end))),
                          _source_starts=tuple(e.source_start for e in applied), _spoken_starts=tuple(spoken_starts))


def _start(result) -> int:
    return result.source_start if isinstance(result, Edit) else result.start


def _length(result) -> int:
    return (result.source_end - result.source_start) if isinstance(result, Edit) else (result.end - result.start)
