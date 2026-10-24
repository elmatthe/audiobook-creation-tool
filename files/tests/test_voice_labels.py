"""v0.6.1 Plan 4 Phase 13A.3 — the voice dropdown's exact display wording.

The maintainer specified sixteen strings, in this order, on 2026-08-20, and that
instruction explicitly supersedes the drop's earlier requirement that the first
twelve ``display_label`` values stay byte-identical. The override reaches
**user-facing text only**: this module wrote the sixteen strings down once, and
then pinned everything the rename was *not* allowed to touch — order, backends,
voice ids, group labels, timing presets, and the identity of the default voice.

v0.6.5 Phase 2 removed two of those sixteen rows entirely (the multilingual Edge
voices, not a relabeling) and later appended two new rows (Chatterbox Male 3 and
Male 4, both approved by the maintainer's final listening ruling, plan Section 5)
that the Phase 13A.3 rename never touched — neither was renamed because neither
existed at that rename's time, and their labels ("Chatterbox - Male 3" / "- Male
4") were simply assigned correctly the first time. Male 3's registration is the
*original* candidate sample — a separate bounded pitch-retry variant was tried
and rejected, so no pitch/timbre adjustment reached this label or any other
column. This module now tracks sixteen; nothing else about the Phase 13A.3
rename changed for the pre-existing rows.

The last section proves the fact that makes the rename safe without a migration:
nothing persists a chosen voice by its label. If that ever changes, the test that
says so fails, and whoever changes it has to decide what happens to labels stored
by an older version.

v0.7.0 P02A (sections 8-10) makes labels and order cosmetic: identity is ``(backend, voice_id)``, the six reference
recordings are fixed by an explicit table, and disposable in-memory registries relabelled "1".."28" and reordered
prove that nothing else moves. The shipped labels above remain the initial values and are still pinned verbatim.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tts import voice_registry as vr
from source_probe import application_python_files  # noqa: E402

#: The maintainer's exact strings, in the maintainer's exact order. ASCII
#: hyphen-minus throughout — no em dash anywhere in a voice name any more.
MAINTAINER_LABELS = [
    "Edge Male - Steffan (en-US)",
    "Edge Male - Andrew (en-US)",
    "Edge Female - Aria (en-US)",
    "Edge Female - Ava (en-US)",
    "Edge Female - Jenny (en-US)",
    "Kokoro Female (Default) - Heart (en-US)",
    "Kokoro Female - Bella (en-US)",
    "Kokoro Male - Michael (en-US)",
    "Kokoro Male - Fenrir (en-US)",
    "Kokoro Male - Puck (en-US)",
    "Kokoro Male - Onyx (en-US)",
    "Kokoro Female - Emma (en-UK)",
    "Kokoro Male - George (en-UK)",
    "Kokoro Male - Daniel (en-UK)",
    "Chatterbox - Female 1",
    "Chatterbox - Female 2",
    "Chatterbox - Male 1",
    "Chatterbox - Male 2",
    "Chatterbox - Male 3",
    "Chatterbox - Male 4",
]

#: v0.6.7 CP6: the eight Qwen3-TTS rows, appended after the twenty above, labels exactly as the owner specified them
#: on 2026-10-19. The twenty above are the strings every earlier phase pinned and they are still pinned verbatim.
QWEN3_LABELS = [
    "Qwen3 - Aiden",
    "Qwen3 - Ryan",
    "Qwen3 - Female 1",
    "Qwen3 - Female 2",
    "Qwen3 - Male 1",
    "Qwen3 - Male 2",
    "Qwen3 - Male 3",
    "Qwen3 - Male 4",
]
ALL_LABELS = MAINTAINER_LABELS + QWEN3_LABELS

#: The wording each row used before this rename. None of these may survive as a
#: selectable label, and — because nothing persists a label — none of them needs
#: to resolve to anything either. The two multilingual formers are kept even
#: though v0.6.5 Phase 2 removed those rows entirely: the assertion (not offered)
#: only gets stronger, and this stays the historical record of what Phase 13A.3
#: renamed.
FORMER_LABELS = [
    "Steffan — en-US Male (default)",
    "Andrew Multilingual — en-US Male",
    "Andrew — en-US Male",
    "Aria — en-US Female",
    "Ava Multilingual — en-US Female",
    "Ava — en-US Female",
    "Jenny — en-US Female",
    "Heart (af_heart) — US Female (Kokoro default)",
    "Bella (af_bella) — US Female",
    "Michael (am_michael) — US Male",
    "Emma (bf_emma) — British Female",
    "George (bm_george) — British Male",
]

#: Every voice id, in registry order. The rename may not have moved or edited one.
#: v0.6.5 Phase 2 removed the two multilingual Edge ids entirely.
VOICE_IDS = [
    "en-US-SteffanNeural", "en-US-AndrewNeural",
    "en-US-AriaNeural", "en-US-AvaNeural",
    "en-US-JennyNeural",
    "af_heart", "af_bella", "am_michael", "am_fenrir", "am_puck", "am_onyx", "bf_emma", "bm_george", "bm_daniel",
    "chatterbox-female-1", "chatterbox-female-2",
    "chatterbox-male-1", "chatterbox-male-2",
    "chatterbox-male-3", "chatterbox-male-4",
]
QWEN3_IDS = ["qwen3-aiden", "qwen3-ryan", "qwen3-female-1", "qwen3-female-2",
             "qwen3-male-1", "qwen3-male-2", "qwen3-male-3", "qwen3-male-4"]

BACKENDS = ["edge"] * 5 + ["kokoro"] * 9 + ["chatterbox"] * 6

CHATTERBOX_LABELS = MAINTAINER_LABELS[14:]


# --------------------------------------------------------------------------- #
# 1. The dropdown text itself
# --------------------------------------------------------------------------- #


def test_the_dropdown_offers_the_maintainers_twenty_strings_in_order_then_the_eight_qwen3_strings():
    assert vr.display_labels()[:20] == MAINTAINER_LABELS  # nothing earlier moved, was renamed or was reordered
    assert vr.display_labels()[20:] == QWEN3_LABELS
    assert vr.display_labels() == ALL_LABELS and len(ALL_LABELS) == 28


def test_every_label_uses_the_ascii_hyphen_and_no_em_dash():
    for label in vr.display_labels():
        assert "—" not in label, f"{label!r} still carries the superseded em dash"
        assert " - " in label, f"{label!r} is missing the ASCII hyphen separator"


def test_the_labels_are_unique_so_one_never_shadows_another():
    labels = vr.display_labels()
    assert len(labels) == len(set(labels)) == 28


@pytest.mark.parametrize("label", ALL_LABELS)
def test_each_label_resolves_to_its_own_row(label):
    entry = vr.get_voice(label)
    assert entry is not None, f"{label!r} is not selectable"
    assert entry.display_label == label


@pytest.mark.parametrize("former", FORMER_LABELS)
def test_no_former_label_is_offered_any_more(former):
    assert former not in vr.display_labels()
    assert vr.get_voice(former) is None


# --------------------------------------------------------------------------- #
# 2-4. What the rename was not allowed to touch
# --------------------------------------------------------------------------- #


def test_the_backends_are_unchanged():
    assert [entry.backend for entry in vr.VOICES[:20]] == BACKENDS
    assert [entry.backend for entry in vr.VOICES[20:]] == ["qwen3"] * 8


def test_the_voice_ids_are_unchanged_and_still_in_the_same_order():
    assert [entry.voice_id for entry in vr.VOICES[:20]] == VOICE_IDS
    assert [entry.voice_id for entry in vr.VOICES[20:]] == QWEN3_IDS
    assert not {i for i in QWEN3_IDS} & {i for i in VOICE_IDS}  # a Qwen3 id never collides with a Chatterbox id


def test_the_timing_presets_are_still_the_approved_values():
    """Against the literal table the Phase 8 gate froze, not against the helpers.

    Comparing a row to ``_edge_preset(...)`` would pass even if a helper *default*
    were edited, because both sides would move together. ``EXPECTED_VOICES`` spells
    every millisecond out, so a changed default fails here.
    """
    from test_chatterbox_boundaries import EXPECTED_VOICES

    by_id = {entry.voice_id: entry for entry in vr.VOICES}
    assert [by_id[expected[1]].timing_preset for expected in EXPECTED_VOICES] == [
        preset for *_head, preset in EXPECTED_VOICES]
    # The four Decision B Kokoro rows and all six Chatterbox rows take their shared preset unmodified.
    for voice_id in ("am_fenrir", "am_puck", "am_onyx", "bm_daniel"):
        assert by_id[voice_id].timing_preset == vr._kokoro_preset(speed=1.0)
    assert [entry.timing_preset for entry in vr.VOICES[14:20]] == [vr._chatterbox_preset()] * 6
    # The eight Qwen3 rows take the shared local-engine preset unmodified (CP6 Q6: existing narration policy).
    assert [entry.timing_preset for entry in vr.VOICES[20:]] == [vr._qwen3_preset()] * 8
    assert vr._qwen3_preset() == vr._chatterbox_preset() == vr._kokoro_preset(speed=1.0)
    # v0.7.0 P01B (Q1): the local engines' closing pause is 0; the between-chunk pause is unchanged.
    assert vr._qwen3_preset()["paragraphpause"] == "700" and vr._qwen3_preset()["end_pause"] == "0"
    # v0.7.0 P01C (Q1): the Edge rows too; every voice of all four engines freezes no closing pause.
    assert all(entry.timing_preset["end_pause"] == "0" for entry in vr.VOICES)
    assert vr._edge_preset()["end_pause"] == "0" and vr._edge_preset()["chapter_ms"] == "2000"


def test_the_group_labels_are_unchanged_and_are_never_the_voice_name():
    groups = [entry.group_label for entry in vr.VOICES]
    assert groups[:5] == ["Microsoft Edge TTS — English (US)"] * 5
    assert groups[5:11] == ["Kokoro Local AI — American English"] * 6
    assert groups[11:14] == ["Kokoro Local AI — British English"] * 3
    assert groups[14:20] == [vr.CHATTERBOX_GROUP_LABEL] * 6
    assert groups[20:] == [vr.QWEN3_GROUP_LABEL] * 8
    assert vr.QWEN3_GROUP_LABEL != vr.CHATTERBOX_GROUP_LABEL and "Qwen3" in vr.QWEN3_GROUP_LABEL
    assert not set(groups) & set(vr.display_labels())


# --------------------------------------------------------------------------- #
# 5-6. Default identity, and the four labels that were already correct
# --------------------------------------------------------------------------- #


def test_steffan_is_still_the_default_voice_under_the_new_wording():
    assert vr.DEFAULT_VOICE_LABEL == "Edge Male - Steffan (en-US)"
    assert vr.DEFAULT_VOICE_LABEL == vr.VOICES[0].display_label
    assert vr.get_voice(vr.DEFAULT_VOICE_LABEL).voice_id == "en-US-SteffanNeural"
    assert vr.get_voice(vr.DEFAULT_VOICE_LABEL).backend == "edge"


def test_the_six_chatterbox_labels_were_already_right_and_did_not_change():
    """Four pre-existing (Phase 13A.3, untouched) plus Male 3 and Male 4
    (both new, Phase 2 — Male 3 is the original candidate, not the rejected
    pitch-retry variant)."""
    assert [entry.display_label for entry in vr.VOICES[14:20]] == CHATTERBOX_LABELS
    assert CHATTERBOX_LABELS == [
        "Chatterbox - Female 1", "Chatterbox - Female 2",
        "Chatterbox - Male 1", "Chatterbox - Male 2",
        "Chatterbox - Male 3", "Chatterbox - Male 4",
    ]


# --------------------------------------------------------------------------- #
# 7. Why no migration exists
# --------------------------------------------------------------------------- #


def test_no_persisted_setting_stores_a_voice_by_label():
    """The rename needs no compatibility seam, and this is the reason.

    A chosen voice lives in a ``tk.StringVar`` for the life of the panel and is
    never written to ``settings.json``: no production ``settings.set`` call names
    a voice, and the allowlist of keys the app understands has no entry for one.
    Should that ever change, this fails first.
    """
    from shared import config

    assert not any("voice" in key.lower() for key in config.USER_STATE_SETTINGS)

    scripts = Path(vr.__file__).resolve().parents[1]
    setters: list[str] = []
    for path in application_python_files(scripts):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "set" or not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                setters.append(first.value)
    assert setters, "the AST scan must actually find the settings writers"
    assert not any("voice" in key.lower() or "label" in key.lower() for key in setters), \
        f"a voice is being persisted after all: {setters}"


def test_the_panel_starts_on_the_default_voice_rather_than_a_stored_one():
    """Confirms the same fact from the panel's side, without building a window."""
    source = (Path(vr.__file__).resolve().parent / "epub2tts_gui.py").read_text(
        encoding="utf-8")
    # v0.7.0 P02A: the start label is the default voice's *current* label, asked of the registry by stable key
    assert "self.selected_voice_label = tk.StringVar(value=default_voice_label())" in source
    assert vr.DEFAULT_VOICE_KEY == ("edge", "en-US-SteffanNeural")


