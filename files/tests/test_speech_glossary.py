"""Plan 01B checkpoint A2: the spoken-form glossary (section 4.5, decision D9).

Data only: the bundled file ships empty, the user file is optional, a broken file or entry never blocks a run, and
precedence is user > bundled > rules. Modes decide whether an entry may touch a token a class claims.
"""

from __future__ import annotations

import json

import pytest

from tts.speech import glossary as g
from tts.speech.normalize import GLOSSARY_ONLY, NATIVE, normalize


def entry(**fields) -> dict:
    return {"id": "e1", "written": "Tamar", "spoken": "tay mar", **fields}


def parsed(*entries, source="user") -> g.Glossary:
    return g.parse({"version": 1, "entries": list(entries)}, source)


def test_the_bundled_glossary_ships_empty_and_valid():
    data = json.loads(g.BUNDLED_GLOSSARY.read_text(encoding="utf-8"))
    assert data == {"version": 1, "entries": []}
    assert g.load(g.BUNDLED_GLOSSARY, "bundled") == g.EMPTY


def test_a_valid_entry_loads_with_defaults():
    loaded = parsed(entry())
    assert loaded.notes == ()
    (only,) = loaded.entries
    assert (only.match, only.case, only.preserve_case, only.engines, only.phonemes, only.source) == \
        ("word", "sensitive", False, ("*",), None, "user")


@pytest.mark.parametrize("bad, reason", [
    ("not an object", "must be an object"),
    (entry(colour="red"), "unknown field"),
    (entry(id="has space"), "id must be"),
    (entry(written=""), "written must be"),
    (entry(written=" Tamar"), "written must be"),
    (entry(written="a\nb"), "written must be"),
    (entry(written="x" * 81), "written must be"),
    (entry(spoken="tay-mar"), "spoken must be"),
    (entry(spoken="tay  mar"), "spoken must be"),
    (entry(spoken="tay mar,"), "spoken must be"),
    (entry(spoken=""), "spoken must be"),
    (entry(spoken="a" * 81), "spoken must be"),
    (entry(spoken="the tamar way"), "must not contain written"),
    (entry(match="regex"), "match must be"),
    (entry(case="upper"), "case must be"),
    (entry(preserve_case="yes"), "preserve_case"),
    (entry(engines=[]), "engines must be"),
    (entry(engines=["piper"]), "engines must be"),
    (entry(engines=["*", "kokoro"]), "engines must be"),
    (entry(engines=["kokoro", "kokoro"]), "engines must be"),
    (entry(phonemes="t(a)"), "phonemes must be"),
    (entry(phonemes=""), "phonemes must be"),
    (entry(note="n" * 201), "note must be"),
])
def test_a_broken_entry_is_skipped_with_a_note_naming_it(bad, reason):
    loaded = parsed(bad, entry(id="ok", written="Ascended", spoken="uh sended"))
    assert [e.id for e in loaded.entries] == ["ok"]
    (note,) = loaded.notes
    assert reason in note and "skipped" in note


@pytest.mark.parametrize("data", [[], {"entries": []}, {"version": 2, "entries": []}, {"version": 1, "entries": {}}])
def test_a_broken_file_contributes_nothing_and_one_note(data):
    loaded = g.parse(data, "user")
    assert loaded.entries == () and len(loaded.notes) == 1 and "ignored" in loaded.notes[0]


def test_files_missing_corrupt_oversized_or_overfull(tmp_path):
    assert g.load(tmp_path / "absent.json", "user") == g.EMPTY
    assert "missing" in g.load(tmp_path / "absent.json", "bundled").notes[0]
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not json", encoding="utf-8")
    assert g.load(corrupt, "user").entries == () and "ignored" in g.load(corrupt, "user").notes[0]
    undecodable = tmp_path / "bytes.json"
    undecodable.write_bytes(b"\xff\xfe\x00")
    assert "ignored" in g.load(undecodable, "user").notes[0]
    big = tmp_path / "big.json"
    big.write_text(" " * (g.MAX_FILE_BYTES + 1), encoding="utf-8")
    assert "larger than" in g.load(big, "user").notes[0]
    many = [entry(id=f"e{i}", written=f"Word{i}x", spoken="word") for i in range(g.MAX_ENTRIES + 1)]
    assert "more than" in parsed(*many).notes[0]
    bom = tmp_path / "bom.json"
    bom.write_bytes(b"\xef\xbb\xbf" + json.dumps({"version": 1, "entries": [entry()]}).encode("utf-8"))
    assert len(g.load(bom, "user").entries) == 1


