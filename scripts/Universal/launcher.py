#!/usr/bin/env python3
"""Unified launcher for the Audiobook Creation Tool.

A single window with a sidebar of tools on the left and one swappable content
panel on the right. Each tool exposes ``build_ui(parent)`` and is built into its
own container the first time it is selected, then shown/hidden on later
selections so in-progress state (file lists, typed metadata) survives switching.

Theming lives in ``shared/ui_theme.py`` and the shell is chosen from
``theme["mode"]``:

- ``aqua`` (macOS) — a native Finder-style shell: source-list sidebar, toolbar
  strip, content card.
- ``windows`` — the v0.6.0 dark shell: navigation rail, header strip with the
  active tool's name/description, framed content card, status bar with a log
  action. Built entirely from the ``ACT.*`` styles in the theme bundle.
- ``classic`` (Linux/other) — the pre-v0.5.0 layout, byte-for-byte.

**The content host is never styled.** ``self.content`` and each tool's
container stay plain, unstyled ``ttk.Frame``s in every mode, so a panel that
has not been converted inherits nothing from the shell and keeps rendering
through the platform's generic ttk styles. A converted panel opts in by naming
``ACT.*`` styles itself.

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

from shared import ffmpeg_utils, logging_setup, paths, preferences_ui, ui_theme
from shared import settings as app_settings
from shared import subprocess_utils as sp

APP_TITLE = "Audiobook Creation Tool"

#: Label of the cross-platform Preferences & Data entry point in the status bar.
PREFERENCES_LABEL = preferences_ui.MENU_LABEL


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
        "Convert PDF / TXT into a narrated MP3 using Edge TTS or the local Kokoro AI voices.",
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
        # The one live Preferences window. Held here so repeated activation
        # focuses it instead of stacking duplicates.
        self.preferences_dialog = None

        self._build_ui()
        self._apply_default_geometry()
        self._bind_preferences_accelerators()

        # Open the last-used tool, or the first available one.
        last = app_settings.get("last_tool")
        start_key = last if any(t.key == last for t in self._available_tools()) else None
        if start_key is None and self._available_tools():
            start_key = self._available_tools()[0].key
        if start_key:
            self.select_tool(start_key)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Configuration diagnostics are reported once, after the window exists,
        # so a bad value can never turn into a startup failure.
        self.root.after(0, self.present_configuration_warnings)
        # Then, if a previous session cleared downloaded data, say what happened.
        # Second in the queue so the two reports cannot argue over focus, and
        # after the launcher is safely built either way.
        self.root.after(0, self.present_downloaded_data_report)

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
        elif self.theme["mode"] == "windows":
            self._build_ui_windows()
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
        # A real button, not a link label: Preferences must be keyboard-reachable
        # on every platform, and the classic shell has no styling to preserve.
        self.preferences_button = ttk.Button(
            status, text=PREFERENCES_LABEL, command=self.open_preferences, takefocus=True
        )
        self.preferences_button.pack(side="right", padx=(0, 12))

    def _build_ui_windows(self):
        """The v0.6.0 dark Windows shell — navigation rail, header, card, status.

        Every widget here names an ``ACT.*`` style from ``theme["styles"]``;
        no generic style is configured and no value is hard-coded, so the five
        unconverted panels are untouched (see ``shared/ui_theme.py``).

        Nothing in this method uses a fixed pixel height: the header and status
        bar size themselves from their own fonts so 125% display scaling grows
        them instead of clipping them. The sidebar is the one fixed dimension
        (``metrics["sidebar_width"]``), which has ample slack for the longest
        tool name at 125%.
        """
        s = self.theme["styles"]
        c = self.theme["colors"]
        m = self.theme["metrics"]
        self.root.configure(background=c["window"])

        # --- status bar (packed first so it can never be squeezed out) -------
        status_outer = ttk.Frame(self.root, style=s["window"])
        status_outer.pack(fill="x", side="bottom")
        ttk.Frame(status_outer, style=s["divider"], height=1).pack(fill="x")
        status = ttk.Frame(status_outer, style=s["window"],
                           padding=(m["status_pad"][0], m["status_pad"][1]))
        status.pack(fill="x")
        self.status_var = tk.StringVar(value="Ready.")
        self._status_label = ttk.Label(
            status, textvariable=self.status_var, style=s["status_label"],
            anchor="w",
        )
        self._status_label.pack(side="left", fill="x", expand=True)
        # A real button rather than the classic clickable label: it takes
        # keyboard focus, shows the theme's focus ring, and fires on Enter and
        # Space. The action itself is unchanged.
        self._log_button = ttk.Button(
            status, text="Open log folder", style=s["ghost_button"],
            command=self._open_logs, takefocus=True,
        )
        self._log_button.pack(side="right", padx=(m["gap_md"], 0))
        # Same ghost treatment as the log action, so the status bar keeps one
        # visual language and both actions stay in the Tab order.
        self.preferences_button = ttk.Button(
            status, text=PREFERENCES_LABEL, style=s["ghost_button"],
            command=self.open_preferences, takefocus=True,
        )
        self.preferences_button.pack(side="right", padx=(m["gap_md"], 0))

        outer = ttk.Frame(self.root, style=s["window"])
        outer.pack(fill="both", expand=True)

        # --- navigation rail --------------------------------------------------
        sidebar = ttk.Frame(outer, style=s["sidebar"], width=m["sidebar_width"])
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        ttk.Label(sidebar, text="TOOLS", style=s["sidebar_label"], anchor="w"
                  ).pack(fill="x", padx=m["sidebar_pad"] + m["row_padx"],
                         pady=(m["gap_lg"], m["gap_sm"]))

        for spec in self._available_tools():
            b = ttk.Button(
                sidebar, text=spec.title, style=s["nav_button"],
                command=lambda key=spec.key: self.select_tool(key),
            )
            b.pack(fill="x", padx=m["sidebar_pad"], pady=(0, m["row_gap"]))
            self.buttons[spec.key] = b

        ttk.Frame(outer, style=s["divider"], width=1).pack(side="left", fill="y")

        # --- header strip + content card -------------------------------------
        column = ttk.Frame(outer, style=s["window"])
        column.pack(side="left", fill="both", expand=True)

        header = ttk.Frame(column, style=s["toolbar"],
                           padding=(m["content_pad"], m["gap_md"],
                                    m["content_pad"], m["gap_sm"]))
        header.pack(fill="x")
        self._toolbar_title = ttk.Label(header, text=APP_TITLE, style=s["title"],
                                        anchor="w")
        self._toolbar_title.pack(fill="x")
        self._toolbar_desc = ttk.Label(header, text="", style=s["status_label"],
                                       anchor="w")
        self._toolbar_desc.pack(fill="x", pady=(m["gap_xs"], 0))
        ttk.Frame(column, style=s["divider"], height=1).pack(fill="x")

        # Deliberately the tight end of the spacing scale rather than
        # ``content_pad``: the rail plus this card frame already cost the tool
        # panels 143px of width against the classic shell, and every one of
        # those pixels is content the five unconverted panels cannot reflow.
        card_holder = ttk.Frame(column, style=s["window"])
        card_holder.pack(fill="both", expand=True, padx=m["gap_sm"],
                         pady=(m["gap_sm"], m["gap_sm"]))
        # A 1px hairline frame drawn *around* the content host, so the card has
        # a border without the host itself carrying a style a panel could
        # inherit from.
        card = ttk.Frame(card_holder, style=s["divider"])
        card.pack(fill="both", expand=True)

        # Deliberately unstyled: the swappable content area keeps the generic
        # ttk.Frame background so an unconverted panel renders exactly as it
        # does on master, and the converted editor paints over it in Phase 3.
        self.content = ttk.Frame(card)
        self.content.pack(fill="both", expand=True, padx=1, pady=1)

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
        # A native aqua ttk.Button rather than another link label: Preferences
        # has to be keyboard-reachable, and an unstyled ttk widget is exactly
        # what keeps macOS rendering natively.
        self.preferences_button = ttk.Button(
            status, text=PREFERENCES_LABEL, command=self.open_preferences, takefocus=True
        )
        self.preferences_button.pack(side="right", padx=(0, m["row_padx"]))

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

    # ----- Preferences & Data -----
    def _bind_preferences_accelerators(self):
        """Ctrl+, and Cmd+, — the conventional Preferences shortcut on each OS.

        Both are bound unconditionally: a shortcut that the platform never
        emits simply never fires, which is cheaper than branching on
        ``sys.platform`` for a key binding.
        """
        for sequence in preferences_ui.ACCELERATORS:
            try:
                self.root.bind_all(sequence, lambda _e: self.open_preferences())
            except tk.TclError:
                pass

    def open_preferences(self):
        """Open Preferences & Data, or focus the window that is already open."""
        self.preferences_dialog = preferences_ui.open_preferences(
            self.root, self.theme, self.preferences_dialog, logger=self.logger,
            close_application=self.close_for_downloaded_data,
        )
        self._set_status("Preferences & Data.")
        return self.preferences_dialog

    def close_for_downloaded_data(self):
        """Shut the app down so the separate helper can clear the selected data.

        Reached only after that helper has acknowledged the request. The
        last-used tool is still remembered, exactly as on an ordinary close.
        """
        self._on_close()

    def present_downloaded_data_report(self):
        """Report what the last clearing run did — once, and never fatally."""
        try:
            return preferences_ui.present_cleanup_result(
                self.root, self.theme, logger=self.logger
            )
        except Exception:
            self.logger.exception("Could not present the downloaded-data report")
            return None

    def present_configuration_warnings(self):
        """Report configuration diagnostics once per launch. Never fatal."""
        try:
            summary = preferences_ui.present_launch_warnings(
                self.root, self.theme, logger=self.logger
            )
        except Exception:
            # A warning about configuration must never itself break the launch.
            self.logger.exception("Could not present configuration warnings")
            return None
        if summary:
            self._set_status("Some settings could not be used — safe defaults are in force.")
        return summary

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
        # This panel is launcher-owned chrome, not tool content, so on Windows
        # it is themed. It is the one thing inside a tool container that may
        # carry an ACT.* style — and it only exists when that tool failed to
        # build, which the smoke tests assert never happens.
        if self.theme["mode"] == "windows":
            s, m = self.theme["styles"], self.theme["metrics"]
            frame = ttk.Frame(container, padding=m["content_pad"], style=s["window"])
            frame.pack(fill="both", expand=True)
            ttk.Label(frame, text=f"{spec.title}", style=s["title"]).pack(anchor="w")
            # ACT.Danger.TLabel sits on the card surface; this banner sits on
            # the window background, so the danger tone is taken from the same
            # token instead (still no literal, and no style is redefined).
            ttk.Label(frame, text="This tool could not be loaded.",
                      style=s["status_label"],
                      foreground=self.theme["colors"]["danger"],
                      ).pack(anchor="w", pady=(2, 0))
            txt = tk.Text(frame, wrap="word", height=18,
                          font=self.theme["fonts"]["mono"])
            ui_theme.style_tk_widget(txt, self.theme, "log")
            txt.pack(fill="both", expand=True, pady=(m["gap_md"], 0))
        else:
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
        if self.theme["mode"] == "windows":
            # The nav rail marks the active tool with the standard ttk
            # ``selected`` state flag, which ACT.Nav.TButton maps to the soft
            # accent fill. Unlike the classic cue the row stays enabled, so it
            # remains reachable by Tab and keeps its focus ring.
            for k, btn in self.buttons.items():
                btn.state(["selected"] if k == key else ["!selected"])
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
