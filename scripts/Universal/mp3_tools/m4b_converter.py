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

import gc
import queue
import sys
import threading
import time
from pathlib import Path
from subprocess import PIPE, STDOUT

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Make the scripts/ root importable so `shared.*` resolves whether this tool is
# run standalone (python mp3_tools/m4b_converter.py) or imported by the launcher.
_SCRIPTS_ROOT = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ROOT))

from shared import config as shared_config
from shared import ffmpeg_utils
from shared import job_ui
from shared import metadata
from shared import output_paths
from shared import paths
from shared import settings
from shared import subprocess_utils as sp
from shared import ui_theme
from shared.import_coordination import ImportCoordinator
from shared.importing import (
    IdFactory,
    ImportedFileManager,
    SupportedType,
    SupportedTypeCatalog,
)

APP_TITLE = "M4B Converter v1.0 (Bulk -> MP3)"
DEFAULT_QUALITY = 2  # LAME VBR q scale (0=best, 9=lowest). 2 ~ ~190kbps

# MP3s are delivered into a run folder reserved at conversion start:
# <output base>/M4B-Converter-Outputs/M4B-Converter-N/. The originals (.m4b)
# are only ever read.
TOOL_KEY = "m4b_converter"
SLUG = paths.TOOL_SLUGS[TOOL_KEY]

# settings.json keys. Only the input-dialog location is remembered; the output
# location is not per-tool state — it comes from the effective configuration.
KEY_INPUT_DIR = "m4b_converter.input_dir"

#: How long ``close()`` waits for the conversion worker before giving up.
WORKER_JOIN_TIMEOUT = 5.0


