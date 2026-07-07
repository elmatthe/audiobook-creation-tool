@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

:: ============================================================================
::  Map-Repo-Structure.bat
:: ----------------------------------------------------------------------------
::  Drop this file into ANY repository root and double-click it. It scans that
::  folder and every subfolder, then writes a clean markdown tree to
::  REPO-STRUCTURE.md in the SAME folder -- ready to paste to an AI so it knows
::  your current layout before you ask for changes.
::
::  Noise folders (.git, .venv, __pycache__, node_modules, files\bin, build,
::  dist, test-logs) are skipped so the map stays readable. Edit EXCLUDE_DIRS
::  below to change what's hidden. The output file and this script exclude
::  themselves from the tree.
:: ============================================================================

set "OUT=REPO-STRUCTURE.md"
set "SELF=%~nx0"

:: Folder names to skip anywhere in the tree (space-separated, lowercase).
set "EXCLUDE_DIRS=.git .venv __pycache__ node_modules .pytest_cache .mypy_cache .ruff_cache build dist bin test-logs"

for %%I in ("%CD%") do set "REPO_NAME=%%~nxI"

echo ========================================
echo   Mapping repository structure
echo   Repo: %REPO_NAME%
echo ========================================
echo.
echo   Scanning "%CD%" ...

:: A PowerShell helper does the recursion and writes the markdown. We pass
:: values in through environment variables to avoid quoting headaches.
set "MRS_OUT=%OUT%"
set "MRS_SELF=%SELF%"
set "MRS_EXCLUDE=%EXCLUDE_DIRS%"

set "ps_helper=%TEMP%\map_repo_%RANDOM%%RANDOM%.ps1"
call :write_helper "%ps_helper%"

powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%ps_helper%"
set "PS_EXIT=%errorlevel%"
del "%ps_helper%" >nul 2>&1

echo.
if "%PS_EXIT%"=="0" (
    if exist "%OUT%" (
        echo   Done. Wrote %OUT% to:
        echo   %CD%
    ) else (
        echo   ERROR: helper ran but %OUT% is missing.
    )
) else (
    echo   ERROR: Could not generate %OUT%. See messages above.
)
echo.
pause
endlocal
exit /b 0


:: ----------------------------------------------------------------------------
:: write_helper - emit the PowerShell script line by line to %1
:: Uses ~ as a placeholder for the pipe char, swapped to '|' inside PS, so no
:: batch pipe-escaping is needed on any line.
:: ----------------------------------------------------------------------------
:write_helper
set "H=%~1"
> "%H%" echo $ErrorActionPreference = 'Stop'
>> "%H%" echo $root = (Get-Location).Path
>> "%H%" echo $repoName = Split-Path -Leaf $root
>> "%H%" echo $outFile = $env:MRS_OUT
>> "%H%" echo $selfBat = $env:MRS_SELF
>> "%H%" echo $exclude = @($env:MRS_EXCLUDE.Split(' ')) ^| Where-Object { $_ -ne '' }
>> "%H%" echo $PIPE = [char]0x7C
>> "%H%" echo $BAR  = $PIPE + '   '
>> "%H%" echo $TEE  = $PIPE + '-- '
>> "%H%" echo $ELL  = '\-- '
>> "%H%" echo $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm'
>> "%H%" echo $lines = New-Object System.Collections.Generic.List[string]
>> "%H%" echo $null = $lines.Add('# ' + $repoName + ' - Repository Structure')
>> "%H%" echo $null = $lines.Add('')
>> "%H%" echo $null = $lines.Add('_Generated ' + $stamp + ' by Map-Repo-Structure.bat._')
>> "%H%" echo $null = $lines.Add('')
>> "%H%" echo $null = $lines.Add('``````')
>> "%H%" echo $null = $lines.Add($repoName + '/')
>> "%H%" echo function Walk($dir, $prefix) {
>> "%H%" echo   $all = Get-ChildItem -LiteralPath $dir -Force
>> "%H%" echo   $items = @()
>> "%H%" echo   foreach ($it in $all) {
>> "%H%" echo     if ($it.PSIsContainer -and ($exclude -contains $it.Name.ToLower())) { continue }
>> "%H%" echo     if (-not $it.PSIsContainer -and ($it.Name -eq $outFile -or $it.Name -eq $selfBat)) { continue }
>> "%H%" echo     $items += $it
>> "%H%" echo   }
>> "%H%" echo   $items = $items ^| Sort-Object @{Expression={ -not $_.PSIsContainer }}, Name
>> "%H%" echo   for ($i = 0; $i -lt $items.Count; $i++) {
>> "%H%" echo     $item = $items[$i]
>> "%H%" echo     $last = ($i -eq ($items.Count - 1))
>> "%H%" echo     if ($last) { $connector = $ELL } else { $connector = $TEE }
>> "%H%" echo     if ($item.PSIsContainer) { $name = $item.Name + '/' } else { $name = $item.Name }
>> "%H%" echo     $null = $lines.Add($prefix + $connector + $name)
>> "%H%" echo     if ($item.PSIsContainer) {
>> "%H%" echo       if ($last) { $childPrefix = $prefix + '    ' } else { $childPrefix = $prefix + $BAR }
>> "%H%" echo       Walk $item.FullName $childPrefix
>> "%H%" echo     }
>> "%H%" echo   }
>> "%H%" echo }
>> "%H%" echo Walk $root ''
>> "%H%" echo $null = $lines.Add('``````')
>> "%H%" echo Set-Content -LiteralPath $outFile -Value $lines -Encoding UTF8
goto :eof
