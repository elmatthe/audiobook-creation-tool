"""The verification gate leaves durable, honest evidence of every run (carried over from v0.7.0 P00C, gate moved in v0.7.2).

A run that fails or is cut short must leave something to inspect (plan §6.2). The gate streams the child's output to disk as
it arrives, records every gate, the interpreter and the tested tree, and finalizes ``results.json`` only after normal
completion. These tests hold it to that: every way a run can end — pass, failure, empty collection, a bad JUnit report, a
moved tree, an interruption, an error, a kill — reads back as what it was. Never PASS by omission.

pytest itself is never run here. A small synthetic child stands in for it through ``verify._pytest_command`` and behaves
like pytest at the boundary the gate sees: merged output in a file, an exit code, a JUnit file and a session record. Real
pytest over a real tree is ``test_verification_gate_contract.py``. The tree fingerprint runs real ``git`` against a
throwaway repository, so nothing touches this checkout's evidence folder.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import _thread
from pathlib import Path

import pytest

from gate_locator import GATE_DIR, GATE_PATH, load_gate

GATE_ORDER = ["pytest", "guarded", "deps", "docs", "docnames", "config"]
EVIDENCE_FILES = {"logs/verify.log", "logs/pytest.log", "reports/pytest.xml", "reports/pytest-probe.jsonl", "start.json",
                  "results.json", "selection.json", "summary.md"}

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="the tree fingerprint needs git")

# Stands in for pytest: argv is <junit path> <mode> [extra]. Output goes to both streams, as pytest's does.
FAKE_PYTEST = r'''
import ctypes, json, os, pathlib, sys, time

junit, mode = pathlib.Path(sys.argv[1]), sys.argv[2]
extra = sys.argv[3] if len(sys.argv) > 3 else None
token = os.environ.get("ACT_GATE_TOKEN", "")
probe_path = os.environ.get("ACT_GATE_PROBE")
error_mode = hex(ctypes.WinDLL("kernel32").GetErrorMode()) if sys.platform == "win32" else None


def row(sink, **fields):
    sink.write(json.dumps(fields) + "\n")


def record(tests, failed=0, skipped=0, exit_status=0, finish=True, drop_first=False):
    """A session record: this many tests, the last ones failed or skipped."""
    with open(probe_path, "x", encoding="utf-8") as sink:
        row(sink, e="session-start", token=token, pid=os.getpid(), ppid=os.getppid(), mode=error_mode)
        ids = [f"synthetic_test.py::test_{index}" for index in range(tests)]
        row(sink, e="collected", ids=ids)
        for index, nodeid in enumerate(ids):
            if drop_first and index == 0:
                continue
            if index >= tests - skipped:
                row(sink, e="r", id=nodeid, w="setup", o="skipped", d=0, reason="synthetic skip reason")
            else:
                row(sink, e="r", id=nodeid, w="setup", o="passed", d=0)
                row(sink, e="r", id=nodeid, w="call", o="failed" if index >= tests - skipped - failed else "passed", d=0)
            row(sink, e="r", id=nodeid, w="teardown", o="passed", d=0)
        if finish:
            row(sink, e="session-finish", exit=exit_status, mode=error_mode)


def report(tests, failures=0, errors=0, skipped=0, suite=None, listed=None):
    cases = []
    for index in range(tests if listed is None else listed):
        body = ""
        if index >= tests - skipped:
            body = '<skipped message="synthetic skip reason"/>'
        elif index >= tests - skipped - failures:
            body = '<failure message="boom"/>'
        cases.append(f'<testcase classname="synthetic_test" name="test_{index}">{body}</testcase>')
    junit.write_text(
        '<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite '
        f'name="{token if suite is None else suite}" tests="{tests}" failures="{failures}" errors="{errors}" '
        f'skipped="{skipped}">{"".join(cases)}</testsuite></testsuites>', encoding="utf-8")


def passed():
    report(3, skipped=1)
    record(3, skipped=1)
    print("SKIPPED [1] synthetic_test.py:4: synthetic skip reason")
    print("2 passed, 1 skipped in 0.01s")
    sys.exit(0)


print("synthetic session starts", flush=True)
print("synthetic stderr line", file=sys.stderr, flush=True)
if mode == "pass":
    passed()
elif mode == "fail":
    print("Traceback (most recent call last):")
    print('  File "synthetic_test.py", line 7, in test_boom')
    print("E   AssertionError: synthetic boom")
    print("FAILED synthetic_test.py::test_boom - AssertionError: synthetic boom")
    report(3, failures=1)
    record(3, failed=1, exit_status=1)
    print("1 failed, 2 passed in 0.01s")
    sys.exit(1)
elif mode == "empty":
    report(0)
    record(0, exit_status=5)
    print("no tests ran in 0.01s")
    sys.exit(5)
elif mode == "collection-error":
    print("ERROR collecting synthetic_test.py")
    report(0, errors=1, listed=0)
    record(0, exit_status=2)
    print("1 error in 0.01s")
    sys.exit(2)
elif mode == "exit0-no-junit":
    record(3)
    print("3 passed in 0.01s")
    sys.exit(0)
elif mode == "exit0-truncated-junit":
    junit.write_text('<?xml version="1.0"?><testsuites><testsuite name="pytest" tests="3"', encoding="utf-8")
    record(3)
    print("3 passed in 0.01s")
    sys.exit(0)
elif mode == "exit0-zero-tests":
    report(0)
    record(0)
    print("no tests ran in 0.01s")
    sys.exit(0)
elif mode == "exit0-junit-failures":
    report(3, failures=1)
    record(3)
    print("3 passed in 0.01s")
    sys.exit(0)
elif mode == "exit0-no-record":
    report(3)
    print("3 passed in 0.01s")
    sys.exit(0)
elif mode == "exit0-unfinished-record":
    report(3)
    record(3, finish=False)
    sys.exit(0)
elif mode == "exit0-masked-session":
    report(3)
    record(3, exit_status=1)
    sys.exit(0)
elif mode == "exit0-stale-report":
    report(3, suite="an-earlier-run-pytest")
    record(3)
    sys.exit(0)
elif mode == "exit0-count-mismatch":
    report(3, listed=2)
    record(3)
    sys.exit(0)
elif mode == "exit0-collected-not-run":
    report(3)
    record(3, drop_first=True)
    sys.exit(0)
elif mode == "wait":
    print("first streamed line", flush=True)
    sys.stdout.write("..partial-progress")  # no newline: still has to reach the log
    sys.stdout.flush()
    go = pathlib.Path(extra)
    deadline = time.monotonic() + 60
    while not go.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    print()
    passed()
elif mode == "forever":
    deadline = time.monotonic() + 60  # bounded, so a lost child can never outlive the test session by much
    while time.monotonic() < deadline:
        print("still running", flush=True)
        time.sleep(0.05)
    sys.exit(0)
elif mode == "touch":
    pathlib.Path(extra).write_text("changed while the gate ran\n", encoding="utf-8")
    passed()
else:
    sys.exit(f"unknown mode {mode}")
'''

POLICY = {
    "schema_version": 1, "stages": {"preflight": {"timeout_seconds": 60}, "collect": {"timeout_seconds": 60},
                                    "pytest": {"timeout_seconds": 90}, "guarded": {"timeout_seconds": 60}},
    "process": {"drain_seconds": 2, "kill_wait_seconds": 10},
    "scenarios": {name: {"phase": 8, "network": [], "detail": "synthetic"}
                  for name in ("m4b-scaling", "edge-low-memory", "optional-engines", "fresh-windows")},
    "later_phase_requirements": [{"id": "native-journeys", "phase": 3, "required": False, "detail": "synthetic"}],
    "inventory": {"minimum_ordinary": 1, "minimum_guarded": {}, "guarded_membership": {}},
    "required_self_tests": [],
    "skip_policy": {platform: [{"id": "synthetic", "pattern": "^synthetic skip reason$", "max": 1}]
                    for platform in ("win32", "darwin", "linux")},
    "focused": {"required_guards": []}, "changed": {"always": [], "no_selection": [], "routes": {}, "full_on": []},
}

# Runs the real verify.main in its own process so the test can kill it outright, as a power cut or a task kill would.
KILLABLE_RUN = r'''
import importlib.util, sys
from pathlib import Path
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("verify_killable", sys.argv[1])
v = importlib.util.module_from_spec(spec)
sys.modules["verify_killable"] = v
spec.loader.exec_module(v)
root = Path(sys.argv[2])
v.REPO_ROOT = root
v.OUTPUTS_ROOT = root / "files" / "dev-work" / "verification-gate" / "outputs"
v.SCRATCH_ROOT = root.parent / "scratch"
v.TESTS_DIR = root / "files" / "tests"
v.POLICY_FILE, v.COVERAGE_FILE = Path(sys.argv[3]), Path(sys.argv[4])
v.check_guarded_specification = lambda membership=None: ("guarded", True, "synthetic")
v.GateRun.preflight_children = lambda self: True
v.GateRun.collect = lambda self, selection: True
fake = sys.argv[5]
v._pytest_command = lambda junit, **kw: [sys.executable, "-u", fake, str(junit), "forever"]
sys.exit(v.main(["--mode", "full"]))
'''


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=ACT test", "-c", "user.email=act-test@example.invalid",
         "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
        cwd=root, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def fake_repo(tmp_path) -> Path:
    """A real git repository with one tracked file, a tracked test and the outputs folder ignored."""
    root = (tmp_path / "repo").resolve()
    (root / "files" / "tests").mkdir(parents=True)
    (root / "tracked.txt").write_text("original\n", encoding="utf-8")
    (root / "files" / "tests" / "test_tracked.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    (root / ".gitignore").write_text("files/dev-work/\n", encoding="utf-8")
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "fixture")
    return root


@pytest.fixture
def fake_pytest(tmp_path) -> Path:
    script = tmp_path / "fake_pytest.py"
    script.write_text(FAKE_PYTEST, encoding="utf-8")
    return script


@pytest.fixture
def policy_files(tmp_path) -> tuple[Path, Path]:
    policy, coverage = tmp_path / "verification.json", tmp_path / "coverage.json"
    policy.write_text(json.dumps(POLICY), encoding="utf-8")
    coverage.write_text(json.dumps({"schema_version": 1, "inventory_reviewed": False, "features": []}), encoding="utf-8")
    return policy, coverage


@pytest.fixture
def verify(monkeypatch, fake_repo, policy_files):
    module = load_gate("act_verify_evidence")
    monkeypatch.setattr(module, "REPO_ROOT", fake_repo)
    monkeypatch.setattr(module, "OUTPUTS_ROOT", fake_repo / "files" / "dev-work" / "verification-gate" / "outputs")
    monkeypatch.setattr(module, "SCRATCH_ROOT", fake_repo.parent / "scratch")
    monkeypatch.setattr(module, "TESTS_DIR", fake_repo / "files" / "tests")
    monkeypatch.setattr(module, "POLICY_FILE", policy_files[0])
    monkeypatch.setattr(module, "COVERAGE_FILE", policy_files[1])
    # The real non-pytest gates read this checkout and are covered by their own test below; here they stand still.
    for function, gate in (("check_requirements", "deps"), ("check_docs", "docs"),
                           ("check_doc_names", "docnames"), ("check_config", "config")):
        monkeypatch.setattr(module, function, lambda gate=gate: (gate, True, f"synthetic {gate} ok"))
    monkeypatch.setattr(module, "check_guarded_specification", lambda membership=None: ("guarded", True, "synthetic"))
    monkeypatch.setattr(module.GateRun, "preflight_children", lambda self: True)
    monkeypatch.setattr(module.GateRun, "collect", lambda self, selection: True)
    monkeypatch.setattr(module.GateRun, "run_guarded",
                        lambda self, selection: self.check("guarded", "PASS", "synthetic guarded ok"))
    return module


def use_child(monkeypatch, verify, script: Path, mode: str, extra: str | None = None) -> None:
    tail = [extra] if extra is not None else []
    monkeypatch.setattr(verify, "_pytest_command",
                        lambda junit, **kw: [sys.executable, "-u", str(script), str(junit), mode, *tail])


def run_dirs(verify) -> list[Path]:
    root = verify.OUTPUTS_ROOT
    return sorted(root.iterdir(), key=lambda path: path.stat().st_mtime_ns) if root.is_dir() else []


def run(verify, *argv: str) -> tuple[int, Path]:
    before = set(run_dirs(verify))
    code = verify.main(list(argv) or ["--mode", "full"])
    created = [path for path in run_dirs(verify) if path not in before]
    assert len(created) == 1, created
    return code, created[0]


def load(directory: Path, name: str) -> dict:
    return json.loads((directory / name).read_text(encoding="utf-8"))


def check(results: dict, name: str) -> dict:
    return next(item for item in results["checks"] if item["name"] == name)


def files_of(directory: Path) -> set[str]:
    return {path.relative_to(directory).as_posix() for path in directory.rglob("*") if path.is_file()}


def wait_for(predicate, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def log_text(directory: Path, name: str) -> str:
    path = directory / name
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


# --------------------------------------------------------------------------- #
# The entry point
# --------------------------------------------------------------------------- #
def test_no_arguments_is_an_invalid_invocation_and_runs_nothing(verify, monkeypatch, capsys):
    """A bare command used to start a 75-minute gate. Now the mode is always said out loud."""
    monkeypatch.setattr(verify, "_pytest_command", lambda junit, **kw: pytest.fail("pytest was started"))
    with pytest.raises(SystemExit) as raised:
        verify.main([])
    assert raised.value.code == 64
    assert "exactly one of --mode and --status" in capsys.readouterr().err
    assert not verify.OUTPUTS_ROOT.exists()


def test_the_script_entry_point_still_exits_with_the_gate_result():
    tree = ast.parse(GATE_PATH.read_text(encoding="utf-8"))
    last = tree.body[-1]
    assert isinstance(last, ast.If) and ast.unparse(last.body[0]) == "sys.exit(main())"


def test_verify_imports_only_the_standard_library_at_module_level():
    """The gate must not import the application or a third-party package to judge them; check_config's and
    check_requirements' lazy imports are the existing exceptions and stay inside those gates. Its own helpers obey the same."""
    for path in [GATE_PATH, *(GATE_DIR / "helpers").glob("*.py")]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names.add(node.module.split(".")[0])
        assert names - {"__future__", "helpers"} <= set(sys.stdlib_module_names), (path.name, names)


