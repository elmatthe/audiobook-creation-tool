@echo off
REM ============================================================================
REM  Audiobook Creation Tool  -  Windows setup and launcher
REM
REM  Double-click this file. The FIRST time it runs it installs everything
REM  (a private Python environment + audio libraries + ffmpeg) using a small
REM  setup window. EVERY time after that it just opens the app instantly with
REM  no console window. All the real work lives in:
REM      Windows\scripts\shared\bootstrap.py
REM ============================================================================

setlocal EnableExtensions
cd /d "%~dp0Windows"

set "BOOTSTRAP=scripts\shared\bootstrap.py"

REM ---------------------------------------------------------------------------
REM  Fast path: the environment is already set up. Launch via pythonw.exe so no
REM  console window appears, then exit immediately.
REM ---------------------------------------------------------------------------
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "%BOOTSTRAP%" --launch-only
    exit /b 0
)

REM ---------------------------------------------------------------------------
REM  First run: we need *some* Python just to run the setup window. The setup
REM  script itself will locate or install the correct Python 3.12 for the app.
REM ---------------------------------------------------------------------------
echo ============================================================
echo   Audiobook Creation Tool - first-time setup
echo ============================================================
echo.
echo Looking for Python...

set "PYCMD="
where py >nul 2>nul && set "PYCMD=py"
if not defined PYCMD (
    where python >nul 2>nul && set "PYCMD=python"
)

REM No Python at all - try to install it with winget, then look again.
if not defined PYCMD (
    echo Python was not found. Attempting to install Python 3.12 via winget...
    where winget >nul 2>nul && winget install --id Python.Python.3.12 -e --silent --accept-source-agreements --accept-package-agreements
    REM winget installs per-user here; PATH may not refresh this session, so
    REM check the known install location directly.
    if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYCMD=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    if not defined PYCMD (
        where py >nul 2>nul && set "PYCMD=py"
    )
)

if not defined PYCMD (
    echo.
    echo Could not find or install Python automatically.
    echo Opening the Python download page in your browser.
    echo Install Python 3.12 ^(check "Add Python to PATH"^), then run this file again.
    start "" "https://www.python.org/downloads/release/python-3120/"
    echo.
    pause
    exit /b 1
)

echo Using Python: %PYCMD%
echo Starting setup...
echo.
"%PYCMD%" "%BOOTSTRAP%"
set "RC=%errorlevel%"

if not "%RC%"=="0" (
    echo.
    echo Setup did not complete successfully ^(exit code %RC%^).
    echo See the log under Windows\resources\logs\ for details.
    echo.
    pause
)
exit /b %RC%
