"""The native layer's rules, proved without a desktop (plan sections 8 and 10; v0.7.2 Phase 3).

The journeys themselves run in the gate's acceptance stage, which needs the desktop; the guards are also proved there on real windows
(``control.*``). Here is what can be settled anywhere: how a report is judged, that the observation channel cannot call anything, that the
frozen scenario list and the code agree, and that a process on the wrong desktop reads as unusable.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from gate_locator import GATE_DIR, REPO_ROOT

sys.path.insert(0, str(GATE_DIR))
from helpers import acceptance_report as judge_module  # noqa: E402

sys.path.remove(str(GATE_DIR))

TOKEN = "run-acceptance"
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
GOOD_FIXTURE = {"id": "track-1", "kind": "mp3-track", "validation": [{"name": "decodes", "ok": True}]}
TOOL = "mp3-tool"


def _entry(root: Path, identifier="mp3.journey", **overrides) -> dict:
    folder = root / identifier
    (folder / "screenshots").mkdir(parents=True, exist_ok=True)
    (folder / "screenshots" / "done.png").write_bytes(PNG)
    (folder / "app-actions.jsonl").write_text("{}\n", encoding="utf-8")
    entry = {"id": identifier, "tool": TOOL, "layers": ["native", "media"], "tier": "journey", "status": "PASS", "reason": "", "seconds": 1.0,
             "checks": [{"name": "output", "ok": True, "detail": ""}], "outputs": [{"name": "a.mp3", "bytes": 10, "sha256": "ab"}],
             "fixtures": [GOOD_FIXTURE], "screenshots": [{"path": f"{identifier}/screenshots/done.png", "name": "done.png"}], "native_inputs": 4,
             "sessions": ["app"], "notes": {}}
    entry.update(overrides)
    return entry


def _write(tmp_path: Path, entries: list[dict], **overrides) -> Path:
    report = {"schema_version": 1, "token": TOKEN, "registered": [item["id"] for item in entries], "scenarios": entries, "finished": True, "unknown": [],
              "runtime_before": {"runtime_data": "x"}, "runtime_after": {"runtime_data": "x"}}
    report.update(overrides)
    path = tmp_path / "acceptance.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def _judge(tmp_path, entries, *, token=TOKEN, returncode=0, ended="exited", wanted=None, required=None, optional=(), tools=(TOOL,), whole=True, **overrides):
    ids = [item["id"] for item in entries]
    path = _write(tmp_path, entries, **overrides)
    return judge_module.judge(path, token=token, wanted=ids if wanted is None else wanted, required=ids if required is None else required,
                              optional=list(optional), evidence_root=tmp_path, returncode=returncode, ended=ended, required_tools=list(tools), whole_set=whole)


def test_the_no_change_control_a_complete_scenario_passes(tmp_path):
    verdict = _judge(tmp_path, [_entry(tmp_path)])
    assert verdict.status == "PASS", verdict.detail


def test_no_report_is_not_run_and_never_a_pass(tmp_path):
    verdict = judge_module.judge(tmp_path / "absent.json", token=TOKEN, wanted=["a"], required=["a"], optional=[], evidence_root=tmp_path, returncode=0,
                                 ended="exited", required_tools=[], whole_set=True)
    assert verdict.status == "NOT RUN" and "left no report" in verdict.detail


def test_a_truncated_report_is_a_failure(tmp_path):
    path = tmp_path / "acceptance.json"
    path.write_text('{"schema_version": 1, "tok', encoding="utf-8")
    verdict = judge_module.judge(path, token=TOKEN, wanted=["a"], required=["a"], optional=[], evidence_root=tmp_path, returncode=0, ended="exited",
                                 required_tools=[], whole_set=True)
    assert verdict.status == "FAIL" and "cannot be read" in verdict.detail


def test_a_report_copied_from_another_run_is_refused(tmp_path):
    verdict = _judge(tmp_path, [_entry(tmp_path)], token="another-run")
    assert verdict.status == "FAIL" and "copied or stale" in verdict.detail


def test_a_required_scenario_that_never_reported_is_not_run(tmp_path):
    entries = [_entry(tmp_path)]
    verdict = _judge(tmp_path, entries, wanted=["mp3.journey", "absent.one"], required=["mp3.journey", "absent.one"], registered=["mp3.journey", "absent.one"])
    assert verdict.status == "NOT RUN" and "absent.one" in verdict.detail


def test_a_status_that_contradicts_its_own_checks_is_a_failure(tmp_path):
    verdict = _judge(tmp_path, [_entry(tmp_path, checks=[{"name": "tag", "ok": False, "detail": "wrong"}])])
    assert verdict.status == "FAIL" and "failed checks" in verdict.detail


def test_a_finished_report_from_a_runner_that_exited_badly_is_a_failure(tmp_path):
    verdict = _judge(tmp_path, [_entry(tmp_path)], returncode=1)
    assert verdict.status == "FAIL" and "disagree" in verdict.detail


def test_a_runner_that_timed_out_is_a_failure_whatever_its_report_says(tmp_path):
    verdict = _judge(tmp_path, [_entry(tmp_path)], ended="timeout", returncode=None)
    assert verdict.status == "FAIL" and "did not finish" in verdict.detail


def test_passing_with_no_checks_is_not_a_pass(tmp_path):
    verdict = _judge(tmp_path, [_entry(tmp_path, checks=[])])
    assert verdict.status == "FAIL" and "without checking" in verdict.detail


def test_native_evidence_needs_real_input(tmp_path):
    verdict = _judge(tmp_path, [_entry(tmp_path, native_inputs=0)])
    assert verdict.status == "FAIL" and "no real input" in verdict.detail


def test_native_evidence_needs_its_action_log(tmp_path):
    entry = _entry(tmp_path)
    (tmp_path / entry["id"] / "app-actions.jsonl").unlink()
    verdict = _judge(tmp_path, [entry])
    assert verdict.status == "FAIL" and "action log" in verdict.detail


def test_a_missing_screenshot_is_missing_evidence(tmp_path):
    verdict = _judge(tmp_path, [_entry(tmp_path, screenshots=[])])
    assert verdict.status == "FAIL" and "no screenshot" in verdict.detail
    entry = _entry(tmp_path)
    (tmp_path / entry["id"] / "screenshots" / "done.png").unlink()
    verdict = _judge(tmp_path, [entry])
    assert verdict.status == "FAIL" and "is missing" in verdict.detail


def test_a_screenshot_that_is_not_an_image_is_refused(tmp_path):
    entry = _entry(tmp_path)
    (tmp_path / entry["id"] / "screenshots" / "done.png").write_bytes(b"not a picture")
    verdict = _judge(tmp_path, [entry])
    assert verdict.status == "FAIL" and "not an image" in verdict.detail


def test_a_media_claim_needs_validated_fixtures_and_inspected_outputs(tmp_path):
    assert "no validated fixture" in _judge(tmp_path, [_entry(tmp_path, fixtures=[])]).detail
    bad = {"id": "x", "kind": "m4b", "validation": [{"name": "decodes", "ok": False}]}
    assert "no passing validation" in _judge(tmp_path, [_entry(tmp_path, fixtures=[bad])]).detail
    fake = {"id": "x", "kind": "fake", "validation": [{"name": "exists", "ok": True}]}
    assert "cannot back a real-media claim" in _judge(tmp_path, [_entry(tmp_path, fixtures=[fake])]).detail
    assert "no inspected output" in _judge(tmp_path, [_entry(tmp_path, outputs=[])]).detail
    assert "no digest" in _judge(tmp_path, [_entry(tmp_path, outputs=[{"name": "a.mp3", "bytes": 0, "sha256": ""}])]).detail


def test_a_blocked_desktop_is_blocked_rather_than_a_pass_or_a_failure(tmp_path):
    verdict = _judge(tmp_path, [_entry(tmp_path, status="BLOCKED", reason="ForegroundLost: elsewhere")])
    assert verdict.status == "BLOCKED"
    whole = _judge(tmp_path, [], wanted=["mp3.journey"], required=["mp3.journey"], blocked="DesktopUnavailable: locked")
    assert whole.status == "BLOCKED" and "neither a pass" in whole.detail


def test_failure_outranks_blocked_and_both_stay_named(tmp_path):
    entries = [_entry(tmp_path, "a.one", status="FAIL", reason="bad"), _entry(tmp_path, "b.two", status="BLOCKED", reason="locked")]
    verdict = _judge(tmp_path, entries, tools=())
    assert verdict.status == "FAIL" and "a.one" in verdict.detail and "b.two" in verdict.detail


def test_a_tool_with_no_complete_journey_stops_a_whole_run(tmp_path):
    verdict = _judge(tmp_path, [_entry(tmp_path)], tools=(TOOL, "cover-image"))
    assert verdict.status == "FAIL" and "cover-image has no complete native and real-output journey" in verdict.detail


def test_an_adverse_only_tool_does_not_count_as_complete(tmp_path):
    verdict = _judge(tmp_path, [_entry(tmp_path, tier="adverse")])
    assert verdict.status == "FAIL" and "no complete" in verdict.detail


def test_writes_outside_the_run_are_a_failure(tmp_path):
    verdict = _judge(tmp_path, [_entry(tmp_path)], runtime_after={"runtime_data": "changed"})
    assert verdict.status == "FAIL" and "runtime data" in verdict.detail


def test_a_scenario_cannot_appear_or_vanish_without_a_policy_edit(tmp_path):
    verdict = _judge(tmp_path, [_entry(tmp_path)], registered=["mp3.journey", "sneaked.in"])
    assert verdict.status == "FAIL" and "sneaked.in" in verdict.detail


def test_a_scenario_reported_twice_is_refused(tmp_path):
    entry = _entry(tmp_path)
    assert "reported twice" in _judge(tmp_path, [entry, entry], wanted=[entry["id"]], required=[entry["id"]], registered=[entry["id"]]).detail


def test_a_required_scenario_cannot_be_called_not_applicable(tmp_path):
    verdict = _judge(tmp_path, [_entry(tmp_path, status="NOT APPLICABLE", reason="no engine")])
    assert verdict.status == "FAIL" and "may not be not applicable" in verdict.detail


def test_an_optional_scenario_needs_evidence_to_be_not_applicable(tmp_path):
    good = _entry(tmp_path)
    absent = _entry(tmp_path, "tts.optional", tool="tts", status="NOT APPLICABLE", reason="no engine")
    entries = [good, absent]
    ids = [good["id"], absent["id"]]
    bad = _judge(tmp_path, entries, wanted=ids, required=[good["id"]], optional=[absent["id"]])
    assert bad.status == "FAIL" and "no evidence of why" in bad.detail
    absent["notes"] = {"applicability": "the package is not installed"}
    fine = _judge(tmp_path, entries, wanted=ids, required=[good["id"]], optional=[absent["id"]])
    assert fine.status == "PASS", fine.detail


def test_a_forced_shutdown_arm_needs_a_real_collection_on_a_worker(tmp_path):
    exit_ok = {"exit_status": 0, "orphans": [], "windows_after": []}
    entry = _entry(tmp_path, "shutdown.x-forced", layers=["native", "shutdown"], tier="shutdown", outputs=[], fixtures=[], notes={"exits": [exit_ok]})
    assert "no record of a full collection" in _judge(tmp_path, [entry], tools=()).detail
    entry["notes"]["forced_collection"] = {"full_passes_on_worker": 1}
    assert _judge(tmp_path, [entry], tools=()).status == "PASS"


def test_an_unclean_exit_cannot_pass_a_shutdown_journey(tmp_path):
    for facts in ({"exit_status": 0x80000003, "orphans": [], "windows_after": []}, {"exit_status": 0, "orphans": [{"pid": 1}], "windows_after": []},
                  {"exit_status": 0, "orphans": [], "windows_after": [{"hwnd": 1}]}):
        entry = _entry(tmp_path, "shutdown.y", layers=["native", "shutdown"], tier="shutdown", outputs=[], fixtures=[], notes={"exits": [facts]})
        assert "not clean" in _judge(tmp_path, [entry], tools=()).detail, facts


# --------------------------------------------------------------------------- #
# The observation channel may look and may not act
# --------------------------------------------------------------------------- #
def _channel():
    sys.path.insert(0, str(GATE_DIR / "adapters" / "windows"))
    try:
        import channel
    finally:
        sys.path.pop(0)
    return channel


def test_a_key_path_reaches_attributes_and_indexes():
    channel = _channel()

    class Thing:
        def __init__(self):
            self.buttons = {"add": "the button"}
            self.rows = ["first", "second"]

    assert channel.follow(Thing(), "buttons[add]") == "the button"
    assert channel.follow(Thing(), "rows[1]") == "second"


def test_a_key_path_has_no_way_to_call_anything():
    channel = _channel()

    class Thing:
        calls = 0

        def business(self):
            Thing.calls += 1
            return "done"

    method = channel.follow(Thing(), "business")
    assert callable(method) and Thing.calls == 0, "following a path returned the method and did not call it"
    for attempt in ("business()", "business(1)", "__class__", "__init__.__globals__"):
        with pytest.raises(channel.KeyPathError):
            channel.follow(Thing(), attempt)
    assert Thing.calls == 0


def test_only_the_test_launcher_starts_the_channel_and_nothing_shipped_imports_it():
    import ast

    from source_probe import application_python_files

    test_only = {"adapters", "journeys", "channel", "app_launcher", "app_session", "native_input", "control_target", "acceptance_runner"}
    for path in application_python_files():
        for node in ast.walk(ast.parse(Path(path).read_text(encoding="utf-8"))):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            assert not {name.split(".")[0] for name in names} & test_only, f"{path} imports a test-only module: {names}"


# --------------------------------------------------------------------------- #
# The frozen list, and the desktop
# --------------------------------------------------------------------------- #
def _runner_list() -> dict:
    done = subprocess.run([sys.executable, "-I", "-B", str(GATE_DIR / "acceptance_runner.py"), "--list"], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_registered_scenarios_are_exactly_the_policys():
    policy = json.loads((GATE_DIR / "verification.json").read_text(encoding="utf-8"))["acceptance"]
    assert set(_runner_list()) == {*policy["required_scenarios"], *policy["optional_scenarios"]}


def test_each_tool_has_a_complete_journey_and_an_adverse_one_and_both_shutdown_arms():
    listing = _runner_list()
    for tool in ("tts-audiobook", "mp3-tool", "m4b-converter", "m4b-maker", "m4b-metadata-editor", "cover-image"):
        mine = [item for item in listing.values() if item["tool"] == tool]
        assert any(item["tier"] == "journey" and {"native", "media"} <= set(item["layers"]) for item in mine), tool
        assert any(item["tier"] == "adverse" for item in mine), tool
        assert sum(item["tier"] == "shutdown" for item in mine) == 2, tool


@pytest.mark.skipif(sys.platform != "win32", reason="a Windows desktop")
def test_a_process_on_another_desktop_reads_as_unusable():
    """A process cannot lock the session from a test, but a process whose desktop is not the input desktop is the position a lock puts it in."""
    probe = ("import ctypes, ctypes.wintypes as w, json, sys\n"
             f"sys.path.insert(0, {str(GATE_DIR)!r})\n"
             "from adapters.windows import native_input as n\n"
             "u = n.user32\n"
             "u.CreateDesktopW.restype = w.HANDLE\n"
             "u.CreateDesktopW.argtypes = [w.LPCWSTR, w.LPCWSTR, w.LPVOID, w.DWORD, w.DWORD, w.LPVOID]\n"
             "u.SetThreadDesktop.argtypes = [w.HANDLE]\n"
             "d = u.CreateDesktopW('ACT-test-' + str(__import__('os').getpid()), None, None, 0, 0x10000000, None)\n"
             "assert d and u.SetThreadDesktop(d)\n"
             "s = n.desktop_status()\n"
             "print(json.dumps({'ok': s.ok, 'reason': s.reason}))\n")
    done = subprocess.run([sys.executable, "-I", "-c", probe], capture_output=True, text=True, timeout=60)
    reading = json.loads(next(line for line in done.stdout.splitlines() if line.startswith("{")))
    assert reading["ok"] is False and "desktop" in reading["reason"], reading


@pytest.mark.skipif(sys.platform != "win32", reason="a Windows named mutex")
def test_the_desktop_lease_is_exclusive_and_released(tmp_path):
    sys.path.insert(0, str(GATE_DIR))
    try:
        from adapters.windows import native_input as native
    finally:
        sys.path.remove(str(GATE_DIR))
    name = f"Local\\ACT-Test-Lease-{tmp_path.name}"
    with native.DesktopLease(name):
        with pytest.raises(native.DesktopUnavailable, match="holds the desktop lease"):
            with native.DesktopLease(name):
                pass
    with native.DesktopLease(name):
        pass


def test_the_policy_and_this_layout_are_where_the_plan_says():
    for relative in ("verify.py", "acceptance_runner.py", "adapters/windows/native_input.py", "adapters/windows/app_launcher.py", "journeys/common.py",
                     "fixtures/manifest.json", "baselines/approved.json", "helpers/media_oracle.py"):
        assert (GATE_DIR / relative).is_file(), relative
    assert (REPO_ROOT / "files" / "tests" / "test_real_media_acceptance.py").is_file()


def test_a_change_reaches_its_tools_journeys_and_a_gate_change_reaches_them_all():
    sys.path.insert(0, str(GATE_DIR))
    try:
        from helpers import selection
    finally:
        sys.path.remove(str(GATE_DIR))
    known = ["mp3.a", "cover.b", "shutdown.mp3-c"]
    routes = {"scripts/mp3/": ["mp3.a", "shutdown.mp3-c"], "files/dev-work/verification-gate/adapters/": "all"}
    assert selection.journeys_for_changes(["scripts/mp3/mp3_tool.py"], routes, known) == ["mp3.a", "shutdown.mp3-c"]
    assert selection.journeys_for_changes(["files/dev-work/verification-gate/adapters/windows/channel.py"], routes, known) == known
    assert selection.journeys_for_changes(["README.md"], routes, known) == []
    assert selection.journeys_for_changes(["scripts/mp3/x.py"], {"scripts/mp3/": ["retired.id"]}, known) == [], "an id the policy no longer knows is not run"
