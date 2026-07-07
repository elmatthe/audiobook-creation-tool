@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

:: === FIXED PATHS FOR HOME / PERSONAL PC VERSION ===
set "workspace_root=%~dp0"
set "coding_root=%~dp0.."
set "templates_root=%coding_root%\templates"
set "md_templates=%templates_root%\md-templates"
set "setup_templates=%templates_root%\setup_and_run-templates"
set "aiworkspace=%coding_root%\AI-WORKSPACE.md"
set "claude_src=%coding_root%\.claude"
set "codex_src=%coding_root%\.codex"

set "setup_bat_template=%setup_templates%\Setup_and_Run-template.bat"
set "setup_command_template=%setup_templates%\Setup_and_Run-template.command"
set "briefing_template=%md_templates%\briefing-template.md"
set "changelog_template=%md_templates%\changelog-template.md"
set "handoff_template=%md_templates%\handoff-template.md"
set "instructions_template=%md_templates%\instructions-template.md"
set "decisions_template=%md_templates%\decisions-template.md"
set "verify_template=%templates_root%\verify-template.py"

cls
echo ========================================
echo   New Project Scaffolder
echo   MyProjects: %CD%
echo ========================================
echo.

:: ----------------------------------------
:: Validate required sources
:: ----------------------------------------
if not exist "%md_templates%" (
    echo   ERROR: md-templates folder not found.
    echo   Expected: %md_templates%
    echo.
    call :safe_pause
    exit /b 1
)

if not exist "%setup_templates%" (
    echo   ERROR: setup_and_run-templates folder not found.
    echo   Expected: %setup_templates%
    echo.
    call :safe_pause
    exit /b 1
)

if not exist "%setup_bat_template%" (
    echo   ERROR: setup_and_run template not found.
    echo   Expected: %setup_bat_template%
    echo.
    call :safe_pause
    exit /b 1
)

if not exist "%setup_command_template%" (
    echo   ERROR: setup_and_run template not found.
    echo   Expected: %setup_command_template%
    echo.
    call :safe_pause
    exit /b 1
)

if not exist "%briefing_template%" (
    echo   ERROR: markdown template not found.
    echo   Expected: %briefing_template%
    echo.
    call :safe_pause
    exit /b 1
)

if not exist "%changelog_template%" (
    echo   ERROR: markdown template not found.
    echo   Expected: %changelog_template%
    echo.
    call :safe_pause
    exit /b 1
)

if not exist "%handoff_template%" (
    echo   ERROR: markdown template not found.
    echo   Expected: %handoff_template%
    echo.
    call :safe_pause
    exit /b 1
)

if not exist "%instructions_template%" (
    echo   ERROR: markdown template not found.
    echo   Expected: %instructions_template%
    echo.
    call :safe_pause
    exit /b 1
)

if not exist "%aiworkspace%" (
    echo   WARNING: AI-WORKSPACE.md not found at %aiworkspace%
    echo   Skipping copy.
    echo.
)

if not exist "%claude_src%" (
    echo   WARNING: .claude source not found at %claude_src%
    echo   An empty .claude\skills folder will be created instead.
    echo.
)

if not exist "%codex_src%" (
    echo   WARNING: .codex source not found at %codex_src%
    echo   An empty .codex\skills folder will be created instead.
    echo.
)

:: ----------------------------------------
:: Choose workspace (live detection)
:: ----------------------------------------
echo   Which workspace is this project for?
echo.

set "ws_count=0"
for /d %%D in ("%workspace_root%*") do (
    set "skip_ws="
    if /i "%%~nxD"=="templates" set "skip_ws=1"
    if /i "%%~nxD"=="md-templates" set "skip_ws=1"
    if /i "%%~nxD"=="setup_and_run-templates" set "skip_ws=1"
    if /i "%%~nxD"==".claude" set "skip_ws=1"
    if /i "%%~nxD"==".codex" set "skip_ws=1"
    if not defined skip_ws (
        set /a ws_count+=1
        set "ws_name[!ws_count!]=%%~nxD"
        echo     !ws_count!. %%~nxD
    )
)

if "%ws_count%"=="0" (
    echo.
    echo   ERROR: No workspace folders found in:
    echo   %workspace_root%
    echo   Create at least one workspace folder and run again.
    echo.
    call :safe_pause
    exit /b 1
)

echo.
set "ws="
set /p ws=Enter choice (1-%ws_count%): 

set "workspace="
if defined ws_name[%ws%] set "workspace=!ws_name[%ws%]!"

if "%workspace%"=="" (
    echo.
    echo   Invalid choice. Please run again.
    call :safe_pause
    exit /b 1
)

echo.
echo   Workspace selected: %workspace%
echo.

