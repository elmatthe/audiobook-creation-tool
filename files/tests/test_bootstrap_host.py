"""v0.7.0 — Windows stage 0 (``scripts/shared/bootstrap_host.ps1``) and the launcher's hand-off to it.

A fresh Windows machine may have no Python at all, and ``bootstrap.py`` cannot run without one. v0.7.0 makes the app
portable: stage 0 never installs Python on the computer and never depends on one that happens to be installed. It uses
the app's own Python in ``files/runtime-data/python`` (proved by RUNNING it), and otherwise, only after asking, downloads
the pinned standalone CPython build (python-build-standalone), checks its exact size and SHA-256, unpacks it with
Windows' own ``tar.exe`` into a staging folder inside the app, moves it into place and proves it. What is pinned here:

* the static contract of the script and of the launcher (pins, what is never done);
* its real behaviour on this Windows machine, without downloading anything: a refusal, a tampered archive.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "shared" / "bootstrap_host.ps1"
LAUNCHER = REPO_ROOT / "Setup_and_Run-audiobook-creation-tool.bat"
TEXT = SCRIPT.read_text(encoding="ascii")  # Windows PowerShell 5.1 reads a BOM-less script as ANSI: keep it ASCII
LAUNCH = LAUNCHER.read_text(encoding="ascii")


# --------------------------------------------------------------------------- #
# The contract, read from the files
# --------------------------------------------------------------------------- #
def test_the_python_is_pinned_to_one_verified_standalone_archive():
    assert "$PyVersion = '3.12.15'" in TEXT and "$BuildTag = '20261009'" in TEXT
    assert ("$ArchiveUrl = \"https://github.com/astral-sh/python-build-standalone/releases/download/$BuildTag/"
            "cpython-$PyVersion%2B$BuildTag-x86_64-pc-windows-msvc-install_only.tar.gz\"") in TEXT
    assert "$ArchiveSize = 46352482" in TEXT
    # Published twice independently (the release's SHA256SUMS and GitHub's asset digest), checked 2026-10-30.
    assert re.search(r"\$ArchiveSha256 = '194C8F0D9E0DE6F1C4576E5DFA67819A48C764BE87608B74B8AD43387A57B93B'", TEXT)
    assert "Get-FileHash" in TEXT


def test_python_lives_only_inside_the_app_folder_and_nothing_is_installed_on_the_computer():
    assert "$PythonHome = Join-Path $Repo 'files\\runtime-data\\python'" in TEXT
    assert "$Downloads = Join-Path $Repo 'files\\temp\\bootstrap'" in TEXT
    for forbidden in ("python.org/ftp", "winget", "msiexec", "InstallAllUsers", "PrependPath", "SetEnvironmentVariable",
                      "setx", "RunAs", "-Verb", "HKLM:", "HKCU:", "LOCALAPPDATA", "ProgramFiles", "py.exe",
                      "Get-Command python"):
        assert forbidden not in TEXT, forbidden
    assert "Join-Path $env:SystemRoot 'System32\\tar.exe'" in TEXT  # Windows' own tar, not a downloaded tool


def test_nothing_is_downloaded_without_a_yes_and_the_result_is_proven_by_running_it():
    main = TEXT[TEXT.index("try {\n    $python = Test-Candidate"):]
    consent = main.index("if (-not (Ask-Consent))")
    assert consent < main.index("Get-Archive") < main.index("Install-Local $archive")
    assert "import sys, ssl, venv, ensurepip, tkinter" in TEXT and "'3.12'" in TEXT
    assert "return Test-Candidate (Join-Path $PythonHome 'python.exe')" in TEXT  # unpacking is not proof


def test_the_archive_is_verified_before_it_is_unpacked_and_moved_into_place_in_one_rename():
    install = TEXT[TEXT.index("function Install-Local"):TEXT.index("function Write-Result")]
    get = TEXT[TEXT.index("function Get-Archive"):TEXT.index("function Install-Local")]
    assert get.index("Invoke-WebRequest") < get.index("Test-Archive $part") < get.index("Move-Item")
    assert install.index("& $tar -xzf $Archive -C $staging") < install.index("Move-Item -LiteralPath $unpacked")
    assert "Remove-Item -LiteralPath $staging" in install  # no staging folder is left behind


def test_the_launcher_hands_first_run_and_repair_to_stage_zero_and_reads_its_answer():
    assert 'powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\\shared\\bootstrap_host.ps1" -OutFile "%PYFILE%"' in LAUNCH
    assert 'if "%HOSTRC%"=="2" (' in LAUNCH and 'for /f "usebackq delims=" %%P in ("%PYFILE%") do set "PYCMD=%%P"' in LAUNCH
    assert "winget" not in LAUNCH.lower()
    assert "python.org" not in LAUNCH  # nothing tells the user to install Python on the computer
    fast_path = LAUNCH[:LAUNCH.index(":needsrepair")]
    assert "bootstrap_host.ps1" not in fast_path  # an ordinary launch never runs stage 0
    assert LAUNCHER.read_bytes().count(b"\r\n") == LAUNCH.count("\n")  # cmd.exe needs CRLF throughout


def test_stage_zero_ships_and_its_downloads_and_the_python_never_do():
    from shared import release

    tracked = subprocess.run(["git", "ls-files", "scripts/shared/bootstrap_host.ps1"], cwd=REPO_ROOT, capture_output=True,
                             text=True).stdout.strip()
    assert tracked == "scripts/shared/bootstrap_host.ps1" and not release._is_excluded(Path(tracked))
    for ignored in ("files/temp/bootstrap/cpython-3.12.15.tar.gz", "files/runtime-data/python/python.exe"):
        assert subprocess.run(["git", "check-ignore", "-q", ignored], cwd=REPO_ROOT).returncode == 0, ignored


# --------------------------------------------------------------------------- #
# Real behaviour on this Windows machine (nothing is downloaded)
# --------------------------------------------------------------------------- #
windows_only = pytest.mark.skipif(not sys.platform.startswith("win") or shutil.which("powershell") is None,
                                  reason="Windows PowerShell is needed")


def stage_zero_copy(tmp_path: Path) -> Path:
    """The script in a disposable app folder of its own, so nothing it does can touch this checkout."""
    app = tmp_path / "app"
    (app / "scripts" / "shared").mkdir(parents=True)
    (app / "files").mkdir()
    shutil.copyfile(SCRIPT, app / "scripts" / "shared" / SCRIPT.name)
    return app


def run_stage_zero(app: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                           str(app / "scripts" / "shared" / SCRIPT.name), *args],
                          capture_output=True, text=True, timeout=180)


def listing(app: Path) -> list[str]:
    return sorted(str(p.relative_to(app)) for p in app.rglob("*"))


@windows_only
def test_declining_downloads_nothing_and_says_so(tmp_path):
    app = stage_zero_copy(tmp_path)
    before = listing(app)
    out = tmp_path / "selected.txt"
    result = run_stage_zero(app, "-OutFile", str(out), "-AssumeNo")
    assert result.returncode == 2 and not out.exists(), result.stdout + result.stderr
    assert "Python was not downloaded" in result.stdout
    assert listing(app) == before  # not even an empty download folder


@windows_only
def test_a_tampered_archive_is_rejected_before_anything_is_unpacked(tmp_path):
    app = stage_zero_copy(tmp_path)
    fake = tmp_path / "cpython.tar.gz"
    fake.write_bytes(b"not the pinned python-build-standalone archive")
    out = tmp_path / "selected.txt"
    result = run_stage_zero(app, "-OutFile", str(out), "-AssumeYes", "-ArchivePath", str(fake))
    assert result.returncode == 3 and not out.exists()
    assert "was rejected" in result.stdout and "not 46352482" in result.stdout
    assert "Unpacking" not in result.stdout
    assert not (app / "files" / "runtime-data").exists()


@windows_only
def test_a_broken_copy_of_the_apps_python_is_not_used(tmp_path):
    app = stage_zero_copy(tmp_path)
    broken = app / "files" / "runtime-data" / "python"
    broken.mkdir(parents=True)
    (broken / "python.exe").write_bytes(b"MZ not a python")
    out = tmp_path / "selected.txt"
    result = run_stage_zero(app, "-OutFile", str(out), "-AssumeNo")
    assert result.returncode == 2 and not out.exists()
    assert "does not work; it will be replaced" in result.stdout
