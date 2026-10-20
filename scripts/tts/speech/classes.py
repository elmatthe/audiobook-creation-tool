"""Normalization classes and their rules (Plan 01B section 4.3).

Each rule scans the decoded source text and yields either an ``Edit`` (a positive cue was found, or the token is
unambiguous) or an ``AmbiguousToken`` (no cue, or conflicting cues: the token is *claimed* so no lower rule rewrites part of
it, and it is left exactly as written). A rule that does not apply yields nothing. Rules never see each other's output:
``normalize`` resolves all candidates against the original text in one pass.

Cue words, units and spoken names are data (``data/lexicon.json``, ``data/units.json``); the code holds only the logic.
Every spoken form is letters, apostrophes and single spaces (invariant I5) and replaces only the matched token.

Tiers: 1 = enable once its gate passes; 2 = candidate, gated per cell; 3 = deliberately never expanded in v1 (``e.g.``,
``i.e.``, ``etc.``, ``vs.``, and the symbols ``@ # / + = § ©``) -- tier 3 has no rule at all.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Union

from . import numbers_en as num

DATA_DIR = Path(__file__).with_name("data")

PROT, GLOSS = "PROT", "GLOSS"
HYG, CARD, DEC, ORD, PCT, CUR, YEAR = "HYG", "CARD", "DEC", "ORD", "PCT", "CUR", "YEAR"
TIME, RATIO, DATE, RANGE, FRAC, UNIT, TITLE, ROMAN, SYM = ("TIME", "RATIO", "DATE", "RANGE", "FRAC", "UNIT", "TITLE",
                                                           "ROMAN", "SYM")

#: Every class a mode-table cell can govern, in table order.
RULE_CLASSES = (HYG, CARD, DEC, ORD, PCT, CUR, YEAR, TIME, RATIO, DATE, RANGE, FRAC, UNIT, TITLE, ROMAN, SYM)
TIERS = {HYG: 1, CARD: 1, DEC: 1, ORD: 1, PCT: 1, CUR: 1, YEAR: 1,
         TIME: 2, RATIO: 2, DATE: 2, RANGE: 2, FRAC: 2, UNIT: 2, TITLE: 2, ROMAN: 2, SYM: 2}

#: Resolution levels (lower first). Protected spans (0) and the glossary (1-2) are resolved by ``normalize`` itself.
#: Hygiene runs last, on what is left: its spans are single characters, and the only overlap with a class is a no-break
#: space inside a numeric token, whose spoken form already uses an ordinary space.
STRUCTURED, NUMERIC, WORDS, SYMBOLS, HYGIENE = 4, 5, 6, 7, 8


@dataclass(frozen=True)
class Edit:
    """One change, in decoded-source coordinates: ``source[source_start:source_end] == original`` becomes ``spoken``."""

    source_start: int
    source_end: int
    original: str
    spoken: str
    rule_id: str
    rule_version: int
    cls: str
    confidence: str  # "unambiguous" | "cue" | "glossary" | "mechanical"


@dataclass(frozen=True)
class AmbiguousToken:
    """A token left unchanged on purpose, with the readings it could have had."""

    start: int
    end: int
    text: str
    candidates: tuple[str, ...]
    reason: str
    rule_id: str


@dataclass(frozen=True)
class ProtectedSpan:
    start: int
    end: int
    kind: str  # "metadata" | "heading_marker" | "url" | "email" | "path" | "non_english"


Result = Union[Edit, AmbiguousToken]


@dataclass(frozen=True)
class Rule:
    rule_id: str
    level: int
    version: int
    classes: tuple[str, ...]
    scan: Callable[[str], Iterator[Result]]


# --------------------------------------------------------------------------- data tables

def _load(name: str) -> dict:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


LEXICON = _load("lexicon.json")
UNIT_TABLE = _load("units.json")


def _lower_set(key: str) -> frozenset[str]:
    return frozenset(word.lower() for word in LEXICON[key])


MONTHS: dict[str, int] = dict(LEXICON["months"])
MONTH_ABBREVIATIONS: dict[str, str] = dict(LEXICON["month_abbreviations"])
MONTH_WORDS = frozenset(w.lower() for w in list(MONTHS) + list(MONTH_ABBREVIATIONS))
YEAR_CUES_BEFORE = _lower_set("year_cues_before")
ERAS = frozenset(LEXICON["year_cues_after"])
COUNT_NOUNS = _lower_set("count_nouns")
IDENTIFIER_CUES = _lower_set("identifier_cues")
STREET_SUFFIXES = frozenset(LEXICON["street_suffixes"])
SECTION_CUES = _lower_set("section_cues")
TIME_CUES_BEFORE = _lower_set("time_cues_before")
TIME_CUES_AFTER = _lower_set("time_cues_after")
RATIO_CUES = _lower_set("ratio_cues")
RANGE_CUES = _lower_set("range_cues")
RANGE_YEAR_CUES = _lower_set("range_year_cues")
FRACTION_NOUNS = _lower_set("fraction_nouns")
TITLES: dict[str, str] = dict(LEXICON["titles"])
AMBIGUOUS_TITLES = frozenset(LEXICON["ambiguous_titles"])
ROMAN_CUES = _lower_set("roman_cues")
ROMAN_CUE_PHRASES = frozenset(LEXICON["roman_cue_phrases"])
REGNAL_NAMES = frozenset(LEXICON["regnal_names"])
CURRENCIES: dict[str, dict] = dict(LEXICON["currencies"])
MAGNITUDE_WORDS = tuple(LEXICON["magnitude_words"])
MAGNITUDE_SUFFIXES: dict[str, str] = dict(LEXICON["magnitude_suffixes"])
AMPM: dict[str, str] = dict(LEXICON["ampm"])
VULGAR_FRACTIONS: dict[str, tuple[int, int]] = {k: tuple(v) for k, v in LEXICON["vulgar_fractions"].items()}
HYGIENE_TABLE = LEXICON["hygiene"]
LANGUAGE = LEXICON["language"]
UNITS = tuple(UNIT_TABLE["units"])
UNIT_BY_SYMBOL = {unit["symbol"]: unit for unit in UNITS}
UNIT_WORDS = frozenset(w.lower() for unit in UNITS for w in (unit["singular"].split()[0], unit["plural"].split()[0],
                                                               unit["symbol"]))
ENGLISH_STOPWORDS = frozenset(LANGUAGE["english_stopwords"])
FOREIGN_STOPWORDS = frozenset(LANGUAGE["foreign_stopwords"])

# --------------------------------------------------------------------------- shared patterns and context

INT = r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)"
#: A numeric token must not be glued to a word, another number, a sign or a symbol another class owns.
BEFORE = r"(?<![\w.,/:+=$£€¥@#'’×°–-])"
AFTER = r"(?![\w%°×/+=]|[.,:][0-9]|[-–]\w|['’]\w)"
#: The space inside a structured token; PDF extraction often leaves a no-break space between a number and its unit.
SP = "[ \u00a0\u202f]"
_AMPM_ALT = "|".join(re.escape(k) for k in sorted(AMPM, key=len, reverse=True))
_SPACES = " \t\u00a0"
_STRIP = "\"'“”‘’()[]{}"
_BOUNDARY_PUNCTUATION = ",;:!?"


def _line_bounds(text: str, pos: int) -> tuple[int, int]:
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    return start, len(text) if end == -1 else end


def prev_tokens(text: str, pos: int, n: int = 1) -> list[str]:
    """Up to ``n`` whitespace-separated words before ``pos`` on the same line, nearest first.

    Empty when the token is glued to something before it, and stops at a word that ends a clause (``said, 1999``).
    """
    start, _ = _line_bounds(text, pos)
    before = text[start:pos]
    if not before or before[-1] not in _SPACES:
        return []
    found: list[str] = []
    for token in reversed(before.split()):
        if len(found) == n or token[-1] in _BOUNDARY_PUNCTUATION:
            break
        found.append(token)
    return found


def next_tokens(text: str, pos: int, n: int = 1) -> list[str]:
    """Up to ``n`` words after ``pos`` on the same line; empty when punctuation follows the token directly."""
    _, end = _line_bounds(text, pos)
    after = text[pos:end]
    if not after or after[0] not in _SPACES:
        return []
    found: list[str] = []
    for token in after.split():
        found.append(token)
        if len(found) == n or token.rstrip(_STRIP)[-1:] in _BOUNDARY_PUNCTUATION:
            break
    return found


def cue(token: str) -> str:
    """Comparison form of a context word: quotes, brackets and clause punctuation removed, one final stop removed, lower case."""
    word = token.strip(_STRIP).rstrip(_BOUNDARY_PUNCTUATION).strip(_STRIP)
    if word.endswith(".") and not word.endswith(".."):
        word = word[:-1]
    return word.lower()


def _raw(token: str) -> str:
    return token.strip(_STRIP).rstrip(_BOUNDARY_PUNCTUATION).strip(_STRIP)


def _first_cue(tokens: list[str]) -> str:
    return cue(tokens[0]) if tokens else ""


def _leading_zero(raw: str) -> bool:
    return len(raw) > 1 and raw[0] == "0" and raw[1] != "."


def _int_value(raw: str) -> int:
    return int(raw.replace(",", ""))


def _number_words(raw: str) -> str:
    """Cardinal or decimal words for a written number (commas allowed in the whole part)."""
    whole, _, fraction = raw.partition(".")
    value = _int_value(whole)
    return num.decimal(value, fraction) if fraction else num.cardinal(value)


def _edit(match_or_span, text: str, spoken: str, rule_id: str, cls: str, confidence: str) -> Edit:
    start, end = match_or_span if isinstance(match_or_span, tuple) else match_or_span.span()
    return Edit(start, end, text[start:end], spoken, rule_id, 1, cls, confidence)


def _ambiguous(span, text: str, candidates: tuple[str, ...], reason: str, rule_id: str) -> AmbiguousToken:
    start, end = span if isinstance(span, tuple) else span.span()
    return AmbiguousToken(start, end, text[start:end], candidates, reason, rule_id)


def _too_long(raw: str) -> bool:
    return len(raw.replace(",", "").split(".")[0]) > 15


def _keep_sentence_stop(text: str, end: int, marker: str) -> int:
    """``p.m.`` ending a sentence: the final stop stays in the text as the sentence's own punctuation."""
    if not marker.endswith("."):
        return end
    rest = text[end:end + 3]
    if rest == "" or rest[0] == "\n" or (rest[0] in _SPACES and len(rest) > 1 and (rest[1].isupper() or rest[1] in "\"“'‘\n")):
        return end - 1
    return end


