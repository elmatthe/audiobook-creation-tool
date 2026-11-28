"""Windows stage 0 (``scripts/shared/bootstrap_host.ps1``), its D-6 fallback (``bootstrap_host_fallback.cmd``) and the
launcher's hand-off to them.

A fresh Windows machine may have no Python at all, and ``bootstrap.py`` cannot run without one. Since v0.7.0 the app is
portable: stage 0 never installs Python on the computer and never depends on one that happens to be installed. v0.8.2
Phase 4: it provides the app's own pinned uv 0.13.10 (``files/runtime-data/uv/uv.exe``) and lets that uv install the
pinned CPython 3.12.15 (python-build-standalone 20261009) from ACT's own verified copy of the archive, through ACT's own
download metadata. Every download is checked against its exact size and SHA-256 before it is used, ``uv.exe`` against
its own SHA-256, and the interpreter is proved by RUNNING it. When PowerShell itself cannot run, the launcher does the
same with Windows' own curl.exe, certutil and tar.exe (owner decision D-6); a Python found on PATH is never used.

What is pinned here:

* the static contract of both scripts and of the launcher (pins, order of verification, what is never done);
* their real behaviour on this Windows machine, without downloading anything: a refusal, tampered archives, a broken
  interpreter, a machine without the fallback's utilities.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "shared" / "bootstrap_host.ps1"
FALLBACK = REPO_ROOT / "scripts" / "shared" / "bootstrap_host_fallback.cmd"
LAUNCHER = REPO_ROOT / "Setup_and_Run-audiobook-creation-tool.bat"
TEXT = SCRIPT.read_text(encoding="ascii")  # Windows PowerShell 5.1 reads a BOM-less script as ANSI: keep it ASCII
CMD = FALLBACK.read_text(encoding="ascii")
LAUNCH = LAUNCHER.read_text(encoding="ascii")

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from shared import uv_runner  # noqa: E402  (standard library only)

PINS = uv_runner.WINDOWS


# --------------------------------------------------------------------------- #
# The contract, read from the files
# --------------------------------------------------------------------------- #
def test_uv_and_the_python_are_pinned_to_the_same_verified_files_as_the_app():
    """One set of pins: the PowerShell route, the fallback and shared/uv_runner.py cannot drift apart."""
    assert f"$UvVersion = '{uv_runner.UV_VERSION}'" in TEXT and f'set "UV_VERSION={uv_runner.UV_VERSION}"' in CMD
    assert f"$UvArchiveName = '{PINS.uv_archive}'" in TEXT and f'set "UV_ZIP={PINS.uv_archive}"' in CMD
    assert f"$UvSize = {PINS.uv_size}" in TEXT and f'set "UV_SIZE={PINS.uv_size}"' in CMD
    assert f"$UvSha256 = '{PINS.uv_sha256.upper()}'" in TEXT and f'set "UV_SHA256={PINS.uv_sha256}"' in CMD
    assert f"$UvExeSha256 = '{PINS.uv_exe_sha256.upper()}'" in TEXT
    assert f'set "UV_EXE_SHA256={PINS.uv_exe_sha256}"' in CMD
    assert f"$PyVersion = '{uv_runner.PYTHON_VERSION}'" in TEXT and f"$BuildTag = '{uv_runner.PYTHON_BUILD}'" in TEXT
    assert f"$PyKey = '{PINS.python_key}'" in TEXT and f'set "PY_KEY={PINS.python_key}"' in CMD
    assert f"$PyMinorKey = '{PINS.python_minor_key}'" in TEXT
    assert f'set "PY_ARCHIVE={PINS.python_archive}"' in CMD
    assert f"$ArchiveSize = {PINS.python_size}" in TEXT and f'set "PY_SIZE={PINS.python_size}"' in CMD
    assert f"$ArchiveSha256 = '{PINS.python_sha256.upper()}'" in TEXT and f'set "PY_SHA256={PINS.python_sha256}"' in CMD
    assert f"$PySysVersion = '{PINS.python_sys_version}'" in TEXT
    assert f'set "PY_SYS_VERSION={PINS.python_sys_version}"' in CMD
    assert ("$ArchiveUrl = \"https://github.com/astral-sh/python-build-standalone/releases/download/$BuildTag/"
            "cpython-$PyVersion%2B$BuildTag-x86_64-pc-windows-msvc-install_only.tar.gz\"") in TEXT
    assert f'set "PY_URL={PINS.python_url.replace("%", "%%")}"' in CMD
    assert '$UvUrl = "https://github.com/astral-sh/uv/releases/download/$UvVersion/$UvArchiveName"' in TEXT


def test_the_python_and_uv_live_only_inside_the_app_folder_and_nothing_is_installed_on_the_computer():
    assert "$UvHome = Join-Path $Repo 'files\\runtime-data\\uv'" in TEXT
    assert "$Downloads = Join-Path $Repo 'files\\temp\\bootstrap'" in TEXT
    assert "$DownloadsJson = Join-Path $Repo 'scripts\\shared\\python-downloads.json'" in TEXT
    for text in (TEXT, CMD):
        for forbidden in ("python.org/ftp", "winget", "msiexec", "InstallAllUsers", "PrependPath",
                          "SetEnvironmentVariable", "setx", "RunAs", "-Verb", "HKLM:", "HKCU:", "reg add", "reg.exe",
                          "LOCALAPPDATA", "ProgramFiles", "py.exe", "Get-Command python", "where py", "where python",
                          "astral.sh/uv/install", "irm ", "iex "):
            assert forbidden.lower() not in text.lower(), forbidden
    # uv itself is kept off the registry, out of any bin folder and away from the computer's settings.
    for flag in ("'--no-bin'", "'--no-registry'", "'--no-config'"):
        assert flag in TEXT, flag
    for flag in ("--no-bin", "--no-registry", "--no-config"):
        assert flag in CMD, flag
    for setting in ("UV_NO_CONFIG", "UV_PYTHON_INSTALL_REGISTRY", "UV_PYTHON_NO_REGISTRY", "UV_PYTHON_INSTALL_BIN",
                    "UV_PYTHON_PREFERENCE", "UV_PYTHON_DOWNLOADS", "UV_PYTHON_DOWNLOADS_JSON_URL", "UV_CACHE_DIR",
                    "UV_PYTHON_CACHE_DIR", "UV_TOOL_DIR", "UV_CREDENTIALS_DIR"):
        assert f"'{setting}'" in TEXT and f'set "{setting}=' in CMD, setting
    assert "Join-Path $env:SystemRoot 'System32\\tar.exe'" in TEXT  # Windows' own tar, not a downloaded tool


def test_nothing_is_downloaded_without_a_yes_and_the_result_is_proven_by_running_it():
    main = TEXT[TEXT.index("try {\n    $uvOk = Test-Uv"):]
    consent = main.index("if (-not (Ask-Consent $items))")
    assert consent < main.index("Get-Verified $UvArchivePath") < main.index("Install-Uv $zip")
    assert consent < main.index("Get-Verified $ArchivePath") < main.index("Save-Archive $archive")
    assert main.index("Save-Archive $archive") < main.index("Install-Managed")
    assert "import os, sys, ssl, venv, ensurepip, tkinter" in TEXT and "print(sys.version)" in TEXT
    assert "$lines[-1] -ne $PySysVersion" in TEXT, "exactly the pinned build, not merely some 3.12"
    # Its own path goes TO the interpreter (as Unicode) and is compared there; it is never read back from its output,
    # which Python writes in the ANSI code page (an accented folder name came back garbled: Phase 4 fresh-copy run).
    assert "assert os.path.samefile(sys.executable, sys.argv[1])" in TEXT
    assert "print(sys.executable)" not in TEXT and "return $Exe" in TEXT
    assert "$python = Test-Python" in main[main.index("Install-Managed"):], "installing is not proof"
    fallback = CMD[CMD.index("REM ---- one question"):]
    assert fallback.index('"%CHOICE%" /C YN') < fallback.index("call :fetch")


def test_every_download_is_verified_before_it_is_used_and_moved_into_place_whole():
    get = TEXT[TEXT.index("function Get-Verified"):TEXT.index("function Install-Uv")]
    assert get.index("Invoke-WebRequest") < get.index("Test-File $part") < get.index("Move-Item")
    install = TEXT[TEXT.index("function Install-Uv"):TEXT.index("function Save-Archive")]
    assert install.index("& $tar -xf $Zip -C $staging uv.exe") < install.index("(Get-Sha256 $unpacked) -ne $UvExeSha256")
    assert install.index("(Get-Sha256 $unpacked) -ne $UvExeSha256") < install.index("Move-Item")
    assert "Remove-Item -LiteralPath $staging" in install  # no staging folder is left behind
    save = TEXT[TEXT.index("function Save-Archive"):TEXT.index("function Install-Managed")]
    assert "Test-File $MirrorArchive $ArchiveSize $ArchiveSha256" in save
    fetch = CMD[CMD.index("\n:fetch\n"):CMD.index("\n:probe_python\n")]
    assert fetch.index('"%CURL%"') < fetch.index('call :verify "%~2.part"') < fetch.index('move /y "%~2.part"')
    assert "--proto =https --proto-redir =https" in fetch, "HTTPS only, redirects included"
    unpack = CMD[CMD.index('"%TAR%" -xf'):CMD.index("\n:archive\n")]
    assert unpack.index('call :sha256 "%STAGE%\\uv.exe"') < unpack.index('move /y "%STAGE%\\uv.exe"')


def test_uv_installs_the_python_offline_from_the_kept_archive_in_a_scratch_folder_of_its_own():
    managed = TEXT[TEXT.index("function Install-Managed"):TEXT.index("function Write-Result")]
    assert "'--mirror', $mirror" in managed and "$mirror = ([System.Uri]$MirrorDir).AbsoluteUri" in managed
    assert "'UV_PYTHON_CACHE_DIR' = (Join-Path $scratch 'pyc')" in managed, "a refused archive never sticks"
    assert "Remove-Item -LiteralPath $scratch -Recurse -Force" in managed
    assert "'^(UV_|PIP_|XDG_|CONDA_|PYTHON|SSL_CERT_)'" in managed, "the computer's settings are removed first"
    assert "--mirror \"!MIRRORURI!\"" in CMD and 'set "UV_PYTHON_CACHE_DIR=%SCRATCH%\\pyc"' in CMD
    assert 'rmdir /s /q "%SCRATCH%"' in CMD
    assert "$MirrorArchive = Join-Path (Join-Path $MirrorDir $BuildTag) $ArchiveName" in TEXT
    assert 'set "MIRRORFILE=%MIRROR%\\%BUILD_TAG%\\%PY_ARCHIVE%"' in CMD


def test_the_launcher_hands_first_run_and_repair_to_stage_zero_and_falls_back_only_to_windows_own_tools():
    assert 'powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\\shared\\bootstrap_host.ps1" -OutFile "%PYFILE%"' in LAUNCH
    assert 'call "scripts\\shared\\bootstrap_host_fallback.cmd" "%PYFILE%"' in LAUNCH
    assert LAUNCH.count('if "%HOSTRC%"=="2" (') == 2, "a No in either route cancels cleanly"
    assert LAUNCH.count('for /f "usebackq delims=" %%P in ("%PYFILE%") do set "PYCMD=%%P"') == 2
    fallback = LAUNCH[LAUNCH.index('if defined PYCMD goto havepython'):LAUNCH.index(":havepython")]
    assert 'if "%HOSTRC%"=="3" goto havepython' in fallback, "a stage 0 that ran and failed is not retried blindly"
    lowered = LAUNCH.lower()
    for forbidden in ("winget", "where py", "where python", "python.org"):
        assert forbidden not in lowered, forbidden
    fast_path = LAUNCH[:LAUNCH.index(":needsrepair")]
    assert "bootstrap_host" not in fast_path  # an ordinary launch never runs stage 0
    assert "EnableDelayedExpansion" not in LAUNCH, "a '!' in the folder's path must survive"
    assert LAUNCHER.read_bytes().count(b"\r\n") == LAUNCH.count("\n")  # cmd.exe needs CRLF throughout
    assert FALLBACK.read_bytes().count(b"\r\n") == CMD.count("\n")


def test_stage_zero_reports_the_interpreter_relative_to_the_app_folder_in_plain_ascii():
    """cmd.exe reads the answer in the console's code page; a relative ASCII path survives any folder name and the
    launcher runs it from the app's folder."""
    relative = f"files\\runtime-data\\uv\\python\\{PINS.python_key}\\python.exe"
    write = TEXT[TEXT.index("function Write-Result"):TEXT.index("try {\n    $uvOk = Test-Uv")]
    assert '"files\\runtime-data\\uv\\python\\$PyKey\\python.exe"' in write and "ASCIIEncoding" in write
    assert '>"%OUTFILE%" echo(files\\runtime-data\\uv\\python\\%PY_KEY%\\python.exe' in CMD
    assert relative.isascii()
    assert 'cd /d "%~dp0"' in LAUNCH and LAUNCH.index('cd /d "%~dp0"') < LAUNCH.index('"%PYCMD%" "%BOOTSTRAP%"')


