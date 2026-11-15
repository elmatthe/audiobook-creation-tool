"""v0.8.x P1B -- the darwin gate cannot report a false PASS (plan section 14.3, MAC-027, MAC-045).

Pure tests of the policy and the judgement, on every platform: the real ``verification.json`` maps every acceptance
scenario exactly once on macOS and its skip policies are exact; and negative controls show that an unmapped scenario,
a malformed entry, a counterpart that passed without evidence, an automated counterpart that waits on an owner's signed
record (no longer allowed since the owner's P1B closeout instruction of 2026-11-15), a required scenario not yet
runnable, an unknown skip reason and a skip count over its limit each keep the darwin stage from passing. The pictures and
the dialog contract are in test_macos_p1b_closeout_gate.py. Windows' judgement and its policy are untouched.
"""

from __future__ import annotations

import json
import re
import sys

import pytest

from gate_locator import GATE_DIR, REPO_ROOT, load_gate

sys.path.insert(0, str(GATE_DIR))
from helpers import acceptance_report as ar  # noqa: E402
from helpers import pytest_reports  # noqa: E402

sys.path.remove(str(GATE_DIR))

POLICY = json.loads((GATE_DIR / "verification.json").read_text(encoding="utf-8"))
ACCEPTANCE = POLICY["acceptance"]
REQUIRED, OPTIONAL = ACCEPTANCE["required_scenarios"], ACCEPTANCE["optional_scenarios"]
SHA = "a" * 40


# --------------------------------------------------------------------------- #
#  The real policy
# --------------------------------------------------------------------------- #
def test_the_real_darwin_map_maps_every_scenario_exactly_once():
    assert ar.darwin_map_problems(ACCEPTANCE["darwin_map"], REQUIRED, OPTIONAL) == []
    assert len(REQUIRED) == 55 and OPTIONAL == ["tts.kokoro-local"], "Windows' acceptance set is unchanged"


def test_not_applicable_on_macos_is_only_the_windows_input_harness():
    na = sorted(sid for sid, entry in ACCEPTANCE["darwin_map"].items() if entry["class"] == "not-applicable")
    assert na == sorted(["control.real-click-reaches-the-target", "control.lost-foreground-blocks-input",
                         "control.covered-target-is-refused", "control.partly-hidden-window-is-not-pictured",
                         "control.other-desktop-is-blocked", "control.dead-input-path-blocks"])


def test_the_five_tools_shutdown_and_behaviour_controls_are_automated_now():
    darwin = ACCEPTANCE["darwin_map"]
    now = {sid for sid, entry in darwin.items() if entry["class"] == "automated" and not entry.get("pending_phase")}
    for prefix in ("mp3.", "converter.", "maker.", "metadata.", "cover.", "control.disabled", "control.second-run",
                   "control.forced-landing", "control.act-", "control.unmapped"):
        assert any(sid.startswith(prefix) for sid in now), prefix
    assert {sid for sid in REQUIRED if sid.startswith("shutdown.") and "tts" not in sid} <= now
    assert {sid for sid in darwin if sid.startswith(("tts.", "shutdown.tts-"))} == \
        {sid for sid, entry in darwin.items() if entry.get("pending_phase") == "P2"}


def test_every_skip_rule_compiles_and_the_windows_rules_stay_exact():
    for platform, rules in POLICY["skip_policy"].items():
        assert len({rule["id"] for rule in rules}) == len(rules), platform
        for rule in rules:
            re.compile(rule["pattern"])
            assert isinstance(rule["max"], int) and rule["max"] >= 0
    win = {rule["id"]: rule for rule in POLICY["skip_policy"]["win32"]}
    assert win["native-macos-only"]["max"] == 39, "the Aqua rule Windows had is unchanged"
    assert re.fullmatch(win["native-macos-p1b"]["pattern"],
                        "native macOS only (P1B): Aqua Tk 9 shell, POSIX containment and macOS filesystem checks")
    assert not re.search(win["native-macos-p1b"]["pattern"], "native macOS only (P1B): something else")


