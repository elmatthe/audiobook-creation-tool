"""Plan 01B checkpoint A4: the A/B corpus tool plans honest, blind, bounded pairs. No audio, no network."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

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


# --------------------------------------------------------------------------- ordered listening export

ROWS = ab.ordered_rows(PLAN)
BLIND_WORDS = ("today", "normalized", "normalised", "expanded", "original", "preparation off", "native")


def test_sixty_comparisons_in_engine_blocks_and_alphabetical_class_order():
    assert [row["number"] for row in ROWS] == list(range(1, 61))
    blocks = {"chatterbox": range(1, 16), "kokoro": range(16, 31), "qwen3": range(31, 46), "edge_direct": range(46, 61)}
    for route, numbers in blocks.items():
        block = [row for row in ROWS if row["route"] == route]
        assert [row["number"] for row in block] == list(numbers)
        assert [row["class"] for row in block] == ["CARD", "CUR", "DATE", "DEC", "FRAC", "ORD", "PCT", "RANGE", "RATIO",
                                                   "ROMAN", "SYM", "TIME", "TITLE", "UNIT", "YEAR"]
    assert ROWS[0]["A"]["file"] == "001-Chatterbox-CARD-A.wav" and ROWS[-1]["B"]["file"] == "060-Edge-YEAR-B.wav"


def test_names_sort_as_pairs_and_slots_follow_the_blind_sheet_not_the_side():
    names = [row[s]["file"] for row in ROWS for s in ("A", "B")]
    assert names == sorted(names) and len(set(names)) == 120
    pairs = {p["pair"]: p for p in PLAN["pairs"]}
    off_in_slot_a = 0
    for row in ROWS:
        first, second = sorted(pairs[row["pair"]]["clips"].values())
        assert (row["A"]["source_clip"], row["B"]["source_clip"]) == (first, second)
        off_in_slot_a += row["A"]["source_clip"] == pairs[row["pair"]]["clips"]["A"]
    assert 15 < off_in_slot_a < 45, "slot A must not systematically be one preparation side"


def test_the_legacy_sheet_agrees_with_the_ordered_slots_where_it_exists():
    sheet = ab.LISTEN / "REVIEW-SHEET.md"
    if not sheet.is_file():
        pytest.skip("no local A4 listening folder")
    names = {v: k for k, v in ab.ENGINE_NAMES.items()}
    by_pair = {(row["route"], row["class"]): row for row in ROWS}
    checked = 0
    for line in sheet.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) == 7 and cells[0].isdigit():
            row = by_pair[(names[cells[1]], cells[2].split(" ")[0])]
            assert (cells[4], cells[5]) == (row["A"]["source_clip"], row["B"]["source_clip"])
            checked += 1
    assert checked == 45


RATE = 24000


def speech_then_silence(path: Path, seed: int, *, speech_s=0.4, tail_s=1.0, tail_level=0.0) -> np.ndarray:
    """A synthetic clip: noise-like 'speech', then a tail at ``tail_level`` (0 = digital silence)."""
    rng = np.random.default_rng(seed)
    speech = (rng.uniform(-0.4, 0.4, int(RATE * speech_s)) * 32767).astype(np.int16)
    tail = (rng.uniform(-tail_level, tail_level, int(RATE * tail_s)) * 32767).astype(np.int16)
    samples = np.concatenate([speech, tail])
    sf.write(str(path), samples, RATE, subtype="PCM_16")
    return samples


@pytest.fixture()
def fake_listen(tmp_path, monkeypatch):
    listen = tmp_path / "listen"
    listen.mkdir()
    for index, pair in enumerate(PLAN["pairs"]):
        for offset, name in enumerate(pair["clips"].values()):
            speech_then_silence(listen / f"{name}.wav", index * 2 + offset)
    monkeypatch.setattr(ab, "synthesize", lambda *a, **k: pytest.fail("the export must never synthesize"))
    return listen


def test_export_writes_trimmed_copies_and_a_private_mapping(fake_listen, tmp_path):
    out, key = tmp_path / "listen-ordered", tmp_path / "key"
    sources_before = {p.name: p.read_bytes() for p in fake_listen.glob("*.wav")}
    assert ab.export_ordered(PLAN, fake_listen, out, key) == 0
    wavs = sorted(p.name for p in out.glob("*.wav"))
    assert wavs == sorted(row[s]["file"] for row in ROWS for s in ("A", "B"))
    mapping = json.loads((key / ab.ORDERED_MAPPING).read_text(encoding="utf-8"))["files"]
    pairs = {p["pair"]: p for p in PLAN["pairs"]}
    for entry in mapping:
        source = fake_listen / f"{entry['source_clip']}.wav"
        original, _ = sf.read(str(source), dtype="int16")
        copy, _ = sf.read(str(out / entry["file"]), dtype="int16")
        assert np.array_equal(copy, original[:len(copy)]), "only the end may be removed"
        assert len(copy) == int(RATE * 0.4) + int(RATE * ab.TRIM_KEEP_MS / 1000)
        assert entry["trimmed_ms"] == round((len(original) - len(copy)) * 1000 / RATE) > 800
        assert entry["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
        assert entry["sha256"] == hashlib.sha256((out / entry["file"]).read_bytes()).hexdigest()
        side = "A" if pairs[entry["pair"]]["clips"]["A"] == entry["source_clip"] else "B"
        assert entry["preparation"] == ("off (today)" if side == "A" else f"{pairs[entry['pair']]['class']} expanded")
    assert {p.name: p.read_bytes() for p in fake_listen.glob("*.wav")} == sources_before, "sources are never touched"
    before = {p.name: p.stat().st_mtime_ns for p in out.glob("*.wav")}
    assert ab.export_ordered(PLAN, fake_listen, out, key) == 0
    assert {p.name: p.stat().st_mtime_ns for p in out.glob("*.wav")} == before, "a rerun rewrites nothing"


def test_quiet_endings_and_clips_without_silence_are_kept_whole(tmp_path):
    quiet = speech_then_silence(tmp_path / "quiet.wav", 1, tail_level=10 ** (-50 / 20))  # a soft fricative, not silence
    data, info = ab.trimmed_listening_copy(tmp_path / "quiet.wav")
    assert info["trimmed_ms"] == 0 and info["kept_samples"] == len(quiet)
    full = speech_then_silence(tmp_path / "full.wav", 2, tail_s=0.0)
    assert ab.trimmed_listening_copy(tmp_path / "full.wav")[1]["kept_samples"] == len(full)
    short = speech_then_silence(tmp_path / "short.wav", 3, tail_s=0.15)  # 150 ms tail: under the 50 ms saving floor
    assert ab.trimmed_listening_copy(tmp_path / "short.wav")[1]["trimmed_ms"] == 0
    assert len(short) == int(RATE * 0.55)


def test_the_copy_check_rejects_changed_samples_and_non_silent_cuts(tmp_path):
    original = speech_then_silence(tmp_path / "src.wav", 4)
    sf.write(str(tmp_path / "bad.wav"), original[:500] * 0, RATE, subtype="PCM_16")
    assert "samples differ" in ab.verify_listening_copy(tmp_path / "src.wav", tmp_path / "bad.wav", 500)
    sf.write(str(tmp_path / "cut.wav"), original[:500], RATE, subtype="PCM_16")
    assert "not silent" in ab.verify_listening_copy(tmp_path / "src.wav", tmp_path / "cut.wav", 500)


def test_an_existing_review_sheet_is_never_replaced(fake_listen, tmp_path):
    out = tmp_path / "listen-ordered"
    out.mkdir()
    (out / "REVIEW-SHEET.md").write_text("| 001 | ... | A | owner verdicts |\n", encoding="utf-8")
    assert ab.export_ordered(PLAN, fake_listen, out, tmp_path / "key") == 0
    assert (out / "REVIEW-SHEET.md").read_text(encoding="utf-8") == "| 001 | ... | A | owner verdicts |\n"


def test_the_ordered_sheet_references_every_file_and_stays_blind(fake_listen, tmp_path):
    out = tmp_path / "listen-ordered"
    ab.export_ordered(PLAN, fake_listen, out, tmp_path / "key")
    sheet = (out / "REVIEW-SHEET.md").read_text(encoding="utf-8")
    table = [line for line in sheet.splitlines() if line.startswith("| 0")]
    assert len(table) == 60
    assert "| # | Engine | Class | Listen for | Clip A | Clip B | My verdict | Notes |" in sheet
    for line, row in zip(table, ROWS):
        assert f"| {row['A']['file']} | {row['B']['file']} |" in line and (out / row["A"]["file"]).is_file()
    for word in BLIND_WORDS:
        assert word not in sheet.lower() and not any(word in name.lower() for name in map(str, out.iterdir()))
    assert sum("touches approved audio" in line for line in table) == sum(p["affects_previously_approved"] != ["none"] for p in PLAN["pairs"])
    for text in ab.SNIPPETS.values():
        assert text in sheet


def test_the_export_refuses_missing_sources_and_foreign_files(fake_listen, tmp_path):
    out = tmp_path / "listen-ordered"
    victim = next(fake_listen.glob("*.wav"))
    kept = victim.read_bytes()
    victim.write_bytes(b"")
    assert ab.export_ordered(PLAN, fake_listen, out, tmp_path / "key") == 1 and not out.exists()
    victim.write_bytes(kept)
    out.mkdir()
    (out / "stray.wav").write_bytes(b"x")
    assert ab.export_ordered(PLAN, fake_listen, out, tmp_path / "key") == 1


def test_the_real_ordered_folder_is_complete_and_identical_to_its_sources():
    mapping_path = ab.KEY / ab.ORDERED_MAPPING
    if not mapping_path.is_file():
        pytest.skip("no local ordered export")
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))["files"]
    assert len(mapping) == 120 and len(list(ab.ORDERED.glob("*.wav"))) == 120
    for entry in mapping:
        source, copy = ab.LISTEN / f"{entry['source_clip']}.wav", ab.ORDERED / entry["file"]
        assert hashlib.sha256(copy.read_bytes()).hexdigest() == entry["sha256"]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == entry["source_sha256"]
        assert ab.verify_listening_copy(source, copy, entry["kept_samples"]) is None
        assert entry["export_seconds"] * 1000 + entry["trimmed_ms"] == pytest.approx(entry["source_seconds"] * 1000, abs=2)
    plan = ab.load_plan()
    assert plan == PLAN, "key/plan.json must be the plan this tool builds (unchanged since generation)"
    edge = [p for p in plan["pairs"] if p["route"] == "edge_direct"]
    assert len(edge) == 15 and all((ab.LISTEN / f"{n}.wav").is_file() for p in edge for n in p["clips"].values())


def test_the_g2_passage_covers_every_class_and_keeps_its_ambiguous_examples():
    from tts.speech.normalize import normalize

    result = normalize(ab.G2_PASSAGE)
    assert {e.cls for e in result.edits} >= set(ab.SNIPPETS)
    assert {a.text for a in result.ambiguities} >= {"24/7", "3:16", "1999", "3.5", "1:30"}
    assert 2000 < len(ab.G2_PASSAGE) < 3000, "about three minutes of narration"
    assert ab.G2_PASSAGE.count("\n# ") == 2 and ab.G2_PASSAGE.startswith("Title: ")
    sheet = ab.g2_review_sheet({"edge_direct": {"seconds": 180.0}})
    assert all(name in sheet for name in ab.G2_FILES.values()) and "not generated" in sheet


@pytest.mark.parametrize("reference, heard, expected", [
    ("It cost $12.50.", "It cost twelve dollars fifty cents.", 0.0),
    ("It cost $12.50.", "It cost $12.50", 0.0),
    ("one two three four", "one three four", 0.25),
    ("one two", "", 1.0),
])
def test_word_error_rate_compares_spoken_forms(reference, heard, expected):
    assert ab.word_error_rate(reference, heard) == expected
