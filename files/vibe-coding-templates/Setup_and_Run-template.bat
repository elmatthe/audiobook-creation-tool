@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

:: ============================================================================
::  Setup_and_Run  --  Windows setup + launcher  (template)
:: ============================================================================
::  HOW THIS TEMPLATE IS USED
::  -------------------------
::  Create_New_Repo.bat copies this into a new project's ROOT and renames it to
::  Setup_and_Run-<project_name>.bat. Replace the [PROJECT_NAME] placeholder
::  below (the scaffolder can do this automatically).
::
::  WHAT THIS FILE DOES (per AI-WORKSPACE.md "Setup and Launch Files")
::  ------------------------------------------------------------------
::  One double-click does everything for a NON-TECHNICAL user:
::    1. Scans the PC for Python (the one unavoidable system dependency).
::    2. If Python is missing, asks Y/N and installs it FOR THE CURRENT USER by
::       default (user scope, no admin). Only asks "just me / all users" when a
::       system install is actually forced.
::    3. Creates a fresh .venv IN THE REPO ROOT and installs all dependencies
::       into it (never system-wide).
::    4. Sets up self-contained tools (e.g. ffmpeg) INSIDE the repo (files\bin),
::       nothing installed on the PC.
::    5. Launches the program. On every later run it acts as the launcher.
::
::  SELF-HEALING: delete .venv (to move/shrink/reset the repo) and re-run -- it
::  rebuilds from scratch. Delete Python and re-run -- it detects the absence
::  and offers to reinstall. Re-running always returns you to a working state.
::
::  Goal: the MINIMUM installed on the PC; everything else contained in the repo
::  and the venv.
:: ============================================================================

:: ============================================================================
::  Configuration  --  edit per project
:: ============================================================================
set "PROJECT_NAME=[PROJECT_NAME]"

:: Minimum Python major.minor this project supports.
set "PY_MIN_MAJOR=3"
set "PY_MIN_MINOR=11"
:: Version winget installs if Python must be installed from scratch.
set "PYTHON_WINGET_ID=Python.Python.3.11"

:: requirements.txt lives in scripts\ per AI-WORKSPACE.md.
set "REQUIREMENTS=scripts\requirements.txt"

:: Main entry point. Single-platform: scripts\launcher.py
:: Cross-platform: scripts\Windows\launcher.py (falls back to scripts\Universal\launcher.py).
:: The launcher is auto-detected below; override here only if your project differs.
set "MAIN_SCRIPT="

:: Set to 1 if this project uses ffmpeg (audio/video). 0 disables the ffmpeg step.
set "USE_FFMPEG=0"

:: Where in-repo tools (like ffmpeg) are kept. Self-contained, no install.
set "BIN_DIR=%~dp0files\bin"

:: Internal: scope chosen only if a forced system install happens.
set "INSTALL_SCOPE="

:: ============================================================================
::  Banner + first-run security note
:: ============================================================================
cls
echo ========================================
echo   %PROJECT_NAME% - Setup ^& Launcher
echo   Folder: %CD%
echo ========================================
echo.
echo   This window sets up and launches the program. Setup keeps everything
echo   inside this project folder where it can. You should not need to install
echo   anything system-wide unless a required tool (Python) is completely
echo   missing from this PC -- and it will ask you first if so.
echo.
echo   FIRST-RUN NOTE: Because this file came from the internet, Windows (or
echo   your work security software) may warn you the first time. If you see
echo   "Windows protected your PC", click "More info" then "Run anyway".
echo   This is normal and only happens once.
echo.

:: ============================================================================
::  STEP 1 - Ensure Python (the only unavoidable system dependency)
:: ============================================================================
:: A virtual environment cannot be created without an interpreter already
:: present, so this is the only tool we may have to install onto the PC. If
:: Python already exists, the scope question is never asked.
echo Checking for Python...
call :detect_python
if not defined PYTHON_OK (
    echo.
    echo   Python is not installed on this PC, and it is required to run this
    echo   program. This is the ONLY tool that has to be installed onto the
    echo   computer itself - everything else stays in this folder.
    echo.
    set "do_py="
    set /p do_py=Install Python now? (Y/N): 
    if /i "!do_py!"=="Y" (
        call :choose_scope
        call :install_python
        :: PATH may be stale in this window after a fresh install; re-detect.
        call :detect_python
        if not defined PYTHON_OK (
            echo.
            echo   Python was installed but isn't visible in THIS window yet.
            echo   Close this window, re-open it, and run this file again so the
            echo   updated PATH takes effect.
            echo.
            pause
            exit /b 1
        )
    ) else (
        echo.
        echo   Python is required. You can install it manually from
        echo     https://www.python.org/downloads/
        echo   During install, check "Add python.exe to PATH", then run this
        echo   file again.
        echo.
        pause
        exit /b 1
    )
)