# --------------------------------------------------------------------------- #
# 8. v0.7.0 P02A — stable identities and the six fixed reference recordings
# --------------------------------------------------------------------------- #
UPLOADS = Path(__file__).resolve().parents[2] / "files" / "Cloned-Voice-Uploads"

#: Plan Revision 2, Appendix A, written out literally: stable reference id, fixed basename, the Chatterbox and Qwen3
#: voices that share it, and the recording's content SHA-256. Nothing here may follow a display label.
REFERENCES = [
    ("Female-1", "Chatterbox - Female 1.wav", "chatterbox-female-1", "qwen3-female-1",
     "b740b9ed352e6a32d93f4e523b27c55a717d1818b137a3af7bc3585a838655e4"),
    ("Female-2", "Chatterbox - Female 2.wav", "chatterbox-female-2", "qwen3-female-2",
     "428d3869b6bc7a26125063dfdaa8da05f8dab015427197f62e84a59f44bdb205"),
    ("Male-1", "Chatterbox - Male 1.wav", "chatterbox-male-1", "qwen3-male-1",
     "45fbfba0815b76b88d00b47a3f0ac3e747c1269a17c5a2f7a75c1bbb8f9c0d58"),
    ("Male-2", "Chatterbox - Male 2.wav", "chatterbox-male-2", "qwen3-male-2",
     "592139a28e82aaf5c8a2b584eddd41540acbf35db91bf053ed76a8a959f0b355"),
    ("Male-3", "Chatterbox - Male 3.wav", "chatterbox-male-3", "qwen3-male-3",
     "4ab6bd671add539afb4e551683047a04cb4ce3a95b0e7584bd5c2801dd44ee80"),
    ("Male-4", "Chatterbox - Male 4.wav", "chatterbox-male-4", "qwen3-male-4",
     "47eff938180617c015959cc56c3744fad8812f021c81930bec055ad324312cad"),
]