:: ----------------------------------------
:: Project name
:: ----------------------------------------
:ask_name
set "projname="
set /p projname=Project folder name (no spaces, use hyphens): 

if "%projname%"=="" (
    echo   Name cannot be blank.
    echo.
    goto ask_name
)

if not "%projname%"=="%projname: =%" (
    echo   Name cannot contain spaces.
    echo.
    goto ask_name
)

set "projpath=%workspace_root%%workspace%\%projname%"

if exist "%projpath%" (
    echo.
    echo   ERROR: "%projname%" already exists.
    echo.
    goto ask_name
)

:: ----------------------------------------
:: Optional details
:: ----------------------------------------
echo.
echo Press Enter to skip any optional field.
echo.

set "desc="
set /p desc=Short description (one line, for README): 

set "techstack="
set /p techstack=Primary language/tech: 

set "guilib="
set /p guilib=GUI library if applicable: 

set "author="
set /p author=Author name: 

echo.
set "crossplat="
set /p crossplat=Cross-platform project? (y/n): 

set "readme_desc=[Add a short description of this project.]"
if not "%desc%"=="" set "readme_desc=%desc%"

set "readme_tech=- Python 3.x"
if not "%techstack%"=="" set "readme_tech=- %techstack%"

set "readme_author=[Author]"
if not "%author%"=="" set "readme_author=%author%"

:: ----------------------------------------
:: Confirm
:: ----------------------------------------
echo.
echo ----------------------------------------
echo   Workspace   : %workspace%
echo   Location    : %projpath%
echo.
if not "%desc%"==""       echo   Description : %desc%
if not "%techstack%"==""  echo   Tech        : %techstack%
if not "%guilib%"==""     echo   GUI         : %guilib%
if not "%author%"==""     echo   Author      : %author%
if /i "%crossplat%"=="y"  echo   Structure   : Cross-platform (Windows + MacOS)
if /i not "%crossplat%"=="y" echo   Structure   : Single-platform
echo ----------------------------------------
echo.
set "confirm="
set /p confirm=Create this project? (y/n): 

if /i "%confirm%" neq "y" (
    echo   Cancelled.
    call :safe_pause
    exit /b 0
)

:: ----------------------------------------
:: Create folders
:: ----------------------------------------
echo.
echo   Creating folders...

mkdir "%projpath%" >nul 2>&1
mkdir "%projpath%\scripts" >nul 2>&1
mkdir "%projpath%\files\tests" >nul 2>&1
mkdir "%projpath%\files\test-files" >nul 2>&1
mkdir "%projpath%\files\test-logs" >nul 2>&1
mkdir "%projpath%\files\bin" >nul 2>&1
mkdir "%projpath%\md-instructions" >nul 2>&1

if /i "%crossplat%"=="y" (
    mkdir "%projpath%\scripts\Universal" >nul 2>&1
    mkdir "%projpath%\scripts\Windows" >nul 2>&1
    mkdir "%projpath%\scripts\MacOS" >nul 2>&1
)

:: ----------------------------------------
:: Clone agent config folders
:: ----------------------------------------
echo   Setting up .claude agent config...
if exist "%claude_src%" (
    robocopy "%claude_src%" "%projpath%\.claude" /E /NFL /NDL /NJH /NJS /NP >nul <nul
) else (
    mkdir "%projpath%\.claude\skills" >nul 2>&1
)

echo   Setting up .codex agent config...
if exist "%codex_src%" (
    robocopy "%codex_src%" "%projpath%\.codex" /E /NFL /NDL /NJH /NJS /NP >nul <nul
) else (
    mkdir "%projpath%\.codex\skills" >nul 2>&1
)

:: ----------------------------------------
:: Copy setup_and_run templates (ALL files in the folder, into repo root)
:: Naming rule: "-template" in a filename becomes "-<projname>".
:: Files without "-template" (e.g. Map-Repo-Structure.bat) copy verbatim.
:: NOTE: no CALL inside the FOR block -- calling a subroutine from within a
:: parenthesized block corrupts cmd's paren tracking and breaks labels later
:: in the file. So we ONLY copy here, then token-substitute afterwards.
:: ----------------------------------------
echo   Copying setup_and_run templates...
for %%F in ("%setup_templates%\*") do (
    set "src_name=%%~nxF"
    set "dst_name=!src_name:-template=-%projname%!"
    copy /Y "%%~fF" "%projpath%\!dst_name!" >nul <nul
)

:: Token-substitute the two launchers (deterministic names after the rename).
if exist "%projpath%\Setup_and_Run-%projname%.bat" (
    set "target_file=%projpath%\Setup_and_Run-%projname%.bat"
    call :replace_project_token
)
if exist "%projpath%\Setup_and_Run-%projname%.command" (
    set "target_file=%projpath%\Setup_and_Run-%projname%.command"
    call :replace_project_token
)

