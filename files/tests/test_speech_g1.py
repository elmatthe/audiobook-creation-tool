"""Plan 01B checkpoint A5: the production mode table is exactly the owner's G1 verdicts, and every route applies it.

``files/tests/golden/speech/g1-verdicts.json`` is the tracked record of the 60 listening verdicts, decoded through the private
A4 key (A/B were listening slots, never preparation sides). Rule: a cell expands unless the owner preferred the engine's
own reading; a Same verdict expands (Plan 01B 7.2, convergence decision D6) because every pair passed its mechanical checks.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from shared import config as shared_config
from tts import quality_corpus as qc
from tts import qwen3_synth as qs
from tts.speech import classes, profiles
from tts.speech.glossary import ENGINE_IDS
from tts.speech.pipeline import OFF, SETTING_V1, build_snapshot, prepare

RECORD = json.loads((Path(__file__).resolve().parent / "golden" / "speech" / "g1-verdicts.json").read_text(encoding="utf-8"))
VERDICTS = RECORD["verdicts"]
EXCEPTIONS = {("edge", "CUR"), ("edge", "FRAC"), ("edge", "SYM"), ("kokoro", "CUR")}

#: One A4 snippet per class (the sentences the owner judged).
SNIPPETS = {
    "CARD": "The ledger listed 1,250 pages, 12 chapters and 1,000,000 words.",
    "CUR": "The ticket cost $12.50, and the meal was $5.",
    "DATE": "The letter was dated March 5, 2024.",
    "DEC": "The beam's rotation had slowed by 2.5 degrees per second.",
    "FRAC": "Add 1/2 cup of flour.",
    "ORD": "She finished 1st and he came 2nd.",
    "PCT": "Turnout rose 12.5% this year.",
    "RANGE": "Read pages 12-15 tonight.",
    "RATIO": "They won 3:1 at home.",
    "ROMAN": "Chapter IV opens in the court of Henry VIII.",
    "SYM": "Smith & Wesson made the lock.",
    "TIME": "The ferry would not arrive before 7:15.",
    "TITLE": "Dr. Elena Marsh checked the logbook.",
    "UNIT": "They hiked 5 km at 72°F.",
    "YEAR": "Built in 1905, restored by 1999.",
}


@pytest.fixture(scope="module")
def production(tmp_path_factory):
    snapshot = build_snapshot(SETTING_V1, user_dir=tmp_path_factory.mktemp("no-user-files"))
    assert snapshot.enabled and not snapshot.notes
    return snapshot


def test_the_record_holds_the_owners_sixty_verdicts():
    assert RECORD["counts"] == {"A": 11, "B": 18, "Same": 31, "Neither": 0}
    assert Counter(v["verdict"] for v in VERDICTS) == {"A": 11, "B": 18, "Same": 31}
    assert [v["number"] for v in VERDICTS] == list(range(1, 61))
    assert len({(v["engine"], v["class"]) for v in VERDICTS}) == 60
    blocks = {"chatterbox": range(1, 16), "kokoro": range(16, 31), "qwen3": range(31, 46), "edge": range(46, 61)}
    for engine, numbers in blocks.items():
        assert [v["number"] for v in VERDICTS if v["engine"] == engine] == list(numbers)
    assert all(v["mechanical_pass"] for v in VERDICTS)
    for v in VERDICTS:
        assert (v["prefers"] == "same") == (v["verdict"] == "Same")


def test_the_bundled_mode_table_is_exactly_the_g1_matrix():
    table = profiles.load_mode_table()
    expected = {engine: {cls: "expand" for cls in classes.RULE_CLASSES} for engine in ENGINE_IDS}
    for v in VERDICTS:
        expected[v["engine"]][v["class"]] = "native" if v["prefers"] == "native" else "expand"
    assert table == expected
    assert {(e, c) for e, row in table.items() for c, m in row.items() if m != "expand"} == EXCEPTIONS
    assert all(row["HYG"] == "expand" for row in table.values()), "hygiene is mechanical-only and expands everywhere"


def test_every_exception_is_an_explicit_owner_preference_and_is_documented():
    decisions = (Path(__file__).resolve().parents[2] / "md-instructions" / "Decisions.md").read_text(encoding="utf-8")
    for engine, cls in EXCEPTIONS:
        verdict = next(v for v in VERDICTS if (v["engine"], v["class"]) == (engine, cls))
        assert verdict["verdict"] in ("A", "B") and verdict["prefers"] == "native"
        assert f"{engine} {cls} (comparison {verdict['number']:03d}" in decisions


def test_speech_preparation_is_on_by_default_through_the_reviewed_cells(production):
    assert shared_config.DEFAULT_SPEECH_PREP == "v1"
    assert {(e, c) for e, c, m in production.exceptions()} == EXCEPTIONS


@pytest.mark.parametrize("route", profiles.ROUTES)
def test_each_route_changes_exactly_the_approved_classes(route, production):
    engine = profiles.PROFILES[route].engine
    for cls, text in SNIPPETS.items():
        prepared = prepare(text, production, route)
        changed = {e.cls for e in prepared.normalized.edits}
        assert changed == (set() if (engine, cls) in EXCEPTIONS else {cls}), (route, cls, prepared.text)


def test_edge_direct_and_edge_folder_each_apply_the_matrix_through_their_own_entry_points(production, tmp_path, monkeypatch):
    from tts import batch_convert as bc
    from tts.epub2tts_edge import epub2tts_edge as edge

    text = "Title: Book 5\n# Chapter 5\n\nMr. Smith paid $5 for 1/2 cup & a 3:1 ratio in 1999."
    source = tmp_path / "book.txt"
    source.write_text(text, encoding="utf-8")
    contents, title, _author, chapters = edge.get_book(str(source), production)
    assert (title, chapters) == ("Book 5", ["Chapter five"])
    assert contents[0]["paragraphs"] == ["Mister Smith paid $5 for 1/2 cup & a three to one ratio in nineteen ninety nine."]
    sent: list[str] = []
    monkeypatch.setattr(bc, "synthesize_chunk_mp3", lambda chunk, path, voice, rate: sent.append(chunk) or Path(path).write_bytes(b""))
    monkeypatch.setattr(bc, "merge_mp3s", lambda paths, output, bitrate=None: None)
    status = bc.convert_single_pdf(source, tmp_path / "o", "v", "+0%", log=lambda m: None, out_mp3=tmp_path / "o" / "a.mp3",
                                   speech_prep=production)
    assert status[0] == "success"
    assert sent == ["Title: Book 5\n# Chapter five\n\nMister Smith paid $5 for 1/2 cup & a three to one ratio in nineteen ninety nine."]


def test_kokoro_keeps_its_own_currency_reading_and_expands_the_rest(production):
    prepared = prepare("It cost $5 in 1999 and 1/2 cup.", production, "kokoro")
    assert prepared.text == "It cost $5 in nineteen ninety nine and one half cup."


def test_trigger_free_and_approved_passages_are_unchanged_under_production(production):
    from tts import generate_voice_samples as gvs

    for route in profiles.ROUTES:
        for item in (v for v in vars(qc).values() if isinstance(v, qc.CorpusItem) and v.name != "difficult_short"):
            assert not prepare(item.text, production, route).normalized.edits, (route, item.name)
        for text in (gvs.SAMPLE_TEXT, gvs.CHATTERBOX_EVAL_TEXT, gvs.CHATTERBOX_CANDIDATE_TEXT):
            assert not prepare(text, production, route).normalized.edits


def test_protected_spans_and_ambiguous_tokens_survive_production(production):
    text = "Visit https://example.com/5 or C:\\x\\7 now; 1999 was odd, John 3:16 too, and 24/7 help."
    for route in profiles.ROUTES:
        prepared = prepare(text, production, route)
        assert "https://example.com/5" in prepared.text and "C:\\x\\7" in prepared.text
        assert all(t in prepared.text for t in ("1999 was", "3:16", "24/7"))


def test_the_off_path_and_the_qwen3_revisions():
    assert qs.PIPELINE_REVISION == 1, "the A0-characterized pipeline itself is unchanged"
    assert qs.pipeline_revision(None) == qs.pipeline_revision(OFF) == 1
    assert qs.pipeline_revision(build_snapshot(SETTING_V1, user_dir=None)) == qs.SPEECH_PREP_PIPELINE_REVISION == 2
    assert prepare("It cost $5.", None, "qwen3").text == "It cost $5."


def test_the_chatterbox_colon_compatibility_behaviour_is_still_in_place():
    from tts import chatterbox_synth as cb

    assert cb.COLON_PAUSE_MS == 75
    assert cb._structural_colon_punc_norm("It was 6:45 then") == "It was 6:45 then."  # a time keeps its colon
    assert cb.split_at_prose_colon("Note: leave now.") == ["Note:", "leave now."]   # a prose colon still splits