# --------------------------------------------------------------------------- protected spans (level 0)

_METADATA = re.compile(r"(?m)^[^\S\n]*(?:Title:|Author:)[^\n]*")
_HEADING_MARKER = re.compile(r"(?m)^[^\S\n]*#+[^\S\n]*")
_URL = re.compile(r"\b(?:https?|ftp)://[^\s<>\"]+|\bwww\.[^\s<>\"]+", re.IGNORECASE)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_WINDOWS_PATH = re.compile(r"\b[A-Za-z]:\\[^\s\"<>|]*|\\\\[^\s\"<>|]+")
_POSIX_PATH = re.compile(r"(?<![\w/.~])(?:~|\.{1,2})?/[\w.-]+(?:/[\w.-]+)+/?")
_TRAILING = ".,;:!?)]}'\"’”"


def _non_latin_ratio(line: str) -> float:
    letters = [c for c in line if c.isalpha()]
    if not letters:
        return 0.0
    foreign = sum(1 for c in letters if ord(c) > 0x24F and "LATIN" not in unicodedata.name(c, ""))
    return foreign / len(letters)


def is_english_line(line: str) -> bool:
    """English unless the script or the function words say otherwise (decision D15: English-only in v1)."""
    if _non_latin_ratio(line) >= LANGUAGE["non_latin_ratio"]:
        return False
    words = [w.strip(_STRIP + ".,;:!?").lower() for w in line.split()]
    if len(words) < LANGUAGE["min_words"]:
        return True
    english = sum(1 for w in words if w in ENGLISH_STOPWORDS)
    foreign = sum(1 for w in words if w in FOREIGN_STOPWORDS and w not in ENGLISH_STOPWORDS)
    return not (foreign >= 2 and foreign > english)


