<#
bootstrap_host.ps1 - stage 0 of the Windows setup: provide the app's OWN Python, inside the app's folder, and tell the
launcher where it is.

Called by Setup_and_Run-audiobook-creation-tool.bat on a first run or an environment repair, never on an ordinary launch.
Everything after this (the .venv, the packages, FFmpeg, the optional models, the health proof, the launch) belongs to
scripts\shared\bootstrap.py; this file only provides a proven base Python, because bootstrap.py cannot run without one.

v0.7.0 portable layout: the app never installs Python on the computer and never depends on one that happens to be
installed. Its Python lives at files\runtime-data\python (outside .venv on purpose: a repair renames .venv aside while
this Python runs the repair, so it cannot live inside the folder being replaced).

1. If files\runtime-data\python\python.exe exists, RUN it to prove it is 3.12 with ssl, venv, ensurepip and a working
   Tk, and use it.
2. Otherwise explain and ask. Nothing is downloaded without a Yes.
3. Download the pinned standalone CPython build (python-build-standalone, the relocatable build uv uses) over HTTPS
   into files\temp\bootstrap, check its exact size and SHA-256 (the authority: these builds are not code-signed),
   unpack it with Windows' own tar.exe into a staging folder, move the complete interpreter into place with one rename,
   prove it by running it, and delete the archive and the staging folder. No installer runs, nothing is registered,
   PATH and file associations are untouched, and nothing is written outside the app's folder.
4. Write the proven interpreter's full path to -OutFile and exit 0.

