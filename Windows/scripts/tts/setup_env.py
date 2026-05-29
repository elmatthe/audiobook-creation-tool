"""
setup_env.py — One-time environment setup for epub2tts-edge.

Usage:
    python setup_env.py                       # install / verify everything
    python setup_env.py --skip-kokoro-download  # skip Kokoro model pre-download
    python setup_env.py --uninstall             # remove the venv and installed components

Supports: Windows 10/11, macOS 12+, Ubuntu/Debian Linux 20.04+
Python 3.11+ must already be installed (the script checks and guides if missing).
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

VENV_DIR = Path(__file__).parent / ".venv"
REQUIREMENTS = Path(__file__).parent / "requirements.txt"
SCRIPT_DIR = Path(__file__).parent
PYTHON_MIN = (3, 11)

BANNER = """
================================================================
        epub2tts-edge  —  Environment Setup v1.1
================================================================
"""

OK = "  [OK]"
SKIP = "  [--]"
WARN = "  [!!]"
ERR = "  [XX]"


def _sys() -> str:
    return platform.system()


def _run(cmd: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)  # type: ignore[call-overload]


def _print(tag: str, msg: str) -> None:
    print(f"{tag} {msg}")


def _section(title: str) -> None:
    pad = max(0, 54 - len(title))
    print(f"\n-- {title} {'-' * pad}")


def _pip_in_venv() -> list[str]:
    if _sys() == "Windows":
        return [str(VENV_DIR / "Scripts" / "pip.exe")]
    return [str(VENV_DIR / "bin" / "pip")]


def _python_in_venv() -> list[str]:
    if _sys() == "Windows":
        return [str(VENV_DIR / "Scripts" / "python.exe")]
    return [str(VENV_DIR / "bin" / "python")]


def check_python_version() -> bool:
    _section("Python version")
    v = sys.version_info[:2]
    if v >= PYTHON_MIN:
        _print(OK, f"Python {sys.version.split()[0]} — meets minimum {PYTHON_MIN[0]}.{PYTHON_MIN[1]}")
        return True
    _print(ERR, f"Python {v[0]}.{v[1]} detected — need {PYTHON_MIN[0]}.{PYTHON_MIN[1]} or newer.")
    print()
    print("  Please install Python 3.11+ from https://www.python.org/downloads/")
    if _sys() == "Windows":
        print("  During installation, check 'Add Python to PATH'.")
    elif _sys() == "Darwin":
        print("  Recommended: use pyenv  ->  brew install pyenv && pyenv install 3.11")
    else:
        print("  On Ubuntu/Debian:  sudo apt install python3.11 python3.11-venv")
    return False


def check_venv() -> bool:
    if not VENV_DIR.exists():
        return False
    pip = _pip_in_venv()
    r = _run(pip + ["--version"])
    return r.returncode == 0


def create_venv() -> bool:
    _section("Virtual environment")
    if check_venv():
        _print(SKIP, f"Virtual environment already exists at  {VENV_DIR}")
        return True
    _print("  [  ]", f"Creating virtual environment at  {VENV_DIR} …")
    r = _run([sys.executable, "-m", "venv", str(VENV_DIR)])
    if r.returncode != 0:
        _print(ERR, f"Failed to create venv:\n{r.stderr.strip()}")
        return False
    _print(OK, "Virtual environment created.")
    return True


def check_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def install_ffmpeg_windows() -> bool:
    if shutil.which("winget"):
        _print("  [  ]", "Installing FFmpeg via winget …")
        r = _run(["winget", "install", "--id", "Gyan.FFmpeg", "-e", "--silent"])
        if r.returncode == 0:
            _print(OK, "FFmpeg installed via winget.")
            return True
        _print(WARN, "winget install failed — falling back to manual instructions.")

    if shutil.which("choco"):
        _print("  [  ]", "Installing FFmpeg via Chocolatey …")
        r = subprocess.run(["choco", "install", "ffmpeg", "-y"], capture_output=True, text=True)
        if r.returncode == 0:
            _print(OK, "FFmpeg installed via Chocolatey.")
            return True

    _print(WARN, "Automatic FFmpeg install not available on this system.")
    print()
    print("  Manual FFmpeg install (Windows):")
    print("  1. Go to  https://github.com/BtbN/FFmpeg-Builds/releases")
    print("  2. Download  ffmpeg-master-latest-win64-gpl.zip")
    print("  3. Extract, then add the  bin/  folder to your system PATH.")
    print("  Tutorial: https://phoenixnap.com/kb/ffmpeg-windows")
    return False


def install_ffmpeg_mac() -> bool:
    if shutil.which("brew"):
        _print("  [  ]", "Installing FFmpeg via Homebrew …")
        r = _run(["brew", "install", "ffmpeg"])
        if r.returncode == 0:
            _print(OK, "FFmpeg installed via Homebrew.")
            return True
        _print(ERR, f"brew install ffmpeg failed:\n{r.stderr.strip()}")
        return False
    _print(WARN, "Homebrew not found.")
    print("  Install Homebrew first:  https://brew.sh/")
    print("  Then run:  brew install ffmpeg")
    return False


def install_ffmpeg_linux() -> bool:
    if shutil.which("apt-get"):
        _print("  [  ]", "Installing FFmpeg via apt-get (may require sudo) …")
        r = subprocess.run(["sudo", "apt-get", "install", "-y", "ffmpeg"], capture_output=False)
        if r.returncode == 0:
            _print(OK, "FFmpeg installed.")
            return True
    elif shutil.which("dnf"):
        r = subprocess.run(["sudo", "dnf", "install", "-y", "ffmpeg"], capture_output=False)
        if r.returncode == 0:
            _print(OK, "FFmpeg installed via dnf.")
            return True
    elif shutil.which("pacman"):
        r = subprocess.run(["sudo", "pacman", "-Sy", "--noconfirm", "ffmpeg"], capture_output=False)
        if r.returncode == 0:
            _print(OK, "FFmpeg installed via pacman.")
            return True
    _print(ERR, "Could not find a supported package manager (apt, dnf, pacman).")
    print("  Please install ffmpeg manually and ensure it is on your PATH.")
    return False


def ensure_ffmpeg() -> bool:
    _section("FFmpeg")
    if check_ffmpeg():
        _print(SKIP, f"FFmpeg already on PATH  ({shutil.which('ffmpeg')})")
        return True
    _print("  [  ]", "FFmpeg not found — attempting install …")
    sys_name = _sys()
    if sys_name == "Windows":
        result = install_ffmpeg_windows()
        if result and not check_ffmpeg():
            _print(WARN, "FFmpeg was installed but is not yet on PATH in this session.")
            print()
            print("  ACTION REQUIRED:")
            print("  Close this window, open a new terminal, then run setup_env.bat again.")
            print("  This is a Windows PATH refresh limitation — not an install failure.")
        return result
    if sys_name == "Darwin":
        return install_ffmpeg_mac()
    return install_ffmpeg_linux()


def ensure_espeak() -> None:
    _section("espeak-ng  (NLTK tokenizer backend)")
    if shutil.which("espeak-ng") or shutil.which("espeak"):
        _print(SKIP, "espeak-ng already installed.")
        return
    sys_name = _sys()
    if sys_name == "Linux":
        if shutil.which("apt-get"):
            subprocess.run(["sudo", "apt-get", "install", "-y", "espeak-ng"], capture_output=False)
            _print(OK, "espeak-ng installed.")
        else:
            _print(WARN, "Please install espeak-ng manually for your distro.")
    elif sys_name == "Darwin":
        if shutil.which("brew"):
            _run(["brew", "install", "espeak"])
            _print(OK, "espeak installed via Homebrew.")
        else:
            _print(WARN, "Homebrew not found — install espeak manually:  brew install espeak")
    else:
        _print(WARN, "Windows: espeak-ng is optional but recommended.")
        print("  Download installer: https://github.com/espeak-ng/espeak-ng/releases")


def install_python_packages() -> bool:
    _section("Python packages")
    pip = _pip_in_venv()

    _print("  [  ]", "Upgrading pip …")
    _run(pip + ["install", "--upgrade", "pip"])

    if REQUIREMENTS.exists():
        _print("  [  ]", f"Installing from  {REQUIREMENTS.name} …")
        r = subprocess.run(pip + ["install", "-r", str(REQUIREMENTS)], capture_output=False)
        if r.returncode != 0:
            _print(ERR, "Package installation failed. Check output above.")
            return False
        _print(OK, "Base requirements installed.")
    else:
        _print(ERR, f"requirements.txt not found at  {REQUIREMENTS}")
        return False

    if sys.version_info < (3, 13):
        kokoro_pkgs = ["kokoro>=0.9.2", "soundfile", "scipy"]
        _print("  [  ]", f"Installing Kokoro packages ({', '.join(kokoro_pkgs)}) …")
        r = subprocess.run(pip + ["install"] + kokoro_pkgs, capture_output=False)
        if r.returncode != 0:
            _print(WARN, "Kokoro packages failed to install.")
            print("  Kokoro voices will not be available, but Edge TTS voices will still work.")
            print(f"  To install later:  pip install {' '.join(kokoro_pkgs)}")
        else:
            _print(OK, "Kokoro packages installed.")
    else:
        _print(
            WARN,
            "Python 3.13+: PyPI 'kokoro' wheels currently require Python <3.13. "
            "Skipping separate kokoro install (soundfile/scipy already from requirements).",
        )
        print("  Use Python 3.12 venv for Kokoro local voices, or wait for upstream 3.13 wheels.")

    return True


def check_all_installed() -> bool:
    if not check_venv():
        return False
    if not check_ffmpeg():
        return False
    pip = _pip_in_venv()
    for pkg in ["edge_tts", "pydub", "fitz"]:
        r = _run(_python_in_venv() + ["-c", f"import {pkg}"])
        if r.returncode != 0:
            return False
    return True


def print_run_instructions() -> None:
    _section("How to run epub2tts-edge")
    sys_name = _sys()
    gui_path = SCRIPT_DIR / "epub2tts_gui.py"

    print()
    print("  Option A — Command line (recommended)")
    if sys_name == "Windows":
        print(f"  Open PowerShell in this folder and run:")
        print(f"    .venv\\Scripts\\python.exe epub2tts_gui.py")
    else:
        print(f"  Open a Terminal in this folder and run:")
        print(f"    .venv/bin/python epub2tts_gui.py")
    print()
    print("  Option B — Windows: double-click  run_gui.bat  (after setup creates it)")
    print()
    print(f"  GUI script: {gui_path}")
    print()
    print("  First run with a Kokoro voice downloads ~300 MB from HuggingFace")
    print("  (one-time, cached under ~/.cache/huggingface/). Requires Python <3.13 for PyPI kokoro.")
    print()


def create_bat_launcher() -> None:
    if _sys() != "Windows":
        return
    bat_path = SCRIPT_DIR / "run_gui.bat"
    if bat_path.exists():
        _print(SKIP, "run_gui.bat already exists.")
        return
    bat_content = (
        "@echo off\n"
        "cd /d \"%~dp0\"\n"
        "if not exist \".venv\\Scripts\\python.exe\" (\n"
        "    echo Virtual environment not found. Please run: python setup_env.py\n"
        "    pause\n"
        "    exit /b 1\n"
        ")\n"
        ".venv\\Scripts\\python.exe epub2tts_gui.py\n"
        "pause\n"
    )
    bat_path.write_text(bat_content, encoding="utf-8")
    _print(OK, "Created  run_gui.bat  — double-click this to launch the GUI.")


def create_shell_launcher() -> None:
    if _sys() == "Windows":
        return
    sh_path = SCRIPT_DIR / "run_gui.sh"
    if sh_path.exists():
        _print(SKIP, "run_gui.sh already exists.")
        return
    sh_content = (
        "#!/usr/bin/env bash\n"
        "cd \"$(dirname \"$0\")\"\n"
        "if [ ! -f .venv/bin/python ]; then\n"
        "    echo 'Virtual environment not found. Run: python setup_env.py'\n"
        "    exit 1\n"
        "fi\n"
        ".venv/bin/python epub2tts_gui.py\n"
    )
    sh_path.write_text(sh_content, encoding="utf-8")
    sh_path.chmod(0o755)
    _print(OK, "Created  run_gui.sh  — run with:  bash run_gui.sh")


def predownload_kokoro_model() -> None:
    _section("Kokoro AI model pre-download (~300 MB, one-time)")
    if sys.version_info >= (3, 13):
        _print(SKIP, "Python 3.13+: Kokoro PyPI wheels require <3.13 — skipping model download.")
        print("  Use a Python 3.12 venv for Kokoro local voices.")
        return

    python = _python_in_venv()

    check = _run(python + ["-c", "import kokoro"])
    if check.returncode != 0:
        _print(SKIP, "Kokoro package not installed — skipping model download.")
        return

    _print("  [  ]", "Pre-downloading Kokoro-82M model weights from HuggingFace …")
    print("  (This may take several minutes on first run. Subsequent runs use the cache.)")

    download_script = (
        "from kokoro import KPipeline; "
        "print('Downloading lang_code=a (US voices) ...'); KPipeline(lang_code='a'); "
        "print('Downloading lang_code=b (British voices) ...'); KPipeline(lang_code='b'); "
        "print('Kokoro model download complete.')"
    )
    result = subprocess.run(
        python + ["-c", download_script],
        capture_output=False,
    )
    if result.returncode == 0:
        _print(OK, "Kokoro model weights cached — all local voices ready.")
    else:
        _print(WARN, "Model download may have failed. Review output above.")
        print("  Kokoro voices will attempt re-download on first use from the GUI.")


def uninstall() -> None:
    print(BANNER)
    print("  UNINSTALL MODE")
    print()
    print("  This will remove the following items installed by setup_env.py:")
    print(f"    - Virtual environment:  {VENV_DIR}")
    print("    - Launcher scripts:  run_gui.bat / run_gui.sh  (if they exist)")
    print()
    print("  It will NOT remove:")
    print("    - Python itself")
    print("    - FFmpeg (installed at system level)")
    print("    - espeak-ng (installed at system level)")
    print("    - The epub2tts-edge source files (this folder)")
    print()
    confirm = input("  Type  YES  to confirm uninstall, anything else to cancel: ").strip()
    if confirm != "YES":
        print("  Uninstall cancelled.")
        return

    removed: list[str] = []

    if VENV_DIR.exists():
        shutil.rmtree(VENV_DIR)
        removed.append(str(VENV_DIR))
        _print(OK, f"Removed virtual environment:  {VENV_DIR}")
    else:
        _print(SKIP, "Virtual environment not found — nothing to remove.")

    for launcher in ["run_gui.bat", "run_gui.sh"]:
        p = SCRIPT_DIR / launcher
        if p.exists():
            p.unlink()
            removed.append(launcher)
            _print(OK, f"Removed  {launcher}")

    hf_cache = Path.home() / ".cache" / "huggingface"
    if hf_cache.exists():
        print()
        ans = input(
            f"  Found HuggingFace model cache at  {hf_cache}\n"
            "  Remove it too? (Kokoro model weights ~300 MB)  [y/N]: "
        ).strip().lower()
        if ans == "y":
            shutil.rmtree(hf_cache)
            _print(OK, "Removed HuggingFace cache.")
        else:
            _print(SKIP, "HuggingFace cache kept.")

    print()
    if removed:
        print(f"  Uninstall complete. Removed {len(removed)} item(s).")
    else:
        print("  Nothing was removed.")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="epub2tts-edge environment setup / uninstall")
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Remove the virtual environment and launcher scripts created by this script.",
    )
    parser.add_argument(
        "--skip-kokoro-download",
        action="store_true",
        help=(
            "Skip pre-downloading the Kokoro AI model (~300 MB). "
            "Edge TTS voices will still work. Kokoro will download on first GUI use."
        ),
    )
    args = parser.parse_args()

    if args.uninstall:
        uninstall()
        return

    print(BANNER)

    _section("System scan")
    if check_all_installed():
        print()
        print("  System scan complete — libraries and dependencies appear installed.")
        print("  No setup steps required.")
        print()
        print_run_instructions()
        return

    if not check_python_version():
        sys.exit(1)

    all_ok = True

    if not create_venv():
        sys.exit(1)

    ffmpeg_ok = ensure_ffmpeg()
    if not ffmpeg_ok:
        all_ok = False

    ensure_espeak()

    if not install_python_packages():
        sys.exit(1)

    create_bat_launcher()
    create_shell_launcher()
    if not args.skip_kokoro_download:
        predownload_kokoro_model()
    else:
        _print(
            SKIP,
            "Kokoro model download skipped (--skip-kokoro-download). "
            "Model will download automatically on first GUI use.",
        )

    _section("Setup complete")
    print()
    if all_ok:
        print("  All core components installed successfully.")
    else:
        print("  Setup finished with warnings — see above. Edge TTS should still work.")
    print()
    print_run_instructions()


if __name__ == "__main__":
    main()