def test_a_full_run_runs_exactly_the_six_gates_in_the_established_order(verify, fake_pytest, monkeypatch):
    use_child(monkeypatch, verify, fake_pytest, "pass")
    calls = []
    for function, gate in (("check_requirements", "deps"), ("check_docs", "docs"), ("check_doc_names", "docnames"),
                           ("check_config", "config")):
        monkeypatch.setattr(verify, function, lambda gate=gate: calls.append(gate) or (gate, True, f"{gate} ok"))
    code, target = run(verify)
    assert code == 0
    assert calls == GATE_ORDER[2:]
    names = [item["name"] for item in load(target, "results.json")["checks"]]
    assert [name for name in names if name in GATE_ORDER] == GATE_ORDER


def test_only_the_installation_decides_whether_two_environments_match():
    load_gate("act_verify_evidence_environment")
    from helpers import runstore

    base = {key: f"value of {key}" for key in runstore.COMPARED_ENVIRONMENT}
    assert runstore.compare_environment(base, dict(base)) == []
    for key in runstore.COMPARED_ENVIRONMENT:
        assert runstore.compare_environment(base, {**base, key: "another"}) == [f"environment.{key}"]
    assert runstore.compare_environment({**base, key: None}, {k: v for k, v in base.items() if k != key}) == []
    session = {"error_mode": "0x3", "interactive_desktop": False}
    assert runstore.compare_environment({**base, "error_mode": "0x8003", "interactive_desktop": True}, {**base, **session}) == []
    for recorded, current in ((None, base), (base, None), ({}, base), (base, {})):
        assert runstore.compare_environment(recorded, current) == ["environment unavailable"]
    # A path that differs only by case is the same path exactly where the filesystem says so, and not otherwise.
    shouted = {**base, "executable": base["executable"].upper()}
    expected = [] if os.path.normcase("A") == "a" else ["environment.executable"]
    assert runstore.compare_environment(base, shouted) == expected


