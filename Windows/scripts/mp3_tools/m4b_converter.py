#!/usr/bin/env python3
# m4b_converter.py
# GUI batch converter: .m4b -> .mp3 with optional bulk metadata, sequential output folders.

import os
import sys
import threading
import subprocess
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP_TITLE = "M4B Converter v1.0 (Bulk -> MP3)"
DEFAULT_QUALITY = 2  # LAME VBR q scale (0=best, 9=lowest). 2 ~ ~190kbps


# ---------- helpers ---------- #


def which(cmd: str) -> str | None:
    from shutil import which as _which

    return _which(cmd)


def next_output_dir() -> Path:
    base = Path.home() / "Downloads"
    base.mkdir(parents=True, exist_ok=True)
    n = 1
    while True:
        candidate = base / f"m4b_converter_output-{n}"
        if not candidate.exists():
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        n += 1


def sanitize_filename(name: str) -> str:
    # Keep filename friendly across platforms; keep stem logic simple.
    bad = ["/", "\0"]
    out = name
    for ch in bad:
        out = out.replace(ch, "-")
    # Colons can be annoying in some tools; replace with dash.
    out = out.replace(":", " - ")
    # Collapse whitespace
    return " ".join(out.split())


def ffmpeg_available() -> bool:
    return which("ffmpeg") is not None and which("ffprobe") is not None


def quote(p: Path) -> str:
    return str(p)


