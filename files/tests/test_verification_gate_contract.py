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
    this test and the packaging test assert its absence; and one comment in ``scripts/requirements.txt`` is byte-hash-locked
    into setup (editing it would make every installed environment look stale), so it waits for the next dependency change.
    """
    assert not (REPO_ROOT / "scripts" / "verify.py").exists()
    done = subprocess.run(["git", "grep", "-l", "-F", "scripts/verify.py"], cwd=REPO_ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if done.returncode not in (0, 1):
        pytest.skip("not a git checkout")
    allowed = {"files/tests/test_verification_gate_contract.py", "files/tests/test_release_packaging.py",
               "scripts/requirements.txt", "md-instructions/Handoff.md", "md-instructions/Decisions.md",
               "md-instructions/Changelog.md", "md-instructions/Briefing.md"}
    active = [path for path in done.stdout.splitlines()
              if path not in allowed and not path.startswith(("files/plans/", "files/release-history/"))]
    assert not active, active


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
import json, sys, time
from pathlib import Path
out = Path(sys.argv[sys.argv.index("--out") + 1])
out.mkdir(parents=True)
(out / "progress.log").write_text("started\\n")
{before}
(out / "verdict.json").write_text(json.dumps({verdict!r}))
sys.exit({code})
'''
TWO_CHECKS = [{"name": "T8:one", "status": "PASS", "detail": "identical"}, {"name": "T1", "status": "PASS", "detail": "2.1x"}]


def _qualification(tree, verdict: dict, code: int, *, before: str = ""):
    """One real qualification run of m4b-scaling whose runner writes *verdict* and exits *code*."""
    (tree.gate / "scaling" / "qualify.py").write_text(
        textwrap.dedent(SCENARIO_RUNNER).format(verdict=verdict, code=code, before=before), encoding="utf-8")
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
        verdict=_verdict("PASS"), code=0, before=f"Path({str(started)!r}).write_text('x')\ntime.sleep(120)"), encoding="utf-8")
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
# The m4b-scaling harness: what T4 and T5 measure (v0.7.2 Phase 8 remediation)
# --------------------------------------------------------------------------- #
@functools.lru_cache(maxsize=None)
def _scaling_module(name: str):
    """bench_run.py or qualify.py, loaded the way the gate runs them (their own folder first on the path)."""
    if sys.platform != "win32":
        pytest.skip("the benchmark harness accounts through Windows Job Objects")
    import importlib.util  # noqa: PLC0415

    saved_path, saved_modules = list(sys.path), {key: sys.modules.get(key) for key in ("winjob", "common", "recipe")}
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


def _seeking(label: str, **over) -> dict:
    """A seeking-route run's summary. The figures are those of the 1,000-chapter book with the corrected harness."""
    run = {"label": label, "files": 1000, "peak_job_commit": 82_100_000, "write_bytes": 339_406_132,
           "app_write_bytes": 2_132_979, "peak_staged_bytes": 215_728, "decoders": [], "pipe": {},
           "staging": {"peak_media_bytes": 94_311, "peak_diagnostics_bytes": 122_852, "peak_total_bytes": 217_163,
                       "readings_before_discard": 3000, "readings_before_publish": 1000, "left_files": 0, "left_bytes": 0}}
    run.update(over)
    return run


def _one_decode(label: str = "tput-scale1000-180", *, decoder=None, staging=None, **over) -> dict:
    stream = 530_963_296
    run = _seeking(label, peak_job_commit=82_100_000 + 29_097_984 + 1_740_800 + 600_000,
                   write_bytes=219_834_875 + 2 * stream, app_write_bytes=stream + 1_999_074, peak_staged_bytes=215_796,
                   pipe={"from_decoder_bytes": stream, "to_encoders_bytes": stream})
    run["decoders"] = [{"peak_buffered": 532_728, "peak_commit": 29_097_984, "write_bytes": stream, "diagnostics_bytes": 0,
                        "companions": [{"pid": 4, "image": "conhost.exe", "peak_commit": 1_740_800}], **(decoder or {})}]
    run["staging"] = {**run["staging"], "readings_before_discard": 3001, **(staging or {})}
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


def test_t5_compares_exact_staged_media_with_no_allowance():
    assert _judged(_one_decode(staging={"peak_media_bytes": 94_311}))["T5"]["ok"], "equal is not more"
    assert _judged(_one_decode(staging={"peak_media_bytes": 94_310}))["T5"]["ok"]
    one_more = _judged(_one_decode(staging={"peak_media_bytes": 94_312}))["T5"]
    assert not one_more["ok"] and "staged media 94312 bytes is more than the seeking route's 94311" in one_more["detail"]
    # One more staged chapter kept, or a decoded chapter spooled beside it:
    assert not _judged(_one_decode(staging={"peak_media_bytes": 94_311 + 32_505}))["T5"]["ok"]
    assert not _judged(_one_decode(staging={"peak_media_bytes": 94_311 + 529_200}))["T5"]["ok"]


def test_the_sampled_figures_that_failed_in_phase_8_no_longer_decide_t5():
    """Session 2dbf: sampled 215,796 against the seeking route's sampled 215,728, 68 bytes. Both were samples of one and
    the same true peak. With the staged media read exactly and equal, that pair of samples passes; the samples are kept
    only as a witness that must not exceed the exact reading."""
    auto = _one_decode(peak_staged_bytes=215_796)
    legacy = [_seeking("a", peak_staged_bytes=215_512), _seeking("b", peak_staged_bytes=215_728), _seeking("c", peak_staged_bytes=215_586)]
    assert _judged(auto, legacy)["T5"]["ok"]


