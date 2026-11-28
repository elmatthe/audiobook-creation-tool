<#
bootstrap_host.ps1 - stage 0 of the Windows setup: provide the app's OWN uv and Python, inside the app's folder, and
tell the launcher where the Python is.

Called by Setup_and_Run-audiobook-creation-tool.bat on a first run or an environment repair, never on an ordinary launch.
Everything after this (the .venv, the packages, FFmpeg, the optional models, the health proof, the launch) belongs to
scripts\shared\bootstrap.py; this file only provides the pinned tools bootstrap.py needs.

v0.8.2 Phase 4 (owner decisions recorded in Phase 3B): the app's Python is CPython 3.12.15 from python-build-standalone
20261009, installed by the pinned uv 0.13.10 from ACT's own verified copy of the archive, through ACT's own download
metadata (scripts\shared\python-downloads.json), so uv can never pick another build. Nothing is installed on the
computer: no installer runs, nothing is registered, PATH and file associations are untouched, nothing is written
outside the app's folder. (The Python earlier versions kept in files\runtime-data\python is left exactly as it is:
voice engines installed before this version still run on it.)

1. uv: files\runtime-data\uv\uv.exe must be exactly the pinned program (its SHA-256).
2. Python: files\runtime-data\uv\python\cpython-3.12.15-windows-x86_64-none\python.exe is RUN to prove it is the pinned
   build (sys.version, uv's BUILD stamp) with ssl, venv, ensurepip and a working Tk. A copied or moved app folder
   whose uv link "cpython-3.12-windows-x86_64-none" still points at the old folder is refreshed.
3. Anything missing: explain and ask ONCE. Nothing is downloaded without a Yes. Each download (the uv ZIP, the Python
   archive) goes over HTTPS into files\temp\bootstrap and is checked against its exact size and SHA-256 before it is
   used; uv.exe is unpacked with Windows' own tar.exe and checked against its own SHA-256. The Python archive is kept
   in files\runtime-data\uv\mirror (a later repair restores the interpreter from it with no network), and uv installs
   it from there with a contained environment and a scratch folder of its own, removed afterwards.
4. Write the proven interpreter's path, relative to the app's folder, to -OutFile and exit 0.

Exit codes: 0 = a proven Python is in -OutFile; 2 = the user declined (nothing downloaded); 3 = it could not be done.
(PowerShell's own 1 - for example a script blocked by policy - is left to mean "stage 0 did not run"; the launcher then
uses bootstrap_host_fallback.cmd, which does the same with curl.exe, certutil and tar.exe.)
The switches after -OutFile exist for qualification testing only; the launcher passes none of them.
#>
[CmdletBinding()]
param(
    [string]$OutFile,
    [switch]$AssumeYes,         # qualification: answer Yes without showing the question
    [switch]$AssumeNo,          # qualification: answer No without showing the question
    [switch]$DownloadOnly,      # qualification: download and verify, but install nothing
    [string]$ArchivePath,       # qualification: verify and use this Python archive instead of downloading
    [string]$UvArchivePath      # qualification: verify and use this uv ZIP instead of downloading
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest is many times slower while drawing a progress bar

$Repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Downloads = Join-Path $Repo 'files\temp\bootstrap'
$UvHome = Join-Path $Repo 'files\runtime-data\uv'
$UvExe = Join-Path $UvHome 'uv.exe'
$PyInstallDir = Join-Path $UvHome 'python'
$MirrorDir = Join-Path $UvHome 'mirror'
$DownloadsJson = Join-Path $Repo 'scripts\shared\python-downloads.json'

# Pins (keep in step with scripts\shared\uv_runner.py and bootstrap_host_fallback.cmd; a test holds them together).
$UvVersion = '0.13.10'
$UvArchiveName = 'uv-x86_64-pc-windows-msvc.zip'
$UvUrl = "https://github.com/astral-sh/uv/releases/download/$UvVersion/$UvArchiveName"
$UvSize = 15641577
$UvSha256 = '297B3881FE1ADFB922BECC2C1613202ABB41DC83EA5FF43D472AA087CA1F8683'
$UvExeSha256 = '9F9F3631112F847C81B2063637CE01F4DD8D65E8AC2A8F4BB1C121F7EFFA5C76'
$PyVersion = '3.12.15'
$BuildTag = '20261009'
$PyKey = 'cpython-3.12.15-windows-x86_64-none'
$PyMinorKey = 'cpython-3.12-windows-x86_64-none'
$ArchiveName = "cpython-$PyVersion+$BuildTag-x86_64-pc-windows-msvc-install_only.tar.gz"
$ArchiveUrl = "https://github.com/astral-sh/python-build-standalone/releases/download/$BuildTag/cpython-$PyVersion%2B$BuildTag-x86_64-pc-windows-msvc-install_only.tar.gz"
$ArchiveSize = 46352482
$ArchiveSha256 = '194C8F0D9E0DE6F1C4576E5DFA67819A48C764BE87608B74B8AD43387A57B93B'
$PySysVersion = '3.12.15 (main, Oct  9 2026, 15:21:55) [MSC v.1944 64 bit (AMD64)]'

$PyHome = Join-Path $PyInstallDir $PyKey
$PyExe = Join-Path $PyHome 'python.exe'
$MirrorArchive = Join-Path (Join-Path $MirrorDir $BuildTag) $ArchiveName
# Tk is proved by initialising it (a withdrawn, destroyed root: no window is shown). Tcl() alone never loads Tk, so a
# Python whose tk.tcl is missing used to pass here and then fail to open the app's window (audit ACT67-AUD-006).
# The interpreter's own path is handed TO it (an argument is passed as Unicode) and compared there; it is never read
# back from its output, which Python writes in the computer's ANSI code page and would garble a folder named, say,
# "Livres ete" with accents (found by the v0.8.2 Phase 4 fresh-copy run). Only sys.version, plain ASCII, comes back.
$Probe = "import os, sys, ssl, venv, ensurepip, tkinter; r = tkinter.Tk(); r.withdraw(); r.destroy(); assert os.path.samefile(sys.executable, sys.argv[1]); print(sys.version)"
$ProbeTimeoutMs = 30000                    # the one bound for every Tk proof (ACT67-CLR-003)

function Say([string]$Message) { Write-Host $Message }

function Test-Candidate([string]$Exe) {
    # Run it; return its full path when it is exactly the pinned build with ssl, venv, ensurepip and Tk, else $null.
    if (-not (Test-Path -LiteralPath $Exe)) { return $null }
    try {
        # Bounded: run it as a process we can stop, never with '&', which would wait forever on a hung interpreter.
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $Exe
        $psi.Arguments = '-I -c "' + $Probe + '" "' + $Exe + '"'
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
        if ($lines.Count -lt 1 -or $lines[-1] -ne $PySysVersion) { return $null }
        return $Exe
    } catch {
        return $null
    }
}

function Get-Sha256([string]$Path) {
    # .NET directly, not Get-FileHash: that cmdlet comes from a module, and a PowerShell 7 module path inherited from
    # the window the launcher was started in makes Windows PowerShell 5.1 fail to load it (found 2026-10-31).
    $stream = [System.IO.File]::OpenRead($Path)
    try {
        $sha = [System.Security.Cryptography.SHA256]::Create()
        try { $bytes = $sha.ComputeHash($stream) } finally { $sha.Dispose() }
    } finally {
        $stream.Dispose()
    }
    return -join ($bytes | ForEach-Object { $_.ToString('X2') })
}

function Test-File([string]$Path, [long]$Size, [string]$Sha256) {
    # The pinned size and SHA-256 decide (these archives are not code-signed as a whole, so the hash is their identity).
    $item = Get-Item -LiteralPath $Path
    if ($item.Length -ne $Size) { return "it is $($item.Length) bytes, not $Size" }
    $hash = Get-Sha256 $Path
    if ($hash -ne $Sha256) { return "its SHA-256 is $hash, not the pinned $Sha256" }
    return $null
}

function Test-Uv {
    if (-not (Test-Path -LiteralPath $UvExe -PathType Leaf)) { return $false }
    return ((Get-Sha256 $UvExe) -eq $UvExeSha256)
}

function Test-Python {
    # The pinned build, proved by running it, with uv's own BUILD stamp.
    $build = Join-Path $PyHome 'BUILD'
    if (-not (Test-Path -LiteralPath $build -PathType Leaf)) { return $null }
    if ((Get-Content -LiteralPath $build -Raw).Trim() -ne $BuildTag) { return $null }
    return Test-Candidate $PyExe
}

function Test-MinorLinkStale {
    # uv keeps a "cpython-3.12-..." junction beside the versioned folder. A copied or moved app folder carries one that
    # still points at the old place until uv installs the interpreter again (Phase 3A); nothing of the app uses it, but
    # it is refreshed so uv itself never reaches back into another folder.
    $link = Join-Path $PyInstallDir $PyMinorKey
    if (-not (Test-Path -LiteralPath $link)) { return $false }
    $target = @((Get-Item -LiteralPath $link -Force).Target)
    if ($target.Count -lt 1 -or -not $target[0]) { return $false }
    $resolved = $target[0] -replace '^\\\\\?\\', ''
    return -not ($resolved.TrimEnd('\') -ieq $PyHome.TrimEnd('\'))
}

function Ask-Consent([string[]]$Items) {
    if ($AssumeYes) { return $true }
    if ($AssumeNo) { return $false }
    $text = "The Audiobook Creation Tool runs on its own copy of Python and its own package tool, kept inside this folder.`n`n" +
            "Download them now?`n`n" + (($Items | ForEach-Object { "  - $_" }) -join "`n") + "`n`n" +
            "  - kept only inside this folder (files\runtime-data\uv); nothing is installed on the computer`n" +
            "  - no administrator rights; your PATH and file associations are not changed`n`n" +
            "Choose No to stop without downloading anything."
    try {
        Add-Type -AssemblyName System.Windows.Forms
        $answer = [System.Windows.Forms.MessageBox]::Show($text, 'Audiobook Creation Tool - download Python',
            [System.Windows.Forms.MessageBoxButtons]::YesNo, [System.Windows.Forms.MessageBoxIcon]::Question)
        return ($answer -eq [System.Windows.Forms.DialogResult]::Yes)
    } catch {
        Say $text
        $reply = Read-Host 'Download now? Type Y and press Enter for yes'
        return ($reply -match '^\s*[Yy]')
    }
}

function Get-Verified([string]$Given, [string]$Url, [string]$Name, [long]$Size, [string]$Sha256, [string]$What) {
    # A verified local file: the qualification copy, the copy downloaded earlier, or a fresh download. Never unverified.
    if ($Given) {
        $problem = Test-File $Given $Size $Sha256
        if ($problem) { throw "The $What at $Given was rejected: $problem." }
        return $Given
    }
    New-Item -ItemType Directory -Force -Path $Downloads | Out-Null
    $target = Join-Path $Downloads $Name
    if (Test-Path -LiteralPath $target) {
        if (-not (Test-File $target $Size $Sha256)) {
            Say "Reusing the $What downloaded earlier (it is still the verified file)."
            return $target
        }
        Remove-Item -LiteralPath $target -Force
    }
    $part = "$target.part"
    Say "Downloading the $What..."
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $part
    $problem = Test-File $part $Size $Sha256
    if ($problem) {
        Remove-Item -LiteralPath $part -Force -ErrorAction SilentlyContinue
        throw "The downloaded $What was rejected and deleted: $problem."
    }
    Move-Item -LiteralPath $part -Destination $target -Force
    return $target
}

function Install-Uv([string]$Zip) {
    # Unpack with Windows' own tar.exe into a staging folder, check uv.exe's own digest, then move it into place.
    $tar = Join-Path $env:SystemRoot 'System32\tar.exe'
    if (-not (Test-Path -LiteralPath $tar)) { throw 'Windows tar.exe was not found (it ships with Windows 10 1803 and later).' }
    $staging = Join-Path $Downloads 'uv-staging'
    if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $staging | Out-Null
    Say "Unpacking uv $UvVersion into this folder..."
    & $tar -xf $Zip -C $staging uv.exe
    if ($LASTEXITCODE -ne 0) { throw "tar.exe could not unpack the uv archive (exit $LASTEXITCODE)." }
    $unpacked = Join-Path $staging 'uv.exe'
    if (-not (Test-Path -LiteralPath $unpacked -PathType Leaf)) { throw 'The uv archive did not contain uv.exe.' }
    if ((Get-Sha256 $unpacked) -ne $UvExeSha256) { throw 'The unpacked uv.exe is not the pinned program.' }
    New-Item -ItemType Directory -Force -Path $UvHome | Out-Null
    if (Test-Path -LiteralPath $UvExe) { Remove-Item -LiteralPath $UvExe -Force }
    Move-Item -LiteralPath $unpacked -Destination $UvExe
    Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
}

function Save-Archive([string]$Archive) {
    # ACT's own offline copy of the interpreter archive, laid out as uv's --mirror reads it: <mirror>\<build>\<name>.
    $folder = Split-Path -Parent $MirrorArchive
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
    if ($ArchivePath) { Copy-Item -LiteralPath $Archive -Destination $MirrorArchive -Force }
    else { Move-Item -LiteralPath $Archive -Destination $MirrorArchive -Force }
    $problem = Test-File $MirrorArchive $ArchiveSize $ArchiveSha256
    if ($problem) { throw "The kept Python archive is not the verified file: $problem." }
}

function Install-Managed([bool]$Reinstall) {
    # uv installs exactly the pinned build from the kept archive (a file:// mirror: no network), with every setting uv
    # could read from this computer removed and a scratch folder of its own (shared\uv_runner.py does the same).
    $scratch = Join-Path (Join-Path $UvHome 't') ([guid]::NewGuid().ToString('N').Substring(0, 8))
    New-Item -ItemType Directory -Force -Path (Join-Path $scratch 'tmp'), (Join-Path $scratch 'pyc') | Out-Null
    $saved = @{}
    foreach ($entry in @(Get-ChildItem Env:)) {
        if ($entry.Name -match '^(UV_|PIP_|XDG_|CONDA_|PYTHON|SSL_CERT_)' -or $entry.Name -in @('VIRTUAL_ENV', 'VIRTUAL_ENV_PROMPT', 'TEMP', 'TMP')) {
            $saved[$entry.Name] = $entry.Value
            Remove-Item -LiteralPath ("Env:" + $entry.Name)
        }
    }
    $confined = Join-Path $UvHome 'home'
    $settings = @{
        'UV_NO_CONFIG' = '1'; 'UV_NO_ENV_FILE' = '1'; 'UV_CACHE_DIR' = (Join-Path $Repo 'files\runtime-data\uvc');
        'UV_PYTHON_INSTALL_DIR' = $PyInstallDir; 'UV_PYTHON_CACHE_DIR' = (Join-Path $scratch 'pyc');
        'UV_PYTHON_BIN_DIR' = (Join-Path $confined 'pybin'); 'UV_PYTHON_INSTALL_BIN' = '0';
        'UV_PYTHON_INSTALL_REGISTRY' = '0'; 'UV_PYTHON_NO_REGISTRY' = '1'; 'UV_PYTHON_PREFERENCE' = 'only-managed';
        'UV_PYTHON_DOWNLOADS' = 'manual'; 'UV_PYTHON_DOWNLOADS_JSON_URL' = $DownloadsJson;
        'UV_TOOL_DIR' = (Join-Path $confined 'tools'); 'UV_TOOL_BIN_DIR' = (Join-Path $confined 'tool-bin');
        'UV_CREDENTIALS_DIR' = (Join-Path $confined 'credentials'); 'UV_NO_PROGRESS' = '1'; 'NO_COLOR' = '1';
        'TEMP' = (Join-Path $scratch 'tmp'); 'TMP' = (Join-Path $scratch 'tmp')
    }
    foreach ($key in $settings.Keys) { Set-Item -LiteralPath ("Env:" + $key) -Value $settings[$key] }
    try {
        $mirror = ([System.Uri]$MirrorDir).AbsoluteUri
        $arguments = @('python', 'install', $PyVersion, '--mirror', $mirror, '--python-downloads-json-url', $DownloadsJson,
                       '--no-bin', '--no-registry', '--no-config', '--color', 'never', '--no-progress')
        if ($Reinstall) { $arguments += '--reinstall' }
        Say "Installing Python $PyVersion into this folder (from the verified copy kept here; nothing is downloaded)..."
        & $UvExe @arguments
        if ($LASTEXITCODE -ne 0) { throw "uv could not install the app's Python (exit $LASTEXITCODE)." }
    } finally {
        foreach ($key in $settings.Keys) { Remove-Item -LiteralPath ("Env:" + $key) -ErrorAction SilentlyContinue }
        foreach ($key in $saved.Keys) { Set-Item -LiteralPath ("Env:" + $key) -Value $saved[$key] }
        Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Write-Result([string]$Python) {
    # The launcher reads -OutFile with cmd.exe, in the console's code page, so it is given the interpreter's path
    # relative to the app's folder (plain ASCII; the launcher runs it from that folder): an absolute path with any
    # letter outside that code page would not survive the trip.
    if ($OutFile) {
        $dir = Split-Path -Parent $OutFile
        if ($dir) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
        [IO.File]::WriteAllText($OutFile, "files\runtime-data\uv\python\$PyKey\python.exe",
            (New-Object System.Text.ASCIIEncoding))
    }
    Say "Using Python: $Python"
}

try {
    $uvOk = Test-Uv
    $python = Test-Python
    $stale = $false
    if ($python) { $stale = Test-MinorLinkStale }
    if ($uvOk -and $python -and -not $stale) { Write-Result $python; exit 0 }

    if (-not $uvOk) {
        if (Test-Path -LiteralPath $UvExe) { Say "The app's uv in files\runtime-data\uv is not the pinned program; it will be replaced." }
        else { Say "The app's package tool (uv $UvVersion) has not been downloaded yet." }
    }
    if (-not $python) {
        if (Test-Path -LiteralPath $PyHome) { Say "The app's own Python in files\runtime-data\uv\python does not work; it will be replaced." }
        else { Say "The app's own Python has not been installed yet." }
    } elseif ($stale) {
        Say "This copy of the app was moved or copied; its Python is refreshed for the new folder."
    }

    $needArchive = (-not $python -or $stale) -and ((-not (Test-Path -LiteralPath $MirrorArchive)) -or
                   (Test-File $MirrorArchive $ArchiveSize $ArchiveSha256))
    $items = @()
    if (-not $uvOk -and -not $UvArchivePath) { $items += "uv $UvVersion, the package tool from Astral (about 16 MB)" }
    if ($needArchive -and -not $ArchivePath) { $items += "Python $PyVersion, the standalone CPython build from python-build-standalone (about 46 MB)" }
    if ($items.Count -gt 0) {
        if (-not (Ask-Consent $items)) {
            Say 'Nothing was downloaded. Run the setup again whenever you are ready.'
            exit 2
        }
    }
    if (-not $uvOk) {
        $zip = Get-Verified $UvArchivePath $UvUrl $UvArchiveName $UvSize $UvSha256 'uv package tool'
        if (-not $DownloadOnly) {
            Install-Uv $zip
            if (-not $UvArchivePath) { Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue }
        }
    }
    if ($needArchive) {
        $archive = Get-Verified $ArchivePath $ArchiveUrl $ArchiveName $ArchiveSize $ArchiveSha256 'Python archive'
        if (-not $DownloadOnly) { Save-Archive $archive }
    }
    if ($DownloadOnly) {
        Say 'Verified the downloads (not installed: -DownloadOnly).'
        exit 0
    }
    if (-not $python -or $stale) {
        Install-Managed ($stale -or (Test-Path -LiteralPath $PyHome))
        $python = Test-Python
        if (-not $python) {
            Say "The app's own Python was installed but could not be started. Nothing outside this folder was changed."
            exit 3
        }
    }
    Write-Result $python
    exit 0
} catch {
    Say "Setting up Python stopped: $($_.Exception.Message)"
    exit 3
}
