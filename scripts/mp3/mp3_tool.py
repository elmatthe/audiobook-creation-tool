#!/usr/bin/env python3
"""MP3 Tool — a multi-book MP3 metadata editor and processor.

v0.6.3 focused MP3 redesign, Phase 4: the workspace UI. This is the first
production panel to adopt the shared Plan 6 multi-book workspace, composed with
the Plan 3 importer and job-control adapters and the Phase 3 MP3 model:

- ``Import Folder`` scans one parent directory through the shared
  ``ImportCoordinator`` and projects the committed snapshot into **one Book per
  directory that directly contains MP3s** (``mp3_workflow.import_folder``);
  ``Add Files`` puts every chosen MP3 into the **current** Book in dialog order
  (``mp3_workflow.add_files``). The panel owns no second list of paths — every
  track shown is the current Book's immutable ``ImportedFileSnapshot``.
- Previous / Next / ``Book X of Y`` / the direct selector / Add / Duplicate /
  Remove are the shared ``BookNavigator``; every press is routed to the Plan 6
  model operation and the result is rendered back. Book identity is the stable
  Plan 6 id; the visible number is a position.
- The Shared area is exactly five fields — Artist / Author, Album Artist /
  Author, Album, Add/Remove Time at End of Each Track (seconds), Book Artwork.
  The four text fields are the shared ``SharedMetadataSurface`` in its compact
  ``rows`` layout; artwork is this panel's own Choose / Clear / preview control,
  once for Shared and once for the Book. A populated Shared value disables the
  matching Book control and leaves the Book's stored value intact — the disabled
  set is ``book_workspace.disabled_fields``, asked, never recomputed here.
- Per Book: the same fields, Auto-number, Start #, a Chapter Titles box (one
  title per line), the track list with Add Files / Move Up / Move Down / Remove
  Selected, per-field *Mixed source metadata* markers and a compact status.
- Exactly two processing actions — **Write ID3 Tags** and **Combine MP3s → One
  MP3** — beside the shared Pause / Resume / Cancel / Retry Failed bar, one
  global progress view and one Summary / Detailed log region.

Phase 7 moved the proven FFmpeg helpers (concat lists, FAST/Safe concat, WAV
normalisation, signed-time append/trim, timestamp text) into
``mp3/mp3_processing.py`` beside the Write ID3 and Combine engines that
consume the frozen plan; they are re-exported here under their original names.

Phase 5 adds the frozen plan: a processing button validates the workspace,
reserves **one** MP3 Tool run for the whole operation through the shared
service, and freezes everything the processing phases and a later Retry Failed
will read — Book order and ids, every track's occurrence, final Title, number
and filename, effective metadata, signed Time, artwork, the Book subfolders and
the private staging beside them (``mp3/mp3_plan.py``).

v0.8.2 moves reserving and planning off the Tk thread: the press validates and
freezes its inputs on Tk and shows "Preparing job…" with Cancel; one
preparation worker reserves and plans (``_Preparation``, ``_prepare``); the
pump adopts the finished plan and only then starts the one controller and the
one processing worker. At 2,341 tracks the v0.8.1 press froze the window for
about 20 minutes.

Phase 9 runs it. One operation is **one** Plan 3 run: one ``JobController``
for the whole batch (never one per Book), one ``JobReporter``, one event
stream drained by one ``JobAdapter`` on the panel's one pump, one worker
thread. The engine knows nothing of any of that: it is handed the controller's
``checkpoint`` and an event listener, and ``_RunProjection`` turns its
``ProcessingEvent`` lines into the shared job events on the worker's own
thread — no widget is ever reached from there. Pause, Resume and Cancel are
the controller's: ``PAUSED`` is shown only once the worker acknowledged it at
a checkpoint, and Cancel stops a running FFmpeg step at once (the engine is
handed the controller's non-blocking ``cancel_check`` too; v0.7.2, ACT72-023)
or otherwise at the next checkpoint, leaving the Books it never
reached ``NOT_ATTEMPTED`` and the batch ``CANCELLED`` (there is no Book-level
"cancelled"). When the terminal event is drained the per-Book ``RunResult``
values the engine settled compose into the Plan 6 ``WorkspaceRunResult`` on
the main thread — the one place Book statuses (Ready / Queued / Processing /
Completed / Failed / Skipped / Not attempted) are read from — and that frozen result is what
**Retry Failed** asks: ``retry_failed_books`` names the failed Books and their
failed occurrences, and the same engine re-runs exactly those against the
same ``RunPlan``, reusing every staged piece the first attempt kept and
publishing each Book whole from its original ``BookPlan``. The live workspace
may have been edited every way there is in between; none of it can reach the
retry.

The log is one region, ``Summary`` | ``Detailed``, whose history survives from
run to run: a divider marks each new run and each retry, the panel's own
import lines sit between, and Clear Log clears the visible text only — the
event history, the session log the shared ``LoggerBridge`` already writes the
technical lines into, and the frozen result are untouched. There is no Copy
button (the panes are selectable) and no level selector.

Removed with the single-book form, as the focused plan directs: the global file
list, the Book-level Title field, ``Silence between tracks``, the FAST checkbox,
the standalone ``Apply to All Files`` time action, the combined-filename popup
and the ad-hoc status queue.

Presentation (v0.6.6 Phase 6): the panel is the dense multi-Book (Family B)
workflow on the shared compact Light/Dark control language, the same one the
approved Cover, TTS and Converter interiors use. There is no MP3-specific
visual system:

  1. Import & Books    -- Import Folder, Clear All Imports, the import status,
                          the output hint and the Book navigator
  2. Book Settings     -- Shared (the tinted group whose values override every
                          Book's own) above Current Book (the ordinary surface)
  3. Tracks & Run      -- the track list and Chapter Titles side by side, then
                          Write ID3 Tags / Combine MP3s and the shared job area
  Activity             -- the one Summary | Detailed log with Clear Log, below

Every widget asks ``job_ui.style_name`` of the ``appearance_bundle`` for its
compact style (native control inheritance on Aqua), and a live Light/Dark
toggle recolors the few classic Tk widgets in place. No colour, font or metric
is declared here. Nothing scrolls the whole tool: the track list, the Chapter
Titles box and the log scroll locally and give up height first, and in the
real launcher's small windows the fixed bands take tighter padding
(``_apply_density``) before either flexible region is squeezed.

Composition follows the theme's metrics where it offers panel hints
(``_layout_hints``): native aqua controls are wider and taller than the
compact design's, so on macOS the navigator's Book actions fold under its
navigation row, the two operations stand in a column beside the job area, the
metadata entries ask for fewer characters, a long field label wraps and the
Book-only options take a row of their own. A bundle without those hints — the
Windows platform bundle, the classic branch, a test theme — gets the compact
single-row composition. Only where things sit differs; every control, label
and callback is the same.
"""

import gc
import queue
import sys
import threading
import time
from collections.abc import Mapping
from pathlib import Path

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox

# Make the scripts/ root importable so `shared.*` resolves whether this tool is
# run standalone (python mp3/mp3_tool.py) or imported by the launcher.
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
from shared import source_readback
from shared import subprocess_utils as sp
from shared import ui_theme
from shared.book_workspace import (
    BookDisposition,
    SharedMetadata,
    WorkspaceContractError,
    WorkspaceRunResult,
    WorkspaceSnapshot,
    add_book,
    disabled_fields,
    duplicate_book,
    has_meaningful_work,
    next_book,
    previous_book,
    remove_book,
    retry_failed_books,
    select_book,
    set_shared_metadata,
)
from shared.book_workspace_ui import BookNavigator, SharedMetadataSurface
from shared.cancellation import ConversionCancelled
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
from shared.job_control import JobAction, JobEventKind, JobState, ProgressMode, ProgressView
from shared.job_ui import MainThreadGuard, MainThreadPump, action_style, style_name
from artwork import mp3_artwork
from mp3 import mp3_plan
from mp3 import mp3_processing
from mp3 import mp3_workflow as wf

# Tk's side of the artwork preview. Decoding, thumbnailing and every rule about
# what a chosen image becomes live in ``mp3_artwork``; this only turns the
# service's in-memory thumbnail into something a label can show.
try:
    from PIL import ImageTk
except Exception:  # pragma: no cover - Pillow is a pinned requirement
    ImageTk = None

APP_TITLE = "MP3 Tool"

# Auto-named output folder slug (v0.1.1): every processing run lands in
# <output base>/MP3-Tool-Outputs/MP3-Tool-N through the shared service. The
# imported MP3s are read-only.
TOOL_KEY = "mp3_tool"
SLUG = paths.TOOL_SLUGS[TOOL_KEY]

# settings.json keys (each only remembers where its dialog opens; the output
# folder is NOT persisted — it always resets to a fresh Downloads/<SLUG>-N).
# v0.8.1: artwork has its own history, shared by Shared and Book artwork, and
# separate from the import history.
KEY_INPUT_DIR = "mp3_tool.input_dir"
KEY_COVER_DIR = "mp3_tool.cover_dir"

#: The artwork preview is a display-only thumbnail: the selected file is never
#: resized, cropped or rewritten, and what is embedded later is the file itself.
#: v0.6.6 Phase 6: no taller than the control's caption and buttons beside it,
#: so choosing artwork never makes Book Settings grow (no layout jump).
PREVIEW_MAX = (40, 40)

#: The compact status shown for the current Book. While a run is under way it
#: is read from that run's frozen plan and the results the engine has settled
#: so far; afterwards from the frozen ``WorkspaceRunResult``'s dispositions —
#: never from a second state machine kept here.
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

MIXED_MARK = "Mixed source metadata"
#: The same marker in the tight density (v0.6.6 Phase 6). At the real
#: launcher's 920x600 content area a field column is ~60-125 px wide; the full
#: wording would widen its column and squeeze every Current Book label, or wrap
#: taller and push Activity off screen. Same place, same style, same meaning.
MIXED_MARK_SHORT = "Mixed"

#: Characters of Album / folder hint shown after ``Book N`` before eliding.
HINT_LIMIT = 40

#: How many frozen Summary and Detailed lines the log region keeps.
LOG_LIMIT = 400

#: The run id the job area carries before any operation has started.
IDLE_RUN_ID = "mp3-idle"

#: The stage announced on the main thread before the worker starts.
STAGE_PREPARE = "prepare"

#: v0.8.2: what the job area says between an accepted press and the plan's adoption, while the preparation worker
#: reserves the run and plans every track off the Tk thread.
STATUS_PREPARING = "Preparing job…"
STATUS_CANCELLING_PREPARATION = "Cancelling preparation…"
STATUS_PREPARATION_CANCELLED = "Cancelled — nothing was started"
STATUS_PREPARATION_FAILED = "Not started"

#: How many preparation messages one pump tick handles at most (one per Book plus one ending, normally).
PREPARATION_DRAIN_LIMIT = 256

#: Rules a line under the previous run's lines in both log panes.
DIVIDER_MARK = "────"

#: The one label of the destructive workspace reset, shared by the three
#: multi-Book tools (v0.6.4 Phase 12 maintainer amendment).
CLEAR_IMPORTS_LABEL = "Clear All Imports"

#: v0.8.2 qualification: Import Folder replaces only the Books the user agreed to replace. If a Book was changed while
#: the import ran (the scan, then the reading of the tags), nothing is replaced and this is said. The same sentence in
#: the three multi-Book tools.
REPLACEMENT_REFUSED = ("Import Folder: the Books were changed while the import was running, so they were not "
                       "replaced and your changes were kept. Choose Import Folder again to replace them.")

#: What the user is told when a worker dies with the run unfinished.
FAULT_MESSAGE = "The run stopped unexpectedly and was not completed."

#: The numbered Family-B hierarchy (frozen UI contract §2), and Activity below.
SECTION_TITLES = ("1. Import & Books", "2. Book Settings", "3. Tracks & Run", "Activity")

#: The Shared group's caption: what it is and what it does, in one line.
SHARED_TITLE = "Shared — applies to every Book and overrides its own value"

#: Spacing, identical to the Cover, TTS and Converter panels' own constants:
#: the approved Cover UI is the concrete visual reference for every tool
#: interior (maintainer ruling 2026-09-28), so these are copied, not re-chosen.
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

#: The shared progress bar defaults to 240 px; the job area sits beside the two
#: operation buttons, so a shorter bar keeps that row inside the minimum.
PROGRESS_BAR_LENGTH = 160

#: In the tight density the status line sits beside the progress bar; a long
#: message (the missing-FFmpeg warning) wraps there instead of widening the row.
TIGHT_STATUS_WRAP = 170


# ---------------------------
# Utilities
# ---------------------------


def _remembered_dir(key: str) -> Path:
    """The saved folder for ``key`` while it is reachable, else the home dir (never erased)."""
    return settings.remembered_dir(key)


# The proven FFmpeg helpers moved to ``mp3_processing`` at Phase 7 of the
# focused MP3 redesign, where the Write ID3 engine shares them. They are
# re-exported here under their original names for every existing caller.
from mp3.mp3_processing import (  # noqa: E402,F401
    add_silence_to_mp3,
    concat_mp3s_fast,
    concat_wavs_to_mp3,
    ensure_ffmpeg_available,
    ffmpeg_escape_listfile_path,
    ffprobe_duration_seconds,
    make_silence_wav,
    normalize_to_wav,
    run_ff,
    save_error_log,
    seconds_to_hms,
    trim_from_end_mp3,
    write_concat_listfile,
)


