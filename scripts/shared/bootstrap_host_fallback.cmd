@echo off
REM ============================================================================================================
REM  bootstrap_host_fallback.cmd - stage 0 when PowerShell cannot run (owner decision D-6, v0.8.2 Phase 4).
REM
REM  Setup_and_Run-audiobook-creation-tool.bat calls this only when bootstrap_host.ps1 did not run at all (for
REM  example an IT policy blocks PowerShell scripts). It does the same job with programs that ship with Windows 10
REM  1803 and later, and needs neither PowerShell nor any Python on the computer:
REM
REM    curl.exe      downloads over HTTPS only (no redirect to anything else)
REM    certutil.exe  computes each file's SHA-256, compared with the pins below BEFORE the file is used
REM    tar.exe       unpacks uv.exe from the verified ZIP (it refuses absolute and ".." paths)
REM
REM  1. uv: files\runtime-data\uv\uv.exe must be exactly the pinned program (its SHA-256).
REM  2. Python: the pinned build in files\runtime-data\uv\python\..., proved by running it (its sys.version, uv's
REM     BUILD stamp, ssl, venv, ensurepip). Tk is proved afterwards by bootstrap.py, which can bound a hung window.
REM  3. Anything missing: ask ONCE, then download, verify, and let the pinned uv install Python from the verified
REM     archive kept in files\runtime-data\uv\mirror (no network for that step), with a contained environment.
REM  4. Write the interpreter's path, relative to the app's folder, to the file named by the first argument.
REM
REM  Exit codes as bootstrap_host.ps1: 0 = done, 2 = the user declined (nothing downloaded), 3 = it could not be done.
REM  Nothing is installed on the computer and nothing outside the app's folder is written.
REM ============================================================================================================
setlocal EnableExtensions EnableDelayedExpansion
set "OUTFILE=%~1"
cd /d "%~dp0..\.." || exit /b 3
set "REPO=%CD%"

REM Pins (keep in step with scripts\shared\uv_runner.py and bootstrap_host.ps1; a test holds them together).
set "UV_VERSION=0.13.10"
set "UV_ZIP=uv-x86_64-pc-windows-msvc.zip"
set "UV_URL=https://github.com/astral-sh/uv/releases/download/%UV_VERSION%/%UV_ZIP%"
set "UV_SIZE=15641577"
set "UV_SHA256=297b3881fe1adfb922becc2c1613202abb41dc83ea5ff43d472aa087ca1f8683"
set "UV_EXE_SHA256=9f9f3631112f847c81b2063637ce01f4dd8d65e8ac2a8f4bb1c121f7effa5c76"
set "PY_VERSION=3.12.15"
set "BUILD_TAG=20261009"
set "PY_KEY=cpython-3.12.15-windows-x86_64-none"
set "PY_ARCHIVE=cpython-3.12.15+20261009-x86_64-pc-windows-msvc-install_only.tar.gz"
set "PY_URL=https://github.com/astral-sh/python-build-standalone/releases/download/20261009/cpython-3.12.15%%2B20261009-x86_64-pc-windows-msvc-install_only.tar.gz"
set "PY_SIZE=46352482"
set "PY_SHA256=194c8f0d9e0de6f1c4576e5dfa67819a48c764be87608b74b8ad43387a57b93b"
set "PY_SYS_VERSION=3.12.15 (main, Oct  9 2026, 15:21:55) [MSC v.1944 64 bit (AMD64)]"

set "DOWNLOADS=%REPO%\files\temp\bootstrap"
set "UVHOME=%REPO%\files\runtime-data\uv"
set "UVEXE=%UVHOME%\uv.exe"
set "PYINSTALL=%UVHOME%\python"
set "PYHOME=%PYINSTALL%\%PY_KEY%"
set "PYEXE=%PYHOME%\python.exe"
set "MIRROR=%UVHOME%\mirror"
set "MIRRORFILE=%MIRROR%\%BUILD_TAG%\%PY_ARCHIVE%"
set "CURL=%SystemRoot%\System32\curl.exe"
set "TAR=%SystemRoot%\System32\tar.exe"
set "CERTUTIL=%SystemRoot%\System32\certutil.exe"
set "CHOICE=%SystemRoot%\System32\choice.exe"

for %%T in ("%CURL%" "%TAR%" "%CERTUTIL%" "%CHOICE%") do (
    if not exist "%%~T" (
        echo This Windows does not have %%~nxT, which setting the app up without PowerShell needs.
        echo Allow PowerShell scripts for this app, or use Windows 10 version 1803 or later, then run setup again.
        exit /b 3
    )
)

