"""A closed window's Tk objects are finalised on the main thread, never by a worker — v0.7.2 Phase 6, ACT72-017.

After the window closes, a closed panel's Tk variables, images and fonts can still sit in reference cycles, or be held by
a worker that is finishing its run. If a collection then lands on a worker thread, each ``__del__`` calls into Tcl from
that thread: Tkinter waits about a second for a main loop that has already ended, then raises "main thread is not in
main loop", which Python reports and ignores. The gate's forced-landing arms measured 18 to 26 s of that at shutdown.
``launcher.main`` now calls ``_release_tk_objects`` on the main thread once the main loop has ended.

Each case runs a real ``tk.Tk()`` in a child process of its own (a second root in the suite's process is not safe), with
the root held the way ``launcher._ROOT`` holds it, a panel-like object in a reference cycle that a "worker" still holds
when the window has gone, and then the worker lets go and a collection is forced onto it. The control runs the very
same script without the release: it must show the waits and the ignored errors, or this test proves nothing.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("tkinter")

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
VARIABLES = 3

CHILD = r"""
import gc, json, sys, threading, time
sys.path.insert(0, sys.argv[1])
release = sys.argv[2] == "release"
import tkinter as tk
import tkinter.font as tkfont
import launcher

root = tk.Tk()
launcher._ROOT = root          # held for the life of the process, as the application does
root.withdraw()

class Panel:
    def __init__(self, master):
        self.frame = tk.Frame(master)
        self.variables = [tk.StringVar(master, value=f"v{i}") for i in range(%(variables)d)]
        self.variables[0].trace_add("write", lambda *a: None)
        self.image = tk.PhotoImage(master=master, width=4, height=4)
        self.font = tkfont.Font(root=master, family="Arial", size=9)
        self.me = self             # a reference cycle, as real panels have
        self.names = [v._name for v in self.variables]
        self.image_name = self.image.name
        self.font_name = self.font.name

panel = Panel(root)
names, image_name, font_name = panel.names, panel.image_name, panel.font_name
held = [panel]                     # a worker finishing its run still holds the panel
del panel
root.update()
root.destroy()                     # the window is gone; the main loop has ended

if release:
    launcher._release_tk_objects(root)

record = {}
unraisable = []
def worker():
    def hook(info):
        unraisable.append(f"{type(info.exc_value).__name__}: {info.exc_value}")
    me = threading.current_thread()
    passes = []
    def watch(phase, info):
        if phase == "stop" and info["generation"] == 2 and threading.current_thread() is me:
            passes.append(info["collected"])
    previous = sys.unraisablehook
    sys.unraisablehook = hook
    gc.callbacks.append(watch)
    began = time.monotonic()
    held.clear()                   # the worker lets go...
    while not passes and time.monotonic() - began < 30:
        gc.collect()               # ...and a collection lands on it
        if not passes:
            time.sleep(0.01)
    record["seconds"] = round(time.monotonic() - began, 3)
    record["passes_on_worker"] = len(passes)
    gc.callbacks.remove(watch)
    sys.unraisablehook = previous

thread = threading.Thread(target=worker)
thread.start()
thread.join(60)
record["unraisable"] = unraisable
record["tcl_variables_left"] = [n for n in names if root.tk.getboolean(root.tk.call("info", "exists", n))]
print(json.dumps(record))
""" % {"variables": VARIABLES}


def run_child(mode: str) -> dict:
    done = subprocess.run([sys.executable, "-c", CHILD, str(SCRIPTS), mode], capture_output=True, text=True,
                          timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_without_the_release_a_worker_collection_waits_and_raises_inside_tk():
    """The control: what the release prevents is really there in this harness."""
    record = run_child("control")
    assert record["passes_on_worker"] >= 1, "the collection really ran on the worker"
    assert record["seconds"] >= 0.8 * VARIABLES, record
    assert any("main thread is not in main loop" in line for line in record["unraisable"]), record


def test_after_the_release_a_worker_collection_touches_no_tk_and_waits_for_nothing():
    record = run_child("release")
    assert record["passes_on_worker"] >= 1, "the collection really ran on the worker"
    assert record["unraisable"] == [], record
    assert record["seconds"] < 0.5 * VARIABLES, record
    assert record["tcl_variables_left"] == [], "the Tcl variables were unset, on the main thread"