def test_the_real_gate_lists_the_static_gates_in_order():
    module = load_gate("act_verify_evidence_static")
    assert [(name, fn) for name, fn in module._static_gates()] == [
        ("deps", module.check_requirements), ("docs", module.check_docs),
        ("docnames", module.check_doc_names), ("config", module.check_config)]


def test_the_evidence_pytest_command_adds_only_reporting_to_the_ordinary_scope(tmp_path):
    module = load_gate("act_verify_evidence_command")
    junit = tmp_path / "pytest.xml"
    command = module._pytest_command(junit, token="run-pytest", basetemp=tmp_path / "b", cache=tmp_path / "c")
    assert command[:5] == [sys.executable, "-u", "-m", "pytest", str(module.TESTS_DIR)]
    assert command[5:5 + len(module._ignore_arguments())] == module._ignore_arguments()
    rest = command[5 + len(module._ignore_arguments()):]
    assert rest == ["-q", "-ra", f"--junitxml={junit}", "-o", "junit_suite_name=run-pytest", f"--basetemp={tmp_path / 'b'}",
                    "-o", f"cache_dir={tmp_path / 'c'}", "-o", f"faulthandler_timeout={module.FAULTHANDLER_SECONDS}"]
    pytest_arguments = command[command.index("pytest") + 1:]
    for narrowing in ("-x", "-k", "-m", "--lf", "--deselect", "--maxfail", "-p"):
        assert narrowing not in pytest_arguments


