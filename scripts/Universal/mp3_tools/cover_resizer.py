#!/usr/bin/env python3
"""Cover Image Resizer — batch resize cover art to a square (letterbox or crop).

Refactored for the unified launcher: the UI is built by :func:`build_ui` into
any parent frame, so it can live inside the launcher's content panel. Running
this file directly still opens it in its own window via :func:`main`.

Phase 5: Cancel button (cooperative, checked between images) and a remembered
input folder via shared.settings (default = home). Resized images are written
next to their source, so this tool has no separate output folder.
"""

import queue
import sys
import threading
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Make the scripts/ root importable so `shared.*` resolves whether this tool is
# run standalone or imported by the launcher.
_SCRIPTS_ROOT = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ROOT))

from shared import settings
from shared import ui_theme

from PIL import Image  # needs: pip install pillow

# Try to add HEIC/HEIF support if pillow-heif is installed
try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:
    pass

APP_TITLE = "Audiobook Cover Resizer v1.1"
TARGET_SIZE = 1024  # default square size for covers

# settings.json keys (Phase 5)
KEY_INPUT_DIR = "cover_resizer.input_dir"


# ---------- helpers ----------


def _remembered_dir(key: str) -> Path:
    """Return the saved folder for ``key`` if it still exists, else the home dir."""
    val = settings.get(key)
    if val:
        p = Path(val)
        if p.exists():
            return p
    return Path.home()


def next_version_path(p: Path) -> Path:
    """Return first available Name-1.ext, Name-2.ext, ... in same folder."""
    stem = p.stem
    suffix = p.suffix
    parent = p.parent
    n = 1
    while True:
        candidate = parent / f"{stem}-{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


# ---------- image logic ----------


def resize_for_audiobook(in_path: Path, out_path: Path, size: int, letterbox: bool):
    """
    Always keep full image visible when letterbox=True:
      - Scale so the LONG side == size
      - Paste on a square canvas with bars if needed.
    """
    img = Image.open(in_path).convert("RGB")
    w, h = img.size

    if letterbox:
        scale = size / max(w, h)
        new_w, new_h = int(round(w * scale)), int(round(h * scale))
        img = img.resize((new_w, new_h), Image.LANCZOS)

        canvas = Image.new("RGB", (size, size), color=(0, 0, 0))
        offset_x = (size - new_w) // 2
        offset_y = (size - new_h) // 2
        canvas.paste(img, (offset_x, offset_y))
        img = canvas
    else:
        scale = size / min(w, h)
        new_w, new_h = int(round(w * scale)), int(round(h * scale))
        img = img.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - size) // 2
        upper = (new_h - size) // 2
        right = left + size
        lower = upper + size
        img = img.crop((left, upper, right, lower))

    ext = out_path.suffix.lower()
    save_kwargs = {}

    if ext in [".jpg", ".jpeg"]:
        save_kwargs = {"format": "JPEG", "quality": 95}
    elif ext == ".png":
        save_kwargs = {"format": "PNG", "compress_level": 6}
    elif ext in [".heic", ".heif"]:
        save_kwargs = {"format": "HEIF", "quality": 95}
    else:
        out_path = out_path.with_suffix(".jpg")
        save_kwargs = {"format": "JPEG", "quality": 95}

    img.save(out_path, **save_kwargs)


# ---------- GUI ----------


