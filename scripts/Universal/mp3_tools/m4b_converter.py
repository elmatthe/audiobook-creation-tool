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
#
# v0.6.2 Plan 5 Phase 7B: the shared ImportedFileManager became the only
# input authority. Phase 8: every destination is planned at Start from the
# provenance that snapshot keeps. Phase 9: the shared job-control foundation
# became the only authority on run state and the only reporting pipeline --
# one JobController, one JobReporter, one JobEventStream, one JobAdapter and
# one EtaEstimator per run, all drained on the panel's single MainThreadPump.
# Pause and cancel settle between books, because the ffmpeg call converting
# one is indivisible; the process lifecycle that makes cancel act mid-file is
# Phase 11's, and nothing here claims to have it.

import gc
import queue
import sys
import threading
import time
from dataclasses import dataclass
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
from shared import job_control
from shared import job_ui
from shared import metadata
from shared import output_paths
from shared import paths
from shared import settings
from shared import subprocess_utils as sp
from shared.cancellation import ConversionCancelled
from shared.import_coordination import ImportCoordinator
from shared.importing import (
    IdFactory,
    ImportedFileManager,
    SupportedType,
    SupportedTypeCatalog,
)
from shared.job_control import (
    FailureLog,
    FailureRecord,
    JobState,
    RunResult,
    capture_run,
)

from . import m4b_destinations

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

#: The one stage this phase's worker reports. Whole-book conversion is a single
#: stage today; the probe and per-segment stages belong to Phases 10 and 11 and
#: are deliberately not named here, because a stage nothing enters is a lie the
#: Summary would have to tell.
STAGE_CONVERT = "convert"

#: The ETA's unit of comparable work **at this phase**: one imported book, from
#: the moment its conversion begins to the moment its output is accepted. When
#: Phase 10 makes the segment the unit, the category changes with it and the
#: shared estimator drops the incomparable history by itself — which is exactly
#: why the unit is named rather than assumed.
ETA_CATEGORY = "book"

#: The run id the shared controls carry before anything has been started, so the
#: panel has a Pause/Cancel bar, a progress line and a Summary from the moment it
#: is built. Every real run replaces it with its own frozen snapshot id.
IDLE_RUN_ID = "m4b-idle"

#: The queue message that hands a settled run back to the main thread, and the one
#: that carries a finished book's measured duration. Both travel on the panel's
#: existing worker queue beside "log", "progress" and "done". Neither is a second
#: event vocabulary: the run's *events* go through the shared stream, and nothing
#: here duplicates them.
RESULT_MESSAGE = "result"
TIMING_MESSAGE = "timing"


@dataclass(frozen=True)
class TimingSample:
    """How long one finished book actually took, as plain immutable data.

    The estimate itself lives in one :class:`~shared.job_control.EtaEstimator`
    that the shared job adapter reads, and that object is compound mutable state
    belonging to the thread that owns the widgets. So the worker does not touch
    it: it measures a duration with the run's injected clock and sends *this* --
    four immutable fields and nothing live -- through the queue the main thread
    already drains.

    ``run_id`` and ``attempt`` are what make a late sample inert. The run id alone
    is not enough, because a retry re-runs the *same* frozen snapshot and carries
    the same id; the attempt number tells one attempt's leftovers from the attempt
    now running. Phase 13 owns Retry Failed, but the field costs nothing now and
    inventing it later would mean re-auditing every sample that had been recorded
    without it.
    """

    run_id: str
    attempt: int
    category: str
    duration: float


