@echo off
REM ============================================================================
REM  Audiobook Creation Tool  -  Windows setup and launcher
REM
REM  Double-click this file. The FIRST time it runs it installs everything
REM  (a private Python environment + audio libraries + ffmpeg) using a small
REM  setup window. EVERY time after that it just opens the app instantly with
REM  no console window. All the real work lives in:
REM      scripts\shared\bootstrap.py
REM
REM  This file deliberately knows nothing about Python versions, ssl or Tk.
REM  Deciding whether the environment is healthy is bootstrap's job; all this
REM  does is ask, then either launch or hand control back for a repair.
REM ============================================================================

setlocal EnableExtensions
cd /d "%~dp0"

set "BOOTSTRAP=scripts\shared\bootstrap.py"
set "REPAIR="

REM ---------------------------------------------------------------------------
REM  Fast path: the environment is already set up.
REM
REM  This used to be "if pythonw.exe exists, start it and quit", which cannot
REM  tell a working environment from a wrecked one. An environment whose Python
REM  no longer runs, that lost ssl, or that sits on an incompatible version
REM  still has the file - so the launcher happily started something that could
REM  not work, and every recovery path bootstrap already owned was unreachable.
REM
REM  So ask bootstrap first. It answers in about 150ms with an exit code:
REM      0 = healthy enough to launch      3 = this environment needs rebuilding
REM  The check runs on python.exe because cmd waits for a console program; the
REM  real launch still goes through pythonw.exe detached, so the healthy steady
REM  state is the same instant, console-free start it always was.
REM ---------------------------------------------------------------------------
if not exist ".venv\Scripts\python.exe" goto firstrun

".venv\Scripts\python.exe" "%BOOTSTRAP%" --venv-check >nul 2>nul
if errorlevel 1 goto needsrepair

start "" ".venv\Scripts\pythonw.exe" "%BOOTSTRAP%" --launch-only
exit /b 0

:needsrepair
REM Any non-zero answer means repair - including the interpreter failing to
REM start at all, which is precisely the case bootstrap cannot report from
REM inside. The repair must run on a different interpreter: Windows locks a
REM running python.exe, so a venv can never replace itself.
set "REPAIR=1"
echo ============================================================
echo   Audiobook Creation Tool - repairing the app environment
echo ============================================================
echo.
echo The app's Python environment needs to be rebuilt.
echo Your settings and your audiobooks are not touched.
echo This can take a few minutes.
echo.
goto findpython

:firstrun
echo ============================================================
echo   Audiobook Creation Tool - first-time setup
echo ============================================================
echo.

REM ---------------------------------------------------------------------------
REM  First run, or an environment repair: we need a proven Python outside the venv.
REM  Stage 0 (scripts\shared\bootstrap_host.ps1) uses the app's OWN Python in
REM  files\runtime-data\python, proved by RUNNING it (3.12 with ssl, venv and Tk),
REM  or - only after asking - downloads the pinned, hash-verified standalone
REM  Python into that folder. Nothing is installed on the computer: no installer,
REM  no administrator rights, no PATH change. It writes the interpreter's full
REM  path to a file; exit 2 means the user said No, 3 means it could not be done.
REM ---------------------------------------------------------------------------
:findpython
echo Preparing the app's own Python (kept inside this folder)...
set "PYCMD="
set "PYFILE=files\temp\bootstrap\selected-python.txt"
if not exist "files\temp\bootstrap" mkdir "files\temp\bootstrap"
if exist "%PYFILE%" del /q "%PYFILE%"
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\shared\bootstrap_host.ps1" -OutFile "%PYFILE%"
set "HOSTRC=%errorlevel%"
if "%HOSTRC%"=="2" (
    echo.
    echo Setup cancelled. Python was not installed and nothing was changed.
    echo Run this file again whenever you are ready to set the app up.
    echo.
    pause
    exit /b 0
)
if "%HOSTRC%"=="0" if exist "%PYFILE%" for /f "usebackq delims=" %%P in ("%PYFILE%") do set "PYCMD=%%P"

REM PowerShell itself could not run (for example, scripts are blocked by an IT
REM policy): fall back to a Python that is already on this computer, if any.
REM bootstrap.py still checks it and refuses one it cannot build from.
if not defined PYCMD if not "%HOSTRC%"=="3" (
    where py >nul 2>nul && set "PYCMD=py"
    if not defined PYCMD where python >nul 2>nul && set "PYCMD=python"
)

if not defined PYCMD (
    echo.
    echo The app's own Python could not be set up ^(see the messages above^).
    echo Check the internet connection and run this file again.
    echo.
    pause
    exit /b 1
)

echo Using Python: %PYCMD%
if defined REPAIR goto runrepair

echo Starting setup...
echo.
"%PYCMD%" "%BOOTSTRAP%"
goto finished

:runrepair
REM Environment repair only. This rebuilds the private Python environment and
REM its packages and then launches; it is NOT the full first-run install.
echo Repairing...
echo.
"%PYCMD%" "%BOOTSTRAP%" --repair-venv

:finished
set "RC=%errorlevel%"

REM Exit code 2 means the user closed the setup window without starting it.
REM Declining an optional install is not a failure, so say so plainly and close
REM cleanly rather than showing the error text and holding the window open.
REM Anything else non-zero is still treated as a genuine failure.
if "%RC%"=="2" (
    echo.
    echo Setup cancelled. Nothing was installed.
    echo Run this file again whenever you are ready to set the app up.
    exit /b 0
)

if not "%RC%"=="0" (
    echo.
    echo Setup did not complete successfully ^(exit code %RC%^).
    echo See the log under files\runtime-data\logs\ for details.
    echo.
    pause
)
exit /b %RC%
