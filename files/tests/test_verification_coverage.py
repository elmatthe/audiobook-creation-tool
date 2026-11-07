"""The coverage inventory held to account (plan sections 7 and 10; v0.7.2 Phase 3). Phase 4 completes it; what enforces it is proved here.

Each control starts from an inventory that passes, damages one thing, and asserts the problem that names the damage.
"""

from __future__ import annotations

import json
import sys

from gate_locator import GATE_DIR, REPO_ROOT

sys.path.insert(0, str(GATE_DIR))
from helpers import coverage_model as model  # noqa: E402

sys.path.remove(str(GATE_DIR))

SCENARIOS = {"mp3.journey": {"layers": ["native", "media"]}, "control.only": {"layers": ["control"]}}
TEST_ID = "files/tests/test_x.py::test_y"


def _feature(identity="ACT.X", tool="mp3-tool", *verifications, **extra) -> dict:
    return {"id": identity, "tool": tool, "release_required": True,
            "verification": {"all_of": list(verifications) or [{"kind": "behavior", "test": TEST_ID}, {"kind": "native", "scenario": "mp3.journey"},
                                                               {"kind": "media", "scenario": "mp3.journey"}]}, **extra}


def _inventory(*features) -> dict:
    tools = [_feature(f"ACT.T{index}", tool) for index, tool in enumerate(model.SIX_TOOLS)]
    return {"schema_version": 1, "inventory_reviewed": False, "features": [*tools, *features]}


def _problems(*features, collected=None) -> list[str]:
    return model.problems_in_inventory(_inventory(*features), scenarios=SCENARIOS, collected=collected)


def test_the_no_change_control_a_sound_inventory_has_no_problems():
    assert _problems(collected={TEST_ID}) == []


def test_a_missing_tool_stops_it():
    coverage = {"features": [_feature("ACT.A", "mp3-tool")]}
    assert any("no feature maps these tools" in item and "cover-image" in item for item in
               model.problems_in_inventory(coverage, scenarios=SCENARIOS))


def test_a_required_feature_that_maps_to_nothing_stops_it():
    assert any("maps to nothing" in item for item in _problems({"id": "ACT.EMPTY", "tool": "shared", "release_required": True}))


def test_a_deleted_test_is_a_dead_id():
    assert any("dead test id" in item for item in _problems(_feature("ACT.A", "shared"), collected={"files/tests/test_x.py::test_other"}))


def test_a_module_or_glob_is_not_proof():
    bad = _feature("ACT.A", "shared", {"kind": "behavior", "test": "files/tests/test_x.py"})
    assert any("not an exact test id" in item for item in _problems(bad))


def test_an_unknown_scenario_is_dead():
    bad = _feature("ACT.A", "shared", {"kind": "native", "scenario": "nothing.here"})
    assert any("dead scenario id" in item for item in _problems(bad))


def test_a_unit_test_cannot_stand_in_for_native_or_media_evidence():
    for kind in ("native", "media"):
        bad = _feature("ACT.A", "shared", {"kind": kind, "test": TEST_ID})
        assert any("a test cannot stand in" in item for item in _problems(bad)), kind


def test_a_scenario_cannot_give_evidence_it_does_not_produce():
    bad = _feature("ACT.A", "shared", {"kind": "media", "scenario": "control.only"})
    assert any("does not give media evidence" in item for item in _problems(bad))


def test_an_agent_cannot_approve_its_own_exception():
    exception = {"approved_by": "claude", "scope": "x", "reason": "y", "compensating_check": "z", "review_trigger": "t", "release": "0.7.2"}
    assert any("not approved by the owner" in item for item in _problems(_feature("ACT.A", "shared", exceptions=[exception])))
    incomplete = {"approved_by": "owner", "reason": "y"}
    assert any("an exception without" in item for item in _problems(_feature("ACT.A", "shared", exceptions=[incomplete])))
    complete = {**exception, "approved_by": "owner"}
    assert _problems(_feature("ACT.A", "shared", exceptions=[complete]), collected={TEST_ID}) == [], "the no-change control"


def test_mapped_is_not_satisfied():
    result = model.evaluate(_inventory(), scenarios=SCENARIOS, passed_tests=set(), passed_scenarios=set())
    assert result.required == result.mapped_required == 6 and result.satisfied_required == 0 and len(result.unsatisfied) == 6


def test_every_part_of_all_of_must_have_been_satisfied():
    only_one = model.evaluate(_inventory(), scenarios=SCENARIOS, passed_tests={TEST_ID}, passed_scenarios=set())
    assert only_one.satisfied_required == 0
    both = model.evaluate(_inventory(), scenarios=SCENARIOS, passed_tests={TEST_ID}, passed_scenarios={"mp3.journey"})
    assert both.satisfied_required == 6 and both.unsatisfied == []


def test_the_report_keeps_the_measures_separate():
    result = model.evaluate(_inventory(), scenarios=SCENARIOS, passed_tests={TEST_ID}, passed_scenarios={"mp3.journey"})
    text = "\n".join(model.report_lines(result))
    assert "Required entries mapped: **6 of 6**" in text and "satisfied in this run: **6 of 6**" in text
    assert "Inventory reviewed: **False**" in text and "Line coverage: not collected" in text


# --------------------------------------------------------------------------- #
# The real files
# --------------------------------------------------------------------------- #
def _real() -> tuple[dict, dict]:
    return (json.loads((GATE_DIR / "coverage.json").read_text(encoding="utf-8")), json.loads((GATE_DIR / "verification.json").read_text(encoding="utf-8")))


def test_the_real_inventory_says_it_is_not_reviewed_yet():
    coverage, _ = _real()
    assert coverage["inventory_reviewed"] is False, "Phase 4 reviews the inventory; nothing before it may claim that"


def test_the_real_inventory_maps_all_six_tools_to_native_and_media_evidence():
    coverage, policy = _real()
    known = {*policy["acceptance"]["required_scenarios"], *policy["acceptance"]["optional_scenarios"]}
    for tool in model.SIX_TOOLS:
        kinds = {item["kind"] for feature in coverage["features"] if feature["tool"] == tool for item in model.verifications_of(feature)}
        assert {"native", "media"} <= kinds, tool
    for feature in coverage["features"]:
        for item in model.verifications_of(feature):
            if item["kind"] != "behavior":
                assert item["scenario"] in known, f"{feature['id']}: {item['scenario']}"
        for journey in feature.get("journeys", []):
            assert journey in known, f"{feature['id']}: {journey}"
        for source in feature.get("source", []):
            assert (REPO_ROOT / source["path"]).is_file(), source["path"]
        for selector in feature.get("selection", []):
            assert (REPO_ROOT / selector).is_file(), selector
    assert model.problems_in_inventory(coverage, scenarios={key: {"layers": ["native", "media"]} for key in known},
                                       required_tools=policy["acceptance"]["required_tools"]) == []


def test_the_real_policy_requires_a_complete_journey_for_each_tool():
    _, policy = _real()
    acceptance = policy["acceptance"]
    assert acceptance["required_tools"] == list(model.SIX_TOOLS)
    assert len(acceptance["required_scenarios"]) >= 40
    assert acceptance["optional_scenarios"] == ["tts.kokoro-local"], "an optional scenario needs a declared applicability rule; do not widen this quietly"
