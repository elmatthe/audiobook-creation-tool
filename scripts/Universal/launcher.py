#!/usr/bin/env python3
"""Unified launcher for the Audiobook Creation Tool.

A single window with a sidebar of tools on the left and one swappable content
panel on the right. Each tool exposes ``build_ui(parent)`` and is built into its
own container the first time it is selected, then shown/hidden on later
selections so in-progress state (file lists, typed metadata) survives switching.

Theming lives in ``shared/ui_theme.py``: macOS gets a native-aqua Finder-style
shell (source-list sidebar, toolbar strip, content card); Windows and other
platforms keep the classic layout byte-for-byte.

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

try:
    import tkinter as tk
    from tkinter import ttk
except (ImportError, ModuleNotFoundError) as _tk_err:  # Tk-less / headless Python
    import sys as _sys
    _sys.stderr.write(
        "\n[Audiobook Creation Tool] The graphical interface cannot start because\n"
        "this Python build has no working Tk (tkinter) support.\n\n"
        "To enable the window, install Tk and relaunch:\n"
        "  - macOS (Homebrew):  brew install python-tk@3.12\n"
        "  - then double-click Setup_and_Run-audiobook-creation-tool again.\n\n"
        f"(details: {_tk_err})\n"
    )
    raise SystemExit(1)

# Make the scripts/ root importable whether launched as `python scripts/launcher.py`
# or imported. (sys.path[0] is already scripts/ when run directly; this is belt-and-braces.)
_SCRIPTS_ROOT = Path(__file__).resolve().parent
if str(_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ROOT))

from shared import ffmpeg_utils, logging_setup, paths, ui_theme
from shared import settings as app_settings
from shared import subprocess_utils as sp

APP_TITLE = "Audiobook Creation Tool"


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
        "Edit tags, series info, and chapter titles on existing M4B files without re-encoding.",
    ),
]


# Leading sidebar glyphs (macOS shell only; the classic layout has none).
_TOOL_GLYPHS = {
    "tts": "🎙",
    "m4b_converter": "🔄",
    "mp3_tool": "🎵",
    "m4b_maker": "📚",
    "cover": "🖼",
    "m4b_metadata": "🏷",
}


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
        self.theme = ui_theme.apply_theme(self.root, ttk.Style(self.root))
        self.root.minsize(*self.theme["min_size"])
        self.font_heading = self.theme["font_heading"]
        self.font_button = self.theme["font_button"]

        if self.theme["mode"] == "aqua":
            self._build_ui_darwin()
        else:
            self._build_ui_classic()

    def _build_ui_classic(self):
        """The pre-v0.5.0 layout — Windows rendering must stay byte-identical."""
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

    def _build_ui_darwin(self):
        """Finder-style shell: source-list sidebar, toolbar strip, content card.

        Chrome is built from classic tk widgets because the aqua theme cannot
        recolor native-drawn ttk widgets; the tool panels themselves stay ttk
        and render as native aqua controls.
        """
        c = self.theme["colors"]
        m = self.theme["metrics"]
        self.root.configure(background=c["window"])

        # Status bar (packed first so it can never be squeezed out).
        status_outer = tk.Frame(self.root, bg=c["window"])
        status_outer.pack(fill="x", side="bottom")
        tk.Frame(status_outer, bg=c["separator"], height=1).pack(fill="x")
        status = tk.Frame(status_outer, bg=c["window"])
        status.pack(fill="x", padx=m["status_pad"][0], pady=m["status_pad"][1])
        self.status_var = tk.StringVar(value="Ready.")
        tk.Label(status, textvariable=self.status_var, bg=c["window"],
                 fg=c["secondary"], font=self.theme["font_status"],
                 anchor="w").pack(side="left")
        log_link = tk.Label(status, text="Open log folder", bg=c["window"],
                            fg=c["link"], cursor="pointinghand",
                            font=self.theme["font_status"])
        log_link.pack(side="right")
        log_link.bind("<Button-1>", lambda _e: self._open_logs())

        outer = tk.Frame(self.root, bg=c["window"])
        outer.pack(fill="both", expand=True)

        # Source-list sidebar
        sidebar = tk.Frame(outer, bg=c["sidebar"], width=m["sidebar_width"])
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        tk.Label(sidebar, text="TOOLS", bg=c["sidebar"], fg=c["secondary"],
                 font=self.theme["font_section"], anchor="w"
                 ).pack(fill="x", padx=m["sidebar_pad"] + m["row_padx"],
                        pady=(m["sidebar_pad"] + 2, 4))

        self.sidebar_rows: dict[str, tuple[tk.Frame, tk.Label]] = {}
        for spec in self._available_tools():
            row = tk.Frame(sidebar, bg=c["sidebar"], height=m["row_height"])
            row.pack(fill="x", padx=m["sidebar_pad"], pady=(0, m["row_gap"]))
            row.pack_propagate(False)
            glyph = _TOOL_GLYPHS.get(spec.key, "")
            lbl = tk.Label(row, text=f"{glyph}  {spec.title}".strip(),
                           bg=c["sidebar"], fg=c["text"],
                           font=self.theme["font_row"], anchor="w",
                           padx=m["row_padx"])
            lbl.pack(fill="both", expand=True)
            for w in (row, lbl):
                w.bind("<Button-1>", lambda _e, s=spec: self.select_tool(s.key))
                w.bind("<Enter>", lambda _e, k=spec.key: self._row_hover(k, True))
                w.bind("<Leave>", lambda _e, k=spec.key: self._row_hover(k, False))
            self.sidebar_rows[spec.key] = (row, lbl)

        tk.Frame(outer, bg=c["separator"], width=1).pack(side="left", fill="y")

        # Toolbar strip + content card
        column = tk.Frame(outer, bg=c["window"])
        column.pack(side="left", fill="both", expand=True)

        toolbar = tk.Frame(column, bg=c["window"], height=m["toolbar_height"])
        toolbar.pack(fill="x")
        toolbar.pack_propagate(False)
        self._toolbar_title = tk.Label(toolbar, text=APP_TITLE, bg=c["window"],
                                       fg=c["text"], font=self.font_heading,
                                       anchor="w")
        self._toolbar_title.pack(side="left", padx=(m["content_pad"], 8))
        self._toolbar_desc = tk.Label(toolbar, text="", bg=c["window"],
                                      fg=c["secondary"],
                                      font=self.theme["font_status"], anchor="w")
        self._toolbar_desc.pack(side="left", fill="x", expand=True)
        tk.Frame(column, bg=c["separator"], height=1).pack(fill="x")

        card_holder = tk.Frame(column, bg=c["window"])
        card_holder.pack(fill="both", expand=True)
        card = tk.Frame(card_holder, bg=c["card"],
                        highlightbackground=c["separator"], highlightthickness=1)
        card.pack(fill="both", expand=True,
                  padx=m["content_pad"], pady=m["content_pad"])

        # The swappable content area keeps its ttk.Frame type — every tool's
        # build_ui(parent) contract and container behaviour is unchanged.
        self.content = ttk.Frame(card)
        self.content.pack(fill="both", expand=True, padx=1, pady=1)

    def _row_hover(self, key: str, entering: bool):
        if key == self.current_key:
            return
        c = self.theme["colors"]
        bg = c["hover"] if entering else c["sidebar"]
        row, lbl = self.sidebar_rows[key]
        row.configure(bg=bg)
        lbl.configure(bg=bg)

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
        if self.theme["mode"] == "aqua":
            # Finder-style cue: accent highlight on the selected sidebar row,
            # and the toolbar strip names the active tool.
            c = self.theme["colors"]
            for k, (row, lbl) in self.sidebar_rows.items():
                bg = c["selection"] if k == key else c["sidebar"]
                fg = c["selection_text"] if k == key else c["text"]
                row.configure(bg=bg)
                lbl.configure(bg=bg, fg=fg)
            spec = next((t for t in TOOLS if t.key == key), None)
            if spec:
                self._toolbar_title.configure(text=spec.title)
                self._toolbar_desc.configure(text=spec.description)
            return
        # Classic cue: disable the active button, enable the rest.
        for k, btn in self.buttons.items():
            btn.state(["disabled"] if k == key else ["!disabled"])

    # ----- geometry -----
    def _apply_default_geometry(self):
        # Always open at the default size — window size/position is intentionally
        # not persisted across sessions (only the last-selected tool is).
        self.root.geometry(self.theme["geometry"])

    def _on_close(self):
        try:
            app_settings.set("last_tool", self.current_key)
        except Exception:
            pass
        self.root.destroy()


def _configure_hf_cache() -> None:
    """Keep the HuggingFace model cache inside the project tree.

    Mirrors ``bootstrap.py``: point ``HF_HOME`` at ``files/runtime-data/models/huggingface/``
    so the ~300 MB Kokoro model never lands in ``~/.cache/huggingface/``. The
    bootstrap fast-path already sets this and it inherits to the launched GUI, but
    set it here too for the case where the launcher is started directly (dev /
    debug) so the redirect holds no matter how the GUI is launched. Must run
    before any kokoro/huggingface import (Kokoro is imported lazily by the TTS
    tool, well after this).
    """
    import os
    hf_cache = paths.RESOURCES_DIR / "models" / "huggingface"
    try:
        hf_cache.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    os.environ["HF_HOME"] = str(hf_cache)
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(hf_cache / "hub"))


def main() -> int:
    # Install the global no-window guard first, before anything imports pydub /
    # edge-tts, so their internal ffmpeg spawns during the TTS combine stage
    # inherit hidden-window flags and do not flash console windows on Windows.
    sp.install_no_window_guard()
    _configure_hf_cache()
    root = tk.Tk()
    LauncherApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