#: The 28 durable identities in shipped order (5 Edge, 9 Kokoro, 6 Chatterbox, 8 Qwen3).
SHIPPED_KEYS = [(b, v) for b, v in zip(BACKENDS + ["qwen3"] * 8, VOICE_IDS + QWEN3_IDS)]


def _sha(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def reference_bindings() -> list[tuple]:
    """Everything that binds a cloned voice to its recording, as the engines themselves resolve it today."""
    from tts import chatterbox_synth as cbx, qwen3_runtime as rt

    rows = []
    for _ref, _name, chatterbox_id, qwen_id, _sha256 in REFERENCES:
        clone = rt.get_voice(qwen_id)
        twin = cbx.REFERENCE_VOICES[chatterbox_id]
        rows.append((vr.reference_id("chatterbox", chatterbox_id), vr.reference_id("qwen3", qwen_id), clone.reference_name,
                     cbx.reference_source_path(chatterbox_id).name, rt.reference_path(clone).name,
                     twin.source_sha256, clone.reference_sha256, clone.model_key, clone.kind))
    return rows


EXPECTED_BINDINGS = [(ref, ref, ref, name, name, sha, sha, "base", "clone") for ref, name, _c, _q, sha in REFERENCES]


def test_the_28_stable_identities_are_exactly_the_shipped_roster():
    assert [v.key for v in vr.VOICES] == SHIPPED_KEYS and len(set(SHIPPED_KEYS)) == 28
    assert [b for b, _v in SHIPPED_KEYS].count("edge") == 5 and [b for b, _v in SHIPPED_KEYS].count("kokoro") == 9
    assert [b for b, _v in SHIPPED_KEYS].count("chatterbox") == 6 and [b for b, _v in SHIPPED_KEYS].count("qwen3") == 8
    assert vr.registry_problems(vr.VOICES) == [] and vr.reference_table_problems() == []


def test_the_six_recordings_are_fixed_by_explicit_tables_not_by_labels():
    assert vr.REFERENCE_RECORDINGS == {ref: name for ref, name, *_ in REFERENCES}
    assert vr.VOICE_REFERENCES == {**{("chatterbox", c): ref for ref, _n, c, _q, _s in REFERENCES},
                                   **{("qwen3", q): ref for ref, _n, _c, q, _s in REFERENCES}}
    assert reference_bindings() == EXPECTED_BINDINGS
    # the six tracked files are exactly these bytes (recomputed, not copied from the code under test)
    assert sorted(p.name for p in UPLOADS.glob("*.wav")) == sorted(name for _r, name, *_ in REFERENCES)
    for _ref, name, chatterbox_id, qwen_id, sha in REFERENCES:
        from tts import chatterbox_synth as cbx, qwen3_runtime as rt

        assert _sha(UPLOADS / name) == sha
        assert rt.reference_path(rt.get_voice(qwen_id)) == cbx.reference_source_path(chatterbox_id) == UPLOADS / name
    for backend, voice_id in (("qwen3", "qwen3-aiden"), ("kokoro", "af_heart"), ("edge", "en-US-AriaNeural"),
                              ("qwen3", "chatterbox-female-1"), ("chatterbox", "qwen3-female-1"), ("qwen3", "nobody")):
        with pytest.raises(KeyError):
            vr.reference_recording_filename(backend, voice_id)


def test_no_production_module_derives_a_file_name_or_engine_from_a_label():
    """The pre-P02A ``f"{entry.display_label}.wav"`` derivation, and fixed engine copies of labels, are gone for good."""
    scripts = Path(vr.__file__).resolve().parents[1]
    offenders = []
    for path in application_python_files(scripts):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr) and "display_label" in ast.unparse(node) and ".wav" in ast.unparse(node):
                offenders.append(f"{path.name}: {ast.unparse(node)}")
            if isinstance(node, ast.keyword) and node.arg == "label" and isinstance(node.value, ast.Constant) \
                    and str(node.value.value).startswith(("Chatterbox", "Qwen3")):
                offenders.append(f"{path.name}: label={node.value.value!r}")
    assert offenders == []


