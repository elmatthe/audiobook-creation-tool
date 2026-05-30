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
        self._refresh_mode()

    def _clear_fields(self):
        for _key, attr, _label in _FIELDS:
            getattr(self, attr).set("")
        self.var_cover_path.set("")

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

    def _prefill_from(self, path: Path):
        self._clear_fields()
        try:
            tags = metadata.read_m4b_tags(path)
        except Exception as e:
            self.log_write(f"Could not read tags from {path.name}: {e}\n")
            return
        for key, attr, _label in _FIELDS:
            if key in tags:
                getattr(self, attr).set(str(tags[key]))
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

    # ----- collect non-blank fields -----
    def _collect_tags(self) -> dict:
        tags: dict = {}
        for key, attr, _label in _FIELDS:
            val = getattr(self, attr).get().strip()
            if val:
                tags[key] = val
        cover = self.var_cover_path.get().strip()
        if cover:
            tags["cover_path"] = cover
        return tags

    # ----- save -----
    def save(self):
        if self._busy.is_set():
            return
        if not self.files:
            messagebox.showerror("No files", "Open one or more M4B files first.")
            return

        tags = self._collect_tags()
        if not tags:
            messagebox.showinfo(
                "Nothing to write",
                "All fields are blank, so there is nothing to change.",
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
        self.log_write(f"\nWriting tags to {len(files)} copy(ies) in {outdir}…\n")

        t = threading.Thread(target=self._save_worker, args=(files, tags, outdir), daemon=True)
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
            self.btn_cover,
            self.btn_cover_clear,
            self.entry_cover,
            self.entry_outdir,
            self.btn_browse_out,
            *self._field_widgets,
        ]
        for w in widgets:
            w.configure(state=tk.DISABLED if state else tk.NORMAL)

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
    def _save_worker(self, files: list, tags: dict, outdir: Path):
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
                    # Copy the original into the output folder, then tag the COPY.
                    # The imported original is only ever read.
                    dest = paths.avoid_input_overwrite(outdir / f.name, files)
                    shutil.copy2(f, dest)
                    self._log_q.put(("log", f"[{idx}/{total}] Copied {f.name} → {dest}\n"))
                    metadata.write_m4b_tags(dest, tags)
                    self._log_q.put(("log", f"[{idx}/{total}] ✓ Tagged {dest.name}\n"))
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
    root.geometry("820x680")
    root.minsize(720, 600)
    build_ui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
