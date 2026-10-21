"""Standalone launcher tests are contained, whatever the import order (v0.6.7 closure review, ACT67-CLR-004).

``test_launcher_smoke.py`` builds the real ``LauncherApp``, which starts the application logger, and the logger prunes old
session logs down to ``logging.max_sessions``. The suite redirects ``shared.paths.LOGS_DIR`` to scratch, but used to do so
only if ``shared.paths`` had already been imported by something else -- true in a full run, false when the file runs on
its own. Run alone, startup then pruned the developer's REAL logs (and the first smoke test rewrote the real settings).

Proving that against the real checkout would repeat the damage, so everything here happens in a DISPOSABLE checkout: a
copy of ``scripts/`` plus the three test files, seeded with synthetic logs and settings, run by a fresh interpreter in
which ``shared.paths`` has not been imported. Nothing here reads or writes the real ``files/runtime-data``.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS = Path(__file__).resolve().parent
SEEDED_LOGS = 45  # comfortably more than the default retention (30), so pruning has something to delete
SETTINGS_BYTES = b'{"last_tool": "mp3_tool", "marker": "synthetic-settings-do-not-touch"}'

# A fresh interpreter, with the precondition the audit named stated and checked before pytest starts.
CHILD = (
    "import sys\n"
    "assert 'shared.paths' not in sys.modules and 'shared.logging_setup' not in sys.modules\n"
    "import pytest\n"
    "sys.exit(pytest.main(sys.argv[1:]))\n"
)


def _tk_works_here() -> bool:
    # Independent of the production proof on purpose, so a weakened proof cannot skip the test that judges it.
    return subprocess.run([sys.executable, "-c", "import tkinter; r = tkinter.Tk(); r.withdraw(); r.destroy()"],
                          capture_output=True, timeout=60).returncode == 0


needs_tk = pytest.mark.skipif(not _tk_works_here(), reason="no working Tk/display for this interpreter")


def _snapshot(folder: Path) -> dict[str, tuple[int, int, str]]:
    """Every file under *folder*: relative path -> (size, mtime_ns, sha256). Missing folder -> empty."""
    result = {}
    if folder.exists():
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                stat = path.stat()
                result[path.relative_to(folder).as_posix()] = (
                    stat.st_size, stat.st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
    return result


def _disposable_checkout(root: Path, *, settings: bytes | None) -> Path:
    """A throwaway repo root holding the application code, the launcher test, and seeded synthetic runtime data."""
    copy = root / "checkout"
    shutil.copytree(REPO_ROOT / "scripts", copy / "scripts", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in ("config.toml", "pytest.ini"):
        shutil.copy2(REPO_ROOT / name, copy / name)
    (copy / "files" / "tests").mkdir(parents=True)
    for name in ("conftest.py", "tk_gate.py", "test_launcher_smoke.py"):
        shutil.copy2(TESTS / name, copy / "files" / "tests" / name)
    logs = copy / "files" / "runtime-data" / "logs"
    logs.mkdir(parents=True)
    for index in range(SEEDED_LOGS):
        (logs / f"session_2001-01-01_{index:06d}.log").write_text(f"synthetic log {index}\n", encoding="utf-8")
    if settings is not None:
        (copy / "files" / "runtime-data" / "settings.json").write_bytes(settings)
    return copy


def _run_smoke(copy: Path, basetemp: Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTEST_ADDOPTS")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-c", CHILD, "files/tests/test_launcher_smoke.py", "-q", "-p", "no:cacheprovider",
         "--basetemp", str(basetemp)],
        cwd=copy, env=env, capture_output=True, text=True, timeout=600)


@needs_tk
@pytest.mark.parametrize("settings", [SETTINGS_BYTES, None], ids=["existing-settings", "absent-settings"])
def test_standalone_launcher_tests_leave_real_runtime_data_alone(tmp_path, settings):
    copy = _disposable_checkout(tmp_path, settings=settings)
    runtime = copy / "files" / "runtime-data"
    before = _snapshot(runtime)
    assert len([p for p in before if p.startswith("logs/")]) == SEEDED_LOGS

    done = _run_smoke(copy, tmp_path / "pytest-base")
    output = done.stdout + done.stderr

    assert done.returncode == 0, output
    assert " passed" in output and " failed" not in output and " error" not in output, output
    after = _snapshot(runtime)
    lost = sorted(set(before) - set(after))
    assert lost == [], f"{len(lost)} existing log/settings file(s) were deleted by the standalone run: {lost[:3]}"
    assert after == before, "the standalone run created or modified files under the (disposable) runtime-data"
    if settings is None:
        assert not (runtime / "settings.json").exists(), "an absent settings file was created outside test scratch"
    else:
        assert (runtime / "settings.json").read_bytes() == SETTINGS_BYTES


@needs_tk
def test_the_standalone_run_builds_all_six_panels(tmp_path):
    copy = _disposable_checkout(tmp_path, settings=SETTINGS_BYTES)
    done = _run_smoke(copy, tmp_path / "pytest-base")
    assert done.returncode == 0, done.stdout + done.stderr
    # The test that builds the six real panels ran, and passed, in the isolated checkout.
    verbose = subprocess.run(
        [sys.executable, "-c", CHILD, "files/tests/test_launcher_smoke.py::test_all_six_tools_build_without_error_panels",
         "-v", "-p", "no:cacheprovider", "--basetemp", str(tmp_path / "pytest-base-2")],
        cwd=copy, env={k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTEST_ADDOPTS")},
        capture_output=True, text=True, timeout=600)
    assert "test_all_six_tools_build_without_error_panels PASSED" in verbose.stdout, verbose.stdout + verbose.stderr