# --------------------------------------------------------------------------- #
# Malformed arguments and unsafe or colliding paths are refused before anything runs
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("argv", [
    ["--bogus"],
    ["--mode"],
    ["positional"],
    ["--mode", "nonsense"],
    ["--evidence-dir", "files/dev-work/act070-remediation/a"],  # the retired flag is an error, not silently ignored
    ["--mode", "full", "--status", "x"],
    ["--mode", "full", "--test", "files/tests/test_a.py"],
    ["--mode", "full", "--base", "main"],
    ["--mode", "full", "--scenario", "m4b-scaling"],
    ["--mode", "focused"],
    ["--mode", "qualification"],
    ["--mode", "qualification", "--scenario", "made-up"],
    ["--mode", "qualification", "--scenario", "m4b-scaling", "--network", "online-edge"],
    ["--mode", "full", "--preflight-only", "--collect-only"],
    ["--status", "x", "--mode", "full"],
    ["--mode", "full", "--require-current"],
])
def test_malformed_arguments_exit_64_without_running_a_gate(verify, monkeypatch, capsys, argv):
    monkeypatch.setattr(verify, "_pytest_command", lambda junit, **kw: pytest.fail("pytest was started"))
    with pytest.raises(SystemExit) as raised:
        verify.main(argv)
    assert raised.value.code == 64
    assert "usage: verify.py" in capsys.readouterr().err
    assert not verify.OUTPUTS_ROOT.exists()


@pytest.mark.parametrize("raw", ["", " name", "bad name", "CON", "nul.txt", "trailing.", "a:b", ".hidden", "a/b", "..", "a\\b"])
def test_an_unsafe_label_is_refused_before_anything_exists(verify, monkeypatch, capsys, raw):
    monkeypatch.setattr(verify, "_pytest_command", lambda junit, **kw: pytest.fail("pytest was started"))
    with pytest.raises(SystemExit) as raised:
        verify.main(["--mode", "full", "--label", raw] if raw else ["--mode", "full", "--label=x y"])
    assert raised.value.code == 64
    assert "label" in capsys.readouterr().err
    assert not verify.OUTPUTS_ROOT.exists()


@pytest.mark.parametrize("raw", [
    "test_a.py", "files/tests/../secrets.py", "C:\\elsewhere\\test_a.py", "/etc/test_a.py", "files/tests/test_a.py; rm x",
    "files/tests/test_a.py::t && del", "-k nothing", "scripts/test_a.py", "files/dev-work/x/test_a.py", " files/tests/test_a.py",
])
def test_a_test_selector_is_an_identity_never_a_command_fragment(verify, monkeypatch, capsys, raw):
    monkeypatch.setattr(verify, "_pytest_command", lambda junit, **kw: pytest.fail("pytest was started"))
    with pytest.raises(SystemExit) as raised:
        verify.main(["--mode", "focused", f"--test={raw}"])
    assert raised.value.code == 64
    assert not verify.OUTPUTS_ROOT.exists()


def test_each_run_takes_a_new_directory_and_leaves_the_last_byte_identical(verify, fake_pytest, monkeypatch):
    use_child(monkeypatch, verify, fake_pytest, "pass")
    code, first = run(verify)
    assert code == 0
    before = {name: (first / name).read_bytes() for name in files_of(first)}
    use_child(monkeypatch, verify, fake_pytest, "fail")
    code, second = run(verify)
    assert code == 1 and second != first
    assert {name: (first / name).read_bytes() for name in files_of(first)} == before


def test_a_name_already_taken_is_never_reused(verify, fake_pytest, monkeypatch):
    """Two runs in one second with the same random part: the second finds the first's directory and draws another."""
    use_child(monkeypatch, verify, fake_pytest, "pass")
    from helpers import runstore

    code, first = run(verify)
    taken = first.name.rsplit("_", 1)[-1]
    before = {name: (first / name).read_bytes() for name in files_of(first)}
    draws = iter([taken, "beef", "cafe"])
    monkeypatch.setattr(runstore.secrets, "token_hex", lambda n: next(draws) if n == 2 else "0" * (n * 2))
    monkeypatch.setattr(runstore, "datetime", _FrozenClock.at(first.name))
    code, second = run(verify)
    assert second.name.endswith("_beef") and second != first
    assert {name: (first / name).read_bytes() for name in files_of(first)} == before