REM ---- what is there already ------------------------------------------------------------------------------
set "UVOK="
call :sha256 "%UVEXE%" UVHASH
if /i "!UVHASH!"=="%UV_EXE_SHA256%" set "UVOK=1"
call :probe_python
set "NEEDARCHIVE="
if not defined PYOK (
    call :verify "%MIRRORFILE%" %PY_SIZE% %PY_SHA256%
    if errorlevel 1 set "NEEDARCHIVE=1"
)
if defined UVOK if defined PYOK goto :done

if not defined UVOK echo The app's package tool ^(uv %UV_VERSION%^) is missing or is not the pinned program.
if not defined PYOK echo The app's own Python has not been installed yet, or does not work.

REM ---- one question for everything that must be downloaded ---------------------------------------------------
if defined UVOK if not defined NEEDARCHIVE goto :install
echo.
echo The Audiobook Creation Tool runs on its own copy of Python and its own package tool, kept inside this folder.
echo Download them now?
if not defined UVOK echo   - uv %UV_VERSION%, the package tool from Astral ^(about 16 MB^)
if defined NEEDARCHIVE echo   - Python %PY_VERSION%, the standalone CPython build from python-build-standalone ^(about 46 MB^)
echo   - kept only inside this folder ^(files\runtime-data\uv^); nothing is installed on the computer
echo   - no administrator rights; your PATH and file associations are not changed
"%CHOICE%" /C YN /N /M "Press Y to download, or N to stop without downloading anything: "
if errorlevel 2 (
    echo Nothing was downloaded. Run the setup again whenever you are ready.
    exit /b 2
)
if not exist "%DOWNLOADS%" mkdir "%DOWNLOADS%" || exit /b 3

if defined UVOK goto :archive
call :fetch "%UV_URL%" "%DOWNLOADS%\%UV_ZIP%" %UV_SIZE% %UV_SHA256% "uv package tool" || exit /b 3
set "STAGE=%DOWNLOADS%\uv-staging"
if exist "%STAGE%" rmdir /s /q "%STAGE%"
mkdir "%STAGE%" || exit /b 3
echo Unpacking uv %UV_VERSION% into this folder...
"%TAR%" -xf "%DOWNLOADS%\%UV_ZIP%" -C "%STAGE%" uv.exe
if errorlevel 1 (
    echo tar.exe could not unpack the uv archive.
    exit /b 3
)
call :sha256 "%STAGE%\uv.exe" STAGEDHASH
if /i not "!STAGEDHASH!"=="%UV_EXE_SHA256%" (
    echo The unpacked uv.exe is not the pinned program; it was not used.
    rmdir /s /q "%STAGE%"
    exit /b 3
)
if not exist "%UVHOME%" mkdir "%UVHOME%" || exit /b 3
move /y "%STAGE%\uv.exe" "%UVEXE%" >nul || exit /b 3
rmdir /s /q "%STAGE%"
del /q "%DOWNLOADS%\%UV_ZIP%" 2>nul

:archive
if not defined NEEDARCHIVE goto :install
call :fetch "%PY_URL%" "%DOWNLOADS%\%PY_ARCHIVE%" %PY_SIZE% %PY_SHA256% "Python archive" || exit /b 3
if not exist "%MIRROR%\%BUILD_TAG%" mkdir "%MIRROR%\%BUILD_TAG%" || exit /b 3
move /y "%DOWNLOADS%\%PY_ARCHIVE%" "%MIRRORFILE%" >nul || exit /b 3