def find_protected(text: str) -> list[ProtectedSpan]:
    """Spans that are recorded and never edited: structure markers, URLs, e-mails, paths, non-English lines."""
    spans: list[ProtectedSpan] = []
    for m in _METADATA.finditer(text):
        spans.append(ProtectedSpan(m.start(), m.end(), "metadata"))
    for m in _HEADING_MARKER.finditer(text):
        if m.end() > m.start():
            spans.append(ProtectedSpan(m.start(), m.end(), "heading_marker"))
    for pattern, kind in ((_URL, "url"), (_EMAIL, "email"), (_WINDOWS_PATH, "path"), (_POSIX_PATH, "path")):
        for m in pattern.finditer(text):
            end = m.end()
            while end > m.start() and text[end - 1] in _TRAILING:
                end -= 1
            if end > m.start():
                spans.append(ProtectedSpan(m.start(), end, kind))
    position = 0
    for line in text.split("\n"):
        if line.strip() and not is_english_line(line):
            spans.append(ProtectedSpan(position, position + len(line), "non_english"))
        position += len(line) + 1
    return spans


# --------------------------------------------------------------------------- structured classes (level 4)

_CURRENCY = re.compile(BEFORE + r"(?P<sym>[$£€¥])[ ]?(?P<int>" + INT + r")(?:\.(?P<frac>[0-9]+))?"
                       r"(?:(?P<word>" + SP + r"(?:" + "|".join(MAGNITUDE_WORDS) + r"))(?!\w)|(?P<suf>bn|k|K|m|M|B)(?!\w))?"
                       + AFTER)


def scan_currency(text: str) -> Iterator[Result]:
    for m in _CURRENCY.finditer(text):
        whole, fraction = m["int"], m["frac"]
        if _leading_zero(whole) or _too_long(whole):
            yield _ambiguous(m, text, (CUR,), "unusual amount", "CUR.amount")
            continue
        major, minor = CURRENCIES[m["sym"]]["major"], CURRENCIES[m["sym"]]["minor"]
        value = _int_value(whole)
        magnitude = (m["word"] or "").strip() or MAGNITUDE_SUFFIXES.get(m["suf"] or "", "")
        if magnitude:
            amount = num.decimal(value, fraction) if fraction else num.cardinal(value)
            spoken = f"{amount} {magnitude} {major[1]}"
        elif fraction is None:
            spoken = f"{num.cardinal(value)} {major[0] if value == 1 else major[1]}"
        elif len(fraction) == 2 and minor:
            cents = int(fraction)
            parts = []
            if value or not cents:
                parts.append(f"{num.cardinal(value)} {major[0] if value == 1 else major[1]}")
            if cents:
                parts.append(f"{num.cardinal(cents)} {minor[0] if cents == 1 else minor[1]}")
            spoken = " ".join(parts)
        else:
            spoken = f"{num.decimal(value, fraction)} {major[1]}"
        yield _edit(m, text, spoken, "CUR.amount", CUR, "unambiguous")


