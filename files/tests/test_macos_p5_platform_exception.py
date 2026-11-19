"""v0.8.0 P5-G -- the one macOS platform exception: ``setup.first-run-refuses-a-folder-too-deep`` is NOT APPLICABLE ON MACOS.

The owner approved (2026-11-18) a narrow macOS-only classification for the journey whose subject is Windows' own installation-path
limit: production ``bootstrap.install_path_problem`` returns no problem on any system but Windows, so a Mac has no refusal to show
and must not fabricate one. These tests hold the exception to exactly that:

  * the production basis is real (no problem off Windows, the refusal on Windows unchanged), and the Windows journey is untouched;
  * the reason id ``windows-only-installation-path-limit`` covers that one scenario id, keeps ``fresh-macos``, and must say why;
  * any other scenario under it, any other reason on it, an unreviewed reason, or the harness reason on a non-``control.*`` scenario
    is refused, by the map validator and by the darwin judge itself;
  * every automated counterpart completed before P5-G is still automated, nothing is pending, and the map is complete.

Pure tests: no desktop, no application, no installation.
"""

from __future__ import annotations

import copy
import inspect
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from gate_locator import GATE_DIR

sys.path.insert(0, str(GATE_DIR))
from helpers import acceptance_report as ar  # noqa: E402

sys.path.remove(str(GATE_DIR))

SCENARIO = "setup.first-run-refuses-a-folder-too-deep"
REASON = "windows-only-installation-path-limit"
POLICY = json.loads((GATE_DIR / "verification.json").read_text(encoding="utf-8"))
ACCEPTANCE = POLICY["acceptance"]
DARWIN = ACCEPTANCE["darwin_map"]
REQUIRED, OPTIONAL = ACCEPTANCE["required_scenarios"], ACCEPTANCE["optional_scenarios"]
SHA = "c" * 40

#: Every automated macOS counterpart as it stood when P5-G was made (49): none of them may become anything else.
AUTOMATED_BEFORE_P5G = [
    "control.act-crash-seen-with-the-root-released", "control.act-orphan-seen-without-the-stop", "control.disabled-target-is-refused",
    "control.forced-landing-sees-the-crash", "control.second-run-refused-by-the-lease", "control.unmapped-live-control-is-caught",
    "converter.cancel-during-encode", "converter.corrupt-source", "converter.split-by-chapter", "converter.whole-book-replace-metadata",
    "cover.center-crop", "cover.corrupt-image", "cover.letterbox-numbered-run", "cover.replace-confirmation", "inventory.live-surfaces",
    "launcher.settings-survive-relaunch", "launcher.six-tools-at-three-sizes", "launcher.switch-tools-during-work",
    "maker.build-with-chapters-and-artwork", "maker.unreadable-track", "maker.wheel-over-a-long-book", "metadata.confirmation-declined",
    "metadata.save-tags-then-clear", "metadata.unreadable-file", "mp3.typed-values-survive-first-import", "mp3.unreadable-track",
    "mp3.write-id3-then-combine", "setup.clear-downloaded-data", "setup.first-run-choices-and-cancel", "shutdown.close-during-folder-scan",
    "shutdown.converter-close-during-work", "shutdown.converter-close-forced-landing", "shutdown.cover-close-during-work",
    "shutdown.cover-close-forced-landing", "shutdown.maker-close-during-work", "shutdown.maker-close-forced-landing",
    "shutdown.metadata-close-during-work", "shutdown.metadata-close-forced-landing", "shutdown.mp3-close-during-work",
    "shutdown.mp3-close-forced-landing", "shutdown.tts-close-during-work", "shutdown.tts-close-forced-landing",
    "tts.cancel-during-narration", "tts.edge-replay-direct-file", "tts.edge-replay-folder-mixed", "tts.kokoro-local",
    "tts.pause-at-file-boundary", "tts.pdf-without-text", "tts.service-failure-then-retry"]
HARNESS = ["control.real-click-reaches-the-target", "control.lost-foreground-blocks-input", "control.covered-target-is-refused",
           "control.partly-hidden-window-is-not-pictured", "control.other-desktop-is-blocked", "control.dead-input-path-blocks"]


def problems_with(darwin):
    return ar.darwin_map_problems(darwin, REQUIRED, OPTIONAL)