:: ----------------------------------------
:: Copy AI-WORKSPACE.md
:: ----------------------------------------
if exist "%aiworkspace%" (
    echo   Copying AI-WORKSPACE.md...
    copy /Y "%aiworkspace%" "%projpath%\AI-WORKSPACE.md" >nul <nul
)

:: ----------------------------------------
:: Copy md templates
:: NOTE: previously each doc was copied then de-templated with its own
:: "call :clean_md_template" (5 separate calls). Testing showed the 2nd
:: consecutive call in that sequence could silently no-op (a batch label/
:: file-pointer quirk specific to repeated calls to the same subroutine),
:: which left CHANGELOG.md still templated with no error surfaced reliably.
:: Fix: copy all core docs first, then de-template them all in ONE call.
:: ----------------------------------------
echo   Copying md-templates...
copy /Y "%briefing_template%" "%projpath%\md-instructions\Briefing.md" >nul <nul
copy /Y "%changelog_template%" "%projpath%\md-instructions\CHANGELOG.md" >nul <nul
copy /Y "%handoff_template%" "%projpath%\md-instructions\handoff.md" >nul <nul
copy /Y "%instructions_template%" "%projpath%\md-instructions\Instructions_Template.md" >nul <nul
if exist "%decisions_template%" (
    copy /Y "%decisions_template%" "%projpath%\md-instructions\DECISIONS.md" >nul <nul
)

:: De-template ALL core md docs in ONE pass (strip HTML comment blocks,
:: substitute [Project Name], and stamp the real date into CHANGELOG.md only).
set "md_dir=%projpath%\md-instructions"
set "changelog_name=CHANGELOG.md"
call :clean_all_md

:: Any OTHER file dropped in md-templates\ (not one of the core docs above)
:: copies into md-instructions\ with the "-template" -> "-<projname>" rename,
:: verbatim (no de-templating). Add new drops here anytime.
echo   Copying any additional md-templates...
for %%F in ("%md_templates%\*") do (
    set "src_name=%%~nxF"
    set "is_core="
    if /i "!src_name!"=="briefing-template.md"     set "is_core=1"
    if /i "!src_name!"=="changelog-template.md"    set "is_core=1"
    if /i "!src_name!"=="handoff-template.md"       set "is_core=1"
    if /i "!src_name!"=="instructions-template.md"  set "is_core=1"
    if /i "!src_name!"=="decisions-template.md"     set "is_core=1"
    if not defined is_core (
        set "dst_name=!src_name:-template=-%projname%!"
        copy /Y "%%~fF" "%projpath%\md-instructions\!dst_name!" >nul <nul
    )
)

:: ----------------------------------------
:: Copy verify gate into scripts\ as verify.py (canonical name)
:: ----------------------------------------
if exist "%verify_template%" (
    echo   Copying verify gate into scripts\...
    copy /Y "%verify_template%" "%projpath%\scripts\verify.py" >nul <nul
    set "target_file=%projpath%\scripts\verify.py"
    call :replace_project_token
) else (
    echo   Note: verify-template.py not found at %verify_template% - skipping.
)

:: ----------------------------------------
:: README.md
:: ----------------------------------------
echo   Writing README.md...
(
    echo # %projname%
    echo.
    echo %readme_desc%
    echo.
    echo ## Setup
    echo Double-click Setup_and_Run-%projname%.bat ^(Windows^) or Setup_and_Run-%projname%.command ^(macOS^).
    echo.
    echo ## Global Preferences
    echo See AI-WORKSPACE.md for developer workflow and AI agent instructions.
    echo.
    echo ## Requirements
    echo %readme_tech%
    echo.
    echo ## Author
    echo %readme_author%
) > "%projpath%\README.md"

:: ----------------------------------------
:: Agent instruction pointers
:: ----------------------------------------
echo   Writing agent instruction files...
(
    echo # %projname% - Claude Instructions
    echo.
    echo See ..\AI-WORKSPACE.md for global preferences and workflow instructions.
    echo See ..\md-instructions\Briefing.md for this project's current state.
    echo See ..\md-instructions\CHANGELOG.md for version history.
    echo See ..\md-instructions\handoff.md for live working state and sync notes.
    echo See skills\ for reusable Claude skills available in this repo.
) > "%projpath%\.claude\CLAUDE.md"

(
    echo # %projname% - Codex Instructions
    echo.
    echo See ..\AI-WORKSPACE.md for global preferences and workflow instructions.
    echo See ..\md-instructions\Briefing.md for this project's current state.
    echo See ..\md-instructions\CHANGELOG.md for version history.
    echo See ..\md-instructions\handoff.md for live working state and sync notes.
    echo See skills\ for reusable Codex skills available in this repo.
) > "%projpath%\.codex\CODEX.md"

