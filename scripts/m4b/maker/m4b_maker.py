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

Presentation (v0.6.6 Phase 7): the panel is the dense multi-Book (Family B)
workflow on the shared compact Light/Dark control language, the same one the
approved Cover, TTS, Converter and MP3 Tool interiors use. There is no
Maker-specific visual system:

  1. Import & Books              -- Import Folder, Clear All Imports, the import
                                    status, the output hint and the Book navigator
  2. Book Settings               -- Shared (the tinted group whose values override
                                    every Book's own) above Current Book (the
                                    ordinary surface, with the Book-only Title,
                                    Series Part, Output Filename and status)
  3. Tracks, Chapters & Build    -- the track list and Chapter Titles side by
                                    side, the run options (series numbering,
                                    FAST, custom destination), then Build and
                                    the shared job area
  Activity                       -- the one Summary | Detailed log with Clear
                                    Log, below

Every widget asks ``job_ui.style_name`` of the ``appearance_bundle`` for its
compact style (native control inheritance on Aqua), and a live Light/Dark
toggle recolors the few classic Tk widgets in place. No colour, font or metric
is declared here. Nothing scrolls the whole tool: the track list, the Chapter
Titles box and the log scroll locally and give up height first, and in the
real launcher's small windows the fixed bands take tighter padding
(``_apply_density``) before either flexible region is squeezed.

Composition follows the theme's metrics where it offers panel hints
(``_layout_hints``): where native aqua controls are wider and taller, the
navigator's Book actions fold under its navigation row, the artwork buttons
take their natural width, the labels wrap and the destination toggle takes a
line of its own -- the same seam the MP3 Tool reads. A bundle without those
hints gets the compact composition. Only where things sit differs.
"""

import gc
import queue
import sys
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox

# Make the scripts/ root importable so `shared.*` resolves whether this tool is
# run standalone (python m4b/maker/m4b_maker.py) or imported by the launcher.
_SCRIPTS_ROOT = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ROOT))

from shared import appearance
from shared import config as shared_config
from shared import job_control
from shared import job_ui
from shared import logging_setup
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
from shared.job_control import (
    JobAction,
    JobEventKind,
    JobState,
    ProgressMode,
    ProgressView,
    TERMINAL_STATES,
)
from shared.job_ui import MainThreadGuard, MainThreadPump, action_style, style_name
from artwork import m4b_artwork_ui
from m4b import m4b_preparation as prep
from m4b.maker import m4b_maker_batch as batch
from m4b.maker import m4b_maker_plan as mp
from m4b.maker import m4b_maker_workflow as wf
from artwork.m4b_artwork_ui import ArtworkControl
from shared import work_area

APP_TITLE = "M4B Maker"

# Every standard build lands in <output base>/M4B-Maker-Outputs/M4B-Maker-N
# through the shared service; the custom destination is the explicit exception.
CUSTOM_DEST_LABEL = "Choose custom destination"

#: Two run options' wording, and the same options in the tight density
#: (v0.6.6 Phase 7; the MP3 Tool's "Mixed" precedent). At the real launcher's
#: 920x600 content area the full wording fills the options line, so the
#: custom destination's path row would need a line of its own and push
#: Activity off screen; the short wording leaves room for it on the same
#: line. Same controls, same variables, same meaning.
START_PART_LABEL = "Start Part (blank → 1):"
START_PART_LABEL_SHORT = "Start Part:"
FAST_LABEL = "Try FAST first (auto-fallback to Safe)"
FAST_LABEL_SHORT = "Try FAST first"

TOOL_KEY = "m4b_maker"
SLUG = paths.TOOL_SLUGS[TOOL_KEY]

# settings.json keys. Each only remembers where its dialog opens (v0.8.1: import,
# artwork and custom-destination histories are separate); the output folder and
# the custom destination itself are NOT persisted.
KEY_INPUT_DIR = "m4b_maker.input_dir"
KEY_COVER_DIR = "m4b_maker.cover_dir"
KEY_DEST_DIR = "m4b_maker.destination_dir"

#: The compact status shown for the current Book, read from the run.
STATUS_READY = "Ready"
STATUS_QUEUED = "Queued"
STATUS_PROCESSING = "Processing"
STATUS_COMPLETED = "Completed"
STATUS_FAILED = "Failed"
STATUS_SKIPPED = "Skipped"
STATUS_NOT_ATTEMPTED = "Not attempted"
#: The Book a Cancel stopped part-way (v0.7.2, ACT72-004). Its result stays NOT_ATTEMPTED (no new disposition); this
#: only tells it apart from the Books the run never reached.
STATUS_CANCELLED = "Cancelled"

#: Characters of Title / Album / folder hint shown after ``Book N`` before eliding.
HINT_LIMIT = 40

#: How many frozen Summary and Detailed lines the log region keeps.
LOG_LIMIT = 400

#: The run id the job area carries before any operation has started.
IDLE_RUN_ID = "m4b-idle"

#: v0.8.2 Checkpoint 2: what the job area says between an accepted Build press and the plan's adoption, while the
#: preparation worker reserves (or validates the custom folder) and plans every Book off the Tk thread. The same
#: words as the MP3 Tool's.
STATUS_PREPARING = "Preparing job…"
STATUS_CANCELLING_PREPARATION = "Cancelling preparation…"
STATUS_PREPARATION_CANCELLED = "Cancelled — nothing was started"
STATUS_PREPARATION_FAILED = "Not started"

#: How many preparation messages one pump tick handles at most (one per Book plus one ending, normally).
PREPARATION_DRAIN_LIMIT = 256

#: The Build label every Build message starts with.
BUILD_LABEL = "Build"

#: Rules a line under the previous run's lines in both log panes.
DIVIDER_MARK = "────"

#: The staging root a custom build uses, inside its owned work-area entry (v0.7.2, ACT72-031).
CUSTOM_STAGING_NAME = "staging"


def _recover_owned_temporaries(cancel_check) -> list[str]:
    """What killed runs left in the owned work area, removed only once their owner is provably gone (ACT72-031).

    Called by the run on its worker thread at a custom build's start, bounded by Cancel and by the work area's own
    limit; never touches a running owner's entries or anything the work area did not make."""
    return work_area.recover(cancel_check=cancel_check).log_lines()


# ---------------------------
# Preparing a Build off the Tk thread (v0.8.2 Checkpoint 2)
# ---------------------------


@dataclass(frozen=True)
class _BuildInputs:
    """What a Build press froze on Tk. The preparation worker reads nothing else.

    Immutable values, plus the panel's ``IdFactory`` (a lock-guarded counter) so the run's snapshot ids come from the
    same sequence as before. The Plan 6 capture is *derived* from the frozen workspace on the worker, inside
    ``plan_run``, exactly as v0.8.1 took it there: it is a pure function of immutable values, and taking it on Tk
    cost one ``RunSnapshot`` per Book there (measured, v0.8.2 Checkpoint 2).
    """

    workspace: WorkspaceSnapshot
    options: mp.MakerRunOptions
    #: The custom folder as typed while the toggle was on, else ``None`` (a standard run).
    custom: str | None
    #: The one output configuration of the press: every Book's run snapshot records it and the reservation
    #: resolves its output base from it.
    run_config: object
    id_factory: IdFactory
    created_at: float


@dataclass(frozen=True)
class _Prepared:
    """A finished plan and, for a custom build, the owned work-area entry it stages in."""

    plan: mp.RunPlan
    owned: object | None


