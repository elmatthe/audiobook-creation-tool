"""Corrective checkpoint after B1 (Codex finding 1): production-module guards scan the application source, exactly.

After ``launcher.py``, ``shared/``, ``tts/`` and ``mp3_tools/`` were lifted to ``scripts/``, a guard written as
``scripts/**/*.py`` also read ``scripts/verify.py`` and any machine-local, untracked script (a developer's
``project-status.py``), so an unrelated helper could fail a security or architecture guard on one machine only.
``source_probe.application_python_files`` is now the one definition of "the application's Python source". These tests pin
it from both sides: it must cover EVERY application module (nested packages and future top-level packages included, so a
syntax error or a forbidden call there still reaches the guards), and it must not cover anything else. The adversarial
tests then drive the real guards against a synthetic tree.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

import source_probe
import test_epub_retirement as epub_guards
import test_ffmpeg_runtime_trust as ffmpeg_guards
from source_probe import application_packages, application_python_files

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPO_ROOT / "scripts"

BARE_FFMPEG = "import subprocess\nsubprocess.run(['ffmpeg', '-i', 'in.mp3', 'out.wav'])\n"
CLEAN = "VALUE = 1\n"


def write(root: Path, files: dict[str, str]) -> Path:
    for relative, text in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def application_tree(tmp_path: Path, extra: dict[str, str] | None = None) -> Path:
    return write(tmp_path / "scripts", {
        "launcher.py": CLEAN, "shared/__init__.py": "", "shared/paths.py": CLEAN, "tts/__init__.py": "",
        "tts/engine.py": CLEAN, "tts/speech/__init__.py": "", "tts/speech/rules.py": CLEAN,
        "mp3_tools/__init__.py": "", "mp3_tools/m4b_plan.py": CLEAN, **(extra or {}),
    })


def relative(files: list[Path], root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in files}


# --------------------------------------------------------------------------- #
# The helper covers every application module and nothing else
# --------------------------------------------------------------------------- #
def test_every_tracked_application_module_is_covered_on_the_real_tree():
    result = subprocess.run(["git", "ls-files", "--", "scripts"], cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        pytest.skip("not a git checkout")
    covered = relative(application_python_files(SCRIPTS), SCRIPTS)
    tracked = {p.removeprefix("scripts/") for p in result.stdout.split("\n") if p.endswith(".py")}
    assert tracked - {"verify.py"} <= covered, sorted(tracked - {"verify.py"} - covered)
    assert "verify.py" not in covered and "launcher.py" in covered and "tts/qwen3_worker.py" in covered


def test_every_tracked_top_level_folder_of_scripts_is_an_application_package():
    result = subprocess.run(["git", "ls-files", "--", "scripts"], cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        pytest.skip("not a git checkout")
    folders = {p.split("/")[1] for p in result.stdout.split("\n") if p.count("/") >= 2}
    assert folders <= set(application_packages(SCRIPTS)), "a new top-level folder needs an __init__.py to be scanned"


def test_nested_and_future_packages_are_covered_and_everything_else_is_not(tmp_path):
    root = application_tree(tmp_path, {
        "speechkit/__init__.py": "", "speechkit/rules.py": CLEAN,       # a future top-level package
        "verify.py": CLEAN, "project-status.py": CLEAN, "local_helper.py": CLEAN,   # not application source
        "notes/helper.py": CLEAN,                                        # a folder that is not a package
        "tts/__pycache__/stale.py": CLEAN,
    })
    covered = relative(application_python_files(root), root)
    assert covered == {"launcher.py", "shared/__init__.py", "shared/paths.py", "tts/__init__.py", "tts/engine.py",
                       "tts/speech/__init__.py", "tts/speech/rules.py", "mp3_tools/__init__.py", "mp3_tools/m4b_plan.py",
                       "speechkit/__init__.py", "speechkit/rules.py"}


def test_a_missing_launcher_or_package_does_not_break_the_helper(tmp_path):
    assert application_python_files(write(tmp_path / "s", {"shared/__init__.py": ""})) == [tmp_path / "s" / "shared" / "__init__.py"]
    assert application_python_files(tmp_path / "does-not-exist") == []


# --------------------------------------------------------------------------- #
# The real guards: a local helper never contaminates them, a production module still fails them
# --------------------------------------------------------------------------- #
def run_bare_ffmpeg_guard(monkeypatch, root: Path) -> None:
    monkeypatch.setattr(ffmpeg_guards, "UNIVERSAL", root)
    ffmpeg_guards.test_no_production_module_spawns_a_bare_ffmpeg_name()


def run_removed_dependency_guard(monkeypatch, root: Path) -> None:
    monkeypatch.setattr(epub_guards, "UNIVERSAL", root)
    epub_guards.test_a_removed_dependency_has_no_active_production_consumer("lxml")


def test_a_local_helper_with_a_bare_ffmpeg_call_does_not_fail_the_ffmpeg_guard(monkeypatch, tmp_path):
    root = application_tree(tmp_path, {"project-status.py": BARE_FFMPEG, "verify.py": BARE_FFMPEG})
    run_bare_ffmpeg_guard(monkeypatch, root)  # passes


def test_the_same_call_inside_any_application_module_fails_the_ffmpeg_guard(monkeypatch, tmp_path):
    for module in ("launcher.py", "shared/paths.py", "tts/engine.py", "tts/speech/rules.py", "mp3_tools/m4b_plan.py"):
        root = application_tree(tmp_path / module.replace("/", "_"), {module: BARE_FFMPEG})
        with pytest.raises(AssertionError) as caught:
            run_bare_ffmpeg_guard(monkeypatch, root)
        assert module in str(caught.value).replace("\\\\", "/").replace("\\", "/"), module


def test_a_local_helper_with_invalid_syntax_does_not_break_the_guards(monkeypatch, tmp_path):
    root = application_tree(tmp_path, {"project-status.py": "def broken(:\n", "local_helper.py": "def broken(:\n"})
    run_bare_ffmpeg_guard(monkeypatch, root)
    run_removed_dependency_guard(monkeypatch, root)


def test_invalid_syntax_in_an_application_module_is_still_detected(monkeypatch, tmp_path):
    for module in ("launcher.py", "tts/engine.py", "tts/speech/rules.py"):
        root = application_tree(tmp_path / module.replace("/", "_"), {module: "def broken(:\n"})
        with pytest.raises(SyntaxError):
            run_removed_dependency_guard(monkeypatch, root)


def test_a_forbidden_import_in_an_application_module_fails_the_dependency_guard_but_not_in_a_local_helper(monkeypatch, tmp_path):
    run_removed_dependency_guard(monkeypatch, application_tree(tmp_path / "a", {"project-status.py": "import lxml\n"}))
    with pytest.raises(AssertionError):
        run_removed_dependency_guard(monkeypatch, application_tree(tmp_path / "b", {"tts/speech/rules.py": "import lxml\n"}))


# --------------------------------------------------------------------------- #
# Bounded inventory: no production-module guard walks scripts/ with a raw rglob any more
# --------------------------------------------------------------------------- #
#: Scans that are broad ON PURPOSE: they inspect the whole shipped tree or a single package, or prove a file is absent.
DELIBERATELY_BROAD = {
    "test_epub_retirement.py": 1,         # TTS.rglob: one package
    "test_job_ui.py": 1,                  # the developer harness must be absent from the whole scripts tree
    "test_plan3_boundaries.py": 1,        # same, by name
    "test_plan6_boundaries.py": 1,        # the adapter module exists somewhere under scripts
}


def test_no_guard_over_production_modules_still_walks_scripts_with_a_raw_rglob():
    tests_dir = Path(__file__).resolve().parent
    found = {}
    for path in sorted(tests_dir.glob("test_*.py")):
        count = 0
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "rglob"
                    and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == "*.py"):
                count += 1
        if count:
            found[path.name] = count
    assert found == DELIBERATELY_BROAD, (
        "a production-module guard walks scripts/**/*.py directly; use source_probe.application_python_files "
        f"(or add a justified entry here): {found}")