_COLON = re.compile(BEFORE + r"(?P<h>[0-9]+):(?P<m>[0-9]+)(?P<s>:[0-9]+)?"
                    r"(?:" + SP + r"?(?P<ap>" + _AMPM_ALT + r")(?!\w))?(?![\w%°×/:]|[.,][0-9]|[-–]\w)")
_HOUR_AMPM = re.compile(BEFORE + r"(?P<h>[0-9]{1,2})" + SP + r"?(?P<ap>" + _AMPM_ALT + r")(?!\w)")


def scan_colon_numbers(text: str) -> Iterator[Result]:
    """``7:05`` (TIME) and ``3:1`` (RATIO). Without a cue the two are indistinguishable, so the token is left alone."""
    for m in _COLON.finditer(text):
        h_raw, m_raw = m["h"], m["m"]
        hour, minute = int(h_raw), int(m_raw)
        candidates = (TIME, RATIO)
        if m["s"]:
            yield _ambiguous(m, text, candidates, "three-part time or duration", "TIME.clock")
            continue
        is_clock = len(m_raw) == 2 and minute < 60 and 1 <= hour <= 24 and len(h_raw) <= 2
        if m["ap"]:
            if is_clock and hour <= 12:
                end = _keep_sentence_stop(text, m.end(), m["ap"])
                words = num.cardinal(hour) if minute == 0 else num.clock_time(hour, minute)
                yield _edit((m.start(), end), text, f"{words} {AMPM[m['ap']]}", "TIME.clock", TIME, "cue")
            else:
                yield _ambiguous(m, text, (TIME,), "not a twelve-hour clock time", "TIME.clock")
            continue
        before, after = prev_tokens(text, m.start(), 3), next_tokens(text, m.end(), 1)
        ratio_cue = any(cue(t) in RATIO_CUES for t in before) or _first_cue(after) in RATIO_CUES
        time_cue = _first_cue(before) in TIME_CUES_BEFORE or _first_cue(after) in TIME_CUES_AFTER
        reference = bool(before) and _raw(before[0])[:1].isupper()
        padded = _leading_zero(h_raw) or (_leading_zero(m_raw) and not is_clock)
        if ratio_cue and time_cue:
            yield _ambiguous(m, text, candidates, "conflicting time and ratio cues", "TIME.clock")
        elif ratio_cue and not padded:
            yield _edit(m, text, f"{num.cardinal(hour)} to {num.cardinal(minute)}", "RATIO.colon", RATIO, "cue")
        elif time_cue and is_clock:
            yield _edit(m, text, num.clock_time(hour, minute), "TIME.clock", TIME, "cue")
        elif not is_clock and not reference and not padded and not ratio_cue and (minute >= 60 or hour > 24):
            yield _edit(m, text, f"{num.cardinal(hour)} to {num.cardinal(minute)}", "RATIO.colon", RATIO, "unambiguous")
        else:
            yield _ambiguous(m, text, candidates, "time, ratio or reference without a cue", "TIME.clock")
    for m in _HOUR_AMPM.finditer(text):
        hour = int(m["h"])
        if 1 <= hour <= 12 and not _leading_zero(m["h"]):
            end = _keep_sentence_stop(text, m.end(), m["ap"])
            yield _edit((m.start(), end), text, f"{num.cardinal(hour)} {AMPM[m['ap']]}", "TIME.hour", TIME, "cue")
        else:
            yield _ambiguous(m, text, (TIME,), "not a twelve-hour clock hour", "TIME.hour")


_MONTH_ALT = "|".join(sorted(list(MONTHS) + [re.escape(a) + r"\.?" for a in MONTH_ABBREVIATIONS],
                             key=lambda s: len(s.replace("\\.?", "")), reverse=True))
_MONTH_DAY = re.compile(r"(?<![\w.])(?P<month>" + _MONTH_ALT + r")" + SP + r"(?P<day>[0-9]{1,2})(?P<sfx>st|nd|rd|th)?"
                        r"(?![\w%°×/:]|[.,][0-9]|[-–]\w|['’]\w)"
                        r"(?:(?P<sep>,?" + SP + r")(?P<year>[0-9]{4})" + AFTER + ")?")
