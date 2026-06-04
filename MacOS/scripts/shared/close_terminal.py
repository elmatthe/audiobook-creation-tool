#!/usr/bin/env python3
"""Detached helper that closes the launcher's Terminal window cleanly on macOS.

``setup_and_run.command`` (fast path) runs this AFTER the GUI has been spawned
detached. Closing the window with a plain ``osascript ... close`` from inside the
``.command`` would run while ``bash`` + ``osascript`` are still alive in that very
window — which is exactly what triggers Terminal's "Do you want to terminate
running processes? (bash, osascript)" dialog. Verified empirically: a self-close
from within is blocked by that modal and the window stays open.

This helper instead:

  * detaches into its OWN session via ``os.setsid()`` so it is not one of the
    launcher window's processes (Terminal never counts it for that window);
  * waits briefly for the ``.command``'s ``bash`` to exit;
  * then closes the window identified by the tty the ``.command`` ran on — by
    which point that window's session has no running process, so the close is
    silent (no prompt).

macOS-only behaviour; on any other platform it does nothing. It is invoked only
by the ``.command`` and never imported by the application.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time


def main() -> int:
    # Windows uses setup_and_run.bat and never calls this; do nothing off macOS.
    if sys.platform != "darwin":
        return 0

    tty = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    if not tty:
        return 0

    # Leave the launcher window's session/process group so we are not counted
    # among that window's processes when we ask Terminal to close it.
    try:
        os.setsid()
    except OSError:
        pass

    # Let the launching bash finish and exit so the window has no live process.
    time.sleep(1.2)

    # Match the window by the exact tty device the .command was running on
    # (robust — unlike a window-title substring match).
    script = (
        'tell application "Terminal"\n'
        "  repeat with w in windows\n"
        "    repeat with t in tabs of w\n"
        "      try\n"
        f'        if (tty of t) is "{tty}" then close w saving no\n'
        "      end try\n"
        "    end repeat\n"
        "  end repeat\n"
        "end tell\n"
    )
    try:
        subprocess.run(
            ["osascript", "-e", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