def test_the_fallback_uses_only_windows_own_programs_and_says_what_is_missing():
    for program in ("curl.exe", "tar.exe", "certutil.exe", "choice.exe"):
        assert f"%SystemRoot%\\System32\\{program}" in CMD, program
    commands = [line for line in CMD.splitlines() if not line.lstrip().upper().startswith(("REM", "ECHO"))]
    assert not any("powershell" in line.lower() for line in commands), "the fallback never starts PowerShell"
    # (Its message for a Windows without these programs is held here statically: cmd.exe itself cannot be started
    # with a SystemRoot that lacks them, so there is no honest way to run that branch in a test.)
    missing = CMD[CMD.index('for %%T in ("%CURL%"'):CMD.index("REM ---- what is there already")]
    assert "exit /b 3" in missing and "Windows 10 version 1803 or later" in missing


def test_stage_zero_ships_and_its_downloads_uv_and_the_python_never_do():
    from shared import release

    for script in ("scripts/shared/bootstrap_host.ps1", "scripts/shared/bootstrap_host_fallback.cmd",
                   "scripts/shared/python-downloads.json"):
        tracked = subprocess.run(["git", "ls-files", script], cwd=REPO_ROOT, capture_output=True, text=True).stdout
        assert tracked.strip() == script and not release._is_excluded(Path(script)), script
    for ignored in ("files/temp/bootstrap/uv-x86_64-pc-windows-msvc.zip", "files/runtime-data/uv/uv.exe",
                    "files/runtime-data/uv/mirror/20261009/x.tar.gz",
                    "files/runtime-data/uv/python/cpython-3.12.15-windows-x86_64-none/python.exe",
                    "files/runtime-data/uvc/CACHEDIR.TAG", "files/runtime-data/python/python.exe"):
        assert subprocess.run(["git", "check-ignore", "-q", ignored], cwd=REPO_ROOT).returncode == 0, ignored