def build_catalog() -> SupportedTypeCatalog:
    """The one type this tool converts (Decision 16A).

    Exactly one entry, so the shared options bar renders exactly one
    ``M4B audiobook`` checkbox — Decision 16A wants individual type
    checkboxes rather than an exclusive choice, and a one-type catalog is
    already that.

    Deliberately **not** widened to ``.m4a``/``.mp4``/generic audio. The
    catalog is the single source of truth for what the file dialog offers
    *and* for what the shared validator will accept, so widening it here
    would quietly widen the whole tool.
    """
    return SupportedTypeCatalog((
        SupportedType("m4b", "M4B audiobook", (".m4b",)),
    ))


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

    def __init__(
        self,
        parent: tk.Misc,
        *,
        clock=None,
        effective_config=None,
        id_factory: IdFactory | None = None,
        scanner=None,
        thread_factory=None,
        choose_files=None,
        choose_folder=None,
        confirm_broad_root=None,
        confirm_large_result=None,
        home=None,
    ):
        """Build the panel.

        Every keyword is a seam the tests drive instead of a real dialog,
        clock or thread — the same injection points the Cover and TTS panels
        already expose. Production passes none of them.
        """
        super().__init__(parent)

        # Cancellation / worker plumbing (mirrors the TTS tool's pattern).
        self._closed = False
        self._worker: threading.Thread | None = None
        self._clock = time.monotonic if clock is None else clock
        self._effective_config = (shared_config.get_effective()
                                  if effective_config is None
                                  else effective_config)
        self._busy = threading.Event()
        self._cancel_event = threading.Event()
        self._log_q: queue.Queue = queue.Queue()

        # Where the next run will go, shown read-only. The numbered run folder
        # itself is reserved atomically when a validated conversion starts
        # (v0.6.0 Drop 2 Phase 4), so building this panel creates nothing and
        # promises no run number. The base is changed in Preferences & Data.
        self.var_outdir = tk.StringVar(value=output_paths.destination_hint(TOOL_KEY))
        # Preferences & Data can change the base while this panel is alive; the
        # shared registry re-points this display the moment that happens.
        output_paths.register_destination_hint(TOOL_KEY, self.var_outdir)
        self._last_run_dir: Path | None = None

        # --- the shared importing foundation --------------------------- #
        # This panel used to own a second input system: a `list[Path]`, its
        # own Listbox, its own three buttons and its own count label, all
        # mutated by list index. That made the visible rows and the queue two
        # separate things that had to be kept in step by hand. The committed
        # ImportedFileManager snapshot is now the only authority, and the
        # shared list is a view of it.
        #
        # One pump owns every scheduled callback here: the import poller
        # rides its `schedule` seam and the conversion worker's queue is
        # registered as a drain, so there is no second `after` loop.
        self._pump = job_ui.MainThreadPump(self)
        self.import_catalog = build_catalog()
        self._manager = ImportedFileManager(id_factory=id_factory)
        self._coordinator = ImportCoordinator(
            self._manager,
            scanner=scanner,
            clock=self._clock,
            id_factory=id_factory,
            # Handed to the coordinator, not the adapter: it is asked
            # *before* a thread exists, so declining starts no worker.
            confirm_broad_root=(self._confirm_broad_root
                                if confirm_broad_root is None
                                else confirm_broad_root),
            thread_factory=thread_factory,
            **({} if home is None else {"home": home}),
        )
        self.importer = job_ui.ImportAdapter(
            self,
            catalog=self.import_catalog,
            effective_config=self._effective_config,
            pump=self._pump,
            manager=self._manager,
            coordinator=self._coordinator,
            # No theme bundle: this panel stays classic. Converting it to the
            # namespaced design system is Plan 9's job, and an empty style
            # name is what ttk means by "draw this the platform's way".
            theme=None,
            clock=self._clock,
            id_factory=id_factory,
            choose_files=(self._choose_files if choose_files is None
                          else choose_files),
            choose_folder=(self._choose_folder if choose_folder is None
                           else choose_folder),
            confirm_large_result=(self._confirm_large_result
                                  if confirm_large_result is None
                                  else confirm_large_result),
            # Six rows, not ten: at the supported 920x600 minimum the panel
            # asks for more height than the host has, and `pack` hands out
            # requested height in order, so every row added here is taken
            # from the run area at the bottom. Six keeps the `Convert`
            # button at its full height there while still showing a useful
            # list; the list still expands on a larger window.
            list_height=6,
        )
        self.importer.frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True,
                                 padx=10, pady=(10, 0))

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

        # Output destination (read-only; the base lives in Preferences & Data)
        row += 1
        ttk.Label(options, text="Output folder:").grid(
            row=row, column=0, sticky="e", padx=8, pady=4
        )
        self.entry_outdir = ttk.Entry(options, textvariable=self.var_outdir,
                                      state="readonly")
        self.entry_outdir.grid(row=row, column=1, columnspan=3, sticky="we", padx=8, pady=4)

        row += 1
        ttk.Label(
            options,
            text="Each conversion gets its own numbered run folder here. "
                 "Change the location in Preferences & Data.",
        ).grid(row=row, column=1, columnspan=3, sticky="w", padx=8, pady=(0, 4))

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

        # Progress (bar + files-done/percentage label; updated only from the
        # main-thread queue pump)
        self.progress = ui_theme.ProgressIndicator(self, length=400)
        self.progress.frame.pack(side=tk.BOTTOM, pady=(0, 10))

        for i in range(4):
            options.grid_columnconfigure(i, weight=1)

        # Initial checks (log instead of a modal so switching tools is quiet)
        if not ffmpeg_utils.have_ffmpeg():
            self.log_write(
                "WARNING: ffmpeg/ffprobe not found. Run the setup launcher to install it.\n"
            )
        else:
            self.log_write("FFmpeg detected.\n")

        # One pump, one scheduled chain: the conversion queue is a drain on
        # the same pump the import poller rides. No second `after` loop.
        self._pump.add_drain(self._pump_queue)
        self._pump.start()

    # ------- UI callbacks -------

    # ------- shared-importer seams (main thread, before any worker) -------

    @property
    def manager(self) -> ImportedFileManager:
        """The one authority on what has been imported."""
        return self._manager

    def imported_files(self) -> list[Path]:
        """The committed queue, in order. Derived on demand, never stored."""
        return [entry.path for entry in self._manager.snapshot().files]

    def _choose_files(self):
        """The Add Files dialog. The dialog's order is the order, and it is kept.

        The remembered input directory survives adoption because this
        callback is the panel's own: it can read and write
        ``m4b_converter.input_dir`` without the shared adapter knowing
        anything about settings.
        """
        chosen = tuple(filedialog.askopenfilenames(
            parent=self,
            title="Select .m4b files",
            initialdir=str(_remembered_dir(KEY_INPUT_DIR)),
            filetypes=[("M4B Audiobooks", "*.m4b"), ("All files", "*.*")],
        ) or ())
        if chosen:
            settings.set(KEY_INPUT_DIR, str(Path(chosen[0]).parent))
        return chosen

    def _choose_folder(self):
        """The Add Folder dialog. One root, as the tuple the seam wants."""
        chosen = filedialog.askdirectory(
            parent=self,
            title="Select a folder of .m4b files",
            initialdir=str(_remembered_dir(KEY_INPUT_DIR)),
            mustexist=True,
        )
        if not chosen:
            return ()
        settings.set(KEY_INPUT_DIR, str(chosen))
        return (str(chosen),)

    def _confirm_broad_root(self, roots) -> bool:
        """Asked before a scan thread exists, so declining starts no worker."""
        listed = "\n".join(str(entry) for entry in roots)
        return job_ui.ask_confirm(
            self,
            "Scan a very broad folder?",
            "This covers a whole drive or your home folder:\n\n"
            f"{listed}\n\nScanning it can take a long time. Continue?",
        )

    def _confirm_large_result(self, outcome) -> bool:
        """Answered after the scan and before anything is committed."""
        return job_ui.ask_confirm(
            self,
            "Add a large number of audiobooks?",
            f"{outcome.proposed_count:,} audiobooks are ready to be added.\n\n"
            "Adding this many at once can make the list slow to work with. "
            "Add them?",
        )

    def output_dir(self) -> Path:
        """The last reserved run, or this tool's parent folder before any run."""
        if self._last_run_dir is not None:
            return self._last_run_dir
        return Path(self.var_outdir.get().strip())

    def open_outdir(self):
        """Reveal the actual reserved run, or the tool folder before any run."""
        try:
            target = (self._last_run_dir if self._last_run_dir is not None
                      else output_paths.ensure_tool_parent(TOOL_KEY))
        except output_paths.OutputPathError as exc:
            messagebox.showerror("Output folder", exc.message)
            return
        sp.reveal_in_file_manager(target)

    def start_convert(self):
        if self._busy.is_set():
            return
        # Exactly one committed snapshot, read here on the main thread. Its
        # order is the run's order, and because it is immutable a later
        # import, removal or reorder cannot reach a conversion already under
        # way.
        snapshot = self._manager.snapshot()
        imported = tuple(snapshot.files)
        if not imported:
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
            # The frozen occurrences themselves, not a reduced list of paths:
            # provenance (source root, root-relative path, occurrence id) is
            # already what Phase 8's output planning needs, and discarding it
            # here only to re-derive it later is how it goes missing.
            "imported_files": imported,
        }

        # Every input is validated above; only now is a run directory reserved.
        try:
            reservation = output_paths.reserve_run_directory(TOOL_KEY)
        except output_paths.OutputPathError as exc:
            messagebox.showerror("Output folder", exc.message)
            self.log_write(f"Output folder unavailable: {exc.message}\n")
            return
        outdir = reservation.run_directory
        self._last_run_dir = outdir
        self.var_outdir.set(str(outdir))
        params["planner"] = reservation.planner()
        self.log_write(f"Output folder: {outdir}\n")

        self._busy.set()
        self._cancel_event.clear()
        self.progress.update(0, len(imported))
        self.disable_inputs(True)
        self.btn_cancel.configure(state=tk.NORMAL)

        t = threading.Thread(
            target=self.convert_worker, args=(outdir, params), daemon=True
        )
        self._worker = t
        t.start()

    def cancel(self):
        if not self._busy.is_set() or self._cancel_event.is_set():
            return
        self._cancel_event.set()
        self.btn_cancel.configure(state=tk.DISABLED)
        self._log_q.put(("log", "Cancelling… will stop after the current file.\n"))

    def disable_inputs(self, state: bool):
        # The shared components own their own enablement, so they are locked
        # through the shared seam rather than by poking at their widgets.
        # This is the narrow importer lock only — Plan 9 owns the full job
        # lock matrix.
        self.importer.set_locked(state)
        widgets = [
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
        # The destination display is never typeable; it only greys out.
        self.entry_outdir.configure(state=tk.DISABLED if state else "readonly")

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
                    self.log_write(payload[0])
                    self._finish_idle()
                    if payload[1] is not None:
                        sp.reveal_in_file_manager(payload[1])
        except queue.Empty:
            pass

    def _finish_idle(self):
        self._busy.clear()
        self._cancel_event.clear()
        self.disable_inputs(False)
        self.btn_cancel.configure(state=tk.DISABLED)

    # ------- conversion (worker thread) -------

    def convert_worker(self, outdir: Path, params: dict):
        # Derived here, inside the run boundary, from the frozen
        # occurrences. This tuple is a local of one conversion, not panel
        # state — reviving a `self.files` here would rebuild exactly the
        # shadow queue Phase 7B removed.
        imported = params["imported_files"]
        files = tuple(entry.path for entry in imported)
        planner = params["planner"]
        total = len(files)
        cancelled = False

        for idx, in_file in enumerate(files, start=1):
            if self._cancel_event.is_set():
                cancelled = True
                break
            try:
                # One batch-scoped planner per reservation: duplicate stems
                # from different folders get -1/-2 instead of overwriting.
                out_mp3 = planner.plan(f"{in_file.stem}.mp3")
                output_paths.assert_not_input(out_mp3, files)
                # The written stem, which is what the fallback title uses.
                stem = out_mp3.stem

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
                self._log_q.put(("progress", (idx, total)))

        if cancelled:
            self._log_q.put(("done", (f"\nCancelled. Output so far: {outdir}\n", outdir)))
        else:
            self._log_q.put(("done", (f"\nAll done. Output: {outdir}\n", outdir)))


    # ------- lifecycle -------

    def close(self):
        """Close the import side and stop the pump. Idempotent, and safe late.

        The conversion worker is asked to stop first, so the bounded join
        below meets a thread already unwinding rather than one still working
        through a long book. Closing the adapter cancels any running scan and
        joins its worker inside the coordinator's own bounded timeout;
        closing the pump cancels the outstanding callback and forgets every
        drain. Nothing is left scheduled.
        """
        if self._closed:
            return
        self._closed = True
        if self._busy.is_set():
            self._cancel_event.set()
        worker = self._worker
        if worker is not None and hasattr(worker, "join"):
            worker.join(WORKER_JOIN_TIMEOUT)
        self._worker = None
        importer = getattr(self, "importer", None)
        if importer is not None:
            importer.close()
        pump = getattr(self, "_pump", None)
        if pump is not None:
            pump.close()

    def destroy(self):
        """Tear the panel down and finish the teardown on this thread.

        The explicit collection is the discipline the Cover panel already
        uses: destroying the shared job widgets leaves Tk variables in
        reference cycles, and a Tk variable finalized on some other thread
        raises "main thread is not in main loop" inside whatever unrelated
        code happened to be running.
        """
        self.close()
        super().destroy()
        gc.collect()


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