def test_fresh_macos_is_a_darwin_scenario_and_windows_keeps_its_frozen_set():
    verify = load_gate("act_verify_p1b_gate")

    assert verify.SCENARIO_NAMES == ("m4b-scaling", "edge-low-memory", "optional-engines", "fresh-windows")
    assert set(POLICY["darwin_scenarios"]) == set(verify.DARWIN_SCENARIO_NAMES) == {
        "fresh-macos", "macos-native-dialogs", "macos-visual", "macos-kx10"}
    assert "runner" not in POLICY["darwin_scenarios"]["fresh-macos"], "REAL CLEAN stays the owner's run of the procedure (P7c)"
    assert (REPO_ROOT / POLICY["darwin_scenarios"]["fresh-macos"]["procedure"]).is_file()


def test_every_feature_has_exactly_one_macos_standing_derived_from_the_census():
    """MAC-027: coverage.json's macOS block covers every feature once, with a reviewed class; none is left to review."""
    coverage = json.loads((GATE_DIR / "coverage.json").read_text(encoding="utf-8"))
    block = coverage["macos"]
    assert re.fullmatch(r"[0-9a-f]{40}", block["census"]["sha"])
    assert sorted(block["features"]) == sorted(feature["id"] for feature in coverage["features"])
    for feature_id, entry in block["features"].items():
        kind = entry["class"]
        assert kind in ("native", "native-with-failures", "pending", "not-applicable"), (feature_id, kind)
        assert entry.get("why"), feature_id
        if kind == "native":
            assert entry["tests"].get("pass", 0) > 0 and not entry["tests"].get("fail"), feature_id
        if kind == "native-with-failures":
            assert entry.get("failing"), feature_id
        if kind == "pending":
            assert re.fullmatch(r"P[2-7][A-Ca-c]?(/P[2-7][A-Ca-c]?)*", entry.get("phase", "")), feature_id


# --------------------------------------------------------------------------- #
#  Negative controls: the map
# --------------------------------------------------------------------------- #
def test_an_unmapped_or_misclassified_scenario_is_a_problem():
    darwin = dict(ACCEPTANCE["darwin_map"])
    removed = darwin.pop("mp3.write-id3-then-combine")
    assert any("unmapped" in p for p in ar.darwin_map_problems(darwin, REQUIRED, OPTIONAL))
    darwin["mp3.write-id3-then-combine"] = {"class": "not-applicable", "reason_id": "windows-input-harness"}
    assert any("not applicable on macOS only" in p for p in ar.darwin_map_problems(darwin, REQUIRED, OPTIONAL))
    darwin["mp3.write-id3-then-combine"] = {"class": "skipped"}
    assert any("is not one of" in p for p in ar.darwin_map_problems(darwin, REQUIRED, OPTIONAL))
    darwin["mp3.write-id3-then-combine"] = removed
    assert ar.darwin_map_problems(darwin, REQUIRED, OPTIONAL) == []
    assert ar.darwin_map_problems(None, REQUIRED, OPTIONAL) == ["there is no acceptance.darwin_map"]
    assert ar.darwin_map_problems(None, ["mp3.write-id3-then-combine"], []) == ["there is no acceptance.darwin_map"]
    assert ar.darwin_map_problems(None, [], []) == [], "a policy with no scenarios has nothing to map"


# --------------------------------------------------------------------------- #
#  Negative controls: the judgement
# --------------------------------------------------------------------------- #
def _entry(sid: str, **extra) -> dict:
    return {"id": sid, "status": "PASS", "reason": "", "tool": "mp3-tool", "tier": "journey", "layers": ["native", "media"],
            "checks": [{"name": "a check", "ok": True}], "native_inputs": 4, "sessions": ["app"],
            "fixtures": [{"id": "f", "kind": "generated", "validation": [{"ok": True}]}],
            "outputs": [{"name": "o.mp3", "sha256": "x", "bytes": 10}], "notes": {"exits": []}, **extra}


