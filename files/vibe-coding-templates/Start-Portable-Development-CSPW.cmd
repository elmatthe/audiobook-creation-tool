@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

:: ============================================================================
::  Start-Portable-Development-CSPW.cmd
:: ----------------------------------------------------------------------------
::  Interactive portable-dev launcher for the WORK PC (no admin rights).
::
::  1. Enables portable Git + Node.js + Claude Code (%USERPROFILE%\.local\bin)
::     onto PATH for THIS session only -- nothing installed system-wide.
::  2. Lists the sub-directories of the folder this file sits in; you pick one
::     by number (e.g. MyProjects, or a workspace root).
::  3. Lists the repositories inside that directory; you pick one by number.
::  4. Changes into the chosen repo, prints tool versions to confirm Claude
::     Code is ready, and leaves you in an interactive PowerShell there.
::
::  Drop this in any Coding_Repositories-style root and it adapts to whatever
::  folders are present -- same live-detection approach as Create_New_Repo.
:: ============================================================================

:: --- Portable tool locations (edit here if you move them) -------------------
set "GIT_HOME=%USERPROFILE%\Portable-User-Installs\PortableGit"
set "NODE_HOME=%USERPROFILE%\Portable-User-Installs\PortableNodeJS\node-v26.4.0-win-x64"
set "CLAUDE_BIN=%USERPROFILE%\.local\bin"

set "PATH=%GIT_HOME%\cmd;%GIT_HOME%\mingw64\bin;%GIT_HOME%\usr\bin;%NODE_HOME%;%CLAUDE_BIN%;%PATH%"

set "START_ROOT=%CD%"

cls
echo ========================================
echo   Portable Development Launcher (CSPW)
echo   Root: %START_ROOT%
echo ========================================
echo.

:: ----------------------------------------------------------------------------
:: STEP 1 - pick a directory inside the root this file sits in
:: ----------------------------------------------------------------------------
echo   Which directory do you want to work in?
echo.

set "dir_count=0"
for /d %%D in ("%START_ROOT%\*") do (
    set "skip_dir="
    if /i "%%~nxD"=="templates" set "skip_dir=1"
    if /i "%%~nxD"==".claude" set "skip_dir=1"
    if /i "%%~nxD"==".codex" set "skip_dir=1"
    if /i "%%~nxD"==".git" set "skip_dir=1"
    if not defined skip_dir (
        set /a dir_count+=1
        set "dir_name[!dir_count!]=%%~nxD"
        set "dir_path[!dir_count!]=%%~fD"
        echo     !dir_count!. %%~nxD
    )
)

if "%dir_count%"=="0" (
    echo.
    echo   No sub-directories found in this root. Nothing to open.
    echo.
    goto :launch_shell_here
)

echo.
set "dc="
set /p dc=Enter choice (1-%dir_count%): 

set "chosen_dir="
set "chosen_dir_path="
if defined dir_name[%dc%] (
    set "chosen_dir=!dir_name[%dc%]!"
    set "chosen_dir_path=!dir_path[%dc%]!"
)

if not defined chosen_dir (
    echo.
    echo   Invalid choice. Please run again.
    echo.
    pause
    exit /b 1
)

echo.
echo   Directory selected: %chosen_dir%
echo.

:: ----------------------------------------------------------------------------
:: STEP 2 - pick a repository inside the chosen directory
:: ----------------------------------------------------------------------------
echo   Which repository do you want to open?
echo.

set "repo_count=0"
for /d %%R in ("%chosen_dir_path%\*") do (
    set /a repo_count+=1
    set "repo_name[!repo_count!]=%%~nxR"
    set "repo_path[!repo_count!]=%%~fR"
    echo     !repo_count!. %%~nxR
)

if "%repo_count%"=="0" (
    echo.
    echo   No repositories found in "%chosen_dir%".
    echo   Opening a shell in that directory instead.
    echo.
    set "TARGET=%chosen_dir_path%"
    goto :launch_shell
)

echo.
echo     0. ^(Just open a shell in "%chosen_dir%" itself^)
echo.
set "rc="
set /p rc=Enter choice (0-%repo_count%): 

if "%rc%"=="0" (
    set "TARGET=%chosen_dir_path%"
    goto :launch_shell
)

set "TARGET="
if defined repo_name[%rc%] set "TARGET=!repo_path[%rc%]!"

if not defined TARGET (
    echo.
    echo   Invalid choice. Please run again.
    echo.
    pause
    exit /b 1
)

set "chosen_repo="
if defined repo_name[%rc%] set "chosen_repo=!repo_name[%rc%]!"
echo.
echo   Repository selected: %chosen_repo%
goto :launch_shell


:: ----------------------------------------------------------------------------
:: Launch an interactive PowerShell in %TARGET% with tools on PATH
:: ----------------------------------------------------------------------------
:launch_shell
cd /d "%TARGET%"
echo.
echo ========================================
echo   Ready. Working directory:
echo   %CD%
echo ========================================
echo.
echo   Portable Git, Node.js, and Claude Code are on PATH for this session.
echo   Verifying tools, then handing you an interactive PowerShell...
echo.
powershell.exe -NoLogo -NoExit -Command ^
  "Write-Host 'Portable Git, Node.js and Claude Code enabled.' -ForegroundColor Green; git --version; node --version; npm.cmd --version; try { claude --version } catch { Write-Host 'claude not found on PATH (check %USERPROFILE%\.local\bin)' -ForegroundColor Yellow }; Write-Host ''; Write-Host ('Now in: ' + (Get-Location).Path) -ForegroundColor Cyan; Write-Host 'Type ''claude'' to start Claude Code, or run any git/node command.' -ForegroundColor Cyan"
exit /b 0

:launch_shell_here
set "TARGET=%START_ROOT%"
goto :launch_shell