# --------------------------------------------------------------------------------------------------------------------- #
#  The basis: production refuses a too-deep folder on Windows only; the Windows journey is unchanged
# --------------------------------------------------------------------------------------------------------------------- #
def test_production_has_no_installation_path_refusal_off_windows_and_keeps_it_on_windows(monkeypatch, tmp_path):
    from shared import bootstrap

    deep = tmp_path / ("x" * 240) / "Audiobook Creation Tool"
    monkeypatch.setattr(bootstrap, "IS_WINDOWS", False)
    assert bootstrap.install_path_problem(deep, long_paths=False) == "", "a Mac has no refusal to show"
    monkeypatch.setattr(bootstrap, "IS_WINDOWS", True)
    refusal = bootstrap.install_path_problem(deep, long_paths=False)
    assert "too long for Windows" in refusal and "Nothing was installed" in refusal, "Windows still refuses it, word for word"


def test_the_windows_journey_is_still_registered_and_unchanged_in_substance():
    sys.path.insert(0, str(GATE_DIR))
    try:
        import acceptance_runner
        from journeys import setup

        scenarios = acceptance_runner.load_scenarios()
    finally:
        sys.path.remove(str(GATE_DIR))
    assert SCENARIO in scenarios and SCENARIO in REQUIRED, "still a required scenario, run on Windows"
    source = inspect.getsource(setup.first_run_refusal)
    for word in ("too long for Windows", "Begin Setup", "Setup did not complete", "status=1", "windows_units"):
        assert word in source, word
    assert "darwin" not in source, "the Windows body has no macOS branch: a Mac never runs it"


# --------------------------------------------------------------------------------------------------------------------- #
#  The entry itself
# --------------------------------------------------------------------------------------------------------------------- #
def test_the_entry_is_the_reviewed_exception_and_keeps_fresh_macos():
    entry = DARWIN[SCENARIO]
    assert entry["class"] == "not-applicable" and entry["reason_id"] == REASON
    assert entry["qualification"] == "fresh-macos" and "P5-G" in entry["decided"] and "install_path_problem" in entry["why"]
    assert "pending_phase" not in entry and "evidence" not in entry
    assert ar.darwin_na_problem(SCENARIO, entry) is None
    assert ar.DARWIN_NA_SCOPE[REASON] == {"exact": (SCENARIO,), "qualification": "fresh-macos"}
    assert "fresh-macos" in POLICY["darwin_scenarios"] and "REAL CLEAN" in POLICY["darwin_scenarios"]["fresh-macos"]["evidence_classes"]


def test_the_map_is_complete_with_nothing_pending_and_every_earlier_counterpart_still_automated():
    assert problems_with(DARWIN) == []
    assert set(DARWIN) == set(REQUIRED) | set(OPTIONAL) and len(DARWIN) == 56
    assert not [sid for sid, entry in DARWIN.items() if entry.get("pending_phase")]
    automated = sorted(sid for sid, entry in DARWIN.items() if entry["class"] == "automated")
    assert automated == sorted(AUTOMATED_BEFORE_P5G)
    for sid in AUTOMATED_BEFORE_P5G:
        assert "journey-checks" in DARWIN[sid]["evidence"] and not DARWIN[sid].get("manual"), sid
    na = {sid: entry["reason_id"] for sid, entry in DARWIN.items() if entry["class"] == "not-applicable"}
    assert na == {**{sid: "windows-input-harness" for sid in HARNESS}, SCENARIO: REASON}
    assert not [sid for sid, entry in DARWIN.items() if entry["class"] == "owner-manual"]


# --------------------------------------------------------------------------------------------------------------------- #
#  Negative controls: the validator
# --------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("other", ["setup.first-run-choices-and-cancel", "setup.clear-downloaded-data", "tts.kokoro-local",
                                   "mp3.write-id3-then-combine", "control.disabled-target-is-refused", "shutdown.tts-close-during-work"])
def test_the_installation_path_reason_on_any_other_scenario_is_refused(other):
    darwin = copy.deepcopy(DARWIN)
    darwin[other] = {**DARWIN[SCENARIO]}
    assert any(other in p and "covers only" in p for p in problems_with(darwin)), other


@pytest.mark.parametrize("reason", ["windows-input-harness", "windows-only", "windows-only-installation-path-limits", "", None,
                                    "approved-exception"])
def test_any_other_reason_on_the_scenario_is_refused(reason):
    darwin = copy.deepcopy(DARWIN)
    darwin[SCENARIO] = {**DARWIN[SCENARIO], "reason_id": reason}
    assert any(SCENARIO in p for p in problems_with(darwin)), reason


def test_the_exception_without_its_fresh_macos_qualification_is_refused():
    for qualification in (None, "fresh-windows", ""):
        darwin = copy.deepcopy(DARWIN)
        darwin[SCENARIO] = {**DARWIN[SCENARIO], "qualification": qualification}
        if qualification is None:
            del darwin[SCENARIO]["qualification"]
        assert any(SCENARIO in p and "fresh-macos" in p for p in problems_with(darwin)), qualification