_ISO_DATE = re.compile(r"(?<![\w.,/:+-])(?P<y>[0-9]{4})-(?P<mo>[0-9]{2})-(?P<d>[0-9]{2})(?![\w%°×/:-]|[.,][0-9])")
_SLASH_DATE = re.compile(r"(?<![\w.,/:+-])[0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4}(?![\w/]|[.,][0-9])")
_DAY_MONTH = re.compile(BEFORE + r"[0-9]{1,2}(?:st|nd|rd|th)?[ ](?:of[ ])?(?:" + _MONTH_ALT + r")(?!\w)(?:,?[ ][0-9]{4}(?![0-9]))?")
_MONTH_NUMBERS = {name: n for name, n in MONTHS.items()}
_MONTH_NAMES = {n: name for name, n in MONTHS.items()}


def _days_in_month(month: int, year: int | None) -> int:
    if month == 2:
        if year is None:
            return 29
        return 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28
    return 30 if month in (4, 6, 9, 11) else 31


def scan_dates(text: str) -> Iterator[Result]:
    for m in _MONTH_DAY.finditer(text):
        name = m["month"].rstrip(".")
        name = MONTH_ABBREVIATIONS.get(name, name)
        month, day = _MONTH_NUMBERS[name], int(m["day"])
        year = int(m["year"]) if m["year"] else None
        if (m["sfx"] and m["sfx"] != num.ordinal_suffix(day)) or _leading_zero(m["day"]) \
                or not 1 <= day <= _days_in_month(month, year) or (year is not None and not 1000 <= year <= 2099):
            yield _ambiguous(m, text, (DATE,), "not a valid month and day", "DATE.month_day")
            continue
        spoken = f"{name} {num.ordinal(day)}" + (f" {num.year(year)}" if year is not None else "")
        yield _edit(m, text, spoken, "DATE.month_day", DATE, "unambiguous")
    for m in _ISO_DATE.finditer(text):
        year, month, day = int(m["y"]), int(m["mo"]), int(m["d"])
        if 1000 <= year <= 2099 and 1 <= month <= 12 and 1 <= day <= _days_in_month(month, year):
            spoken = f"{_MONTH_NAMES[month]} {num.ordinal(day)} {num.year(year)}"
            yield _edit(m, text, spoken, "DATE.iso", DATE, "unambiguous")
        else:
            yield _ambiguous(m, text, (DATE, RANGE), "not a valid ISO date", "DATE.iso")
    for m in _SLASH_DATE.finditer(text):
        yield _ambiguous(m, text, (DATE,), "numeric date: day and month order depend on the locale", "DATE.slash")
    for m in _DAY_MONTH.finditer(text):
        yield _ambiguous(m, text, (DATE,), "day before month: no en-US reading is fixed", "DATE.day_month")


_RANGE = re.compile(BEFORE + r"(?P<a>" + INT + r")(?P<dash>[-–]|[ ]–[ ])(?P<b>" + INT + r")" + AFTER)


def _is_count_word(token: str) -> bool:
    word = cue(token)
    return word in COUNT_NOUNS or word in UNIT_WORDS


def scan_ranges(text: str) -> Iterator[Result]:
    """``pages 12-15`` -> ``pages twelve to fifteen``. Without a cue the dash may be a minus or part of an identifier."""
    for m in _RANGE.finditer(text):
        a_raw, b_raw = m["a"], m["b"]
        if _leading_zero(a_raw) or _leading_zero(b_raw) or _too_long(a_raw) or _too_long(b_raw):
            yield _ambiguous(m, text, (RANGE,), "identifier-like range", "RANGE.dash")
            continue
        a, b = _int_value(a_raw), _int_value(b_raw)
        before, after = _first_cue(prev_tokens(text, m.start())), next_tokens(text, m.end())
        count_after = bool(after) and _is_count_word(after[0])
        if not (before in RANGE_CUES or count_after):
            yield _ambiguous(m, text, (RANGE,), "range, subtraction or identifier without a cue", "RANGE.dash")
            continue
        if 1000 <= a <= 2099 and "," not in a_raw and len(b_raw) < 4:
            yield _ambiguous(m, text, (RANGE, YEAR), "abbreviated second year", "RANGE.dash")
            continue
        as_years = (before in RANGE_YEAR_CUES and not count_after and "," not in a_raw + b_raw
                    and 1000 <= a <= 2099 and 1000 <= b <= 2099)
        form = num.year if as_years else num.cardinal
        yield _edit(m, text, f"{form(a)} to {form(b)}", "RANGE.dash", RANGE, "cue")


_FRACTION = re.compile(BEFORE + r"(?:(?P<whole>[0-9]+)[ ])?(?P<n>[0-9]+)/(?P<d>[0-9]+)" + AFTER)
_VULGAR = re.compile(BEFORE + r"(?:(?P<whole>[0-9]+)[ ]?)?(?P<v>[" + "".join(VULGAR_FRACTIONS) + r"])(?![\w])")