Exit codes: 0 = a proven Python is in -OutFile; 2 = the user declined (nothing downloaded); 3 = it could not be done.
(PowerShell's own 1 - for example a script blocked by policy - is left to mean "stage 0 did not run".)
The switches after -OutFile exist for qualification testing only; the launcher passes none of them.
#>
[CmdletBinding()]
param(
    [string]$OutFile,
    [switch]$AssumeYes,         # qualification: answer Yes without showing the question
    [switch]$AssumeNo,          # qualification: answer No without showing the question
    [switch]$DownloadOnly,      # qualification: download and verify the archive, but do not unpack it
    [string]$ArchivePath        # qualification: verify and use this file instead of downloading
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest is many times slower while drawing a progress bar

$Repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Downloads = Join-Path $Repo 'files\temp\bootstrap'
$PythonHome = Join-Path $Repo 'files\runtime-data\python'
$PyVersion = '3.12.15'
$BuildTag = '20261009'
$ArchiveName = "cpython-$PyVersion+$BuildTag-x86_64-pc-windows-msvc-install_only.tar.gz"
$ArchiveUrl = "https://github.com/astral-sh/python-build-standalone/releases/download/$BuildTag/cpython-$PyVersion%2B$BuildTag-x86_64-pc-windows-msvc-install_only.tar.gz"
$ArchiveSize = 46352482
$ArchiveSha256 = '194C8F0D9E0DE6F1C4576E5DFA67819A48C764BE87608B74B8AD43387A57B93B'
# Tk is proved by initialising it (a withdrawn, destroyed root: no window is shown). Tcl() alone never loads Tk, so a
# Python whose tk.tcl is missing used to pass here and then fail to open the app's window (audit ACT67-AUD-006).
$Probe = "import sys, ssl, venv, ensurepip, tkinter; r = tkinter.Tk(); r.withdraw(); r.destroy(); v = sys.version_info; print(sys.executable); print('%d.%d' % (v[0], v[1]))"
$ProbeTimeoutMs = 60000                    # a first start can be slow while Windows checks new files

function Say([string]$Message) { Write-Host $Message }

function Test-Candidate([string]$Exe) {
    # Run it; return its own full path when it is 3.12 with ssl, venv, ensurepip and Tk, otherwise $null.
    if (-not (Test-Path -LiteralPath $Exe)) { return $null }
    try {
        # Bounded: run it as a process we can stop, never with '&', which would wait forever on a hung interpreter.
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $Exe
        $psi.Arguments = '-I -c "' + $Probe + '"'
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $true
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $proc = [System.Diagnostics.Process]::Start($psi)
        $stdout = $proc.StandardOutput.ReadToEndAsync()
        $null = $proc.StandardError.ReadToEndAsync()
        if (-not $proc.WaitForExit($ProbeTimeoutMs)) {
            try { $proc.Kill() } catch { }
            return $null
        }
        if ($proc.ExitCode -ne 0) { return $null }
        $lines = @($stdout.Result.Trim() -split "`r?`n")
        if ($lines.Count -lt 2 -or $lines[1] -ne '3.12') { return $null }
        if (-not (Test-Path -LiteralPath $lines[0])) { return $null }
        return $lines[0]
    } catch {
        return $null
    }
}

function Ask-Consent {
    if ($AssumeYes) { return $true }
    if ($AssumeNo) { return $false }
    $text = "The Audiobook Creation Tool runs on its own copy of Python, kept inside this folder.`n`n" +
            "Download Python $PyVersion for it now?`n`n" +
            "  - about 46 MB to download (the standalone CPython build from python-build-standalone)`n" +
            "  - kept only inside this folder (files\runtime-data\python); nothing is installed on the computer`n" +
            "  - no administrator rights; your PATH and file associations are not changed`n`n" +
            "Choose No to stop without downloading anything."
    try {
        Add-Type -AssemblyName System.Windows.Forms
        $answer = [System.Windows.Forms.MessageBox]::Show($text, 'Audiobook Creation Tool - download Python',
            [System.Windows.Forms.MessageBoxButtons]::YesNo, [System.Windows.Forms.MessageBoxIcon]::Question)
        return ($answer -eq [System.Windows.Forms.DialogResult]::Yes)
    } catch {
        Say $text
        $reply = Read-Host 'Download Python now? Type Y and press Enter for yes'
        return ($reply -match '^\s*[Yy]')
    }
}

function Test-Archive([string]$Path) {
    # The pinned size and SHA-256 decide (the build is not code-signed, so its hash is its identity).
    $item = Get-Item -LiteralPath $Path
    if ($item.Length -ne $ArchiveSize) { return "it is $($item.Length) bytes, not $ArchiveSize" }
    $hash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    if ($hash -ne $ArchiveSha256) { return "its SHA-256 is $hash, not the pinned $ArchiveSha256" }
    return $null
}

function Get-Archive {
    if ($ArchivePath) {
        $problem = Test-Archive $ArchivePath
        if ($problem) { throw "The Python archive at $ArchivePath was rejected: $problem." }
        return $ArchivePath
    }
    New-Item -ItemType Directory -Force -Path $Downloads | Out-Null
    $target = Join-Path $Downloads $ArchiveName
    if (Test-Path -LiteralPath $target) {
        if (-not (Test-Archive $target)) {
            Say 'Reusing the Python archive downloaded earlier (it is still the verified file).'
            return $target
        }
        Remove-Item -LiteralPath $target -Force
    }
    $part = "$target.part"
    Say "Downloading Python $PyVersion (about 46 MB)..."
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -UseBasicParsing -Uri $ArchiveUrl -OutFile $part
    $problem = Test-Archive $part
    if ($problem) {
        Remove-Item -LiteralPath $part -Force -ErrorAction SilentlyContinue
        throw "The downloaded Python archive was rejected and deleted: $problem."
    }
    Move-Item -LiteralPath $part -Destination $target -Force
    return $target
}

function Install-Local([string]$Archive) {
    # Unpack into a staging folder beside the destination, then move the complete interpreter into place in one rename.
    $tar = Join-Path $env:SystemRoot 'System32\tar.exe'
    if (-not (Test-Path -LiteralPath $tar)) { throw 'Windows tar.exe was not found (it ships with Windows 10 1803 and later).' }
    $staging = Join-Path $Downloads 'python-staging'
    if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $staging | Out-Null
    Say "Unpacking Python $PyVersion into this folder..."
    & $tar -xzf $Archive -C $staging
    if ($LASTEXITCODE -ne 0) { throw "tar.exe could not unpack the archive (exit $LASTEXITCODE)." }
    $unpacked = Join-Path $staging 'python'
    if (-not (Test-Path -LiteralPath (Join-Path $unpacked 'python.exe'))) { throw 'The archive did not contain python\python.exe.' }
    if (Test-Path -LiteralPath $PythonHome) {
        # A copy that failed its proof: set it aside rather than deleting it blind, then remove it.
        $old = "$PythonHome.old"
        if (Test-Path -LiteralPath $old) { Remove-Item -LiteralPath $old -Recurse -Force }
        Move-Item -LiteralPath $PythonHome -Destination $old
        Remove-Item -LiteralPath $old -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $PythonHome) | Out-Null
    Move-Item -LiteralPath $unpacked -Destination $PythonHome
    Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
    return Test-Candidate (Join-Path $PythonHome 'python.exe')
}

function Write-Result([string]$Python) {
    if ($OutFile) {
        $dir = Split-Path -Parent $OutFile
        if ($dir) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
        [IO.File]::WriteAllText($OutFile, $Python, (New-Object System.Text.UTF8Encoding($false)))
    }
    Say "Using Python: $Python"
}

try {
    $python = Test-Candidate (Join-Path $PythonHome 'python.exe')
    if ($python) { Write-Result $python; exit 0 }
    if (Test-Path -LiteralPath $PythonHome) { Say "The app's own Python in files\runtime-data\python does not work; it will be replaced." }
    else { Say "The app's own Python has not been downloaded yet." }
    if (-not (Ask-Consent)) {
        Say 'Python was not downloaded. Run the setup again whenever you are ready.'
        exit 2
    }
    $archive = Get-Archive
    if ($DownloadOnly) {
        Say "Verified archive: $archive (not unpacked: -DownloadOnly)."
        exit 0
    }
    $python = Install-Local $archive
    if (-not $python) {
        Say "The app's own Python was unpacked but could not be started. Nothing outside this folder was changed."
        exit 3
    }
    if (-not $ArchivePath) { Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue }
    Write-Result $python
    exit 0
} catch {
    Say "Setting up Python stopped: $($_.Exception.Message)"
    exit 3
}