def test_overlapping_entries_in_one_file_reject_the_later_one():
    loaded = parsed(entry(id="a", written="New York", spoken="noo york"),
                    entry(id="b", written="York", spoken="yawk"),            # contained in "New York"
                    entry(id="c", written="Yorkshire", spoken="yawk sher"),  # "York" ends one and starts the other
                    entry(id="dup", written="Ottawa", spoken="ot uh wuh"),
                    entry(id="dup", written="Paris", spoken="pair iss"))
    assert [e.id for e in loaded.entries] == ["a", "dup"]
    assert [n.split(": ", 2)[-1] for n in loaded.notes] == ["overlaps entry 'a'", "overlaps entry 'a'",
                                                             "duplicate id 'dup'"]


def test_entries_scoped_to_disjoint_engines_may_overlap():
    loaded = parsed(entry(id="a", engines=["kokoro"]), entry(id="b", engines=["chatterbox"], spoken="tah mar"))
    assert [e.id for e in loaded.entries] == ["a", "b"]


def test_user_entries_take_precedence_over_bundled_ones():
    user = parsed(entry(id="mine", spoken="tah mar"))
    bundled = parsed(entry(id="shipped"), entry(id="other", written="Ascended", spoken="uh sended"), source="bundled")
    merged = g.merge(user, bundled)
    assert [(e.id, e.source) for e in merged.entries] == [("mine", "user"), ("other", "bundled")]
    assert any("replaced by user entry mine" in n for n in merged.notes)
    assert normalize("Tamar wept.", glossary=merged.entries).spoken == "tah mar wept."


def test_word_and_exact_matching_case_and_preserved_case():
    word = parsed(entry(case="insensitive", preserve_case=True)).entries
    assert normalize("Tamar, TAMAR and tamar; Tamarind.", glossary=word).spoken == \
        "Tay mar, TAY MAR and tay mar; Tamarind."
    exact = parsed(entry(match="exact", written="Tam", spoken="tom")).entries
    assert normalize("Tamarind Tam", glossary=exact).spoken == "tomarind tom"
    sensitive = parsed(entry()).entries
    assert normalize("tamar Tamar", glossary=sensitive).spoken == "tamar tay mar"


def test_engine_scope_and_phoneme_markup():
    entries = parsed(entry(engines=["chatterbox"]), entry(id="k", written="Ascended", spoken="uh sended",
                                                          engines=["kokoro"], phonemes="ɐsˈɛndᵻd")).entries
    text = "Tamar Ascended."
    assert normalize(text, glossary=entries, engine="chatterbox").spoken == "tay mar Ascended."
    assert normalize(text, glossary=entries, engine="kokoro").spoken == "Tamar uh sended."
    assert normalize(text, glossary=entries, engine="kokoro", phoneme_markup=True).spoken == \
        "Tamar [Ascended](/ɐsˈɛndᵻd/)."
    assert normalize(text, glossary=entries, engine="edge").spoken == text


def test_the_glossary_never_touches_protected_spans_or_structure():
    entries = parsed(entry(written="Book", spoken="volume"), entry(id="x", written="example", spoken="sample")).entries
    text = "Title: Book\n# Book\nSee https://example.com and the Book."
    assert normalize(text, glossary=entries).spoken == "Title: Book\n# volume\nSee https://example.com and the volume."


def test_modes_decide_whether_an_entry_may_change_a_claimed_token():
    entries = parsed(entry(written="Dr.", spoken="doc", match="exact")).entries
    text = "Dr. Smith came."
    assert normalize(text, glossary=entries).spoken == "doc Smith came."
    assert normalize(text, glossary=entries, modes={"TITLE": GLOSSARY_ONLY}).spoken == "doc Smith came."
    withheld = normalize(text, glossary=entries, modes={"TITLE": NATIVE})
    assert withheld.spoken == text and withheld.withheld[0].rule_id == "GLOSS.user.e1"
    plain = parsed(entry()).entries
    assert normalize("Tamar.", glossary=plain, modes={c: NATIVE for c in ("CARD", "TITLE")}).spoken == "tay mar."


def test_glossary_edits_are_traceable_and_hashed():
    loaded = parsed(entry())
    result = normalize("Tamar.", glossary=loaded.entries)
    (edit,) = result.edits
    assert (edit.rule_id, edit.cls, edit.confidence, edit.original) == ("GLOSS.user.e1", "GLOSS", "glossary", "Tamar")
    assert loaded.content_hash == parsed(entry()).content_hash != parsed(entry(spoken="tah mar")).content_hash
    assert g.EMPTY.content_hash == parsed().content_hash


def test_engine_ids_match_the_four_engines():
    assert g.ENGINE_IDS == ("edge", "kokoro", "chatterbox", "qwen3")
