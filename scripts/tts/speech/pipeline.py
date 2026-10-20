"""Speech preparation for one run (Plan 01B sections 4.6-4.8): the frozen run snapshot and the per-file entry point.

``build_snapshot`` runs once, on the main thread, when a run starts. It reads the bundled mode table, the optional user
mode overrides and both glossaries, validates them, and returns a ``SpeechPrepSnapshot`` holding everything **by value**
(tuples and frozen dataclasses). The run carries that object inside its frozen options; worker threads and Retry Failed
use it and never read a file, so editing a glossary mid-run or before a retry cannot change an attempt. A new run reads
the files again. The hashes are for display and regression detection only -- they do not freeze anything.

``prepare(raw_text, snapshot, route)`` is what each engine route calls on its decoded source text. With the setting
``off`` (the default during rollout) it returns the text unchanged without normalizing at all, so every route behaves
exactly as before. With ``v1`` it normalizes with the route's profile and the snapshot's cells; if an integrity proof
fails, the file is spoken from its unchanged text and the run's Details say so -- a defect never fails a conversion.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from pathlib import Path

from . import glossary as glossary_mod
from . import profiles
from .document import SpeechDocument, parse_structure, structure_segments
from .glossary import GlossaryEntry
from .integrity import IntegrityError, content_hash
from .normalize import RULESET_VERSION, NormalizedText, normalize
from .report import details_lines

SETTING_OFF, SETTING_V1 = "off", "v1"
SETTINGS = (SETTING_OFF, SETTING_V1)
USER_GLOSSARY_NAME = "glossary.user.json"
USER_MODES_NAME = "modes.user.json"


@dataclass(frozen=True)
class SpeechPrepSnapshot:
    """Everything a run needs to prepare text, by value. Safe to share across worker threads."""

    setting: str = SETTING_OFF
    ruleset_version: int = RULESET_VERSION
    cells: tuple[tuple[str, str, str], ...] = ()            # (engine, class, mode), every cell
    glossary: tuple[GlossaryEntry, ...] = ()                # user then bundled, validated, precedence order
    user_overrides: tuple[tuple[str, str, str], ...] = ()
    notes: tuple[str, ...] = ()
    mode_table_hash: str = ""
    bundled_glossary_hash: str = ""
    user_glossary_hash: str = ""
    user_override_hash: str = ""

    @property
    def enabled(self) -> bool:
        return self.setting == SETTING_V1

    @property
    def speech_prep_version(self) -> str:
        """``sha256(RULESET_VERSION | mode table | bundled glossary | user glossary | user overrides)`` -- metadata only."""
        return content_hash([self.ruleset_version, self.mode_table_hash, self.bundled_glossary_hash,
                             self.user_glossary_hash, self.user_override_hash])

    def modes_for(self, engine: str) -> dict[str, str]:
        return {cls: mode for cell_engine, cls, mode in self.cells if cell_engine == engine}

    def exceptions(self) -> tuple[tuple[str, str, str], ...]:
        """Every cell that is not ``expand``: the exception report (Plan 01B 4.6)."""
        return tuple(cell for cell in self.cells if cell[2] != "expand")


OFF = SpeechPrepSnapshot()


def build_snapshot(setting: str, *, user_dir: Path | None, mode_table: Path = profiles.BUNDLED_MODE_TABLE,
                   bundled_glossary: Path = glossary_mod.BUNDLED_GLOSSARY) -> SpeechPrepSnapshot:
    """Read and validate every input once. Never raises for a user file; ``off`` reads nothing at all."""
    if setting not in SETTINGS:
        return SpeechPrepSnapshot(notes=(f"speech preparation setting {setting!r} is not known; using 'off'",))
    if setting == SETTING_OFF:
        return OFF
    try:
        table = profiles.load_mode_table(mode_table)
    except (OSError, ValueError) as exc:  # ships with the code: a defect, but never a reason to fail a run
        return SpeechPrepSnapshot(notes=(f"speech preparation is off for this run: the mode table could not be read "
                                         f"({type(exc).__name__}: {exc})",))
    if user_dir is not None:
        overrides, override_notes = profiles.load_user_modes(Path(user_dir) / USER_MODES_NAME)
        user = glossary_mod.load(Path(user_dir) / USER_GLOSSARY_NAME, "user")
    else:
        overrides, override_notes, user = (), (), glossary_mod.EMPTY
    bundled = glossary_mod.load(bundled_glossary, "bundled")
    merged = glossary_mod.merge(user, bundled)
    return SpeechPrepSnapshot(
        setting=setting, cells=profiles.effective_cells(table, overrides), glossary=merged.entries,
        user_overrides=overrides, notes=tuple(override_notes) + merged.notes,
        mode_table_hash=profiles.table_hash(table), bundled_glossary_hash=bundled.content_hash,
        user_glossary_hash=user.content_hash, user_override_hash=content_hash([list(c) for c in overrides]))


def _identity(text: str) -> NormalizedText:
    return NormalizedText(source=text, spoken=text, edits=(), withheld=(), ambiguities=(), protected=())


class SourceMap:
    """Structured engine text -> normalized text (verified segments) -> decoded source text (``NormalizedText``)."""

    def __init__(self, document: SpeechDocument, normalized: NormalizedText, segments) -> None:
        self.normalized = normalized
        self.segments = tuple(segments)
        self.starts = [s[0] for s in self.segments]
        covered = 0
        for text_start, raw_start, length in self.segments:
            if document.text[text_start:text_start + length] != normalized.spoken[raw_start:raw_start + length]:
                raise IntegrityError("structure map: a segment does not match its source")
            covered += sum(1 for c in document.text[text_start:text_start + length] if not c.isspace())
        if covered != sum(1 for c in document.text if not c.isspace()):
            raise IntegrityError("structure map: the segments do not cover the structured text")

    def _start(self, offset: int) -> int:
        i = bisect.bisect_right(self.starts, offset) - 1
        if i >= 0 and offset < self.segments[i][0] + self.segments[i][2]:
            return self.segments[i][1] + offset - self.segments[i][0]
        # Between segments (a joining newline): the start of the next segment.
        return self.segments[i + 1][1] if i + 1 < len(self.segments) else len(self.normalized.spoken)

    def _end(self, offset: int) -> int:
        i = bisect.bisect_left(self.starts, offset) - 1
        if i >= 0 and offset <= self.segments[i][0] + self.segments[i][2]:
            return self.segments[i][1] + offset - self.segments[i][0]
        # Between segments: the end of the previous segment.
        return self.segments[i][1] + self.segments[i][2] if i >= 0 else 0

    def source_span(self, start: int, end: int) -> tuple[int, int]:
        """A span of structured text in the decoded source. One wholly inside a joining newline covers no source
        character and comes back empty, at the next source character."""
        source_start = self.normalized.spoken_to_source(self._start(start))
        source_end = self.normalized.spoken_to_source(self._end(end), end=True)
        return source_start, max(source_start, source_end)


@dataclass(frozen=True)
class PreparedText:
    """One file's prepared text: the normalized source and, for routes that use the shared structure stage, the
    structured text the engine speaks."""

    route: str
    normalized: NormalizedText
    document: SpeechDocument | None
    notes: tuple[str, ...]
    enabled: bool

    @property
    def spoken_source(self) -> str:
        """The whole normalized text, structure markers included (what Edge direct's ``get_book`` parses)."""
        return self.normalized.spoken

    @property
    def text(self) -> str:
        """What the engine speaks: the structured text for routes that use the shared structure stage."""
        return self.document.text if self.document is not None else self.normalized.spoken

    def source_map(self) -> SourceMap:
        """Built on request (Qwen3's chunk plan), verified on construction."""
        if self.document is None:
            raise ValueError(f"{self.route} parses its own structure; no shared source map")
        options = profiles.PROFILES[self.route].structure
        return SourceMap(self.document, self.normalized, structure_segments(self.normalized.spoken, options))

    def details(self) -> list[str]:
        if not self.enabled:
            return []
        return list(self.notes) + details_lines(self.normalized)


def prepare(raw_text: str, snapshot: SpeechPrepSnapshot | None, route: str) -> PreparedText:
    """Prepare one decoded source text for ``route``. ``None`` means the setting is off."""
    profile = profiles.PROFILES[route]
    snapshot = OFF if snapshot is None else snapshot
    notes: list[str] = []
    normalized = _identity(raw_text)
    if snapshot.enabled:
        try:
            normalized = normalize(raw_text, glossary=snapshot.glossary, engine=profile.engine,
                                   modes=snapshot.modes_for(profile.engine), phoneme_markup=profile.phoneme_markup)
            for edit in normalized.edits:
                if edit.cls != "GLOSS" and set(edit.spoken) & set(profile.avoid_punctuation):
                    raise IntegrityError(f"{edit.rule_id} would add prosodic punctuation for {route}")
        except IntegrityError as exc:
            normalized = _identity(raw_text)
            notes.append(f"Speech preparation skipped for this file (integrity check: {exc}); the text was used unchanged")
    document = None if profile.structure is None else parse_structure(normalized.spoken, profile.structure)
    return PreparedText(route, normalized, document, tuple(notes), snapshot.enabled)
