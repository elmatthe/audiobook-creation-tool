"""Routine verification refuses heavyweight effects at the operation (v0.8.2 Phase 1A-1, corrected in R1; routine_effects.py).

Every negative control here is synthetic and harmless even if the mechanism under test were missing: a refused launch names
an engine interpreter that does not exist, a program's ``--version``, or a heavyweight root that refuses itself before it
does anything; a nested pytest runs a few lines written into a temporary folder; a refused network operation targets a
reserved ``.invalid`` name or a documentation address (TEST-NET, RFC 5737) and is refused before any socket call; a refused
model-weight read names a file that does not exist; a refused native-input resolution never calls the function. Children
that refuse are given a private ledger inside an ``expected_refusals`` block, which adopts it and accounts for it. Nothing
here starts the application, a journey, an engine, an installer or the network.

R1 findings covered here: H1 (location is never evidence of a synthetic execution), H2 (the actual child-launch contract),
H3 (the common early envelope and the operation boundaries) and M2 (fail-closed refusal accounting).
"""

from __future__ import annotations

import ast
import ctypes
import json
import os
import shutil
import socket
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

import routine_effects as effects
from gate_locator import GATE_DIR, REPO_ROOT

context = effects.context
TESTS = REPO_ROOT / "files" / "tests"
BOOTSTRAP = TESTS / "routine_pytest.py"
CONTEXT_HELPER = GATE_DIR / "helpers" / "routine_context.py"
ABSENT_ENGINE = REPO_ROOT / ".venv-omnivoice" / "Scripts" / "python.exe"
GATE = "files/dev-work/verification-gate/"
WINDOWS = pytest.mark.skipif(sys.platform != "win32", reason="Windows behaviour")


def _clean_env(ledger: Path, **extra) -> dict:
    """A child's environment: this session's gate probe and pytest internals removed, a private effect ledger (adopted by the
    surrounding ``expected_refusals`` block)."""
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith(("PYTEST_", "_PYTEST", "ACT_GATE_"))}
    env[effects.LEDGER_ENV] = str(ledger)
    env.update(extra)
    return env


def _copy_tree_with(tmp_path: Path, *relatives: str) -> Path:
    """A disposable copy of the checkout holding just ``relatives`` (and the routine contract they load)."""
    root = tmp_path / "copy"
    for relative in (*relatives, GATE + "helpers/routine_context.py"):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / relative, target)
    return root


# --------------------------------------------------------------------------- #
#  The environment and the grant that does not exist
# --------------------------------------------------------------------------- #
def test_this_session_runs_inside_the_routine_envelope():
    assert os.environ.get(effects.CONTEXT_ENV) == effects.ROUTINE
    assert os.path.normcase(os.environ.get(effects.ROOT_ENV, "")) == os.path.normcase(os.path.realpath(REPO_ROOT))
    assert not [name for name in os.environ if effects.OPT_IN.match(name.upper())], "an ambient opt-in reached a test"
    assert not set(os.environ) & effects.OVERRIDES
    assert effects._bootstrapped in ("routine-pytest", "guarded-pytest"), "run through the bootstrap (GATE.md)"
    verdict = effects.read_ledger(os.environ[effects.LEDGER_ENV])
    assert any(role == effects._bootstrapped for role in verdict["roles"]), "this session's accounting was initialized"


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
    with effects.expected_refusals(effect), pytest.raises(effects.EffectRefused, match="Phase 1A-2"):
        effects.require(effect, "synthetic control")
    assert effects.refusals()[-1]["effect"] == effect and effects.refusals()[-1]["expected"] is True


def test_an_unknown_effect_is_a_programming_error():
    with pytest.raises(ValueError, match="unknown effect"):
        effects.admitted("teleport")


def test_the_gate_side_and_test_side_contract_is_one_module():
    """R1 maintainability: the names, launch roots, shapes and ledger format have one home (helpers/routine_context.py)."""
    assert Path(context.__file__).resolve() == CONTEXT_HELPER.resolve()
    for name in ("CONTEXT_ENV", "ROOT_ENV", "LEDGER_ENV", "DISPOSABLE_ENV", "ROUTINE", "REFUSED_EXIT", "DATA_ONLY", "EFFECTS"):
        assert getattr(effects, name) == getattr(context, name), name
    policy = json.loads((GATE_DIR / "verification.json").read_text(encoding="utf-8"))
    table = {key: value for key, value in policy["entrypoints"].items() if key != "about"}
    for relative, entry in table.items():
        if entry.get("routine") in ("refused", "data-only"):
            assert context.launch_role(relative) is not None, f"{relative} is refused but no launch root covers it"
    engine = [path for path, word in effects.ENGINE_EXCEPTIONS]
    guarded = (TESTS / "guarded_pytest.py").read_text(encoding="utf-8")
    assert all(path.rsplit("/", 1)[-1] in guarded for path in engine) and "selfcheck" in guarded, \
        "the routine engine exception mirrors the guarded runner's calm selfcheck profile"


# --------------------------------------------------------------------------- #
#  H1: launch classification never trusts location
# --------------------------------------------------------------------------- #
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
    (["curl", "https://example.invalid/x"], "external-network"),
    # H1: another checkout's root is the same root (the previous rule allowed this one)
    ([sys.executable, str(Path(os.sep) / "elsewhere" / "copy" / GATE / "acceptance_runner.py")], "native-desktop"),
    ([sys.executable, str(Path(os.sep) / "other" / "checkout" / "scripts" / "launcher.py")], "real-app-launch"),
    # a data-only token is only data-only in its reviewed place
    ([sys.executable, GATE + "scaling/recipe.py", "--out", "x", "--help"], "scaling"),
    ([sys.executable, GATE + "verify.py", "--mode", "full", "--status", "x"], "native-desktop"),
    ([sys.executable, GATE + "acceptance_runner.py", "--only", "x", "--list"], "native-desktop"),
], ids=lambda value: str(value)[-48:] if isinstance(value, (list, str)) else value)
def test_a_heavyweight_launch_is_classified_wherever_it_lies(command, effect):
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
    ["cmd", "/c", "mklink", "/J", "a", "b"],
    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts/shared/bootstrap_host.ps1", "-OutFile",
     "x", "-AssumeNo"],
], ids=lambda value: " ".join(map(str, value))[-48:])
def test_a_data_only_bounded_or_reviewed_launch_is_allowed(command):
    assert effects.classify_launch(command, cwd=REPO_ROOT) is None


