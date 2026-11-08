"""The coverage inventory held to account (plan sections 7 and 10; v0.7.2 Phases 3 and 4).

Each control starts from an inventory that passes, damages one thing, and asserts the problem that names the damage. The last part holds
the real inventory, policy, source and feature-map documents to the same rules, so a source change, a new control, a renamed test or a
dangling id cannot reach a passing changed or full run without the mapping being reviewed (this module runs in every changed run).
"""

from __future__ import annotations

import json
import shutil
import sys

import pytest

from gate_locator import GATE_DIR, REPO_ROOT

sys.path.insert(0, str(GATE_DIR))
from helpers import coverage_model as model  # noqa: E402
from helpers import inventory  # noqa: E402

sys.path.remove(str(GATE_DIR))

SCENARIOS = {"mp3.journey": {"layers": ["native", "media"]}, "control.only": {"layers": ["control"]}}
TEST_ID = "files/tests/test_x.py::test_y"
FAMILY = {"tts-audiobook": "TTS", "mp3-tool": "MP3", "m4b-converter": "CONVERTER", "m4b-maker": "MAKER", "m4b-metadata-editor": "METADATA",
          "cover-image": "COVER", "shared": "SHARED"}


def _feature(identity="ACT.X", tool="mp3-tool", *verifications, **extra) -> dict:
    return {"id": identity, "tool": tool, "release_required": True,
            "verification": {"all_of": list(verifications) or [{"kind": "behavior", "test": TEST_ID}, {"kind": "native", "scenario": "mp3.journey"},
                                                               {"kind": "media", "scenario": "mp3.journey"}]}, **extra}


def _inventory(*features) -> dict:
    tools = [_feature(f"ACT.T{index}", tool) for index, tool in enumerate(model.SIX_TOOLS)]
    return {"schema_version": 1, "inventory_reviewed": False, "features": [*tools, *features]}


def _problems(*features, collected=None) -> list[str]:
    return model.problems_in_inventory(_inventory(*features), scenarios=SCENARIOS, collected=collected)


# --------------------------------------------------------------------------- #
# The mapping rules (schema 1 and 2 alike)
# --------------------------------------------------------------------------- #
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
# Schema 2: identities, release-pending evidence, surfaces, the ledger, journeys
# --------------------------------------------------------------------------- #
V2_SCENARIOS = {"mp3.journey": {"layers": ["native", "media"], "required": True}, "control.only": {"layers": ["control"], "required": False}}
OPEN = {"id": "ACT72-901", "severity": "Minor", "title": "a known gap", "phase": 5, "status": "open", "features": []}


def _v2_feature(identity, tool="mp3-tool", *verifications, **extra) -> dict:
    return _feature(identity, tool, *verifications, source=[{"path": "scripts/x.py", "symbols": []}], **extra)


def _v2(*features, issues=(OPEN,), surfaces=None) -> dict:
    base = [_v2_feature(f"ACT.{FAMILY[tool]}.BASE", tool) for tool in model.SIX_TOOLS]
    return {"schema_version": 2, "inventory_reviewed": True, "tools": {tool: {"document": f"maps/{tool}.md"} for tool in FAMILY},
            "features": [*base, *features], "surfaces": surfaces or {"static": {}, "live": {}}, "issues": list(issues)}


def _v2_problems(coverage) -> list[str]:
    return model.problems_in_inventory(coverage, scenarios=V2_SCENARIOS, collected={TEST_ID}, qualification_scenarios=("optional-engines",))


def test_v2_the_no_change_control_has_no_problems():
    assert _v2_problems(_v2()) == []


@pytest.mark.parametrize("identity", ["ACT.mp3.lower", "ACT.NOPE.X", "ACT.MP3", "MP3.X", "ACT.MP3.TWO  WORDS"])
def test_v2_an_id_that_is_not_a_stable_feature_id_is_refused(identity):
    assert any("is not a feature id" in item for item in _v2_problems(_v2(_v2_feature(identity))))


def test_v2_a_feature_outside_the_known_tools_or_without_source_is_refused():
    assert any("is not one of the inventory's tools" in item for item in _v2_problems(_v2(_v2_feature("ACT.MP3.X", "nowhere"))))
    assert any("names no source" in item for item in _v2_problems(_v2({**_v2_feature("ACT.MP3.X"), "source": []})))


