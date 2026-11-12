"""The gate itself, proved from outside: it cannot call a bad run PASS (plan §10, v0.7.2 Phase 2).

Each test copies the real gate into a throwaway repository beside a tiny real test suite, then runs it as a separate process
from a directory outside that repository, exactly as a person would, and reads back its exit code and its evidence. Real
pytest, real guarded runner, real JUnit, real git, real Job Object. Nothing here patches the gate.

Every negative control has the same shape: the good tree passes (``test_the_known_good_tree_passes``, the no-change control),
one thing is damaged, and the test asserts the check that names that damage, not merely a non-zero exit. A control that is
stopped by something else, or that skipped its target, would otherwise look like a catch.
"""

from __future__ import annotations

import ctypes
import functools
import json
import os
import shutil
import signal
import subprocess
import sys
import textwrap
import time
import types
from pathlib import Path

import pytest

from gate_locator import GATE_DIR, REPO_ROOT, load_gate

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="the gate needs git")

TESTS_SOURCE = REPO_ROOT / "files" / "tests"
PASSING = "def test_one():\n    pass\n\n\ndef test_two():\n    pass\n"
GUARDED = "def test_guarded_one():\n    pass\n\n\ndef test_guarded_two():\n    pass\n"
WINDOWS_ONLY = pytest.mark.skipif(sys.platform != "win32", reason="Windows behaviour")


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=ACT test", "-c", "user.email=act-test@example.invalid", "-c", "commit.gpgsign=false",
         "-c", "core.autocrlf=false", *args], cwd=root, check=True, capture_output=True, text=True).stdout


class Tree:
    """A throwaway repository holding a copy of the gate and a small suite: two ordinary tests, two guarded."""

    def __init__(self, root: Path, outside: Path) -> None:
        self.root = root
        self.outside = outside
        self.tests = root / "files" / "tests"
        self.gate = root / "files" / "dev-work" / "verification-gate"
        self.outputs = self.gate / "outputs"
        self.tests.mkdir(parents=True)
        shutil.copytree(GATE_DIR, self.gate, ignore=shutil.ignore_patterns("outputs", "__pycache__"))
        for name in ("gate_session_probe.py", "guarded_pytest.py", "write_tripwire.py"):
            shutil.copyfile(TESTS_SOURCE / name, self.tests / name)
        self.write("files/tests/conftest.py", "import gate_session_probe\n\n\ndef pytest_configure(config):\n"
                                              "    gate_session_probe.register(config)\n")
        self.write("files/tests/test_ordinary.py", PASSING)
        self.write("files/tests/test_guarded.py", GUARDED)
        self.write("files/tests/guarded_groups.json", json.dumps(
            {"version": 1, "groups": [{"name": "only", "basetemp_prefix": "stage-only-", "modules": ["test_guarded.py"]}],
             "process_sites": {}, "tools": []}))
        self.write("pytest.ini", "[pytest]\ntestpaths = files/tests\nnorecursedirs = dev-work\n")
        self.write(".gitignore", "__pycache__/\n*.pyc\nfiles/dev-work/*\n!files/dev-work/verification-gate/\n"
                                 "files/dev-work/verification-gate/outputs/\n")
        # The real static gates judge this tree, so they read the real rules and the real pinned files.
        shutil.copytree(REPO_ROOT / "scripts" / "shared", root / "scripts" / "shared",
                        ignore=shutil.ignore_patterns("__pycache__"))
        for name in ("scripts/requirements.txt", "scripts/requirements-lock-windows-py312.txt", "config.toml"):
            shutil.copyfile(REPO_ROOT / name, root / name)
        self.write("scripts/launcher.py", "# the entry point config.toml names\n")
        for name in ("Briefing.md", "Decisions.md", "Handoff.md"):
            self.write(f"md-instructions/{name}", f"# {name}\n\nA real document.\n")
        self.write("md-instructions/Changelog.md", "# Changelog\n\n## [0.0.1] - 2026-01-01\n\nA real entry.\n")
        policy = json.loads((self.gate / "verification.json").read_text(encoding="utf-8"))
        policy["inventory"] = {"minimum_ordinary": 1, "minimum_guarded": {"only": 1},
                               "guarded_membership": {"only": ["test_guarded.py"]}}
        policy["required_self_tests"] = ["files/tests/test_ordinary.py"]
        policy["acceptance"] = {"required_tools": [], "required_scenarios": [], "optional_scenarios": [], "journey_routes": {}}
        policy["focused"]["required_guards"] = []
        policy["changed"]["always"] = []
        # This small tree carries a one-feature seed inventory, so it does not require the reviewed one. The real policy does
        # (test_verification_coverage pins that), and test_an_unreviewed_inventory_stops_full_and_changed_runs turns it on here.
        policy["coverage"] = {"require_reviewed_inventory": False}
        policy["process"] = {"drain_seconds": 3, "kill_wait_seconds": 10}
        policy["stages"] = {"preflight": {"timeout_seconds": 60}, "collect": {"timeout_seconds": 90, "stall_seconds": 60},
                            "pytest": {"timeout_seconds": 120, "stall_seconds": 60},
                            "guarded": {"timeout_seconds": 120, "stall_seconds": 60}}
        self.write_policy(policy)
        self.write("files/dev-work/verification-gate/coverage.json", json.dumps(
            {"schema_version": 1, "inventory_reviewed": False, "features": [
                {"id": "ACT.TEST.ONE", "selection": ["files/tests/test_ordinary.py"], "source": []}]}))
        git(root, "init", "-q")
        self.commit("fixture")

    def write(self, relative: str, text: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text), encoding="utf-8", newline="\n")
        return path

    def write_policy(self, policy: dict) -> None:
        (self.gate / "verification.json").write_text(json.dumps(policy, indent=1), encoding="utf-8", newline="\n")

    def policy(self) -> dict:
        return json.loads((self.gate / "verification.json").read_text(encoding="utf-8"))

    def commit(self, message: str = "change") -> None:
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", message)

    def run(self, *argv: str, env: dict | None = None, creationflags: int = 0, timeout: float = 240,
            script: Path | None = None) -> "Outcome":
        environment = self.environment()
        environment.update(env or {})
        before = set(self.outputs.iterdir()) if self.outputs.is_dir() else set()
        done = subprocess.run([sys.executable, str(script or (self.gate / "verify.py")), *argv], cwd=self.outside,
                              env=environment, capture_output=True, text=True, timeout=timeout, creationflags=creationflags)
        created = [path for path in self.outputs.iterdir() if path not in before] if self.outputs.is_dir() else []
        assert len(created) <= 1, created
        return Outcome(done, created[0] if created else None)

    def environment(self) -> dict:
        """What every gate this tree starts runs under. The gate's scratch lands in this tree's own temp, so each tree's is its own and can be
        looked at, and nothing reaches the real %TEMP%\\act-gate (ACT72-024: one test started the gate without this and left a folder there)."""
        environment = {key: value for key, value in os.environ.items()
                       if not key.upper().startswith(("PYTEST_", "ACT_GATE_"))}
        self.system_temp.mkdir(exist_ok=True)
        environment.update(TEMP=str(self.system_temp), TMP=str(self.system_temp), TMPDIR=str(self.system_temp))
        return environment

    @property
    def system_temp(self) -> Path:
        return self.root.parent / "tt"

    def status(self, *argv: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(self.gate / "verify.py"), "--status", *argv], cwd=self.outside,
                              capture_output=True, text=True, timeout=120)

    def full(self, **kwargs) -> "Outcome":
        return self.run("--mode", "full", **kwargs)

    def focused(self, *selectors: str, **kwargs) -> "Outcome":
        return self.run("--mode", "focused", *[f"--test={selector}" for selector in selectors], **kwargs)


class Outcome:
    def __init__(self, done: subprocess.CompletedProcess, directory: Path | None) -> None:
        self.code = done.returncode
        self.stdout = done.stdout
        self.stderr = done.stderr
        self.directory = directory

    @property
    def results(self) -> dict:
        assert self.directory is not None, self.stderr
        path = self.directory / "results.json"
        assert path.is_file(), f"no results.json: {self.stdout}\n{self.stderr}\n{list(self.directory.iterdir())}"
        return json.loads(path.read_text(encoding="utf-8"))

    def check(self, name: str) -> dict:
        found = [item for item in self.results["checks"] if item["name"] == name]
        assert found, f"no check {name}: {[c['name'] for c in self.results['checks']]}\n{self.stdout}"
        return found[0]

    def __repr__(self) -> str:
        return f"exit {self.code}\n{self.stdout}\n{self.stderr}"


@pytest.fixture(scope="session")
def template_tree(tmp_path_factory) -> Path:
    """Building one tree costs a git init and a commit; every test takes a copy of this one."""
    base = tmp_path_factory.mktemp("gt", numbered=True)
    outside = base / "cwd"
    outside.mkdir()
    Tree(base / "r", outside)
    return base / "r"


@pytest.fixture
def tree(template_tree, tmp_path_factory) -> Tree:
    # Not tmp_path: its folder is named after the test. Inside a checkout this deep, every character counts (SCRATCH_ROOT).
    base = tmp_path_factory.mktemp("g")
    root = (base / "r").resolve()
    shutil.copytree(template_tree, root)
    outside = (base / "o").resolve()
    outside.mkdir()
    instance = Tree.__new__(Tree)
    instance.root, instance.outside = root, outside
    instance.tests = root / "files" / "tests"
    instance.gate = root / "files" / "dev-work" / "verification-gate"
    instance.outputs = instance.gate / "outputs"
    return instance


# --------------------------------------------------------------------------- #
# The control: a good tree passes, from another directory, and says what ran
# --------------------------------------------------------------------------- #
def test_the_known_good_tree_passes(tree):
    outcome = tree.full()
    assert outcome.code == 0, outcome
    results = outcome.results
    assert results["status"] == "PASS" and results["lifecycle"] == "completed"
    assert results["counts"]["expected"] == 4 and results["counts"]["executed"] == 4 and results["counts"]["passed"] == 4
    assert outcome.check("partition")["status"] == "PASS" and outcome.check("inventory")["status"] == "PASS"
    assert outcome.check("guarded")["status"] == "PASS" and outcome.check("self-tests")["status"] == "PASS"
    assert (outcome.directory / "collection" / "pytest.txt").read_text(encoding="utf-8").splitlines() == [
        "files/tests/test_ordinary.py::test_one", "files/tests/test_ordinary.py::test_two"]
    assert (outcome.directory / "collection" / "guarded-only.txt").read_text(encoding="utf-8").splitlines() == [
        "files/tests/test_guarded.py::test_guarded_one", "files/tests/test_guarded.py::test_guarded_two"]
    assert "RESULT: PASS" in outcome.stdout
    assert results["scope"]["full_acceptance"] is False and results["release_ready"] is False
    assert results["cleanup"]["scratch"] is None and results["cleanup"]["temp_not_removed"] == []
    assert not list(tree.system_temp.iterdir()), "disposable scratch should go on PASS"
    assert not list((tree.root / "files/dev-work/p05b-stage4c").iterdir()), "a passing run leaves its guarded scratch"
    status = tree.status(str(outcome.directory), "--require-current")
    assert status.returncode == 0 and "status: PASS" in status.stdout and "current: exact" in status.stdout, status.stdout


_LATER = {"id": "later-thing", "phase": 9, "required": False, "detail": "a requirement a later phase delivers"}


def _with_later_requirement(tree, **overrides) -> None:
    """The real policy has none left since Phase 4 delivered the coverage inventory; the mechanism stays for the next one."""
    policy = tree.policy()
    policy["later_phase_requirements"] = [{**_LATER, **overrides}]
    tree.write_policy(policy)


def test_later_phase_requirements_are_reported_as_not_run_and_never_as_satisfied(tree):
    _with_later_requirement(tree)
    outcome = tree.full()
    assert outcome.code == 0, outcome
    later = outcome.check("requirement:later-thing")
    assert later["status"] == "NOT RUN" and later["required"] is False and "Phase 9" in later["detail"]
    assert "NOT full acceptance" in outcome.stdout and "later-thing" in outcome.stdout
    assert outcome.results["coverage"]["inventory_reviewed"] is False
    assert outcome.check("coverage-inventory")["status"] == "NOT APPLICABLE", "this tree's policy does not require the reviewed inventory"


def test_an_unreviewed_inventory_stops_full_and_changed_runs(tree):
    """The real policy's requirement, turned on in this tree: its one-feature seed is schema 1 and unreviewed, so neither run may pass."""
    policy = tree.policy()
    policy["coverage"] = {"require_reviewed_inventory": True}
    tree.write_policy(policy)
    tree.commit("require the reviewed inventory")
    full = tree.full()
    assert full.code == 1, full
    check = full.check("coverage-inventory")
    assert check["status"] == "FAIL" and check["required"] is True and "schema 1" in check["detail"]
    assert full.check("pytest")["status"] == "PASS", "the suite passed; only the inventory check stops it"
    tree.write("files/tests/test_ordinary.py", PASSING + "\n# touched\n")
    changed = tree.run("--mode", "changed", "--base", "HEAD")
    assert changed.code == 1 and changed.check("coverage-inventory")["status"] == "FAIL", changed
    focused = tree.focused("files/tests/test_ordinary.py")
    assert focused.code == 0 and focused.check("coverage-inventory")["required"] is False, "a focused run reports it without being stopped"


def test_a_full_run_that_did_not_execute_the_gates_own_negative_controls_cannot_pass(tree):
    """Dropping this very file from the suite must not leave a gate that passes without ever proving it can fail."""
    policy = tree.policy()
    policy["required_self_tests"] = ["files/tests/test_ordinary.py", "files/tests/test_missing_controls.py"]
    tree.write_policy(policy)
    outcome = tree.full()
    assert outcome.code == 1, outcome
    gate = outcome.check("self-tests")
    assert gate["status"] == "FAIL" and "test_missing_controls.py" in gate["detail"]
    assert outcome.check("pytest")["status"] == "PASS", "the suites passed; only this check catches it"


def test_a_later_requirement_made_required_stops_the_pass_until_it_exists(tree):
    """How a phase turns a requirement on: the same list, one flag. Until the check exists the run is NOT RUN."""
    _with_later_requirement(tree, required=True)
    outcome = tree.full()
    assert outcome.code == 3 and outcome.results["status"] == "NOT RUN", outcome


# --------------------------------------------------------------------------- #
# Tests that fail, at every phase
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("source, needle, junit_tag", [
    ("def test_bad():\n    assert 1 == 2, 'THE-ASSERTION-RAN'\n", "THE-ASSERTION-RAN", "failure"),
    ("import pytest\n@pytest.fixture\ndef f():\n    raise RuntimeError('SETUP-RAN')\ndef test_bad(f):\n    pass\n", "SETUP-RAN", "error"),
    ("import pytest\n@pytest.fixture\ndef f():\n    yield\n    raise RuntimeError('TEARDOWN-RAN')\ndef test_bad(f):\n    pass\n",
     "TEARDOWN-RAN", "error"),
])
def test_a_failing_assertion_setup_or_teardown_fails_and_names_the_stage(tree, source, needle, junit_tag):
    tree.write("files/tests/test_bad.py", source)
    outcome = tree.focused("files/tests/test_bad.py", "files/tests/test_ordinary.py")
    assert outcome.code == 1, outcome
    gate = outcome.check("pytest")
    assert gate["status"] == "FAIL" and gate["exit_status"] == 1
    junit = (outcome.directory / "reports" / "pytest.xml").read_text(encoding="utf-8")
    assert needle in junit and f"<{junit_tag}" in junit, "the target of this control never executed"
    assert needle in (outcome.directory / "logs" / "pytest.log").read_text(encoding="utf-8")
    assert outcome.results["counts"]["executed"] == 3


def test_a_failure_in_a_guarded_group_fails_the_guarded_gate(tree):
    tree.write("files/tests/test_guarded.py", "def test_guarded_bad():\n    assert False, 'GUARDED-RAN'\n")
    outcome = tree.full()
    assert outcome.code == 1, outcome
    assert outcome.check("guarded")["status"] == "FAIL" and "pytest exit 1" in outcome.check("guarded")["detail"]
    assert outcome.check("pytest")["status"] == "PASS"
    assert "GUARDED-RAN" in (outcome.directory / "logs" / "guarded-only.log").read_text(encoding="utf-8")


def test_a_real_fail_leaves_its_scratch_and_evidence_behind(tree):
    tree.write("files/tests/test_bad.py", "def test_bad():\n    assert False\n")
    outcome = tree.focused("files/tests/test_bad.py")
    assert outcome.code == 1, outcome
    assert Path(outcome.results["cleanup"]["scratch"]).is_dir() and (outcome.directory / "failures.md").is_file()
    status = tree.status(str(outcome.directory))
    assert status.returncode == 1 and "status: FAIL" in status.stdout, status.stdout


# --------------------------------------------------------------------------- #
# Nothing ran
# --------------------------------------------------------------------------- #
def test_zero_tests_collected_is_not_a_pass(tree):
    tree.write("files/tests/test_empty.py", "# no tests here\n")
    outcome = tree.focused("files/tests/test_empty.py")
    assert outcome.code == 3 and outcome.results["status"] == "NOT RUN", outcome
    assert "no tests collected" in outcome.check("pytest")["detail"]
    assert outcome.results["counts"]["executed"] == 0


@pytest.mark.parametrize("selector", ["files/tests/test_ordinary.py::test_does_not_exist", "files/tests/test_no_such_module.py"])
def test_an_unknown_selector_runs_nothing_and_is_not_a_pass(tree, selector):
    outcome = tree.focused(selector, "files/tests/test_ordinary.py::test_one")
    assert outcome.code == 3, outcome
    gate = outcome.check("pytest")
    assert gate["status"] == "NOT RUN" and gate["exit_status"] == 4
    assert outcome.results["counts"]["executed"] == 0


def test_an_unknown_feature_is_an_invalid_invocation_with_a_record(tree):
    outcome = tree.run("--mode", "focused", "--feature", "ACT.NO.SUCH")
    assert outcome.code == 64, outcome
    assert "unknown feature" in outcome.check("selection")["detail"]
    status = tree.status(str(outcome.directory))
    assert "status: NOT RUN" in status.stdout


def test_a_known_feature_selects_its_tests_and_nothing_else(tree):
    outcome = tree.run("--mode", "focused", "--feature", "ACT.TEST.ONE")
    assert outcome.code == 0, outcome
    assert outcome.results["counts"]["executed"] == 2
    assert outcome.results["scope"]["full_acceptance"] is False and "selection only" in outcome.stdout


@pytest.mark.parametrize("flag", ["--preflight-only", "--collect-only"])
def test_preflight_and_collect_only_leave_evidence_and_never_establish_acceptance(tree, flag):
    outcome = tree.run("--mode", "full", flag)
    assert outcome.code == 3, outcome
    assert outcome.results["status"] == "NOT RUN" and outcome.results["counts"]["executed"] == 0
    assert outcome.check("execution")["status"] == "NOT RUN"
    assert (outcome.directory / "collection" / "pytest.txt").exists() == (flag == "--collect-only")


@pytest.mark.parametrize("scenario", ["edge-low-memory", "optional-engines", "fresh-windows"])
def test_a_scenario_the_policy_lists_with_no_runner_says_so_and_who_owns_it(tree, scenario):
    """Every scenario has a runner since v0.7.2 Phase 8. The rule itself stays: a policy entry without one is NOT RUN, never a pass."""
    policy = tree.policy()
    del policy["scenarios"][scenario]["runner"]
    tree.write_policy(policy)
    tree.commit("a scenario with no runner")
    outcome = tree.run("--mode", "qualification", "--scenario", scenario)
    assert outcome.code == 3, outcome
    gate = outcome.check(f"scenario:{scenario}")
    assert gate["status"] == "NOT RUN" and "Phase" in gate["detail"]


@pytest.mark.parametrize("scenario, grant, why", [
    ("edge-low-memory", None, "was not given --network online-edge"),
    ("edge-low-memory", "online-edge", "TTS code is not here"),
    ("optional-engines", None, "TTS code is not here"),
    ("fresh-windows", None, "was not given --network online-setup"),
    ("fresh-windows", "online-setup", "not complete here"),
], ids=["edge-without-its-grant", "edge-without-the-application", "engines-without-the-application",
        "fresh-windows-without-its-grant", "fresh-windows-without-the-application"])
def test_a_phase_8_scenario_is_blocked_without_its_network_grant_or_the_application(tree, scenario, grant, why):
    """v0.7.2 Phase 8 implements the three scenarios (qualification/). This small tree has the gate and its runners but not the
    application, and a run without ``--network`` has no grant: each must say BLOCKED, with the reason, quickly, in a verdict in
    the run's own folder, having sent and downloaded nothing. The grant reaches the runner only as the policy's own name."""
    extra = ("--network", grant) if grant else ()
    outcome = tree.run("--mode", "qualification", "--scenario", scenario, *extra)
    assert outcome.code == 2, outcome
    gate = outcome.check(f"scenario:{scenario}")
    assert gate["status"] == "BLOCKED" and why in gate["detail"], gate
    verdict = json.loads((outcome.directory / "qualification" / "verdict.json").read_text(encoding="utf-8"))
    assert verdict["status"] == "BLOCKED" and verdict["scenario"] == scenario and verdict["checks"] == []
    assert outcome.check("cleanup")["status"] == "PASS"
    assert outcome.results["qualification"]["satisfied"] == [] and scenario in outcome.results["qualification"]["pending"]
    assert sorted(path.name for path in (outcome.directory / "qualification").iterdir()) == ["runs.json", "verdict.json"]