# ---------------------------
# One attempt at one frozen run
# ---------------------------


def _identifier(text: str) -> str:
    """A stage name the shared event vocabulary accepts: no whitespace."""
    return "-".join(str(text).split()) or "processing"


def _one_line(text: str) -> str:
    """A display-safe message: the engine's line, with any break folded away."""
    return " ".join(str(text).splitlines()).strip()


class _RunProjection:
    """Projects the engine's ``ProcessingEvent`` lines into shared job events.

    Built on the main thread from the frozen plan, called on the **worker**
    thread by the engine, and it touches nothing but the reporter — which only
    hands typed events to the queue the adapter drains. The engine never learns
    a reporter exists; this is the one translation, and the engine's vocabulary
    (``kind``) is what it reads, never the message text.

    Progress is one determinate count for the whole batch: every track the
    attempt will process is one unit and every Book's finalisation — publish,
    or combine-tag-timestamps-publish — is one more. The stage is the Book
    (``book-<position>``) and the current item the real occurrence, which is
    what the panel's status line turns into ``Book 2 of 10 — Track 14 of 32``.
    """

    def __init__(self, reporter, plan: mp3_plan.RunPlan, *, retry_items=None) -> None:
        self._reporter = reporter
        books = [book for book in plan.books
                 if retry_items is None or book.book_id in retry_items]
        self.count = len(books)
        self._position = {book.book_id: index for index, book in enumerate(books, start=1)}
        self._published_dir = {book.book_id: book.published_dir for book in plan.books}
        self._offset: dict[str, int] = {}
        self._units: dict[str, int] = {}
        total = 0
        for book in books:
            units = (len(book.tracks) if retry_items is None
                     else len(tuple(retry_items[book.book_id]))) + 1
            self._offset[book.book_id] = total
            self._units[book.book_id] = units
            total += units
        self.total = total
        self._started: dict[str, int] = {}
        #: The Books whose processing began (their "started" line), for telling a Book a Cancel stopped part-way
        #: from one never reached (ACT72-004). Written on the worker, read on the main thread after the terminal event.
        self.began: set[str] = set()

    def stage_of(self, book_id: str) -> str:
        return f"book-{self._position.get(book_id, 0)}"

    def __call__(self, event: mp3_processing.ProcessingEvent) -> None:
        reporter = self._reporter
        book_id = event.book_id
        stage = self.stage_of(book_id)
        message = _one_line(event.message)
        kind = event.kind
        if kind == "book":
            self.began.add(book_id)
            reporter.stage_changed(stage, message)
            reporter.progress(self._offset.get(book_id, 0), self.total, stage=stage)
        elif kind == "track":
            started = self._started.get(book_id, 0)
            self._started[book_id] = started + 1
            reporter.current_item(event.occurrence_id, message)
            reporter.progress(self._offset.get(book_id, 0) + started, self.total,
                              item_id=event.occurrence_id, stage=stage)
        elif kind == "kept":
            reporter.technical(message)
        elif kind == "failure":
            reporter.failure(message, event.detail, item_id=event.occurrence_id,
                             stage=_identifier(event.stage))
            if event.occurrence_id is None:
                self._finish(book_id)
        elif kind == "completed":
            location = self._published_dir.get(book_id)
            if location is not None:
                reporter.output_location(location, message)
            else:  # pragma: no cover - every planned Book has a published dir
                reporter.warning(message)
            self._finish(book_id)
        elif kind == "failed":
            reporter.warning(message, event.detail)
            self._finish(book_id)
        elif kind == "warning":
            reporter.warning(message, event.detail)
        else:
            detail = message if not event.detail else f"{message}\n{event.detail}"
            reporter.technical(detail)

    def _finish(self, book_id: str) -> None:
        if book_id not in self._offset:
            return
        reporter = self._reporter
        reporter.progress(self._offset[book_id] + self._units[book_id], self.total,
                          stage=self.stage_of(book_id))


class _Preparation:
    """One accepted press of Write ID3 Tags or Combine, from the click until its plan is adopted or it ends (v0.8.2).

    Reserving the run and planning every track used to happen inside the button's Tk callback; at 2,341 tracks that
    froze the window for 20 minutes before anything was shown. Now the press freezes its inputs here, on Tk -- the
    immutable workspace snapshot and observation store, the Plan 6 capture, the stable Book numbers, the output
    configuration -- and one preparation worker reserves and plans from them alone. It reads no widget and no Tk
    variable, and talks back only through the panel's preparation queue.

    This is not a job controller: the operation still gets exactly one ``JobController``, created when the plan is
    adopted. Cancelling a preparation is this record's own ``threading.Event``, seen by the worker at every
    :meth:`checkpoint` (between inputs, tracks and Books) through the shared ``ConversionCancelled``.

    **Who owns the reservation.** The worker, from the moment it reserves until :meth:`offer` hands the finished plan
    over; if the offer is refused (Cancel or Close came first) or planning fails, the worker releases the still-empty
    run itself. Once offered, the panel owns it: :meth:`adopt` takes it for the conversion, or :meth:`withdraw` takes it
    back so the panel releases it. The lock makes offer, adopt and withdraw one decision each, so exactly one side
    releases a run and a plan nobody adopted can never start media.
    """

    def __init__(self, *, label: str, operation, workspace, store, capture, numbers, run_config,
                 book_count: int, track_count: int) -> None:
        self.label = label
        self.operation = operation
        self.workspace = workspace
        self.store = store
        self.capture = capture
        self.numbers = dict(numbers)
        self.run_config = run_config
        self.book_count = book_count
        self.track_count = track_count
        self.cancel_requested = threading.Event()
        self._lock = threading.Lock()
        self._offered = None
        self._handed_over = False

    def checkpoint(self) -> None:
        """The worker's cooperative stop: raises once Cancel or Close asked for it."""
        if self.cancel_requested.is_set():
            raise ConversionCancelled("preparation cancelled")

    def offer(self, plan) -> bool:
        """Worker: hand the finished plan to the panel. False when the panel no longer wants it.

        Once only: a second offer for the same press (a replayed worker body) is refused, so its worker releases its
        own run instead of replacing -- and leaking -- the run already handed over.
        """
        with self._lock:
            if self.cancel_requested.is_set() or self._handed_over:
                return False
            self._handed_over = True
            self._offered = plan
            return True

    def adopt(self):
        """Panel: take the offered plan to run it, or ``None`` when there is none or Cancel came first."""
        with self._lock:
            if self.cancel_requested.is_set():
                return None
            plan, self._offered = self._offered, None
            return plan

    def withdraw(self):
        """Panel: stop wanting this preparation. Returns an offered plan the caller must now release, if any."""
        with self._lock:
            self.cancel_requested.set()
            plan, self._offered = self._offered, None
            return plan


class _PreparationMessage:
    """What the preparation worker tells the panel: ``progress``, ``prepared``, ``cancelled``, ``refused`` or
    ``fault``. Exactly one non-progress message per preparation, always the last it sends."""

    __slots__ = ("preparation", "kind", "text", "detail", "done", "total")

    def __init__(self, preparation: _Preparation, kind: str, *, text: str = "", detail: str = "",
                 done: int = 0, total: int = 0) -> None:
        self.preparation = preparation
        self.kind = kind
        self.text = text
        self.detail = detail
        self.done = done
        self.total = total


class _AttemptNotStarted(Exception):
    """An attempt's setup failed before anything changed hands (v0.8.2 R1).

    Raised by ``_start_attempt`` only while the previous job area, run, result and Retry Failed are all still exactly
    as they were, so the caller can report it and carry on as if the press had been refused.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class _PendingImport:
    """A committed import whose files' tags are being read off Tk (v0.8.2 Checkpoint 6).

    Nothing of it is in the workspace yet: the Books (Import Folder) or tracks (Add Files) are made from the committed
    snapshot only when :attr:`readback` has finished, through the unchanged workflow functions. ``target`` is the Book
    Add Files was pressed on, by identity, so navigating while the tags are read cannot send the files elsewhere.
    ``replacing`` is, for Import Folder, the Books the user agreed to replace when they pressed it (v0.8.2
    qualification): the import replaces them only if the workspace still holds exactly those Books.
    """

    __slots__ = ("readback", "kind", "outcome", "target", "replacing", "shown")

    def __init__(self, readback: source_readback.SourceReadback, kind: str | None, outcome: ImportOutcome,
                 target: str, replacing: tuple | None = None) -> None:
        self.readback = readback
        self.kind = kind
        self.outcome = outcome
        self.target = target
        self.replacing = replacing
        self.shown = -1


class _Attempt:
    """The facts one attempt shares between the worker and the main thread.

    Everything here is frozen before the worker starts, except ``results``:
    the worker appends each Book's settled ``RunResult`` there — through the
    engine's own per-Book callback, in frozen order — as soon as the Book
    returns, before the next Book's first event and before the terminal
    event. The main thread only ever reads it while draining an event, so
    by the time the terminal event is drained every result is there.
    """

    def __init__(self, *, label: str, plan: mp3_plan.RunPlan, run_id: str, number: int,
                 controller, reporter, retry_items=None, prior=None, superseded=None) -> None:
        self.label = label
        self.plan = plan
        #: v0.8.2: the previous run's plan this one replaced, whose kept staging no Retry Failed can reach any more.
        #: Its private staging is removed by this attempt's worker before the engine starts, off the Tk thread.
        self.superseded = superseded
        self.run_id = run_id
        self.number = number
        self.controller = controller
        self.reporter = reporter
        self.retry_items = None if retry_items is None else dict(retry_items)
        self.prior = prior
        self.books = tuple(book for book in plan.books
                           if retry_items is None or book.book_id in retry_items)
        self.projection = _RunProjection(reporter, plan, retry_items=self.retry_items)
        self.results: list[tuple[str, job_control.RunResult]] = []
        self.report = None
        #: Read and written only under the panel's staging lock (v0.7.2, ACT72-019): ``running`` until the worker has
        #: released what this attempt cannot retry; ``abandoned`` once no Retry Failed can reach the plan.
        self.running = True
        self.abandoned = False

    def record(self, report) -> None:
        """The engine's per-Book callback. Worker thread; append only."""
        self.results.append((report.book_id, report.result))

    def settled(self, book_id: str):
        for candidate, result in tuple(self.results):
            if candidate == book_id:
                return result
        return None

    def position_of(self, book_id: str) -> int:
        for index, book in enumerate(self.books, start=1):
            if book.book_id == book_id:
                return index
        return 0

    def track_context(self, item_id: str | None) -> str:
        if not item_id:
            return ""
        for book in self.plan.books:
            track = book.track_for(item_id)
            if track is not None:
                return f"Track {track.position} of {len(book.tracks)}"
        return ""


# ---------------------------
# GUI
# ---------------------------


