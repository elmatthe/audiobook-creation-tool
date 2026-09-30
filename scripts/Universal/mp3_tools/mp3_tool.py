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
``mp3_tools/mp3_processing.py`` beside the Write ID3 and Combine engines that
consume the frozen plan; they are re-exported here under their original names.

Phase 5 adds the frozen plan: a processing button validates the workspace,
reserves **one** MP3 Tool run for the whole operation through the shared
service, and freezes everything the processing phases and a later Retry Failed
will read — Book order and ids, every track's occurrence, final Title, number
and filename, effective metadata, signed Time, artwork, the Book subfolders and
the private staging beside them (``mp3_tools/mp3_plan.py``).

Phase 9 runs it. One operation is **one** Plan 3 run: one ``JobController``
for the whole batch (never one per Book), one ``JobReporter``, one event
stream drained by one ``JobAdapter`` on the panel's one pump, one worker
thread. The engine knows nothing of any of that: it is handed the controller's
``checkpoint`` and an event listener, and ``_RunProjection`` turns its
``ProcessingEvent`` lines into the shared job events on the worker's own
thread — no widget is ever reached from there. Pause, Resume and Cancel are
the controller's: ``PAUSED`` is shown only once the worker acknowledged it at
a checkpoint, and Cancel stops at the next one, leaving the Books it never
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

import queue
import sys
import time
from collections.abc import Mapping
from pathlib import Path

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox

# Make the scripts/ root importable so `shared.*` resolves whether this tool is
# run standalone (python mp3_tools/mp3_tool.py) or imported by the launcher.
_SCRIPTS_ROOT = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ROOT))

from shared import appearance
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
from shared.job_control import JobEventKind, JobState
from shared.job_ui import MainThreadGuard, MainThreadPump, style_name
from mp3_tools import mp3_artwork
from mp3_tools import mp3_plan
from mp3_tools import mp3_processing
from mp3_tools import mp3_workflow as wf

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

# settings.json key (input dir only remembers the dialog location; the output
# folder is NOT persisted — it always resets to a fresh Downloads/<SLUG>-N).
KEY_INPUT_DIR = "mp3_tool.input_dir"

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

#: Rules a line under the previous run's lines in both log panes.
DIVIDER_MARK = "────"

#: The one label of the destructive workspace reset, shared by the three
#: multi-Book tools (v0.6.4 Phase 12 maintainer amendment).
CLEAR_IMPORTS_LABEL = "Clear All Imports"

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
    """Return the saved folder for ``key`` if it still exists, else the home dir."""
    val = settings.get(key)
    if val:
        p = Path(val)
        if p.exists():
            return p
    return Path.home()


