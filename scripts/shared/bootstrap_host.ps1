<#
bootstrap_host.ps1 - stage 0 of the Windows setup: find, or (only with the user's consent) install, a Python that the
Audiobook Creation Tool can build its private environment from, and tell the launcher which one.

Called by Setup_and_Run-audiobook-creation-tool.bat on a first run or an environment repair, never on an ordinary launch.
Everything after this (the .venv, the packages, FFmpeg, the optional models, the health proof, the launch) belongs to
scripts\shared\bootstrap.py; this file only provides a proven base Python, because bootstrap.py cannot run without one.

1. Discover candidates (py -3.12, py -3.11, the usual per-user and machine install folders, python on PATH) and RUN each
   one to prove it is 3.11 or 3.12 with ssl, venv and a working Tk. The Microsoft Store "python" alias is never run.
2. If none works: explain and ask. Nothing is installed without a Yes.
3. Install the pinned official python.org 3.12.10 installer for this user only (no administrator rights, no PATH change,
   no file associations): downloaded over HTTPS into files\temp\bootstrap, then checked against the pinned size and
   SHA-256 (the authority) and its Python Software Foundation Authenticode signature. winget is used only if the direct
   route fails and winget is already present. The exit code of an installer is never taken as proof: the result is run
   and checked again, and the installer file is deleted once Python is proven.
4. Write the proven interpreter's full path to -OutFile and exit 0.

Exit codes: 0 = a proven Python is in -OutFile; 2 = the user declined (nothing installed); 3 = it could not be done.
(PowerShell's own 1 - for example a script blocked by policy - is left to mean "stage 0 did not run".)
The switches after -OutFile exist for qualification testing only; the launcher passes none of them.
#>
[CmdletBinding()]
param(
    [string]$OutFile,
    [switch]$AssumeYes,         # qualification: answer Yes without showing the question
    [switch]$AssumeNo,          # qualification: answer No without showing the question
    [switch]$IgnoreInstalled,   # qualification: behave as if no usable Python were installed
    [switch]$DownloadOnly,      # qualification: download and verify the installer, but do not run it
    [string]$InstallerPath,     # qualification: verify and use this file instead of downloading
    [switch]$NoWinget           # qualification: never fall back to winget
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest is many times slower while drawing a progress bar

$Repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Downloads = Join-Path $Repo 'files\temp\bootstrap'
$PyVersion = '3.12.10'                     # the last 3.12 release with a Windows installer; the app is tested on it
$InstallerName = "python-$PyVersion-amd64.exe"
$InstallerUrl = "https://www.python.org/ftp/python/$PyVersion/$InstallerName"
$InstallerSize = 26964224
$InstallerSha256 = '67B5635E80EA51072B87941312D00EC8927C4DB9BA18938F7AD2D27B328B95FB'
$InstallerSigner = 'Python Software Foundation'
$TargetDir = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312'
# Tk is proved by initialising it (a withdrawn, destroyed root: no window is shown). Tcl() alone never loads Tk, so a
# Python whose tk.tcl is missing used to pass here and then fail to open the app's window (audit ACT67-AUD-006).
$Probe = "import sys, ssl, venv, tkinter; r = tkinter.Tk(); r.withdraw(); r.destroy(); v = sys.version_info; print(sys.executable); print('%d.%d' % (v[0], v[1]))"
$ProbeTimeoutMs = 30000                    # a candidate that has not answered by then is not used (a hung Tk cannot run the app)

function Say([string]$Message) { Write-Host $Message }

function Test-Candidate([string[]]$Command) {
    # Run the candidate; return its own full path when it is 3.11/3.12 with ssl, venv and Tk, otherwise $null.
    $exe = $Command[0]
    if ($exe -like '*\WindowsApps\*') { return $null }   # the Store alias opens the Store; it is not a Python
    $rest = @()
    if ($Command.Count -gt 1) { $rest = $Command[1..($Command.Count - 1)] }
    try {
        # Bounded: run it as a process we can stop, never with '&', which would wait forever on a hung interpreter.
        # (Windows PowerShell 5.1 has no ProcessStartInfo.ArgumentList; none of these arguments contains a double quote.)
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $exe
        $psi.Arguments = (@($rest) + @('-c', $Probe) | ForEach-Object { '"' + $_ + '"' }) -join ' '
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
        $out = $stdout.Result.Trim()
        if (-not $out) { return $null }
        $lines = @($out -split "`r?`n")
        if ($lines.Count -lt 2) { return $null }
        if ($lines[1] -ne '3.12' -and $lines[1] -ne '3.11') { return $null }
        if (-not (Test-Path -LiteralPath $lines[0])) { return $null }
        return $lines[0]
    } catch {
        return $null
    }
}

function Find-Python {
    $candidates = New-Object System.Collections.Generic.List[object]
    if (Get-Command py.exe -ErrorAction SilentlyContinue) {
        $candidates.Add(@('py.exe', '-3.12'))
        $candidates.Add(@('py.exe', '-3.11'))
    }
    foreach ($tag in '312', '311') {
        $candidates.Add(@((Join-Path $env:LOCALAPPDATA "Programs\Python\Python$tag\python.exe")))
        if ($env:ProgramFiles) { $candidates.Add(@((Join-Path $env:ProgramFiles "Python$tag\python.exe"))) }
    }
    $onPath = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($onPath) { $candidates.Add(@($onPath.Source)) }
    foreach ($command in $candidates) {
        if ($command.Count -eq 1 -and -not (Test-Path -LiteralPath $command[0])) { continue }
        $found = Test-Candidate $command
        if ($found) { return $found }
    }
    return $null
}

function Ask-Consent {
    if ($AssumeYes) { return $true }
    if ($AssumeNo) { return $false }
    $text = "The Audiobook Creation Tool needs Python 3.12 to run, and no usable copy was found on this computer.`n`n" +
            "Install the official Python $PyVersion from python.org now?`n`n" +
            "  - about 27 MB to download`n" +
            "  - installed for your user account only (no administrator rights)`n" +
            "  - your system PATH and file associations are not changed`n`n" +
            "Choose No to stop without installing anything."
    try {
        Add-Type -AssemblyName System.Windows.Forms
        $answer = [System.Windows.Forms.MessageBox]::Show($text, 'Audiobook Creation Tool - install Python',
            [System.Windows.Forms.MessageBoxButtons]::YesNo, [System.Windows.Forms.MessageBoxIcon]::Question)
        return ($answer -eq [System.Windows.Forms.DialogResult]::Yes)
    } catch {
        Say $text
        $reply = Read-Host 'Install Python now? Type Y and press Enter for yes'
        return ($reply -match '^\s*[Yy]')
    }
}

function Test-Installer([string]$Path) {
    # The pinned size and SHA-256 decide; the Authenticode signature is checked as well wherever Windows can check it.
    $item = Get-Item -LiteralPath $Path
    if ($item.Length -ne $InstallerSize) { return "it is $($item.Length) bytes, not $InstallerSize" }
    $hash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    if ($hash -ne $InstallerSha256) { return "its SHA-256 is $hash, not the pinned $InstallerSha256" }
    try {
        $signature = Get-AuthenticodeSignature -LiteralPath $Path
        if ($signature.Status -ne 'Valid') { return "its digital signature is $($signature.Status)" }
        if ($signature.SignerCertificate.Subject -notlike "*O=$InstallerSigner*") {
            return "it is signed by '$($signature.SignerCertificate.Subject)', not the $InstallerSigner"
        }
    } catch {
        Say '  (Windows could not check the digital signature here; the pinned SHA-256 matched, which is the authority.)'
    }
    return $null
}

function Get-Installer {
    if ($InstallerPath) {
        $problem = Test-Installer $InstallerPath
        if ($problem) { throw "The installer at $InstallerPath was rejected: $problem." }
        return $InstallerPath
    }
    New-Item -ItemType Directory -Force -Path $Downloads | Out-Null
    $target = Join-Path $Downloads $InstallerName
    if (Test-Path -LiteralPath $target) {
        if (-not (Test-Installer $target)) {
            Say 'Reusing the Python installer downloaded earlier (it is still the verified file).'
            return $target
        }
        Remove-Item -LiteralPath $target -Force
    }
    $part = "$target.part"
    Say "Downloading Python $PyVersion from python.org (about 27 MB)..."
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -UseBasicParsing -Uri $InstallerUrl -OutFile $part
    $problem = Test-Installer $part
    if ($problem) {
        Remove-Item -LiteralPath $part -Force -ErrorAction SilentlyContinue
        throw "The downloaded Python installer was rejected and deleted: $problem."
    }
    Move-Item -LiteralPath $part -Destination $target -Force
    return $target
}

function Install-Direct([string]$Installer) {
    Say "Installing Python $PyVersion for this user (this takes a minute or two)..."
    $arguments = @('/quiet', 'InstallAllUsers=0', 'PrependPath=0', 'AssociateFiles=0', 'Shortcuts=0', 'Include_launcher=0',
                   'InstallLauncherAllUsers=0', 'Include_test=0', 'Include_doc=0', 'Include_tcltk=1', 'Include_pip=1',
                   "TargetDir=`"$TargetDir`"")
    $process = Start-Process -FilePath $Installer -ArgumentList $arguments -Wait -PassThru
    Say "  The installer finished (exit code $($process.ExitCode)); checking the result..."
    return Test-Candidate @((Join-Path $TargetDir 'python.exe'))
}

function Install-Winget {
    if ($NoWinget -or -not (Get-Command winget.exe -ErrorAction SilentlyContinue)) { return $null }
    Say 'Trying winget instead (for this user only)...'
    & winget.exe install --id Python.Python.3.12 -e --scope user --silent --accept-source-agreements --accept-package-agreements | Out-Host
    return Find-Python
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
    if (-not $IgnoreInstalled) {
        $python = Find-Python
        if ($python) { Write-Result $python; exit 0 }
    }
    Say 'No usable Python 3.11 or 3.12 was found on this computer.'
    if (-not (Ask-Consent)) {
        Say 'Python was not installed. Run the setup again whenever you are ready.'
        exit 2
    }
    $installer = $null
    try {
        $installer = Get-Installer
    } catch {
        Say "The direct download did not work: $($_.Exception.Message)"
    }
    if ($installer -and $DownloadOnly) {
        Say "Verified installer: $installer (not run: -DownloadOnly)."
        exit 0
    }
    $python = $null
    if ($installer) { $python = Install-Direct $installer }
    if (-not $python) { $python = Install-Winget }
    if (-not $python) {
        Say 'Python could not be installed automatically. Nothing else was changed.'
        exit 3
    }
    if ($installer -and -not $InstallerPath) { Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue }
    Write-Result $python
    exit 0
} catch {
    Say "Setting up Python stopped: $($_.Exception.Message)"
    exit 3
}