class _AttemptNotStarted(Exception):
    """An attempt's setup failed before anything changed hands (v0.8.2).

    Raised by ``_start_attempt`` only while the previous job area, run, result and Retry Failed are all still exactly
    as they were, so the caller can report it and carry on as if the press had been refused.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def _reserve_destination(inputs: _BuildInputs):
    """Worker: one reserved standard run, or the validated custom folder with its owned work-area entry.

    The same decisions and the same refusal texts as v0.8.1's ``_destination`` on Tk. Custom mode writes straight into
    the chosen folder: no standard run is reserved, and staging lives elsewhere, never among the user's files -- an
    entry of the owned work area (``shared.work_area``, kind "maker"; v0.7.2, ACT72-031), listed with this process as
    owner before it exists, closed once no Retry Failed can reach it, and recovered by a later run if this one is
    killed. Never a loose, unowned temporary folder. Returns ``(MakerDestination, owned or None)``.
    """
    if inputs.custom is not None:
        try:
            folder = output_paths.validate_custom_destination(inputs.custom)
        except output_paths.OutputPathError as exc:
            raise prep.Refusal(exc.message, exc.detail) from exc
        try:
            owned = work_area.new_folder("maker")
        except OSError as exc:
            raise prep.Refusal(f"{BUILD_LABEL}: {exc}", f"{type(exc).__name__}: {exc}") from exc
        try:
            return mp.custom_destination(folder, work_root=owned.path / CUSTOM_STAGING_NAME), owned
        except mp.PlanError as exc:
            owned.close()
            raise prep.Refusal(str(exc)) from exc
        except BaseException:
            owned.close()
            raise
    try:
        reservation = output_paths.reserve_run_directory(TOOL_KEY, effective=inputs.run_config)
    except output_paths.OutputPathError as exc:
        raise prep.Refusal(exc.message, exc.detail) from exc
    return mp.standard_destination(reservation), None


def _release_destination(holding) -> None:
    """Give back what :func:`_reserve_destination` took while nothing was written into it. Any thread; never raises.

    The standard run folder goes only while still empty (``release_if_empty`` leaves links and contents alone); a
    custom build's owned work-area entry is closed. The chosen custom folder itself is never touched.
    """
    destination, owned = holding
    if destination.reservation is not None:
        try:
            output_paths.release_if_empty(destination.reservation)
        except Exception:  # noqa: BLE001 - release_if_empty never raises; still, a worker must not
            pass
    if owned is not None:
        try:
            owned.close()
        except Exception:  # noqa: BLE001
            pass


def _plan_build(inputs: _BuildInputs, holding, checkpoint, progress) -> _Prepared:
    """Worker: plan every Book from the frozen inputs into the destination just reserved."""
    destination, owned = holding
    plan = mp.plan_run(inputs.workspace, options=inputs.options, destination=destination,
                       catalog=wf.MAKER_CATALOG, import_options=ImportOptions.for_catalog(wf.MAKER_CATALOG),
                       effective_config=inputs.run_config, id_factory=inputs.id_factory,
                       created_at=inputs.created_at, checkpoint=checkpoint, progress=progress)
    return _Prepared(plan=plan, owned=owned)


def _build_refusal(exc: BaseException) -> prep.Refusal | None:
    """The plan's own refusals, worded exactly as v0.8.1's Build reported them; anything else is a fault."""
    if isinstance(exc, (wf.MakerValueError, mp.PlanError, output_paths.OutputPathError)):
        detail = exc.detail if isinstance(exc, output_paths.OutputPathError) else ""
        return prep.Refusal(f"{BUILD_LABEL}: {exc}", detail)
    return None

#: The one label of the destructive workspace reset, shared by the three
#: multi-Book tools (v0.6.4 Phase 12 maintainer amendment).
CLEAR_IMPORTS_LABEL = "Clear All Imports"

#: v0.8.2 qualification: Import Folder replaces only the Books the user agreed to replace. If a Book was changed while
#: the import ran (the scan), nothing is replaced and this is said. The same sentence in the three multi-Book tools.
REPLACEMENT_REFUSED = ("Import Folder: the Books were changed while the import was running, so they were not "
                       "replaced and your changes were kept. Choose Import Folder again to replace them.")

#: The numbered Family-B hierarchy (frozen UI contract §2), and Activity below.
SECTION_TITLES = ("1. Import & Books", "2. Book Settings",
                  "3. Tracks, Chapters & Build", "Activity")

#: The Shared group's caption: what it is and what it does, in one line.
SHARED_TITLE = "Shared — applies to every Book and overrides its own value"

#: Spacing, identical to the Cover, TTS, Converter and MP3 Tool panels' own
#: constants: the approved Cover UI is the concrete visual reference for every
#: tool interior (maintainer ruling 2026-09-28), so these are copied, not
#: re-chosen.
OUTER_PAD = 10
SECTION_GAP = 8
SECTION_PADDING = (10, 6, 10, 8)

#: The frozen contract's tight-window steps (§1), used where the regular
#: density would squeeze a flexible region below its floor -- the real
#: launcher's 920x600 and 1024x720 content areas. Padding and chrome shrink
#: first; no control is hidden and the minimum size is unchanged.
TIGHT_OUTER_PAD = 3
TIGHT_SECTION_GAP = 2
TIGHT_SECTION_PADDING = (5, 0, 5, 1)

#: Rows the track list and Chapter Titles box ask for, and the rows each keeps
#: however small the window gets.
TRACK_ROWS = 6
TRACK_FLOOR_ROWS = 2
TIGHT_TRACK_FLOOR_ROWS = 1

#: The Activity log: natural size in lines, and the lines it keeps at the
#: smallest window (§3: Activity may shrink before a required control does).
LOG_HEIGHT = 6
LOG_FLOOR_LINES = 2
TIGHT_LOG_FLOOR_LINES = 1

#: The shared progress bar defaults to 240 px; the job area sits beside Build,
#: so a shorter bar keeps that row inside the minimum.
PROGRESS_BAR_LENGTH = 160

#: In the tight density the status view sits beside the job controls, the
#: status line beside a shorter progress bar; a long message wraps there
#: instead of widening the row.
TIGHT_PROGRESS_BAR_LENGTH = 110
TIGHT_STATUS_WRAP = 150


# ---------------------------
# Utilities
# ---------------------------


def _remembered_dir(key: str) -> Path:
    """The saved folder for ``key`` while it is reachable, else the home dir (never erased)."""
    return settings.remembered_dir(key)


def _layout_hints(theme) -> dict:
    """The panel's composition, read off the theme bundle with its own defaults.

    The defaults are the compact composition (v0.6.6 Phase 7: the outer pad
    and section gap are the Cover/TTS/Converter/MP3 Tool constants; the output
    hint yields in the import band, the entries ask for 8 characters, and the
    Book-only row runs the full width beneath the artwork -- which is what
    keeps Book Settings inside the real launcher's 920x600 content area). A
    theme whose ``metrics`` carry the panel hints (the aqua bundle) overrides
    them; one without changes nothing. Presentation only: nothing read here
    reaches the model or the plan.
    """
    metrics = (theme or {}).get("metrics") or {}
    if not isinstance(metrics, Mapping):
        metrics = {}
    return {
        "pad": int(metrics.get("panel_pad", OUTER_PAD)),
        "gap": int(metrics.get("panel_gap", SECTION_GAP)),
        "gap_small": int(metrics.get("panel_gap_small", 4)),
        "navigator_layout": str(metrics.get("navigator_layout", "row")),
        "actions_layout": str(metrics.get("actions_layout", "row")),
        "entry_width": int(metrics.get("field_entry_width", 8)),
        "label_wrap": metrics.get("field_label_wrap"),
        "label_wrap_narrow": metrics.get("field_label_wrap_narrow"),
        "artwork_buttons": str(metrics.get("artwork_buttons", "fixed")),
        "artwork_gap": int(metrics.get("artwork_gap", 8)),
        # v0.6.4 Phase 13 (macOS parity), measured on the real launcher at
        # the aqua floor: the import band, the Shared / Book band, the
        # Book-only row and the run options each asked for more width than
        # the content host has. v0.6.6 Phase 7: the compact composition
        # takes the same compact import band and full-width Book-only row
        # for the same reason inside the launcher's 920x600 content area.
        "import_band_layout": str(metrics.get("import_band_layout", "compact")),
        "group_pad": int(metrics.get("group_pad", 6)),
        "field_gap": int(metrics.get("field_gap", 6)),
        "label_wrap_short": metrics.get("field_label_wrap_short"),
        "book_fields_span": str(metrics.get("book_fields_span", "wide")),
        "options_layout": str(metrics.get("options_layout", "row")),
        # v0.8.x P1B remediation (ACT72-078): in the tight density the status
        # line sits beside the controls; "fit" keeps it one line ending in an
        # ellipsis (it was cut mid-word on Aqua). Windows keeps its wrap.
        "status_line": str(metrics.get("status_line", "wrap")),
        # v0.8.x P1B remediation (ACT72-078): "fit" shortens a long Book label
        # so the navigator's "(X of Y)" is never cut. Windows keeps "natural".
        "navigator_heading": str(metrics.get("navigator_heading", "natural")),
    }


def _label_wraps(hints: Mapping[str, object], fields) -> dict[str, int] | None:
    """Per-field label widths for the metadata surface, or ``None`` for none.

    The Silence caption is this panel's long one (~200 px under aqua): it
    folds once at ``label_wrap_short`` when the theme offers it — the MP3
    Tool's ~300 px caption needs the wider ``label_wrap`` to fold only once —
    and at ``label_wrap`` otherwise.
    """
    wide = hints.get("label_wrap")
    if wide is None:
        return None
    short = hints.get("label_wrap_short")
    narrow = hints.get("label_wrap_narrow")
    wraps = {}
    for key in fields:
        if key == "silence":
            wraps[key] = int(wide if short is None else short)
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
        appearance_bundle: dict | None = None,
    ):
        """Build the panel.

        Every keyword is a seam the tests drive instead of a real dialog, clock
        or thread. Production passes none of them. ``thread_factory`` makes both
        the import scan's thread and the processing worker's; ``run_factory``
        builds the ``MakerRun`` (the Phase 5 class by default).

        ``appearance_bundle`` (v0.6.6 Phase 7) is the seam Cover, TTS, the
        Converter and the MP3 Tool take: the production default reads the
        remembered Light/Dark setting, and the suite may inject an exact bundle.
        Every widget is styled from it. ``theme`` is the platform bundle and now
        supplies only the composition hints (``_layout_hints``) -- the aqua
        arrangement.
        """
        if theme is None:
            theme = ui_theme.apply_theme(parent.winfo_toplevel(), ttk.Style(parent))
        if appearance_bundle is None:
            appearance_bundle = appearance.build_bundle(
                ttk.Style(parent), appearance.get_appearance(),
                root=parent.winfo_toplevel())
        self.appearance_bundle = appearance_bundle
        super().__init__(parent, style=style_name(appearance_bundle, "window"))
        self.theme = theme
        self._guard = MainThreadGuard()
        self._closed = False
        self._clock = time.monotonic if clock is None else clock
        self._effective_config = (shared_config.get_effective()
                                  if effective_config is None
                                  else effective_config)
        self._ids = IdFactory("m4b-") if id_factory is None else id_factory
        self._choose_files = self._ask_files if choose_files is None else choose_files
        # The folder an import dialog chose, held until its import settles (v0.8.1).
        self._pending_input_dir: str | None = None
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
        # v0.8.2 Checkpoint 2: an accepted Build press is prepared off the Tk thread. The press that is being
        # prepared (``None`` when none is), how many presses and release workers this panel has started (their
        # threads' names), and the queue the preparation worker speaks through, drained by the pump.
        self._preparing: prep.Preparation | None = None
        self._preparations = 0
        self._releases = 0
        self._prep_q: queue.SimpleQueue = queue.SimpleQueue()
        self._worker_thread = None

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
        # v0.8.2 qualification: the Books an Import Folder in progress was pressed to replace (None otherwise).
        self._replacing: tuple | None = None

        # Where the next standard run will go, shown read-only.
        self.var_outdir = tk.StringVar(value=output_paths.destination_hint(TOOL_KEY))
        output_paths.register_destination_hint(TOOL_KEY, self.var_outdir)

        self._build(theme)
        # Registered only once every widget it recolors exists; ``close``
        # removes it, so a closed panel is never reached by a later toggle.
        appearance.register_listener(self._on_appearance_changed)

        # Run locking is the shared contract: the adapter's lock group applies
        # the approved matrix to these seams whenever the run's state moves.
        self._tracks_lock = self._ButtonLock(
            self.btn_add_files, self.btn_move_up, self.btn_move_down,
            self.btn_remove_tracks)
        self._import_lock = self._ButtonLock(self.btn_import_folder, self.btn_clear_imports)
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
        self._pump.add_drain(self._drain_preparation)

        self.render()
        self._pump.start()

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #

    def _style(self, key: str) -> str:
        """The shared compact style for *key* (native control inheritance on Aqua)."""
        return style_name(self.appearance_bundle, key)

    def _action_style(self, action: str) -> str:
        """The outlined role style for a stable button action (v0.8.1)."""
        return action_style(self.appearance_bundle, action)

    def _build(self, theme) -> None:
        """Compose the four sections from the live widgets.

        v0.6.6 Phase 7: the dense Family-B hierarchy on the approved compact
        control language. Every control, variable and callback is the one the
        panel already had, re-homed into its numbered section and styled from
        the appearance bundle; ``theme`` supplies only the composition hints.
        """
        hints = _layout_hints(theme)
        self._hints = hints
        bundle = self.appearance_bundle
        st = self._style
        pad, gap = hints["pad"], hints["gap"]
        self._tight = False
        self._density_needs: dict | None = None
        self.columnconfigure(0, weight=1)
        # The two fixed sections keep their requested height; the two variable
        # ones -- Tracks, Chapters & Build, whose track list and Chapter Titles
        # scroll, and Activity, whose log scrolls -- absorb a short window.
        # Nothing else yields, so no required control falls off the bottom and
        # no whole-panel scrollbar is needed.
        self.rowconfigure(0, weight=0)   # 1. Import & Books
        self.rowconfigure(1, weight=0)   # 2. Book Settings
        self.rowconfigure(2, weight=3)   # 3. Tracks, Chapters & Build -- lists scroll
        self.rowconfigure(3, weight=2)   # Activity -- the log scrolls

        self.import_section, self.settings_section, self.run_section, self.activity = (
            ttk.LabelFrame(self, text=title, padding=SECTION_PADDING,
                           style=st("labelframe"))
            for title in SECTION_TITLES)
        self.sections = (self.import_section, self.settings_section,
                         self.run_section, self.activity)
        for row, section in enumerate(self.sections):
            section.grid(row=row, column=0, sticky="nsew", padx=pad,
                         pady=(pad if row == 0 else 0,
                               pad if row == len(self.sections) - 1 else gap))

        # -- 1. Import & Books: workspace import, then the navigator ----------- #
        imp = self.import_section
        imp.columnconfigure(0, weight=1)
        top = ttk.Frame(imp, style=st("surface"))
        top.grid(row=0, column=0, sticky="ew")
        self.import_band = top
        self.btn_import_folder = ttk.Button(
            top, text="Import Folder", style=self._action_style("import_folder"),
            command=self.import_folder)
        self.btn_import_folder.grid(row=0, column=0, sticky="w")
        # The destructive workspace reset lives with the import controls it
        # undoes, in the shared destructive treatment (Phase 12 amendment).
        self.btn_clear_imports = ttk.Button(
            top, text=CLEAR_IMPORTS_LABEL, style=self._action_style("clear_imports"),
            command=self.clear_all_imports)
        self.btn_clear_imports.grid(row=0, column=1, sticky="w", padx=(4, 0))
        self.import_status = job_ui.ImportStatusBar(
            top, theme=bundle, on_cancel=self.cancel_import)
        self._outdir_trace = None
        if hints["import_band_layout"] == "compact":
            # The status bar keeps its natural width — it is the only place
            # a running scan and its Cancel appear — and the output hint is
            # the one thing that yields. ttk clips an overlong label from the
            # right whatever its anchor, which would cut off the run folder --
            # the part that says where the run lands -- so the label asks for
            # almost no width, takes whatever the band has left, and shows the
            # path's tail behind an ellipsis when the whole will not fit
            # (``_fit_output_hint``). The full path stays in ``var_outdir``.
            self.output_label = ttk.Label(top, width=1, anchor="e",
                                          style=st("secondary_label"))
            top.columnconfigure(3, weight=1)
            self.import_status.frame.grid(row=0, column=2, sticky="w", padx=(10, 10))
            self.output_label.grid(row=0, column=3, sticky="ew")
            self.output_label.bind("<Configure>", self._fit_output_hint, add="+")
            self._outdir_trace = self.var_outdir.trace_add(
                "write", lambda *_a: self._fit_output_hint())
            self._fit_output_hint()
        else:
            self.output_label = ttk.Label(
                top, textvariable=self.var_outdir, anchor="e",
                style=st("secondary_label"))
            top.columnconfigure(2, weight=1)
            self.import_status.frame.grid(row=0, column=2, sticky="ew", padx=(10, 10))
            self.output_label.grid(row=0, column=3, sticky="e")

        self.navigator = BookNavigator(
            imp, theme=bundle, layout=hints["navigator_layout"],
            fit_heading=hints["navigator_heading"] == "fit",
            describe=self._describe, label_for=self._label_for,
            on_previous=self.on_previous, on_next=self.on_next,
            on_add=self.on_add, on_duplicate=self.on_duplicate,
            on_remove=self.on_remove, on_select=self.on_select)
        self.navigator.frame.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        # The selector's drop-down list is a classic Tk listbox no ttk style
        # reaches; without this a Dark combobox would open a white list.
        appearance.style_combobox_popdown(self.navigator.selector, bundle)

        # -- 2. Book Settings: Shared above Current Book ------------------------ #
        settings_section = self.settings_section
        settings_section.columnconfigure(0, weight=1)
        text_fields = tuple(
            (key, wf.FIELD_LABELS[key]) for key in wf.SHARED_FIELDS if key != "artwork")
        # Shared is the tinted group -- the shared palette's restrained blue
        # surface, stronger border and heading, in Light and Dark alike -- and
        # Current Book the ordinary section surface with the quieter border.
        # Both treatments are the shared surface's own ``shared_labelframe`` /
        # ``labelframe`` styles; nothing here picks a color.
        self.surface = SharedMetadataSurface(
            settings_section, text_fields, theme=bundle, layout="rows",
            show_header=False, entry_width=hints["entry_width"],
            field_gap=hints["field_gap"],
            wraplength=_label_wraps(hints, (key for key, _label in text_fields)),
            shared_title=SHARED_TITLE,
            book_title="Current Book",
            on_shared_change=self.on_shared_change,
            on_book_change=self.on_book_change)
        self.surface.frame.grid(row=0, column=0, sticky="ew")
        field_columns = self.surface.field_columns
        field_rows = 2 * self.surface.field_lines
        # Widget padding, not a style: two stacked groups at the section's own
        # padding would spend the height the track list needs at the supported
        # minimum. The style (and its colours) is unchanged.
        for group in (self.surface.shared_frame, self.surface.book_frame):
            group.configure(padding=(hints["group_pad"], 2))

        # "wide" (the compact default, and aqua's): the artwork spans the
        # field rows only and the Book-only row runs the full width beneath,
        # its Title stretching. "beside": the artwork column runs the height
        # of the Book group and the Book-only row sits beside it.
        wide = hints["book_fields_span"] == "wide"
        natural = hints["artwork_buttons"] == "natural"
        # The preview is no taller than the control's caption and buttons, so
        # choosing artwork never makes Book Settings grow (no layout jump).
        self.shared_artwork = ArtworkControl(
            self.surface.shared_frame, caption=wf.FIELD_LABELS["artwork"],
            theme=bundle, shared=True, natural_buttons=natural,
            preview_max=m4b_artwork_ui.COMPACT_PREVIEW_MAX,
            on_choose=self.choose_shared_artwork, on_clear=self.clear_shared_artwork)
        self.shared_artwork.frame.grid(row=0, column=field_columns, rowspan=field_rows,
                                       sticky="nw", padx=(hints["artwork_gap"], 0))
        self.book_artwork = ArtworkControl(
            self.surface.book_frame, caption=wf.FIELD_LABELS["artwork"],
            theme=bundle, shared=False, natural_buttons=natural,
            preview_max=m4b_artwork_ui.COMPACT_PREVIEW_MAX,
            on_choose=self.choose_book_artwork, on_clear=self.clear_book_artwork)
        self.book_artwork.frame.grid(row=0, column=field_columns,
                                     rowspan=field_rows + (0 if wide else 2),
                                     sticky="nw", padx=(hints["artwork_gap"], 0))

        # The Book-only text fields, on one row of the Book group: Title,
        # Series Part, Output Filename, then the Book's status. Stored raw
        # through the model.
        own = ttk.Frame(self.surface.book_frame, style=st("surface"))
        own.grid(row=field_rows, column=0, columnspan=field_columns + (1 if wide else 0),
                 sticky="ew", pady=(4, 0))
        self.book_own = own
        self.book_vars: dict[str, tk.StringVar] = {}
        self.book_entries: dict[str, ttk.Entry] = {}
        self._book_traces: dict[str, str] = {}
        widths = {"title": 20, "series_part": 5, "output_filename": 16}
        if wide:
            widths["title"] = 12
            own.columnconfigure(1, weight=1)
        for column, key in enumerate(self.BOOK_TEXT_FIELDS):
            ttk.Label(own, text=f"{wf.FIELD_LABELS[key]}:", style=st("label")).grid(
                row=0, column=2 * column, sticky="w", padx=((0 if column == 0 else 12), 4))
            variable = tk.StringVar(master=self, value="")
            entry = ttk.Entry(own, textvariable=variable, width=widths[key],
                              style=st("entry"))
            entry.grid(row=0, column=2 * column + 1,
                       sticky="ew" if wide and key == "title" else "w")
            self.book_vars[key] = variable
            self.book_entries[key] = entry
            self._book_traces[key] = variable.trace_add(
                "write", lambda *_a, bound=key: self._on_own_field(bound))
        ttk.Label(own, text="Status:", style=st("label")).grid(
            row=0, column=6, sticky="w", padx=(12, 4))
        # On the Book group's surface, like every other label in it.
        self.status_label = ttk.Label(own, text=STATUS_READY, style=st("label"))
        self.status_label.grid(row=0, column=7, sticky="w")

        # -- 3. Tracks, Chapters & Build ---------------------------------------- #
        run = self.run_section
        run.columnconfigure(0, weight=1)
        run.rowconfigure(0, weight=1)
        middle = ttk.Frame(run, style=st("surface"))
        middle.grid(row=0, column=0, sticky="nsew")
        middle.columnconfigure(0, weight=3)
        middle.columnconfigure(1, weight=2)
        middle.rowconfigure(1, weight=1)
        self.tracks_caption = ttk.Label(
            middle, text="MP3 Tracks (this Book) — one chapter each", style=st("label"))
        self.tracks_caption.grid(row=0, column=0, sticky="w", pady=(0, 2))
        self.chapters_caption = ttk.Label(
            middle, text="Chapter Titles — one title per line", style=st("label"))
        self.chapters_caption.grid(row=0, column=1, sticky="w", padx=(10, 0), pady=(0, 2))

        tracks = ttk.Frame(middle, style=st("surface"))
        tracks.grid(row=1, column=0, sticky="nsew")
        tracks.columnconfigure(0, weight=1)
        tracks.rowconfigure(0, weight=1)
        self.track_list = tk.Listbox(tracks, selectmode="extended",
                                     exportselection=False, height=TRACK_ROWS,
                                     width=24, activestyle="none")
        track_scroll = ttk.Scrollbar(tracks, orient="vertical",
                                     command=self.track_list.yview,
                                     style=st("vscrollbar"))
        self.track_list.configure(yscrollcommand=track_scroll.set)
        self.track_list.grid(row=0, column=0, sticky="nsew")
        track_scroll.grid(row=0, column=1, sticky="ns")
        job_ui.style_tk_widget(self.track_list, bundle, "list")
        # The frozen ordered-list keyboard contract (§4) -- the same primitive
        # the shared ImportedFileList binds on its own listbox. Bound on this
        # listbox only, so a focused Entry or the Chapter Titles box keeps its
        # own text-editing keys; and each key goes through the same run lock
        # the buttons do, so a shortcut cannot edit what a run has locked.
        job_ui.bind_list_shortcuts(
            self.track_list,
            on_move_up=lambda: self._track_key(self.move_up),
            on_move_down=lambda: self._track_key(self.move_down),
            on_remove=lambda: self._track_key(self.remove_selected_tracks))
        ui_theme.enable_mousewheel(self.track_list)

        track_buttons = ttk.Frame(middle, style=st("surface"))
        track_buttons.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        self.track_buttons = track_buttons
        self.btn_add_files = ttk.Button(track_buttons, text="Add Files",
                                        style=self._action_style("add_files"),
                                        command=self.add_files)
        self.btn_move_up = ttk.Button(track_buttons, text="Move Up",
                                      style=self._action_style("move_up"),
                                      command=self.move_up)
        self.btn_move_down = ttk.Button(track_buttons, text="Move Down",
                                        style=self._action_style("move_down"),
                                        command=self.move_down)
        self.btn_remove_tracks = ttk.Button(track_buttons, text="Remove Selected",
                                            style=self._action_style("remove_selected"),
                                            command=self.remove_selected_tracks)
        for column, button in enumerate((self.btn_add_files, self.btn_move_up,
                                         self.btn_move_down, self.btn_remove_tracks)):
            button.grid(row=0, column=column, padx=(0 if column == 0 else 4, 0))

        chapters = ttk.Frame(middle, style=st("surface"))
        # Spans the track buttons' row too: the editor is the taller region.
        chapters.grid(row=1, column=1, rowspan=2, sticky="nsew", padx=(10, 0))
        chapters.columnconfigure(0, weight=1)
        chapters.rowconfigure(0, weight=1)
        self.chapter_text = tk.Text(chapters, height=TRACK_ROWS, width=24,
                                    wrap="none", undo=True)
        chapter_scroll = ttk.Scrollbar(chapters, orient="vertical",
                                       command=self.chapter_text.yview,
                                       style=st("vscrollbar"))
        self.chapter_text.configure(yscrollcommand=chapter_scroll.set)
        self.chapter_text.grid(row=0, column=0, sticky="nsew")
        chapter_scroll.grid(row=0, column=1, sticky="ns")
        job_ui.style_tk_widget(self.chapter_text, bundle, "text")
        ui_theme.enable_mousewheel(self.chapter_text)
        self.chapter_text.bind("<KeyRelease>", self.on_chapter_edit)
        # v0.8.2 Checkpoint 2 (the MP3 Tool's R1-1): a paste, a drop or an input method changes the box without a key
        # release. Tk's modified flag reports every change, so the model hears of it on the next event-loop turn;
        # until then :meth:`flush_pending_editor_state` keeps it (every callback that can redraw the box calls it).
        self.chapter_text.bind("<<Modified>>", self._on_chapter_modified)
        self._suspend_chapters = False
        #: What the box showed when the panel last wrote it, and the Book it showed it for. A difference between the
        #: box and the baseline is an edit the model has not heard of yet; it belongs to that Book and no other.
        self._chapter_baseline = ""
        self._chapter_book_id: str | None = None

        self.run_separator = ttk.Separator(run, orient=tk.HORIZONTAL,
                                           style=st("separator"))
        self.run_separator.grid(row=1, column=0, sticky="ew", pady=(6, 5))

        # The run options: series numbering, FAST, the custom destination.
        options = ttk.Frame(run, style=st("surface"))
        options.grid(row=2, column=0, sticky="ew")
        options.columnconfigure(5, weight=1)
        self.run_options = options
        self.var_auto_number = tk.BooleanVar(master=self, value=False)
        self.check_auto_number = ttk.Checkbutton(
            options, text="Auto-number Series Part", variable=self.var_auto_number,
            style=st("checkbutton"), command=self.on_auto_number)
        self.check_auto_number.grid(row=0, column=0, sticky="w")
        self.label_start_part = ttk.Label(options, text=START_PART_LABEL,
                                          style=st("label"))
        self.label_start_part.grid(row=0, column=1, sticky="w", padx=(8, 4))
        self.var_start_part = tk.StringVar(master=self, value="")
        self.entry_start_part = ttk.Entry(
            options, textvariable=self.var_start_part, width=4, style=st("entry"))
        self.entry_start_part.grid(row=0, column=2, sticky="w")
        self.var_fast_first = tk.BooleanVar(master=self, value=True)
        self.check_fast_first = ttk.Checkbutton(
            options, text=FAST_LABEL,
            variable=self.var_fast_first, style=st("checkbutton"))
        self.check_fast_first.grid(row=0, column=3, sticky="w", padx=(8, 0))
        # The explicit custom destination (Decision 10A): off on every fresh
        # build, its path row hidden until the toggle is on, never persisted.
        self.var_custom_dest = tk.BooleanVar(master=self, value=False)
        self.chk_custom_dest = ttk.Checkbutton(
            options, text=CUSTOM_DEST_LABEL, variable=self.var_custom_dest,
            style=st("checkbutton"), command=self._on_custom_dest_change)
        if hints["options_layout"] == "stacked":
            # Five controls on one line ask for more than the aqua host has;
            # the destination toggle takes its own line, its path row beneath.
            self.chk_custom_dest.grid(row=1, column=0, columnspan=5, sticky="w", pady=(4, 0))
            self._customrow_at = 2
        else:
            self.chk_custom_dest.grid(row=0, column=4, sticky="w", padx=(8, 0))
            self._customrow_at = 1
        self.customrow = ttk.Frame(options, style=st("surface"))
        self.customrow.columnconfigure(0, weight=1)
        self.var_custom_path = tk.StringVar(master=self, value="")
        # A short request that stretches: the row gives the path whatever
        # width is left, beneath the options or, in the tight density, beside
        # them.
        self.entry_custom = ttk.Entry(self.customrow, textvariable=self.var_custom_path,
                                      width=12, style=st("entry"))
        self.entry_custom.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.btn_browse_custom = ttk.Button(
            self.customrow, text="Browse…", style=self._action_style("browse"),
            command=self.choose_custom_dest)
        self.btn_browse_custom.grid(row=0, column=1, sticky="e")

        # Build, then the shared job area beside it: one adapter per run,
        # installed into column 2 by ``_install_jobs``. Build is the tool's one
        # primary action, so it takes the compact button with ttk's restrained
        # accent outline -- the treatment TTS's Start, Cover's Resize, the
        # Converter's Convert and the MP3 Tool's operations get.
        self.actions = ttk.Frame(run, style=st("surface"))
        self.actions.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        self.actions.columnconfigure(2, weight=1)
        self.btn_build = ttk.Button(
            self.actions, text="Build M4B(s)", default="active",
            style=self._action_style("run"), command=self.build)
        self.btn_build.grid(row=0, column=0, padx=(0, 12),
                            sticky="nw" if hints["actions_layout"] == "row" else "new")
        self._jobs_rowspan = 1

        # -- Activity: the one Summary | Detailed log, below -------------------- #
        # The universal Activity presentation (frozen contract §3): the note and
        # Clear Log above the shared Summary | Detailed view. Built once and
        # handed to every run's adapter, so the history of one run is still
        # there when the next one starts.
        act = self.activity
        act.columnconfigure(0, weight=1)
        act.rowconfigure(1, weight=1)
        bar = ttk.Frame(act, style=st("surface"))
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        bar.columnconfigure(0, weight=1)
        self.activity_bar = bar
        self.activity_note = ttk.Label(
            bar, text="Summary: progress and results.  Detailed: every step.",
            style=st("secondary_label"), justify=tk.LEFT)
        self.activity_note.grid(row=0, column=0, sticky="w")
        # Not a processing option, so it never locks: clearing the visible log
        # never interferes with a run in flight.
        self.btn_clear_log = ttk.Button(bar, text="Clear Log",
                                        style=self._action_style("clear_log"),
                                        command=self.clear_log)
        self.btn_clear_log.grid(row=0, column=1, sticky="e", padx=(8, 0))
        self.log = job_ui.SummaryDetailsView(act, theme=bundle, height=LOG_HEIGHT,
                                             details_label="Detailed", limit=LOG_LIMIT)
        self.log.frame.grid(row=1, column=0, sticky="nsew")

        self._on_custom_dest_change()
        self.bind("<Configure>", self._on_panel_configure, add="+")

    def _install_jobs(self, run_id: str, item_ids) -> None:
        """Point the shared job area at one run. Main thread only.

        A run owns its event stream, so a new attempt gets a new adapter in the
        same place; the retired one is closed first so the one pump keeps
        exactly one job drain. The log view is the panel's one region, handed
        in, and keeps every earlier attempt's lines.
        """
        # v0.8.2 Checkpoint 2 -- transactional, in three steps (the MP3 Tool's R1-2, applied here):
        #
        # 1. BUILD. The new adapter is constructed, dressed, registered and laid out completely while the previous
        #    one is still the live job area and has not been touched. If anything here raises, the half-built
        #    adapter is taken down and the exception goes to the caller with the previous job area -- stream,
        #    result, locks, Retry Failed -- exactly as it was, and still live.
        # 2. SWAP. Plain attribute assignments, which cannot fail: from here the new adapter is the job area.
        # 3. RETIRE. The previous adapter no longer owns anything, so closing it and taking its frame down is
        #    cleanup (``_retire_adapter``): a Tk error there is reported and the frame is taken out of the layout;
        #    it can neither undo the swap nor stop the run the new adapter belongs to.
        previous = getattr(self, "jobs", None)
        bundle = self.appearance_bundle
        event_q: queue.Queue = queue.Queue()
        estimator = job_control.EtaEstimator(run_id, clock=self._clock)
        adapter = None
        try:
            adapter = job_ui.JobAdapter(
                self.actions,
                run_id=run_id,
                pump=self._pump,
                # The shared compact bundle, exactly as Cover's, TTS's, the
                # Converter's and the MP3 Tool's job areas use it.
                theme=bundle,
                pull=job_ui.queue_pull(event_q),
                estimator=estimator,
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
            # Laid out in the previous adapter's cell, above it (a newer sibling stacks higher), before the swap.
            adapter.frame.grid(row=0, column=2, rowspan=self._jobs_rowspan, sticky="ew")
            adapter.controls.frame.grid_configure(sticky="e")
            # Per-instance restyling, exactly as Cover, TTS, the Converter and the
            # MP3 Tool do it: the shared indicator stays generic for every panel
            # that has not adopted the compact system, but here an unstyled native
            # frame would be a light island in Dark. Aqua names inherit native controls.
            status = adapter.status
            status.indicator.frame.configure(style=style_name(bundle, "card"))
            status.indicator.bar.configure(style=style_name(bundle, "progressbar"),
                                           length=PROGRESS_BAR_LENGTH)
            status.indicator.label.configure(style=style_name(bundle, "secondary_label"))
            status.label_status.configure(style=style_name(bundle, "secondary_label"))
            self._arrange_status(adapter)
            adapter.register_inputs(self.navigator, self._tracks_lock, self._import_lock)
            adapter.register_options(self.surface, self.shared_artwork, self.book_artwork,
                                     self._options_lock, self._series_part_lock,
                                     self._chapters_lock)
        except BaseException:
            if adapter is not None:
                self._retire_adapter(adapter)  # the build error is the one the caller must see
            raise
        # -- 2. SWAP: the panel's own names for the shared pieces, re-pointed per run. Assignments only. ------- #
        self._event_q = event_q
        self._estimator = estimator
        self.jobs = adapter
        self.controls = adapter.controls
        self.status = adapter.status
        self.lock_group = adapter.locks
        # -- 3. RETIRE the previous adapter: cleanup of something the panel no longer owns. --------------------- #
        if previous is not None:
            for problem in self._retire_adapter(previous):
                logging_setup.get_logger().warning("M4B Maker: the previous job area was not fully retired: %s",
                                                   problem)
                self._say("The previous job area could not be fully removed; it was taken out of the layout.",
                          f"Previous job area not fully retired: {problem}")
        self.jobs.render()

    def _retire_adapter(self, adapter) -> tuple[str, ...]:
        """Close an adapter the panel does not (or no longer) own and take its frame down. Main thread; never raises.

        Cleanup, never a decision: whatever this meets, the caller's job area and run stay as they are. Each step is
        tried on its own -- ``close`` drops the adapter's pump drain first (one pump, one job drain), then the frame
        is destroyed; a frame Tk will not destroy is taken out of the layout, failing that lowered, and its
        indeterminate bar stopped. Returns one line per step that failed, for the caller to report once.
        """
        problems: list[str] = []
        try:
            adapter.close()
        except Exception as exc:  # noqa: BLE001 - reported by the caller; the frame must still go
            problems.append(f"close: {type(exc).__name__}: {exc}")
            try:
                self._pump.remove_drain(adapter.drain)
            except Exception:  # noqa: BLE001
                pass
        try:
            adapter.frame.destroy()
        except Exception as exc:  # noqa: BLE001 - reported by the caller
            problems.append(f"destroy: {type(exc).__name__}: {exc}")
            for fallback in (adapter.frame.grid_forget, adapter.frame.lower):
                try:
                    fallback()
                    break
                except Exception:  # noqa: BLE001 - try the next way of getting it out of sight
                    continue
            try:
                adapter.status.indicator.bar.stop()
            except Exception:  # noqa: BLE001
                pass
        return tuple(problems)

    def _fit_output_hint(self, _event=None) -> None:
        """Show as much of the output path as the band holds, tail first.

        Presentation only: ``var_outdir`` keeps the whole path, and the
        shared destination registry still writes it there.
        """
        if self._closed or self._outdir_trace is None:
            return
        label = self.output_label
        full = str(self.var_outdir.get())
        try:
            described = ttk.Style(label).lookup(
                str(label.cget("style")) or "TLabel", "font")
            font = tkfont.Font(font=described or "TkDefaultFont")
            # The label's own padding is not room for text (the last glyph was cut).
            width = ui_theme.text_room(label, font.measure)
        except tk.TclError:
            return
        text = full
        if width > 1 and font.measure(full) > width:
            tail = full
            while tail and font.measure("…" + tail) > width:
                tail = tail[1:]
            text = "…" + tail if tail else ""
        try:
            label.configure(text=text)
        except tk.TclError:
            pass

    @property
    def output_hint_text(self) -> str:
        """What the output hint currently shows."""
        if self._outdir_trace is None:
            return str(self.var_outdir.get())
        return str(self.output_label.cget("text"))

    # -- appearance: the shared compact control language -------------------- #

    def _on_appearance_changed(self, bundle: dict) -> None:
        """Re-color the few classic Tk widgets a ttk style mutation cannot reach.

        Every ttk widget here names a ``Compact.*`` style, and
        ``shared.appearance`` reconfigured those in place before calling this,
        so they have already repainted. What is left is classic Tk: the track
        list, the Chapter Titles box, the Activity log's two panes and the Book
        selector's drop-down list. Nothing is rebuilt, so no Book, selection,
        value, chapter title, track order, run option, log line, progress or
        running job moves.
        """
        self.appearance_bundle = bundle
        if self._closed:
            return
        job_ui.style_tk_widget(self.track_list, bundle, "list")
        job_ui.style_tk_widget(self.chapter_text, bundle, "text")
        self.log.apply_appearance(bundle)
        appearance.style_combobox_popdown(self.navigator.selector, bundle)

    # -- density: the frozen contract's tight-window steps ----------------- #

    def _linespace(self, widget) -> int:
        try:
            return max(1, int(tkfont.Font(font=widget.cget("font")).metrics("linespace")))
        except (tk.TclError, ValueError):
            return 1

    def _gives(self) -> tuple[int, int]:
        """Pixels the two flexible regions may give up above their floors.

        The track list and Chapter Titles box give up to the density's track
        floor, the log to the density's log floor. From the live fonts, so the
        numbers follow the platform's real metrics and scaling.
        """
        floor_rows = TIGHT_TRACK_FLOOR_ROWS if self._tight else TRACK_FLOOR_ROWS
        row = max(self._linespace(self.track_list), self._linespace(self.chapter_text))
        tracks = row * (TRACK_ROWS - floor_rows)
        log_floor = TIGHT_LOG_FLOOR_LINES if self._tight else LOG_FLOOR_LINES
        log = self._linespace(self.log.summary_text) * (LOG_HEIGHT - log_floor)
        return tracks, log

    def _measure_density(self) -> dict:
        """What the regular density needs, from the live widgets.

        ``floor`` is the panel height at which the regular padding still leaves
        the track list, the Chapter Titles box and the log at or above their
        floors. Below it the tight density applies.
        """
        self.update_idletasks()
        tracks, log = self._gives()
        return {"floor": self.winfo_reqheight() - tracks - log}

    def _set_row_floors(self) -> None:
        """Hold Tracks, Chapters & Build and Activity at their measured floors.

        A short window takes its height from these two rows only (the other two
        have no weight); the minimum sizes stop either from being squeezed below
        the height its options, Build, job area and chrome need plus the floor
        rows of its list or log, so no control inside is ever clipped.
        """
        self.update_idletasks()
        tracks, log = self._gives()
        self.rowconfigure(2, minsize=max(0, self.run_section.winfo_reqheight() - tracks))
        self.rowconfigure(3, minsize=max(0, self.activity.winfo_reqheight() - log))

    def _apply_density(self, tight: bool) -> None:
        """Regular or tight. Positions, padding and chrome only -- the same
        widgets, variables and commands, and nothing of the workspace.

        Tight is the frozen contract's §1 order: less padding and chrome first
        (section padding, gaps, the run separator, Activity's explanatory
        note), then a reflow (Clear Log beside the Summary | Detailed view
        rather than above it; the job status beside the job controls; the
        run options in their short wording, with the custom destination's path
        row on their line), and only then the flexible regions' lower floor.
        Nothing is hidden that can be used.
        """
        self._tight = bool(tight)
        hints = self._hints
        pad = TIGHT_OUTER_PAD if tight else hints["pad"]
        gap = TIGHT_SECTION_GAP if tight else hints["gap"]
        padding = TIGHT_SECTION_PADDING if tight else SECTION_PADDING
        last = len(self.sections) - 1
        for row, section in enumerate(self.sections):
            section.configure(padding=padding)
            section.grid_configure(padx=pad, pady=(pad if row == 0 else 0,
                                                   pad if row == last else gap))
        small = 2 if tight else 4
        self.navigator.frame.grid_configure(pady=(small, 0))
        # The shared surface's own gap between its Shared and Current Book
        # groups, and the groups' own padding.
        self.surface.book_frame.grid_configure(pady=(2 if tight else 8, 0))
        for group in (self.surface.shared_frame, self.surface.book_frame):
            group.configure(padding=(4, 0, 4, 1) if tight else (hints["group_pad"], 2))
        self.book_own.grid_configure(pady=(small, 0))
        for caption in (self.tracks_caption, self.chapters_caption):
            caption.grid_configure(pady=(0, 0 if tight else 2))
        self.track_buttons.grid_configure(pady=(small, 0))
        if tight:
            self.run_separator.grid_remove()
            self.run_options.grid_configure(pady=0)
            self.actions.grid_configure(pady=(small, 0))
            # Clear Log beside the log view, level with its tabs.
            self.activity_note.grid_remove()
            self.log.frame.grid_configure(row=0, column=0, rowspan=2)
            self.activity_bar.grid_configure(row=0, column=1, sticky="ne",
                                             padx=(6, 0), pady=0)
        else:
            self.run_separator.grid()
            self.run_options.grid_configure(pady=0)
            self.actions.grid_configure(pady=(6, 0))
            self.activity_note.grid()
            self.log.frame.grid_configure(row=1, column=0, rowspan=1)
            self.activity_bar.grid_configure(row=0, column=0, sticky="ew",
                                             padx=0, pady=(0, 4))
        self.label_start_part.configure(
            text=START_PART_LABEL_SHORT if tight else START_PART_LABEL)
        self.check_fast_first.configure(text=FAST_LABEL_SHORT if tight else FAST_LABEL)
        self._place_customrow()
        self._arrange_status()
        self._set_row_floors()

    def _arrange_status(self, jobs=None) -> None:
        """The shared job area's arrangement: controls over three status
        lines, or, in the tight density, the status view's two lines beside
        the controls.

        Grid positions, bar length and wrap only -- the same widgets, bound to
        the same variables the shared view writes. Regular is the adapter's own
        layout: the controls, then progress, stage and ETA, then the status
        line. Tight is a §1 reflow: the status beside a shorter progress bar
        and the stage beside the ETA, the whole view beside the controls, so
        the area beside Build is one control row tall rather than three lines
        taller (the Maker has one more run row than the MP3 Tool: its options).

        *jobs* (v0.8.2) is an adapter being built that is not the panel's yet;
        with none given, the installed one.
        """
        if jobs is None:
            jobs = getattr(self, "jobs", None)
        if jobs is None:
            return
        view = jobs.status
        if self._tight:
            jobs.controls.frame.grid_configure(row=0, column=0, sticky="nw")
            view.frame.grid_configure(row=0, column=1, sticky="new", padx=(8, 0), pady=0)
            jobs.frame.columnconfigure(0, weight=0)
            jobs.frame.columnconfigure(1, weight=1)
            view.indicator.bar.configure(length=TIGHT_PROGRESS_BAR_LENGTH)
            view.indicator.frame.grid_configure(row=0, column=0, columnspan=1, sticky="w")
            fit = self._hints["status_line"] == "fit"
            view.label_status.grid_configure(row=0, column=1, columnspan=2,
                                             sticky="ew" if fit else "w", padx=(8, 0))
            view.label_stage.grid_configure(row=1, column=0, columnspan=2, sticky="w")
            view.label_eta.grid_configure(row=1, column=2, columnspan=1, sticky="e")
            view.frame.columnconfigure(0, weight=0)
            view.frame.columnconfigure(1, weight=1)
            if fit:
                view.fit_status(True)
            else:
                view.label_status.configure(wraplength=TIGHT_STATUS_WRAP)
        else:
            view.fit_status(False)
            jobs.controls.frame.grid_configure(row=0, column=0, sticky="e")
            view.frame.grid_configure(row=1, column=0, sticky="ew", padx=0, pady=(4, 0))
            jobs.frame.columnconfigure(0, weight=1)
            jobs.frame.columnconfigure(1, weight=0)
            view.indicator.bar.configure(length=PROGRESS_BAR_LENGTH)
            view.indicator.frame.grid_configure(row=0, column=0, columnspan=2, sticky="ew")
            view.label_stage.grid_configure(row=1, column=0, columnspan=1, sticky="w")
            view.label_eta.grid_configure(row=1, column=1, columnspan=1, sticky="e")
            view.label_status.grid_configure(row=2, column=0, columnspan=2, sticky="w",
                                             padx=0)
            view.frame.columnconfigure(0, weight=1)
            view.frame.columnconfigure(1, weight=0)
            view.label_status.configure(wraplength=0)

    @property
    def density(self) -> str:
        """``"regular"`` or ``"tight"``: the padding currently applied."""
        return "tight" if self._tight else "regular"

    def _on_panel_configure(self, event=None) -> None:
        """Choose the density for the panel's real height. Main thread only."""
        if self._closed or (event is not None and event.widget is not self):
            return
        if self._density_needs is None:
            if self._tight:
                self._apply_density(False)
            self._density_needs = self._measure_density()
            self._set_row_floors()
        height = self.winfo_height()
        if height <= 1:
            return
        tight = height < self._density_needs["floor"]
        if tight != self._tight:
            self._apply_density(tight)

    def _track_key(self, action) -> None:
        """A §4 shortcut on the track list, refused while a run locks the
        track controls -- the same lock the four buttons are under."""
        lock = getattr(self, "_tracks_lock", None)
        if self._closed or (lock is not None and lock.locked):
            return
        action()

    class _ButtonLock:
        """Registers a set of this panel's own widgets with the shared group."""

        def __init__(self, *widgets) -> None:
            self.widgets = widgets
            self.locked = False

        def set_locked(self, locked: bool) -> None:
            self.locked = bool(locked)
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
            filetypes=[("MP3 audio", "*.mp3"), ("All files", "*.*")]) or ())
        # Remembered only once the import commits (_settle_import_dir).
        self._pending_input_dir = settings.selected_dir(chosen, is_file=True)
        return chosen

    def _ask_folder(self):
        chosen = filedialog.askdirectory(
            parent=self, title="Select a folder of MP3 audiobooks",
            initialdir=str(_remembered_dir(KEY_INPUT_DIR)), mustexist=True)
        self._pending_input_dir = settings.selected_dir(chosen, is_file=False)
        if not chosen:
            return ()
        return (str(chosen),)

    def _settle_import_dir(self, outcome: ImportOutcome) -> None:
        """Remember the import dialog's folder once its selection committed; forget it otherwise."""
        accepted = job_ui.import_choice_accepted(outcome)
        if accepted is None:
            return
        folder, self._pending_input_dir = self._pending_input_dir, None
        if accepted and folder:
            settings.set(KEY_INPUT_DIR, folder)

    def _ask_artwork(self) -> str:
        return m4b_artwork_ui.ask_artwork(
            self, initialdir=_remembered_dir(KEY_COVER_DIR), title="Select Book Artwork")

    def _remember_cover_dir(self, chosen: str) -> None:
        """Shared and Book artwork share this tool's one artwork history, written only for accepted artwork."""
        folder = settings.selected_dir(chosen, is_file=True)
        if folder:
            settings.set(KEY_COVER_DIR, folder)

    def _ask_destination(self) -> str:
        chosen = filedialog.askdirectory(parent=self, title="Choose the destination folder",
                                         initialdir=str(_remembered_dir(KEY_DEST_DIR)),
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
        # v0.8.2 Checkpoint 6: a set, not the list: this runs on every render, and ``in`` a list of 5,000 Books made
        # it quadratic (about 0.1 s a keystroke in the Metadata Editor at 5,000 Books).
        present = set(ids)
        self.book_numbers = {book_id: number for book_id, number in self.book_numbers.items()
                             if book_id in present}

    def render(self) -> None:
        """Show the current workspace. Every value comes from the snapshot."""
        self._guard.require("render")
        if self._closed:
            return
        # v0.8.2: whatever moved the model, the box is about to be redrawn from it; an edit it has not heard of yet
        # is committed to the Book it was typed for first, never painted over.
        self.flush_pending_editor_state()
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
        # v0.8.2 Checkpoint 6: a render that changed nothing about this Book's tracks (a Shared keystroke, numbering)
        # leaves the list, and the rows the user selected, as they are. The snapshot is immutable, so the same object
        # means the same rows; refilling 5,000 rows cost about 45 ms of Tk work per keystroke.
        shown = getattr(self, "_tracks_shown", None)
        if not selection and shown is not None and shown[0] == book.book_id and shown[1] is book.files:
            return
        self.track_list.delete(0, "end")
        names = [entry.name for entry in book.files.files]
        if names:
            self.track_list.insert("end", *names)  # one Tk call for every row instead of one per track
        self._tracks_shown = (book.book_id, book.files)
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
        # Never paints over an edit the model has not heard of: it is committed to its own Book first (v0.8.2).
        self.flush_pending_editor_state()
        raw = self._chapter_display()
        self._chapter_baseline = raw
        self._chapter_book_id = self.workspace.current.book_id
        if raw == self.chapter_text.get("1.0", "end-1c"):
            return
        self._suspend_chapters = True
        try:
            state = str(self.chapter_text.cget("state"))
            self.chapter_text.configure(state="normal")
            self.chapter_text.delete("1.0", "end")
            if raw:
                self.chapter_text.insert("1.0", raw)
            # v0.8.2: the panel's own repaint is not an edit, so Ctrl+Z may not undo it (left on the undo stack, an
            # undo after a Book switch could bring the previous Book's titles back into this one). Undo history
            # starts again at each repaint; a box the repaint did not change keeps its history.
            self.chapter_text.edit_reset()
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

    # v0.8.2: every callback that asks the model for a change first commits a Chapter Titles edit no key release
    # reported yet (a paste, a drop, an input method) through :meth:`flush_pending_editor_state`, so the change is
    # computed from a workspace that already holds it: a duplicate copies it, a removal asks about it, a Build
    # freezes it. ``render`` repeats the flush as the safety net, so nothing redraws the box over it.

    def on_previous(self) -> None:
        self.flush_pending_editor_state()
        self._apply(previous_book(self.workspace))

    def on_next(self) -> None:
        self.flush_pending_editor_state()
        self._apply(next_book(self.workspace))

    def on_select(self, book_id: str) -> None:
        self.flush_pending_editor_state()
        self._apply(select_book(self.workspace, book_id))

    def on_add(self) -> None:
        self.flush_pending_editor_state()
        self._apply(add_book(self.workspace, id_factory=self._ids))

    def on_duplicate(self) -> None:
        self.flush_pending_editor_state()
        self._apply(duplicate_book(self.workspace, id_factory=self._ids))

    def on_remove(self, meaningful: bool) -> None:
        """Decision 50A: the model answered; this panel decides to ask."""
        # A pasted title the navigator could not know of yet still makes the Book worth asking about.
        if self.flush_pending_editor_state():
            meaningful = meaningful or has_meaningful_work(self.workspace.current)
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
        self.flush_pending_editor_state()
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
        self.flush_pending_editor_state()
        self._apply(wf.set_book_field(self.workspace, name, value))

    def on_auto_number(self) -> None:
        if self._rendering or self._closed:
            return
        self._render_series_part_state()

    def on_chapter_edit(self, _event=None) -> None:
        """A key release (or a modified flag) in the Chapter Titles box: commit what it shows."""
        if self._suspend_chapters or self._rendering or self._closed:
            return
        if self.flush_pending_editor_state():
            self._render_light()

    def _on_chapter_modified(self, _event=None) -> None:
        """Tk's ``<<Modified>>``: some change reached the box, typed or not. Main thread only.

        The flag is cleared so the next change reports again; clearing it reports once more, and that report finds
        nothing new. A change the panel itself painted is the baseline already, so it commits nothing.
        """
        if self._closed:
            return
        try:
            if not self.chapter_text.edit_modified():
                return
            self.chapter_text.edit_modified(False)
        except tk.TclError:
            return
        self.on_chapter_edit()

    def flush_pending_editor_state(self) -> bool:
        """Commit a Chapter Titles change the model has not heard of yet, to the Book it was typed for (v0.8.2).

        **The one commit boundary for the panel's own editor** (the MP3 Tool's R1-1, applied here). The box shows one
        Book's titles; the panel remembers which Book (``_chapter_book_id``) and what it last wrote there
        (``_chapter_baseline``). Text that differs from the baseline is the user's and is stored -- raw, exactly as
        the box holds it, as a key release stores it -- on *that* Book by its identity, so a change that already moved
        the selection can never hand it to another Book. Unchanged text commits nothing, so a Book whose defaults
        were never edited keeps an empty configuration and its displayed defaults keep following the track order. A
        Book that no longer exists has nowhere to keep it. The box itself is not touched: no repaint, caret and
        selection stay where they are. Returns whether the model changed. Main thread only.
        """
        if self._closed or self._suspend_chapters:
            return False
        try:
            raw = self.chapter_text.get("1.0", "end-1c")
        except tk.TclError:
            return False
        if raw == self._chapter_baseline:
            return False
        self._chapter_baseline = raw
        space = self.workspace
        owner = self._chapter_book_id or space.current.book_id
        if owner not in space.book_ids:
            return False
        mutation = wf.set_book_field(space, "chapter_titles", raw, book_id=owner)
        if mutation.changed:
            self.workspace = mutation.workspace
        return mutation.changed

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
            self._remember_cover_dir(chosen)
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
            self._remember_cover_dir(chosen)
            self.set_book_field("artwork", chosen)

    def clear_book_artwork(self) -> None:
        self._guard.require("clear_book_artwork")
        if not self.book_artwork.enabled:
            return
        self.set_book_field("artwork", "")

    # -- custom destination ---------------------------------------------- #

    def _on_custom_dest_change(self):
        """Show the path controls only while the custom mode is on.

        The path row changes what Tracks, Chapters & Build needs, so the
        density and the row floors are measured again: the flexible lists give
        way to the new row rather than Build or the job area falling off.
        """
        self._place_customrow()
        if self._density_needs is not None and not self._closed:
            self._density_needs = None
            self._on_panel_configure()

    def _place_customrow(self) -> None:
        """Where the path row goes: beside the toggle on the options line in
        the tight density (where the short wording leaves it room), else on
        the line beneath. Hidden while the custom mode is off."""
        if not self.var_custom_dest.get():
            self.customrow.grid_forget()
            return
        if self._tight and self._hints["options_layout"] == "row":
            self.customrow.grid(row=0, column=5, columnspan=1, sticky="ew",
                                padx=(8, 0), pady=0)
        else:
            self.customrow.grid(row=self._customrow_at, column=0, columnspan=6,
                                sticky="ew", padx=0, pady=(4, 0))

    def choose_custom_dest(self):
        chosen = str(self._choose_destination() or "")
        if chosen:
            self.var_custom_path.set(chosen)
            # Only where the dialog opens next; the destination itself is never persisted.
            folder = settings.selected_dir(chosen, is_file=False)
            if folder:
                settings.set(KEY_DEST_DIR, folder)

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
        self.flush_pending_editor_state()
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
        self.flush_pending_editor_state()
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
        self.flush_pending_editor_state()  # a pasted title is work the replace question must count
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
        # What the user agreed to replace: the Books as they are at this press (navigation does not change them).
        self._replacing = self.workspace.books
        report = self._coordinator.start(self._request(roots))
        if report.outcome is StartOutcome.STARTED:
            self.import_status.set_scanning(0)
            self._poller.start()
            return
        self._replacing = None
        self._pending_input_dir = None  # a declined or refused scan is not remembered
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

    def _workspace_has_meaningful_work(self) -> bool:
        """The shared vocabulary, composed: any Book with files or configuration,
        or any populated Shared field. Not a fourth definition of "empty"."""
        space = self.workspace
        return (any(has_meaningful_work(book) for book in space.books)
                or bool(space.shared.populated_fields))

    def clear_all_imports(self) -> bool:
        """Return the tool to its pristine startup state — a workspace reset only.

        The reset authority is the model's own ``new_workspace``; nothing is
        deleted or written on disk, the log keeps its history (a divider marks
        the reset), settings are untouched, and a run in progress owns the
        workspace so the button is locked and this refuses. A pristine
        workspace asks nothing; meaningful work asks first.
        """
        self._guard.require("clear_all_imports")
        if self._closed or self.is_running or self._coordinator.is_active:
            return False
        self.flush_pending_editor_state()  # a pasted title is work the clear question must count
        meaningful = self._workspace_has_meaningful_work()
        if meaningful and not self._confirm(
                "Clear all imports?",
                "This clears every imported Book and file, and any unsaved workspace "
                "edits, from this tool.\n\nThe original files are not deleted or modified, "
                "and outputs already written are kept.\n\nClear them?"):
            return False
        had_run = self.run is not None
        # v0.8.2: the fresh, idle job area is built first, transactionally; if it cannot be, nothing is reset and
        # the previous run, its result and its Retry Failed stay exactly as they were.
        try:
            self._install_jobs(IDLE_RUN_ID, ())
        except Exception as exc:  # noqa: BLE001 - nothing changed
            text = f"{CLEAR_IMPORTS_LABEL}: the tool could not be reset; nothing was cleared."
            self._say(text, f"{type(exc).__name__}: {exc}")
            messagebox.showerror(APP_TITLE, text, parent=self)
            return False
        # The run goes with the workspace, and with it every chance of a Retry Failed: its kept staging goes too.
        self._abandon_run()
        self.workspace = wf.new_workspace(id_factory=self._ids)
        self.book_numbers = {}
        self.last_plan = None
        self.run = None
        self._attempt = None
        self.var_outdir.set(output_paths.destination_hint(TOOL_KEY))
        if meaningful or had_run:
            self.log.divider(f"{DIVIDER_MARK} {CLEAR_IMPORTS_LABEL}")
        self.render()
        return True

    def _handle_outcome(self, outcome: ImportOutcome) -> ImportOutcome:
        if self._closed:
            return outcome
        self._settle_import_dir(outcome)
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
            replacing, self._replacing = self._replacing, None
            if (status is OutcomeStatus.COMMITTED and outcome.commit is not None and kind == "folder"
                    and self._books_changed_since(replacing)):
                self._refuse_replacement(outcome)
                return outcome
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

    def _books_changed_since(self, replacing: tuple | None) -> bool:
        """Whether a Book changed after Import Folder was pressed to replace *replacing* (v0.8.2 qualification).

        Books are immutable values and every edit makes a new one, so the comparison is exact: a field, Chapter
        Titles (a paste no key release reported is committed first), a track moved or removed, a Book added,
        duplicated or removed. Navigation and Shared fields leave the Books as they were (Shared Metadata is carried
        through a replacement); an edit put back to the identical value is no change. Main thread.
        """
        if replacing is None:
            return False
        self.flush_pending_editor_state()
        return self.workspace.books != replacing

    def _refuse_replacement(self, outcome: ImportOutcome) -> None:
        """Keep the Books the user changed while Import Folder ran, and say so: nothing is replaced or added."""
        self.render()
        self.import_status.set_idle(REPLACEMENT_REFUSED)
        self._say(REPLACEMENT_REFUSED)
        for problem in outcome.problems:
            self._say(f"  {problem.display_message}",
                      f"  {problem.technical_detail or problem.display_message}")
        messagebox.showwarning(APP_TITLE, REPLACEMENT_REFUSED, parent=self)

    def _project_import(self, kind: str | None, outcome: ImportOutcome) -> None:
        """The committed snapshot becomes Books (folder) or tracks (files)."""
        self.flush_pending_editor_state()
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

    def _abandon_run(self) -> None:
        """No Retry Failed can reach the current run any more (ACT72-031): its kept staging goes. Main thread; never
        raises. A worker still running keeps nothing when it ends."""
        run = self.run
        if run is None:
            return
        try:
            problems = run.abandon()
        except Exception as exc:  # noqa: BLE001 - closing and clearing must go on
            problems = (f"{type(exc).__name__}: {exc}",)
        for line in problems:
            if self._closed:
                logging_setup.get_logger().warning("M4B Maker: private staging left in place: %s", line)
            else:
                self._say("Some private staging could not be removed.", line)

    def build(self) -> bool:
        """Validate on Tk, freeze the inputs, and hand reserving and planning to the preparation worker.

        Exactly one destination per operation, never one per Book, and only after the workspace validated. The plan
        is frozen from the workspace as it is at this moment; editing anything afterwards cannot reach it, and
        neither can a later Retry Failed read anything but it. A press while a run is under way -- or being prepared
        -- is refused before anything is reserved.

        v0.8.2 Checkpoint 2: ``True`` now means *accepted*. The press returns at once with the job area showing
        "Preparing job…" and Cancel; the preparation worker reserves the standard run (or validates the custom folder
        and makes its owned work area) and plans every Book, off the Tk thread; the run starts when the pump adopts
        the finished plan (:meth:`_on_preparation`). A refused plan is reported then, exactly as before, with what
        it reserved released and nothing started.
        """
        self._guard.require("build")
        if self._closed or self.is_running:
            return False
        # A Chapter Titles change no key release reported (a paste, an input method) is committed through the
        # model, to its own Book, before anything is frozen, so the run uses exactly what the box shows.
        if self.flush_pending_editor_state():
            self._render_light()
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
                # The Book's stable number, as the navigator shows it, never its position (v0.7.2, ACT72-036, as in
                # the MP3 Tool).
                number = self.book_numbers.get(book.book_id, position)
                messagebox.showerror(APP_TITLE, f"Silence for Book {number}: {exc}",
                                     parent=self)
                return False
        if options.auto_number:
            try:
                wf.parse_start_part(options.start_part_text)
            except wf.MakerValueError as exc:
                messagebox.showerror(APP_TITLE, f"Start Part: {exc}", parent=self)
                return False
        # Frozen here, on Tk, and never read again: the immutable workspace, the options, the custom folder as typed,
        # the moment of the press and ONE output configuration -- the one in force at this press -- that both every
        # Book's run snapshot records and the reservation resolves its output base from, even if Preferences change
        # while the worker prepares. The run's Plan 6 capture is derived from these on the worker.
        inputs = _BuildInputs(workspace=space, options=options, custom=self.custom_destination(),
                              run_config=shared_config.get_effective(), id_factory=self._ids,
                              created_at=self._clock())
        attempted = [book for book in space.books if not book.files.is_empty]
        self._preparations += 1
        preparation = prep.Preparation(label=BUILD_LABEL, inputs=inputs, number=self._preparations)
        self._preparing = preparation
        self._show_preparing(preparation, books=len(attempted),
                             tracks=sum(book.file_count for book in attempted))
        # Tell the worker once Tk has painted this press: its CPU-bound planning would otherwise compete with that
        # one repaint for the GIL and stretch it past 100 ms (measured at 5,000 files, v0.8.2 Checkpoint 2).
        try:
            self.after_idle(preparation.painted.set)
        except tk.TclError:
            preparation.painted.set()
        try:
            thread = self._thread_factory(lambda: self._prepare(preparation),
                                          f"m4b-maker-prepare-{preparation.number}")
            thread.start()
        except Exception as exc:  # noqa: BLE001 - nothing was reserved yet; the panel must not stay locked
            if self._preparing is preparation:
                self._preparing = None
                preparation.withdraw()
                text = f"{BUILD_LABEL}: the job could not be prepared, and nothing was started."
                self._end_preparation(STATUS_PREPARATION_FAILED, text, f"{type(exc).__name__}: {exc}")
                messagebox.showerror(APP_TITLE, text, parent=self)
            return False
        return True

    # -- the preparation: worker side ------------------------------------------ #

    def _prepare(self, preparation: prep.Preparation) -> None:
        """The preparation worker's whole body: reserve or validate the destination, then plan. Never raises.

        Reads only the frozen *preparation* and writes only the preparation queue -- no widget, no Tk variable, no
        panel state. Everything it does is in module-level functions that are handed what they need.
        """
        inputs = preparation.inputs
        prep.prepare(
            preparation, self._prep_q.put,
            reserve=lambda: _reserve_destination(inputs),
            build=lambda holding, progress: _plan_build(inputs, holding, preparation.checkpoint, progress),
            release=_release_destination,
            refusal=_build_refusal)

    # -- the preparation: Tk side --------------------------------------------- #

    def _show_preparing(self, preparation: prep.Preparation, *, books: int, tracks: int) -> None:
        """Lock the workspace, offer Cancel, and say "Preparing job…" on the current job area. Main thread only.

        The job area keeps the previous run's adapter: its stream, result and Retry Failed stay untouched behind this
        presentation and come back with one ``jobs.render()`` if the preparation ends without a run.
        """
        self.lock_group.apply(JobState.RUNNING)
        self.controls.apply(JobState.RUNNING)
        # Cancel is the one control a preparation honours; Pause has no checkpoint to wait at here.
        pause = self.controls.buttons.get(JobAction.PAUSE)
        if pause is not None:
            try:
                pause.configure(state="disabled")  # the shared bar enables by this option, so it disables by it
            except tk.TclError:
                pass
        self._show_preparation_progress(f"{preparation.label}: checking {books} Book(s), {tracks} track(s)")
        self.status.set_eta("")
        self.status.set_status(STATUS_PREPARING)
        self._say(f"{preparation.label}: preparing {books} Book(s), {tracks} track(s)…")

    def _show_preparation_progress(self, stage: str) -> None:
        self.status.apply(ProgressView(ProgressMode.INDETERMINATE, label=STATUS_PREPARING), stage=stage)

    def _drain_preparation(self) -> None:
        """The pump's preparation drain: handle what the preparation worker said. Main thread only; never raises."""
        for _ in range(PREPARATION_DRAIN_LIMIT):
            try:
                message = self._prep_q.get_nowait()
            except queue.Empty:
                return
            current = message.preparation is self._preparing
            try:
                self._on_preparation(message)
            except Exception as exc:  # noqa: BLE001 - one bad message must not stop the pump that frees the panel
                logging_setup.get_logger().exception("M4B Maker: preparation message failed: %s", exc)
                # The current preparation's ending must free the panel even if it failed part-way, as long as no
                # attempt took the run over; a plan it offered is released off Tk.
                if current and self._preparing is message.preparation and not self._closed:
                    self._preparing = None
                    left = message.preparation.withdraw()
                    if left is not None:
                        self._release_unadopted(left)
                    try:
                        self._end_preparation(STATUS_PREPARATION_FAILED,
                                              f"{message.preparation.label}: the job could not be prepared.",
                                              f"{type(exc).__name__}: {exc}")
                    except Exception:  # noqa: BLE001 - the pump must keep running
                        logging_setup.get_logger().exception("M4B Maker: the preparation could not be ended")

    def _on_preparation(self, message: prep.PreparationMessage) -> None:
        """Adopt a finished plan and start the run, or end the preparation. Main thread only.

        A message from any preparation but the current one is stale: it is never acted on, and a plan it offered is
        taken back and released. A plan Cancel or Close withdrew is never adopted, so no media starts.
        """
        preparation = message.preparation
        if self._closed or preparation is not self._preparing:
            left = preparation.withdraw()
            if left is not None:
                self._release_unadopted(left)
            return
        kind = message.kind
        if kind == prep.PROGRESS:
            if message.total and not preparation.cancel_requested.is_set():
                self._show_preparation_progress(
                    f"{preparation.label}: planning Book {min(message.done + 1, message.total)} "
                    f"of {message.total}")
            return
        self._preparing = None
        if kind == prep.PREPARED:
            prepared = preparation.adopt()
            if prepared is not None:
                self._adopt(preparation, prepared)
                return
            kind = prep.CANCELLED
        if kind == prep.CANCELLED or preparation.cancel_requested.is_set():
            note = f" ({message.text})" if kind != prep.CANCELLED and message.text else ""
            self._end_preparation(
                STATUS_PREPARATION_CANCELLED,
                f"{preparation.label}: cancelled before anything was started; the workspace is unchanged.",
                f"{preparation.label}: preparation cancelled{note}; {message.detail}".rstrip("; "))
            return
        self._end_preparation(STATUS_PREPARATION_FAILED, message.text, message.detail or message.text)
        if message.warning:
            messagebox.showwarning(APP_TITLE, message.text, parent=self)
        else:
            messagebox.showerror(APP_TITLE, message.text, parent=self)

    def _end_preparation(self, status: str, line: str, detail: str) -> None:
        """Put the job area back exactly as the previous run left it, then say why nothing started."""
        self.jobs.render()
        self.status.set_status(status)
        self._say(line, detail)
        self.render()

    def _adopt(self, preparation: prep.Preparation, prepared: "_Prepared") -> None:
        """The prepared plan becomes the run. Main thread only; never raises.

        The one ``MakerRun`` is made, and only once the new attempt's job area is up does the new run replace the old
        one (:meth:`_start_attempt`): its Retry Failed can no longer be reached, so the old run's kept staging goes --
        removed by the new attempt's worker, off the Tk thread. If that setup fails before anything changed hands,
        the preparation ends as a failed one does -- the previous run, its result, Retry Failed and kept staging
        untouched, the panel unlocked, the error shown -- and what the plan reserved is released off the Tk thread.
        """
        plan, owned = prepared.plan, prepared.owned
        text = f"{preparation.label}: the job could not be started, and nothing was started."
        try:
            # Each run gets its own staging lock: it orders that run's worker against this thread (ACT72-031), and
            # a superseded run's cleanup on another worker can then never make this thread wait.
            run = self._run_factory(plan, id_factory=self._ids, clock=self._clock,
                                    publish=self._publish, staging_lock=threading.Lock(),
                                    on_staging_released=None if owned is None else owned.close,
                                    recover_temporaries=None if owned is None else _recover_owned_temporaries)
        except Exception as exc:  # noqa: BLE001 - nothing changed hands
            self._release_unadopted(prepared)
            self._end_preparation(STATUS_PREPARATION_FAILED, text, f"{type(exc).__name__}: {exc}")
            messagebox.showerror(APP_TITLE, text, parent=self)
            return
        try:
            self._start_attempt(run, run.start, "Build M4B(s)", replaces=True)
        except _AttemptNotStarted as exc:
            self._release_unadopted(prepared)
            self._end_preparation(STATUS_PREPARATION_FAILED, text, exc.detail)
            messagebox.showerror(APP_TITLE, text, parent=self)

    def _release_unadopted(self, prepared: "_Prepared") -> None:
        """Release what a plan nobody will run reserved, **off the Tk thread**. Main thread; returns at once.

        A plan offered and then withdrawn (Cancel, Close, a stale ending) or one whose run could not be set up hands
        what it reserved here exactly once (``Preparation.withdraw`` / ``adopt`` decide that under one lock): the
        standard run folder, removed only while still empty (``output_paths.release_if_empty``: links and anything
        inside are left alone; no source is ever touched), or the custom build's owned work-area entry, closed. A
        short-lived worker does it, needing neither Tk nor the pump, so it finishes even after the panel closed.
        Should no worker start, what was reserved is left (an empty folder, or a work-area entry a later run
        recovers) and named in the log rather than making Tk wait on the filesystem.
        """
        self._releases += 1
        holding = (prepared.plan.destination, prepared.owned)

        def release() -> None:
            try:
                _release_destination(holding)
            except Exception as exc:  # noqa: BLE001 - a worker must not raise
                logging_setup.get_logger().warning("M4B Maker: an unused destination could not be released: %s (%s)",
                                                   prepared.plan.root, exc)

        try:
            self._thread_factory(release, f"m4b-maker-release-{self._releases}").start()
        except Exception as exc:  # noqa: BLE001 - something empty left behind is harmless; a frozen window is not
            logging_setup.get_logger().warning("M4B Maker: an unused destination was left in place: %s (%s: %s)",
                                               prepared.plan.root, type(exc).__name__, exc)
            if not self._closed:
                self._say("An unused, empty output folder was left in place.",
                          f"Unused output left in place: {prepared.plan.root} ({type(exc).__name__}: {exc})")

    # ------------------------------------------------------------------ #
    # The one run: adapter, attempt, worker
    # ------------------------------------------------------------------ #

    def _start_attempt(self, run: batch.MakerRun, begin, label: str, *, replaces: bool = False) -> None:
        """Begin one attempt at *run* through *begin* (``run.start`` or ``run.retry_failed``) and start its one worker.

        v0.8.2 Checkpoint 2 -- **ownership changes hands in one place.** The new job area is built first, for the
        run's id, transactionally (:meth:`_install_jobs`). If that fails, :class:`_AttemptNotStarted` is raised and
        *nothing* has changed: the previous attempt, its result, its job area with its Retry Failed and its kept
        staging, and the panel's idle state are all as they were, and the run has not begun. Only after the job area
        is up does the attempt begin (and, with ``replaces``, the run replace the last one, whose kept staging is
        handed to the new worker to remove). A failure from there until the worker is running settles the attempt
        as failed through its own controller and terminal event, as a worker fault would, so the panel never stays
        busy with nothing running.
        """
        retired = self.jobs
        plan = run.plan
        failure: BaseException | None = None
        try:
            item_ids = tuple(occ for book in plan.books for occ in book.occurrence_ids)
            self._install_jobs(run.run_id, item_ids)
        except Exception as exc:  # noqa: BLE001 - decided here: nothing changed hands, or the attempt settles
            if self.jobs is retired:
                raise _AttemptNotStarted(f"{type(exc).__name__}: {exc}") from exc
            failure = exc

        # -- From here the new job area is the panel's. ------------------------- #
        superseded = None
        if replaces:
            # The new run replaces the old one: no Retry Failed can reach it any more. Its kept staging is removed by
            # a short-lived release worker once this attempt's worker is running, off the Tk thread
            # (``_release_superseded``).
            superseded = self.run if self.run is not run else None
            self.last_plan = plan
            self.run = run
            self.var_outdir.set(str(plan.root))
        try:
            attempt = begin()
        except Exception as exc:  # noqa: BLE001 - nothing began; the panel must not stay locked
            detail = f"{type(exc).__name__}: {exc}"
            logging_setup.get_logger().warning("M4B Maker: an attempt could not begin: %s", detail)
            if replaces:
                self._attempt = None  # the new run never began; Clear All Imports or closing lets it go
            if superseded is not None:
                self._release_in_background(lambda: self._release_superseded(superseded))
            self.jobs.set_result(run.result)
            self.jobs.render()
            self.status.set_status(STATUS_PREPARATION_FAILED)
            self._say(f"{label}: the job could not be started, and nothing was processed.", detail)
            self.render()
            return
        self._attempt = attempt
        try:
            if failure is not None:
                raise failure
            self.lock_group.apply(attempt.controller.state)
            heading = (f"Retry Failed — attempt {attempt.number}" if attempt.is_retry
                       else f"{label} — {plan.root.name}")
            self.log.divider(f"{DIVIDER_MARK} {heading}")
            self._render_status()
            # The worker body is the attempt's own (``Attempt.run`` never raises and always sends the one terminal
            # event); it is handed to the thread, never called here.
            thread = self._thread_factory(attempt.run, f"m4b-{attempt.run_id}")
            self._worker_thread = thread
            thread.start()
        except Exception as exc:  # noqa: BLE001 - a worker that never started must still settle the run
            self._fail_unstarted(attempt, superseded, f"{type(exc).__name__}: {exc}")
            return
        if superseded is not None:
            # Beside the new run, not before it: the two runs share no folder and no lock.
            self._release_in_background(lambda: self._release_superseded(superseded))

    def _release_superseded(self, run) -> None:
        """Remove the kept staging of the run a new run replaced (v0.8.2). Release worker; touches no widget; never
        raises.

        That run is finished and nothing else holds it; its own staging lock is not the new run's, so this never
        makes Tk or the new run wait. What could not be removed is named in the session log and stays where it is.
        """
        try:
            problems = run.abandon()
        except Exception as exc:  # noqa: BLE001 - the new run must still go on
            problems = (f"{type(exc).__name__}: {exc}",)
        for line in problems:
            logging_setup.get_logger().warning(
                "M4B Maker: private staging of the previous run left in place: %s", line)

    def _release_in_background(self, work) -> None:
        """Run one cleanup on a short-lived worker; when none can start, run it here. Main thread."""
        self._releases += 1
        try:
            self._thread_factory(work, f"m4b-maker-release-{self._releases}").start()
        except Exception:  # noqa: BLE001 - no worker at all: do it here rather than leave it behind
            work()

    def _fail_unstarted(self, attempt: batch.Attempt, superseded, detail: str) -> None:
        """Settle an attempt whose worker never started as failed. Main thread only; never raises.

        Nothing ran. The superseded run's kept staging goes to a short-lived release worker (Tk does not wait for
        it); the attempt settles FAILED through its own controller (``Attempt.fail_unstarted``), which releases the
        staging nobody can retry -- for a run that never started, a few directory checks -- and sends the one
        terminal event that frees the panel. Should even that fail, the panel is freed directly.
        """
        if superseded is not None:
            self._release_in_background(lambda: self._release_superseded(superseded))
        try:
            attempt.fail_unstarted(detail)
            return
        except Exception as exc:  # noqa: BLE001 - the attempt cannot settle; the panel must still be freed
            logging_setup.get_logger().exception("M4B Maker: an attempt could not be settled: %s", exc)
        self._attempt = None
        try:
            self.jobs.render()
            self.status.set_status(STATUS_PREPARATION_FAILED)
        except Exception:  # noqa: BLE001
            pass
        self._say("Build: the job could not be started, and nothing was processed.", detail)
        self.render()

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
                      f"{self._counts_text(result)} → {self.last_plan.root}")
        self.render()

    @property
    def is_running(self) -> bool:
        """An attempt is running, or an accepted Build press is still being prepared (v0.8.2)."""
        return self._preparing is not None or self._attempt_running

    @property
    def is_preparing(self) -> bool:
        """An accepted Build press is being reserved and planned off the Tk thread; no run has started yet."""
        return self._preparing is not None

    @property
    def _attempt_running(self) -> bool:
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
        if self._attempt_running:
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
        if book_id == self._stopped_book_id(result):
            return STATUS_CANCELLED
        return self._status_of_disposition(result.disposition_for(book_id))

    def _stopped_book_id(self, result) -> str | None:
        """The Book a Cancel stopped part-way in the latest attempt, if the frozen result still calls it NOT_ATTEMPTED."""
        attempt = self._attempt
        stopped = getattr(attempt, "stopped_book_id", None)
        if (stopped is None or result is None or result.state is not JobState.CANCELLED
                or result.disposition_for(stopped) is not BookDisposition.NOT_ATTEMPTED):
            return None
        return stopped

    def _counts_text(self, result) -> str:
        """"N not attempted", or with the stopped Book told apart: "1 stopped by Cancel, N not attempted"."""
        stopped = 1 if self._stopped_book_id(result) is not None else 0
        never = result.not_attempted_count - stopped
        return (f"{stopped} stopped by Cancel, {never} not attempted" if stopped
                else f"{result.not_attempted_count} not attempted")

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
        if self.run is not None and self._attempt_running:
            self.run.pause()

    def resume(self) -> None:
        if self.run is not None and self._attempt_running:
            self.run.resume()

    def cancel(self) -> None:
        """Ask the run to stop -- or, while a Build press is still being prepared, the preparation (v0.8.2).

        During preparation there is no run yet. Cancel asks the preparation worker to stop at its next checkpoint and
        says so at once; the panel ends the preparation when the worker acknowledges (what it reserved released,
        nothing started, the workspace and the previous run as they were). A plan already offered is taken back here
        and released off the Tk thread, so it can never start.
        """
        preparation = self._preparing
        if preparation is not None:
            if preparation.cancel_requested.is_set():
                return
            left = preparation.withdraw()
            if left is not None:
                self._release_unadopted(left)  # off Tk: Cancel never waits on the output storage
            if not self._closed:
                self.controls.apply(JobState.CANCEL_REQUESTED)
                self.status.set_status(STATUS_CANCELLING_PREPARATION)
            return
        if self.run is not None and self._attempt_running:
            self.run.cancel()

    def retry_failed(self) -> bool:
        """Re-run the frozen run's failed Books. A new attempt, not a new run."""
        self._guard.require("retry_failed")
        if self._closed or self.is_running or self.run is None:
            return False
        result = self.run.result
        if result is None or not result.can_retry_failed:
            return False
        try:
            self._start_attempt(self.run, self.run.retry_failed, "Retry Failed")
        except _AttemptNotStarted as exc:
            # v0.8.2: nothing changed hands; the failed Books, their kept staging and Retry Failed stay as they were.
            text = "Retry Failed: the retry could not be started; nothing was changed."
            self.jobs.render()
            self._say(text, exc.detail)
            messagebox.showerror(APP_TITLE, text, parent=self)
            return False
        return True

    # ------------------------------------------------------------------ #
    # Teardown
    # ------------------------------------------------------------------ #

    def close(self) -> None:
        """Cancel any scan or run, stop the pump, close every component. Idempotent."""
        if self._closed:
            return
        self._closed = True
        appearance.unregister_listener(self._on_appearance_changed)
        # v0.8.2: a preparation still going stops at its next checkpoint and releases what it reserved; a plan it
        # already offered is taken back here and released off Tk, so nothing it planned can start after closing.
        preparation, self._preparing = self._preparing, None
        if preparation is not None:
            left = preparation.withdraw()
            if left is not None:
                self._release_unadopted(left)
        # Nothing can retry once the tool is closed (ACT72-031): kept staging goes now, or when the worker ends.
        self._abandon_run()
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
        traces = [(self.book_vars[key], token) for key, token in self._book_traces.items()]
        traces.append((self.var_outdir, self._outdir_trace))
        for variable, token in traces:
            if token is None:
                continue
            try:
                variable.trace_remove("write", token)
            except (tk.TclError, ValueError):
                pass

    def destroy(self) -> None:
        """Tear the panel down and finish the teardown on this thread, as the Converter and Cover panels do. Without this a closing window
        never reaches :meth:`close`, so a running worker is never told to stop (measured, v0.7.2 Phase 3)."""
        self.close()
        super().destroy()
        gc.collect()


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
