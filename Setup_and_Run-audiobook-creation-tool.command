#!/bin/bash
# ============================================================================
#  Audiobook Creation Tool  -  macOS setup and launcher
#
#  Double-click this file in Finder. The FIRST time it runs it downloads the
#  app's own Python into this folder (stage 0, with your consent), then installs
#  everything else (a private Python environment + audio libraries + ffmpeg)
#  using a small setup window. EVERY time after that it just opens the app.
#  Nothing is installed on the Mac itself: no Homebrew, no administrator
#  password. All the real work lives in:
#      scripts/shared/bootstrap_host_macos.sh   (the app's own Python)
#      scripts/shared/bootstrap.py              (everything else)
# ============================================================================

set -u

# Resolve this script's directory (the repo root when properly extracted).
HERE="$(cd "$(dirname "$0")" && pwd)"

# ---------------------------------------------------------------------------
# Gatekeeper "App Translocation" guard.
#
# When a quarantined download (this whole folder came from a browser/zip) is
# opened straight from Finder, macOS may run THIS script from a temporary,
# read-only randomized copy that contains only the .command file — its scripts/
# program folder is NOT beside it. The old code then failed the cd into the
# program folder and exited silently, which looked exactly like "Terminal
# flashes, no window".
#
# The same "no scripts/ sibling" situation also happens if someone copies just
# the .command out on its own. In every such case we cannot find the app, so
# show a clear, actionable message and KEEP THE WINDOW OPEN (no auto-close)
# instead of dying silently.
# ---------------------------------------------------------------------------
if [ ! -d "$HERE/scripts" ]; then
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

  1. In Finder, move the WHOLE app folder (the extracted
     "AudiobookTool-MacOS-v..." folder that holds this file) OUT
     of Downloads — for example drag it onto your Desktop or into
     Applications.
  2. Open that moved folder and double-click
     Setup_and_Run-audiobook-creation-tool.command again.

Moving the folder in Finder clears the translocation.

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

cd "$HERE" || { echo "Could not enter the app folder."; exit 1; }

BOOTSTRAP="scripts/shared/bootstrap.py"

# ---------------------------------------------------------------------------
# Fast path: environment already set up.
#
# Run the launcher in the FOREGROUND. bootstrap.py --launch-only spawns the GUI
# fully detached (its own session via start_new_session, output redirected to
# files/runtime-data/logs/launch_<date>.log) and then returns within a couple of
# seconds. Because we WAIT for it to return, by the time we ask Terminal to
# close there is no child process left in this window's session, so macOS does
# not show the "terminate running processes (bash, Python…)?" dialog. The
# detached GUI lives in its own session with no controlling terminal, so
# Terminal ignores it.
#
# If the GUI fails to start, bootstrap exits non-zero: keep the window OPEN and
# point at the log instead of closing silently (that silent close was the old
# "Terminal flashes, no window" symptom).
# ---------------------------------------------------------------------------
# The executable bit is a necessary condition, never a sufficient one: an
# environment whose Python no longer runs, that lost ssl, or that sits on an
# incompatible version still has an executable file there. Bootstrap decides
# what "healthy" means — this script deliberately knows nothing about Python
# versions, ssl or Tk — and exit code 3 is it asking for the environment to be
# rebuilt, which cannot be done from inside the environment being replaced.
VENV_REPAIR_REQUIRED=3
NEEDS_VENV_REPAIR=""

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
    else
        # Capture bootstrap's status here: after `fi`, a failed condition with
        # no else branch has status zero and would hide its repair request.
        rc=$?
    fi
    if [ "$rc" -eq "$VENV_REPAIR_REQUIRED" ]; then
        NEEDS_VENV_REPAIR=1
    else
        echo
        echo "The app window did not start. Details are in:"
        echo "  files/runtime-data/logs/launch_$(date +%Y-%m-%d).log"
        echo
        read -n 1 -s -r -p "Press any key to close..."
        echo
        exit 1
    fi
elif [ -e ".venv/bin/python" ]; then
    # Present but not runnable at all. Bootstrap cannot report this from inside
    # itself, because it never gets to start, so the launcher has to notice.
    NEEDS_VENV_REPAIR=1
fi

if [ -n "$NEEDS_VENV_REPAIR" ]; then
    echo "============================================================"
    echo "  Audiobook Creation Tool - repairing the app environment"
    echo "============================================================"
    echo
    echo "The app's Python environment needs to be rebuilt."
    echo "Your settings and your audiobooks are not touched."
    echo "This can take a few minutes."
    echo
fi

# ---------------------------------------------------------------------------
# First run or repair: the app's OWN uv and Python (v0.8.2 Phase 4).
#
# Stage 0 (scripts/shared/bootstrap_host_macos.sh) proves, or downloads with
# consent, verifies and installs with the pinned uv, a pinned standalone
# CPython 3.12.15 inside this folder (files/runtime-data/uv/python). That
# interpreter -- never one found on PATH, never Homebrew's, never Apple's --
# then runs the setup. Nothing is installed on the Mac and no administrator
# password is ever asked for. It writes the interpreter's path to a file.
# Stage 0's codes: 0 = proven, 2 = you declined (nothing downloaded),
# 3 = it could not be done (the reason is printed above).
# ---------------------------------------------------------------------------
echo "============================================================"
echo "  Audiobook Creation Tool - first-time setup"
echo "============================================================"
echo

APP_PY_FILE="files/temp/bootstrap/selected-python.txt"
rm -f "$APP_PY_FILE"
/bin/bash "scripts/shared/bootstrap_host_macos.sh" --out-file "$APP_PY_FILE"
STAGE0=$?
APP_PY=""
[ "$STAGE0" -eq 0 ] && [ -f "$APP_PY_FILE" ] && APP_PY="$(cat "$APP_PY_FILE")"
if [ "$STAGE0" -eq 0 ] && [ -z "$APP_PY" ]; then
    STAGE0=3
fi
if [ "$STAGE0" -ne 0 ]; then
    echo
    if [ "$STAGE0" -eq 2 ]; then
        echo "Setup stopped before downloading anything. Double-click this file again"
        echo "whenever you are ready."
    else
        echo "The app's own Python could not be set up (see the message above)."
        echo "Nothing outside this folder was changed."
    fi
    echo
    read -n 1 -s -r -p "Press any key to close..."
    echo
    exit "$STAGE0"
fi

if [ -n "$NEEDS_VENV_REPAIR" ]; then
    # Environment repair only: rebuild the private Python environment and its
    # packages, then launch. Deliberately NOT the full first-run install.
    echo "Repairing..."
    echo
    "$APP_PY" "$BOOTSTRAP" --repair-venv
else
    echo "Starting setup..."
    echo
    "$APP_PY" "$BOOTSTRAP"
fi
RC=$?

if [ "$RC" -ne 0 ]; then
    echo
    echo "Setup did not complete successfully (exit code $RC)."
    echo "See the log under files/runtime-data/logs/ for details."
    echo
    read -n 1 -s -r -p "Press any key to close..."
    echo
fi
exit $RC
