#!/usr/bin/env python3
# m4b_converter.py
# GUI batch converter: .m4b -> .mp3 with optional bulk metadata, sequential output folders.
#
# Refactored for the unified launcher: UI is built by build_ui(parent); all
# ffmpeg calls and folder-opening go through shared.subprocess_utils so no
# console window flashes on Windows.
#
# Phase 5: Cancel button (cooperative, checked between files), input/output
# folders remembered via shared.settings (default = home, no hardcoded
# ~/Downloads), and tag args built by shared.metadata.

import queue
import sys
import threading
from pathlib import Path
from subprocess import PIPE, STDOUT

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Make the scripts/ root importable so `shared.*` resolves whether this tool is
# run standalone (python mp3_tools/m4b_converter.py) or imported by the launcher.
_SCRIPTS_ROOT = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ROOT))

from shared import ffmpeg_utils
from shared import metadata
from shared import paths
from shared import settings
from shared import subprocess_utils as sp

APP_TITLE = "M4B Converter v1.0 (Bulk -> MP3)"
DEFAULT_QUALITY = 2  # LAME VBR q scale (0=best, 9=lowest). 2 ~ ~190kbps

# Auto-named output folder slug (v0.1.1): MP3s are delivered into
# Downloads/<SLUG>-N. The originals (.m4b) are only ever read.
SLUG = paths.TOOL_SLUGS["m4b_converter"]

# settings.json keys (input dir only remembers the dialog location; the output
# folder is NOT persisted — it always resets to a fresh Downloads/<SLUG>-N).
KEY_INPUT_DIR = "m4b_converter.input_dir"


# ---------- helpers ---------- #


def _remembered_dir(key: str) -> Path:
    """Return the saved folder for ``key`` if it still exists, else the home dir."""
    val = settings.get(key)
    if val:
        p = Path(val)
        if p.exists():
            return p
    return Path.home()


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


def quote(p: Path) -> str:
    return str(p)


# ---------- GUI ----------


