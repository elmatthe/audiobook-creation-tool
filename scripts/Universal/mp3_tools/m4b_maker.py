#!/usr/bin/env python3
"""M4B Maker — build chaptered M4B audiobooks from ordered MP3s, one Book at a time.

v0.6.4 Phase 6: the production panel is a **thin Tk composition/orchestration
adapter** over the completed Maker layers. No business rule lives in a widget:

- **Workspace.** The shared Plan 6 multi-Book workspace: ``Import Folder`` scans
  one parent through the shared ``ImportCoordinator`` and projects the committed
  snapshot into **one Book per directory that directly contains MP3s**
  (``m4b_maker_workflow.import_folder``); ``Add Files`` puts the chosen MP3s
  into the **current** Book (``add_files``). Previous / Next / ``Book X of Y`` /
  the direct selector / Add / Duplicate / Remove are the shared ``BookNavigator``
  with its default action set; every press asks the model and renders the result.
  The panel owns no list of paths — the current Book's ``ImportedFileSnapshot``
  is the list shown.
- **Shared and Book fields.** The Shared area is exactly the Maker's six —
  Artist / Author, Album Artist / Author, Album, Series Name, Silence Between
  Tracks (seconds), Artwork. The five text fields are the shared
  ``SharedMetadataSurface`` (``rows`` layout); artwork is the common M4B
  ``ArtworkControl`` (Phase 1's deferred seam), once for Shared and once for
  the Book. A populated Shared value disables the matching Book control and
  leaves the Book's stored value intact — ``disabled_fields`` decides, never
  this panel. The Book-only fields — Title, Series Part, Output Filename,
  Chapter Titles — are this panel's own entries and box, stored raw through
  ``set_book_field``; the Chapter Titles box shows the Phase 2 defaults until
  the user edits it.
- **Run options.** Auto-number Series Part + Start Part (batch-level; the
  manual Series Part entry is disabled while Auto-number is on), Fast-first,
  and the explicit custom destination (Decision 10A): a toggle that reveals a
  path row, never persisted, off on every fresh build.
- **Build.** Validates, reserves **one** standard run (or validates the custom
  folder and makes an operation-owned work root outside it), freezes one
  immutable ``RunPlan`` through ``m4b_maker_plan``, and hands it to **one**
  ``MakerRun`` (Phase 5). The worker body is ``Attempt.run`` on one thread; its
  events cross to the panel through a queue the shared ``JobAdapter`` drains on
  the one ``MainThreadPump``. Pause / Resume / Cancel / Retry Failed are the
  shared control bar's, forwarded to the run; locking is the shared
  ``LockGroup`` applying the job-state matrix. Book status is read from the
  attempt's settled records and, afterwards, the frozen ``WorkspaceRunResult``
  — never from a second state model. Retry Failed re-runs the frozen run's
  failed Books only; nothing typed since can reach it.
- **Log.** One region, ``Summary`` | ``Detailed``, whose history survives from
  run to run with a divider per attempt; Clear Log clears the visible text only.

Removed with the single-Book form: the raw file list, the private worker,
cancel event and log queue, the FFmpeg helpers (now ``m4b_maker_processing``),
and the panel's own filename logic (now ``m4b_maker_plan``).

Presentation: every widget asks ``job_ui.style_name`` for the approved ``ACT.*``
style on Windows; on macOS and the classic branch the lookup returns ``""`` and
the panel is drawn natively. No colour, font or metric is declared here. Nothing
scrolls the whole tool: the track list, the Chapter Titles box and the log
scroll locally and give up height first. Where the theme's metrics carry the
panel hints (the aqua bundle) the navigator's Book actions fold under its
navigation row, the actions stack, and the artwork buttons take their natural
width — the same seam the MP3 Tool reads, and only where things sit differs.
"""

import queue
import sys
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Make the scripts/ root importable so `shared.*` resolves whether this tool is
# run standalone (python mp3_tools/m4b_maker.py) or imported by the launcher.
_SCRIPTS_ROOT = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ROOT))

from shared import config as shared_config
from shared import job_control
from shared import job_ui
from shared import output_paths
from shared import paths
from shared import settings
from shared import ui_theme
from shared.book_workspace import (
    BookDisposition,
    SharedMetadata,
    WorkspaceRunResult,
    WorkspaceSnapshot,
    add_book,
    disabled_fields,
    duplicate_book,
    has_meaningful_work,
    next_book,
    previous_book,
    remove_book,
    select_book,
    set_shared_metadata,
)
from shared.book_workspace_ui import BookNavigator, SharedMetadataSurface
from shared.import_coordination import (
    TERMINAL_STATUSES,
    ImportCoordinator,
    ImportOutcome,
    ImportPoller,
    OutcomeStatus,
    StartOutcome,
)
from shared.importing import (
    IdFactory,
    ImportOptions,
    ImportRoot,
    ImportedFileManager,
    RootKind,
    ScanRequest,
)
from shared.job_control import JobEventKind, JobState, TERMINAL_STATES
from shared.job_ui import MainThreadGuard, MainThreadPump, style_name
from mp3_tools import m4b_artwork_ui
from mp3_tools import m4b_maker_batch as batch
from mp3_tools import m4b_maker_plan as mp
from mp3_tools import m4b_maker_workflow as wf
from mp3_tools.m4b_artwork_ui import ArtworkControl

APP_TITLE = "M4B Maker"

# Every standard build lands in <output base>/M4B-Maker-Outputs/M4B-Maker-N
# through the shared service; the custom destination is the explicit exception.
CUSTOM_DEST_LABEL = "Choose custom destination"

TOOL_KEY = "m4b_maker"
SLUG = paths.TOOL_SLUGS[TOOL_KEY]

# settings.json keys (input/cover dirs only remember the dialog location; the
# output folder and the custom destination are NOT persisted).
KEY_INPUT_DIR = "m4b_maker.input_dir"
KEY_COVER_DIR = "m4b_maker.cover_dir"

#: The compact status shown for the current Book, read from the run.
STATUS_READY = "Ready"
STATUS_QUEUED = "Queued"
STATUS_PROCESSING = "Processing"
STATUS_COMPLETED = "Completed"
STATUS_FAILED = "Failed"
STATUS_SKIPPED = "Skipped"
STATUS_NOT_ATTEMPTED = "Not attempted"

#: Characters of Title / Album / folder hint shown after ``Book N`` before eliding.
HINT_LIMIT = 40

#: How many frozen Summary and Detailed lines the log region keeps.
LOG_LIMIT = 400

#: The run id the job area carries before any operation has started.
IDLE_RUN_ID = "m4b-idle"

#: Rules a line under the previous run's lines in both log panes.
DIVIDER_MARK = "────"

#: The prefix of the operation-owned staging root a custom build uses.
WORK_ROOT_PREFIX = "act-m4b-build-"


# ---------------------------
# Utilities
# ---------------------------


def _remembered_dir(key: str) -> Path:
    """Return the saved folder for ``key`` if it still exists, else the home dir."""
    val = settings.get(key)
    if val:
        p = Path(val)
        if p.exists():
            return p
    return Path.home()