def test_the_classification_ignores_case_as_ntfs_and_apfs_do():
    command = [sys.executable, GATE.upper() + "ACCEPTANCE_RUNNER.PY"]
    assert effects.classify_launch(command, cwd=REPO_ROOT) is not None


def test_a_copied_or_renamed_real_root_is_the_same_root(tmp_path):
    """H1 controls 2 and 3: a byte copy of a real heavyweight root -- in another tree, or renamed -- classifies as that root."""
    root = _copy_tree_with(tmp_path, GATE + "scaling/recipe.py")
    copy = root / GATE / "scaling" / "recipe.py"
    renamed = tmp_path / "harmless_looking.py"
    shutil.copyfile(copy, renamed)
    for script in (copy, renamed):
        verdict = effects.classify_launch([sys.executable, str(script)], cwd=tmp_path)
        assert verdict is not None and verdict[0] == "scaling", (script, verdict)
    assert "renamed copy" in effects.classify_launch([sys.executable, str(renamed)], cwd=tmp_path)[1]


def test_a_root_refuses_itself_wherever_it_lies_and_only_a_data_only_shape_passes(tmp_path, monkeypatch):
    """H1 child side: the same-checkout root and a foreign or copied root refuse alike (the previous rule exempted the copy)."""
    copy = _copy_tree_with(tmp_path, GATE + "scaling/recipe.py")
    origins = [(GATE_DIR / "scaling" / "recipe.py", REPO_ROOT), (copy / GATE / "scaling" / "recipe.py", copy)]
    with effects.expected_refusals("scaling"):
        for origin, root in origins:
            with pytest.raises(effects.EffectRefused):  # in a routine pytest process the refusal is this session's own
                context.refuse_under_routine("recipe", "scaling", [], origin=str(origin), root=root)
    for origin, root in origins:
        context.refuse_under_routine("recipe", "scaling", ["--help"], origin=str(origin), root=root)  # data-only
    monkeypatch.delenv(effects.CONTEXT_ENV)
    context.refuse_under_routine("outside routine", "scaling", [], origin=str(origins[0][0]), root=REPO_ROOT)


#: Starts ``<folder>/<stem>.py`` as ``__main__`` from ``python -c``. The parent's audit hook sees only ``python -c`` and a folder
#: and a stem -- no script name it could classify -- so what refuses is the root's own ``__main__`` guard, in the child.
INTERMEDIARY = ("import os, runpy, sys; sys.argv = [os.path.join(sys.argv[1], sys.argv[2] + '.py'), *sys.argv[3:]]; "
                "runpy.run_path(sys.argv[0], run_name='__main__')")


@pytest.mark.parametrize("where", ["this-checkout", "copy"])
def test_a_root_started_through_an_intermediary_refuses_in_the_child_and_accounts_for_it(tmp_path, where):
    """H1/H2 child-side refusal propagation: the child records start, refusal and end in the ledger it was given; the parent
    adopts that ledger. A copied root refuses exactly as the original does (the previous rule exempted the copy)."""
    folder = GATE_DIR / "scaling" if where == "this-checkout" else \
        _copy_tree_with(tmp_path, GATE + "scaling/recipe.py") / GATE / "scaling"
    recipe = [str(folder), "recipe"]
    assert effects.classify_launch([sys.executable, "-c", INTERMEDIARY, *recipe], cwd=REPO_ROOT) is None
    ledger = effects.new_ledger(tmp_path / "child")
    with effects.expected_refusals("scaling") as scope:
        done = subprocess.run([sys.executable, "-c", INTERMEDIARY, *recipe], env=_clean_env(ledger), capture_output=True,
                              text=True, timeout=120)
        helped = subprocess.run([sys.executable, "-c", INTERMEDIARY, *recipe, "--help"], env=_clean_env(ledger),
                                capture_output=True, text=True, timeout=120)
    assert done.returncode == effects.REFUSED_EXIT and "refused" in done.stderr, done
    assert helped.returncode == 0 and "usage" in helped.stdout.lower(), helped
    verdict = scope.ledgers[str(ledger)]
    assert verdict["problems"] == [] and [row["effect"] for row in verdict["refusals"]] == ["scaling"], verdict


