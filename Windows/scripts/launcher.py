#!/usr/bin/env python3
"""Unified launcher for the Audiobook Creation Tool.

A single window with a sidebar of tools on the left and one swappable content
panel on the right. Each tool exposes ``build_ui(parent)`` and is built into its
own container the first time it is selected, then shown/hidden on later
selections so in-progress state (file lists, typed metadata) survives switching.

Run under ``pythonw.exe`` on Windows so no console window appears; all external
binaries (ffmpeg/ffprobe) are invoked through ``shared.subprocess_utils`` which
hides their console windows too.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path

import tkinter as tk
from tkinter import ttk

# Make the scripts/ root importable whether launched as `python scripts/launcher.py`
# or imported. (sys.path[0] is already scripts/ when run directly; this is belt-and-braces.)
_SCRIPTS_ROOT = Path(__file__).resolve().parent
if str(_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ROOT))

from shared import ffmpeg_utils, logging_setup, paths
from shared import settings as app_settings
from shared import subprocess_utils as sp

APP_TITLE = "Audiobook Creation Tool"
DEFAULT_GEOMETRY = "1024x720"
MIN_SIZE = (920, 600)


@dataclass(frozen=True)
class ToolSpec:
    key: str
    title: str
    module: str  # importable module under scripts/, e.g. "tts.epub2tts_gui"
    description: str


# The six-tool sidebar. The Metadata Editor (Phase 6) is registered when its
# module exists; until then the launcher shows the five shipped tools.
TOOLS: list[ToolSpec] = [
    ToolSpec(
        "tts",
        "TTS Audiobook",
        "tts.epub2tts_gui",
        "Convert EPUB / PDF / TXT into a narrated MP3 using Edge TTS or the local Kokoro AI voices.",
    ),
    ToolSpec(
        "m4b_converter",
        "M4B Converter",
        "mp3_tools.m4b_converter",
        "Batch-convert M4B audiobooks into clean MP3 files.",
    ),
    ToolSpec(
        "mp3_tool",
        "MP3 Tool",
        "mp3_tools.mp3_tool",
        "Combine MP3s, add/remove time at track ends, and bulk-write ID3 tags.",
    ),
    ToolSpec(
        "m4b_maker",
        "M4B Maker",
        "mp3_tools.m4b_maker",
        "Assemble MP3 files into a chaptered M4B with cover art and metadata.",
    ),
    ToolSpec(
        "cover",
        "Cover Image",
        "mp3_tools.cover_resizer",
        "Resize cover art to a clean square (letterbox without cropping, or center-crop).",
    ),
    ToolSpec(
        "m4b_metadata",
        "M4B Metadata",
        "mp3_tools.m4b_metadata_editor",
        "Edit tags on existing M4B files; untouched fields are preserved. (Added in Phase 6.)",
    ),
]


def _ui_font_family() -> str:
    if sys.platform == "win32":
        return "Segoe UI"
    if sys.platform == "darwin":
        return "Helvetica Neue"
    return "TkDefaultFont"


class LauncherApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.logger = logging_setup.get_logger()
        ffmpeg_utils.configure_pydub()

        self.containers: dict[str, ttk.Frame] = {}
        self.current_key: str | None = None
        self.buttons: dict[str, ttk.Button] = {}

        self._build_ui()
        self._apply_default_geometry()

        # Open the last-used tool, or the first available one.
        last = app_settings.get("last_tool")
        start_key = last if any(t.key == last for t in self._available_tools()) else None
        if start_key is None and self._available_tools():
            start_key = self._available_tools()[0].key
        if start_key:
            self.select_tool(start_key)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ----- which tools actually exist (Metadata Editor lands in Phase 6) -----
    def _available_tools(self) -> list[ToolSpec]:
        out: list[ToolSpec] = []
        for spec in TOOLS:
            if spec.key == "m4b_metadata" and not self._module_exists(spec.module):
                continue
            out.append(spec)
        return out

    @staticmethod
    def _module_exists(module: str) -> bool:
        try:
            return importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            return False

    # ----- UI -----
    def _build_ui(self):
        self.root.title(APP_TITLE)
        self.root.minsize(*MIN_SIZE)

        family = _ui_font_family()
        self.font_heading = (family, 15, "bold")
        self.font_button = (family, 11)

        try:
            ttk.Style().theme_use("vista" if sys.platform == "win32" else "clam")
        except tk.TclError:
            pass

        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=0)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=1)

        # Sidebar
        sidebar = ttk.Frame(outer)
        sidebar.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        ttk.Label(sidebar, text="Tools", font=self.font_heading).pack(anchor="w", pady=(0, 10))

        for spec in self._available_tools():
            b = ttk.Button(
                sidebar, text=spec.title, command=lambda s=spec: self.select_tool(s.key)
            )
            b.pack(fill="x", pady=4, ipady=8)
            self.buttons[spec.key] = b

        # Content area (swappable)
        self.content = ttk.Frame(outer, relief="groove", borderwidth=1)
        self.content.grid(row=0, column=1, sticky="nsew")

        # Status bar
        status = ttk.Frame(self.root, padding=(10, 4))
        status.pack(fill="x", side="bottom")
        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(status, textvariable=self.status_var).pack(side="left")
        log_link = ttk.Label(
            status, text="Open log folder", foreground="#1d4ed8", cursor="hand2"
        )
        log_link.pack(side="right")
        log_link.bind("<Button-1>", lambda _e: self._open_logs())

    def _set_status(self, msg: str):
        self.status_var.set(msg)

    def _open_logs(self):
        paths.logs_dir()  # ensure it exists
        sp.reveal_in_file_manager(paths.LOGS_DIR)

    # ----- tool switching -----
    def select_tool(self, key: str):
        if key == self.current_key:
            return

        # Hide the current tool's container.
        if self.current_key and self.current_key in self.containers:
            self.containers[self.current_key].pack_forget()

        # Build the tool once, lazily; reuse afterwards so state survives switches.
        if key not in self.containers:
            container = ttk.Frame(self.content)
            if not self._load_tool_into(key, container):
                container.destroy()
                return
            self.containers[key] = container

        self.containers[key].pack(fill="both", expand=True)
        self.current_key = key
        self._highlight_selection(key)

        spec = next((t for t in TOOLS if t.key == key), None)
        if spec:
            self._set_status(f"{spec.title} — ready.")
        app_settings.set("last_tool", key)

    def _load_tool_into(self, key: str, container: ttk.Frame) -> bool:
        spec = next((t for t in TOOLS if t.key == key), None)
        if spec is None:
            return False
        try:
            module = importlib.import_module(spec.module)
            module.build_ui(container)
            self.logger.debug("Loaded tool %s (%s)", key, spec.module)
            return True
        except Exception as exc:  # missing deps, import error, etc.
            self.logger.exception("Failed to load tool %s", key)
            self._show_load_error(container, spec, exc)
            return True  # keep the container so the error message stays visible

    def _show_load_error(self, container: ttk.Frame, spec: ToolSpec, exc: Exception):
        msg = (
            f"Could not load '{spec.title}'.\n\n"
            f"{type(exc).__name__}: {exc}\n\n"
            "This usually means a dependency is missing. Try running the setup "
            "launcher again to reinstall requirements.\n\n"
            f"{traceback.format_exc()}"
        )
        frame = ttk.Frame(container, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=f"{spec.title}", font=self.font_heading).pack(anchor="w")
        txt = tk.Text(frame, wrap="word", height=18)
        txt.pack(fill="both", expand=True, pady=(8, 0))
        txt.insert("1.0", msg)
        txt.configure(state=tk.DISABLED)
        self._set_status(f"{spec.title} failed to load.")

    def _highlight_selection(self, key: str):
        # Light-touch selection cue: disable the active button, enable the rest.
        for k, btn in self.buttons.items():
            btn.state(["disabled"] if k == key else ["!disabled"])

    # ----- geometry -----
    def _apply_default_geometry(self):
        # Always open at the default size — window size/position is intentionally
        # not persisted across sessions (only the last-selected tool is).
        self.root.geometry(DEFAULT_GEOMETRY)

    def _on_close(self):
        try:
            app_settings.set("last_tool", self.current_key)
        except Exception:
            pass
        self.root.destroy()


def main() -> int:
    root = tk.Tk()
    LauncherApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
