#!/bin/bash
# ============================================================================
#  Setup_and_Run  --  macOS setup + launcher  (template)
# ============================================================================
#  HOW THIS TEMPLATE IS USED
#  -------------------------
#  Create_New_Repo.bat copies this into a new project's ROOT and renames it to
#  Setup_and_Run-<project_name>.command. Replace the [PROJECT_NAME] placeholder
#  below (the scaffolder can do this automatically). The file MUST keep the
#  .command extension (so it opens on double-click from Finder) and MUST be
#  executable:  chmod +x Setup_and_Run-<project_name>.command
#
#  WHAT THIS FILE DOES (per AI-WORKSPACE.md "Setup and Launch Files")
#  ------------------------------------------------------------------
#  One double-click does everything for a NON-TECHNICAL user:
#    1. Scans the Mac for Python 3 (the one unavoidable system dependency).
#    2. If Python is missing, asks Y/N and installs it FOR THE CURRENT USER by
#       default (user scope via Homebrew, no admin password). Only asks
#       "just me / all users" when a system install is actually forced.
#    3. Creates a fresh .venv IN THE REPO ROOT and installs all dependencies
#       into it (never system-wide).
#    4. Sets up self-contained tools (e.g. ffmpeg) INSIDE the repo (files/bin),
#       nothing installed on the Mac.
#    5. Launches the program. On every later run it acts as the launcher.
#
#  SELF-HEALING: delete .venv (to move/shrink/reset the repo) and re-run -- it
#  rebuilds from scratch. Delete Python and re-run -- it detects the absence
#  and offers to reinstall. Re-running always returns you to a working state.
#
#  Goal: the MINIMUM installed on the Mac; everything else contained in the repo
#  and the venv.
# ============================================================================

cd "$(dirname "$0")" || exit 1

# ============================================================================
#  Configuration  --  edit per project
# ============================================================================
PROJECT_NAME="[PROJECT_NAME]"

# Minimum Python major.minor this project supports.
PY_MIN_MAJOR="3"
PY_MIN_MINOR="11"
# Homebrew formula used if Python must be installed from scratch (user scope).
PYTHON_BREW_FORMULA="python@3.11"

# requirements.txt lives in scripts/ per AI-WORKSPACE.md.
REQUIREMENTS="scripts/requirements.txt"

# Main entry point. Single-platform: scripts/launcher.py
# Cross-platform: scripts/MacOS/launcher.py (falls back to scripts/Universal/launcher.py).
# Auto-detected below; override here only if your project differs.
MAIN_SCRIPT=""

# Set to 1 if this project uses ffmpeg (audio/video). 0 disables the ffmpeg step.
USE_FFMPEG=0

# Where in-repo tools (like ffmpeg) are kept. Self-contained, no install.
BIN_DIR="$(pwd)/files/bin"

# Internal: scope chosen only if a forced system install happens.
INSTALL_SCOPE=""
PYTHON_CMD=""

# ============================================================================
#  Banner + first-run security note
# ============================================================================
clear 2>/dev/null
echo "========================================"
echo "  ${PROJECT_NAME} - Setup & Launcher"
echo "  Folder: $(pwd)"
echo "========================================"
echo
echo "  This window sets up and launches the program. Setup keeps everything"
echo "  inside this project folder where it can. You should not need to install"
echo "  anything system-wide unless a required tool (Python) is completely"
echo "  missing from this Mac -- and it will ask you first if so."
echo
echo "  FIRST-RUN NOTE: Because this file came from the internet, macOS may"
echo "  block it the first time. If you see \"cannot be opened\", go to"
echo "  System Settings > Privacy & Security, scroll down, and click"
echo "  \"Open Anyway\". This is normal and only happens once."
echo

# ============================================================================
#  Helpers
# ============================================================================

# Find a usable Python 3 and store it in PYTHON_CMD. Returns 0 if found.
detect_python() {
    PYTHON_CMD=""
    if command -v python3 &> /dev/null; then
        PYTHON_CMD="python3"
        return 0
    fi
    return 1
}

# Warn (don't block) if the detected Python is below the project minimum.
check_python_version() {
    local minor
    minor="$("$PYTHON_CMD" -c 'import sys; print(sys.version_info[1])' 2>/dev/null)"
    if [ -n "$minor" ] && [ "$minor" -lt "$PY_MIN_MINOR" ] 2>/dev/null; then
        echo "  WARNING: Detected Python 3.${minor}, but this project targets"
        echo "           ${PY_MIN_MAJOR}.${PY_MIN_MINOR} or newer. Some features may not work."
        echo
    fi
}