def test_the_real_gate_never_executes_a_run_inside_routine_verification(tmp_path):
    ledger = effects.new_ledger(tmp_path / "gate")
    gate = [sys.executable, "-c", INTERMEDIARY, str(GATE_DIR), "verify"]
    with effects.expected_refusals("native-desktop") as scope:
        done = subprocess.run([*gate, "--mode", "focused", "--test", "files/tests/test_a.py"],
                              env=_clean_env(ledger), capture_output=True, text=True, timeout=300)
        planned = subprocess.run([*gate, "--mode", "focused", "--test", "files/tests/test_cancel_semantics.py", "--plan"],
                                 env=_clean_env(ledger), capture_output=True, text=True, timeout=300)
    assert done.returncode == effects.REFUSED_EXIT and "refused" in done.stderr, done
    assert planned.returncode == 3 and "PLAN:" in planned.stdout, planned
    assert [row["effect"] for row in scope.ledgers[str(ledger)]["refusals"]] == ["native-desktop"], "a plan is data-only"


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
    its ``__main__`` block; a qualification runner does it through ``common.start``. Since R1 the gate's native adapters do
    too, and the callables that start real work check the operation itself (scaling main(), the acceptance runner's desktop
    lease, the native-input sender)."""
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
        first = _calls(body[:6])  # a root that loads the guard by path spends four statements on loading it
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


# --------------------------------------------------------------------------- #
#  H1: the reviewed synthetic gate fixture, and what cannot inherit it
# --------------------------------------------------------------------------- #
def _synthetic_tree(tmp_path: Path, *, declare=True, root_name=None) -> Path:
    tree = tmp_path / "tree"
    for relative in (context.ORCHESTRATOR, GATE + "acceptance_runner.py", GATE + "scaling/qualify.py"):
        target = tree / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / relative, target)
    stand_in = tree / GATE / "scaling" / "stand_in_qualify.py"
    stand_in.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    if declare:
        digest = __import__("hashlib").sha256(stand_in.read_bytes()).hexdigest()
        real = __import__("hashlib").sha256((tree / GATE / "scaling" / "qualify.py").read_bytes()).hexdigest()
        (tree / context.SYNTHETIC_DECLARATION).write_text(json.dumps({
            "format": context.SYNTHETIC_FORMAT, "root": str((root_name or tree).resolve()),
            "synthetic": {GATE + "scaling/stand_in_qualify.py": digest, GATE + "scaling/qualify.py": real}}), encoding="utf-8")
    return tree


def test_a_reviewed_synthetic_fixture_lets_only_its_orchestrator_and_declared_stand_ins_run(tmp_path):
    """H1 control 4: the reviewed synthetic fixture. Its orchestrator (byte-identical to the real gate, inside this session's
    own disposable root, declared) may start; a declared stand-in may start in place of a runner; a real runner copied into
    the tree never may -- not even when the declaration names it with its real bytes."""
    tree = _synthetic_tree(tmp_path)
    assert context.synthetic_fixture(tree) is not None
    assert effects.classify_launch([sys.executable, str(tree / context.ORCHESTRATOR), "--mode", "focused", "--test",
                                    "files/tests/test_ordinary.py"], cwd=tmp_path) is None
    assert context.synthetic_stand_in(tree, GATE + "scaling/stand_in_qualify.py") is True
    assert context.synthetic_stand_in(tree, GATE + "scaling/qualify.py") is False, "a real runner is never a stand-in"
    assert context.synthetic_stand_in(tree, GATE + "acceptance_runner.py") is False, "an undeclared runner is no stand-in"
    with effects.expected_refusals("scaling", "native-desktop"):
        with pytest.raises(PermissionError):
            context.check_operation("scaling", "a real runner in a synthetic tree", root=tree, stand_in=GATE + "scaling/qualify.py")
        context.check_operation("scaling", "a declared stand-in", root=tree, stand_in=GATE + "scaling/stand_in_qualify.py")
        with pytest.raises(PermissionError):
            context.refuse_under_routine("acceptance_runner.py", "native-desktop", [],
                                         origin=str(tree / GATE / "acceptance_runner.py"), root=tree)


@pytest.mark.parametrize("variation", ["undeclared", "declared-elsewhere", "outside-disposable", "orchestrator-modified",
                                       "orchestrator-renamed", "untrusted-interpreter", "stand-in-modified"])
def test_an_unexpected_path_or_argument_variation_cannot_inherit_the_synthetic_exception(tmp_path, variation):
    """H1 control 6: every variation of the reviewed shape is refused."""
    tree = _synthetic_tree(tmp_path, declare=variation != "undeclared",
                           root_name=tmp_path / "other" if variation == "declared-elsewhere" else None)
    script = tree / context.ORCHESTRATOR
    interpreter = sys.executable
    if variation == "outside-disposable":
        with effects._lock:
            saved = list(effects._disposable_roots)
            effects._disposable_roots[:] = [os.path.normcase(str(tmp_path / "elsewhere"))]
        try:
            assert effects.classify_launch([interpreter, str(script), "--mode", "full"], cwd=tmp_path) is not None
        finally:
            with effects._lock:
                effects._disposable_roots[:] = saved
        return
    if variation == "orchestrator-modified":
        script.write_text(script.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    if variation == "orchestrator-renamed":
        script = script.with_name("gate_copy.py")
        shutil.copyfile(tree / context.ORCHESTRATOR, script)
    if variation == "untrusted-interpreter":
        interpreter = str(tmp_path / "python.exe")
    if variation == "stand-in-modified":
        (tree / GATE / "scaling" / "stand_in_qualify.py").write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
        assert context.synthetic_stand_in(tree, GATE + "scaling/stand_in_qualify.py") is False
        return
    verdict = effects.classify_launch([interpreter, str(script), "--mode", "full"], cwd=tmp_path)
    assert verdict is not None and verdict[0] == "native-desktop", verdict


# --------------------------------------------------------------------------- #
#  H2: the actual child-launch contract
# --------------------------------------------------------------------------- #
def test_the_executable_override_is_the_program_classified():
    assert effects.classify_launch(["git", GATE + "acceptance_runner.py"], cwd=REPO_ROOT, executable=sys.executable) is not None
    verdict = effects.classify_launch([sys.executable, "-c", "pass"], cwd=REPO_ROOT, executable=str(ABSENT_ENGINE))
    assert verdict is not None and verdict[0] == "real-engine", verdict


def test_a_changed_working_directory_resolves_the_real_target():
    assert effects.classify_launch([sys.executable, "acceptance_runner.py"], cwd=GATE_DIR) is not None
    assert effects.classify_launch([sys.executable, "recipe.py"], cwd=GATE_DIR / "scaling") is not None
    assert effects.classify_launch([sys.executable, "-m", "verify", "--mode", "full"], cwd=GATE_DIR) is not None
    assert effects.classify_launch([sys.executable, "-m", "verify", "--plan"], cwd=GATE_DIR) is None


@pytest.mark.parametrize("change, needle", [
    ("drop-everything", "drops the routine marker"),
    ("drop-ledger", "replaces or drops the effect ledger"),
    ("other-ledger", "replaces or drops the effect ledger"),
    ("other-root", "changes the marked checkout"),
    ("opt-in", "re-adds a real-engine opt-in"),
])
def test_a_replacement_environment_must_keep_the_envelope(tmp_path, change, needle):
    env = {key: value for key, value in os.environ.items()}
    if change == "drop-everything":
        env = {"PATH": os.environ.get("PATH", ""), "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")}
    elif change == "drop-ledger":
        env.pop(effects.LEDGER_ENV)
    elif change == "other-ledger":
        env[effects.LEDGER_ENV] = str(tmp_path / "elsewhere")  # outside any expected_refusals block: never adopted
    elif change == "other-root":
        env[effects.ROOT_ENV] = str(tmp_path)
    elif change == "opt-in":
        env["ACT_KOKORO_P2_REAL"] = "1"
    for command in ([sys.executable, "-c", "pass"], ["cmd", "/c", "rem"] if os.name == "nt" else ["/bin/sh", "-c", "true"]):
        verdict = effects.classify_launch(command, cwd=REPO_ROOT, env=env)
        assert verdict is not None and needle in verdict[1], (command, verdict)
    assert effects.classify_launch([sys.executable, "-c", "pass"], cwd=REPO_ROOT, env=dict(os.environ)) is None
    assert effects.classify_launch(["git", "status"], cwd=REPO_ROOT, env={"PATH": os.environ.get("PATH", "")}) is None


def test_inline_module_and_nested_pytest_forms_are_judged():
    run_path = f"import runpy; runpy.run_path({str(GATE_DIR / 'acceptance_runner.py')!r}, run_name='__main__')"
    assert effects.classify_launch([sys.executable, "-c", run_path], cwd=REPO_ROOT) is not None
    assert effects.classify_launch([sys.executable, "-m", "pytest", "files/tests/test_a.py"], cwd=REPO_ROOT)[0] == "real-app-launch"
    assert effects.classify_launch([sys.executable, "-c", "import pytest; pytest.main(['x'])"], cwd=REPO_ROOT) is not None
    assert effects.classify_launch([sys.executable, "-c", "print('harmless')"], cwd=REPO_ROOT) is None
    assert effects.classify_launch([sys.executable, str(BOOTSTRAP), "files/tests/test_a.py"], cwd=REPO_ROOT) is None


def test_shell_mediated_launches_are_judged_by_what_the_shell_runs():
    inner = f'"{sys.executable}" "{GATE}acceptance_runner.py"'
    assert effects.classify_launch(f"cmd /c {inner}", cwd=REPO_ROOT) is not None
    assert effects.classify_launch(["cmd", "/c", "start", "book.m4b"], cwd=REPO_ROOT)[0] == "native-desktop"
    assert effects.classify_launch(["cmd", "/c", "call", "Setup_and_Run-audiobook-creation-tool.bat"], cwd=REPO_ROOT)[0] == "install"
    assert effects.classify_launch(["/bin/sh", "-c", "winget install x"], cwd=REPO_ROOT)[0] == "install"
    assert effects.classify_launch(["powershell", "-NoProfile", "-Command", "Invoke-WebRequest x"], cwd=REPO_ROOT) is not None
    assert effects.classify_launch(["powershell", "-File", "scripts/shared/bootstrap_host.ps1", "-OutFile", "x"],
                                   cwd=REPO_ROOT)[0] == "install", "stage 0 without -AssumeNo can install"
    assert effects.classify_launch(["powershell", "-File", "scripts/shared/bootstrap_host.ps1", "-AssumeNo", "-Url",
                                    "https://example.invalid"], cwd=REPO_ROOT) is not None


def test_stage_zero_runs_only_in_its_reviewed_no_install_shapes(tmp_path):
    """The real stage 0 handed a local archive would unpack into this checkout: refused. A copy in the test's own disposable
    folder, given a local archive there, unpacks only into that copy: bounded. "-AssumeNo" never installs."""
    archive = tmp_path / "cpython.tar.gz"
    real = ["powershell", "-File", "scripts/shared/bootstrap_host.ps1", "-AssumeYes", "-ArchivePath", str(archive)]
    assert effects.classify_launch(real, cwd=REPO_ROOT)[0] == "install"
    copy = tmp_path / "app" / "scripts" / "shared" / "bootstrap_host.ps1"
    copy.parent.mkdir(parents=True)
    shutil.copyfile(REPO_ROOT / "scripts" / "shared" / "bootstrap_host.ps1", copy)
    assert effects.classify_launch(["powershell", "-File", str(copy), "-AssumeYes", "-ArchivePath", str(archive)],
                                   cwd=tmp_path) is None
    assert effects.classify_launch(["powershell", "-File", str(copy), "-AssumeYes"], cwd=tmp_path)[0] == "install"


SETUP_BAT = "Setup_and_Run-audiobook-creation-tool.bat"
SETUP_COMMAND = "Setup_and_Run-audiobook-creation-tool.command"


def test_a_setup_launcher_is_syntax_checked_but_runs_only_as_a_copy_whose_backends_are_stand_ins(tmp_path):
    """R1 (H1 with the launchers as launch roots): ``sh -n`` runs nothing; the real launcher, or a copy whose own stage 0 or
    bootstrap is the real one, is refused; a copy in this session's disposable tree whose every backend pair has a stand-in
    side is the reviewed bounded shape (the venv-recovery and packaging sandboxes)."""
    assert effects.classify_launch(["bash", "-n", SETUP_COMMAND], cwd=REPO_ROOT) is None, "a syntax check"
    assert effects.classify_launch(["bash", SETUP_COMMAND], cwd=REPO_ROOT)[0] == "install"
    assert effects.classify_launch(["bash", "-nc", f"bash {SETUP_COMMAND}"], cwd=REPO_ROOT)[0] == "install", "-c in a group"
    assert effects.classify_launch(["cmd", "/c", str(REPO_ROOT / SETUP_BAT)], cwd=REPO_ROOT)[0] == "install"

    # Windows sandbox: a real venv interpreter, a stub bootstrap, no stage 0.
    win = tmp_path / "win"
    (win / "scripts" / "shared").mkdir(parents=True)
    shutil.copyfile(REPO_ROOT / SETUP_BAT, win / SETUP_BAT)
    (win / "scripts" / "shared" / "bootstrap.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    assert effects.classify_launch(["cmd", "/c", str(win / SETUP_BAT)], cwd=win) is None
    shutil.copyfile(REPO_ROOT / "scripts" / "shared" / "bootstrap.py", win / "scripts" / "shared" / "bootstrap.py")
    assert effects.classify_launch(["cmd", "/c", str(win / SETUP_BAT)], cwd=win)[0] == "install", "the real bootstrap"
    (win / "scripts" / "shared" / "bootstrap.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    shutil.copyfile(REPO_ROOT / "scripts" / "shared" / "bootstrap_host.ps1", win / "scripts" / "shared" / "bootstrap_host.ps1")
    assert effects.classify_launch(["cmd", "/c", str(win / SETUP_BAT)], cwd=win)[0] == "install", "the real stage 0"

    # macOS sandbox (the packaged archive): real bootstrap.py, but every interpreter that could run it is a text shim.
    mac = tmp_path / "mac"
    for relative in ("scripts/shared/bootstrap.py", "scripts/shared/close_terminal.py"):
        (mac / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / relative, mac / relative)
    shutil.copyfile(REPO_ROOT / SETUP_COMMAND, mac / SETUP_COMMAND)
    (mac / "scripts" / "shared" / "bootstrap_host_macos.sh").write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    for relative in (".venv/bin/python", "files/runtime-data/python/bin/python3.12"):
        (mac / relative).parent.mkdir(parents=True, exist_ok=True)
        (mac / relative).write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    assert effects.classify_launch(["bash", str(mac / SETUP_COMMAND)], cwd=mac) is None
    (mac / ".venv/bin/python").write_bytes(b"\x7fELF a real interpreter")
    assert effects.classify_launch(["bash", str(mac / SETUP_COMMAND)], cwd=mac)[0] == "install", "a real interpreter"

    # Outside this session's disposable tree, the same stand-in layout is no exception.
    outside = REPO_ROOT / "files" / "run-temp"
    assert not effects._launcher_bounded(str(outside / SETUP_BAT), SETUP_BAT)


def test_native_programs_are_reviewed_or_refused(tmp_path):
    assert effects.classify_launch(["tasklist", "/FI", "PID eq 4", "/NH"], cwd=REPO_ROOT) is None
    assert effects.classify_launch(["git", "-C", str(tmp_path), "status"], cwd=REPO_ROOT) is None
    stub = tmp_path / "made_by_this_test.exe"
    stub.write_bytes(b"MZ not a real program")
    assert effects.classify_launch([str(stub)], cwd=tmp_path) is None, "a program the test made in its own folder"
    made = tmp_path / ".venv" / "engines" / "qwen3" / "Scripts" / "python.exe"  # an empty venv a layout test makes
    assert effects.classify_launch([str(made), "-c", "pass"], cwd=tmp_path) is None
    assert effects.classify_launch([str(REPO_ROOT / ".venv" / "engines" / "qwen3" / "Scripts" / "python.exe"), "-c", "pass"],
                                   cwd=tmp_path)[0] == "real-engine", "the checkout's real engine environment"
    if os.name == "nt":
        verdict = effects.classify_launch(["notepad"], cwd=REPO_ROOT)
        assert verdict is not None and "unclassified native program" in verdict[1], verdict


def test_a_real_launch_is_refused_before_any_process_exists():
    """Harmless even if the hook were missing: the interpreter named does not exist (FileNotFoundError, a different failure)."""
    assert not ABSENT_ENGINE.exists()
    with effects.expected_refusals("real-engine"), pytest.raises(effects.EffectRefused, match="real-engine"):
        subprocess.Popen([str(ABSENT_ENGINE), "-c", "pass"])
    with effects.expected_refusals("install"), pytest.raises(effects.EffectRefused, match="install"):
        os.system("winget --version")
    with effects.expected_refusals("real-app-launch"), pytest.raises(effects.EffectRefused, match="replacement environment"):
        subprocess.run([sys.executable, "-c", "pass"], env={"PATH": os.environ.get("PATH", "")})


# --------------------------------------------------------------------------- #
#  H3: the common early envelope and the operation boundaries
# --------------------------------------------------------------------------- #
def test_both_runners_take_the_common_early_envelope_before_pytest_is_imported():
    for name, runner in (("routine_pytest.py", "routine-pytest"), ("guarded_pytest.py", "guarded-pytest")):
        source = (TESTS / name).read_text(encoding="utf-8")
        assert f'bootstrap("{runner}"' in source, name
        assert source.index(f'bootstrap("{runner}"') < source.index("import pytest\n"), name
    assert "--disable-plugin-autoload" in (REPO_ROOT / "pytest.ini").read_text(encoding="utf-8")


def test_external_network_is_refused_at_the_socket_and_loopback_is_not():
    assert effects._external("socket.getaddrinfo", ("example.invalid", 443, 0, 0, 0)) == "example.invalid"
    assert effects._external("socket.connect", (None, ("192.0.2.1", 80))) == "192.0.2.1"
    assert effects._external("socket.connect", (None, ("127.0.0.1", 80))) is None
    assert effects._external("socket.getaddrinfo", ("localhost", 80, 0, 0, 0)) is None
    with effects.expected_refusals("external-network"), pytest.raises(effects.EffectRefused, match="external-network"):
        socket.getaddrinfo("example.invalid", 443)  # refused before the resolver is asked
    server = socket.socket()
    try:
        server.bind(("127.0.0.1", 0))  # loopback stays usable for local fixtures
    finally:
        server.close()


#: A frame of a model library opening a weight file, without importing the library: the code below is compiled under a
#: torch-shaped file name, so the hook sees exactly what a ``torch.load`` frame would show it.
MODEL_FRAME = "def load(path):\n    with open(path, 'rb') as handle:\n        return handle.read()\n"


def test_a_model_library_reading_real_weights_is_refused_and_ordinary_reads_are_not(tmp_path):
    fake = tmp_path / "tiny.safetensors"
    fake.write_bytes(b"\0" * 8)
    assert fake.read_bytes() == b"\0" * 8
    absent = REPO_ROOT / "files" / "runtime-data" / "models" / "no-such-model" / "model.safetensors"
    assert not absent.exists()
    with pytest.raises(FileNotFoundError):
        open(absent, "rb")  # reading (hashing, copying) a weight file is not model initialization
    namespace = {}
    exec(compile(MODEL_FRAME, str(tmp_path / "Lib" / "site-packages" / "torch" / "serialization.py"), "exec"), namespace)
    assert namespace["load"](fake) == b"\0" * 8, "a test-made weight file in the disposable root stays readable"
    with effects.expected_refusals("real-engine"), pytest.raises(effects.EffectRefused, match="real weights"):
        namespace["load"](absent)


@WINDOWS
def test_resolving_a_native_input_function_is_refused_outside_the_gate_adapter():
    """Resolution only: the function is never called, and the refusal comes before ctypes looks it up."""
    with effects.expected_refusals("native-desktop"), pytest.raises(effects.EffectRefused, match="native input"):
        ctypes.WinDLL("user32").SendInput  # noqa: B018


def test_startfile_is_refused():
    with effects.expected_refusals("native-desktop"), pytest.raises(effects.EffectRefused, match="desktop"):
        effects._audit("os.startfile", ("C:/somewhere/book.m4b",))


def test_an_imported_scaling_callable_refuses_at_its_operation(monkeypatch):
    """H3: not only ``__main__``. ``recipe.main()`` parses its arguments, then refuses before any work."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("act_recipe_control", GATE_DIR / "scaling" / "recipe.py")
    recipe = importlib.util.module_from_spec(spec)
    saved = list(sys.path)
    try:
        spec.loader.exec_module(recipe)
    finally:
        sys.path[:] = saved
    monkeypatch.setattr(sys, "argv", ["recipe.py", "--ffmpeg", "ffmpeg-not-run", "--out", "never-written", "a"])
    with effects.expected_refusals("scaling"), pytest.raises(PermissionError, match="scaling"):
        recipe.main()
    assert not Path("never-written").exists()


