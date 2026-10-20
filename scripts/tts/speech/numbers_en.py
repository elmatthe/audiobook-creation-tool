"""US-English number verbalizer for speech preparation (Plan 01B section 4.3, decision D5).

The spoken style is fixed: no "and" inside whole numbers (``one hundred one``), no hyphens (``twenty one``), no commas,
years in pairs (``nineteen oh five``, ``two thousand five``, ``twenty twenty four``), ``oh`` for a zero in minutes and
years, ``o'clock`` on the hour. Every function returns only letters, apostrophes and single spaces, because engines turn
commas, hyphens and colons into pauses or chunk splits (invariant I5).

Pure functions, standard library only. ``num2words`` is used by a developer test as an oracle, never here.
"""

from __future__ import annotations

ONES = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
        "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen")
TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
SCALES = ("", "thousand", "million", "billion", "trillion")

#: Largest cardinal verbalized; longer digit strings are identifiers more often than quantities.
MAX_CARDINAL = 10 ** 15 - 1

_ORDINAL_IRREGULAR = {"one": "first", "two": "second", "three": "third", "five": "fifth", "eight": "eighth",
                      "nine": "ninth", "twelve": "twelfth"}


def _below_thousand(n: int) -> list[str]:
    words: list[str] = []
    hundreds, rest = divmod(n, 100)
    if hundreds:
        words += [ONES[hundreds], "hundred"]
    if rest >= 20:
        tens, ones = divmod(rest, 10)
        words.append(TENS[tens])
        if ones:
            words.append(ONES[ones])
    elif rest or not words:
        words.append(ONES[rest])
    return words


def cardinal(n: int) -> str:
    """``1250`` -> ``one thousand two hundred fifty``."""
    if not 0 <= n <= MAX_CARDINAL:
        raise ValueError(f"cardinal out of range: {n}")
    if n == 0:
        return "zero"
    groups: list[str] = []
    scale = 0
    while n:
        n, group = divmod(n, 1000)
        if group:
            words = _below_thousand(group)
            if SCALES[scale]:
                words.append(SCALES[scale])
            groups.insert(0, " ".join(words))
        scale += 1
    return " ".join(groups)


def ordinal_word(word: str) -> str:
    """The ordinal of one number word: ``twenty`` -> ``twentieth``, ``one`` -> ``first``."""
    if word in _ORDINAL_IRREGULAR:
        return _ORDINAL_IRREGULAR[word]
    if word.endswith("y"):
        return word[:-1] + "ieth"
    return word + "th"


def ordinal(n: int) -> str:
    """``21`` -> ``twenty first``."""
    words = cardinal(n).split(" ")
    words[-1] = ordinal_word(words[-1])
    return " ".join(words)


def ordinal_suffix(n: int) -> str:
    """The written suffix that belongs to ``n`` (``st``, ``nd``, ``rd`` or ``th``)."""
    if 10 <= n % 100 <= 20:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def digits(text: str) -> str:
    """Digit by digit: ``07`` -> ``zero seven``."""
    return " ".join(ONES[int(c)] for c in text)


def decimal(integer_part: int, fraction_digits: str) -> str:
    """``3`` and ``"5"`` -> ``three point five``."""
    return f"{cardinal(integer_part)} point {digits(fraction_digits)}"


def year(n: int) -> str:
    """Years read in pairs: ``1905`` -> ``nineteen oh five``; ``2005`` -> ``two thousand five``; ``2024`` -> ``twenty twenty four``.

    Below 1000 a year is read as a cardinal (``44`` -> ``forty four``, as in "44 BC").
    """
    if not 0 <= n <= 9999:
        raise ValueError(f"year out of range: {n}")
    if n < 1000 or 2000 <= n <= 2009 or n % 1000 == 0:
        return cardinal(n)
    high, low = divmod(n, 100)
    if low == 0:
        return f"{cardinal(high)} hundred"
    if low < 10:
        return f"{cardinal(high)} oh {ONES[low]}"
    return f"{cardinal(high)} {cardinal(low)}"


def plural_word(word: str) -> str:
    """Plural of a number word: ``ninety`` -> ``nineties``, ``six`` -> ``sixes``, ``hundred`` -> ``hundreds``."""
    if word.endswith("y"):
        return word[:-1] + "ies"
    if word.endswith(("s", "x")):
        return word + "es"
    return word + "s"


def decade(n: int) -> str:
    """``1990`` (from ``1990s``) -> ``nineteen nineties``; ``2000`` -> ``two thousands``."""
    if n % 10:
        raise ValueError(f"not a decade: {n}")
    words = year(n).split(" ")
    words[-1] = plural_word(words[-1])
    return " ".join(words)


_FRACTION_NAMES = {2: ("half", "halves"), 4: ("quarter", "quarters")}


def fraction(numerator: int, denominator: int) -> str:
    """``1/2`` -> ``one half``; ``3/4`` -> ``three quarters``; ``5/8`` -> ``five eighths``."""
    if denominator < 2:
        raise ValueError(f"not a fraction denominator: {denominator}")
    singular, plural = _FRACTION_NAMES.get(denominator, (None, None))
    if singular is None:
        singular = ordinal(denominator)
        plural = singular + "s"
    return f"{cardinal(numerator)} {singular if numerator == 1 else plural}"


def clock_time(hour: int, minute: int) -> str:
    """``7:00`` -> ``seven o'clock``; ``7:05`` -> ``seven oh five``; ``14:00`` -> ``fourteen hundred``."""
    if not (1 <= hour <= 24 and 0 <= minute <= 59):
        raise ValueError(f"not a clock time: {hour}:{minute}")
    if minute == 0:
        return f"{cardinal(hour)} o'clock" if hour <= 12 else f"{cardinal(hour)} hundred"
    if minute < 10:
        return f"{cardinal(hour)} oh {ONES[minute]}"
    return f"{cardinal(hour)} {cardinal(minute)}"
