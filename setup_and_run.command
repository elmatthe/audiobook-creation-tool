#!/bin/bash
# ============================================================================
#  Audiobook Creation Tool  -  macOS setup and launcher
#
#  Double-click this file in Finder. The FIRST time it runs it installs
#  everything (a private Python environment + audio libraries + ffmpeg) using a
#  small setup window. EVERY time after that it just opens the app. All the real
#  work lives in:
#      MacOS/scripts/shared/bootstrap.py
# ============================================================================

set -u

# Resolve this script's directory, then the MacOS/ subfolder beside it.
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE/MacOS" || { echo "Could not find the MacOS folder next to this script."; exit 1; }

BOOTSTRAP="scripts/shared/bootstrap.py"

# ---------------------------------------------------------------------------
# Fast path: environment already set up. Launch detached and close the Terminal.
# ---------------------------------------------------------------------------
if [ -x ".venv/bin/python" ]; then
    nohup ".venv/bin/python" "$BOOTSTRAP" --launch-only >/dev/null 2>&1 &
    disown 2>/dev/null || true
    # Best-effort: close the Terminal window this script opened.
    osascript -e 'tell application "Terminal" to close (every window whose name contains "setup_and_run")' >/dev/null 2>&1 || true
    exit 0
fi

# ---------------------------------------------------------------------------
# First run: find some Python just to run the setup window. The setup script
# itself locates or installs the correct Python 3.12 for the app.
# ---------------------------------------------------------------------------
echo "============================================================"
echo "  Audiobook Creation Tool - first-time setup"
echo "============================================================"
echo
echo "Looking for Python..."

# A GUI-capable Python is one whose Tk actually initializes — not merely one
# that exists. Homebrew's python@3.12 has NO working _tkinter unless
# python-tk@3.12 is also installed, and the app imports tkinter at startup, so
# every candidate is probed with a real Tcl() init before we accept it.
tk_ok() { "$1" -c "import tkinter; tkinter.Tcl()" >/dev/null 2>&1; }

# Make an installed Homebrew usable in THIS shell (Apple Silicon vs Intel paths).
load_brew_env() {
    if [ -x /opt/homebrew/bin/brew ]; then eval "$(/opt/homebrew/bin/brew shellenv)";
    elif [ -x /usr/local/bin/brew ]; then eval "$(/usr/local/bin/brew shellenv)"; fi
}

PYBIN=""
for cand in python3.12 python3.11 python3; do
    if command -v "$cand" >/dev/null 2>&1 && tk_ok "$cand"; then
        PYBIN="$(command -v "$cand")"; break
    fi
done

# Nothing GUI-capable yet → repair via Homebrew (installs Tk support).
if [ -z "$PYBIN" ]; then
    load_brew_env
    if ! command -v brew >/dev/null 2>&1; then
        echo
        echo "------------------------------------------------------------"
        echo "  A GUI-capable Python is needed and Homebrew is not yet"
        echo "  installed. The official Homebrew installer will run now."
        echo
        echo "  >>>  macOS will ask for YOUR MAC LOGIN PASSWORD.  <<<"
        echo
        echo "  That prompt comes from Homebrew (not this app), asking"
        echo "  permission to install software. Type your password and"
        echo "  press Return. Nothing is shown as you type — that's normal."
        echo "------------------------------------------------------------"
        echo
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        load_brew_env
    fi
    if command -v brew >/dev/null 2>&1; then
        echo "Installing a GUI-capable Python (python@3.12 + python-tk@3.12) via Homebrew..."
        brew install python@3.12 python-tk@3.12 || true
        # Install ffmpeg now too while brew is in hand (bootstrap re-checks harmlessly).
        brew install ffmpeg || true
        BREW_PY="$(brew --prefix)/bin/python3.12"
        if [ -x "$BREW_PY" ] && tk_ok "$BREW_PY"; then PYBIN="$BREW_PY"; fi
    fi
fi

# Still nothing GUI-capable → fall back to a headless install with any python3.
HEADLESS_FLAG=""
if [ -z "$PYBIN" ]; then
    for cand in python3.12 python3.11 python3; do
        if command -v "$cand" >/dev/null 2>&1; then PYBIN="$(command -v "$cand")"; break; fi
    done
    if [ -n "$PYBIN" ]; then
        HEADLESS_FLAG="--headless"
        echo
        echo "  [!!] No GUI-capable Python could be set up — continuing in HEADLESS"
        echo "       mode. Setup will still finish (Python env + libraries + ffmpeg)."
        echo "       To enable the app window later, install Tk support and re-run:"
        echo "           brew install python-tk@3.12"
        echo
    else
        echo
        echo "Could not find or install Python automatically."
        echo "Install Python 3.12 from python.org, then run this file again."
        open "https://www.python.org/downloads/" >/dev/null 2>&1 || true
        echo
        read -n 1 -s -r -p "Press any key to close..."
        echo
        exit 1
    fi
fi

echo "Using Python: $PYBIN ($("$PYBIN" --version 2>&1))"
echo "Starting setup..."
echo
"$PYBIN" "$BOOTSTRAP" $HEADLESS_FLAG
RC=$?

if [ "$RC" -ne 0 ]; then
    echo
    echo "Setup did not complete successfully (exit code $RC)."
    echo "See the log under MacOS/resources/logs/ for details."
    echo
    read -n 1 -s -r -p "Press any key to close..."
    echo
fi
exit $RC