# --------------------------------------------------------------------------- #
#  M2: the ledger reader never calls an unverified ledger clean
# --------------------------------------------------------------------------- #
def _ledger_with(tmp_path: Path, *lines: str, header=True) -> Path:
    ledger = tmp_path / "led"
    if header:
        effects.new_ledger(ledger)
    else:
        ledger.mkdir()
    if lines:
        (ledger / "p1-abcd.jsonl").write_bytes("".join(lines).encode("utf-8") if all(isinstance(x, str) for x in lines)
                                              else b"".join(lines))
    return ledger


START = json.dumps({"kind": "start", "pid": 1, "ppid": 0, "role": "routine-pytest"}) + "\n"
END = json.dumps({"kind": "end", "exit": 0, "refusals": 0, "unexpected": 0, "accounting": "ok"}) + "\n"


@pytest.mark.parametrize("case, needle", [
    ("missing", "missing"),
    ("no-header", "uninitialized"),
    ("empty", "no completed routine-pytest session"),
    ("malformed-json", "not JSON"),
    ("wrong-shape", "wrong shape"),
    ("wrong-field-type", "wrong shape"),
    ("interrupted", "never completed"),
    ("accounting-failed", "accounting failed"),
    ("unreadable", "unreadable"),
    ("header-wrong-format", "unknown format"),
])
def test_an_unverified_ledger_is_never_clean(tmp_path, case, needle):
    if case == "missing":
        path = tmp_path / "never-made"
    elif case == "no-header":
        path = _ledger_with(tmp_path, START, END, header=False)
    elif case == "empty":
        path = _ledger_with(tmp_path)
    elif case == "malformed-json":
        path = _ledger_with(tmp_path, START, "not json\n", END)
    elif case == "wrong-shape":
        path = _ledger_with(tmp_path, START, "[1, 2]\n", END)
    elif case == "wrong-field-type":
        path = _ledger_with(tmp_path, START, json.dumps({"kind": "refusal", "effect": "scaling", "detail": "x", "origin": "o",
                                                         "pid": 1, "expected": "no"}) + "\n", END)
    elif case == "interrupted":
        path = _ledger_with(tmp_path, START)
    elif case == "accounting-failed":
        path = _ledger_with(tmp_path, START, END.replace('"ok"', '"failed"'))
    elif case == "unreadable":
        path = _ledger_with(tmp_path, START.encode() + b"\xff\xfe\xfa" + END.encode())
    else:
        path = _ledger_with(tmp_path)
        (path / context.LEDGER_HEADER).write_text("[]", encoding="utf-8")
    verdict = effects.read_ledger(path, require_role="routine-pytest")
    assert verdict["status"] != "PASS" and any(needle in problem for problem in verdict["problems"]), verdict


