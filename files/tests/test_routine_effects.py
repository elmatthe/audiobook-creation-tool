"""Routine verification refuses heavyweight effects at the operation (v0.8.2 Phase 1A-1; routine_effects.py).

Every negative control here is synthetic and harmless even if the mechanism under test were missing: a refused launch
names an engine interpreter that does not exist or an installer's ``--version``, a nested pytest runs a few lines written
into a temporary folder, and a child that a gate root would refuse is given its own private ledger, so its refusal is
read here and never reaches this session's own ledger. Nothing here starts the application, a journey, an engine, an
installer or the network.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import routine_effects as effects
from gate_locator import GATE_DIR, REPO_ROOT

TESTS = REPO_ROOT / "files" / "tests"
BOOTSTRAP = TESTS / "routine_pytest.py"
CONTEXT_HELPER = GATE_DIR / "helpers" / "routine_context.py"
ABSENT_ENGINE = REPO_ROOT / ".venv-omnivoice" / "Scripts" / "python.exe"


def _load_routine_context():
    import importlib.util

    spec = importlib.util.spec_from_file_location("act_test_routine_context", CONTEXT_HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _clean_env(ledger: Path, **extra) -> dict:
    """A child's environment: this session's gate probe and pytest internals removed, a private effect ledger."""
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith(("PYTEST_", "_PYTEST", "ACT_GATE_"))}
    env[effects.LEDGER_ENV] = str(ledger)
    env.update(extra)
    return env


# --------------------------------------------------------------------------- #
#  The environment and the grant that does not exist
# --------------------------------------------------------------------------- #
def test_this_session_runs_inside_the_routine_envelope():
    assert os.environ.get(effects.CONTEXT_ENV) == effects.ROUTINE
    assert os.path.normcase(os.environ.get(effects.ROOT_ENV, "")) == os.path.normcase(os.path.realpath(REPO_ROOT))
    assert not [name for name in os.environ if effects.OPT_IN.match(name.upper())], "an ambient opt-in reached a test"
    assert not set(os.environ) & effects.OVERRIDES


def test_opt_ins_and_overrides_are_scrubbed_and_nothing_else():
    environ = {"ACT_KOKORO_P2_REAL": "1", "ACT_OMNIVOICE_P1_REAL": "1", "act_qwen3_real_long": "1", "ACT_P2_EVIDENCE": "x",
               "ACT_MAC_FFMPEG": "/x", "ACT_XHE_PROOF_APPLE_CAF": "x", "ACT_REALISTIC": "keep", "PATH": "keep"}
    removed = effects.scrub(environ)
    assert removed == sorted(["ACT_KOKORO_P2_REAL", "ACT_OMNIVOICE_P1_REAL", "act_qwen3_real_long", "ACT_P2_EVIDENCE",
                              "ACT_MAC_FFMPEG", "ACT_XHE_PROOF_APPLE_CAF"])
    assert environ == {"ACT_REALISTIC": "keep", "PATH": "keep"}


@pytest.mark.parametrize("effect", sorted(effects.EFFECTS))
def test_no_effect_is_ever_admitted_and_an_opt_in_grants_nothing(monkeypatch, effect):
    monkeypatch.setenv("ACT_OMNIVOICE_P1_REAL", "1")
    monkeypatch.setenv("ACT_KOKORO_P2_REAL", "1")
    assert effects.admitted(effect) is False
    with effects.expected_refusals(), pytest.raises(effects.EffectRefused, match="Phase 1A-2"):
        effects.require(effect, "synthetic control")
    assert effects.refusals()[-1]["effect"] == effect and effects.refusals()[-1]["expected"] is True


def test_an_unknown_effect_is_a_programming_error():
    with pytest.raises(ValueError, match="unknown effect"):
        effects.admitted("teleport")


def test_a_refusal_reaches_the_ledger_even_when_the_caller_swallows_it(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setenv(effects.LEDGER_ENV, str(ledger))
    with effects.expected_refusals():
        try:
            effects.require("real-engine", "swallowed on purpose")
        except effects.EffectRefused:
            pass
    rows = effects.read_ledger(ledger)
    assert [(row["effect"], row["detail"], row["expected"]) for row in rows] == [("real-engine", "swallowed on purpose", True)]
    ledger.write_text("not json\n", encoding="utf-8")
    assert effects.read_ledger(ledger)[0]["expected"] is False, "an unreadable line counts against the run"


# --------------------------------------------------------------------------- #
#  Launch classification
# --------------------------------------------------------------------------- #
GATE = "files/dev-work/verification-gate/"


@pytest.mark.parametrize("command, effect", [
    ([sys.executable, GATE + "acceptance_runner.py"], "native-desktop"),
    ([sys.executable, "-u", GATE + "acceptance_runner.py", "--report", "x"], "native-desktop"),
    ([sys.executable, GATE + "verify.py", "--mode", "full"], "native-desktop"),
    ([sys.executable, GATE + "qualification/edge_low_memory.py"], "external-network"),
    ([sys.executable, GATE + "qualification/not_yet_reviewed.py"], "real-app-launch"),  # unknown below a root: fail closed
    ([sys.executable, GATE + "scaling/bench_run.py"], "scaling"),
    ([sys.executable, "files/tests/macos_gui_driver.py"], "native-desktop"),  # its reviewed row's first effect
    ([sys.executable, "scripts/launcher.py"], "real-app-launch"),
    ([sys.executable, "scripts/shared/bootstrap.py"], "install"),
    ([sys.executable, "scripts/shared/release.py"], "release-build"),
    (["cmd", "/c", "Setup_and_Run-audiobook-creation-tool.bat"], "install"),
    ([str(ABSENT_ENGINE), "-c", "print(1)"], "real-engine"),
    ([".venv/engines/kokoro/Scripts/python.exe", "-m", "worker"], "real-engine"),
    (["winget", "install", "ffmpeg"], "install"),
    (["C:/Program Files/Brew/brew.exe", "--version"], "install"),
    ([sys.executable, "-m", "pip", "install", "requests"], "external-network"),
    (["pip3", "install", "-U", "pip"], "external-network"),
    (f'"{sys.executable}" "{GATE}acceptance_runner.py"', "native-desktop"),
    ([sys.executable, "-X", "utf8", "-u", GATE + "verify.py", "--mode", "full"], "native-desktop"),
    (["explorer", "C:/somewhere"], "native-desktop"),
    ([sys.executable, GATE + "adapters/windows/containment.py"], "native-desktop"),  # anything but its data-only --probe
    (["xdg-open", "book.m4b"], "native-desktop"),
], ids=lambda value: str(value)[-40:] if isinstance(value, (list, str)) else value)
def test_a_heavyweight_launch_of_this_checkout_is_classified(command, effect):
    verdict = effects.classify_launch(command, cwd=REPO_ROOT)
    assert verdict is not None and verdict[0] == effect, verdict


@pytest.mark.parametrize("command", [
    [sys.executable, GATE + "acceptance_runner.py", "--list"],
    [sys.executable, GATE + "verify.py", "--status", "x"],
    [sys.executable, GATE + "verify.py", "--mode", "focused", "--test", "files/tests/test_a.py", "--plan"],
    [sys.executable, GATE + "scaling/bench_run.py", "--help"],
    [sys.executable, "files/tests/local_engine_stub.py"],
    [sys.executable, "files/tests/guarded_pytest.py", "--config", "x"],
    [sys.executable, "files/tests/routine_pytest.py", "files/tests/test_a.py"],
    [sys.executable, "-m", "pip", "install", "--no-index", "--find-links", "wheels", "x"],
    [sys.executable, "-c", "print(1)"],
    ["git", "status"],
    ["git", "check-ignore", "--no-index", "-q", GATE + "verify.py"],  # a program's arguments are data, not a script
    [sys.executable, "-I", "-B", GATE + "adapters/windows/containment.py", "--probe", "out.json"],  # read-only probe
    ["ffprobe", "-i", "scripts/launcher.py"],
    [sys.executable, "-m", "pytest", GATE + "acceptance_runner.py"],  # -m runs a module; the path is its argument
    [sys.executable, str(Path(os.sep) / "elsewhere" / "copy" / "acceptance_runner.py")],
], ids=lambda value: " ".join(map(str, value))[-48:])
def test_a_data_only_bounded_or_foreign_launch_is_allowed(command):
    assert effects.classify_launch(command, cwd=REPO_ROOT) is None


def test_the_classification_ignores_case_as_ntfs_and_apfs_do():
    command = [sys.executable, GATE.upper() + "ACCEPTANCE_RUNNER.PY"]
    assert effects.classify_launch(command, cwd=REPO_ROOT) is not None


def test_a_real_launch_is_refused_before_any_process_exists():
    """Harmless even if the hook were missing: the interpreter named does not exist (FileNotFoundError, a different failure)."""
    assert not ABSENT_ENGINE.exists()
    with effects.expected_refusals(), pytest.raises(effects.EffectRefused, match="real-engine"):
        subprocess.Popen([str(ABSENT_ENGINE), "-c", "pass"])
    with effects.expected_refusals(), pytest.raises(effects.EffectRefused, match="install"):
        os.system("winget --version")


def test_startfile_is_refused():
    with effects.expected_refusals(), pytest.raises(effects.EffectRefused, match="desktop"):
        effects._audit("os.startfile", ("C:/somewhere/book.m4b",))


# --------------------------------------------------------------------------- #
#  The roots refuse by themselves, in a child that has no audit hook
# --------------------------------------------------------------------------- #
def test_the_gate_side_and_test_side_markers_are_the_same_names():
    context = _load_routine_context()
    for name in ("CONTEXT_ENV", "ROOT_ENV", "LEDGER_ENV", "ROUTINE", "REFUSED_EXIT", "DATA_ONLY"):
        assert getattr(context, name) == getattr(effects, name), name


def test_a_gate_root_refuses_inside_the_marked_checkout_and_not_in_a_copy_elsewhere(tmp_path, monkeypatch):
    context = _load_routine_context()
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setenv(effects.LEDGER_ENV, str(ledger))
    with pytest.raises(SystemExit) as raised:
        context.refuse_under_routine("scaling/recipe.py", "scaling", [], origin=str(GATE_DIR / "scaling" / "recipe.py"))
    assert raised.value.code == effects.REFUSED_EXIT
    assert [row["effect"] for row in effects.read_ledger(ledger)] == ["scaling"]
    context.refuse_under_routine("copy", "scaling", [], origin=str(tmp_path / "copy" / "recipe.py"))  # the test's own copy
    context.refuse_under_routine("data", "scaling", ["--help"], origin=str(GATE_DIR / "scaling" / "recipe.py"))
    monkeypatch.delenv(effects.ROOT_ENV)
    with pytest.raises(SystemExit):
        context.refuse_under_routine("no root", "scaling", [], origin=str(tmp_path / "copy" / "recipe.py"))  # fail closed
    monkeypatch.delenv(effects.CONTEXT_ENV)
    context.refuse_under_routine("outside routine", "scaling", [], origin=str(GATE_DIR / "scaling" / "recipe.py"))
    assert len(effects.read_ledger(ledger)) == 2


#: Starts ``<folder>/<stem>.py`` as ``__main__`` from ``python -c``. The parent's audit hook sees only ``python -c`` and a folder
#: and a stem -- no script name it could classify -- so what refuses is the root's own ``__main__`` guard, in the child.
INTERMEDIARY = ("import os, runpy, sys; sys.argv = [os.path.join(sys.argv[1], sys.argv[2] + '.py'), *sys.argv[3:]]; "
                "runpy.run_path(sys.argv[0], run_name='__main__')")


def test_a_real_gate_root_started_through_an_intermediary_refuses_in_the_child(tmp_path):
    ledger = tmp_path / "child.jsonl"
    recipe = [str(GATE_DIR / "scaling"), "recipe"]
    assert effects.classify_launch([sys.executable, "-c", INTERMEDIARY, *recipe], cwd=REPO_ROOT) is None
    done = subprocess.run([sys.executable, "-c", INTERMEDIARY, *recipe], env=_clean_env(ledger), capture_output=True,
                          text=True, timeout=120)
    assert done.returncode == effects.REFUSED_EXIT and "refused" in done.stderr, done
    assert [(row["effect"], row["expected"]) for row in effects.read_ledger(ledger)] == [("scaling", False)]
    helped = subprocess.run([sys.executable, "-c", INTERMEDIARY, *recipe, "--help"], env=_clean_env(ledger),
                            capture_output=True, text=True, timeout=120)
    assert helped.returncode == 0 and "usage" in helped.stdout.lower(), helped
    assert len(effects.read_ledger(ledger)) == 1, "--help is data-only"


def test_the_real_gate_never_executes_a_run_inside_routine_verification(tmp_path):
    ledger = tmp_path / "gate.jsonl"
    gate = [sys.executable, "-c", INTERMEDIARY, str(GATE_DIR), "verify"]
    done = subprocess.run([*gate, "--mode", "focused", "--test", "files/tests/test_a.py"],
                          env=_clean_env(ledger), capture_output=True, text=True, timeout=300)
    assert done.returncode == effects.REFUSED_EXIT and "refused" in done.stderr, done
    assert [row["effect"] for row in effects.read_ledger(ledger)] == ["native-desktop"]
    planned = subprocess.run([*gate, "--mode", "focused", "--test", "files/tests/test_cancel_semantics.py", "--plan"],
                             env=_clean_env(ledger), capture_output=True, text=True, timeout=300)
    assert planned.returncode == 3 and "PLAN: COMPLETE" in planned.stdout, planned
    assert len(effects.read_ledger(ledger)) == 1, "a plan is data-only"


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
    its ``__main__`` block; a qualification runner does it through ``common.start``."""
    table = {key: value for key, value in json.loads((GATE_DIR / "verification.json").read_text(encoding="utf-8"))[
        "entrypoints"].items() if key != "about"}
    common = ast.parse((GATE_DIR / "qualification" / "common.py").read_text(encoding="utf-8"))
    start = next(node for node in common.body if isinstance(node, ast.FunctionDef) and node.name == "start")
    assert "_refuse_under_routine" in _calls(start.body[:2]), "common.start must refuse first (after its docstring)"
    unguarded = []
    for relative, entry in table.items():
        if entry.get("routine") == "bounded" or entry.get("class") == "obsolete" or relative.startswith(
                ("files/dev-tools/", GATE + "adapters/")):
            continue
        body = _main_block(REPO_ROOT / relative)
        first = _calls(body[:6])  # a root that loads the guard by path spends four statements on loading it
        if relative.startswith(GATE + "qualification/"):
            source = (REPO_ROOT / relative).read_text(encoding="utf-8")
            if "start(" in source and "common" in source:
                continue
        if not first & {"refuse_under_routine", "_refuse_under_routine"} and relative != GATE + "verify.py":
            unguarded.append(relative)
    assert unguarded == [], unguarded