class _FrozenClock:
    """``datetime.now().astimezone().strftime`` always answering with the stamp of one run's name."""

    def __init__(self, stamp):
        self.stamp = stamp

    @classmethod
    def at(cls, run_name):
        import datetime as real

        stamp = "_".join(run_name.split("_")[:2])

        class Clock(real.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls._frozen if tz is None else real.datetime.now(tz)

        class Frozen:
            def astimezone(self):
                return self

            def strftime(self, _format):
                return stamp

        Clock._frozen = Frozen()
        return Clock


def test_when_no_name_can_be_had_the_run_is_refused_and_nothing_is_touched(verify, fake_pytest, monkeypatch, capsys):
    use_child(monkeypatch, verify, fake_pytest, "pass")
    from helpers import runstore

    code, first = run(verify)
    taken = first.name.rsplit("_", 1)[-1]
    before = sorted(path.name for path in verify.OUTPUTS_ROOT.iterdir())
    monkeypatch.setattr(runstore.secrets, "token_hex", lambda n: taken if n == 2 else "0" * (n * 2))
    monkeypatch.setattr(runstore, "datetime", _FrozenClock.at(first.name))
    assert verify.main(["--mode", "full"]) == 64
    assert "no free run name" in capsys.readouterr().err
    assert sorted(path.name for path in verify.OUTPUTS_ROOT.iterdir()) == before


def _link_directory(target: Path, link: Path) -> None:
    try:
        if sys.platform == "win32":
            import _winapi

            _winapi.CreateJunction(str(target), str(link))
        else:
            os.symlink(target, link, target_is_directory=True)
    except (OSError, AttributeError) as exc:
        pytest.skip(f"cannot create a link here: {exc}")


def test_an_outputs_root_that_is_a_link_or_junction_is_refused_and_its_target_untouched(verify, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(verify, "_pytest_command", lambda junit, **kw: pytest.fail("pytest was started"))
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sentinel.txt").write_text("keep", encoding="utf-8")
    verify.OUTPUTS_ROOT.parent.mkdir(parents=True)
    _link_directory(outside, verify.OUTPUTS_ROOT)
    assert verify.main(["--mode", "full"]) == 64
    assert "link or junction" in capsys.readouterr().err
    assert [path.name for path in outside.iterdir()] == ["sentinel.txt"]


def test_a_link_further_up_the_outputs_path_is_refused_too(verify, tmp_path, capsys):
    outside = tmp_path / "outside"
    outside.mkdir()
    (verify.REPO_ROOT / "files" / "dev-work").mkdir(parents=True)
    _link_directory(outside, verify.REPO_ROOT / "files" / "dev-work" / "verification-gate")
    assert verify.main(["--mode", "full"]) == 64
    assert "link or junction" in capsys.readouterr().err
    assert not any(outside.iterdir())


def test_outputs_removed_between_runs_is_recreated_by_the_next_run(verify, fake_pytest, monkeypatch):
    """The whole subtree is disposable: nothing a run needs may live only in an earlier run."""
    use_child(monkeypatch, verify, fake_pytest, "pass")
    assert run(verify)[0] == 0
    shutil.rmtree(verify.OUTPUTS_ROOT)
    code, target = run(verify)
    assert code == 0 and target.parent == verify.OUTPUTS_ROOT


# --------------------------------------------------------------------------- #
# Completed runs: PASS and FAIL are finalized, and say why
# --------------------------------------------------------------------------- #
def test_a_successful_run_is_finalized_with_every_gate_the_interpreter_and_the_tree(
        verify, fake_pytest, fake_repo, monkeypatch, capsys):
    use_child(monkeypatch, verify, fake_pytest, "pass")
    from helpers import runstore

    code, target = run(verify)
    assert code == 0
    assert files_of(target) == EVIDENCE_FILES  # no marker, no temporary file left behind
    results = load(target, "results.json")
    outcome = runstore.read_run_status(target)
    assert outcome["status"] == "PASS" and outcome["valid"], outcome["problems"]
    assert (results["schema_version"], results["lifecycle"], results["status"], results["exit_code"]) == (
        1, "completed", "PASS", 0)
    assert results["mode"] == "full" and results["release_ready"] is False and results["scope"]["full_acceptance"] is False
    pytest_gate = check(results, "pytest")
    assert pytest_gate["exit_status"] == 0 and pytest_gate["detail"] == "2 passed, 1 skipped in 0.01s"
    assert all(check(results, name)["status"] == "PASS" and check(results, name)["seconds"] >= 0
               for name in ("pytest", "deps", "docs", "docnames", "config"))
    stage = results["stages"][0]
    assert stage["junit_summary"]["valid"] and stage["junit_summary"]["tests"] == 3 and stage["junit_summary"]["skipped"] == 1
    assert results["counts"]["executed"] == 3 and results["counts"]["passed"] == 2 and results["counts"]["skipped"] == 1
    assert results["environment"]["executable"] == sys.executable
    identity = results["identity"]
    assert identity["start"]["available"] and identity["start"]["sha256"] == identity["end"]["sha256"]
    assert identity["start_end_match"] is True and identity["head"] == git(fake_repo, "rev-parse", "HEAD").strip()
    tree_check = check(results, "tree")
    assert tree_check["status"] == "PASS" and tree_check["detail"] == f"unchanged during the run ({identity['end']['sha256']})"
    start = load(target, "start.json")
    assert start["argv"][-1] == "full" and start["identity"] == identity["start"] and start["run_id"] == target.name
    pytest_log = log_text(target, "logs/pytest.log")
    assert "synthetic session starts" in pytest_log and "synthetic stderr line" in pytest_log
    assert "SKIPPED [1] synthetic_test.py:4: synthetic skip reason" in pytest_log
    verify_log = log_text(target, "logs/verify.log")
    assert "check pytest: PASS" in verify_log and "complete: RESULT PASS" in verify_log
    out = capsys.readouterr().out
    assert "  RESULT: PASS" in out and f"  evidence: {target}" in out
    assert "NOT full acceptance" in out and "native-journeys" in out


def test_a_failing_run_keeps_the_whole_traceback_and_still_runs_every_gate(verify, fake_pytest, monkeypatch):
    use_child(monkeypatch, verify, fake_pytest, "fail")
    from helpers import runstore

    code, target = run(verify)
    assert code == 1
    assert runstore.read_run_status(target)["status"] == "FAIL"
    results = load(target, "results.json")
    names = [item["name"] for item in results["checks"]]
    assert [name for name in names if name in GATE_ORDER] == GATE_ORDER
    pytest_gate = check(results, "pytest")
    assert (pytest_gate["status"], pytest_gate["exit_status"]) == ("FAIL", 1)
    assert pytest_gate["detail"] == "exit 1: 1 failed, 2 passed in 0.01s"
    assert results["stages"][0]["junit_summary"]["failures"] == 1
    pytest_log = log_text(target, "logs/pytest.log")
    for line in ("Traceback (most recent call last):", 'File "synthetic_test.py", line 7, in test_boom',
                 "E   AssertionError: synthetic boom", "FAILED synthetic_test.py::test_boom"):
        assert line in pytest_log
    assert "pytest" in (target / "failures.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("mode, code, status, exit_status, detail", [
    ("empty", 3, "NOT RUN", 5, "no tests collected (an empty gate is not valid)"),
    ("collection-error", 1, "FAIL", 2, "exit 2: 1 error in 0.01s"),
])
def test_empty_and_errored_collections_are_not_passes(verify, fake_pytest, monkeypatch, mode, code, status, exit_status, detail):
    use_child(monkeypatch, verify, fake_pytest, mode)
    got, target = run(verify)
    assert got == code
    results = load(target, "results.json")
    assert results["status"] == status
    gate = check(results, "pytest")
    assert (gate["exit_status"], gate["detail"]) == (exit_status, detail)


@pytest.mark.parametrize("mode, code, status, detail", [
    ("exit0-no-junit", 3, "NOT RUN", "exit 0 but the JUnit report is missing"),
    ("exit0-truncated-junit", 3, "NOT RUN", "exit 0 but the JUnit report is unreadable or truncated"),
    ("exit0-zero-tests", 3, "NOT RUN", "exit 0 but the JUnit report records no tests"),
    ("exit0-junit-failures", 1, "FAIL", "exit 0 but the JUnit report records 1 failure(s) and 0 error(s)"),
    ("exit0-no-record", 3, "NOT RUN", "exit 0 but the session record is missing"),
    ("exit0-unfinished-record", 3, "NOT RUN", "exit 0 but the session record is the session never reported its finish"),
    ("exit0-masked-session", 1, "FAIL", "exit 0 masks the session's own exit status 1"),
    ("exit0-stale-report", 1, "FAIL", "exit 0 but the JUnit report does not hold together: the report belongs to"),
    ("exit0-count-mismatch", 1, "FAIL", "exit 0 but the JUnit report does not hold together: it declares 3 tests but lists 2"),
    ("exit0-collected-not-run", 1, "FAIL", "collected and executed tests differ"),
])
def test_exit_zero_without_records_that_agree_is_not_a_pass(verify, fake_pytest, monkeypatch, mode, code, status, detail):
    use_child(monkeypatch, verify, fake_pytest, mode)
    got, target = run(verify)
    assert got == code
    results = load(target, "results.json")
    assert results["status"] == status
    gate = check(results, "pytest")
    assert gate["exit_status"] == 0 and gate["status"] == status
    assert gate["detail"].startswith(detail), gate["detail"]


def test_a_failing_non_pytest_gate_is_recorded_as_such(verify, fake_pytest, monkeypatch):
    use_child(monkeypatch, verify, fake_pytest, "pass")
    monkeypatch.setattr(verify, "check_requirements", lambda: ("deps", False, "'pkg' (bare/unpinned package)"))
    code, target = run(verify)
    assert code == 1
    results = load(target, "results.json")
    deps = check(results, "deps")
    assert (deps["status"], deps["exit_status"], deps["detail"]) == ("FAIL", None, "'pkg' (bare/unpinned package)")
    assert check(results, "pytest")["status"] == "PASS" and results["status"] == "FAIL"


def test_the_real_non_pytest_gates_are_recorded_exactly_as_they_report(monkeypatch, fake_pytest, policy_files, tmp_path):
    """No stand-ins for deps/docs/docnames/config: the run records the checkout's real answers unchanged.
    The guarded gate runs suites, like pytest, so it is the one stand-in besides pytest (test_verify_guarded.py)."""
    module = load_gate("act_verify_evidence_real")
    monkeypatch.setattr(module, "OUTPUTS_ROOT", tmp_path / "outputs")
    monkeypatch.setattr(module, "SCRATCH_ROOT", tmp_path / "vg")
    # The gates read this checkout; the run's own files go to tmp_path, so the link checks start there.
    reserve_run = module.runstore.reserve_run_dir
    monkeypatch.setattr(module.runstore, "reserve_run_dir", lambda root, _base, mode: reserve_run(root, tmp_path, mode))
    monkeypatch.setattr(module, "POLICY_FILE", policy_files[0])
    monkeypatch.setattr(module, "COVERAGE_FILE", policy_files[1])
    use_child(monkeypatch, module, fake_pytest, "pass")
    monkeypatch.setattr(module, "check_guarded_specification", lambda membership=None: ("guarded", True, "synthetic"))
    monkeypatch.setattr(module.GateRun, "preflight_children", lambda self: True)
    monkeypatch.setattr(module.GateRun, "collect", lambda self, selection: True)
    monkeypatch.setattr(module.GateRun, "run_guarded", lambda self, selection: self.check("guarded", "PASS", "synthetic"))
    module.main(["--mode", "full"])
    target = next((tmp_path / "outputs").iterdir())
    recorded = {item["name"]: item for item in load(target, "results.json")["checks"]}
    for function, name in (("check_requirements", "deps"), ("check_docs", "docs"),
                           ("check_doc_names", "docnames"), ("check_config", "config")):
        _, ok, detail = getattr(module, function)()
        assert (recorded[name]["status"] == "PASS", recorded[name]["detail"], recorded[name]["exit_status"]) == (ok, detail, None)


def test_a_tree_that_changes_during_the_run_cannot_pass(verify, fake_pytest, fake_repo, monkeypatch):
    use_child(monkeypatch, verify, fake_pytest, "touch", str(fake_repo / "tracked.txt"))
    code, target = run(verify)
    assert code == 1
    results = load(target, "results.json")
    assert check(results, "pytest")["status"] == "PASS" and results["status"] == "FAIL"
    tree = check(results, "tree")
    assert tree["status"] == "FAIL" and "changed during the run" in tree["detail"]
    assert results["identity"]["start_end_match"] is False


def test_an_unavailable_fingerprint_blocks_the_run_before_any_test(verify, fake_pytest, monkeypatch, tmp_path):
    """Nothing could be said about what was tested, so an hour is not spent testing it."""
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "no-such-git-dir"))  # every git call now fails, as without a checkout
    monkeypatch.setattr(verify, "_pytest_command", lambda junit, **kw: pytest.fail("pytest was started"))
    code, target = run(verify)
    assert code == 2
    results = load(target, "results.json")
    assert results["status"] == "BLOCKED"
    gate = check(results, "source-identity")
    assert gate["status"] == "BLOCKED" and gate["detail"].startswith("fingerprint unavailable")