def test_a_complete_clean_ledger_is_clean_and_an_unexpected_refusal_is_not(tmp_path):
    clean = _ledger_with(tmp_path, START, END)
    assert effects.read_ledger(clean, require_role="routine-pytest")["status"] == "PASS"
    refusal = json.dumps({"kind": "refusal", "effect": "scaling", "detail": "x", "origin": "o", "pid": 1, "expected": False})
    (clean / "p2-abcd.jsonl").write_text(START + refusal + "\n" + END, encoding="utf-8")
    verdict = effects.read_ledger(clean, require_role="routine-pytest")
    assert verdict["status"] == "FAIL" and len(verdict["unexpected"]) == 1


def test_a_ledger_write_failure_is_an_accounting_failure_never_absorbed(tmp_path, monkeypatch):
    ledger = effects.new_ledger(tmp_path / "w")
    record = context.ProcessRecord(ledger, "unit")
    record.start()

    def refuse_open(*_args, **_kwargs):
        raise OSError(28, "No space left on device (synthetic)")

    monkeypatch.setattr(context, "_os_open", refuse_open)
    with pytest.raises(context.LedgerError):
        record.refusal({"effect": "scaling", "detail": "x", "origin": "o", "pid": 1, "expected": False})
    assert record.failed
    monkeypatch.undo()
    with pytest.raises(context.LedgerError):
        context.ProcessRecord(tmp_path / "never-initialized", "unit").start()


