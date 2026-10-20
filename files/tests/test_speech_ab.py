"""Plan 01B checkpoint A4: the A/B corpus tool plans honest, blind, bounded pairs. No audio, no network."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dev-tools"))

import speech_ab as ab  # noqa: E402

from tts.speech import classes  # noqa: E402

PLAN = ab.build_plan()


def test_every_audible_class_has_one_short_snippet_and_hygiene_has_none():
    assert set(ab.SNIPPETS) == set(classes.RULE_CLASSES) - {"HYG"}
    assert all(len(text) <= 250 for text in ab.SNIPPETS.values()), "a snippet must stay within the ~25 s budget"
    assert ab.VOICES == {"edge_direct": "en-US-SteffanNeural", "kokoro": "af_heart",
                         "chatterbox": "chatterbox-female-1", "qwen3": "qwen3-aiden"}


def test_each_pair_differs_only_in_its_own_class_and_proves_its_source():
    assert len(PLAN["pairs"]) == 60
    for pair in PLAN["pairs"]:
        assert pair["a_text"] != pair["b_text"] and pair["integrity_proof"]
        assert {e["rule"].split(".")[0] for e in pair["edits"]} == {pair["class"]}
        for edit in pair["edits"]:
            assert pair["source"][edit["source_start"]:edit["source_end"]] == edit["original"]


def test_a_side_is_todays_text_and_b_side_is_the_engine_route_with_one_cell_expanded():
    from tts.speech.pipeline import prepare

    for pair in PLAN["pairs"]:
        today = prepare(pair["source"], None, pair["route"])
        assert pair["a_text"] == (today.spoken_source if today.document is None else today.text)
        cells = dict(((e, c), m) for e, c, m in ab.snapshot_for(pair["route"], pair["class"]).cells)
        expanded = [key for key, mode in cells.items() if mode == "expand"]
        assert expanded == [(pair["engine"], pair["class"])]


def test_clip_names_are_neutral_unique_and_do_not_follow_the_sides():
    names = [name for pair in PLAN["pairs"] for name in pair["clips"].values()]
    assert len(set(names)) == len(names) == 120
    assert all(name.startswith("clip-") and name[5:].isdigit() for name in names)
    b_first = sum(1 for pair in PLAN["pairs"] if pair["clips"]["B"] < pair["clips"]["A"])
    assert 15 < b_first < 45, "the lower clip number must not systematically be one side"
    assert ab.build_plan() == PLAN, "the shuffle is seeded"


def test_changes_to_previously_approved_audio_are_labelled():
    labels = {pair["pair"]: pair["affects_previously_approved"] for pair in PLAN["pairs"]}
    for route in ab.VOICES:
        assert "pronunciation" in labels[f"{route}:TITLE"] and "pacing" in labels[f"{route}:TITLE"]
        assert labels[f"{route}:DEC"] == ["pronunciation"]
        assert labels[f"{route}:CUR"] == ["none"]
    assert labels["chatterbox:RATIO"] == ["pacing", "pronunciation"]
    assert labels["kokoro:RATIO"] == ["none"]


def test_the_review_sheet_never_reveals_which_clip_is_which():
    manifest = {"pairs": [dict(p, mechanical={}) for p in PLAN["pairs"]]}
    sheet = ab.review_sheet(manifest)
    for pair in PLAN["pairs"]:
        assert pair["b_text"] not in sheet
    assert "today" not in sheet.split("Sentences:")[1] and " A " not in sheet and " B " not in sheet


@pytest.mark.parametrize("reference, heard, expected", [
    ("It cost $12.50.", "It cost twelve dollars fifty cents.", 0.0),
    ("It cost $12.50.", "It cost $12.50", 0.0),
    ("one two three four", "one three four", 0.25),
    ("one two", "", 1.0),
])
def test_word_error_rate_compares_spoken_forms(reference, heard, expected):
    assert ab.word_error_rate(reference, heard) == expected