def _layout_hints(theme) -> dict:
    """The panel's composition, read off the theme bundle with its own defaults.

    The defaults are the accepted Windows composition. A theme whose ``metrics``
    carry the panel hints (the aqua bundle) overrides them; one without changes
    nothing. Presentation only: nothing read here reaches the model or the plan.
    """
    metrics = (theme or {}).get("metrics") or {}
    if not isinstance(metrics, Mapping):
        metrics = {}
    return {
        "pad": int(metrics.get("panel_pad", 10)),
        "gap": int(metrics.get("panel_gap", 6)),
        "gap_small": int(metrics.get("panel_gap_small", 4)),
        "navigator_layout": str(metrics.get("navigator_layout", "row")),
        "actions_layout": str(metrics.get("actions_layout", "row")),
        "entry_width": int(metrics.get("field_entry_width", 10)),
        "label_wrap": metrics.get("field_label_wrap"),
        "label_wrap_narrow": metrics.get("field_label_wrap_narrow"),
        "artwork_buttons": str(metrics.get("artwork_buttons", "fixed")),
        "artwork_gap": int(metrics.get("artwork_gap", 12)),
    }


def _label_wraps(hints: Mapping[str, object], fields) -> dict[str, int] | None:
    """Per-field label widths for the metadata surface, or ``None`` for none."""
    wide = hints.get("label_wrap")
    if wide is None:
        return None
    narrow = hints.get("label_wrap_narrow")
    wraps = {}
    for key in fields:
        if key == "silence":
            wraps[key] = int(wide)
        elif narrow is not None:
            wraps[key] = int(narrow)
    return wraps


# ---------------------------
# GUI
# ---------------------------