:: Warn (don't block) if the present Python is older than the project minimum.
call :check_python_version

:: ============================================================================
::  STEP 2 - Virtual environment (self-healing; everything below stays in repo)
:: ============================================================================
:: If .venv is missing OR broken (e.g. partially deleted), rebuild it cleanly.
set "VENV_OK="
if exist ".venv\Scripts\activate.bat" set "VENV_OK=1"

if not defined VENV_OK (
    if exist ".venv" (
        echo Existing .venv looks incomplete - rebuilding it from scratch...
        rmdir /s /q ".venv" >nul 2>&1
    ) else (
        echo Creating a new virtual environment in this folder...
    )
    "%PYTHON_CMD%" -m venv .venv
    if !errorlevel! neq 0 (
        echo   ERROR: Failed to create the virtual environment.
        pause
        exit /b 1
    )
)

call .venv\Scripts\activate.bat
if not exist ".venv\Scripts\activate.bat" (
    echo   ERROR: Virtual environment activation script missing after setup.
    pause
    exit /b 1
)

:: ============================================================================
::  STEP 3 - Dependencies (into the venv - never system-wide, installed quietly)
:: ============================================================================
if exist "%REQUIREMENTS%" (
    echo Installing dependencies into the project environment...
    python -m pip install --upgrade pip >nul 2>&1
    python -m pip install -r "%REQUIREMENTS%"
    if !errorlevel! neq 0 (
        echo   ERROR: Some dependencies failed to install. See messages above.
        pause
        exit /b 1
    )
) else (
    echo   Note: No requirements.txt at %REQUIREMENTS% - skipping dependencies.
)

:: ============================================================================
::  STEP 4 - Optional self-contained ffmpeg (kept INSIDE the repo, no install)
:: ============================================================================
if "%USE_FFMPEG%"=="1" call :ensure_ffmpeg
if exist "%BIN_DIR%" set "PATH=%BIN_DIR%;%PATH%"

:: ============================================================================
::  STEP 5 - Locate the launcher and run it
:: ============================================================================
call :detect_main_script
if not defined MAIN_SCRIPT (
    echo.
    echo   ERROR: Could not find the program's entry point.
    echo   Expected one of:
    echo     scripts\launcher.py
    echo     scripts\Windows\launcher.py
    echo     scripts\Universal\launcher.py
    echo   Create one of those or set MAIN_SCRIPT in this file's Configuration.
    echo.
    pause
    exit /b 1
)

echo.
echo Launching %PROJECT_NAME%...
echo.
python "%MAIN_SCRIPT%"
set "RUN_EXIT=%errorlevel%"

echo.
if not "%RUN_EXIT%"=="0" (
    echo Program exited with code %RUN_EXIT%.
) else (
    echo Program finished.
)
pause
endlocal
exit /b %RUN_EXIT%


:: ============================================================================
::  Helpers
:: ============================================================================

:: ----------------------------------------------------------------------------
:: detect_python - set PYTHON_OK and PYTHON_CMD if a usable Python is found.
:: Tries the "py" launcher first (most reliable on Windows), then "python".
:: ----------------------------------------------------------------------------
:detect_python
set "PYTHON_OK="
set "PYTHON_CMD="
py -%PY_MIN_MAJOR% --version >nul 2>&1
if !errorlevel! equ 0 (
    set "PYTHON_CMD=py -%PY_MIN_MAJOR%"
    set "PYTHON_OK=1"
    goto :eof
)
python --version >nul 2>&1
if !errorlevel! equ 0 (
    set "PYTHON_CMD=python"
    set "PYTHON_OK=1"
)
goto :eof

:: ----------------------------------------------------------------------------
:: check_python_version - warn if the detected Python is below the minimum.
:: ----------------------------------------------------------------------------
:check_python_version
for /f "tokens=2 delims=. " %%a in ('%PYTHON_CMD% --version 2^>^&1') do set "FOUND_MINOR=%%a"
if defined FOUND_MINOR (
    if !FOUND_MINOR! lss %PY_MIN_MINOR% (
        echo   WARNING: Detected Python 3.!FOUND_MINOR!, but this project targets
        echo            %PY_MIN_MAJOR%.%PY_MIN_MINOR% or newer. Some features may not work.
        echo.
    )
)
goto :eof

:: ----------------------------------------------------------------------------
:: choose_scope - ask user vs machine scope. ONLY called for a forced install.
:: ----------------------------------------------------------------------------
:choose_scope
echo.
echo ----------------------------------------
echo   This install has to go onto the PC itself. Where should it go?
echo.
echo     1. Just for me     (no admin rights needed - safest at work)
echo     2. For all users   (requires admin rights on this PC)
echo ----------------------------------------
set "scope_choice="
set /p scope_choice=Enter 1 or 2 (default 1): 
if "%scope_choice%"=="2" (
    set "INSTALL_SCOPE=machine"
    echo   Installing system-wide (all users). Admin may be requested.
) else (
    set "INSTALL_SCOPE=user"
    echo   Installing for the current user only. No admin needed.
)
echo.
goto :eof

:: ----------------------------------------------------------------------------
:: install_python - install Python via winget at the chosen scope.
:: ----------------------------------------------------------------------------
:install_python
echo   Installing Python (%INSTALL_SCOPE% scope)...
where winget >nul 2>&1
if %errorlevel% neq 0 (
    echo   Windows Package Manager (winget) is not available on this PC.
    echo   Please install Python manually from:
    echo     https://www.python.org/downloads/
    echo   During install, check "Add python.exe to PATH", then run this file again.
    echo.
    pause
    goto :eof
)
if /i "%INSTALL_SCOPE%"=="machine" (
    winget install --id %PYTHON_WINGET_ID% --scope machine --accept-source-agreements --accept-package-agreements
) else (
    winget install --id %PYTHON_WINGET_ID% --scope user --accept-source-agreements --accept-package-agreements
)
goto :eof

:: ----------------------------------------------------------------------------
:: detect_main_script - find the launcher unless MAIN_SCRIPT was set manually.
:: ----------------------------------------------------------------------------
:detect_main_script
if defined MAIN_SCRIPT goto :eof
if exist "scripts\launcher.py"           set "MAIN_SCRIPT=scripts\launcher.py"           & goto :eof
if exist "scripts\Windows\launcher.py"   set "MAIN_SCRIPT=scripts\Windows\launcher.py"   & goto :eof
if exist "scripts\Universal\launcher.py" set "MAIN_SCRIPT=scripts\Universal\launcher.py" & goto :eof
goto :eof

:: ----------------------------------------------------------------------------
:: ensure_ffmpeg - prefer a self-contained in-repo copy; no system install.
:: ----------------------------------------------------------------------------
:ensure_ffmpeg
where ffmpeg >nul 2>&1
if %errorlevel% equ 0 goto :eof
if exist "%BIN_DIR%\ffmpeg.exe" goto :eof

echo.
echo   This project uses ffmpeg (audio/video processing). It is not on this PC,
echo   so it can be placed INSIDE the project folder only - nothing is installed
echo   system-wide and no admin rights are needed.
echo.
set "do_ff="
set /p do_ff=Set up ffmpeg inside the project now? (Y/N): 
if /i not "!do_ff!"=="Y" (
    echo   Skipped ffmpeg. The program will still run; features that need it may
    echo   be unavailable until it is set up.
    goto :eof
)

if not exist "%BIN_DIR%" mkdir "%BIN_DIR%"
set "FF_ZIP=%TEMP%\ffmpeg_repo_dl.zip"
set "FF_URL=https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

echo   Downloading a self-contained ffmpeg into the project...
powershell -Command "try { Invoke-WebRequest -Uri '%FF_URL%' -OutFile '%FF_ZIP%' -UseBasicParsing } catch { exit 1 }"
if %errorlevel% neq 0 (
    echo   Could not download ffmpeg automatically. You can download it later
    echo   from https://www.gyan.dev/ffmpeg/builds/ and place ffmpeg.exe in:
    echo     %BIN_DIR%
    echo.
    goto :eof
)

echo   Extracting ffmpeg into the project folder...
powershell -Command "try { Expand-Archive -Path '%FF_ZIP%' -DestinationPath '%TEMP%\ffmpeg_repo_extract' -Force } catch { exit 1 }"
for /r "%TEMP%\ffmpeg_repo_extract" %%F in (ffmpeg.exe) do copy "%%F" "%BIN_DIR%\ffmpeg.exe" >nul
del "%FF_ZIP%" >nul 2>&1
rmdir /s /q "%TEMP%\ffmpeg_repo_extract" >nul 2>&1

if exist "%BIN_DIR%\ffmpeg.exe" (
    echo   ffmpeg is set up inside the project. Nothing was installed on the PC.
) else (
    echo   ffmpeg setup did not complete. You can place ffmpeg.exe in:
    echo     %BIN_DIR%
)
echo.
goto :eof
