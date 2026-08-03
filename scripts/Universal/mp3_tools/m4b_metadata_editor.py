#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
M4B Metadata Editor — edit tags on existing M4B files without re-encoding.

Open one or more M4B files and edit their tags (Title, Author/Artist, Album,
Year, Comment, Genre, cover image, and Audiobookshelf Series Name / Series Part).
Reading and writing go through shared.metadata (mutagen), which only touches the
keys you pass, so every other tag in each file is preserved.

Non-destructive (v0.1.1): the imported originals are **never modified**. Each
selected file is first copied into the output folder (a fresh
``Downloads/M4B-Metadata-N`` by default, redirectable via Browse for the current
run), and all tag writes run against the **copy**.

Behaviour:
- **Single file:** the form is pre-filled from the file's existing tags. Editing
  a field and saving writes that field back (to the copy).
- **Multiple files / folder (batch mode):** fields whose value is identical
  across ALL loaded files are pre-filled (shared-value detection, Drop 2);
  fields that differ are left blank and reported as "(varies)". Fields left
  **blank are not written** (each copy keeps the original's tag); any field
  with a value **overwrites** that tag in every copy. An "Open Folder…" button
  loads every .m4b/.m4a/.mp4 directly inside a chosen folder (non-recursive).

Series Name / Series Part are written as the freeform atoms
``----:com.apple.iTunes:SERIES`` / ``SERIES-PART`` (Briefing §6), which
Audiobookshelf's ffprobe scanner reads as ``series`` / ``series-part``. When a
part is auto-numbered the writer also sets the native ``trkn`` (Windows
Explorer's ``#`` column) and movement atoms (``©mvn``/``©mvi``/``©mvc``) — see
``shared.metadata.write_m4b_tags``. "Remove Series Numbering" strips every one of
those surfaces again (``shared.metadata.clear_series_numbering``).

Series Part is governed by an **Auto-number** toggle: OFF (default) writes
nothing to series-part (the field is display-only — preserve-by-default); ON
treats the Series Part field as the starting number and writes sequential parts
across the loaded files in list order (a single file gets just that number).

Refactored like the other tools: UI is built by build_ui(parent); the save runs
on a worker thread with a Cancel button (cooperative cancellation between files)
via shared.cancellation; a standalone main() is kept for debugging.

Presentation (v0.6.0 Drop 1, Phase 3): the panel forks on ``theme["mode"]``.
On Windows it builds a card layout from the ``ACT.*`` design system in
``shared/ui_theme.py`` — an "Audiobook Files" card, the distinct **Shared
Metadata** surface (muted accent fill/border/header) holding every batch-wide
tag field plus the series sub-group, then Chapter Titles, Output, an
always-visible action bar and an always-visible Log. Every other platform
builds the historical layout byte-for-byte. **Nothing about metadata reading,
writing, precedence, file order, output paths, threading or cancellation
differs between the two** — both forks create the same widgets and attributes
and every method below is shared. The Shared Metadata grouping is a visual
statement of the batch behaviour that already exists; it adds no per-book
override, disables no field, and implements no Plan 6/8 precedence.
"""

import queue
import shutil
import sys
import threading
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Make the scripts/ root importable so `shared.*` resolves whether this tool is
# run standalone (python mp3_tools/m4b_metadata_editor.py) or imported by the launcher.
_SCRIPTS_ROOT = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ROOT))

from shared import metadata
from shared import paths
from shared import settings
from shared import subprocess_utils as sp
from shared import ui_theme
from shared.cancellation import ConversionCancelled, raise_if_cancelled

APP_TITLE = "M4B Metadata Editor"

# Auto-named output folder slug (v0.1.1): tags are written to COPIES delivered
# into Downloads/<SLUG>-N, never to the imported originals.
SLUG = paths.TOOL_SLUGS["m4b_metadata"]

# settings.json keys (input/cover dirs only remember the dialog's last location;
# the output folder is NOT persisted — it always resets to a fresh Downloads/<SLUG>-N).
KEY_INPUT_DIR = "m4b_metadata.input_dir"
KEY_COVER_DIR = "m4b_metadata.cover_dir"

# (friendly metadata key, Tk variable attribute, form label)
_FIELDS = [
    ("title", "var_title", "Title"),
    ("artist", "var_artist", "Author / Artist"),
    ("album", "var_album", "Album"),
    ("year", "var_year", "Year"),
    ("genre", "var_genre", "Genre"),
    ("comment", "var_comment", "Comment"),
    ("series", "var_series", "Series Name"),
    ("series_part", "var_series_part", "Series Part"),
]

# Series fields are preserve-by-default even on a normal Save: a pre-filled value
# left unchanged is never written back (it may have been read from a vendor/movement
# atom, and silently migrating it to the canonical atom is not what the user asked).
_SERIES_KEYS = {"series", "series_part"}


def _remembered_dir(key: str) -> Path:
    """Return the saved folder for ``key`` if it still exists, else the home dir."""
    val = settings.get(key)
    if val:
        p = Path(val)
        if p.exists():
            return p
    return Path.home()


class M4BMetadataEditorUI(ttk.Frame):
    """The M4B Metadata Editor as an embeddable frame.

    ``theme`` is the optional ``shared.ui_theme`` bundle. It is resolved from
    the platform when omitted, so every existing caller — including the
    launcher's ``module.build_ui(container)`` — keeps working unchanged. It
    exists so a developer-only fixture (or a future launcher) can hand the
    panel a bundle it already applied instead of re-resolving it.

    The presentation forks on ``theme["mode"]``: ``windows`` builds the v0.6.0
    card layout from the ``ACT.*`` design system; every other mode builds the
    historical layout byte-for-byte, so macOS aqua and Linux/other are
    untouched. Both forks create exactly the same widgets and attributes, so
    every callback, worker, cancel path and busy/idle transition below is
    shared and unaware of which one built the screen.
    """

    def __init__(self, parent: tk.Misc, theme: dict | None = None):
        if theme is None:
            theme = ui_theme.apply_theme(parent.winfo_toplevel(), ttk.Style(parent))
        windows = theme.get("mode") == "windows"
        if windows:
            super().__init__(parent, style=theme["styles"]["window"])
        else:
            super().__init__(parent)
        self.theme = theme
        self._windows = windows

        self.files: list[Path] = []

        # Cancellation / worker plumbing (mirrors the other MP3 tools' pattern).
        self._busy = threading.Event()
        self._cancel_event = threading.Event()
        self._log_q: queue.Queue = queue.Queue()

        # One Tk var per editable text field.
        for _key, attr, _label in _FIELDS:
            setattr(self, attr, tk.StringVar())
        self.var_cover_path = tk.StringVar()
        self.mode_var = tk.StringVar(value="No files loaded.")
        # Read-only "Detected on file" line for the series actually present on the
        # loaded file (and which atom it came from), so an overwrite can be trusted.
        self.series_readback_var = tk.StringVar(value="")

        # Auto-number Series Part. This toggle is the *sole* control over whether
        # anything is written to the series-part tag: OFF (default) writes nothing
        # to series-part (the field is display-only / preserve-by-default); ON uses
        # the Series Part field as the starting number and assigns sequential parts
        # across the loaded files in list order (single file → just that number).
        self.var_autonumber = tk.BooleanVar(value=False)
        self.autonumber_hint_var = tk.StringVar(value="")

        # Snapshot of the values auto-loaded into the form in single-file mode.
        # A "Clear All Tags" run re-applies only fields the user changed from
        # this snapshot, so unchanged pre-filled fields are genuinely wiped.
        self._prefill: dict[str, str] = {}

        # Cache of read_m4b_tags() per file (Drop 2). Keyed by Path; populated
        # lazily by _tags_for(); cleared whenever the file list changes.
        self._tag_cache: dict[Path, dict] = {}

        # Per-file chapter-title import (Phase D). Buffers are keyed by Path so
        # they survive paging and reordering; counts cache each file's chapter
        # count (ffprobe) so paging doesn't re-probe repeatedly.
        self._chap_page = 0
        self._chap_shown: Path | None = None  # path currently displayed in the box
        self._chap_buffers: dict[Path, str] = {}
        self._chap_counts: dict[Path, int] = {}
        self.chap_pager_var = tk.StringVar(value="No files loaded.")
        self.chap_hint_var = tk.StringVar(value="")

        # Output folder: a fresh Downloads/<SLUG>-N decided once now, at build
        # time. Browse redirects it for this run only; it is never persisted, so
        # the next launch starts at the next free -N. The folder is created
        # lazily on the first successful save.
        self.var_outdir = tk.StringVar(value=str(paths.next_output_dir(SLUG)))

        self._build_ui()

        # Start draining the worker->GUI queue on the main thread.
        self.after(150, self._pump_queue)

    # ----- UI -----
    def _build_ui(self):
        """Build the panel, then run the two state syncs both forks need."""
        if self._windows:
            self._build_ui_windows()
        else:
            self._build_ui_classic()
        self._update_chap_buttons()  # disabled until files are loaded
        self._update_autonumber_hint()  # set the initial (toggle-off) hint text

    def _build_ui_classic(self):
        """The pre-v0.6.0 layout. macOS and Linux/other must stay byte-identical."""
        # The tag/settings sections are taller than the launcher window once a
        # batch is loaded, so they live in a vertically scrollable canvas —
        # the same canvas_wrap + create_window + scrollregion/width-sync +
        # enable_mousewheel wiring as the TTS panel. The action buttons (row 1)
        # and the Log (row 2) sit OUTSIDE the canvas so they are always
        # visible, and the Log gets a fixed, larger height.
        self.rowconfigure(0, weight=1)   # scrollable settings grow with window
        self.rowconfigure(1, weight=0)   # action buttons — fixed, always visible
        self.rowconfigure(2, weight=0)   # log box — fixed height, always visible
        self.columnconfigure(0, weight=1)

        canvas_wrap = ttk.Frame(self)
        canvas_wrap.grid(row=0, column=0, sticky="nsew")
        canvas_wrap.rowconfigure(0, weight=1)
        canvas_wrap.columnconfigure(0, weight=1)
        settings_canvas = tk.Canvas(canvas_wrap, highlightthickness=0, borderwidth=0)
        settings_canvas.grid(row=0, column=0, sticky="nsew")
        settings_sb = ttk.Scrollbar(
            canvas_wrap, orient="vertical", command=settings_canvas.yview
        )
        settings_sb.grid(row=0, column=1, sticky="ns")
        settings_canvas.configure(yscrollcommand=settings_sb.set)

        body = ttk.Frame(settings_canvas)
        _body_window = settings_canvas.create_window((0, 0), window=body, anchor="nw")

        def _sync_scrollregion(_event=None):
            settings_canvas.configure(scrollregion=settings_canvas.bbox("all"))

        def _sync_body_width(event):
            # Make the body fill the canvas width so "fill=X" rows expand as before.
            settings_canvas.itemconfigure(_body_window, width=event.width)

        body.bind("<Configure>", _sync_scrollregion)
        settings_canvas.bind("<Configure>", _sync_body_width)

        # Wheel binding is scoped to while the pointer is over this panel (the
        # wrap frame, not the canvas — the body frame covers the canvas).
        ui_theme.enable_mousewheel(settings_canvas, hover_region=canvas_wrap)

        # Top: file actions
        top = ttk.Frame(body)
        top.pack(side=tk.TOP, fill=tk.X, padx=12, pady=(10, 6))
        self.btn_add = ttk.Button(top, text="Open M4B File(s)", command=self.add_files)
        self.btn_add.pack(side=tk.LEFT)
        self.btn_add_folder = ttk.Button(top, text="Open Folder…", command=self.add_folder)
        self.btn_add_folder.pack(side=tk.LEFT, padx=(8, 0))
        self.btn_remove = ttk.Button(top, text="Remove Selected", command=self.remove_selected)
        self.btn_remove.pack(side=tk.LEFT, padx=(8, 0))
        self.btn_clear = ttk.Button(top, text="Clear List", command=self.clear_list)
        self.btn_clear.pack(side=tk.LEFT, padx=(8, 0))
        self.lbl_mode = ttk.Label(top, textvariable=self.mode_var, foreground="#b45309")
        self.lbl_mode.pack(side=tk.RIGHT)

        # File list
        list_frame = ttk.LabelFrame(body, text="M4B Files")
        list_frame.pack(side=tk.TOP, fill=tk.X, padx=12, pady=(0, 6))
        self.listbox = tk.Listbox(list_frame, selectmode=tk.EXTENDED, height=5)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.configure(yscrollcommand=sb.set)

        # Metadata form
        form_box = ttk.LabelFrame(body, text="Tags (blank fields are left unchanged)")
        form_box.pack(side=tk.TOP, fill=tk.X, padx=12, pady=(0, 6))
        form = ttk.Frame(form_box)
        form.pack(fill=tk.X, padx=8, pady=8)
        form.columnconfigure(1, weight=1)

        self._field_widgets = []
        for r, (_key, attr, label) in enumerate(_FIELDS):
            ttk.Label(form, text=label + ":").grid(row=r, column=0, sticky="e", padx=5, pady=3)
            ent = ttk.Entry(form, textvariable=getattr(self, attr))
            ent.grid(row=r, column=1, sticky="we", padx=5, pady=3)
            self._field_widgets.append(ent)

        # Cover row
        cover_row = len(_FIELDS)
        ttk.Label(form, text="Cover image:").grid(
            row=cover_row, column=0, sticky="e", padx=5, pady=3
        )
        self.entry_cover = ttk.Entry(form, textvariable=self.var_cover_path)
        self.entry_cover.grid(row=cover_row, column=1, sticky="we", padx=5, pady=3)
        cover_btns = ttk.Frame(form)
        cover_btns.grid(row=cover_row, column=2, sticky="w", padx=4)
        self.btn_cover = ttk.Button(cover_btns, text="Browse…", command=self.choose_cover)
        self.btn_cover.pack(side=tk.LEFT)
        self.btn_cover_clear = ttk.Button(cover_btns, text="Clear", command=lambda: self.var_cover_path.set(""))
        self.btn_cover_clear.pack(side=tk.LEFT, padx=(6, 0))

        # Auto-number toggle, beside the Series Part entry. Ticking it turns the
        # Series Part field into the starting number and writes incrementing parts
        # across the loaded files; unticked, series-part is never written.
        sp_row = next(i for i, (k, _a, _l) in enumerate(_FIELDS) if k == "series_part")
        self.chk_autonumber = ttk.Checkbutton(
            form,
            text="Auto-number across files",
            variable=self.var_autonumber,
            command=self._update_autonumber_hint,
        )
        self.chk_autonumber.grid(row=sp_row, column=2, sticky="w", padx=4)
        self.var_series_part.trace_add("write", lambda *_: self._update_autonumber_hint())

        # Read-only read-back of the series detected on the loaded file (and its
        # source atom). Lets the user confirm the existing series before, and the
        # written series after, an overwrite. Single file only; cleared otherwise.
        self.lbl_series_readback = ttk.Label(
            form_box, textvariable=self.series_readback_var, foreground="#1e3a8a"
        )
        self.lbl_series_readback.pack(side=tk.TOP, anchor="w", padx=8, pady=(0, 2))

        # Live hint explaining exactly what the auto-number toggle will write.
        self.lbl_autonumber_hint = ttk.Label(
            form_box, textvariable=self.autonumber_hint_var, foreground="#6b7280"
        )
        self.lbl_autonumber_hint.pack(side=tk.TOP, anchor="w", padx=8, pady=(0, 8))

        # Chapter Titles (optional) — paged, one page per loaded file, applied
        # positionally (line N -> chapter N; blank line = leave that chapter).
        chap_box = ttk.LabelFrame(body, text="Chapter Titles (optional)")
        chap_box.pack(side=tk.TOP, fill=tk.BOTH, expand=False, padx=12, pady=(0, 6))
        pager = ttk.Frame(chap_box)
        pager.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(6, 2))
        self.btn_chap_prev = ttk.Button(pager, text="◀", width=3, command=self._chap_prev)
        self.btn_chap_prev.pack(side=tk.LEFT)
        ttk.Label(pager, textvariable=self.chap_pager_var).pack(side=tk.LEFT, padx=8)
        self.btn_chap_next = ttk.Button(pager, text="▶", width=3, command=self._chap_next)
        self.btn_chap_next.pack(side=tk.LEFT)
        ttk.Label(chap_box, textvariable=self.chap_hint_var, foreground="#6b7280").pack(
            side=tk.TOP, anchor="w", padx=8
        )
        self.chap_text = tk.Text(chap_box, height=6, wrap="none")
        self.chap_text.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=(2, 8))

        # Output folder row — tagged copies are delivered here; originals are
        # never touched. Last row of the scrollable body.
        outrow = ttk.Frame(body)
        outrow.pack(side=tk.TOP, fill=tk.X, padx=12, pady=(0, 6))
        ttk.Label(outrow, text="Output folder:").pack(side=tk.LEFT)
        self.entry_outdir = ttk.Entry(outrow, textvariable=self.var_outdir)
        self.entry_outdir.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 6))
        self.btn_browse_out = ttk.Button(outrow, text="Browse…", command=self.choose_outdir)
        self.btn_browse_out.pack(side=tk.LEFT)
        self.btn_open_out = ttk.Button(outrow, text="Open", command=self.open_outdir)
        self.btn_open_out.pack(side=tk.LEFT, padx=(6, 0))

        # Action buttons (row 1): always visible, outside the scroll area.
        action = ttk.Frame(self)
        action.grid(row=1, column=0, sticky="ew", padx=12, pady=(6, 6))
        self.btn_save = ttk.Button(action, text="Save Tags", command=self.save)
        self.btn_save.pack(side=tk.LEFT)
        self.btn_clear_tags = ttk.Button(
            action, text="Clear All Tags (keep chapters)", command=self.on_clear_all_tags
        )
        self.btn_clear_tags.pack(side=tk.LEFT, padx=(8, 0))
        self.btn_remove_numbering = ttk.Button(
            action, text="Remove Series Numbering", command=self.on_remove_series_numbering
        )
        self.btn_remove_numbering.pack(side=tk.LEFT, padx=(8, 0))
        self.btn_cancel = ttk.Button(action, text="Cancel", command=self.cancel, state=tk.DISABLED)
        self.btn_cancel.pack(side=tk.LEFT, padx=(8, 0))
        # Progress (bar + files-done/percentage label; updated only from the
        # main-thread queue pump)
        self.progress = ui_theme.ProgressIndicator(action, length=240)
        self.progress.frame.pack(side=tk.RIGHT)

        # Log (row 2): a fixed, larger pane that is always visible and never
        # crushed by the sections above (they scroll instead).
        logf = ttk.LabelFrame(self, text="Log")
        logf.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 10))
        self.log = tk.Text(logf, height=14, wrap="word", state=tk.DISABLED)
        self.log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb2 = ttk.Scrollbar(logf, orient="vertical", command=self.log.yview)
        sb2.pack(side=tk.RIGHT, fill=tk.Y)
        self.log.configure(yscrollcommand=sb2.set)

    # ----- Windows presentation (v0.6.0 Drop 1) -----
    @staticmethod
    def _wrap_with(label: ttk.Label, host: tk.Misc, slack: int):
        """Keep a caption's wraplength tied to its container's real width.

        A fixed wraplength would either clip or force the card wider than the
        window (a label's requested width propagates), which is exactly the
        kind of horizontal overflow this layout has to avoid at 920x600.
        """
        def _resize(event):
            width = max(160, event.width - slack)
            if abs(int(label.cget("wraplength") or 0) - width) > 4:
                label.configure(wraplength=width)
        host.bind("<Configure>", _resize, add="+")

    def _build_ui_windows(self):
        """The v0.6.0 Windows layout: titled cards on the dark shell.

        Same three-row skeleton as the classic build — scrollable body (row 0),
        always-visible action bar (row 1), always-visible Log (row 2) — so the
        scroll region, the scoped mouse-wheel wiring and the "primary actions
        never scroll away" contract are unchanged. Only the composition and the
        styling differ.

        Every colour, font, pad and style name comes from the theme bundle, so
        no hex literal or magic number is written here, and every style used is
        ``ACT.*``-namespaced — the five unconverted panels are untouched.
        """
        s = self.theme["styles"]
        m = self.theme["metrics"]
        f = self.theme["fonts"]

        self.rowconfigure(0, weight=1)   # scrollable settings grow with window
        self.rowconfigure(1, weight=0)   # action bar — fixed, always visible
        self.rowconfigure(2, weight=0)   # log — fixed height, always visible
        self.columnconfigure(0, weight=1)

        # --- scrollable body: identical wiring to the classic build ----------
        canvas_wrap = ttk.Frame(self, style=s["window"])
        canvas_wrap.grid(row=0, column=0, sticky="nsew")
        canvas_wrap.rowconfigure(0, weight=1)
        canvas_wrap.columnconfigure(0, weight=1)
        settings_canvas = tk.Canvas(canvas_wrap, highlightthickness=0, borderwidth=0)
        ui_theme.style_tk_widget(settings_canvas, self.theme, "window")
        settings_canvas.grid(row=0, column=0, sticky="nsew")
        settings_sb = ttk.Scrollbar(
            canvas_wrap, orient="vertical", style=s["vscrollbar"],
            command=settings_canvas.yview,
        )
        settings_sb.grid(row=0, column=1, sticky="ns")
        settings_canvas.configure(yscrollcommand=settings_sb.set)

        body = ttk.Frame(settings_canvas, style=s["window"],
                         padding=(m["gap_md"], m["gap_md"], m["gap_md"], 0))
        _body_window = settings_canvas.create_window((0, 0), window=body, anchor="nw")

        def _sync_scrollregion(_event=None):
            settings_canvas.configure(scrollregion=settings_canvas.bbox("all"))

        def _sync_body_width(event):
            settings_canvas.itemconfigure(_body_window, width=event.width)

        body.bind("<Configure>", _sync_scrollregion)
        settings_canvas.bind("<Configure>", _sync_body_width)
        ui_theme.enable_mousewheel(settings_canvas, hover_region=canvas_wrap)

        # --- card 1: the imported files --------------------------------------
        files_card = ttk.Labelframe(body, text="Audiobook Files",
                                    style=s["labelframe"])
        files_card.pack(side=tk.TOP, fill=tk.X, pady=(0, m["card_gap"]))

        file_actions = ttk.Frame(files_card, style=s["card"])
        file_actions.pack(fill=tk.X)
        self.btn_add = ttk.Button(file_actions, text="Open M4B File(s)",
                                  style=s["button"], command=self.add_files)
        self.btn_add.pack(side=tk.LEFT)
        self.btn_add_folder = ttk.Button(file_actions, text="Open Folder…",
                                         style=s["button"], command=self.add_folder)
        self.btn_add_folder.pack(side=tk.LEFT, padx=(m["gap_sm"], 0))
        self.btn_remove = ttk.Button(file_actions, text="Remove Selected",
                                     style=s["button"], command=self.remove_selected)
        self.btn_remove.pack(side=tk.LEFT, padx=(m["gap_sm"], 0))
        self.btn_clear = ttk.Button(file_actions, text="Clear List",
                                    style=s["button"], command=self.clear_list)
        self.btn_clear.pack(side=tk.LEFT, padx=(m["gap_sm"], 0))

        list_row = ttk.Frame(files_card, style=s["card"])
        list_row.pack(fill=tk.BOTH, expand=True, pady=(m["gap_sm"], 0))
        self.listbox = tk.Listbox(list_row, selectmode=tk.EXTENDED, height=5,
                                  font=f["row"], activestyle="none")
        ui_theme.style_tk_widget(self.listbox, self.theme, "list")
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(list_row, orient="vertical", style=s["vscrollbar"],
                           command=self.listbox.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.configure(yscrollcommand=sb.set)

        # --- card 2: Shared Metadata -----------------------------------------
        # The drop's distinct batch-wide surface: muted accent fill, accent
        # border, accent header (ACT.Shared.TLabelframe). Every field in here is
        # written to *every* loaded file — which is exactly what the existing
        # shared-value / "(varies)" detection already reports, so the grouping
        # is a visual statement of behaviour that already exists. It adds no
        # precedence, no per-book override and disables nothing (Plan 6/8).
        shared_card = ttk.Labelframe(body, text="Shared Metadata",
                                     style=s["shared_labelframe"])
        shared_card.pack(side=tk.TOP, fill=tk.X, pady=(0, m["card_gap"]))

        caption = ttk.Label(
            shared_card, style=s["shared_secondary"], justify="left",
            text=("These values are written to every loaded file. Blank fields are "
                  "left unchanged."),
        )
        caption.pack(anchor="w")
        self._wrap_with(caption, shared_card, m["card_pad"] * 2)

        # The existing mode/"(varies)" notice lives here: it reports which
        # shared fields were pre-filled and which differ across the batch.
        self.lbl_mode = ttk.Label(shared_card, textvariable=self.mode_var,
                                  style=s["shared_secondary"], justify="left")
        self.lbl_mode.pack(anchor="w", pady=(m["gap_xs"], m["gap_md"]))
        self._wrap_with(self.lbl_mode, shared_card, m["card_pad"] * 2)

        form = ttk.Frame(shared_card, style=s["shared_surface"])
        form.pack(fill=tk.X)
        # Equal weights so the one two-up row (Year | Genre) splits evenly; the
        # full-width fields span both and are unaffected.
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)

        attr_by_key = {key: attr for key, attr, _label in _FIELDS}
        label_by_key = {key: label for key, _attr, label in _FIELDS}
        entry_by_key: dict[str, ttk.Entry] = {}

        def _field(key: str, row: int, col: int, span: int, **grid):
            ttk.Label(form, text=label_by_key[key], style=s["shared_label"]).grid(
                row=row, column=col, sticky="w",
                padx=(0, m["gap_sm"]), pady=m["gap_xs"],
            )
            ent = ttk.Entry(form, textvariable=getattr(self, attr_by_key[key]),
                            style=s["entry"])
            ent.grid(row=row, column=col + 1, columnspan=span, sticky="we",
                     padx=(0, m["gap_md"]), pady=m["gap_xs"], **grid)
            entry_by_key[key] = ent
            return ent

        _field("title", 0, 0, 3)
        _field("artist", 1, 0, 3)
        _field("album", 2, 0, 3)
        _field("year", 3, 0, 1)
        _field("genre", 3, 2, 1)
        _field("comment", 4, 0, 3)

        # Cover row.
        ttk.Label(form, text="Cover image", style=s["shared_label"]).grid(
            row=5, column=0, sticky="w", padx=(0, m["gap_sm"]), pady=m["gap_xs"])
        self.entry_cover = ttk.Entry(form, textvariable=self.var_cover_path,
                                     style=s["entry"])
        self.entry_cover.grid(row=5, column=1, columnspan=2, sticky="we",
                              padx=(0, m["gap_sm"]), pady=m["gap_xs"])
        cover_btns = ttk.Frame(form, style=s["shared_surface"])
        cover_btns.grid(row=5, column=3, sticky="w")
        self.btn_cover = ttk.Button(cover_btns, text="Browse…", style=s["button"],
                                    command=self.choose_cover)
        self.btn_cover.pack(side=tk.LEFT)
        self.btn_cover_clear = ttk.Button(
            cover_btns, text="Clear", style=s["button"],
            command=lambda: self.var_cover_path.set(""),
        )
        self.btn_cover_clear.pack(side=tk.LEFT, padx=(m["gap_sm"], 0))

        # Series sub-group, inside the same shared surface.
        ttk.Frame(shared_card, style=s["divider"], height=1).pack(
            fill=tk.X, pady=(m["gap_md"], m["gap_md"]))
        ttk.Label(shared_card, text="Series", style=s["shared_header"]).pack(anchor="w")

        series = ttk.Frame(shared_card, style=s["shared_surface"])
        series.pack(fill=tk.X, pady=(m["gap_sm"], 0))
        series.columnconfigure(1, weight=1)

        ttk.Label(series, text=label_by_key["series"], style=s["shared_label"]).grid(
            row=0, column=0, sticky="w", padx=(0, m["gap_sm"]), pady=m["gap_xs"])
        entry_by_key["series"] = ttk.Entry(series, textvariable=self.var_series,
                                           style=s["entry"])
        entry_by_key["series"].grid(row=0, column=1, columnspan=2, sticky="we",
                                    pady=m["gap_xs"])

        ttk.Label(series, text=label_by_key["series_part"],
                  style=s["shared_label"]).grid(
            row=1, column=0, sticky="w", padx=(0, m["gap_sm"]), pady=m["gap_xs"])
        entry_by_key["series_part"] = ttk.Entry(
            series, textvariable=self.var_series_part, style=s["entry"], width=10)
        entry_by_key["series_part"].grid(row=1, column=1, sticky="w",
                                         pady=m["gap_xs"])
        self.chk_autonumber = ttk.Checkbutton(
            series, text="Auto-number across files", variable=self.var_autonumber,
            style=s["shared_checkbutton"], command=self._update_autonumber_hint,
        )
        self.chk_autonumber.grid(row=1, column=2, sticky="w", padx=(m["gap_md"], 0))

        # Field widgets in _FIELDS order — disable_inputs() and the busy state
        # walk this list, so the order stays the historical one.
        self._field_widgets = [entry_by_key[key] for key, _attr, _label in _FIELDS]
        self.var_series_part.trace_add(
            "write", lambda *_: self._update_autonumber_hint())

        self.lbl_series_readback = ttk.Label(
            shared_card, textvariable=self.series_readback_var,
            style=s["shared_secondary"], justify="left",
        )
        self.lbl_series_readback.pack(anchor="w", pady=(m["gap_md"], 0))
        self._wrap_with(self.lbl_series_readback, shared_card, m["card_pad"] * 2)

        self.lbl_autonumber_hint = ttk.Label(
            shared_card, textvariable=self.autonumber_hint_var,
            style=s["shared_secondary"], justify="left",
        )
        self.lbl_autonumber_hint.pack(anchor="w", pady=(m["gap_xs"], 0))
        self._wrap_with(self.lbl_autonumber_hint, shared_card, m["card_pad"] * 2)

        # --- card 3: chapter titles ------------------------------------------
        chap_card = ttk.Labelframe(body, text="Chapter Titles (optional)",
                                   style=s["labelframe"])
        chap_card.pack(side=tk.TOP, fill=tk.BOTH, expand=False,
                       pady=(0, m["card_gap"]))
        pager = ttk.Frame(chap_card, style=s["card"])
        pager.pack(fill=tk.X)
        self.btn_chap_prev = ttk.Button(pager, text="◀", width=3,
                                        style=s["button"], command=self._chap_prev)
        self.btn_chap_prev.pack(side=tk.LEFT)
        ttk.Label(pager, textvariable=self.chap_pager_var, style=s["label"]).pack(
            side=tk.LEFT, padx=m["gap_sm"])
        self.btn_chap_next = ttk.Button(pager, text="▶", width=3,
                                        style=s["button"], command=self._chap_next)
        self.btn_chap_next.pack(side=tk.LEFT)
        self.lbl_chap_hint = ttk.Label(chap_card, textvariable=self.chap_hint_var,
                                       style=s["secondary_label"], justify="left")
        self.lbl_chap_hint.pack(anchor="w", pady=(m["gap_sm"], 0))
        self._wrap_with(self.lbl_chap_hint, chap_card, m["card_pad"] * 2)
        self.chap_text = tk.Text(chap_card, height=6, wrap="none", font=f["mono"])
        ui_theme.style_tk_widget(self.chap_text, self.theme, "text")
        self.chap_text.pack(fill=tk.BOTH, expand=True, pady=(m["gap_sm"], 0))

        # --- card 4: output ---------------------------------------------------
        out_card = ttk.Labelframe(body, text="Output", style=s["labelframe"])
        out_card.pack(side=tk.TOP, fill=tk.X, pady=(0, m["card_gap"]))
        outrow = ttk.Frame(out_card, style=s["card"])
        outrow.pack(fill=tk.X)
        ttk.Label(outrow, text="Folder", style=s["label"]).pack(side=tk.LEFT)
        self.entry_outdir = ttk.Entry(outrow, textvariable=self.var_outdir,
                                      style=s["entry"])
        self.entry_outdir.pack(side=tk.LEFT, fill=tk.X, expand=True,
                               padx=(m["gap_sm"], m["gap_sm"]))
        self.btn_browse_out = ttk.Button(outrow, text="Browse…", style=s["button"],
                                         command=self.choose_outdir)
        self.btn_browse_out.pack(side=tk.LEFT)
        self.btn_open_out = ttk.Button(outrow, text="Open", style=s["button"],
                                       command=self.open_outdir)
        self.btn_open_out.pack(side=tk.LEFT, padx=(m["gap_sm"], 0))
        out_note = ttk.Label(
            out_card, style=s["secondary_label"], justify="left",
            text=("Tagged copies are written here. The files you import are never "
                  "modified."),
        )
        out_note.pack(anchor="w", pady=(m["gap_sm"], 0))
        self._wrap_with(out_note, out_card, m["card_pad"] * 2)

        # --- row 1: action bar (never scrolls away) ---------------------------
        # Progress sits on its own full-width line above the buttons so it can
        # never be pushed off the right edge at the 920x600 minimum.
        action = ttk.Frame(self, style=s["window"],
                           padding=(m["gap_md"], m["gap_sm"]))
        action.grid(row=1, column=0, sticky="ew")
        self.progress = ui_theme.ProgressIndicator(action, length=240)
        # Per-instance restyling only: ProgressIndicator itself stays generic,
        # because five unconverted panels build their own from the same class.
        self.progress.frame.configure(style=s["window"])
        self.progress.bar.configure(style=s["progressbar"])
        self.progress.label.configure(style=s["status_label"])
        # Natural width, left-aligned: a full-width trough reads as an empty box
        # when the panel is idle, which is most of the time.
        self.progress.frame.pack(anchor="w", pady=(0, m["gap_sm"]))

        buttons = ttk.Frame(action, style=s["window"])
        buttons.pack(fill=tk.X)
        self.btn_save = ttk.Button(buttons, text="Save Tags",
                                   style=s["primary_button"], command=self.save)
        self.btn_save.pack(side=tk.LEFT)
        self.btn_clear_tags = ttk.Button(
            buttons, text="Clear All Tags (keep chapters)", style=s["danger_button"],
            command=self.on_clear_all_tags,
        )
        self.btn_clear_tags.pack(side=tk.LEFT, padx=(m["gap_sm"], 0))
        self.btn_remove_numbering = ttk.Button(
            buttons, text="Remove Series Numbering", style=s["danger_button"],
            command=self.on_remove_series_numbering,
        )
        self.btn_remove_numbering.pack(side=tk.LEFT, padx=(m["gap_sm"], 0))
        self.btn_cancel = ttk.Button(buttons, text="Cancel", style=s["button"],
                                     command=self.cancel, state=tk.DISABLED)
        self.btn_cancel.pack(side=tk.RIGHT)

        # --- row 2: log (never scrolls away) ----------------------------------
        logf = ttk.Labelframe(self, text="Log", style=s["labelframe"])
        logf.grid(row=2, column=0, sticky="nsew",
                  padx=m["gap_md"], pady=(0, m["gap_md"]))
        log_row = ttk.Frame(logf, style=s["card"])
        log_row.pack(fill=tk.BOTH, expand=True)
        self.log = tk.Text(log_row, height=8, wrap="word", state=tk.DISABLED,
                           font=f["mono"])
        ui_theme.style_tk_widget(self.log, self.theme, "log")
        self.log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb2 = ttk.Scrollbar(log_row, orient="vertical", style=s["vscrollbar"],
                            command=self.log.yview)
        sb2.pack(side=tk.RIGHT, fill=tk.Y)
        self.log.configure(yscrollcommand=sb2.set)

    # ----- file actions -----
    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="Select M4B file(s)",
            initialdir=str(_remembered_dir(KEY_INPUT_DIR)),
            filetypes=[("M4B Audiobooks", "*.m4b"), ("MP4 audio", "*.m4a *.mp4"), ("All files", "*.*")],
        )
        if not paths:
            return
        for f in paths:
            p = Path(f)
            if p not in self.files:
                self.files.append(p)
                self.listbox.insert(tk.END, str(p))
        settings.set(KEY_INPUT_DIR, str(Path(paths[0]).parent))
        self._refresh_mode()

    def add_folder(self):
        """Load every M4B/M4A/MP4 directly inside a chosen folder (non-recursive)."""
        d = filedialog.askdirectory(
            title="Select a folder of M4B files",
            initialdir=str(_remembered_dir(KEY_INPUT_DIR)),
        )
        if not d:
            return
        folder = Path(d)
        found = sorted(
            p for p in folder.iterdir()
            if p.is_file() and p.suffix.lower() in {".m4b", ".m4a", ".mp4"}
        )
        if not found:
            messagebox.showinfo(
                "No audiobooks found",
                f"No .m4b / .m4a / .mp4 files were found directly in:\n{folder}\n\n"
                "Subfolders are not searched — if the books sit inside a subfolder, "
                "pick that subfolder instead.",
            )
            return
        for p in found:
            if p not in self.files:
                self.files.append(p)
                self.listbox.insert(tk.END, str(p))
        settings.set(KEY_INPUT_DIR, str(folder))
        self._refresh_mode()

    def remove_selected(self):
        sel = list(self.listbox.curselection())
        for idx in reversed(sel):
            del self.files[idx]
            self.listbox.delete(idx)
        self._tag_cache.clear()
        self._refresh_mode()

    def clear_list(self):
        self.files.clear()
        self._tag_cache.clear()
        self.listbox.delete(0, tk.END)
        self._chap_buffers.clear()
        self._chap_counts.clear()
        self._chap_shown = None
        self._refresh_mode()

    def _clear_fields(self):
        for _key, attr, _label in _FIELDS:
            getattr(self, attr).set("")
        self.var_cover_path.set("")
        self.series_readback_var.set("")
        self._prefill = {}

    @staticmethod
    def _series_readback_text(tags: dict) -> str:
        """Build the "Detected on file" line from read_m4b_tags() results.

        Four cases (see Phase 3): a full series (real name [+ part]); a part with
        no real name but an album Audiobookshelf likely groups by; a part with no
        name and no album; or nothing at all. An ``"album-implied"`` name is *not*
        a real name — it is shown as the album-grouping hint, not as the series.
        """
        series = (tags.get("series") or "").strip()
        part = (tags.get("series_part") or "").strip()
        album = (tags.get("album") or "").strip()
        name_implied = tags.get("series_source") == "album-implied"
        has_real_name = bool(series) and not name_implied

        if not series and not part:
            return "Detected on file: none — this file has no series tag"

        if part and not has_real_name:
            # Part with no real series name (the name is at most album-implied).
            atom = tags.get("series_part_atom") or tags.get("series_part_source") or "?"
            if album:
                return (
                    f"Detected on file: part #{part} only — no series name on file; "
                    f"Audiobookshelf likely groups by Album: '{album}'  (source: {atom})"
                )
            return f"Detected on file: part #{part} only — no series name  (source: {atom})"

        # Real series name (with or without a part).
        shown = series + (f" #{part}" if part else "")
        atom = (
            tags.get("series_atom")
            or tags.get("series_part_atom")
            or tags.get("series_source")
            or tags.get("series_part_source")
            or "?"
        )
        return f"Detected on file: {shown}  (source: {atom})"

    def _refresh_mode(self):
        """Update the mode notice and (single-file) pre-fill from the file's tags."""
        n = len(self.files)
        if n == 0:
            self._clear_fields()
            self.mode_var.set("No files loaded.")
        elif n == 1:
            self.mode_var.set("Single file — fields pre-filled from existing tags.")
            self._prefill_from(self.files[0])
        else:
            self._prefill_shared(n)
        self._sync_chapter_pager()
        self._update_autonumber_hint()

    # ----- chapter-title pager -----
    def _chap_count(self, path: Path) -> int:
        if path not in self._chap_counts:
            try:
                self._chap_counts[path] = len(metadata.read_chapter_titles(path))
            except Exception:
                self._chap_counts[path] = 0
        return self._chap_counts[path]

    def _flush_chapter_page(self):
        """Save the visible text into the buffer for the file it belongs to."""
        if self._chap_shown is not None:
            self._chap_buffers[self._chap_shown] = self.chap_text.get("1.0", "end-1c")

    def _show_chapter_page(self, idx: int):
        self._flush_chapter_page()
        self.chap_text.delete("1.0", tk.END)
        if not self.files:
            self._chap_page = 0
            self._chap_shown = None
            self.chap_pager_var.set("No files loaded.")
            self.chap_hint_var.set("")
            self._update_chap_buttons()
            return
        idx = max(0, min(idx, len(self.files) - 1))
        self._chap_page = idx
        path = self.files[idx]
        self._chap_shown = path
        self.chap_text.insert("1.0", self._chap_buffers.get(path, ""))
        self.chap_pager_var.set(f"File {idx + 1} of {len(self.files)}: {path.name}")
        k = self._chap_count(path)
        self.chap_hint_var.set(
            f"This file has {k} chapters. Paste up to {k} titles, one per line; "
            "a blank line leaves that chapter's title unchanged."
        )
        self._update_chap_buttons()

    def _update_chap_buttons(self):
        n = len(self.files)
        self.btn_chap_prev.configure(state=tk.NORMAL if self._chap_page > 0 else tk.DISABLED)
        self.btn_chap_next.configure(
            state=tk.NORMAL if self._chap_page < n - 1 else tk.DISABLED
        )

    def _chap_prev(self):
        self._show_chapter_page(self._chap_page - 1)

    def _chap_next(self):
        self._show_chapter_page(self._chap_page + 1)

    def _sync_chapter_pager(self):
        """Refresh the pager after the file list changed (clamp the page)."""
        if self._chap_page >= len(self.files):
            self._chap_page = max(0, len(self.files) - 1)
        self._show_chapter_page(self._chap_page)

    def _prefill_from(self, path: Path):
        self._clear_fields()
        try:
            tags = metadata.read_m4b_tags(path)
        except Exception as e:
            self.log_write(f"Could not read tags from {path.name}: {e}\n")
            return
        # An album-implied series *name* is display-only: leave the Series Name
        # field blank so an unedited Save writes nothing (preserve-by-default).
        # The Series Part is still populated independently — a part-only file must
        # show its part number even when the name is blank.
        name_implied = tags.get("series_source") == "album-implied"
        for key, attr, _label in _FIELDS:
            if key == "series" and name_implied:
                continue
            if key in tags:
                getattr(self, attr).set(str(tags[key]))
                self._prefill[key] = str(tags[key])
        self.series_readback_var.set(self._series_readback_text(tags))
        if tags.get("has_cover"):
            self.log_write(f"{path.name}: existing cover present (leave Cover blank to keep it).\n")

    def _tags_for(self, path: Path) -> dict | None:
        """Return read_m4b_tags(path), cached. None (logged) if the read fails."""
        if path in self._tag_cache:
            return self._tag_cache[path]
        try:
            tags = metadata.read_m4b_tags(path)
        except Exception as e:  # corrupt / locked file — skip, don't abort the load
            self.log_write(f"Could not read tags from {path.name}: {e}\n")
            self._tag_cache[path] = None
            return None
        self._tag_cache[path] = tags
        return tags

    def _shared_tags(self) -> tuple[dict, set[str]]:
        """Compute values identical across ALL readable loaded files.

        Returns (shared, varies): `shared` maps friendly key -> the common value
        for every editable text field present-and-equal in every readable file;
        `varies` is the set of editable keys that appear on some files but are not
        identical across all of them (used to show a "(varies)" hint).

        A key is shared only when EVERY readable file has it and all values match
        after .strip(). album-implied series names and track-implied parts are
        excluded (display-only, never written).
        """
        readable = [t for p in self.files if (t := self._tags_for(p)) is not None]
        shared: dict = {}
        varies: set[str] = set()
        if not readable:
            return shared, varies
        for key, _attr, _label in _FIELDS:
            # series_part is display-only here (owned by the auto-number toggle);
            # it is summarised in the read-back, never pre-filled for writing.
            if key == "series_part":
                continue
            vals = []
            missing = False
            for t in readable:
                # album-implied series name is display-only -> treat as absent.
                if key == "series" and t.get("series_source") == "album-implied":
                    missing = True
                    break
                if key in t and str(t[key]).strip():
                    vals.append(str(t[key]).strip())
                else:
                    missing = True
                    break
            if missing or not vals:
                # It appears on *some* files but not identically on all -> "(varies)".
                if any(key in t for t in readable):
                    varies.add(key)
                continue
            if len(set(vals)) == 1:
                shared[key] = vals[0]
            else:
                varies.add(key)
        return shared, varies

    def _prefill_shared(self, n: int):
        """Batch mode: pre-fill fields whose value is identical across all files.

        Shared values are snapshotted into self._prefill, so an unedited shared
        Series Name is not written back (preserve-by-default via _SERIES_KEYS,
        same as single-file mode). Shared NON-series fields left unedited ARE
        written on Save — a byte-identical rewrite, matching the existing batch
        rule that any non-blank field overwrites (maintainer ruling, Drop 2).
        Fields that differ across files are left blank and named in the
        mode/read-back hints as "(varies)".
        """
        self._clear_fields()
        shared, varies = self._shared_tags()
        label_by_key = {k: lbl for k, _a, lbl in _FIELDS}
        for key, attr, _label in _FIELDS:
            if key in shared:
                getattr(self, attr).set(shared[key])
                self._prefill[key] = shared[key]
        shared_names = ", ".join(label_by_key[k] for k in shared) or "none"
        self.mode_var.set(
            f"Batch mode: {n} files — shared fields pre-filled ({shared_names}); "
            "blank fields are left unchanged."
        )
        self.series_readback_var.set(self._batch_series_readback(shared, varies))

    def _batch_series_readback(self, shared: dict, varies: set) -> str:
        """One-line series summary for batch mode."""
        if "series" in shared:
            return f"Detected across all files: Series '{shared['series']}' (identical)"
        if "series" in varies:
            return "Detected across files: Series name varies — left blank"
        return "Detected across files: no shared series name"

    # ----- cover -----
    def choose_cover(self):
        p = filedialog.askopenfilename(
            title="Select Cover Image (JPG/PNG)",
            initialdir=str(_remembered_dir(KEY_COVER_DIR)),
            filetypes=[("Image", "*.jpg *.jpeg *.png"), ("All files", "*.*")],
        )
        if not p:
            return
        settings.set(KEY_COVER_DIR, str(Path(p).parent))
        self.var_cover_path.set(p)

    # ----- output folder -----
    def choose_outdir(self):
        cur = self.var_outdir.get().strip()
        initial = cur if cur and Path(cur).parent.exists() else str(paths.downloads_dir())
        d = filedialog.askdirectory(title="Choose output folder", initialdir=initial)
        if d:
            self.var_outdir.set(d)

    def output_dir(self) -> Path:
        val = self.var_outdir.get().strip()
        return Path(val) if val else paths.next_output_dir(SLUG)

    def open_outdir(self):
        out = self.output_dir()
        out.mkdir(parents=True, exist_ok=True)
        sp.reveal_in_file_manager(out)

    # ----- logging -----
    def log_write(self, text: str):
        self.log.config(state=tk.NORMAL)
        self.log.insert(tk.END, text)
        self.log.see(tk.END)
        self.log.config(state=tk.DISABLED)

    def _autonumber_start(self) -> tuple[int | None, bool]:
        """Parse the Series Part field as the auto-number start.

        Returns ``(start, ok)``: a blank field starts at ``(1, True)``; a whole
        number gives ``(n, True)``; anything else is ``(None, False)``.
        """
        raw = self.var_series_part.get().strip()
        if not raw:
            return 1, True
        try:
            return int(raw), True
        except ValueError:
            return None, False

    def _update_autonumber_hint(self):
        """Refresh the live hint describing what the auto-number toggle will write."""
        n = len(self.files)
        if not self.var_autonumber.get():
            self.autonumber_hint_var.set(
                "Series Part is not written. Tick “Auto-number” to write part "
                "numbers to the series-part tag."
            )
            return
        start, ok = self._autonumber_start()
        if not ok:
            self.autonumber_hint_var.set(
                "Auto-number on: enter a whole number in Series Part (or leave it blank "
                "to start at 1)."
            )
        elif n <= 1:
            self.autonumber_hint_var.set(
                f"Auto-number on: Series Part #{start} will be written."
            )
        else:
            self.autonumber_hint_var.set(
                f"Auto-number on: Series Parts #{start}–#{start + n - 1} will be "
                f"written across the {n} files, in list order."
            )

    # ----- collect non-blank fields -----
    def _collect_tags(self, *, only_edited: bool = False) -> dict:
        """Collect the non-blank tag fields shared by every file.

        With ``only_edited`` (used by Clear All Tags), a field that still holds
        the value auto-loaded from the file in single-file mode is skipped, so
        the clear genuinely wipes it; only fields the user changed are re-applied.

        ``series_part`` is deliberately NOT collected here — it is governed solely
        by the auto-number toggle and injected per-file in the worker.
        """
        tags: dict = {}
        for key, attr, _label in _FIELDS:
            if key == "series_part":
                continue  # owned by the auto-number toggle (see _save_worker)
            val = getattr(self, attr).get().strip()
            if not val:
                continue
            # Series name is preserve-by-default even on a normal Save: an unchanged
            # pre-filled name is not written back, so a value read from a vendor/
            # movement atom (or an album-implied value) is never silently migrated to
            # the canonical atom unless the user actually edits it.
            skip_unchanged = only_edited or key in _SERIES_KEYS
            if skip_unchanged and val == (self._prefill.get(key, "")).strip():
                continue
            tags[key] = val
        cover = self.var_cover_path.get().strip()
        if cover:
            tags["cover_path"] = cover
        return tags

    # ----- save / clear -----
    def save(self):
        """Write the typed tag fields onto a copy of each file (preserve-by-default)."""
        self._start_job(clear_first=False)

    def on_clear_all_tags(self):
        """Strip all metadata (keep chapters) on a copy of each file, then apply
        any typed tag fields on top of the cleared copy."""
        if not self._busy.is_set() and self.files:
            if not messagebox.askyesno(
                "Clear all tags?",
                "This writes COPIES with ALL metadata removed (title, author, "
                "album, year, genre, comment, series, cover art).\n\n"
                "Chapter markers and titles are kept. The imported originals are "
                "not modified. Any tag fields you have typed will be re-applied "
                "on top of the cleared copies.\n\nProceed?",
            ):
                return
        # The output copies will have no series tag; clear the read-back so it
        # doesn't keep advertising the (now-irrelevant) source file's series.
        self.series_readback_var.set("")
        self._start_job(clear_first=True)

    def on_remove_series_numbering(self):
        """Strip all series/track numbering (trkn, freeform series atoms, and
        movement atoms) on a COPY of each loaded file, keeping chapters and every
        other tag. Mirrors the Clear All Tags wiring (copy-based, worker thread,
        Cancel, per-file log) but targets only the numbering surfaces."""
        if self._busy.is_set():
            return
        if not self.files:
            messagebox.showerror("No files", "Open one or more M4B files first.")
            return
        if not messagebox.askyesno(
            "Remove series numbering?",
            "This writes COPIES with all series/track numbering removed: the "
            "track number (Explorer's # column), the Series Name / Series Part, "
            "and the movement atoms — across every tagger namespace.\n\n"
            "Chapter markers and titles, cover art, and all other tags are kept. "
            "The imported originals are not modified.\n\nProceed?",
        ):
            return

        files = list(self.files)
        outdir = self.output_dir()  # read Tk var on the main thread
        self.series_readback_var.set("")
        self._busy.set()
        self._cancel_event.clear()
        self.progress.update(0, len(files))
        self.disable_inputs(True)
        self.btn_cancel.configure(state=tk.NORMAL)
        self.log_write(
            f"\nRemoving series numbering on {len(files)} copy(ies) in {outdir}…\n"
        )
        t = threading.Thread(
            target=self._remove_numbering_worker, args=(files, outdir), daemon=True
        )
        t.start()

    def _start_job(self, *, clear_first: bool):
        if self._busy.is_set():
            return
        if not self.files:
            messagebox.showerror("No files", "Open one or more M4B files first.")
            return

        tags = self._collect_tags(only_edited=clear_first)

        # Auto-number Series Part (read on the main thread). When on, validate the
        # starting number now so we fail fast with a clear message.
        autonumber = bool(self.var_autonumber.get())
        start_part = 1
        if autonumber:
            start_part, ok = self._autonumber_start()
            if not ok:
                messagebox.showerror(
                    "Series Part not a number",
                    "Auto-number Series Part is on, but the Series Part field is not "
                    "a whole number.\n\nEnter a starting number, or clear the field to "
                    "start at 1.",
                )
                return

        # Per-file chapter-title lists (parsed from the paged buffers). Flush the
        # visible page first so the current edits are captured.
        self._flush_chapter_page()
        chapter_map: dict[str, list[str]] = {}
        for p, buf in self._chap_buffers.items():
            if buf.strip():
                chapter_map[str(p)] = buf.splitlines()

        if not tags and not clear_first and not chapter_map and not autonumber:
            messagebox.showinfo(
                "Nothing to write",
                "No tag fields, no clear request, no chapter titles, and auto-number "
                "off — nothing to change.",
            )
            return

        cover = tags.get("cover_path")
        if cover and not Path(cover).exists():
            messagebox.showerror("Cover not found", f"Cover image not found:\n{cover}")
            return

        files = list(self.files)
        outdir = self.output_dir()  # read Tk var on the main thread
        self._busy.set()
        self._cancel_event.clear()
        self.progress.update(0, len(files))
        self.disable_inputs(True)
        self.btn_cancel.configure(state=tk.NORMAL)
        verb = "Clearing tags on" if clear_first else "Writing tags to"
        self.log_write(f"\n{verb} {len(files)} copy(ies) in {outdir}…\n")
        if autonumber:
            self.log_write(f"Auto-numbering Series Part from #{start_part} (list order).\n")

        t = threading.Thread(
            target=self._save_worker,
            args=(files, tags, outdir, clear_first, chapter_map, autonumber, start_part),
            daemon=True,
        )
        t.start()

    def cancel(self):
        if not self._busy.is_set() or self._cancel_event.is_set():
            return
        self._cancel_event.set()
        self.btn_cancel.configure(state=tk.DISABLED)
        self._log_q.put(("log", "Cancelling… will stop after the current file.\n"))

    def disable_inputs(self, state: bool):
        widgets = [
            self.btn_add,
            self.btn_add_folder,
            self.btn_remove,
            self.btn_clear,
            self.btn_save,
            self.btn_clear_tags,
            self.btn_remove_numbering,
            self.btn_cover,
            self.btn_cover_clear,
            self.entry_cover,
            self.entry_outdir,
            self.btn_browse_out,
            self.chap_text,
            self.btn_chap_prev,
            self.btn_chap_next,
            self.chk_autonumber,
            *self._field_widgets,
        ]
        for w in widgets:
            w.configure(state=tk.DISABLED if state else tk.NORMAL)
        if not state:
            # Restore the pager arrows to their correct page-bounded state.
            self._update_chap_buttons()

    # ----- worker -> GUI queue pump (main thread) -----
    def _pump_queue(self):
        try:
            while True:
                kind, payload = self._log_q.get_nowait()
                if kind == "log":
                    self.log_write(payload)
                elif kind == "progress":
                    self.progress.update(*payload)
                elif kind == "done":
                    ok, fail, cancelled = payload
                    self._finish_idle()
                    if cancelled:
                        self.log_write(f"Cancelled. {ok} saved, {fail} failed.\n")
                    else:
                        self.log_write(f"Done. {ok} saved, {fail} failed.\n")
                        if fail == 0:
                            messagebox.showinfo("Saved", f"Tags written to {ok} file(s).")
                        else:
                            messagebox.showwarning(
                                "Completed with errors",
                                f"{ok} file(s) saved, {fail} failed. See the log for details.",
                            )
        except queue.Empty:
            pass
        self.after(150, self._pump_queue)

    def _finish_idle(self):
        self._busy.clear()
        self._cancel_event.clear()
        self.disable_inputs(False)
        self.btn_cancel.configure(state=tk.DISABLED)

    # ----- save worker (worker thread) -----
    def _save_worker(
        self,
        files: list,
        tags: dict,
        outdir: Path,
        clear_first: bool,
        chapter_map: dict,
        autonumber: bool,
        start_part: int,
    ):
        cancel_check = self._cancel_event.is_set
        total = len(files)
        ok = 0
        fail = 0
        cancelled = False
        try:
            outdir.mkdir(parents=True, exist_ok=True)  # lazy create on first save
            for idx, f in enumerate(files, start=1):
                raise_if_cancelled(cancel_check)
                try:
                    # Per-file order (Phase B/C/D): copy original → output folder,
                    # then (optionally) clear all metadata keeping chapters, then
                    # re-apply any typed tag fields, then apply imported chapter
                    # titles positionally. Only the COPY is ever written; the
                    # imported original is read-only.
                    dest = paths.avoid_input_overwrite(outdir / f.name, files)
                    shutil.copy2(f, dest)
                    self._log_q.put(("log", f"[{idx}/{total}] Copied {f.name} → {dest}\n"))
                    if clear_first:
                        metadata.clear_metadata_keep_chapters(dest)
                        self._log_q.put(
                            ("log", f"[{idx}/{total}] Cleared all tags (kept chapters)\n")
                        )
                    # Shared text/series-name fields, plus the auto-numbered Series
                    # Part for this file's position (when the toggle is on).
                    file_tags = dict(tags)
                    if autonumber:
                        file_tags["series_part"] = str(start_part + (idx - 1))
                    if file_tags:
                        metadata.write_m4b_tags(dest, file_tags, total=total)
                        msg = f"[{idx}/{total}] Applied typed tag fields"
                        if autonumber:
                            msg += f" (Series Part #{file_tags['series_part']})"
                        self._log_q.put(("log", msg + "\n"))
                    titles = chapter_map.get(str(f))
                    if titles:
                        metadata.apply_chapter_titles(dest, titles)
                        self._log_q.put(
                            ("log", f"[{idx}/{total}] Applied imported chapter titles\n")
                        )
                    self._log_q.put(("log", f"[{idx}/{total}] ✓ {dest.name}\n"))
                    ok += 1
                except Exception as e:
                    self._log_q.put(("log", f"[{idx}/{total}] ✗ {f.name}: {e}\n"))
                    fail += 1
                finally:
                    self._log_q.put(("progress", (idx, total)))
        except ConversionCancelled:
            cancelled = True
        self._log_q.put(("done", (ok, fail, cancelled)))

    # ----- remove-series-numbering worker (worker thread) -----
    def _remove_numbering_worker(self, files: list, outdir: Path):
        cancel_check = self._cancel_event.is_set
        total = len(files)
        ok = 0
        fail = 0
        cancelled = False
        try:
            outdir.mkdir(parents=True, exist_ok=True)  # lazy create on first run
            for idx, f in enumerate(files, start=1):
                raise_if_cancelled(cancel_check)
                try:
                    # Copy original → output folder, then strip numbering on the
                    # COPY only (chapters/other tags preserved). The imported
                    # original is read-only.
                    dest = paths.avoid_input_overwrite(outdir / f.name, files)
                    shutil.copy2(f, dest)
                    self._log_q.put(("log", f"[{idx}/{total}] Copied {f.name} → {dest}\n"))
                    metadata.clear_series_numbering(dest)
                    self._log_q.put(
                        ("log", f"[{idx}/{total}] Removed series numbering (kept chapters)\n")
                    )
                    self._log_q.put(("log", f"[{idx}/{total}] ✓ {dest.name}\n"))
                    ok += 1
                except Exception as e:
                    self._log_q.put(("log", f"[{idx}/{total}] ✗ {f.name}: {e}\n"))
                    fail += 1
                finally:
                    self._log_q.put(("progress", (idx, total)))
        except ConversionCancelled:
            cancelled = True
        self._log_q.put(("done", (ok, fail, cancelled)))


def build_ui(parent: tk.Misc, theme: dict | None = None) -> M4BMetadataEditorUI:
    """Build the M4B Metadata Editor UI into ``parent`` and return the frame.

    ``theme`` is optional and backwards-compatible: the launcher's existing
    ``module.build_ui(container)`` call is unchanged, and the panel resolves the
    platform theme itself when nothing is passed.
    """
    ui = M4BMetadataEditorUI(parent, theme=theme)
    ui.pack(fill=tk.BOTH, expand=True)
    return ui


def main():
    root = tk.Tk()
    root.title(APP_TITLE)
    root.geometry("880x900")
    root.minsize(760, 760)
    build_ui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
