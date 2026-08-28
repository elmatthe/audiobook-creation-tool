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

from . import m4b_execution
from . import m4b_metadata
from . import m4b_numbering
from . import m4b_plan
from . import m4b_probe
from .m4b_metadata import MetadataMode
from .m4b_plan import ConversionMode, PlanOptions

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

#: The two stages a run passes through. Preflight reads every source before
#: anything is written; conversion begins only once the whole run is decided.
#: They are separate stages rather than one because their progress means
#: different things: the first has no honest denominator until it finishes.
STAGE_PREFLIGHT = "preflight"
STAGE_CONVERT = "convert"

#: The ETA's unit of comparable work: one planned **segment**. Whole-book mode
#: yields one segment per usable book, so this is the same measurement Phase 9
#: took; naming the unit for what the plan actually counts is what lets the
#: shared estimator drop incomparable history by itself if the unit ever
#: changes again.
ETA_CATEGORY = "segment"

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

#: The queue message that hands the finished, immutable conversion plan back to
#: the main thread. It travels rather than being assigned from the worker for
#: the same reason every other result does: the panel's own state belongs to the
#: thread that owns the widgets. The plan itself is frozen, so what crosses is a
#: value, not a handle.
PLAN_MESSAGE = "plan"


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
    now running. Phase 13 is where that stops being anticipation: a retry really
    does raise the attempt number, and a sample from the attempt before it is
    dropped rather than folded into the new estimate.
    """

    run_id: str
    attempt: int
    category: str
    duration: float


#: What the panel says when a retryable failure turns out to have no executable
#: plan entry behind it. This is an internal invariant violation, not something a
#: person can cause or fix, so it is refused rather than repaired: re-probing the
#: source or planning it a destination now would silently turn Retry Failed into a
#: second, late planner, which is the one thing the frozen-plan contract forbids.
RETRY_INVARIANT_MESSAGE = (
    "Retry Failed could not run: part of this run has no plan to repeat. "
    "Please start a new run for the books that did not convert.")


def merge_attempt(prior, snapshot, *, retried_ids, completed, records, cancelled):
    """One cumulative disposition for a frozen run, across all of its attempts.

    A retry re-executes a **subset** of one run, so settling it from that subset
    alone would report the books it did not touch as ``NOT_ATTEMPTED`` -- turning
    an earlier success into an absence. This folds the attempt into what the run
    already knew:

    * a book that succeeded before still has succeeded;
    * a failure that was **not** retried keeps the record it already had;
    * a retried failure that succeeded loses its record and joins the completed;
    * a retried failure that failed again has its record **replaced** by the new
      attempt's, so Details describes what just happened rather than what used to;
    * a retried book the attempt never reached -- a cancellation partway down the
      list -- keeps its previous failure, because that is still the true and only
      known reason it was a retry candidate. Nothing is invented for it.

    Ordering is the frozen snapshot's, so the same run always settles the same
    way however many attempts it took and in whatever order things failed.

    Pure, and built only from the public immutable shared values: no shared
    contract is extended, and no result is mutated -- ``RunResult.settle`` derives
    the state from the merged facts exactly as it does for a first attempt.
    """
    position = {item_id: index for index, item_id in enumerate(snapshot.item_ids)}
    fresh = {entry.item_id: entry for entry in records if entry.item_id is not None}
    succeeded_now = set(completed)

    kept: dict = {}
    for entry in prior.failures.records:
        if entry.item_id is None:
            continue  # job-level; carried separately below, never re-attributed
        if entry.item_id in succeeded_now:
            continue  # retried and earned its way out of the log
        kept[entry.item_id] = fresh.get(entry.item_id, entry)
    for item_id, entry in fresh.items():
        kept.setdefault(item_id, entry)

    fatal = tuple(e for e in prior.failures.records if e.item_id is None)
    fatal += tuple(e for e in records if e.item_id is None)
    ordered = tuple(
        kept[item_id] for item_id in
        sorted(kept, key=lambda value: position.get(value, len(position))))

    earlier = set(prior.completed_ids)
    merged_completed = tuple(
        item_id for item_id in snapshot.item_ids
        if item_id in earlier or item_id in succeeded_now)
    log = FailureLog(snapshot_id=snapshot.snapshot_id, records=fatal + ordered)
    return RunResult.settle(
        snapshot, log, completed_ids=merged_completed, cancelled=cancelled)


def measured_duration(path):
    """How long a produced file actually is, or ``None`` if it cannot be read.

    Handed to the executor so the drift guard can be exercised without media,
    and kept at module level because the worker thread reaches for exactly two
    attributes on the panel and this is not going to become a third.
    """
    info = ffmpeg_utils.probe_audio_stream(path)
    return info.get("duration") if info else None


def freeze_m4b_options(options: PlanOptions) -> dict:
    """The approved run configuration, as plain immutable scalars.

    Handed to ``capture_run``, which deep-freezes it and refuses a widget, a Tk
    variable, a callable or anything else live. The widgets are read once, on
    the main thread, in :meth:`M4BConverterUI.read_options`; this only reshapes
    what that produced so the shared snapshot and the plan can never describe
    two different runs.
    """
    return {
        "mode": options.mode.value,
        "metadata_mode": options.metadata_mode.value,
        "replacement": dict(options.replacement),
        "auto_number": options.auto_number,
        "start_number": options.start_number,
        "quality": options.quality,
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
        self._plan = None
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

        # Whole book / Split by chapter (Decision 44A). **One batch-wide
        # choice**, never per book: a run is planned once, and a per-item mode
        # would mean two different answers to what the run is.
        #
        # It shares the quality row rather than taking one of its own. The
        # panel already sits 10 px inside the supported 920x600 minimum, and a
        # new row would spend all of that; columns 2 and 3 of this row were
        # empty.
        ttk.Label(options, text="Convert:").grid(
            row=row, column=2, sticky="e", padx=8, pady=4
        )
        shapes = ttk.Frame(options)
        shapes.grid(row=row, column=3, sticky="w", padx=8, pady=4)
        self.var_mode = tk.StringVar(value=ConversionMode.WHOLE.value)
        self.rb_whole = ttk.Radiobutton(
            shapes, text="Whole book", variable=self.var_mode,
            value=ConversionMode.WHOLE.value)
        self.rb_split = ttk.Radiobutton(
            shapes, text="Split by chapter", variable=self.var_mode,
            value=ConversionMode.SPLIT.value)
        for column, button in enumerate((self.rb_whole, self.rb_split)):
            button.grid(row=0, column=column, sticky="w",
                        padx=(0 if column == 0 else 12, 0))

        # Metadata mode (Decision 19A/47A). This replaces the old two-state
        # "Do NOT write any metadata" checkbox, which could not express the
        # approved three-way contract: Preserve carries the source's own
        # compatible fields, Replace carries only what is typed below, and
        # Strip writes nothing at all. The default is Preserve.
        #
        # Three radios on one row, in a plain frame: the same single row the
        # checkbox occupied, so the form is no taller than it was.
        row += 1
        ttk.Label(options, text="Metadata:").grid(
            row=row, column=0, sticky="e", padx=8, pady=(2, 8)
        )
        modes = ttk.Frame(options)
        modes.grid(row=row, column=1, columnspan=3, sticky="w", padx=8, pady=(2, 8))
        self.var_metadata_mode = tk.StringVar(value=MetadataMode.PRESERVE.value)
        self.rb_preserve = ttk.Radiobutton(
            modes, text="Preserve source", variable=self.var_metadata_mode,
            value=MetadataMode.PRESERVE.value)
        self.rb_replace = ttk.Radiobutton(
            modes, text="Replace with the values below",
            variable=self.var_metadata_mode, value=MetadataMode.REPLACE.value)
        self.rb_strip = ttk.Radiobutton(
            modes, text="Write none", variable=self.var_metadata_mode,
            value=MetadataMode.STRIP.value)
        for column, button in enumerate(
                (self.rb_preserve, self.rb_replace, self.rb_strip)):
            button.grid(row=0, column=column, sticky="w", padx=(0 if column == 0 else 12, 0))

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
    def run_plan(self):
        """The immutable plan preflight produced, or ``None`` before one exists.

        The authority on what this run will write: which books are usable, how
        many outputs each produces, where every one of them goes, and which
        books were refused before anything was reserved.
        """
        return self._plan

    @property
    def run_result(self):
        """How this run stands, cumulatively, across every attempt it has had.

        Not "the last attempt": a retry re-runs a *subset* of one frozen run, so
        settling it with only that subset's outcome would forget the books that
        already succeeded. See :func:`merge_attempt`.
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

        ``on_retry`` is wired here (Phase 13), and its availability is still not
        this panel's to decide: the shared bar offers Retry Failed only when the
        adapter has been handed a settled result that reports a retryable failure
        *and* the run reached ``COMPLETED_WITH_FAILURES``. A fresh adapter holds
        no result, which is why the control is unavailable before a run, during
        one, and for the whole of a retry attempt -- no state is set by hand.
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
            on_retry=self.retry_failed,
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

    def read_options(self) -> PlanOptions:
        """Freeze every run-wide choice. **Main thread only, exactly once.**

        This is the whole of Decision 9A's widget half: after this returns, the
        run holds values and nothing it does can be changed by touching the
        panel. A worker that read a ``StringVar`` would not merely be unsafe --
        it would let a checkbox toggled during a long run change what the rest of
        that run wrote.
        """
        try:
            quality = max(0, min(9, int(self.var_quality.get())))
        except Exception:
            quality = DEFAULT_QUALITY
        try:
            start_number = max(1, int(self.var_start_num.get() or 1))
        except Exception:
            start_number = 1
        try:
            metadata_mode = MetadataMode(self.var_metadata_mode.get())
        except ValueError:
            metadata_mode = MetadataMode.PRESERVE
        try:
            mode = ConversionMode(self.var_mode.get())
        except ValueError:
            mode = ConversionMode.WHOLE
        return PlanOptions(
            mode=mode,
            metadata_mode=metadata_mode,
            replacement={
                "title": self.title_entry.get(),
                "artist": self.artist_entry.get(),
                "album_artist": self.album_artist_entry.get(),
                "album": self.album_entry.get(),
            },
            auto_number=bool(self.var_auto_num.get()),
            start_number=start_number,
            quality=quality,
        )

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

        # Every Tk value the run will ever use, read once, here.
        options = self.read_options()

        # Decision 9A, in one call: the imported list, the catalog, the import
        # options, the effective configuration and every output-affecting
        # setting are copied here and never consulted again. The
        # already-committed ``snapshot`` is passed rather than the manager, so
        # the shared run snapshot and the conversion plan describe the *same*
        # queue -- taking a second snapshot is how one run ends up with two.
        self._run_count += 1
        run = capture_run(
            snapshot_id=f"m4b-run-{self._run_count}",
            files=snapshot,
            catalog=self.import_catalog,
            import_options=self.importer.options.options(),
            effective_config=self._effective_config,
            tool_options=freeze_m4b_options(options),
            created_at=float(self._clock()),
        )
        self._snapshot = run
        self._result = None
        self._plan = None
        self._attempt += 1
        # The shared controller is this run's one state authority. Its listener
        # copies every state it actually reaches into the event stream, so the
        # panel keeps no rival state machine beside it.
        self._controller = job_control.JobController(
            run.snapshot_id, listener=self._on_state)
        self._install_jobs(run.snapshot_id, run.item_ids)
        self._reporter = job_control.JobReporter.for_run(
            run, clock=self._clock, publish=self._publish)

        params = {
            # The frozen occurrences themselves, not a reduced list of paths:
            # provenance is what the plan's destination routing needs, and
            # discarding it here only to re-derive it later is how it goes
            # missing.
            "imported_files": imported,
            "options": options,
            "snapshot": run,
            "controller": self._controller,
            "reporter": self._reporter,
            # Timing travels back as data, never as a shared estimator: the
            # worker is handed the clock and the two labels it needs to stamp a
            # measurement, and nothing it can mutate.
            "clock": self._clock,
            "run_id": run.snapshot_id,
            "attempt": self._attempt,
            # A first attempt has nothing to fold into and no subset to run: it
            # preflights every source and converts everything the plan allows.
            # Both keys are what :meth:`retry_failed` fills in.
            "plan": None,
            "retry_ids": None,
            "prior_result": None,
        }

        self._busy.set()
        self._cancel_event.clear()
        self._controller.start()
        # **No denominator yet, and that is the point.** Until every source has
        # been read there is no honest number of outputs, so preflight reports
        # indeterminate progress and the authoritative
        # ``ConversionPlan.total_segments`` is published once, later, by the
        # worker. Nothing here guesses it.
        self._reporter.stage_changed(
            STAGE_PREFLIGHT, "Examining the imported audiobooks…")
        self._reporter.progress(0, None, stage=STAGE_PREFLIGHT)
        self.disable_inputs(True)

        t = threading.Thread(
            target=self.convert_worker, args=(params,), daemon=True
        )
        self._worker = t
        t.start()

    def retry_failed(self):
        """Re-run the failed books of the frozen run. Main thread only.

        **A new attempt at the same run, not a new run.** The snapshot is the
        original object, the plan is the original object, the destinations are the
        ones planned at the original Start and the run directory is the one that
        was reserved then. Nothing here reads a widget, the imported-file manager,
        the catalog or the configuration: the user may have reordered the list,
        removed a book, switched Whole to Split and changed every option since,
        and none of it reaches what this executes.

        What *is* new is the attempt: a retired adapter cannot be reused, so the
        controller, the reporter, the event stream and the estimate are all fresh
        and the attempt number rises -- which is what makes the previous attempt's
        late timing samples inert rather than merged into the new estimate.
        """
        if self._busy.is_set():
            return
        result = self._result
        plan = self._plan
        run = self._snapshot
        if result is None or plan is None or run is None:
            return
        if not result.has_retryable:
            return

        # The shared model decides *what* is retried, from the failures the run
        # actually recorded and the snapshot it was accepted with. This asks it,
        # rather than filtering a list of its own.
        request = result.retry()

        # Defensive, and it should never fire: classification already guarantees
        # that only an execution failure -- which by definition has an executable
        # plan entry -- is ever retryable. If a future change breaks that, the
        # honest move is to refuse, because every way of "fixing" it here (probe
        # it again, plan it a destination, quietly drop it) is forbidden.
        missing = tuple(
            item_id for item_id in request.item_ids if plan.item_for(item_id) is None)
        if missing:
            shown = ", ".join(missing[:3])
            if len(missing) > 3:
                shown += f", and {len(missing) - 3} more"
            self._log_q.put((
                "log",
                "\n  \u2717 " + RETRY_INVARIANT_MESSAGE + "\n"
                + f"      no plan entry for: {shown}\n"))
            messagebox.showerror("Retry Failed", RETRY_INVARIANT_MESSAGE)
            return

        # Frozen order, not failure order: the retried books run in the order the
        # plan holds them, which is the order the run was given them.
        wanted = set(request.item_ids)
        items = tuple(
            item for item in plan.items if item.occurrence_id in wanted)

        self._attempt += 1
        self._controller = job_control.JobController(
            run.snapshot_id, listener=self._on_state)
        # The retired adapter is closed inside here, which drops its drain: one
        # pump, one job drain and one scheduled callback however many attempts a
        # run takes. The new adapter holds no result, so Retry Failed is
        # unavailable for the whole of this attempt without anything setting it.
        self._install_jobs(run.snapshot_id, run.item_ids)
        self._reporter = job_control.JobReporter.for_run(
            run, clock=self._clock, publish=self._publish)

        params = {
            # The frozen occurrences of the original run, taken from the snapshot
            # itself rather than from the manager as it stands now.
            "imported_files": tuple(run.files.files),
            "options": None,
            "snapshot": run,
            "controller": self._controller,
            "reporter": self._reporter,
            "clock": self._clock,
            "run_id": run.snapshot_id,
            "attempt": self._attempt,
            "plan": plan,
            "retry_ids": tuple(request.item_ids),
            "prior_result": result,
        }

        self._busy.set()
        self._cancel_event.clear()
        self._controller.start()
        # The stage is announced here and the **denominator is not**, which is
        # the same division of labour a first attempt uses: the main thread says
        # what is starting, and the worker publishes the authoritative count of
        # what is actually going to be written.
        self._reporter.stage_changed(
            STAGE_CONVERT, "Retrying the books that failed…")
        self.disable_inputs(True)
        self._log_q.put((
            "log", f"\nRetrying {len(items)} book(s) that failed.\n"))

        t = threading.Thread(
            target=self.convert_worker, args=(params,), daemon=True)
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
            self.rb_whole,
            self.rb_split,
            self.rb_preserve,
            self.rb_replace,
            self.rb_strip,
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
                elif kind == PLAN_MESSAGE:
                    self._adopt_plan(payload)
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

    def _adopt_plan(self, plan) -> None:
        """Take the finished plan on the main thread. Nothing here decides.

        The run directory is shown from the plan rather than from a reservation
        made at Start, because there no longer is one: the folder appears only
        after preflight has proved something is worth writing into it, so a run
        whose books are all unreadable leaves the display exactly as it was.
        """
        self._plan = plan
        outdir = getattr(plan, "run_directory", None)
        if outdir is None:
            return
        self._last_run_dir = outdir
        try:
            self.var_outdir.set(str(outdir))
        except tk.TclError:  # pragma: no cover - a destroyed panel
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

        It is handed to the shared adapter too, which is what makes Retry Failed
        available -- and the two arrived together, in this phase, so the control
        has never been offered without something behind it. The result given here
        is the **cumulative** one the worker settled, so the summary describes the
        whole frozen run rather than whichever subset the last attempt ran.
        """
        self._result = result
        jobs = getattr(self, "jobs", None)
        if jobs is not None and not self._closed:
            jobs.set_result(result)

    def _finish_idle(self):
        self._busy.clear()
        self._cancel_event.clear()
        self.disable_inputs(False)

    # ------- conversion (worker thread) -------

    def convert_worker(self, params: dict):
        """Preflight the whole run, plan it, then convert what the plan allows.

        **The order is the contract.** Every source is read first, on this
        thread -- no ffprobe call may ever run on the thread that owns the
        widgets, because a forty-seven-chapter book must not freeze the window.
        Only once every source has been judged is a run directory reserved and
        every destination planned; only then does anything get written. So a
        queue whose books are all unreadable reserves nothing at all and leaves
        no empty numbered folder behind.

        The plan is the single authority from that point on. This body reads no
        widget, no variable and no manager: it was handed frozen occurrences and
        one frozen :class:`~mp3_tools.m4b_plan.PlanOptions`, and it consults
        them and the plan alone.

        **A retry enters below the preflight.** When ``retry_ids`` is present the
        plan already exists and arrived with the call, so nothing here probes a
        source, validates a chapter map, partitions a timeline, selects a cover,
        reserves a directory or plans a destination -- every one of those answers
        was frozen before the first attempt wrote anything, and re-deriving one
        now is exactly how a retry would land somewhere other than the run it is
        repeating. It converts the selected books, at their original names, and
        folds the outcome into what the run already knew.
        """
        imported = params["imported_files"]
        options = params.get("options") or PlanOptions()
        controller = params.get("controller")
        reporter = params.get("reporter")
        snapshot = params.get("snapshot")
        clock = params.get("clock")
        run_id = params.get("run_id")
        attempt = params.get("attempt", 0)
        # A retry arrives with the frozen plan, the ordered subset to re-execute
        # and the run's cumulative disposition so far. All three are ``None`` on
        # a first attempt, and that is the only thing that tells the two apart.
        retry_ids = params.get("retry_ids")
        prior = params.get("prior_result")
        retrying = retry_ids is not None
        timed = clock is not None and run_id is not None
        cancelled = False
        completed: list = []
        failures: list = []
        reservation = None

        def checkpoint() -> None:
            """The one cooperative boundary, and it sits **between sources**.

            An ffprobe read and an ffmpeg encode are both indivisible at this
            phase, so a pause asked for during either is honoured here rather
            than there. The cancel latch is mirrored into the controller instead
            of being acted on directly, so ``checkpoint()`` remains the single
            place that decides what a request means.
            """
            if controller is not None:
                if self._cancel_event.is_set():
                    controller.request_cancel()
                controller.checkpoint()
            elif self._cancel_event.is_set():
                raise ConversionCancelled("Cancelled.")

        def note(item_id, message, detail, stage, *, retryable):
            """Record one failure once, in both the typed log and the report.

            ``retryable`` has **no default on purpose.** The two callers below sit
            at genuinely different stages -- one refuses a source that never got a
            plan entry, the other loses a book that had one -- and a helper that
            stamped the same answer on both is precisely how a preflight failure
            came to be offered a retry it could not possibly execute.
            """
            if snapshot is not None:
                failures.append(FailureRecord(
                    item_id=item_id, stage=stage,
                    display_message=message, technical_detail=detail,
                    retryable=retryable, snapshot_id=snapshot.snapshot_id))
            if reporter is not None:
                reporter.failure(message, detail, item_id=item_id, stage=stage)

        # ------- preflight: read every source before deciding anything -------
        #
        # **Empty on a retry**, which is what skips it: the plan this produces
        # already exists and arrived with the call, and running it again would
        # re-open every question that plan has already answered.
        reports: dict = {}
        try:
            for entry in (() if retrying else imported):
                checkpoint()
                if reporter is not None:
                    reporter.current_item(
                        entry.occurrence_id, f"Examining {entry.path.name}")
                self._log_q.put(("log", f"  Examining {entry.path.name}…\n"))
                reports[entry.occurrence_id] = m4b_probe.probe_source(entry.path)
        except ConversionCancelled:
            cancelled = True

        plan = params.get("plan")
        if not cancelled and not retrying:
            def _reserve_run():
                """The run's one reservation seam.

                Called *by the plan*, and only once it has found something
                genuinely usable -- which is what puts the folder after
                validation and before any destination is planned.
                """
                nonlocal reservation
                reservation = output_paths.reserve_run_directory(TOOL_KEY)
                return reservation.run_directory, reservation.planner()

            try:
                plan = m4b_plan.assemble_plan(
                    snapshot_id=run_id or "m4b-run",
                    entries=imported,
                    reports=reports,
                    options=options,
                    reserve=_reserve_run,
                )
            except Exception as exc:
                # Nothing was written, so a directory reserved a moment ago is
                # still empty and is given back rather than left lying about.
                if reservation is not None:
                    output_paths.release_if_empty(reservation)
                detail = f"{type(exc).__name__}: {exc}"
                self._log_q.put(("log", f"\n  ✗ The run could not be planned: {exc}\n"))
                if snapshot is not None:
                    failures.append(FailureRecord(
                        item_id=None, stage=STAGE_PREFLIGHT,
                        display_message="This run could not be planned, so nothing was converted.",
                        technical_detail=detail, retryable=False,
                        snapshot_id=snapshot.snapshot_id))
                if reporter is not None:
                    reporter.failure(
                        "This run could not be planned, so nothing was converted.",
                        detail, stage=STAGE_PREFLIGHT)

        if plan is not None and not retrying:
            self._log_q.put((PLAN_MESSAGE, plan))
            # Every source that will not be converted, reported before any
            # output exists. A preflight failure is typed, keeps its occurrence
            # and never becomes an empty success.
            for failure in plan.unusable:
                self._log_q.put((
                    "log", f"\n  ✗ {failure.source.name}: {failure.message}\n"))
                # Typed, non-fatal, nothing written -- and **not** a Retry Failed
                # candidate, which is the classification itself and not an
                # afterthought: this occurrence has no ``ItemPlan`` and no frozen
                # destination, so there is nothing for an in-place retry to
                # re-execute. A corrected source comes back through a new run.
                note(failure.occurrence_id, failure.message, failure.detail,
                     STAGE_PREFLIGHT, retryable=failure.retryable)

        # **What this attempt runs**, and the only place the two shapes differ:
        # everything the plan found usable, or the frozen subset a retry selected.
        # Either way these are plan entries, in the plan's own order.
        if plan is None:
            run_items: tuple = ()
        elif retrying:
            wanted = set(retry_ids)
            run_items = tuple(
                item for item in plan.items if item.occurrence_id in wanted)
        else:
            run_items = tuple(plan.items)
        # The denominator describes the work about to be done, not the whole run:
        # a retry that converts everything it was asked to must fill the bar.
        total = sum(item.total_segments for item in run_items)
        outdir = plan.run_directory if plan is not None else None
        if plan is not None and run_items:
            if outdir is not None:
                self._log_q.put(("log", f"\nOutput folder: {outdir}\n"))
                if reporter is not None:
                    reporter.output_location(outdir)
            if reporter is not None:
                # **The authoritative denominator, published exactly once per
                # attempt.** It is the segment count of the work this attempt
                # will do, not the imported-file count -- so a first attempt
                # publishes the plan's total and a retry publishes only what it
                # was asked to re-run, and either one fills the bar when it
                # converts everything it set out to.
                reporter.stage_changed(
                    STAGE_CONVERT,
                    "Retrying…" if retrying else "Converting…")
                reporter.progress(0, total, stage=STAGE_CONVERT)

        # ------- execution -------
        #
        # From here on the plan is the only authority. Nothing below re-probes a
        # source, rebuilds a span, renames a segment, re-plans a destination,
        # re-selects a cover or reads a widget: every one of those answers was
        # frozen before the run directory existed, and reinterpreting one now is
        # how a retry would land somewhere different from the run it repeats.
        done = 0
        if run_items and not cancelled:

            def interrupted() -> bool:
                """The low-level latch a running child is polled against.

                Both doors into a cancellation are read: this panel's own event,
                which `close()` also sets, and the controller's request. The
                controller stays the **state** authority -- this is only the
                signal that has to reach a process mid-encode, which a
                checkpoint between segments cannot do on its own.
                """
                if self._cancel_event.is_set():
                    return True
                return controller is not None and controller.cancel_check()

            def announce(argv) -> None:
                """One command, into the transcript and the Details pane."""
                line = " ".join(str(part) for part in argv)
                self._log_q.put(("log", "  ffmpeg: " + line + "\n"))
                if reporter is not None:
                    reporter.technical(line)

            # **Whole-book sequential numbering (Decision 21A/28A).** One
            # counter for the whole run attempt, started from the frozen
            # `Start #`, and created at all only when this is a whole-book
            # run with Auto-number on.
            #
            # The eligibility test is the run's **mode**, deliberately not
            # `item.fragment`. A chapterless book in split mode is planned as
            # one non-fragment whole-file output, so keying off the item
            # would hand it a whole-run sequence number in a run where
            # auto-numbering does not apply at all.
            #
            # **A retry continues the sequence; it does not restart it.** The
            # counter is per attempt, so a retry gets a new one -- but the run is
            # the same run, and the books that already succeeded already carry
            # their numbers. It therefore starts where the run has actually got
            # to: the frozen ``Start #`` plus however many books this run has
            # successfully written so far, taken from the cumulative result and
            # never from a filename, an output tag or a directory listing.
            first = plan.start_number
            if retrying and prior is not None:
                first += len(prior.completed_ids)
            numbers = (m4b_numbering.SuccessNumbers(first)
                       if plan.auto_number and not plan.split else None)

            for index, item in enumerate(run_items):
                item_id = item.occurrence_id
                in_file = item.source
                finalised: list = []
                failure = None
                # Proposed, not taken. The number has to exist before ffmpeg
                # runs because it is written into the file; it counts only
                # once the file actually exists.
                tentative = None if numbers is None else numbers.propose()

                if reporter is not None:
                    reporter.current_item(item_id, f"Converting {in_file.name}")
                self._log_q.put((
                    "log",
                    f"\n[{index + 1}/{len(run_items)}] {in_file.name} "
                    f"-> {item.total_segments} file(s)\n"))

                if plan.split and not item.chaptered:
                    # Decision 18A: a genuinely chapterless book is a success in
                    # split mode, written whole and named as a whole book.
                    note_text = (f"{in_file.name} has no chapters, so it was "
                                 f"written as one file: "
                                 f"{item.segments[0].destination.name}")
                    self._log_q.put(("log", f"  {note_text}\n"))
                    if reporter is not None:
                        reporter.warning(note_text, "chapterless source (18A)")
                if item.undecodable_xhe:
                    trouble = (f"{in_file.name} is xHE-AAC and this ffmpeg "
                               "build has no decoder for it on this platform, "
                               "so the output may be sped up or choppy.")
                    self._log_q.put(("log", f"  \u26a0 WARNING: {trouble}\n"))
                    if reporter is not None:
                        reporter.warning(trouble, f"codec={item.codec_hint}")

                for segment in item.segments:
                    # **The safe checkpoint, and it now sits between segments.**
                    # An ffmpeg encode is indivisible, so a pause asked for
                    # during one is honoured here -- after that segment has been
                    # measured and finalised, never by suspending the process.
                    try:
                        checkpoint()
                    except ConversionCancelled:
                        cancelled = True
                        break

                    if item.fragment:
                        tags = m4b_metadata.segment_tags(
                            plan.metadata_mode,
                            title=segment.title,
                            order=segment.track or segment.order,
                            source=item.tags,
                            replacement=plan.replacement,
                        )
                    else:
                        # Success-only: this is the number the book *would*
                        # carry. Nothing has been consumed yet, so a failure
                        # below leaves it available for the next book and the
                        # run comes out gap-free.
                        number = None if tentative is None else tentative.number
                        tags = m4b_metadata.whole_book_tags(
                            plan.metadata_mode,
                            source=item.tags,
                            replacement=plan.replacement,
                            track=number,
                        )

                    work = m4b_execution.SegmentWork(
                        source=in_file,
                        destination=segment.destination,
                        expected_duration=segment.duration,
                        quality=plan.quality,
                        metadata_mode=plan.metadata_mode,
                        tags=tags,
                        decoder_args=item.decoder_args,
                        picture=item.picture,
                        span=((segment.start, segment.end) if item.fragment
                              else None),
                    )

                    self._log_q.put((
                        "log", f"  -> {segment.destination}\n"))
                    started = clock() if timed else None
                    outcome = m4b_execution.convert_segment(
                        work,
                        ffmpeg=ffmpeg_utils.ffmpeg_cmd(),
                        cancelled=interrupted,
                        measure=measured_duration,
                        sources=tuple(entry.path for entry in imported),
                        on_command=announce,
                    )
                    ended = clock() if timed else None

                    if outcome.cancelled:
                        cancelled = True
                        break
                    if not outcome.finalised:
                        failure = outcome
                        self._log_q.put(("log", f"  \u2717 {outcome.message}\n"))
                        done += 1
                        if reporter is not None:
                            reporter.progress(done, total, item_id=item_id,
                                              stage=STAGE_CONVERT)
                        break

                    finalised.append(outcome.destination)
                    self._log_q.put(("log", "  \u2713 Done\n"))
                    done += 1
                    if started is not None:
                        self._log_q.put((TIMING_MESSAGE, TimingSample(
                            run_id=run_id, attempt=attempt,
                            category=ETA_CATEGORY,
                            duration=float(ended) - float(started))))
                    if reporter is None:
                        self._log_q.put(("progress", (done, total)))
                    else:
                        reporter.progress(done, total, item_id=item_id,
                                          stage=STAGE_CONVERT)

                if cancelled or failure is not None:
                    # **A partially split book must never look complete.** The
                    # segments already written for *this* item are taken back;
                    # every other book's finished work is untouched.
                    removed = m4b_execution.remove_outputs(
                        finalised, inside=plan.run_directory)
                    if removed:
                        self._log_q.put((
                            "log",
                            f"  {len(removed)} incomplete file(s) for "
                            f"{in_file.name} were removed.\n"))

                if failure is not None:
                    # Named by book *and* by output: a split run has many
                    # outputs per book, and "which file" is the first thing
                    # a person needs to know.
                    # An execution failure **is** retryable: this book has an
                    # executable plan entry and frozen destinations, so repeating
                    # it needs nothing re-decided and lands exactly where the
                    # first attempt was going to put it.
                    note(item_id, f"{in_file.name}: {failure.message}",
                         failure.detail, STAGE_CONVERT, retryable=True)
                elif not cancelled:
                    completed.append(item_id)
                    # **The only place the counter moves.** Reached only when
                    # every segment of this item converted, validated and was
                    # finalised -- so a failure, a drift breach, an occupied
                    # destination or a cancellation all consume nothing.
                    if tentative is not None:
                        numbers.commit(tentative)

                if cancelled:
                    # Settled only now: the child is reaped, its temporary file
                    # is gone and the partial book has been taken back. The
                    # checkpoint is what records the acknowledgement, without
                    # which the controller refuses to report CANCELLED at all.
                    try:
                        checkpoint()
                    except ConversionCancelled:
                        pass
                    break

        if snapshot is not None:
            if retrying and prior is not None:
                # **The run, not the attempt.** A retry re-ran a subset, so
                # settling it from that subset alone would report every book it
                # did not touch as never attempted -- turning an earlier success
                # into an absence.
                settled = merge_attempt(
                    prior, snapshot, retried_ids=retry_ids,
                    completed=tuple(completed), records=tuple(failures),
                    cancelled=cancelled)
            else:
                log = FailureLog(
                    snapshot_id=snapshot.snapshot_id, records=tuple(failures))
                settled = RunResult.settle(
                    snapshot, log, completed_ids=tuple(completed),
                    cancelled=cancelled)
            if controller is not None:
                if cancelled:
                    final = controller.finish_cancelled()
                elif settled.state is JobState.COMPLETED_WITH_FAILURES:
                    final = controller.complete_with_failures()
                elif settled.state is JobState.FAILED:
                    final = controller.fail(
                        "This run could not be planned, so nothing was converted.")
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
        elif outdir is None:
            self._log_q.put((
                "done", ("\nNothing could be converted, so no output folder was "
                         "created.\n", None)))
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