def test_concurrent_writers_never_corrupt_the_ledger(tmp_path):
    """Several processes and several threads record at once: each process owns its file, each thread takes the lock."""
    ledger = effects.new_ledger(tmp_path / "c")
    writer = ("import importlib.util, sys, threading\n"
              "s = importlib.util.spec_from_file_location('c', sys.argv[1]); m = importlib.util.module_from_spec(s); "
              "s.loader.exec_module(m)\n"
              "r = m.ProcessRecord(sys.argv[2], 'writer'); r.start()\n"
              "def go(n):\n"
              "    for i in range(25):\n"
              "        r.refusal({'effect': 'scaling', 'detail': f'{n}-{i}', 'origin': 'o', 'pid': 1, 'expected': True})\n"
              "ts = [threading.Thread(target=go, args=(n,)) for n in range(4)]\n"
              "[t.start() for t in ts]; [t.join() for t in ts]\n"
              "r.end(exit_status=0, refusals=100, unexpected=0)\n")
    children = [subprocess.Popen([sys.executable, "-c", writer, str(CONTEXT_HELPER), str(ledger)]) for _ in range(4)]
    assert [child.wait(timeout=120) for child in children] == [0, 0, 0, 0]
    verdict = effects.read_ledger(ledger)
    assert verdict["problems"] == [] and verdict["complete"] == 4 and len(verdict["refusals"]) == 400, verdict["problems"][:3]


