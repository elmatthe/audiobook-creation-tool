#!/usr/bin/env python3
"""M4B Metadata Editor — edit the tags of existing M4B-family files, one Book per file.

v0.6.4 Phase 10: the production panel is a **thin Tk composition/orchestration
adapter** over the completed Editor layers. No business rule lives in a widget:

- **Workspace.** The shared Plan 6 multi-Book workspace with the Editor's own
  projection: **one imported occurrence = one Book/page**, whatever directory
  it came from (``m4b_metadata_workflow.import_folder`` replaces the workspace
  through the shared ``ImportCoordinator`` scan; ``add_files`` appends one Book
  per new source). Previous / Next / ``Book X of Y`` / the direct selector /
  Remove Book are the shared ``BookNavigator`` with the Editor's action subset
  — no ``Add Book``, no ``Duplicate Book``: the import controls are how pages
  arrive. The panel owns no list of paths — the Books are the list.
- **Source versus edit.** Every page shows its source's metadata as prefill,
  read once into a frozen ``SourceObservation`` and displayed through the
  model's ``page_values``. Rendering a page **never** writes into the Book's
  configuration: only a keystroke reaches ``set_book_field``, and the model's
  ``edit_intent`` decides what a later action writes (blank or unchanged =
  preserve the source; a populated Shared value overrides every Book). The
  Series read-back line, the source Series Part, the artwork presence and the
  chapter count are read-back facts beside the entries, never edits.
- **Shared and Book fields.** The Shared area is exactly the Editor's eight —
  the seven text fields on the shared ``SharedMetadataSurface`` (``rows``
  layout) plus the common M4B ``ArtworkControl``, once for Shared and once for
  the Book. A populated Shared value disables the matching Book control;
  ``disabled_fields`` decides, never this panel. Series Part is not a text
  field: it is read-back plus the batch-level Auto-number contract.
- **Chapters.** One local Chapter Titles box per Book, positional: line *N*
  targets chapter *N*, a blank line preserves that chapter, an unchanged line
  preserves it, blank lines are never collapsed. The box shows the source
  titles until the user edits them; showing them is not an edit.
- **Actions.** ``Save Tags`` / ``Clear All Tags (keep chapters)`` / ``Remove
  Series Numbering`` each reserve **one** standard run, freeze one immutable
  ``RunPlan`` through ``m4b_metadata_plan`` and hand it to **one**
  ``EditorRun`` (Phase 9). The worker body is ``Attempt.run`` on one thread; its
  events cross to the panel through a queue the shared ``JobAdapter`` drains on
  the one ``MainThreadPump``. Pause / Resume / Cancel / Retry Failed are the
  shared control bar's, forwarded to the run; locking is the shared
  ``LockGroup`` applying the job-state matrix. Book status is read from the
  attempt's settled records and, afterwards, the frozen ``WorkspaceRunResult``
  — never from a second state model. Retry Failed re-runs the frozen run's
  failed Books only; nothing typed since can reach it.
- **Log.** One region, ``Summary`` | ``Detailed``, whose history survives from
  run to run with a divider per attempt; Clear Log clears the visible text only.

Removed with the batch-global form: the raw file list and its cache, the
private worker, busy flag, cancel event and log queue, the chapter pager, the
"(varies)" detection and the position-based auto-number (now the shared
success-only ``SuccessNumbers``), and the whole-form ``Canvas`` scroller.

Presentation: every widget asks ``job_ui.style_name`` for the approved ``ACT.*``
style on Windows; on macOS and the classic branch the lookup returns ``""`` and
the panel is drawn natively. No colour, font or metric is declared here. Nothing
scrolls the whole tool: the Chapter Titles box and the log scroll locally and
give up height first. Where the theme's metrics carry the panel hints (the aqua
bundle) the navigator's actions fold under its navigation row, the actions
stack, and the artwork buttons take their natural width — the same seam the
MP3 Tool and the Maker read.
"""

import queue
import sys
import time
from collections.abc import Mapping
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Make the scripts/ root importable so `shared.*` resolves whether this tool is
# run standalone (python mp3_tools/m4b_metadata_editor.py) or imported by the launcher.
_SCRIPTS_ROOT = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ROOT))

