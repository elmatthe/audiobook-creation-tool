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
#
# v0.6.6 Phase 4: presentation only. The panel is the Family-A guided layout
# (1. Sources / 2. Conversion & Metadata / 3. Output & Run, Activity on the
# right) on the shared compact Light/Dark appearance the approved Cover and TTS
# interiors use; the old raw "Log" box became Activity's Detailed pane. No
# conversion, metadata, chapter, artwork, numbering, retry or output rule moved.

import gc
import queue
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox

# Make the scripts/ root importable so `shared.*` resolves whether this tool is
# run standalone (python mp3_tools/m4b_converter.py) or imported by the launcher.
_SCRIPTS_ROOT = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ROOT))

from shared import appearance
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
from . import m4b_winaudio
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

    ``retried_ids`` is the attempt's boundary and is enforced, not assumed: an
    occurrence this attempt was not asked to repeat is settled from *prior*
    alone, whatever the attempt reports about it. So a caller that supplied a
    stray completion or a stray failure record for an untouched book could not
    change that book's cumulative disposition even by accident.

    Pure, and built only from the public immutable shared values: no shared
    contract is extended, and no result is mutated -- ``RunResult.settle`` derives
    the state from the merged facts exactly as it does for a first attempt.
    """
    #: **The attempt boundary, enforced here rather than merely assumed.**
    #: ``retried_ids`` is what this attempt was asked to repeat, and it is the
    #: only thing the attempt is allowed to speak about: both halves of what it
    #: reports are restricted to it, so an occurrence outside the attempt is
    #: settled from *prior* alone no matter what a caller supplies for it. That
    #: is what makes one retry structurally incapable of turning an untouched
    #: book's success into a failure, or an unretried failure into a success.
    #:
    #: Deliberately silent rather than raising. This seam produces the run's one
    #: terminal disposition, so refusing here would leave a finished run with no
    #: result at all and a panel still reporting itself busy -- strictly worse,
    #: for the person waiting, than declining to believe a claim about a book
    #: this attempt never ran. The shared layer keeps its own contract errors for
    #: values it can reject *before* any work has happened; this is after.
    attempted = frozenset(retried_ids)
    position = {item_id: index for index, item_id in enumerate(snapshot.item_ids)}
    fresh = {entry.item_id: entry for entry in records
             if entry.item_id is not None and entry.item_id in attempted}
    succeeded_now = {item_id for item_id in completed if item_id in attempted}

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

#: Spacing, identical to the TTS and Cover Image panels' own constants: the
#: approved Cover UI is the concrete visual reference for every tool interior
#: (maintainer ruling 2026-09-28), so these are copied rather than re-chosen.
OUTER_PAD = 10
COLUMN_GAP = 10
SECTION_GAP = 8
SECTION_PADDING = (10, 6, 10, 8)

#: The tight-window padding TTS's small-window ("split") arrangement uses.
SPLIT_SECTION_PADDING = (10, 4, 10, 5)

#: Wrap widths for prose, so a caption can never decide how wide its section
#: must be (TTS's rule): the output note, the metadata note and changing
#: status lines add a line rather than a column. They are re-wrapped to the
#: section's real width once the arrangement is known (``_rewrap``).
NOTE_WRAP = 200
STATUS_WRAP = 190

#: The imported list: rows it asks for, and the rows it keeps however small the
#: window gets. It is Sources' flexible region. In the small-window split it
#: may give up everything but one row, exactly as TTS's list does.
IMPORTER_LIST_HEIGHT = 6
IMPORTER_FLOOR_ROWS = 2
IMPORTER_SPLIT_FLOOR_ROWS = 1

#: The Activity log: natural size in lines/characters, the lines it keeps at
#: the smallest window, and the history cap shared with the sibling tools.
LOG_HEIGHT = 12
LOG_WIDTH_CHARS = 40
LOG_FLOOR_LINES = 3
LOG_LIMIT = 400

#: The narrowest Activity column worth putting beside the workflow.
ACTIVITY_MIN_WIDTH = 150
ACTIVITY_NOTE_MIN_WRAP = 60

#: Share of the panel the workflow column takes on a wide window, when that is
#: more than its measured natural width -- the frozen contract's 32-35%.
WORKFLOW_SHARE = 0.34

#: The shared status view's progress bar defaults to 240 px; that alone would
#: decide how wide Output & Run must be. Narrower reads the same.
PROGRESS_BAR_LENGTH = 110

#: The read-only output path's requested width in characters (it stretches).
OUTDIR_CHARS = 24
SPLIT_OUTDIR_CHARS = 12

#: The four replacement fields' requested width in characters (they stretch).
FIELD_CHARS = 14


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
        appearance_bundle: dict | None = None,
    ):
        """Build the panel.

        Every keyword is a seam the tests drive instead of a real dialog,
        clock or thread — the same injection points the Cover and TTS panels
        already expose. Production passes none of them.

        ``appearance_bundle`` (v0.6.6 Phase 4) is the same seam Cover and TTS
        take: the production default reads the remembered Light/Dark setting,
        and the suite may inject an exact bundle without touching settings.
        """
        # v0.6.6 Phase 4: the whole interior is built from the shared compact
        # appearance bundle -- the approved Cover/TTS control language -- so no
        # native light island is left inside a Dark panel. Aqua style names inherit
        # native control layouts and metrics, with the app appearance.
        if appearance_bundle is None:
            appearance_bundle = appearance.build_bundle(
                ttk.Style(parent), appearance.get_appearance(),
                root=parent.winfo_toplevel())
        self.appearance_bundle = appearance_bundle
        super().__init__(parent, style=job_ui.style_name(appearance_bundle, "window"))
        appearance.register_listener(self._on_appearance_changed)

        # Cancellation / worker plumbing (mirrors the TTS tool's pattern).
        self._closed = False
        self._worker: threading.Thread | None = None
        self._clock = time.monotonic if clock is None else clock
        self._effective_config = (shared_config.get_effective()
                                  if effective_config is None
                                  else effective_config)
        #: The effective configuration this run was accepted with, captured at
        #: Start. Resolution of it stays in ``output_paths``; this only records
        #: *which* configuration the accepted run belongs to.
        self._run_config = None
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
        # ---- layout: the Family-A workflow, Cover/TTS's own composition --- #
        # v0.6.6 Phase 4. The panel is four sections, on the approved Cover and
        # TTS interiors' compact control language:
        #
        #   1. Sources                -- the imported list, the six import
        #                                actions, the import options, Cancel Import
        #   2. Conversion & Metadata  -- Output structure first (Whole book /
        #                                Split by chapter), then quality, the
        #                                metadata mode, the four fields and
        #                                auto-numbering
        #   3. Output & Run           -- destination, Convert, the shared controls
        #   Activity                  -- the one Summary | Detailed log, on the right
        #
        # 1-3 are the workflow, read top to bottom. How they sit depends only on
        # the panel's size (_choose_layout), from the sections' own measured
        # sizes -- never a whole-panel scrollbar, never a scrolling options form:
        #
        #   wide     1 over 2 over 3 on the left, Activity on the right
        #   split    1 over 2 on the left, 3 over Activity on the right -- the
        #            approved TTS small-window precedent, for the real launcher's
        #            920x600 and 1024x720 content areas
        #   stacked  the workflow above Activity; a last resort only
        #
        # Only the imported list and the log scroll, and each keeps a measured
        # floor so neither collapses. No control, variable, callback or policy
        # changed in this rebuild: every widget below is the one the panel
        # already had, re-homed and styled.
        bundle = self.appearance_bundle
        st = self._style
        self._needs: dict | None = None
        self._layout_mode: str | None = None
        self._inputs_locked = False
        self.workflow = ttk.Frame(self, style=st("window"))
        self.sources_section = ttk.LabelFrame(
            self.workflow, text="1. Sources", padding=SECTION_PADDING,
            style=st("labelframe"))
        self.options_section = ttk.LabelFrame(
            self.workflow, text="2. Conversion & Metadata", padding=SECTION_PADDING,
            style=st("labelframe"))
        # A child of the panel rather than of the workflow frame, exactly as in
        # TTS: wide and stacked grid it *into* the workflow frame (grid's
        # ``in_``, which Tk allows for a descendant of the parent), while split
        # stands it above Activity in the right-hand column. Created after the
        # workflow and before Activity, so stacking and Tab order still read
        # 1, 2, 3, Activity.
        self.run_section = ttk.LabelFrame(
            self, text="3. Output & Run", padding=SECTION_PADDING,
            style=st("labelframe"))
        self.activity = ttk.LabelFrame(
            self, text="Activity", padding=SECTION_PADDING, style=st("labelframe"))

        # ---- 1. Sources --------------------------------------------------- #
        sources = self.sources_section
        sources.columnconfigure(0, weight=1)
        sources.rowconfigure(0, weight=1)
        self.importer = job_ui.ImportAdapter(
            sources,
            catalog=self.import_catalog,
            effective_config=self._effective_config,
            pump=self._pump,
            manager=self._manager,
            coordinator=self._coordinator,
            # The shared compact bundle: the importer's list, actions, options
            # and status take the same styles as the rest of the panel, and the
            # list carries the shared §4 keyboard contract itself.
            theme=bundle,
            clock=self._clock,
            id_factory=id_factory,
            choose_files=(self._choose_files if choose_files is None
                          else choose_files),
            choose_folder=(self._choose_folder if choose_folder is None
                           else choose_folder),
            confirm_large_result=(self._confirm_large_result
                                  if confirm_large_result is None
                                  else confirm_large_result),
            list_height=IMPORTER_LIST_HEIGHT,
        )
        self.importer.frame.grid(row=0, column=0, sticky="nsew")
        # A long status wraps onto a second line instead of widening Sources.
        self.importer.list.count_label.configure(wraplength=STATUS_WRAP)
        self.importer.status.label.configure(wraplength=STATUS_WRAP)

        # ---- 2. Conversion & Metadata -------------------------------------- #
        options = self.options_section
        options.columnconfigure(1, weight=1)
        options.columnconfigure(3, weight=1)

        # Output structure (Decision 44A), first and prominent: it decides what
        # the run *is*. **One batch-wide choice**, never per book: a run is
        # planned once, and a per-item mode would mean two answers to that.
        structure = ttk.Frame(options, style=st("surface"))
        structure.grid(row=0, column=0, columnspan=4, sticky="w")
        self.structure_label = ttk.Label(structure, text="Output structure",
                                         style=st("subheading"))
        self.structure_label.grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.var_mode = tk.StringVar(value=ConversionMode.WHOLE.value)
        self.rb_whole = ttk.Radiobutton(
            structure, text="Whole book", variable=self.var_mode,
            value=ConversionMode.WHOLE.value, style=st("radiobutton"))
        self.rb_split = ttk.Radiobutton(
            structure, text="Split by chapter", variable=self.var_mode,
            value=ConversionMode.SPLIT.value, style=st("radiobutton"))
        self.rb_whole.grid(row=0, column=1, sticky="w")
        self.rb_split.grid(row=0, column=2, sticky="w", padx=(12, 0))

        self.options_separator = ttk.Separator(options, orient=tk.HORIZONTAL,
                                               style=st("separator"))
        self.options_separator.grid(row=1, column=0, columnspan=4, sticky="ew",
                                    pady=(6, 5))

        quality = ttk.Frame(options, style=st("surface"))
        quality.grid(row=2, column=0, columnspan=4, sticky="w")
        ttk.Label(quality, text="MP3 quality", style=st("label")).grid(
            row=0, column=0, sticky="w")
        self.var_quality = tk.IntVar(value=DEFAULT_QUALITY)
        self.entry_quality = ttk.Spinbox(
            quality, from_=0, to=9, textvariable=self.var_quality, width=4,
            style=st("spinbox"))
        self.entry_quality.grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Label(quality, text="VBR 0–9, lower is better",
                  style=st("secondary_label")).grid(
            row=0, column=2, sticky="w", padx=(8, 0))

        # Metadata mode (Decision 19A/47A): Preserve carries the source's own
        # compatible fields (a filled field below overrides its own), Replace
        # carries only what is typed below, and Write none writes nothing at
        # all. The default is Preserve.
        ttk.Label(options, text="Metadata", style=st("label")).grid(
            row=3, column=0, columnspan=4, sticky="w", pady=(6, 0))
        modes = ttk.Frame(options, style=st("surface"))
        modes.grid(row=4, column=0, columnspan=4, sticky="w")
        self.var_metadata_mode = tk.StringVar(value=MetadataMode.PRESERVE.value)
        self.rb_preserve = ttk.Radiobutton(
            modes, text="Preserve source", variable=self.var_metadata_mode,
            value=MetadataMode.PRESERVE.value, style=st("radiobutton"))
        self.rb_replace = ttk.Radiobutton(
            modes, text="Replace with the values below",
            variable=self.var_metadata_mode, value=MetadataMode.REPLACE.value,
            style=st("radiobutton"))
        self.rb_strip = ttk.Radiobutton(
            modes, text="Write none", variable=self.var_metadata_mode,
            value=MetadataMode.STRIP.value, style=st("radiobutton"))
        for column, button in enumerate(
                (self.rb_preserve, self.rb_replace, self.rb_strip)):
            button.grid(row=0, column=column, sticky="w",
                        padx=(0 if column == 0 else 12, 0))

        # The four fields. Always visible; disabled only where they cannot
        # apply -- Write none, which writes nothing -- so the form never jumps.
        fields = (
            ("title_entry", "Title (blank → filename)", 5, 0),
            ("artist_entry", "Artist", 5, 2),
            ("album_artist_entry", "Album Artist", 6, 0),
            ("album_entry", "Album", 6, 2),
        )
        for attribute, text, row, column in fields:
            ttk.Label(options, text=text, style=st("label")).grid(
                row=row, column=column, sticky="w", pady=(4, 0),
                padx=(0 if column == 0 else 12, 0))
            entry = ttk.Entry(options, width=FIELD_CHARS, style=st("entry"))
            entry.grid(row=row, column=column + 1, sticky="ew", padx=(8, 0),
                       pady=(4, 0))
            setattr(self, attribute, entry)

        # Auto-number checkbox + start. Off on a fresh panel (maintainer
        # decision, v0.6.2 Plan 5 Phase 16): renumbering somebody's library is
        # an opt-in; ``Start #`` keeps its 1 so it is ready once ticked. Nothing
        # about the success-only sequence changes -- see ``m4b_numbering``.
        numbering = ttk.Frame(options, style=st("surface"))
        numbering.grid(row=7, column=0, columnspan=4, sticky="w", pady=(6, 0))
        self.var_auto_num = tk.BooleanVar(value=False)
        self.chk_auto_num = ttk.Checkbutton(
            numbering, text="Auto-number tracks", variable=self.var_auto_num,
            style=st("checkbutton"))
        self.chk_auto_num.grid(row=0, column=0, sticky="w")
        ttk.Label(numbering, text="Start #", style=st("label")).grid(
            row=0, column=1, sticky="w", padx=(18, 0))
        self.var_start_num = tk.IntVar(value=1)
        self.entry_start_num = ttk.Entry(numbering, textvariable=self.var_start_num,
                                         width=6, style=st("entry"))
        self.entry_start_num.grid(row=0, column=2, sticky="w", padx=(8, 0))

        # Enabled/disabled follows the variable itself, so a mode set from
        # code behaves exactly like a click on the radio.
        self.var_metadata_mode.trace_add(
            "write", lambda *_a: self._sync_replacement_fields())

        # ---- 3. Output & Run ---------------------------------------------- #
        run = self.run_section
        run.columnconfigure(1, weight=1)
        ttk.Label(run, text="Output", style=st("label")).grid(row=0, column=0, sticky="w")
        # Read-only; the base lives in Preferences & Data.
        self.entry_outdir = ttk.Entry(run, textvariable=self.var_outdir,
                                      state="readonly", width=OUTDIR_CHARS,
                                      style=st("entry"))
        self.entry_outdir.grid(row=0, column=1, sticky="ew", padx=(8, 6))
        # Navigation, never a processing input, so it never locks.
        self.btn_open_out = ttk.Button(run, text="Open Output Folder",
                                       command=self.open_outdir, style=st("button"))
        self.btn_open_out.grid(row=0, column=2, sticky="e")
        self.output_note = ttk.Label(
            run,
            text="Each conversion gets its own numbered run folder here. "
                 "Change the location in Preferences & Data.",
            style=st("secondary_label"), justify=tk.LEFT, wraplength=NOTE_WRAP)
        self.output_note.grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 0))

        self.run_separator = ttk.Separator(run, orient=tk.HORIZONTAL,
                                           style=st("separator"))
        self.run_separator.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(6, 6))

        # Convert is the primary action: it leads the run row and is the
        # panel's default button, exactly as TTS's Start and Cover's Resize
        # Covers are. The panel's own ``Cancel`` button stays **retired**:
        # Pause, Resume, Cancel and Retry Failed belong to the shared control
        # bar beneath it, which offers each exactly when the approved
        # availability rules say it is meaningful. :meth:`cancel` survives as
        # the method that bar calls.
        self.run_row = ttk.Frame(run, style=st("surface"))
        self.run_row.grid(row=3, column=0, columnspan=3, sticky="ew")
        self.run_row.columnconfigure(0, weight=1)
        self.btn_convert = ttk.Button(
            self.run_row, text="Convert M4Bs → MP3s", command=self.start_convert,
            default="active", style=st("button"))
        self.btn_convert.grid(row=0, column=0, sticky="w")
        # The shared run controls and status view (progress, stage, ETA). The
        # adapter is rebuilt for each run -- one run, one event stream, one
        # estimate -- so this container holds its place in the layout.
        self.job_area = ttk.Frame(self.run_row, style=st("surface"))
        self.job_area.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.job_area.columnconfigure(0, weight=1)

        # ---- Activity: the one Summary | Detailed log --------------------- #
        # Built once and handed to every run's JobAdapter, so a fresh adapter's
        # empty first render can never drop an earlier run's lines. Summary is
        # the shared projection of the run's events; the worker's own raw
        # transcript -- the ffmpeg command lines, the per-file lines, the error
        # text the old "Log" box showed -- goes to Detailed (log_write), and the
        # run's closing line to both.
        act = self.activity
        act.columnconfigure(0, weight=1)
        act.rowconfigure(1, weight=1)
        bar = ttk.Frame(act, style=st("surface"))
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        bar.columnconfigure(0, weight=1)
        self.activity_note = ttk.Label(
            bar,
            text="Summary: progress and results.  Detailed: every step and the "
                 "ffmpeg transcript.",
            style=st("secondary_label"), justify=tk.LEFT,
            wraplength=ACTIVITY_NOTE_MIN_WRAP)
        self.activity_note.grid(row=0, column=0, sticky="w")
        # Not a processing option, so it never locks: clearing the visible log
        # never interferes with a run in flight.
        self.btn_clear_log = ttk.Button(bar, text="Clear Log", command=self.clear_log,
                                        style=st("button"))
        self.btn_clear_log.grid(row=0, column=1, sticky="e", padx=(8, 0))
        self.log = job_ui.SummaryDetailsView(
            act, theme=bundle, height=LOG_HEIGHT, width=LOG_WIDTH_CHARS,
            details_label="Detailed", limit=LOG_LIMIT)
        self.log.frame.grid(row=1, column=0, sticky="nsew")

        self.bind("<Configure>", self._on_panel_configure, add="+")

        # Initial checks (log instead of a modal so switching tools is quiet)
        # v0.6.2 Plan 5 Phase 15: this used to say "FFmpeg detected." whenever a
        # path resolved, which is what told the maintainer everything was fine
        # about an installation Windows was refusing to execute. The wording now
        # comes from ``status_line`` so "found" and "verified" cannot be confused
        # again, and so the distinction is stated in exactly one place. It
        # lands in both panes, as it always showed in the panel's one log, so
        # the FFmpeg state is visible the moment the tool opens.
        self.log_write(ffmpeg_utils.status_line() + "\n", summary=True)

        # One pump, one scheduled chain: the conversion queue is a drain on
        # the same pump the import poller rides, and so is the shared job
        # adapter's event drain -- the adapter registers itself on this very
        # pump rather than scheduling anything of its own. No second `after`
        # loop, and no timer.
        self._pump.add_drain(self._pump_queue)
        self._install_jobs(IDLE_RUN_ID, ())
        self._sync_replacement_fields()
        # Measured once everything exists, then placed; the first <Configure>
        # of a mapped panel re-decides the arrangement for the real size.
        self._measure_layout()
        self._apply_layout("wide")
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
        bundle = self.appearance_bundle
        self.jobs = job_ui.JobAdapter(
            self.job_area,
            run_id=run_id,
            pump=self._pump,
            # The shared compact bundle, exactly as Cover's and TTS's controls use it.
            theme=bundle,
            pull=job_ui.queue_pull(self._event_q),
            estimator=self._estimator,
            bridge=self._bridge,
            item_ids=item_ids,
            on_pause=self.pause,
            on_resume=self.resume,
            on_cancel=self.cancel,
            on_retry=self.retry_failed,
            # The panel's one persistent Summary/Detailed log in Activity, not a
            # fresh view per adapter: the adapter renders into it, and neither
            # places nor closes it.
            views=self.log,
        )
        self.jobs.frame.grid(row=0, column=0, sticky="nsew")
        # One progress model, not two: the panel's indicator *is* the shared
        # status view's, so nothing can draw a second, disagreeing bar.
        self.progress = self.jobs.status.indicator
        # Per-instance restyling, exactly as Cover and TTS do it: the shared
        # indicator stays generic for every panel that has not adopted the
        # compact system, but here an unstyled native frame would be a light
        # island in Dark. Aqua names inherit native controls.
        self.progress.frame.configure(style=job_ui.style_name(bundle, "card"))
        self.progress.bar.configure(style=job_ui.style_name(bundle, "progressbar"),
                                    length=PROGRESS_BAR_LENGTH)
        self.progress.label.configure(style=job_ui.style_name(bundle, "secondary_label"))
        # Long run text wraps, never widens Output & Run.
        for label in (self.jobs.status.label_stage, self.jobs.status.label_status):
            label.configure(wraplength=STATUS_WRAP)
        self.jobs.status.label_status.configure(
            style=job_ui.style_name(bundle, "secondary_label"))
        self._arrange_job_controls()
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
        if not ffmpeg_utils.verified_ffmpeg():
            # Verified, not merely found: a coherent path proves nothing about
            # whether this machine will execute it, which is exactly how a
            # conversion used to fail in front of the user.
            messagebox.showerror("FFmpeg is not ready",
                                 ffmpeg_utils.status_line())
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

        # Captured once, on the main thread, at the moment the run is accepted.
        self._run_config = shared_config.get_effective()

        params = {
            # The frozen occurrences themselves, not a reduced list of paths:
            # provenance is what the plan's destination routing needs, and
            # discarding it here only to re-derive it later is how it goes
            # missing.
            "imported_files": imported,
            "options": options,
            "snapshot": run,
            # **Which configuration this run belongs to, decided here and not
            # again.** Preflight runs on the worker and can take minutes on a
            # large queue; the reservation happens at the end of it. Leaving the
            # reservation to read the *live* configuration there meant a base
            # saved after Start silently moved a run that had already been
            # accepted -- while the run still reported itself against the
            # configuration it was frozen with. Capturing it once, here, on the
            # main thread, is the rule the rest of the snapshot already follows.
            # ``output_paths`` still owns what a base *means*; this only says
            # which configuration to ask. A later run captures again at its own
            # Start, so changing Preferences still takes effect normally -- it
            # just cannot reach backwards into a run already under way.
            "run_config": self._run_config,
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
            # The retry repeats an attempt whose destinations are already
            # frozen, so it reserves nothing; the configuration is carried only
            # so both attempts describe the same run.
            "run_config": self._run_config,
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
        self._inputs_locked = bool(state)
        widgets = [
            self.btn_convert,
            self.entry_quality,
            self.rb_whole,
            self.rb_split,
            self.rb_preserve,
            self.rb_replace,
            self.rb_strip,
            self.chk_auto_num,
            self.entry_start_num,
        ]
        for w in widgets:
            w.configure(state=tk.DISABLED if state else tk.NORMAL)
        # The four metadata fields follow the lock *and* the metadata mode, so
        # they never come back enabled under Write none.
        self._sync_replacement_fields()
        # The destination display is never typeable; it only greys out.
        self.entry_outdir.configure(state=tk.DISABLED if state else "readonly")

    def replacement_fields(self) -> tuple:
        """Title, Artist, Album Artist, Album -- in the form's reading order."""
        return (self.title_entry, self.artist_entry, self.album_artist_entry,
                self.album_entry)

    def _sync_replacement_fields(self) -> None:
        """Grey the four metadata fields out exactly when they cannot apply.

        Preserve lets a filled field override the source's own value and
        Replace writes only these fields, so both use them; Write none writes
        nothing, so there they are disabled -- visible and greyed, never
        hidden, so the form does not jump. A locked panel (a run in flight)
        keeps them disabled whatever the mode. Presentation only: the typed
        text is kept, and ``read_options`` reads it exactly as before.
        """
        if getattr(self, "_closed", True):
            return
        try:
            mode = self.var_metadata_mode.get()
        except tk.TclError:  # pragma: no cover - torn down
            return
        usable = not self._inputs_locked and mode != MetadataMode.STRIP.value
        for entry in self.replacement_fields():
            try:
                entry.configure(state=tk.NORMAL if usable else tk.DISABLED)
            except tk.TclError:  # pragma: no cover - torn down
                pass

    def log_write(self, text: str, *, summary: bool = False) -> None:
        """Add the worker's own transcript text to the Activity log.

        Detailed only by default -- the per-file transcript and the ffmpeg
        command lines are technical detail, and Summary is the shared
        adapter's own projection of the run. ``summary=True`` puts a line in
        both panes; the FFmpeg status and the run's closing line use it, so
        they are visible without switching tabs. Blank lines the worker uses
        as spacing are dropped: each view line is already its own row. The
        same contract Cover Image's Activity uses.
        """
        lines = [line for line in str(text).splitlines() if line.strip()]
        if getattr(self, "_closed", True) or not lines:
            return
        if summary:
            for line in lines:
                self.log.append(line)
        else:
            self.log.append_detail(lines)

    def clear_log(self) -> None:
        """Clear the visible Summary + Detailed text only. The run's own event
        stream, the session log and any settled result are untouched."""
        if not self._closed:
            self.log.clear()

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
                    self.log_write(payload[0], summary=True)
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
        """Run the conversion, and **never let anything escape this thread**.

        The body below is the run. This wrapper exists because the body is not
        the last word on whether the window unlocks: ``done`` is, and ``done`` is
        sent from inside the body. An exception thrown anywhere in the execution
        loop -- the final move meeting a full disk, an ejected volume, or a file
        an antivirus scanner still holds open -- therefore ended the worker
        thread with ``_busy`` still set, the controller still ``RUNNING`` and
        ``Convert`` disabled for the rest of the session, with nothing said to
        the user. A daemon thread dying silently is the one failure a person
        cannot work around.

        So the shape ``JobController`` prescribes for a worker, and that the TTS
        and Cover panels already use, is applied here: settle the run, say so,
        and send ``done`` regardless. The settlement is guarded too, because a
        fault raised while reporting a fault must not be the thing that strands
        the window.
        """
        try:
            self._run_conversion(params)
        except ConversionCancelled:
            # The body handles its own cancellation and sends ``done``. Reaching
            # here means one escaped a path that does not, so settle it as a
            # cancellation rather than as a fault.
            self._settle_unexpected(params, None)
        except BaseException as exc:  # noqa: BLE001 - deliberately everything
            self._settle_unexpected(params, exc)

    def _settle_unexpected(self, params: dict, exc: BaseException | None) -> None:
        """Close out a run whose worker did not finish, and free the window.

        Every step is independently guarded: a failure while reporting a failure
        must not strand the panel. ``done`` is sent last and unconditionally,
        because that is the message ``_finish_idle`` listens for.
        """
        detail = "" if exc is None else f"{type(exc).__name__}: {exc}"
        message = ("The run stopped unexpectedly and was not completed."
                   if exc is not None else "Cancelled.")
        try:
            self._log_q.put(("log", f"\n  ✗ {message}\n"
                                    + (f"     {detail}\n" if detail else "")))
        except Exception:  # pragma: no cover - a queue that will not take a line
            pass
        controller = params.get("controller")
        reporter = params.get("reporter")
        try:
            if controller is not None and exc is not None:
                final = controller.fail(message, detail)
                if reporter is not None:
                    reporter.completed(final)
            elif controller is not None:
                final = controller.finish_cancelled()
                if reporter is not None:
                    reporter.cancelled(final)
        except Exception:  # pragma: no cover - already failing; do not mask it
            pass
        try:
            self._log_q.put(("done", ("\nThe run did not complete.\n", None)))
        except Exception:  # pragma: no cover
            pass

    def _run_conversion(self, params: dict):
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
                reservation = output_paths.reserve_run_directory(
                    TOOL_KEY, effective=params.get("run_config"))
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
                if item.undecodable_xhe and item.windows_decode:
                    # v0.6.2 Plan 5 Phase 15: ffmpeg drops 23.91% of a real
                    # xHE-AAC book's frames, so Windows decodes this one.
                    note_text = (f"{in_file.name} is xHE-AAC, so its audio is "
                                 "decoded by Windows rather than by ffmpeg.")
                    self._log_q.put(("log", f"  {note_text}\n"))
                    if reporter is not None:
                        reporter.warning(note_text, f"codec={item.codec_hint}")
                elif item.undecodable_xhe:
                    trouble = (f"{in_file.name} is xHE-AAC and this ffmpeg "
                               "build has no decoder for it on this platform, "
                               "so the output may be sped up or choppy.")
                    self._log_q.put(("log", f"  \u26a0 WARNING: {trouble}\n"))
                    if reporter is not None:
                        reporter.warning(trouble, f"codec={item.codec_hint}")

                # One decode serves every output of this item. Seeking a USAC
                # decoder costs 0.183s of primed audio per jump -- measured --
                # so a split book is cut in the PCM stream instead, in the
                # frozen order the segments already run in.
                timeline = None
                if item.windows_decode:
                    try:
                        timeline = m4b_winaudio.PcmTimeline(
                            in_file, cancelled=interrupted)
                    except Exception as exc:  # noqa: BLE001
                        note(item_id,
                             f"{in_file.name}: its audio could not be decoded.",
                             f"{type(exc).__name__}: {exc}",
                             STAGE_CONVERT, retryable=True)
                        continue

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
                        # Carried, never re-derived: the preflight already
                        # decided this, and it is the only thing that entitles a
                        # duration mismatch to name a cause.
                        undecodable_xhe=item.undecodable_xhe,
                        windows_decode=item.windows_decode,
                        pcm_args=(() if timeline is None
                                  else tuple(timeline.format.ffmpeg_input_args())),
                        # Frozen at preflight with everything else, so the worker
                        # never re-opens the book to recover what its chapters
                        # were called.
                        chapter_titles=item.chapter_titles,
                    )

                    self._log_q.put((
                        "log", f"  -> {segment.destination}\n"))
                    started = clock() if timed else None
                    feed = None
                    if timeline is not None:
                        wanted = (timeline.bytes_for(segment.end - segment.start)
                                  if item.fragment else None)

                        def feed(write, _wanted=wanted):
                            timeline.feed(write, _wanted)

                    outcome = m4b_execution.convert_segment(
                        work,
                        ffmpeg=ffmpeg_utils.ffmpeg_cmd(),
                        cancelled=interrupted,
                        measure=measured_duration,
                        sources=tuple(entry.path for entry in imported),
                        on_command=announce,
                        feed=feed,
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

                if timeline is not None:
                    # Released on every route out of this item, including a
                    # failure or a cancel: a live decoder is a held file handle.
                    timeline.close()

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


    # ------- appearance: the shared compact control language -------

    def _style(self, key: str) -> str:
        """The shared compact style for *key* (native control inheritance on Aqua)."""
        return job_ui.style_name(self.appearance_bundle, key)

    def _on_appearance_changed(self, bundle: dict) -> None:
        """Re-color the few classic Tk widgets a ttk style mutation cannot reach.

        Every ttk widget here names a ``Compact.*`` style, and
        ``shared.appearance`` reconfigured those in place before calling this,
        so they have already repainted. What is left is classic Tk: the
        importer's ``Listbox`` and the Activity log's two ``Text`` panes.
        Nothing is rebuilt, so no import, selection, mode, metadata value,
        output setting, log line, progress or running job moves.
        """
        self.appearance_bundle = bundle
        if getattr(self, "_closed", True):
            return
        importer = getattr(self, "importer", None)
        if importer is not None:
            importer.list.apply_appearance(bundle)
        log = getattr(self, "log", None)
        if log is not None:
            log.apply_appearance(bundle)

    # ------- layout: measured, responsive, never a whole-panel scrollbar -------

    def _arrange_sections(self, narrow: bool) -> None:
        """Re-grid the few controls whose best arrangement depends on width.

        Only grid positions, padding and requested widths change -- the same
        widgets, variables and commands, and nothing of the importer's state.
        The six import actions keep the frozen §4 order, three per row (the
        workflow column is never wide enough for six); the import options take
        Cover's two rows. ``narrow`` is the small-window split, which also takes
        TTS's tight-window steps: less section padding, a shorter requested
        path field and the job controls in two rows of two.
        """
        padding = SPLIT_SECTION_PADDING if narrow else SECTION_PADDING
        for section in (self.sources_section, self.options_section, self.run_section,
                        self.activity):
            section.configure(padding=padding)
        gap = 3 if narrow else 4
        for index, (key, _label) in enumerate(job_ui.ImportedFileList.ACTIONS):
            row, column = divmod(index, 3)
            self.importer.list.buttons[key].grid_configure(
                row=row, column=column, padx=(0 if column == 0 else 4, 0),
                pady=(0 if row == 0 else gap, 0), sticky="ew")
        options = self.importer.options
        types = list(options.type_buttons.values())
        count = len(types)
        for column, button in enumerate(types):
            button.grid_configure(row=0, column=column, columnspan=1, sticky="w",
                                  padx=(0 if column == 0 else 8, 0), pady=0)
        options.check_subfolders.grid_configure(
            row=0, column=count, columnspan=1, sticky="w", padx=(14, 0), pady=0)
        options.check_hidden.grid_configure(
            row=1, column=0, columnspan=count, sticky="w", padx=0, pady=(1, 0))
        options.check_duplicates.grid_configure(
            row=1, column=count, columnspan=1, sticky="w", padx=(14, 0), pady=(1, 0))
        options.frame.grid_configure(pady=(gap, 0))
        self.importer.status.frame.grid_configure(pady=(gap, 0))
        self.options_separator.grid_configure(pady=(4, 3) if narrow else (6, 5))
        self.run_separator.grid_configure(pady=(4, 4) if narrow else (6, 6))
        self.entry_outdir.configure(width=SPLIT_OUTDIR_CHARS if narrow else OUTDIR_CHARS)
        self._arrange_job_controls(narrow)

    def _arrange_job_controls(self, narrow: bool | None = None) -> None:
        """The shared job controls: one row, or two rows of two in split.

        Grid positions only -- the shared bar still decides which of the four
        is available.
        """
        jobs = getattr(self, "jobs", None)
        if jobs is None:
            return
        if narrow is None:
            narrow = self._layout_mode == "split"
        for index, button in enumerate(jobs.controls.buttons.values()):
            row, column = divmod(index, 2) if narrow else (0, index)
            button.grid_configure(row=row, column=column,
                                  padx=(0 if column == 0 else 4, 0),
                                  pady=(0 if row == 0 else 4, 0),
                                  sticky="ew" if narrow else "")
        jobs.status.frame.grid_configure(pady=(4, 0))

    def _measure_layout(self) -> None:
        """Measure what each arrangement needs, from the live widgets.

        Every threshold :meth:`_choose_layout` uses comes from here -- the
        three sections' natural sizes in both inner arrangements, Activity's,
        the imported list's row height, and how much height the list and the
        log may give up before their floors -- so the breakpoints follow the
        platform's real fonts and scaling rather than pixel constants. The
        captions are measured at their narrow wrap, so prose never decides a
        section's width.
        """
        listbox = self.importer.list.listbox
        listbox.configure(height=IMPORTER_LIST_HEIGHT)
        sections = {"sources": self.sources_section, "options": self.options_section,
                    "run": self.run_section}
        inset = SECTION_PADDING[0] + SECTION_PADDING[2] + 6
        needs: dict = {}
        for narrow in (False, True):
            self._arrange_sections(narrow)
            # Widths first, with both captions at a narrow wrap ...
            self.output_note.configure(wraplength=NOTE_WRAP)
            self.activity_note.configure(wraplength=NOTE_WRAP)
            self.update_idletasks()
            widths = {name: widget.winfo_reqwidth() for name, widget in sections.items()}
            activity_w = self.activity.winfo_reqwidth()
            # ... then heights, with each caption wrapped at the narrowest width
            # its column will actually get in this arrangement.
            if narrow:
                run_col = act_col = max(widths["run"], ACTIVITY_MIN_WIDTH)
            else:
                run_col, act_col = max(widths.values()), activity_w
            self.output_note.configure(wraplength=max(NOTE_WRAP, run_col - inset))
            self.activity_note.configure(wraplength=max(
                ACTIVITY_NOTE_MIN_WRAP,
                act_col - inset - self.btn_clear_log.winfo_reqwidth() - 8))
            self.update_idletasks()
            needs["split" if narrow else "wide"] = {
                name: (widths[name], widget.winfo_reqheight())
                for name, widget in sections.items()}
            needs["activity_split" if narrow else "activity"] = (
                activity_w, self.activity.winfo_reqheight())
        row_px = listbox.winfo_reqheight() / IMPORTER_LIST_HEIGHT
        needs["list_row_px"] = row_px
        needs["list_give"] = int(row_px * (IMPORTER_LIST_HEIGHT - IMPORTER_FLOOR_ROWS))
        needs["list_give_split"] = int(
            row_px * (IMPORTER_LIST_HEIGHT - IMPORTER_SPLIT_FLOOR_ROWS))
        line = tkfont.Font(font=self.log.summary_text.cget("font")).metrics("linespace")
        needs["log_give"] = int(line) * (LOG_HEIGHT - LOG_FLOOR_LINES)
        self._needs = needs
        self._arrange_sections(self._layout_mode == "split")

    def _workflow_needs(self, mode: str) -> tuple[int, int]:
        """The workflow's natural width and its floor height in *mode*.

        In ``split`` the workflow is 1 over 2 only; 3 stands above Activity.
        """
        n = self._needs
        if mode == "split":
            s = n["split"]
            return (max(s["sources"][0], s["options"][0]),
                    s["sources"][1] - n["list_give_split"] + SECTION_GAP
                    + s["options"][1])
        s = n["wide"]
        return (max(s["sources"][0], s["options"][0], s["run"][0]),
                s["sources"][1] - n["list_give"] + 2 * SECTION_GAP
                + s["options"][1] + s["run"][1])

    def _split_right_needs(self) -> tuple[int, int]:
        """The split arrangement's right column: 3 over Activity at its floor."""
        n = self._needs
        run_w, run_h = n["split"]["run"]
        activity_floor = n["activity_split"][1] - n["log_give"]
        return (max(run_w, ACTIVITY_MIN_WIDTH),
                run_h + SECTION_GAP + activity_floor)

    def _choose_layout(self, width: int, height: int) -> str:
        """Pick the arrangement for a panel of this size. A pure function of it.

        Activity is on the right whenever it can be. The vertical workflow
        (1 over 2 over 3) is used when it and a usable log both fit; where it
        cannot -- the real launcher's small content areas -- the approved TTS
        precedent: 1 over 2 on the left, 3 over Activity on the right. Only a
        panel too small even for that drops Activity beneath the workflow.
        """
        room_w = width - 2 * OUTER_PAD
        room_h = height - 2 * OUTER_PAD
        activity_floor = self._needs["activity"][1] - self._needs["log_give"]
        flow_w, flow_floor = self._workflow_needs("wide")
        if (flow_w + COLUMN_GAP + ACTIVITY_MIN_WIDTH <= room_w
                and max(flow_floor, activity_floor) <= room_h):
            return "wide"
        left_w, left_floor = self._workflow_needs("split")
        right_w, right_floor = self._split_right_needs()
        if (left_w + COLUMN_GAP + right_w <= room_w
                and max(left_floor, right_floor) <= room_h):
            return "split"
        return "stacked"

    def _left_width(self, width: int) -> int:
        """The workflow column's width beside Activity.

        Its natural width, or -- one vertical column on a wide window --
        WORKFLOW_SHARE of the panel when that is more, never leaving Activity
        less than ACTIVITY_MIN_WIDTH. In split the left column keeps its
        natural width and the right column (3 over Activity) takes the rest.
        """
        mode = self._layout_mode or "wide"
        flow_w, _ = self._workflow_needs("split" if mode == "split" else "wide")
        if mode != "wide" or width <= 1:
            return flow_w
        room_w = width - 2 * OUTER_PAD
        share = int(room_w * WORKFLOW_SHARE)
        return max(flow_w, min(share, room_w - COLUMN_GAP - ACTIVITY_MIN_WIDTH))

    def _grid_workflow(self, mode: str) -> None:
        flow = self.workflow
        for index in (0, 1, 2, 3):
            flow.rowconfigure(index, weight=0, minsize=0)
        for index in (0, 1):
            flow.columnconfigure(index, weight=0, minsize=0)
        self.sources_section.grid(row=0, column=0, columnspan=2, sticky="nsew",
                                  padx=0, pady=0)
        if mode == "stacked":
            # Last resort: 2 beside 3 under Sources, so the whole workflow is
            # as short as it can be above Activity.
            self.options_section.grid(row=1, column=0, columnspan=1, sticky="nsew",
                                      padx=(0, SECTION_GAP), pady=(SECTION_GAP, 0))
            self.run_section.grid(in_=flow, row=1, column=1, columnspan=1,
                                  sticky="nsew", padx=0, pady=(SECTION_GAP, 0))
            flow.columnconfigure(0, weight=1)
            flow.columnconfigure(1, weight=1)
            return
        self.options_section.grid(row=1, column=0, columnspan=2, sticky="nsew",
                                  padx=0, pady=(SECTION_GAP, 0))
        flow.columnconfigure(0, weight=1)
        if mode == "wide":
            self.run_section.grid(in_=flow, row=2, column=0, columnspan=2,
                                  sticky="nsew", padx=0, pady=(SECTION_GAP, 0))

    def _apply_layout(self, mode: str) -> None:
        """Grid the workflow and Activity for one arrangement, then set floors."""
        if self._needs is None:
            return
        self._layout_mode = mode
        self._arrange_sections(mode == "split")
        self._grid_workflow(mode)
        for index in (0, 1):
            self.columnconfigure(index, weight=0, minsize=0)
            self.rowconfigure(index, weight=0, minsize=0)
        half = COLUMN_GAP // 2
        if mode == "split":
            # 1 over 2 on the left, spanning the panel's height; 3 over
            # Activity on the right, Activity taking whatever height is left.
            self.workflow.grid(row=0, column=0, rowspan=2, sticky="nsew",
                               padx=(OUTER_PAD, half), pady=OUTER_PAD)
            self.run_section.grid(in_=self, row=0, column=1, columnspan=1,
                                  sticky="nsew", padx=(COLUMN_GAP - half, OUTER_PAD),
                                  pady=(OUTER_PAD, 0))
            self.activity.grid(row=1, column=1, rowspan=1, sticky="nsew",
                               padx=(COLUMN_GAP - half, OUTER_PAD),
                               pady=(SECTION_GAP, OUTER_PAD))
            self.columnconfigure(1, weight=1)
        elif mode == "wide":
            self.workflow.grid(row=0, column=0, rowspan=1, sticky="nsew",
                               padx=(OUTER_PAD, half), pady=OUTER_PAD)
            self.activity.grid(row=0, column=1, rowspan=1, sticky="nsew",
                               padx=(COLUMN_GAP - half, OUTER_PAD), pady=OUTER_PAD)
            self.columnconfigure(1, weight=1)
        else:
            self.workflow.grid(row=0, column=0, rowspan=1, sticky="nsew",
                               padx=OUTER_PAD, pady=(OUTER_PAD, half))
            self.activity.grid(row=1, column=0, rowspan=1, sticky="nsew",
                               padx=OUTER_PAD, pady=(COLUMN_GAP - half, OUTER_PAD))
            self.columnconfigure(0, weight=1)
        self._size_columns()
        self._rewrap()
        self._apply_floors()

    def _size_columns(self) -> None:
        """Beside Activity, fix the workflow column's width from the layout
        math -- never from ``grid`` weights, so the log, not the controls,
        takes the room a wider window adds."""
        if self._layout_mode not in ("wide", "split") or self._needs is None:
            return
        minsize = self._left_width(self.winfo_width()) + OUTER_PAD + COLUMN_GAP // 2
        if int(self.grid_columnconfigure(0)["minsize"]) != minsize:
            self.columnconfigure(0, weight=0, minsize=minsize)

    def _rewrap(self) -> bool:
        """Wrap each caption to the width its section actually has, so a wide
        window shows it on fewer lines and the minimum on more -- never letting
        a caption decide a column's width (TTS's rule). True if any moved."""
        if self._needs is None or self._layout_mode is None:
            return False
        width = self.winfo_width()
        if width <= 1:
            return False
        room_w = width - 2 * OUTER_PAD
        inset = SECTION_PADDING[0] + SECTION_PADDING[2] + 6
        if self._layout_mode == "stacked":
            left = activity = room_w
            run = room_w // 2
        else:
            left = self._left_width(width)
            activity = room_w - COLUMN_GAP - left
            run = activity if self._layout_mode == "split" else left
        targets = (
            (self.output_note, max(NOTE_WRAP, run - inset)),
            (self.activity_note, max(ACTIVITY_NOTE_MIN_WRAP,
                                     activity - inset
                                     - self.btn_clear_log.winfo_reqwidth() - 8)),
        )
        changed = False
        for label, wrap in targets:
            if int(float(str(label.cget("wraplength")) or 0)) != wrap:
                label.configure(wraplength=wrap)
                changed = True
        return changed

    def _apply_floors(self) -> None:
        """Keep the list and the log from being squeezed below their floors.

        ``grid`` takes a shortfall out of weighted rows only, and below a row's
        minsize it clips rather than shrinks -- so every elastic row gets a
        floor measured from the live widgets. Measured after wrapping, so a
        caption that grew a line is already counted.
        """
        if self._needs is None or self._layout_mode is None:
            return
        try:
            self.update_idletasks()
        except tk.TclError:  # pragma: no cover - torn down
            return
        give_log = self._needs["log_give"]
        give_list = (self._needs["list_give_split"] if self._layout_mode == "split"
                     else self._needs["list_give"])
        self.activity.rowconfigure(
            1, weight=1, minsize=max(0, self.log.frame.winfo_reqheight() - give_log))
        activity_floor = max(0, self.activity.winfo_reqheight() - give_log)
        sources_floor = max(0, self.sources_section.winfo_reqheight() - give_list)
        self.workflow.rowconfigure(0, weight=1, minsize=sources_floor)
        half = COLUMN_GAP // 2
        if self._layout_mode == "wide":
            self.rowconfigure(0, weight=1, minsize=activity_floor + 2 * OUTER_PAD)
        elif self._layout_mode == "split":
            self.rowconfigure(0, weight=0, minsize=0)
            self.rowconfigure(1, weight=1,
                              minsize=activity_floor + SECTION_GAP + OUTER_PAD)
        else:
            flow_floor = max(0, self.workflow.winfo_reqheight() - give_list)
            self.rowconfigure(0, weight=1, minsize=flow_floor + OUTER_PAD + half)
            self.rowconfigure(1, weight=2,
                              minsize=activity_floor + OUTER_PAD + COLUMN_GAP - half)

    def _reflow(self, force: bool = False) -> None:
        width, height = self.winfo_width(), self.winfo_height()
        if width <= 1 or height <= 1 or self._needs is None:
            return
        mode = self._choose_layout(width, height)
        if force or mode != self._layout_mode:
            self._apply_layout(mode)
            return
        self._size_columns()
        if self._rewrap():
            self._apply_floors()

    def _on_panel_configure(self, event) -> None:
        if event.widget is not self or self._closed or self._needs is None:
            return
        self._reflow()

    @property
    def layout_mode(self) -> str | None:
        """The arrangement currently applied: ``wide``, ``split`` or ``stacked``."""
        return self._layout_mode

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
        appearance.unregister_listener(self._on_appearance_changed)
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