def _slash_fraction(text: str, start: int, end: int, whole: str | None, n: str, d: str) -> Result:
    numerator, denominator = int(n), int(d)
    after = next_tokens(text, end)
    noun = bool(after) and (cue(after[0]) in FRACTION_NOUNS or _is_count_word(after[0]))
    if any(_leading_zero(r) for r in (whole or "1", n, d)) or not 2 <= denominator <= 100 or numerator == 0 or not noun:
        return _ambiguous((start, end), text, (FRAC, DATE), "fraction, date or identifier without a noun", "FRAC.slash")
    spoken = num.fraction(numerator, denominator)
    if whole:
        spoken = f"{num.cardinal(int(whole))} and {spoken}"
    return _edit((start, end), text, spoken, "FRAC.slash", FRAC, "cue")


def scan_fractions(text: str) -> Iterator[Result]:
    """``1/2 cup`` -> ``one half cup``. A bare ``1/2`` could be a date, so a following noun is required.

    A mixed number (``1 1/2``) also offers its bare fraction as a candidate: if the whole number is claimed by a longer
    token (``March 5, 2024 1/2 cup``), the fraction must still be found, or a second pass would find it (invariant I6).
    """
    for m in _FRACTION.finditer(text):
        yield _slash_fraction(text, m.start(), m.end(), m["whole"], m["n"], m["d"])
        if m["whole"]:
            yield _slash_fraction(text, m.start("n"), m.end(), None, m["n"], m["d"])
    for m in _VULGAR.finditer(text):
        numerator, denominator = VULGAR_FRACTIONS[m["v"]]
        spoken = num.fraction(numerator, denominator)
        if m["whole"]:
            yield _edit((m.start("v"), m.end()), text, spoken, "FRAC.vulgar", FRAC, "unambiguous")
            if _leading_zero(m["whole"]):
                yield _ambiguous(m, text, (FRAC,), "identifier-like number", "FRAC.vulgar")
                continue
            spoken = f"{num.cardinal(int(m['whole']))} and {spoken}"
        yield _edit(m, text, spoken, "FRAC.vulgar", FRAC, "unambiguous")


_UNIT_ALT = "|".join(re.escape(u["symbol"]) for u in sorted(UNITS, key=lambda u: len(u["symbol"]), reverse=True))
_UNIT = re.compile(BEFORE + r"(?P<num>" + INT + r"(?:\.[0-9]+)?)(?P<sp>" + SP + r"?)(?P<unit>" + _UNIT_ALT + r")"
                   r"(?![\w°/])(?![.,][0-9])")


def scan_units(text: str) -> Iterator[Result]:
    for m in _UNIT.finditer(text):
        unit = UNIT_BY_SYMBOL[m["unit"]]
        spaced = m["sp"] != ""
        if (unit["space"] == "required" and not spaced) or (unit["space"] == "none" and spaced):
            continue
        raw = m["num"]
        if _leading_zero(raw) or _too_long(raw):
            yield _ambiguous(m, text, (UNIT,), "identifier-like number", "UNIT.symbol")
            continue
        name = unit["singular"] if raw == "1" else unit["plural"]
        yield _edit(m, text, f"{_number_words(raw)} {name}", "UNIT.symbol", UNIT, "unambiguous")


_TIMES = re.compile(BEFORE + r"(?P<a>" + INT + r")[ ]?×[ ]?(?P<b>" + INT + r")" + AFTER)


def scan_multiplication(text: str) -> Iterator[Result]:
    for m in _TIMES.finditer(text):
        if _leading_zero(m["a"]) or _leading_zero(m["b"]) or _too_long(m["a"]) or _too_long(m["b"]):
            yield _ambiguous(m, text, (SYM,), "identifier-like number", "SYM.times")
            continue
        spoken = f"{num.cardinal(_int_value(m['a']))} times {num.cardinal(_int_value(m['b']))}"
        yield _edit(m, text, spoken, "SYM.times", SYM, "unambiguous")


# --------------------------------------------------------------------------- single-token numerics (level 5)

_PERCENT = re.compile(BEFORE + r"(?P<num>" + INT + r"(?:\.[0-9]+)?)%(?![\w%])")
_ORDINAL = re.compile(BEFORE + r"(?P<num>" + INT + r")(?P<sfx>st|nd|rd|th)(?![\w]|[-–]\w)")
_DECADE = re.compile(BEFORE + r"(?P<num>[0-9]{3}0)s(?![\w'’]|[-–]\w)")
_DECIMAL = re.compile(BEFORE + r"(?P<int>" + INT + r")\.(?P<frac>[0-9]+)" + AFTER)
_INTEGER = re.compile(BEFORE + r"(?P<num>" + INT + r")" + AFTER)


def scan_percent(text: str) -> Iterator[Result]:
    for m in _PERCENT.finditer(text):
        if _leading_zero(m["num"]) or _too_long(m["num"]):
            yield _ambiguous(m, text, (PCT,), "identifier-like number", "PCT.sign")
            continue
        yield _edit(m, text, f"{_number_words(m['num'])} percent", "PCT.sign", PCT, "unambiguous")


