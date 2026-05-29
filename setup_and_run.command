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

PYCMD=""
for cand in python3.12 python3.11 python3; do
    if command -v "$cand" >/dev/null 2>&1; then PYCMD="$cand"; break; fi
done

# No Python - try Homebrew.
if [ -z "$PYCMD" ]; then
    if command -v brew >/dev/null 2>&1; then
        echo "Python not found. Installing python@3.12 via Homebrew..."
        brew install python@3.12
        for cand in python3.12 "$(brew --prefix)/bin/python3.12" python3; do
            if command -v "$cand" >/dev/null 2>&1 || [ -x "$cand" ]; then PYCMD="$cand"; break; fi
        done
    else
        echo
        echo "Homebrew is required to install Python automatically."
        echo "Opening the Homebrew install page. Install it, then run this file again."
        open "https://brew.sh/" >/dev/null 2>&1 || true
        echo
        read -n 1 -s -r -p "Press any key to close..."
        echo
        exit 1
    fi
fi

if [ -z "$PYCMD" ]; then
    echo
    echo "Could not find or install Python automatically."
    echo "Install Python 3.12 from python.org, then run this file again."
    open "https://www.python.org/downloads/" >/dev/null 2>&1 || true
    echo
    read -n 1 -s -r -p "Press any key to close..."
    echo
    exit 1
fi

echo "Using Python: $PYCMD"
echo "Starting setup..."
echo
"$PYCMD" "$BOOTSTRAP"
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