def test_qwen3_engine_data_is_unchanged_by_the_label_work():
    """Preset speaker tokens, model keys, transcript keys and the clone generation profile (owner Q31: tuning frozen)."""
    from tts import qwen3_runtime as rt, qwen3_synth

    assert [(v.voice_id, v.kind, v.model_key, v.speaker, v.reference_name) for v in rt.QWEN3_VOICES] == [
        ("qwen3-aiden", "custom_voice", "customvoice", "Aiden", ""),
        ("qwen3-ryan", "custom_voice", "customvoice", "Ryan", ""),
        *[(q, "clone", "base", "", ref) for ref, _n, _c, q, _s in REFERENCES]]
    assert qwen3_synth.CLONE_GENERATION == {"temperature": 0.70, "subtalker_temperature": 0.80}
    assert qwen3_synth.CLONE_GENERATION_REVISION == 1 and qwen3_synth.CLONE_REFERENCE_TAIL_SILENCE_S == 0.6


# --------------------------------------------------------------------------- #
# 9. v0.7.0 P02A — arbitrary labels and order are cosmetic (disposable in-memory registries only)
# --------------------------------------------------------------------------- #
def relabelled(order: list[int], labels: list[str] | None = None) -> list:
    """The shipped rows in ``order`` (indexes into VOICES), relabelled ``labels`` (default "1".."28" by new position)."""
    from dataclasses import replace

    labels = labels or [str(n) for n in range(1, len(order) + 1)]
    return [replace(vr.VOICES[i], display_label=labels[n]) for n, i in enumerate(order)]