def test_a_network_policy_another_scenario_declares_is_refused_before_anything_exists(tree):
    for scenario, policy in (("optional-engines", "online-edge"), ("edge-low-memory", "online-setup"), ("fresh-windows", "online-edge")):
        outcome = tree.run("--mode", "qualification", "--scenario", scenario, "--network", policy)
        assert outcome.code == 64 and outcome.directory is None, (scenario, policy, outcome)


def test_the_m4b_scaling_scenario_runs_its_runner_and_is_blocked_without_the_application(tree):
    """v0.7.2 Phase 7B implements m4b-scaling. This small tree has the gate and its scaling/ runner but not the
    application's M4B code, so the runner must say BLOCKED, quickly, with a verdict in the run's own folder; the gate must
    report that verdict rather than a PASS, and must have owned and reaped the runner."""
    outcome = tree.run("--mode", "qualification", "--scenario", "m4b-scaling")
    assert outcome.code == 2, outcome
    gate = outcome.check("scenario:m4b-scaling")
    assert gate["status"] == "BLOCKED" and "application" in gate["detail"], gate
    verdict = json.loads((outcome.directory / "qualification" / "verdict.json").read_text(encoding="utf-8"))
    assert verdict["status"] == "BLOCKED" and verdict["scenario"] == "m4b-scaling"
    assert outcome.check("cleanup")["status"] == "PASS"
    assert outcome.results["qualification"]["satisfied"] == [] and "m4b-scaling" in outcome.results["qualification"]["pending"]


def test_a_scenario_runner_that_reports_pass_without_exiting_zero_is_not_a_pass(tree):
    """The verdict file alone cannot make a PASS: the runner's own exit status must agree with it."""
    runner = tree.gate / "scaling" / "qualify.py"
    runner.write_text(textwrap.dedent('''
        import json, sys
        from pathlib import Path
        out = Path(sys.argv[sys.argv.index("--out") + 1])
        out.mkdir(parents=True)
        (out / "progress.log").write_text("started\\n")
        (out / "verdict.json").write_text(json.dumps({"scenario": "m4b-scaling", "status": "PASS", "reason": "lies",
                                                      "checks": [], "runs": 0}))
        sys.exit(1)
    '''), encoding="utf-8")
    tree.commit("a runner that lies")
    outcome = tree.run("--mode", "qualification", "--scenario", "m4b-scaling")
    assert outcome.code == 1, outcome
    assert outcome.check("scenario:m4b-scaling")["status"] == "FAIL"


def test_a_benchmark_run_can_open_no_file_manager_window():
    """The Converter reveals its output folder when a run ends. Attempt 1 of the m4b-scaling qualification let every
    benchmark run do it: about 200 Explorer windows, the owner's shell crashed twice under them, and os.startfile held
    the Tk loop for up to 36.9 s, which the heartbeat and Cancel budgets then measured. A benchmark run replaces both
    ways of opening the file manager with recorders, and refuses to start if the Converter could still reach another."""
    if sys.platform != "win32":
        pytest.skip("the benchmark harness accounts through Windows Job Objects")
    import importlib.util  # noqa: PLC0415
    import types  # noqa: PLC0415

    saved_path, had_winjob = list(sys.path), "winjob" in sys.modules
    try:
        spec = importlib.util.spec_from_file_location("act_bench_run_contract", GATE_DIR / "scaling" / "bench_run.py")
        bench = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bench)
    finally:  # the harness puts its own folder first on the path and imports winjob from it
        sys.path[:] = saved_path
        if not had_winjob:
            sys.modules.pop("winjob", None)

    opened = []
    sp = types.SimpleNamespace(reveal_in_file_manager=lambda path: opened.append(("reveal", path)))
    converter = types.SimpleNamespace(sp=sp)
    os_module = types.SimpleNamespace(startfile=lambda *args: opened.append(("startfile", args)))
    reveals = []
    bench.neutralize_shell(sp, converter, os_module, reveals)
    converter.sp.reveal_in_file_manager("run/output-base/M4B-Converter-Outputs")
    os_module.startfile("run/output-base")
    assert opened == [], "a benchmark run opened the file manager"
    assert [next(iter(record)) for record in reveals] == ["reveal", "startfile"]

    elsewhere = types.SimpleNamespace(reveal_in_file_manager=lambda path: opened.append(("reveal", path)))
    with pytest.raises(bench.Refused):
        bench.neutralize_shell(sp, types.SimpleNamespace(sp=elsewhere), os_module, [])