# ---------- GUI app ----------


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("900x620")
        self.minsize(900, 620)

        self.files: list[Path] = []

        # Top buttons
        top = tk.Frame(self)
        top.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(10, 6))

        self.btn_add = ttk.Button(top, text="Import M4B Files", command=self.add_files)
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

        # Options area (styled like your mp3 tool)
        options = tk.LabelFrame(self, text="Conversion & Metadata (applies to all files)")
        options.pack(side=tk.TOP, fill=tk.X, padx=10, pady=10, ipady=4)

        row = 0
        ttk.Label(options, text="MP3 Quality (VBR 0–9, lower is better):").grid(
            row=row, column=0, sticky="w", padx=8, pady=4
        )
        self.var_quality = tk.IntVar(value=DEFAULT_QUALITY)
        self.entry_quality = ttk.Spinbox(
            options, from_=0, to=9, textvariable=self.var_quality, width=4
        )
        self.entry_quality.grid(row=row, column=1, sticky="w", padx=8, pady=4)

        row += 1
        self.var_no_tags = tk.BooleanVar(value=False)
        self.chk_no_tags = ttk.Checkbutton(
            options,
            text="Do NOT write any metadata (use filenames only)",
            variable=self.var_no_tags,
        )
        self.chk_no_tags.grid(row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(2, 8))

        # Metadata entries
        row += 1
        ttk.Label(options, text="Title (blank → filename):").grid(
            row=row, column=0, sticky="e", padx=8, pady=2
        )
        self.title_entry = ttk.Entry(options, width=40)
        self.title_entry.grid(row=row, column=1, sticky="w", padx=8, pady=2)

        ttk.Label(options, text="Artist:").grid(
            row=row, column=2, sticky="e", padx=8, pady=2
        )
        self.artist_entry = ttk.Entry(options, width=30)
        self.artist_entry.grid(row=row, column=3, sticky="w", padx=8, pady=2)

        row += 1
        ttk.Label(options, text="Album Artist:").grid(
            row=row, column=0, sticky="e", padx=8, pady=2
        )
        self.album_artist_entry = ttk.Entry(options, width=40)
        self.album_artist_entry.grid(row=row, column=1, sticky="w", padx=8, pady=2)

        ttk.Label(options, text="Album:").grid(
            row=row, column=2, sticky="e", padx=8, pady=2
        )
        self.album_entry = ttk.Entry(options, width=30)
        self.album_entry.grid(row=row, column=3, sticky="w", padx=8, pady=2)

        # Auto-number checkbox + start
        row += 1
        self.var_auto_num = tk.BooleanVar(value=True)
        self.chk_auto_num = ttk.Checkbutton(
            options, text="Auto-number tracks", variable=self.var_auto_num
        )
        self.chk_auto_num.grid(row=row, column=0, sticky="w", padx=8, pady=2)

        ttk.Label(options, text="Start #:").grid(row=row, column=1, sticky="e", padx=8, pady=2)
        self.var_start_num = tk.IntVar(value=1)
        self.entry_start_num = ttk.Entry(options, textvariable=self.var_start_num, width=6)
        self.entry_start_num.grid(row=row, column=1, sticky="w", padx=(70, 8), pady=2)

        # Output dir preview
        row += 1
        self.out_dir_preview = tk.StringVar(value=str(next_output_dir()))
        ttk.Label(options, text="Output folder (auto):").grid(
            row=row, column=0, sticky="e", padx=8, pady=4
        )
        self.lbl_outdir = ttk.Label(
            options, textvariable=self.out_dir_preview, foreground="#15803d"
        )
        self.lbl_outdir.grid(row=row, column=1, columnspan=3, sticky="w", padx=8, pady=4)

        # Action buttons
        action = tk.Frame(self)
        action.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(0, 10))
        self.btn_convert = ttk.Button(action, text="Convert M4Bs → MP3s", command=self.start_convert)
        self.btn_convert.pack(side=tk.LEFT)
        self.btn_open_out = ttk.Button(action, text="Open Output Folder", command=self.open_outdir)
        self.btn_open_out.pack(side=tk.LEFT, padx=8)

        # Log area
        logf = tk.LabelFrame(self, text="Log")
        logf.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        self.log = tk.Text(logf, height=8, wrap="word")
        self.log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb2 = ttk.Scrollbar(logf, orient="vertical", command=self.log.yview)
        sb2.pack(side=tk.RIGHT, fill=tk.Y)
        self.log.configure(yscrollcommand=sb2.set)

        # Progress
        self.progress = ttk.Progressbar(self, length=400, mode="determinate")
        self.progress.pack(side=tk.BOTTOM, pady=(0, 10))

        # Initial checks
        if not ffmpeg_available():
            messagebox.showerror(
                "FFmpeg not found",
                "FFmpeg/ffprobe not found in PATH.\nInstall FFmpeg and ensure it is on PATH.",
            )
        else:
            self.log_write("FFmpeg detected.\n")

        for i in range(4):
            options.grid_columnconfigure(i, weight=1)

        self.refresh_outdir_preview()

    # ------- UI callbacks -------

    def add_files(self):
        files = filedialog.askopenfilenames(
            title="Select .m4b files",
            filetypes=[("M4B Audiobooks", "*.m4b"), ("All files", "*.*")],
        )
        if not files:
            return
        for f in files:
            p = Path(f)
            if p.suffix.lower() != ".m4b":
                continue
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

    def refresh_outdir_preview(self):
        # preview without actually creating a new folder each time
        base = Path.home() / "Downloads"
        n = 1
        while True:
            candidate = base / f"m4b_converter_output-{n}"
            if not candidate.exists():
                self.out_dir_preview.set(str(candidate))
                break
            n += 1

    def open_outdir(self):
        out_dir = Path(self.out_dir_preview.get())
        if not out_dir.exists():
            out_dir.mkdir(parents=True, exist_ok=True)
        if sys.platform == "darwin":
            subprocess.run(["open", str(out_dir)])
        elif os.name == "nt":
            os.startfile(str(out_dir))  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", str(out_dir)])

    def start_convert(self):
        if not self.files:
            messagebox.showwarning("No files", "Please import .m4b files first.")
            return
        if not ffmpeg_available():
            messagebox.showerror("FFmpeg not found", "FFmpeg/ffprobe not found in PATH.")
            return
        outdir = next_output_dir()
        self.out_dir_preview.set(str(outdir))
        self.disable_inputs(True)
        t = threading.Thread(target=self.convert_worker, args=(outdir,), daemon=True)
        t.start()

    def disable_inputs(self, state: bool):
        widgets = [
            self.btn_add,
            self.btn_remove,
            self.btn_clear,
            self.btn_convert,
            self.entry_quality,
            self.chk_no_tags,
            self.title_entry,
            self.artist_entry,
            self.album_artist_entry,
            self.album_entry,
            self.chk_auto_num,
            self.entry_start_num,
        ]
        for w in widgets:
            w.configure(state=tk.DISABLED if state else tk.NORMAL)

    def log_write(self, text: str):
        self.log.insert(tk.END, text)
        self.log.see(tk.END)
        self.update_idletasks()

    # ------- conversion -------

    def convert_worker(self, outdir: Path):
        total = len(self.files)
        self.progress.configure(maximum=total, value=0)
        quality = max(0, min(9, int(self.var_quality.get())))
        write_tags = not self.var_no_tags.get()
        bulk_title = self.title_entry.get().strip()
        artist = self.artist_entry.get().strip()
        album_artist = self.album_artist_entry.get().strip()
        album = self.album_entry.get().strip()
        do_track = self.var_auto_num.get()
        start_num = int(self.var_start_num.get() or 1)

        for idx, in_file in enumerate(self.files, start=1):
            try:
                stem = sanitize_filename(in_file.stem)
                out_mp3 = outdir / f"{stem}.mp3"

                cmd = ["ffmpeg", "-hide_banner", "-y", "-i", quote(in_file), "-vn"]

                if write_tags:
                    title_val = bulk_title if bulk_title else stem
                    cmd += ["-metadata", f"title={title_val}"]
                    if artist:
                        cmd += ["-metadata", f"artist={artist}"]
                    if album_artist:
                        cmd += ["-metadata", f"album_artist={album_artist}"]
                    if album:
                        cmd += ["-metadata", f"album={album}"]
                    if do_track:
                        trackno = start_num + (idx - 1)
                        cmd += ["-metadata", f"track={trackno}"]
                    cmd += ["-id3v2_version", "3"]
                else:
                    cmd += ["-map_metadata", "-1"]

                cmd += [
                    "-c:a",
                    "libmp3lame",
                    "-q:a",
                    str(quality),
                    "-threads",
                    "0",
                    quote(out_mp3),
                ]

                self.log_write(
                    f"\n[{idx}/{total}] Converting:\n  {in_file}\n  -> {out_mp3}\n"
                )
                proc = subprocess.run(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
                )
                if proc.returncode != 0:
                    self.log_write(proc.stdout[-2000:] + "\n")
                    raise RuntimeError(f"FFmpeg failed (code {proc.returncode}).")

                self.log_write("  ✓ Done\n")
            except Exception as e:
                self.log_write(f"  ✗ Error: {e}\n")
            finally:
                self.progress.configure(value=idx)
                self.update_idletasks()

        self.log_write(f"\nAll done. Output: {outdir}\n")
        self.disable_inputs(False)
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", str(outdir)])
            elif os.name == "nt":
                os.startfile(str(outdir))  # type: ignore[attr-defined]
            else:
                subprocess.run(["xdg-open", str(outdir)])
        except Exception:
            pass


if __name__ == "__main__":
    app = App()
    app.mainloop()