from shared import config as shared_config
from shared import job_control
from shared import job_ui
from shared import output_paths
from shared import paths
from shared import settings
from shared import subprocess_utils as sp
from shared import ui_theme
from shared.book_workspace import (
    BookDisposition,
    SharedMetadata,
    WorkspaceRunResult,
    WorkspaceSnapshot,
    disabled_fields,
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
from mp3_tools import m4b_metadata_batch as batch
from mp3_tools import m4b_metadata_plan as mp
from mp3_tools import m4b_metadata_workflow as wf
from mp3_tools.m4b_artwork_ui import ArtworkControl
from mp3_tools.m4b_metadata_plan import EditorAction

APP_TITLE = "M4B Metadata Editor"

TOOL_KEY = "m4b_metadata"
SLUG = paths.TOOL_SLUGS[TOOL_KEY]

# settings.json keys (dialog locations only; the output folder is NOT persisted).
KEY_INPUT_DIR = "m4b_metadata.input_dir"
KEY_COVER_DIR = "m4b_metadata.cover_dir"

#: The compact status shown for the current Book, read from the run.
STATUS_READY = "Ready"
STATUS_QUEUED = "Queued"
STATUS_PROCESSING = "Processing"
STATUS_COMPLETED = "Completed"
STATUS_FAILED = "Failed"
STATUS_SKIPPED = "Skipped (unreadable)"
STATUS_NOT_ATTEMPTED = "Not attempted"

#: Characters of the page Title / filename shown after ``Book N`` before eliding.
HINT_LIMIT = 40

#: How many frozen Summary and Detailed lines the log region keeps.
LOG_LIMIT = 400

#: The run id the job area carries before any operation has started.
IDLE_RUN_ID = "m4b-metadata-idle"

#: Rules a line under the previous run's lines in both log panes.
DIVIDER_MARK = "────"

#: What the panel says about preserve-by-default, once, where the fields are.
SHARED_TITLE = "Shared — a value here overrides every Book; blank = each Book on its own"
BOOK_TITLE = "Current Book — blank or unchanged = keep the source's own value"
PRESERVE_HINT = ("Originals are never modified; each action writes copies to a new output "
                 "run. Blank or unchanged Book fields keep the source's values.")

#: The action labels the run announces and the log headings use.
ACTION_LABELS = batch.ACTION_LABELS


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
        "entry_width": int(metrics.get("field_entry_width", 9)),
        "label_wrap": metrics.get("field_label_wrap"),
        "artwork_buttons": str(metrics.get("artwork_buttons", "fixed")),
        "artwork_gap": int(metrics.get("artwork_gap", 12)),
    }


# ---------------------------
# GUI
# ---------------------------