def _judge(tmp_path, entries, *, wanted=None, signed=(), darwin_map=None, runtime_after=None, report_extra=None,
           returncode=0, required_tools=(), whole_set=False):
    darwin_map = darwin_map or {
        "mp3.write-id3-then-combine": {"class": "automated", "journey": "mp3.write-id3-then-combine", "evidence": ["journey-checks"]},
        "tts.edge-replay-direct-file": {"class": "automated", "journey": "tts.edge-replay-direct-file", "pending_phase": "P2"},
        "control.real-click-reaches-the-target": {"class": "not-applicable", "reason_id": "windows-input-harness"},
    }
    required = [sid for sid in darwin_map if sid != "tts.kokoro-local"]
    evidence = tmp_path / "evidence"
    (evidence / "mp3.write-id3-then-combine").mkdir(parents=True)
    (evidence / "mp3.write-id3-then-combine" / "app-actions.jsonl").write_text("{}\n")
    manual = tmp_path / "manual"
    for item in signed:
        (manual / SHA).mkdir(parents=True, exist_ok=True)
        (manual / SHA / f"{item.replace(':', '--')}.json").write_text(json.dumps({"sha": SHA, "signed_by": "owner", "result": "PASS"}))
    report = {"schema_version": 1, "token": "t", "finished": True, "scenarios": entries, "registered": required,
              "runtime_before": {"x": 1}, "runtime_after": runtime_after or {"x": 1}, **(report_extra or {})}
    path = tmp_path / "acceptance.json"
    path.write_text(json.dumps(report))
    return ar.judge_darwin(path, token="t", wanted=wanted or required, required=required, optional=[], evidence_root=evidence,
                           returncode=returncode, ended="exited", darwin_map=darwin_map, manual_evidence=manual, sha=SHA,
                           required_tools=list(required_tools), whole_set=whole_set)


def test_a_required_scenario_pending_its_phase_keeps_the_stage_from_passing(tmp_path):
    judged = _judge(tmp_path, [_entry("mp3.write-id3-then-combine")])
    verdicts = {item["id"]: item["verdict"] for item in judged.scenarios}
    assert verdicts == {"mp3.write-id3-then-combine": "PASS", "tts.edge-replay-direct-file": "NOT RUN",
                        "control.real-click-reaches-the-target": "NOT APPLICABLE"}
    assert judged.status == "NOT RUN"


def test_only_a_complete_map_with_its_evidence_passes(tmp_path):
    darwin_map = {"mp3.write-id3-then-combine": {"class": "automated", "journey": "mp3.write-id3-then-combine",
                                                 "evidence": ["journey-checks"]},
                  "control.real-click-reaches-the-target": {"class": "not-applicable", "reason_id": "windows-input-harness"}}
    judged = _judge(tmp_path, [_entry("mp3.write-id3-then-combine")], darwin_map=darwin_map)
    assert judged.status == "PASS", judged.detail
    assert "1 automated PASS" in judged.detail and "1 not applicable" in judged.detail
    labels = {item["id"]: item["requirement"] for item in judged.scenarios}
    assert labels == {"mp3.write-id3-then-combine": "AUTOMATED PASS",
                      "control.real-click-reaches-the-target": "NOT APPLICABLE — JUSTIFIED"}


def test_an_automated_counterpart_may_not_wait_on_an_owner_signature(tmp_path):
    """P1B closeout: no fabricated or real owner signature stands in for an automated check; the map itself is refused."""
    darwin_map = {"mp3.write-id3-then-combine": {"class": "automated", "journey": "mp3.write-id3-then-combine",
                                                 "evidence": ["journey-checks"], "manual": ["macos-checklist:native-dialogs"]}}
    judged = _judge(tmp_path, [_entry("mp3.write-id3-then-combine")], signed=["macos-checklist:native-dialogs"], darwin_map=darwin_map)
    assert judged.status == "FAIL" and "may not wait on an owner's signed record" in judged.detail


@pytest.mark.parametrize("damage", ["no checks", "failed check", "worker thread called Tk", "status says N/A"])
def test_a_counterpart_that_passed_without_its_evidence_fails(tmp_path, damage):
    entry = _entry("mp3.write-id3-then-combine")
    if damage == "no checks":
        entry["checks"] = []
    elif damage == "failed check":
        entry["checks"] = [{"name": "x", "ok": False}]
    elif damage == "worker thread called Tk":
        entry["notes"] = {"exits": [{"exit_status": 0, "orphans": [], "windows_after": [], "tk_off_thread": [{"call": "call"}]}]}
    else:
        entry["status"] = "NOT APPLICABLE"
    darwin_map = {"mp3.write-id3-then-combine": {"class": "automated", "journey": "mp3.write-id3-then-combine",
                                                 "evidence": ["journey-checks"]}}
    assert _judge(tmp_path, [entry], darwin_map=darwin_map).status == "FAIL"