def test_stage_zero_hashes_without_a_module_cmdlet_and_the_launcher_clears_an_inherited_module_path():
    """2026-10-31: started from a PowerShell 7 window, Windows PowerShell 5.1 inherits PowerShell 7's PSModulePath and
    cannot load Get-FileHash, so stage 0 downloaded Python and then failed. It now hashes with .NET, and the launcher
    clears the variable for its stage-0 call (5.1 then uses its own module path)."""
    assert "Get-FileHash" not in TEXT.replace("not Get-FileHash", "")
    assert "[System.Security.Cryptography.SHA256]::Create()" in TEXT
    cleared = LAUNCH.index('set "PSModulePath="')
    assert cleared < LAUNCH.index('powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\\shared\\bootstrap_host.ps1"')
    assert LAUNCH.index("setlocal EnableExtensions") < cleared, "local to the launcher, never the user's session"


# --------------------------------------------------------------------------- #
# Real behaviour on this Windows machine (nothing is downloaded)
# --------------------------------------------------------------------------- #
windows_only = pytest.mark.skipif(not sys.platform.startswith("win") or shutil.which("powershell") is None,
                                  reason="Windows PowerShell is needed")


def stage_zero_copy(tmp_path: Path) -> Path:
    """Both scripts in a disposable app folder of their own (with a space and non-ASCII letters in its path), so
    nothing they do can touch this checkout."""
    app = tmp_path / "My Apps" / "Livres \u00e9t\u00e9"
    (app / "scripts" / "shared").mkdir(parents=True)
    (app / "files").mkdir()
    for source in (SCRIPT, FALLBACK, REPO_ROOT / "scripts" / "shared" / "python-downloads.json"):
        shutil.copyfile(source, app / "scripts" / "shared" / source.name)
    return app


