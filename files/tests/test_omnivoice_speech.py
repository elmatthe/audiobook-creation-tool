"""v0.8.0 Phase 2 -- OmniVoice in ACT's EXISTING speech preparation (plan section 4), held to the tracked golden corpus.

OmniVoice gets its own route, engine scope and mode-table row -- provisionally ``expand`` for all 16 classes -- and
nothing else: no rule, data table, unit, lexicon or historical verdict changes. Every one of the 160 golden cases is
run through the OmniVoice route with the production ``v1`` snapshot and must come out exactly as the corpus expects;
``off`` must leave the decoded text to the structure stage alone; glossary scope and user mode overrides must reach
OmniVoice and only OmniVoice; the four older engines must read exactly as before.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tts.speech import classes, profiles
from tts.speech.document import HEADING_PARAGRAPH_STRUCTURE
from tts.speech.glossary import ENGINE_IDS
from tts.speech.integrity import IntegrityError
from tts.speech.pipeline import OFF, SETTING_V1, build_snapshot, prepare

CORPUS_DIR = Path(__file__).resolve().parent / "golden" / "speech" / "corpus"
CORPUS = [dict(json.loads(line), file=path.stem) for path in sorted(CORPUS_DIR.glob("*.jsonl"))
          for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
ROUTE = "omnivoice"


@pytest.fixture(scope="module")
def production(tmp_path_factory):
    snapshot = build_snapshot(SETTING_V1, user_dir=tmp_path_factory.mktemp("no-user-files"))
    assert snapshot.enabled and not snapshot.notes
    return snapshot


def user_dir(tmp_path: Path, *, glossary=None, modes=None) -> Path:
    folder = tmp_path / "user"
    folder.mkdir(exist_ok=True)
    if glossary is not None:
        (folder / "glossary.user.json").write_text(json.dumps({"version": 1, "entries": glossary}), encoding="utf-8")
    if modes is not None:
        (folder / "modes.user.json").write_text(json.dumps({"version": 1, "modes": modes}), encoding="utf-8")
    return folder


# --------------------------------------------------------------------------- #
# Registration in the existing system
# --------------------------------------------------------------------------- #
def test_omnivoice_is_a_fifth_engine_with_its_own_route_and_a_complete_all_expand_row():
    assert ENGINE_IDS[-1] == ROUTE and ENGINE_IDS[:4] == ("edge", "kokoro", "chatterbox", "qwen3")
    assert profiles.ROUTES[-1] == ROUTE
    profile = profiles.PROFILES[ROUTE]
    assert (profile.engine, profile.structure, profile.phoneme_markup) == (ROUTE, HEADING_PARAGRAPH_STRUCTURE, False)
    assert profile.avoid_punctuation == profiles.PROFILES["qwen3"].avoid_punctuation
    table = profiles.load_mode_table()
    assert table[ROUTE] == {cls: "expand" for cls in classes.RULE_CLASSES} and len(table[ROUTE]) == 16


def test_the_production_default_is_v1_and_omnivoice_has_no_exception(production):
    from shared import config

    assert config.DEFAULT_SPEECH_PREP == "v1"
    assert production.modes_for(ROUTE) == {cls: "expand" for cls in classes.RULE_CLASSES}
    assert not [cell for cell in production.exceptions() if cell[0] == ROUTE]
    assert len(production.cells) == len(ENGINE_IDS) * len(classes.RULE_CLASSES) == 80


# --------------------------------------------------------------------------- #
# The golden corpus, all 16 classes, through the OmniVoice route
# --------------------------------------------------------------------------- #
def test_the_corpus_reaches_every_class():
    assert {cls for case in CORPUS for cls in case["classes"]} == set(classes.RULE_CLASSES)
    assert len(CORPUS) == 160


@pytest.mark.parametrize("case", CORPUS, ids=[c["id"] for c in CORPUS])
def test_every_golden_case_reads_exactly_as_the_corpus_expects(case, production):
    prepared = prepare(case["input"], production, ROUTE)
    assert prepared.notes == (), "no integrity fallback"
    assert prepared.normalized.spoken == case["expected"]
    assert sorted({e.cls for e in prepared.normalized.edits}) == case["classes"]
    if "ambiguous" in case:
        assert len(prepared.normalized.ambiguities) == case["ambiguous"]


@pytest.mark.parametrize("case", [c for c in CORPUS if c["classes"]], ids=lambda c: c["id"])
def test_off_never_rewrites_a_golden_case(case):
    prepared = prepare(case["input"], OFF, ROUTE)
    assert prepared.normalized.spoken == case["input"] and prepared.normalized.edits == () and not prepared.enabled
    assert prepare(case["input"], None, ROUTE).normalized.spoken == case["input"]


def test_hygiene_is_a_text_change_that_can_be_shown(production):
    hyg = [c for c in CORPUS if "HYG" in c["classes"]]
    assert hyg
    for case in hyg:
        prepared = prepare(case["input"], production, ROUTE)
        assert prepared.normalized.spoken == case["expected"] != case["input"]
        assert any(e.cls == "HYG" for e in prepared.normalized.edits)


def test_protected_and_ambiguous_tokens_are_left_for_the_engine(production):
    text = ("Visit https://example.com/5 or write to name99@example.com; open C:\\Books\\2024 now. 1999 was odd, "
            "John 3:16 too, 03/04/2024, 24/7 help, Agent 007, R2-D2, Version 1.2.3 and 1250 Elm Street.")
    prepared = prepare(text, production, ROUTE)
    for token in ("https://example.com/5", "name99@example.com", "C:\\Books\\2024", "1999 was", "3:16", "03/04/2024",
                  "24/7", "007", "R2-D2", "1.2.3"):
        assert token in prepared.text, token


def test_headings_metadata_and_a_byte_order_mark_take_the_qwen3_structure(production, tmp_path):
    from tts.speech.document import read_source_text

    source = tmp_path / "book.txt"
    source.write_bytes("Title: The Book\nAuthor: Someone\n# Chapter 5\n\nMr. Yates paid $5.".encode("utf-8-sig"))
    raw = read_source_text(source)
    assert not raw.startswith("\ufeff")
    assert prepare(raw, production, ROUTE).text == "Chapter five\n\n\nMister Yates paid five dollars."
    assert prepare(raw, OFF, ROUTE).text == "Chapter 5\n\n\nMr. Yates paid $5."
    assert prepare(raw, production, ROUTE).text == prepare(raw, production, "qwen3").text


def test_the_four_older_engines_read_exactly_as_before(production):
    """The OmniVoice row adds cells; it moves none. Kokoro keeps its currency exception, Edge its three."""
    text = "Mr. Smith paid $5 for 1/2 cup & a 3:1 ratio in 1999."
    assert prepare(text, production, "kokoro").text == "Mister Smith paid $5 for one half cup and a three to one ratio in nineteen ninety nine."
    assert prepare(text, production, "edge_folder").text == "Mister Smith paid $5 for 1/2 cup & a three to one ratio in nineteen ninety nine."
    expanded = "Mister Smith paid five dollars for one half cup and a three to one ratio in nineteen ninety nine."
    assert prepare(text, production, "qwen3").text == prepare(text, production, "chatterbox").text == expanded
    assert prepare(text, production, ROUTE).text == expanded


# --------------------------------------------------------------------------- #
# Glossary scope and user mode overrides
# --------------------------------------------------------------------------- #
def entry(id_, written, spoken, engines):
    return {"id": id_, "written": written, "spoken": spoken, "engines": engines}


def test_an_omnivoice_scoped_glossary_entry_reaches_omnivoice_alone(tmp_path):
    folder = user_dir(tmp_path, glossary=[entry("ov", "Szeth", "Seth", ["omnivoice"]),
                                          entry("qw", "Roshar", "Row shar", ["qwen3"]),
                                          entry("all", "Shinovar", "Shin oh var", ["*"])])
    snapshot = build_snapshot(SETTING_V1, user_dir=folder)
    assert not snapshot.notes
    text = "Szeth of Shinovar crossed Roshar."
    assert prepare(text, snapshot, ROUTE).text == "Seth of Shin oh var crossed Roshar."
    assert prepare(text, snapshot, "qwen3").text == "Szeth of Shin oh var crossed Row shar."


def test_a_user_mode_override_for_omnivoice_changes_omnivoice_only_and_native_suppresses_the_glossary(tmp_path):
    folder = user_dir(tmp_path, modes={ROUTE: {"CUR": "native", "YEAR": "glossary_only"}},
                      glossary=[entry("five", "$5", "five bucks", ["omnivoice"]),
                                entry("year", "1905", "nineteen oh five", ["omnivoice"])])
    snapshot = build_snapshot(SETTING_V1, user_dir=folder)
    assert not snapshot.notes and snapshot.modes_for(ROUTE)["CUR"] == "native"
    assert snapshot.modes_for("qwen3")["CUR"] == "expand"
    text = "It cost $5 in 1905."
    assert prepare(text, snapshot, ROUTE).text == "It cost $5 in nineteen oh five."
    assert prepare(text, snapshot, "qwen3").text == "It cost five dollars in nineteen oh five."


def test_a_user_override_naming_an_unknown_engine_is_ignored_with_a_note(tmp_path):
    snapshot = build_snapshot(SETTING_V1, user_dir=user_dir(tmp_path, modes={"omni-voice": {"CUR": "native"}}))
    assert any("unknown engine 'omni-voice'" in note for note in snapshot.notes)
    assert snapshot.modes_for(ROUTE)["CUR"] == "expand"


# --------------------------------------------------------------------------- #
# The run snapshot is frozen; a broken proof falls back to the unchanged text
# --------------------------------------------------------------------------- #
def test_editing_the_glossary_after_the_run_started_changes_nothing_in_that_run(tmp_path):
    folder = user_dir(tmp_path, glossary=[entry("ov", "Szeth", "Seth", ["omnivoice"])])
    frozen = build_snapshot(SETTING_V1, user_dir=folder)
    user_dir(tmp_path, glossary=[entry("ov", "Szeth", "Zeth", ["omnivoice"])])
    assert prepare("Szeth.", frozen, ROUTE).text == "Seth."
    assert prepare("Szeth.", build_snapshot(SETTING_V1, user_dir=folder), ROUTE).text == "Zeth."


def test_an_integrity_failure_speaks_the_unchanged_text_and_says_so(monkeypatch, production):
    from tts.speech import pipeline

    def broken(*args, **kwargs):
        raise IntegrityError("simulated")

    monkeypatch.setattr(pipeline, "normalize", broken)
    prepared = prepare("It cost $5.", production, ROUTE)
    assert prepared.text == "It cost $5." and any("integrity check: simulated" in n for n in prepared.notes)
    assert prepared.details()[0].startswith("Speech preparation skipped for this file")


def test_the_omnivoice_engine_module_holds_no_normalization_rules():
    """Rule code lives only in tts/speech: the engine imports ``prepare`` and the route name, nothing else of it."""
    import ast

    from tts import omnivoice_synth, omnivoice_worker

    for module in (omnivoice_synth, omnivoice_worker):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        imported = {(n.module, a.name) for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module
                    and n.module.startswith("tts.speech") for a in n.names}
        assert imported <= {("tts.speech.pipeline", "prepare"), ("tts.speech.document", "read_source_text"),
                            ("tts.speech.profiles", "OMNIVOICE")}, (module.__name__, imported)
