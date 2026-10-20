"""Spoken-form pronunciation glossary (Plan 01B section 4.5, decision D9).

The glossary is data, never code: a tracked bundled file that ships empty, and an optional, ignored user file. Engine
modules hold no word lists, so the "no hard-coded pronunciation substitutions" guards stay valid unmodified.

Matching is literal (``word`` = whole word, ``exact`` = anywhere); there are no regular expressions in an entry, so a
user file cannot cause catastrophic backtracking. A broken file never blocks a run: it contributes no entries and one
note; a broken entry is skipped with a note naming it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from .integrity import content_hash

BUNDLED_GLOSSARY = Path(__file__).with_name("data") / "glossary.default.json"
SCHEMA_VERSION = 1
ENGINE_IDS = ("edge", "kokoro", "chatterbox", "qwen3")
ALL_ENGINES = "*"
MAX_FILE_BYTES = 1_000_000
MAX_ENTRIES = 2000
MAX_WRITTEN = 80
MAX_SPOKEN = 80
MAX_PHONEMES = 120

_KEYS = {"id", "written", "spoken", "match", "case", "preserve_case", "engines", "phonemes", "note", "added"}
_ID = re.compile(r"[A-Za-z0-9_.-]{1,64}")
_SPOKEN = re.compile(r"[A-Za-z']+(?: [A-Za-z']+)*")
_PHONEME_FORBIDDEN = set("[]()/\\\n\r\t")


@dataclass(frozen=True)
class GlossaryEntry:
    id: str
    written: str
    spoken: str
    match: str = "word"            # "word" | "exact"
    case: str = "sensitive"        # "sensitive" | "insensitive"
    preserve_case: bool = False
    engines: tuple[str, ...] = (ALL_ENGINES,)
    phonemes: str | None = None
    note: str = ""
    added: str = ""
    source: str = "user"           # "user" | "bundled"

    def applies_to(self, engine: str) -> bool:
        return ALL_ENGINES in self.engines or engine in self.engines

    def as_data(self) -> dict:
        return {"id": self.id, "written": self.written, "spoken": self.spoken, "match": self.match, "case": self.case,
                "preserve_case": self.preserve_case, "engines": list(self.engines), "phonemes": self.phonemes,
                "source": self.source}


@dataclass(frozen=True)
class Glossary:
    """Validated entries in precedence order (user first), the notes produced while loading, and a content hash."""

    entries: tuple[GlossaryEntry, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def content_hash(self) -> str:
        return content_hash([e.as_data() for e in self.entries])


EMPTY = Glossary()


def _entry_error(raw: object, seen_ids: set[str]) -> str | None:
    if not isinstance(raw, dict):
        return "an entry must be an object"
    unknown = set(raw) - _KEYS
    if unknown:
        return f"unknown field(s) {sorted(unknown)}"
    entry_id, written, spoken = raw.get("id"), raw.get("written"), raw.get("spoken")
    if not isinstance(entry_id, str) or not _ID.fullmatch(entry_id):
        return "id must be 1-64 letters, digits, '.', '_' or '-'"
    if entry_id in seen_ids:
        return f"duplicate id {entry_id!r}"
    if not isinstance(written, str) or not written or len(written) > MAX_WRITTEN or written != written.strip() \
            or any(not c.isprintable() for c in written):
        return f"written must be 1-{MAX_WRITTEN} printable characters without surrounding spaces"
    if not isinstance(spoken, str) or len(spoken) > MAX_SPOKEN or not _SPOKEN.fullmatch(spoken):
        return f"spoken must be 1-{MAX_SPOKEN} characters: letters and apostrophes separated by single spaces"
    if re.search(r"(?<!\w)" + re.escape(written) + r"(?!\w)", spoken, re.IGNORECASE):
        return "spoken must not contain written"
    if raw.get("match", "word") not in ("word", "exact"):
        return "match must be 'word' or 'exact'"
    if raw.get("case", "sensitive") not in ("sensitive", "insensitive"):
        return "case must be 'sensitive' or 'insensitive'"
    if not isinstance(raw.get("preserve_case", False), bool):
        return "preserve_case must be true or false"
    engines = raw.get("engines", [ALL_ENGINES])
    if not isinstance(engines, list) or not engines or len(set(engines)) != len(engines) \
            or not all(e in ENGINE_IDS or e == ALL_ENGINES for e in engines) or (ALL_ENGINES in engines and len(engines) > 1):
        return f"engines must be [\"*\"] or a list drawn from {list(ENGINE_IDS)}"
    phonemes = raw.get("phonemes")
    if phonemes is not None and (not isinstance(phonemes, str) or not phonemes.strip() or len(phonemes) > MAX_PHONEMES
                                 or _PHONEME_FORBIDDEN & set(phonemes)):
        return f"phonemes must be 1-{MAX_PHONEMES} characters without brackets, slashes or line breaks"
    for key, limit in (("note", 200), ("added", 32)):
        if not isinstance(raw.get(key, ""), str) or len(raw.get(key, "")) > limit:
            return f"{key} must be text of at most {limit} characters"
    return None


def _overlaps(a: GlossaryEntry, b: GlossaryEntry) -> bool:
    """Could the two entries match overlapping text? Compared case-insensitively when either entry is."""
    if not (ALL_ENGINES in a.engines or ALL_ENGINES in b.engines or set(a.engines) & set(b.engines)):
        return False
    x, y = a.written, b.written
    if a.case == "insensitive" or b.case == "insensitive":
        x, y = x.casefold(), y.casefold()
    if x in y or y in x:
        return True
    return any(x.endswith(y[:k]) or y.endswith(x[:k]) for k in range(1, min(len(x), len(y))))


def parse(data: object, source: str) -> Glossary:
    """Validate one decoded file. Overlapping entries within a file: the later one is rejected."""
    label = f"{source} glossary"
    if not isinstance(data, dict) or data.get("version") != SCHEMA_VERSION or not isinstance(data.get("entries"), list):
        return Glossary((), (f"{label} ignored: expected {{\"version\": {SCHEMA_VERSION}, \"entries\": [...]}}",))
    raw_entries = data["entries"]
    if len(raw_entries) > MAX_ENTRIES:
        return Glossary((), (f"{label} ignored: more than {MAX_ENTRIES} entries",))
    entries: list[GlossaryEntry] = []
    notes: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_entries):
        error = _entry_error(raw, seen)
        if error is None:
            entry = GlossaryEntry(id=raw["id"], written=raw["written"], spoken=raw["spoken"],
                                  match=raw.get("match", "word"), case=raw.get("case", "sensitive"),
                                  preserve_case=raw.get("preserve_case", False),
                                  engines=tuple(raw.get("engines", [ALL_ENGINES])), phonemes=raw.get("phonemes"),
                                  note=raw.get("note", ""), added=raw.get("added", ""), source=source)
            clash = next((e for e in entries if _overlaps(e, entry)), None)
            if clash is not None:
                error = f"overlaps entry {clash.id!r}"
            else:
                seen.add(entry.id)
                entries.append(entry)
                continue
        name = raw.get("id") if isinstance(raw, dict) and isinstance(raw.get("id"), str) else f"#{index + 1}"
        notes.append(f"{label}: entry {name} skipped: {error}")
    return Glossary(tuple(entries), tuple(notes))


def load(path: Path, source: str) -> Glossary:
    """Read and validate a glossary file. A missing user file is normal (no note); any other problem is one note."""
    label = f"{source} glossary"
    try:
        if not path.exists():
            return EMPTY if source == "user" else Glossary((), (f"{label} missing: {path.name}",))
        if path.stat().st_size > MAX_FILE_BYTES:
            return Glossary((), (f"{label} ignored: larger than {MAX_FILE_BYTES} bytes",))
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return Glossary((), (f"{label} ignored: {type(exc).__name__}: {exc}",))
    return parse(data, source)


def merge(user: Glossary, bundled: Glossary) -> Glossary:
    """User entries take precedence; a bundled entry that overlaps a user entry is dropped with a note."""
    kept = list(user.entries)
    notes = list(user.notes) + list(bundled.notes)
    for entry in bundled.entries:
        clash = next((e for e in user.entries if _overlaps(e, entry)), None)
        if clash is not None:
            notes.append(f"bundled glossary: entry {entry.id} replaced by user entry {clash.id}")
        else:
            kept.append(entry)
    return Glossary(tuple(kept), tuple(notes))


def _pattern(entry: GlossaryEntry) -> re.Pattern:
    body = re.escape(entry.written)
    if entry.match == "word":
        body = r"(?<!\w)" + body + r"(?!\w)"
    return re.compile(body, re.IGNORECASE if entry.case == "insensitive" else 0)


def spoken_for(entry: GlossaryEntry, matched: str, phoneme_markup: bool) -> str:
    if phoneme_markup and entry.phonemes:
        return f"[{matched}](/{entry.phonemes}/)"
    spoken = entry.spoken
    if entry.preserve_case and entry.case == "insensitive":
        if len(matched) > 1 and matched.isupper():
            spoken = spoken.upper()
        elif matched[:1].isupper():
            spoken = spoken[:1].upper() + spoken[1:]
    return spoken


def find_matches(text: str, entries: Iterable[GlossaryEntry], engine: str) -> Iterator[tuple[int, int, GlossaryEntry]]:
    """Every match of every entry that applies to ``engine``, entries in precedence order."""
    for entry in entries:
        if engine == ALL_ENGINES or entry.applies_to(engine):
            for m in _pattern(entry).finditer(text):
                yield m.start(), m.end(), entry