# --------------------------------------------------------------------------- #
# Runs that do not finish are INCOMPLETE, never PASS
# --------------------------------------------------------------------------- #
def test_output_is_on_disk_while_pytest_is_still_running(verify, fake_pytest, monkeypatch, tmp_path):
    go = tmp_path / "go"
    use_child(monkeypatch, verify, fake_pytest, "wait", str(go))
    from helpers import runstore

    outcome = {}
    worker = threading.Thread(target=lambda: outcome.setdefault("code", verify.main(["--mode", "full"])))
    worker.start()
    try:
        assert wait_for(lambda: bool(run_dirs(verify))), "the run never reserved a directory"
        target = run_dirs(verify)[0]
        assert wait_for(lambda: "..partial-progress" in log_text(target, "logs/pytest.log")), "output was not streamed"
        assert "first streamed line" in log_text(target, "logs/pytest.log")
        assert "pytest child started" in log_text(target, "logs/verify.log")
        assert (target / "INCOMPLETE.json").is_file() and not (target / "results.json").exists()
        marker = load(target, "INCOMPLETE.json")
        assert marker["current_gate"] == "pytest" and marker["lifecycle"] == "running"
        assert runstore.read_run_status(target)["status"] == "INCOMPLETE"
    finally:
        go.write_text("go", encoding="utf-8")
        worker.join(timeout=60)
    assert outcome["code"] == 0
    assert runstore.read_run_status(target)["status"] == "PASS"