:: ----------------------------------------
:: .gitignore + .env
:: ----------------------------------------
echo   Writing .gitignore...
(
    echo .venv/
    echo .python_runtime/
    echo __pycache__/
    echo *.pyc
    echo *.pyo
    echo dist/
    echo build/
    echo *.spec
    echo files/bin/
    echo files/test-logs/
    echo .env
) > "%projpath%\.gitignore"

echo   Writing .env...
(
    echo # Secrets and credentials. Gitignored.
    echo # Keep API keys and local-only settings here.
    echo.
    echo # API_KEY=your_key_here
) > "%projpath%\.env"

:: ----------------------------------------
:: .gitkeep placeholders for otherwise-empty directories
:: ----------------------------------------
echo   Writing folder placeholders...
if /i "%crossplat%"=="y" (
    call :write_gitkeep "%projpath%\scripts\Universal"
    call :write_gitkeep "%projpath%\scripts\Windows"
    call :write_gitkeep "%projpath%\scripts\MacOS"
) else (
    call :write_gitkeep "%projpath%\scripts"
)
call :write_gitkeep "%projpath%\files\tests"
call :write_gitkeep "%projpath%\files\test-files"
call :write_gitkeep "%projpath%\files\test-logs"
call :write_gitkeep "%projpath%\files\bin"

echo.
echo ========================================
echo   Done. %workspace%\%projname% created successfully.
echo ========================================
call :safe_pause
endlocal
exit /b 0


:: ----------------------------------------
:: Helpers
:: ----------------------------------------
:replace_project_token
set "ps_helper=%TEMP%\scaffold_replace_%RANDOM%%RANDOM%.ps1"
> "%ps_helper%" echo $p = $env:target_file
>> "%ps_helper%" echo $project = $env:projname
>> "%ps_helper%" echo $s = Get-Content -Raw -LiteralPath $p
>> "%ps_helper%" echo $s = $s.Replace('[PROJECT_NAME]', $project)
>> "%ps_helper%" echo Set-Content -LiteralPath $p -Value $s -NoNewline
powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%ps_helper%" <nul
del "%ps_helper%" >nul 2>&1
goto :eof

:clean_all_md
:: De-templates every *.md in %md_dir% in ONE PowerShell invocation, avoiding
:: the repeated-subroutine-call issue that could silently skip a doc when
:: :clean_md_template was called 5 times in a row for 5 separate files.
set "ps_helper=%TEMP%\scaffold_clean_md_%RANDOM%%RANDOM%.ps1"
> "%ps_helper%" echo $dir = $env:md_dir
>> "%ps_helper%" echo $project = $env:projname
>> "%ps_helper%" echo $changelogName = $env:changelog_name
>> "%ps_helper%" echo $open = [string][char]60 + [string][char]33 + '--'
>> "%ps_helper%" echo $close = '--' + [string][char]62
>> "%ps_helper%" echo foreach ($f in Get-ChildItem -LiteralPath $dir -Filter '*.md' -File) {
>> "%ps_helper%" echo     $s = Get-Content -Raw -LiteralPath $f.FullName
>> "%ps_helper%" echo     while ($s.Contains($open)) {
>> "%ps_helper%" echo         $start = $s.IndexOf($open)
>> "%ps_helper%" echo         $end = $s.IndexOf($close, $start)
>> "%ps_helper%" echo         if ($end -lt 0) { break }
>> "%ps_helper%" echo         $s = $s.Remove($start, ($end - $start) + 3).TrimStart([char[]]@([char]13,[char]10))
>> "%ps_helper%" echo     }
>> "%ps_helper%" echo     $s = $s.Replace('[Project Name]', $project)
>> "%ps_helper%" echo     if ($f.Name -eq $changelogName) {
>> "%ps_helper%" echo         $s = $s.Replace('[YYYY-MM-DD]', (Get-Date -Format 'yyyy-MM-dd'))
>> "%ps_helper%" echo     }
>> "%ps_helper%" echo     Set-Content -LiteralPath $f.FullName -Value $s -NoNewline
>> "%ps_helper%" echo }
powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%ps_helper%" <nul
del "%ps_helper%" >nul 2>&1
goto :eof

:write_gitkeep
set "keep_dir=%~1"
if not exist "%keep_dir%" mkdir "%keep_dir%" >nul 2>&1
dir /a /b "%keep_dir%" 2>nul | findstr /r "." >nul
if errorlevel 1 (
    echo # placeholder so git tracks this folder>"%keep_dir%\.gitkeep"
)
goto :eof

:safe_pause
if defined SCAFFOLDER_AUTOMATED (
    pause <nul
) else (
    pause
)
goto :eof