# --------------------------------------------------------------------------- #
#  A refusal cannot be swallowed: nested pytest sessions, from outside
# --------------------------------------------------------------------------- #
def _nested(tmp_path: Path, files: dict[str, str], *, with_conftest: bool) -> tuple[subprocess.CompletedProcess, list[dict]]:
    suite = tmp_path / "suite"
    suite.mkdir()
    for name, text in files.items():
        (suite / name).write_text(textwrap.dedent(text), encoding="utf-8")
    ledger = tmp_path / "nested.jsonl"
    command = [sys.executable, "-u", str(BOOTSTRAP), str(suite), "-q", "-rA", "-p", "no:cacheprovider",
               f"--basetemp={tmp_path / 'nb'}", "--rootdir", str(suite)]
    if with_conftest:
        command += ["-p", "conftest"]  # the repository's own conftest.py as a plugin (cwd puts files/tests first on sys.path)
    done = subprocess.run(command, cwd=TESTS, env=_clean_env(ledger), capture_output=True, text=True, timeout=600)
    return done, effects.read_ledger(ledger)


PHASES = """
    import atexit, os, subprocess, sys
    import pytest
    import routine_effects

    ENGINE = {engine!r}

    @pytest.fixture
    def refusing_setup():
        try:
            routine_effects.require("real-engine", "setup")
        except routine_effects.EffectRefused:
            pass
        yield

    @pytest.fixture
    def refusing_teardown():
        yield
        try:
            routine_effects.require("real-engine", "teardown")
        except routine_effects.EffectRefused:
            pass

    def test_body_swallows():
        try:
            routine_effects.require("real-engine", "body")
        except routine_effects.EffectRefused:
            pass

    def test_launch_swallows():
        try:
            subprocess.Popen([ENGINE, "-c", "pass"])
        except PermissionError:
            pass

    def test_setup(refusing_setup):
        pass

    def test_teardown(refusing_teardown):
        pass

    def test_child_refuses():
        code = ("import importlib.util, sys; s = importlib.util.spec_from_file_location('c', sys.argv[1]); "
                "m = importlib.util.module_from_spec(s); s.loader.exec_module(m); "
                "m.refuse_under_routine('nested', 'scaling', [], origin=sys.argv[2])")
        done = subprocess.run([sys.executable, "-c", code, {helper!r}, {origin!r}])
        assert done.returncode == 2

    def test_clean():
        pass
"""


