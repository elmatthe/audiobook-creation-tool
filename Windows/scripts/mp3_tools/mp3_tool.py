#!/usr/bin/env python3
# mp3_tool.py
#
# MP3 Tool: combine MP3s, add/remove time at end of tracks, bulk ID3 tagging.
#
# Refactored for the unified launcher: UI is built by build_ui(parent); all
# ffmpeg/ffprobe calls go through shared.subprocess_utils so no console window
# flashes on Windows.
#
# Behavior preserved from v5.7:
# - Write ID3 Tags always outputs to ~/Downloads/edited_mp3s-* (even at delta 0).
# - Keep combined_time-stamps.txt for combined MP3s.
# - Only create ffmpeg_log.txt when an ffmpeg error occurs.
# - Fast-first concat with auto-fallback to safe WAV (and gap insertion).
# - Strip ALL metadata on any new/processed file; only write title, artist,
#   albumartist, album, tracknumber (when you click Write ID3).

import sys
import shlex
from pathlib import Path
from typing import List, Tuple, Optional

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Make the scripts/ root importable so `shared.*` resolves whether this tool is
# run standalone (python mp3_tools/mp3_tool.py) or imported by the launcher.
_SCRIPTS_ROOT = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ROOT))

from shared import ffmpeg_utils
from shared import subprocess_utils as sp

try:
    from mutagen.easyid3 import EasyID3
    from mutagen.mp3 import MP3 as MutagenMP3
except Exception:
    EasyID3 = None
    MutagenMP3 = None

APP_TITLE = "MP3 Tool v5.7 (Fast-first + Auto-fallback)"
BASE_OUTPUT_DIRNAME = "edited_mp3s"

# ---------------------------
# Utilities
# ---------------------------


def ensure_ffmpeg_available() -> bool:
    return ffmpeg_utils.have_ffmpeg()


def run_ff(args: List[str]) -> Tuple[int, str, str]:
    """Run ffmpeg/ffprobe and return (code, stdout, stderr) as text."""
    try:
        from subprocess import PIPE

        p = sp.run(args, stdout=PIPE, stderr=PIPE, text=True)
        return p.returncode, p.stdout, p.stderr
    except Exception as e:
        return 999, "", f"Subprocess failed: {e}"


