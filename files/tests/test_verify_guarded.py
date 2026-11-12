"""v0.7.0: the gate's guarded stage runs every guarded-only suite through guarded_pytest.py, and nothing else hides them.

The ordinary pytest gate leaves out exactly the suites of files/tests/guarded_groups.json; the guarded gate runs each of
them once, in a new owned tree, and passes a group only when pytest passed AND the process-lifetime guard saw no
unintended production write, no unqualified process and no network/model use. Most tests here judge synthetic guard reports
and the configuration the gate would hand the runner; the bottom section starts the real runner on a throwaway tree, because
its refusals of a bad basetemp or report had no direct test before v0.7.2.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from gate_locator import REPO_ROOT, load_gate


def load_verify():
    return load_gate("act_verify_guarded")


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


def test_the_policy_pins_the_same_membership_as_the_specification():
    """Moving a suite out of its guard takes an edit in both places, so it cannot happen as a side effect of anything."""
    verify = load_verify()
    spec = verify.load_guarded_spec()
    assert verify.load_policy()["inventory"]["guarded_membership"] == {g["name"]: g["modules"] for g in spec["groups"]}
    name, ok, detail = verify.check_guarded_specification(verify.load_policy()["inventory"]["guarded_membership"])
    assert ok and name == "guarded", detail


def test_a_specification_that_drifts_from_the_policy_fails():
    verify = load_verify()
    membership = json.loads(json.dumps(verify.load_policy()["inventory"]["guarded_membership"]))
    membership["v3-supervisor"].append("test_moved_here.py")
    _, ok, detail = verify.check_guarded_specification(membership)
    assert not ok and "differs from the policy" in detail


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
    name, ok, detail = verify.check_guarded_specification()
    assert name == "guarded" and not ok and "specification unusable" in detail and message in detail


def test_a_tree_without_a_specification_guards_nothing_but_the_guarded_gate_fails(tmp_path, monkeypatch):
    verify = load_verify()
    monkeypatch.setattr(verify, "TESTS_DIR", tmp_path)
    assert verify.guarded_modules() == [] and verify._ignore_arguments() == []
    name, ok, detail = verify.check_guarded_specification()
    assert name == "guarded" and not ok and "missing" in detail


def test_the_guarded_command_is_the_runner_under_isolated_mode_with_one_new_basetemp(tmp_path):
    verify = load_verify()
    command = verify._guarded_command(tmp_path / "c.json", tmp_path / "r.json", tmp_path / "bt", ["test_a.py"])
    assert command[1:4] == ["-I", "-B", str(verify.TESTS_DIR / "guarded_pytest.py")]
    assert command[-1] == f"--basetemp={tmp_path / 'bt'}"
    assert "-p" in command and command[command.index("-p") + 1] == "no:cacheprovider"
    for narrowing in ("-x", "-k", "-m", "--lf", "--deselect", "--maxfail"):
        assert narrowing not in command


# --------------------------------------------------------------------------- #
# The real runner on a throwaway tree: its containment, and what it protects
# --------------------------------------------------------------------------- #
@pytest.fixture
def runner_tree(tmp_path):
    """A copy of the runner in a synthetic repository, whose owned tree holds what an earlier run left."""
    root = (tmp_path / "app").resolve()
    tests = root / "files" / "tests"
    tests.mkdir(parents=True)
    for name in ("guarded_pytest.py", "write_tripwire.py"):
        shutil.copyfile(Path(__file__).with_name(name), tests / name)
    owned = root / "files" / "dev-work" / "p05b-stage4c"
    (owned / "verify-now").mkdir(parents=True)
    (owned / "verify-earlier").mkdir()
    (owned / "verify-earlier" / "report.json").write_text("earlier evidence", encoding="utf-8")
    config = owned / "verify-now" / "config.json"
    config.write_text(json.dumps({"version": 1, "process_sites": {}, "tools": {}}))
    (tests / "test_probe.py").write_text("def test_ok():\n    pass\n", encoding="utf-8")
    return root, owned, config


def run_guarded(root, owned, config, report, basetemp, test="test_probe.py"):
    return subprocess.run([sys.executable, "-I", "-B", str(root / "files" / "tests" / "guarded_pytest.py"), str(config),
                           str(report), str(root / "files" / "tests" / test), "-q", "-p", "no:cacheprovider",
                           f"--basetemp={basetemp}"], capture_output=True, text=True, timeout=60)


def test_a_clean_run_of_the_runner_records_its_identity_and_error_mode(runner_tree):
    root, owned, config = runner_tree
    report = owned / "verify-now" / "g.json"
    done = run_guarded(root, owned, config, report, owned / "stage-x")
    assert done.returncode == 0, done.stdout + done.stderr
    audit = json.loads(report.read_text())
    assert audit["outer_exit"] == 0 and audit["counts"]["passed"] == 1
    assert audit["runner_sha256"] == hashlib.sha256((root / "files/tests/guarded_pytest.py").read_bytes()).hexdigest()
    assert audit["config_sha256"] == hashlib.sha256(config.read_bytes()).hexdigest()
    if sys.platform == "win32":
        assert int(audit["error_mode"], 16) & 1


@pytest.mark.parametrize("where, message", [
    ("outside-basetemp", "basetemp must be in this checkpoint"),
    ("root-basetemp", "basetemp must be in this checkpoint"),
    ("existing-basetemp", "basetemp must not exist yet"),
    ("outside-report", "report must stay in the checkpoint"),
    ("existing-report", "report must not exist yet"),
    ("linked-basetemp", "basetemp must be in this checkpoint"),
])
def test_the_runner_refuses_a_bad_basetemp_or_report_before_running_anything(runner_tree, tmp_path, where, message):
    """Pytest clears its basetemp. Pointing it at the wrong place would destroy that place, so this is refused first."""
    root, owned, config = runner_tree
    report, basetemp = owned / "verify-now" / "g.json", owned / "stage-x"
    sentinel = None
    if where == "outside-basetemp":
        basetemp = tmp_path / "elsewhere"
    elif where == "root-basetemp":
        basetemp = owned
    elif where == "existing-basetemp":
        basetemp = owned / "verify-earlier"
        sentinel = basetemp / "report.json"
    elif where == "outside-report":
        report = tmp_path / "elsewhere.json"
    elif where == "existing-report":
        report = owned / "verify-earlier" / "report.json"
        sentinel = report
    elif where == "linked-basetemp":
        outside = tmp_path / "outside-target"
        outside.mkdir()
        sentinel = outside / "keep.txt"
        sentinel.write_text("keep", encoding="utf-8")
        try:
            if sys.platform == "win32":
                import _winapi

                _winapi.CreateJunction(str(outside), str(owned / "link"))
            else:
                (owned / "link").symlink_to(outside, target_is_directory=True)
        except (OSError, AttributeError) as exc:
            pytest.skip(f"cannot create a link here: {exc}")
        basetemp = owned / "link" / "inner"
    done = run_guarded(root, owned, config, report, basetemp)
    assert done.returncode != 0 and message in done.stderr, done.stdout + done.stderr
    if sentinel is not None:
        assert sentinel.is_file()
    if where == "existing-report":
        assert sentinel.read_text(encoding="utf-8") == "earlier evidence"


def test_a_guarded_test_cannot_write_to_an_earlier_run_or_to_the_gate(runner_tree):
    """The current run owns its own children of the qualification root. Everything else there, and the gate, is read-only."""
    root, owned, config = runner_tree
    earlier = owned / "verify-earlier" / "report.json"
    gate = root / "files" / "dev-work" / "verification-gate" / "outputs" / "some-run"
    gate.mkdir(parents=True)
    (gate / "results.json").write_text("evidence", encoding="utf-8")
    (root / "files" / "tests" / "test_writer.py").write_text(
        "from pathlib import Path\nimport pytest\n"
        f"@pytest.mark.parametrize('target', [{str(earlier)!r}, {str(gate / 'results.json')!r}])\n"
        "def test_write(target):\n    with pytest.raises(PermissionError):\n        Path(target).write_text('x')\n",
        encoding="utf-8")
    report = owned / "verify-now" / "g.json"
    done = run_guarded(root, owned, config, report, owned / "stage-x", "test_writer.py")
    audit = json.loads(report.read_text())
    assert audit["pytest_exit"] == 0, done.stdout + done.stderr
    assert len(audit["unintended_production_refusals"]) == 2 and done.returncode == 1
    assert earlier.read_text(encoding="utf-8") == "earlier evidence"
    assert (gate / "results.json").read_text(encoding="utf-8") == "evidence"


def test_the_runner_really_applies_its_isolation(runner_tree):
    """What the guarded suites rely on, read from inside a real guarded test rather than from the command line."""
    root, owned, config = runner_tree
    (root / "files" / "tests" / "test_isolation.py").write_text(
        "import os, sys, tempfile\nfrom pathlib import Path\n"
        "def test_isolated_interpreter():\n"
        "    assert sys.flags.isolated == 1 and sys.dont_write_bytecode is True\n"
        "    assert os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] == '1' and os.environ['PYTHONDONTWRITEBYTECODE'] == '1'\n"
        "def test_its_temp_is_its_own():\n"
        "    temp = Path(tempfile.gettempdir())\n"
        "    assert temp.name == 'g-process-temp' and temp == Path(os.environ['TEMP']) == Path(os.environ['TMP'])\n"
        "def test_git_cannot_reach_a_production_repository():\n"
        "    assert os.environ['GIT_CONFIG_NOSYSTEM'] == '1' and os.environ['GIT_CONFIG_GLOBAL'] == os.devnull\n"
        "    assert 'GIT_DIR' not in os.environ and 'GIT_WORK_TREE' not in os.environ\n"
        "def test_no_third_party_plugin_was_autoloaded(pytestconfig):\n"
        "    assert pytestconfig.pluginmanager.list_plugin_distinfo() == []\n",
        encoding="utf-8")
    report = owned / "verify-now" / "g.json"
    done = run_guarded(root, owned, config, report, owned / "stage-x", "test_isolation.py")
    audit = json.loads(report.read_text())
    assert done.returncode == 0 and audit["counts"]["passed"] == 4, done.stdout + done.stderr


@pytest.mark.parametrize("body, key, label", [
    ("import socket\nimport pytest\ndef test_it():\n    with pytest.raises(PermissionError):\n"
     "        socket.create_connection(('192.0.2.1', 80), timeout=1)\n", "network_model_refusals", "network/model refusal(s)"),
    ("import pytest\ndef test_it():\n    with pytest.raises(PermissionError):\n        import torch\n",
     "network_model_refusals", "network/model refusal(s)"),
    ("import pytest, subprocess, sys\ndef test_it():\n    with pytest.raises(PermissionError):\n"
     "        subprocess.run([sys.executable, '-c', 'print(1)'])\n", "unexpected_processes", "unqualified process(es)"),
])
def test_a_real_refusal_by_the_runner_fails_the_group_even_though_the_test_passed(runner_tree, body, key, label):
    """The test catches the refusal and passes; pytest exits 0. Only the guard's own record stops this being a pass."""
    root, owned, config = runner_tree
    (root / "files" / "tests" / "test_refused.py").write_text(body, encoding="utf-8")
    report = owned / "verify-now" / "g.json"
    done = run_guarded(root, owned, config, report, owned / "stage-x", "test_refused.py")
    audit = json.loads(report.read_text())
    assert audit["pytest_exit"] == 0 and audit["counts"]["passed"] == 1, done.stdout + done.stderr
    assert audit[key] and done.returncode == 1 and audit["outer_exit"] == 1
    ok, text = load_verify()._judge_group("g", done.returncode, audit)
    assert not ok and label in text