# The proven FFmpeg helpers moved to ``mp3_processing`` at Phase 7 of the
# focused MP3 redesign, where the Write ID3 engine shares them. They are
# re-exported here under their original names for every existing caller.
from mp3_tools.mp3_processing import (  # noqa: E402,F401
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

    def stage_of(self, book_id: str) -> str:
        return f"book-{self._position.get(book_id, 0)}"

    def __call__(self, event: mp3_processing.ProcessingEvent) -> None:
        reporter = self._reporter
        book_id = event.book_id
        stage = self.stage_of(book_id)
        message = _one_line(event.message)
        kind = event.kind
        if kind == "book":
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
                 controller, reporter, retry_items=None, prior=None) -> None:
        self.label = label
        self.plan = plan
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
        "artwork_gap": int(metrics.get("artwork_gap", 8)),
        # v0.6.4 Phase 13 (macOS parity): Clear All Imports widened this band
        # past the aqua host, squeezing the import status bar to one pixel.
        "import_band_layout": str(metrics.get("import_band_layout", "compact")),
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
        self.btn_choose = ttk.Button(self.frame, text="Choose…",
                                     style=style_name(theme, "button"),
                                     command=self._choose,
                                     **({} if natural else {"width": 7}))
        self.btn_clear = ttk.Button(self.frame, text="Clear",
                                    style=style_name(theme, "button"),
                                    command=self._clear,
                                    **({} if natural else {"width": 5}))
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
        self._attempts = 0
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
        self._install_jobs(IDLE_RUN_ID, ())

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
            top, text="Import Folder", style=st("button"), command=self.import_folder)
        self.btn_import_folder.grid(row=0, column=0, sticky="w")
        # The destructive workspace reset lives with the import controls it
        # undoes, in the shared destructive treatment (v0.6.4 Phase 12 amendment).
        self.btn_clear_imports = ttk.Button(
            top, text=CLEAR_IMPORTS_LABEL, style=st("danger_button"),
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
                                        style=st("button"), command=self.add_files)
        self.btn_move_up = ttk.Button(track_buttons, text="Move Up",
                                      style=st("button"), command=self.move_up)
        self.btn_move_down = ttk.Button(track_buttons, text="Move Down",
                                        style=st("button"), command=self.move_down)
        self.btn_remove_tracks = ttk.Button(track_buttons, text="Remove Selected",
                                            style=st("button"),
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
        self._suspend_chapters = False
        self._chapter_baseline = ""

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
            style=st("button"), command=self.write_id3_tags)
        self.btn_combine = ttk.Button(
            self.actions, text="Combine MP3s → One MP3", default="active",
            style=st("button"), command=self.combine_mp3s)
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
        self.btn_clear_log = ttk.Button(bar, text="Clear Log", style=st("button"),
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
        previous = getattr(self, "jobs", None)
        if previous is not None:
            previous.close()
            previous.frame.destroy()
        bundle = self.appearance_bundle
        self._event_q = queue.Queue()
        self._estimator = job_control.EtaEstimator(run_id, clock=self._clock)
        self.jobs = job_ui.JobAdapter(
            self.actions,
            run_id=run_id,
            pump=self._pump,
            # The shared compact bundle, exactly as Cover's, TTS's and the
            # Converter's job areas use it.
            theme=bundle,
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
        # The panel's own names for the shared pieces, re-pointed per run.
        self.controls = self.jobs.controls
        self.status = self.jobs.status
        self.lock_group = self.jobs.locks
        # Per-instance restyling, exactly as Cover, TTS and the Converter do it:
        # the shared indicator stays generic for every panel that has not
        # adopted the compact system, but here an unstyled native frame would
        # be a light island in Dark. Aqua names inherit native controls.
        self.status.indicator.frame.configure(style=style_name(bundle, "card"))
        self.status.indicator.bar.configure(style=style_name(bundle, "progressbar"),
                                            length=PROGRESS_BAR_LENGTH)
        self.status.indicator.label.configure(style=style_name(bundle, "secondary_label"))
        self.status.label_status.configure(style=style_name(bundle, "secondary_label"))
        self._arrange_status()
        self.jobs.register_inputs(self.navigator, self._tracks_lock, self._import_lock)
        self.jobs.register_options(self.surface, self.shared_artwork, self.book_artwork,
                                   self._book_options_lock)
        self.jobs.render()

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
            width = label.winfo_width()
            described = ttk.Style(label).lookup(
                str(label.cget("style")) or "TLabel", "font")
            font = tkfont.Font(font=described or "TkDefaultFont")
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

    def _arrange_status(self) -> None:
        """The shared status view's lines: three, or two in the tight density.

        Grid positions and wrap only -- the same labels, bound to the same
        variables the shared view writes. Regular is the view's own layout:
        progress, then stage and ETA, then the status line. Tight sets the
        status beside the progress bar and the stage beside the ETA, one line
        fewer beside the two operations.
        """
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

    # ------------------------------------------------------------------ #
    # Dialog and confirmation seams (main thread, before any worker)
    # ------------------------------------------------------------------ #

    def _remember(self, path: Path) -> None:
        settings.set(KEY_INPUT_DIR, str(path))

    def _ask_files(self):
        chosen = tuple(filedialog.askopenfilenames(
            parent=self, title="Select MP3 files",
            initialdir=str(_remembered_dir(KEY_INPUT_DIR)),
            filetypes=[("MP3 files", "*.mp3"), ("All files", "*.*")]))
        if chosen:
            self._remember(Path(chosen[0]).parent)
        return chosen

    def _ask_folder(self):
        chosen = filedialog.askdirectory(
            parent=self, title="Select a folder of MP3 audiobooks",
            initialdir=str(_remembered_dir(KEY_INPUT_DIR)), mustexist=True)
        if not chosen:
            return ()
        self._remember(Path(chosen))
        return (str(chosen),)

    def artwork_filetypes(self) -> list:
        """The chooser filter, from the shared capability probe, never a list."""
        return mp3_artwork.artwork_filetypes()

    def _ask_artwork(self) -> str:
        chosen = filedialog.askopenfilename(
            parent=self, title="Select Book Artwork",
            initialdir=str(_remembered_dir(KEY_INPUT_DIR)),
            filetypes=self.artwork_filetypes())
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
        self.track_list.delete(0, "end")
        for entry in book.files.files:
            self.track_list.insert("end", entry.name)
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
        raw = self._chapter_display()
        self._chapter_baseline = raw
        if raw == self.chapter_text.get("1.0", "end-1c"):
            return
        self._suspend_chapters = True
        try:
            self.chapter_text.delete("1.0", "end")
            if raw:
                self.chapter_text.insert("1.0", raw)
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

    def set_book_field(self, name: str, value) -> None:
        """Store one raw Book value and show it. The model owns the write."""
        self._guard.require("set_book_field")
        self._apply(wf.set_book_field(self.workspace, name, value))

    def on_auto_number(self) -> None:
        if self._rendering:
            return
        self._apply(wf.set_book_field(self.workspace, "auto_number",
                                      bool(self.var_auto_number.get())))

    def on_start_number(self) -> None:
        if self._rendering or self._closed:
            return
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
            catalog=wf.MP3_CATALOG,
            options=ImportOptions.for_catalog(wf.MP3_CATALOG),
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
        """Into the current Book, in the order the dialog returned them."""
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

        The reset authorities are the model's own ``new_workspace`` and an
        empty observation store; nothing is deleted or written on disk, the
        log keeps its history (a divider marks the reset), settings are
        untouched, and a run in progress owns the workspace so the button is
        locked and this refuses. A pristine workspace asks nothing; meaningful
        work asks first.
        """
        self._guard.require("clear_all_imports")
        if self._closed or self.is_running or self._coordinator.is_active:
            return False
        meaningful = self._workspace_has_meaningful_work()
        if meaningful and not self._confirm(
                "Clear all imports?",
                "This clears every imported Book and file, and any unsaved workspace "
                "edits, from this tool.\n\nThe original files are not deleted or modified, "
                "and outputs already written are kept.\n\nClear them?"):
            return False
        had_run = self._attempt is not None
        self.workspace = wf.new_workspace(id_factory=self._ids)
        self.store = wf.ObservationStore()
        self.book_numbers = {}
        self.last_plan = None
        self._attempt = None
        self._settled = None
        self.var_outdir.set(output_paths.destination_hint(TOOL_KEY))
        if meaningful or had_run:
            self.log.divider(f"{DIVIDER_MARK} {CLEAR_IMPORTS_LABEL}")
        self._install_jobs(IDLE_RUN_ID, ())
        self.status.set_status(STATUS_READY)
        self.render()
        return True

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
            result = wf.import_folder(
                self.workspace, commit.snapshot, id_factory=self._ids,
                store=self.store, reader=self._reader)
            self.store = result.store
            self._apply(result.mutation)
            books = [book for book in self.workspace.books if not book.files.is_empty]
            total = sum(book.file_count for book in books)
            self._say(f"Import Folder: {total} MP3 file(s) in {len(books)} Book(s).")
            return
        held = set(self.workspace.current.files.identities)
        additions = tuple(entry for entry in commit.added if entry.identity not in held)
        skipped = len(commit.added) - len(additions)
        result = wf.add_files(self.workspace, additions, store=self.store,
                              reader=self._reader)
        self.store = result.store
        self._apply(result.mutation)
        note = f" {skipped} already in this Book were skipped." if skipped else ""
        self._say(f"Add Files: {len(additions)} MP3 file(s) added to "
                  f"{self.navigator.position_text}.{note}")

    # ------------------------------------------------------------------ #
    # The processing seams
    # ------------------------------------------------------------------ #

    def write_id3_tags(self) -> bool:
        self._guard.require("write_id3_tags")
        return self._request_operation("Write ID3 Tags")

    def combine_mp3s(self) -> bool:
        self._guard.require("combine_mp3s")
        return self._request_operation("Combine MP3s → One MP3")

    def _reserve_run(self):
        """Reserve one run for one validated operation. None means do not start."""
        try:
            return output_paths.reserve_run_directory(TOOL_KEY)
        except output_paths.OutputPathError as exc:
            messagebox.showerror(APP_TITLE, exc.message, parent=self)
            return None

    def _request_operation(self, label: str) -> bool:
        """Validate, reserve one run, freeze the plan, start the one worker.

        Exactly one reservation per operation, never one per Book, and only
        after the workspace validated. The plan is frozen from the workspace as
        it is at this moment; editing anything afterwards cannot reach it, and
        neither can a later Retry Failed read anything but it. A press while a
        run is under way is refused before anything is reserved.
        """
        if self._closed or self._busy:
            return False
        space = self.workspace
        eligible = []
        for position, book in enumerate(space.books, start=1):
            try:
                wf.parse_start_number(wf.start_number_text(book))
            except wf.MP3ValueError as exc:
                messagebox.showerror(APP_TITLE, f"{label}: Start # for Book {position}: {exc}",
                                     parent=self)
                return False
            try:
                wf.parse_time_delta(
                    str(wf.effective_scalars(space.shared, book).get("time_delta", "")))
            except wf.MP3ValueError as exc:
                messagebox.showerror(APP_TITLE, f"{label}: Time for Book {position}: {exc}",
                                     parent=self)
                return False
            if not book.files.is_empty:
                eligible.append(book)
        if not eligible:
            messagebox.showwarning(APP_TITLE, "Import a folder or add MP3 files first.",
                                   parent=self)
            return False
        reservation = self._reserve_run()
        if reservation is None:
            return False
        operation = (mp3_plan.MP3Operation.COMBINE if label.startswith("Combine")
                     else mp3_plan.MP3Operation.WRITE_ID3)
        try:
            plan = mp3_plan.plan_run(
                space, self.store, operation=operation, reservation=reservation,
                catalog=wf.MP3_CATALOG,
                import_options=ImportOptions.for_catalog(wf.MP3_CATALOG),
                effective_config=self._effective_config, id_factory=self._ids,
                created_at=self._clock(), numbers=self.book_numbers)
        except (wf.MP3ValueError, mp3_plan.PlanError,
                output_paths.OutputPathError) as exc:
            output_paths.release_if_empty(reservation)
            messagebox.showerror(APP_TITLE, f"{label}: {exc}", parent=self)
            return False
        self.last_plan = plan
        self._settled = None
        self._start_attempt(label, plan)
        return True

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
        return self._busy

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
                       retry_items=None, prior=None) -> None:
        """Begin one attempt at *plan*: a first run, or a retry of it.

        The shared controller is this attempt's one state authority; its
        listener copies every state it actually reaches into the event stream,
        so the panel keeps no rival state machine beside it. A retry is a new
        attempt at the **same** run -- same plan, same run id, same run
        directory, nothing reserved -- with a fresh controller, reporter and
        adapter, because a terminal controller and a retired adapter cannot be
        revived.
        """
        attempt_number = self._attempts + 1
        run_id = (self._attempt.run_id if retry_items is not None and self._attempt
                  else self._ids.next_id("run"))
        item_ids = tuple(track.occurrence_id for book in plan.books for track in book.tracks)
        controller = job_control.JobController(run_id, listener=self._on_state)
        reporter = job_control.JobReporter(
            run_id, clock=self._clock, publish=self._publish, item_ids=item_ids)
        attempt = _Attempt(label=label, plan=plan, run_id=run_id, number=attempt_number,
                           controller=controller, reporter=reporter,
                           retry_items=retry_items, prior=prior)
        self._attempts = attempt_number
        self._attempt = attempt
        self._busy = True
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
            self._run_attempt(attempt)
        except ConversionCancelled:
            try:
                reporter.cancelled(controller.finish_cancelled())
            except Exception:  # pragma: no cover - already stopping; do not mask it
                pass
        except BaseException as exc:  # noqa: BLE001 - deliberately everything
            detail = f"{type(exc).__name__}: {exc}"
            try:
                reporter.technical(detail)
                reporter.completed(controller.fail(FAULT_MESSAGE, detail))
            except Exception:  # pragma: no cover - already failing; do not mask it
                pass

    def _run_attempt(self, attempt: _Attempt) -> None:
        """The worker's body: the engine, then the controller's verdict."""
        plan = attempt.plan
        engine = (mp3_processing.combine_run
                  if plan.operation is mp3_plan.MP3Operation.COMBINE
                  else mp3_processing.write_id3_run)
        report = engine(plan, checkpoint=attempt.controller.checkpoint,
                        on_event=attempt.projection, on_book=attempt.record,
                        retry_items=attempt.retry_items)
        attempt.report = report
        controller = attempt.controller
        final = (controller.complete_with_failures() if report.failed_book_ids
                 else controller.succeed())
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
            self._say(f"{attempt.label}: {result.succeeded_count} Book(s) completed, "
                      f"{result.failed_count} failed, {skipped} skipped, "
                      f"{result.not_attempted_count} not attempted "
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
        return self._status_of_disposition(result.disposition_for(book_id))

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
        """Ask the run to stop at its next checkpoint. Cooperative, never forced.

        No later Book starts; the one in flight stops between its stages; the
        Books never reached settle as ``NOT_ATTEMPTED`` and the batch as
        ``CANCELLED`` once the worker has acknowledged it -- never before.
        """
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
        if self._closed or self._busy:
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
        self._start_attempt(attempt.label, plan, retry_items=retry_items, prior=result)
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
