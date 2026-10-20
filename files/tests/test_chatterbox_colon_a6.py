"""Plan 01B checkpoint A6: why the Chatterbox colon compatibility code is retained (Decisions 2026-10-20, A6).

A6 asked whether the structural-colon ``punc_norm`` patch (mechanism A) and the 75 ms prose-colon pause (mechanism B)
can be retired now that speech preparation is on. These tests pin the text-level evidence behind the answer, through
the real production path (``prepare`` -> ``split_for_chatterbox`` -> ``split_at_prose_colon`` -> ``punc_norm``) with the
A5 mode table, so a later change that alters the evidence fails here and re-opens the question at its review point:

* With speech preparation ``off`` and ``v1`` alike, structured colons that the ambiguity and protected-span policies
  leave unexpanded still reach ``generate()``; only the patch keeps them away from the pinned wheel's blanket
  ``:`` -> ``,`` (criterion 1 unmet without it).
* Prose colons never reach the tokenizer either way; the pause after them comes only from assembly (mechanism B).
* Colon-free text is byte-identical under the patch and the wheel (criterion 3 holds while the patch stays).

No model, no audio, no network: ``files/dev-tools/chatterbox_colon_matrix.py`` traces the text only.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dev-tools"))

import chatterbox_colon_matrix as matrix  # noqa: E402

from chatterbox.tts_turbo import punc_norm as wheel_punc_norm  # noqa: E402

from tts import chatterbox_synth as cbx  # noqa: E402
from tts.quality_corpus import DIFFICULT_SHORT  # noqa: E402
from tts.speech.pipeline import SETTING_OFF, SETTING_V1, build_snapshot  # noqa: E402

SNAPSHOTS = {SETTING_OFF: build_snapshot(SETTING_OFF, user_dir=None), SETTING_V1: build_snapshot(SETTING_V1, user_dir=None)}
CASES = {case_id: source for _, case_id, source in matrix.CASES}


def trace(case_id: str, mode: str) -> dict:
    return matrix.trace(CASES[case_id], SNAPSHOTS[mode], wheel_punc_norm, None)


#: Structured colons the A5 normalizer leaves as written, by policy: cue-less times and ratios, references, URL
#: schemes and Windows paths. (structured form kept by the patch, what the wheel alone would make of it)
UNEXPANDED_IN_BOTH_MODES = [
    ("time-cue-word", "6:45", "6,45"),
    ("time-ambiguous-1:30", "1:30", "1,30"),
    ("time-ambiguous-3:15", "3:15", "3,15"),
    ("time-hms", "01:02:03", "01,02,03"),
    ("ratio-bare", "2:1", "2,1"),
    ("scripture", "3:16", "3,16"),
    ("section-ref", "4:2", "4,2"),
    ("url-https", "https://", "https,//"),
    ("url-ftp", "ftp://", "ftp,//"),
    ("url-mailto", "mailto:keeper", "mailto,keeper"),
    ("path-windows", "C:\\Users", "C,\\Users"),
]


@pytest.mark.parametrize("mode", [SETTING_OFF, SETTING_V1])
@pytest.mark.parametrize("case_id,kept,corrupted", UNEXPANDED_IN_BOTH_MODES)
def test_unexpanded_structured_colons_reach_generate_and_only_the_patch_keeps_them(case_id, kept, corrupted, mode):
    traced = trace(case_id, mode)
    (call,) = traced["calls"]
    assert kept in call["generate_input"]
    assert kept in call["patched_tokenizer_input"]
    assert corrupted in call["wheel_tokenizer_input"] and kept not in call["wheel_tokenizer_input"]
    assert traced["generate_calls"] == 1 and traced["colon_pauses_75ms"] == 0


@pytest.mark.parametrize("case_id,spoken", [
    ("time-cued", "six forty five P M"), ("time-cued-1:30", "one thirty"), ("ratio-cued", "three to one"),
])
def test_cued_times_and_ratios_are_expanded_in_v1_and_need_no_patch_there(case_id, spoken):
    on, off = trace(case_id, SETTING_V1), trace(case_id, SETTING_OFF)
    assert spoken in on["prepared"] and on["structural_colons_needing_patch"] == 0
    assert not on["patch_changes_tokenizer_input"]
    assert off["structural_colons_needing_patch"] > 0, "with preparation off the same colons still need the patch"


@pytest.mark.parametrize("mode", [SETTING_OFF, SETTING_V1])
@pytest.mark.parametrize("case_id,pauses", [
    ("prose-heading", 1), ("prose-sentence", 1), ("prose-dialogue", 2), ("prose-list", 1), ("metadata", 1),
    ("prose-end-of-string", 0),
])
def test_prose_colons_never_reach_the_tokenizer_and_their_pause_comes_from_assembly(case_id, pauses, mode):
    traced = trace(case_id, mode)
    assert traced["colon_pauses_75ms"] == pauses
    for call in traced["calls"]:
        assert ":" not in call["patched_tokenizer_input"] and ":" not in call["wheel_tokenizer_input"]
        assert call["patched_tokenizer_input"] == call["wheel_tokenizer_input"]
    assert cbx.COLON_PAUSE_MS == 75


@pytest.mark.parametrize("mode", [SETTING_OFF, SETTING_V1])
@pytest.mark.parametrize("case_id", ["colon-free", "colon-free-numbers"])
def test_colon_free_text_is_byte_identical_under_the_patch_and_the_wheel(case_id, mode):
    traced = trace(case_id, mode)
    assert traced["generate_calls"] == 1 and traced["colon_pauses_75ms"] == 0
    assert not traced["patch_changes_tokenizer_input"]


def test_difficult_short_still_depends_on_the_patch_with_preparation_on():
    assert CASES["difficult-short"] == DIFFICULT_SHORT.text
    off, on = trace("difficult-short", SETTING_OFF), trace("difficult-short", SETTING_V1)
    assert (off["chunks"], off["generate_calls"], off["colon_pauses_75ms"]) == (4, 4, 0)
    assert (on["chunks"], on["generate_calls"], on["colon_pauses_75ms"]) == (4, 4, 0)
    assert off["structural_colons_needing_patch"] == 4  # 6:45, 7:15, 3:1, https://
    assert on["structural_colons_needing_patch"] == 3  # 7:15 is expanded; 6:45, 3:1 (no cue) and the URL are not
    patched = " ".join(c["patched_tokenizer_input"] for c in on["calls"])
    wheel = " ".join(c["wheel_tokenizer_input"] for c in on["calls"])
    assert all(form in patched for form in ("6:45", "3:1", "https://"))
    assert all(form in wheel for form in ("6,45", "3,1", "https,//"))


def test_the_production_compatibility_code_is_still_wired():
    """A6 retained both mechanisms; their own contract tests live in test_chatterbox_colon_integration.py."""
    assert callable(cbx._ensure_structural_colon_patch) and callable(cbx._structural_colon_punc_norm)
    assert cbx.split_at_prose_colon("a: b") == ["a:", "b"]