def freeze_m4b_options(
    quality: int,
    write_tags: bool,
    title: str,
    artist: str,
    album_artist: str,
    album: str,
    do_track: bool,
    start_num: int,
) -> dict:
    """Every output-affecting Converter setting, as plain immutable scalars.

    Handed to ``capture_run``, which deep-freezes it and refuses a widget, a Tk
    variable, a callable or anything else live. Reading the widgets happens once,
    on the main thread, in :meth:`M4BConverterUI.start_convert`; this only shapes
    what was read.
    """
    return {
        "quality": int(quality),
        "write_tags": bool(write_tags),
        "title": str(title),
        "artist": str(artist),
        "album_artist": str(album_artist),
        "album": str(album),
        "do_track": bool(do_track),
        "start_num": int(start_num),
    }


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
        bridge=None,
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
        # Kept, deliberately. The **shared controller** is the authority on job
        # state from this phase on -- this is not a second state machine but the
        # low-level stop latch: `close()` sets it before a controller may exist,
        # and Phase 11's subprocess loop still needs a primitive it can poll
        # while an ffmpeg child is running. The worker never *decides* anything
        # from it while a controller is present; it mirrors it into the
        # controller and lets `checkpoint()` decide.
        self._cancel_event = threading.Event()
        self._log_q: queue.Queue = queue.Queue()

        # --- the shared job-control foundation ------------------------- #
        # One run, one controller, one event stream, one estimate. None of them
        # can be rebound, so a new run gets new ones and the retired adapter is
        # closed rather than reused.
        self._run_count = 0
        self._attempt = 0
        self._controller = None
        self._reporter = None
        self._estimator = None
        self._snapshot = None
        self._result = None
        self._bridge = job_control.LoggerBridge() if bridge is None else bridge
        self._event_q: queue.Queue = queue.Queue()

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
        # Rows, weights, and why the geometry manager changed here.
        #
        # `pack` hands out requested height in declaration order and clips
        # whatever is left over at the *end*. That was survivable while the run
        # area was one progress bar; Phase 9 adds the shared control bar, the
        # status line and Summary/Details below the action, so under `pack` they
        # would be the first things to fall off a 920x600 window -- Pause and
        # Cancel included. `grid` with explicit weights puts the shortfall where
        # it belongs instead: a weight-0 row always gets its requested height,
        # and the weighted rows give up space in proportion to their weight.
        #
        # So the two rows that cannot usefully shrink are pinned -- the options
        # form, where every entry has to stay reachable, and the `Convert`
        # action -- and the three that scroll absorb a short window: the
        # imported list, the run area (whose own Summary/Details row is the
        # flexible one inside it) and the log.
        #
        # This is layout mechanics, not a redesign: no colour, no font, no style
        # name and no control changed, and the panel stays classic.
        # The four numbers below were measured, not guessed: seven weightings
        # were laid out at 920x600, 1024x720 and 1280x900 and the mapped height
        # of every control and every scrollable view read off the live window.
        # This one keeps all three views usable at the 1024x720 default
        # (list 53 px, Summary 44 px, log 20 px) and gives the Summary a real
        # line at the 920x600 minimum, where the panel's content genuinely
        # exceeds the window whatever the weights are.
        self.rowconfigure(0, weight=4)   # imported queue -- scrolls
        self.rowconfigure(1, weight=0)   # conversion & metadata -- pinned
        self.rowconfigure(2, weight=0)   # Convert -- pinned
        self.rowconfigure(3, weight=2)   # shared run controls, progress, Summary
        self.rowconfigure(4, weight=4)   # run log -- the transcript, not the tool
        self.columnconfigure(0, weight=1)

        self.importer.frame.grid(row=0, column=0, sticky="nsew",
                                 padx=10, pady=(10, 6))

        # Options area
        options = ttk.LabelFrame(self, text="Conversion & Metadata (applies to all files)")
        options.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 6), ipady=4)

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

        # Start, and the navigation that is never a processing input.
        #
        # The panel's own `Cancel` button is **retired here**, not duplicated:
        # Pause, Resume, Cancel and Retry Failed belong to the shared control bar
        # below, which offers each of them exactly when the approved availability
        # rules say it is meaningful. Two Cancel buttons for one cooperative
        # request is precisely the parallel authority this phase removes.
        # :meth:`cancel` survives as the method that bar calls.
        action = ttk.Frame(self)
        action.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 6))
        self.btn_convert = ttk.Button(action, text="Convert M4Bs → MP3s", command=self.start_convert)
        self.btn_convert.pack(side=tk.LEFT)
        self.btn_open_out = ttk.Button(action, text="Open Output Folder", command=self.open_outdir)
        self.btn_open_out.pack(side=tk.LEFT, padx=8)

        # The shared run controls, the progress bar, the estimate and
        # Summary/Details all live here. The adapter is rebuilt for each run --
        # one run, one event stream, one estimate -- so this container is what
        # holds its place in the layout.
        self.job_area = ttk.Frame(self)
        self.job_area.grid(row=3, column=0, sticky="nsew", padx=10, pady=(0, 6))

        # The panel's own run log, unchanged in kind. It is the raw transcript of
        # what the worker did -- the ffmpeg command line, the per-file lines, the
        # error text. Summary and Details above are the shared *projections* of
        # the run's events, and neither is a copy of the other.
        logf = ttk.LabelFrame(self, text="Log")
        logf.grid(row=4, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.log = tk.Text(logf, height=4, wrap="word")
        self.log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb2 = ttk.Scrollbar(logf, orient="vertical", command=self.log.yview)
        sb2.pack(side=tk.RIGHT, fill=tk.Y)
        self.log.configure(yscrollcommand=sb2.set)

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
        # the same pump the import poller rides, and so is the shared job
        # adapter's event drain -- the adapter registers itself on this very
        # pump rather than scheduling anything of its own. No second `after`
        # loop, and no timer.
        self._pump.add_drain(self._pump_queue)
        self._install_jobs(IDLE_RUN_ID, ())
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

    # ------- the run: what it is, and who is driving it -------

    @property
    def run_snapshot(self):
        """The frozen configuration of the current or most recent run, if any."""
        return self._snapshot

    @property
    def run_result(self):
        """How the most recent run was settled, or ``None`` before the first.

        Recorded, and deliberately **not** handed to the shared adapter yet. See
        :meth:`_settle`: offering Retry Failed before Phase 13 can execute one
        would be a button that promises work this phase cannot do.
        """
        return self._result

    @property
    def job_controller(self):
        """The cooperative controller of the current run, or ``None``."""
        return self._controller

    @property
    def job_estimator(self):
        """The current run's rolling estimate, or ``None`` before the first run."""
        return self._estimator

    def _install_jobs(self, run_id: str, item_ids) -> None:
        """Point the shared run controls at one run. Main thread only.

        A run owns its event stream and its estimate, and neither can be rebound,
        so a new run gets a new adapter in the same container. The retired one is
        closed first, and closing is what drops its drain -- so the one pump keeps
        exactly one job drain however many runs a session performs.

        ``on_retry`` is deliberately absent. Phase 13 owns Retry Failed; until it
        exists the control is rendered by the shared bar and stays unavailable,
        because the adapter is never handed a settled result to make it available
        and there is no callback behind it either.
        """
        previous = getattr(self, "jobs", None)
        if previous is not None:
            previous.close()
            previous.frame.destroy()
        self._event_q = queue.Queue()
        self._estimator = job_control.EtaEstimator(run_id, clock=self._clock)
        self.jobs = job_ui.JobAdapter(
            self.job_area,
            run_id=run_id,
            pump=self._pump,
            # No theme bundle: this panel stays classic until Plan 9 converts it.
            theme=None,
            pull=job_ui.queue_pull(self._event_q),
            estimator=self._estimator,
            bridge=self._bridge,
            item_ids=item_ids,
            on_pause=self.pause,
            on_resume=self.resume,
            on_cancel=self.cancel,
            details_height=4,
        )
        self.jobs.frame.pack(fill=tk.BOTH, expand=True)
        # One progress model, not two: the panel's indicator *is* the shared
        # status view's, so nothing can draw a second, disagreeing bar.
        self.progress = self.jobs.status.indicator
        self.jobs.register_inputs(self.importer)
        self.jobs.register_options(self)
        self.jobs.render()

    def _publish(self, event) -> None:
        """Hand one produced event to the queue the shared adapter drains.

        Called from whichever thread produced it -- the worker for progress and
        failures, the main thread for a button press that moved the controller.
        A queue is the only thing that crosses that boundary; no widget is ever
        touched from the worker, not even for progress.
        """
        self._event_q.put(event)

    def _on_state(self, snapshot) -> None:
        """The controller's listener: copy its state into the event stream.

        The reporter mints the event *from this snapshot*, so the UI can never
        show a state the controller did not actually reach -- a ``PAUSED`` no
        worker acknowledged is not merely avoided here, it is unconstructible.
        """
        reporter = self._reporter
        if reporter is not None:
            reporter.state_changed(snapshot)

    def pause(self) -> None:
        """Ask the run to pause at its next safe checkpoint.

        Truthful by construction. This reaches ``PAUSE_REQUESTED`` and stops
        there, which is what the status line shows; only the worker, arriving
        between two books, can make it ``PAUSED``. The ffmpeg call converting the
        current book is indivisible and is **not** suspended, frozen, killed or
        restarted -- Decision 38A, and nothing here claims otherwise.
        """
        controller = self._controller
        if controller is not None:
            controller.request_pause()

    def resume(self) -> None:
        """Return a paused or pausing run to running and wake its worker."""
        controller = self._controller
        if controller is not None:
            controller.resume()

    def set_locked(self, locked: bool) -> None:
        """The shared lock matrix's hook onto this panel's own option controls."""
        self.disable_inputs(bool(locked))

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

        # Phase 8: every destination is decided here, on the main thread,
        # from the provenance Phase 7B retained — before any work starts and
        # while the queue is still the frozen snapshot. One planner from the
        # reservation serves the whole run, so a directly chosen book and a
        # folder-imported one can never plan onto the same path.
        #
        # Whole-book mode asks for exactly one name per occurrence. The seam
        # already accepts many, which is what split mode will need, but this
        # phase deliberately does not probe chapters to produce them.
        try:
            planned = m4b_destinations.plan_outputs(
                imported,
                {entry.occurrence_id: (f"{entry.path.stem}.mp3",)
                 for entry in imported},
                run_root=outdir,
                planner=reservation.planner(),
            )
        except output_paths.OutputPathError as exc:
            messagebox.showerror("Output folder", exc.message)
            self.log_write(f"Output could not be planned: {exc.message}\n")
            return

        self._last_run_dir = outdir
        self.var_outdir.set(str(outdir))
        params["destinations"] = {
            item.occurrence_id: item.destinations for item in planned}
        self.log_write(f"Output folder: {outdir}\n")

        # Decision 9A, in one call: the imported list, the catalog, the import
        # options, the effective configuration and every output-affecting
        # setting are copied here, on the main thread, and never consulted
        # again. The already-committed ``snapshot`` is passed rather than the
        # manager, so this freezes the *same* queue the destinations above were
        # planned from -- taking a second snapshot here is how one run would end
        # up using two configurations.
        self._run_count += 1
        run = capture_run(
            snapshot_id=f"m4b-run-{self._run_count}",
            files=snapshot,
            catalog=self.import_catalog,
            import_options=self.importer.options.options(),
            effective_config=self._effective_config,
            tool_options=freeze_m4b_options(
                quality,
                params["write_tags"],
                params["title"],
                params["artist"],
                params["album_artist"],
                params["album"],
                params["do_track"],
                params["start_num"],
            ),
            created_at=float(self._clock()),
        )
        self._snapshot = run
        self._result = None
        self._attempt += 1
        # The shared controller is this run's one state authority. Its listener
        # copies every state it actually reaches into the event stream, so the
        # panel keeps no rival state machine beside it.
        self._controller = job_control.JobController(
            run.snapshot_id, listener=self._on_state)
        self._install_jobs(run.snapshot_id, run.item_ids)
        self._reporter = job_control.JobReporter.for_run(
            run, clock=self._clock, publish=self._publish)

        params.update({
            "snapshot": run,
            "controller": self._controller,
            "reporter": self._reporter,
            # Timing travels back as data, never as a shared estimator: the
            # worker is handed the clock and the two labels it needs to stamp a
            # measurement, and nothing it can mutate.
            "clock": self._clock,
            "run_id": run.snapshot_id,
            "attempt": self._attempt,
        })

        self._busy.set()
        self._cancel_event.clear()
        self._controller.start()
        self._reporter.output_location(outdir)
        # The truthful interim denominator: **one unit per imported
        # occurrence**, which is exactly what this phase's whole-book worker
        # knows. Phase 10 replaces it with the immutable plan's
        # ``total_segments`` once chapters have actually been probed; nothing
        # here pretends that number exists yet.
        self._reporter.progress(0, len(imported), stage=STAGE_CONVERT)
        self.disable_inputs(True)

        t = threading.Thread(
            target=self.convert_worker, args=(outdir, params), daemon=True
        )
        self._worker = t
        t.start()

    def cancel(self):
        """Ask the run to stop. Cooperative: nothing is suspended or killed.

        At this phase the request settles at the **next boundary between
        books**, because the ffmpeg call converting the current one is
        indivisible and this phase does not own its process lifecycle. Phase 11
        owns real mid-file termination and reaping; until then the status line
        says ``Cancelling…`` and means exactly that.

        What it does guarantee now: no later book starts, and a worker already
        waiting at a paused checkpoint is woken, because cancel outranks pause
        in the shared model.
        """
        if not self._busy.is_set() or self._cancel_event.is_set():
            return
        self._cancel_event.set()
        controller = self._controller
        if controller is not None:
            controller.request_cancel()
        self._log_q.put(("log", "Cancelling… will stop after the current file.\n"))

    def disable_inputs(self, state: bool):
        """Lock or unlock this panel's inputs and processing options.

        **Which states lock is not decided here.** The approved shared matrix
        decided it, and the shared lock group calls this through
        :meth:`set_locked` whenever the run moves -- so there is no second lock
        matrix and no per-widget rule about *when*. It stays callable directly
        because locking is also what stops a **new** import starting mid-run,
        which is a moment the job state alone does not describe.

        The imported list and the import options lock as one unit through the
        adapter. The import **status** bar deliberately does not: a scan that
        was already running when a conversion started can still be cancelled,
        and that cancellation reaches the coordinator only -- never this panel's
        processing cancel.
        """
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
        """Drain the worker transcript queue. Registered once, on the one pump.

        The run's *events* do not come through here -- they ride the shared
        stream, which the job adapter drains on this same pump. What travels on
        this queue is the raw transcript, the settled result and one measured
        duration per finished book.
        """
        try:
            while True:
                kind, payload = self._log_q.get_nowait()
                if kind == "log":
                    self.log_write(payload)
                elif kind == "progress":
                    # Only a run with no reporter reports this way; a real run's
                    # progress is a shared event and is drawn from the stream.
                    self.progress.update(*payload)
                elif kind == TIMING_MESSAGE:
                    self._record_timing(payload)
                elif kind == RESULT_MESSAGE:
                    self._settle(payload)
                elif kind == "done":
                    self.log_write(payload[0])
                    self._finish_idle()
                    if payload[1] is not None:
                        sp.reveal_in_file_manager(payload[1])
        except queue.Empty:
            pass

    def _record_timing(self, sample) -> bool:
        """Apply one measured duration to this run's estimate. Main thread only.

        Reached only from the drain above, which the one pump calls on the
        thread that owns the widgets -- so this is the single place any
        estimator is ever mutated, and the worker never holds one at all.

        A sample is dropped, inertly, if the panel has closed, if it belongs to
        a run this panel has moved on from, or if it belongs to an earlier
        attempt of the same run. None of those is an error.
        """
        if self._closed:
            return False
        estimator = self._estimator
        if estimator is None:
            return False
        if sample.run_id != estimator.run_id or sample.attempt != self._attempt:
            return False
        return estimator.record(sample.category, sample.duration) is not None

    def _settle(self, result) -> None:
        """Record how the run was settled. Main thread only.

        The result is the shared authority on what succeeded, what failed and
        what was never attempted, and this panel keeps no rival tally beside it.

        **It is deliberately not handed to the shared adapter yet.** Doing so is
        what makes Retry Failed available, and Phase 13 owns retry execution:
        an enabled control that cannot re-run anything would be a promise this
        phase cannot keep. Phase 13 adds the ``set_result`` call and the
        ``on_retry`` callback together, against this same real result -- no
        fabricated plan is needed then and none is invented now.
        """
        self._result = result

    def _finish_idle(self):
        self._busy.clear()
        self._cancel_event.clear()
        self.disable_inputs(False)

    # ------- conversion (worker thread) -------

    def convert_worker(self, outdir: Path, params: dict):
        # Derived here, inside the run boundary, from the frozen
        # occurrences. This tuple is a local of one conversion, not panel
        # state — reviving a `self.files` here would rebuild exactly the
        # shadow queue Phase 7B removed.
        imported = params["imported_files"]
        files = tuple(entry.path for entry in imported)
        # Phase 8: destinations were planned at Start from each occurrence's
        # provenance. The worker looks them up by occurrence id rather than
        # planning its own, so placement cannot depend on execution order and
        # a retry cannot land somewhere new.
        destinations = params["destinations"]
        # Phase 9: the run's control and reporting arrive as params, and every
        # one of them is optional so this same body still runs a plain,
        # unreported batch when it is handed one. Nothing Tk-shaped is here:
        # what the worker says goes out through the panel's queue and the run's
        # reporter, and it holds no estimator, no widget and no variable.
        controller = params.get("controller")
        reporter = params.get("reporter")
        snapshot = params.get("snapshot")
        clock = params.get("clock")
        run_id = params.get("run_id")
        attempt = params.get("attempt", 0)
        timed = clock is not None and run_id is not None
        total = len(files)
        cancelled = False
        completed: list = []
        failures: list = []

        for idx, entry in enumerate(imported, start=1):
            in_file = entry.path
            item_id = entry.occurrence_id
            # The one safe checkpoint this phase honestly has, and it sits
            # **between books**. A pause asked for while ffmpeg is converting
            # one is honoured here, not there: that call is indivisible and is
            # never suspended, frozen or restarted (Decision 38A). Cancel is
            # settled here too, which is the current limitation -- Phase 11 owns
            # real mid-file termination and reaping.
            #
            # The cancel latch is mirrored *into* the controller rather than
            # acted on directly, so `checkpoint()` remains the single place that
            # decides what a request means.
            if controller is not None:
                if self._cancel_event.is_set():
                    controller.request_cancel()
                try:
                    controller.checkpoint()
                except ConversionCancelled:
                    cancelled = True
                    break
            elif self._cancel_event.is_set():
                cancelled = True
                break

            succeeded = False
            if reporter is not None:
                reporter.current_item(item_id, f"Converting {in_file.name}")
            # The measurement brackets this book's own work and nothing else.
            # Time the message then spends waiting in the queue is outside the
            # bracket, so a slow drain is never mistaken for a slow book.
            started = clock() if timed else None
            try:
                out_mp3 = destinations[entry.occurrence_id][0]
                # Already checked when the run was planned; re-checked here
                # because this is the last moment before ffmpeg is told to
                # write, and a source that has since moved must not be hit.
                output_paths.assert_not_input(out_mp3, files)
                # A mirrored destination lives under folders that the
                # reservation did not create.
                out_mp3.parent.mkdir(parents=True, exist_ok=True)
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
                    if reporter is not None:
                        # A user-level warning belongs in the Summary; the reason
                        # it was reached belongs in Details and the session log.
                        reporter.warning(
                            f"{in_file.name}: this ffmpeg build has no xHE-AAC "
                            "decoder on this platform, so the output may be sped "
                            "up or choppy.",
                            f"codec={info.get('codec_name')!r} "
                            f"profile={info.get('profile')!r}; "
                            "no input decoder argument was available")

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
                command_line = " ".join(str(c) for c in cmd)
                self._log_q.put(("log", "  ffmpeg: " + command_line + "\n"))
                if reporter is not None:
                    # Technical detail: Details and the session log read it, and
                    # the Summary structurally cannot, because a summary line is
                    # never built from a `detail` field.
                    reporter.technical(f"[{idx}/{total}] {command_line}")
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
                succeeded = True
                completed.append(item_id)
            except Exception as e:
                self._log_q.put(("log", f"  ✗ Error: {e}\n"))
                trouble = f"{in_file.name} could not be converted."
                detail = f"{type(e).__name__}: {e}"
                if snapshot is not None:
                    failures.append(FailureRecord(
                        item_id=item_id, stage=STAGE_CONVERT,
                        display_message=trouble, technical_detail=detail,
                        retryable=True, snapshot_id=snapshot.snapshot_id))
                if reporter is not None:
                    # One item failing is not the run failing: this records, and
                    # changes no state at all.
                    reporter.failure(trouble, detail, item_id=item_id,
                                     stage=STAGE_CONVERT)
            finally:
                # Read once, first, so nothing this block does is counted as
                # work. A book that did not honestly complete is not history and
                # sends no sample at all.
                ended = clock() if timed else None
                if succeeded and started is not None:
                    self._log_q.put((TIMING_MESSAGE, TimingSample(
                        run_id=run_id, attempt=attempt, category=ETA_CATEGORY,
                        duration=float(ended) - float(started))))
                if reporter is None:
                    self._log_q.put(("progress", (idx, total)))
                else:
                    # The interim unit: one imported book. Phase 10 replaces the
                    # denominator with the frozen plan's segment count.
                    reporter.progress(idx, total, item_id=item_id,
                                      stage=STAGE_CONVERT)

        if snapshot is not None:
            # The shared authority on what succeeded, what failed and what was
            # never reached. Items the run never got to are NOT_ATTEMPTED, not
            # failures, and the controller is settled from what this derived --
            # the panel invents no second verdict.
            log = FailureLog(snapshot_id=snapshot.snapshot_id, records=tuple(failures))
            settled = RunResult.settle(snapshot, log, completed_ids=tuple(completed),
                                       cancelled=cancelled)
            if controller is not None:
                if cancelled:
                    # Legal only because a checkpoint actually observed the
                    # cancellation above: CANCELLED means it has stopped, not
                    # that someone clicked Cancel.
                    final = controller.finish_cancelled()
                elif settled.state is JobState.COMPLETED_WITH_FAILURES:
                    final = controller.complete_with_failures()
                else:
                    final = controller.succeed()
                if reporter is not None:
                    if cancelled:
                        reporter.cancelled(final)
                    else:
                        reporter.completed(final)
            self._log_q.put((RESULT_MESSAGE, settled))

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
        controller = self._controller
        if controller is not None and not controller.is_terminal:
            # This is also what makes closing a *paused* run safe: the request
            # wakes a worker waiting at a checkpoint, so the bounded join below
            # meets a thread already unwinding rather than one nothing will wake.
            controller.request_cancel()
        worker = self._worker
        if worker is not None and hasattr(worker, "join"):
            worker.join(WORKER_JOIN_TIMEOUT)
        self._worker = None
        jobs = getattr(self, "jobs", None)
        if jobs is not None:
            jobs.close()
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