def scan_ordinals(text: str) -> Iterator[Result]:
    for m in _ORDINAL.finditer(text):
        raw = m["num"]
        if _leading_zero(raw) or _too_long(raw) or m["sfx"] != num.ordinal_suffix(_int_value(raw)):
            yield _ambiguous(m, text, (ORD,), "suffix does not match the number", "ORD.suffix")
            continue
        yield _edit(m, text, num.ordinal(_int_value(raw)), "ORD.suffix", ORD, "unambiguous")


def scan_decades(text: str) -> Iterator[Result]:
    for m in _DECADE.finditer(text):
        value = int(m["num"])
        if 1000 <= value <= 2090:
            yield _edit(m, text, num.decade(value), "YEAR.decade", YEAR, "unambiguous")


def _line_prefix_is_empty(text: str, pos: int) -> bool:
    start, _ = _line_bounds(text, pos)
    return text[start:pos].strip().strip("#").strip() == ""


def scan_decimals(text: str) -> Iterator[Result]:
    for m in _DECIMAL.finditer(text):
        whole = m["int"]
        before = _first_cue(prev_tokens(text, m.start()))
        rest = text[m.end():m.end() + 2]
        section = before in SECTION_CUES or (_line_prefix_is_empty(text, m.start()) and len(rest) == 2
                                             and rest[0] == " " and rest[1].isupper())
        if section:
            yield _ambiguous(m, text, (DEC,), "section or version number", "DEC.point")
        elif _leading_zero(whole) or _too_long(whole):
            yield _ambiguous(m, text, (DEC,), "identifier-like number", "DEC.point")
        else:
            yield _edit(m, text, num.decimal(_int_value(whole), m["frac"]), "DEC.point", DEC, "unambiguous")


def _is_address(text: str, end: int) -> bool:
    after = next_tokens(text, end, 4)
    if not after or not _raw(after[0])[:1].isupper():
        return False
    return any(_raw(t).rstrip(".") in STREET_SUFFIXES for t in after)


def scan_integers(text: str) -> Iterator[Result]:
    """Whole numbers: CARD, or YEAR when a cue says so. A four-digit number whose year and cardinal readings differ needs a cue."""
    for m in _INTEGER.finditer(text):
        raw = m["num"]
        if _leading_zero(raw) or _too_long(raw):
            yield _ambiguous(m, text, (CARD,), "identifier-like number", "CARD.integer")
            continue
        value = _int_value(raw)
        before_tokens, after_tokens = prev_tokens(text, m.start()), next_tokens(text, m.end())
        before = _first_cue(before_tokens)
        before_raw = _raw(before_tokens[0]) if before_tokens else ""
        after_raw = _raw(after_tokens[0]) if after_tokens else ""
        if value >= 100 and (before in IDENTIFIER_CUES or _is_address(text, m.end())):
            yield _ambiguous(m, text, (CARD,), "identifier or street number", "CARD.integer")
            continue
        era = after_raw in ERAS or after_raw.rstrip(".") in ERAS or before_raw in ("AD", "A.D.")
        if "," in raw:
            yield _edit(m, text, num.cardinal(value), "CARD.integer", CARD, "unambiguous")
        elif 1000 <= value <= 2099:
            year_cue = era or before in YEAR_CUES_BEFORE or before in MONTH_WORDS
            count_cue = bool(after_tokens) and _is_count_word(after_tokens[0])
            if year_cue and not count_cue:
                # Classed YEAR even where both readings coincide (2005), so the YEAR mode governs every cued year.
                yield _edit(m, text, num.year(value), "YEAR.integer", YEAR, "cue")
            elif num.year(value) == num.cardinal(value):
                yield _edit(m, text, num.cardinal(value), "CARD.integer", CARD, "unambiguous")
            elif count_cue and not year_cue:
                yield _edit(m, text, num.cardinal(value), "CARD.integer", CARD, "cue")
            else:
                reason = "conflicting year and count cues" if year_cue else "four-digit number without a cue"
                yield _ambiguous(m, text, (YEAR, CARD), reason, "YEAR.integer")
        elif era and value <= 9999:
            yield _edit(m, text, num.year(value), "YEAR.integer", YEAR, "cue")
        else:
            yield _edit(m, text, num.cardinal(value), "CARD.integer", CARD, "unambiguous")


# --------------------------------------------------------------------------- titles and Roman numerals (level 6)

_TITLE = re.compile(r"(?<![\w.])(?P<abbr>" + "|".join(sorted(list(TITLES) + list(AMBIGUOUS_TITLES), key=len, reverse=True))
                    + r")\.(?=[ ]+[A-Z])")
_ROMAN_TOKEN = re.compile(r"(?<![\w'’.-])(?P<r>[MDCLXVI]{2,})(?![\w'’])")
_ROMAN_VALID = re.compile(r"M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})")
_ROMAN_VALUES = {"M": 1000, "D": 500, "C": 100, "L": 50, "X": 10, "V": 5, "I": 1}