def test_an_expected_refusal_is_scoped_to_its_thread_and_its_effect(tmp_path):
    """M2: the allowance belongs to the negative control's own thread and named effects. Shown in a nested session, whose
    failure is the assertion: another thread's refusal, and the wrong effect on the right thread, stay unexpected."""
    files = {"test_scope.py": """
        import threading
        import pytest
        import routine_effects

        def test_another_threads_refusal_is_unexpected():
            def other():
                try:
                    routine_effects.require("real-engine", "another thread")
                except routine_effects.EffectRefused:
                    pass
            with routine_effects.expected_refusals("real-engine"):
                worker = threading.Thread(target=other)
                worker.start()
                worker.join()

        def test_the_wrong_effect_is_unexpected():
            with routine_effects.expected_refusals("scaling"):
                try:
                    routine_effects.require("install", "not the named effect")
                except routine_effects.EffectRefused:
                    pass

        def test_the_named_effect_on_its_own_thread_is_expected():
            with routine_effects.expected_refusals("scaling"), pytest.raises(routine_effects.EffectRefused):
                routine_effects.require("scaling", "the control")
    """}
    done, verdict = _nested(tmp_path, files, with_conftest=True)
    lines = done.stdout.splitlines()
    for name in ("test_another_threads_refusal_is_unexpected", "test_the_wrong_effect_is_unexpected"):
        assert any(line.startswith("ERROR ") and line.endswith(f"test_scope.py::{name}") for line in lines), done.stdout[-3000:]
    assert not any(line.endswith("test_the_named_effect_on_its_own_thread_is_expected") and line.startswith(("ERROR", "FAILED"))
                   for line in lines)
    assert done.returncode == 1 and sorted(row["effect"] for row in verdict["unexpected"]) == ["install", "real-engine"]


# --------------------------------------------------------------------------- #
#  M2: a refusal cannot be swallowed and accounting fails closed: nested sessions, from outside
# --------------------------------------------------------------------------- #
def _nested(tmp_path: Path, files: dict[str, str], *, with_conftest: bool, ledger_state: str = "initialized",
            timeout: float = 600, background: bool = False):
    suite = tmp_path / "suite"
    suite.mkdir()
    for name, text in files.items():
        (suite / name).write_text(textwrap.dedent(text), encoding="utf-8")
    ledger = tmp_path / "nested"
    if ledger_state == "initialized":
        effects.new_ledger(ledger)
    elif ledger_state == "a-file":
        ledger.write_text("not a ledger directory", encoding="utf-8")
    command = [sys.executable, "-u", str(BOOTSTRAP), str(suite), "-q", "-rA", "-p", "no:cacheprovider",
               f"--basetemp={tmp_path / 'nb'}", "--rootdir", str(suite)]
    if with_conftest:
        command += ["-p", "conftest"]  # the repository's own conftest.py as a plugin (cwd puts files/tests first on sys.path)
    with effects.expected_refusals(accounting="report") as scope:
        if background:
            return subprocess.Popen(command, cwd=TESTS, env=_clean_env(ledger), stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL), ledger, scope
        done = subprocess.run(command, cwd=TESTS, env=_clean_env(ledger), capture_output=True, text=True, timeout=timeout)
    return done, scope.ledgers.get(str(ledger), effects.read_ledger(ledger))


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

    def test_child_refuses_and_its_exit_is_ignored():
        code = ("import importlib.util, sys; s = importlib.util.spec_from_file_location('c', sys.argv[1]); "
                "m = importlib.util.module_from_spec(s); s.loader.exec_module(m); "
                "m.refuse_under_routine('nested', 'scaling', [], origin=sys.argv[2])")
        subprocess.run([sys.executable, "-c", code, {helper!r}, {origin!r}])  # exit status deliberately ignored

    def test_clean():
        pass
