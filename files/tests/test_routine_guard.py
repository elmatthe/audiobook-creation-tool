"""The routine verification guard (v0.8.2 simplification, 2026-11-27; GATE.md "Routine guard").

What routine verification must still guarantee, after the launch interception and per-child accounting were retired:

* the marker reaches every ordinary child through the environment, and a real heavyweight entrypoint refuses under it;
* ambient real-engine opt-ins are scrubbed before any test module is imported;
* a refused effect fails the test that caused it even when the test swallowed the refusal, and fails the session;
* network and desktop hand-offs are refused in-process; nothing grants a heavyweight effect;
* every refusing entrypoint checks the marker in its own bytes, so a copy anywhere refuses as the original does;
* the synthetic gate fixture exception covers a declared disposable tree only.
"""

from __future__ import annotations

import ast
import json
import os
import socket
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import routine_effects as effects
from gate_locator import GATE_DIR, REPO_ROOT

GATE = "files/dev-work/verification-gate/"
context = effects.context

INNER = '''
import os, socket, subprocess, sys
import routine_effects

def test_marker_reaches_a_child():
    out = subprocess.run([sys.executable, "-c", "import os; print(os.environ.get('ACT_VERIFY_CONTEXT'))"],
                         capture_output=True, text=True, timeout=60)
    assert out.stdout.strip() == "routine"

def test_opt_in_was_scrubbed():
    assert "ACT_KOKORO_REAL" not in os.environ and "ACT_P2_EVIDENCE" not in os.environ

def test_a_real_entrypoint_refuses_in_a_child():
    runner = os.path.join(os.environ["ACT_TEST_REPO"], "files", "dev-work", "verification-gate", "acceptance_runner.py")
    out = subprocess.run([sys.executable, runner, "--only", "x"], capture_output=True, text=True, timeout=60)
    assert out.returncode == 2 and "refused" in out.stderr, (out.returncode, out.stderr[-400:])

def test_swallowed_refusal():
    try:
        socket.getaddrinfo("example.invalid", 80)
    except PermissionError:
        pass
'''


def test_the_guard_marks_children_scrubs_opt_ins_and_fails_a_swallowed_refusal(tmp_path):
    """One real pytest child session with this repository's conftest: three behaviours pass, the swallowed refusal fails
    its own test, and the session exits non-zero."""
    inner = tmp_path / "test_inner.py"
    inner.write_text(textwrap.dedent(INNER), encoding="utf-8")
    junit = tmp_path / "inner.xml"
    env = {key: value for key, value in os.environ.items() if not key.startswith(("PYTEST_", "ACT_VERIFY_"))}
    env.update(ACT_KOKORO_REAL="1", ACT_P2_EVIDENCE=str(tmp_path / "x"), ACT_TEST_REPO=str(REPO_ROOT),
               PYTHONPATH=os.pathsep.join([str(REPO_ROOT / "files" / "tests"), str(REPO_ROOT / "scripts")]))
    result = subprocess.run([sys.executable, "-m", "pytest", "-p", "conftest", str(inner), "-q", "-p", "no:cacheprovider",
                             f"--basetemp={tmp_path / 'bt'}", f"--junitxml={junit}"],
                            cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=300)
    assert result.returncode == 1, result.stdout[-2000:]
    import xml.etree.ElementTree as ET

    cases = {case.get("name"): case for case in ET.parse(junit).getroot().iter("testcase")}
    failed = {name for name, case in cases.items() if case.find("failure") is not None or case.find("error") is not None}
    assert set(cases) >= {"test_marker_reaches_a_child", "test_opt_in_was_scrubbed", "test_a_real_entrypoint_refuses_in_a_child",
                          "test_swallowed_refusal"}, sorted(cases)
    assert failed == {"test_swallowed_refusal"}, result.stdout[-2000:]


def test_network_and_desktop_hand_offs_are_refused_in_process_and_nothing_is_admitted():
    with effects.expected_refusals("external-network"):
        with pytest.raises(effects.EffectRefused):
            socket.getaddrinfo("example.invalid", 443)
    with effects.expected_refusals("external-network"):
        with pytest.raises(effects.EffectRefused):
            socket.create_connection(("192.0.2.1", 9), timeout=1)
    if hasattr(os, "startfile"):
        with effects.expected_refusals("native-desktop"):
            with pytest.raises(effects.EffectRefused):
                os.startfile(str(REPO_ROOT / "README.md"))
    with effects.expected_refusals("real-engine"):
        with pytest.raises(effects.EffectRefused):
            effects.require("real-engine", "a declared boundary")
    assert not any(effects.admitted(effect) for effect in effects.EFFECTS)
    listener = socket.socket()
    try:
        listener.bind(("127.0.0.1", 0))  # loopback stays usable
    finally:
        listener.close()


