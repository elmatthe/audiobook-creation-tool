#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
M4B Tool v5.0 — Unified UI style

- Single main window (like webnovel_pdf_editor & m4b_converter)
- MP3 -> M4B with chapters
- Optional silence between tracks (safe WAV mode)
- Fast concat with auto-fallback to safe path
- Cover picker with preview (Pillow, optional)
- Output -> ~/Downloads/M4B-Output-*
"""

import os
import re
import json
import shutil
import subprocess
import sys
import wave
import contextlib
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

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

APP_TITLE = "M4B Tool v5.0 (Fast-first + Auto-fallback)"


# -------- helpers --------
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
    data = subprocess.check_output(
        [
            "ffprobe",
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
        data = subprocess.check_output(
            [
                "ffprobe",
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


def next_output_dir(base: Path | None = None) -> Path:
    if base is None:
        base = Path.home() / "Downloads"
    base.mkdir(parents=True, exist_ok=True)
    n = 1
    while True:
        d = base / f"M4B-Output-{n}"
        if not d.exists():
            d.mkdir()
            return d
        n += 1


def compute_titles(files):
    return [normalize_title(Path(p).stem) for p in files]


def build_ffmetadata_from_starts(titles, starts_ms, meta, total_ms):
    """Create ffmetadata with proper chapter ends (last chapter ends at total_ms-1)."""
    lines = [";FFMETADATA1"]
    if meta.get("title"):
        lines.append(f"title={meta['title']}")
    if meta.get("artist"):
        lines.append(f"artist={meta['artist']}")
    if meta.get("album_artist"):
        lines.append(f"album_artist={meta['album_artist']}")
    if meta.get("album"):
        lines.append(f"album={meta['album']}")

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
def normalize_to_wav(inputs, tmp_dir: Path):
    wav_dir = tmp_dir / "wav"
    wav_dir.mkdir(parents=True, exist_ok=True)
    wavs = []
    for i, src in enumerate(inputs, 1):
        dst = wav_dir / f"{i:04d}.wav"
        cmd = [
            "ffmpeg",
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
        subprocess.run(cmd, check=True)
        wavs.append(dst)
    return wavs


def create_silence_wav(seconds: float, tmp_dir: Path) -> Path:
    dst = tmp_dir / f"silence_{seconds:.3f}s.wav"
    cmd = [
        "ffmpeg",
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
    subprocess.run(cmd, check=True)
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
        "ffmpeg",
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
    subprocess.run(cmd, check=True)


def run_fast_concat(audio_list_path, ffmeta_path, cover_path, out_path, bitrate):
    cmd = [
        "ffmpeg",
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
    subprocess.run(cmd, check=True)


# -------- GUI --------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("980x740")
        self.minsize(860, 640)

        self.files: list[Path] = []
        self.cover_path: Path | None = None
        self.cover_thumb = None

        self.silence_seconds = tk.StringVar(value="0")
        self.fast_first = tk.BooleanVar(value=True)

        self.var_title = tk.StringVar()
        self.var_artist = tk.StringVar()
        self.var_album_artist = tk.StringVar()
        self.var_album = tk.StringVar()
        self.var_cover_path = tk.StringVar()

        self.status = tk.StringVar(value="Added 0 files. Total: 0")

        self._build_ui()

    # ----- UI -----
    def _build_ui(self):
        # Top buttons
        top = ttk.Frame(self)
        top.pack(fill="x", padx=12, pady=8)

        ttk.Button(top, text="Import MP3 Files", command=self.add_files).pack(side="left")
        ttk.Button(top, text="Remove Selected", command=self.remove_selected).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(top, text="Clear List", command=self.clear_all).pack(
            side="left", padx=(8, 0)
        )

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

        # Controls row
        ctrls = ttk.Frame(self)
        ctrls.pack(fill="x", padx=12, pady=(0, 6))

        ttk.Label(ctrls, text="Silence between tracks (seconds, 0 = none):").pack(side="left")
        ttk.Entry(ctrls, width=8, textvariable=self.silence_seconds).pack(
            side="left", padx=(6, 14)
        )

        ttk.Checkbutton(
            ctrls,
            text="Always try FAST mode first (auto-fallback on failure)",
            variable=self.fast_first,
        ).pack(side="left", padx=6)

        ttk.Button(ctrls, text="Combine files → M4B", command=self.build).pack(side="right")

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

        # Cover row
        ttk.Label(form, text="Cover image (JPG/PNG):").grid(
            row=4, column=0, sticky="e", padx=5, pady=4
        )
        ttk.Entry(form, textvariable=self.var_cover_path).grid(
            row=4, column=1, sticky="we", padx=5, pady=4
        )
        btns = ttk.Frame(form)
        btns.grid(row=4, column=2, sticky="w", padx=6, pady=4)
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
            title="Select MP3 files", filetypes=[("MP3 audio", "*.mp3")]
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
        self.update_idletasks()

    # ----- cover -----
    def choose_cover(self):
        p = filedialog.askopenfilename(
            title="Select Cover Image (JPG/PNG)",
            filetypes=[("Image", "*.jpg *.jpeg *.png")],
        )
        if not p:
            return
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

    # ----- build -----
    def build(self):
        if not self.files:
            messagebox.showerror("No files", "Please import MP3 files first.")
            return

        out_dir = next_output_dir(Path.home() / "Downloads")
        tmp = out_dir / "build"
        tmp.mkdir(exist_ok=True)

        def write_error(msg: str):
            try:
                (out_dir / "ERROR.txt").write_text(msg, encoding="utf-8")
            except Exception:
                pass

        try:
            # Titles
            pasted = [s.strip() for s in self.chapters_txt.get("1.0", "end").splitlines() if s.strip()]
            auto = [normalize_title(Path(p).stem) for p in self.files]
            titles = pasted if pasted else auto
            if len(titles) < len(self.files):
                titles += auto[len(titles) :]
            if len(titles) > len(self.files):
                titles = titles[: len(self.files)]

            # Silence
            try:
                silence_val = float(self.silence_seconds.get().strip() or "0")
            except ValueError:
                silence_val = 0.0
            silence_ms = int(round(silence_val * 1000))

            if silence_ms > 0:
                self.log("Normalizing to WAV and inserting silence…")
                wavs = normalize_to_wav(self.files, tmp)
                gap = create_silence_wav(silence_val, tmp)
                seq = []
                for i, w in enumerate(wavs):
                    seq.append(w)
                    if i < len(wavs) - 1:
                        seq.append(gap)
                starts_ms, total_ms = compute_audio_starts_with_silence(wavs, silence_ms)
                audio_for_build = seq
                use_safe = True
            else:
                self.log("Using FAST path timings (no silence)…")
                audio_for_build = self.files
                starts_ms, total_ms = compute_starts_total_fast(self.files)
                use_safe = False

            # Output name
            base_name = self.var_title.get().strip() or self.var_album.get().strip() or "audiobook"
            base_name = re.sub(r'[\\/:*?"<>|]+', "_", base_name) or "audiobook"
            out_path = out_dir / f"{base_name}.m4b"

            # Metadata
            meta = {
                "title": base_name,
                "artist": self.var_artist.get().strip(),
                "album_artist": self.var_album_artist.get().strip(),
                "album": self.var_album.get().strip(),
            }

            ffmeta = tmp / "chapters.ffmeta.txt"
            ffmeta.write_text(
                build_ffmetadata_from_starts(titles, starts_ms, meta, total_ms),
                encoding="utf-8",
            )

            # Concat list
            listfile = tmp / "inputs.txt"
            write_concat_list(audio_for_build, listfile)

            cover_path = self.cover_path if (self.cover_path and self.cover_path.exists()) else None

            # Progress
            total_files = len(self.files)
            self.progress["maximum"] = total_files
            self.progress["value"] = 0

            self.status.set("Encoding…")
            self.update_idletasks()

            try:
                if not use_safe and self.fast_first.get():
                    self.log("Trying FAST concat mode…")
                    run_fast_concat(listfile, ffmeta, cover_path, out_path, "128k")
                else:
                    self.log("Using SAFE concat mode…")
                    run_safe_concat(listfile, ffmeta, cover_path, out_path, "128k")
            except subprocess.CalledProcessError:
                if not use_safe:
                    self.log("Fast path failed — retrying in Safe Mode…")
                    wavs = normalize_to_wav(self.files, tmp)
                    write_concat_list(wavs, listfile)
                    starts_ms, total_ms = compute_audio_starts_with_silence(wavs, 0)
                    ffmeta.write_text(
                        build_ffmetadata_from_starts(titles, starts_ms, meta, total_ms),
                        encoding="utf-8",
                    )
                    run_safe_concat(listfile, ffmeta, cover_path, out_path, "128k")
                else:
                    raise

            shutil.rmtree(tmp, ignore_errors=True)
            self.progress["value"] = total_files
            self.status.set(f"Done → {out_path}")
            self.log(f"Created: {out_path}")
            messagebox.showinfo("Success", f"Created:\n{out_path}")

            # open output folder
            try:
                if sys.platform.startswith("darwin"):
                    os.system(f'open "{out_dir}"')
                elif os.name == "nt":
                    os.startfile(out_dir)  # type: ignore[attr-defined]
                elif os.name == "posix":
                    os.system(f'xdg-open "{out_dir}"')
            except Exception:
                pass

        except subprocess.CalledProcessError as e:
            self.status.set("ffmpeg error")
            try:
                stderr = getattr(e, "stderr", None)
                msg = stderr.decode("utf-8") if stderr else str(e)
            except Exception:
                msg = str(e)
            write_error(f"ffmpeg error:\n\n{msg}")
            self.log(f"ffmpeg error: {msg}")
            messagebox.showerror("ffmpeg error", msg)
        except FileNotFoundError as e:
            write_error(f"Missing file(s): {e}")
            self.log(f"Missing file(s): {e}")
            messagebox.showerror("Missing file(s)", str(e))
        except Exception as e:
            self.status.set("Error")
            write_error(f"Unhandled error:\n\n{traceback.format_exc()}")
            self.log(f"Unhandled error: {e}")
            messagebox.showerror("Error", str(e))


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()