def test_an_interrupted_run_stops_its_child_and_is_recorded_as_incomplete(verify, fake_pytest, monkeypatch, capsys):
    use_child(monkeypatch, verify, fake_pytest, "forever")
    from helpers import runstore

    def interrupt_once_streaming():
        def streaming():
            dirs = run_dirs(verify)
            return bool(dirs) and "still running" in log_text(dirs[0], "logs/pytest.log")
        if wait_for(streaming):
            _thread.interrupt_main()

    trigger = threading.Thread(target=interrupt_once_streaming)
    trigger.start()
    try:
        code = verify.main(["--mode", "full"])
    finally:
        trigger.join(timeout=60)
    target = run_dirs(verify)[0]
    assert code == 130
    assert runstore.read_run_status(target)["status"] == "INCOMPLETE"
    assert not (target / "results.json").exists()
    marker = load(target, "INCOMPLETE.json")
    assert (marker["status"], marker["reason"], marker["current_gate"], marker["lifecycle"]) == (
        "INCOMPLETE", "interrupted (KeyboardInterrupt)", "pytest", "interrupted")
    verify_log = log_text(target, "logs/verify.log")
    assert "INTERRUPTED (KeyboardInterrupt) during gate pytest" in verify_log
    assert "still running" in log_text(target, "logs/pytest.log")  # partial diagnostics are kept
    assert "INCOMPLETE" in capsys.readouterr().err


def test_an_unexpected_error_keeps_its_traceback_and_leaves_the_run_incomplete(verify, fake_pytest, monkeypatch):
    use_child(monkeypatch, verify, fake_pytest, "pass")
    from helpers import runstore

    def broken_gate():
        raise RuntimeError("synthetic gate crash")

    monkeypatch.setattr(verify, "check_docs", broken_gate)
    with pytest.raises(RuntimeError, match="synthetic gate crash"):
        verify.main(["--mode", "full"])
    target = run_dirs(verify)[0]
    assert runstore.read_run_status(target)["status"] == "INCOMPLETE"
    marker = load(target, "INCOMPLETE.json")
    assert marker["reason"] == "error: RuntimeError: synthetic gate crash" and marker["current_gate"] == "docs"
    verify_log = log_text(target, "logs/verify.log")
    assert "Traceback (most recent call last):" in verify_log and "synthetic gate crash" in verify_log
    assert "check pytest: PASS" in verify_log


