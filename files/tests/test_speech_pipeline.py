"""Plan 01B checkpoint A3: engine profiles, the mode table, the run-scoped snapshot and the wiring at the five routes.

The acceptance condition: with the setting ``off`` (the default) or ``v1`` with every cell ``native`` and no user files,
every route produces exactly the A0 characterization -- proven by re-running the unmodified A0 collectors with ``v1``
switched on underneath them. The snapshot is taken by value at run start; edits to the user files mid-run, before
Retry Failed, or a corrupt replacement cannot reach the run; a new run reads the files again.
"""

from __future__ import annotations

import dataclasses
import json
import random
import sys
from pathlib import Path

import pytest

from shared import config as shared_config
from shared import job_control
from tts import qwen3_synth as qs
from tts.speech import classes, document, pipeline, profiles
from tts.speech.document import (HEADING_PARAGRAPH_STRUCTURE, LOCAL_ENGINE_STRUCTURE, RAW_STRUCTURE, parse_structure,
                                 structure_segments)
from tts.speech.glossary import ENGINE_IDS
from tts.speech.integrity import IntegrityError
from tts.speech.pipeline import OFF, SETTING_V1, SpeechPrepSnapshot, build_snapshot, prepare

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CORPUS_DIR = Path(__file__).resolve().parent / "golden" / "speech" / "corpus"
CORPUS_INPUTS = [json.loads(line)["input"] for path in sorted(CORPUS_DIR.glob("*.jsonl"))
                 for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
ALL_EXPAND = {"version": 1, "modes": {e: {c: "expand" for c in classes.RULE_CLASSES} for e in ENGINE_IDS}}


def _document(rng: random.Random) -> str:
    pieces = ["Title: Book 5", "Author: A. Writer", "", "# Chapter 5", "## Part IV", "#", "   # Indented 1999",
              "It cost $12.50 at 7:05 in 1999.", "Mr. Smith ran 5 km.", "  Indented line, with 1,250 pages.",
              "Plain prose here.", "", "\t", "Dr. Patel said: leave now.", "https://example.com/5 and 3:1 odds."]
    lines = [rng.choice(pieces) for _ in range(rng.randint(0, 14))]
    joiner = rng.choice(["\n", "\r\n", "\n\n"])
    return joiner.join(lines) + rng.choice(["", "\n", "  "])


DOCUMENTS = [_document(random.Random(seed)) for seed in range(250)] + CORPUS_INPUTS


def write_user(directory: Path, glossary=None, modes=None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    if glossary is not None:
        (directory / pipeline.USER_GLOSSARY_NAME).write_text(
            glossary if isinstance(glossary, str) else json.dumps({"version": 1, "entries": glossary}), encoding="utf-8")
    if modes is not None:
        (directory / pipeline.USER_MODES_NAME).write_text(
            modes if isinstance(modes, str) else json.dumps(modes), encoding="utf-8")
    return directory


def tamar(spoken="tay mar") -> list[dict]:
    return [{"id": "t", "written": "Tamar", "spoken": spoken}]


# --------------------------------------------------------------------------- profiles and the mode table

def test_five_routes_four_engines_and_no_rules_in_profiles():
    assert profiles.ROUTES == ("edge_direct", "edge_folder", "kokoro", "chatterbox", "qwen3")
    assert {p.engine for p in profiles.PROFILES.values()} == set(ENGINE_IDS)
    assert profiles.PROFILES["edge_direct"].structure is None
    assert profiles.PROFILES["edge_folder"].structure == RAW_STRUCTURE
    assert profiles.PROFILES["kokoro"].structure == profiles.PROFILES["chatterbox"].structure == LOCAL_ENGINE_STRUCTURE
    assert profiles.PROFILES["qwen3"].structure == HEADING_PARAGRAPH_STRUCTURE
    assert [r for r, p in profiles.PROFILES.items() if p.phoneme_markup] == ["kokoro"]
    source = Path(profiles.__file__).read_text(encoding="utf-8")
    assert "re.compile" not in source and "finditer" not in source, "profiles select classes; rules live in classes.py"


def test_the_bundled_mode_table_is_all_native_during_rollout():
    table = profiles.load_mode_table()
    assert set(table) == set(ENGINE_IDS)
    assert all(row == {c: "native" for c in classes.RULE_CLASSES} for row in table.values())


@pytest.mark.parametrize("broken", [
    {}, {"version": 2, "modes": {}}, {"version": 1, "modes": {"edge": {}}},
    {"version": 1, "modes": {e: {c: "native" for c in classes.RULE_CLASSES} for e in ("edge", "kokoro", "chatterbox")}},
    {"version": 1, "modes": {e: {**{c: "native" for c in classes.RULE_CLASSES}, "CARD": "loud"} for e in ENGINE_IDS}},
    {"version": 1, "modes": {e: {**{c: "native" for c in classes.RULE_CLASSES}, "NOPE": "native"} for e in ENGINE_IDS}},
])
def test_a_malformed_bundled_table_is_rejected(broken):
    with pytest.raises(ValueError):
        profiles.parse_mode_table(broken)


def test_user_mode_overrides_validate_per_engine():
    cells, notes = profiles.parse_user_modes({"version": 1, "modes": {
        "kokoro": {"CARD": "expand", "YEAR": "glossary_only"}, "piper": {"CARD": "expand"},
        "edge": {"CARD": "maybe"}, "qwen3": {"NOPE": "expand"}}})
    assert cells == (("kokoro", "CARD", "expand"), ("kokoro", "YEAR", "glossary_only"))
    assert len(notes) == 3
    assert profiles.parse_user_modes([])[0] == () and "ignored" in profiles.parse_user_modes([])[1][0]
    effective = dict(((e, c), m) for e, c, m in profiles.effective_cells(profiles.load_mode_table(), cells))
    assert effective[("kokoro", "CARD")] == "expand" and effective[("edge", "CARD")] == "native"
    assert len(effective) == len(ENGINE_IDS) * len(classes.RULE_CLASSES)


# --------------------------------------------------------------------------- snapshot

def test_off_reads_nothing_and_unknown_settings_fall_back_to_off(tmp_path):
    user = write_user(tmp_path / "u", glossary="{broken", modes="{broken")
    assert build_snapshot("off", user_dir=user, mode_table=tmp_path / "missing.json") is OFF
    unknown = build_snapshot("v2", user_dir=user)
    assert not unknown.enabled and "not known" in unknown.notes[0]


def test_v1_reads_validates_and_reports_but_never_raises(tmp_path):
    clean = build_snapshot(SETTING_V1, user_dir=tmp_path / "absent")
    assert clean.enabled and clean.notes == () and clean.glossary == () and clean.user_overrides == ()
    assert len(clean.cells) == 64 and len(clean.exceptions()) == 64
    broken = build_snapshot(SETTING_V1, user_dir=write_user(tmp_path / "b", glossary="{broken", modes="[1, 2]"))
    assert broken.enabled and broken.glossary == () and len(broken.notes) == 2
    unreadable_table = build_snapshot(SETTING_V1, user_dir=None, mode_table=tmp_path / "missing.json")
    assert not unreadable_table.enabled and "mode table could not be read" in unreadable_table.notes[0]


def test_the_snapshot_is_deeply_immutable_and_passes_the_run_freeze(tmp_path):
    snapshot = build_snapshot(SETTING_V1, user_dir=write_user(tmp_path / "u", glossary=tamar(),
                                                              modes={"version": 1, "modes": {"kokoro": {"CARD": "expand"}}}))
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.setting = "off"
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.glossary[0].spoken = "x"
    assert isinstance(snapshot.cells, tuple) and all(isinstance(c, tuple) for c in snapshot.cells)
    assert isinstance(snapshot.glossary[0].engines, tuple)
    frozen = job_control.freeze_options({"speech_prep": snapshot})
    assert frozen["speech_prep"] is snapshot and job_control.is_frozen_options(frozen)


def test_speech_prep_version_is_stable_and_moves_with_every_input(tmp_path):
    first = build_snapshot(SETTING_V1, user_dir=write_user(tmp_path / "a", glossary=tamar()))
    again = build_snapshot(SETTING_V1, user_dir=write_user(tmp_path / "b", glossary=tamar()))
    assert first.speech_prep_version == again.speech_prep_version and len(first.speech_prep_version) == 64
    other_glossary = build_snapshot(SETTING_V1, user_dir=write_user(tmp_path / "c", glossary=tamar("tah mar")))
    other_modes = build_snapshot(SETTING_V1, user_dir=write_user(
        tmp_path / "d", glossary=tamar(), modes={"version": 1, "modes": {"edge": {"CARD": "expand"}}}))
    assert len({first.speech_prep_version, other_glossary.speech_prep_version, other_modes.speech_prep_version}) == 3


def test_edits_after_run_start_never_reach_the_run_and_a_new_run_reads_them(tmp_path):
    user = write_user(tmp_path / "u", glossary=tamar())
    run = build_snapshot(SETTING_V1, user_dir=user)          # run start: taken by value
    text = "Tamar spoke."
    assert prepare(text, run, "kokoro").text == "tay mar spoke."
    write_user(user, glossary=tamar("tah mar"))               # edited mid-run
    assert prepare(text, run, "kokoro").text == "tay mar spoke."
    write_user(user, glossary="{corrupt")                     # replaced by a broken file before Retry Failed
    write_user(user, modes={"version": 1, "modes": {"kokoro": {"CARD": "expand"}}})
    assert prepare(text, run, "kokoro").text == "tay mar spoke.", "a retry re-uses the original snapshot"
    assert prepare("It has 5 parts.", run, "kokoro").text == "It has 5 parts."
    fresh = build_snapshot(SETTING_V1, user_dir=user)         # a NEW run reads the files again
    assert prepare(text, fresh, "kokoro").text == text and "ignored" in fresh.notes[-1]
    assert prepare("It has 5 parts.", fresh, "kokoro").text == "It has five parts."


# --------------------------------------------------------------------------- prepare

@pytest.mark.parametrize("route", profiles.ROUTES)
def test_off_and_v1_native_are_identical_to_the_structure_stage_alone(route, tmp_path):
    native = build_snapshot(SETTING_V1, user_dir=tmp_path / "none")
    options = profiles.PROFILES[route].structure
    for text in DOCUMENTS:
        expected = text if options is None else parse_structure(text, options).text
        for snapshot in (None, OFF, native):
            prepared = prepare(text, snapshot, route)
            assert prepared.text == expected and prepared.spoken_source == text and not prepared.normalized.edits


def test_v1_applies_only_cells_set_to_expand_and_engine_scope(tmp_path):
    user = write_user(tmp_path / "u", glossary=[{"id": "t", "written": "Tamar", "spoken": "tay mar", "engines": ["qwen3"]}],
                      modes={"version": 1, "modes": {"chatterbox": {"CUR": "expand"}}})
    run = build_snapshot(SETTING_V1, user_dir=user)
    text = "Tamar paid $5 in 1999."
    assert prepare(text, run, "chatterbox").text == "Tamar paid five dollars in 1999."
    assert prepare(text, run, "qwen3").text == "tay mar paid $5 in 1999."
    assert prepare(text, run, "kokoro").text == text
    assert prepare(text, run, "edge_folder").text == text and prepare(text, run, "edge_direct").spoken_source == text


def test_kokoro_alone_receives_phoneme_markup(tmp_path):
    entry = [{"id": "a", "written": "Ascended", "spoken": "uh sended", "phonemes": "ɐsˈɛndᵻd"}]
    run = build_snapshot(SETTING_V1, user_dir=write_user(tmp_path / "u", glossary=entry))
    assert prepare("Ascended.", run, "kokoro").text == "[Ascended](/ɐsˈɛndᵻd/)."
    assert prepare("Ascended.", run, "chatterbox").text == "uh sended."


def test_an_integrity_failure_falls_back_to_the_unchanged_text_with_a_note(tmp_path, monkeypatch):
    run = build_snapshot(SETTING_V1, user_dir=write_user(tmp_path / "u", modes={"version": 1, "modes": {"kokoro": {"CARD": "expand"}}}))

    def broken(*args, **kwargs):
        raise IntegrityError("I2: simulated")

    monkeypatch.setattr(pipeline, "normalize", broken)
    prepared = prepare("It has 5 parts.", run, "kokoro")
    assert prepared.text == "It has 5 parts." and "integrity check" in prepared.details()[0]


def test_a_spoken_form_with_the_engines_prosodic_punctuation_is_refused(tmp_path, monkeypatch):
    run = build_snapshot(SETTING_V1, user_dir=write_user(tmp_path / "u", modes={"version": 1, "modes": {"kokoro": {"CARD": "expand"}}}))
    strict = dataclasses.replace(profiles.PROFILES["kokoro"], avoid_punctuation="v")  # "five" contains a v
    monkeypatch.setitem(profiles.PROFILES, "kokoro", strict)
    prepared = prepare("It has 5 parts.", run, "kokoro")
    assert prepared.text == "It has 5 parts." and "prosodic punctuation" in prepared.details()[0]


def test_details_are_silent_when_off_and_informative_when_on(tmp_path):
    assert prepare("It has 5 parts.", None, "kokoro").details() == []
    run = build_snapshot(SETTING_V1, user_dir=write_user(tmp_path / "u", modes={"version": 1, "modes": {"kokoro": {"CARD": "expand"}}}))
    lines = prepare("It has 5 parts; 1999 was odd.", run, "kokoro").details()
    assert lines[0] == "Speech preparation: 1 edit, 1 ambiguous left unchanged"


# --------------------------------------------------------------------------- structure map and Qwen3 spans

@pytest.mark.parametrize("options", [LOCAL_ENGINE_STRUCTURE, HEADING_PARAGRAPH_STRUCTURE, RAW_STRUCTURE])
def test_structure_segments_mirror_parse_structure_exactly(options):
    for text in DOCUMENTS:
        structured = parse_structure(text, options).text
        segments = structure_segments(text, options)
        covered = 0
        previous = (-1, -1)
        for text_start, raw_start, length in segments:
            assert length > 0 and (text_start, raw_start) > previous
            assert structured[text_start:text_start + length] == text[raw_start:raw_start + length]
            covered += sum(1 for c in structured[text_start:text_start + length] if not c.isspace())
            previous = (text_start, raw_start)
        assert covered == sum(1 for c in structured if not c.isspace()), repr(text)


def test_qwen3_chunk_source_spans_map_every_chunk_back_to_its_source(tmp_path):
    run = build_snapshot(SETTING_V1, user_dir=write_user(tmp_path / "u", modes=ALL_EXPAND))
    checked = 0
    for text in DOCUMENTS:
        prepared = prepare(text, run, "qwen3")
        if not prepared.text:
            continue
        chunks = qs.plan_chunks(prepared.text)
        spans = qs.chunk_source_spans(prepared, chunks)
        for chunk, (start, end) in zip(chunks, spans):
            spoken = prepared.normalized.spoken[prepared.normalized.source_to_spoken(start):
                                                prepared.normalized.source_to_spoken(end)]
            # A span may enclose a Title:/Author: line the engine never speaks; compare what is spoken.
            speakable = parse_structure(spoken, HEADING_PARAGRAPH_STRUCTURE).text
            assert "".join(speakable.split()) == "".join(chunk.text.split()), (text, chunk.text)
            checked += 1
    assert checked > 300


def test_the_source_map_resolves_offsets_inside_joining_newlines(tmp_path):
    """Structured text ``Chapter five`` + ``\\n\\n\\n`` + ``Mister Smith.``: the gaps belong to no source character."""
    run = build_snapshot(SETTING_V1, user_dir=write_user(tmp_path / "u", modes=ALL_EXPAND))
    source = "Title: T\n# Chapter 5\n\nMr. Smith.\n"
    prepared = prepare(source, run, "qwen3")
    assert prepared.text == "Chapter five\n\n\nMister Smith."
    source_map = prepared.source_map()
    heading, body = source.index("Chapter"), source.index("Mr.")
    gap = len("Chapter five") + 1                                    # inside the joining newlines
    assert source_map.source_span(gap, gap + 1) == (body, body), "a gap covers no source character"
    assert source_map.source_span(gap, gap + 3) == (body, body + 3), "ending inside 'Mister' covers all of 'Mr.'"
    assert source_map.source_span(0, len("Chapter five")) == (heading, source.index("5") + 1)
    assert source_map.source_span(0, len(prepared.text)) == (heading, source.index(".\n") + 1)
    assert source_map.source_span(len(prepared.text) - 1, len(prepared.text)) == (body + 9, body + 10)


def test_unchanged_documents_keep_identical_qwen3_chunks_and_seeds(tmp_path):
    native = build_snapshot(SETTING_V1, user_dir=tmp_path / "none")
    for text in DOCUMENTS:
        before = qs.prepare_text(text)
        if not before:
            continue
        old_plan = qs.plan_chunks(before)
        for snapshot in (None, native):
            new_plan = qs.plan_chunks(prepare(text, snapshot, "qwen3").text)
            assert new_plan == old_plan
            assert [qs.derive_seed("qwen3-aiden", c) for c in new_plan] == [qs.derive_seed("qwen3-aiden", c) for c in old_plan]


# --------------------------------------------------------------------------- A0 acceptance with v1 underneath

@pytest.fixture(scope="module")
def characterization():
    sys.path.insert(0, str(REPO_ROOT / "files" / "dev-tools"))
    import speech_characterization as sc

    return sc


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_a0_goldens_are_unchanged_with_v1_and_every_cell_native(characterization, monkeypatch, tmp_path):
    """Every route's real entry point now runs the full v1 path (normalize, modes, structure) and still matches A0."""
    native = build_snapshot(SETTING_V1, user_dir=tmp_path / "none")
    assert native.enabled and not native.notes
    monkeypatch.setattr(pipeline, "OFF", native)  # what the routes fall back to when handed no snapshot
    assert characterization.check_all() == []


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_mutation_a0_detects_v1_with_cells_expanded(characterization, monkeypatch, tmp_path):
    """The previous test can fail: with every cell expanded, the routes' text changes and A0 says so."""
    expanded = build_snapshot(SETTING_V1, user_dir=write_user(tmp_path / "u", modes=ALL_EXPAND))
    monkeypatch.setattr(pipeline, "OFF", expanded)
    problems = characterization.check_all()
    assert {p.split(":")[0] for p in problems} >= {"edge_direct", "edge_folder", "kokoro", "chatterbox"}


# --------------------------------------------------------------------------- configuration and the panel

def test_the_configuration_key_is_validated_and_defaults_to_off(tmp_path):
    assert shared_config.SPEECH_PREP_VALUES == pipeline.SETTINGS
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "launcher.py").write_text("", encoding="utf-8")

    def load(toml: str):
        path = root / "config.toml"
        path.write_text(toml, encoding="utf-8")
        return shared_config.load(config_path=path, settings_data={}, repo_root=root, home=tmp_path)

    assert load("").tts.speech_prep == "off"
    assert load('[tts]\nspeech_prep = "V1"\n').tts.speech_prep == "v1"
    bad = load('[tts]\nspeech_prep = "on"\n')
    assert bad.tts.speech_prep == "off" and any(d.key == "tts.speech_prep" for d in bad.diagnostics)


def test_the_panel_freezes_the_snapshot_and_hands_it_on_only_when_on(tmp_path):
    from tts import epub2tts_gui as gui

    base = dict(speaker="s", backend="kokoro", voice_id="v", rate="+0%", resume=False, overwrite=False, bitrate="128k",
                workers=1, kokoro_speed=1.0, end_pause=1, paragraph_pause=1, pause_kw={})
    assert gui.freeze_tts_options(**base)["speech_prep"] is OFF
    run = build_snapshot(SETTING_V1, user_dir=write_user(tmp_path / "u", glossary="{bad"))
    options = job_control.freeze_options(gui.freeze_tts_options(**base, speech_prep=run))
    assert options["speech_prep"] is run
    assert gui.speech_prep_kwargs({"speech_prep": OFF}) == {} and gui.speech_prep_kwargs({}) == {}
    assert gui.speech_prep_kwargs({"speech_prep": run}) == {"speech_prep": run}
    assert gui.speech_prep_run_lines(OFF) == [] and gui.speech_prep_run_lines(None) == []
    lines = gui.speech_prep_run_lines(run)
    assert lines[0].startswith("Speech preparation v1 (ruleset 1") and "64 of 64 cells not expanded" in lines[0]
    assert "glossary ignored" in lines[1]
    assert gui.SPEECH_USER_DIR.parts[-2:] == ("runtime-data", "speech")


@pytest.mark.parametrize("helper, engine_name", [("convert_with_kokoro", "kokoro_file_to_mp3"),
                                                 ("convert_with_chatterbox", "chatterbox_file_to_mp3"),
                                                 ("convert_with_qwen3", "qwen3_file_to_mp3")])
def test_local_engine_helpers_pass_the_snapshot_only_when_on(helper, engine_name, tmp_path, monkeypatch):
    import importlib

    from tts import epub2tts_gui as gui

    module = {"kokoro_file_to_mp3": "tts.kokoro_synth", "chatterbox_file_to_mp3": "tts.chatterbox_synth",
              "qwen3_file_to_mp3": "tts.qwen3_synth"}[engine_name]
    seen: list[dict] = []
    monkeypatch.setattr(importlib.import_module(module), engine_name, lambda *a, **k: seen.append(k))
    source = tmp_path / "a.txt"
    source.write_text("x", encoding="utf-8")
    item = {"item_id": "1", "source": source, "destination": tmp_path / "out" / "a.mp3"}
    run = build_snapshot(SETTING_V1, user_dir=tmp_path / "none")
    for snapshot in (OFF, run):
        params = {"voice_id": "v", "kokoro_speed": 1.0, "end_pause": 1, "paragraph_pause": 1, "bitrate": "128k",
                  "speech_prep": snapshot}
        getattr(gui, helper)(item, params, None, lambda m: None, lambda: False)
    assert "speech_prep" not in seen[0] and seen[1]["speech_prep"] is run


def test_edge_direct_get_book_prepares_the_body_and_keeps_its_metadata(tmp_path):
    from tts.epub2tts_edge import epub2tts_edge as edge

    path = tmp_path / "b.txt"
    path.write_text("Title: Book 5\nAuthor: Agent 99\n\n# Chapter 5\n\nIt cost $5.\n", encoding="utf-8")
    run = build_snapshot(SETTING_V1, user_dir=write_user(tmp_path / "u", modes=ALL_EXPAND))
    contents, title, author, chapters = edge.get_book(str(path), run)
    assert (title, author, chapters) == ("Book 5", "Agent 99", ["Chapter five"])
    assert contents[0]["paragraphs"] == ["It cost five dollars."]
    assert edge.get_book(str(path))[0][0]["paragraphs"] == ["It cost $5."]


def test_the_edge_runner_hands_the_snapshot_to_get_book_only_when_given(tmp_path, monkeypatch):
    from tts.epub2tts_edge import runner

    seen: list[tuple] = []

    def fake_get_book(*args):
        seen.append(args)
        return [], "t", "a", []

    monkeypatch.setattr(runner, "get_book", fake_get_book)
    source = tmp_path / "a.txt"
    source.write_text("x", encoding="utf-8")
    run = build_snapshot(SETTING_V1, user_dir=tmp_path / "none")
    for snapshot in (None, run):
        kwargs = {} if snapshot is None else {"speech_prep": snapshot}
        with pytest.raises(ValueError, match="No text content"):
            runner.run_conversion_job(str(source), output_dir=str(tmp_path / "o"), audio_format="mp3", **kwargs)
    assert len(seen[0]) == 1 and seen[1][1] is run


def test_edge_folder_prepares_the_text_handed_to_its_splitter(tmp_path, monkeypatch):
    from tts import batch_convert as bc

    sent: list[str] = []
    monkeypatch.setattr(bc, "synthesize_chunk_mp3", lambda chunk, path, voice, rate: sent.append(chunk) or Path(path).write_bytes(b""))
    monkeypatch.setattr(bc, "merge_mp3s", lambda paths, output, bitrate=None: None)
    source = tmp_path / "a.txt"
    source.write_text("Title: Book 5\nIt cost $5.\n", encoding="utf-8")
    run = build_snapshot(SETTING_V1, user_dir=write_user(tmp_path / "u", modes=ALL_EXPAND))
    logged: list[str] = []
    status = bc.convert_single_pdf(source, tmp_path / "o", "voice", "+0%", log=logged.append,
                                   out_mp3=tmp_path / "o" / "a.mp3", speech_prep=run)
    assert status[0] == "success" and sent == ["Title: Book 5\nIt cost five dollars."]
    assert any("Speech preparation: 1 edit" in line for line in logged)


def test_the_qwen3_entry_point_plans_the_prepared_text_and_proves_its_spans(tmp_path, monkeypatch):
    import contextlib

    planned: list[str] = []
    real_plan = qs.plan_chunks

    def capture(text, *args):
        planned.append(text)
        real_plan(text, *args)
        raise RuntimeError("stop before any worker")

    monkeypatch.setattr(qs, "plan_chunks", capture)
    monkeypatch.setattr(qs.rt, "inference_lease", contextlib.nullcontext)
    source = tmp_path / "a.txt"
    source.write_text("# Chapter 5\n\nMr. Smith paid $5.\n", encoding="utf-8")
    run = build_snapshot(SETTING_V1, user_dir=write_user(tmp_path / "u", modes=ALL_EXPAND))
    for snapshot in (None, run):
        with pytest.raises(RuntimeError, match="stop before"):
            qs.qwen3_file_to_mp3(str(source), str(tmp_path / "o.mp3"), "qwen3-aiden", log=lambda m: None,
                                 speech_prep=snapshot, availability=lambda voice: (True, ""))
    # Qwen3's heading-as-paragraph adds its own blank line beside the source's (unchanged since A1).
    assert planned == ["Chapter 5\n\n\nMr. Smith paid $5.", "Chapter five\n\n\nMister Smith paid five dollars."]


def test_engine_modules_hold_no_normalization_rules():
    """Rule code lives only in tts/speech (convergence rule, Plan 01B 4.6): engines import ``prepare`` and nothing else."""
    import ast

    tts_dir = Path(qs.__file__).parent
    for name in ("kokoro_synth.py", "chatterbox_synth.py", "qwen3_synth.py", "batch_convert.py",
                 "epub2tts_edge/epub2tts_edge.py", "epub2tts_gui.py"):
        tree = ast.parse((tts_dir / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "tts.speech":
                assert {a.name for a in node.names} <= {"pipeline"}, (name, [a.name for a in node.names])
            elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("tts.speech"):
                assert node.module in ("tts.speech.document", "tts.speech.pipeline", "tts.speech.profiles"), (name, node.module)
            if isinstance(node, ast.Import):
                assert not any(a.name.startswith("tts.speech.") and a.name not in ("tts.speech.pipeline",) for a in node.names)
