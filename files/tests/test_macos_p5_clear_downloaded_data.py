"""v0.8.0 P5 -- the macOS counterpart of ``setup.clear-downloaded-data`` cannot PASS on a wrong root, missing evidence, an
incomplete cleanup or a changed bystander.

Pure tests of ``helpers/cleanup_journey.py`` (what the journey decides with) and of the darwin judge's evidence rules for this
scenario, on every platform: no desktop, no application, nothing deleted. The positive control asks a real disposable copy of the
committed code, in ``tmp_path``, where it would clean; every negative control changes one fact and must be refused.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from gate_locator import GATE_DIR, REPO_ROOT

sys.path.insert(0, str(GATE_DIR))
from helpers import acceptance_report as ar  # noqa: E402
from helpers import cleanup_journey as cj  # noqa: E402

sys.path.remove(str(GATE_DIR))

SCENARIO = "setup.clear-downloaded-data"
SHA = "b" * 40


@pytest.fixture(scope="module")
def copy_world(tmp_path_factory):
    """A disposable copy of the committed ``scripts/`` in a scratch folder, and what its own code says about it."""
    work = Path(os.path.realpath(tmp_path_factory.mktemp("cdd")))
    copy = work / "copy" / "app"
    listed = subprocess.run(["git", "-C", str(REPO_ROOT), "ls-files", "-z", "--", "scripts"], capture_output=True, check=True).stdout
    for name in [item for item in listed.decode("utf-8").split("\0") if item]:
        (copy / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / name, copy / name)
    outside = work / "outside"
    cj.seed(copy, outside, links=False)  # the four items present, as in the journey; the links are judged from ``links`` below
    env = {key: value for key, value in os.environ.items() if key not in ("PYTHONPATH", "PYTHONHOME")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    facts = cj.copy_facts(copy, env=env)
    links = {name: str(outside / target) for name, target in cj.LINKS.items()}
    return {"work": work, "copy": copy, "facts": facts, "outside": outside, "links": links,
            "protected": cj.protected_locations(REPO_ROOT, home=work / "home")}


def judge(world, *, facts=None, copy=None, scratch=None, links=None, real_root=REPO_ROOT):
    return cj.isolation_problems(facts if facts is not None else world["facts"], copy=copy or world["copy"],
                                 scratch=scratch or world["work"], real_root=real_root, protected=world["protected"],
                                 outside=world["outside"], links=world["links"] if links is None else links)


def with_fact(world, **changes):
    return {**json.loads(json.dumps(world["facts"])), **changes}


# --------------------------------------------------------------------------------------------------------------------- #
#  Isolation: the preflight
# --------------------------------------------------------------------------------------------------------------------- #
def test_a_real_copy_names_only_itself_and_an_interpreter_outside_every_target(copy_world):
    facts = copy_world["facts"]
    assert Path(facts["repo_root"]) == copy_world["copy"]
    assert judge(copy_world) == []


def test_a_root_that_is_not_the_copy_is_refused(copy_world):
    problems = judge(copy_world, facts=with_fact(copy_world, repo_root=str(REPO_ROOT)))
    assert any("says its root is" in p for p in problems)


def test_a_target_in_the_real_checkout_is_refused(copy_world):
    targets = {**copy_world["facts"]["targets"], "virtual_environment": str(REPO_ROOT / ".venv")}
    problems = judge(copy_world, facts=with_fact(copy_world, targets=targets))
    assert any("virtual_environment" in p and "real" in p for p in problems)


def test_a_refused_or_missing_target_is_refused(copy_world):
    targets = {**copy_world["facts"]["targets"], "portable_binaries": {"refused": "a link"}}
    assert any("portable_binaries" in p for p in judge(copy_world, facts=with_fact(copy_world, targets=targets)))
    assert any("exactly the four" in p for p in judge(copy_world, facts=with_fact(copy_world, offered=["application_logs"])))


def test_a_state_folder_inside_a_target_or_outside_the_copy_is_refused(copy_world):
    inside_target = str(copy_world["copy"] / ".venv" / "maintenance")
    assert any("state folder" in p for p in judge(copy_world, facts=with_fact(copy_world, state_dir=inside_target)))
    elsewhere = str(REPO_ROOT / "files" / "runtime-data" / "maintenance")
    assert any("state folder" in p for p in judge(copy_world, facts=with_fact(copy_world, state_dir=elsewhere)))


def test_a_helper_that_is_not_the_copys_own_is_refused(copy_world):
    real_helper = str(REPO_ROOT / "scripts" / "shared" / "cleanup_worker.py")
    assert any("cleanup helper" in p for p in judge(copy_world, facts=with_fact(copy_world, coordinator_script=real_helper)))


def test_a_helper_interpreter_inside_the_copy_or_a_real_target_or_missing_is_refused(copy_world):
    inside = str(copy_world["copy"] / ".venv" / "bin" / "python3")
    assert any("inside the copy" in p for p in judge(copy_world, facts=with_fact(copy_world, interpreter=inside)))
    real_venv = str(REPO_ROOT / ".venv" / "bin" / "python3")
    assert any("cleanup target" in p for p in judge(copy_world, facts=with_fact(copy_world, interpreter=real_venv)))
    assert any("no Python" in p for p in judge(copy_world, facts=with_fact(copy_world, interpreter=None)))


def test_a_copy_outside_the_scratch_or_overlapping_the_checkout_is_refused(copy_world):
    assert any("not inside the gate's scratch" in p for p in judge(copy_world, scratch=copy_world["work"] / "elsewhere"))
    assert any("overlap" in p for p in judge(copy_world, real_root=copy_world["copy"].parent))


def test_a_link_the_journey_did_not_seed_or_one_into_the_checkout_is_refused(copy_world):
    planted = {**copy_world["links"], "files/escape": str(REPO_ROOT / "files")}
    assert any("did not seed" in p for p in judge(copy_world, links=planted))
    turned = {**copy_world["links"], ".venv/bin/escape-file-link": str(REPO_ROOT / "README.md")}
    assert any("outside the scratch sentinel" in p or "not the sentinel" in p for p in judge(copy_world, links=turned))
    assert any("missing" in p for p in judge(copy_world, links={}))


# --------------------------------------------------------------------------------------------------------------------- #
#  The outcome: only what was ticked, all of it, and nothing beside it
# --------------------------------------------------------------------------------------------------------------------- #
BEFORE = {".venv/pyvenv.cfg": "sha256:1", ".venv/bin/escape-file-link": "link:/s/sentinel.txt", "files/bin/tool.bin": "sha256:2",
          "files/runtime-data/models/blob": "sha256:3", "files/runtime-data/logs/session_2026-01-01.log": "sha256:4",
          "files/runtime-data/logs/app_now.log": "sha256:5", "files/keep-me.txt": "sha256:6", "scripts/launcher.py": "sha256:7"}
GOOD_AFTER = {"files/bin/": "dir", "files/runtime-data/models/": "dir", "files/runtime-data/logs/session_2026-01-01.log": "sha256:4",
              "files/runtime-data/logs/app_now.log": "sha256:5b", "files/runtime-data/maintenance/cleanup-result.json": "sha256:8",
              "files/keep-me.txt": "sha256:6", "scripts/launcher.py": "sha256:7"}
PINNED = ["files/runtime-data/logs/session_2026-01-01.log"]


def test_the_right_outcome_passes():
    assert cj.outcome_problems(BEFORE, GOOD_AFTER, pinned=PINNED) == []


def test_an_incomplete_cleanup_cannot_pass():
    after = {**GOOD_AFTER, "files/runtime-data/models/blob": "sha256:3"}
    assert any("incomplete cleanup" in p for p in cj.outcome_problems(BEFORE, after, pinned=PINNED))
    after = {**GOOD_AFTER, ".venv/bin/escape-file-link": "link:/s/sentinel.txt"}
    assert any("incomplete cleanup" in p for p in cj.outcome_problems(BEFORE, after, pinned=PINNED))


def test_an_unticked_or_protected_entry_changed_or_removed_cannot_pass():
    changed_log = {**GOOD_AFTER, "files/runtime-data/logs/session_2026-01-01.log": "sha256:x"}
    assert any("changed" in p for p in cj.outcome_problems(BEFORE, changed_log, pinned=PINNED))
    removed_code = {key: value for key, value in GOOD_AFTER.items() if key != "scripts/launcher.py"}
    assert any("removed" in p for p in cj.outcome_problems(BEFORE, removed_code, pinned=PINNED))


def test_something_new_outside_where_the_application_writes_cannot_pass():
    assert any("something new" in p for p in cj.outcome_problems(BEFORE, {**GOOD_AFTER, "files/surprise.txt": "sha256:9"}, pinned=PINNED))
    assert any("inside a cleared item" in p for p in cj.outcome_problems(BEFORE, {**GOOD_AFTER, "files/bin/new.bin": "sha256:9"},
                                                                         pinned=PINNED))


def test_only_the_engine_leases_own_empty_locks_may_appear_and_they_are_its_names():
    from shared import engine_lease

    expected = sorted([f"files/runtime-data/qwen3/{name}" for name in engine_lease.ORDER]
                      + [f"files/runtime-data/omnivoice/{name}" for name in engine_lease.OMNIVOICE_ORDER])
    assert sorted(cj.LEASE_LOCKS) == expected
    locks = {name: cj.EMPTY_FILE for name in cj.LEASE_LOCKS}
    assert cj.outcome_problems(BEFORE, {**GOOD_AFTER, **locks}, pinned=PINNED) == []
    full = {**GOOD_AFTER, **locks, cj.LEASE_LOCKS[0]: "sha256:not-empty"}
    assert any("with content" in p for p in cj.outcome_problems(BEFORE, full, pinned=PINNED))
    other = {**GOOD_AFTER, "files/runtime-data/qwen3/other.lock": cj.EMPTY_FILE}
    assert any("something new" in p for p in cj.outcome_problems(BEFORE, other, pinned=PINNED))


def test_a_changed_bystander_or_sentinel_cannot_pass():
    assert cj.tree_problems("the bystander", {"a": "sha256:1"}, {"a": "sha256:1"}) == []
    assert cj.tree_problems("the bystander", {"a": "sha256:1"}, {"a": "sha256:2"})
    assert cj.tree_problems("the bystander", {"a": "sha256:1", "b": "dir"}, {"a": "sha256:1"})


def test_the_digest_sees_bytes_links_and_empty_folders(tmp_path):
    (tmp_path / "d").mkdir()
    (tmp_path / "f.txt").write_bytes(b"one")
    first = cj.content_digest(tmp_path)
    assert set(first) == {"d/", "f.txt"}
    (tmp_path / "f.txt").write_bytes(b"two")
    assert cj.content_digest(tmp_path)["f.txt"] != first["f.txt"]


# --------------------------------------------------------------------------------------------------------------------- #
#  Evidence: what the darwin judge requires of this scenario's PASS
# --------------------------------------------------------------------------------------------------------------------- #
def _entry(**changes) -> dict:
    return {"id": SCENARIO, "status": "PASS", "layers": ["native"], "tier": "journey", "sessions": ["app"], "native_inputs": 9,
            "checks": [{"name": "isolation preflight", "ok": True}], "screenshots": [], "notes": {"exits": []}, **changes}


def _with_actions(tmp_path: Path) -> Path:
    (tmp_path / SCENARIO).mkdir(parents=True, exist_ok=True)
    (tmp_path / SCENARIO / "app-actions.jsonl").write_text(json.dumps({"kind": "input", "action": "click"}) + "\n", encoding="utf-8")
    return tmp_path


def test_a_pass_without_a_real_picture_is_refused(tmp_path):
    problems = ar._darwin_evidence_problems(_entry(), _with_actions(tmp_path), ("journey-checks", "real-screenshots"), SHA)
    assert any("no picture" in p for p in problems)


def test_a_pass_with_a_failed_check_or_no_input_is_refused(tmp_path):
    root = _with_actions(tmp_path)
    failed = _entry(checks=[{"name": "only the ticked items were removed", "ok": False}])
    assert any("failed checks" in p for p in ar._darwin_evidence_problems(failed, root, ("journey-checks",), SHA))
    assert any("no real input" in p for p in ar._darwin_evidence_problems(_entry(native_inputs=0), root, ("journey-checks",), SHA))


def test_dialog_contract_cannot_be_claimed_by_a_journey_that_answers_no_file_dialog(tmp_path):
    """Clear Downloaded Data opens no file or folder dialog (its confirmation is the application's own window, checked by the journey),
    so the dialog-contract evidence class would fail it by construction; its map entry names journey checks and real pictures."""
    problems = ar._darwin_evidence_problems(_entry(), _with_actions(tmp_path), ("dialog-contract",), SHA)
    assert any("answered no file or folder dialog" in p for p in problems)


# --------------------------------------------------------------------------------------------------------------------- #
#  The map: the transition P5-E made, and only that one
# --------------------------------------------------------------------------------------------------------------------- #
POLICY = json.loads((GATE_DIR / "verification.json").read_text(encoding="utf-8"))
DARWIN = POLICY["acceptance"]["darwin_map"]


def test_clear_downloaded_data_is_an_automated_counterpart_now_with_the_evidence_its_pass_needs():
    entry = DARWIN[SCENARIO]
    assert entry["class"] == "automated" and entry["journey"] == SCENARIO and entry["driver"] == "adapters/macos"
    assert "pending_phase" not in entry and not entry.get("manual")
    assert entry["evidence"] == ["journey-checks", "real-screenshots"]
    assert "files/tests/test_macos_p5_clear_downloaded_data.py" in entry["tests"]
    assert ar.darwin_map_problems(DARWIN, POLICY["acceptance"]["required_scenarios"], POLICY["acceptance"]["optional_scenarios"]) == []


def test_nothing_is_pending_and_the_folder_depth_journey_is_not_applicable_on_macos():
    from types import SimpleNamespace

    sys.path.insert(0, str(GATE_DIR))
    try:
        import acceptance_runner
    finally:
        sys.path.remove(str(GATE_DIR))
    pending = {sid: entry["pending_phase"] for sid, entry in DARWIN.items() if entry.get("pending_phase")}
    assert pending == {}  # P5-F-R1 completed setup.first-run-choices-and-cancel; P5-G mapped the folder-depth journey not applicable

    def shape(sid):
        return SimpleNamespace(id=sid, tool="setup", layers=("native",), tier="journey", summary="")

    assert acceptance_runner._not_run_on_macos(shape(SCENARIO), DARWIN[SCENARIO]) is None, "it runs now"
    folder = "setup.first-run-refuses-a-folder-too-deep"
    assert acceptance_runner._not_run_on_macos(shape(folder), DARWIN[folder])["status"] == "NOT APPLICABLE"


def test_a_not_run_or_a_pass_without_evidence_for_this_scenario_is_not_an_automated_pass(tmp_path):
    """judge_darwin over a report: NOT RUN (selected, never reported) and a PASS with no picture both fail the stage."""
    required, optional = POLICY["acceptance"]["required_scenarios"], POLICY["acceptance"]["optional_scenarios"]
    root = _with_actions(tmp_path / "evidence")
    for scenarios, wanted in (([], "NOT RUN"), ([_entry()], "FAIL")):
        report = tmp_path / f"report-{wanted}.json"
        report.write_text(json.dumps({"schema_version": 1, "token": "t", "finished": True, "registered": required + optional,
                                      "scenarios": scenarios, "unknown": []}), encoding="utf-8")
        verdict = ar.judge_darwin(report, token="t", wanted=[SCENARIO], required=required, optional=optional, evidence_root=root,
                                  returncode=0, ended="exited", darwin_map=DARWIN, manual_evidence=None, sha=SHA)
        assert verdict.status != "PASS"
        assert [item["verdict"] for item in verdict.scenarios if item["id"] == SCENARIO] == [wanted]
