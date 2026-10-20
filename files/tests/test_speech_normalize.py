"""Plan 01B checkpoint A2: the shared normalizer core (sections 4.3, 4.4, 4.8).

The tracked corpus (``files/tests/golden/speech/corpus/*.jsonl``) holds hand-written expectations with every class set to
``expand``; production modes are decided per engine later (A3-A5) and nothing here is wired into an engine.
Invariants I1-I10 are each proven here, mostly over a seeded random generator, and every rule family and every invariant
check is mutation-tested: switching a class off must change corpus output, and a corrupted result must be rejected.
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import replace
from pathlib import Path

import pytest

from tts import quality_corpus as qc
from tts.speech import classes, integrity, numbers_en as num
from tts.speech.classes import Edit, ProtectedSpan
from tts.speech.normalize import (EXPAND, GLOSSARY_ONLY, NATIVE, RULESET_VERSION, normalize, resolve_modes,
                                  ruleset_fingerprint)
from tts.speech.report import details_line, details_lines, summarize

CORPUS_DIR = Path(__file__).resolve().parent / "golden" / "speech" / "corpus"
CORPUS = [dict(json.loads(line), file=path.stem) for path in sorted(CORPUS_DIR.glob("*.jsonl"))
          for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

#: Pinned so that a data-table or rule change cannot slip in without a RULESET_VERSION bump (and a Changelog line).
FINGERPRINTS = {1: "bc0560aa6c8d8832ae0e8fe7a9a3c9d146209257859abd03e7f6ff39da3a199a"}


# --------------------------------------------------------------------------- corpus

def test_the_corpus_is_complete_and_well_formed():
    assert len(CORPUS) == 160
    assert len({c["id"] for c in CORPUS}) == len(CORPUS)
    files = {c["file"] for c in CORPUS}
    assert files == {"tier1", "tier2", "no_change", "adversarial"}
    for case in CORPUS:
        assert set(case) <= {"id", "input", "expected", "classes", "engines", "note", "ambiguous", "file"}, case["id"]
        assert set(case["classes"]) <= set(classes.RULE_CLASSES), case["id"]
        assert case["engines"] == ["edge", "kokoro", "chatterbox", "qwen3"], case["id"]
    covered = {cls for case in CORPUS for cls in case["classes"]}
    assert covered == set(classes.RULE_CLASSES), "every class needs at least one corpus case"


@pytest.mark.parametrize("case", CORPUS, ids=[c["id"] for c in CORPUS])
def test_corpus_case(case):
    result = normalize(case["input"])
    assert result.spoken == case["expected"]
    assert sorted({e.cls for e in result.edits}) == case["classes"]
    if "ambiguous" in case:
        assert len(result.ambiguities) == case["ambiguous"], [(a.text, a.reason) for a in result.ambiguities]


def test_unchanged_cases_are_byte_identical_and_produce_no_edit():
    for case in CORPUS:
        if not case["classes"]:
            result = normalize(case["input"])
            assert result.spoken == case["input"] and result.edits == (), case["id"]


def test_approved_passages_are_identical_except_the_difficult_short_text():
    """The preview sentence and the sustained/structural evaluation passages have no trigger (no audio can change)."""
    from tts import generate_voice_samples as gvs

    for item in (v for v in vars(qc).values() if isinstance(v, qc.CorpusItem)):
        result = normalize(item.text)
        if item.name == "difficult_short":
            assert {e.original for e in result.edits} == {"Dr.", "7:15", "2.5", "Mr.", "Mrs.", "Prof."}
            assert {a.text for a in result.ambiguities} == {"6:45", "3:1"}
        else:
            assert result.spoken == item.text and not result.ambiguities, item.name
    for text in (gvs.SAMPLE_TEXT, gvs.CHATTERBOX_EVAL_TEXT, gvs.CHATTERBOX_CANDIDATE_TEXT):
        assert normalize(text).spoken == text


# --------------------------------------------------------------------------- verbalizer

@pytest.mark.parametrize("value, words", [
    (0, "zero"), (7, "seven"), (13, "thirteen"), (20, "twenty"), (21, "twenty one"), (100, "one hundred"),
    (101, "one hundred one"), (110, "one hundred ten"), (1000, "one thousand"), (1250, "one thousand two hundred fifty"),
    (1_000_000, "one million"), (1_000_001, "one million one"), (12_000_340, "twelve million three hundred forty"),
    (10 ** 12, "one trillion"), (num.MAX_CARDINAL, "nine hundred ninety nine trillion nine hundred ninety nine billion "
     "nine hundred ninety nine million nine hundred ninety nine thousand nine hundred ninety nine"),
])
def test_cardinal(value, words):
    assert num.cardinal(value) == words


@pytest.mark.parametrize("value, words", [(1, "first"), (2, "second"), (3, "third"), (5, "fifth"), (8, "eighth"),
                                          (9, "ninth"), (12, "twelfth"), (20, "twentieth"), (21, "twenty first"),
                                          (100, "one hundredth"), (1000, "one thousandth")])
def test_ordinal(value, words):
    assert num.ordinal(value) == words


@pytest.mark.parametrize("value, words", [(1066, "ten sixty six"), (1900, "nineteen hundred"), (1905, "nineteen oh five"),
                                          (1999, "nineteen ninety nine"), (2000, "two thousand"),
                                          (2005, "two thousand five"), (2010, "twenty ten"), (2024, "twenty twenty four"),
                                          (2100, "twenty one hundred"), (44, "forty four"), (3000, "three thousand")])
def test_year(value, words):
    assert num.year(value) == words


def test_decade_fraction_time_and_suffix():
    assert num.decade(1990) == "nineteen nineties" and num.decade(1800) == "eighteen hundreds"
    assert num.decade(2000) == "two thousands" and num.decade(2010) == "twenty tens"
    assert num.fraction(1, 2) == "one half" and num.fraction(3, 4) == "three quarters"
    assert num.fraction(5, 8) == "five eighths" and num.fraction(1, 3) == "one third"
    assert num.clock_time(7, 0) == "seven o'clock" and num.clock_time(7, 5) == "seven oh five"
    assert num.clock_time(14, 0) == "fourteen hundred" and num.clock_time(10, 30) == "ten thirty"
    assert [num.ordinal_suffix(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 101, 111, 112)] == \
        ["st", "nd", "rd", "th", "th", "th", "th", "st", "nd", "st", "th", "th"]
    for bad in (lambda: num.cardinal(-1), lambda: num.cardinal(10 ** 15), lambda: num.decade(1995),
                lambda: num.fraction(1, 1), lambda: num.clock_time(0, 5), lambda: num.clock_time(7, 60)):
        with pytest.raises(ValueError):
            bad()


def test_every_verbalizer_output_is_a_valid_spoken_form():
    rng = random.Random(7)
    values = list(range(0, 2200)) + [rng.randrange(0, num.MAX_CARDINAL) for _ in range(2000)]
    for value in values:
        assert integrity.SPOKEN_FORM.fullmatch(num.cardinal(value)), value
        assert integrity.SPOKEN_FORM.fullmatch(num.ordinal(value)), value
    for value in range(0, 10000):
        assert integrity.SPOKEN_FORM.fullmatch(num.year(value)), value


def test_the_verbalizer_agrees_with_num2words_where_installed():
    """Developer cross-check (decision D5): num2words is an oracle only, never a runtime dependency."""
    num2words = pytest.importorskip("num2words").num2words

    def plain(words: str) -> str:
        return " ".join(words.replace(",", " ").replace("-", " ").replace(" and ", " ").split())

    rng = random.Random(11)
    for value in list(range(0, 3000)) + [rng.randrange(0, 10 ** 12) for _ in range(3000)]:
        assert num.cardinal(value) == plain(num2words(value)), value
        assert num.ordinal(value) == plain(num2words(value, to="ordinal")), value
    for value in list(range(1100, 2000)) + list(range(2010, 2100)):
        assert num.year(value) == plain(num2words(value, to="year")), value


# --------------------------------------------------------------------------- invariants I1-I10 over generated text

_WORDS = "the a keeper light harbor was and she said quietly storm door it night of to in".split()
_TRIGGERS = ["1,250", "3.5", "21st", "12.5%", "$12.50", "in 1999", "1990s", "at 7:05", "a 3:1 ratio", "John 3:16",
             "March 5, 2024", "pages 12-15", "1/2 cup", "5 km", "72\N{DEGREE SIGN}F", "Mr. Smith", "Chapter IV",
             "Henry VIII", "Smith & Wesson", "3 \N{MULTIPLICATION SIGN} 4", "https://example.com/7", "a@b.com",
             "C:\\x\\2", "007", "1250 Elm Street", "\N{LATIN SMALL LIGATURE FI}ne", "x\N{SOFT HYPHEN}y",
             "two\N{NO-BREAK SPACE}words", "\N{ZERO WIDTH SPACE}", "St. Paul", "1999", "5-year-old", "9/11", "1:02:33",
             "7 p.m.", "Le chat est sur la table avec 5 amis", "Dr. Then", "2\N{VULGAR FRACTION ONE HALF}"]


def _document(rng: random.Random) -> str:
    lines = []
    if rng.random() < 0.3:
        lines += [f"Title: Book {rng.randint(1, 99)}", f"Author: A {rng.randint(1, 9)}", ""]
    for _ in range(rng.randint(1, 12)):
        roll = rng.random()
        if roll < 0.15:
            lines.append("#" * rng.randint(1, 3) + " Chapter " + rng.choice(["5", "IV", "One", "2024"]))
        elif roll < 0.25:
            lines.append("")
        else:
            parts = [rng.choice(_TRIGGERS) if rng.random() < 0.35 else rng.choice(_WORDS)
                     for _ in range(rng.randint(1, 14))]
            lines.append(" ".join(parts) + rng.choice([".", "!", "?", ",", "", "..."]))
    return "\n".join(lines)


DOCUMENTS = [_document(random.Random(seed)) for seed in range(300)]


def test_i1_identity_on_trigger_free_text():
    rng = random.Random(3)
    alphabet = "abcdefghij klmnop qrstuvwxyz ABCDEFG .,;!?'\"()-\n"
    for _ in range(300):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 400)))
        result = normalize(text)
        assert result.spoken == text and result.edits == ()


def test_i2_to_i5_i7_i8_hold_on_generated_documents():
    for text in DOCUMENTS:
        result = normalize(text)  # normalize itself runs integrity.verify; restated here explicitly
        integrity.verify(result.source, result.spoken, result.edits, result.protected)
        assert integrity.reconstruct_source(result.spoken, result.edits) == text
        for edit in result.edits:
            assert edit.cls == "HYG" or integrity.SPOKEN_FORM.fullmatch(edit.spoken)
            assert edit.rule_version == 1 and edit.confidence in {"unambiguous", "cue", "mechanical"}
        for span in result.protected:
            assert result.spoken[result.source_to_spoken(span.start):result.source_to_spoken(span.end)] == \
                text[span.start:span.end]


def test_i6_idempotence_spoken_text_changes_no_further():
    for text in DOCUMENTS + [c["input"] for c in CORPUS]:
        spoken = normalize(text).spoken
        again = normalize(spoken)
        assert again.spoken == spoken and again.edits == (), text


def test_i7_i8_structure_markers_and_lines_survive():
    for text in DOCUMENTS:
        spoken = normalize(text).spoken
        assert spoken.count("\n") == text.count("\n")
        for before, after in zip(text.split("\n"), spoken.split("\n")):
            if before.lstrip().startswith(("Title:", "Author:")):
                assert after == before
            if before.lstrip().startswith("#"):
                assert after[:len(before) - len(before.lstrip("# \t"))] == before[:len(before) - len(before.lstrip("# \t"))]
            assert bool(before.strip()) <= bool(after.strip())


def test_i9_determinism_same_input_same_output_and_hash():
    for text in DOCUMENTS[:60]:
        first, second = normalize(text), normalize(text)
        assert first == second
        assert integrity.text_hash(first.spoken) == integrity.text_hash(second.spoken)


def test_i10_a_one_megabyte_book_is_prepared_in_bounded_time():
    rng = random.Random(5)
    book = "\n".join(_document(rng) for _ in range(800))
    while len(book) < 1_000_000:
        book += "\n" + book[:200_000]
    started = time.perf_counter()
    result = normalize(book)
    elapsed = time.perf_counter() - started
    assert result.edits and elapsed < 15.0, f"{elapsed:.1f} s for {len(book)} characters"


# --------------------------------------------------------------------------- mappings

def test_offset_maps_are_monotone_and_exact_outside_edits():
    for text in DOCUMENTS[:80]:
        result = normalize(text)
        forward = [result.source_to_spoken(i) for i in range(len(text) + 1)]
        assert forward == sorted(forward) and forward[-1] == len(result.spoken)
        back = [result.spoken_to_source(i) for i in range(len(result.spoken) + 1)]
        assert back == sorted(back) and back[-1] == len(text)
        ends = [result.spoken_to_source(i, end=True) for i in range(len(result.spoken) + 1)]
        assert ends == sorted(ends)
        edited = {i for e in result.edits for i in range(e.source_start, e.source_end)}
        for i in range(len(text)):
            if i not in edited:
                assert result.spoken[result.source_to_spoken(i)] == text[i]
                assert result.spoken_to_source(result.source_to_spoken(i)) == i


def test_each_edit_maps_to_its_spoken_span_and_back():
    result = normalize("At 7:05 she paid $12.50 for 1,250 pages.")
    for index, edit in enumerate(result.edits):
        start, end = result.spoken_span(index)
        assert result.spoken[start:end] == edit.spoken
        assert result.spoken_to_source(start) == edit.source_start
        assert result.spoken_to_source(end, end=True) == edit.source_end
        assert result.source_to_spoken(edit.source_start) == start
        assert result.source_to_spoken(edit.source_end) == end


# --------------------------------------------------------------------------- modes

def test_resolve_modes_defaults_and_validation():
    assert resolve_modes(None) == {cls: EXPAND for cls in classes.RULE_CLASSES}
    assert resolve_modes({"CARD": NATIVE})["CARD"] == NATIVE
    with pytest.raises(ValueError):
        resolve_modes({"NOPE": EXPAND})
    with pytest.raises(ValueError):
        resolve_modes({"CARD": "maybe"})


def test_a_withheld_class_leaves_its_whole_token_for_the_engine():
    text = "Run 5 km on March 5, 2024 at 7:05 in 1999."
    all_native = normalize(text, modes={cls: NATIVE for cls in classes.RULE_CLASSES})
    assert all_native.spoken == text and all_native.edits == () and all_native.withheld
    unit_native = normalize(text, modes={"UNIT": NATIVE})
    assert "5 km" in unit_native.spoken, "a native UNIT must not be half-expanded by CARD"
    date_native = normalize(text, modes={"DATE": GLOSSARY_ONLY})
    assert "March 5, 2024" in date_native.spoken and "seven oh five" in date_native.spoken


@pytest.mark.parametrize("cls", classes.RULE_CLASSES)
def test_mutation_switching_off_any_class_changes_corpus_output(cls):
    """Every rule family is load-bearing for the corpus: disabling it must be detected."""
    changed = [c["id"] for c in CORPUS if cls in c["classes"]
               and normalize(c["input"], modes={cls: NATIVE}).spoken != c["expected"]]
    assert changed, f"no corpus case notices {cls} switched off"


# --------------------------------------------------------------------------- integrity checker mutation tests

def _valid():
    return normalize("Title: Book 5\n# Chapter 5\nIt cost $5 at https://x.com/9 today.")


@pytest.mark.parametrize("corrupt, code", [
    (lambda r: (r.edits[1], r.edits[0]) + r.edits[2:], "I3"),
    (lambda r: (replace(r.edits[0], original="six"),) + r.edits[1:], "I3"),
    (lambda r: (replace(r.edits[0], source_end=r.edits[0].source_end + 50),) + r.edits[1:], "I3"),
    (lambda r: (replace(r.edits[0], spoken="five, dollars"),) + r.edits[1:], "I5"),
    (lambda r: (replace(r.edits[0], spoken="5"),) + r.edits[1:], "I5"),
    (lambda r: (replace(r.edits[0], spoken=""),) + r.edits[1:], "I5"),
    (lambda r: (replace(r.edits[0], spoken="one\ntwo"),) + r.edits[1:], "I8"),
])
def test_mutation_the_checker_rejects_corrupted_edits(corrupt, code):
    result = _valid()
    edits = corrupt(result)
    with pytest.raises(integrity.IntegrityError, match=code):
        integrity.verify(result.source, integrity.apply_edits(result.source, sorted(edits, key=lambda e: e.source_start))
                         if code != "I3" else result.spoken, edits, result.protected)


def test_mutation_the_checker_rejects_protected_marker_and_emptied_line_damage():
    source = "Title: Book 5\n# Chapter 5\nIt is \N{ZERO WIDTH SPACE}.\nGo https://x.com/9 now."
    url = source.index("https")
    into_url = Edit(url + 14, url + 15, "9", "nine", "T", 1, "CARD", "unambiguous")
    with pytest.raises(integrity.IntegrityError, match="I4"):
        integrity.verify(source, integrity.apply_edits(source, [into_url]), [into_url],
                         [ProtectedSpan(url, url + 15, "url")])
    marker = Edit(14, 15, "#", "hash", "T", 1, "SYM", "unambiguous")
    with pytest.raises(integrity.IntegrityError, match="I8"):
        integrity.verify(source, integrity.apply_edits(source, [marker]), [marker], [])
    line = "only\N{ZERO WIDTH SPACE}"
    wipe = [Edit(0, 4, "only", "", "T", 1, "HYG", "mechanical"), Edit(4, 5, line[4], "", "T", 1, "HYG", "mechanical")]
    with pytest.raises(integrity.IntegrityError, match="I7"):
        integrity.verify(line, "", wipe, [])
    good = _valid()
    with pytest.raises(integrity.IntegrityError, match="I2"):
        integrity.verify(good.source, good.spoken + " ", good.edits, good.protected)


def test_reconstruction_detects_a_spoken_text_that_does_not_match_its_edits():
    result = _valid()
    with pytest.raises(integrity.IntegrityError):
        integrity.reconstruct_source(result.spoken.replace("five", "nine"), result.edits)


# --------------------------------------------------------------------------- ruleset version, hashes, report

def test_ruleset_fingerprint_is_pinned_to_the_ruleset_version():
    assert RULESET_VERSION in FINGERPRINTS, "RULESET_VERSION bumped: add its fingerprint and a Changelog line"
    assert ruleset_fingerprint() == FINGERPRINTS[RULESET_VERSION], (
        "a rule or data table changed: bump RULESET_VERSION and record the change in the Changelog")


def test_content_hash_is_canonical():
    assert integrity.content_hash({"b": 1, "a": [1, "x"]}) == integrity.content_hash({"a": [1, "x"], "b": 1})
    assert integrity.content_hash({"a": 1}) != integrity.content_hash({"a": 2})
    assert len(integrity.text_hash("")) == 64


def test_report_lines():
    result = normalize("It cost $5 in 1999, or 1999 was it? Pages 3-4.")
    summary = summarize(result)
    assert details_line(summary) == "Speech preparation: 3 edits, 1 ambiguous left unchanged"
    assert dict(summary.edits_by_class) == {"CUR": 1, "YEAR": 1, "RANGE": 1}
    lines = details_lines(result)
    assert lines[0] == details_line(summary) and any("'1999' unchanged" in line for line in lines)
    assert details_line(summarize(normalize("one"))) == "Speech preparation: 0 edits, 0 ambiguous left unchanged"
    withheld = details_lines(normalize("It cost $5.", modes={"CUR": NATIVE}))
    assert "  left to the engine: CUR 1" in withheld


def test_every_rule_is_registered_with_a_known_class_and_level():
    assert len({r.rule_id for r in classes.RULES}) == len(classes.RULES)
    for rule in classes.RULES:
        assert set(rule.classes) <= set(classes.RULE_CLASSES) and rule.level in range(4, 9) and rule.version == 1
    assert set(classes.TIERS) == set(classes.RULE_CLASSES)
    assert {cls for cls, tier in classes.TIERS.items() if tier == 1} == {"HYG", "CARD", "DEC", "ORD", "PCT", "CUR", "YEAR"}


def test_data_tables_are_well_formed():
    units = classes.UNITS
    assert len(units) >= 35 and len({u["symbol"] for u in units}) == len(units)
    for unit in units:
        assert unit["space"] in {"required", "optional", "none"}
        assert integrity.SPOKEN_FORM.fullmatch(unit["singular"]) and integrity.SPOKEN_FORM.fullmatch(unit["plural"])
    assert {"in", "s", "h"}.isdisjoint({u["symbol"] for u in units})
    for spoken in list(classes.TITLES.values()) + list(classes.AMPM.values()):
        assert integrity.SPOKEN_FORM.fullmatch(spoken)
    hygiene = classes.HYGIENE_TABLE
    assert "\N{ZERO WIDTH JOINER}" not in hygiene["delete"] and "\N{ZERO WIDTH NON-JOINER}" not in hygiene["delete"]
    assert sorted(classes.MONTHS.values()) == list(range(1, 13))