class M4BMakerUI(ttk.Frame):
    """The M4B Maker as an embeddable frame: a multi-Book workspace."""

    #: The Book-only text fields this panel draws itself, in order.
    BOOK_TEXT_FIELDS = ("title", "series_part", "output_filename")

    def __init__(
        self,
        parent: tk.Misc,
        *,
        theme=None,
        clock=None,
        effective_config=None,
        id_factory: IdFactory | None = None,
        scanner=None,
        thread_factory=None,
        choose_files=None,
        choose_folder=None,
        choose_artwork=None,
        choose_destination=None,
        confirm_broad_root=None,
        confirm_large_result=None,
        confirm=None,
        home=None,
        bridge=None,
        run_factory=None,
    ):
        """Build the panel.

        Every keyword is a seam the tests drive instead of a real dialog, clock
        or thread. Production passes none of them. ``thread_factory`` makes both
        the import scan's thread and the processing worker's; ``run_factory``
        builds the ``MakerRun`` (the Phase 5 class by default).
        """
        if theme is None:
            theme = ui_theme.apply_theme(parent.winfo_toplevel(), ttk.Style(parent))
        super().__init__(parent, style=style_name(theme, "window"))
        self.theme = theme
        self._guard = MainThreadGuard()
        self._closed = False
        self._clock = time.monotonic if clock is None else clock
        self._effective_config = (shared_config.get_effective()
                                  if effective_config is None
                                  else effective_config)
        self._ids = IdFactory("m4b-") if id_factory is None else id_factory
        self._choose_files = self._ask_files if choose_files is None else choose_files
        self._choose_folder = self._ask_folder if choose_folder is None else choose_folder
        self._choose_artwork = (self._ask_artwork if choose_artwork is None
                                else choose_artwork)
        self._choose_destination = (self._ask_destination if choose_destination is None
                                    else choose_destination)
        self._confirm = self._ask_confirm if confirm is None else confirm
        self._confirm_large = (self._confirm_large_result
                               if confirm_large_result is None
                               else confirm_large_result)
        self._thread_factory = (self._default_thread if thread_factory is None
                                else thread_factory)
        self._bridge = job_control.LoggerBridge() if bridge is None else bridge
        self._run_factory = batch.MakerRun if run_factory is None else run_factory

        # --- the workspace ------------------------------------------------- #
        # The one mutable reference to the current immutable workspace lives
        # here. Every edit asks a model operation and renders the value back.
        self.workspace: WorkspaceSnapshot = wf.new_workspace(id_factory=self._ids)
        # The user-facing Book number by stable id: assigned once, never reused
        # while that workspace lives; a folder import starts again at 1.
        self.book_numbers: dict[str, int] = {}
        #: The most recently frozen plan and the run that executes it. Retry
        #: Failed reads only these; nothing here reads them back into widgets.
        self.last_plan: mp.RunPlan | None = None
        self.run: batch.MakerRun | None = None
        self._attempt: batch.Attempt | None = None
        self._rendering = False

        # --- the shared importing foundation ------------------------------- #
        self._pump = MainThreadPump(self)
        self._manager = ImportedFileManager(id_factory=self._ids)
        self._coordinator = ImportCoordinator(
            self._manager,
            scanner=scanner,
            clock=self._clock,
            id_factory=self._ids,
            confirm_broad_root=(self._confirm_broad_root
                                if confirm_broad_root is None
                                else confirm_broad_root),
            thread_factory=thread_factory,
            **({} if home is None else {"home": home}),
        )
        self._poller = ImportPoller(
            self._coordinator, self._pump.schedule, cancel=self._pump.cancel,
            interval_ms=self._pump.interval_ms, on_outcome=self._handle_outcome)
        self._import_kind: str | None = None

        # Where the next standard run will go, shown read-only.
        self.var_outdir = tk.StringVar(value=output_paths.destination_hint(TOOL_KEY))
        output_paths.register_destination_hint(TOOL_KEY, self.var_outdir)

        self._build(theme)

        # Run locking is the shared contract: the adapter's lock group applies
        # the approved matrix to these seams whenever the run's state moves.
        self._tracks_lock = self._ButtonLock(
            self.btn_add_files, self.btn_move_up, self.btn_move_down,
            self.btn_remove_tracks)
        self._import_lock = self._ButtonLock(self.btn_import_folder)
        self._options_lock = self._ButtonLock(
            self.btn_build, self.check_auto_number, self.entry_start_part,
            self.check_fast_first, self.chk_custom_dest, self.entry_custom,
            self.btn_browse_custom, self.book_entries["title"],
            self.book_entries["output_filename"])
        # Series Part has two disabling reasons -- Auto-number and the run
        # lock -- kept apart in one seam, the way the artwork control does it.
        self._series_part_lock = self._SeriesPartSeam(self)
        self._chapters_lock = self._TextLock(self.chapter_text)
        self._install_jobs(IDLE_RUN_ID, ())

        self.render()
        self._pump.start()

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #

    def _build(self, theme) -> None:
        hints = _layout_hints(theme)
        pad, gap, gap_small = hints["pad"], hints["gap"], hints["gap_small"]
        self.columnconfigure(0, weight=1)
        # Pinned rows keep their requested height; the two variable-length
        # regions -- tracks/chapters and the log -- absorb a short window, so
        # at 920x600 the actions row never falls off the bottom and no
        # whole-panel scrollbar is needed.
        self.rowconfigure(0, weight=0)   # Import Folder, import status, output
        self.rowconfigure(1, weight=0)   # navigator
        self.rowconfigure(2, weight=0)   # Shared + Current Book
        self.rowconfigure(3, weight=3)   # tracks | chapter titles -- scroll
        self.rowconfigure(4, weight=0)   # run options
        self.rowconfigure(5, weight=0)   # Build, job controls, progress
        self.rowconfigure(6, weight=2)   # the one log region -- scrolls

        # -- row 0: workspace-level import ------------------------------ #
        top = ttk.Frame(self, style=style_name(theme, "window"))
        top.grid(row=0, column=0, sticky="ew", padx=pad, pady=(pad, gap_small))
        top.columnconfigure(1, weight=1)
        self.btn_import_folder = ttk.Button(
            top, text="Import Folder", style=style_name(theme, "button"),
            command=self.import_folder)
        self.btn_import_folder.grid(row=0, column=0, sticky="w")
        self.import_status = job_ui.ImportStatusBar(
            top, theme=theme, on_cancel=self.cancel_import)
        self.import_status.frame.grid(row=0, column=1, sticky="ew", padx=(10, 10))
        self.output_label = ttk.Label(
            top, textvariable=self.var_outdir, anchor="e",
            style=style_name(theme, "secondary_label"))
        self.output_label.grid(row=0, column=2, sticky="e")

        # -- row 1: the shared navigator --------------------------------- #
        self.navigator = BookNavigator(
            self, theme=theme, layout=hints["navigator_layout"],
            describe=self._describe, label_for=self._label_for,
            on_previous=self.on_previous, on_next=self.on_next,
            on_add=self.on_add, on_duplicate=self.on_duplicate,
            on_remove=self.on_remove, on_select=self.on_select)
        self.navigator.frame.grid(row=1, column=0, sticky="ew", padx=pad,
                                  pady=(0, gap_small))

        # -- row 2: Shared above Current Book ----------------------------- #
        text_fields = tuple(
            (key, wf.FIELD_LABELS[key]) for key in wf.SHARED_FIELDS if key != "artwork")
        self.surface = SharedMetadataSurface(
            self, text_fields, theme=theme, layout="rows",
            show_header=False, entry_width=hints["entry_width"],
            wraplength=_label_wraps(hints, (key for key, _label in text_fields)),
            shared_title="Shared — applies to every Book and overrides its own value",
            book_title="Current Book",
            on_shared_change=self.on_shared_change,
            on_book_change=self.on_book_change)
        self.surface.frame.grid(row=2, column=0, sticky="ew", padx=pad, pady=(0, gap))
        field_columns = len(text_fields)
        for group in (self.surface.shared_frame, self.surface.book_frame):
            group.configure(padding=(8, 2))

        natural = hints["artwork_buttons"] == "natural"
        self.shared_artwork = ArtworkControl(
            self.surface.shared_frame, caption=wf.FIELD_LABELS["artwork"],
            theme=theme, shared=True, natural_buttons=natural,
            on_choose=self.choose_shared_artwork, on_clear=self.clear_shared_artwork)
        self.shared_artwork.frame.grid(row=0, column=field_columns, rowspan=2,
                                       sticky="nw", padx=(hints["artwork_gap"], 0))
        self.book_artwork = ArtworkControl(
            self.surface.book_frame, caption=wf.FIELD_LABELS["artwork"],
            theme=theme, shared=False, natural_buttons=natural,
            on_choose=self.choose_book_artwork, on_clear=self.clear_book_artwork)
        self.book_artwork.frame.grid(row=0, column=field_columns, rowspan=4,
                                     sticky="nw", padx=(hints["artwork_gap"], 0))

        # The Book-only text fields, on one row of the Book group: Title,
        # Series Part, Output Filename. Stored raw through the model.
        own = ttk.Frame(self.surface.book_frame, style=style_name(theme, "surface"))
        own.grid(row=2, column=0, columnspan=field_columns, sticky="ew", pady=(4, 0))
        self.book_vars: dict[str, tk.StringVar] = {}
        self.book_entries: dict[str, ttk.Entry] = {}
        self._book_traces: dict[str, str] = {}
        widths = {"title": 20, "series_part": 5, "output_filename": 16}
        for column, key in enumerate(self.BOOK_TEXT_FIELDS):
            ttk.Label(own, text=f"{wf.FIELD_LABELS[key]}:",
                      style=style_name(theme, "label")).grid(
                row=0, column=2 * column, sticky="w", padx=((0 if column == 0 else 12), 4))
            variable = tk.StringVar(master=self, value="")
            entry = ttk.Entry(own, textvariable=variable, width=widths[key],
                              style=style_name(theme, "entry"))
            entry.grid(row=0, column=2 * column + 1, sticky="w")
            self.book_vars[key] = variable
            self.book_entries[key] = entry
            self._book_traces[key] = variable.trace_add(
                "write", lambda *_a, bound=key: self._on_own_field(bound))
        ttk.Label(own, text="Status:", style=style_name(theme, "label")).grid(
            row=0, column=6, sticky="w", padx=(12, 4))
        self.status_label = ttk.Label(own, text=STATUS_READY,
                                      style=style_name(theme, "status_label"))
        self.status_label.grid(row=0, column=7, sticky="w")

        # -- row 3: tracks | chapter titles ------------------------------- #
        middle = ttk.Frame(self, style=style_name(theme, "window"))
        middle.grid(row=3, column=0, sticky="nsew", padx=pad, pady=(0, gap))
        middle.columnconfigure(0, weight=3)
        middle.columnconfigure(1, weight=2)
        middle.rowconfigure(0, weight=1)

        tracks = ttk.Labelframe(middle, text="MP3 Tracks (this Book) — one chapter each",
                                style=style_name(theme, "labelframe"), padding=(6, 2))
        tracks.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        tracks.columnconfigure(0, weight=1)
        tracks.rowconfigure(0, weight=1)
        self.track_list = tk.Listbox(tracks, selectmode="extended",
                                     exportselection=False, height=3, width=24,
                                     activestyle="none")
        track_scroll = ttk.Scrollbar(tracks, orient="vertical",
                                     command=self.track_list.yview,
                                     style=style_name(theme, "vscrollbar"))
        self.track_list.configure(yscrollcommand=track_scroll.set)
        self.track_list.grid(row=0, column=0, sticky="nsew")
        track_scroll.grid(row=0, column=1, sticky="ns")
        ui_theme.style_tk_widget(self.track_list, theme, role="list")
        ui_theme.enable_mousewheel(self.track_list)
        track_buttons = ttk.Frame(tracks, style=style_name(theme, "surface"))
        track_buttons.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self.btn_add_files = ttk.Button(track_buttons, text="Add Files",
                                        style=style_name(theme, "button"),
                                        command=self.add_files)
        self.btn_move_up = ttk.Button(track_buttons, text="Move Up",
                                      style=style_name(theme, "button"),
                                      command=self.move_up)
        self.btn_move_down = ttk.Button(track_buttons, text="Move Down",
                                        style=style_name(theme, "button"),
                                        command=self.move_down)
        self.btn_remove_tracks = ttk.Button(track_buttons, text="Remove Selected",
                                            style=style_name(theme, "button"),
                                            command=self.remove_selected_tracks)
        for column, button in enumerate((self.btn_add_files, self.btn_move_up,
                                         self.btn_move_down, self.btn_remove_tracks)):
            button.grid(row=0, column=column, padx=(0 if column == 0 else 4, 0))

        chapters = ttk.Labelframe(middle, text="Chapter Titles — one title per line",
                                  style=style_name(theme, "labelframe"), padding=(6, 2))
        chapters.grid(row=0, column=1, sticky="nsew")
        chapters.columnconfigure(0, weight=1)
        chapters.rowconfigure(0, weight=1)
        self.chapter_text = tk.Text(chapters, height=3, width=24, wrap="none", undo=True)
        chapter_scroll = ttk.Scrollbar(chapters, orient="vertical",
                                       command=self.chapter_text.yview,
                                       style=style_name(theme, "vscrollbar"))
        self.chapter_text.configure(yscrollcommand=chapter_scroll.set)
        self.chapter_text.grid(row=0, column=0, sticky="nsew")
        chapter_scroll.grid(row=0, column=1, sticky="ns")
        ui_theme.style_tk_widget(self.chapter_text, theme, role="text")
        ui_theme.enable_mousewheel(self.chapter_text)
        self.chapter_text.bind("<KeyRelease>", self.on_chapter_edit)
        self._suspend_chapters = False
        self._chapter_baseline = ""

        # -- row 4: run options ----------------------------------------- #
        options = ttk.Frame(self, style=style_name(theme, "window"))
        options.grid(row=4, column=0, sticky="ew", padx=pad, pady=(0, gap_small))
        options.columnconfigure(5, weight=1)
        self.var_auto_number = tk.BooleanVar(master=self, value=False)
        self.check_auto_number = ttk.Checkbutton(
            options, text="Auto-number Series Part", variable=self.var_auto_number,
            style=style_name(theme, "checkbutton"), command=self.on_auto_number)
        self.check_auto_number.grid(row=0, column=0, sticky="w")
        ttk.Label(options, text="Start Part (blank → 1):",
                  style=style_name(theme, "label")).grid(
            row=0, column=1, sticky="w", padx=(12, 4))
        self.var_start_part = tk.StringVar(master=self, value="")
        self.entry_start_part = ttk.Entry(
            options, textvariable=self.var_start_part, width=6,
            style=style_name(theme, "entry"))
        self.entry_start_part.grid(row=0, column=2, sticky="w")
        self.var_fast_first = tk.BooleanVar(master=self, value=True)
        self.check_fast_first = ttk.Checkbutton(
            options, text="Try FAST first (auto-fallback to Safe)",
            variable=self.var_fast_first, style=style_name(theme, "checkbutton"))
        self.check_fast_first.grid(row=0, column=3, sticky="w", padx=(16, 0))
        # The explicit custom destination (Decision 10A): off on every fresh
        # build, its path row hidden until the toggle is on, never persisted.
        self.var_custom_dest = tk.BooleanVar(master=self, value=False)
        self.chk_custom_dest = ttk.Checkbutton(
            options, text=CUSTOM_DEST_LABEL, variable=self.var_custom_dest,
            style=style_name(theme, "checkbutton"), command=self._on_custom_dest_change)
        self.chk_custom_dest.grid(row=0, column=4, sticky="w", padx=(16, 0))
        self.customrow = ttk.Frame(options, style=style_name(theme, "window"))
        self.customrow.columnconfigure(0, weight=1)
        self.var_custom_path = tk.StringVar(master=self, value="")
        self.entry_custom = ttk.Entry(self.customrow, textvariable=self.var_custom_path,
                                      style=style_name(theme, "entry"))
        self.entry_custom.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.btn_browse_custom = ttk.Button(
            self.customrow, text="Browse…", style=style_name(theme, "button"),
            command=self.choose_custom_dest)
        self.btn_browse_custom.grid(row=0, column=1, sticky="e")
        self._on_custom_dest_change()

        # -- row 5: Build, the shared job area, Clear Log ------------------ #
        self.actions = ttk.Frame(self, style=style_name(theme, "window"))
        self.actions.grid(row=5, column=0, sticky="ew", padx=pad, pady=(0, gap))
        self.actions.columnconfigure(2, weight=1)
        self.btn_build = ttk.Button(
            self.actions, text="Build M4B(s)",
            style=style_name(theme, "primary_button"), command=self.build)
        self.btn_clear_log = ttk.Button(
            self.actions, text="Clear Log", style=style_name(theme, "button"),
            command=self.clear_log)
        if hints["actions_layout"] == "row":
            self.btn_build.grid(row=0, column=0, sticky="nw")
            self.btn_clear_log.grid(row=1, column=0, sticky="sw", pady=(4, 0))
            self._jobs_rowspan = 2
        else:
            self.btn_build.grid(row=0, column=0, sticky="new", padx=(0, 16))
            self.btn_clear_log.grid(row=1, column=0, sticky="sew", padx=(0, 16), pady=(4, 0))
            self._jobs_rowspan = 2

        # -- row 6: the one log region ----------------------------------- #
        self.log = job_ui.SummaryDetailsView(self, theme=theme, height=2,
                                             details_label="Detailed", limit=LOG_LIMIT)
        self.log.frame.grid(row=6, column=0, sticky="nsew", padx=pad, pady=(0, pad))

    def _install_jobs(self, run_id: str, item_ids) -> None:
        """Point the shared job area at one run. Main thread only.

        A run owns its event stream, so a new attempt gets a new adapter in the
        same place; the retired one is closed first so the one pump keeps
        exactly one job drain. The log view is the panel's one region, handed
        in, and keeps every earlier attempt's lines.
        """
        previous = getattr(self, "jobs", None)
        if previous is not None:
            previous.close()
            previous.frame.destroy()
        theme = self.theme
        self._event_q = queue.Queue()
        self._estimator = job_control.EtaEstimator(run_id, clock=self._clock)
        self.jobs = job_ui.JobAdapter(
            self.actions,
            run_id=run_id,
            pump=self._pump,
            theme=theme,
            pull=job_ui.queue_pull(self._event_q),
            estimator=self._estimator,
            bridge=self._bridge,
            item_ids=item_ids,
            views=self.log,
            context=self._context,
            on_pause=self.pause,
            on_resume=self.resume,
            on_cancel=self.cancel,
            on_retry=self.retry_failed,
            on_event=self._on_job_event,
            on_terminal=self._on_terminal,
        )
        self.jobs.frame.grid(row=0, column=2, rowspan=self._jobs_rowspan, sticky="ew")
        self.jobs.controls.frame.grid_configure(sticky="e")
        self.controls = self.jobs.controls
        self.status = self.jobs.status
        self.lock_group = self.jobs.locks
        self.status.indicator.frame.configure(style=style_name(theme, "card"))
        self.status.indicator.bar.configure(style=style_name(theme, "progressbar"))
        self.status.indicator.label.configure(style=style_name(theme, "status_label"))
        self.jobs.register_inputs(self.navigator, self._tracks_lock, self._import_lock)
        self.jobs.register_options(self.surface, self.shared_artwork, self.book_artwork,
                                   self._options_lock, self._series_part_lock,
                                   self._chapters_lock)
        self.jobs.render()

    class _ButtonLock:
        """Registers a set of this panel's own widgets with the shared group."""

        def __init__(self, *widgets) -> None:
            self.widgets = widgets

        def set_locked(self, locked: bool) -> None:
            for widget in self.widgets:
                try:
                    widget.configure(state="disabled" if locked else "normal")
                except tk.TclError:
                    pass

    class _SeriesPartSeam:
        """The run-lock reason for the manual Series Part entry."""

        def __init__(self, panel) -> None:
            self.panel = panel
            self.locked = False

        def set_locked(self, locked: bool) -> None:
            self.locked = bool(locked)
            self.panel._render_series_part_state()

    class _TextLock:
        def __init__(self, text: tk.Text) -> None:
            self.text = text

        def set_locked(self, locked: bool) -> None:
            try:
                self.text.configure(state="disabled" if locked else "normal")
            except tk.TclError:
                pass

    # ------------------------------------------------------------------ #
    # Dialog and confirmation seams (main thread, before any worker)
    # ------------------------------------------------------------------ #

    def _ask_files(self):
        chosen = tuple(filedialog.askopenfilenames(
            parent=self, title="Select MP3 files",
            initialdir=str(_remembered_dir(KEY_INPUT_DIR)),
            filetypes=[("MP3 audio", "*.mp3"), ("All files", "*.*")]))
        if chosen:
            settings.set(KEY_INPUT_DIR, str(Path(chosen[0]).parent))
        return chosen

    def _ask_folder(self):
        chosen = filedialog.askdirectory(
            parent=self, title="Select a folder of MP3 audiobooks",
            initialdir=str(_remembered_dir(KEY_INPUT_DIR)), mustexist=True)
        if not chosen:
            return ()
        settings.set(KEY_INPUT_DIR, str(chosen))
        return (str(chosen),)

    def _ask_artwork(self) -> str:
        chosen = m4b_artwork_ui.ask_artwork(
            self, initialdir=_remembered_dir(KEY_COVER_DIR), title="Select Book Artwork")
        if chosen:
            settings.set(KEY_COVER_DIR, str(Path(chosen).parent))
        return chosen

    def _ask_destination(self) -> str:
        chosen = filedialog.askdirectory(parent=self, title="Choose the destination folder",
                                         mustexist=True)
        return str(chosen or "")

    def _ask_confirm(self, title: str, message: str) -> bool:
        return job_ui.ask_confirm(self, title, message)

    def _confirm_broad_root(self, roots) -> bool:
        listed = "\n".join(str(entry) for entry in roots)
        return self._confirm(
            "Scan a very broad folder?",
            "This covers a whole drive or your home folder:\n\n"
            f"{listed}\n\nScanning it can take a long time. Continue?")

    def _confirm_large_result(self, outcome) -> bool:
        return self._confirm(
            "Import a large number of MP3s?",
            f"{outcome.proposed_count:,} MP3 files are ready to be imported.\n\n"
            "Importing this many at once can make the workspace slow. Import them?")

    # ------------------------------------------------------------------ #
    # Rendering
    # ------------------------------------------------------------------ #

    def _describe(self, book) -> str:
        return wf.display_hint(self.workspace.shared, book)

    def _label_for(self, book, _position: int) -> str:
        number = self.book_numbers.get(book.book_id, "?")
        hint = self._describe(book)
        if len(hint) > HINT_LIMIT:
            hint = hint[:HINT_LIMIT - 1].rstrip() + "…"
        return f"Book {number} — {hint}" if hint else f"Book {number}"

    def _assign_book_numbers(self) -> None:
        ids = [book.book_id for book in self.workspace.books]
        if not any(book_id in self.book_numbers for book_id in ids):
            self.book_numbers = {}
        highest = max(self.book_numbers.values(), default=0)
        for book_id in ids:
            if book_id not in self.book_numbers:
                highest += 1
                self.book_numbers[book_id] = highest
        self.book_numbers = {book_id: number for book_id, number in self.book_numbers.items()
                             if book_id in ids}

    def render(self) -> None:
        """Show the current workspace. Every value comes from the snapshot."""
        self._guard.require("render")
        if self._closed:
            return
        self._rendering = True
        try:
            space = self.workspace
            book = space.current
            self._assign_book_numbers()
            self.navigator.render(space)
            self.surface.render(space)
            overridden = disabled_fields(space.shared)
            self.shared_artwork.set_path(str(space.shared.values.get("artwork", "")))
            self.book_artwork.set_path(str(book.configuration.get("artwork", "")))
            self.book_artwork.set_enabled("artwork" not in overridden)
            for key, variable in self.book_vars.items():
                stored = str(book.configuration.get(key, ""))
                if variable.get() != stored:
                    variable.set(stored)
            self._render_series_part_state()
            self._render_tracks()
            self._render_chapters()
            self._render_status()
        finally:
            self._rendering = False

    def _render_series_part_state(self) -> None:
        """Auto-number on, or a run in progress → the manual Series Part is disabled."""
        seam = getattr(self, "_series_part_lock", None)
        run_locked = seam is not None and seam.locked
        usable = not self.var_auto_number.get() and not run_locked
        try:
            self.book_entries["series_part"].configure(state="normal" if usable else "disabled")
        except tk.TclError:
            pass

    def _render_status(self) -> None:
        if self._closed:
            return
        try:
            self.status_label.configure(
                text=self.book_status_for(self.workspace.current.book_id))
        except tk.TclError:
            pass

    def _render_light(self) -> None:
        """After a per-Book text edit: what the edit can change, and no more."""
        if self._closed:
            return
        self._assign_book_numbers()
        self.navigator.render(self.workspace)

    def _render_tracks(self, selection=()) -> None:
        book = self.workspace.current
        self.track_list.delete(0, "end")
        for entry in book.files.files:
            self.track_list.insert("end", entry.name)
        wanted = set(selection)
        for row, entry in enumerate(book.files.files):
            if entry.occurrence_id in wanted:
                self.track_list.selection_set(row)
                self.track_list.see(row)

    def _chapter_display(self) -> str:
        """Stored Chapter Titles text; until the user edits it, the Phase 2 defaults."""
        book = self.workspace.current
        if "chapter_titles" in book.configuration:
            return wf.chapter_titles_text(book)
        return "\n".join(wf.default_titles(book))

    def _render_chapters(self) -> None:
        raw = self._chapter_display()
        self._chapter_baseline = raw
        if raw == self.chapter_text.get("1.0", "end-1c"):
            return
        self._suspend_chapters = True
        try:
            state = str(self.chapter_text.cget("state"))
            self.chapter_text.configure(state="normal")
            self.chapter_text.delete("1.0", "end")
            if raw:
                self.chapter_text.insert("1.0", raw)
            self.chapter_text.configure(state=state)
        finally:
            self._suspend_chapters = False

    # -- read-back seams --------------------------------------------------- #

    def shared_field_keys(self) -> tuple:
        return self.surface.fields + ("artwork",)

    def book_field_keys(self) -> tuple:
        return self.surface.fields + ("artwork",) + self.BOOK_TEXT_FIELDS + ("chapter_titles",)

    def book_field_enabled(self, name: str) -> bool:
        """Whether the current Book's control for *name* is usable right now."""
        if name in self.book_entries:
            return "disabled" not in self.book_entries[name].state()
        if name == "artwork":
            return self.book_artwork.enabled
        return self.surface.book_field_enabled(name)

    def book_status_text(self) -> str:
        return str(self.status_label.cget("text"))

    def book_title_text(self) -> str:
        return self.book_vars["title"].get()

    def chapter_titles_text(self) -> str:
        return self.chapter_text.get("1.0", "end-1c")

    # ------------------------------------------------------------------ #
    # Applying model results
    # ------------------------------------------------------------------ #

    def _apply(self, mutation) -> bool:
        if mutation.changed:
            self.workspace = mutation.workspace
        self.render()
        return mutation.changed

    def _say(self, line: str, detail: str = "") -> None:
        if not self._closed:
            self.log.append(line, detail or line)

    def clear_log(self) -> None:
        self._guard.require("clear_log")
        if not self._closed:
            self.log.clear()

    # ------------------------------------------------------------------ #
    # Navigator callbacks
    # ------------------------------------------------------------------ #

    def on_previous(self) -> None:
        self._apply(previous_book(self.workspace))

    def on_next(self) -> None:
        self._apply(next_book(self.workspace))

    def on_select(self, book_id: str) -> None:
        self._apply(select_book(self.workspace, book_id))

    def on_add(self) -> None:
        self._apply(add_book(self.workspace, id_factory=self._ids))

    def on_duplicate(self) -> None:
        self._apply(duplicate_book(self.workspace, id_factory=self._ids))

    def on_remove(self, meaningful: bool) -> None:
        """Decision 50A: the model answered; this panel decides to ask."""
        if meaningful and not self._confirm(
                "Remove this Book?",
                "This Book has imported MP3s or edited settings.\n\nRemove it anyway?"):
            return
        self._apply(remove_book(self.workspace, id_factory=self._ids))

    # ------------------------------------------------------------------ #
    # Shared and Book field callbacks
    # ------------------------------------------------------------------ #

    def on_shared_change(self, field: str, raw: str) -> None:
        if self._rendering:
            return
        values = dict(self.workspace.shared.values)
        values[field] = raw
        self._apply(set_shared_metadata(
            self.workspace, SharedMetadata(wf.SHARED_FIELDS, values)))

    def on_book_change(self, field: str, raw: str) -> None:
        if self._rendering:
            return
        mutation = wf.set_book_field(self.workspace, field, raw)
        if mutation.changed:
            self.workspace = mutation.workspace
        self._render_light()

    def _on_own_field(self, key: str) -> None:
        if self._rendering or self._closed:
            return
        raw = self.book_vars[key].get()
        if raw == str(self.workspace.current.configuration.get(key, "")):
            return
        mutation = wf.set_book_field(self.workspace, key, raw)
        if mutation.changed:
            self.workspace = mutation.workspace
        self._render_light()

    def set_book_field(self, name: str, value) -> None:
        """Store one raw Book value and show it. The model owns the write."""
        self._guard.require("set_book_field")
        self._apply(wf.set_book_field(self.workspace, name, value))

    def on_auto_number(self) -> None:
        if self._rendering or self._closed:
            return
        self._render_series_part_state()

    def on_chapter_edit(self, _event=None) -> None:
        if self._suspend_chapters or self._rendering or self._closed:
            return
        raw = self.chapter_text.get("1.0", "end-1c")
        if raw == self._chapter_baseline:
            return
        self._chapter_baseline = raw
        mutation = wf.set_book_field(self.workspace, "chapter_titles", raw)
        if mutation.changed:
            self.workspace = mutation.workspace
        self._render_light()

    def type_chapter_titles(self, raw: str) -> None:
        """Type into the Chapter Titles box as a person would, then report it."""
        self.chapter_text.delete("1.0", "end")
        if raw:
            self.chapter_text.insert("1.0", raw)
        self.on_chapter_edit()

    # -- artwork ----------------------------------------------------------- #

    def _artwork_error(self, message: str) -> None:
        messagebox.showerror(APP_TITLE, f"Book Artwork: {message}", parent=self)

    def choose_shared_artwork(self) -> None:
        self._guard.require("choose_shared_artwork")
        chosen = m4b_artwork_ui.validated_artwork(str(self._choose_artwork() or ""),
                                                  self._artwork_error)
        if chosen:
            self.on_shared_change("artwork", chosen)

    def clear_shared_artwork(self) -> None:
        self._guard.require("clear_shared_artwork")
        self.on_shared_change("artwork", "")

    def choose_book_artwork(self) -> None:
        self._guard.require("choose_book_artwork")
        if not self.book_artwork.enabled:
            return
        chosen = m4b_artwork_ui.validated_artwork(str(self._choose_artwork() or ""),
                                                  self._artwork_error)
        if chosen:
            self.set_book_field("artwork", chosen)

    def clear_book_artwork(self) -> None:
        self._guard.require("clear_book_artwork")
        if not self.book_artwork.enabled:
            return
        self.set_book_field("artwork", "")

    # -- custom destination ---------------------------------------------- #

    def _on_custom_dest_change(self):
        """Show the path controls only while the custom mode is on."""
        if self.var_custom_dest.get():
            self.customrow.grid(row=1, column=0, columnspan=6, sticky="ew", pady=(4, 0))
        else:
            self.customrow.grid_forget()

    def choose_custom_dest(self):
        chosen = str(self._choose_destination() or "")
        if chosen:
            self.var_custom_path.set(chosen)

    def custom_destination(self):
        """The chosen folder while the toggle is on, else ``None``. Not persisted."""
        if not self.var_custom_dest.get():
            return None
        return self.var_custom_path.get().strip()

    # ------------------------------------------------------------------ #
    # Tracks
    # ------------------------------------------------------------------ #

    def selected_occurrences(self) -> tuple:
        files = self.workspace.current.files.files
        return tuple(files[int(row)].occurrence_id
                     for row in self.track_list.curselection()
                     if int(row) < len(files))

    def select_tracks(self, *rows: int) -> None:
        self.track_list.selection_clear(0, "end")
        for row in rows:
            self.track_list.selection_set(row)

    def _move(self, direction: int) -> None:
        selected = self.selected_occurrences()
        if not selected:
            return
        mutation = wf.move_tracks(self.workspace, selected, direction)
        if mutation.changed:
            self.workspace = mutation.workspace
        self._render_tracks(selected)
        self._render_chapters()
        self._render_light()

    def move_up(self) -> None:
        self._guard.require("move_up")
        self._move(wf.UP)

    def move_down(self) -> None:
        self._guard.require("move_down")
        self._move(wf.DOWN)

    def remove_selected_tracks(self) -> None:
        self._guard.require("remove_selected_tracks")
        selected = self.selected_occurrences()
        if not selected:
            return
        self._apply(wf.remove_tracks(self.workspace, selected))

    # ------------------------------------------------------------------ #
    # Importing
    # ------------------------------------------------------------------ #

    def _request(self, roots: tuple) -> ScanRequest:
        return ScanRequest(
            request_id=self._ids.next_id("req"),
            roots=roots,
            catalog=wf.MAKER_CATALOG,
            options=ImportOptions.for_catalog(wf.MAKER_CATALOG),
            effective_config=self._effective_config,
            created_at=self._clock(),
        )

    def import_folder(self) -> None:
        """Workspace-level: scan one parent folder, then replace the Books."""
        self._guard.require("import_folder")
        if self._closed or self._coordinator.is_active:
            return
        if any(has_meaningful_work(book) for book in self.workspace.books):
            if not self._confirm(
                    "Replace the current Books?",
                    "Import Folder replaces every Book in the workspace with the "
                    "folders it finds.\n\nReplace them?"):
                return
        chosen = tuple(self._choose_folder() or ())
        if not chosen:
            return
        roots = tuple(
            ImportRoot(root_id=self._ids.next_id("root"), path=Path(entry),
                       order=order, kind=RootKind.FOLDER)
            for order, entry in enumerate(chosen))
        self._manager.clear()
        self._import_kind = "folder"
        report = self._coordinator.start(self._request(roots))
        if report.outcome is StartOutcome.STARTED:
            self.import_status.set_scanning(0)
            self._poller.start()
            return
        self._import_kind = None
        self.import_status.set_idle(report.display_message)
        self._say(f"Import Folder: {report.display_message}")

    def add_files(self) -> None:
        """Into the current Book; the model natural-orders the addition."""
        self._guard.require("add_files")
        if self._closed or self._coordinator.is_active:
            return
        paths_chosen = tuple(self._choose_files() or ())
        if not paths_chosen:
            return
        root = ImportRoot(root_id=self._ids.next_id("root"), path=None, order=0,
                          kind=RootKind.DIRECT_FILES)
        self._manager.clear()
        self._import_kind = "files"
        outcome = self._coordinator.import_files(self._request((root,)), paths_chosen)
        self._handle_outcome(outcome)

    def cancel_import(self) -> bool:
        self._guard.require("cancel_import")
        if self._closed:
            return False
        cancelled = self._coordinator.request_cancel()
        if cancelled:
            self.import_status.set_cancelling()
        return cancelled

    def _handle_outcome(self, outcome: ImportOutcome) -> ImportOutcome:
        if self._closed:
            return outcome
        status = outcome.status
        if status is OutcomeStatus.RUNNING:
            self.import_status.set_scanning(outcome.discovered_count)
            return outcome
        if status is OutcomeStatus.AWAITING_CONFIRMATION:
            self.import_status.set_message(
                f"{outcome.proposed_count:,} files found — waiting for confirmation…")
            if self._confirm_large(outcome):
                return self._handle_outcome(self._coordinator.confirm_pending())
            return self._handle_outcome(self._coordinator.decline_pending())
        if status in TERMINAL_STATUSES or status is OutcomeStatus.CLOSED:
            self._poller.stop()
            kind, self._import_kind = self._import_kind, None
            self.import_status.set_idle(outcome.display_message)
            if status is OutcomeStatus.COMMITTED and outcome.commit is not None:
                self._project_import(kind, outcome)
            else:
                label = "Import Folder" if kind == "folder" else "Add Files"
                self._say(f"{label}: {outcome.display_message}",
                          outcome.technical_detail or outcome.display_message)
            for problem in outcome.problems:
                self._say(f"  {problem.display_message}",
                          f"  {problem.technical_detail or problem.display_message}")
            return outcome
        if status in (OutcomeStatus.BUSY, OutcomeStatus.NO_TYPES_SELECTED):
            self.import_status.set_message(outcome.display_message)
        return outcome

    def _project_import(self, kind: str | None, outcome: ImportOutcome) -> None:
        """The committed snapshot becomes Books (folder) or tracks (files)."""
        commit = outcome.commit
        if kind == "folder":
            self._apply(wf.import_folder(self.workspace, commit.snapshot,
                                         id_factory=self._ids))
            books = [book for book in self.workspace.books if not book.files.is_empty]
            total = sum(book.file_count for book in books)
            self._say(f"Import Folder: {total} MP3 file(s) in {len(books)} Book(s).")
            return
        held = set(self.workspace.current.files.identities)
        additions = tuple(entry for entry in commit.added if entry.identity not in held)
        skipped = len(commit.added) - len(additions)
        self._apply(wf.add_files(self.workspace, additions))
        note = f" {skipped} already in this Book were skipped." if skipped else ""
        self._say(f"Add Files: {len(additions)} MP3 file(s) added to "
                  f"{self.navigator.position_text}.{note}")

    # ------------------------------------------------------------------ #
    # Build: validate, reserve or validate the destination, freeze, run
    # ------------------------------------------------------------------ #

    def _run_options(self) -> mp.MakerRunOptions:
        return mp.MakerRunOptions(auto_number=bool(self.var_auto_number.get()),
                                  start_part_text=self.var_start_part.get(),
                                  fast_first=bool(self.var_fast_first.get()))

    def _destination(self) -> mp.MakerDestination | None:
        """One reserved standard run, or the validated custom folder. None = stop."""
        custom = self.custom_destination()
        if custom is not None:
            try:
                folder = output_paths.validate_custom_destination(custom)
            except output_paths.OutputPathError as exc:
                messagebox.showerror(APP_TITLE, exc.message, parent=self)
                return None
            # Custom mode writes straight into the chosen folder: no standard
            # run is reserved, and staging lives in an operation-owned root
            # elsewhere, never among the user's files.
            work_root = Path(tempfile.mkdtemp(prefix=WORK_ROOT_PREFIX))
            try:
                return mp.custom_destination(folder, work_root=work_root)
            except mp.PlanError as exc:
                self._drop_empty(work_root)
                messagebox.showerror(APP_TITLE, str(exc), parent=self)
                return None
        try:
            reservation = output_paths.reserve_run_directory(TOOL_KEY)
        except output_paths.OutputPathError as exc:
            messagebox.showerror(APP_TITLE, exc.message, parent=self)
            return None
        return mp.standard_destination(reservation)

    @staticmethod
    def _drop_empty(directory: Path) -> None:
        try:
            directory.rmdir()
        except OSError:
            pass

    def build(self) -> bool:
        """Validate, reserve one destination, freeze one plan, start one run."""
        self._guard.require("build")
        if self._closed or self.is_running:
            return False
        space = self.workspace
        if all(book.files.is_empty for book in space.books):
            messagebox.showwarning(APP_TITLE, "Import a folder or add MP3 files first.",
                                   parent=self)
            return False
        options = self._run_options()
        for position, book in enumerate(space.books, start=1):
            if book.files.is_empty:
                continue
            try:
                wf.effective_silence(space.shared, book)
            except wf.MakerValueError as exc:
                messagebox.showerror(APP_TITLE, f"Silence for Book {position}: {exc}",
                                     parent=self)
                return False
        if options.auto_number:
            try:
                wf.parse_start_part(options.start_part_text)
            except wf.MakerValueError as exc:
                messagebox.showerror(APP_TITLE, f"Start Part: {exc}", parent=self)
                return False
        destination = self._destination()
        if destination is None:
            return False
        try:
            plan = mp.plan_run(
                space, options=options, destination=destination,
                catalog=wf.MAKER_CATALOG,
                import_options=ImportOptions.for_catalog(wf.MAKER_CATALOG),
                effective_config=self._effective_config, id_factory=self._ids,
                created_at=self._clock())
        except (wf.MakerValueError, mp.PlanError, output_paths.OutputPathError) as exc:
            if destination.reservation is not None:
                output_paths.release_if_empty(destination.reservation)
            else:
                self._drop_empty(destination.work_root)
            messagebox.showerror(APP_TITLE, f"Build: {exc}", parent=self)
            return False
        self.last_plan = plan
        self.run = self._run_factory(plan, id_factory=self._ids, clock=self._clock,
                                     publish=self._publish)
        self.var_outdir.set(str(plan.root))
        self._start_attempt(self.run.start, "Build M4B(s)")
        return True

    def _start_attempt(self, begin, label: str) -> None:
        """Begin one attempt through the run and start its one worker thread."""
        # The queue exists before the run publishes its first event; the
        # adapter installed just after drains everything the attempt sends.
        self._event_q = queue.Queue()
        attempt = begin()
        self._attempt = attempt
        item_ids = tuple(occ for book in self.last_plan.books for occ in book.occurrence_ids)
        pending = self._event_q
        self._install_jobs(attempt.run_id, item_ids)
        # Events the run published before the adapter existed.
        while True:
            try:
                self._event_q.put(pending.get_nowait())
            except queue.Empty:
                break
        self.lock_group.apply(attempt.controller.state)
        heading = (f"Retry Failed — attempt {attempt.number}" if attempt.is_retry
                   else f"{label} — {self.last_plan.root.name}")
        self.log.divider(f"{DIVIDER_MARK} {heading}")
        self._render_status()
        thread = self._thread_factory(attempt.run, f"m4b-{attempt.run_id}")
        self._worker_thread = thread
        thread.start()

    def _publish(self, event) -> None:
        """Hand one produced event to the queue the shared adapter drains.

        Called from whichever thread produced it. A queue is the only thing
        that crosses that boundary; no widget is ever touched from the worker.
        """
        self._event_q.put(event)

    @staticmethod
    def _default_thread(target, name: str):
        import threading

        return threading.Thread(target=target, name=name, daemon=True)

    def _context(self, stage: str | None, item_id: str | None) -> str:
        """The status line under the bar: ``Alpha.m4b (2 of 3)``."""
        attempt, plan = self._attempt, self.last_plan
        if not stage or not stage.startswith("book-") or attempt is None or plan is None:
            return stage or ""
        try:
            number = int(stage[len("book-"):])
        except ValueError:
            return stage
        for index, book in enumerate(attempt.books, start=1):
            if book.number == number:
                return f"{book.filename} ({index} of {len(attempt.books)})"
        return f"Book {number}"

    # -- main-thread projections of the run --------------------------------- #

    def _on_job_event(self, _event) -> None:
        self._render_status()

    def _on_terminal(self, event) -> None:
        """The attempt ended: the frozen result is the run's. Main thread only."""
        attempt = self._attempt
        if attempt is None or event.run_id != attempt.run_id:
            return
        result = self.run.result if self.run is not None else None
        self.jobs.set_result(result)
        if result is not None:
            skipped = result.skipped_empty_count + result.skipped_invalid_count
            self._say(f"Build: {result.succeeded_count} Book(s) completed, "
                      f"{result.failed_count} failed, {skipped} skipped, "
                      f"{result.not_attempted_count} not attempted → {self.last_plan.root}")
        self.render()

    @property
    def is_running(self) -> bool:
        attempt = self._attempt
        return attempt is not None and attempt.controller.state not in TERMINAL_STATES

    @property
    def job_controller(self):
        attempt = self._attempt
        return None if attempt is None else attempt.controller

    @property
    def last_result(self) -> WorkspaceRunResult | None:
        return None if self.run is None else self.run.result

    def book_status_for(self, book_id: str) -> str:
        """One Book's compact status, read from the run -- never kept here."""
        attempt = self._attempt
        plan = self.last_plan
        if attempt is None or plan is None:
            return STATUS_READY
        if book_id in plan.capture.skipped_book_ids:
            return STATUS_SKIPPED
        if self.is_running:
            for record in attempt.records:
                if record.book_id == book_id:
                    return STATUS_COMPLETED if record.succeeded else STATUS_FAILED
            prior = self.run.result if self.run is not None else None
            if attempt.is_retry and prior is not None and book_id not in attempt.retry:
                return self._status_of_disposition(prior.disposition_for(book_id))
            if any(book.book_id == book_id for book in attempt.books):
                stage = self._current_stage()
                book = plan.book_for(book_id)
                if book is not None and stage == f"book-{book.number}":
                    return STATUS_PROCESSING
                return STATUS_QUEUED
            return STATUS_READY
        result = self.last_result
        if result is None:
            return STATUS_READY
        return self._status_of_disposition(result.disposition_for(book_id))

    def _current_stage(self) -> str | None:
        for entry in reversed(self.jobs.stream.events):
            if entry.kind is JobEventKind.STAGE_CHANGED:
                return entry.stage
        return None

    @staticmethod
    def _status_of_disposition(disposition) -> str:
        if disposition is BookDisposition.SUCCEEDED:
            return STATUS_COMPLETED
        if disposition is BookDisposition.FAILED:
            return STATUS_FAILED
        if disposition in (BookDisposition.SKIPPED_EMPTY, BookDisposition.SKIPPED_INVALID):
            return STATUS_SKIPPED
        if disposition is BookDisposition.NOT_ATTEMPTED:
            return STATUS_NOT_ATTEMPTED
        return STATUS_READY

    # -- the shared control bar's callbacks ---------------------------------- #

    def pause(self) -> None:
        if self.run is not None and self.is_running:
            self.run.pause()

    def resume(self) -> None:
        if self.run is not None and self.is_running:
            self.run.resume()

    def cancel(self) -> None:
        if self.run is not None and self.is_running:
            self.run.cancel()

    def retry_failed(self) -> bool:
        """Re-run the frozen run's failed Books. A new attempt, not a new run."""
        self._guard.require("retry_failed")
        if self._closed or self.is_running or self.run is None:
            return False
        result = self.run.result
        if result is None or not result.can_retry_failed:
            return False
        self._start_attempt(self.run.retry_failed, "Retry Failed")
        return True

    # ------------------------------------------------------------------ #
    # Teardown
    # ------------------------------------------------------------------ #

    def close(self) -> None:
        """Cancel any scan or run, stop the pump, close every component. Idempotent."""
        if self._closed:
            return
        self._closed = True
        if self.run is not None:
            try:
                self.run.cancel()
            except Exception:
                pass
        for component in (self._poller, self.navigator, self.surface,
                          self.shared_artwork, self.book_artwork, self.jobs,
                          self.log, self.import_status):
            try:
                component.close()
            except Exception:
                pass
        try:
            self._coordinator.close()
        except Exception:
            pass
        try:
            self._pump.close()
        except Exception:
            pass
        for key, trace in self._book_traces.items():
            try:
                self.book_vars[key].trace_remove("write", trace)
            except (tk.TclError, ValueError):
                pass


def build_ui(parent: tk.Misc, theme=None) -> M4BMakerUI:
    """Build the M4B Maker UI into ``parent`` and return the frame."""
    ui = M4BMakerUI(parent, theme=theme)
    ui.pack(fill=tk.BOTH, expand=True)
    return ui


def main():
    root = tk.Tk()
    root.title(APP_TITLE)
    root.geometry(ui_theme.DEFAULT_GEOMETRY)
    root.minsize(*ui_theme.MIN_SIZE)
    build_ui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