def test_check_operation_refuses_under_the_marker_and_the_synthetic_exception_needs_a_declared_disposable_tree(tmp_path):
    with effects.expected_refusals("native-desktop"), pytest.raises(PermissionError):
        context.check_operation("native-desktop", "a test of the boundary")
    tree = tmp_path / "tree"
    (tree / GATE).mkdir(parents=True)
    stand_in = GATE + "acceptance_runner.py"
    argv = [sys.executable, str(tree / stand_in)]
    assert context.synthetic_fixture(tree) is None
    with effects.expected_refusals("native-desktop"), pytest.raises(PermissionError):
        context.check_operation("native-desktop", "undeclared", root=tree, stand_in=stand_in, argv=argv)
    (tree / context.SYNTHETIC_DECLARATION).write_text(json.dumps({"format": context.SYNTHETIC_FORMAT, "root": str(tree)}),
                                                      encoding="utf-8")
    assert context.synthetic_fixture(tree) is not None
    context.check_operation("native-desktop", "declared stand-in", root=tree, stand_in=stand_in, argv=argv)
    with effects.expected_refusals("native-desktop"), pytest.raises(PermissionError):  # nothing else is admitted
        context.check_operation("native-desktop", "other", root=tree, stand_in=stand_in, argv=[sys.executable, "x.py"])
    assert context.synthetic_fixture(REPO_ROOT) is None  # the marked checkout is never synthetic
    assert context.synthetic_fixture(tmp_path, environ={}) is None  # outside routine verification nothing is synthetic


def test_the_real_gate_refuses_to_execute_a_run_inside_routine_verification_but_plans():
    verify = [sys.executable, str(GATE_DIR / "verify.py")]
    refused = subprocess.run([*verify, "--mode", "focused", "--test", "files/tests/test_routine_guard.py"], cwd=REPO_ROOT,
                             capture_output=True, text=True, timeout=300)
    assert refused.returncode == 2 and "refused" in refused.stderr, refused.stderr[-500:]
    planned = subprocess.run([*verify, "--mode", "focused", "--test", "files/tests/test_routine_guard.py", "--plan"],
                             cwd=REPO_ROOT, capture_output=True, text=True, timeout=300)
    assert planned.returncode == 3 and '"mode": "focused"' in planned.stdout, planned.stderr[-500:]


def _main_block(path: Path) -> list[ast.stmt]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.If) and "__main__" in ast.dump(node.test):
            return node.body
    return []


def _calls(nodes) -> set[str]:
    found = set()
    for node in nodes:
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call):
                target = inner.func
                found.add(target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", ""))
    return found


def test_every_refused_entrypoint_guards_itself_before_it_does_anything():
    """Each maintained root the reviewed table refuses (or allows only data-only) calls the guard in the first statements of
    its ``__main__`` block; a qualification runner does it through ``common.start``; the callables that start real work
    check the operation themselves."""
    table = {key: value for key, value in json.loads((GATE_DIR / "verification.json").read_text(encoding="utf-8"))[
        "entrypoints"].items() if key != "about"}
    common = ast.parse((GATE_DIR / "qualification" / "common.py").read_text(encoding="utf-8"))
    start = next(node for node in common.body if isinstance(node, ast.FunctionDef) and node.name == "start")
    assert "_refuse_under_routine" in _calls(start.body[:2]), "common.start must refuse first (after its docstring)"
    unguarded = []
    for relative, entry in table.items():
        if entry.get("routine") == "bounded" or entry.get("class") == "obsolete" or relative.startswith("files/dev-tools/"):
            continue
        body = _main_block(REPO_ROOT / relative)
        first = _calls(body[:6])
        if relative.startswith(GATE + "qualification/"):
            source = (REPO_ROOT / relative).read_text(encoding="utf-8")
            if "start(" in source and "common" in source:
                continue
        if not first & {"refuse_under_routine", "_refuse_under_routine"} and relative != GATE + "verify.py":
            unguarded.append(relative)
    assert unguarded == [], unguarded
    for relative, needle in ((GATE + "acceptance_runner.py", "native.DesktopLease()"),
                             (GATE + "adapters/windows/native_input.py", "user32.SendInput(len")):
        source = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert source.index("check_operation(") < source.index(needle), relative
    for name in ("bench_run", "calibrate", "qualify", "recipe"):
        source = (GATE_DIR / "scaling" / f"{name}.py").read_text(encoding="utf-8")
        main = source[source.index("\ndef main("):]
        assert "check_operation(\"scaling\"" in main.split("\ndef ", 2)[1], name