def _layout_hints(theme) -> dict:
    """The panel's composition, read off the theme bundle with its own defaults.

    The defaults are the compact composition (v0.6.6 Phase 6: the outer pad
    and section gap are the Cover/TTS/Converter constants; the output hint
    yields in the import band and the entries ask for 8 characters and
    stretch -- which is what keeps Book Settings inside the real launcher's
    920x600 content area). A theme whose
    ``metrics`` carry the panel hints (the aqua bundle) overrides them; one
    without ``metrics`` at all (the classic branch) or with other keys only
    (the Windows design system, a test theme) changes nothing. Presentation
    only: nothing read here reaches the model, the plan or the engines.
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
        # The fields' own gap (6): at 920x600 Book Settings is full to the
        # pixel, and the 2 px this returns are what "Choose…" needed to show
        # its whole label (v0.7.2 Phase 5, ACT72-020). Aqua's metrics keep 8.
        "artwork_gap": int(metrics.get("artwork_gap", 6)),
        # v0.6.4 Phase 13 (macOS parity): Clear All Imports widened this band
        # past the aqua host, squeezing the import status bar to one pixel.
        "import_band_layout": str(metrics.get("import_band_layout", "compact")),
        # v0.8.x P1B remediation (ACT72-078): "fit" shortens a long Book label
        # so the navigator's "(X of Y)" is never cut. Windows keeps "natural".
        "navigator_heading": str(metrics.get("navigator_heading", "natural")),
    }


def _label_wraps(hints: Mapping[str, object], fields) -> dict[str, int] | None:
    """Per-field label widths for the metadata surface, or ``None`` for none.

    The Time label is the long one and takes the wide budget; every other
    label takes the narrow budget, which keeps it near its entry's width.
    Without a wide budget in the hints nothing wraps, exactly as before.
    """
    wide = hints.get("label_wrap")
    if wide is None:
        return None
    narrow = hints.get("label_wrap_narrow")
    wraps = {}
    for key in fields:
        if key == "time_delta":
            wraps[key] = int(wide)
        elif narrow is not None:
            wraps[key] = int(narrow)
    return wraps


class _ArtworkControl:
    """Book Artwork: a caption, a small preview and Choose / Clear. MP3-owned.

    Deliberately **not** a ``SharedMetadataSurface`` field: artwork is a file, not
    a line of text, so it gets its own control drawn once for Shared and once for
    the current Book. Whether the Book copy is enabled is the model's Decision 20B
    answer (``disabled_fields``) combined with the run lock, in the same two-reason
    shape the surface uses — clearing one reason never wrongly enables a control
    the other still holds.

    The preview is a display-only thumbnail scaled in memory; the selected file
    is never opened for writing, resized or rewritten.
    """

    def __init__(self, parent, *, caption: str, theme, shared: bool,
                 on_choose, on_clear, natural: bool = False) -> None:
        self.caption = caption
        self.path = ""
        self.has_preview = False
        self._overridden = False
        self._locked = False
        self._closed = False
        self._image = None
        self._on_choose = on_choose
        self._on_clear = on_clear

        self.frame = ttk.Frame(
            parent, style=style_name(theme, "shared_surface" if shared else "surface"))
        self.caption_label = ttk.Label(
            self.frame, text=caption,
            style=style_name(theme, "shared_label" if shared else "label"))
        self.preview = ttk.Label(
            self.frame, text="(none)", anchor="center", width=6,
            style=style_name(theme, "shared_secondary" if shared else "secondary_label"))
        # Fixed character widths keep the pair compact; a theme whose native
        # buttons carry their own bezel padding (aqua) asks for the natural
        # width instead. ``theme`` is the appearance bundle and only styles.
        # Each takes its label's own width (ttk width 0), never a fixed
        # allocation: a width of 7 cut "Choose…" to "Choose." (v0.7.2 Phase 5,
        # ACT72-020; the same correction as artwork.m4b_artwork_ui).
        self.btn_choose = ttk.Button(self.frame, text="Choose…",
                                     style=action_style(theme, "artwork_choose"),
                                     command=self._choose,
                                     **({} if natural else {"width": 0}))
        self.btn_clear = ttk.Button(self.frame, text="Clear",
                                    style=action_style(theme, "artwork_clear"),
                                    command=self._clear,
                                    **({} if natural else {"width": 0}))
        # Two rows only -- caption, then the two buttons side by side -- with
        # the preview spanning both on the left, so the control is no taller
        # than a label and an entry and the band it sits in stays compact.
        self.preview.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 6))
        self.caption_label.grid(row=0, column=1, columnspan=2, sticky="w")
        self.btn_choose.grid(row=1, column=1, sticky="ew")
        self.btn_clear.grid(row=1, column=2, sticky="ew", padx=(4, 0))

    def _choose(self) -> None:
        if not self._closed and self._usable():
            self._on_choose()

    def _clear(self) -> None:
        if not self._closed and self._usable():
            self._on_clear()

    @property
    def enabled(self) -> bool:
        """Usable only when **neither** reason holds — override or run lock."""
        return not (self._overridden or self._locked)

    def _usable(self) -> bool:
        return self.enabled

    def set_path(self, path: str) -> None:
        """Show *path*'s preview, or the no-artwork placeholder for blank.

        The thumbnail is the artwork service's, scaled in memory; the stored
        value stays the source path and the source is never touched. A path
        that cannot be previewed is shown as such rather than dropped: the
        selection is the user's until they change it.
        """
        self.path = str(path or "")
        self._image = None
        self.has_preview = False
        if not self.path:
            self.preview.configure(image="", text="(none)")
            return
        if ImageTk is None:
            self.preview.configure(image="", text="(no preview)")
            return
        try:
            thumb = mp3_artwork.preview_image(self.path, PREVIEW_MAX)
            self._image = ImageTk.PhotoImage(thumb)
            self.preview.configure(image=self._image, text="")
            self.has_preview = True
        except (mp3_artwork.ArtworkError, Exception):
            self.preview.configure(image="", text="(no preview)")

    def set_enabled(self, enabled: bool) -> None:
        """The Shared-override reason. ``set_locked`` is the run reason."""
        self._overridden = not bool(enabled)
        self._apply_state()

    def set_locked(self, locked: bool) -> None:
        self._locked = bool(locked)
        self._apply_state()

    def _apply_state(self) -> None:
        state = "normal" if self._usable() and not self._closed else "disabled"
        for button in (self.btn_choose, self.btn_clear):
            try:
                button.configure(state=state)
            except tk.TclError:
                pass

    def close(self) -> None:
        self._closed = True
        self._apply_state()
        self._image = None


class MP3ToolUI(ttk.Frame):
    """The MP3 Tool as an embeddable frame: a multi-book workspace."""

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
        reader=None,
        bridge=None,
        appearance_bundle: dict | None = None,
    ):
        """Build the panel.

        Every keyword is a seam the tests drive instead of a real dialog, clock,
        thread or tag reader — the injection points the Converter, Cover and TTS
        panels already expose. Production passes none of them. ``thread_factory``
        makes both the import scan's thread and the processing worker's;
        ``bridge`` is the one ``LoggerBridge`` every run's event stream forwards
        its technical lines through into the session log.

        ``appearance_bundle`` (v0.6.6 Phase 6) is the seam Cover, TTS and the
        Converter take: the production default reads the remembered Light/Dark
        setting, and the suite may inject an exact bundle. Every widget is
        styled from it. ``theme`` is the platform bundle and now supplies only
        the composition hints (``_layout_hints``) -- the aqua arrangement.
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
        self._ids = IdFactory("mp3-") if id_factory is None else id_factory
        self._reader = wf.read_source_tags if reader is None else reader
        self._choose_files = self._ask_files if choose_files is None else choose_files
        # The folder an import dialog chose, held until its import settles (v0.8.1).
        self._pending_input_dir: str | None = None
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

        # --- the workspace: the Plan 6 snapshot and the Phase 3 store -------- #
        # The one mutable reference to the current immutable workspace lives
        # here. Every edit asks a model operation and renders the value back;
        # nothing below mutates a book in place.
        self.workspace: WorkspaceSnapshot = wf.new_workspace(id_factory=self._ids)
        self.store = wf.ObservationStore()
        # The user-facing Book number, by stable id. Assigned once, the first
        # time a Book appears in the workspace, and never reused while that
        # workspace lives: remove Book 1 of three and the survivors stay Book 2
        # and Book 3. A folder import replaces every Book, so numbering starts
        # again at 1 for the new set. This is a display fact hung off the real
        # identity — never a key anything else is stored by.
        self.book_numbers: dict[str, int] = {}
        #: The most recently frozen run plan: what the worker ran and what a
        #: Retry Failed re-runs. Nothing here reads it back into the widgets.
        self.last_plan: mp3_plan.RunPlan | None = None
        #: The current or most recent attempt, and the frozen batch result it
        #: (or its predecessor) settled into. Retry Failed reads only these.
        self._attempt: _Attempt | None = None
        self._settled: WorkspaceRunResult | None = None
        self._busy = False
        #: v0.8.2: the accepted press still being prepared off the Tk thread, or ``None``. While it is set the panel
        #: is running (no second press, no Retry Failed, no Clear All Imports) but the previous attempt, its result
        #: and its job area stay exactly as they were, so a refused or cancelled preparation leaves them reachable.
        self._preparing: _Preparation | None = None
        #: The one queue the preparation worker writes and the pump's preparation drain reads. Never replaced.
        self._prep_q: queue.SimpleQueue = queue.SimpleQueue()
        self._preparations = 0
        #: v0.8.2 R1: names the short-lived workers that release an unused, empty run off the Tk thread.
        self._releases = 0
        self._attempts = 0
        #: Private staging lives exactly as long as a Retry Failed can reach it (v0.7.2, ACT72-019 / ACT72-037). The
        #: worker releases what its attempt cannot retry; the main thread releases the rest once nothing can retry the
        #: plan. This lock keeps the two from overlapping. A plain mutex around a few filesystem calls, not a signal.
        self._staging_lock = threading.Lock()
        self._rendering = False

        # --- the shared importing foundation ----------------------------- #
        # One pump owns every scheduled callback; the scan poller rides it.
        # The manager is a *scratch* commit target for the shared coordinator:
        # a folder scan or a file selection is committed through it, projected
        # into Books, and the manager is cleared before the next import. The
        # Books are the only list; the manager is never rendered.
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
        # v0.8.2 Checkpoint 6: the committed import whose tags a worker is reading, and how many were started.
        self._pending_import: _PendingImport | None = None
        self._readbacks = 0
        # v0.8.2 qualification: the Books an Import Folder in progress was pressed to replace (None otherwise).
        self._replacing: tuple | None = None

        # Where the next run will go, shown read-only. Reserving the numbered
        # run folder is the processing phases' job; nothing is created here.
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
        self._book_options_lock = self._ButtonLock(
            self.btn_write_id3, self.btn_combine, self.check_auto_number,
            self.entry_start_number)
        # The Chapter Titles box locks with the run, as the Maker's and the Editor's do (v0.7.2, ACT72-014): the run
        # froze the titles at its start, so an edit made during it looked live and reached nothing.
        self._chapters_lock = self._TextLock(self.chapter_text)
        self._install_jobs(IDLE_RUN_ID, ())
        self._pump.add_drain(self._drain_preparation)
        self._pump.add_drain(self._drain_readback)

        self.render()
        if not ensure_ffmpeg_available():
            self.status.set_status(
                "WARNING: ffmpeg/ffprobe not found. Run the setup launcher to install it.")
        else:
            self.status.set_status(STATUS_READY)
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

        v0.6.6 Phase 6: the dense Family-B hierarchy on the approved compact
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
        # ones -- Tracks & Run, whose track list and Chapter Titles scroll, and
        # Activity, whose log scrolls -- absorb a short window. Nothing else
        # yields, so no required control falls off the bottom and no
        # whole-panel scrollbar is needed.
        self.rowconfigure(0, weight=0)   # 1. Import & Books
        self.rowconfigure(1, weight=0)   # 2. Book Settings
        self.rowconfigure(2, weight=3)   # 3. Tracks & Run -- lists scroll
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
        # undoes, in the shared destructive treatment (v0.6.4 Phase 12 amendment).
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
            # right whatever its anchor, which cut off the run folder -- the
            # part that says where the run lands -- so the label asks for
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
            show_header=False, entry_width=hints["entry_width"], field_gap=6,
            wraplength=_label_wraps(hints, (key for key, _label in text_fields)),
            shared_title=SHARED_TITLE,
            book_title="Current Book",
            on_shared_change=self.on_shared_change,
            on_book_change=self.on_book_change)
        self.surface.frame.grid(row=0, column=0, sticky="ew")
        field_columns = len(text_fields)
        # Widget padding, not a style: two stacked groups at the section's
        # own padding would spend the height the track list needs at the
        # supported minimum. The style (and its colours) is unchanged.
        for group in (self.surface.shared_frame, self.surface.book_frame):
            group.configure(padding=(6, 2))

        # Artwork sits beside the four text fields in each group. It is this
        # panel's own control, not a surface field.
        natural = hints["artwork_buttons"] == "natural"
        self.shared_artwork = _ArtworkControl(
            self.surface.shared_frame, caption=wf.FIELD_LABELS["artwork"],
            theme=bundle, shared=True, natural=natural,
            on_choose=self.choose_shared_artwork, on_clear=self.clear_shared_artwork)
        self.shared_artwork.frame.grid(row=0, column=field_columns, rowspan=2,
                                       sticky="nw", padx=(hints["artwork_gap"], 0))
        self.book_artwork = _ArtworkControl(
            self.surface.book_frame, caption=wf.FIELD_LABELS["artwork"],
            theme=bundle, shared=False, natural=natural,
            on_choose=self.choose_book_artwork, on_clear=self.clear_book_artwork)
        # Where the Book-only options go: beside the mixed-source markers,
        # under Time and Artwork -- the two columns no marker uses -- so
        # Current Book is one row shorter; or, where aqua's wrapped labels make
        # those columns too narrow, on a row of their own beneath (the
        # accepted macOS arrangement).
        beside = hints["label_wrap"] is None
        self.book_artwork.frame.grid(row=0, column=field_columns,
                                     rowspan=2 if beside else 4,
                                     sticky="nw", padx=(hints["artwork_gap"], 0))

        # Mixed-source markers, one under each observed scalar of the Book.
        self.mixed_labels: dict[str, ttk.Label] = {}
        for column, key in enumerate(wf.SCALAR_FIELDS):
            marker = ttk.Label(self.surface.book_frame, text="",
                               style=st("warning_label"))
            marker.grid(row=2, column=column, sticky="w")
            self.mixed_labels[key] = marker

        # Auto-number | Start # | status, on one row of the Book group.
        options = ttk.Frame(self.surface.book_frame, style=st("surface"))
        if beside:
            options.grid(row=2, column=len(wf.SCALAR_FIELDS),
                         columnspan=field_columns + 1 - len(wf.SCALAR_FIELDS),
                         sticky="w", pady=(2, 0))
        else:
            options.grid(row=3, column=0, columnspan=field_columns, sticky="ew",
                         pady=(2, 0))
        self.book_options = options
        self.var_auto_number = tk.BooleanVar(master=self, value=wf.DEFAULT_AUTO_NUMBER)
        self.check_auto_number = ttk.Checkbutton(
            options, text="Auto-number tracks", variable=self.var_auto_number,
            style=st("checkbutton"), command=self.on_auto_number)
        self.check_auto_number.grid(row=0, column=0, sticky="w")
        ttk.Label(options, text="Start # (blank → 1):", style=st("label")).grid(
            row=0, column=1, sticky="w", padx=(12, 4))
        self.var_start_number = tk.StringVar(master=self, value="")
        self.entry_start_number = ttk.Entry(
            options, textvariable=self.var_start_number, width=6, style=st("entry"))
        self.entry_start_number.grid(row=0, column=2, sticky="w")
        self._start_trace = self.var_start_number.trace_add(
            "write", lambda *_a: self.on_start_number())
        ttk.Label(options, text="Status:", style=st("label")).grid(
            row=0, column=3, sticky="w", padx=(12, 4))
        # On the Book group's surface, like every other label in it.
        self.status_label = ttk.Label(options, text=STATUS_READY, style=st("label"))
        self.status_label.grid(row=0, column=4, sticky="w")

        # -- 3. Tracks & Run: tracks | chapter titles, then the operations ------ #
        run = self.run_section
        run.columnconfigure(0, weight=1)
        run.rowconfigure(0, weight=1)
        middle = ttk.Frame(run, style=st("surface"))
        middle.grid(row=0, column=0, sticky="nsew")
        middle.columnconfigure(0, weight=3)
        middle.columnconfigure(1, weight=2)
        middle.rowconfigure(1, weight=1)
        self.tracks_caption = ttk.Label(middle, text="MP3 Tracks (this Book)",
                                        style=st("label"))
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
        # v0.8.2 R1: a paste, a drop or an input method changes the box without a key release. Tk's modified flag
        # reports every change, so the model hears of it on the next event-loop turn; until then
        # :meth:`flush_pending_editor_state` is what keeps it (any callback that can redraw the box calls it first).
        self.chapter_text.bind("<<Modified>>", self._on_chapter_modified)
        self._suspend_chapters = False
        #: What the box showed when the panel last wrote it, and the Book it showed it for. A difference between the
        #: box and the baseline is an edit the model has not heard of yet; it belongs to that Book and no other.
        self._chapter_baseline = ""
        self._chapter_book_id: str | None = None

        self.run_separator = ttk.Separator(run, orient=tk.HORIZONTAL,
                                           style=st("separator"))
        self.run_separator.grid(row=1, column=0, sticky="ew", pady=(6, 5))

        # The two operations, then the shared job area beside them: one
        # adapter per run, installed into column 2 by ``_install_jobs``. Both
        # operations are run actions of equal rank, so both take the compact
        # button with ttk's restrained accent outline -- the treatment TTS's
        # Start, Cover's Resize and the Converter's Convert get -- rather than
        # two filled primaries competing for one "primary action" (§5).
        self.actions = ttk.Frame(run, style=st("surface"))
        self.actions.grid(row=2, column=0, sticky="ew")
        self.actions.columnconfigure(2, weight=1)
        self.btn_write_id3 = ttk.Button(
            self.actions, text="Write ID3 Tags", default="active",
            style=self._action_style("run"), command=self.write_id3_tags)
        self.btn_combine = ttk.Button(
            self.actions, text="Combine MP3s → One MP3", default="active",
            style=self._action_style("run"), command=self.combine_mp3s)
        if hints["actions_layout"] == "row":
            self.btn_write_id3.grid(row=0, column=0, sticky="nw")
            self.btn_combine.grid(row=0, column=1, sticky="nw", padx=(6, 12))
            self._jobs_rowspan = 1
        else:
            # Stacked (aqua): the two operations in one column beside the job
            # area, where native buttons are too wide to sit side by side.
            self.btn_write_id3.grid(row=0, column=0, sticky="new", padx=(0, 12))
            self.btn_combine.grid(row=1, column=0, sticky="new",
                                  padx=(0, 12), pady=(4, 0))
            self._jobs_rowspan = 2

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
                                             details_label="Detailed",
                                             limit=LOG_LIMIT)
        self.log.frame.grid(row=1, column=0, sticky="nsew")

        self.bind("<Configure>", self._on_panel_configure, add="+")

    def _install_jobs(self, run_id: str, item_ids) -> None:
        """Point the shared job area at one run. Main thread only.

        A run owns its event stream, and a stream cannot be rebound, so a new
        run -- or a new attempt at the same run -- gets a new adapter in the
        same place. The retired one is closed first, which drops its drain, so
        the one pump keeps exactly one job drain however many runs a session
        performs. The log view is **not** the adapter's: it is the panel's one
        region, handed in, and it keeps every earlier run's lines.

        Retry Failed's availability is not decided here or anywhere in this
        panel: a fresh adapter holds no result, and the control is offered only
        once a settled ``WorkspaceRunResult`` reporting a retryable Book is
        handed to it *and* the run reached ``COMPLETED_WITH_FAILURES``.
        """
        # v0.8.2 R1 -- transactional, in three steps that cannot be confused for one another:
        #
        # 1. BUILD. The new adapter is constructed, dressed, registered and laid out completely while the previous
        #    one is still the live job area and has not been touched. If anything here raises, the half-built
        #    adapter is taken down (its pump drain and its frame; the shared constructor undoes its own failure the
        #    same way) and the exception goes to the caller with the previous job area -- stream, result, locks,
        #    Retry Failed -- exactly as it was. ``self.jobs`` is still the previous adapter, and it is a live one.
        # 2. SWAP. Plain attribute assignments, which cannot fail: from here the new adapter is the job area.
        # 3. RETIRE. The previous adapter no longer owns anything, so closing it and taking its frame down is
        #    cleanup (``_retire_adapter``): a Tk error there is reported and the frame is taken out of the layout,
        #    and it can neither undo the swap nor stop the run the new adapter belongs to. (The second independent
        #    review found the first R1 version closing the previous adapter *before* the swap: an error destroying
        #    its frame then left a closed adapter installed, the navigator locked and both Start buttons disabled.)
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
                # The shared compact bundle, exactly as Cover's, TTS's and the
                # Converter's job areas use it.
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
            # Per-instance restyling, exactly as Cover, TTS and the Converter do it:
            # the shared indicator stays generic for every panel that has not
            # adopted the compact system, but here an unstyled native frame would
            # be a light island in Dark. Aqua names inherit native controls.
            status = adapter.status
            status.indicator.frame.configure(style=style_name(bundle, "card"))
            status.indicator.bar.configure(style=style_name(bundle, "progressbar"),
                                           length=PROGRESS_BAR_LENGTH)
            status.indicator.label.configure(style=style_name(bundle, "secondary_label"))
            status.label_status.configure(style=style_name(bundle, "secondary_label"))
            adapter.register_inputs(self.navigator, self._tracks_lock, self._import_lock)
            adapter.register_options(self.surface, self.shared_artwork, self.book_artwork,
                                     self._book_options_lock, self._chapters_lock)
            # Laid out in the previous adapter's cell, above it (a newer sibling stacks higher), before the swap.
            adapter.frame.grid(row=0, column=2, rowspan=self._jobs_rowspan, sticky="ew")
            adapter.controls.frame.grid_configure(sticky="e")
            self._arrange_status(adapter)
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
                logging_setup.get_logger().warning("MP3 Tool: the previous job area was not fully retired: %s",
                                                   problem)
                self._say("The previous job area could not be fully removed; it was taken out of the layout.",
                          f"Previous job area not fully retired: {problem}")
        self.jobs.render()

    def _retire_adapter(self, adapter) -> tuple[str, ...]:
        """Close an adapter the panel does not (or no longer) own and take its frame down. Main thread; never raises.

        Cleanup, never a decision: whatever this meets, the caller's job area and run stay as they are. Each step is
        tried on its own, so one failure cannot skip the next -- ``close`` drops the adapter's pump drain first thing
        (one pump, one job drain), and the frame is destroyed. A frame Tk will not destroy is taken out of the
        layout instead, and failing that lowered beneath its siblings, so it cannot sit over the live job area.
        Returns one line per step that failed, for the caller to report once; nothing is retried or looped.
        """
        problems: list[str] = []
        try:
            adapter.close()
        except Exception as exc:  # noqa: BLE001 - reported by the caller; the frame must still go
            problems.append(f"close: {type(exc).__name__}: {exc}")
            try:
                self._pump.remove_drain(adapter.drain)  # ``close`` does this first; make sure of it regardless
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
            # A frame that outlives its adapter must not keep animating: an indeterminate "Preparing job…" bar
            # re-arms a Tk timer for as long as its widget exists.
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
        value, chapter title, track order, log line, progress or running job
        moves.
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
        """Hold Tracks & Run and Activity at their measured floors.

        A short window takes its height from these two rows only (the other two
        have no weight); the minimum sizes stop either from being squeezed below
        the height its buttons, job area and chrome need plus the floor rows of
        its list or log, so no control inside is ever clipped.
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
        rather than above it; the job status on two lines), and only then the
        flexible regions' lower floor. Nothing is hidden that can be used.
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
        self.surface.book_frame.grid_configure(pady=(3 if tight else 8, 0))
        for group in (self.surface.shared_frame, self.surface.book_frame):
            group.configure(padding=(4, 0, 4, 1) if tight else (6, 2))
        self.book_options.grid_configure(pady=(0 if tight else 2, 0))
        for caption in (self.tracks_caption, self.chapters_caption):
            caption.grid_configure(pady=(0, 0 if tight else 2))
        self.track_buttons.grid_configure(pady=(small, 0))
        if tight:
            self.run_separator.grid_remove()
            self.actions.grid_configure(pady=(small, 0))
            # Clear Log beside the log view, level with its tabs.
            self.activity_note.grid_remove()
            self.log.frame.grid_configure(row=0, column=0, rowspan=2)
            self.activity_bar.grid_configure(row=0, column=1, sticky="ne",
                                             padx=(6, 0), pady=0)
        else:
            self.run_separator.grid()
            self.actions.grid_configure(pady=0)
            self.activity_note.grid()
            self.log.frame.grid_configure(row=1, column=0, rowspan=1)
            self.activity_bar.grid_configure(row=0, column=0, sticky="ew",
                                             padx=0, pady=(0, 4))
        self._arrange_status()
        self._render_mixed()
        self._set_row_floors()

    def _arrange_status(self, jobs=None) -> None:
        """The shared status view's lines: three, or two in the tight density.

        Grid positions and wrap only -- the same labels, bound to the same
        variables the shared view writes. Regular is the view's own layout:
        progress, then stage and ETA, then the status line. Tight sets the
        status beside the progress bar and the stage beside the ETA, one line
        fewer beside the two operations.

        *jobs* (v0.8.2 R1) is an adapter being built that is not the panel's
        yet; with none given, the installed one.
        """
        if jobs is None:
            jobs = getattr(self, "jobs", None)
        if jobs is None:
            return
        view = jobs.status
        view.frame.grid_configure(pady=(2 if self._tight else 4, 0))
        if self._tight:
            view.indicator.frame.grid_configure(row=0, column=0, columnspan=1, sticky="w")
            view.label_status.grid_configure(row=0, column=1, columnspan=2, sticky="w",
                                             padx=(8, 0))
            view.label_stage.grid_configure(row=1, column=0, columnspan=2, sticky="w")
            view.label_eta.grid_configure(row=1, column=2, columnspan=1, sticky="e")
            view.frame.columnconfigure(0, weight=0)
            view.frame.columnconfigure(1, weight=1)
            view.label_status.configure(wraplength=TIGHT_STATUS_WRAP)
        else:
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

    # -- lock seams for the panel's own buttons ---------------------------- #

    class _ButtonLock:
        """Registers a set of this panel's own buttons with the shared group."""

        def __init__(self, *buttons) -> None:
            self.buttons = buttons
            self.locked = False

        def set_locked(self, locked: bool) -> None:
            self.locked = bool(locked)
            for button in self.buttons:
                try:
                    button.configure(state="disabled" if locked else "normal")
                except tk.TclError:
                    pass

    class _TextLock:
        """The Chapter Titles box's run lock, as the Maker's and the Editor's (v0.7.2, ACT72-014)."""

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
            filetypes=[("MP3 files", "*.mp3"), ("All files", "*.*")]) or ())
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

    def artwork_filetypes(self) -> list:
        """The chooser filter, from the shared capability probe, never a list."""
        return mp3_artwork.artwork_filetypes()

    def _ask_artwork(self) -> str:
        chosen = filedialog.askopenfilename(
            parent=self, title="Select Book Artwork",
            initialdir=str(_remembered_dir(KEY_COVER_DIR)),
            filetypes=self.artwork_filetypes())
        return str(chosen or "")

    def _remember_cover_dir(self, chosen: str) -> None:
        """Shared and Book artwork share this tool's one artwork history, written only for accepted artwork."""
        folder = settings.selected_dir(chosen, is_file=True)
        if folder:
            settings.set(KEY_COVER_DIR, folder)

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
        """``Book <stable number>``, with the Album / folder hint when there is one.

        A long hint is elided so the heading beside the navigator buttons stays
        one readable line at the 920px minimum; the number, which is what keeps
        two Books apart, is never shortened.
        """
        number = self.book_numbers.get(book.book_id, "?")
        hint = self._describe(book)
        if len(hint) > HINT_LIMIT:
            hint = hint[:HINT_LIMIT - 1].rstrip() + "…"
        return f"Book {number} — {hint}" if hint else f"Book {number}"

    def _assign_book_numbers(self) -> None:
        """Number every Book that has none, in workspace order; forget the gone.

        When no current Book is numbered the set was replaced wholesale -- a
        folder import, or removing the last Book, which leaves the model's one
        fresh pristine Book -- so numbering starts again at 1: there is no
        survivor whose identity a reused number could blur. Otherwise a newcomer
        takes the next number after the highest ever given, and a removed
        Book's number is never handed to anyone else.
        """
        ids = [book.book_id for book in self.workspace.books]
        if not any(book_id in self.book_numbers for book_id in ids):
            self.book_numbers = {}
        highest = max(self.book_numbers.values(), default=0)
        for book_id in ids:
            if book_id not in self.book_numbers:
                highest += 1
                self.book_numbers[book_id] = highest
        # Forgetting the gone: their numbers stay retired because ``highest``
        # was taken before they were dropped.
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
        # v0.8.2 R1: whatever moved the model, the box is about to be redrawn from it; an edit it has not heard of
        # yet is committed to the Book it was typed for first, never painted over.
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
            self._render_tracks()
            self._render_chapters()
            self.var_auto_number.set(wf.auto_number_enabled(book))
            if self.var_start_number.get() != wf.start_number_text(book):
                self.var_start_number.set(wf.start_number_text(book))
            self._render_mixed()
            self._render_status()
        finally:
            self._rendering = False

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
        """Stored Chapter Titles text; until the user edits it, the defaults.

        Section 15.3: the editor is populated with each track's automatic Title
        on import. Those defaults are *displayed*, not stored — so reordering
        tracks re-orders the display, and a Book the user never edited keeps an
        empty configuration. The first real edit stores the whole box.
        """
        book = self.workspace.current
        if "chapter_titles" in book.configuration:
            return wf.chapter_titles_text(book)
        return "\n".join(wf.default_titles(book, self.store))

    def _render_chapters(self) -> None:
        # Never paints over an edit the model has not heard of: it is committed to its own Book first (v0.8.2 R1).
        self.flush_pending_editor_state()
        raw = self._chapter_display()
        self._chapter_baseline = raw
        self._chapter_book_id = self.workspace.current.book_id
        if raw == self.chapter_text.get("1.0", "end-1c"):
            return
        self._suspend_chapters = True
        try:
            # A locked box is still filled by the panel itself (a disabled Text ignores edits); its state is put back.
            state = str(self.chapter_text.cget("state"))
            self.chapter_text.configure(state="normal")
            self.chapter_text.delete("1.0", "end")
            if raw:
                self.chapter_text.insert("1.0", raw)
            # v0.8.2 R1: the panel's own repaint is not an edit, so it is not something Ctrl+Z may undo. Left on the
            # undo stack, one undo after a Book switch blanked the box and a second brought back the previous Book's
            # titles, which the next key release then stored on this Book. Undo history starts again at each repaint;
            # a box the repaint did not change (the early return above) keeps its history.
            self.chapter_text.edit_reset()
            self.chapter_text.configure(state=state)
        finally:
            self._suspend_chapters = False

    def _render_mixed(self) -> None:
        summary = wf.summary_for(self.workspace.current, self.store)
        mixed = wf.mixed_fields(summary)
        mark = MIXED_MARK_SHORT if self._tight else MIXED_MARK
        for key, marker in self.mixed_labels.items():
            marker.configure(text=mark if key in mixed else "")

    # -- read-back seams --------------------------------------------------- #

    def shared_field_keys(self) -> tuple:
        return self.surface.fields + ("artwork",)

    def book_status_text(self) -> str:
        return str(self.status_label.cget("text"))

    def mixed_text(self, name: str) -> str:
        return str(self.mixed_labels[name].cget("text"))

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
        """One Summary line of the panel's own, with its Detailed companion."""
        if not self._closed:
            self.log.append(line, detail or line)

    def clear_log(self) -> None:
        """Clear the visible log text. The history behind it is untouched:
        the run's event stream, the session log and the frozen result."""
        self._guard.require("clear_log")
        if not self._closed:
            self.log.clear()

    # ------------------------------------------------------------------ #
    # Navigator callbacks
    # ------------------------------------------------------------------ #

    # v0.8.2 R1: every callback that asks the model for a change first commits a Chapter Titles change no key release
    # reported yet (a paste, a drop, an input method) through :meth:`flush_pending_editor_state`, so the change it
    # asks for is computed from a workspace that already holds it: a duplicate copies it, a removal asks about it, a
    # Start freezes it. ``render`` repeats the flush as the safety net, so nothing redraws the box over it.

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
        self.flush_pending_editor_state()
        mutation = wf.set_book_field(self.workspace, field, raw)
        if mutation.changed:
            self.workspace = mutation.workspace
        self._render_light()

    def set_book_field(self, name: str, value) -> None:
        """Store one raw Book value and show it. The model owns the write."""
        self._guard.require("set_book_field")
        self.flush_pending_editor_state()
        self._apply(wf.set_book_field(self.workspace, name, value))

    def on_auto_number(self) -> None:
        if self._rendering:
            return
        self.flush_pending_editor_state()
        self._apply(wf.set_book_field(self.workspace, "auto_number",
                                      bool(self.var_auto_number.get())))

    def on_start_number(self) -> None:
        if self._rendering or self._closed:
            return
        self.flush_pending_editor_state()
        raw = self.var_start_number.get()
        if raw == wf.start_number_text(self.workspace.current):
            return
        mutation = wf.set_book_field(self.workspace, "start_number", raw)
        if mutation.changed:
            self.workspace = mutation.workspace
        self._render_light()

    def type_start_number(self, raw: str) -> None:
        self.var_start_number.set(raw)

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
        """Commit a Chapter Titles change the model has not heard of yet, to the Book it was typed for (v0.8.2 R1).

        **The one commit boundary for the panel's own editor.** The box shows one Book's titles; the panel remembers
        which Book (``_chapter_book_id``) and what it last wrote there (``_chapter_baseline``). Text that differs from
        the baseline is the user's and is stored -- raw, exactly as the box holds it, like a key release stores it --
        on *that* Book by its identity, so a change that already moved the selection can never hand it to another
        Book. Unchanged text commits nothing, so a Book whose defaults were never edited keeps an empty
        configuration and its displayed defaults keep following the track order. A Book that no longer exists
        (removed or replaced after confirmation) has nowhere to keep it. The box itself is not touched: no repaint,
        caret and selection stay where they are. Returns whether the model changed. Main thread only.
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

    def _validated_artwork(self, chosen: str) -> str | None:
        """A chosen file the service accepts, or None after a visible refusal.

        The service decodes it the way the tag will; a refusal leaves whatever
        was selected before exactly as it was.
        """
        if not chosen:
            return None
        try:
            mp3_artwork.load_artwork(chosen)
        except mp3_artwork.ArtworkError as exc:
            messagebox.showerror(APP_TITLE, f"Book Artwork: {exc}", parent=self)
            return None
        return chosen

    def choose_shared_artwork(self) -> None:
        self._guard.require("choose_shared_artwork")
        chosen = self._validated_artwork(str(self._choose_artwork() or ""))
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
        chosen = self._validated_artwork(str(self._choose_artwork() or ""))
        if chosen:
            self._remember_cover_dir(chosen)
            self.set_book_field("artwork", chosen)

    def clear_book_artwork(self) -> None:
        self._guard.require("clear_book_artwork")
        if not self.book_artwork.enabled:
            return
        self.set_book_field("artwork", "")

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
            catalog=wf.MP3_CATALOG,
            options=ImportOptions.for_catalog(wf.MP3_CATALOG),
            effective_config=self._effective_config,
            created_at=self._clock(),
        )

    def import_folder(self) -> None:
        """Workspace-level: scan one parent folder, then replace the Books."""
        self._guard.require("import_folder")
        if self._closed or self._import_busy:
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
        """Into the current Book, in the order the dialog returned them."""
        self._guard.require("add_files")
        if self._closed or self._import_busy:
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
        if self._pending_import is not None:
            self._abandon_readback(self._pending_import)
            return True
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

        The reset authorities are the model's own ``new_workspace`` and an
        empty observation store; nothing is deleted or written on disk, the
        log keeps its history (a divider marks the reset), settings are
        untouched, and a run in progress owns the workspace so the button is
        locked and this refuses. A pristine workspace asks nothing; meaningful
        work asks first.
        """
        self._guard.require("clear_all_imports")
        if self._closed or self.is_running or self._import_busy:
            return False
        self.flush_pending_editor_state()  # a pasted title is work the clear question must count
        meaningful = self._workspace_has_meaningful_work()
        if meaningful and not self._confirm(
                "Clear all imports?",
                "This clears every imported Book and file, and any unsaved workspace "
                "edits, from this tool.\n\nThe original files are not deleted or modified, "
                "and outputs already written are kept.\n\nClear them?"):
            return False
        had_run = self._attempt is not None
        if meaningful or had_run:
            self.log.divider(f"{DIVIDER_MARK} {CLEAR_IMPORTS_LABEL}")
        # v0.8.2 R1: the fresh job area first, and only then the reset. The same transactional swap a new run uses
        # (``_install_jobs``): if the fresh job area cannot be built, nothing has changed hands and nothing has been
        # cleared -- the Books, the previous run, its Retry Failed and its kept staging are all still there -- so the
        # tool says so and stays as it was instead of showing an emptied workspace beside a stale job area.
        retired = self.jobs
        try:
            self._install_jobs(IDLE_RUN_ID, ())
        except Exception as exc:  # noqa: BLE001 - decided here: nothing changed, or the reset goes on
            detail = f"{type(exc).__name__}: {exc}"
            if self.jobs is retired:
                text = "Clear All Imports: the tool could not be reset; nothing was cleared."
                self._say(text, detail)
                messagebox.showerror(APP_TITLE, text, parent=self)
                return False
            # The fresh job area is installed and only its last repaint failed: the reset goes on and repaints it.
            logging_setup.get_logger().warning("MP3 Tool: the fresh job area was not rendered: %s", detail)
        # The run goes with the workspace, and with it every chance of a Retry Failed: its kept staging goes too.
        self._abandon_staging()
        self.workspace = wf.new_workspace(id_factory=self._ids)
        self.store = wf.ObservationStore()
        self.book_numbers = {}
        self.last_plan = None
        self._attempt = None
        self._settled = None
        self.var_outdir.set(output_paths.destination_hint(TOOL_KEY))
        self.status.set_status(STATUS_READY)
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
            if status is OutcomeStatus.COMMITTED and outcome.commit is not None:
                # v0.8.2 Checkpoint 6: the tags are read off Tk; the Books are made when the reading is done, and the
                # outcome's message and problems are reported then, in the order they always were.
                self._begin_readback(kind, outcome, replacing if kind == "folder" else None)
                return outcome
            self.import_status.set_idle(outcome.display_message)
            label = "Import Folder" if kind == "folder" else "Add Files"
            self._say(f"{label}: {outcome.display_message}",
                      outcome.technical_detail or outcome.display_message)
            self._say_problems(outcome)
            return outcome
        if status in (OutcomeStatus.BUSY, OutcomeStatus.NO_TYPES_SELECTED):
            self.import_status.set_message(outcome.display_message)
        return outcome

    def _say_problems(self, outcome: ImportOutcome) -> None:
        for problem in outcome.problems:
            self._say(f"  {problem.display_message}",
                      f"  {problem.technical_detail or problem.display_message}")

    # -- reading the committed files' tags off Tk (v0.8.2 Checkpoint 6) ---- #

    @property
    def _import_busy(self) -> bool:
        """A scan is running, or a committed import's tags are still being read: nothing may start or reset."""
        return self._coordinator.is_active or self._pending_import is not None

    @property
    def is_reading_tags(self) -> bool:
        return self._pending_import is not None

    def _begin_readback(self, kind: str | None, outcome: ImportOutcome,
                        replacing: tuple | None = None) -> None:
        """Read the committed files' tags on a worker; the import is finished when they are read.

        The workspace does not change yet: what the workflow will make of the commit is decided in
        :meth:`_finish_readback`, from the workspace as it is then. A worker that cannot start leaves the reading to
        this thread, exactly as before. *replacing* is what an Import Folder was pressed to replace.
        """
        self.flush_pending_editor_state()
        commit = outcome.commit
        entries = commit.snapshot.files if kind == "folder" else commit.added
        readback = source_readback.SourceReadback(
            "mp3", (entry.path for entry in entries), {"reader": self._reader})
        pending = _PendingImport(readback, kind, outcome, self.workspace.current_book_id, replacing)
        self._pending_import = pending
        self._show_reading(pending)
        self._readbacks += 1
        try:
            self._thread_factory(readback.read_sources, f"mp3-readback-{self._readbacks}").start()
        except Exception as exc:  # noqa: BLE001 - no worker: read here, as v0.8.1 did
            logging_setup.get_logger().warning("MP3 Tool: tags read on the main thread: %s: %s",
                                               type(exc).__name__, exc)
            readback.read_sources()
        self._drain_readback()  # an inline or already finished reading completes the import now

    def _show_reading(self, pending: _PendingImport) -> None:
        done = pending.readback.done
        if done == pending.shown:
            return
        pending.shown = done
        self.import_status.set_message(
            f"Reading tags… {done:,} of {pending.readback.total:,} files")
        self.import_status.set_cancel_enabled(True)

    def _drain_readback(self) -> None:
        """Pump drain: report the reading's progress, and finish the import once every file was read."""
        pending = self._pending_import
        if pending is None or self._closed:
            return
        if pending.readback.finished:
            self._finish_readback(pending)
        elif pending.readback.failed:
            self._abandon_readback(pending, "The files could not be read, so nothing was added.")
        else:
            self._show_reading(pending)

    def _abandon_readback(self, pending: _PendingImport,
                          message: str = "The import was cancelled and nothing was added.") -> None:
        """Cancel Import (or a reading that failed) while the tags are read: nothing is added, and a late result is
        never adopted."""
        if self._pending_import is not pending:
            return
        self._pending_import = None
        pending.readback.cancel()
        self.import_status.set_idle(message)
        label = "Import Folder" if pending.kind == "folder" else "Add Files"
        self._say(f"{label}: {message}")
        self._say_problems(pending.outcome)

    def _finish_readback(self, pending: _PendingImport) -> None:
        if self._pending_import is not pending or self._closed or not pending.readback.finished:
            return  # cancelled, closed or replaced: a stale reading changes nothing
        self._pending_import = None
        if pending.kind == "folder" and self._books_changed_since(pending.replacing):
            self._refuse_replacement(pending.outcome)
            return
        self.import_status.set_idle(pending.outcome.display_message)
        self._project_import(pending)
        self._say_problems(pending.outcome)

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
        self._say_problems(outcome)
        messagebox.showwarning(APP_TITLE, REPLACEMENT_REFUSED, parent=self)

    def _project_import(self, pending: _PendingImport) -> None:
        """The committed snapshot becomes Books (folder) or tracks (files), observed from what the worker read."""
        self.flush_pending_editor_state()
        commit = pending.outcome.commit
        reader = pending.readback.reader("reader")
        if pending.kind == "folder":
            result = wf.import_folder(
                self.workspace, commit.snapshot, id_factory=self._ids,
                store=self.store, reader=reader)
            self.store = result.store
            self._apply(result.mutation)
            books = [book for book in self.workspace.books if not book.files.is_empty]
            total = sum(book.file_count for book in books)
            self._say(f"Import Folder: {total} MP3 file(s) in {len(books)} Book(s).")
            return
        space = self.workspace
        target = pending.target
        if target not in space.book_ids:
            self.render()
            self._say("Add Files: the Book these files were for was removed while their tags were read; "
                      "nothing was added.")
            return
        # Add Files goes into the Book it was pressed on, even if another Book is showing now; the page stays put.
        showing = space.current_book_id
        if showing != target:
            space = select_book(space, target).workspace
        held = set(space.current.files.identities)
        additions = tuple(entry for entry in commit.added if entry.identity not in held)
        skipped = len(commit.added) - len(additions)
        result = wf.add_files(space, additions, store=self.store, reader=reader)
        self.store = result.store
        grown = result.mutation.workspace if result.mutation.changed else space
        position = grown.book_ids.index(target) + 1
        where = f"Book {position} of {grown.count}"
        if grown.current_book_id != showing:
            grown = select_book(grown, showing).workspace
        self.workspace = grown
        self.render()
        note = f" {skipped} already in this Book were skipped." if skipped else ""
        self._say(f"Add Files: {len(additions)} MP3 file(s) added to {where}.{note}")

    # ------------------------------------------------------------------ #
    # The processing seams
    # ------------------------------------------------------------------ #

    def write_id3_tags(self) -> bool:
        self._guard.require("write_id3_tags")
        return self._request_operation("Write ID3 Tags")

    def combine_mp3s(self) -> bool:
        self._guard.require("combine_mp3s")
        return self._request_operation("Combine MP3s → One MP3")

    def _request_operation(self, label: str) -> bool:
        """Validate on Tk, freeze the inputs, and hand reserving and planning to the preparation worker.

        Exactly one reservation per operation, never one per Book, and only
        after the workspace validated. The plan is frozen from the workspace as
        it is at this moment; editing anything afterwards cannot reach it, and
        neither can a later Retry Failed read anything but it. A press while a
        run is under way -- or being prepared, or while an import is still
        settling -- is refused before anything is reserved.

        v0.8.2: ``True`` now means *accepted*: the press returns at once with
        the job area showing "Preparing job…" and Cancel, and the run starts
        when the pump adopts the worker's finished plan
        (:meth:`_on_preparation`). A refused plan is reported then, exactly as
        before, with the empty run released and nothing started.
        """
        if self._closed or self.is_running or self._import_busy:
            return False
        # A Chapter Titles change no key release reported (a mouse paste, an input method) is committed through the
        # model, to its own Book, before anything is frozen, so the run uses exactly what the box shows.
        if self.flush_pending_editor_state():
            self._render_light()
        space = self.workspace
        eligible = []
        for position, book in enumerate(space.books, start=1):
            # The Book's stable number, as the navigator and the run log show it, never its position, which changes
            # when a Book is removed (v0.7.2, ACT72-036).
            number = self.book_numbers.get(book.book_id, position)
            try:
                wf.parse_start_number(wf.start_number_text(book))
            except wf.MP3ValueError as exc:
                messagebox.showerror(APP_TITLE, f"{label}: Start # for Book {number}: {exc}",
                                     parent=self)
                return False
            try:
                wf.parse_time_delta(
                    str(wf.effective_scalars(space.shared, book).get("time_delta", "")))
            except wf.MP3ValueError as exc:
                messagebox.showerror(APP_TITLE, f"{label}: Time for Book {number}: {exc}",
                                     parent=self)
                return False
            if not book.files.is_empty:
                eligible.append(book)
        if not eligible:
            messagebox.showwarning(APP_TITLE, "Import a folder or add MP3 files first.",
                                   parent=self)
            return False
        operation = (mp3_plan.MP3Operation.COMBINE if label.startswith("Combine")
                     else mp3_plan.MP3Operation.WRITE_ID3)
        # Frozen here, on Tk, and never read again: the capture (taken on the caller's thread, as the shared capture
        # requires; no disk is read), the immutable workspace and store, the stable Book numbers, and the output
        # configuration -- the one in force at this press, even if Preferences change while the worker prepares.
        # v0.8.2 R1: ONE configuration snapshot, read once here, is both what every Book's run snapshot records and
        # what the reservation resolves its output base from, so the plan can never describe one base and write to
        # another. (The panel's construction-time configuration still governs importing only.)
        run_config = shared_config.get_effective()
        capture = mp3_plan.capture_for_run(
            space, catalog=wf.MP3_CATALOG,
            import_options=ImportOptions.for_catalog(wf.MP3_CATALOG),
            effective_config=run_config, id_factory=self._ids,
            created_at=self._clock())
        attempted = {book_id for book_id, _snapshot in capture.runs}
        preparation = _Preparation(
            label=label, operation=operation, workspace=space, store=self.store, capture=capture,
            numbers=self.book_numbers, run_config=run_config,
            book_count=len(attempted),
            track_count=sum(book.file_count for book in space.books if book.book_id in attempted))
        self._preparations += 1
        self._preparing = preparation
        self._show_preparing(preparation)
        self._say(f"{label}: preparing {preparation.book_count} Book(s), "
                  f"{preparation.track_count} track(s)…")
        try:
            thread = self._thread_factory(lambda: self._prepare(preparation),
                                          f"mp3-prepare-{self._preparations}")
            thread.start()
        except Exception as exc:  # noqa: BLE001 - nothing was reserved yet; the panel must not stay locked
            if self._preparing is preparation:
                self._preparing = None
                preparation.withdraw()
                text = f"{label}: the job could not be prepared, and nothing was started."
                self._end_preparation(STATUS_PREPARATION_FAILED, text, f"{type(exc).__name__}: {exc}")
                messagebox.showerror(APP_TITLE, text, parent=self)
            return False
        return True

    # -- the preparation: worker side ------------------------------------------ #

    def _prepare(self, preparation: _Preparation) -> None:
        """Reserve the run and plan it. **The preparation worker's whole body**; it never raises.

        Reads only the frozen *preparation* and writes only the preparation queue: no widget, no Tk variable, no
        panel state. Its last message is always exactly one ending -- ``prepared``, ``cancelled``, ``refused`` or
        ``fault`` -- and any run it reserved but could not hand over is released (only while still empty) before
        that message is sent, so the panel never sees an ending while a run of this press is still left behind.
        """
        post = self._prep_q.put
        reservation = None
        ending: _PreparationMessage | None = None
        try:
            preparation.checkpoint()
            try:
                reservation = output_paths.reserve_run_directory(
                    TOOL_KEY, effective=preparation.run_config)
            except output_paths.OutputPathError as exc:
                ending = _PreparationMessage(preparation, "refused", text=exc.message, detail=exc.detail)
                return
            plan = mp3_plan.plan_run(
                preparation.workspace, preparation.store, operation=preparation.operation,
                reservation=reservation, capture=preparation.capture, numbers=preparation.numbers,
                checkpoint=preparation.checkpoint,
                progress=lambda done, total: post(
                    _PreparationMessage(preparation, "progress", done=done, total=total)))
            if preparation.offer(plan):
                reservation = None  # the panel owns the run now
                ending = _PreparationMessage(preparation, "prepared")
            else:
                ending = _PreparationMessage(preparation, "cancelled")
        except ConversionCancelled:
            ending = _PreparationMessage(preparation, "cancelled")
        except (wf.MP3ValueError, mp3_plan.PlanError, output_paths.OutputPathError) as exc:
            detail = exc.detail if isinstance(exc, output_paths.OutputPathError) else ""
            ending = _PreparationMessage(preparation, "refused", text=f"{preparation.label}: {exc}", detail=detail)
        except BaseException as exc:  # noqa: BLE001 - deliberately everything: the panel must hear an ending
            ending = _PreparationMessage(
                preparation, "fault",
                text=f"{preparation.label}: the job could not be prepared, and nothing was started.",
                detail=f"{type(exc).__name__}: {exc}")
        finally:
            if reservation is not None:
                try:
                    output_paths.release_if_empty(reservation)
                except Exception:  # pragma: no cover - release_if_empty never raises; the ending must still go
                    pass
            post(ending if ending is not None else _PreparationMessage(
                preparation, "fault", text=f"{preparation.label}: the job could not be prepared.",
                detail="the preparation ended without a result"))

    # -- the preparation: Tk side --------------------------------------------- #

    def _show_preparing(self, preparation: _Preparation) -> None:
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
        self._show_preparation_progress(
            f"{preparation.label}: checking {preparation.book_count} Book(s), {preparation.track_count} track(s)")
        self.status.set_eta("")
        self.status.set_status(STATUS_PREPARING)

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
                logging_setup.get_logger().exception("MP3 Tool: preparation message failed: %s", exc)
                # v0.8.2 R1: the current preparation's ending must free the panel even if it failed part-way, as
                # long as no attempt took the run over; a plan it offered is released off Tk.
                if current and not self._busy and not self._closed:
                    self._preparing = None
                    left = message.preparation.withdraw()
                    if left is not None:
                        self._release_unadopted(left)
                    try:
                        self._end_preparation(STATUS_PREPARATION_FAILED,
                                              f"{message.preparation.label}: the job could not be prepared.",
                                              f"{type(exc).__name__}: {exc}")
                    except Exception:  # noqa: BLE001 - the pump must keep running
                        logging_setup.get_logger().exception("MP3 Tool: the preparation could not be ended")

    def _on_preparation(self, message: _PreparationMessage) -> None:
        """Adopt a finished plan and start the run, or end the preparation. Main thread only.

        A message from any preparation but the current one is stale: it is never acted on, and a plan it offered is
        taken back and its empty run released. A plan Cancel or Close withdrew is never adopted, so no media starts.
        """
        preparation = message.preparation
        if self._closed or preparation is not self._preparing:
            left = preparation.withdraw()
            if left is not None:
                self._release_unadopted(left)
            return
        kind = message.kind
        if kind == "progress":
            if message.total and not preparation.cancel_requested.is_set():
                self._show_preparation_progress(
                    f"{preparation.label}: planning Book {min(message.done + 1, message.total)} "
                    f"of {message.total}")
            return
        self._preparing = None
        if kind == "prepared":
            plan = preparation.adopt()
            if plan is not None:
                self._adopt(preparation, plan)
                return
            kind = "cancelled"
        if kind == "cancelled" or preparation.cancel_requested.is_set():
            note = f" ({message.text})" if kind != "cancelled" and message.text else ""
            self._end_preparation(
                STATUS_PREPARATION_CANCELLED,
                f"{preparation.label}: cancelled before anything was started; the workspace is unchanged.",
                f"{preparation.label}: preparation cancelled{note}; {message.detail}".rstrip("; "))
            return
        self._end_preparation(STATUS_PREPARATION_FAILED, message.text, message.detail or message.text)
        messagebox.showerror(APP_TITLE, message.text, parent=self)

    def _end_preparation(self, status: str, line: str, detail: str) -> None:
        """Put the job area back exactly as the previous run left it, then say why nothing started."""
        self.jobs.render()
        self.status.set_status(status)
        self._say(line, detail)
        self.render()

    def _adopt(self, preparation: _Preparation, plan: mp3_plan.RunPlan) -> None:
        """The prepared plan becomes the run. Main thread only; never raises.

        Only once the new attempt's job area is up does the new run replace the old one (``_start_attempt``): its
        Retry Failed can no longer be reached, so the old plan's kept staging goes -- removed by the new attempt's
        worker, off the Tk thread -- and the one controller, reporter, adapter and conversion worker are created
        exactly as before.

        v0.8.2 R1: if that setup fails before anything changed hands, the preparation ends as a failed one does --
        the previous run, its result, Retry Failed and kept staging untouched, the panel unlocked, the error shown --
        and the plan nobody will run has its still-empty run released off the Tk thread.
        """
        try:
            self._start_attempt(preparation.label, plan, replaces=True)
        except _AttemptNotStarted as exc:
            self._release_unadopted(plan)
            text = f"{preparation.label}: the job could not be started, and nothing was started."
            self._end_preparation(STATUS_PREPARATION_FAILED, text, exc.detail)
            messagebox.showerror(APP_TITLE, text, parent=self)

    def _release_unadopted(self, plan: mp3_plan.RunPlan) -> None:
        """Release the still-empty run of a plan nobody will run, **off the Tk thread** (v0.8.2 R1). Main thread.

        A plan offered and then withdrawn (Cancel, Close, a stale ending) or one whose run could not be set up hands
        its reservation here exactly once -- :meth:`_Preparation.withdraw` and :meth:`_Preparation.adopt` decide that
        under the preparation's lock -- and a short-lived worker removes the run folder only while it is still empty
        (``output_paths.release_if_empty``: links and anything inside are left alone; no source is ever touched).
        The call returns at once whatever the storage does, and the worker needs neither Tk nor the pump, so it
        finishes even after the panel closed. Should no worker start, the empty folder is left and named in the log
        rather than making Tk wait on the filesystem.
        """
        reservation = plan.reservation
        self._releases += 1
        name = f"mp3-release-{self._releases}"

        def release() -> None:
            try:
                released = output_paths.release_if_empty(reservation)
            except Exception as exc:  # noqa: BLE001 - release_if_empty never raises; still, a worker must not
                logging_setup.get_logger().warning("MP3 Tool: an unused run could not be released: %s (%s: %s)",
                                                   reservation.run_directory, type(exc).__name__, exc)
                return
            if not released:
                logging_setup.get_logger().warning("MP3 Tool: an unused run was left in place: %s",
                                                   reservation.run_directory)

        try:
            self._thread_factory(release, name).start()
        except Exception as exc:  # noqa: BLE001 - an empty folder left behind is harmless; a frozen window is not
            logging_setup.get_logger().warning("MP3 Tool: an unused run was left in place: %s (%s: %s)",
                                               reservation.run_directory, type(exc).__name__, exc)
            if not self._closed:
                self._say("An unused, empty run folder was left in place.",
                          f"Unused run left in place: {reservation.run_directory} ({type(exc).__name__}: {exc})")

    # ------------------------------------------------------------------ #
    # The one run: controller, reporter, adapter, worker
    # ------------------------------------------------------------------ #

    @staticmethod
    def _default_thread(target, name: str):
        import threading

        # ``daemon`` is a backstop, never the mechanism: ``close`` asks the
        # controller to cancel, and the worker stops at its next checkpoint.
        return threading.Thread(target=target, name=name, daemon=True)

    @property
    def is_running(self) -> bool:
        """An attempt is running, or an accepted press is still being prepared (v0.8.2)."""
        return self._busy or self._preparing is not None

    @property
    def is_preparing(self) -> bool:
        """An accepted press is being reserved and planned off the Tk thread; no run has started yet."""
        return self._preparing is not None

    @property
    def job_controller(self):
        """The cooperative controller of the current or last attempt, or ``None``."""
        attempt = self._attempt
        return None if attempt is None else attempt.controller

    @property
    def last_result(self) -> WorkspaceRunResult | None:
        """The frozen batch result the last attempt settled into, or ``None``."""
        return self._settled

    @property
    def attempt(self) -> int:
        """How many attempts this panel has started: runs and retries alike."""
        return self._attempts

    def _start_attempt(self, label: str, plan: mp3_plan.RunPlan, *,
                       retry_items=None, prior=None, replaces: bool = False) -> None:
        """Begin one attempt at *plan*: a first run, or a retry of it.

        The shared controller is this attempt's one state authority; its
        listener copies every state it actually reaches into the event stream,
        so the panel keeps no rival state machine beside it. A retry is a new
        attempt at the **same** run -- same plan, same run id, same run
        directory, nothing reserved -- with a fresh controller, reporter and
        adapter, because a terminal controller and a retired adapter cannot be
        revived.

        v0.8.2 R1 -- **ownership changes hands in one place.** Everything that
        can fail without consequence comes first: the controller, the reporter
        and the attempt are plain objects, and the new job area is installed
        transactionally. If that fails, :class:`_AttemptNotStarted` is raised
        and *nothing* has changed: the previous attempt, its result, its job
        area with its Retry Failed and its kept staging, and the panel's idle
        state are all as they were. Only after the job area is up does the new
        attempt become the panel's (and, with ``replaces``, the plan replace the
        last one, whose kept staging is handed to the new worker to remove). A
        failure from there until the worker is running settles the attempt as
        failed through its own controller and terminal event, as a worker
        fault would, so the panel never stays busy with nothing running.
        """
        retired = self.jobs
        failure: BaseException | None = None
        try:
            attempt_number = self._attempts + 1
            run_id = (self._attempt.run_id if retry_items is not None and self._attempt
                      else self._ids.next_id("run"))
            item_ids = tuple(track.occurrence_id for book in plan.books for track in book.tracks)
            controller = job_control.JobController(run_id, listener=self._on_state, cancel_clock=time.monotonic)
            reporter = job_control.JobReporter(
                run_id, clock=self._clock, publish=self._publish, item_ids=item_ids)
            attempt = _Attempt(label=label, plan=plan, run_id=run_id, number=attempt_number,
                               controller=controller, reporter=reporter,
                               retry_items=retry_items, prior=prior)
            # The divider first: it freezes the previous run's lines into the log's
            # history, so the fresh adapter's empty first render cannot drop them.
            heading = (f"Retry Failed — {label} — attempt {attempt_number}"
                       if retry_items is not None
                       else f"{label} — {plan.run_directory.name}")
            self.log.divider(f"{DIVIDER_MARK} {heading}")
            # The retired adapter is closed inside here, which drops its drain: one
            # pump, one job drain however many attempts a run takes. The new
            # adapter holds no result, so Retry Failed is unavailable for the whole
            # of this attempt without anything setting it.
            self._install_jobs(run_id, item_ids)
        except Exception as exc:  # noqa: BLE001 - decided here: nothing changed hands, or the attempt settles
            if self.jobs is retired:
                raise _AttemptNotStarted(f"{type(exc).__name__}: {exc}") from exc
            failure = exc

        # -- From here the attempt owns the run. ----------------------------- #
        if replaces:
            # The new run replaces the old one: no Retry Failed can reach the old plan any more. Its kept staging is
            # removed by this attempt's worker, off the Tk thread (``_release_superseded``).
            attempt.superseded = self._abandon_staging(defer=True)
            self.last_plan = plan
            self._settled = None
        self._attempts = attempt_number
        self._attempt = attempt
        self._busy = True
        try:
            if failure is not None:
                raise failure
            controller.start()
            # Locked now, from the state the controller actually reached, rather
            # than a tick later when the RUNNING event is drained.
            self.lock_group.apply(controller.state)
            books = len(attempt.books)
            reporter.stage_changed(
                STAGE_PREPARE,
                (f"{label}: retrying {books} Book(s) in {plan.run_directory.name}…"
                 if retry_items is not None
                 else f"{label}: {books} Book(s) → {plan.run_directory.name}"))
            reporter.output_location(plan.run_directory, f"Output: {plan.run_directory}")
            reporter.progress(0, attempt.projection.total, stage=STAGE_PREPARE)
            self._render_status()
            thread = self._thread_factory(lambda: self._worker(attempt), f"mp3-{run_id}")
            self._worker_thread = thread
            thread.start()
        except Exception as exc:  # noqa: BLE001 - a worker that never started must still settle the run
            # v0.8.2: reached from the pump since preparation; an exception escaping here would stop the pump and
            # leave the panel locked. The run fails as a worker fault would, through the same terminal event.
            self._fail_unstarted(attempt, f"{type(exc).__name__}: {exc}")

    def _fail_unstarted(self, attempt: _Attempt, detail: str) -> None:
        """Settle an attempt whose worker never started as failed. Main thread only; never raises.

        Nothing ran, so nothing of it can be retried: its staging (none for a first run) and the superseded run's
        kept staging go, exactly as a worker fault releases them. The controller settles ``FAILED`` and the one
        terminal event frees the panel. Should the controller not even have reached RUNNING -- it cannot be failed
        from IDLE -- the panel is freed directly and the attempt is never reported as running.

        Where the cleanup runs: the superseded run's kept staging can be large and has no ordering to keep (see
        :meth:`_release_superseded`), so it goes to a short-lived release worker and Tk does not wait for it; only
        when no worker can be started at all -- the usual reason the run's own could not -- is it removed here.
        This attempt's own staging is released here, before the terminal event, because that order is what a later
        Retry Failed relies on; for a run that never started it is a few directory checks.
        """
        controller, reporter = attempt.controller, attempt.reporter
        try:
            reporter.technical(f"The processing worker could not be started: {detail}")
        except Exception:  # noqa: BLE001 - reporting is best effort here
            pass
        if attempt.superseded is not None:
            self._releases += 1
            try:
                self._thread_factory(lambda: self._release_superseded(attempt),
                                     f"mp3-release-{self._releases}").start()
            except Exception:  # noqa: BLE001 - no worker at all: remove it here rather than leave it behind
                self._release_superseded(attempt)
        self._release_staging(attempt, keep=())
        try:
            if controller.state is JobState.IDLE:
                controller.start()
            reporter.completed(controller.fail(FAULT_MESSAGE, detail))
            return
        except Exception as exc:  # noqa: BLE001 - the controller cannot settle; the panel must still be freed
            logging_setup.get_logger().exception("MP3 Tool: an attempt could not be settled: %s", exc)
        self._busy = False
        self._settled = None
        try:
            self.jobs.render()
            self.status.set_status(STATUS_PREPARATION_FAILED)
        except Exception:  # noqa: BLE001
            pass
        self._say(f"{attempt.label}: the job could not be started, and nothing was processed.", detail)
        self.render()

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
        attempt = self._attempt
        if attempt is not None and snapshot.run_id == attempt.run_id:
            attempt.reporter.state_changed(snapshot)

    def _context(self, stage: str | None, item_id: str | None) -> str:
        """The status line under the bar: ``Book 2 of 10 — Track 14 of 32``."""
        attempt = self._attempt
        if not stage:
            return ""
        if attempt is None or not stage.startswith("book-"):
            return stage
        try:
            position = int(stage[len("book-"):])
        except ValueError:
            return stage
        text = f"Book {position} of {attempt.projection.count}"
        track = attempt.track_context(item_id)
        return f"{text} — {track}" if track else text

    def _worker(self, attempt: _Attempt) -> None:
        """Run the attempt, and **never let anything escape this thread**.

        Whatever happens in the engine, the controller settles and the one
        terminal event is sent, because that event is what frees the panel. A
        cancellation raised at a checkpoint settles as cancelled; anything
        else as failed, with the fault kept to the Detailed pane and the
        session log. Nothing here reaches a widget.
        """
        controller = attempt.controller
        reporter = attempt.reporter
        try:
            self._release_superseded(attempt)
            self._run_attempt(attempt)
        except ConversionCancelled:
            # Plan 3 offers no Retry Failed after a Cancel, so nothing staged is kept (ACT72-037).
            # v0.8.x P5-I-R3: CANCELLED only once every contained process of the run is confirmed ended.
            problem = sp.containment_problem(controller.cancel_check)
            self._release_staging(attempt, keep=())
            try:
                if problem is not None:
                    reporter.technical(problem)
                    reporter.completed(controller.fail(sp.CONTAINMENT_FAILED_MESSAGE, problem))
                else:
                    reporter.cancelled(controller.finish_cancelled())
            except Exception:  # pragma: no cover - already stopping; do not mask it
                pass
        except BaseException as exc:  # noqa: BLE001 - deliberately everything
            detail = f"{type(exc).__name__}: {exc}"
            try:
                reporter.technical(detail)
            except Exception:  # pragma: no cover - already failing; do not mask it
                pass
            self._release_staging(attempt, keep=())
            try:
                reporter.completed(controller.fail(FAULT_MESSAGE, detail))
            except Exception:  # pragma: no cover - already failing; do not mask it
                pass

    def _release_staging(self, attempt: _Attempt, *, keep) -> None:
        """The worker's half of the staging rule (v0.7.2, ACT72-019 / ACT72-037). Worker thread; touches no widget.

        Called once per attempt, before its terminal event, with the Books this attempt can still retry: everything
        else the plan staged goes now, so a run that cannot be retried leaves no ``.work``. A plan the main thread
        already let go (:meth:`_abandon_staging`) keeps nothing. Never raises; what could not be removed is named in
        the Detailed pane and stays where it is.
        """
        try:
            with self._staging_lock:
                attempt.running = False
                problems = mp3_plan.release_staging(
                    attempt.plan, keep=() if attempt.abandoned else frozenset(keep))
        except Exception as exc:  # noqa: BLE001 - the terminal event must still be sent
            problems = (f"{type(exc).__name__}: {exc}",)
        for line in problems:
            try:
                attempt.reporter.technical(f"Private staging left in place: {line}")
            except Exception:  # pragma: no cover - reporting is best effort here
                pass

    def _release_superseded(self, attempt: _Attempt) -> None:
        """Remove the kept staging of the run this attempt replaced (v0.8.2). Any thread; touches no widget.

        That run is abandoned and finished, and nothing else holds or will release it, so the staging lock (which
        orders one attempt's worker against Tk) is not taken: a large old ``.work`` is removed without making Tk wait.
        Runs once, at most. Never raises; what could not be removed is named and stays where it is.
        """
        plan, attempt.superseded = attempt.superseded, None
        if plan is None:
            return
        try:
            problems = mp3_plan.release_staging(plan)
        except Exception as exc:  # noqa: BLE001 - the new run must still go on
            problems = (f"{type(exc).__name__}: {exc}",)
        for line in problems:
            # The session log always hears of it; the run's own Detailed pane does while the run is still open.
            logging_setup.get_logger().warning(
                "MP3 Tool: private staging of the previous run left in place (its .work folder): %s", line)
            try:
                attempt.reporter.technical(
                    f"Private staging of the previous run left in place (its .work folder): {line}")
            except Exception:  # pragma: no cover - reporting is best effort here
                pass

    def _abandon_staging(self, *, defer: bool = False):
        """The main thread's half: no Retry Failed can reach the current plan any more. Main thread only.

        Clear All Imports, a new run and closing the tool all drop the run. A worker still running keeps nothing
        when it ends; otherwise the kept Books go now. Never raises.

        ``defer=True`` (v0.8.2, a new run adopting its plan): nothing is removed here; the plan whose kept staging
        must go is returned for the new attempt's worker to remove (:meth:`_release_superseded`), off the Tk thread.
        Returns ``None`` when there is nothing left for anyone to remove.
        """
        attempt = self._attempt
        if attempt is None:
            return None
        try:
            with self._staging_lock:
                attempt.abandoned = True
                if attempt.running:
                    return None
                if defer:
                    return attempt.plan
                problems = mp3_plan.release_staging(attempt.plan)
        except Exception as exc:  # noqa: BLE001 - closing must go on
            problems = (f"{type(exc).__name__}: {exc}",)
        for line in problems:
            if self._closed:
                logging_setup.get_logger().warning("MP3 Tool: private staging left in place: %s", line)
            else:
                self._say("Some private staging could not be removed; it stays in the run's .work folder.", line)

    def _run_attempt(self, attempt: _Attempt) -> None:
        """The worker's body: the engine, then the controller's verdict."""
        plan = attempt.plan
        engine = (mp3_processing.combine_run
                  if plan.operation is mp3_plan.MP3Operation.COMBINE
                  else mp3_processing.write_id3_run)
        # cancel_check, not checkpoint, is what a running FFmpeg step watches: Cancel stops it (ACT72-023), Pause waits.
        report = engine(plan, checkpoint=attempt.controller.checkpoint,
                        cancel_check=attempt.controller.cancel_check,
                        on_event=attempt.projection, on_book=attempt.record,
                        retry_items=attempt.retry_items)
        attempt.report = report
        controller = attempt.controller
        # v0.8.x P5-I-R3: never finished with a contained process of the run not confirmed ended.
        problem = sp.containment_problem(controller.cancel_check)
        if problem is not None:
            attempt.reporter.technical(problem)
            final = controller.fail(sp.CONTAINMENT_FAILED_MESSAGE, problem)
        else:
            final = (controller.complete_with_failures() if report.failed_book_ids
                     else controller.succeed())
        # Retry Failed is offered only after a run completed with failures, and re-runs only Books with a retryable
        # failure: their good pieces stay staged for it; every other Book's staging goes before the terminal event.
        keep = ({book.book_id for book in report.books if not book.succeeded and book.result.has_retryable}
                if final.state is JobState.COMPLETED_WITH_FAILURES else ())
        self._release_staging(attempt, keep=keep)
        attempt.reporter.completed(final)

    # -- main-thread projections of the run --------------------------------- #

    def _on_job_event(self, _event) -> None:
        """Every accepted event may move the current Book's status line."""
        self._render_status()

    def _on_terminal(self, event) -> None:
        """The attempt ended: compose the frozen batch result. Main thread only.

        The per-Book ``RunResult`` values are the engine's, settled against each
        Book's own original ``RunSnapshot``; a retry merges its Books' new
        results over the earlier attempt's, so the result always describes the
        whole frozen run. The batch state is the controller's terminal state,
        except that a retry attempt which itself succeeded while another Book
        still stands failed is, for the batch, completed with failures
        (Decision 28A). Nothing is rebuilt or re-captured.
        """
        attempt = self._attempt
        if attempt is None or event.run_id != attempt.run_id or not self._busy:
            return
        results: dict[str, job_control.RunResult] = {}
        if attempt.prior is not None:
            results.update(attempt.prior.results)
        results.update(tuple(attempt.results))
        state = event.state or JobState.FAILED
        if state is JobState.SUCCEEDED and any(
                entry.state is not JobState.SUCCEEDED for entry in results.values()):
            state = JobState.COMPLETED_WITH_FAILURES
        try:
            result = WorkspaceRunResult(attempt.plan.capture, results=tuple(results.items()),
                                        state=state)
        except WorkspaceContractError as exc:
            result = None
            self._say(f"{attempt.label}: the result could not be settled.", str(exc))
        self._settled = result
        self._busy = False
        self.jobs.set_result(result)
        if result is not None:
            skipped = result.skipped_empty_count + result.skipped_invalid_count
            stopped = len(self._stopped_book_ids(result))
            never = (f"{stopped} stopped by Cancel, {result.not_attempted_count - stopped} not attempted"
                     if stopped else f"{result.not_attempted_count} not attempted")
            self._say(f"{attempt.label}: {result.succeeded_count} Book(s) completed, "
                      f"{result.failed_count} failed, {skipped} skipped, {never} "
                      f"→ {attempt.plan.run_directory}")
        self.render()

    def book_status_for(self, book_id: str) -> str:
        """One Book's compact status, read from the run -- never kept here.

        During an attempt: a Book the capture skipped is ``Skipped``; one the
        engine has settled is ``Completed`` or ``Failed`` by its own result; a
        Book an earlier attempt settled and this retry leaves alone keeps that
        answer; the Book at the projected stage is ``Processing`` and the rest
        of the attempt's Books are ``Queued`` -- a presentation of the active
        batch, held nowhere. Afterwards the frozen result's disposition answers
        (focused plan section 26): ``NOT_ATTEMPTED`` is shown as *Not attempted*,
        and a Book the result does not know at all is ``Ready``.
        """
        attempt = self._attempt
        if attempt is not None and self._busy:
            capture = attempt.plan.capture
            if book_id in capture.skipped_book_ids:
                return STATUS_SKIPPED
            settled = attempt.settled(book_id)
            if settled is not None:
                return self._status_of_result(settled)
            prior = attempt.prior
            if prior is not None and book_id not in attempt.retry_items:
                return self._status_of_disposition(prior.disposition_for(book_id))
            position = attempt.position_of(book_id)
            if position:
                if self._current_stage() == attempt.projection.stage_of(book_id):
                    return STATUS_PROCESSING
                return STATUS_QUEUED
            return STATUS_READY
        result = self._settled
        if result is None:
            return STATUS_READY
        if book_id in self._stopped_book_ids(result):
            return STATUS_CANCELLED
        return self._status_of_disposition(result.disposition_for(book_id))

    def _stopped_book_ids(self, result) -> set[str]:
        """The Books a Cancel stopped part-way in the latest attempt: begun, never settled, NOT_ATTEMPTED (ACT72-004)."""
        attempt = self._attempt
        if attempt is None or result is None or result.state is not JobState.CANCELLED:
            return set()
        return {book_id for book_id in attempt.projection.began
                if attempt.settled(book_id) is None
                and result.disposition_for(book_id) is BookDisposition.NOT_ATTEMPTED}

    def _current_stage(self) -> str | None:
        """The stage the run's accepted events last announced, if any.

        Read from the adapter's stream rather than its projected view because
        the adapter hands each accepted event to this panel *before* it
        re-projects, and the status label must not lag one drain behind.
        """
        for entry in reversed(self.jobs.stream.events):
            if entry.kind is JobEventKind.STAGE_CHANGED:
                return entry.stage
        return None

    @staticmethod
    def _status_of_result(result) -> str:
        return STATUS_COMPLETED if result.state is JobState.SUCCEEDED else STATUS_FAILED

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
        """Ask the run to pause at its next safe checkpoint.

        Truthful by construction: this reaches ``PAUSE_REQUESTED`` and stops
        there; only the worker, arriving at a checkpoint between two tracks or
        two Books, can make it ``PAUSED``. The FFmpeg call in flight is never
        suspended or killed, and nothing here claims otherwise.
        """
        controller = self.job_controller
        if controller is not None and self._busy:
            controller.request_pause()

    def resume(self) -> None:
        """Return a paused or pausing run to running and wake its worker."""
        controller = self.job_controller
        if controller is not None and self._busy:
            controller.resume()

    def cancel(self) -> None:
        """Ask the run to stop. A running FFmpeg step is stopped at once (ACT72-023).

        No later Book starts and no later FFmpeg step; the one in flight is
        terminated through its own process handle and a half-written staged
        track or combined file removed (the ``.work`` folder itself stays, as
        ACT72-037 records); the Books never reached settle as ``NOT_ATTEMPTED`` and the
        batch as ``CANCELLED`` once the worker has acknowledged it -- never before.

        v0.8.2: during preparation there is no run yet. Cancel asks the preparation
        worker to stop at its next checkpoint and says so at once; the panel ends the
        preparation when the worker acknowledges (its empty run released, nothing
        started, the workspace and the previous run as they were). A plan already
        offered is taken back here and its empty run released, so it can never start.
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
        controller = self.job_controller
        if controller is not None and self._busy:
            controller.request_cancel()

    def retry_failed(self) -> bool:
        """Re-run the failed Books of the frozen run. Main thread only.

        **A new attempt at the same run, not a new run.** The plan is the
        original object, the run directory the one reserved at the original
        press, and nothing here reads a widget, the workspace, the store or
        the configuration: the user may have edited every field, reordered and
        removed tracks and added Books since, and none of it reaches what this
        executes. The shared model decides *what* is retried --
        ``retry_failed_books`` on the frozen result -- and the engine re-stages
        exactly those occurrences, reuses every other staged piece and
        publishes each Book whole from its original ``BookPlan``.
        """
        self._guard.require("retry_failed")
        if self._closed or self.is_running:
            return False
        attempt = self._attempt
        result = self._settled
        plan = self.last_plan
        if attempt is None or result is None or plan is None or attempt.plan is not plan:
            return False
        if not result.can_retry_failed:
            return False
        retry_items = {}
        for request in retry_failed_books(result):
            book = next((entry for entry in plan.books
                         if entry.snapshot is request.snapshot), None)
            if book is None:  # pragma: no cover - the result was settled from this plan
                messagebox.showerror(APP_TITLE, "Retry Failed: the failed Book is not in "
                                     "the frozen plan; nothing was retried.", parent=self)
                return False
            retry_items[book.book_id] = tuple(request.item_ids)
        if not retry_items:
            return False
        try:
            self._start_attempt(attempt.label, plan, retry_items=retry_items, prior=result)
        except _AttemptNotStarted as exc:
            # v0.8.2 R1: nothing changed hands; the failed Books, their kept staging and Retry Failed stay as they were.
            text = "Retry Failed: the retry could not be started; nothing was changed."
            self.jobs.render()
            self._say(text, exc.detail)
            messagebox.showerror(APP_TITLE, text, parent=self)
            return False
        return True

    def on_pause(self) -> None:
        self.pause()

    def on_resume(self) -> None:
        self.resume()

    def on_cancel(self) -> None:
        self.cancel()

    def on_retry(self) -> None:
        self.retry_failed()

    # ------------------------------------------------------------------ #
    # Teardown
    # ------------------------------------------------------------------ #

    def close(self) -> None:
        """Cancel any scan or run, stop the pump, close every component. Idempotent.

        A worker still running is asked to cancel through its controller and
        stops at its next checkpoint; the events it sends after this go to a
        queue nothing drains, which is exactly where they should go.
        """
        if self._closed:
            return
        self._closed = True
        appearance.unregister_listener(self._on_appearance_changed)
        # v0.8.2 Checkpoint 6: tags still being read stop after the file in hand, and are never adopted.
        pending, self._pending_import = self._pending_import, None
        if pending is not None:
            pending.readback.cancel()
        # v0.8.2: a preparation still going stops at its next checkpoint and releases its own empty run; a plan it
        # already offered is taken back here and released, so nothing it planned can start after the tool closed.
        preparation, self._preparing = self._preparing, None
        if preparation is not None:
            left = preparation.withdraw()
            if left is not None:
                self._release_unadopted(left)  # off Tk; finishes after the pump closed
        # Nothing can retry once the tool is closed (ACT72-019): kept staging goes now, or when the worker ends.
        self._abandon_staging()
        controller = self.job_controller
        if controller is not None and self._busy:
            try:
                controller.request_cancel()
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
        for variable, token in ((self.var_start_number, self._start_trace),
                                (self.var_outdir, self._outdir_trace)):
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


def build_ui(parent: tk.Misc, theme=None) -> MP3ToolUI:
    """Build the MP3 Tool UI into ``parent`` and return the frame.

    ``theme`` is optional and backwards-compatible: the launcher's existing
    ``build_ui(container)`` call keeps working, and the panel resolves the
    platform theme itself when nothing is passed.
    """
    ui = MP3ToolUI(parent, theme=theme)
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
