#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import tkinter as tk
from tkinter import ttk, messagebox

_FONT_FAMILY = "Segoe UI" if sys.platform == "win32" else "Helvetica Neue"


@dataclass(frozen=True)
class ToolSpec:
    key: str
    title: str
    script_relpath: str
    description: str


TOOLS: list[ToolSpec] = [
    ToolSpec(
        key="mp3",
        title="MP3 Tool",
        script_relpath="mp3_tool.py",
        description=(
            "Combine MP3s, add/remove time at end of tracks, and bulk-write ID3 tags.\n"
            "Requires: ffmpeg/ffprobe, mutagen."
        ),
    ),
    ToolSpec(
        key="m4b_maker",
        title="M4B Maker",
        script_relpath="m4b_maker.py",
        description=(
            "Build a chaptered M4B from MP3 files. Optional cover preview.\n"
            "Requires: ffmpeg/ffprobe. Pillow enables cover preview."
        ),
    ),
    ToolSpec(
        key="m4b_converter",
        title="M4B Converter",
        script_relpath="m4b_converter.py",
        description=("Batch convert M4B → MP3 with optional bulk metadata.\nRequires: ffmpeg/ffprobe."),
    ),
    ToolSpec(
        key="cover",
        title="Cover Resizer",
        script_relpath="cover_resizer.py",
        description=(
            "Batch resize cover images to audiobook-friendly square output.\n"
            "Requires: Pillow. Optional: pillow-heif for HEIC/HEIF."
        ),
    ),
]


class LauncherApp(ttk.Frame):
    def __init__(self, master: tk.Tk):
        super().__init__(master)
        self.master = master
        self.repo_root = Path(__file__).resolve().parent
        self.proc_by_key: dict[str, subprocess.Popen] = {}
        self._build_ui()
        self._log(f"Launcher started. Python: {sys.version.split()[0]}")
        self._log(f"Working directory: {self.repo_root}")

    def _build_ui(self):
        self.master.title("MP3 / M4B / Cover Tools Launcher")
        self.master.geometry("980x620")
        self.master.minsize(900, 560)

        outer = ttk.Frame(self.master, padding=14)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=0)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=1)

        # Left: big buttons
        left = ttk.Frame(outer)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 14))

        ttk.Label(left, text="Tools", font=(_FONT_FAMILY, 14, "bold")).pack(anchor="w", pady=(0, 10))

        for tool in TOOLS:
            b = ttk.Button(left, text=tool.title, command=lambda t=tool: self.launch_tool(t))
            b.pack(fill="x", pady=6, ipadx=10, ipady=10)

        ttk.Separator(left).pack(fill="x", pady=10)

        ttk.Button(left, text="Exit", command=self.master.destroy).pack(fill="x", pady=(6, 0))

        # Right: description + status
        right = ttk.Frame(outer)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(2, weight=1)
        right.columnconfigure(0, weight=1)

        self.title_var = tk.StringVar(value="Select a tool")
        ttk.Label(right, textvariable=self.title_var, font=(_FONT_FAMILY, 14, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )

        self.desc = tk.Text(right, height=6, wrap="word")
        self.desc.grid(row=1, column=0, sticky="ew")
        self.desc.configure(state=tk.DISABLED)

        log_frame = ttk.LabelFrame(right, text="Status")
        log_frame.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        self.log = tk.Text(log_frame, wrap="word")
        self.log.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=sb.set, state=tk.DISABLED)

        # Default description
        _setup_hint = "setup_and_run_mp3.sh" if sys.platform == "darwin" else "Setup_and_Run_MP3.bat"
        self._set_description(
            "This launcher starts each tool in a separate process.\n"
            f"If setup detected missing dependencies, run `{_setup_hint}` again."
        )

    def _set_description(self, text: str):
        self.desc.configure(state=tk.NORMAL)
        self.desc.delete("1.0", "end")
        self.desc.insert("1.0", text)
        self.desc.configure(state=tk.DISABLED)

    def _log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.log.configure(state=tk.NORMAL)
        self.log.insert("end", f"[{ts}] {msg}\n")
        self.log.see("end")
        self.log.configure(state=tk.DISABLED)
        self.master.update_idletasks()

    def _tool_script_path(self, tool: ToolSpec) -> Path:
        return (self.repo_root / tool.script_relpath).resolve()

    def _python_for_child(self) -> str:
        # If we were launched via pythonw/pyw, sys.executable will be windowless already.
        # If not, prefer pythonw.exe when available to avoid flashing a console.
        exe = Path(sys.executable)
        if exe.name.lower() in {"pythonw.exe", "pyw.exe"}:
            return str(exe)

        if exe.name.lower() == "python.exe":
            pyw = exe.with_name("pythonw.exe")
            if pyw.exists():
                return str(pyw)

        return str(exe)

    def launch_tool(self, tool: ToolSpec):
        self.title_var.set(tool.title)
        self._set_description(tool.description)

        script_path = self._tool_script_path(tool)
        if not script_path.exists():
            messagebox.showerror(
                "Missing tool script",
                f"Can't find:\n{script_path}\n\nMake sure the `tools/` folder is present.",
            )
            return

        if tool.key in self.proc_by_key:
            p = self.proc_by_key[tool.key]
            if p.poll() is None:
                messagebox.showinfo(tool.title, "This tool is already running.")
                return

        python_exe = self._python_for_child()
        cmd = [python_exe, str(script_path)]

        try:
            self._log(f"Starting {tool.title}…")
            p = subprocess.Popen(
                cmd,
                cwd=str(self.repo_root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
            self.proc_by_key[tool.key] = p
            self._log(f"{tool.title} started (pid {p.pid}).")
            threading.Thread(
                target=self._watch_process, args=(tool.title, tool.key, p), daemon=True
            ).start()
        except Exception as e:
            self._log(f"Failed to start {tool.title}: {e}")
            messagebox.showerror(tool.title, f"Failed to start.\n\n{e}")

    def _watch_process(self, title: str, key: str, p: subprocess.Popen):
        code = p.wait()
        self.master.after(0, lambda: self._log(f"{title} exited with code {code}."))  # type: ignore[arg-type]
        self.master.after(0, lambda: self.proc_by_key.pop(key, None))  # type: ignore[arg-type]


def main() -> int:
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except Exception:
        pass
    _app = LauncherApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