class CoverResizerUI(ttk.Frame):
    """The Cover Resizer tool as an embeddable frame."""

    def __init__(self, parent: tk.Misc):
        super().__init__(parent)

        self.files: list[Path] = []

        # Cancellation / worker plumbing (mirrors the TTS tool's pattern).
        self._busy = threading.Event()
        self._cancel_event = threading.Event()
        self._log_q: queue.Queue = queue.Queue()

        # Top buttons
        top = ttk.Frame(self)
        top.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(10, 6))

        self.btn_add = ttk.Button(top, text="Import Images", command=self.add_files)
        self.btn_add.pack(side=tk.LEFT)

        self.btn_remove = ttk.Button(top, text="Remove Selected", command=self.remove_selected)
        self.btn_remove.pack(side=tk.LEFT, padx=8)

        self.btn_clear = ttk.Button(top, text="Clear List", command=self.clear_list)
        self.btn_clear.pack(side=tk.LEFT)

        self.count_var = tk.StringVar(value="0 file(s)")
        ttk.Label(top, textvariable=self.count_var).pack(side=tk.RIGHT)

        # File list
        list_frame = ttk.Frame(self)
        list_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10)

        self.listbox = tk.Listbox(list_frame, selectmode=tk.EXTENDED, height=12)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sb = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.configure(yscrollcommand=sb.set)

        # Options
        options = ttk.LabelFrame(self, text="Resize Options (applies to all images)")
        options.pack(side=tk.TOP, fill=tk.X, padx=10, pady=10, ipady=4)

        row = 0

        ttk.Label(options, text="Target size (square, px):").grid(
            row=row, column=0, sticky="w", padx=8, pady=4
        )
        self.var_size = tk.IntVar(value=TARGET_SIZE)
        self.entry_size = ttk.Spinbox(
            options, from_=256, to=4096, textvariable=self.var_size, width=6, increment=64
        )
        self.entry_size.grid(row=row, column=1, sticky="w", padx=8, pady=4)

        row += 1
        self.var_letterbox = tk.BooleanVar(value=True)
        self.chk_letterbox = ttk.Checkbutton(
            options,
            text="Keep full image (letterbox into square, no cropping)",
            variable=self.var_letterbox,
        )
        self.chk_letterbox.grid(
            row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(2, 4)
        )

        row += 1
        self.var_overwrite = tk.BooleanVar(value=False)
        self.chk_overwrite = ttk.Checkbutton(
            options,
            text="Overwrite original files (no -1 copy; old image is replaced)",
            variable=self.var_overwrite,
        )
        self.chk_overwrite.grid(
            row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(2, 8)
        )

        # Log + progress
        logf = ttk.LabelFrame(self, text="Log")
        logf.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        self.log = tk.Text(logf, height=8, wrap="word")
        self.log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sb2 = ttk.Scrollbar(logf, orient="vertical", command=self.log.yview)
        sb2.pack(side=tk.RIGHT, fill=tk.Y)
        self.log.configure(yscrollcommand=sb2.set)

        # Progress (bar + images-done/percentage label; updated only from the
        # main-thread queue pump)
        self.progress = ui_theme.ProgressIndicator(self, length=400)
        self.progress.frame.pack(side=tk.BOTTOM, pady=(0, 10))

        # Bottom action bar
        action = ttk.Frame(self)
        action.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(0, 10))

        self.btn_convert = ttk.Button(action, text="Resize Covers", command=self.start_resize)
        self.btn_convert.pack(side=tk.LEFT)
        self.btn_cancel = ttk.Button(
            action, text="Cancel", command=self.cancel, state=tk.DISABLED
        )
        self.btn_cancel.pack(side=tk.LEFT, padx=8)

        # Start draining the worker->GUI queue on the main thread.
        self.after(150, self._pump_queue)

    # ------- UI callbacks -------

    def add_files(self):
        files = filedialog.askopenfilenames(
            title="Select cover images",
            initialdir=str(_remembered_dir(KEY_INPUT_DIR)),
            filetypes=[
                ("Images", "*.jpg *.jpeg *.png *.heic *.heif"),
                ("All files", "*.*"),
            ],
        )
        if not files:
            return

        for f in files:
            p = Path(f)
            self.files.append(p)
            self.listbox.insert(tk.END, str(p))

        settings.set(KEY_INPUT_DIR, str(Path(files[0]).parent))
        self.update_count()

    def remove_selected(self):
        sel = list(self.listbox.curselection())
        sel.reverse()
        for idx in sel:
            self.listbox.delete(idx)
            del self.files[idx]
        self.update_count()

    def clear_list(self):
        self.listbox.delete(0, tk.END)
        self.files.clear()
        self.update_count()

    def update_count(self):
        self.count_var.set(f"{len(self.files)} file(s)")

    def start_resize(self):
        if self._busy.is_set():
            return
        if not self.files:
            messagebox.showwarning("No files", "Please import images first.")
            return

        try:
            size = int(self.var_size.get() or TARGET_SIZE)
        except Exception:
            messagebox.showerror("Bad size", "Target size must be a number.")
            return

        if size <= 0:
            messagebox.showerror("Bad size", "Target size must be positive.")
            return

        params = {
            "size": size,
            "letterbox": self.var_letterbox.get(),
            "overwrite": self.var_overwrite.get(),
            "files": list(self.files),
        }

        self._busy.set()
        self._cancel_event.clear()
        self.progress.update(0, len(params["files"]))
        self.disable_inputs(True)
        self.btn_cancel.configure(state=tk.NORMAL)

        t = threading.Thread(target=self.resize_worker, args=(params,), daemon=True)
        t.start()

    def cancel(self):
        if not self._busy.is_set() or self._cancel_event.is_set():
            return
        self._cancel_event.set()
        self.btn_cancel.configure(state=tk.DISABLED)
        self._log_q.put(("log", "Cancelling… will stop after the current image.\n"))

    def disable_inputs(self, state: bool):
        widgets = [
            self.btn_add,
            self.btn_remove,
            self.btn_clear,
            self.entry_size,
            self.chk_letterbox,
            self.chk_overwrite,
            self.btn_convert,
        ]
        for w in widgets:
            w.configure(state=tk.DISABLED if state else tk.NORMAL)

    def log_write(self, text: str):
        self.log.insert(tk.END, text)
        self.log.see(tk.END)

    # ------- worker -> GUI queue pump (main thread) -------

    def _pump_queue(self):
        try:
            while True:
                kind, payload = self._log_q.get_nowait()
                if kind == "log":
                    self.log_write(payload)
                elif kind == "progress":
                    self.progress.update(*payload)
                elif kind == "done":
                    self.log_write(payload)
                    self._finish_idle()
        except queue.Empty:
            pass
        self.after(150, self._pump_queue)

    def _finish_idle(self):
        self._busy.clear()
        self._cancel_event.clear()
        self.disable_inputs(False)
        self.btn_cancel.configure(state=tk.DISABLED)

    # ------- worker (thread) -------

    def resize_worker(self, params: dict):
        files = params["files"]
        size = params["size"]
        letterbox = params["letterbox"]
        overwrite = params["overwrite"]
        total = len(files)
        cancelled = False

        for idx, in_file in enumerate(files, start=1):
            if self._cancel_event.is_set():
                cancelled = True
                break
            temp_out = None
            try:
                if overwrite:
                    temp_out = next_version_path(in_file)  # make a temp with -1
                    final_out = in_file
                else:
                    temp_out = next_version_path(in_file)
                    final_out = temp_out

                self._log_q.put(("log", f"\n[{idx}/{total}] Resizing:\n {in_file}\n -> {final_out}\n"))

                resize_for_audiobook(in_file, temp_out, size=size, letterbox=letterbox)

                if overwrite and temp_out != final_out:
                    temp_out.replace(final_out)

                self._log_q.put(("log", " ✓ Done\n"))

            except Exception as e:
                # Clean up a partial temp file from a failed resize.
                if temp_out is not None and overwrite:
                    try:
                        temp_out.unlink(missing_ok=True)
                    except OSError:
                        pass
                self._log_q.put(("log", f" ✗ Error: {e}\n"))

            finally:
                self._log_q.put(("progress", (idx, total)))

        if cancelled:
            self._log_q.put(("done", "\nCancelled.\n"))
        else:
            self._log_q.put(("done", "\nAll done.\n"))


def build_ui(parent: tk.Misc) -> CoverResizerUI:
    """Build the Cover Resizer UI into ``parent`` and return the frame."""
    ui = CoverResizerUI(parent)
    ui.pack(fill=tk.BOTH, expand=True)
    return ui


def main():
    root = tk.Tk()
    root.title(APP_TITLE)
    root.geometry("900x640")
    root.minsize(900, 640)
    build_ui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
