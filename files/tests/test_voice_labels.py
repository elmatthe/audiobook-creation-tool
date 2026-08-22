"""v0.6.1 Plan 4 Phase 13A.3 — the voice dropdown's exact display wording.

The maintainer specified these sixteen strings, in this order, on 2026-08-20, and
that instruction explicitly supersedes the drop's earlier requirement that the
first twelve ``display_label`` values stay byte-identical. The override reaches
**user-facing text only**: this module writes the sixteen strings down once, and
then pins everything the rename was *not* allowed to touch — order, backends,
voice ids, group labels, timing presets, and the identity of the default voice.

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

#: The maintainer's exact strings, in the maintainer's exact order. ASCII
#: hyphen-minus throughout — no em dash anywhere in a voice name any more.
MAINTAINER_LABELS = [
    "Edge Male - Steffan (en-US)",
    "Edge Male - Andrew (en-Multilingual)",
    "Edge Male - Andrew (en-US)",
    "Edge Female - Aria (en-US)",
    "Edge Female - Ava (en-Multilingual)",
    "Edge Female - Ava (en-US)",
    "Edge Female - Jenny (en-US)",
    "Kokoro Female (Default) - Heart (en-US)",
    "Kokoro Female - Bella (en-US)",
    "Kokoro Male - Michael (en-US)",
    "Kokoro Female - Emma (en-UK)",
    "Kokoro Male - George (en-UK)",
    "Chatterbox - Female 1",
    "Chatterbox - Female 2",
    "Chatterbox - Male 1",
    "Chatterbox - Male 2",
]

#: The wording each row used before this rename. None of these may survive as a
#: selectable label, and — because nothing persists a label — none of them needs
#: to resolve to anything either.
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
VOICE_IDS = [
    "en-US-SteffanNeural", "en-US-AndrewMultilingualNeural", "en-US-AndrewNeural",
    "en-US-AriaNeural", "en-US-AvaMultilingualNeural", "en-US-AvaNeural",
    "en-US-JennyNeural",
    "af_heart", "af_bella", "am_michael", "bf_emma", "bm_george",
    "chatterbox-female-1", "chatterbox-female-2",
    "chatterbox-male-1", "chatterbox-male-2",
]

BACKENDS = ["edge"] * 7 + ["kokoro"] * 5 + ["chatterbox"] * 4

CHATTERBOX_LABELS = MAINTAINER_LABELS[12:]


# --------------------------------------------------------------------------- #
# 1. The dropdown text itself
# --------------------------------------------------------------------------- #


def test_the_dropdown_offers_exactly_the_maintainers_sixteen_strings_in_order():
    assert vr.display_labels() == MAINTAINER_LABELS


def test_every_label_uses_the_ascii_hyphen_and_no_em_dash():
    for label in vr.display_labels():
        assert "—" not in label, f"{label!r} still carries the superseded em dash"
        assert " - " in label, f"{label!r} is missing the ASCII hyphen separator"


def test_the_labels_are_unique_so_one_never_shadows_another():
    labels = vr.display_labels()
    assert len(labels) == len(set(labels)) == 16


@pytest.mark.parametrize("label", MAINTAINER_LABELS)
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
    assert [entry.backend for entry in vr.VOICES] == BACKENDS


def test_the_voice_ids_are_unchanged_and_still_in_the_same_order():
    assert [entry.voice_id for entry in vr.VOICES] == VOICE_IDS


def test_the_timing_presets_are_still_the_approved_values():
    """Against the literal table the Phase 8 gate froze, not against the helpers.

    Comparing a row to ``_edge_preset(...)`` would pass even if a helper *default*
    were edited, because both sides would move together. ``EXPECTED_VOICES`` spells
    every millisecond out, so a changed default fails here.
    """
    from test_chatterbox_boundaries import EXPECTED_VOICES

    twelve = [entry.timing_preset for entry in vr.VOICES[:12]]
    assert twelve == [preset for *_head, preset in EXPECTED_VOICES]
    # The four approved rows all take the shared preset unmodified (drop §6).
    assert [entry.timing_preset for entry in vr.VOICES[12:]] == [
        vr._chatterbox_preset()] * 4


def test_the_group_labels_are_unchanged_and_are_never_the_voice_name():
    groups = [entry.group_label for entry in vr.VOICES]
    assert groups[:7] == ["Microsoft Edge TTS — English (US)"] * 7
    assert groups[7:10] == ["Kokoro Local AI — American English"] * 3
    assert groups[10:12] == ["Kokoro Local AI — British English"] * 2
    assert groups[12:] == [vr.CHATTERBOX_GROUP_LABEL] * 4
    assert not set(groups) & set(vr.display_labels())


# --------------------------------------------------------------------------- #
# 5-6. Default identity, and the four labels that were already correct
# --------------------------------------------------------------------------- #


def test_steffan_is_still_the_default_voice_under_the_new_wording():
    assert vr.DEFAULT_VOICE_LABEL == "Edge Male - Steffan (en-US)"
    assert vr.DEFAULT_VOICE_LABEL == vr.VOICES[0].display_label
    assert vr.get_voice(vr.DEFAULT_VOICE_LABEL).voice_id == "en-US-SteffanNeural"
    assert vr.get_voice(vr.DEFAULT_VOICE_LABEL).backend == "edge"


def test_the_four_chatterbox_labels_were_already_right_and_did_not_change():
    assert [entry.display_label for entry in vr.VOICES[12:]] == CHATTERBOX_LABELS
    assert CHATTERBOX_LABELS == [
        "Chatterbox - Female 1", "Chatterbox - Female 2",
        "Chatterbox - Male 1", "Chatterbox - Male 2",
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
    for path in scripts.rglob("*.py"):
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