@pytest.mark.parametrize("planted, needle", [
    (dict(staging={"left_files": 1, "left_bytes": 31_918}), "1 temporaries left behind"),
    (dict(staging={"readings_before_publish": 999}), "999 readings before a publication for 1000 outputs"),
    (dict(staging={"readings_before_discard": 0}), "readings before a publication"),
    (dict(peak_staged_bytes=217_164), "the 0.5 s sampler saw 217164 bytes staged, more than the exact reading's peak 217163"),
    (dict(staging={"peak_diagnostics_bytes": 128_995}), "diagnostics 128995 bytes is more than the seeking route's 122852 x 1.05"),
    (dict(staging={"peak_media_bytes": None}), "staged media None bytes"),
], ids=["a-temporary-left-behind", "a-publication-not-read", "no-discard-read", "the-sampler-saw-more", "diagnostics-over-1.05x",
        "media-not-measured"])
def test_t5_fails_when_the_reading_is_incomplete_or_shows_more(planted, needle):
    judged = _judged(_one_decode(**planted))["T5"]
    assert not judged["ok"] and needle in judged["detail"], judged["detail"]


def test_t5_fails_without_exact_figures_and_when_the_seeking_runs_disagree():
    missing = _one_decode()
    missing["staging"] = {}
    assert "no exact staging figures" in _judged(missing)["T5"]["detail"]
    legacy = [_seeking("a"), _seeking("b"), _seeking("c")]
    legacy[1]["staging"] = {**legacy[1]["staging"], "peak_media_bytes": 94_312}
    judged = _judged(_one_decode(), legacy)["T5"]
    assert not judged["ok"] and "not an exact figure" in judged["detail"], judged["detail"]
    legacy[2]["staging"] = {}
    assert "no exact staging figures" in _judged(_one_decode(), legacy)["T5"]["detail"]


def test_diagnostics_text_a_few_bytes_longer_is_not_extra_staging():
    """FFmpeg's own text differs by a few bytes between identical runs (measured: 14,651 against 14,655 on one book)."""
    assert _judged(_one_decode(staging={"peak_diagnostics_bytes": 122_856}))["T5"]["ok"]


def _census(tmp_path):
    bench = _scaling_module("bench_run")
    base = tmp_path / "output-base"
    folder = base / "M4B-Converter-Outputs" / "run" / "book"
    folder.mkdir(parents=True)
    census = bench.StagingCensus(base)

    def discard(path):
        if path is None:
            return False
        Path(path).unlink()
        return True

    module = types.SimpleNamespace(discard_temporary=discard, atomic_replace=lambda source, target: os.replace(source, target))
    census.wrap(module)
    return census, module, folder


def _chapter(module, folder: Path, number: int, *, audio: int, final: int, log: int) -> None:
    """One chapter staged, measured and published the way m4b_execution.convert_segment does it."""
    staged_final, staged_audio = folder / f".act-tmp-{number:04d}-f.mp3", folder / f".act-tmp-{number:04d}-a.mp3"
    staged_final.write_bytes(b"")
    staged_audio.write_bytes(b"")
    for target, size in ((staged_audio, audio), (staged_final, final)):
        diagnostics = folder / f".act-tmp-ffmpeg-{number:04d}{target.name[-5]}.log"
        diagnostics.write_bytes(b"d" * log)
        target.write_bytes(b"m" * size)
        module.discard_temporary(diagnostics)
    module.atomic_replace(staged_final, folder / f"{number:04d}.mp3")
    module.discard_temporary(staged_audio)


def test_the_staging_census_reads_the_exact_peak_of_media_and_diagnostics_apart(tmp_path):
    """The peak is at the end of a chapter's second pass, just before that pass's diagnostics file is discarded: for a
    few milliseconds in a real run, which a 0.5 s sampler mostly misses. The census reads it because it reads there."""
    census, module, folder = _census(tmp_path)
    for number, audio, final in ((1, 31_656, 60_900), (2, 32_505, 61_816), (3, 31_918, 61_237)):
        _chapter(module, folder, number, audio=audio, final=final, log=122_852)
    census.finish()
    record = census.record()
    assert record["peak_media_bytes"] == 32_505 + 61_816 and record["peak_media_files"] == 2
    assert record["peak_diagnostics_bytes"] == 122_852 and record["peak_diagnostics_files"] == 1
    assert record["peak_total_bytes"] == 32_505 + 61_816 + 122_852 and record["peak_total_files"] == 3
    assert record["at_peak"]["media_bytes"] == {"moment": "discard", "media": [32_505, 61_816], "diagnostics": [122_852]}
    assert record["readings_before_publish"] == 3 and record["readings_before_discard"] == 9
    assert record["left_files"] == 0 and record["left_bytes"] == 0
    assert sorted(path.name for path in folder.iterdir()) == ["0001.mp3", "0002.mp3", "0003.mp3"], "published outputs are not staging"


def test_the_staging_census_sees_extra_staging_a_spool_and_a_leftover(tmp_path):
    census, module, folder = _census(tmp_path)
    _chapter(module, folder, 1, audio=31_656, final=60_900, log=100)
    honest = census.record()["peak_media_bytes"]
    assert honest == 31_656 + 60_900
    # A decoded chapter spooled beside the outputs as one of the application's own temporaries, kept while a chapter is made:
    spool = folder / ".act-tmp-decoded-0002.pcm"
    spool.write_bytes(b"p" * 529_200)
    _chapter(module, folder, 2, audio=31_656, final=60_900, log=100)
    assert census.record()["peak_media_bytes"] == honest + 529_200
    census.finish()
    assert census.record()["left_files"] == 1 and census.record()["left_bytes"] == 529_200
    # Discarding nothing (the application passes None for a temporary it never made) is not a reading.
    before = census.record()["readings_before_discard"]
    assert module.discard_temporary(None) is False and census.record()["readings_before_discard"] == before


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
