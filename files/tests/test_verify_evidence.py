"""v0.7.0 P00C: ``scripts/verify.py --evidence-dir`` leaves durable, honest evidence of a gate run.

The ordinary gate captures pytest's output and keeps only its last line, so a 20-minute run that fails or is cut short
leaves nothing to inspect (plan §6, "Durable full gates"). Evidence mode streams the child's output to disk as it
arrives, records every gate, the interpreter and the tested tree, and finalizes ``result.json`` only after normal
completion. These tests hold it to that from both sides: the ordinary no-argument gate is unchanged, and every way a run
can end — pass, failure, empty collection, a bad JUnit report, a moved tree, an interruption, an error, a kill — reads
back as what it was. Never PASS by omission.

pytest itself is never run here. A small synthetic child stands in for it through ``verify._pytest_command`` and
behaves like pytest at the boundary verify.py sees: merged stdout/stderr, an exit code and a JUnit file. The tree
fingerprint runs real ``git`` against a throwaway repository, so nothing touches this checkout's evidence folder.
"""

from __future__ import annotations

import ast
import importlib.util
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

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
VERIFY_PATH = REPO_ROOT / "scripts" / "verify.py"
GATE_ORDER = ["pytest", "deps", "docs", "docnames", "config"]
EVIDENCE_FILES = {"verify.log", "pytest.log", "pytest.xml", "start.json", "result.json"}

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="the tree fingerprint needs git")