def test_the_harness_reason_still_covers_only_control_scenarios():
    darwin = copy.deepcopy(DARWIN)
    darwin["setup.first-run-choices-and-cancel"] = {"class": "not-applicable", "reason_id": "windows-input-harness", "why": "x"}
    assert any("Windows input harness" in p for p in problems_with(darwin))
    darwin = copy.deepcopy(DARWIN)
    darwin["control.disabled-target-is-refused"] = {"class": "not-applicable", "reason_id": "windows-input-harness", "why": "x"}
    assert problems_with(darwin) == [], "a control.* harness test may still be not applicable (the P1B rule, unchanged)"


def test_no_other_setup_scenario_can_be_made_not_applicable_by_any_reviewed_reason():
    for sid in ("setup.first-run-choices-and-cancel", "setup.clear-downloaded-data"):
        for reason in ar.DARWIN_NA_REASONS:
            darwin = copy.deepcopy(DARWIN)
            darwin[sid] = {"class": "not-applicable", "reason_id": reason, "qualification": "fresh-macos", "why": "x"}
            assert any(sid in p for p in problems_with(darwin)), (sid, reason)


# --------------------------------------------------------------------------------------------------------------------- #
#  The runner and the judge
# --------------------------------------------------------------------------------------------------------------------- #
def _runner():
    sys.path.insert(0, str(GATE_DIR))
    try:
        import acceptance_runner
    finally:
        sys.path.remove(str(GATE_DIR))
    return acceptance_runner


def _judge(tmp_path, darwin, scenarios, wanted):
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"schema_version": 1, "token": "t", "finished": True, "registered": REQUIRED + OPTIONAL,
                                  "scenarios": scenarios, "unknown": [], "runtime_before": {"r": "1"}, "runtime_after": {"r": "1"}}),
                      encoding="utf-8")
    return ar.judge_darwin(report, token="t", wanted=wanted, required=REQUIRED, optional=OPTIONAL, evidence_root=tmp_path / "evidence",
                           returncode=0, ended="exited", darwin_map=darwin, manual_evidence=None, sha=SHA)


def test_the_runner_reports_it_not_applicable_with_its_reason_and_never_runs_it():
    shape = SimpleNamespace(id=SCENARIO, tool="setup", layers=("native",), tier="adverse", summary="")
    entry = _runner()._not_run_on_macos(shape, DARWIN[SCENARIO])
    assert entry["status"] == "NOT APPLICABLE" and REASON in entry["reason"] and "install_path_problem" in entry["notes"]["applicability"]


def test_the_judge_reads_it_as_justified_and_refuses_the_same_class_anywhere_else(tmp_path):
    verdict = _judge(tmp_path, DARWIN, [], [SCENARIO])
    # Justified, and neither a pass nor a failure of the stage: with nothing else selected, nothing ran (NOT RUN, never PASS).
    assert [item["verdict"] for item in verdict.scenarios] == ["NOT APPLICABLE"] and verdict.status == "NOT RUN"
    assert verdict.scenarios[0]["requirement"] == "NOT APPLICABLE — JUSTIFIED" and REASON in verdict.scenarios[0]["reason"]
    # Handed a map that names the reason on another setup scenario, or another reason on this one, the judge itself refuses the
    # whole stage before reading any result: it validates the map it is given (darwin_map_problems), whoever hands it over.
    darwin = copy.deepcopy(DARWIN)
    darwin["setup.first-run-choices-and-cancel"] = {**DARWIN[SCENARIO]}
    verdict = _judge(tmp_path, darwin, [], ["setup.first-run-choices-and-cancel"])
    assert verdict.status == "FAIL" and "covers only" in verdict.detail and not verdict.scenarios
    darwin = copy.deepcopy(DARWIN)
    darwin[SCENARIO] = {**DARWIN[SCENARIO], "reason_id": "windows-only"}
    verdict = _judge(tmp_path, darwin, [], [SCENARIO])
    assert verdict.status == "FAIL" and "reviewed reason id" in verdict.detail


def test_a_failed_automated_counterpart_still_fails_the_stage_beside_the_exception(tmp_path):
    failed = {"id": "setup.first-run-choices-and-cancel", "status": "FAIL", "reason": "x", "layers": ["native"], "tier": "geometry",
              "sessions": ["setup"], "native_inputs": 5, "checks": [{"name": "x", "ok": False}], "screenshots": [], "notes": {"exits": []}}
    verdict = _judge(tmp_path, DARWIN, [failed], [SCENARIO, "setup.first-run-choices-and-cancel"])
    assert verdict.status != "PASS", "the exception never turns another scenario's FAIL into a pass"