def test_a_swallowed_refusal_fails_its_test_in_every_phase_and_the_session(tmp_path):
    source = PHASES.format(engine=str(ABSENT_ENGINE), helper=str(CONTEXT_HELPER),
                           origin=str(GATE_DIR / "scaling" / "recipe.py"))
    done, rows = _nested(tmp_path, {"test_phases.py": source}, with_conftest=True)
    report = done.stdout
    assert done.returncode == 1, report[-3000:]
    # Each test that caused a refusal is an error of that test (reported at its teardown, where the accounting runs),
    # whichever phase the refusal happened in and although every one of them caught it.
    for name in ("test_body_swallows", "test_launch_swallows", "test_setup", "test_teardown", "test_child_refuses"):
        assert any(line.startswith("ERROR ") and line.endswith(f"test_phases.py::{name}") for line in report.splitlines()), (
            name, report[-3000:])
    assert not any(line.startswith(("ERROR ", "FAILED ")) and line.endswith("test_phases.py::test_clean")
                   for line in report.splitlines()), "the clean control must not be caught"
    assert "refused heavyweight effect(s) in routine verification" in report and "5 errors" in report
    assert sorted(row["effect"] for row in rows) == ["real-engine"] * 4 + ["scaling"], rows


def test_a_refusal_at_import_or_after_the_session_still_fails_the_run(tmp_path):
    """No conftest here: the bootstrap alone accounts for a refusal outside every test, including an atexit callback."""
    files = {
        "test_imports.py": """
            import routine_effects
            try:
                routine_effects.require("real-app-launch", "at import")
            except routine_effects.EffectRefused:
                pass

            def test_passes():
                pass
        """,
    }
    done, rows = _nested(tmp_path, files, with_conftest=False)
    assert done.returncode == 1 and "1 passed" in done.stdout, done.stdout[-2000:]
    assert [row["effect"] for row in rows] == ["real-app-launch"]
    late = tmp_path / "late"
    late.mkdir()
    files = {
        "test_late.py": """
            import atexit
            import routine_effects

            def _later():
                try:
                    routine_effects.require("scaling", "after the session")
                except routine_effects.EffectRefused:
                    pass

            def test_registers():
                atexit.register(_later)
        """,
    }
    done, rows = _nested(late, files, with_conftest=False)
    assert done.returncode == 1 and "1 passed" in done.stdout, (done.stdout[-2000:], done.stderr[-2000:])
    assert "after the session ended" in done.stderr
    assert [row["effect"] for row in rows] == ["scaling"]


