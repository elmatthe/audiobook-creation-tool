"""A tiny Tk window owned by a native negative control. It proves what the driver refuses and what the forced-landing arm can see.

It counts every click on its button, so a control can show that nothing arrived, and it is not the application: nothing here is ever
evidence about ACT. With ``hazard`` it builds the exact shape the Phase 2 closeout measured, a closed root and a variable in a cycle with
nothing else holding them, and forces one collection onto a worker: that must end the process with ``Tcl_AsyncDelete``, or the forced
arm would be proving nothing about the application.

Usage: python control_target.py <config.json>
"""

from __future__ import annotations

import gc
import json
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))
from channel import Channel  # noqa: E402

def _routine_context():
    """helpers/routine_context.py, loaded by path so this program's own imports stay as they are (v0.8.2 Phase 1A-1 R1)."""
    import importlib.util
    import sys as _sys

    if "act_gate_routine_context" in _sys.modules:
        return _sys.modules["act_gate_routine_context"]
    spec = importlib.util.spec_from_file_location("act_gate_routine_context",
                                                  Path(__file__).resolve().parents[2] / "helpers" / "routine_context.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _sys.modules["act_gate_routine_context"] = module
    return module



class _Cycle:
    """What a panel is to its root: an object holding the window that the window, in turn, keeps a route back to."""


def main() -> int:
    config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    counts = Path(config["counts_file"])
    root = tk.Tk()
    root.title(config.get("title", "ACT acceptance control"))
    root.geometry(config.get("geometry", "360x200+100+100"))
    clicks = {"count": 0}

    def clicked() -> None:
        clicks["count"] += 1
        counts.write_text(str(clicks["count"]), encoding="ascii")

    holder = _Cycle()
    holder.button = ttk.Button(root, text="Target", command=clicked)
    holder.button.pack(padx=20, pady=20, fill="x")
    holder.disabled = ttk.Button(root, text="Disabled", state="disabled", command=clicked)
    holder.disabled.pack(padx=20, pady=4, fill="x")
    if config.get("on_top"):
        root.attributes("-topmost", True)

    channel = Channel(root, channel_file=config["channel_file"], resolve=lambda scope: holder)
    if config.get("no_input_mark"):
        root.unbind_all("<KeyPress-F24>")
    forced = config.get("force_worker_collection")
    if forced:
        holder.root, holder.variable, holder.self = root, tk.StringVar(master=root, value="x"), holder
        holder.channel = channel
    root.mainloop()
    if forced:
        del root, holder, channel, clicked
        done = threading.Event()

        def collect() -> None:
            Path(forced).write_text(json.dumps({"collected_on_worker": gc.collect()}), encoding="utf-8")
            done.set()

        threading.Thread(target=collect, name="forced-landing", daemon=True).start()
        done.wait(30)
    return 0


if __name__ == "__main__":
    _routine_context().refuse_under_routine("adapters/windows/control_target.py", "native-desktop")  # v0.8.2 Phase 1A-1 R1: wherever it lies
    raise SystemExit(main())
