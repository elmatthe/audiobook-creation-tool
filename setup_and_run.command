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

# ---------------------------------------------------------------------------
# Gatekeeper "App Translocation" guard.
#
# When a quarantined download (this whole folder came from a browser/zip) is
# opened straight from Finder, macOS may run THIS script from a temporary,
# read-only randomized copy that contains only the .command file — its MacOS/
# program folder is NOT beside it. The old code then failed `cd "$HERE/MacOS"`
# and exited silently, which looked exactly like "Terminal flashes, no window".
#
# The same "no MacOS/ sibling" situation also happens if someone copies just the
# .command out on its own. In every such case we cannot find the app, so show a
# clear, actionable message and KEEP THE WINDOW OPEN (no auto-close) instead of
# dying silently.
# ---------------------------------------------------------------------------
if [ ! -d "$HERE/MacOS" ]; then
    translocated=no
    case "$HERE" in
        */AppTranslocation/*) translocated=yes ;;
    esac

    cat <<'EOF'

============================================================
  Audiobook Creation Tool — can't start from here
============================================================

macOS is running this launcher from a temporary, read-only copy
(Gatekeeper "App Translocation"), so it cannot find its program
files. This happens when the app is opened straight from a
Downloads or unzipped-in-place location.

To fix it (one time):

  1. In Finder, move the WHOLE "audiobook-creation-tool" folder
     OUT of Downloads — for example drag it onto your Desktop or
     into Applications.
  2. Open that moved folder and double-click setup_and_run.command
     again.

Moving the folder in Finder clears the translocation. (Alternatively,
right-click setup_and_run.command -> Open, then confirm the prompt.)

EOF
    if [ "$translocated" = yes ]; then
        echo "  Detected translocated path:"
        echo "    $HERE"
        echo
    fi
    # Pause so the message is actually read — this window is NOT auto-closed.
    read -n 1 -s -r -p "Press any key to close..."
    echo
    exit 1
fi

cd "$HERE/MacOS" || { echo "Could not find the MacOS folder next to this script."; exit 1; }

BOOTSTRAP="scripts/shared/bootstrap.py"

# ---------------------------------------------------------------------------
# Fast path: environment already set up.
#
# Run the launcher in the FOREGROUND. bootstrap.py --launch-only spawns the GUI
# fully detached (its own session via start_new_session, output redirected to
# resources/logs/launch_<date>.log) and then returns within a couple of seconds.
# Because we WAIT for it to return, by the time we ask Terminal to close there is
# no child process left in this window's session, so macOS does not show the
# "terminate running processes (bash, Python…)?" dialog. The detached GUI lives
# in its own session with no controlling terminal, so Terminal ignores it.
#
# If the GUI fails to start, bootstrap exits non-zero: keep the window OPEN and
# point at the log instead of closing silently (that silent close was the old
# "Terminal flashes, no window" symptom).
# ---------------------------------------------------------------------------
if [ -x ".venv/bin/python" ]; then
    if ".venv/bin/python" "$BOOTSTRAP" --launch-only; then
        # The GUI is up and detached. Auto-close THIS Terminal window WITHOUT the
        # "terminate running processes (bash, osascript)" prompt. Closing the
        # window from here directly would run osascript while bash + osascript are
        # still alive in this very window — which is exactly what triggers that
        # dialog (verified: such a self-close is blocked by the modal). Instead a
        # helper detached into its own session waits for this bash to exit, then
        # closes the window (matched by our tty) when nothing is running in it.
        launcher_tty="$(tty 2>/dev/null || true)"
        nohup ".venv/bin/python" "scripts/shared/close_terminal.py" "$launcher_tty" \
            >/dev/null 2>&1 &
        disown 2>/dev/null || true
        exit 0
    fi
    echo
    echo "The app window did not start. Details are in:"
    echo "  MacOS/resources/logs/launch_$(date +%Y-%m-%d).log"
    echo
    read -n 1 -s -r -p "Press any key to close..."
    echo
    exit 1
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
