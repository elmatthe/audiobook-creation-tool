#!/usr/bin/env python3

import os
import sys
import threading
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from PIL import Image  # needs: pip install pillow

# Try to add HEIC/HEIF support if pillow-heif is installed
try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:
    pass

APP_TITLE = "Audiobook Cover Resizer v1.1"
TARGET_SIZE = 1024  # default square size for covers


# ---------- helpers ----------


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


# ---------- GUI app ----------


class App(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title(APP_TITLE)
        self.geometry("900x640")
        self.minsize(900, 640)

        self.files: list[Path] = []

        # Top buttons
        top = tk.Frame(self)
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
        list_frame = tk.Frame(self)
        list_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10)

        self.listbox = tk.Listbox(list_frame, selectmode=tk.EXTENDED, height=12)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sb = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.configure(yscrollcommand=sb.set)

        # Options
        options = tk.LabelFrame(self, text="Resize Options (applies to all images)")
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
        logf = tk.LabelFrame(self, text="Log")
        logf.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        self.log = tk.Text(logf, height=8, wrap="word")
        self.log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sb2 = ttk.Scrollbar(logf, orient="vertical", command=self.log.yview)
        sb2.pack(side=tk.RIGHT, fill=tk.Y)
        self.log.configure(yscrollcommand=sb2.set)

        self.progress = ttk.Progressbar(self, length=400, mode="determinate")
        self.progress.pack(side=tk.BOTTOM, pady=(0, 10))

        # Bottom action bar
        action = tk.Frame(self)
        action.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(0, 10))

        self.btn_convert = ttk.Button(action, text="Resize Covers", command=self.start_resize)
        self.btn_convert.pack(side=tk.LEFT)

    # ------- UI callbacks -------

    def add_files(self):
        files = filedialog.askopenfilenames(
            title="Select cover images",
            filetypes=[
                ("Images", "*.jpg;*.jpeg;*.png;*.heic;*.heif"),
                ("All files", "*.*"),
            ],
        )
        if not files:
            return

        for f in files:
            p = Path(f)
            self.files.append(p)
            self.listbox.insert(tk.END, str(p))

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

        self.disable_inputs(True)
        t = threading.Thread(
            target=self.resize_worker,
            args=(size, self.var_letterbox.get(), self.var_overwrite.get()),
            daemon=True,
        )
        t.start()

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
        self.update_idletasks()

    # ------- worker -------

    def resize_worker(self, size: int, letterbox: bool, overwrite: bool):
        total = len(self.files)
        self.progress.configure(maximum=total, value=0)

        for idx, in_file in enumerate(self.files, start=1):
            try:
                if overwrite:
                    temp_out = next_version_path(in_file)  # make a temp with -1
                    final_out = in_file
                else:
                    temp_out = next_version_path(in_file)
                    final_out = temp_out

                self.log_write(f"\n[{idx}/{total}] Resizing:\n {in_file}\n -> {final_out}\n")

                resize_for_audiobook(in_file, temp_out, size=size, letterbox=letterbox)

                if overwrite and temp_out != final_out:
                    temp_out.replace(final_out)

                self.log_write(" ✓ Done\n")

            except Exception as e:
                self.log_write(f" ✗ Error: {e}\n")

            finally:
                self.progress.configure(value=idx)
                self.update_idletasks()

        self.log_write("\nAll done.\n")
        self.disable_inputs(False)


if __name__ == "__main__":
    app = App()
    app.mainloop()