def scan_titles(text: str) -> Iterator[Result]:
    """``Mr. Smith`` -> ``Mister Smith``. Only before a capitalised name: ``Dr. Then`` may end a sentence."""
    for m in _TITLE.finditer(text):
        abbr = m["abbr"]
        after = next_tokens(text, m.end())
        if not after or cue(after[0]) in ENGLISH_STOPWORDS:
            continue
        if abbr in AMBIGUOUS_TITLES:
            yield _ambiguous(m, text, (TITLE,), f"{abbr}. has more than one reading", "TITLE.abbreviation")
        else:
            yield _edit(m, text, TITLES[abbr], "TITLE.abbreviation", TITLE, "cue")


def roman_value(token: str) -> int:
    total = 0
    for i, ch in enumerate(token):
        value = _ROMAN_VALUES[ch]
        total += -value if i + 1 < len(token) and _ROMAN_VALUES[token[i + 1]] > value else value
    return total


def scan_roman(text: str) -> Iterator[Result]:
    """``Chapter IV`` -> ``Chapter four``; ``Henry VIII`` -> ``Henry the eighth``. A single letter is never a numeral."""
    for m in _ROMAN_TOKEN.finditer(text):
        token = m["r"]
        if not _ROMAN_VALID.fullmatch(token):
            continue
        value = roman_value(token)
        before = prev_tokens(text, m.start(), 2)
        if not before:
            continue
        phrase = " ".join(_raw(t) for t in reversed(before))
        if cue(before[0]) in ROMAN_CUES or phrase in ROMAN_CUE_PHRASES:
            yield _edit(m, text, num.cardinal(value), "ROMAN.numeral", ROMAN, "cue")
        elif _raw(before[0]) in REGNAL_NAMES:
            yield _edit(m, text, f"the {num.ordinal(value)}", "ROMAN.numeral", ROMAN, "cue")


# --------------------------------------------------------------------------- symbols (level 7) and hygiene (level 8)

_AMPERSAND = re.compile(r"(?<=[A-Za-z0-9] )&(?= [A-Za-z0-9])")


def scan_symbols(text: str) -> Iterator[Result]:
    for m in _AMPERSAND.finditer(text):
        yield _edit(m, text, "and", "SYM.ampersand", SYM, "unambiguous")


_HYGIENE_SPOKEN = {**{c: "" for c in HYGIENE_TABLE["delete"]}, **{c: " " for c in HYGIENE_TABLE["space"]},
                   **HYGIENE_TABLE["ligatures"]}
_HYGIENE = re.compile("[" + "".join(re.escape(c) for c in _HYGIENE_SPOKEN) + "]")
_INVISIBLE = set(HYGIENE_TABLE["delete"])


def scan_hygiene(text: str) -> Iterator[Result]:
    """Invisible characters, no-break spaces and ligatures. A line is never emptied (invariant I7)."""
    for m in _HYGIENE.finditer(text):
        char = m.group()
        if char in _INVISIBLE:
            start, end = _line_bounds(text, m.start())
            if all(c in _INVISIBLE or c.isspace() for c in text[start:end]):
                continue
        yield _edit(m, text, _HYGIENE_SPOKEN[char], "HYG.character", HYG, "mechanical")


#: Rule order is the tie-break within a level (after "longest match wins").
RULES: tuple[Rule, ...] = (
    Rule("CUR.amount", STRUCTURED, 1, (CUR,), scan_currency),
    Rule("DATE", STRUCTURED, 1, (DATE,), scan_dates),
    Rule("TIME.RATIO", STRUCTURED, 1, (TIME, RATIO), scan_colon_numbers),
    Rule("UNIT.symbol", STRUCTURED, 1, (UNIT,), scan_units),
    Rule("RANGE.dash", STRUCTURED, 1, (RANGE,), scan_ranges),
    Rule("FRAC", STRUCTURED, 1, (FRAC,), scan_fractions),
    Rule("SYM.times", STRUCTURED, 1, (SYM,), scan_multiplication),
    Rule("PCT.sign", NUMERIC, 1, (PCT,), scan_percent),
    Rule("ORD.suffix", NUMERIC, 1, (ORD,), scan_ordinals),
    Rule("YEAR.decade", NUMERIC, 1, (YEAR,), scan_decades),
    Rule("DEC.point", NUMERIC, 1, (DEC,), scan_decimals),
    Rule("CARD.integer", NUMERIC, 1, (CARD, YEAR), scan_integers),
    Rule("TITLE.abbreviation", WORDS, 1, (TITLE,), scan_titles),
    Rule("ROMAN.numeral", WORDS, 1, (ROMAN,), scan_roman),
    Rule("SYM.ampersand", SYMBOLS, 1, (SYM,), scan_symbols),
    Rule("HYG.character", HYGIENE, 1, (HYG,), scan_hygiene),
)