def run_stage_zero(app: Path, *args: str, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                           str(app / "scripts" / "shared" / SCRIPT.name), *args],
                          capture_output=True, text=True, timeout=180, env=env)


def listing(app: Path) -> list[str]:
    return sorted(str(p.relative_to(app)) for p in app.rglob("*"))


@windows_only
def test_declining_downloads_nothing_and_says_so(tmp_path):
    app = stage_zero_copy(tmp_path)
    before = listing(app)
    out = tmp_path / "selected.txt"
    result = run_stage_zero(app, "-OutFile", str(out), "-AssumeNo")
    assert result.returncode == 2 and not out.exists(), result.stdout + result.stderr
    assert "Nothing was downloaded" in result.stdout
    assert "has not been downloaded yet" in result.stdout and "has not been installed yet" in result.stdout
    assert listing(app) == before  # not even an empty download folder


@windows_only
def test_a_tampered_uv_archive_is_rejected_before_anything_is_unpacked(tmp_path):
    app = stage_zero_copy(tmp_path)
    fake_uv, fake_py = tmp_path / "uv.zip", tmp_path / "cpython.tar.gz"
    fake_uv.write_bytes(b"not the pinned uv archive")
    fake_py.write_bytes(b"not the pinned python-build-standalone archive")
    out = tmp_path / "selected.txt"
    result = run_stage_zero(app, "-OutFile", str(out), "-AssumeYes", "-UvArchivePath", str(fake_uv),
                            "-ArchivePath", str(fake_py))
    assert result.returncode == 3 and not out.exists(), result.stdout + result.stderr
    assert "was rejected" in result.stdout and f"not {PINS.uv_size}" in result.stdout
    assert "Unpacking" not in result.stdout and "Installing Python" not in result.stdout
    assert not (app / "files" / "runtime-data").exists()


