"""What speech preparation did to one file, in a form the run's Details view can show (Plan 01B 4.3 ambiguity policy, 4.7).

Diagnostics never block a conversion; they make the behaviour visible: "Speech preparation: N edits, M ambiguous left
unchanged", per-class counts, the edits a mode withheld, and a few examples with their line numbers.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .normalize import NormalizedText


@dataclass(frozen=True)
class SpeechPrepSummary:
    edits: int
    ambiguous: int
    withheld: int
    protected: int
    edits_by_class: tuple[tuple[str, int], ...]
    withheld_by_class: tuple[tuple[str, int], ...]
    ambiguous_by_reason: tuple[tuple[str, int], ...]


def _counted(values) -> tuple[tuple[str, int], ...]:
    return tuple(sorted(Counter(values).items()))


def summarize(result: NormalizedText) -> SpeechPrepSummary:
    return SpeechPrepSummary(
        edits=len(result.edits), ambiguous=len(result.ambiguities), withheld=len(result.withheld),
        protected=len(result.protected),
        edits_by_class=_counted(e.cls for e in result.edits),
        withheld_by_class=_counted(e.cls for e in result.withheld),
        ambiguous_by_reason=_counted(a.reason for a in result.ambiguities))


def details_line(summary: SpeechPrepSummary) -> str:
    edits = f"{summary.edits} edit{'' if summary.edits == 1 else 's'}"
    return f"Speech preparation: {edits}, {summary.ambiguous} ambiguous left unchanged"


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def details_lines(result: NormalizedText, *, examples: int = 5) -> list[str]:
    """Human-readable lines for the Details view: the headline, counts, and a few examples of each kind."""
    summary = summarize(result)
    lines = [details_line(summary)]
    if summary.edits_by_class:
        lines.append("  changed: " + ", ".join(f"{cls} {n}" for cls, n in summary.edits_by_class))
    if summary.withheld_by_class:
        lines.append("  left to the engine: " + ", ".join(f"{cls} {n}" for cls, n in summary.withheld_by_class))
    for edit in result.edits[:examples]:
        lines.append(f"  line {_line_number(result.source, edit.source_start)}: "
                     f"{edit.original!r} -> {edit.spoken!r} ({edit.cls})")
    for token in result.ambiguities[:examples]:
        lines.append(f"  line {_line_number(result.source, token.start)}: {token.text!r} unchanged ({token.reason})")
    return lines