def test_scenario_names_are_the_same_in_the_gate_its_policy_and_its_help():
    gate = load_gate("act_verify_contract_scenarios")
    policy = gate.load_policy()
    assert set(gate.SCENARIO_NAMES) == set(policy["scenarios"])
    for name, scenario in policy["scenarios"].items():
        assert set(scenario["network"]) == set(gate._SCENARIO_NETWORK.get(name, ())), name
    done = subprocess.run([sys.executable, str(gate.__file__), "--help"], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0
    for name in (*gate.SCENARIO_NAMES, *gate.MODES, "--test", "--feature", "--base", "--platform", "--network"):
        assert name in done.stdout, name
    for code in ("0 PASS", "1 FAIL", "2 BLOCKED", "3 NOT RUN", "64 invalid", "130 interrupted"):
        assert code in done.stdout, code


def test_asking_for_the_wrong_platform_is_blocked_before_any_test(tree):
    other = "macos" if sys.platform == "win32" else "windows"
    outcome = tree.run("--mode", "full", "--platform", other)
    assert outcome.code == 2 and outcome.results["status"] == "BLOCKED", outcome
    assert outcome.results["counts"]["executed"] == 0


# --------------------------------------------------------------------------- #
# Selection cannot be narrowed from outside
# --------------------------------------------------------------------------- #
def test_a_conftest_that_deselects_a_test_is_caught(tree):
    conftest = (tree.tests / "conftest.py").read_text(encoding="utf-8")
    tree.write("files/tests/conftest.py", conftest + textwrap.dedent("""\

        def pytest_collection_modifyitems(config, items):
            dropped = [item for item in items if item.name == "test_two"]
            items[:] = [item for item in items if item.name != "test_two"]
            config.hook.pytest_deselected(items=dropped)
        """))
    outcome = tree.focused("files/tests/test_ordinary.py")
    assert outcome.code == 1, outcome
    assert "deselected" in outcome.check("pytest")["detail"]


def test_a_conftest_that_silently_drops_a_test_is_caught_by_the_full_inventory(tree):
    conftest = (tree.tests / "conftest.py").read_text(encoding="utf-8")
    # Only during the real run: --collect-only sees every test, then the run quietly executes fewer.
    tree.write("files/tests/conftest.py", conftest + textwrap.dedent("""\

        def pytest_collection_modifyitems(config, items):
            if not config.getoption("collectonly"):
                items[:] = [item for item in items if item.name != "test_two"]
        """))
    outcome = tree.full()
    assert outcome.code == 1, outcome
    assert outcome.check("inventory")["status"] == "FAIL" and "test_two" in outcome.check("inventory")["detail"]


def test_pytest_addopts_in_the_environment_cannot_narrow_a_run(tree):
    outcome = tree.focused("files/tests/test_ordinary.py", env={"PYTEST_ADDOPTS": "-k test_one"})
    assert outcome.code == 0, outcome
    assert outcome.results["counts"]["executed"] == 2


def test_an_unexpected_skip_or_xfail_cannot_pass(tree):
    tree.write("files/tests/test_skips.py", """\
        import pytest
        def test_a_new_skip():
            pytest.skip('a reason the policy has never heard of')
        """)
    outcome = tree.focused("files/tests/test_skips.py", "files/tests/test_ordinary.py")
    assert outcome.code == 1, outcome
    assert outcome.check("pytest")["status"] == "PASS", "the suite itself passed; the policy is what caught this"
    assert "unexpected skip" in outcome.check("skips")["detail"] and "never heard of" in outcome.check("skips")["detail"]


def test_an_xfail_cannot_pass_unnoticed(tree):
    tree.write("files/tests/test_xfails.py", """\
        import pytest
        @pytest.mark.xfail(reason='known broken')
        def test_known_broken():
            assert False
        """)
    outcome = tree.focused("files/tests/test_xfails.py", "files/tests/test_ordinary.py")
    assert outcome.code == 1, outcome
    assert "unexpected xfail" in outcome.check("skips")["detail"]


def test_a_skip_the_policy_names_passes_only_within_its_limit(tree):
    policy = tree.policy()
    policy["skip_policy"][sys.platform] = [{"id": "known", "pattern": "^known reason$", "max": 1}]
    tree.write_policy(policy)
    tree.write("files/tests/test_skips.py", """\
        import pytest
        @pytest.mark.parametrize("n", [0, 1])
        def test_known_skip(n):
            pytest.skip('known reason')
        """)
    outcome = tree.focused("files/tests/test_skips.py::test_known_skip[0]", "files/tests/test_ordinary.py")
    assert outcome.code == 0, outcome
    assert outcome.check("skips")["tally"] == {"known": 1}
    outcome = tree.focused("files/tests/test_skips.py", "files/tests/test_ordinary.py")
    assert outcome.code == 1, outcome
    assert "more than the 1 the policy allows" in outcome.check("skips")["detail"]


# --------------------------------------------------------------------------- #
# A wrapper hiding its child, and reports that cannot be trusted
# --------------------------------------------------------------------------- #
def _patched_gate(tree, source: str) -> Path:
    """A launcher beside the gate that replaces how pytest is started, and nothing else. For a wrapper between gate and child."""
    return tree.write("files/dev-work/verification-gate/launch_patched.py", f"""\
        import importlib.util, sys
        from pathlib import Path
        sys.dont_write_bytecode = True
        spec = importlib.util.spec_from_file_location("gate", Path(__file__).with_name("verify.py"))
        gate = importlib.util.module_from_spec(spec)
        sys.modules["gate"] = gate
        spec.loader.exec_module(gate)
        real_pytest_command = gate._pytest_command
        real_guarded_command = gate._guarded_command
{textwrap.indent(textwrap.dedent(source), " " * 8)}
        sys.exit(gate.main())
        """)


WRAPPER = """\
    import pathlib, subprocess, sys
    junit = pathlib.Path(sys.argv[1])
    code = subprocess.call(sys.argv[3:])
    action = sys.argv[2]
    if action == "delete-junit":
        junit.unlink()
    elif action == "truncate-junit":
        junit.write_text(junit.read_text(encoding="utf-8")[:80], encoding="utf-8")
    elif action == "lie-about-counts":
        text = junit.read_text(encoding="utf-8")
        junit.write_text(text.replace('tests="2"', 'tests="7"'), encoding="utf-8")
    elif action == "duplicate-testcase":
        import re
        text = junit.read_text(encoding="utf-8")
        case = re.search(r"<testcase .*?/>", text).group(0)
        text = text.replace(case, case + case).replace('tests="2"', 'tests="3"')
        junit.write_text(text, encoding="utf-8")
    elif action == "stale-suite-name":
        import re
        text = junit.read_text(encoding="utf-8")
        junit.write_text(re.sub(r'testsuite name="[^"]+"', 'testsuite name="an-earlier-run"', text), encoding="utf-8")
    sys.exit(0)
    """


@pytest.mark.parametrize("action, code, status, needle", [
    ("nothing", 1, "FAIL", "exit 0 but the JUnit report records 1 failure"),
    ("delete-junit", 3, "NOT RUN", "exit 0 but the JUnit report is missing"),
    ("truncate-junit", 3, "NOT RUN", "exit 0 but the JUnit report is unreadable or truncated"),
])
def test_a_wrapper_exit_zero_cannot_hide_a_failing_child_or_its_report(tree, action, code, status, needle):
    """The wrapper always exits 0, the way a trailing shell command once did. The child under it really fails."""
    tree.write("files/tests/test_bad.py", "def test_bad():\n    assert False, 'THE-CHILD-REALLY-RAN'\n\n\ndef test_ok():\n    pass\n")
    wrapper = tree.write("files/dev-work/verification-gate/wrapper.py", WRAPPER)
    launcher = _patched_gate(tree, f"""\
        def wrapped(junit, **kwargs):
            return [sys.executable, {str(wrapper)!r}, str(junit), {action!r}, *real_pytest_command(junit, **kwargs)]
        gate._pytest_command = wrapped
        """)
    outcome = tree.run("--mode", "focused", "--test=files/tests/test_bad.py", script=launcher)
    assert outcome.code == code, outcome
    gate = outcome.check("pytest")
    assert gate["status"] == status and gate["exit_status"] == 0 and gate["detail"].startswith(needle), gate["detail"]
    assert "THE-CHILD-REALLY-RAN" in (outcome.directory / "logs" / "pytest.log").read_text(encoding="utf-8")


@pytest.mark.parametrize("action, needle", [
    ("lie-about-counts", "does not hold together"),
    ("duplicate-testcase", "does not hold together"),
    ("stale-suite-name", "belongs to"),
])
def test_a_junit_report_that_does_not_hold_together_is_rejected(tree, action, needle):
    wrapper = tree.write("files/dev-work/verification-gate/wrapper.py", WRAPPER)
    launcher = _patched_gate(tree, f"""\
        def wrapped(junit, **kwargs):
            return [sys.executable, {str(wrapper)!r}, str(junit), {action!r}, *real_pytest_command(junit, **kwargs)]
        gate._pytest_command = wrapped
        """)
    outcome = tree.run("--mode", "focused", "--test=files/tests/test_ordinary.py", script=launcher)
    assert outcome.code == 1, outcome
    gate = outcome.check("pytest")
    assert gate["status"] == "FAIL" and gate["exit_status"] == 0 and needle in gate["detail"], gate["detail"]


@pytest.mark.parametrize("damage, needle", [
    ("no-report", "guard report"),
    ("foreign-report", "does not belong to this run"),
])
def test_a_guarded_group_without_its_own_report_fails(tree, damage, needle):
    """The runner is replaced by a child that reports success and leaves no report, or somebody else's."""
    fake = tree.write("files/dev-work/verification-gate/fake_guard.py", f"""\
        import json, pathlib, sys
        report = pathlib.Path(sys.argv[1])
        if {damage!r} == "foreign-report":
            report.write_text(json.dumps({{"outer_exit": 0, "pytest_exit": 0, "counts": {{"passed": 2}},
                "unintended_production_refusals": [], "unexpected_processes": [], "network_model_refusals": [],
                "runner_sha256": "0" * 64, "config_sha256": "0" * 64}}), encoding="utf-8")
        sys.exit(0)
        """)
    launcher = _patched_gate(tree, f"""\
        def fake_command(config, report, basetemp, targets, *, extra=()):
            if "--collect-only" in extra:
                return real_guarded_command(config, report, basetemp, targets, extra=extra)
            return [sys.executable, {str(fake)!r}, str(report)]
        gate._guarded_command = fake_command
        """)
    outcome = tree.run("--mode", "full", script=launcher)
    assert outcome.code == 1, outcome
    gate = outcome.check("guarded")
    assert gate["status"] == "FAIL" and needle in gate["detail"], gate["detail"]


# --------------------------------------------------------------------------- #
# The partition between ordinary and guarded
# --------------------------------------------------------------------------- #
def test_a_module_moved_out_of_its_guard_is_caught(tree):
    """Dropping a suite from guarded_groups.json would run it unguarded. The policy still names it, so the run stops."""
    spec = json.loads((tree.tests / "guarded_groups.json").read_text(encoding="utf-8"))
    tree.write("files/tests/test_second.py", "def test_x():\n    pass\n")
    spec["groups"][0]["modules"] = ["test_second.py"]
    (tree.tests / "guarded_groups.json").write_text(json.dumps(spec), encoding="utf-8")
    outcome = tree.full()
    assert outcome.code == 1, outcome
    assert "differs from the policy" in outcome.check("guarded-specification")["detail"]
    assert outcome.results["counts"]["executed"] == 0


def test_a_module_duplicated_in_two_groups_is_refused(tree):
    spec = json.loads((tree.tests / "guarded_groups.json").read_text(encoding="utf-8"))
    spec["groups"].append({"name": "again", "basetemp_prefix": "stage-again-", "modules": ["test_guarded.py"]})
    (tree.tests / "guarded_groups.json").write_text(json.dumps(spec), encoding="utf-8")
    outcome = tree.full()
    assert outcome.code == 1, outcome
    assert "more than one group" in outcome.check("guarded-specification")["detail"]


def test_a_test_module_with_nothing_collected_breaks_the_partition(tree):
    tree.write("files/tests/test_forgotten.py", "x = 1\n")
    outcome = tree.full()
    assert outcome.code == 1, outcome
    assert "test_forgotten.py is on disk but neither collection" in outcome.check("partition")["detail"]
    assert outcome.results["counts"]["executed"] == 0, "the partition must stop the run before the suites"


def test_a_module_the_policy_says_is_empty_is_allowed_only_while_that_stays_true(tree):
    tree.write("files/tests/test_harness.py", "x = 1\n")
    policy = tree.policy()
    policy["inventory"]["modules_without_tests"] = {"test_harness.py": "a script, not a suite"}
    tree.write_policy(policy)
    outcome = tree.full()
    assert outcome.code == 0, outcome
    tree.write("files/tests/test_harness.py", "def test_now_a_suite():\n    pass\n")
    outcome = tree.full()
    assert outcome.code == 1, outcome
    assert "remove the entry" in outcome.check("partition")["detail"]


def test_fewer_tests_than_the_floor_breaks_the_partition(tree):
    policy = tree.policy()
    policy["inventory"]["minimum_ordinary"] = 3
    tree.write_policy(policy)
    outcome = tree.full()
    assert outcome.code == 1, outcome
    assert "fewer than the required 3" in outcome.check("partition")["detail"]


def test_the_partition_logic_on_each_way_it_can_break():
    load_gate("act_verify_contract_partition")
    from helpers import pytest_reports

    disk = {"t/test_a.py", "t/test_g.py"}
    good = (["t/test_a.py::x"], {"g": ["t/test_g.py::y"]}, {"g": ["test_g.py"]}, disk, "t")
    assert pytest_reports.partition_problems(*good) == []
    for arguments, needle in [
        ((["t/test_a.py::x", "t/test_a.py::x"], {"g": ["t/test_g.py::y"]}, {"g": ["test_g.py"]}, disk, "t"), "duplicated node"),
        ((["t/test_a.py::x", "t/test_g.py::y"], {"g": ["t/test_g.py::y"]}, {"g": ["test_g.py"]}, disk, "t"), "in both"),
        ((["t/test_a.py::x", "t/test_g.py::z"], {"g": ["t/test_g.py::y"]}, {"g": ["test_g.py"]}, disk, "t"), "collected as ordinary"),
        ((["t/test_a.py::x"], {"g": []}, {"g": ["test_g.py"]}, disk, "t"), "collected nothing"),
        ((["t/test_a.py::x"], {"g": ["t/test_g.py::y", "t/test_b.py::z"]}, {"g": ["test_g.py"]}, disk, "t"), "does not list"),
        ((["t/test_a.py::x"], {"g": ["t/test_g.py::y"]}, {"g": ["test_g.py"], "h": ["test_g.py"]}, disk, "t"), "both"),
        (([], {"g": ["t/test_g.py::y"]}, {"g": ["test_g.py"]}, disk, "t"), "neither collection"),
    ]:
        problems = pytest_reports.partition_problems(*arguments)
        assert any(needle in problem for problem in problems), (needle, problems)


# --------------------------------------------------------------------------- #
# Identity: what was tested, and old runs standing in for new ones
# --------------------------------------------------------------------------- #
def test_source_changed_during_the_run_is_not_a_pass(tree):
    tree.write("files/tests/test_writes_source.py", f"""\
        from pathlib import Path
        def test_edits_a_tracked_file():
            Path({str(tree.root / 'pytest.ini')!r}).write_text("[pytest]\\n", encoding="utf-8")
        """)
    outcome = tree.focused("files/tests/test_writes_source.py")
    assert outcome.code == 1, outcome
    assert outcome.check("pytest")["status"] == "PASS", "the tests passed; only the identity check catches this"
    gate = outcome.check("tree")
    assert gate["status"] == "FAIL" and "policy_digest" in gate["detail"]
    assert outcome.results["identity"]["start_end_match"] is False


def test_an_untracked_helper_appearing_during_the_run_is_not_a_pass(tree):
    tree.write("files/tests/test_adds_helper.py", f"""\
        from pathlib import Path
        def test_adds():
            Path({str(tree.gate / 'new_helper.py')!r}).write_text("x = 1\\n", encoding="utf-8")
        """)
    outcome = tree.focused("files/tests/test_adds_helper.py")
    assert outcome.code == 1, outcome
    assert "policy_digest" in outcome.check("tree")["detail"]


@pytest.fixture
def passing_run(tree):
    outcome = tree.focused("files/tests/test_ordinary.py")
    assert outcome.code == 0, outcome
    assert tree.status(str(outcome.directory)).returncode == 0
    return tree, outcome.directory


def _rewrite_results(directory: Path, change, *, reseal: bool = False) -> None:
    load_gate("act_verify_contract_seal")
    from helpers import runstore

    path = directory / "results.json"
    results = json.loads(path.read_text(encoding="utf-8"))
    change(results)
    if reseal:
        results["seal"] = runstore.seal_of(results)
    path.write_text(json.dumps(results), encoding="utf-8")


def test_a_run_copied_to_a_new_directory_reads_invalid(passing_run):
    tree, directory = passing_run
    copy = directory.with_name(directory.name[:-4] + "aaaa")
    shutil.copytree(directory, copy)
    status = tree.status(str(copy))
    assert status.returncode == 3 and "status: INVALID" in status.stdout and "copied or renamed" in status.stdout, status.stdout


def test_a_copied_run_with_its_id_edited_is_still_invalid(passing_run):
    tree, directory = passing_run
    copy = directory.with_name(directory.name[:-4] + "bbbb")
    shutil.copytree(directory, copy)
    _rewrite_results(copy, lambda r: r.update(run_id=copy.name))
    status = tree.status(str(copy))
    assert status.returncode == 3 and "the seal does not match" in status.stdout, status.stdout


def test_a_copied_run_with_its_id_edited_and_resealed_is_caught_by_its_start_record(passing_run):
    tree, directory = passing_run
    copy = directory.with_name(directory.name[:-4] + "cccc")
    shutil.copytree(directory, copy)
    _rewrite_results(copy, lambda r: r.update(run_id=copy.name), reseal=True)
    status = tree.status(str(copy))
    assert status.returncode == 3 and "names another run" in status.stdout, status.stdout


@pytest.mark.parametrize("how", ["copied-out", "through-a-junction-inside-outputs", "a-junction-as-the-run", "traversal-out"])
def test_a_run_that_does_not_live_in_outputs_is_never_current(passing_run, how):
    """Plan section 10: an old run copied into a new directory is rejected as current acceptance, and the directory name is not
    trusted. A copy normally keeps its folder name, and its id, nonce and manifest all travel with it, so only where it is can
    tell it apart. A copy on the same source still tells the truth; it just is not the gate's own record of a run."""
    tree, directory = passing_run
    elsewhere = tree.root.parent / "elsewhere"
    shutil.copytree(directory, elsewhere / directory.name)
    target = str(elsewhere / directory.name)
    if how == "through-a-junction-inside-outputs":
        _junction_or_skip(elsewhere, tree.outputs / "redirect")
        target = str(tree.outputs / "redirect" / directory.name)
    elif how == "a-junction-as-the-run":
        shutil.rmtree(directory)
        _junction_or_skip(elsewhere / directory.name, directory)
        target = str(directory)
    elif how == "traversal-out":
        target = f"../elsewhere/{directory.name}"
    status = tree.status(target, "--require-current")
    assert status.returncode == 3 and "current: elsewhere" in status.stdout and "current: exact" not in status.stdout, status.stdout


def test_a_run_in_its_own_place_is_current_however_the_path_is_spelled(passing_run):
    """The no-change control of the test above."""
    tree, directory = passing_run
    relative = directory.relative_to(tree.root).as_posix()
    outputs = directory.parent.relative_to(tree.root).as_posix()
    for raw in (str(directory), relative, f"{outputs}/../outputs/{directory.name}"):
        status = tree.status(raw, "--require-current")
        assert status.returncode == 0 and "current: exact" in status.stdout, (raw, status.stdout)


def test_status_on_something_that_is_not_a_run_is_never_zero(passing_run):
    tree, directory = passing_run
    outputs = directory.parent.relative_to(tree.root).as_posix()
    for raw, expected in ((f"{outputs}/no-such-run", "status: INVALID"), (outputs, "status: INCOMPLETE"),
                          (str(directory / "results.json"), "status: INVALID")):
        status = tree.status(raw)
        assert status.returncode == 3 and expected in status.stdout, (raw, status.stdout)


def test_an_artifact_reached_through_a_link_is_not_a_pass(passing_run):
    """The manifest's hashes would still match, because a junction for logs/ serves the same bytes from somewhere else."""
    tree, directory = passing_run
    elsewhere = tree.root.parent / "logs-elsewhere"
    shutil.copytree(directory / "logs", elsewhere)
    shutil.rmtree(directory / "logs")
    _junction_or_skip(elsewhere, directory / "logs")
    status = tree.status(str(directory))
    assert status.returncode == 3 and "status: INVALID" in status.stdout and "below a link" in status.stdout, status.stdout


@pytest.mark.parametrize("edit, needle", [
    (lambda r: r.update(status="PASS", exit_code=1), "PASS with exit code"),
    (lambda r: r["identity"].update(start_end_match=False), "without a matching start and end identity"),
    (lambda r: r["cleanup"].update(owned_children_remaining=1), "without a clean process cleanup"),
    (lambda r: r["counts"].update(executed=0), "PASS with no executed tests"),
    (lambda r: r["checks"][0].update(status="FAIL"), "required checks not passed"),
    (lambda r: r.update(lifecycle="running"), "is not completed"),
    (lambda r: r.update(schema_version=99), "schema_version"),
])
def test_a_pass_that_contradicts_itself_is_invalid_even_if_resealed(passing_run, edit, needle):
    tree, directory = passing_run
    _rewrite_results(directory, edit, reseal=True)
    status = tree.status(str(directory))
    assert status.returncode == 3 and "status: INVALID" in status.stdout and needle in status.stdout, status.stdout


def test_a_missing_or_changed_artifact_makes_a_pass_invalid(passing_run):
    tree, directory = passing_run
    junit = directory / "reports" / "pytest.xml"
    original = junit.read_bytes()
    junit.write_bytes(original + b" ")
    status = tree.status(str(directory))
    assert status.returncode == 3 and "changed after the run" in status.stdout, status.stdout
    junit.unlink()
    status = tree.status(str(directory))
    assert status.returncode == 3 and "pytest.xml is missing" in status.stdout, status.stdout


def test_an_old_pass_does_not_stand_in_for_changed_source(passing_run):
    tree, directory = passing_run
    assert "current: exact" in tree.status(str(directory), "--require-current").stdout
    tree.write("scripts/app.py", "x = 1\n")
    tree.commit("source moved")
    status = tree.status(str(directory), "--require-current")
    assert status.returncode == 3 and "current: stale" in status.stdout and "does not describe" in status.stdout, status.stdout
    assert tree.status(str(directory)).returncode == 0, "still a true record of the source it ran on"


def test_a_docs_only_change_is_reported_as_docs_only_and_never_as_the_same_source(passing_run):
    """Plan §13.3: execution evidence may carry over a docs commit, but the claim must say that is what happened."""
    tree, directory = passing_run
    tree.write("md-instructions/Handoff.md", "# a docs-only edit\n")
    status = tree.status(str(directory), "--require-current")
    assert "current: docs-only" in status.stdout and status.returncode == 3, status.stdout
    assert "only documents differ" in status.stdout and "both SHAs" in status.stdout, status.stdout


@pytest.mark.parametrize("field, value", [
    ("python", "3.99.0 (another interpreter)"),
    ("ffmpeg_sha256", "0" * 64),
    ("executable", "C:/elsewhere/python.exe"),
])
def test_a_pass_from_another_environment_is_not_current_even_on_the_same_source(passing_run, field, value):
    """Plan section 13.3: evidence carries only where the environment matches too. A replaced FFmpeg is not the run that passed."""
    tree, directory = passing_run
    assert "current: exact" in tree.status(str(directory), "--require-current").stdout
    _rewrite_results(directory, lambda r: r["environment"].update({field: value}), reseal=True)
    status = tree.status(str(directory), "--require-current")
    assert status.returncode == 3 and "current: stale" in status.stdout, status.stdout
    assert f"environment.{field}" in status.stdout and "does not describe" in status.stdout, status.stdout
    assert tree.status(str(directory)).returncode == 0, "still a true record of the environment it ran on"


def test_a_docs_change_cannot_carry_evidence_across_a_changed_environment(passing_run):
    tree, directory = passing_run
    _rewrite_results(directory, lambda r: r["environment"].update(tk="8.0.0"), reseal=True)
    tree.write("md-instructions/Handoff.md", "# a docs-only edit\n")
    status = tree.status(str(directory), "--require-current")
    assert status.returncode == 3 and "current: stale" in status.stdout and "environment.tk" in status.stdout, status.stdout


def test_the_session_reading_a_pass_does_not_make_it_stale(passing_run):
    """Whichever shell reads the result has its own error mode and desktop. Neither says anything about the run."""
    tree, directory = passing_run
    _rewrite_results(directory, lambda r: r["environment"].update(error_mode="0x3", interactive_desktop=False), reseal=True)
    status = tree.status(str(directory), "--require-current")
    assert status.returncode == 0 and "current: exact" in status.stdout, status.stdout


def test_a_reader_that_brings_no_environment_cannot_read_current(passing_run):
    _tree, directory = passing_run
    load_gate("act_verify_contract_no_environment")
    from helpers import runstore

    results = json.loads((directory / "results.json").read_text(encoding="utf-8"))
    recorded = results["identity"]["start"]
    outcome = runstore.read_run_status(directory, recorded)
    assert (outcome["status"], outcome["current"]) == ("PASS", "stale"), outcome["current"]
    assert outcome["identity_differences"] == ["environment unavailable"]
    assert runstore.read_run_status(directory, recorded, results["environment"])["current"] == "exact"


def test_a_run_with_a_marker_left_behind_is_incomplete_whatever_its_result_says(passing_run):
    tree, directory = passing_run
    (directory / "INCOMPLETE.json").write_text("{}", encoding="utf-8")
    status = tree.status(str(directory))
    assert status.returncode == 3 and "status: INCOMPLETE" in status.stdout


def test_legacy_evidence_reads_as_legacy_and_never_as_current(tree):
    legacy = tree.root / "files" / "dev-work" / "act070-remediation" / "verify" / "old-run"
    legacy.mkdir(parents=True)
    (legacy / "result.json").write_text('{"status": "COMPLETE", "result": "PASS"}', encoding="utf-8")
    status = tree.status(str(legacy))
    assert status.returncode == 3 and "legacy evidence: PASS" in status.stdout and "never current" in status.stdout
    assert list(legacy.iterdir()) == [legacy / "result.json"], "the reader wrote something"


def test_status_takes_a_relative_path_from_the_repository_root_not_the_current_directory(passing_run):
    tree, directory = passing_run
    status = tree.status(directory.relative_to(tree.root).as_posix())
    assert status.returncode == 0 and "status: PASS" in status.stdout, status.stdout + status.stderr


# --------------------------------------------------------------------------- #
# Process ownership
# --------------------------------------------------------------------------- #
SLEEPER = "import time; time.sleep(120)"


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        kernel32 = ctypes.WinDLL("kernel32")
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = ctypes.c_ulong()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _wait_gone(pid: int, seconds: float = 15) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return True
        time.sleep(0.05)
    return not _pid_alive(pid)


def test_a_grandchild_left_behind_is_a_failed_cleanup_and_an_unrelated_process_survives(tree):
    """Pytest passes and exits, its grandchild does not. The run fails for that, the tree dies, a stranger does not."""
    pid_file = tree.root / "grandchild.pid"
    tree.write("files/tests/test_leaves.py", f"""\
        import subprocess, sys
        from pathlib import Path
        def test_starts_a_process_and_walks_away():
            child = subprocess.Popen([sys.executable, "-c", {SLEEPER!r}])
            Path({str(pid_file)!r}).write_text(str(child.pid), encoding="ascii")
        """)
    stranger = subprocess.Popen([sys.executable, "-c", SLEEPER])
    try:
        outcome = tree.focused("files/tests/test_leaves.py")
        assert outcome.code == 1, outcome
        assert outcome.check("pytest")["status"] == "PASS", "the test itself passed; only the cleanup check catches this"
        gate = outcome.check("cleanup")
        assert gate["status"] == "FAIL" and "left behind" in gate["detail"]
        assert outcome.results["cleanup"]["owned_children_remaining"] >= 1
        violation = outcome.results["cleanup"]["violations"][0]
        assert violation["remaining"] and violation["survivors"] == [], "the stop must end what it found, within its budget"
        assert _wait_gone(int(pid_file.read_text(encoding="ascii"))), "the owned grandchild was not stopped"
        assert stranger.poll() is None, "an unrelated process was killed"
    finally:
        stranger.kill()
        stranger.wait(timeout=30)


def test_a_stalled_child_and_its_grandchild_are_stopped_within_the_budget(tree):
    policy = tree.policy()
    policy["stages"]["pytest"] = {"timeout_seconds": 120, "stall_seconds": 3}
    tree.write_policy(policy)
    pid_file = tree.root / "grandchild.pid"
    tree.write("files/tests/test_hangs.py", f"""\
        import subprocess, sys, time
        from pathlib import Path
        def test_hangs():
            child = subprocess.Popen([sys.executable, "-c", {SLEEPER!r}])
            Path({str(pid_file)!r}).write_text(str(child.pid), encoding="ascii")
            time.sleep(120)
        """)
    began = time.monotonic()
    outcome = tree.focused("files/tests/test_hangs.py")
    assert time.monotonic() - began < 90, "the stall budget did not bound the run"
    assert outcome.code == 1, outcome
    gate = outcome.check("pytest")
    assert gate["status"] == "FAIL" and gate["detail"].startswith("stall")
    assert _wait_gone(int(pid_file.read_text(encoding="ascii"))), "the owned grandchild was not stopped"
    assert Path(outcome.results["cleanup"]["scratch"]).is_dir(), "a failed run keeps its scratch"


def test_a_total_timeout_is_a_failure_even_while_output_keeps_coming(tree):
    policy = tree.policy()
    policy["stages"]["pytest"] = {"timeout_seconds": 3, "stall_seconds": 60}
    tree.write_policy(policy)
    tree.write("files/tests/test_chatters.py", """\
        import time
        def test_chatters():
            for _ in range(600):
                print("still going", flush=True)
                time.sleep(0.1)
        """)
    outcome = tree.focused("files/tests/test_chatters.py")
    assert outcome.code == 1, outcome
    assert outcome.check("pytest")["detail"].startswith("timeout")


def test_output_too_large_for_a_pipe_cannot_block_the_gate(tree):
    """The old gate read a pipe. Output goes straight to a file now, so a grandchild holding it open blocks nothing."""
    tree.write("files/tests/test_loud.py", """\
        import sys
        def test_loud(capfd):
            with capfd.disabled():
                sys.stdout.write("x" * (1 << 22))
                sys.stdout.flush()
        """)
    outcome = tree.focused("files/tests/test_loud.py")
    assert outcome.code == 0, outcome
    assert (outcome.directory / "logs" / "pytest.log").stat().st_size > (1 << 22)


@pytest.mark.parametrize("stage", ["pytest"])
def test_killing_the_gate_kills_its_tree_and_leaves_an_incomplete_run(tree, stage):
    """Nobody is left to clean up, and the kill-on-close job does it anyway. Also proves the marker survives a real kill."""
    pid_file = tree.root / "grandchild.pid"
    tree.write("files/tests/test_waits.py", f"""\
        import subprocess, sys, time
        from pathlib import Path
        def test_waits():
            child = subprocess.Popen([sys.executable, "-c", {SLEEPER!r}])
            Path({str(pid_file)!r}).write_text(str(child.pid), encoding="ascii")
            time.sleep(120)
        """)
    proc = subprocess.Popen([sys.executable, str(tree.gate / "verify.py"), "--mode", "focused", "--test=files/tests/test_waits.py"],
                            cwd=tree.outside, env=tree.environment(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 60
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert pid_file.exists(), "the test never started"
        time.sleep(0.2)
    finally:
        proc.kill()
        proc.wait(timeout=30)
    if sys.platform == "win32":
        assert _wait_gone(int(pid_file.read_text(encoding="ascii"))), "the job did not take the tree with it"
    else:
        os.kill(int(pid_file.read_text(encoding="ascii")), signal.SIGKILL)
    run = next(tree.outputs.iterdir())
    assert not (run / "results.json").exists()
    assert json.loads((run / "INCOMPLETE.json").read_text(encoding="utf-8"))["lifecycle"] == "running"
    status = tree.status(str(run))
    assert status.returncode == 3 and "status: INCOMPLETE" in status.stdout
    owners = [json.loads(path.read_text(encoding="utf-8"))["run_id"] for path in (tree.system_temp / "act-gate").glob("*/act-gate-owner.json")]
    assert owners == [run.name], "the killed run's scratch stays where this tree put it, never in the real %TEMP%\\act-gate"


@WINDOWS_ONLY
def test_ownership_that_cannot_be_established_is_blocked_rather_than_run_unowned(tree):
    launcher = _patched_gate(tree, """\
        def refuse(*args, **kwargs):
            raise gate.winproc.JobUnavailable("AssignProcessToJobObject failed: error 5 (synthetic)")
        gate.winproc._Job = refuse
        """)
    outcome = tree.run("--mode", "focused", "--test=files/tests/test_ordinary.py", script=launcher)
    assert outcome.code == 2, outcome
    gate = outcome.check("process-ownership")
    assert gate["status"] == "BLOCKED" and "error 5" in gate["detail"]
    assert outcome.results["counts"]["executed"] == 0


def _junction_or_skip(target: Path, link: Path) -> None:
    try:
        if sys.platform == "win32":
            import _winapi

            _winapi.CreateJunction(str(target), str(link))
        else:
            link.symlink_to(target, target_is_directory=True)
    except (OSError, AttributeError) as exc:
        pytest.skip(f"cannot create a link here: {exc}")


@pytest.mark.parametrize("linked", ["scratch", "guarded"])
def test_a_scratch_or_guarded_root_that_is_a_junction_stops_the_run_and_its_target_is_untouched(tree, linked):
    """Scratch and pytest basetemps get deleted. A junction here would aim that at whatever it points to."""
    outside = tree.root.parent / "outside"
    outside.mkdir()
    sentinel = outside / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    tree.system_temp.mkdir(exist_ok=True)
    link = tree.system_temp / "act-gate" if linked == "scratch" else tree.root / "files/dev-work/p05b-stage4c"
    link.parent.mkdir(parents=True, exist_ok=True)
    _junction_or_skip(outside, link)
    outcome = tree.full()
    assert outcome.code == 2, outcome
    assert outcome.results["status"] == "BLOCKED" and outcome.results["counts"]["executed"] == 0
    detail = " ".join(str(item["detail"]) for item in outcome.results["checks"])
    assert "link or junction" in detail, detail
    assert sentinel.read_text(encoding="utf-8") == "keep" and [path.name for path in outside.iterdir()] == ["keep.txt"]


def test_a_failing_stage_still_runs_the_others_but_a_blocked_preflight_stops_everything(tree):
    tree.write("scripts/requirements.txt", "pytest==0.0.1\n")
    outcome = tree.focused("files/tests/test_ordinary.py")
    assert outcome.code == 2, outcome
    assert "the requirements pin 0.0.1" in outcome.check("interpreter")["detail"]
    assert outcome.results["counts"]["executed"] == 0 and not (outcome.directory / "logs" / "pytest.log").exists()


def test_bad_policy_is_an_invalid_configuration_with_a_record(tree):
    (tree.gate / "verification.json").write_text("{ not json", encoding="utf-8")
    outcome = tree.focused("files/tests/test_ordinary.py")
    assert outcome.code == 64, outcome
    assert "verification.json is unusable" in outcome.check("policy")["detail"]


# --------------------------------------------------------------------------- #
# Windows error dialogs (the protection Phase 1 needed an ignored helper for)
# --------------------------------------------------------------------------- #
INVALID_EXECUTABLE_TEST = """\
    import ctypes, subprocess, time
    from pathlib import Path

    def test_an_invalid_executable_fails_at_once_and_no_dialog_holds_it(tmp_path):
        mode = ctypes.WinDLL("kernel32").GetErrorMode()
        assert mode & 0x8003 == 0x8003, hex(mode)
        stub = tmp_path / "ffprobe.exe"
        stub.write_text("sandbox binary", encoding="utf-8")
        began = time.monotonic()
        try:
            subprocess.run([str(stub), "-version"], capture_output=True, timeout=30)
        except OSError as exc:
            assert exc.winerror == 216, exc
        else:
            raise AssertionError("the stub started")
        assert time.monotonic() - began < 5
    """


@WINDOWS_ONLY
def test_the_gate_started_from_a_mode_zero_parent_protects_its_real_pytest_child(tree):
    """The Phase 1 failure itself. CREATE_DEFAULT_ERROR_MODE starts the gate at mode 0, as a detached launch did; the gate
    must establish the flags on itself, the pytest child must inherit them, and starting the fixture's invalid executable
    must fail at once instead of opening a dialog. The test inside proves the last two, and a dialog would trip the stall."""
    policy = tree.policy()
    policy["stages"]["pytest"] = {"timeout_seconds": 60, "stall_seconds": 30}
    tree.write_policy(policy)
    tree.write("files/tests/test_stub.py", INVALID_EXECUTABLE_TEST)
    outcome = tree.focused("files/tests/test_stub.py", creationflags=subprocess.CREATE_DEFAULT_ERROR_MODE)
    assert outcome.code == 0, outcome
    start = json.loads((outcome.directory / "start.json").read_text(encoding="utf-8"))
    assert start["error_mode"] == {"applicable": True, "found": "0x0", "established": "0x8003", "ok": True}
    assert "inherited 0x8003" in outcome.check("error-mode")["detail"]
    assert outcome.check("error-mode-held")["status"] == "PASS"


@WINDOWS_ONLY
def test_the_real_pytest_child_reports_its_mode_and_a_drift_is_recorded_and_repaired(tree):
    """The observed 0x8003 -> 0x8001. A test clears the crash-dialog flag, as overlapping process starts can; the next
    boundary finds it, restores it and records it. The run passes, because the flag that matters for the invalid executable
    never left."""
    tree.write("files/tests/test_drift.py", """\
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32")

        def test_loses_the_flag_as_overlapping_process_starts_can():
            kernel32.SetErrorMode(0x8001)
            assert kernel32.GetErrorMode() == 0x8001

        def test_finds_it_restored():
            assert kernel32.GetErrorMode() & 0x8003 == 0x8003
        """)
    outcome = tree.focused("files/tests/test_drift.py")
    assert outcome.code == 0, outcome
    gate = outcome.check("error-mode-held")
    assert gate["status"] == "PASS"
    assert gate["drifts"] and gate["drifts"][0]["found"] == "0x8001" and gate["drifts"][0]["restored"] == "0x8003"


@WINDOWS_ONLY
def test_losing_the_flag_that_stops_the_dialog_fails_the_run(tree):
    tree.write("files/tests/test_drift.py", """\
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32")

        def test_clears_everything():
            kernel32.SetErrorMode(0)

        def test_next():
            pass
        """)
    outcome = tree.focused("files/tests/test_drift.py")
    assert outcome.code == 1, outcome
    assert outcome.check("pytest")["status"] == "PASS"
    gate = outcome.check("error-mode-held")
    assert gate["status"] == "FAIL" and "was clear" in gate["detail"]


@WINDOWS_ONLY
def test_process_creation_never_clears_the_flag_that_matters():
    """Regression for the cause: process creation goes through 0x8001 without the crash-dialog flag, and overlapping starts
    can leave it there. It must never touch SEM_FAILCRITICALERRORS, or the suite's invalid executable would open a dialog."""
    import threading

    kernel32 = ctypes.WinDLL("kernel32")
    before = kernel32.GetErrorMode()
    kernel32.SetErrorMode(before | 0x8003)
    seen, stop = set(), threading.Event()

    def watch():
        while not stop.is_set():
            seen.add(kernel32.GetErrorMode())

    def spawn():
        for _ in range(6):
            subprocess.run(["cmd", "/c", "rem"], capture_output=True, check=False)

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    workers = [threading.Thread(target=spawn, daemon=True) for _ in range(4)]
    try:
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=60)
    finally:
        stop.set()
        watcher.join(timeout=10)
        kernel32.SetErrorMode(before | 0x8003)
    assert seen and all(mode & 1 for mode in seen), sorted(hex(mode) for mode in seen)


@WINDOWS_ONLY
def test_a_child_that_cannot_prove_the_mode_blocks_the_run(tree):
    launcher = _patched_gate(tree, """\
        gate._dialog_probe_source = lambda stub: "import json;print(json.dumps({'mode':'0x0','refused':True}))"
        """)
    outcome = tree.run("--mode", "focused", "--test=files/tests/test_ordinary.py", script=launcher)
    assert outcome.code == 2, outcome
    assert outcome.check("error-mode")["status"] == "BLOCKED"
    assert outcome.results["counts"]["executed"] == 0


# --------------------------------------------------------------------------- #
# The changed-area selection
# --------------------------------------------------------------------------- #
def test_changed_mode_maps_a_changed_test_and_never_claims_full_acceptance(tree):
    git(tree.root, "branch", "base")
    tree.write("files/tests/test_ordinary.py", PASSING + "\n\ndef test_three():\n    pass\n")
    tree.commit()
    outcome = tree.run("--mode", "changed", "--base", "base")
    assert outcome.code == 0, outcome
    selection = json.loads((outcome.directory / "selection.json").read_text(encoding="utf-8"))
    assert selection["kind"] == "changed" and selection["ordinary"] == ["files/tests/test_ordinary.py"]
    assert selection["guarded"] == {}
    assert outcome.results["scope"]["full_acceptance"] is False
    assert outcome.results["counts"]["executed"] == 3


def test_changed_mode_widens_to_everything_for_an_unmapped_path(tree):
    git(tree.root, "branch", "base")
    tree.write("some/new/place.txt", "x\n")
    tree.commit()
    outcome = tree.run("--mode", "changed", "--base", "base")
    selection = json.loads((outcome.directory / "selection.json").read_text(encoding="utf-8"))
    assert selection["kind"] == "changed-conservative-full"
    assert any("no selection rule" in reason for reason in selection["widened_because"])
    assert outcome.results["counts"]["executed"] == 4 and outcome.results["scope"]["full_acceptance"] is False


def test_changed_mode_with_an_unknown_base_is_an_invalid_invocation(tree):
    outcome = tree.run("--mode", "changed", "--base", "no-such-ref")
    assert outcome.code == 64, outcome
    assert "cannot be resolved" in outcome.check("selection")["detail"]


def test_the_changed_selection_rules(tmp_path):
    load_gate("act_verify_contract_selection")
    from helpers import selection

    policy = {"always": ["files/tests/test_guard.py"], "no_selection": ["md-instructions/", "README.md"],
              "routes": {".gitignore": ["files/tests/test_ignore.py"]}, "full_on": ["scripts/shared/", "files/tests/conftest.py"]}
    sources = {"files/tests/test_guard.py": "", "files/tests/test_a.py": "from tts import engine\n", "files/tests/test_b.py": "import other\n"}
    chosen = selection.select_for_changes(["md-instructions/Handoff.md", "README.md"], policy, sources)
    assert chosen.tests == ["files/tests/test_guard.py"] and not chosen.conservative_full and len(chosen.ignored) == 2
    chosen = selection.select_for_changes(["scripts/tts/engine.py"], policy, sources)
    assert chosen.tests == ["files/tests/test_a.py", "files/tests/test_guard.py"] and not chosen.conservative_full
    chosen = selection.select_for_changes([".gitignore"], policy, sources)
    assert "files/tests/test_ignore.py" in chosen.tests
    for path, needle in (("scripts/shared/paths.py", "shared"), ("files/tests/conftest.py", "shared"),
                         ("scripts/tts/nobody_names_me.py", "no test names"), ("elsewhere/file.bin", "no selection rule")):
        chosen = selection.select_for_changes([path], policy, sources)
        assert chosen.conservative_full and any(needle in reason for reason in chosen.reasons), path


def test_a_selector_is_normalized_in_its_path_and_left_alone_in_its_node():
    load_gate("act_verify_contract_selector")
    from helpers import selection

    assert selection.parse_selector("files\\tests\\test_a.py") == "files/tests/test_a.py"
    node = "files/tests/test_a.py::test_x[a/b c]"
    assert selection.parse_selector(node) == node
    assert selection.in_suite_order(["files/tests/test_b.py", "files/tests/test_a.py::x", "files/tests/test_a.py::x"]) == [
        "files/tests/test_a.py::x", "files/tests/test_b.py"]


# --------------------------------------------------------------------------- #
# Removal of a run's own scratch, and only that
# --------------------------------------------------------------------------- #
def test_a_record_written_while_something_briefly_holds_it_still_lands_and_a_real_refusal_still_raises(tmp_path, monkeypatch):
    """Measured on HOME-PC: something outside the process holds paths just created under the repository for about a millisecond."""
    load_gate("act_verify_contract_settled")
    from helpers import runstore

    real_replace, attempts = os.replace, []

    def briefly_held(source, target):
        attempts.append(target)
        if len(attempts) < 3:
            raise PermissionError(13, "Access is denied")
        real_replace(source, target)

    monkeypatch.setattr(runstore.os, "replace", briefly_held)
    target = tmp_path / "results.json"
    runstore.write_json_atomic(target, {"a": 1})
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1} and len(attempts) == 3

    def always_refused(source, target):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(runstore.os, "replace", always_refused)
    monkeypatch.setattr(runstore, "_SETTLE_DELAYS", (0.0, 0.0))
    with pytest.raises(PermissionError):
        runstore.write_json_atomic(target, {"a": 2})
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}, "the old record must survive a refused replace"