def test_v2_a_dangling_feature_id_anywhere_is_refused():
    for surfaces in ({"static": {"widget:a": "ACT.MP3.GONE"}, "live": {}}, {"static": {}, "live": {"mp3_tool": {"btn": "ACT.MP3.GONE"}}}):
        assert any("ACT.MP3.GONE" in item and "dangling" in item for item in _v2_problems(_v2(surfaces=surfaces))), surfaces
    issue = {**OPEN, "features": ["ACT.MP3.GONE"]}
    assert any("issue ACT72-901 names 'ACT.MP3.GONE'" in item for item in _v2_problems(_v2(issues=(issue,))))
    assert _v2_problems(_v2(surfaces={"static": {"widget:a": "ACT.MP3.BASE"}, "live": {"mp3_tool": {"b": "ACT.MP3.BASE"}}})) == [], "the control"


def test_v2_a_planned_gap_needs_an_open_issue_and_a_later_phase():
    good = {"kind": "planned", "gap": "follow the bottom", "phase": 6, "issue": "ACT72-901"}
    assert _v2_problems(_v2(_v2_feature("ACT.MP3.X", "mp3-tool", {"kind": "behavior", "test": TEST_ID}, good))) == [], "the control"
    for broken, needle in (({**good, "issue": None}, "must name an open issue"), ({**good, "issue": "ACT72-999"}, "must name an open issue"),
                           ({**good, "phase": 5}, "later phase"), ({**good, "gap": ""}, "what is missing")):
        assert any(needle in item for item in _v2_problems(_v2(_v2_feature("ACT.MP3.X", "mp3-tool", broken)))), broken
    closed = {**OPEN, "status": "closed"}
    assert any("must name an open issue" in item for item in _v2_problems(_v2(_v2_feature("ACT.MP3.X", "mp3-tool", good), issues=(closed,))))


def test_v2_qualification_and_owner_entries_must_be_real():
    assert any("unknown qualification scenario" in item
               for item in _v2_problems(_v2(_v2_feature("ACT.MP3.X", "mp3-tool", {"kind": "qualification", "scenario": "made-up"}))))
    assert any("owner check needs" in item for item in _v2_problems(_v2(_v2_feature("ACT.MP3.X", "mp3-tool", {"kind": "owner", "check": "listen"}))))


def test_v2_a_registered_journey_no_feature_maps_is_a_workflow_outside_the_inventory():
    scenarios = {**V2_SCENARIOS, "maker.new-journey": {"layers": ["native"], "required": True}}
    problems = model.problems_in_inventory(_v2(), scenarios=scenarios, collected={TEST_ID})
    assert problems == ["a registered journey no feature maps: maker.new-journey"]


def test_v2_a_control_journey_gives_control_evidence_only():
    assert any("does not give native evidence" in item
               for item in _v2_problems(_v2(_v2_feature("ACT.MP3.X", "mp3-tool", {"kind": "native", "scenario": "control.only"}))))
    assert _v2_problems(_v2(_v2_feature("ACT.MP3.X", "mp3-tool", {"kind": "control", "scenario": "control.only"}))) == []


def test_v2_an_owner_exception_must_cite_the_owners_approval():
    exception = {"approved_by": "owner", "scope": "x", "reason": "y", "compensating_check": "z", "review_trigger": "t", "release": "0.7.2"}
    assert any("must cite where the owner approved it" in item for item in _v2_problems(_v2(_v2_feature("ACT.MP3.X", exceptions=[exception]))))


def test_v2_release_pending_evidence_is_counted_apart_and_never_satisfied_by_a_routine_run():
    planned = {"kind": "planned", "gap": "g", "phase": 6, "issue": "ACT72-901"}
    owner = {"kind": "owner", "check": "listening", "detail": "the owner listens"}
    coverage = _v2(_v2_feature("ACT.MP3.PENDING", "mp3-tool", {"kind": "behavior", "test": TEST_ID}, owner),
                   _v2_feature("ACT.MP3.GAP", "mp3-tool", planned))
    result = model.evaluate(coverage, scenarios=V2_SCENARIOS, passed_tests={TEST_ID}, passed_scenarios={"mp3.journey"})
    assert result.required == 8 and result.mapped_required == 7 and result.unmapped_required == ["ACT.MP3.GAP"]
    assert result.satisfied_required == 7 and result.release_satisfied_required == 6 and result.unsatisfied == []
    assert result.release_pending == {"owner": ["ACT.MP3.PENDING"], "planned": ["ACT.MP3.GAP"]}
    text = "\n".join(model.report_lines(result))
    assert "with no routine evidence at all" in text and "`ACT.MP3.GAP`" in text and "nothing release-pending, satisfied here: **6 of 8**" in text


# --------------------------------------------------------------------------- #
# Source review, documents and the resolvers
# --------------------------------------------------------------------------- #
def _reviewed(**digests) -> dict:
    coverage = _v2()
    coverage["features"][0]["source"] = [{"path": path, "symbols": []} for path in digests]
    coverage["source_review"] = dict(digests)
    return coverage