"""


def test_a_swallowed_refusal_fails_its_test_in_every_phase_and_the_session(tmp_path):
    source = PHASES.format(engine=str(ABSENT_ENGINE), helper=str(CONTEXT_HELPER),
                           origin=str(GATE_DIR / "scaling" / "recipe.py"))
    done, verdict = _nested(tmp_path, {"test_phases.py": source}, with_conftest=True)
    report = done.stdout
    assert done.returncode == 1, report[-3000:]
    # Each test that caused a refusal is an error of that test (reported at its teardown, where the accounting runs),
    # whichever phase the refusal happened in and although every one of them caught it -- the child's included, whose exit
    # status its test ignored.
    for name in ("test_body_swallows", "test_launch_swallows", "test_setup", "test_teardown",
                 "test_child_refuses_and_its_exit_is_ignored"):
        assert any(line.startswith("ERROR ") and line.endswith(f"test_phases.py::{name}") for line in report.splitlines()), (
            name, report[-3000:])
    assert not any(line.startswith(("ERROR ", "FAILED ")) and line.endswith("test_phases.py::test_clean")
                   for line in report.splitlines()), "the clean control must not be caught"
    assert "refused heavyweight effect(s) in routine verification" in report and "5 errors" in report
    assert sorted(row["effect"] for row in verdict["refusals"]) == ["real-engine"] * 4 + ["scaling"], verdict["refusals"]
    assert verdict["status"] == "FAIL"


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
    done, verdict = _nested(tmp_path, files, with_conftest=False)
    assert done.returncode == 1 and "1 passed" in done.stdout, done.stdout[-2000:]
    assert [row["effect"] for row in verdict["refusals"]] == ["real-app-launch"]
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
    done, verdict = _nested(late, files, with_conftest=False)
    assert done.returncode == 1 and "1 passed" in done.stdout, (done.stdout[-2000:], done.stderr[-2000:])
    assert "not a pass" in done.stderr
    assert [row["effect"] for row in verdict["refusals"]] == ["scaling"]
    assert verdict["status"] == "FAIL" and verdict["complete"] == 1, "the late refusal is in the session's completed record"


@pytest.mark.parametrize("ledger_state", ["missing", "a-file"])
def test_a_session_whose_ledger_is_missing_or_unwritable_is_never_a_pass(tmp_path, ledger_state):
    """M2: the stage-owned ledger was not initialized (missing) or cannot hold records (a file where the directory should be):
    every test passes, and the run still fails, because its accounting could not be established or completed."""
    files = {"test_fine.py": "def test_fine():\n    pass\n"}
    done, _verdict = _nested(tmp_path, files, with_conftest=True, ledger_state=ledger_state)
    assert done.returncode != 0, (done.stdout[-2000:], done.stderr[-2000:])


def test_an_interrupted_session_leaves_an_incomplete_ledger(tmp_path):
    """M2: a cooperating child killed before it completed its accounting is never verified clean."""
    files = {"test_waits.py": "import time\n\ndef test_waits():\n    time.sleep(120)\n"}
    proc, ledger, scope = _nested(tmp_path, files, with_conftest=False, background=True)
    try:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and not any(path.suffix == ".jsonl" for path in ledger.iterdir()):
            time.sleep(0.1)
        time.sleep(1.0)
    finally:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True) if os.name == "nt" else proc.kill()
        proc.wait(timeout=60)
    verdict = effects.read_ledger(ledger, require_role="routine-pytest")
    assert verdict["status"] == "FAIL" and any("never completed" in problem for problem in verdict["problems"]), verdict


def test_the_synthetic_control_still_works_and_grants_nothing(tmp_path):
    """The negative controls above are possible because expected_refusals marks a refusal as expected; it never lets the
    operation happen. A truly clean nested session is clean."""
    files = {"test_control.py": """
        import pytest
        import routine_effects

        def test_expected():
            with routine_effects.expected_refusals("real-engine"), pytest.raises(routine_effects.EffectRefused):
                routine_effects.require("real-engine", "control")
            assert routine_effects.admitted("real-engine") is False
    """, "test_clean.py": "def test_clean():\n    pass\n"}
    done, verdict = _nested(tmp_path, files, with_conftest=True)
    assert done.returncode == 0 and "2 passed" in done.stdout, done.stdout[-2000:]
    assert [(row["effect"], row["expected"]) for row in verdict["refusals"]] == [("real-engine", True)]
    assert verdict["problems"] == [] and verdict["status"] == "PASS", verdict


#: Adds the opt-in and the override inside the child, then starts the bootstrap there: the launch rule refuses a child whose
#: environment re-adds them, so this is the one way to prove the bootstrap's own scrub runs before any test module imports.
WITH_OPT_IN = ("import os, runpy, sys; os.environ['ACT_OMNIVOICE_P1_REAL'] = '1'; os.environ['ACT_P2_EVIDENCE'] = 'x'; "
               "sys.argv = [sys.argv[1], *sys.argv[2:]]; runpy.run_path(sys.argv[0], run_name='__main__')")


def test_an_inherited_opt_in_is_scrubbed_before_any_test_module_is_imported(tmp_path):
    files = {"test_env.py": """
        import os

        SEEN_AT_IMPORT = (os.environ.get("ACT_OMNIVOICE_P1_REAL"), os.environ.get("ACT_P2_EVIDENCE"),
                          os.environ.get("ACT_VERIFY_CONTEXT"), bool(os.environ.get("ACT_EFFECT_LEDGER")))

        def test_scrubbed():
            assert SEEN_AT_IMPORT == (None, None, "routine", True)
            assert os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    """}
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "test_env.py").write_text(textwrap.dedent(files["test_env.py"]), encoding="utf-8")
    ledger = effects.new_ledger(tmp_path / "l")
    env = _clean_env(ledger)
    assert effects.classify_launch([sys.executable, "-c", "pass"], env={**env, "ACT_OMNIVOICE_P1_REAL": "1"}) is not None
    with effects.expected_refusals() as scope:
        done = subprocess.run([sys.executable, "-c", WITH_OPT_IN, str(BOOTSTRAP), str(suite), "-q", "-p", "no:cacheprovider",
                               f"--basetemp={tmp_path / 'b'}", "--rootdir", str(suite)], cwd=TESTS, env=env,
                              capture_output=True, text=True, timeout=300)
    assert done.returncode == 0 and "1 passed" in done.stdout, done.stdout[-2000:]
    assert scope.ledgers[str(ledger)]["status"] == "PASS", scope.ledgers[str(ledger)]


def test_raw_pytest_runs_disable_third_party_plugin_autoload():
    text = (REPO_ROOT / "pytest.ini").read_text(encoding="utf-8")
    assert "--disable-plugin-autoload" in text