# --------------------------------------------------------------------------- #
# A refusal has to end the call that was refused
# --------------------------------------------------------------------------- #
_REFUSED_TEMPORARY = """\
import sys, tempfile
sys.path[:0] = [sys.argv[1]]
import write_tripwire
from pathlib import Path
protected = Path(sys.argv[2])
with write_tripwire.armed([protected]):
    try:
        getattr(tempfile, sys.argv[3])(dir=protected)
        print("created")
    except PermissionError:
        print("refused", len(write_tripwire.refusals))
"""
_REFUSED_SETTINGS = """\
import sys
sys.path[:0] = [sys.argv[1], sys.argv[3]]
import write_tripwire
from pathlib import Path
from shared import settings
protected = Path(sys.argv[2])
settings.use_path(protected / "settings.json")
with write_tripwire.armed([protected]):
    print("saved" if settings.set("key", "value") else "reported failure", len(write_tripwire.refusals) > 0)
"""


@pytest.mark.parametrize("call", ["mkstemp", "mkdtemp"])
def test_a_refused_temporary_name_ends_the_call_instead_of_being_retried(tmp_path, call):
    """On Windows tempfile takes a PermissionError from the OS call to mean a folder holds that name and tries the next one, up
    to TMP_MAX, which is 2**31 - 1. So a refusal at the OS call never returned: measured on HOME-PC, a refused mkstemp was still
    going after 300 s, and each attempt kept a stack, 2.8 GB in about 7 minutes. A regression that wrote a protected path through a
    temporary file stalled the whole group instead of failing the test that did it. The child is bounded, so this test cannot."""
    protected = tmp_path / "protected"
    protected.mkdir()
    done = subprocess.run([sys.executable, "-I", "-B", "-c", _REFUSED_TEMPORARY, str(Path(__file__).parent), str(protected), call],
                          capture_output=True, text=True, timeout=45)
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == ["refused", "1"]
    assert list(protected.iterdir()) == []


def test_a_refused_settings_write_comes_back_as_a_failed_save(tmp_path):
    """The application's own atomic writer goes through mkstemp, so this is the shape the hang took in practice."""
    protected = tmp_path / "protected"
    protected.mkdir()
    done = subprocess.run([sys.executable, "-I", "-B", "-c", _REFUSED_SETTINGS, str(Path(__file__).parent), str(protected),
                           str(REPO_ROOT / "scripts")], capture_output=True, text=True, timeout=45)
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == ["reported", "failure", "True"]
    assert list(protected.iterdir()) == []
