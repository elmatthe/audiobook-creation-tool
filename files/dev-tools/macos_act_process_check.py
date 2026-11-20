#!/usr/bin/env python3
"""KX-10 (v0.8.x P1B, owner-manual): after a Force Quit, is anything of this app still running, and what did it leave?

READ ONLY. It lists processes and folders and changes nothing: it never stops, signals or deletes anything, and it opens
no file for writing. Run it with any Python 3 (the app's own is fine), from anywhere:

    files/runtime-data/python/bin/python3 files/dev-tools/macos_act_process_check.py [--outputs <output folder>]

A process counts as this app's when the program it runs lives inside this checkout (the app's own Python and FFmpeg
are both under it) or its command line names a file inside this checkout (``scripts/launcher.py``, the containment
helpers ``child_entry.py`` and ``child_guardian.py``, the setup scripts). That is how it is *reported*, never acted on.

Exit 0: no process of this app is running. Exit 1: at least one is (listed with pid, parent, group, start time and
command). Leftovers in the output folder (``.work`` staging and ``.act-tmp-`` temporary files) are listed either way:
the next launch of the tool recovers staging, so they are information, not a failure.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUTS = Path.home() / "Downloads" / "Audiobook-Creation-Tool-Outputs"


def _processes() -> list[dict]:
    """Every process this user can see, from ``ps`` (no privilege, nothing changed)."""
    done = subprocess.run(["/bin/ps", "-axww", "-o", "pid=,ppid=,pgid=,user=,lstart=,command="],
                          capture_output=True, text=True, timeout=30, check=True)
    rows = []
    for line in done.stdout.splitlines():
        parts = line.split(None, 9)
        if len(parts) < 10:
            continue
        pid, ppid, pgid, user = parts[:4]
        started = " ".join(parts[4:9])
        rows.append({"pid": int(pid), "ppid": int(ppid), "pgid": int(pgid), "user": user, "started": started,
                     "command": parts[9]})
    return rows


def _program_path(pid: int) -> str:
    """The executable's full path from the kernel (libproc), or '' when it cannot be read."""
    try:
        import ctypes

        libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        buffer = ctypes.create_string_buffer(4096)
        length = libproc.proc_pidpath(ctypes.c_int(pid), buffer, ctypes.c_uint32(4096))
        return buffer.value.decode("utf-8", "replace") if length > 0 else ""
    except (OSError, AttributeError):
        return ""


def act_processes(root: Path = ROOT) -> list[dict]:
    me = os.getpid()
    inside = str(root) + os.sep
    found = []
    for row in _processes():
        if row["pid"] == me:
            continue
        program = _program_path(row["pid"])
        if program.startswith(inside) or inside in row["command"]:
            found.append({**row, "program": program})
    return found


def leftovers(outputs: Path) -> list[str]:
    if not outputs.is_dir():
        return []
    found = []
    for path in sorted(outputs.rglob("*")):
        if path.name == ".work" and path.is_dir():
            found.append(f"staging folder (recovered at the next run of that tool): {path}")
        elif path.name.startswith(".act-tmp-"):
            found.append(f"temporary file (never under a final name): {path}")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--outputs", type=Path, default=DEFAULT_OUTPUTS,
                        help=f"the app's output folder (default {DEFAULT_OUTPUTS})")
    parser.add_argument("--json", action="store_true", help="print the findings as JSON")
    args = parser.parse_args(argv)
    if sys.platform != "darwin":
        print("This check is for macOS.")
        return 2
    running = act_processes()
    left = leftovers(args.outputs)
    if args.json:
        print(json.dumps({"checkout": str(ROOT), "running": running, "leftovers": left}, indent=2))
    else:
        print(f"Checkout: {ROOT}")
        if running:
            print(f"STILL RUNNING: {len(running)} process(es) of this app:")
            for row in running:
                print(f"  pid {row['pid']} (parent {row['ppid']}, group {row['pgid']}, started {row['started']}): {row['command']}")
        else:
            print("No process of this app is running.")
        print(f"Output folder: {args.outputs}")
        for line in left:
            print(f"  {line}")
        if not left:
            print("  no staging or temporary leftovers")
    return 1 if running else 0


if __name__ == "__main__":
    raise SystemExit(main())