:install
if defined PYOK goto :done
REM ---- uv installs the pinned build from the kept archive, contained (shared\uv_runner.py does the same) --------
for %%P in (UV_ PIP_ XDG_ CONDA_ PYTHON SSL_CERT_) do (
    for /f "delims==" %%V in ('set %%P 2^>nul') do set "%%V="
)
set "VIRTUAL_ENV="
set "OPID=%RANDOM%%RANDOM%"
set "SCRATCH=%UVHOME%\t\b%OPID%"
mkdir "%SCRATCH%\tmp" "%SCRATCH%\pyc" || exit /b 3
set "UV_NO_CONFIG=1"
set "UV_NO_ENV_FILE=1"
set "UV_CACHE_DIR=%REPO%\files\runtime-data\uvc"
set "UV_PYTHON_INSTALL_DIR=%PYINSTALL%"
set "UV_PYTHON_CACHE_DIR=%SCRATCH%\pyc"
set "UV_PYTHON_BIN_DIR=%UVHOME%\home\pybin"
set "UV_PYTHON_INSTALL_BIN=0"
set "UV_PYTHON_INSTALL_REGISTRY=0"
set "UV_PYTHON_NO_REGISTRY=1"
set "UV_PYTHON_PREFERENCE=only-managed"
set "UV_PYTHON_DOWNLOADS=manual"
set "UV_PYTHON_DOWNLOADS_JSON_URL=%REPO%\scripts\shared\python-downloads.json"
set "UV_TOOL_DIR=%UVHOME%\home\tools"
set "UV_TOOL_BIN_DIR=%UVHOME%\home\tool-bin"
set "UV_CREDENTIALS_DIR=%UVHOME%\home\credentials"
set "UV_NO_PROGRESS=1"
set "NO_COLOR=1"
set "TEMP=%SCRATCH%\tmp"
set "TMP=%SCRATCH%\tmp"
set "MIRRORURI=%MIRROR:\=/%"
set "MIRRORURI=file:///!MIRRORURI: =%%20!"
set "REINSTALL="
if exist "%PYHOME%" set "REINSTALL=--reinstall"
echo Installing Python %PY_VERSION% into this folder ^(from the verified copy kept here; nothing is downloaded^)...
"%UVEXE%" python install %PY_VERSION% --mirror "!MIRRORURI!" --python-downloads-json-url "%UV_PYTHON_DOWNLOADS_JSON_URL%" --no-bin --no-registry --no-config --color never --no-progress %REINSTALL%
set "UVRC=%errorlevel%"
rmdir /s /q "%SCRATCH%" 2>nul
if not "%UVRC%"=="0" (
    echo uv could not install the app's Python ^(exit %UVRC%^).
    exit /b 3
)
call :probe_python
if not defined PYOK (
    echo The app's own Python was installed but could not be started. Nothing outside this folder was changed.
    exit /b 3
)

:done
if not defined OUTFILE goto :said
for %%D in ("%OUTFILE%") do if not exist "%%~dpD" mkdir "%%~dpD"
REM Relative to the app's folder (plain ASCII), as bootstrap_host.ps1 writes it: the launcher runs it from there.
>"%OUTFILE%" echo(files\runtime-data\uv\python\%PY_KEY%\python.exe
:said
echo Using Python: !PYEXE!
exit /b 0

REM ------------------------------------------------------------------------------------------------------------
REM  :sha256 FILE VAR  -  VAR = the file's SHA-256 in lower case (empty when the file is missing or unreadable).
REM  certutil runs inside the file's own folder so its one quoted argument is the plain file name.
:sha256
set "%~2="
if not exist "%~1" exit /b 0
pushd "%~dp1" || exit /b 0
for /f "skip=1 delims=" %%H in ('%CERTUTIL% -hashfile "%~nx1" SHA256 2^>nul') do (
    if not defined %~2 set "%~2=%%H"
)
popd
if defined %~2 set "%~2=!%~2: =!"
exit /b 0

REM  :verify FILE SIZE SHA256  -  errorlevel 0 only for exactly the pinned file.
:verify
if not exist "%~1" exit /b 1
if not "%~z1"=="%~2" exit /b 1
call :sha256 "%~1" VERIFYHASH
if /i not "!VERIFYHASH!"=="%~3" exit /b 1
exit /b 0

REM  :fetch URL TARGET SIZE SHA256 WHAT  -  reuse a verified earlier copy, else download over HTTPS and verify.
:fetch
call :verify "%~2" %~3 %~4
if not errorlevel 1 (
    echo Reusing the %~5 downloaded earlier ^(it is still the verified file^).
    exit /b 0
)
del /q "%~2" "%~2.part" 2>nul
echo Downloading the %~5...
"%CURL%" --fail --location --proto =https --proto-redir =https --connect-timeout 30 --silent --show-error --output "%~2.part" "%~1"
if errorlevel 1 (
    del /q "%~2.part" 2>nul
    echo The download did not finish. Check the internet connection and run setup again.
    exit /b 1
)
call :verify "%~2.part" %~3 %~4
if errorlevel 1 (
    del /q "%~2.part" 2>nul
    echo The downloaded %~5 was rejected and deleted: it is not the pinned file.
    exit /b 1
)
move /y "%~2.part" "%~2" >nul || exit /b 1
exit /b 0

REM  :probe_python  -  PYOK=1 only when the pinned build runs here with ssl, venv and ensurepip.
:probe_python
set "PYOK="
if not exist "%PYEXE%" exit /b 0
set "PYBUILD="
if exist "%PYHOME%\BUILD" set /p PYBUILD=<"%PYHOME%\BUILD"
if not "!PYBUILD!"=="%BUILD_TAG%" exit /b 0
"%PYEXE%" -I -c "import sys, ssl, venv, ensurepip; sys.exit(0 if sys.version == '%PY_SYS_VERSION%' else 4)" >nul 2>nul
if errorlevel 1 exit /b 0
set "PYOK=1"
exit /b 0
