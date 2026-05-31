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
- **Multiple files (batch mode):** the form starts blank with a batch notice.
  Fields left **blank are not written** (each copy keeps the original's tag); any
  field with a value **overwrites** that tag in every copy.

Series Name / Series Part are written as the freeform atoms
``----:com.apple.iTunes:SERIES`` / ``SERIES-PART`` (Briefing §6), which
Audiobookshelf's ffprobe scanner reads as ``series`` / ``series-part``.

Series Part is governed by an **Auto-number** toggle: OFF (default) writes
nothing to series-part (the field is display-only — preserve-by-default); ON
treats the Series Part field as the starting number and writes sequential parts
across the loaded files in list order (a single file gets just that number).

Refactored like the other tools: UI is built by build_ui(parent); the save runs
on a worker thread with a Cancel button (cooperative cancellation between files)
via shared.cancellation; a standalone main() is kept for debugging.
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
    """The M4B Metadata Editor as an embeddable frame."""

    def __init__(self, parent: tk.Misc):
        super().__init__(parent)

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
        # Top: file actions
        top = ttk.Frame(self)
        top.pack(side=tk.TOP, fill=tk.X, padx=12, pady=(10, 6))
        self.btn_add = ttk.Button(top, text="Open M4B File(s)", command=self.add_files)
        self.btn_add.pack(side=tk.LEFT)
        self.btn_remove = ttk.Button(top, text="Remove Selected", command=self.remove_selected)
        self.btn_remove.pack(side=tk.LEFT, padx=(8, 0))
        self.btn_clear = ttk.Button(top, text="Clear List", command=self.clear_list)
        self.btn_clear.pack(side=tk.LEFT, padx=(8, 0))
        self.lbl_mode = ttk.Label(top, textvariable=self.mode_var, foreground="#b45309")
        self.lbl_mode.pack(side=tk.RIGHT)

        # File list
        list_frame = ttk.LabelFrame(self, text="M4B Files")
        list_frame.pack(side=tk.TOP, fill=tk.X, padx=12, pady=(0, 6))
        self.listbox = tk.Listbox(list_frame, selectmode=tk.EXTENDED, height=5)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.configure(yscrollcommand=sb.set)

        # Metadata form
        form_box = ttk.LabelFrame(self, text="Tags (blank fields are left unchanged)")
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
        chap_box = ttk.LabelFrame(self, text="Chapter Titles (optional)")
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
        # never touched.
        outrow = ttk.Frame(self)
        outrow.pack(side=tk.TOP, fill=tk.X, padx=12, pady=(0, 6))
        ttk.Label(outrow, text="Output folder:").pack(side=tk.LEFT)
        self.entry_outdir = ttk.Entry(outrow, textvariable=self.var_outdir)
        self.entry_outdir.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 6))
        self.btn_browse_out = ttk.Button(outrow, text="Browse…", command=self.choose_outdir)
        self.btn_browse_out.pack(side=tk.LEFT)
        self.btn_open_out = ttk.Button(outrow, text="Open", command=self.open_outdir)
        self.btn_open_out.pack(side=tk.LEFT, padx=(6, 0))

        # Action buttons
        action = ttk.Frame(self)
        action.pack(side=tk.TOP, fill=tk.X, padx=12, pady=(0, 6))
        self.btn_save = ttk.Button(action, text="Save Tags", command=self.save)
        self.btn_save.pack(side=tk.LEFT)
        self.btn_clear_tags = ttk.Button(
            action, text="Clear All Tags (keep chapters)", command=self.on_clear_all_tags
        )
        self.btn_clear_tags.pack(side=tk.LEFT, padx=(8, 0))
        self.btn_cancel = ttk.Button(action, text="Cancel", command=self.cancel, state=tk.DISABLED)
        self.btn_cancel.pack(side=tk.LEFT, padx=(8, 0))
        self.progress = ttk.Progressbar(action, mode="determinate", length=240)
        self.progress.pack(side=tk.RIGHT)

        # Log
        logf = ttk.LabelFrame(self, text="Log")
        logf.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=12, pady=(0, 10))
        self.log = tk.Text(logf, height=8, wrap="word", state=tk.DISABLED)
        self.log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb2 = ttk.Scrollbar(logf, orient="vertical", command=self.log.yview)
        sb2.pack(side=tk.RIGHT, fill=tk.Y)
        self.log.configure(yscrollcommand=sb2.set)

        self._update_chap_buttons()  # disabled until files are loaded
        self._update_autonumber_hint()  # set the initial (toggle-off) hint text

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

    def remove_selected(self):
        sel = list(self.listbox.curselection())
        for idx in reversed(sel):
            del self.files[idx]
            self.listbox.delete(idx)
        self._refresh_mode()

    def clear_list(self):
        self.files.clear()
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
            self._clear_fields()
            self.mode_var.set(f"Batch mode: {n} files — blank fields are left unchanged.")
            self.series_readback_var.set("Detected on file: (multiple files loaded)")
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
        self.progress.configure(maximum=len(files), value=0)
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
            self.btn_remove,
            self.btn_clear,
            self.btn_save,
            self.btn_clear_tags,
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
                    self.progress.configure(value=payload)
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
                        metadata.write_m4b_tags(dest, file_tags)
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
                    self._log_q.put(("progress", idx))
        except ConversionCancelled:
            cancelled = True
        self._log_q.put(("done", (ok, fail, cancelled)))


def build_ui(parent: tk.Misc) -> M4BMetadataEditorUI:
    """Build the M4B Metadata Editor UI into ``parent`` and return the frame."""
    ui = M4BMetadataEditorUI(parent)
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