REVERSED = list(range(27, -1, -1))
#: Engines interleaved (shipped row indexes): Qwen3, Edge, Chatterbox, Kokoro, Qwen3, Edge, ... until each row is placed once.
INTERLEAVED = [20, 0, 14, 5, 21, 1, 15, 6, 22, 2, 16, 7, 23, 3, 17, 8, 24, 4, 18, 9, 25, 19, 10, 26, 11, 27, 12, 13]
PERMUTATIONS = {"shipped": list(range(28)), "reversed": REVERSED, "interleaved": INTERLEAVED}


def test_the_interleaved_order_really_interleaves_every_engine():
    assert sorted(INTERLEAVED) == list(range(28))
    backends = [vr.VOICES[i].backend for i in INTERLEAVED]
    assert backends[:4] == ["qwen3", "edge", "chatterbox", "kokoro"]
    runs = sum(1 for a, b in zip(backends, backends[1:]) if a != b)
    assert runs >= 16  # not merely four contiguous engine blocks in a new order


@pytest.mark.parametrize("name", PERMUTATIONS)
def test_numbered_labels_in_any_order_keep_every_identity_reference_and_engine_label(monkeypatch, name):
    from tts import chatterbox_synth as cbx, qwen3_runtime as rt

    order = PERMUTATIONS[name]
    shipped = list(vr.VOICES)
    voices = relabelled(order)
    assert vr.registry_problems(voices) == []
    monkeypatch.setattr(vr, "VOICES", voices)

    def numbered(key) -> str:  # the label the stress registry gives a stable key: its new position
        return str(order.index(SHIPPED_KEYS.index(key)) + 1)

    # the dropdown is exactly the edited order, labels "1".."28", never regrouped or sorted
    assert vr.display_labels() == [str(n) for n in range(1, 29)]
    for n, index in enumerate(order, start=1):
        entry = vr.get_voice(str(n))
        assert entry.key == SHIPPED_KEYS[index]  # the label "n" selects the voice placed there, nothing else
        assert entry.timing_preset == shipped[index].timing_preset and entry.group_label == shipped[index].group_label
    # the default is still Steffan, now under whatever label he carries
    assert vr.default_voice_label() == numbered(("edge", "en-US-SteffanNeural"))
    # recordings, hashes, transcript keys and models are untouched
    assert reference_bindings() == EXPECTED_BINDINGS
    # every visible engine label follows the registry
    for clone in rt.QWEN3_VOICES:
        assert clone.label == numbered(("qwen3", clone.voice_id))
    for voice in cbx.REFERENCE_VOICES.values():
        assert voice.label == numbered(("chatterbox", voice.voice_id))


