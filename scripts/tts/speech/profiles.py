"""Engine profiles and the mode table (Plan 01B section 4.6).

A profile declares what one text route can take: its engine id (which glossary scope and mode-table row apply), how it
reads structure today, its kept chunk ceiling, the prosodic punctuation a spoken form must never introduce, and whether
it understands Kokoro's inline phoneme markup. Profiles hold **no rules**: every rule lives in ``classes.py`` and the
mode table only selects, per engine and class, ``expand`` | ``native`` | ``glossary_only``.

Rollout state (decision D6): every bundled cell is ``native``. The end state is one shared rule set that expands
everywhere; a non-``expand`` cell is an exception that needs evidence, a Decisions entry and a review checkpoint.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import classes
from .document import HEADING_PARAGRAPH_STRUCTURE, LOCAL_ENGINE_STRUCTURE, RAW_STRUCTURE, StructureOptions
from .glossary import ENGINE_IDS
from .integrity import content_hash
from .normalize import MODES

BUNDLED_MODE_TABLE = Path(__file__).with_name("data") / "modes.json"
MODE_TABLE_VERSION = 1
MAX_MODE_FILE_BYTES = 100_000

EDGE_DIRECT, EDGE_FOLDER, KOKORO, CHATTERBOX, QWEN3 = "edge_direct", "edge_folder", "kokoro", "chatterbox", "qwen3"
ROUTES = (EDGE_DIRECT, EDGE_FOLDER, KOKORO, CHATTERBOX, QWEN3)


@dataclass(frozen=True)
class EngineProfile:
    route: str
    engine: str                        # glossary scope and mode-table row
    structure: StructureOptions | None  # None: the route parses structure itself (Edge direct's get_book)
    max_chunk_chars: int | None        # informational: the engine's own ceiling, unchanged
    avoid_punctuation: str             # never allowed inside a spoken form for this engine
    phoneme_markup: bool
    native_risk: str


PROFILES: dict[str, EngineProfile] = {
    EDGE_DIRECT: EngineProfile(EDGE_DIRECT, "edge", None, None, ",-—.", False,
                               "server-side normalization is undocumented; treated as a black box"),
    EDGE_FOLDER: EngineProfile(EDGE_FOLDER, "edge", RAW_STRUCTURE, 3000, ",-—.", False,
                               "server-side normalization is undocumented; treated as a black box"),
    KOKORO: EngineProfile(KOKORO, "kokoro", LOCAL_ENGINE_STRUCTURE, 3000, ",:", True,
                          "misaki reads any cue-less four-digit integer as a year"),
    CHATTERBOX: EngineProfile(CHATTERBOX, "chatterbox", LOCAL_ENGINE_STRUCTURE, 300, ",:;-—–", False,
                              "unknown for years and currency; wheel punc_norm rewrites colons and dashes"),
    QWEN3: EngineProfile(QWEN3, "qwen3", HEADING_PARAGRAPH_STRUCTURE, 600, ",:;-—–", False, "unknown"),
}


def _valid_row(row: object) -> str | None:
    if not isinstance(row, dict):
        return "must be an object of class -> mode"
    unknown = set(row) - set(classes.RULE_CLASSES)
    if unknown:
        return f"unknown class(es) {sorted(unknown)}"
    bad = sorted(cls for cls, mode in row.items() if mode not in MODES)
    if bad:
        return f"mode must be one of {list(MODES)} for {bad}"
    return None


def parse_mode_table(data: object) -> dict[str, dict[str, str]]:
    """The bundled table: every engine, every class, a valid mode. Raises ``ValueError`` -- it ships with the code."""
    if not isinstance(data, dict) or data.get("version") != MODE_TABLE_VERSION or not isinstance(data.get("modes"), dict):
        raise ValueError(f"mode table must be {{\"version\": {MODE_TABLE_VERSION}, \"modes\": {{...}}}}")
    table = data["modes"]
    if set(table) != set(ENGINE_IDS):
        raise ValueError(f"mode table must have exactly the engines {list(ENGINE_IDS)}")
    for engine, row in table.items():
        error = _valid_row(row)
        if error or set(row) != set(classes.RULE_CLASSES):
            raise ValueError(f"mode table row {engine}: {error or 'must name every class'}")
    return {engine: dict(row) for engine, row in table.items()}


def load_mode_table(path: Path = BUNDLED_MODE_TABLE) -> dict[str, dict[str, str]]:
    return parse_mode_table(json.loads(path.read_text(encoding="utf-8")))


def parse_user_modes(data: object) -> tuple[tuple[tuple[str, str, str], ...], tuple[str, ...]]:
    """Optional per-cell overrides. Invalid content contributes nothing and one note; it never fails a run."""
    label = "user mode overrides"
    if not isinstance(data, dict) or data.get("version") != MODE_TABLE_VERSION or not isinstance(data.get("modes"), dict):
        return (), (f"{label} ignored: expected {{\"version\": {MODE_TABLE_VERSION}, \"modes\": {{engine: {{class: mode}}}}}}",)
    cells: list[tuple[str, str, str]] = []
    notes: list[str] = []
    for engine, row in sorted(data["modes"].items()):
        error = f"unknown engine {engine!r}" if engine not in ENGINE_IDS else _valid_row(row)
        if error:
            notes.append(f"{label}: {engine} ignored: {error}")
            continue
        cells.extend((engine, cls, mode) for cls, mode in sorted(row.items()))
    return tuple(cells), tuple(notes)


def load_user_modes(path: Path) -> tuple[tuple[tuple[str, str, str], ...], tuple[str, ...]]:
    try:
        if not path.exists():
            return (), ()
        if path.stat().st_size > MAX_MODE_FILE_BYTES:
            return (), (f"user mode overrides ignored: larger than {MAX_MODE_FILE_BYTES} bytes",)
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return (), (f"user mode overrides ignored: {type(exc).__name__}: {exc}",)
    return parse_user_modes(data)


def effective_cells(table: dict[str, dict[str, str]],
                    overrides: tuple[tuple[str, str, str], ...]) -> tuple[tuple[str, str, str], ...]:
    """Every (engine, class, mode) cell after the user's overrides, in a stable order."""
    merged = {engine: dict(row) for engine, row in table.items()}
    for engine, cls, mode in overrides:
        merged[engine][cls] = mode
    return tuple((engine, cls, merged[engine][cls]) for engine in ENGINE_IDS for cls in classes.RULE_CLASSES)


def table_hash(table: dict[str, dict[str, str]]) -> str:
    return content_hash(table)