class M4BMetadataEditorUI(ttk.Frame):
    """The M4B Metadata Editor as an embeddable frame: one page per imported file."""

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
        builds the ``EditorRun`` (the Phase 9 class by default).
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
        self._ids = IdFactory("m4b-meta-") if id_factory is None else id_factory
        self._choose_files = self._ask_files if choose_files is None else choose_files
        self._choose_folder = self._ask_folder if choose_folder is None else choose_folder
        self._choose_artwork = (self._ask_artwork if choose_artwork is None
                                else choose_artwork)
        self._confirm = self._ask_confirm if confirm is None else confirm
        self._confirm_large = (self._confirm_large_result
                               if confirm_large_result is None
                               else confirm_large_result)
        self._thread_factory = (self._default_thread if thread_factory is None
                                else thread_factory)
        self._bridge = job_control.LoggerBridge() if bridge is None else bridge
        self._run_factory = batch.EditorRun if run_factory is None else run_factory

        # --- the workspace ------------------------------------------------- #
        # The one mutable reference to the current immutable workspace, and
        # the immutable store of what each source contains. Every edit asks a
        # model operation and renders the value back.
        self.workspace: WorkspaceSnapshot = wf.new_workspace(id_factory=self._ids)
        self.store: wf.ObservationStore = wf.ObservationStore()
        # The user-facing Book number by stable id: assigned once, never reused
        # while that workspace lives; a folder import starts again at 1.
        self.book_numbers: dict[str, int] = {}
        #: The most recently frozen plan and the run that executes it. Retry
        #: Failed reads only these; nothing here reads them back into widgets.
        self.last_plan: mp.RunPlan | None = None
        self.run: batch.EditorRun | None = None
        self._attempt: batch.Attempt | None = None
        self._label: str = ""
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

        # Where the next run will go, shown read-only.
        self.var_outdir = tk.StringVar(value=output_paths.destination_hint(TOOL_KEY))
        output_paths.register_destination_hint(TOOL_KEY, self.var_outdir)

        self._build(theme)

        # Run locking is the shared contract: the adapter's lock group applies
        # the approved matrix to these seams whenever the run's state moves.
        self._import_lock = self._ButtonLock(self.btn_import_folder, self.btn_add_files)
        self._options_lock = self._ButtonLock(
            self.btn_save, self.btn_clear_tags, self.btn_remove_numbering,
            self.check_auto_number, self.entry_start_part)
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
        # regions -- the chapter box and the log -- absorb a short window, so
        # at 920x600 the actions row never falls off the bottom and no
        # whole-panel scrollbar is needed.
        self.rowconfigure(0, weight=0)   # Import Folder, Add Files, import status, output
        self.rowconfigure(1, weight=0)   # navigator
        self.rowconfigure(2, weight=0)   # Shared + Current Book
        self.rowconfigure(3, weight=3)   # chapter titles -- scrolls
        self.rowconfigure(4, weight=0)   # run options + preserve hint
        self.rowconfigure(5, weight=0)   # actions, job controls, progress
        self.rowconfigure(6, weight=2)   # the one log region -- scrolls

        # -- row 0: workspace-level import ------------------------------ #
        top = ttk.Frame(self, style=style_name(theme, "window"))
        top.grid(row=0, column=0, sticky="ew", padx=pad, pady=(pad, gap_small))
        top.columnconfigure(2, weight=1)
        self.btn_import_folder = ttk.Button(
            top, text="Import Folder", style=style_name(theme, "button"),
            command=self.import_folder)
        self.btn_import_folder.grid(row=0, column=0, sticky="w")
        self.btn_add_files = ttk.Button(
            top, text="Add Files", style=style_name(theme, "button"),
            command=self.add_files)
        self.btn_add_files.grid(row=0, column=1, sticky="w", padx=(4, 0))
        self.import_status = job_ui.ImportStatusBar(
            top, theme=theme, on_cancel=self.cancel_import)
        self.import_status.frame.grid(row=0, column=2, sticky="ew", padx=(10, 10))
        self.output_label = ttk.Label(
            top, textvariable=self.var_outdir, anchor="e",
            style=style_name(theme, "secondary_label"))
        self.output_label.grid(row=0, column=3, sticky="e")
        self.btn_open_out = ttk.Button(
            top, text="Open Output Folder", style=style_name(theme, "button"),
            command=self.open_outdir)
        self.btn_open_out.grid(row=0, column=4, sticky="e", padx=(6, 0))

        # -- row 1: the shared navigator, Editor action subset ------------ #
        self.navigator = BookNavigator(
            self, theme=theme, layout=hints["navigator_layout"],
            actions=(BookNavigator.REMOVE,),
            describe=self._describe, label_for=self._label_for,
            on_previous=self.on_previous, on_next=self.on_next,
            on_remove=self.on_remove, on_select=self.on_select)
        self.navigator.frame.grid(row=1, column=0, sticky="ew", padx=pad,
                                  pady=(0, gap_small))

        # -- row 2: Shared above Current Book ----------------------------- #
        text_fields = tuple((key, wf.FIELD_LABELS[key]) for key in wf.TEXT_FIELDS)
        wrap = hints["label_wrap"]
        self.surface = SharedMetadataSurface(
            self, text_fields, theme=theme, layout="rows",
            show_header=False, entry_width=hints["entry_width"],
            wraplength=None if wrap is None else int(wrap),
            shared_title=SHARED_TITLE, book_title=BOOK_TITLE,
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
        self.book_artwork.frame.grid(row=0, column=field_columns, rowspan=5,
                                     sticky="nw", padx=(hints["artwork_gap"], 0))

        # The read-back lines under the Book fields: source identity, the
        # series read-back and the compact facts + status. Display only.
        readback = ttk.Frame(self.surface.book_frame, style=style_name(theme, "surface"))
        readback.grid(row=2, column=0, columnspan=field_columns, sticky="ew", pady=(4, 0))
        readback.columnconfigure(0, weight=1)
        self.var_source = tk.StringVar(master=self, value="")
        self.source_label = ttk.Label(readback, textvariable=self.var_source, anchor="w",
                                      style=style_name(theme, "secondary_label"))
        self.source_label.grid(row=0, column=0, sticky="ew")
        self.var_readback = tk.StringVar(master=self, value="")
        self.readback_label = ttk.Label(readback, textvariable=self.var_readback, anchor="w",
                                        style=style_name(theme, "secondary_label"))
        self.readback_label.grid(row=1, column=0, sticky="ew")
        facts = ttk.Frame(readback, style=style_name(theme, "surface"))
        facts.grid(row=2, column=0, sticky="ew")
        self.var_facts = tk.StringVar(master=self, value="")
        self.facts_label = ttk.Label(facts, textvariable=self.var_facts, anchor="w",
                                     style=style_name(theme, "secondary_label"))
        self.facts_label.grid(row=0, column=0, sticky="w")
        ttk.Label(facts, text="Status:", style=style_name(theme, "label")).grid(
            row=0, column=1, sticky="w", padx=(12, 4))
        self.status_label = ttk.Label(facts, text=STATUS_READY,
                                      style=style_name(theme, "status_label"))
        self.status_label.grid(row=0, column=2, sticky="w")

        # -- row 3: the local Chapter Titles editor ------------------------ #
        chapters = ttk.Labelframe(
            self, text="Chapter Titles (this Book) — line N renames chapter N; "
                       "a blank or unchanged line keeps the source title",
            style=style_name(theme, "labelframe"), padding=(6, 2))
        chapters.grid(row=3, column=0, sticky="nsew", padx=pad, pady=(0, gap))
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

        # -- row 4: series numbering + the preserve hint ------------------- #
        options = ttk.Frame(self, style=style_name(theme, "window"))
        options.grid(row=4, column=0, sticky="ew", padx=pad, pady=(0, gap_small))
        options.columnconfigure(3, weight=1)
        self.var_auto_number = tk.BooleanVar(master=self, value=False)
        self.check_auto_number = ttk.Checkbutton(
            options, text="Auto-number Series Part (Save / Clear; successes only)",
            variable=self.var_auto_number, style=style_name(theme, "checkbutton"))
        self.check_auto_number.grid(row=0, column=0, sticky="w")
        ttk.Label(options, text="Start Part (blank → 1):",
                  style=style_name(theme, "label")).grid(
            row=0, column=1, sticky="w", padx=(12, 4))
        self.var_start_part = tk.StringVar(master=self, value="")
        self.entry_start_part = ttk.Entry(
            options, textvariable=self.var_start_part, width=6,
            style=style_name(theme, "entry"))
        self.entry_start_part.grid(row=0, column=2, sticky="w")
        self.hint_label = ttk.Label(options, text=PRESERVE_HINT, anchor="w",
                                    style=style_name(theme, "secondary_label"))
        self.hint_label.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(2, 0))

        # -- row 5: the three actions, the shared job area, Clear Log ------ #
        self.actions = ttk.Frame(self, style=style_name(theme, "window"))
        self.actions.grid(row=5, column=0, sticky="ew", padx=pad, pady=(0, gap))
        self.actions.columnconfigure(2, weight=1)
        buttons = ttk.Frame(self.actions, style=style_name(theme, "window"))
        buttons.grid(row=0, column=0, rowspan=2, sticky="nw")
        self.btn_save = ttk.Button(
            buttons, text="Save Tags", style=style_name(theme, "primary_button"),
            command=self.save)
        self.btn_clear_tags = ttk.Button(
            buttons, text="Clear All Tags (keep chapters)",
            style=style_name(theme, "danger_button"), command=self.on_clear_all_tags)
        self.btn_remove_numbering = ttk.Button(
            buttons, text="Remove Series Numbering",
            style=style_name(theme, "danger_button"), command=self.on_remove_series_numbering)
        self.btn_clear_log = ttk.Button(
            buttons, text="Clear Log", style=style_name(theme, "button"),
            command=self.clear_log)
        if hints["actions_layout"] == "row":
            self.btn_save.grid(row=0, column=0, sticky="w")
            self.btn_clear_tags.grid(row=0, column=1, sticky="w", padx=(6, 0))
            self.btn_remove_numbering.grid(row=0, column=2, sticky="w", padx=(6, 0))
            self.btn_clear_log.grid(row=1, column=0, sticky="w", pady=(4, 0))
        else:
            for row, button in enumerate((self.btn_save, self.btn_clear_tags,
                                          self.btn_remove_numbering, self.btn_clear_log)):
                button.grid(row=row, column=0, sticky="ew", pady=(0 if row == 0 else 4, 0))
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
        self.jobs.frame.grid(row=0, column=2, rowspan=self._jobs_rowspan, sticky="ew",
                             padx=(12, 0))
        self.jobs.controls.frame.grid_configure(sticky="e")
        self.controls = self.jobs.controls
        self.status = self.jobs.status
        self.lock_group = self.jobs.locks
        self.status.indicator.frame.configure(style=style_name(theme, "card"))
        self.status.indicator.bar.configure(style=style_name(theme, "progressbar"))
        self.status.indicator.label.configure(style=style_name(theme, "status_label"))
        self.jobs.register_inputs(self.navigator, self._import_lock)
        self.jobs.register_options(self.surface, self.shared_artwork, self.book_artwork,
                                   self._options_lock, self._chapters_lock)
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
            parent=self, title="Select M4B file(s)",
            initialdir=str(_remembered_dir(KEY_INPUT_DIR)),
            filetypes=[("M4B Audiobooks", "*.m4b"), ("MP4 audio", "*.m4a *.mp4"),
                       ("All files", "*.*")]))
        if chosen:
            settings.set(KEY_INPUT_DIR, str(Path(chosen[0]).parent))
        return chosen

    def _ask_folder(self):
        chosen = filedialog.askdirectory(
            parent=self, title="Select a folder of M4B files",
            initialdir=str(_remembered_dir(KEY_INPUT_DIR)), mustexist=True)
        if not chosen:
            return ()
        settings.set(KEY_INPUT_DIR, str(chosen))
        return (str(chosen),)

    def _ask_artwork(self) -> str:
        chosen = m4b_artwork_ui.ask_artwork(
            self, initialdir=_remembered_dir(KEY_COVER_DIR), title="Select Artwork")
        if chosen:
            settings.set(KEY_COVER_DIR, str(Path(chosen).parent))
        return chosen

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
            "Import a large number of files?",
            f"{outcome.proposed_count:,} files are ready to be imported, one Book each.\n\n"
            "Importing this many at once can make the workspace slow. Import them?")

    # ------------------------------------------------------------------ #
    # Rendering
    # ------------------------------------------------------------------ #

    def _describe(self, book) -> str:
        return wf.display_hint(self.workspace.shared, book, self.store)

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
        """Show the current workspace. Every value comes from the snapshot and the store.

        Rendering is not an edit: the Book entries are populated with the
        model's page values while ``_rendering`` holds, and the change
        callbacks ignore everything that arrives during that window.
        """
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
            # What the page shows: Shared -> Book edit -> source prefill. The
            # surface rendered the stored edits; the prefill is displayed over
            # them here, and displaying it writes nothing into the Book.
            shown = wf.page_values(space.shared, book, self.store)
            for name in self.surface.fields:
                if self.surface.book_value(name) != shown[name]:
                    self.surface.set_book_text(name, shown[name])
            overridden = disabled_fields(space.shared)
            self.shared_artwork.set_path(str(space.shared.values.get("artwork", "")))
            self.book_artwork.set_path(str(book.configuration.get("artwork", "")))
            self.book_artwork.set_enabled("artwork" not in overridden)
            self._render_readback()
            self._render_chapters()
            self._render_status()
        finally:
            self._rendering = False

    def _render_readback(self) -> None:
        """The source facts beside the entries: identity, series, part, cover, chapters."""
        book = self.workspace.current
        source = wf.source_of(book)
        seen = self.store.for_book(book)
        if source is None:
            self.var_source.set("No source — use Import Folder or Add Files.")
            self.var_readback.set("")
            self.var_facts.set("")
            return
        path = source.path
        if seen is None or not seen.readable:
            error = seen.error if seen is not None and seen.error else "unreadable"
            self.var_source.set(f"Source: {path.name}  ({path.parent})  — "
                                f"the file's tags could not be read: {error}")
            self.var_readback.set(wf.series_readback(seen))
            self.var_facts.set("Series Part: —  ·  Artwork: unknown  ·  Chapters: —")
            return
        self.var_source.set(f"Source: {path.name}  ({path.parent})  — readable")
        self.var_readback.set(wf.series_readback(seen))
        part = seen.series_part.strip() or "—"
        if seen.series_part_source and seen.series_part.strip():
            part = f"{part} ({seen.series_part_source})"
        cover = "on file" if seen.has_cover else "none"
        self.var_facts.set(f"Series Part: {part}  ·  Artwork: {cover}  ·  "
                           f"Chapters: {seen.chapter_count}")

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

    def _chapter_display(self) -> str:
        """The stored chapter buffer; until the user edits it, the source's titles."""
        book = self.workspace.current
        if "chapter_titles" in book.configuration:
            return wf.chapter_titles_text(book)
        seen = self.store.for_book(book)
        if seen is None or not seen.readable:
            return ""
        return "\n".join(seen.chapter_titles)

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
        return self.surface.fields + ("artwork", "chapter_titles")

    def book_field_enabled(self, name: str) -> bool:
        """Whether the current Book's control for *name* is usable right now."""
        if name == "artwork":
            return self.book_artwork.enabled
        if name == "chapter_titles":
            return str(self.chapter_text.cget("state")) != "disabled"
        return self.surface.book_field_enabled(name)

    def book_value(self, name: str) -> str:
        """The text the current Book's control shows for *name*."""
        return self.surface.book_value(name)

    def book_status_text(self) -> str:
        return str(self.status_label.cget("text"))

    def source_text(self) -> str:
        return self.var_source.get()

    def series_readback_text(self) -> str:
        return self.var_readback.get()

    def facts_text(self) -> str:
        return self.var_facts.get()

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

    def _receive(self, result: wf.ReceiveResult) -> None:
        """An import's result: the grown store first, then the workspace."""
        self.store = result.store
        self._apply(result.mutation)

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

    def on_remove(self, meaningful: bool) -> None:
        """Decision 50A: the model answered; this panel decides to ask."""
        if meaningful and not self._confirm(
                "Remove this Book?",
                "This page holds an imported file or edited values.\n\n"
                "Remove it from the workspace? (The file itself is not touched.)"):
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
        """A keystroke in a Book entry — the only way a text edit is stored."""
        if self._rendering:
            return
        mutation = wf.set_book_field(self.workspace, field, raw)
        if mutation.changed:
            self.workspace = mutation.workspace
        self._render_light()

    def set_book_field(self, name: str, value) -> None:
        """Store one raw explicit Book edit and show it. The model owns the write."""
        self._guard.require("set_book_field")
        self._apply(wf.set_book_field(self.workspace, name, value))

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
        messagebox.showerror(APP_TITLE, f"Artwork: {message}", parent=self)

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

    # ------------------------------------------------------------------ #
    # Importing
    # ------------------------------------------------------------------ #

    def _request(self, roots: tuple) -> ScanRequest:
        return ScanRequest(
            request_id=self._ids.next_id("req"),
            roots=roots,
            catalog=wf.EDITOR_CATALOG,
            options=ImportOptions.for_catalog(wf.EDITOR_CATALOG),
            effective_config=self._effective_config,
            created_at=self._clock(),
        )

    def import_folder(self) -> None:
        """Workspace-level: scan one folder, then replace the Books — one per file."""
        self._guard.require("import_folder")
        if self._closed or self._coordinator.is_active:
            return
        if any(has_meaningful_work(book) for book in self.workspace.books):
            if not self._confirm(
                    "Replace the current Books?",
                    "Import Folder replaces every Book in the workspace with the "
                    "files it finds, one Book per file.\n\nReplace them?"):
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
        """Append one Book per chosen file; a source already held is skipped."""
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
        """The committed snapshot becomes Books: one per occurrence, observed once."""
        commit = outcome.commit
        if kind == "folder":
            result = wf.import_folder(self.workspace, commit.snapshot,
                                      id_factory=self._ids, store=self.store)
            self._receive(result)
            books = [book for book in self.workspace.books if not book.files.is_empty]
            unreadable = sum(
                1 for book in books
                if (seen := self.store.for_book(book)) is not None and not seen.readable)
            note = f" {unreadable} could not be read and will be skipped." if unreadable else ""
            self._say(f"Import Folder: {len(books)} file(s) → {len(books)} Book(s).{note}")
            return
        result = wf.add_files(self.workspace, tuple(commit.added), store=self.store,
                              id_factory=self._ids)
        self._receive(result)
        added = len(commit.added) - result.skipped
        note = (f" {result.skipped} already in the workspace were skipped."
                if result.skipped else "")
        self._say(f"Add Files: {added} file(s) added as {added} Book(s).{note}")

    # ------------------------------------------------------------------ #
    # The three actions: validate, reserve one run, freeze one plan, run
    # ------------------------------------------------------------------ #

    def _run_options(self) -> mp.EditorRunOptions:
        return mp.EditorRunOptions(auto_number=bool(self.var_auto_number.get()),
                                   start_part_text=self.var_start_part.get())

    def _reserve_run(self):
        """Reserve one standard run for a validated action. None means do not start."""
        try:
            return output_paths.reserve_run_directory(TOOL_KEY)
        except output_paths.OutputPathError as exc:
            messagebox.showerror(APP_TITLE, exc.message, parent=self)
            return None

    def save(self) -> bool:
        """Write the explicit edits onto copies (preserve-by-default)."""
        self._guard.require("save")
        return self._start_action(EditorAction.SAVE_TAGS)

    def on_clear_all_tags(self) -> bool:
        """Clear every tag and the cover on copies, keep the chapters, reapply edits."""
        self._guard.require("on_clear_all_tags")
        if self._closed or self.is_running:
            return False
        if not self._confirm(
                "Clear all tags?",
                "This writes COPIES with all metadata removed (title, author, album, "
                "year, genre, comment, series, cover art).\n\n"
                "Chapters are kept (markers and titles). The imported originals are never "
                "modified. Only the values you typed here — Book edits and Shared "
                "values, and any replacement artwork — are re-applied on top of the "
                "cleared copies; unchanged source values are not.\n\nProceed?"):
            return False
        return self._start_action(EditorAction.CLEAR_ALL_TAGS)

    def on_remove_series_numbering(self) -> bool:
        """Strip the numbering surfaces on copies; the Series Name and every other tag stay."""
        self._guard.require("on_remove_series_numbering")
        if self._closed or self.is_running:
            return False
        if not self._confirm(
                "Remove series numbering?",
                "This writes COPIES with the series/track numbering removed: the "
                "Series Part, the track number (Explorer's # column) and the movement "
                "index — across every tagger namespace.\n\n"
                "The Series Name, chapter markers and titles, cover art and every other "
                "tag are kept. Pending edits on these pages are not part of this action. "
                "The imported originals are never modified.\n\nProceed?"):
            return False
        return self._start_action(EditorAction.REMOVE_SERIES_NUMBERING)

    def _start_action(self, action: EditorAction) -> bool:
        """Validate, reserve one run, freeze one plan, start one run."""
        if self._closed or self.is_running:
            return False
        space = self.workspace
        if all(wf.source_of(book) is None for book in space.books):
            messagebox.showwarning(APP_TITLE, "Import a folder or add M4B files first.",
                                   parent=self)
            return False
        options = self._run_options()
        if options.auto_number and action is not EditorAction.REMOVE_SERIES_NUMBERING:
            try:
                wf.parse_start_part(options.start_part_text)
            except wf.EditorValueError as exc:
                messagebox.showerror(APP_TITLE, f"Start Part: {exc}", parent=self)
                return False
        reservation = self._reserve_run()
        if reservation is None:
            return False
        try:
            plan = mp.plan_run(
                space, self.store, action=action, options=options, reservation=reservation,
                catalog=wf.EDITOR_CATALOG,
                import_options=ImportOptions.for_catalog(wf.EDITOR_CATALOG),
                effective_config=self._effective_config, id_factory=self._ids,
                created_at=self._clock())
        except (wf.EditorValueError, mp.PlanError, output_paths.OutputPathError) as exc:
            output_paths.release_if_empty(reservation)
            messagebox.showerror(APP_TITLE, f"{ACTION_LABELS[action]}: {exc}", parent=self)
            return False
        if not plan.books:
            output_paths.release_if_empty(reservation)
            messagebox.showwarning(
                APP_TITLE, "None of the imported files could be read, so there is "
                           "nothing to write.", parent=self)
            return False
        self.last_plan = plan
        self._label = ACTION_LABELS[action]
        self.run = self._run_factory(plan, id_factory=self._ids, clock=self._clock,
                                     publish=self._publish)
        self.var_outdir.set(str(plan.run_directory))
        self._start_attempt(self.run.start, self._label)
        return True

    def _start_attempt(self, begin, label: str) -> None:
        """Begin one attempt through the run and start its one worker thread."""
        # The queue exists before the run publishes its first event; the
        # adapter installed just after drains everything the attempt sends.
        self._event_q = queue.Queue()
        attempt = begin()
        self._attempt = attempt
        item_ids = tuple(book.occurrence_id for book in self.last_plan.books)
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
                   else f"{label} — {self.last_plan.run_directory.name}")
        self.log.divider(f"{DIVIDER_MARK} {heading}")
        skipped = len(self.last_plan.capture.skipped)
        if skipped and not attempt.is_retry:
            self._say(f"{label}: {skipped} unreadable file(s) skipped; the others proceed.")
        self._render_status()
        thread = self._thread_factory(attempt.run, f"m4b-metadata-{attempt.run_id}")
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
            self._say(f"{self._label}: {result.succeeded_count} Book(s) completed, "
                      f"{result.failed_count} failed, {result.skipped_invalid_count} "
                      f"skipped (unreadable), {result.not_attempted_count} not attempted "
                      f"→ {self.last_plan.run_directory}")
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

    # -- the output folder ---------------------------------------------------- #

    def output_dir(self) -> Path:
        """The last frozen run's folder, or this tool's parent folder before any run."""
        if self.last_plan is not None:
            return self.last_plan.run_directory
        return Path(self.var_outdir.get().strip())

    def open_outdir(self) -> None:
        """Reveal the last run, or the tool folder before any run."""
        self._guard.require("open_outdir")
        if self.last_plan is None:
            try:
                sp.reveal_in_file_manager(output_paths.ensure_tool_parent(TOOL_KEY))
            except output_paths.OutputPathError as exc:
                messagebox.showerror(APP_TITLE, exc.message, parent=self)
            return
        sp.reveal_in_file_manager(self.output_dir())

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


def build_ui(parent: tk.Misc, theme=None) -> M4BMetadataEditorUI:
    """Build the M4B Metadata Editor UI into ``parent`` and return the frame."""
    ui = M4BMetadataEditorUI(parent, theme=theme)
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
