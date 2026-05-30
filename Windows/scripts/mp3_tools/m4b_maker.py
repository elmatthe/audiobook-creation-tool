#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
M4B Maker — MP3 -> M4B with chapters.

Refactored for the unified launcher: UI is built by build_ui(parent); all
ffmpeg/ffprobe calls and folder-opening go through shared.subprocess_utils so
no console window flashes on Windows.

- MP3 -> M4B with chapters
- Optional silence between tracks (safe WAV mode)
- Fast concat with auto-fallback to safe path
- Cover picker with preview (Pillow, optional)
- Output -> a remembered folder (settings; default = home), in M4B-Output-*

Phase 5: the build now runs on a worker thread with a Cancel button (cooperative
cancellation at stage boundaries, partial output removed), input/output/cover
folders are remembered via shared.settings, and the ffmetadata header is built
by shared.metadata so the field set matches the other M4B tool.
"""

import re
import shutil
import sys
import wave
import json
import queue
import threading
import contextlib
import traceback
from pathlib import Path
from subprocess import CalledProcessError

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Make the scripts/ root importable so `shared.*` resolves whether this tool is
# run standalone (python mp3_tools/m4b_maker.py) or imported by the launcher.
_SCRIPTS_ROOT = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ROOT))

from shared import ffmpeg_utils
from shared import metadata
from shared import paths
from shared import settings
from shared import subprocess_utils as sp
from shared.cancellation import ConversionCancelled, raise_if_cancelled

# Optional dependency for cover preview
try:
    from PIL import Image, ImageTk
except Exception:
    Image = ImageTk = None

# -------- tuning --------
LEADIN_MS = 250
WAV_SR = 44100
WAV_CH = 2
WAV_FMT = "s16"
PREVIEW_MAX = (260, 260)

APP_TITLE = "M4B Maker v5.0 (Fast-first + Auto-fallback)"

# Auto-named output folder slug (v0.1.1): the built .m4b is delivered into
# Downloads/<SLUG>-N. The input MP3s are only ever read.
SLUG = paths.TOOL_SLUGS["m4b_maker"]

# settings.json keys (input/cover dirs only remember the dialog location; the
# output folder is NOT persisted — it always resets to a fresh Downloads/<SLUG>-N).
KEY_INPUT_DIR = "m4b_maker.input_dir"
KEY_COVER_DIR = "m4b_maker.cover_dir"


# -------- helpers --------
def _remembered_dir(key: str) -> Path:
    """Return the saved folder for ``key`` if it still exists, else the home dir."""
    val = settings.get(key)
    if val:
        p = Path(val)
        if p.exists():
            return p
    return Path.home()


def natural_key(s):
    import re as _re

    return [int(t) if t.isdigit() else t.lower() for t in _re.split(r"(\d+)", str(s))]


def strip_leading_numbers(name: str) -> str:
    return re.sub(r"^\s*\d+\s*[-_.\)\(]*\s*", "", name).strip() or name


def normalize_title(stem: str) -> str:
    base = strip_leading_numbers(stem)
    base = re.sub(r"\s*_\s*", ": ", base, count=1)
    base = re.sub(r"(\w)_s\b", r"\1’s", base)
    base = re.sub(r"_\s*$", "?", base)
    base = re.sub(r"\s+", " ", base).strip()
    return base


def ffprobe_duration_ms(p: Path) -> int:
    data = sp.check_output(
        [
            ffmpeg_utils.ffprobe_cmd(),
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=duration",
            "-of",
            "json",
            str(p),
        ]
    )
    j = json.loads(data)
    dur = j["streams"][0].get("duration") if j.get("streams") else None
    if dur is None:
        data = sp.check_output(
            [
                ffmpeg_utils.ffprobe_cmd(),
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nk=1:nw=1",
                str(p),
            ]
        )
        dur = data.decode().strip()
    return max(int(round(float(dur) * 1000)), 0)


def compute_titles(files):
    return [normalize_title(Path(p).stem) for p in files]


def build_ffmetadata_from_starts(titles, starts_ms, meta, total_ms):
    """Create ffmetadata with proper chapter ends (last chapter ends at total_ms-1)."""
    lines = [";FFMETADATA1"]
    lines += metadata.ffmetadata_header_lines(
        {
            "title": meta.get("title"),
            "artist": meta.get("artist"),
            "album_artist": meta.get("album_artist"),
            "album": meta.get("album"),
        }
    )

    n = len(titles)
    for i in range(n):
        start = max(starts_ms[i] - LEADIN_MS, 0)
        end = (starts_ms[i + 1] - 1) if (i + 1 < n) else (total_ms - 1)
        end = max(min(end, total_ms - 1), start + 100)  # >=100ms
        lines += [
            "",
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={start}",
            f"END={end}",
            f"title={titles[i]}",
        ]
    return "\n".join(lines)


def write_concat_list(paths, dest: Path):
    with open(dest, "w", encoding="utf-8") as f:
        for p in paths:
            pp = str(p).replace("'", r"'\'\'")
            f.write(f"file '{pp}'\n")


# ----- SAFE path helpers -----
def normalize_to_wav(inputs, tmp_dir: Path, cancel_check=None):
    wav_dir = tmp_dir / "wav"
    wav_dir.mkdir(parents=True, exist_ok=True)
    wavs = []
    for i, src in enumerate(inputs, 1):
        raise_if_cancelled(cancel_check)
        dst = wav_dir / f"{i:04d}.wav"
        cmd = [
            ffmpeg_utils.ffmpeg_cmd(),
            "-hide_banner",
            "-y",
            "-i",
            str(src),
            "-vn",
            "-ac",
            str(WAV_CH),
            "-ar",
            str(WAV_SR),
            "-sample_fmt",
            WAV_FMT,
            "-af",
            "asetpts=N/SR/TB,aresample=async=1:first_pts=0",
            "-fflags",
            "+genpts",
            "-avoid_negative_ts",
            "make_zero",
            "-map_metadata",
            "-1",
            str(dst),
        ]
        sp.run(cmd, check=True)
        wavs.append(dst)
    return wavs


def create_silence_wav(seconds: float, tmp_dir: Path) -> Path:
    dst = tmp_dir / f"silence_{seconds:.3f}s.wav"
    cmd = [
        ffmpeg_utils.ffmpeg_cmd(),
        "-hide_banner",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=r={WAV_SR}:cl=stereo",
        "-t",
        f"{seconds:.6f}",
        "-ar",
        str(WAV_SR),
        "-ac",
        str(WAV_CH),
        "-sample_fmt",
        WAV_FMT,
        str(dst),
    ]
    sp.run(cmd, check=True)
    return dst


def wav_duration_ms(wav_path: Path) -> int:
    with contextlib.closing(wave.open(str(wav_path), "rb")) as w:
        return int(round(w.getnframes() * 1000.0 / w.getframerate()))


def compute_starts_total_fast(files):
    starts = []
    t = 0
    for p in files:
        starts.append(t)
        t += ffprobe_duration_ms(p)
    return starts, t


def compute_audio_starts_with_silence(wavs, silence_ms):
    """Return (chapter_starts_ms_for_audio_only, total_ms_including_silence)."""
    starts = []
    t = 0
    for i, w in enumerate(wavs):
        starts.append(t)
        t += wav_duration_ms(w)
        if i < len(wavs) - 1:
            t += silence_ms
    return starts, t


# ----- ffmpeg runners -----
def run_safe_concat(audio_list_path, ffmeta_path, cover_path, out_path, bitrate):
    cmd = [
        ffmpeg_utils.ffmpeg_cmd(),
        "-hide_banner",
        "-y",
        "-xerror",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(audio_list_path),
        "-i",
        str(ffmeta_path),
    ]
    maps = ["-map_metadata", "1", "-map_chapters", "1", "-map", "0:a:0"]
    if cover_path:
        cmd += ["-i", str(cover_path)]
        maps += [
            "-map",
            "2:v:0",
            "-disposition:v:0",
            "attached_pic",
            "-metadata:s:v:0",
            "title=Album cover",
            "-metadata:s:v:0",
            "comment=Cover (front)",
        ]
        cmd += ["-c:v:0", "mjpeg"]
    cmd += maps + [
        "-c:a",
        "aac",
        "-b:a",
        bitrate,
        "-ar",
        str(WAV_SR),
        "-ac",
        str(WAV_CH),
        "-movflags",
        "+faststart",
        str(out_path),
    ]
    sp.run(cmd, check=True)


def run_fast_concat(audio_list_path, ffmeta_path, cover_path, out_path, bitrate):
    cmd = [
        ffmpeg_utils.ffmpeg_cmd(),
        "-hide_banner",
        "-y",
        "-xerror",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(audio_list_path),
        "-i",
        str(ffmeta_path),
        "-fflags",
        "+genpts",
        "-avoid_negative_ts",
        "make_zero",
        "-filter:a",
        "asetpts=N/SR/TB,aresample=async=1:first_pts=0",
    ]
    maps = ["-map_metadata", "1", "-map_chapters", "1", "-map", "0:a:0"]
    if cover_path:
        cmd += ["-i", str(cover_path)]
        maps += [
            "-map",
            "2:v:0",
            "-disposition:v:0",
            "attached_pic",
            "-metadata:s:v:0",
            "title=Album cover",
            "-metadata:s:v:0",
            "comment=Cover (front)",
        ]
        cmd += ["-c:v:0", "mjpeg"]
    cmd += maps + [
        "-c:a",
        "aac",
        "-b:a",
        bitrate,
        "-movflags",
        "+faststart",
        str(out_path),
    ]
    sp.run(cmd, check=True)


# -------- GUI --------
class M4BMakerUI(ttk.Frame):
    """The M4B Maker as an embeddable frame."""

    def __init__(self, parent: tk.Misc):
        super().__init__(parent)

        self.files: list[Path] = []
        self.cover_path: Path | None = None
        self.cover_thumb = None

        # Cancellation / worker plumbing (mirrors the TTS tool's pattern).
        self._busy = threading.Event()
        self._cancel_event = threading.Event()
        self._log_q: queue.Queue = queue.Queue()

        self.silence_seconds = tk.StringVar(value="0")
        self.fast_first = tk.BooleanVar(value=True)

        self.var_title = tk.StringVar()
        self.var_artist = tk.StringVar()
        self.var_album_artist = tk.StringVar()
        self.var_album = tk.StringVar()
        self.var_series = tk.StringVar()
        self.var_series_part = tk.StringVar()
        self.var_cover_path = tk.StringVar()
        # Output folder: a fresh Downloads/<SLUG>-N decided once now, at build
        # time. Browse redirects it for this run only (never persisted); the
        # folder is created lazily on the first build.
        self.var_outdir = tk.StringVar(value=str(paths.next_output_dir(SLUG)))

        self.status = tk.StringVar(value="Added 0 files. Total: 0")

        self._build_ui()

        # Start draining the worker->GUI queue on the main thread.
        self.after(150, self._pump_queue)

    # ----- UI -----
    def _build_ui(self):
        # Top buttons
        top = ttk.Frame(self)
        top.pack(fill="x", padx=12, pady=8)

        self.btn_import = ttk.Button(top, text="Import MP3 Files", command=self.add_files)
        self.btn_import.pack(side="left")
        self.btn_remove = ttk.Button(top, text="Remove Selected", command=self.remove_selected)
        self.btn_remove.pack(side="left", padx=(8, 0))
        self.btn_clear = ttk.Button(top, text="Clear List", command=self.clear_all)
        self.btn_clear.pack(side="left", padx=(8, 0))

        # File list + log (same window)
        center = ttk.Frame(self)
        center.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        center.rowconfigure(0, weight=1)
        center.columnconfigure(0, weight=1)
        center.columnconfigure(1, weight=1)

        # File list
        file_frame = ttk.LabelFrame(center, text="Input MP3 Files")
        file_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        file_frame.rowconfigure(0, weight=1)
        file_frame.columnconfigure(0, weight=1)

        self.listbox = tk.Listbox(file_frame, selectmode="extended")
        self.listbox.grid(row=0, column=0, sticky="nsew")
        sb_files = ttk.Scrollbar(file_frame, orient="vertical", command=self.listbox.yview)
        sb_files.grid(row=0, column=1, sticky="ns")
        self.listbox.config(yscrollcommand=sb_files.set)

        # Log area
        log_frame = ttk.LabelFrame(center, text="Log")
        log_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        self.log_text = tk.Text(log_frame, wrap="word", height=10, state=tk.DISABLED)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        sb_log = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        sb_log.grid(row=0, column=1, sticky="ns")
        self.log_text.config(yscrollcommand=sb_log.set)

        # Output folder row
        outrow = ttk.Frame(self)
        outrow.pack(fill="x", padx=12, pady=(0, 4))
        ttk.Label(outrow, text="Output folder:").pack(side="left")
        self.entry_outdir = ttk.Entry(outrow, textvariable=self.var_outdir)
        self.entry_outdir.pack(side="left", fill="x", expand=True, padx=(6, 6))
        self.btn_browse_out = ttk.Button(outrow, text="Browse…", command=self.choose_outdir)
        self.btn_browse_out.pack(side="left")

        # Controls row
        ctrls = ttk.Frame(self)
        ctrls.pack(fill="x", padx=12, pady=(0, 6))

        ttk.Label(ctrls, text="Silence between tracks (seconds, 0 = none):").pack(side="left")
        self.entry_silence = ttk.Entry(ctrls, width=8, textvariable=self.silence_seconds)
        self.entry_silence.pack(side="left", padx=(6, 14))

        self.chk_fast = ttk.Checkbutton(
            ctrls,
            text="Always try FAST mode first (auto-fallback on failure)",
            variable=self.fast_first,
        )
        self.chk_fast.pack(side="left", padx=6)

        self.btn_cancel = ttk.Button(
            ctrls, text="Cancel", command=self.cancel, state=tk.DISABLED
        )
        self.btn_cancel.pack(side="right", padx=(8, 0))
        self.btn_build = ttk.Button(ctrls, text="Combine files → M4B", command=self.build)
        self.btn_build.pack(side="right")

        # Metadata & cover
        meta = ttk.LabelFrame(self, text="M4B Metadata & Chapters")
        meta.pack(fill="both", expand=False, padx=12, pady=(4, 4))
        meta.columnconfigure(0, weight=1)
        meta.columnconfigure(1, weight=0)

        # Left form
        form = ttk.Frame(meta)
        form.grid(row=0, column=0, sticky="nwe", padx=8, pady=8)
        form.columnconfigure(0, weight=0)
        form.columnconfigure(1, weight=1)
        form.columnconfigure(2, weight=0)

        def add_row(r, label, var):
            ttk.Label(form, text=label).grid(row=r, column=0, sticky="e", padx=5, pady=4)
            ttk.Entry(form, textvariable=var).grid(
                row=r, column=1, sticky="we", padx=5, pady=4
            )

        add_row(0, "Title (blank → filename)", self.var_title)
        add_row(1, "Artist", self.var_artist)
        add_row(2, "Album Artist", self.var_album_artist)
        add_row(3, "Album", self.var_album)
        add_row(4, "Series Name", self.var_series)
        add_row(5, "Series Part", self.var_series_part)

        # Cover row
        ttk.Label(form, text="Cover image (JPG/PNG):").grid(
            row=6, column=0, sticky="e", padx=5, pady=4
        )
        ttk.Entry(form, textvariable=self.var_cover_path).grid(
            row=6, column=1, sticky="we", padx=5, pady=4
        )
        btns = ttk.Frame(form)
        btns.grid(row=6, column=2, sticky="w", padx=6, pady=4)
        ttk.Button(btns, text="Browse…", command=self.choose_cover).pack(side="left")
        ttk.Button(btns, text="Clear", command=self.clear_cover).pack(side="left", padx=(6, 0))

        # Right: cover preview
        preview = ttk.Frame(meta)
        preview.grid(row=0, column=1, sticky="nsw", padx=(12, 8), pady=8)
        ttk.Label(preview, text="Preview").pack(anchor="w")
        self.preview_label = ttk.Label(preview, text="(no image)", width=30)
        self.preview_label.pack(anchor="w", padx=2, pady=4)

        # Chapters box
        chap = ttk.Frame(meta)
        chap.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=8, pady=8)
        meta.rowconfigure(1, weight=1)

        ttk.Label(chap, text="Chapter titles (one per line):").pack(anchor="w")
        self.chapters_txt = tk.Text(chap, height=8, wrap="word")
        self.chapters_txt.pack(fill="both", expand=True)

        # Bottom status frame so it never gets covered
        bottom = ttk.Frame(self)
        bottom.pack(fill="x", padx=12, pady=(0, 10))

        self.progress = ttk.Progressbar(bottom, mode="determinate")
        self.progress.pack(fill="x", pady=(0, 4))

        ttk.Label(bottom, textvariable=self.status, foreground="#4a6").pack(anchor="w")

        # Connect cover path -> preview
        self.var_cover_path.trace_add("write", lambda *_: self.update_preview())

    # ----- file actions -----
    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="Select MP3 files",
            initialdir=str(_remembered_dir(KEY_INPUT_DIR)),
            filetypes=[("MP3 audio", "*.mp3")],
        )
        if not paths:
            return
        batch = sorted([Path(p) for p in paths], key=lambda p: natural_key(p.name))
        added = 0
        for p in batch:
            if p.exists() and p not in self.files:
                self.files.append(p)
                self.listbox.insert("end", p.name)
                added += 1
        settings.set(KEY_INPUT_DIR, str(Path(paths[0]).parent))
        self.status.set(f"Added {added} files. Total: {len(self.files)}")

    def remove_selected(self):
        sel = list(self.listbox.curselection())
        if not sel:
            return
        for idx in reversed(sel):
            del self.files[idx]
            self.listbox.delete(idx)
        self.status.set(f"Total: {len(self.files)}")

    def clear_all(self):
        self.files.clear()
        self.listbox.delete(0, "end")
        self.status.set("Added 0 files. Total: 0")

    # ----- logging -----
    def log(self, msg: str):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

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

    # ----- cover -----
    def choose_cover(self):
        p = filedialog.askopenfilename(
            title="Select Cover Image (JPG/PNG)",
            initialdir=str(_remembered_dir(KEY_COVER_DIR)),
            filetypes=[("Image", "*.jpg *.jpeg *.png")],
        )
        if not p:
            return
        settings.set(KEY_COVER_DIR, str(Path(p).parent))
        self.var_cover_path.set(p)

    def clear_cover(self):
        self.var_cover_path.set("")
        self.cover_path = None
        self.preview_label.config(image="", text="(no image)")
        self.cover_thumb = None

    def update_preview(self):
        path_str = self.var_cover_path.get()
        self.cover_path = Path(path_str).expanduser() if path_str else None
        if not self.cover_path:
            self.preview_label.config(image="", text="(no image)")
            self.cover_thumb = None
            return
        if Image is None:
            self.preview_label.config(image="", text="(install Pillow for preview)")
            self.cover_thumb = None
            return
        try:
            img = Image.open(self.cover_path)
            img.thumbnail(PREVIEW_MAX)
            self.cover_thumb = ImageTk.PhotoImage(img)
            self.preview_label.config(image=self.cover_thumb, text="")
        except Exception as e:
            self.preview_label.config(image="", text=f"(preview error: {e})")
            self.cover_thumb = None

    # ----- cancel + queue pump -----
    def cancel(self):
        if not self._busy.is_set() or self._cancel_event.is_set():
            return
        self._cancel_event.set()
        self.btn_cancel.configure(state=tk.DISABLED)
        self._log_q.put(("log", "Cancelling… will stop at the next stage."))

    def disable_inputs(self, state: bool):
        widgets = [
            self.btn_import,
            self.btn_remove,
            self.btn_clear,
            self.btn_build,
            self.entry_silence,
            self.chk_fast,
            self.entry_outdir,
            self.btn_browse_out,
        ]
        for w in widgets:
            w.configure(state=tk.DISABLED if state else tk.NORMAL)

    def _pump_queue(self):
        try:
            while True:
                kind, payload = self._log_q.get_nowait()
                if kind == "log":
                    self.log(payload)
                elif kind == "status":
                    self.status.set(payload)
                elif kind == "progress":
                    self.progress["value"] = payload
                elif kind == "progress_max":
                    self.progress["maximum"] = payload
                elif kind == "done":
                    self._finish_idle()
                    out_path, out_dir = payload
                    self.status.set(f"Done → {out_path}")
                    self.log(f"Created: {out_path}")
                    messagebox.showinfo("Success", f"Created:\n{out_path}")
                    sp.reveal_in_file_manager(out_dir)
                elif kind == "cancelled":
                    self._finish_idle()
                    self.status.set("Cancelled.")
                    self.log("Cancelled.")
                elif kind == "err":
                    self._finish_idle()
                    title, msg = payload
                    self.status.set(title)
                    self.log(f"{title}: {msg}")
                    messagebox.showerror(title, msg)
        except queue.Empty:
            pass
        self.after(150, self._pump_queue)

    def _finish_idle(self):
        self._busy.clear()
        self._cancel_event.clear()
        self.disable_inputs(False)
        self.btn_cancel.configure(state=tk.DISABLED)

    # ----- build -----
    def build(self):
        if self._busy.is_set():
            return
        if not self.files:
            messagebox.showerror("No files", "Please import MP3 files first.")
            return

        # Read every Tk var here on the main thread; the worker uses copies only.
        pasted = [
            s.strip() for s in self.chapters_txt.get("1.0", "end").splitlines() if s.strip()
        ]
        try:
            silence_val = float(self.silence_seconds.get().strip() or "0")
        except ValueError:
            silence_val = 0.0

        params = {
            "files": list(self.files),
            "pasted_titles": pasted,
            "silence_val": silence_val,
            "fast_first": self.fast_first.get(),
            "title": self.var_title.get().strip(),
            "artist": self.var_artist.get().strip(),
            "album_artist": self.var_album_artist.get().strip(),
            "album": self.var_album.get().strip(),
            "series": self.var_series.get().strip(),
            "series_part": self.var_series_part.get().strip(),
            "cover_path": self.cover_path if (self.cover_path and self.cover_path.exists()) else None,
        }

        out_dir = self.output_dir()
        out_dir.mkdir(parents=True, exist_ok=True)  # lazy create on first build

        self._busy.set()
        self._cancel_event.clear()
        self.progress["maximum"] = len(params["files"])
        self.progress["value"] = 0
        self.disable_inputs(True)
        self.btn_cancel.configure(state=tk.NORMAL)

        t = threading.Thread(
            target=self._build_worker, args=(params, out_dir), daemon=True
        )
        t.start()

    def _build_worker(self, params: dict, out_dir: Path):
        cancel_check = self._cancel_event.is_set
        files = params["files"]
        tmp = out_dir / "build"
        tmp.mkdir(exist_ok=True)

        def write_error(msg: str):
            try:
                (out_dir / "ERROR.txt").write_text(msg, encoding="utf-8")
            except Exception:
                pass

        try:
            # Titles
            auto = [normalize_title(Path(p).stem) for p in files]
            titles = params["pasted_titles"] if params["pasted_titles"] else auto
            if len(titles) < len(files):
                titles += auto[len(titles):]
            if len(titles) > len(files):
                titles = titles[: len(files)]

            silence_ms = int(round(params["silence_val"] * 1000))

            raise_if_cancelled(cancel_check)

            if silence_ms > 0:
                self._log_q.put(("log", "Normalizing to WAV and inserting silence…"))
                wavs = normalize_to_wav(files, tmp, cancel_check=cancel_check)
                gap = create_silence_wav(params["silence_val"], tmp)
                seq = []
                for i, w in enumerate(wavs):
                    seq.append(w)
                    if i < len(wavs) - 1:
                        seq.append(gap)
                starts_ms, total_ms = compute_audio_starts_with_silence(wavs, silence_ms)
                audio_for_build = seq
                use_safe = True
            else:
                self._log_q.put(("log", "Using FAST path timings (no silence)…"))
                audio_for_build = files
                starts_ms, total_ms = compute_starts_total_fast(files)
                use_safe = False

            raise_if_cancelled(cancel_check)

            # Output name
            base_name = params["title"] or params["album"] or "audiobook"
            base_name = re.sub(r'[\\/:*?"<>|]+', "_", base_name) or "audiobook"
            out_path = paths.avoid_input_overwrite(out_dir / f"{base_name}.m4b", files)

            # Metadata
            meta = {
                "title": base_name,
                "artist": params["artist"],
                "album_artist": params["album_artist"],
                "album": params["album"],
            }

            ffmeta = tmp / "chapters.ffmeta.txt"
            ffmeta.write_text(
                build_ffmetadata_from_starts(titles, starts_ms, meta, total_ms),
                encoding="utf-8",
            )

            # Concat list
            listfile = tmp / "inputs.txt"
            write_concat_list(audio_for_build, listfile)

            cover_path = params["cover_path"]

            self._log_q.put(("status", "Encoding…"))
            raise_if_cancelled(cancel_check)

            try:
                if not use_safe and params["fast_first"]:
                    self._log_q.put(("log", "Trying FAST concat mode…"))
                    run_fast_concat(listfile, ffmeta, cover_path, out_path, "128k")
                else:
                    self._log_q.put(("log", "Using SAFE concat mode…"))
                    run_safe_concat(listfile, ffmeta, cover_path, out_path, "128k")
            except CalledProcessError:
                raise_if_cancelled(cancel_check)
                if not use_safe:
                    self._log_q.put(("log", "Fast path failed — retrying in Safe Mode…"))
                    wavs = normalize_to_wav(files, tmp, cancel_check=cancel_check)
                    write_concat_list(wavs, listfile)
                    starts_ms, total_ms = compute_audio_starts_with_silence(wavs, 0)
                    ffmeta.write_text(
                        build_ffmetadata_from_starts(titles, starts_ms, meta, total_ms),
                        encoding="utf-8",
                    )
                    run_safe_concat(listfile, ffmeta, cover_path, out_path, "128k")
                else:
                    raise

            # Series tags (Audiobookshelf freeform atoms) — ffmpeg can't write
            # these, so add them with mutagen after the encode succeeds.
            series_tags = {
                k: params[k]
                for k in ("series", "series_part")
                if params.get(k)
            }
            if series_tags:
                self._log_q.put(("log", "Writing series tags…"))
                metadata.write_m4b_tags(out_path, series_tags)

            shutil.rmtree(tmp, ignore_errors=True)
            self._log_q.put(("progress", len(files)))
            self._log_q.put(("done", (out_path, out_dir)))

        except ConversionCancelled:
            # Remove the whole output folder created for this (now-abandoned) build.
            shutil.rmtree(out_dir, ignore_errors=True)
            self._log_q.put(("cancelled", None))
        except CalledProcessError as e:
            try:
                stderr = getattr(e, "stderr", None)
                msg = stderr.decode("utf-8") if stderr else str(e)
            except Exception:
                msg = str(e)
            write_error(f"ffmpeg error:\n\n{msg}")
            self._log_q.put(("err", ("ffmpeg error", msg)))
        except FileNotFoundError as e:
            write_error(f"Missing file(s): {e}")
            self._log_q.put(("err", ("Missing file(s)", str(e))))
        except Exception as e:
            write_error(f"Unhandled error:\n\n{traceback.format_exc()}")
            self._log_q.put(("err", ("Error", str(e))))


def build_ui(parent: tk.Misc) -> M4BMakerUI:
    """Build the M4B Maker UI into ``parent`` and return the frame."""
    ui = M4BMakerUI(parent)
    ui.pack(fill=tk.BOTH, expand=True)
    return ui


def main():
    root = tk.Tk()
    root.title(APP_TITLE)
    root.geometry("980x780")
    root.minsize(860, 660)
    build_ui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