def test_the_shipped_tables_are_not_edited_by_a_disposable_registry(monkeypatch):
    before = [(v.key, v.display_label) for v in vr.VOICES]
    monkeypatch.setattr(vr, "VOICES", relabelled(REVERSED))
    monkeypatch.undo()
    assert [(v.key, v.display_label) for v in vr.VOICES] == before
    source = Path(vr.__file__).read_text(encoding="utf-8")
    assert all(f'display_label="{label}"' in source for label in ALL_LABELS)


def test_punctuation_and_unicode_labels_are_kept_exactly_as_written(monkeypatch):
    labels = ["Ärger (Test) #1!", "日本語の声", "Zoë — the narrator", "A/B: \"quoted\"", "Ω", "Café"]
    labels += [f"voice {n}" for n in range(len(labels) + 1, 29)]
    voices = relabelled(list(range(28)), labels)
    assert vr.registry_problems(voices) == []
    monkeypatch.setattr(vr, "VOICES", voices)
    assert vr.display_labels() == labels  # displayed text is not normalised or escaped
    assert vr.get_voice("日本語の声").key == SHIPPED_KEYS[1]


# --------------------------------------------------------------------------- #
# 10. v0.7.0 P02A — an invalid or ambiguous registry is refused with the stable keys named
# --------------------------------------------------------------------------- #
def with_label(index: int, label: str) -> list:
    from dataclasses import replace

    return [replace(v, display_label=label) if i == index else v for i, v in enumerate(vr.VOICES)]


