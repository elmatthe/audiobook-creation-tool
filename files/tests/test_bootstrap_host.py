"""v0.6.7 — Windows stage 0 (``scripts/shared/bootstrap_host.ps1``) and the launcher's hand-off to it.

A fresh Windows machine may have no Python at all, and ``bootstrap.py`` cannot run without one. Stage 0 finds a working
3.11/3.12 by RUNNING it, and otherwise installs the pinned python.org 3.12.10 for this user only after asking: verified by
size, SHA-256 and signature, no administrator rights, no PATH change, winget only as a fallback. What is pinned here:

* the static contract of the script and of the launcher (pins, installer switches, what is never done);
* its real behaviour on this Windows machine, without installing anything: discovery, a refusal, a tampered installer.
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
def test_the_installer_is_pinned_to_one_official_verified_file():
    assert "$InstallerUrl = \"https://www.python.org/ftp/python/$PyVersion/$InstallerName\"" in TEXT
    assert "$PyVersion = '3.12.10'" in TEXT and "$InstallerName = \"python-$PyVersion-amd64.exe\"" in TEXT
    assert "$InstallerSize = 26964224" in TEXT
    assert re.search(r"\$InstallerSha256 = '67B5635E80EA51072B87941312D00EC8927C4DB9BA18938F7AD2D27B328B95FB'", TEXT)
    assert "Get-FileHash" in TEXT and "Get-AuthenticodeSignature" in TEXT and "Python Software Foundation" in TEXT


def test_the_install_is_per_user_and_changes_no_path_or_association():
    for switch in ("/quiet", "InstallAllUsers=0", "PrependPath=0", "AssociateFiles=0", "Shortcuts=0", "Include_launcher=0",
                   "Include_tcltk=1", "Include_pip=1"):
        assert f"'{switch}'" in TEXT, switch
    for forbidden in ("SetEnvironmentVariable", "setx", "RunAs", "-Verb", "HKLM:", "InstallAllUsers=1", "PrependPath=1"):
        assert forbidden not in TEXT, forbidden
    assert "--scope user" in TEXT  # the winget fallback is per-user too


def test_nothing_is_installed_without_a_yes_and_a_candidate_is_proven_by_running_it():
    install_calls = [m.start() for m in re.finditer(r"Install-Direct \$installer|Install-Winget\b(?!\s*\{)", TEXT)]
    consent = TEXT.index("if (-not (Ask-Consent))")
    assert install_calls and all(position > consent for position in install_calls)
    assert "import sys, ssl, venv, tkinter" in TEXT and "'3.12'" in TEXT and "'3.11'" in TEXT
    assert "*\\WindowsApps\\*" in TEXT  # the Microsoft Store alias is never run
    assert "return Test-Candidate @((Join-Path $TargetDir 'python.exe'))" in TEXT  # an exit code is not proof


def test_winget_is_only_a_fallback_after_the_direct_route():
    main = TEXT[TEXT.index("try {\n    if (-not $IgnoreInstalled)"):]
    assert main.index("Install-Direct $installer") < main.index("Install-Winget")


def test_the_launcher_hands_first_run_and_repair_to_stage_zero_and_reads_its_answer():
    assert 'powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\\shared\\bootstrap_host.ps1" -OutFile "%PYFILE%"' in LAUNCH
    assert 'if "%HOSTRC%"=="2" (' in LAUNCH and 'for /f "usebackq delims=" %%P in ("%PYFILE%") do set "PYCMD=%%P"' in LAUNCH
    assert "winget install" not in LAUNCH  # acquisition lives in stage 0 now, not in the thin launcher
    fast_path = LAUNCH[:LAUNCH.index(":needsrepair")]
    assert "bootstrap_host.ps1" not in fast_path  # an ordinary launch never runs stage 0
    assert LAUNCHER.read_bytes().count(b"\r\n") == LAUNCH.count("\n")  # cmd.exe needs CRLF throughout


def test_stage_zero_ships_and_its_downloads_never_do():
    from shared import release

    tracked = subprocess.run(["git", "ls-files", "scripts/shared/bootstrap_host.ps1"], cwd=REPO_ROOT, capture_output=True,
                             text=True).stdout.strip()
    assert tracked == "scripts/shared/bootstrap_host.ps1" and not release._is_excluded(Path(tracked))
    assert subprocess.run(["git", "check-ignore", "-q", "files/temp/bootstrap/python-3.12.10-amd64.exe"],
                          cwd=REPO_ROOT).returncode == 0


# --------------------------------------------------------------------------- #
# Real behaviour on this Windows machine (nothing is installed)
# --------------------------------------------------------------------------- #
windows_only = pytest.mark.skipif(not sys.platform.startswith("win") or shutil.which("powershell") is None,
                                  reason="Windows PowerShell is needed")


def run_stage_zero(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), *args],
                          capture_output=True, text=True, timeout=180)


@windows_only
def test_an_installed_compatible_python_is_found_proven_and_reported(tmp_path):
    out = tmp_path / "selected.txt"
    result = run_stage_zero("-OutFile", str(out), "-AssumeNo")  # a No must not matter when nothing needs installing
    if result.returncode == 2:
        pytest.skip("no Python 3.11/3.12 on this machine")
    assert result.returncode == 0, result.stdout + result.stderr
    chosen = Path(out.read_text(encoding="utf-8"))
    probe = subprocess.run([str(chosen), "-c", "import sys, ssl, venv, tkinter; print('%d.%d' % sys.version_info[:2])"],
                           capture_output=True, text=True)
    assert probe.stdout.strip() in ("3.11", "3.12") and "WindowsApps" not in str(chosen)


@windows_only
def test_declining_installs_nothing_and_says_so(tmp_path):
    out = tmp_path / "selected.txt"
    result = run_stage_zero("-OutFile", str(out), "-IgnoreInstalled", "-AssumeNo")
    assert result.returncode == 2 and not out.exists()
    assert "Python was not installed" in result.stdout


@windows_only
def test_a_tampered_installer_is_rejected_and_nothing_else_is_tried(tmp_path):
    fake = tmp_path / "python-3.12.10-amd64.exe"
    fake.write_bytes(b"MZ not the python.org installer")
    out = tmp_path / "selected.txt"
    result = run_stage_zero("-OutFile", str(out), "-IgnoreInstalled", "-AssumeYes", "-NoWinget", "-InstallerPath", str(fake))
    assert result.returncode == 3 and not out.exists()
    assert "was rejected" in result.stdout and "not 26964224" in result.stdout
    assert "Installing Python" not in result.stdout  # it never got as far as running anything