def test_review_the_no_change_control():
    assert model.review_problems(_reviewed(**{"scripts/a.py": "1", "scripts/b.py": "2"}), {"scripts/a.py": "1", "scripts/b.py": "2"}) == []


def test_review_a_changed_new_removed_or_unnamed_source_file_is_named():
    coverage = _reviewed(**{"scripts/a.py": "1", "scripts/gone.py": "3"})
    problems = model.review_problems(coverage, {"scripts/a.py": "CHANGED", "scripts/new.py": "9"})
    assert any(item.startswith("scripts/a.py changed since its mapping was reviewed (features ['ACT.TTS.BASE'])") for item in problems)
    assert any(item.startswith("scripts/new.py: a source file nobody has reviewed") for item in problems)
    assert any(item.startswith("scripts/new.py: no feature names this source file") for item in problems)
    assert any(item.startswith("scripts/gone.py: reviewed, but it no longer exists") for item in problems)
    assert len(problems) == 4, problems


def test_documents_must_describe_every_feature_and_name_only_real_ones(tmp_path):
    coverage = _v2()
    text = "\n".join(f"`{feature['id']}`" for feature in coverage["features"])
    documents = {f"maps/{tool}.md": text for tool in FAMILY}
    readme = " ".join(f"{tool}.md" for tool in FAMILY)
    assert model.discovery_problems(coverage, static_found=None, source_digests=None, documents=documents, readme=readme) == [], "the control"
    damaged = {**documents, "maps/mp3-tool.md": text.replace("`ACT.MP3.BASE`", "") + "\nSee ACT.MP3.NOTHING and files/tests/test_a.py::test_b"}
    problems = model.discovery_problems(coverage, static_found=None, source_digests=None, documents=damaged, readme=readme)
    assert "ACT.MP3.BASE is not described in maps/mp3-tool.md" in problems
    assert "maps/mp3-tool.md mentions ACT.MP3.NOTHING, which is no feature (a dangling id)" in problems
    assert "maps/mp3-tool.md names an exact test id; the mapping lives only in coverage.json" in problems
    missing = model.discovery_problems(coverage, static_found=None, source_digests=None, documents={**documents, "maps/shared.md": None},
                                       readme=readme.replace("shared.md", ""))
    assert "tool shared: its feature-map document maps/shared.md does not exist" in missing
    assert "the feature-map README does not list maps/shared.md" in missing


def test_a_deleted_or_renamed_test_is_seen_without_collecting(tmp_path):
    module = tmp_path / "files" / "tests" / "test_sample.py"
    module.parent.mkdir(parents=True)
    module.write_text("class Base:\n    def test_inherited(self):\n        pass\n\n\nclass TestThing(Base):\n    def test_method(self):\n        pass\n\n\n"
                      "def test_plain():\n    pass\n", encoding="utf-8")
    resolve = inventory.test_resolver(tmp_path)
    for good in ("files/tests/test_sample.py::test_plain", "files/tests/test_sample.py::test_plain[param-1]",
                 "files/tests/test_sample.py::TestThing::test_method", "files/tests/test_sample.py::TestThing::test_inherited"):
        assert resolve(good) is None, good
    assert "defines no test_renamed" in resolve("files/tests/test_sample.py::test_renamed")
    assert "does not exist" in resolve("files/tests/test_gone.py::test_plain")


def test_a_real_test_renamed_in_a_copy_is_dead_and_the_unchanged_copy_resolves(tmp_path):
    real = _real()[0]
    test_id = next(item["test"] for feature in real["features"] for item in model.verifications_of(feature) if item["kind"] == "behavior")
    module, _, rest = test_id.partition("::")
    name = rest.split("::")[-1].split("[")[0]
    copy = tmp_path / module
    copy.parent.mkdir(parents=True)
    shutil.copyfile(REPO_ROOT / module, copy)
    assert inventory.test_resolver(tmp_path)(test_id) is None, "the no-change control"
    copy.write_text(copy.read_text(encoding="utf-8").replace(f"def {name}(", f"def {name}_renamed(", 1), encoding="utf-8")
    inventory._tree.cache_clear()
    assert "defines no" in inventory.test_resolver(tmp_path)(test_id)


def test_a_symbol_that_does_not_exist_is_refused(tmp_path):
    (tmp_path / "m.py").write_text("X = 1\nclass A:\n    def b(self):\n        def c():\n            pass\n", encoding="utf-8")
    exists = inventory.symbol_resolver(tmp_path)
    assert all(exists("m.py", symbol) for symbol in ("X", "A", "A.b", "A.b.c"))
    assert not exists("m.py", "A.gone") and not exists("Setup_and_Run-x.bat", "anything")