@pytest.mark.parametrize("label,expected", [
    ("", "is empty"),
    ("   ", "is empty"),
    (" Padded", "starts or ends with whitespace"),
    ("Padded\t", "starts or ends with whitespace"),
    ("Two\nlines", "control character"),
    ("Edge Male - Steffan (en-US)", "is used by 2 voices"),
])
def test_a_bad_label_is_refused_naming_the_voice(label, expected):
    problems = vr.registry_problems(with_label(5, label))
    assert any(expected in p for p in problems), problems
    assert any("kokoro/af_heart" in p for p in problems), problems
    with pytest.raises(vr.VoiceRegistryError, match="kokoro/af_heart"):
        vr.check_registry(with_label(5, label))


def test_labels_that_differ_only_in_unicode_composition_are_duplicates():
    composed, decomposed = "Café", "Café"
    assert composed != decomposed  # different code points, same text on screen
    voices = with_label(0, composed)
    voices = [*voices[:1], *with_label(1, decomposed)[1:]]
    problems = vr.registry_problems(voices)
    assert any("is used by 2 voices" in p and "edge/en-US-SteffanNeural" in p and "edge/en-US-AndrewNeural" in p
               for p in problems), problems
    assert vr.registry_problems(with_label(1, "Cafe")) == []  # different text is not a duplicate


def test_a_duplicate_or_malformed_identity_is_refused():
    from dataclasses import replace

    voices = list(vr.VOICES)
    twice = voices + [replace(voices[3], display_label="Ava again")]
    assert any("listed twice" in p and "edge/en-US-AvaNeural" in p for p in vr.registry_problems(twice))
    shared_id = voices + [replace(voices[5], backend="qwen3", display_label="Heart elsewhere")]
    assert any("also used by the kokoro backend" in p for p in vr.registry_problems(shared_id))
    bad_id = [replace(voices[6], voice_id="af bella")] + voices[7:] + voices[:6]
    assert any("not a plain token" in p for p in vr.registry_problems(bad_id))
    bad_backend = [replace(voices[6], backend="piper")] + voices[7:] + voices[:6]
    assert any("unknown backend 'piper'" in p for p in vr.registry_problems(bad_backend))
    no_default = voices[1:]
    assert any("default voice edge/en-US-SteffanNeural is not registered" in p for p in vr.registry_problems(no_default))
    unmapped = voices + [replace(voices[14], voice_id="chatterbox-female-9", display_label="New clone")]
    assert any("chatterbox/chatterbox-female-9: no reference recording is mapped" in p for p in vr.registry_problems(unmapped))
    assert vr.registry_problems([]) == ["no voices are registered"]


def _load_copy(tmp_path, monkeypatch, text: str):
    import importlib.util
    import sys

    copy = tmp_path / "voice_registry_copy.py"
    copy.write_text(text, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("voice_registry_copy", copy)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "voice_registry_copy", module)  # dataclasses look their module up while defining
    spec.loader.exec_module(module)
    return module


def test_the_module_refuses_to_load_an_invalid_registry(tmp_path, monkeypatch):
    """Negative control on a disposable copy of the real module: one duplicated label stops the import, with keys named."""
    source = Path(vr.__file__).read_text(encoding="utf-8")
    assert _load_copy(tmp_path, monkeypatch, source).display_labels() == ALL_LABELS  # the unedited copy loads
    broken = source.replace('display_label="Edge Male - Andrew (en-US)"', 'display_label="Edge Male - Steffan (en-US)"', 1)
    assert broken != source
    with pytest.raises(Exception) as caught:
        _load_copy(tmp_path, monkeypatch, broken)
    assert type(caught.value).__name__ == "VoiceRegistryError"
    assert "edge/en-US-SteffanNeural" in str(caught.value) and "edge/en-US-AndrewNeural" in str(caught.value)