class M4BConverterUI(ttk.Frame):
    """The M4B → MP3 converter as an embeddable frame."""

    def __init__(self, parent: tk.Misc):
        super().__init__(parent)

        self.files: list[Path] = []

        # Cancellation / worker plumbing (mirrors the TTS tool's pattern).
        self._busy = threading.Event()
        self._cancel_event = threading.Event()
        self._log_q: queue.Queue = queue.Queue()

        # Output folder: a fresh Downloads/<SLUG>-N decided once now, at build
        # time. Browse redirects it for this run only (never persisted); the
        # folder is created lazily on the first conversion.
        self.var_outdir = tk.StringVar(value=str(paths.next_output_dir(SLUG)))

        # Top buttons
        top = ttk.Frame(self)
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
        list_frame = ttk.Frame(self)
        list_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10)
        self.listbox = tk.Listbox(list_frame, selectmode=tk.EXTENDED, height=12)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.configure(yscrollcommand=sb.set)

        # Options area
        options = ttk.LabelFrame(self, text="Conversion & Metadata (applies to all files)")
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

        # Output folder picker (remembered base)
        row += 1
        ttk.Label(options, text="Output folder:").grid(
            row=row, column=0, sticky="e", padx=8, pady=4
        )
        self.entry_outdir = ttk.Entry(options, textvariable=self.var_outdir)
        self.entry_outdir.grid(row=row, column=1, columnspan=2, sticky="we", padx=8, pady=4)
        self.btn_browse_out = ttk.Button(options, text="Browse…", command=self.choose_outdir)
        self.btn_browse_out.grid(row=row, column=3, sticky="w", padx=8, pady=4)

        # Action buttons
        action = ttk.Frame(self)
        action.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(0, 10))
        self.btn_convert = ttk.Button(action, text="Convert M4Bs → MP3s", command=self.start_convert)
        self.btn_convert.pack(side=tk.LEFT)
        self.btn_cancel = ttk.Button(
            action, text="Cancel", command=self.cancel, state=tk.DISABLED
        )
        self.btn_cancel.pack(side=tk.LEFT, padx=8)
        self.btn_open_out = ttk.Button(action, text="Open Output Folder", command=self.open_outdir)
        self.btn_open_out.pack(side=tk.LEFT, padx=8)

        # Log area
        logf = ttk.LabelFrame(self, text="Log")
        logf.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        self.log = tk.Text(logf, height=8, wrap="word")
        self.log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb2 = ttk.Scrollbar(logf, orient="vertical", command=self.log.yview)
        sb2.pack(side=tk.RIGHT, fill=tk.Y)
        self.log.configure(yscrollcommand=sb2.set)

        # Progress
        self.progress = ttk.Progressbar(self, length=400, mode="determinate")
        self.progress.pack(side=tk.BOTTOM, pady=(0, 10))

        for i in range(4):
            options.grid_columnconfigure(i, weight=1)

        # Initial checks (log instead of a modal so switching tools is quiet)
        if not ffmpeg_utils.have_ffmpeg():
            self.log_write(
                "WARNING: ffmpeg/ffprobe not found. Run the setup launcher to install it.\n"
            )
        else:
            self.log_write("FFmpeg detected.\n")

        # Start draining the worker->GUI queue on the main thread.
        self.after(150, self._pump_queue)

    # ------- UI callbacks -------

    def add_files(self):
        files = filedialog.askopenfilenames(
            title="Select .m4b files",
            initialdir=str(_remembered_dir(KEY_INPUT_DIR)),
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
        out_dir = self.output_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        sp.reveal_in_file_manager(out_dir)

    def start_convert(self):
        if self._busy.is_set():
            return
        if not self.files:
            messagebox.showwarning("No files", "Please import .m4b files first.")
            return
        if not ffmpeg_utils.have_ffmpeg():
            messagebox.showerror("FFmpeg not found", "FFmpeg/ffprobe not found.")
            return

        # Read all Tk vars here on the main thread; the worker uses these copies
        # only (touching Tk from a worker raises "main thread is not in main loop").
        try:
            quality = max(0, min(9, int(self.var_quality.get())))
        except Exception:
            quality = DEFAULT_QUALITY
        params = {
            "quality": quality,
            "write_tags": not self.var_no_tags.get(),
            "title": self.title_entry.get().strip(),
            "artist": self.artist_entry.get().strip(),
            "album_artist": self.album_artist_entry.get().strip(),
            "album": self.album_entry.get().strip(),
            "do_track": self.var_auto_num.get(),
            "start_num": int(self.var_start_num.get() or 1),
            "files": list(self.files),
        }

        outdir = self.output_dir()
        outdir.mkdir(parents=True, exist_ok=True)  # lazy create on first run

        self._busy.set()
        self._cancel_event.clear()
        self.progress.configure(maximum=len(params["files"]), value=0)
        self.disable_inputs(True)
        self.btn_cancel.configure(state=tk.NORMAL)

        t = threading.Thread(
            target=self.convert_worker, args=(outdir, params), daemon=True
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
            self.btn_convert,
            self.entry_quality,
            self.chk_no_tags,
            self.title_entry,
            self.artist_entry,
            self.album_artist_entry,
            self.album_entry,
            self.chk_auto_num,
            self.entry_start_num,
            self.entry_outdir,
            self.btn_browse_out,
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
                    self.progress.configure(value=payload)
                elif kind == "done":
                    self.log_write(payload[0])
                    self._finish_idle()
                    if payload[1] is not None:
                        sp.reveal_in_file_manager(payload[1])
        except queue.Empty:
            pass
        self.after(150, self._pump_queue)

    def _finish_idle(self):
        self._busy.clear()
        self._cancel_event.clear()
        self.disable_inputs(False)
        self.btn_cancel.configure(state=tk.DISABLED)

    # ------- conversion (worker thread) -------

    def convert_worker(self, outdir: Path, params: dict):
        files = params["files"]
        total = len(files)
        cancelled = False

        for idx, in_file in enumerate(files, start=1):
            if self._cancel_event.is_set():
                cancelled = True
                break
            try:
                stem = sanitize_filename(in_file.stem)
                out_mp3 = paths.avoid_input_overwrite(outdir / f"{stem}.mp3", files)

                # Probe the source so the decode side can be chosen correctly.
                # xHE-AAC (USAC) m4b sources are mis-decoded by ffmpeg's native
                # AAC decoder (it drops packets → a shorter, sped-up MP3); on
                # macOS the Apple AudioToolbox decoder (aac_at) handles them.
                info = ffmpeg_utils.probe_audio_stream(in_file)
                dec_args = ffmpeg_utils.input_decoder_args(info)
                if info:
                    self._log_q.put(
                        (
                            "log",
                            "  source: {codec}{prof} {sr} Hz, {ch} ch\n".format(
                                codec=info.get("codec_name") or "?",
                                prof=(
                                    f" [{info['profile']}]" if info.get("profile") else ""
                                ),
                                sr=info.get("sample_rate") or "?",
                                ch=info.get("channels") or "?",
                            ),
                        )
                    )
                if dec_args:
                    self._log_q.put(
                        ("log", f"  using {dec_args[1]} decoder (xHE-AAC source)\n")
                    )
                elif ffmpeg_utils.needs_special_aac_decoder(info):
                    self._log_q.put(
                        (
                            "log",
                            "  ⚠ WARNING: source is xHE-AAC and this ffmpeg build has "
                            "no compatible decoder on this platform — the output may be "
                            "sped up / choppy.\n",
                        )
                    )

                cmd = [ffmpeg_utils.ffmpeg_cmd(), "-hide_banner", "-y", *dec_args, "-i", quote(in_file), "-vn"]

                if params["write_tags"]:
                    tags = {
                        "title": params["title"] if params["title"] else stem,
                        "artist": params["artist"],
                        "album_artist": params["album_artist"],
                        "album": params["album"],
                    }
                    if params["do_track"]:
                        tags["track"] = params["start_num"] + (idx - 1)
                    cmd += metadata.ffmpeg_metadata_args(tags)
                    cmd += ["-id3v2_version", "3"]
                else:
                    cmd += ["-map_metadata", "-1"]

                cmd += [
                    "-c:a",
                    "libmp3lame",
                    "-q:a",
                    str(params["quality"]),
                    "-threads",
                    "0",
                    quote(out_mp3),
                ]

                self._log_q.put(
                    ("log", f"\n[{idx}/{total}] Converting:\n  {in_file}\n  -> {out_mp3}\n")
                )
                self._log_q.put(("log", "  ffmpeg: " + " ".join(str(c) for c in cmd) + "\n"))
                proc = sp.run(cmd, stdout=PIPE, stderr=STDOUT, text=True)
                if proc.returncode != 0:
                    self._log_q.put(("log", (proc.stdout or "")[-2000:] + "\n"))
                    # Drop the partial/failed output so the folder only holds good files.
                    try:
                        out_mp3.unlink(missing_ok=True)
                    except OSError:
                        pass
                    raise RuntimeError(f"FFmpeg failed (code {proc.returncode}).")

                # Defensive duration guard (all platforms): a source ffmpeg
                # cannot fully decode — e.g. xHE-AAC on a platform without the
                # aac_at decoder — silently drops packets, producing an output
                # much shorter than the source that plays sped up and choppy.
                # Compare the output length to the source and fail loudly rather
                # than deliver a corrupt MP3.
                src_dur = info.get("duration") if info else None
                out_info = ffmpeg_utils.probe_audio_stream(out_mp3)
                out_dur = out_info.get("duration") if out_info else None
                if src_dur and out_dur and src_dur > 1.0:
                    drift = abs(out_dur - src_dur) / src_dur
                    if drift > 0.03:
                        try:
                            out_mp3.unlink(missing_ok=True)
                        except OSError:
                            pass
                        raise RuntimeError(
                            "output length {:.0f}s != source {:.0f}s ({:.0%} off) — the "
                            "source could not be decoded correctly (likely xHE-AAC with "
                            "no compatible decoder on this platform). Output discarded.".format(
                                out_dur, src_dur, drift
                            )
                        )

                self._log_q.put(("log", "  ✓ Done\n"))
            except Exception as e:
                self._log_q.put(("log", f"  ✗ Error: {e}\n"))
            finally:
                self._log_q.put(("progress", idx))

        if cancelled:
            self._log_q.put(("done", (f"\nCancelled. Output so far: {outdir}\n", outdir)))
        else:
            self._log_q.put(("done", (f"\nAll done. Output: {outdir}\n", outdir)))


def build_ui(parent: tk.Misc) -> M4BConverterUI:
    """Build the M4B Converter UI into ``parent`` and return the frame."""
    ui = M4BConverterUI(parent)
    ui.pack(fill=tk.BOTH, expand=True)
    return ui


def main():
    root = tk.Tk()
    root.title(APP_TITLE)
    root.geometry("900x680")
    root.minsize(900, 680)
    build_ui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