def test_removing_scratch_never_follows_a_junction_out_of_it(tmp_path):
    load_gate("act_verify_contract_remove")
    from helpers import runstore

    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    run = tmp_path / "run"
    scratch = run / "temp"
    (scratch / "deep").mkdir(parents=True)
    (scratch / "deep" / "file.txt").write_text("x", encoding="utf-8")
    link = scratch / "deep" / "escape"
    try:
        if sys.platform == "win32":
            import _winapi

            _winapi.CreateJunction(str(outside), str(link))
        else:
            link.symlink_to(outside, target_is_directory=True)
    except (OSError, AttributeError) as exc:
        pytest.skip(f"cannot create a link here: {exc}")
    assert runstore.safe_remove_tree(scratch, within=run) == []
    assert not scratch.exists() and sentinel.read_text(encoding="utf-8") == "keep"


def test_a_run_directory_outside_its_base_is_refused_rather_than_crashing(tmp_path):
    load_gate("act_verify_contract_outside")
    from helpers import runstore

    with pytest.raises(runstore.RunRefused, match="is not inside"):
        runstore.reserve_run_dir(tmp_path / "somewhere" / "outputs", tmp_path / "elsewhere", "full")
    assert not (tmp_path / "somewhere").exists()


def test_removing_a_tree_that_is_itself_a_link_or_outside_its_parent_is_refused(tmp_path):
    load_gate("act_verify_contract_refuse")
    from helpers import runstore

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")
    run = tmp_path / "run"
    run.mkdir()
    with pytest.raises(runstore.RunRefused):
        runstore.safe_remove_tree(outside, within=run)
    with pytest.raises(runstore.RunRefused):
        runstore.safe_remove_tree(run, within=run)
    link = run / "temp"
    try:
        if sys.platform == "win32":
            import _winapi

            _winapi.CreateJunction(str(outside), str(link))
        else:
            link.symlink_to(outside, target_is_directory=True)
    except (OSError, AttributeError) as exc:
        pytest.skip(f"cannot create a link here: {exc}")
    with pytest.raises(runstore.RunRefused, match="link or junction"):
        runstore.safe_remove_tree(link, within=run)
    assert (outside / "keep.txt").is_file()