# Stands in for pytest: argv is <junit path> <mode> [extra]. Output goes to both streams, as pytest's does.
FAKE_PYTEST = r'''
import pathlib, sys, time

junit, mode = pathlib.Path(sys.argv[1]), sys.argv[2]
extra = sys.argv[3] if len(sys.argv) > 3 else None


def report(tests, failures=0, errors=0, skipped=0):
    junit.write_text(
        '<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" '
        f'tests="{tests}" failures="{failures}" errors="{errors}" skipped="{skipped}"></testsuite></testsuites>',
        encoding="utf-8")


def passed():
    report(3, skipped=1)
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
    print("1 failed, 2 passed in 0.01s")
    sys.exit(1)
elif mode == "empty":
    report(0)
    print("no tests ran in 0.01s")
    sys.exit(5)
elif mode == "collection-error":
    print("ERROR collecting synthetic_test.py")
    report(0, errors=1)
    print("1 error in 0.01s")
    sys.exit(2)
elif mode == "exit0-no-junit":
    print("3 passed in 0.01s")
    sys.exit(0)
elif mode == "exit0-truncated-junit":
    junit.write_text('<?xml version="1.0"?><testsuites><testsuite name="pytest" tests="3"', encoding="utf-8")
    print("3 passed in 0.01s")
    sys.exit(0)
elif mode == "exit0-zero-tests":
    report(0)
    print("no tests ran in 0.01s")
    sys.exit(0)
elif mode == "exit0-junit-failures":
    report(3, failures=1)
    print("3 passed in 0.01s")
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

# Runs the real verify.main in its own process so the test can kill it outright, as a power cut or a task kill would.
KILLABLE_RUN = r'''
import importlib.util, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("verify_killable", sys.argv[1])
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)
v.REPO_ROOT = Path(sys.argv[2])
v.EVIDENCE_ROOT = Path(sys.argv[3])
v.TESTS_DIR = v.REPO_ROOT / "files" / "tests"
fake = sys.argv[5]
v._pytest_command = lambda junit: [sys.executable, "-u", fake, str(junit), "forever"]
sys.exit(v.main(["--evidence-dir", sys.argv[4]]))
'''


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=ACT test", "-c", "user.email=act-test@example.invalid",
         "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
        cwd=root, check=True, capture_output=True, text=True).stdout


def load_verify():
    spec = importlib.util.spec_from_file_location("act_verify_evidence", VERIFY_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fake_repo(tmp_path) -> Path:
    """A real git repository with one tracked file, a tracked test and the evidence folder ignored."""
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
def verify(monkeypatch, fake_repo):
    module = load_verify()
    monkeypatch.setattr(module, "REPO_ROOT", fake_repo)
    monkeypatch.setattr(module, "EVIDENCE_ROOT", fake_repo / "files" / "dev-work" / "act070-remediation")
    monkeypatch.setattr(module, "TESTS_DIR", fake_repo / "files" / "tests")
    # The real non-pytest gates read this checkout and are covered by their own test below; here they stand still.
    for function, gate in (("check_requirements", "deps"), ("check_docs", "docs"),
                           ("check_doc_names", "docnames"), ("check_config", "config")):
        monkeypatch.setattr(module, function, lambda gate=gate: (gate, True, f"synthetic {gate} ok"))
    return module


def use_child(monkeypatch, verify, script: Path, mode: str, extra: str | None = None) -> None:
    tail = [extra] if extra is not None else []
    monkeypatch.setattr(verify, "_pytest_command",
                        lambda junit: [sys.executable, "-u", str(script), str(junit), mode, *tail])


def evidence_dir(verify, name: str = "P00C-test-run") -> Path:
    return verify.EVIDENCE_ROOT / "verify" / name


def run(verify, name: str = "P00C-test-run") -> tuple[int, Path]:
    target = evidence_dir(verify, name)
    return verify.main(["--evidence-dir", str(target.relative_to(verify.REPO_ROOT))]), target


def load(directory: Path, name: str) -> dict:
    return json.loads((directory / name).read_text(encoding="utf-8"))


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
# The ordinary gate is unchanged
# --------------------------------------------------------------------------- #
def test_the_ordinary_gate_runs_the_same_pytest_command_and_keeps_its_summary(monkeypatch):
    module = load_verify()
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"], seen["kwargs"] = cmd, kwargs
        return subprocess.CompletedProcess(cmd, 0, stdout="....\n5 passed in 1.00s\n", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    assert module.check_pytest() == ("pytest", True, "5 passed in 1.00s")
    assert seen["cmd"] == [sys.executable, "-m", "pytest", str(module.TESTS_DIR), "-q"]
    assert seen["kwargs"] == {"cwd": str(module.REPO_ROOT), "capture_output": True, "text": True}


@pytest.mark.parametrize("code, expected", [
    (5, "no tests collected (an empty gate is not valid)"),
    (1, "exit 1: 1 failed in 1.00s"),
    (2, "exit 2: 1 failed in 1.00s"),
])
def test_the_ordinary_gate_still_fails_empty_and_failing_runs(monkeypatch, code, expected):
    module = load_verify()
    monkeypatch.setattr(module.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, code, stdout="F\n1 failed in 1.00s\n", stderr=""))
    assert module.check_pytest() == ("pytest", False, expected)


def test_no_arguments_runs_the_five_gates_in_order_prints_the_same_report_and_writes_no_evidence(
        monkeypatch, capsys, tmp_path):
    module = load_verify()
    monkeypatch.setattr(module, "EVIDENCE_ROOT", tmp_path / "evidence-root")
    calls = []
    for function, gate, ok in (("check_pytest", "pytest", True), ("check_requirements", "deps", True),
                               ("check_docs", "docs", False), ("check_doc_names", "docnames", True),
                               ("check_config", "config", True)):
        monkeypatch.setattr(module, function,
                            lambda gate=gate, ok=ok: calls.append(gate) or (gate, ok, f"{gate} detail"))
    assert module.main([]) == 1
    assert calls == GATE_ORDER
    assert capsys.readouterr().out == (
        "=" * 60 + "\nverify.py — Audiobook Creation Tool gate\n" + "=" * 60 + "\n"
        "  [PASS] pytest   - pytest detail\n  [PASS] deps     - deps detail\n  [FAIL] docs     - docs detail\n"
        "  [PASS] docnames - docnames detail\n  [PASS] config   - config detail\n"
        + "-" * 60 + "\n  RESULT: FAIL\n" + "=" * 60 + "\n")
    assert not (tmp_path / "evidence-root").exists()


def test_the_script_entry_point_still_exits_with_the_gate_result():
    tree = ast.parse(VERIFY_PATH.read_text(encoding="utf-8"))
    last = tree.body[-1]
    assert isinstance(last, ast.If) and ast.unparse(last.body[0]) == "sys.exit(main())"


def test_verify_imports_only_the_standard_library_at_module_level():
    """Evidence mode must not import the application or a third-party package; check_config's lazy import is the
    one existing exception and stays inside that gate."""
    tree = ast.parse(VERIFY_PATH.read_text(encoding="utf-8"))
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            names.add(node.module.split(".")[0])
    assert names - {"__future__"} <= set(sys.stdlib_module_names), names


def test_evidence_mode_runs_exactly_the_ordinary_gates_in_the_ordinary_order():
    module = load_verify()
    gates = module._evidence_gates()
    assert [name for name, _ in gates] == GATE_ORDER
    assert [fn for _, fn in gates[1:]] == [module.check_requirements, module.check_docs,
                                           module.check_doc_names, module.check_config]


def test_the_evidence_pytest_command_adds_only_reporting_to_the_ordinary_scope(tmp_path):
    module = load_verify()
    junit = tmp_path / "pytest.xml"
    command = module._pytest_command(junit)
    assert command == [sys.executable, "-u", "-m", "pytest", str(module.TESTS_DIR), "-q", "-ra", f"--junitxml={junit}"]
    pytest_arguments = command[command.index("pytest") + 1:]
    for narrowing in ("-x", "-k", "-m", "--lf", "--deselect", "--maxfail", "-p"):
        assert narrowing not in pytest_arguments


# --------------------------------------------------------------------------- #
# Malformed arguments and unsafe or colliding paths are refused before anything runs
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("argv", [
    ["--bogus"],
    ["--evidence-dir"],
    ["positional"],
    ["--evidence-dir", "files/dev-work/act070-remediation/a", "--evidence-dir", "files/dev-work/act070-remediation/b"],
])
def test_malformed_arguments_exit_two_without_running_a_gate(verify, monkeypatch, capsys, argv):
    monkeypatch.setattr(verify, "check_pytest", lambda: pytest.fail("a gate ran"))
    monkeypatch.setattr(verify, "_pytest_command", lambda junit: pytest.fail("pytest was started"))
    with pytest.raises(SystemExit) as raised:
        verify.main(argv)
    assert raised.value.code == 2
    assert "usage: verify.py" in capsys.readouterr().err
    assert not verify.EVIDENCE_ROOT.exists()


@pytest.mark.parametrize("raw", [
    "",
    " files/dev-work/act070-remediation/run",
    "files/dev-work/other/run",
    "files/dev-work/act070-remediation",
    "files/dev-work/act070-remediation/../escape",
    "files/dev-work/act070-remediation/run/../../escape",
    "files/dev-work/act070-remediation/bad name",
    "files/dev-work/act070-remediation/CON",
    "files/dev-work/act070-remediation/nul.txt",
    "files/dev-work/act070-remediation/trailing.",
    "files/dev-work/act070-remediation/a:b",
    "files/dev-work/act070-remediation/.hidden",
    "scripts/run",
])
def test_unsafe_and_out_of_scope_paths_are_refused(verify, monkeypatch, capsys, raw):
    monkeypatch.setattr(verify, "_pytest_command", lambda junit: pytest.fail("pytest was started"))
    assert verify.main(["--evidence-dir", raw]) == 2
    assert "refusing --evidence-dir" in capsys.readouterr().err
    assert not verify.EVIDENCE_ROOT.exists()


def test_an_absolute_path_outside_the_evidence_root_is_refused(verify, tmp_path):
    with pytest.raises(verify.EvidenceError):
        verify.resolve_evidence_dir(str(tmp_path / "elsewhere"))
    assert not (tmp_path / "elsewhere").exists()


def test_relative_paths_are_taken_from_the_repository_root_not_the_current_directory(verify, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    target = verify.resolve_evidence_dir("files/dev-work/act070-remediation/verify/run-1")
    assert target == verify.EVIDENCE_ROOT / "verify" / "run-1"


@pytest.mark.parametrize("kind", ["directory", "file"])
def test_an_existing_path_is_never_reused_or_overwritten(verify, fake_pytest, monkeypatch, capsys, kind):
    use_child(monkeypatch, verify, fake_pytest, "pass")
    target = evidence_dir(verify, "already-here")
    target.parent.mkdir(parents=True)
    if kind == "directory":
        target.mkdir()
        (target / "result.json").write_text('{"keep": "me"}', encoding="utf-8")
    else:
        target.write_text("keep me", encoding="utf-8")
    before = sorted(p.name for p in target.parent.rglob("*"))
    assert run(verify, "already-here")[0] == 2
    assert "already exists" in capsys.readouterr().err
    assert sorted(p.name for p in target.parent.rglob("*")) == before
    if kind == "directory":
        assert (target / "result.json").read_text(encoding="utf-8") == '{"keep": "me"}'
    else:
        assert target.read_text(encoding="utf-8") == "keep me"


def test_a_second_run_into_the_same_directory_leaves_the_first_byte_identical(verify, fake_pytest, monkeypatch):
    use_child(monkeypatch, verify, fake_pytest, "pass")
    code, target = run(verify)
    assert code == 0
    first = {p.name: p.read_bytes() for p in target.iterdir()}
    use_child(monkeypatch, verify, fake_pytest, "fail")
    assert run(verify)[0] == 2
    assert {p.name: p.read_bytes() for p in target.iterdir()} == first


def test_a_case_variant_of_an_existing_directory_is_refused_where_names_are_case_insensitive(verify):
    existing = evidence_dir(verify, "Run-A")
    existing.mkdir(parents=True)
    if not (existing.parent / "run-a").exists():
        pytest.skip("case-sensitive filesystem: 'run-a' is a different, absent name")
    with pytest.raises(verify.EvidenceError, match="already exists"):
        verify.resolve_evidence_dir(str(evidence_dir(verify, "run-a")))


def test_a_link_or_junction_inside_the_evidence_root_is_refused(verify, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    verify.EVIDENCE_ROOT.mkdir(parents=True)
    link = verify.EVIDENCE_ROOT / "redirect"
    try:
        if sys.platform == "win32":
            import _winapi
            _winapi.CreateJunction(str(outside), str(link))
        else:
            os.symlink(outside, link, target_is_directory=True)
    except (OSError, AttributeError) as exc:
        pytest.skip(f"cannot create a link here: {exc}")
    with pytest.raises(verify.EvidenceError, match="link or junction"):
        verify.resolve_evidence_dir(str(link / "run"))
    assert not any(outside.iterdir())


# --------------------------------------------------------------------------- #
# Completed runs: PASS and FAIL are finalized, and say why
# --------------------------------------------------------------------------- #
def test_a_successful_run_is_finalized_with_every_gate_the_interpreter_and_the_tree(
        verify, fake_pytest, fake_repo, monkeypatch, capsys):
    use_child(monkeypatch, verify, fake_pytest, "pass")
    code, target = run(verify)
    assert code == 0
    assert {p.name for p in target.iterdir()} == EVIDENCE_FILES  # no marker, no temporary file left behind
    assert verify.read_evidence_status(target) == "PASS"
    result = load(target, "result.json")
    assert (result["status"], result["result"], result["exit_code"], result["gates_result"]) == (
        "COMPLETE", "PASS", 0, "PASS")
    assert [g["name"] for g in result["gates"]] == GATE_ORDER
    assert result["gates"][0]["exit_status"] == 0
    assert result["gates"][0]["detail"] == "2 passed, 1 skipped in 0.01s"
    assert all(g["exit_status"] is None for g in result["gates"][1:])
    assert all(g["elapsed_seconds"] >= 0 and g["status"] == "PASS" for g in result["gates"])
    assert result["junit"] == {"valid": True, "tests": 3, "failures": 0, "errors": 0, "skipped": 1}
    assert result["interpreter"]["executable"] == sys.executable
    fingerprint = result["fingerprint"]
    assert fingerprint["start"]["available"] and fingerprint["start"]["sha256"] == fingerprint["end"]["sha256"]
    assert fingerprint["start"]["head"] == git(fake_repo, "rev-parse", "HEAD").strip()
    assert result["evidence_checks"] == [{"name": "tree", "status": "PASS",
                                          "detail": f"unchanged during the run ({fingerprint['end']['sha256']})"}]
    start = load(target, "start.json")
    assert start["argv"][-1] == str(target.relative_to(fake_repo))
    assert start["fingerprint"] == fingerprint["start"]
    pytest_log = log_text(target, "pytest.log")
    assert "synthetic session starts" in pytest_log and "synthetic stderr line" in pytest_log
    assert "SKIPPED [1] synthetic_test.py:4: synthetic skip reason" in pytest_log
    verify_log = log_text(target, "verify.log")
    assert "gate pytest: PASS" in verify_log and "complete: RESULT PASS" in verify_log
    out = capsys.readouterr().out
    assert "  RESULT: PASS" in out and f"  evidence: {target}" in out


def test_a_failing_run_keeps_the_whole_traceback_and_still_runs_every_gate(verify, fake_pytest, monkeypatch):
    use_child(monkeypatch, verify, fake_pytest, "fail")
    code, target = run(verify)
    assert code == 1
    assert verify.read_evidence_status(target) == "FAIL"
    result = load(target, "result.json")
    assert [g["name"] for g in result["gates"]] == GATE_ORDER
    pytest_gate = result["gates"][0]
    assert (pytest_gate["status"], pytest_gate["exit_status"]) == ("FAIL", 1)
    assert pytest_gate["detail"] == "exit 1: 1 failed, 2 passed in 0.01s"
    assert result["junit"]["failures"] == 1
    pytest_log = log_text(target, "pytest.log")
    for line in ("Traceback (most recent call last):", 'File "synthetic_test.py", line 7, in test_boom',
                 "E   AssertionError: synthetic boom", "FAILED synthetic_test.py::test_boom"):
        assert line in pytest_log


@pytest.mark.parametrize("mode, exit_status, detail", [
    ("empty", 5, "no tests collected (an empty gate is not valid)"),
    ("collection-error", 2, "exit 2: 1 error in 0.01s"),
])
def test_empty_and_errored_collections_fail_with_their_real_exit(verify, fake_pytest, monkeypatch,
                                                                 mode, exit_status, detail):
    use_child(monkeypatch, verify, fake_pytest, mode)
    code, target = run(verify)
    assert code == 1
    result = load(target, "result.json")
    assert result["result"] == "FAIL"
    assert (result["gates"][0]["exit_status"], result["gates"][0]["detail"]) == (exit_status, detail)


@pytest.mark.parametrize("mode, detail", [
    ("exit0-no-junit", "exit 0 but the JUnit report is missing"),
    ("exit0-truncated-junit", "exit 0 but the JUnit report is unreadable or truncated"),
    ("exit0-zero-tests", "exit 0 but the JUnit report records no tests"),
    ("exit0-junit-failures", "exit 0 but the JUnit report records 1 failure(s) and 0 error(s)"),
])
def test_exit_zero_without_a_trustworthy_junit_report_is_not_a_pass(verify, fake_pytest, monkeypatch, mode, detail):
    use_child(monkeypatch, verify, fake_pytest, mode)
    code, target = run(verify)
    assert code == 1
    assert verify.read_evidence_status(target) == "FAIL"
    gate = load(target, "result.json")["gates"][0]
    assert gate["exit_status"] == 0 and gate["status"] == "FAIL"
    assert gate["detail"].startswith(detail)


def test_a_failing_non_pytest_gate_is_recorded_as_such(verify, fake_pytest, monkeypatch):
    use_child(monkeypatch, verify, fake_pytest, "pass")
    monkeypatch.setattr(verify, "check_requirements", lambda: ("deps", False, "'pkg' (bare/unpinned package)"))
    code, target = run(verify)
    assert code == 1
    result = load(target, "result.json")
    deps = result["gates"][1]
    assert (deps["name"], deps["status"], deps["exit_status"], deps["detail"]) == (
        "deps", "FAIL", None, "'pkg' (bare/unpinned package)")
    assert result["gates"][0]["status"] == "PASS" and result["result"] == "FAIL"


def test_the_real_non_pytest_gates_are_recorded_exactly_as_they_report(monkeypatch, fake_pytest, tmp_path):
    """No stand-ins for deps/docs/docnames/config: evidence mode records the checkout's real answers unchanged."""
    module = load_verify()
    monkeypatch.setattr(module, "EVIDENCE_ROOT", tmp_path / "evidence-root")
    use_child(monkeypatch, module, fake_pytest, "pass")
    target = tmp_path / "evidence-root" / "real-gates"
    module.main(["--evidence-dir", str(target)])
    recorded = {g["name"]: g for g in load(target, "result.json")["gates"]}
    for function, name in (("check_requirements", "deps"), ("check_docs", "docs"),
                           ("check_doc_names", "docnames"), ("check_config", "config")):
        _, ok, detail = getattr(module, function)()
        assert (recorded[name]["ok"], recorded[name]["detail"], recorded[name]["exit_status"]) == (ok, detail, None)


def test_a_tree_that_changes_during_the_run_cannot_pass(verify, fake_pytest, fake_repo, monkeypatch):
    use_child(monkeypatch, verify, fake_pytest, "touch", str(fake_repo / "tracked.txt"))
    code, target = run(verify)
    assert code == 1
    result = load(target, "result.json")
    assert result["gates_result"] == "PASS" and result["result"] == "FAIL"
    assert result["evidence_checks"][0]["status"] == "FAIL"
    assert "changed during the run" in result["evidence_checks"][0]["detail"]


def test_an_unavailable_fingerprint_cannot_pass(verify, fake_pytest, monkeypatch, tmp_path):
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "no-such-git-dir"))  # every git call now fails, as without a checkout
    use_child(monkeypatch, verify, fake_pytest, "pass")
    code, target = run(verify)
    assert code == 1
    check = load(target, "result.json")["evidence_checks"][0]
    assert check["status"] == "FAIL" and check["detail"].startswith("fingerprint unavailable")


# --------------------------------------------------------------------------- #
# Runs that do not finish are INCOMPLETE, never PASS
# --------------------------------------------------------------------------- #
def test_output_is_on_disk_while_pytest_is_still_running(verify, fake_pytest, monkeypatch, tmp_path):
    go = tmp_path / "go"
    use_child(monkeypatch, verify, fake_pytest, "wait", str(go))
    target = evidence_dir(verify)
    outcome = {}
    worker = threading.Thread(target=lambda: outcome.setdefault("code", run(verify)[0]))
    worker.start()
    try:
        assert wait_for(lambda: "..partial-progress" in log_text(target, "pytest.log")), "output was not streamed"
        assert "first streamed line" in log_text(target, "pytest.log")
        assert "gate pytest: start" in log_text(target, "verify.log")
        assert (target / "INCOMPLETE.json").is_file() and not (target / "result.json").exists()
        assert load(target, "INCOMPLETE.json")["current_gate"] == "pytest"
        assert verify.read_evidence_status(target) == "INCOMPLETE"
    finally:
        go.write_text("go", encoding="utf-8")
        worker.join(timeout=60)
    assert outcome["code"] == 0
    assert verify.read_evidence_status(target) == "PASS"


def test_an_interrupted_run_stops_its_child_and_is_recorded_as_incomplete(verify, fake_pytest, monkeypatch, capsys):
    use_child(monkeypatch, verify, fake_pytest, "forever")
    target = evidence_dir(verify)

    def interrupt_once_streaming():
        if wait_for(lambda: "still running" in log_text(target, "pytest.log")):
            _thread.interrupt_main()

    trigger = threading.Thread(target=interrupt_once_streaming)
    trigger.start()
    try:
        code = run(verify)[0]
    finally:
        trigger.join(timeout=60)
    assert code == 130
    assert verify.read_evidence_status(target) == "INCOMPLETE"
    assert not (target / "result.json").exists()
    marker = load(target, "INCOMPLETE.json")
    assert (marker["status"], marker["reason"], marker["current_gate"]) == (
        "INCOMPLETE", "interrupted (KeyboardInterrupt)", "pytest")
    verify_log = log_text(target, "verify.log")
    assert "INTERRUPTED (KeyboardInterrupt) during gate pytest" in verify_log
    assert "pytest child pid" in verify_log and "ended with exit" in verify_log
    assert "still running" in log_text(target, "pytest.log")  # partial diagnostics are kept
    assert "INCOMPLETE" in capsys.readouterr().err


def test_an_unexpected_error_keeps_its_traceback_and_leaves_the_run_incomplete(verify, fake_pytest, monkeypatch):
    use_child(monkeypatch, verify, fake_pytest, "pass")

    def broken_gate():
        raise RuntimeError("synthetic gate crash")

    monkeypatch.setattr(verify, "check_docs", broken_gate)
    target = evidence_dir(verify)
    with pytest.raises(RuntimeError, match="synthetic gate crash"):
        run(verify)
    assert verify.read_evidence_status(target) == "INCOMPLETE"
    marker = load(target, "INCOMPLETE.json")
    assert marker["reason"] == "error: RuntimeError: synthetic gate crash" and marker["current_gate"] == "docs"
    verify_log = log_text(target, "verify.log")
    assert "Traceback (most recent call last):" in verify_log and "synthetic gate crash" in verify_log
    assert "gate pytest: PASS" in verify_log


def test_a_run_killed_outright_reads_incomplete(fake_repo, fake_pytest, tmp_path):
    wrapper = tmp_path / "killable_run.py"
    wrapper.write_text(KILLABLE_RUN, encoding="utf-8")
    root = fake_repo / "files" / "dev-work" / "act070-remediation"
    target = root / "verify" / "killed-run"
    proc = subprocess.Popen([sys.executable, str(wrapper), str(VERIFY_PATH), str(fake_repo), str(root),
                             str(target), str(fake_pytest)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    child_pid = None
    try:
        assert wait_for(lambda: "still running" in log_text(target, "pytest.log")), "the run never started"
        line = next(l for l in log_text(target, "verify.log").splitlines() if "pytest child started, pid" in l)
        child_pid = int(line.rsplit(" ", 1)[1])
    finally:
        proc.kill()
        proc.wait(timeout=30)
        if child_pid is not None:  # end the one known synthetic child the kill orphaned
            try:
                os.kill(child_pid, signal.SIGTERM)
            except OSError:
                pass
    assert not (target / "result.json").exists()
    marker = load(target, "INCOMPLETE.json")
    assert marker["reason"] == "started; no normal completion has been recorded"
    assert marker["current_gate"] == "pytest"
    load_verify_module = load_verify()
    assert load_verify_module.read_evidence_status(target) == "INCOMPLETE"


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
    module = load_verify()
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    assert module.read_evidence_status(tmp_path) == expected


# --------------------------------------------------------------------------- #
# The tested-tree fingerprint
# --------------------------------------------------------------------------- #
def test_the_fingerprint_tracks_working_tree_bytes_and_new_test_files_only(fake_repo):
    module = load_verify()
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
    module = load_verify()
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))  # never discover an enclosing checkout
    fingerprint = module.tree_fingerprint(tmp_path)
    assert fingerprint["available"] is False and fingerprint["error"]