def save_error_log(folder: Path, title: str, args: List[str], stderr: str):
    """Write (append) a minimal ffmpeg_log.txt only on error."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
        log = folder / "ffmpeg_log.txt"
        with log.open("a", encoding="utf-8") as f:
            f.write(f"\n--- {title} ---\n")
            f.write("CMD: " + " ".join(shlex.quote(a) for a in args) + "\n")
            if stderr:
                f.write(stderr.strip() + "\n")
    except Exception:
        pass


def ffmpeg_escape_listfile_path(p: Path) -> str:
    s = str(p).replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\\n")
    return f"file '{s}'"


def write_concat_listfile(paths: List[Path], listfile: Path):
    with listfile.open("w", encoding="utf-8") as f:
        for p in paths:
            f.write(ffmpeg_escape_listfile_path(p) + "\n")


def next_available_folder(base: Path) -> Path:
    i = 0
    while True:
        cand = base if i == 0 else Path(f"{base}-{i}")
        if not cand.exists():
            cand.mkdir(parents=True, exist_ok=True)
            return cand
        i += 1


def ffprobe_duration_seconds(path: Path) -> Optional[float]:
    code, out, _ = run_ff(
        [
            ffmpeg_utils.ffprobe_cmd(),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
    )
    if code == 0:
        try:
            return float(out.strip())
        except Exception:
            return None
    return None


def seconds_to_hms(sec: float) -> str:
    sec = max(0.0, float(sec))
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec - h * 3600 - m * 60
    return f"{h:02d}:{m:02d}:{s:06.3f}" if h > 0 else f"{m:02d}:{s:06.3f}"


# ---------------------------
# FAST PATH (metadata stripped)
# ---------------------------


def concat_mp3s_fast(listfile: Path, out_mp3: Path, log_dir: Path) -> bool:
    args = [
        ffmpeg_utils.ffmpeg_cmd(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(listfile),
        "-map_metadata",
        "-1",
        "-c:a",
        "libmp3lame",
        "-q:a",
        "2",
        str(out_mp3),
    ]
    code, _, err = run_ff(args)
    if code != 0:
        save_error_log(log_dir, "FAST PATH concat_mp3s_fast", args, err)
    return code == 0


# ---------------------------
# SAFE PATH (WAV normalize + optional gaps)
# ---------------------------


def normalize_to_wav(in_path: Path, out_wav: Path, log_dir: Path) -> bool:
    args = [
        ffmpeg_utils.ffmpeg_cmd(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(in_path),
        "-vn",
        "-sn",
        "-dn",
        "-ac",
        "2",
        "-ar",
        "44100",
        "-sample_fmt",
        "s16",
        str(out_wav),
    ]
    code, _, err = run_ff(args)
    if code != 0:
        save_error_log(log_dir, f"normalize_to_wav: {in_path.name}", args, err)
    return code == 0


def make_silence_wav(seconds: float, out_wav: Path, log_dir: Path) -> bool:
    seconds = max(0.0, float(seconds))
    args = [
        ffmpeg_utils.ffmpeg_cmd(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=44100:cl=stereo",
        "-t",
        f"{seconds:.6f}",
        "-ac",
        "2",
        "-ar",
        "44100",
        "-sample_fmt",
        "s16",
        str(out_wav),
    ]
    code, _, err = run_ff(args)
    if code != 0:
        save_error_log(log_dir, "make_silence_wav", args, err)
    return code == 0


def concat_wavs_to_mp3(listfile: Path, out_mp3: Path, log_dir: Path) -> bool:
    args = [
        ffmpeg_utils.ffmpeg_cmd(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(listfile),
        "-map_metadata",
        "-1",
        "-c:a",
        "libmp3lame",
        "-q:a",
        "2",
        str(out_mp3),
    ]
    code, _, err = run_ff(args)
    if code != 0:
        save_error_log(log_dir, "SAFE PATH concat_wavs_to_mp3", args, err)
    return code == 0


# ---------------------------
# Time edit helpers (always strip metadata)
# ---------------------------


def add_silence_to_mp3(in_mp3: Path, seconds: float, out_mp3: Path, log_dir: Path) -> bool:
    seconds = max(0.0, float(seconds))
    args = [
        ffmpeg_utils.ffmpeg_cmd(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(in_mp3),
        "-f",
        "lavfi",
        "-t",
        f"{seconds:.6f}",
        "-i",
        "anullsrc=r=44100:cl=stereo",
        "-filter_complex",
        "[0:a][1:a]concat=n=2:v=0:a=1[a]",
        "-map",
        "[a]",
        "-map_metadata",
        "-1",
        "-ac",
        "2",
        "-ar",
        "44100",
        "-c:a",
        "libmp3lame",
        "-q:a",
        "2",
        str(out_mp3),
    ]
    code, _, err = run_ff(args)
    if code != 0:
        save_error_log(log_dir, f"add_silence_to_mp3: {in_mp3.name}", args, err)
    return code == 0


def trim_from_end_mp3(in_mp3: Path, seconds_to_remove: float, out_mp3: Path, log_dir: Path) -> bool:
    seconds_to_remove = max(0.0, float(seconds_to_remove))
    dur = ffprobe_duration_seconds(in_mp3) or 0.0
    new_dur = max(0.0, dur - seconds_to_remove)
    args = [
        ffmpeg_utils.ffmpeg_cmd(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(in_mp3),
        "-t",
        f"{new_dur:.6f}",
        "-map_metadata",
        "-1",
        "-ac",
        "2",
        "-ar",
        "44100",
        "-c:a",
        "libmp3lame",
        "-q:a",
        "2",
        str(out_mp3),
    ]
    code, _, err = run_ff(args)
    if code != 0:
        save_error_log(log_dir, f"trim_from_end_mp3: {in_mp3.name}", args, err)
    return code == 0


# ---------------------------
# GUI
# ---------------------------


class MP3ToolUI(ttk.Frame):
    """The MP3 Tool as an embeddable frame."""

    def __init__(self, parent: tk.Misc):
        super().__init__(parent)

        self.file_list: List[Path] = []

        frame = ttk.Frame(self)
        frame.pack(padx=10, pady=10, fill="both", expand=True)

        # Top buttons
        bbar = ttk.Frame(frame)
        bbar.pack(fill="x")
        ttk.Button(bbar, text="Import MP3 Files", command=self.import_files).pack(
            side="left", padx=5
        )
        ttk.Button(bbar, text="Remove Selected", command=self.remove_selected).pack(
            side="left", padx=5
        )
        ttk.Button(bbar, text="Clear List", command=self.clear_list).pack(side="left", padx=5)

        # Listbox
        self.listbox = tk.Listbox(frame, selectmode=tk.EXTENDED, width=80, height=12)
        self.listbox.pack(fill="both", expand=True, pady=8)

        # Gap
        gaprow = ttk.Frame(frame)
        gaprow.pack(fill="x", pady=5)
        ttk.Label(gaprow, text="Silence between tracks (seconds, 0 = none):").pack(side="left")
        self.gap_var = tk.StringVar(value="0")
        ttk.Entry(gaprow, textvariable=self.gap_var, width=8).pack(side="left", padx=5)

        # Fast-first checkbox
        self.fast_first_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            frame,
            text="Always try FAST mode first (auto-fallback on failure)",
            variable=self.fast_first_var,
        ).pack(anchor="w")

        # Combine
        ttk.Button(frame, text="Combine MP3s → One MP3", command=self.combine_mp3s).pack(pady=6)

        # Time edit (applies to ALL files)
        trow = ttk.Frame(frame)
        trow.pack(fill="x", pady=5)
        ttk.Label(trow, text="Add/Remove time at END of each track (seconds):").pack(side="left")
        self.time_delta_var = tk.StringVar(value="0")
        ttk.Entry(trow, textvariable=self.time_delta_var, width=8).pack(side="left", padx=5)
        ttk.Button(trow, text="Apply to All Files", command=self.apply_time_edit).pack(
            side="left", padx=6
        )

        # ID3 group (applies to ALL files)
        grp = ttk.LabelFrame(frame, text="Bulk Edit ID3 Tags (applies to all files)")
        grp.pack(fill="x", pady=10)
        self.id3_title_var = tk.StringVar()
        self.id3_artist_var = tk.StringVar()
        self.id3_albumartist_var = tk.StringVar()
        self.id3_album_var = tk.StringVar()

        # Auto-number UI
        self.auto_number_var = tk.BooleanVar(value=True)  # default ON
        self.start_num_var = tk.StringVar(value="")  # blank -> 1

        ttk.Label(grp, text="Title (blank → filename)").grid(
            row=0, column=0, sticky="e", padx=5, pady=3
        )
        ttk.Entry(grp, textvariable=self.id3_title_var, width=40).grid(
            row=0, column=1, sticky="w", padx=5, pady=3
        )

        ttk.Label(grp, text="Artist").grid(row=1, column=0, sticky="e", padx=5, pady=3)
        ttk.Entry(grp, textvariable=self.id3_artist_var, width=40).grid(
            row=1, column=1, sticky="w", padx=5, pady=3
        )

        ttk.Label(grp, text="Album Artist").grid(row=2, column=0, sticky="e", padx=5, pady=3)
        ttk.Entry(grp, textvariable=self.id3_albumartist_var, width=40).grid(
            row=2, column=1, sticky="w", padx=5, pady=3
        )

        ttk.Label(grp, text="Album").grid(row=3, column=0, sticky="e", padx=5, pady=3)
        ttk.Entry(grp, textvariable=self.id3_album_var, width=40).grid(
            row=3, column=1, sticky="w", padx=5, pady=3
        )

        ttk.Checkbutton(grp, text="Auto-number tracks", variable=self.auto_number_var).grid(
            row=4, column=1, sticky="w", padx=5, pady=(4, 0)
        )
        ttk.Label(grp, text="Start # (blank → 1)").grid(
            row=5, column=0, sticky="e", padx=5, pady=3
        )
        ttk.Entry(grp, textvariable=self.start_num_var, width=40).grid(
            row=5, column=1, sticky="w", padx=5, pady=3
        )

        ttk.Label(grp, text="Chapter titles (one per line):").grid(
            row=6, column=0, sticky="ne", padx=5, pady=3
        )
        self.chapter_titles_text = tk.Text(grp, height=8, width=50, wrap="word")
        self.chapter_titles_text.grid(row=6, column=1, sticky="we", padx=5, pady=3)

        ttk.Button(grp, text="Write ID3 Tags", command=self.write_id3_tags).grid(
            row=7, column=0, columnspan=2, pady=8
        )

        # Status
        self.status = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.status, foreground="blue").pack(pady=8)

        if not ensure_ffmpeg_available():
            self.status.set("WARNING: ffmpeg/ffprobe not found. Run the setup launcher to install it.")

    # ---------- file list ops ----------

    def import_files(self):
        files = filedialog.askopenfilenames(
            title="Select MP3 files", filetypes=[("MP3 files", "*.mp3")]
        )
        if not files:
            return
        added = 0
        for f in files:
            p = Path(f)
            if p not in self.file_list:  # allow multiple batches; skip duplicates
                self.file_list.append(p)
                self.listbox.insert(tk.END, p.name)
                added += 1
        self.status.set(f"Added {added} files. Total: {len(self.file_list)}")

    def remove_selected(self):
        idxs = list(self.listbox.curselection())
        if not idxs:
            return
        for i in sorted(idxs, reverse=True):
            del self.file_list[i]
            self.listbox.delete(i)
        self.status.set(f"Removed {len(idxs)} files. Total: {len(self.file_list)}")

    def clear_list(self):
        self.file_list.clear()
        self.listbox.delete(0, tk.END)
        self.status.set("Cleared file list.")

    # ---------- combine ----------

    def combine_mp3s(self):
        if not self.file_list:
            messagebox.showwarning(APP_TITLE, "Import MP3 files first.")
            return

        try:
            gap = float(self.gap_var.get().strip())
        except Exception:
            messagebox.showwarning(APP_TITLE, "Enter a numeric value for gap seconds.")
            return
        gap = max(0.0, gap)

        out_path = filedialog.asksaveasfilename(
            title="Save combined MP3 as…",
            defaultextension=".mp3",
            initialfile="combined.mp3",
            filetypes=[("MP3 files", "*.mp3")],
        )
        if not out_path:
            return
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        base_out_dir = out_path.parent / BASE_OUTPUT_DIRNAME
        out_dir = next_available_folder(base_out_dir)
        build_dir = out_dir / "build"
        build_dir.mkdir(parents=True, exist_ok=True)

        fast_allowed = (gap == 0.0) and self.fast_first_var.get()

        # FAST PATH
        if fast_allowed:
            self.status.set("FAST mode: concatenating MP3s…")
            self.update_idletasks()
            list_fast = build_dir / "inputs_fast.txt"
            write_concat_listfile(self.file_list, list_fast)
            if concat_mp3s_fast(list_fast, out_path, out_dir):
                self._write_timestamps(self.file_list, gap, out_dir)  # keep timestamps
                self.status.set(f"Done (FAST). Output: {out_path}")
                messagebox.showinfo(APP_TITLE, f"Combine complete.\nOutput: {out_path}")
                return
            else:
                self.status.set("FAST failed — switching to SAFE (WAV normalize)…")
                self.update_idletasks()

        # SAFE PATH
        if self._safe_concat_with_optional_gaps(self.file_list, gap, out_path, out_dir):
            self.status.set(f"Done (SAFE). Output: {out_path}")
            messagebox.showinfo(APP_TITLE, f"Combine complete.\nOutput: {out_path}")
        else:
            messagebox.showerror(
                APP_TITLE, f"FFmpeg failed.\nSee: {out_dir / 'ffmpeg_log.txt'} (if present)"
            )

    def _safe_concat_with_optional_gaps(
        self, mp3s: List[Path], gap_sec: float, out_path: Path, out_dir: Path
    ) -> bool:
        wav_dir = out_dir / "build" / "wavs"
        wav_dir.mkdir(parents=True, exist_ok=True)
        list_safe = out_dir / "build" / "inputs_safe.txt"

        stage_paths: List[Path] = []
        current_time = 0.0
        timestamps: List[str] = []

        for idx, inp in enumerate(mp3s, start=1):
            norm = wav_dir / f"{idx:04d}.wav"
            if not normalize_to_wav(inp, norm, out_dir):
                return False
            stage_paths.append(norm)

            dur = ffprobe_duration_seconds(norm) or 0.0
            timestamps.append(
                f"{idx:02d}. {inp.name} @ {seconds_to_hms(current_time)} (+{seconds_to_hms(dur)})"
            )
            current_time += dur

            if gap_sec > 0.0 and idx < len(mp3s):
                gp = wav_dir / f"{idx:04d}_gap.wav"
                if not make_silence_wav(gap_sec, gp, out_dir):
                    return False
                stage_paths.append(gp)
                current_time += gap_sec

        write_concat_listfile(stage_paths, list_safe)
        ok = concat_wavs_to_mp3(list_safe, out_path, out_dir)

        # Always keep timestamps for combined MP3s
        try:
            with (out_dir / "combined_time-stamps.txt").open("w", encoding="utf-8") as f:
                f.write("\n".join(timestamps))
        except Exception:
            pass

        if ok:
            # Clean big WAVs
            try:
                for p in stage_paths:
                    if p.exists():
                        p.unlink(missing_ok=True)
                (wav_dir).rmdir()
            except Exception:
                pass

        return ok

    def _write_timestamps(self, mp3s: List[Path], gap_sec: float, out_dir: Path):
        current_time = 0.0
        lines = []
        for idx, p in enumerate(mp3s, start=1):
            d = ffprobe_duration_seconds(p) or 0.0
            lines.append(f"{idx:02d}. {p.name} @ {seconds_to_hms(current_time)} (+{seconds_to_hms(d)})")
            current_time += d
            if gap_sec > 0 and idx < len(mp3s):
                current_time += gap_sec
        try:
            with (out_dir / "combined_time-stamps.txt").open("w", encoding="utf-8") as f:
                f.write("\n".join(lines))
        except Exception:
            pass

    # ---------- time edit (ALL files) ----------

    def apply_time_edit(self):
        if not self.file_list:
            messagebox.showwarning(APP_TITLE, "Import MP3 files first.")
            return
        try:
            delta = float(self.time_delta_var.get().strip())
        except Exception:
            messagebox.showwarning(APP_TITLE, "Enter a numeric value (can be negative).")
            return

        out_dir = next_available_folder(Path.home() / "Downloads" / BASE_OUTPUT_DIRNAME)

        ok_count = 0
        for src in self.file_list:
            dst = out_dir / src.name
            if delta > 0:
                ok = add_silence_to_mp3(src, delta, dst, out_dir)
            elif delta < 0:
                ok = trim_from_end_mp3(src, -delta, dst, out_dir)
            else:
                # Copy stream but clear metadata too
                args = [
                    ffmpeg_utils.ffmpeg_cmd(),
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(src),
                    "-map_metadata",
                    "-1",
                    "-c",
                    "copy",
                    str(dst),
                ]
                code, _, err = run_ff(args)
                ok = code == 0
                if not ok:
                    save_error_log(out_dir, f"copy_no_change: {src.name}", args, err)
            ok_count += int(ok)

        self.status.set(f"Time edit complete: {ok_count}/{len(self.file_list)} written to {out_dir}")
        messagebox.showinfo(APP_TITLE, f"Time edit complete.\nOutput folder: {out_dir}")

    # ---------- ID3 (ALL files; ALWAYS outputs to edited_mp3s-*) ----------

    def write_id3_tags(self):
        if EasyID3 is None or MutagenMP3 is None:
            messagebox.showerror(APP_TITLE, "Mutagen not installed. Install with pip: pip install mutagen")
            return
        if not self.file_list:
            messagebox.showwarning(APP_TITLE, "Import MP3 files first.")
            return

        # Parse time delta; if non-zero, time-edit first and tag outputs
        try:
            delta = float(self.time_delta_var.get().strip())
        except Exception:
            delta = 0.0

        title_in = self.id3_title_var.get().strip()
        artist_in = self.id3_artist_var.get().strip()
        albumartist_in = self.id3_albumartist_var.get().strip()
        album_in = self.id3_album_var.get().strip()

        auto_num = self.auto_number_var.get()
        start_raw = self.start_num_var.get().strip()
        try:
            start_num = int(start_raw) if start_raw else 1
        except Exception:
            start_num = 1

        # Chapter titles from multiline box (ignore blank lines)
        chapter_blob = self.chapter_titles_text.get("1.0", "end")
        chapter_titles = [ln.strip() for ln in chapter_blob.splitlines() if ln.strip()]

        # ALWAYS create an output folder for ID3 operations
        out_dir = next_available_folder(Path.home() / "Downloads" / BASE_OUTPUT_DIRNAME)

        # Prepare targets in output folder:
        # - If delta != 0, time-edit into out_dir.
        # - If delta == 0, stream copy with -map_metadata -1 into out_dir.
        targets: List[Path] = []
        if abs(delta) > 1e-9:
            for p in self.file_list:
                dst = out_dir / p.name
                ok = (
                    add_silence_to_mp3(p, delta, dst, out_dir)
                    if delta > 0
                    else trim_from_end_mp3(p, -delta, dst, out_dir)
                )
                targets.append(dst if ok else p)
        else:
            for p in self.file_list:
                dst = out_dir / p.name
                args = [
                    ffmpeg_utils.ffmpeg_cmd(),
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(p),
                    "-map_metadata",
                    "-1",
                    "-c",
                    "copy",
                    str(dst),
                ]
                code, _, err = run_ff(args)
                if code != 0:
                    save_error_log(out_dir, f"copy_for_id3: {p.name}", args, err)
                    targets.append(p)  # fallback
                else:
                    targets.append(dst)

        # Write ONLY allowed tags onto targets
        updated = 0
        total = len(targets)
        for idx, p in enumerate(targets, start=1):
            try:
                m = MutagenMP3(p)
                try:
                    tags = EasyID3(p)
                except Exception:
                    m.add_tags()
                    tags = EasyID3(p)

                # Clear any existing keys (defense-in-depth)
                for k in list(tags.keys()):
                    try:
                        del tags[k]
                    except Exception:
                        pass

                # Title priority: pasted chapter title -> Title field -> filename
                if idx <= len(chapter_titles):
                    title = chapter_titles[idx - 1]
                else:
                    title = title_in if title_in else p.stem
                if title:
                    tags["title"] = title
                if artist_in:
                    tags["artist"] = artist_in
                if albumartist_in:
                    tags["albumartist"] = albumartist_in
                if album_in:
                    tags["album"] = album_in
                if auto_num:
                    tags["tracknumber"] = str(start_num + (idx - 1))

                tags.save()
                updated += 1
            except Exception as e:
                self.status.set(f"ID3 write failed for {p.name}: {e}")

        self.status.set(f"ID3 updated: {updated}/{total} file(s). Output folder: {out_dir}")
        messagebox.showinfo(APP_TITLE, f"ID3 writing complete.\nOutput folder: {out_dir}")


def build_ui(parent: tk.Misc) -> MP3ToolUI:
    """Build the MP3 Tool UI into ``parent`` and return the frame."""
    ui = MP3ToolUI(parent)
    ui.pack(fill=tk.BOTH, expand=True)
    return ui


def main():
    root = tk.Tk()
    root.title(APP_TITLE)
    build_ui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