def test_no_active_caller_depends_on_the_retired_gate_path():
    """Migration is complete only when nothing active still names ``scripts/verify.py``.

    What may still name it, and why: the plans and the permanent history record past commands and stay true as history;
    so do the review reports kept as Markdown in ``files/dev-work/phase9-remote-review/`` (v0.7.2 Phase 9: an independent
    reviewer's report is never edited afterwards, and two say the retired path was not run); this test and the packaging
    test assert its absence; and one comment in ``scripts/requirements.txt`` is byte-hash-locked into setup (editing it
    would make every installed environment look stale), so it waits for the next dependency change.
    """
    assert not (REPO_ROOT / "scripts" / "verify.py").exists()
    done = subprocess.run(["git", "grep", "-l", "-F", "scripts/verify.py"], cwd=REPO_ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if done.returncode not in (0, 1):
        pytest.skip("not a git checkout")
    assert active_callers_of_the_retired_path(done.stdout) == []


def active_callers_of_the_retired_path(listed: str) -> list[str]:
    """Of ``git grep -l`` output naming ``scripts/verify.py``, the paths that are not history or the tests asserting absence."""
    allowed = {"files/tests/test_verification_gate_contract.py", "files/tests/test_release_packaging.py",
               "scripts/requirements.txt", "md-instructions/Handoff.md", "md-instructions/Decisions.md",
               "md-instructions/Changelog.md", "md-instructions/Briefing.md"}
    return [path for path in listed.splitlines()
            if path not in allowed and not path.startswith(("files/plans/", "files/release-history/"))
            and not (path.startswith("files/dev-work/phase9-remote-review/") and path.endswith(".md")
                     and "/" not in path[len("files/dev-work/phase9-remote-review/"):])]


def test_only_history_and_the_absence_tests_may_name_the_retired_gate_path():
    """The exemptions above, held exactly: a review report is history; code, a nested file or any other folder is not."""
    history = "\n".join(["files/plans/old.md", "files/release-history/x.md", "md-instructions/Handoff.md",
                         "files/dev-work/phase9-remote-review/PHASE9-CODEX-FOCUSED-CLOSURE.md"])
    assert active_callers_of_the_retired_path(history) == []
    for active in ("files/dev-work/phase9-remote-review/probe.py", "files/dev-work/phase9-remote-review/sub/notes.md",
                   "files/dev-work/verification-gate/verify.py", "scripts/launcher.py", "README.md",
                   "files/dev-work/phase9-remote-review.md"):
        assert active_callers_of_the_retired_path(history + "\n" + active) == [active], active


# --------------------------------------------------------------------------- #
# The native and real-media stage, proved from outside with a scripted runner (v0.7.2 Phase 3)
# --------------------------------------------------------------------------- #
#: Stands where acceptance_runner.py stands, as a real child under the gate's real job: it writes what it is told to and exits as it is told to.
_SCRIPTED_RUNNER = """
import argparse, json, os, sys, time
from pathlib import Path
parser = argparse.ArgumentParser()
for name in ("report", "token", "evidence", "scratch"):
    parser.add_argument("--" + name)
parser.add_argument("--only", action="append", default=[])
args = parser.parse_args()
script = json.loads((Path(__file__).parent / "scripted.json").read_text(encoding="utf-8"))
if script.get("hang"):
    time.sleep(120)
if script.get("no_report"):
    sys.exit(script.get("exit", 0))
evidence = Path(args.evidence)
entries = []
for identifier in args.only:
    folder = evidence / identifier
    (folder / "screenshots").mkdir(parents=True)
    (folder / "app-actions.jsonl").write_text("{}", encoding="utf-8")
    (folder / "screenshots" / "done.png").write_bytes(bytes.fromhex("89504e470d0a1a0a") + bytes(32))
    entry = {"id": identifier, "tool": "mp3-tool", "layers": ["native", "media"], "tier": "journey", "status": "PASS", "reason": "", "seconds": 1.0,
             "checks": [{"name": "output", "ok": True, "detail": ""}], "outputs": [{"name": "a.mp3", "bytes": 1, "sha256": "ab"}],
             "fixtures": [{"id": "t", "kind": "mp3-track", "validation": [{"name": "decodes", "ok": True}]}],
             "screenshots": [{"name": "done.png", "path": identifier + "/screenshots/done.png"}], "native_inputs": 3, "sessions": ["app"], "notes": {}}
    entry.update(script.get("entry", {}))
    entries.append(entry)
report = {"schema_version": 1, "token": script.get("token", args.token), "registered": script.get("registered", args.only), "scenarios": entries,
          "finished": True, "unknown": [], "runtime_before": {"a": 1}, "runtime_after": script.get("after", {"a": 1}),
          "dialog_history": {"preflight": {"verdict": "contained"}, "before": 0, "after": 0, "added": {}}}
report.update(script.get("report", {}))
Path(args.report).write_text(json.dumps(report), encoding="utf-8")
sys.exit(script.get("exit", 0))
"""


def _with_runner(tree, script=None, *, required=("mp3.journey",), tools=("mp3-tool",), **policy_overrides) -> None:
    tree.write("files/dev-work/verification-gate/acceptance_runner.py", _SCRIPTED_RUNNER)
    tree.write("files/dev-work/verification-gate/scripted.json", json.dumps(script or {}))
    policy = tree.policy()
    policy["acceptance"] = {"required_tools": list(tools), "required_scenarios": list(required), "optional_scenarios": [], "journey_routes": {}}
    policy["stages"]["acceptance"] = {"timeout_seconds": 60, "stall_seconds": 6}
    policy.update(policy_overrides)
    tree.write_policy(policy)
    tree.commit("acceptance")


def _journey(tree, *ids, **kwargs):
    return tree.run("--mode", "focused", *[f"--journey={item}" for item in ids], **kwargs)


def _with_feature(tree, verification, **extra) -> None:
    tree.write("files/dev-work/verification-gate/coverage.json", json.dumps({"schema_version": 1, "inventory_reviewed": False, "features": [
        {"id": "ACT.MP3.X", "tool": "mp3-tool", "release_required": True, "source": [], "verification": {"all_of": verification}, **extra}]}))
    tree.commit("coverage")


def test_the_no_change_control_a_complete_journey_passes_the_stage(tree):
    _with_runner(tree)
    outcome = _journey(tree, "mp3.journey")
    assert outcome.code == 0, outcome
    assert outcome.check("acceptance")["status"] == "PASS"
    assert (outcome.directory / "acceptance-report.md").is_file() and (outcome.directory / "visual-candidates.md").is_file()
    assert (outcome.directory / "acceptance" / "mp3.journey" / "screenshots" / "done.png").is_file()
    assert "focused selection only" in outcome.stdout


_MAPPED = [{"kind": "native", "scenario": "mp3.journey"}, {"kind": "media", "scenario": "mp3.journey"}]


def test_a_full_run_requires_every_registered_journey_and_it_runs_first(tree):
    _with_runner(tree)
    _with_feature(tree, _MAPPED)
    outcome = tree.full()
    assert outcome.code == 0, outcome
    names = [item["name"] for item in outcome.results["checks"]]
    assert names.index("acceptance") < names.index("pytest") < names.index("guarded")
    assert outcome.check("coverage")["status"] == "PASS"


def test_an_unknown_journey_is_an_invalid_invocation(tree):
    _with_runner(tree)
    outcome = _journey(tree, "nothing.here")
    assert outcome.code == 64 and "unknown journey" in outcome.results["invocation_error"]


def test_a_journey_with_no_tests_or_selection_is_refused_before_anything_runs(tree):
    _with_runner(tree)
    done = tree.run("--mode", "focused")
    assert done.code == 64 and "an empty selection is not a test run" in done.stderr


def test_no_report_from_the_runner_is_not_run(tree):
    _with_runner(tree, {"no_report": True})
    outcome = _journey(tree, "mp3.journey")
    assert outcome.code == 3 and outcome.check("acceptance")["status"] == "NOT RUN", outcome


def test_a_runner_that_exits_badly_with_a_clean_looking_report_is_a_failure(tree):
    """A fake PASS the other way round: the report looks fine and the child says otherwise."""
    _with_runner(tree, {"exit": 1})
    outcome = _journey(tree, "mp3.journey")
    assert outcome.code == 1 and "disagree" in outcome.check("acceptance")["detail"], outcome


def test_a_report_copied_from_an_old_run_is_refused(tree):
    _with_runner(tree, {"token": "2020-01-01_000000_full_0000-acceptance"})
    outcome = _journey(tree, "mp3.journey")
    assert outcome.code == 1 and "copied or stale" in outcome.check("acceptance")["detail"], outcome


def test_a_status_contradicting_its_checks_is_a_failure(tree):
    _with_runner(tree, {"entry": {"checks": [{"name": "tag", "ok": False, "detail": "wrong"}]}})
    outcome = _journey(tree, "mp3.journey")
    assert outcome.code == 1 and "failed checks" in outcome.check("acceptance")["detail"], outcome


def test_a_claimed_pass_with_no_media_output_is_a_failure(tree):
    _with_runner(tree, {"entry": {"outputs": []}})
    outcome = _journey(tree, "mp3.journey")
    assert outcome.code == 1 and "no inspected output" in outcome.check("acceptance")["detail"], outcome


def test_a_claimed_pass_with_no_picture_is_a_failure(tree):
    _with_runner(tree, {"entry": {"screenshots": []}})
    outcome = _journey(tree, "mp3.journey")
    assert outcome.code == 1 and "no screenshot" in outcome.check("acceptance")["detail"], outcome


def test_a_locked_desktop_is_blocked_and_the_rest_of_the_run_still_happens(tree):
    _with_runner(tree, {"report": {"blocked": "DesktopUnavailable: the input desktop cannot be opened"}})
    _with_feature(tree, _MAPPED)
    outcome = tree.full()
    assert outcome.code == 2 and outcome.results["status"] == "BLOCKED", outcome
    assert outcome.check("acceptance")["status"] == "BLOCKED"
    assert outcome.check("pytest")["status"] == "PASS", "a missing desktop does not stop what can still run"


def test_a_failure_outranks_a_blocked_desktop_and_both_stay_visible(tree):
    _with_runner(tree, {"report": {"blocked": "DesktopUnavailable: locked"}})
    _with_feature(tree, _MAPPED)
    tree.write("files/tests/test_bad.py", "def test_bad():\n    assert False\n")
    tree.commit("a failing test")
    outcome = tree.full()
    assert outcome.code == 1 and outcome.results["status"] == "FAIL", outcome
    assert outcome.check("acceptance")["status"] == "BLOCKED" and outcome.check("pytest")["status"] == "FAIL"


def test_a_hung_runner_is_stopped_and_fails(tree):
    _with_runner(tree, {"hang": True})
    began = time.monotonic()
    outcome = _journey(tree, "mp3.journey")
    assert time.monotonic() - began < 60, "the stall budget did not bound the stage"
    assert outcome.code == 1 and "stall" in outcome.check("acceptance")["detail"], outcome


def test_writing_outside_the_run_is_a_failure(tree):
    _with_runner(tree, {"after": {"a": 2}})
    outcome = _journey(tree, "mp3.journey")
    assert outcome.code == 1 and "runtime data" in outcome.check("acceptance")["detail"], outcome


def test_a_tool_with_no_complete_journey_stops_a_full_run(tree):
    _with_runner(tree, tools=("mp3-tool", "cover-image"))
    outcome = tree.full()
    assert outcome.code == 1 and "cover-image has no complete" in outcome.check("acceptance")["detail"], outcome


def test_a_scenario_added_without_a_policy_edit_stops_the_run(tree):
    _with_runner(tree, {"registered": ["mp3.journey", "sneaked.in"]})
    outcome = _journey(tree, "mp3.journey")
    assert outcome.code == 1 and "sneaked.in" in outcome.check("acceptance")["detail"], outcome


def test_a_dead_test_id_in_the_inventory_stops_a_full_run(tree):
    _with_runner(tree)
    _with_feature(tree, [{"kind": "behavior", "test": "files/tests/test_ordinary.py::test_deleted_long_ago"}])
    outcome = tree.full()
    assert outcome.code == 1 and "dead test id" in outcome.check("coverage")["detail"], outcome


def test_a_dead_scenario_in_the_inventory_stops_a_full_run(tree):
    _with_runner(tree)
    _with_feature(tree, [{"kind": "native", "scenario": "gone.away"}])
    outcome = tree.full()
    assert outcome.code == 1 and "dead scenario id" in outcome.check("coverage")["detail"], outcome


def test_a_test_standing_in_for_native_evidence_stops_a_full_run(tree):
    _with_runner(tree)
    _with_feature(tree, [{"kind": "native", "test": "files/tests/test_ordinary.py::test_one"}])
    outcome = tree.full()
    assert outcome.code == 1 and "a test cannot stand in" in outcome.check("coverage")["detail"], outcome


def test_a_sound_mapping_is_satisfied_by_what_really_ran(tree):
    _with_runner(tree)
    _with_feature(tree, [{"kind": "behavior", "test": "files/tests/test_ordinary.py::test_one"}, {"kind": "native", "scenario": "mp3.journey"},
                         {"kind": "media", "scenario": "mp3.journey"}])
    outcome = tree.full()
    assert outcome.code == 0, outcome
    coverage = outcome.results["coverage"]
    assert coverage["mapped_required"] == coverage["satisfied_required"] == 1 and coverage["inventory_reviewed"] is False
    assert (outcome.directory / "coverage-report.md").is_file()


def test_a_baseline_an_agent_approved_stops_the_run_and_a_run_never_writes_one(tree):
    _with_runner(tree)
    approved = tree.gate / "baselines" / "approved.json"
    untouched = approved.read_bytes()
    outcome = _journey(tree, "mp3.journey")
    assert outcome.code == 0 and approved.read_bytes() == untouched, "a normal run must not touch the approved list"
    assert outcome.check("visual-baselines")["status"] == "NOT RUN", "listing candidates is not comparing or approving them"
    tree.write("files/dev-work/verification-gate/baselines/approved.json", json.dumps({"approved": [
        {"name": "x", "approved_by": "claude", "sha256": "a", "os": "w", "tk": "8.6", "dpi": 96, "client": [1, 1]}]}))
    tree.commit("a self-approved baseline")
    outcome = _journey(tree, "mp3.journey")
    assert outcome.code == 1 and "not approved by the owner" in outcome.check("visual-baselines")["detail"], outcome


def test_deleting_a_picture_after_the_run_invalidates_its_pass(tree):
    _with_runner(tree)
    outcome = _journey(tree, "mp3.journey")
    assert outcome.code == 0, outcome
    assert tree.status(str(outcome.directory)).returncode == 0
    (outcome.directory / "acceptance" / "mp3.journey" / "screenshots" / "done.png").unlink()
    status = tree.status(str(outcome.directory))
    assert status.returncode == 3 and "status: INVALID" in status.stdout and "done.png" in status.stdout, status.stdout


def test_a_failed_test_leaves_its_folder_in_the_runs_evidence(tree):
    tree.write("files/tests/test_bad.py", "from pathlib import Path\n\ndef test_bad(tmp_path):\n    (tmp_path / 'why.txt').write_text('because')\n    assert False\n")
    tree.commit("a failing test")
    outcome = tree.focused("files/tests/test_bad.py")
    assert outcome.code == 1, outcome
    assert (outcome.directory / "failed-scratch" / "pytest" / "test_bad0" / "why.txt").read_text() == "because"
    assert Path(outcome.results["cleanup"]["scratch"]).is_dir(), "the scratch itself stays until someone deliberately removes it"


def test_a_runs_scratch_carries_its_owner_and_the_audit_reads_it(tree):
    tree.write("files/tests/test_bad.py", "def test_bad():\n    assert False\n")
    tree.commit("a failing test")
    outcome = tree.focused("files/tests/test_bad.py")
    scratch = Path(outcome.results["cleanup"]["scratch"])
    owner = json.loads((scratch / "act-gate-owner.json").read_text(encoding="utf-8"))
    assert owner["run_id"] == outcome.directory.name and owner["kind"] == "act-gate-scratch"
    done = tree.run("--audit-scratch")
    assert done.code == 0 and scratch.name in done.stdout and "abandoned" in done.stdout and scratch.is_dir(), done


# --------------------------------------------------------------------------- #
# Reading a qualification run back (v0.7.2 Phase 8 remediation)
# --------------------------------------------------------------------------- #
# Until this phase the reader applied "PASS with no executed tests" to qualification runs too. A qualification collects
# no test and runs no journey, so every true qualification PASS read INVALID (Phase 7B's among them): the reader could
# refuse a true PASS, though never certify a false one. Each test below makes a real run with a real runner of the
# scenario, through the gate, and reads it back through the public --status.
SCENARIO_RUNNER = '''
import json, subprocess, sys, time
from pathlib import Path
out = Path(sys.argv[sys.argv.index("--out") + 1])
out.mkdir(parents=True)
(out / "progress.log").write_text("started\\n")
head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
(out / "identity.json").write_text(json.dumps({{"scenario": "m4b-scaling", "head": head}}))
(out / "runs.json").write_text(json.dumps([{{"label": f"run-{{n}}"}} for n in range({runs})]))
{before}
{write_verdict}
sys.exit({code})
'''
TWO_CHECKS = [{"name": "T8:one", "status": "PASS", "detail": "identical"}, {"name": "T1", "status": "PASS", "detail": "2.1x"}]
#: What this small tree's policy says a PASS of the scenario holds: the two checks above, by name and by family, and three runs.
SMALL_PASS = {"checks": 2, "runs": 3, "names": ["T1"], "families": {"T8:": 1}}
_UNSET = object()


def _qualification(tree, verdict, code: int, *, before: str = "", requires=_UNSET, stage: dict | None = None):
    """One real qualification run of m4b-scaling whose runner leaves its identity and its runs, writes *verdict* (a string is
    written as it is; ``None`` writes no verdict) and exits *code*. *before* runs just before the verdict is written."""
    counted = verdict.get("runs") if isinstance(verdict, dict) else 0
    written = ("" if verdict is None else f'(out / "verdict.json").write_text({verdict!r})' if isinstance(verdict, str)
               else f'(out / "verdict.json").write_text(json.dumps({verdict!r}))')
    (tree.gate / "scaling" / "qualify.py").write_text(textwrap.dedent(SCENARIO_RUNNER).format(
        write_verdict=written, code=code, before=before, runs=counted if type(counted) is int else 0), encoding="utf-8")
    policy = tree.policy()
    if requires is None:
        policy["scenarios"]["m4b-scaling"].pop("pass_requires", None)
    else:
        policy["scenarios"]["m4b-scaling"]["pass_requires"] = SMALL_PASS if requires is _UNSET else requires
    if stage is not None:
        policy["stages"]["qualification"] = stage
    tree.write_policy(policy)
    tree.commit("a small runner for the scenario")
    return tree.run("--mode", "qualification", "--scenario", "m4b-scaling")


def _verdict(status: str, checks=None, runs: int = 3) -> dict:
    return {"scenario": "m4b-scaling", "status": status, "reason": "as planted", "runs": runs,
            "checks": TWO_CHECKS if checks is None else checks}


@pytest.fixture
def qualified_run(tree):
    outcome = _qualification(tree, _verdict("PASS"), 0)
    assert outcome.code == 0 and outcome.results["status"] == "PASS", outcome
    return tree, outcome.directory


def test_a_sealed_qualification_pass_reads_pass(qualified_run):
    """The defect: this very record, with no test executed and no journey passed, read INVALID."""
    tree, directory = qualified_run
    results = json.loads((directory / "results.json").read_text(encoding="utf-8"))
    assert results["counts"]["executed"] == 0 and results["counts"]["journeys_passed"] == 0, "the condition the old rule refused"
    assert results["qualification"]["ran"] == {"m4b-scaling": "PASS"}
    status = tree.status(str(directory))
    assert status.returncode == 0 and "status: PASS" in status.stdout and "problem" not in status.stdout, status.stdout
    current = tree.status(str(directory), "--require-current")
    assert current.returncode == 0 and "current: exact" in current.stdout, current.stdout


def test_the_no_executed_tests_rule_still_stands_for_every_other_mode(qualified_run):
    """The control of the repair: the rule was not removed, only kept away from the one mode that executes no test."""
    tree, directory = qualified_run
    _rewrite_results(directory, lambda r: r.update(mode="focused"), reseal=True)
    status = tree.status(str(directory))
    assert status.returncode == 3 and "status: INVALID" in status.stdout and "PASS with no executed tests" in status.stdout, status.stdout


def test_a_sealed_qualification_fail_stays_fail(tree):
    failing = [*TWO_CHECKS, {"name": "T5:scale1000:tput-scale1000-180", "status": "FAIL", "detail": "68 bytes"}]
    outcome = _qualification(tree, _verdict("FAIL", failing), 1)
    assert outcome.code == 1, outcome
    status = tree.status(str(outcome.directory))
    assert status.returncode == 1 and "status: FAIL" in status.stdout and "problem" not in status.stdout, status.stdout
    assert tree.status(str(outcome.directory), "--require-current").returncode == 1


def test_a_sealed_qualification_blocked_stays_blocked(tree):
    """The real runner in this small tree: the application's M4B code is not here, so it says BLOCKED."""
    outcome = tree.run("--mode", "qualification", "--scenario", "m4b-scaling")
    assert outcome.code == 2, outcome
    status = tree.status(str(outcome.directory))
    assert status.returncode == 2 and "status: BLOCKED" in status.stdout and "problem" not in status.stdout, status.stdout


def test_a_pass_verdict_from_a_runner_that_did_not_exit_zero_reads_fail_never_pass(tree):
    outcome = _qualification(tree, _verdict("PASS"), 1)
    assert outcome.code == 1, outcome
    status = tree.status(str(outcome.directory))
    assert status.returncode == 1 and "status: FAIL" in status.stdout, status.stdout


def test_a_qualification_stopped_part_way_is_incomplete_and_never_a_pass(tree):
    """A real interruption: the gate is killed while the scenario's runner works. What is left has no verdict."""
    started = tree.root / "runner-started"
    (tree.gate / "scaling" / "qualify.py").write_text(textwrap.dedent(SCENARIO_RUNNER).format(
        write_verdict=f'(out / "verdict.json").write_text(json.dumps({_verdict("PASS")!r}))', code=0, runs=3,
        before=f"Path({str(started)!r}).write_text('x')\ntime.sleep(120)"), encoding="utf-8")
    tree.commit("a runner that is still working")
    proc = subprocess.Popen([sys.executable, str(tree.gate / "verify.py"), "--mode", "qualification", "--scenario", "m4b-scaling"],
                            cwd=tree.outside, env=tree.environment(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 60
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert started.exists(), "the runner never started"
    finally:
        proc.kill()
        proc.wait(timeout=30)
    run = next(tree.outputs.iterdir())
    assert not (run / "results.json").exists() and (run / "INCOMPLETE.json").exists()
    for extra in ((), ("--require-current",)):
        status = tree.status(str(run), *extra)
        assert status.returncode == 3 and "status: INCOMPLETE" in status.stdout, status.stdout


def test_a_qualification_pass_with_its_marker_back_or_its_result_gone_is_incomplete(qualified_run):
    tree, directory = qualified_run
    (directory / "INCOMPLETE.json").write_text("{}", encoding="utf-8")
    assert "status: INCOMPLETE" in tree.status(str(directory)).stdout
    (directory / "INCOMPLETE.json").unlink()
    assert tree.status(str(directory)).returncode == 0, "the control: the same run without the marker"
    (directory / "results.json").unlink()
    status = tree.status(str(directory))
    assert status.returncode == 3 and "status: INCOMPLETE" in status.stdout, status.stdout


@pytest.mark.parametrize("damage, needle", [
    (lambda path: path.unlink(), "verdict.json is missing"),
    (lambda path: path.write_bytes(path.read_bytes()[:40]), "changed after the run"),
    (lambda path: path.write_text(json.dumps(_verdict("FAIL")), encoding="utf-8"), "changed after the run"),
], ids=["missing", "truncated", "rewritten"])
def test_a_qualification_pass_whose_verdict_file_is_missing_truncated_or_rewritten_is_invalid(qualified_run, damage, needle):
    tree, directory = qualified_run
    damage(directory / "qualification" / "verdict.json")
    status = tree.status(str(directory))
    assert status.returncode == 3 and "status: INVALID" in status.stdout and needle in status.stdout, status.stdout


def _replant_verdict(directory: Path, verdict) -> None:
    """A determined edit: the verdict replaced, the manifest brought into line with it, and the record sealed again."""
    load_gate("act_verify_contract_replant")
    from helpers import runstore

    path = directory / "qualification" / "verdict.json"
    path.write_text(verdict if isinstance(verdict, str) else json.dumps(verdict), encoding="utf-8")

    def relist(results):
        for item in results["artifacts"]:
            if item["path"] == "qualification/verdict.json":
                item.update(size=path.stat().st_size, sha256=runstore.sha256_file(path))

    _rewrite_results(directory, relist, reseal=True)


@pytest.mark.parametrize("verdict, needle", [
    (_verdict("FAIL"), "that makes FAIL"),
    (_verdict("BLOCKED"), "that makes BLOCKED"),
    (_verdict("PASS", [*TWO_CHECKS, {"name": "T4:x", "status": "FAIL"}]), "checks not passed in its verdict: ['T4:x']"),
    (_verdict("PASS", []), "passed with no checks"),
    (_verdict("PASS", runs=0), "having made no run"),
    ({**_verdict("PASS"), "scenario": "fresh-windows"}, "is not the verdict of scenario m4b-scaling"),
    ("{ not json", "missing or unreadable"),
    ("[]", "is not the verdict of scenario m4b-scaling"),
], ids=["says-fail", "says-blocked", "a-failed-check", "no-checks", "no-runs", "another-scenario", "not-json", "not-an-object"])
def test_a_resealed_qualification_pass_that_its_own_verdict_contradicts_is_invalid(qualified_run, verdict, needle):
    """Sealing a record again does not make it agree with itself: the verdict is read, not only hashed."""
    tree, directory = qualified_run
    _replant_verdict(directory, verdict)
    status = tree.status(str(directory))
    assert status.returncode == 3 and "status: INVALID" in status.stdout and needle in status.stdout, status.stdout


def _drop_verdict_from_manifest(results: dict) -> None:
    results["artifacts"] = [item for item in results["artifacts"] if item["path"] != "qualification/verdict.json"]


@pytest.mark.parametrize("edit, needle", [
    (lambda r: [s for s in r["stages"] if s["name"].startswith("qualification:")][0].update(returncode=1), "with exit 1: that makes FAIL"),
    (lambda r: [s for s in r["stages"] if s["name"].startswith("qualification:")][0].update(ended="killed"), "that makes FAIL"),
    (lambda r: r["qualification"].update(ran={}), "a qualification PASS whose scenarios ended {}"),
    (lambda r: r["qualification"].update(ran={"m4b-scaling": "FAIL"}), "a qualification PASS whose scenarios ended"),
    (lambda r: r["qualification"].update(satisfied=[]), "does not name ['m4b-scaling'] as satisfied"),
    (lambda r: r["qualification"]["ran"].update({"fresh-windows": "PASS"}), "recorded 2 scenarios"),
    (lambda r: r.update(stages=[s for s in r["stages"] if not s["name"].startswith("qualification:")]), "0 recorded runs of its runner"),
    (_drop_verdict_from_manifest, "not part of the sealed evidence"),
    (lambda r: r.update(exit_code=1), "PASS with exit code"),
], ids=["runner-exit-1", "runner-killed", "ran-nothing", "ran-fail", "not-satisfied", "two-scenarios", "no-runner-stage",
        "verdict-unlisted", "exit-code-1"])
def test_a_resealed_qualification_pass_that_its_own_record_contradicts_is_invalid(qualified_run, edit, needle):
    tree, directory = qualified_run
    _rewrite_results(directory, edit, reseal=True)
    status = tree.status(str(directory))
    assert status.returncode == 3 and "status: INVALID" in status.stdout and needle in status.stdout, status.stdout


def test_a_qualification_fail_cannot_be_resealed_into_a_pass(tree):
    """The sealed result must follow from the verdict and the runner's exit, in both directions."""
    outcome = _qualification(tree, _verdict("FAIL", [{"name": "T5:x", "status": "FAIL"}]), 1)
    assert outcome.code == 1, outcome

    def claim_pass(results):
        results.update(status="PASS", exit_code=0)
        results["qualification"].update(ran={"m4b-scaling": "PASS"}, satisfied=["m4b-scaling"], pending=[])
        for check in results["checks"]:
            check["status"] = "PASS"

    _rewrite_results(outcome.directory, claim_pass, reseal=True)
    status = tree.status(str(outcome.directory))
    assert status.returncode == 3 and "status: INVALID" in status.stdout and "that makes FAIL" in status.stdout, status.stdout


def test_a_qualification_pass_does_not_stand_in_for_changed_source_policy_or_documents(qualified_run):
    tree, directory = qualified_run
    tree.write("md-instructions/Handoff.md", "# a docs-only edit\n")
    docs = tree.status(str(directory), "--require-current")
    assert docs.returncode == 3 and "current: docs-only" in docs.stdout and "both SHAs" in docs.stdout, docs.stdout
    policy = tree.policy()
    policy["process"]["drain_seconds"] = 4
    tree.write_policy(policy)
    tree.commit("policy moved")
    moved = tree.status(str(directory), "--require-current")
    assert moved.returncode == 3 and "current: stale" in moved.stdout and "policy_digest" in moved.stdout, moved.stdout
    tree.write("scripts/app.py", "x = 1" + chr(10))
    tree.commit("source moved")
    stale = tree.status(str(directory), "--require-current")
    assert stale.returncode == 3 and "current: stale" in stale.stdout and "source_digest" in stale.stdout, stale.stdout
    assert tree.status(str(directory)).returncode == 0, "still a true record of the source it ran on"


# --------------------------------------------------------------------------- #
# What the gate itself seals for a scenario (v0.7.2 Phase 9, review finding P9-03)
# --------------------------------------------------------------------------- #
# The tests above damage a record after it was sealed and ask the reader. The Phase 9 review asked the other question:
# what does the gate seal when the scenario's own runner hands it a verdict that contradicts itself? It sealed PASS with
# exit 0 for a PASS beside a failed check, for a PASS with nothing run, and for another scenario's PASS, and only the
# reader refused the record afterwards. Each test below is one real run: the real gate, its real supervisor, a real child
# that exits by itself, the real finalizer, and then the real reader. It states all four answers: what the gate judged,
# what it exited with, what it sealed, and what the reader makes of the sealed record. They must agree, and none may be
# PASS unless the first test's control is.
def _answers(tree, outcome) -> dict:
    """The gate's judgement, its exit, the sealed result and the reader's answer, for one run."""
    results = outcome.results
    scenario = [c for c in results["checks"] if c["name"] == "scenario:m4b-scaling"]
    evidence = [c for c in results["checks"] if c["name"] == "scenario-evidence:m4b-scaling"]
    read = tree.status(str(outcome.directory))
    said = [line.split("status:", 1)[1].split("(")[0].strip() for line in read.stdout.splitlines() if line.startswith("status:")]
    return {"scenario": scenario[0]["status"] if scenario else None, "scenario_detail": scenario[0]["detail"] if scenario else "",
            "evidence": evidence[0]["status"] if evidence else None, "evidence_detail": evidence[0]["detail"] if evidence else "",
            "exit": outcome.code, "sealed": (results["status"], results["exit_code"]),
            "ran": results["qualification"]["ran"], "satisfied": results["qualification"]["satisfied"],
            "reader": (said[0] if said else None, read.returncode), "reader_problems": "problem:" in read.stdout,
            "reader_out": read.stdout}


def _assert_agreed_and_not_a_pass(answers: dict, status: str = "FAIL") -> None:
    code = {"FAIL": 1, "BLOCKED": 2}[status]
    assert answers["exit"] == code and answers["sealed"] == (status, code), answers
    assert answers["satisfied"] == [], answers
    assert answers["reader"] == (status, code) and not answers["reader_problems"], answers["reader_out"]


def test_the_control_a_whole_scenario_pass_is_sealed_pass_and_read_as_pass(tree):
    """The no-change control of every case below: the same runner, the same policy, an honest verdict."""
    answers = _answers(tree, _qualification(tree, _verdict("PASS"), 0))
    assert answers["scenario"] == "PASS" and answers["evidence"] == "PASS", answers
    assert answers["exit"] == 0 and answers["sealed"] == ("PASS", 0), answers
    assert answers["ran"] == {"m4b-scaling": "PASS"} and answers["satisfied"] == ["m4b-scaling"], answers
    assert answers["reader"] == ("PASS", 0) and not answers["reader_problems"], answers["reader_out"]


@pytest.mark.parametrize("verdict, needle", [
    (_verdict("PASS", [*TWO_CHECKS, {"name": "T5:x", "status": "FAIL", "detail": "9 bytes"}]), "1 of its checks did not pass: ['T5:x']"),
    (_verdict("PASS", [], runs=0), "it holds no checks"),
    (_verdict("PASS", []), "it holds no checks"),
    (_verdict("PASS", runs=0), "it made no run (0)"),
    ({**_verdict("PASS"), "runs": True}, "it made no run (True)"),
    ({**_verdict("PASS"), "checks": "every one passed"}, "it holds no checks"),
    ({**_verdict("PASS"), "checks": [*TWO_CHECKS, "T9 passed"]}, "1 of its checks did not pass"),
    ({**_verdict("PASS"), "status": "SMOKE"}, "the verdict's status is 'SMOKE'"),
], ids=["a-failed-check", "nothing-executed", "no-checks", "no-runs", "runs-is-not-a-number", "checks-is-not-a-list",
        "a-check-that-is-not-a-record", "an-unknown-status"])
def test_a_pass_verdict_that_does_not_bear_itself_out_is_sealed_fail_by_the_gate_itself(tree, verdict, needle):
    """The runner exits 0 in every case: only the verdict's own content stands between it and a sealed PASS."""
    answers = _answers(tree, _qualification(tree, verdict, 0))
    assert answers["scenario"] == "FAIL" and needle in answers["scenario_detail"], answers
    assert answers["evidence"] is None, "a verdict that is not a PASS has no PASS to hold to its evidence"
    assert answers["ran"] == {"m4b-scaling": "FAIL"}, answers
    _assert_agreed_and_not_a_pass(answers)


@pytest.mark.parametrize("verdict, needle", [
    ({**_verdict("PASS"), "scenario": "fresh-windows"}, "the verdict is about scenario 'fresh-windows', not m4b-scaling"),
    ({key: value for key, value in _verdict("PASS").items() if key != "scenario"}, "the verdict is about scenario None"),
    ("[]", "the verdict is list, not an object"),
    ('"PASS"', "the verdict is str, not an object"),
    ("{ not json", "without a readable verdict"),
    (None, "without a readable verdict"),
], ids=["another-scenario", "no-scenario-named", "a-list", "a-string", "not-json", "no-verdict-at-all"])
def test_a_verdict_that_is_not_this_scenarios_is_no_verdict_and_the_run_fails(tree, verdict, needle):
    """Nothing of the scenario is recorded, because there is nothing of it: the run is FAIL and reads FAIL."""
    answers = _answers(tree, _qualification(tree, verdict, 0))
    assert answers["scenario"] == "FAIL" and needle in answers["scenario_detail"], answers
    assert answers["ran"] == {} and answers["evidence"] is None, answers
    _assert_agreed_and_not_a_pass(answers)


@pytest.mark.parametrize("status, code, sealed", [
    ("PASS", 1, "FAIL"), ("PASS", 2, "FAIL"), ("PASS", 3, "FAIL"),
    ("FAIL", 0, "FAIL"), ("FAIL", 1, "FAIL"), ("FAIL", 2, "FAIL"),
    ("BLOCKED", 0, "BLOCKED"), ("BLOCKED", 2, "BLOCKED"), ("BLOCKED", 1, "BLOCKED"),
], ids=lambda value: str(value))
def test_no_exit_code_can_raise_a_verdict_and_only_exit_zero_lets_a_pass_stand(tree, status, code, sealed):
    """The verdict and the runner's exit are held against each other in one direction only: downwards."""
    answers = _answers(tree, _qualification(tree, _verdict(status), code))
    assert answers["scenario"] == sealed and answers["ran"] == {"m4b-scaling": sealed}, answers
    _assert_agreed_and_not_a_pass(answers, sealed)


@WINDOWS_ONLY
def test_a_runner_stopped_by_the_gate_after_writing_pass_is_not_a_pass(tree):
    """An interrupted child: the PASS verdict is on disk, but the runner never exited by itself. The gate stops it at its
    budget, and what it stopped did not pass."""
    outcome = _qualification(tree, _verdict("PASS"), 0, stage={"timeout_seconds": 8, "stall_seconds": 60},
                             before=f'(out / "verdict.json").write_text(json.dumps({_verdict("PASS")!r}))\ntime.sleep(300)')
    answers = _answers(tree, outcome)
    stage = [s for s in outcome.results["stages"] if s["name"] == "qualification:m4b-scaling"][0]
    assert stage["ended"] != "exited", stage
    assert answers["scenario"] == "FAIL" and "its runner" in answers["scenario_detail"], answers
    _assert_agreed_and_not_a_pass(answers)


@pytest.mark.parametrize("before, requires, needle", [
    ('(out / "identity.json").unlink()', _UNSET, "no readable identity.json"),
    ('(out / "identity.json").write_text("{ not json")', _UNSET, "no readable identity.json"),
    ('(out / "identity.json").write_text(json.dumps({"scenario": "m4b-scaling", "head": "0" * 40}))', _UNSET,
     "the scenario measured HEAD '0000000000000000000000000000000000000000'"),
    ('(out / "identity.json").write_text(json.dumps({"scenario": "edge-low-memory", "head": head}))', _UNSET,
     "identity.json is of scenario 'edge-low-memory'"),
    ('(out / "runs.json").unlink()', _UNSET, "no readable runs.json"),
    ('(out / "runs.json").write_text(json.dumps([{"label": "only-one"}]))', _UNSET, "runs.json records 1 run(s), the verdict counts 3"),
    ("", {**SMALL_PASS, "checks": 3}, "2 checks, the scenario has at least 3"),
    ("", {**SMALL_PASS, "runs": 4}, "3 runs, the scenario has at least 4"),
    ("", {**SMALL_PASS, "names": ["T1", "T6"]}, "required checks are missing: ['T6']"),
    ("", {**SMALL_PASS, "families": {"T8:": 1, "T5:": 1}}, "0 checks named 'T5:'*, the scenario has at least 1"),
    ("", {**SMALL_PASS, "families": {"T8:": 2}}, "1 checks named 'T8:'*, the scenario has at least 2"),
    ("", None, "the policy states no pass_requires for m4b-scaling"),
], ids=["no-identity", "unreadable-identity", "another-head", "another-scenarios-identity", "no-runs-file", "fewer-runs-recorded",
        "fewer-checks-than-the-scenario", "fewer-runs-than-the-scenario", "a-required-check-missing", "a-required-family-missing",
        "a-family-short-of-its-checks", "no-requirement-stated"])
def test_a_pass_verdict_without_the_whole_scenario_or_its_evidence_is_not_accepted(tree, before, requires, needle):
    """The verdict is honest and consistent, so the scenario's own result stays PASS; what is missing beside it fails the
    run through a check of its own, the scenario is not called satisfied, and the reader agrees with the sealed FAIL."""
    answers = _answers(tree, _qualification(tree, _verdict("PASS"), 0, before=before, requires=requires))
    assert answers["scenario"] == "PASS" and answers["ran"] == {"m4b-scaling": "PASS"}, answers
    assert answers["evidence"] == "FAIL" and needle in answers["evidence_detail"], answers
    assert answers["satisfied"] == [], "a scenario is satisfied only by a run that itself passed"
    _assert_agreed_and_not_a_pass(answers)


@WINDOWS_ONLY
def test_a_scenario_that_passes_but_leaves_a_process_behind_fails_the_run_and_satisfies_nothing(tree):
    pid_file = tree.root / "left-behind.pid"
    before = (f"child = subprocess.Popen([sys.executable, '-c', {SLEEPER!r}])\n"
              f"Path({str(pid_file)!r}).write_text(str(child.pid), encoding='ascii')")
    outcome = _qualification(tree, _verdict("PASS"), 0, before=before)
    answers = _answers(tree, outcome)
    assert answers["scenario"] == "PASS" and outcome.check("cleanup")["status"] == "FAIL", answers
    assert outcome.results["cleanup"]["owned_children_remaining"] >= 1 and answers["satisfied"] == [], answers
    _assert_agreed_and_not_a_pass(answers)
    assert _wait_gone(int(pid_file.read_text(encoding="ascii"))), "the owned process was not stopped"


def test_a_scenario_that_passes_while_its_source_changes_fails_the_run_and_satisfies_nothing(tree):
    """The tested inputs were not frozen: the PASS describes no one source."""
    target = tree.root / "scripts" / "launcher.py"
    outcome = _qualification(tree, _verdict("PASS"), 0, before=f"Path({str(target)!r}).write_text('# changed during the run\\n')")
    answers = _answers(tree, outcome)
    assert answers["scenario"] == "PASS" and outcome.check("tree")["status"] == "FAIL", answers
    assert answers["satisfied"] == [], answers
    _assert_agreed_and_not_a_pass(answers)


def test_a_record_the_gate_sealed_fail_for_a_contradictory_verdict_cannot_be_resealed_into_a_pass(tree):
    """The tampered sealed record: the gate's own FAIL, edited to say PASS and sealed again, is INVALID to the reader."""
    outcome = _qualification(tree, _verdict("PASS", [*TWO_CHECKS, {"name": "T5:x", "status": "FAIL"}]), 0)
    assert outcome.code == 1, outcome

    def claim_pass(results):
        results.update(status="PASS", exit_code=0)
        results["qualification"].update(ran={"m4b-scaling": "PASS"}, satisfied=["m4b-scaling"], pending=[])
        for check in results["checks"]:
            check["status"] = "PASS"

    _rewrite_results(outcome.directory, claim_pass, reseal=True)
    status = tree.status(str(outcome.directory))
    assert status.returncode == 3 and "status: INVALID" in status.stdout and "that makes FAIL" in status.stdout, status.stdout
    assert "checks not passed in its verdict: ['T5:x']" in status.stdout, status.stdout


def _gate_module():
    return load_gate("act_verify_contract_scenario")


@pytest.mark.parametrize("ended, code, verdict, expected", [
    ("exited", 0, _verdict("PASS"), "PASS"),
    ("exited", 0, _verdict("PASS", [{"name": "only", "status": "PASS"}], runs=1), "PASS"),
    ("exited", 1, _verdict("PASS"), "FAIL"),
    ("exited", None, _verdict("PASS"), "FAIL"),
    ("timeout", 0, _verdict("PASS"), "FAIL"),
    ("killed", 0, _verdict("PASS"), "FAIL"),
    ("exited", 0, _verdict("PASS", [{"name": "only", "status": "pass"}]), "FAIL"),
    ("exited", 0, _verdict("PASS", [{"name": "only"}]), "FAIL"),
    ("exited", 0, _verdict("PASS", [{"name": "only", "status": "NOT RUN"}]), "FAIL"),
    ("exited", 0, _verdict("PASS", runs=-1), "FAIL"),
    ("exited", 0, {**_verdict("PASS"), "runs": 2.0}, "FAIL"),
    ("exited", 0, {**_verdict("PASS"), "runs": "3"}, "FAIL"),
    ("exited", 0, _verdict("FAIL"), "FAIL"),
    ("exited", 0, _verdict("BLOCKED"), "BLOCKED"),
    ("exited", 0, {**_verdict("PASS"), "status": None}, "FAIL"),
    ("exited", 0, {**_verdict("PASS"), "scenario": "m4b-scaling "}, None),
    ("exited", 0, None, None),
    ("exited", 0, 7, None),
])
def test_the_gates_rule_and_the_readers_rule_for_a_scenario_verdict_agree_on_every_planted_case(tmp_path, ended, code, verdict, expected):
    """Two implementations of one rule, on purpose (the reader takes nothing of the gate's on trust): ``verify.judge_scenario``
    decides what is sealed, ``runstore._scenario_problems`` re-derives it from the sealed evidence. Whatever the gate would seal
    for these inputs, the reader must find no fault with exactly that and must fault every other status."""
    verify = _gate_module()
    from helpers import runstore

    status, _why = verify.judge_scenario("m4b-scaling", verdict, ended, code)
    assert status == expected
    if status is None:
        return  # no verdict of this scenario: the gate records no scenario result, and the reader has nothing to compare
    directory = tmp_path / "run"
    (directory / "qualification").mkdir(parents=True)
    (directory / "qualification" / "verdict.json").write_text(json.dumps(verdict), encoding="utf-8")
    for sealed in ("PASS", "FAIL", "BLOCKED"):
        results = {"qualification": {"ran": {"m4b-scaling": sealed}},
                   "checks": [{"name": "scenario:m4b-scaling", "status": sealed, "required": True}],
                   "stages": [{"name": "qualification:m4b-scaling", "ended": ended, "returncode": code}],
                   "artifacts": [{"path": "qualification/verdict.json"}]}
        problems = runstore._scenario_problems(directory, results)
        assert (problems == []) == (sealed == status), (sealed, status, problems)


def test_the_real_policy_states_the_whole_of_every_scenarios_pass():
    """Every frozen scenario says what its PASS contains, and the named checks and the families account for every check of it:
    a scenario cannot lose a budget's check and still be accepted. The numbers are those of each scenario's own PASS on the
    v0.7.2 Phase 8 candidate (79, 61, 76 and 43 checks; 207, 6, 6 and 11 runs)."""
    policy = json.loads((GATE_DIR / "verification.json").read_text(encoding="utf-8"))
    whole = {"m4b-scaling": (79, 207), "edge-low-memory": (61, 6), "optional-engines": (76, 6), "fresh-windows": (43, 11)}
    assert set(policy["scenarios"]) == set(whole)
    for name, (checks, runs) in whole.items():
        requires = policy["scenarios"][name]["pass_requires"]
        assert (requires["checks"], requires["runs"]) == (checks, runs), name
        assert len(requires["names"]) + sum(requires["families"].values()) == checks, f"{name}: a check no rule requires"
        prefixes = list(requires["families"])
        assert not [(a, b) for a in prefixes for b in prefixes if a != b and b.startswith(a)], f"{name}: one family inside another"
        assert not [(n, p) for n in requires["names"] for p in prefixes if n.startswith(p)], f"{name}: a named check counted in a family"
    scaling = policy["scenarios"]["m4b-scaling"]["pass_requires"]
    assert {"T1", "T1b", "T6", "containment"} == set(scaling["names"])
    assert {"T2:below:", "T2:above:", "T3:", "T4:", "T5:", "T7:", "T8:", "fault:", "pause:"} == set(scaling["families"])


def test_a_whole_scenario_verdict_meets_the_real_policy_and_one_missing_budget_check_does_not(tmp_path):
    """The real requirement of m4b-scaling, on a verdict shaped like its real PASS; then the same verdict without its T5 checks,
    with one T4 check fewer, and without T6: each is refused by name."""
    verify = _gate_module()
    requires = json.loads((GATE_DIR / "verification.json").read_text(encoding="utf-8"))["scenarios"]["m4b-scaling"]["pass_requires"]
    names = [*requires["names"], *(f"{prefix}{n}" for prefix, count in requires["families"].items() for n in range(count))]
    folder = tmp_path / "qualification"
    folder.mkdir()
    (folder / "identity.json").write_text(json.dumps({"head": "abc"}), encoding="utf-8")
    (folder / "runs.json").write_text(json.dumps([{}] * 207), encoding="utf-8")

    def problems(kept):
        verdict = {"scenario": "m4b-scaling", "status": "PASS", "runs": 207, "checks": [{"name": n, "status": "PASS"} for n in kept]}
        return verify.scenario_evidence_problems("m4b-scaling", verdict, folder, "abc", requires)

    assert problems(names) == []
    assert any("'T5:'" in text for text in problems([n for n in names if not n.startswith("T5:")]))
    assert any("8 checks named 'T4:'" in text for text in problems([n for n in names if n != "T4:0"]))
    assert any("required checks are missing: ['T6']" in text for text in problems([n for n in names if n != "T6"]))
    # A check of another name does not stand in for a missing one, even when the count is made up.
    padded = [n for n in names if not n.startswith("T5:")] + [f"run:extra-{n}" for n in range(9)]
    assert len(padded) == 79 and any("'T5:'" in text for text in problems(padded))


# --------------------------------------------------------------------------- #
# The m4b-scaling harness: what T4 and T5 measure (v0.7.2 Phase 8 remediation)
# --------------------------------------------------------------------------- #
@functools.lru_cache(maxsize=None)
def _scaling_module(name: str):
    """bench_run.py or qualify.py, loaded the way the gate runs them (their own folder first on the path)."""
    if sys.platform != "win32":
        pytest.skip("the benchmark harness accounts through Windows Job Objects")
    import importlib.util  # noqa: PLC0415

    saved_path, saved_modules = list(sys.path), {key: sys.modules.get(key) for key in ("winjob", "common", "recipe", "staging")}
    try:
        spec = importlib.util.spec_from_file_location(f"act_scaling_{name}_contract", GATE_DIR / "scaling" / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path[:] = saved_path
        for key, value in saved_modules.items():
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value


MIB = 1 << 20


def _clean_staging(**over) -> dict:
    """What ``staging.StagingCensus.record()`` holds for a run that was read completely: the 1,000-chapter book's figures."""
    record = {"base_chars": 214, "peak_media_bytes": 94_311, "peak_diagnostics_bytes": 122_852, "peak_total_bytes": 217_163,
              "readings": {"start": 1, "remove": 3000, "rename": 1000, "end": 1}, "at_start_files": 0, "left_files": 0,
              "left_bytes": 0,
              "observer": {"finished": True, "audit_hook": True, "diagnostics_sinks": 2000, "unobserved": [], "links": [],
                           "without_creation": [], "written_by_the_application": [], "errors": [],
                           "watch": {"armed": True, "drained": True, "lost": 0, "error": None, "events": 9004,
                                     "created": 4000, "removed": 3000, "renamed": 1000}}}
    observer = over.pop("observer", None)
    watch = over.pop("watch", None)
    record.update(over)
    if observer is not None:
        record["observer"] = {**record["observer"], **observer}
    if watch is not None:
        record["observer"] = {**record["observer"], "watch": {**record["observer"]["watch"], **watch}}
    return record


def _seeking(label: str, *, staging=None, **over) -> dict:
    """A seeking-route run's summary. The figures are those of the 1,000-chapter book with the corrected harness."""
    run = {"label": label, "files": 1000, "peak_job_commit": 82_100_000, "write_bytes": 339_406_132,
           "app_write_bytes": 2_132_979, "peak_staged_bytes": 215_728, "decoders": [], "pipe": {},
           "staging": _clean_staging(**(staging or {}))}
    run.update(over)
    return run


def _one_decode(label: str = "tput-scale1000-180", *, decoder=None, staging=None, **over) -> dict:
    stream = 530_963_296
    run = _seeking(label, staging=staging, peak_job_commit=82_100_000 + 29_097_984 + 1_740_800 + 600_000,
                   write_bytes=219_834_875 + 2 * stream, app_write_bytes=stream + 1_999_074, peak_staged_bytes=215_796,
                   pipe={"from_decoder_bytes": stream, "to_encoders_bytes": stream})
    run["decoders"] = [{"peak_buffered": 532_728, "peak_commit": 29_097_984, "write_bytes": stream, "diagnostics_bytes": 0,
                        "companions": [{"pid": 4, "image": "conhost.exe", "peak_commit": 1_740_800}], **(decoder or {})}]
    run.update(over)
    return run


def _judged(auto: dict, legacy=None) -> dict:
    qualify = _scaling_module("qualify")
    legacy = legacy or [_seeking("tput-scale1000-179"), _seeking("tput-scale1000-182"), _seeking("tput-scale1000-183")]
    checks = qualify.resource_checks("scale1000", legacy, [auto])
    assert [c["name"] for c in checks] == [f"T4:scale1000:{auto['label']}", f"T5:scale1000:{auto['label']}"]
    return {c["name"].split(":")[0]: c for c in checks}


def test_the_resource_checks_pass_a_run_that_keeps_every_budget():
    """The no-change control of every planted figure below."""
    judged = _judged(_one_decode())
    assert judged["T4"]["ok"] and judged["T5"]["ok"], judged
    assert judged["T4"]["facts"]["failed_parts"] == [] and judged["T5"]["facts"]["problems"] == []


@pytest.mark.parametrize("planted, part", [
    (dict(decoder={"peak_buffered": MIB + 1}), "audio held"),
    (dict(decoder={"peak_buffered": 0}), "audio held"),
    (dict(decoder={"peak_buffered": 16 * MIB}), "audio held"),
    (dict(pipe={"from_decoder_bytes": 0, "to_encoders_bytes": 530_963_296}), "stream counted"),
    (dict(write_bytes=219_834_875 + 2 * 530_963_296 + 530_963_296), "writes"),
    (dict(decoder={"write_bytes": 2 * 530_963_296}), "decoder wrote only its stream"),
    (dict(decoder={"write_bytes": 530_963_296 + 1}), "decoder wrote only its stream"),
    (dict(decoder={"write_bytes": None}), "decoder wrote only its stream"),
    (dict(app_write_bytes=530_963_296 + 1_999_074 + 530_963_296), "application wrote only its feed"),
    (dict(app_write_bytes=530_963_296 + 2_132_979 * 2), "application wrote only its feed"),
    (dict(app_write_bytes=None), "application wrote only its feed"),
], ids=["a-buffer-over-1-MiB", "no-buffer-measured", "a-16-MiB-buffer", "the-stream-not-counted", "a-whole-book-PCM-spool-in-the-total",
        "the-decoder-spools-its-stream", "the-decoder-writes-one-byte-elsewhere", "the-decoder's-writes-not-measured",
        "the-application-spools-the-stream", "the-application-writes-twice-its-own", "the-application's-writes-not-measured"])
def test_t4_fails_on_a_buffer_over_the_limit_or_any_audio_written_to_disk(planted, part):
    judged = _judged(_one_decode(**planted))
    assert not judged["T4"]["ok"] and part in judged["T4"]["facts"]["failed_parts"], judged["T4"]


def test_a_decoder_diagnostics_file_is_accounted_for_and_nothing_else_is():
    """Every byte the decoder wrote is its stream or its own diagnostics file, whose size is measured."""
    told = dict(write_bytes=530_963_296 + 120, diagnostics_bytes=120)
    assert _judged(_one_decode(decoder=told))["T4"]["ok"]
    assert not _judged(_one_decode(decoder={**told, "diagnostics_bytes": 119}))["T4"]["ok"]


def test_t4_holds_the_job_peak_to_the_seeking_peak_one_more_ffmpeg_and_one_mebibyte():
    """Seeking peak + the decoder + the console host Windows starts for it + 1 MiB: to the byte, and nothing more."""
    envelope = 82_100_000 + 29_097_984 + 1_740_800 + MIB
    assert _judged(_one_decode(peak_job_commit=envelope))["T4"]["ok"]
    over = _judged(_one_decode(peak_job_commit=envelope + 1))["T4"]
    assert not over["ok"] and over["facts"]["failed_parts"] == ["job peak"] and over["facts"]["envelope"] == envelope
    # A route that held an eighth of this book's audio (66 MB) outside its counted buffer, or one chapter of a long book:
    assert not _judged(_one_decode(peak_job_commit=envelope + 66_000_000))["T4"]["ok"]
    # The seeking route's peak is the largest of its runs, as it always was.
    lower = [_seeking("a", peak_job_commit=81_000_000), _seeking("b", peak_job_commit=81_500_000), _seeking("c")]
    assert _judged(_one_decode(peak_job_commit=envelope), lower)["T4"]["ok"]
    assert not _judged(_one_decode(peak_job_commit=envelope), lower[:2])["T4"]["ok"]


@pytest.mark.parametrize("companions, allowed", [
    ([], 0),
    ([{"pid": 4, "image": "conhost.exe", "peak_commit": None}], 0),
    ([{"pid": 4, "image": "conhost.exe", "peak_commit": 1_740_800}, {"pid": 5, "image": "conhost.exe", "peak_commit": 1_740_800}], 0),
], ids=["no-console-host-found", "its-peak-not-read", "two-console-hosts"])
def test_only_one_measured_console_host_is_allowed_for(companions, allowed):
    """What was not found or not measured is not allowed for: the envelope falls back to the decoder alone."""
    base = 82_100_000 + 29_097_984 + MIB
    judged = _judged(_one_decode(decoder={"companions": companions}, peak_job_commit=base + 1))["T4"]
    assert judged["facts"]["console_host_peak"] == allowed and "job peak" in judged["facts"]["failed_parts"], judged


def test_a_decoder_that_starts_anything_but_its_console_host_fails_t4():
    extra = [{"pid": 4, "image": "conhost.exe", "peak_commit": 1_740_800}, {"pid": 9, "image": "ffmpeg.exe", "peak_commit": 30_000_000}]
    judged = _judged(_one_decode(decoder={"companions": extra}))["T4"]
    assert not judged["ok"] and "job peak" in judged["facts"]["failed_parts"] and "ffmpeg.exe" in judged["detail"], judged


def test_the_job_peak_that_failed_in_phase_8_was_inside_the_complete_envelope():
    """Session 95eb, T4:scale1000:tput-scale1000-181, as recorded: 266,633,216 bytes against 236,277,760 (seeking, with
    the harness's own held handles in it) + 29,097,984 (decoder) + 1 MiB. The envelope left out the decoder's console
    host. With one counted, the same reading is inside; this is the arithmetic, not a verdict on that run."""
    recorded = _one_decode(peak_job_commit=266_633_216, decoder={"peak_commit": 29_097_984, "companions": []})
    legacy = [_seeking("a", peak_job_commit=235_909_120), _seeking("b", peak_job_commit=236_277_760),
              _seeking("c", peak_job_commit=235_761_664)]
    as_frozen = _judged(recorded, legacy)["T4"]
    assert not as_frozen["ok"] and as_frozen["facts"]["envelope"] == 236_277_760 + 29_097_984 + MIB
    assert recorded["peak_job_commit"] - as_frozen["facts"]["envelope"] == 208_896
    with_host = _one_decode(peak_job_commit=266_633_216, decoder={"peak_commit": 29_097_984})
    assert _judged(with_host, legacy)["T4"]["ok"]


def test_t5_holds_every_staged_byte_to_the_seeking_routes_largest_peak_with_no_allowance():
    """The approved budget, to the letter (Phase 7A record, section 8: "peak staged bytes no higher than production's"):
    everything the application has staged, media and diagnostics alike, against the largest exact peak of the session's
    seeking runs. Phase 8 had judged the media exactly and the diagnostics apart at 1.05 x, which let a larger total
    pass; the Phase 9 review showed one passing nine bytes over (P9-04)."""
    assert _judged(_one_decode())["T5"]["ok"], "equal is not higher"
    assert _judged(_one_decode(staging={"peak_total_bytes": 217_162, "peak_diagnostics_bytes": 122_851}))["T5"]["ok"]
    one_more = _judged(_one_decode(staging={"peak_total_bytes": 217_164, "peak_diagnostics_bytes": 122_853}))["T5"]
    assert not one_more["ok"], "one byte more, in a diagnostics file, is more"
    assert "217164 bytes staged at the peak is more than the seeking route's 217163" in one_more["detail"]
    assert (one_more["facts"]["total"], one_more["facts"]["seeking_total"]) == (217_164, 217_163)
    nine_more = _judged(_one_decode(staging={"peak_total_bytes": 217_172, "peak_diagnostics_bytes": 122_861}))["T5"]
    assert not nine_more["ok"], "the reviewed harness passed exactly this"
    five_percent = _judged(_one_decode(staging={"peak_total_bytes": 217_163 + 6_142, "peak_diagnostics_bytes": 128_994}))["T5"]
    assert not five_percent["ok"], "and this was the allowance it gave"


def test_the_seeking_routes_figure_is_the_largest_exact_peak_of_its_own_runs_and_the_boundary_is_that_byte():
    legacy = [_seeking("a", staging={"peak_total_bytes": 217_160, "peak_diagnostics_bytes": 122_849}),
              _seeking("b"),
              _seeking("c", staging={"peak_total_bytes": 217_161, "peak_diagnostics_bytes": 122_850})]
    at_the_boundary = _judged(_one_decode(), legacy)["T5"]
    assert at_the_boundary["ok"] and at_the_boundary["facts"]["seeking_totals"] == [217_160, 217_163, 217_161]
    assert not _judged(_one_decode(staging={"peak_total_bytes": 217_164, "peak_diagnostics_bytes": 122_853}), legacy)["T5"]["ok"]
    # Against the two lower seeking runs alone the same one-decode run is two bytes over: a FAIL, not something to round away.
    over = _judged(_one_decode(), [legacy[0], legacy[2]])["T5"]
    assert not over["ok"] and "217163 bytes staged at the peak is more than the seeking route's 217161" in over["detail"]


def test_more_staged_media_fails_even_where_the_total_is_no_higher():
    """The media's sizes are fixed by the outputs, so it is also held exactly on its own. That can only add a failure."""
    swapped = _judged(_one_decode(staging={"peak_media_bytes": 94_316, "peak_diagnostics_bytes": 122_847}))["T5"]
    assert not swapped["ok"] and "staged media 94316 bytes is more than the seeking route's 94311" in swapped["detail"]
    # One more staged chapter kept, or a decoded chapter spooled beside it:
    for extra in (32_505, 529_200):
        more = _judged(_one_decode(staging={"peak_media_bytes": 94_311 + extra, "peak_total_bytes": 217_163 + extra}))["T5"]
        assert not more["ok"] and "bytes staged at the peak is more than" in more["detail"], more["detail"]


def test_the_sampled_figures_that_failed_in_phase_8_do_not_decide_t5():
    """Session 2dbf: sampled 215,796 against the seeking route's sampled 215,728, 68 bytes. Both were samples of one and
    the same true peak. With everything staged read exactly and equal, that pair of samples passes; the samples are kept
    only as a witness that must not exceed the exact reading."""
    auto = _one_decode(peak_staged_bytes=215_796)
    legacy = [_seeking("a", peak_staged_bytes=215_512), _seeking("b", peak_staged_bytes=215_728), _seeking("c", peak_staged_bytes=215_586)]
    assert _judged(auto, legacy)["T5"]["ok"]


@pytest.mark.parametrize("planted, needle", [
    (dict(staging={"left_files": 1, "left_bytes": 31_918}), "1 temporaries left behind (31918 bytes)"),
    (dict(staging={"readings": {"start": 1, "remove": 3001, "rename": 999, "end": 1}}), "999 readings before a rename for 1000 outputs"),
    (dict(staging={"readings": {"start": 1, "rename": 1000, "end": 1}}), "no reading before a removal"),
    (dict(staging={"readings": None}), "None readings before a rename for 1000 outputs"),
    (dict(peak_staged_bytes=217_164), "the 0.5 s sampler saw 217164 bytes staged, more than the exact reading's peak 217163"),
    (dict(staging={"peak_media_bytes": None}), "staged media None bytes"),
    (dict(staging={"peak_total_bytes": None}), "None bytes staged at the peak"),
    (dict(staging={"peak_total_bytes": True}), "True bytes staged at the peak"),
    (dict(staging={"at_start_files": 2}), "2 temporaries were there before the run"),
    (dict(staging={"base_chars": 215}), "paths of different lengths [214, 215]"),
    (dict(staging={"observer": {"finished": False}}), "the reading was not finished"),
    (dict(staging={"observer": {"audit_hook": False}}), "file operations were not being heard"),
    (dict(staging={"watch": {"armed": False}}), "Windows' report of the output base was not complete"),
    (dict(staging={"watch": {"drained": False}}), "Windows' report of the output base was not complete"),
    (dict(staging={"watch": {"lost": 1}}), "Windows' report of the output base was not complete"),
    (dict(staging={"watch": {"error": "ReadDirectoryChangesW failed (error 5)"}}), "Windows' report of the output base was not complete"),
    (dict(staging={"observer": {"unobserved": [".act-tmp-x.mp3 (61440 bytes) was gone at a reading"]}}), "the total fell without a reading"),
    (dict(staging={"observer": {"links": [".act-tmp-link.mp3"]}}), "links among the temporaries"),
    (dict(staging={"observer": {"without_creation": [".act-tmp-old.mp3"]}}), "temporaries nobody saw created under this base in this run"),
    (dict(staging={"observer": {"written_by_the_application": [".act-tmp-audio.log (wb)"]}}),
     "temporaries the application wrote through a handle of its own"),
    (dict(staging={"observer": {"errors": ["os.truncate: IndexError"]}}), "errors while reading"),
    (dict(staging={"observer": {"diagnostics_sinks": 0}}), "bytes counted as diagnostics with no child's output sink recorded"),
], ids=["a-temporary-left-behind", "a-publication-not-read", "no-removal-read", "no-readings-recorded", "the-sampler-saw-more",
        "media-not-measured", "total-not-measured", "total-not-a-number", "temporaries-before-the-run", "paths-of-another-length",
        "reading-not-finished", "operations-not-heard", "watch-never-live", "watch-not-drained", "watch-lost-a-report",
        "watch-failed", "a-decrease-nobody-read", "a-link", "a-temporary-nobody-saw-created", "written-by-the-application",
        "an-error-while-reading", "diagnostics-with-no-sink"])
def test_t5_fails_when_the_reading_is_not_complete_or_shows_more(planted, needle):
    """Every figure is equal to the seeking route's in each case: only what the reading says about itself differs."""
    judged = _judged(_one_decode(**planted))["T5"]
    assert not judged["ok"] and needle in judged["detail"], judged["detail"]


def test_an_incomplete_reading_of_a_seeking_run_fails_t5_as_well():
    """The seeking route's figure is the budget. If it was not read completely there is no budget to hold anything to."""
    legacy = [_seeking("a"), _seeking("b", staging={"observer": {"unobserved": ["a temporary went unread"]}}), _seeking("c")]
    judged = _judged(_one_decode(), legacy)["T5"]
    assert not judged["ok"] and "b: the total fell without a reading" in judged["detail"], judged["detail"]


@pytest.mark.parametrize("missing", ["unobserved", "links", "without_creation", "written_by_the_application", "errors"])
def test_a_record_that_does_not_say_is_never_taken_as_clean(missing):
    auto = _one_decode()
    del auto["staging"]["observer"][missing]
    judged = _judged(auto)["T5"]
    assert not judged["ok"] and "the record does not say whether there were" in judged["detail"], judged["detail"]


def test_t5_fails_without_exact_figures_without_the_observers_account_and_when_the_seeking_runs_disagree():
    missing = _one_decode()
    missing["staging"] = {}
    assert "no exact staging figures" in _judged(missing)["T5"]["detail"]
    as_phase_8_recorded = _one_decode()  # figures, and no account of how completely they were read
    del as_phase_8_recorded["staging"]["observer"]
    assert "no record that every decrease of the staged total was observed" in _judged(as_phase_8_recorded)["T5"]["detail"]
    legacy = [_seeking("a"), _seeking("b", staging={"peak_media_bytes": 94_312}), _seeking("c")]
    judged = _judged(_one_decode(), legacy)["T5"]
    assert not judged["ok"] and "not an exact figure" in judged["detail"], judged["detail"]
    legacy[2]["staging"] = {}
    assert "no exact staging figures" in _judged(_one_decode(), legacy)["T5"]["detail"]
    unmeasured = [_seeking("a"), _seeking("b", staging={"peak_total_bytes": None}), _seeking("c")]
    assert "are not all measured" in _judged(_one_decode(), unmeasured)["T5"]["detail"]


# --------------------------------------------------------------------------- #
# The staging census itself, on real files (v0.7.2 Phase 9, review finding P9-04)
# --------------------------------------------------------------------------- #
# The tests above hand the judge planted figures. These make the figures: a real output base, real files, real child
# processes writing them, and the real census (its audit hook and its directory watch) reading. In every case the
# truth is taken by a witness that shares nothing with the census: the test's own listing and its own ``stat``, at the
# moment the test knows the total is at its largest. The census must report that number. Phase 8's census read before two
# wrapped helpers only, and its tests removed their extra files through those same helpers, so they could not show what
# the review then showed with a direct ``unlink``: 200,100 bytes staged, 100 reported.
_WRITER = ("import sys; open(sys.argv[1], 'wb').write(b'm' * int(sys.argv[2])); "
           "sys.stdout.write('d' * int(sys.argv[3])); sys.stdout.flush()")


class _Staged:
    """One output base with the census on it, and a chapter's life lived on it by plain filesystem calls and real children."""

    def __init__(self, root: Path, name: str = "run-a") -> None:
        self.module = _scaling_module("staging")
        self.base = root / name / "output-base"
        self.folder = self.base / "M4B-Converter-Outputs" / "run" / "book"
        self.folder.mkdir(parents=True)
        self.census = self.module.StagingCensus(self.base)
        assert self.census.armed(), self.census.record()["observer"]
        self.witnessed = 0

    def witness(self) -> int:
        """Everything staged right now, by this test's own listing: nothing of the census is used."""
        now = sum(path.stat().st_size for path in self.base.rglob(".act-tmp-*") if path.is_file())
        self.witnessed = max(self.witnessed, now)
        return now

    def temporary(self, stem: str, suffix: str) -> Path:
        import tempfile  # noqa: PLC0415

        handle, name = tempfile.mkstemp(prefix=f".act-tmp-{stem}-", suffix=suffix, dir=self.folder)
        os.close(handle)
        return Path(name)

    def written_by_a_child(self, target: Path, size: int) -> Path:
        """*size* bytes in *target*, written by another process: how FFmpeg fills a staged file."""
        subprocess.run([sys.executable, "-c", _WRITER, str(target), str(size), "0"], check=True, stdout=subprocess.DEVNULL)
        return target

    def a_pass(self, target: Path, size: int, log: int) -> Path:
        """One encoder pass as ``m4b_execution.run_argv`` makes it: a diagnostics file created, opened and handed to a child
        as its output, the child writing its output file. Returns the diagnostics file, still there."""
        diagnostics = self.temporary("ffmpeg", ".log")
        with open(diagnostics, "wb") as sink:
            child = subprocess.Popen([sys.executable, "-c", _WRITER, str(target), str(size), str(log)], stdout=sink)
            self.census.diagnostics_sink(sink, child.pid)
        assert child.wait(60) == 0
        return diagnostics

    def chapter(self, number: int, *, audio: int, final: int, log: int, at_the_peak=None, in_the_publication=None) -> None:
        """One chapter staged and published in ``m4b_execution.convert_segment``'s order."""
        staged_final, staged_audio = self.temporary(f"{number:04d}", ".mp3"), self.temporary(f"{number:04d}", ".mp3")
        os.unlink(self.a_pass(staged_audio, audio, log))
        diagnostics = self.a_pass(staged_final, final, log)
        self.witness()  # the largest moment of an honest chapter: both files and the second pass's diagnostics
        if at_the_peak is not None:
            at_the_peak(staged_final)
        os.unlink(diagnostics)
        if in_the_publication is not None:
            in_the_publication(staged_final)
        os.rename(staged_final, self.folder / f"{number:04d}.mp3")
        os.unlink(staged_audio)

    def record(self) -> dict:
        self.census.finish()
        return self.census.record()

    def summary(self, label: str, files: int) -> dict:
        """This run as ``Qualification.run`` would summarise it for the judge: its real census record, an honest sampler."""
        return {"label": label, "files": files, "peak_staged_bytes": 0, "staging": self.record()}


def _t5_of(auto: dict, legacy: list[dict]) -> dict:
    """T5 alone, from real census records: the other figures of a run are not the subject here."""
    qualify = _scaling_module("qualify")
    problems = [f"{run['label']}: {text}" for run in (*legacy, auto) for text in qualify.staging_problems(run)]
    totals = [run["staging"]["peak_total_bytes"] for run in legacy]
    return {"problems": problems, "seeking_total": max(totals), "total": auto["staging"]["peak_total_bytes"],
            "ok": not problems and auto["staging"]["peak_total_bytes"] <= max(totals)
            and auto["staging"]["peak_media_bytes"] <= max(run["staging"]["peak_media_bytes"] for run in legacy)}


def _honest(root: Path, name: str, chapters=((1, 31_656, 60_900),), log: int = 4_100) -> "_Staged":
    run = _Staged(root, name)
    for number, audio, final in chapters:
        run.chapter(number, audio=audio, final=final, log=log)
    return run


@WINDOWS_ONLY
def test_the_census_reads_the_exact_peak_of_everything_staged_and_says_how_completely(tmp_path):
    """Three honest chapters. The peak is at the end of a chapter's second pass, just before that pass's diagnostics file
    is removed: a few milliseconds in a real run. The census reads it because it reads before every removal."""
    run = _honest(tmp_path, "run-a", ((1, 31_656, 60_900), (2, 32_505, 61_816), (3, 31_918, 61_237)), log=122_852)
    record = run.record()
    assert record["peak_total_bytes"] == run.witnessed == 32_505 + 61_816 + 122_852
    assert (record["peak_media_bytes"], record["peak_media_files"]) == (32_505 + 61_816, 2)
    assert (record["peak_diagnostics_bytes"], record["peak_diagnostics_files"]) == (122_852, 1)
    assert record["at_peak"]["total_bytes"] == {"moment": "remove", "media": [32_505, 61_816], "diagnostics": [122_852]}
    assert record["readings"] == {"start": 1, "remove": 9, "rename": 3, "end": 1}, "three removals and one rename a chapter"
    assert (record["at_start_files"], record["left_files"], record["left_bytes"]) == (0, 0, 0)
    observer = record["observer"]
    assert observer["finished"] and observer["audit_hook"] and observer["diagnostics_sinks"] == 6
    assert {key: observer[key] for key in ("unobserved", "links", "without_creation", "written_by_the_application", "errors")} == {
        "unobserved": [], "links": [], "without_creation": [], "written_by_the_application": [], "errors": []}
    watch = observer["watch"]
    assert (watch["armed"], watch["drained"], watch["lost"], watch["error"]) == (True, True, 0, None)
    assert (watch["created"], watch["removed"], watch["renamed"]) == (12, 9, 3), "Windows counted the same life, independently"
    assert sorted(path.name for path in run.folder.iterdir()) == ["0001.mp3", "0002.mp3", "0003.mp3"], "published outputs are not staging"
    assert _scaling_module("qualify").staging_problems({"label": "x", "files": 3, "peak_staged_bytes": run.witnessed,
                                                        "staging": record}) == [], "and the judge takes this record as complete"


@WINDOWS_ONLY
@pytest.mark.parametrize("extra, by, where", [(61_816, "a-child", "in_the_publication"),
                                             (61_816, "the-application", "in_the_publication"),
                                             (4_096, "a-child", "at_the_peak")],
                         ids=["a-whole-copy-inside-the-publication", "a-whole-copy-written-by-the-application",
                              "four-kibibytes-at-the-peak"])
def test_one_more_file_made_and_unlinked_directly_is_read_to_the_byte_and_fails_t5(tmp_path, extra, by, where):
    """The review's two controls (P9-04): a whole copy of the chapter made inside the publication, and 4 KiB of audio made
    at the peak, each removed by a plain ``unlink`` that goes through no helper of the application. The reviewed harness
    reported the honest peak for both and passed T5; another check's failure in the same run was all that stopped them.
    Here T5 itself reads the larger total, the very number the witness took, and fails."""
    legacy = [_honest(tmp_path, f"seek-{n}").summary(f"seek-{n}", 1) for n in (1, 2)]
    run = _Staged(tmp_path, "onedec")
    seen = {}

    def one_more_file(staged_final: Path) -> None:
        copy = staged_final.with_name(".act-tmp-review-extra.mp3")
        if by == "a-child":
            run.written_by_a_child(copy, extra)
        else:
            copy.write_bytes(b"m" * extra)
        seen["with_it"] = run.witness()
        copy.unlink()  # not discard_temporary, not a publication: nothing the old census wrapped

    run.chapter(1, audio=31_656, final=60_900, log=4_100, **{where: one_more_file})
    auto = run.summary("onedec", 1)
    honest_peak = 31_656 + 60_900 + 4_100
    assert legacy[0]["staging"]["peak_total_bytes"] == legacy[1]["staging"]["peak_total_bytes"] == honest_peak
    with_it = 31_656 + 60_900 + extra + (4_100 if where == "at_the_peak" else 0)
    assert seen["with_it"] == with_it > honest_peak, "the planted file really made the total larger than an honest run's"
    assert auto["staging"]["peak_total_bytes"] == with_it == run.witnessed, "the census read exactly what the witness saw"
    judged = _t5_of(auto, legacy)
    assert not judged["ok"] and judged["total"] > judged["seeking_total"], judged
    if by == "the-application":
        assert any("the application wrote through a handle of its own" in text for text in judged["problems"]), judged
    else:
        assert judged["problems"] == [], "the reading was complete; the run simply staged more than the seeking route"


@WINDOWS_ONLY
@pytest.mark.parametrize("how", ["os.truncate", "open-for-writing", "a-handle's-truncate", "a-descriptor's-truncate",
                                 "renamed-away", "written-over", "pathlib-unlink", "shutil-rmtree"])
def test_every_way_of_lowering_what_is_staged_is_read_first(tmp_path, how):
    """A 50,000-byte file a child wrote, and nothing larger anywhere in the run, then made to stop counting in each way a
    file can. The witness takes the total while it is there; the census must report exactly that, whichever call lowered
    it. (Nothing here passes through ``discard_temporary`` or a publication.)"""
    import shutil  # noqa: PLC0415

    run = _Staged(tmp_path)
    transient = run.written_by_a_child(run.temporary("spool", ".pcm"), 50_000)
    bystander = run.written_by_a_child(run.temporary("other", ".mp3"), 7_000)
    there = run.witness()
    assert there == 57_000
    flagged = None
    if how == "os.truncate":
        os.truncate(transient, 0)
    elif how == "open-for-writing":
        with open(transient, "wb"):
            pass
        flagged = "written_by_the_application"
    elif how == "a-handle's-truncate":
        with open(transient, "r+b") as handle:
            handle.truncate(0)
        flagged = "unobserved"
    elif how == "a-descriptor's-truncate":
        descriptor = os.open(transient, os.O_RDWR)
        os.ftruncate(descriptor, 0)
        os.close(descriptor)
        flagged = "unobserved"
    elif how == "renamed-away":
        os.rename(transient, run.folder / "kept-under-another-name.bin")
    elif how == "written-over":
        small = run.written_by_a_child(run.temporary("small", ".pcm"), 10)
        there = run.witness()
        assert there == 57_010
        os.replace(small, transient)
    elif how == "pathlib-unlink":
        transient.unlink()
    else:
        nested = run.folder / "work"
        nested.mkdir()
        os.rename(transient, nested / transient.name)
        shutil.rmtree(nested)
    for leftover in (transient, bystander):
        if leftover.exists():
            os.unlink(leftover)
    record = run.record()
    assert record["peak_total_bytes"] == there == run.witnessed, (how, record["peak_total_bytes"], there)
    observer = record["observer"]
    assert observer["errors"] == []
    if flagged is None:
        assert observer["unobserved"] == [] and observer["written_by_the_application"] == [], observer
    else:
        assert observer[flagged], f"{how} leaves something the reading cannot follow, and the record must say so: {observer}"


@WINDOWS_ONLY
def test_a_temporary_forgotten_and_a_publication_interrupted_are_left_behind_and_say_so(tmp_path):
    run = _Staged(tmp_path)
    run.chapter(1, audio=31_656, final=60_900, log=4_100)
    run.written_by_a_child(run.temporary("forgotten", ".pcm"), 529_200)
    # A second chapter that stops after its first pass: its two staged files and that pass's diagnostics stay.
    staged_final, staged_audio = run.temporary("0002", ".mp3"), run.temporary("0002", ".mp3")
    run.a_pass(staged_audio, 31_000, 4_100)
    assert staged_final.exists()
    record = run.record()
    assert (record["left_files"], record["left_bytes"]) == (4, 529_200 + 31_000 + 4_100)
    problems = _scaling_module("qualify").staging_problems({"label": "x", "files": 1, "peak_staged_bytes": 0, "staging": record})
    assert problems == [f"4 temporaries left behind ({529_200 + 31_000 + 4_100} bytes)"]


@WINDOWS_ONLY
def test_a_file_is_diagnostics_only_when_a_child_was_given_it_as_its_output_never_by_its_name(tmp_path):
    """The reviewed census took any name ending in ``.log`` for diagnostics, so 4,096 bytes of audio in
    ``.act-tmp-audio-buffer.log`` were not staged media. Provenance decides now: what a child was handed as its output."""
    run = _Staged(tmp_path)
    audio_named_log = run.written_by_a_child(run.folder / ".act-tmp-audio-buffer.log", 4_096)
    reading = run.census.read("check")
    assert (reading["media_bytes"], reading["diagnostics_bytes"]) == (4_096, 0), "a .log nobody was handed is media"
    # The other way round: a real child's real output sink is diagnostics whatever it is called.
    target = run.temporary("0001", ".mp3")
    sink_named_mp3 = run.temporary("sink", ".mp3")
    with open(sink_named_mp3, "wb") as sink:
        child = subprocess.Popen([sys.executable, "-c", _WRITER, str(target), "100", "300"], stdout=sink)
        run.census.diagnostics_sink(sink, child.pid)
    assert child.wait(60) == 0
    reading = run.census.read("check")
    assert (reading["media_bytes"], reading["diagnostics_bytes"]) == (4_096 + 100, 300)
    # ...and it is that file, not that name: remove it, let a child write audio under the same name, and it is media.
    os.unlink(sink_named_mp3)
    run.written_by_a_child(sink_named_mp3, 800)
    reading = run.census.read("check")
    assert (reading["media_bytes"], reading["diagnostics_bytes"]) == (4_096 + 100 + 800, 0)
    for path in (audio_named_log, target, sink_named_mp3):
        os.unlink(path)
    record = run.record()
    assert record["peak_media_bytes"] == 4_096 + 100 + 800 and record["peak_diagnostics_bytes"] == 300
    assert record["observer"]["unobserved"] == [] and record["observer"]["written_by_the_application"] == []


@WINDOWS_ONLY
def test_a_link_among_the_temporaries_is_never_followed_and_fails_the_reading(tmp_path):
    """A junction (a reparse point any account may make) to a folder that holds someone else's 80,000-byte file under a
    temporary's name, and a second name (a hard link) for someone else's file. Neither is entered or taken as staged media
    without saying so; a symbolic link is the same case where this account may create one."""
    import _winapi  # noqa: PLC0415

    foreign = tmp_path / "someone-elses"
    foreign.mkdir()
    (foreign / ".act-tmp-foreign.mp3").write_bytes(b"f" * 80_000)
    (foreign / "theirs.bin").write_bytes(b"t" * 9_000)
    run = _Staged(tmp_path)
    junction = run.folder / "linked"
    _winapi.CreateJunction(str(foreign), str(junction))
    made = ["linked"]
    try:
        os.link(foreign / "theirs.bin", run.folder / ".act-tmp-second-name.mp3")
        made.append(".act-tmp-second-name.mp3")
        try:
            os.symlink(foreign / ".act-tmp-foreign.mp3", run.folder / ".act-tmp-symbolic.mp3")
            made.append(".act-tmp-symbolic.mp3")
        except OSError:
            pass  # this account may not create symbolic links; the junction and the hard link are the case either way
        reading = run.census.read("check")
        assert reading["total_bytes"] == 9_000, "the junction was not entered and the symbolic link not followed"
        os.unlink(run.folder / ".act-tmp-second-name.mp3")
        if ".act-tmp-symbolic.mp3" in made:
            os.unlink(run.folder / ".act-tmp-symbolic.mp3")
        record = run.record()
        assert sorted(record["observer"]["links"]) == sorted(made)
        problems = _scaling_module("qualify").staging_problems({"label": "x", "files": 0, "peak_staged_bytes": 0, "staging": record})
        assert any("links among the temporaries" in text for text in problems), problems
        assert (foreign / ".act-tmp-foreign.mp3").stat().st_size == 80_000 and (foreign / "theirs.bin").stat().st_size == 9_000
    finally:
        os.rmdir(junction)  # the link alone; what it pointed to stays


@WINDOWS_ONLY
def test_a_temporary_that_was_there_before_the_run_is_not_this_runs_and_the_record_says_so(tmp_path):
    """Missing ownership evidence: nothing saw this file created under this base in this run."""
    base = tmp_path / "run-a" / "output-base" / "M4B-Converter-Outputs" / "run" / "book"
    base.mkdir(parents=True)
    (base / ".act-tmp-from-an-earlier-run.mp3").write_bytes(b"o" * 12_345)
    run = _Staged.__new__(_Staged)
    run.module = _scaling_module("staging")
    run.base, run.folder, run.witnessed = tmp_path / "run-a" / "output-base", base, 0
    run.census = run.module.StagingCensus(run.base)
    os.unlink(base / ".act-tmp-from-an-earlier-run.mp3")
    record = run.record()
    assert record["at_start_files"] == 1 and record["observer"]["without_creation"] == [".act-tmp-from-an-earlier-run.mp3"]
    problems = _scaling_module("qualify").staging_problems({"label": "x", "files": 0, "peak_staged_bytes": 0, "staging": record})
    assert any("nobody saw created under this base in this run" in text for text in problems)
    assert any("1 temporaries were there before the run" in text for text in problems)


@WINDOWS_ONLY
def test_a_temporary_another_process_removes_is_not_passed_off_as_read(tmp_path):
    """The audit hook hears this process only. A removal by any other process is what Windows' own report is kept for:
    one file a reading had seen, and one a child both made and removed between two readings."""
    remover = "import os, sys; os.unlink(sys.argv[1])"
    run = _Staged(tmp_path)
    seen = run.written_by_a_child(run.temporary("seen", ".mp3"), 40_000)
    run.census.read("check")
    subprocess.run([sys.executable, "-c", remover, str(seen)], check=True)
    unseen = run.folder / ".act-tmp-never-read.pcm"
    subprocess.run([sys.executable, "-c", "import os, sys; open(sys.argv[1], 'wb').write(b'p' * 90000); os.unlink(sys.argv[1])",
                    str(unseen)], check=True)
    record = run.record()
    unobserved = record["observer"]["unobserved"]
    assert any(seen.name in text and "was gone at a reading" in text for text in unobserved), unobserved
    assert any(unseen.name in text and "as Windows reported, with no reading taken for it" in text for text in unobserved), unobserved
    assert record["peak_total_bytes"] == 40_000, "what was never read is not in the figure, which is why the figure is refused"
    problems = _scaling_module("qualify").staging_problems({"label": "x", "files": 0, "peak_staged_bytes": 0, "staging": record})
    assert any("the total fell without a reading" in text for text in problems)


_TRANSIENT = ("from pathlib import Path; import sys; p = Path(sys.argv[1]); p.write_bytes(b'z' * 200_100); "
              "print(p.stat().st_size, flush=True); p.unlink()")


@WINDOWS_ONLY
@pytest.mark.parametrize("child", [None, ".act-tmp-reused.mp3", ".act-tmp-fresh.mp3"],
                         ids=["the-control", "a-name-a-reading-was-taken-for", "a-name-never-read"])
def test_a_reading_taken_for_one_file_never_vouches_for_a_later_file_of_the_same_name(tmp_path, child):
    """v0.7.2 Phase 9 remote re-review R9-02, the reviewer's three cases. This process makes ``.act-tmp-reused.mp3``
    (100 bytes), and removes it: read for, and announced. A child then makes a file of that very name, grows it to
    200,100 bytes, confirms the size and removes it, with no reading taken. The census kept its account per name, so the
    earlier announcement covered the later file and T5 passed on the honest peak. Each file that has a name is
    accounted for now: the reused name fails as the never-read name always did, and the run with no child still passes
    against the same budget, unchanged."""
    legacy = [_honest(tmp_path, f"seek-{n}").summary(f"seek-{n}", 1) for n in (1, 2)]
    run = _Staged(tmp_path, "auto")
    first = run.folder / ".act-tmp-reused.mp3"
    descriptor = os.open(first, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(descriptor, b"x" * 100)
    os.close(descriptor)
    os.unlink(first)
    witnessed = None
    if child is not None:
        done = subprocess.run([sys.executable, "-c", _TRANSIENT, str(run.folder / child)], check=True,
                              capture_output=True, text=True)
        witnessed = int(done.stdout.strip())
    run.chapter(1, audio=31_656, final=60_900, log=4_100)
    auto = run.summary("auto", 1)
    judged = _t5_of(auto, legacy)
    if child is None:
        assert judged["ok"] and judged["problems"] == [], judged
        assert judged["total"] == judged["seeking_total"] == 31_656 + 60_900 + 4_100
        return
    assert witnessed == 200_100 > auto["staging"]["peak_total_bytes"], "the child's file was never read"
    assert not judged["ok"], judged
    unobserved = auto["staging"]["observer"]["unobserved"]
    expected = ("was removed or renamed 2 times, as Windows reported, and a reading was taken for only 1"
                if child == ".act-tmp-reused.mp3" else "as Windows reported, with no reading taken for it")
    assert any(text.startswith(child) and expected in text for text in unobserved), unobserved
    assert any("the total fell without a reading" in text for text in judged["problems"]), judged


@WINDOWS_ONLY
def test_the_directory_watch_reports_what_happened_under_the_folder_and_nothing_else(tmp_path):
    module = _scaling_module("staging")
    inside, outside = tmp_path / "watched", tmp_path / "elsewhere"
    (inside / "deep" / "er").mkdir(parents=True)
    outside.mkdir()
    watch = module.DirectoryWatch(inside)
    try:
        assert watch.armed and watch.error is None
        owned = inside / "deep" / "er" / ".act-tmp-0001-abc.mp3"
        renamed, moved = owned.with_name(".act-tmp-0001-def.mp3"), inside / "deep" / "er" / ".act-tmp-0002-ghi.mp3"
        owned.write_bytes(b"x")
        os.rename(owned, renamed)                                  # to another temporary's name, in its own folder
        os.rename(renamed, inside / "deep" / "er" / "0001.mp3")    # published: to an output's name, in its own folder
        moved.write_bytes(b"m")
        os.rename(moved, inside / "deep" / moved.name)             # into another folder
        (inside / ".act-tmp-top.log").write_bytes(b"y")
        os.unlink(inside / ".act-tmp-top.log")
        (inside / "an-ordinary-file.txt").write_bytes(b"z")
        (outside / ".act-tmp-not-watched.mp3").write_bytes(b"w")
        assert watch.mark(), "everything up to here has been reported"
        place = lambda path: os.path.normcase(str(path))  # noqa: E731
        # Windows reports a rename inside one folder as a rename, and a move to another folder as a removal there and a
        # creation here. Either way the old name is in what the census holds its readings to (removed or renamed away).
        assert watch.added == {place(owned), place(moved), place(inside / "deep" / moved.name), place(inside / ".act-tmp-top.log")}
        assert watch.renamed_from == {place(owned), place(renamed)} and watch.renamed_to == {place(renamed)}
        assert watch.removed == {place(moved), place(inside / ".act-tmp-top.log")}
        assert watch.lost == 0
    finally:
        watch.stop()


@WINDOWS_ONLY
def test_the_census_hears_only_its_own_base_never_stops_an_operation_and_hands_out_copies(tmp_path):
    run = _Staged(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    before = dict(run.census.readings)
    stranger = elsewhere / ".act-tmp-someone-elses.mp3"
    stranger.write_bytes(b"s" * 100)
    os.unlink(stranger)
    (run.folder / "an-output.mp3").write_bytes(b"o")
    os.unlink(run.folder / "an-output.mp3")
    assert run.census.readings == before, "a temporary of another folder, and a file that is not a temporary, are not this census's"
    # An event the hook cannot make sense of is recorded and never raised: raising would stop the application's operation.
    for event, arguments in (("os.truncate", ()), ("os.remove", (object(),)), ("os.rename", (None, 7, None, None)),
                             ("open", (b"\xff\xfe.act-tmp-odd", "wb", 0))):
        run.census._heard(event, arguments)
    run.chapter(1, audio=1_000, final=2_000, log=300)
    first = run.record()
    first["at_peak"]["total_bytes"]["media"].append(999_999)
    first["observer"]["errors"].append("edited by a reader")
    again = run.census.record()
    assert again["at_peak"]["total_bytes"]["media"] == [1_000, 2_000]
    assert again["observer"]["errors"] == ["os.truncate: IndexError: tuple index out of range"]
    assert again["peak_total_bytes"] == run.witnessed == 3_300


def test_the_converters_own_code_never_shortens_a_file_through_a_handle():
    """The one thing the census cannot hear is a file shortened through a handle already open. The Converter has no such
    code; if it ever gains some, this fails and the census has to learn to read it before T5 can be trusted again."""
    import ast  # noqa: PLC0415

    scripts = REPO_ROOT / "scripts"
    sources = [*sorted((scripts / "m4b").glob("*.py")), *sorted((scripts / "m4b" / "converter").glob("*.py")),
               scripts / "shared" / "output_paths.py", scripts / "shared" / "subprocess_utils.py"]
    assert {"m4b_execution.py", "m4b_continuous.py", "m4b_converter.py", "output_paths.py"} <= {path.name for path in sources}
    found = []
    for source in sources:
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in ("truncate", "ftruncate", "fdopen", "mmap"):
                found.append(f"{source.relative_to(scripts).as_posix()}: .{node.attr}")
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [alias.name for alias in node.names] + ([node.module] if isinstance(node, ast.ImportFrom) else [])
                if "mmap" in names:
                    found.append(f"{source.relative_to(scripts).as_posix()}: imports mmap")
    assert found == []


def test_a_benchmark_child_is_let_go_once_it_has_ended():
    """Windows keeps charging a job for an exited process while a handle to it is open (about 77 KB each, measured), and
    the harness used to keep every child's Popen object: 155 MB of the 1,000-chapter book's 236 MB 'job peak' was that."""
    if sys.platform != "win32":
        pytest.skip("the benchmark harness accounts through Windows Job Objects")
    bench = _scaling_module("bench_run")
    proc = subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.read()"], stdin=subprocess.PIPE)
    child = bench.Child("segment", proc, time.perf_counter())
    try:
        assert child.alive() and child.proc is proc
        running = child.settle()
        assert child.proc is proc and child.facts is None and "peak_commit" in running, "a running child keeps its handle"
    finally:
        proc.stdin.close()
        proc.wait(30)
    assert not child.alive()
    facts = child.settle()
    assert child.proc is None, "the harness still holds the exited child's Popen object, and with it the handle"
    assert facts["peak_commit"] > 0 and facts is child.facts and child.settle() is facts and child.pid == proc.pid
    source = (GATE_DIR / "scaling" / "bench_run.py").read_text(encoding="utf-8")
    assert "children.append(Child(" in source and "children.append((kind, proc" not in source


def test_a_benchmark_run_refuses_a_folder_too_deep_for_its_own_temp():
    """Every run is given its own TEMP inside its folder. At 262 characters that TEMP made Windows spin for good inside
    CreateProcess (BasepQueryAppCompat -> GetTempPathW, read from the thread's stack), with FFprobe created and never
    started: twenty minutes at a full core before it was stopped (Phase 9 remediation, a planted-defect control with a
    long name). A run folder that deep is refused before anything is made in it; one character less is not."""
    bench = _scaling_module("bench_run")
    assert 222 < bench.LONGEST_TEMP < 260, "a gate qualification's own run folders (about 222) must stay allowed"
    root = Path("C:/q")
    fits = root / ("d" * (bench.LONGEST_TEMP - len(str(root / "x" / "tmp")) + 1))
    assert len(str(fits / "tmp")) == bench.LONGEST_TEMP and bench.run_temp(fits) == fits / "tmp"
    too_deep = fits.with_name(fits.name + "d")
    with pytest.raises(bench.Refused) as refused:
        bench.run_temp(too_deep)
    assert refused.value.code == bench.EXIT_CONTAINMENT
    assert f"would be {bench.LONGEST_TEMP + 1} characters" in refused.value.message and "TEMP" in refused.value.message
    source = (GATE_DIR / "scaling" / "bench_run.py").read_text(encoding="utf-8")
    main = source[source.index("def main("):]
    assert main.index("temp = run_temp(out)") < main.index("out.mkdir("), "refused only after the folder was made"
    assert 'out / "tmp"' not in main, "the run's TEMP is taken from somewhere the length is not judged"


def test_the_decoders_console_host_is_found_among_the_jobs_processes():
    """The job is made in a child interpreter: a job that kills on close must never be put around pytest itself."""
    if sys.platform != "win32":
        pytest.skip("console hosts and Job Objects are Windows")
    script = textwrap.dedent(f"""
        import json, subprocess, sys
        sys.path.insert(0, {str(GATE_DIR / 'scaling')!r})
        import winjob
        job = winjob.Job()
        child = subprocess.Popen(["cmd.exe", "/d", "/k"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            child.stdin.write(b"rem\\r\\n")
            child.stdin.flush()
            found = []
            for _ in range(200):
                found = job.children_of(child.pid)
                if found:
                    break
                import time; time.sleep(0.05)
            facts = [dict(image=c["image"], peak=winjob.process_facts(c["handle"]).get("peak_commit")) for c in found]
            for c in found:
                winjob.close_handle(c["handle"])
            print(json.dumps({{"ids": len(job.process_ids()), "found": facts, "strangers": job.children_of(0)}}))
        finally:
            child.stdin.close()
            child.wait(30)
    """)
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    told = json.loads(done.stdout.strip().splitlines()[-1])
    assert [item["image"] for item in told["found"]] == ["conhost.exe"], told
    assert told["found"][0]["peak"] > 0 and told["ids"] >= 3 and told["strangers"] == [], told