def test_a_run_that_changed_the_real_runtime_data_fails(tmp_path):
    darwin_map = {"mp3.write-id3-then-combine": {"class": "automated", "journey": "mp3.write-id3-then-combine",
                                                 "evidence": ["journey-checks"]}}
    judged = _judge(tmp_path, [_entry("mp3.write-id3-then-combine")], darwin_map=darwin_map, runtime_after={"x": 2})
    assert judged.status == "FAIL"


_ONE = {"mp3.write-id3-then-combine": {"class": "automated", "journey": "mp3.write-id3-then-combine", "evidence": ["journey-checks"]}}


@pytest.mark.parametrize("damage, words", [
    ({"report_extra": {"registered": ["mp3.write-id3-then-combine", "sneaked.in"]}}, "sneaked.in"),
    ({"report_extra": {"token": "an-old-run"}}, "copied or stale"),
    ({"returncode": 1}, "disagree"),
    ({"report_extra": {"unknown": ["typo.journey"]}}, "unknown scenarios"),
    ({"required_tools": ["mp3-tool", "cover-image"], "whole_set": True}, "cover-image has no complete"),
], ids=["registered-but-not-in-the-policy", "stale-token", "finished-but-exited-1", "unknown-asked-for", "tool-without-a-journey"])
def test_the_report_itself_is_held_to_the_windows_judges_rules(tmp_path, damage, words):
    entries = [_entry("mp3.write-id3-then-combine")]
    judged = _judge(tmp_path, entries, darwin_map=_ONE, **damage)
    assert judged.status == "FAIL" and words in judged.detail, judged.detail
    assert _judge(tmp_path / "control", entries, darwin_map=_ONE, required_tools=["mp3-tool"], whole_set=True).status == "PASS"


def test_a_tool_whose_journeys_are_mapped_to_a_later_phase_is_not_run_not_failed(tmp_path):
    darwin_map = dict(_ONE)
    darwin_map["tts.edge-replay-direct-file"] = {"class": "automated", "journey": "tts.edge-replay-direct-file",
                                                 "pending_phase": "P2", "tool": "tts-audiobook"}
    judged = _judge(tmp_path, [_entry("mp3.write-id3-then-combine")], darwin_map=darwin_map,
                    required_tools=["mp3-tool", "tts-audiobook"], whole_set=True)
    assert judged.status == "NOT RUN" and judged.problems == [], judged.detail


def test_an_unmapped_scenario_fails_before_anything_is_read(tmp_path):
    judged = ar.judge_darwin(tmp_path / "missing.json", token="t", wanted=REQUIRED, required=REQUIRED, optional=OPTIONAL,
                             evidence_root=tmp_path, returncode=0, ended="exited", darwin_map={}, manual_evidence=None, sha=SHA)
    assert judged.status == "FAIL" and "unmapped" in judged.detail


# --------------------------------------------------------------------------- #
#  Negative controls: the skip policy
# --------------------------------------------------------------------------- #
def test_an_unknown_darwin_skip_and_one_over_its_limit_fail():
    darwin = POLICY["skip_policy"]["darwin"]
    problems, _ = pytest_reports.skip_policy_problems([{"id": "t::x", "reason": "a reason nobody reviewed"}], [], darwin)
    assert problems and problems[0].startswith("unexpected skip")
    rule = next(rule for rule in darwin if rule["id"] == "empty-parameter-set")
    over = [{"id": f"t::{i}", "reason": "got empty parameter set for (x)"} for i in range(rule["max"] + 1)]
    problems, _ = pytest_reports.skip_policy_problems(over, [], darwin)
    assert any("more than" in problem for problem in problems)
    problems, tally = pytest_reports.skip_policy_problems(over[:rule["max"]], [], darwin)
    assert problems == [] and tally == {"empty-parameter-set": rule["max"]}