# Ask user vs machine scope. ONLY called when a forced system install happens.
choose_scope() {
    echo
    echo "----------------------------------------"
    echo "  This install has to go onto the Mac itself. Where should it go?"
    echo
    echo "    1. Just for me     (no admin password needed - safest at work)"
    echo "    2. For all users   (may require an admin password)"
    echo "----------------------------------------"
    read -p "Enter 1 or 2 (default 1): " scope_choice
    if [ "$scope_choice" = "2" ]; then
        INSTALL_SCOPE="machine"
        echo "  Installing system-wide. You may be asked for an admin password."
    else
        INSTALL_SCOPE="user"
        echo "  Installing for the current user only. No admin password needed."
    fi
    echo
}

# Ensure Homebrew (user-local, no sudo) is available. Returns 0 on success.
ensure_homebrew() {
    if command -v brew &> /dev/null; then
        return 0
    fi
    echo
    echo "  Homebrew (the macOS installer tool) is not installed."
    read -p "  Install Homebrew now? (Y/N): " do_brew
    if [[ "$do_brew" =~ ^[Yy]$ ]]; then
        echo "  Installing Homebrew into your user account..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        if [ -x /opt/homebrew/bin/brew ]; then
            eval "$(/opt/homebrew/bin/brew shellenv)"
        elif [ -x /usr/local/bin/brew ]; then
            eval "$(/usr/local/bin/brew shellenv)"
        fi
        command -v brew &> /dev/null && return 0
    fi
    return 1
}

# Locate the launcher unless MAIN_SCRIPT was set manually in Configuration.
detect_main_script() {
    [ -n "$MAIN_SCRIPT" ] && return 0
    if   [ -f "scripts/launcher.py" ];           then MAIN_SCRIPT="scripts/launcher.py"
    elif [ -f "scripts/MacOS/launcher.py" ];     then MAIN_SCRIPT="scripts/MacOS/launcher.py"
    elif [ -f "scripts/Universal/launcher.py" ]; then MAIN_SCRIPT="scripts/Universal/launcher.py"
    fi
}

# Prefer a self-contained in-repo ffmpeg; no system install.
ensure_ffmpeg() {
    command -v ffmpeg &> /dev/null && return 0
    [ -x "$BIN_DIR/ffmpeg" ] && return 0

    echo
    echo "  This project uses ffmpeg (audio/video processing). It is not on this"
    echo "  Mac, so it can be placed INSIDE the project folder only - nothing is"
    echo "  installed system-wide and no admin password is needed."
    echo
    read -p "  Set up ffmpeg inside the project now? (Y/N): " do_ff
    if [[ ! "$do_ff" =~ ^[Yy]$ ]]; then
        echo "  Skipped ffmpeg. The program will still run; features that need it"
        echo "  may be unavailable until it is set up."
        return 0
    fi

    mkdir -p "$BIN_DIR"
    local arch ff_url ff_zip
    arch="$(uname -m)"
    if [ "$arch" = "arm64" ]; then
        ff_url="https://www.osxexperts.net/ffmpeg7arm.zip"
    else
        ff_url="https://www.osxexperts.net/ffmpeg7intel.zip"
    fi
    ff_zip="/tmp/ffmpeg_repo_dl.zip"

    echo "  Downloading a self-contained ffmpeg into the project..."
    if curl -fsSL "$ff_url" -o "$ff_zip"; then
        unzip -o -q "$ff_zip" -d "$BIN_DIR" && rm -f "$ff_zip"
        if [ -f "$BIN_DIR/ffmpeg" ]; then
            chmod +x "$BIN_DIR/ffmpeg"
            echo "  ffmpeg is set up inside the project. Nothing was installed on the Mac."
        else
            echo "  ffmpeg downloaded but the binary wasn't where expected."
            echo "  You can place an 'ffmpeg' binary in: $BIN_DIR"
        fi
    else
        echo "  Could not download ffmpeg automatically. You can download a static"
        echo "  build later and place the 'ffmpeg' binary in: $BIN_DIR"
    fi
    echo
}

