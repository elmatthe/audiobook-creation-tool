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
    assert "self.selected_voice_label = tk.StringVar(value=DEFAULT_VOICE_LABEL)" in source


def test_the_six_reference_recordings_are_named_after_the_chatterbox_labels_and_shared_by_the_qwen3_clones():
    """One bundled copy per speaker, named exactly like its Chatterbox dropdown label; each Qwen3 clone resolves to it."""
    import hashlib
    from pathlib import Path

    from tts import chatterbox_synth as cbx, qwen3_runtime as rt, voice_registry as vr

    uploads = Path(__file__).resolve().parents[2] / "files" / "Chatterbox-Voice-Uploads"
    chatterbox = [v for v in vr.VOICES if v.backend == "chatterbox"]
    assert sorted(p.name for p in uploads.glob("*.wav")) == sorted(f"{v.display_label}.wav" for v in chatterbox)
    for entry in chatterbox:
        assert vr.reference_recording_filename(entry.voice_id) == f"{entry.display_label}.wav"
        assert cbx.reference_source_path(entry.voice_id) == uploads / f"{entry.display_label}.wav"
    assert sorted(vr.CLONE_REFERENCE_VOICE) == sorted(v.voice_id for v in rt.QWEN3_VOICES if v.kind == rt.KIND_CLONE)
    for clone_id, chatterbox_id in vr.CLONE_REFERENCE_VOICE.items():
        voice = rt.get_voice(clone_id)
        path = rt.reference_path(voice)
        assert path == cbx.reference_source_path(chatterbox_id)  # the same single file, not a copy
        assert hashlib.sha256(path.read_bytes()).hexdigest() == voice.reference_sha256 == cbx.REFERENCE_VOICES[chatterbox_id].source_sha256
        assert voice.label.removeprefix("Qwen3 - ") == vr.get_voice(path.stem).display_label.removeprefix("Chatterbox - ")
    import pytest

    for voice_id in ("qwen3-aiden", "af_heart", "en-US-AriaNeural", "nobody"):
        with pytest.raises(KeyError):
            vr.reference_recording_filename(voice_id)