def test_the_synthetic_control_still_works_and_grants_nothing(tmp_path):
    """The negative controls above are possible because expected_refusals marks a refusal as expected; it never lets the
    operation happen."""
    files = {"test_control.py": """
        import pytest
        import routine_effects

        def test_expected():
            with routine_effects.expected_refusals(), pytest.raises(routine_effects.EffectRefused):
                routine_effects.require("real-engine", "control")
            assert routine_effects.admitted("real-engine") is False
    """}
    done, rows = _nested(tmp_path, files, with_conftest=True)
    assert done.returncode == 0 and "1 passed" in done.stdout, done.stdout[-2000:]
    assert [(row["effect"], row["expected"]) for row in rows] == [("real-engine", True)]


def test_an_inherited_opt_in_is_scrubbed_before_any_test_module_is_imported(tmp_path):
    files = {"test_env.py": """
        import os

        SEEN_AT_IMPORT = os.environ.get("ACT_OMNIVOICE_P1_REAL"), os.environ.get("ACT_P2_EVIDENCE")

        def test_scrubbed():
            assert SEEN_AT_IMPORT == (None, None)
            assert os.environ["ACT_VERIFY_CONTEXT"] == "routine"
            assert os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    """}
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "test_env.py").write_text(textwrap.dedent(files["test_env.py"]), encoding="utf-8")
    env = _clean_env(tmp_path / "l.jsonl", ACT_OMNIVOICE_P1_REAL="1", ACT_P2_EVIDENCE=str(tmp_path))
    done = subprocess.run([sys.executable, "-u", str(BOOTSTRAP), str(suite), "-q", "-p", "no:cacheprovider",
                           f"--basetemp={tmp_path / 'b'}", "--rootdir", str(suite)], cwd=TESTS, env=env,
                          capture_output=True, text=True, timeout=300)
    assert done.returncode == 0 and "1 passed" in done.stdout, done.stdout[-2000:]


def test_raw_pytest_runs_disable_third_party_plugin_autoload():
    text = (REPO_ROOT / "pytest.ini").read_text(encoding="utf-8")
    assert "--disable-plugin-autoload" in text