# ============================================================================
#  STEP 1 - Ensure Python (the only unavoidable system dependency)
# ============================================================================
# A virtual environment cannot be created without an interpreter already
# present, so this is the only tool we may have to install onto the Mac. If
# Python already exists, the scope question is never asked.
echo "Checking for Python..."
if ! detect_python; then
    echo
    echo "  Python 3 is not installed on this Mac, and it is required to run this"
    echo "  program. This is the ONLY tool that has to be installed onto the"
    echo "  computer itself - everything else stays in this folder."
    echo
    read -p "  Install Python now? (Y/N): " do_py
    if [[ "$do_py" =~ ^[Yy]$ ]]; then
        choose_scope
        if [ "$INSTALL_SCOPE" = "machine" ]; then
            echo "  Please install Python system-wide from python.org:"
            echo "    https://www.python.org/downloads/macos/"
            echo "  (The official installer may require an admin password.)"
            read -p "  Press Enter once Python is installed to continue..."
        else
            if ensure_homebrew; then
                echo "  Installing Python via Homebrew (no admin password)..."
                brew install "$PYTHON_BREW_FORMULA"
            else
                echo "  Skipped. Python is required to run this program."
                read -p "Press Enter to exit..."
                exit 1
            fi
        fi
    else
        echo "  Python is required. Install it from:"
        echo "    https://www.python.org/downloads/macos/"
        echo "  then run this file again."
        read -p "Press Enter to exit..."
        exit 1
    fi

    # Re-detect; a fresh install may not be on PATH in this same window.
    if ! detect_python; then
        echo
        echo "  Python was installed but isn't visible in THIS window yet. Close"
        echo "  this window, re-open it, and run this file again so the updated"
        echo "  PATH takes effect."
        read -p "Press Enter to exit..."
        exit 1
    fi
fi

# Warn (don't block) if the present Python is older than the project minimum.
check_python_version

# ============================================================================
#  STEP 2 - Virtual environment (self-healing; everything below stays in repo)
# ============================================================================
# If .venv is missing OR broken (e.g. partially deleted), rebuild it cleanly.
if [ ! -f ".venv/bin/activate" ]; then
    if [ -d ".venv" ]; then
        echo "Existing .venv looks incomplete - rebuilding it from scratch..."
        rm -rf ".venv"
    else
        echo "Creating a new virtual environment in this folder..."
    fi
    if ! "$PYTHON_CMD" -m venv .venv; then
        echo "  ERROR: Failed to create the virtual environment."
        read -p "Press Enter to exit..."
        exit 1
    fi
fi

# shellcheck disable=SC1091
source .venv/bin/activate
if [ ! -f ".venv/bin/activate" ]; then
    echo "  ERROR: Virtual environment activation script missing after setup."
    read -p "Press Enter to exit..."
    exit 1
fi

# ============================================================================
#  STEP 3 - Dependencies (into the venv - never system-wide, installed quietly)
# ============================================================================
if [ -f "$REQUIREMENTS" ]; then
    echo "Installing dependencies into the project environment..."
    pip install --upgrade pip >/dev/null 2>&1
    if ! pip install -r "$REQUIREMENTS"; then
        echo "  ERROR: Some dependencies failed to install. See messages above."
        read -p "Press Enter to exit..."
        exit 1
    fi
else
    echo "  Note: No requirements.txt at $REQUIREMENTS - skipping dependencies."
fi

# ============================================================================
#  STEP 4 - Optional self-contained ffmpeg (kept INSIDE the repo, no install)
# ============================================================================
if [ "$USE_FFMPEG" = "1" ]; then
    ensure_ffmpeg
fi
if [ -d "$BIN_DIR" ]; then
    export PATH="$BIN_DIR:$PATH"
fi

# ============================================================================
#  STEP 5 - Locate the launcher and run it
# ============================================================================
detect_main_script
if [ -z "$MAIN_SCRIPT" ]; then
    echo
    echo "  ERROR: Could not find the program's entry point."
    echo "  Expected one of:"
    echo "    scripts/launcher.py"
    echo "    scripts/MacOS/launcher.py"
    echo "    scripts/Universal/launcher.py"
    echo "  Create one of those or set MAIN_SCRIPT in this file's Configuration."
    echo
    read -p "Press Enter to exit..."
    exit 1
fi

echo
echo "Launching ${PROJECT_NAME}..."
echo
python "$MAIN_SCRIPT"
RUN_EXIT=$?

echo
if [ "$RUN_EXIT" -ne 0 ]; then
    echo "Program exited with code ${RUN_EXIT}."
else
    echo "Program finished."
fi
read -p "Press Enter to close..."
exit $RUN_EXIT