def test_a_run_killed_outright_reads_incomplete(fake_repo, fake_pytest, policy_files, tmp_path):
    wrapper = tmp_path / "killable_run.py"
    wrapper.write_text(KILLABLE_RUN, encoding="utf-8")
    root = fake_repo / "files" / "dev-work" / "verification-gate" / "outputs"
    proc = subprocess.Popen([sys.executable, str(wrapper), str(GATE_PATH), str(fake_repo), str(policy_files[0]),
                             str(policy_files[1]), str(fake_pytest)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    child_pid = None
    target = None
    try:
        def streaming():
            nonlocal target
            found = list(root.iterdir()) if root.is_dir() else []
            target = found[0] if found else None
            return target is not None and "still running" in log_text(target, "logs/pytest.log")
        assert wait_for(streaming), "the run never started"
        line = next(l for l in log_text(target, "logs/verify.log").splitlines() if "pytest child started, pid" in l)
        child_pid = int(line.split(" pid ", 1)[1].split(",", 1)[0])
    finally:
        proc.kill()
        proc.wait(timeout=30)
        if child_pid is not None and sys.platform != "win32":  # on Windows the job went with the gate
            try:
                os.kill(child_pid, signal.SIGTERM)
            except OSError:
                pass
    assert not (target / "results.json").exists()
    marker = load(target, "INCOMPLETE.json")
    assert marker["reason"] == "started; no normal completion has been recorded"
    assert marker["current_gate"] == "pytest"
    from helpers import runstore

    assert runstore.read_run_status(target)["status"] == "INCOMPLETE"


@pytest.mark.parametrize("files, expected", [
    ({}, "INCOMPLETE"),
    ({"INCOMPLETE.json": "{}"}, "INCOMPLETE"),
    ({"INCOMPLETE.json": "{}", "result.json": '{"status": "COMPLETE", "result": "PASS"}'}, "INCOMPLETE"),
    ({"result.json": '{"status": "COMPLETE", "result": "PA'}, "INVALID"),
    ({"result.json": '{"status": "STARTED", "result": "PASS"}'}, "INVALID"),
    ({"result.json": '{"status": "COMPLETE", "result": "MAYBE"}'}, "INVALID"),
    ({"result.json": '["PASS"]'}, "INVALID"),
    ({"result.json": '{"status": "COMPLETE", "result": "FAIL"}'}, "FAIL"),
    ({"result.json": '{"status": "COMPLETE", "result": "PASS"}'}, "PASS"),
])
def test_only_a_finalized_result_without_a_marker_can_read_pass(tmp_path, files, expected):
    """Earlier runs stay where they are, under their old schema. This reader is the only thing that still understands them."""
    load_gate("act_verify_evidence_legacy")
    from helpers import runstore

    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    assert runstore.read_legacy_evidence_status(tmp_path) == expected


# --------------------------------------------------------------------------- #
# The tested-tree fingerprint
# --------------------------------------------------------------------------- #
def test_the_fingerprint_tracks_working_tree_bytes_and_new_test_files_only(fake_repo):
    module = load_gate("act_verify_evidence_fingerprint")
    first = module.tree_fingerprint(fake_repo)
    assert first["available"] and module.tree_fingerprint(fake_repo)["sha256"] == first["sha256"]
    assert first["tracked_files"] == 3 and first["untracked_in_scope"] == []

    (fake_repo / "files" / "run-temp").mkdir(parents=True)
    (fake_repo / "files" / "run-temp" / "scratch.txt").write_text("scratch", encoding="utf-8")
    (fake_repo / "notes.txt").write_text("local note", encoding="utf-8")
    assert module.tree_fingerprint(fake_repo)["sha256"] == first["sha256"], "out-of-scope untracked files counted"

    (fake_repo / "files" / "tests" / "test_new.py").write_text("def test_new():\n    pass\n", encoding="utf-8")
    with_new_test = module.tree_fingerprint(fake_repo)
    assert with_new_test["sha256"] != first["sha256"]
    assert with_new_test["untracked_in_scope"] == ["files/tests/test_new.py"]

    (fake_repo / "tracked.txt").write_text("edited\n", encoding="utf-8")
    edited = module.tree_fingerprint(fake_repo)
    assert edited["sha256"] not in (first["sha256"], with_new_test["sha256"])
    assert any(line.endswith("tracked.txt") for line in edited["dirty_tracked"])

    (fake_repo / "tracked.txt").unlink()
    deleted = module.tree_fingerprint(fake_repo)
    assert deleted["deleted_tracked"] == ["tracked.txt"] and deleted["sha256"] != edited["sha256"]


def test_the_fingerprint_reports_when_it_is_unavailable(monkeypatch, tmp_path):
    module = load_gate("act_verify_evidence_unavailable")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))  # never discover an enclosing checkout
    fingerprint = module.tree_fingerprint(tmp_path)
    assert fingerprint["available"] is False and fingerprint["error"]


def test_an_untracked_gate_helper_changes_the_policy_digest_even_below_an_ignored_parent(tmp_path):
    """New canonical files under the once wholly-ignored files/dev-work must be inputs, not invisible local files."""
    module = load_gate("act_verify_evidence_helper")
    root = (tmp_path / "repo").resolve()
    (root / "files" / "dev-work" / "verification-gate").mkdir(parents=True)
    (root / ".gitignore").write_text(
        "files/dev-work/*\n!files/dev-work/verification-gate/\nfiles/dev-work/verification-gate/outputs/\n", encoding="utf-8")
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "fixture")
    first = module.tree_fingerprint(root)
    (root / "files" / "dev-work" / "verification-gate" / "new_helper.py").write_text("x = 1\n", encoding="utf-8")
    second = module.tree_fingerprint(root)
    assert second["policy_digest"] != first["policy_digest"] and second["test_digest"] == first["test_digest"]
    outputs = root / "files" / "dev-work" / "verification-gate" / "outputs" / "some-run"
    outputs.mkdir(parents=True)
    (outputs / "results.json").write_text("{}", encoding="utf-8")
    assert module.tree_fingerprint(root)["sha256"] == second["sha256"], "a run's own output entered the fingerprint"
    (root / "files" / "dev-work" / "other.txt").write_text("ignored", encoding="utf-8")
    assert module.tree_fingerprint(root)["sha256"] == second["sha256"]


def test_each_class_of_file_moves_only_its_own_digest(tmp_path):
    """Documentation is separate on purpose, so a docs-only commit can truthfully carry code evidence forward (plan §13.3)."""
    module = load_gate("act_verify_evidence_classes")
    root = (tmp_path / "repo").resolve()
    files = {"scripts/app.py": "source_digest", "files/tests/test_x.py": "test_digest", "pytest.ini": "policy_digest",
             "scripts/requirements.txt": "locks_digest", "md-instructions/Handoff.md": "docs_digest", "stray.txt": "other_digest"}
    for relative in files:
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_text("one\n", encoding="utf-8")
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "fixture")
    keys = set(files.values())
    before = module.tree_fingerprint(root)
    for relative, key in files.items():
        (root / relative).write_text("two\n", encoding="utf-8")
        after = module.tree_fingerprint(root)
        assert {k for k in keys if before[k] != after[k]} == {key}, relative
        (root / relative).write_text("one\n", encoding="utf-8")