def test_a_real_source_change_without_a_restamp_is_caught_and_names_its_features(tmp_path):
    coverage = _real()[0]
    digests = inventory.source_digests()
    assert model.review_problems(coverage, digests) == [], "the no-change control: the real source against the real stamps"
    path = "scripts/mp3/mp3_tool.py"
    copy = tmp_path / "mp3_tool.py"
    copy.write_bytes((REPO_ROOT / path).read_bytes() + b"\n# a change nobody reviewed\n")
    problems = model.review_problems(coverage, {**digests, path: inventory.digest(copy)})
    assert len(problems) == 1 and problems[0].startswith(f"{path} changed since its mapping was reviewed") and "ACT.MP3." in problems[0]


def test_restamp_stamps_only_what_it_is_given(tmp_path):
    target = tmp_path / "coverage.json"
    shutil.copyfile(GATE_DIR / "coverage.json", target)
    with pytest.raises(SystemExit, match="needs the paths you reviewed"):
        inventory.restamp([], coverage_file=target)
    with pytest.raises(SystemExit, match="is not application source"):
        inventory.restamp(["README.md"], coverage_file=target)
    before = json.loads(target.read_text(encoding="utf-8"))
    tampered = {**before, "source_review": {**before["source_review"], "scripts/mp3/mp3_tool.py": "0" * 64}}
    target.write_text(json.dumps(tampered), encoding="utf-8")
    done = inventory.restamp(["scripts/mp3/mp3_tool.py"], coverage_file=target)
    after = json.loads(target.read_text(encoding="utf-8"))
    assert after["source_review"] == before["source_review"] and "ACT.MP3." in done[0], "only the named stamp moved, back to the real digest"


# --------------------------------------------------------------------------- #
# The real files
# --------------------------------------------------------------------------- #
def _real() -> tuple[dict, dict]:
    return (json.loads((GATE_DIR / "coverage.json").read_text(encoding="utf-8")), json.loads((GATE_DIR / "verification.json").read_text(encoding="utf-8")))


def test_the_real_inventory_is_reviewed_and_has_no_problems():
    """The maintenance check itself, on the real inventory: discovered surfaces, review stamps, documents, ids, tests, scenarios, symbols.
    A full run also checks every test id against the exact collection; the live index is checked by inventory.live-surfaces."""
    coverage, policy = _real()
    assert coverage["schema_version"] == 2 and coverage["inventory_reviewed"] is True
    assert inventory.problems(coverage, policy) == []


def test_the_real_policy_requires_the_reviewed_inventory_and_runs_this_module_on_every_change():
    _, policy = _real()
    assert policy["coverage"]["require_reviewed_inventory"] is True, "turning this off would let an unreviewed inventory pass the gate"
    assert "files/tests/test_verification_coverage.py" in policy["changed"]["always"]
    assert {"files/tests/test_verification_coverage.py", "files/tests/test_surface_discovery.py"} <= set(policy["required_self_tests"])
    assert all(item.get("id") != "coverage-inventory" for item in policy["later_phase_requirements"]), "Phase 4 delivered it"


def test_the_real_inventory_maps_all_six_tools_to_native_and_media_evidence():
    coverage, _ = _real()
    for tool in model.SIX_TOOLS:
        kinds = {item["kind"] for feature in coverage["features"] if feature["tool"] == tool for item in model.verifications_of(feature)}
        assert {"native", "media", "behavior"} <= kinds, tool


def test_the_real_inventory_has_no_exception_and_every_gap_is_visible():
    """No owner has approved an exception, so there is none; a required feature with no routine evidence must say why, as an open issue."""
    coverage, _ = _real()
    assert all(not feature.get("exceptions") for feature in coverage["features"])
    open_issues = {issue["id"] for issue in coverage["issues"] if issue["status"] == "open"}
    for feature in coverage["features"]:
        if feature.get("release_required") and not model.routine_of(feature):
            planned = [item for item in model.verifications_of(feature) if item["kind"] == "planned"]
            assert planned and all(item["issue"] in open_issues for item in planned), feature["id"]


def test_the_real_policy_requires_a_complete_journey_for_each_tool():
    _, policy = _real()
    acceptance = policy["acceptance"]
    assert acceptance["required_tools"] == list(model.SIX_TOOLS)
    assert len(acceptance["required_scenarios"]) >= 40
    assert acceptance["optional_scenarios"] == ["tts.kokoro-local"], "an optional scenario needs a declared applicability rule; do not widen this quietly"
