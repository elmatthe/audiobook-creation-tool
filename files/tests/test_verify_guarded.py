"""v0.7.0: verify.py's guarded gate runs every guarded-only suite through guarded_pytest.py, and nothing else hides them.

The ordinary pytest gate leaves out exactly the suites of files/tests/guarded_groups.json; the guarded gate runs each of
them once, in a new owned tree, and passes a group only when pytest passed AND the process-lifetime guard saw no
unintended production write, no unqualified process and no network/model use. The guarded runner itself is never
started here: these tests judge synthetic guard reports and the configuration verify.py would hand it.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
VERIFY_PATH = REPO_ROOT / "scripts" / "verify.py"


def load_verify():
    spec = importlib.util.spec_from_file_location("act_verify_guarded", VERIFY_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def clean_report(**changes):
    report = {"outer_exit": 0, "pytest_exit": 0, "counts": {"passed": 12},
              "unintended_production_refusals": [], "unexpected_processes": [], "network_model_refusals": []}
    report.update(changes)
    return report


def test_every_guarded_suite_runs_in_exactly_one_group_and_the_ordinary_gate_leaves_out_only_those():
    verify = load_verify()
    spec = verify.load_guarded_spec()
    modules = [m for group in spec["groups"] for m in group["modules"]]
    assert len(modules) == len(set(modules))
    assert all((verify.TESTS_DIR / m).is_file() for m in modules)
    assert verify._ignore_arguments() == [f"--ignore={verify.TESTS_DIR / m}" for m in modules]
    # Every other test module stays in the ordinary gate.
    ordinary = {p.name for p in verify.TESTS_DIR.glob("test_*.py")} - set(modules)
    assert "test_verify_guarded.py" in ordinary and len(ordinary) > 100


def test_each_group_basetemp_prefix_is_one_its_fixtures_accept():
    spec = load_verify().load_guarded_spec()
    prefixes = {group["name"]: group["basetemp_prefix"] for group in spec["groups"]}
    # The planning bridge needs stage4d2d-, the read-only context stage4d2d-m1-, the supervisor stage4d2b-.
    assert prefixes == {"v3-planning": "stage4d2d-m1-", "v3-supervisor": "stage4d2b-"}


def test_a_clean_report_passes_and_names_its_counts():
    ok, text = load_verify()._judge_group("g", 0, clean_report())
    assert ok and text == "g: 12 passed"


@pytest.mark.parametrize("returncode, changes, expected", [
    (1, {"outer_exit": 1}, "exit 1/outer 1"),
    (0, {"pytest_exit": 1}, "pytest exit 1"),
    (0, {"counts": {}}, "no test passed"),
    (0, {"counts": {"passed": 3, "failed": 2}}, "2 failed"),
    (0, {"counts": {"passed": 3, "error": 1}}, "1 error"),
    (0, {"unintended_production_refusals": [{}]}, "1 unintended production write(s)"),
    (0, {"unexpected_processes": [{"argv": ["lscpu"]}]}, "1 unqualified process(es)"),
    (0, {"network_model_refusals": [{}, {}]}, "2 network/model refusal(s)"),
])
def test_any_failure_or_guard_finding_fails_the_group(returncode, changes, expected):
    ok, text = load_verify()._judge_group("g", returncode, clean_report(**changes))
    assert not ok and expected in text


def test_a_missing_or_unreadable_guard_report_is_never_a_pass(tmp_path):
    verify = load_verify()
    for report in (verify._read_guard_report(tmp_path / "absent.json"),
                   verify._read_guard_report((tmp_path / "bad.json", (tmp_path / "bad.json").write_text("{"))[0])):
        ok, text = verify._judge_group("g", 0, report)
        assert not ok and "guard report" in text


def test_the_run_configuration_pins_each_reviewed_source_by_its_current_bytes():
    verify = load_verify()
    spec = verify.load_guarded_spec()
    config = verify.guarded_run_config(spec)
    assert config["version"] == 1 and set(config["process_sites"]) == set(spec["process_sites"])
    for relative, entry in config["process_sites"].items():
        assert entry["sha256"] == hashlib.sha256((REPO_ROOT / relative).read_bytes()).hexdigest()
        assert entry["functions"] == spec["process_sites"][relative]
    # NumPy's Windows-unavailable SVE probe is refused before launch only when its caller is pinned.
    assert config["process_sites"][".venv/Lib/site-packages/numpy/testing/_private/utils.py"]["functions"] == \
        ["check_support_sve"]
    assert config["spacy_fixture"] == spec["spacy_fixture"]


def test_a_missing_reviewed_source_fails_rather_than_being_dropped():
    verify = load_verify()
    spec = json.loads(json.dumps(verify.load_guarded_spec()))
    spec["process_sites"]["scripts/shared/no_such_module.py"] = ["f"]
    with pytest.raises(verify.GuardedSpecError, match="missing"):
        verify.guarded_run_config(spec)


@pytest.mark.parametrize("damage, message", [
    ("duplicate", "more than one group"),
    ("absent", "is not a test module"),
    ("path", "is not a test module"),
    ("version", "unknown version"),
])
def test_a_damaged_specification_is_refused(tmp_path, monkeypatch, damage, message):
    verify = load_verify()
    tests = tmp_path / "tests"
    tests.mkdir()
    for name in ("test_a.py", "test_b.py"):
        (tests / name).write_text("def test_x():\n    pass\n")
    groups = [{"name": "one", "basetemp_prefix": "p-", "modules": ["test_a.py"]},
              {"name": "two", "basetemp_prefix": "q-", "modules": ["test_b.py"]}]
    spec = {"version": 1, "groups": groups, "process_sites": {}}
    if damage == "duplicate":
        groups[1]["modules"].append("test_a.py")
    elif damage == "absent":
        groups[1]["modules"] = ["test_c.py"]
    elif damage == "path":
        groups[1]["modules"] = ["../tests/test_b.py"]
    else:
        spec["version"] = 2
    (tests / verify.GUARDED_SPEC_NAME).write_text(json.dumps(spec))
    monkeypatch.setattr(verify, "TESTS_DIR", tests)
    with pytest.raises(verify.GuardedSpecError, match=message):
        verify.load_guarded_spec()
    name, ok, detail = verify.check_guarded()
    assert name == "guarded" and not ok and message in detail
    name, ok, detail = verify.check_pytest()
    assert not ok and "specification unusable" in detail


def test_a_tree_without_a_specification_guards_nothing_but_the_guarded_gate_fails(tmp_path, monkeypatch):
    verify = load_verify()
    monkeypatch.setattr(verify, "TESTS_DIR", tmp_path)
    assert verify.guarded_modules() == [] and verify._ignore_arguments() == []
    name, ok, detail = verify.check_guarded()
    assert name == "guarded" and not ok and "missing" in detail


def test_the_guarded_command_is_the_runner_under_isolated_mode_with_one_new_basetemp(tmp_path):
    verify = load_verify()
    command = verify._guarded_command(tmp_path / "c.json", tmp_path / "r.json", tmp_path / "bt", ["test_a.py"])
    assert command[1:4] == ["-I", "-B", str(verify.TESTS_DIR / "guarded_pytest.py")]
    assert command[-1] == f"--basetemp={tmp_path / 'bt'}"
    for narrowing in ("-x", "-k", "-m", "--lf", "--deselect", "--maxfail"):
        assert narrowing not in command