def _powershell7_module_path() -> str:
    """A PSModulePath as PowerShell 7 hands it down (its own folders first), from this machine where possible."""
    folders = [p for p in os.environ.get("PSModulePath", "").split(";") if p and "WindowsPowerShell" not in p]
    for candidate in (r"C:\Program Files\PowerShell\7\Modules", r"C:\Program Files\PowerShell\Modules"):
        if Path(candidate).is_dir() and candidate not in folders:
            folders.append(candidate)
    return ";".join([*folders, r"C:\Windows\system32\WindowsPowerShell\v1.0\Modules"])


@windows_only
def test_a_right_sized_archive_with_the_wrong_hash_is_rejected_by_its_sha256_under_a_powershell7_module_path(tmp_path):
    app = stage_zero_copy(tmp_path)
    fake = tmp_path / "uv.zip"
    with open(fake, "wb") as handle:
        handle.truncate(PINS.uv_size)  # the pinned size, so only the SHA-256 can refuse it
    out = tmp_path / "selected.txt"
    env = {**os.environ, "PSModulePath": _powershell7_module_path()}
    result = run_stage_zero(app, "-OutFile", str(out), "-AssumeYes", "-UvArchivePath", str(fake),
                            "-ArchivePath", str(fake), env=env)
    assert result.returncode == 3 and not out.exists(), result.stdout + result.stderr
    assert re.search(r"its SHA-256 is [0-9A-F]{64}, not the pinned", result.stdout), result.stdout
    assert "not recognized" not in result.stdout
    assert not (app / "files" / "runtime-data").exists()


@windows_only
def test_a_broken_copy_of_the_apps_python_is_not_used(tmp_path):
    app = stage_zero_copy(tmp_path)
    broken = app / "files" / "runtime-data" / "uv" / "python" / PINS.python_key
    broken.mkdir(parents=True)
    (broken / "python.exe").write_bytes(b"MZ not a python")
    (broken / "BUILD").write_text(uv_runner.PYTHON_BUILD, encoding="ascii")
    out = tmp_path / "selected.txt"
    result = run_stage_zero(app, "-OutFile", str(out), "-AssumeNo")
    assert result.returncode == 2 and not out.exists()
    assert "does not work; it will be replaced" in result.stdout


@windows_only
def test_the_python_of_an_earlier_version_is_neither_used_nor_touched(tmp_path):
    """files/runtime-data/python (v0.7.0 - v0.8.1) still runs the voice engines installed under it; stage 0 neither
    selects it nor changes it."""
    app = stage_zero_copy(tmp_path)
    legacy = app / "files" / "runtime-data" / "python"
    legacy.mkdir(parents=True)
    (legacy / "python.exe").write_bytes(b"MZ the earlier version's python")
    before = (legacy / "python.exe").read_bytes()
    out = tmp_path / "selected.txt"
    result = run_stage_zero(app, "-OutFile", str(out), "-AssumeNo")
    assert result.returncode == 2 and not out.exists()
    assert (legacy / "python.exe").read_bytes() == before


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="cmd.exe is needed")
def test_the_fallback_declines_when_no_one_can_answer_and_downloads_nothing(tmp_path):
    """Without a console to answer choice.exe the answer is No: nothing is downloaded, nothing is written."""
    app = stage_zero_copy(tmp_path)
    before = listing(app)
    out = tmp_path / "selected.txt"
    result = subprocess.run(["cmd", "/d", "/c", str(app / "scripts" / "shared" / FALLBACK.name), str(out)],
                            capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "Nothing was downloaded" in result.stdout and not out.exists()
    assert listing(app) == before
