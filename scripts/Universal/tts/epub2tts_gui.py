"""Desktop GUI for the PDF / TXT → MP3 audiobook engine — one unified queue.

The module and package names (``epub2tts_gui``, ``tts.epub2tts_edge``) are the upstream
project's names and are kept deliberately — see ``files/archived-code/epub-tts/README.md``
for the documented compatibility boundary. EPUB itself was retired as an application input
by maintainer decision on 2026-08-11; PDF and TXT are the only supported types.

v0.6.1 Plan 4 Phase 6 replaced this panel's two input models — a Single-file browse
box and a Batch-folder browse box, chosen with a mode radio — with **one unified
PDF/TXT queue** built on the shared Plan 3 importing foundation (drop §4.5, decisions
1A and 2A). The :class:`~shared.importing.ImportedFileManager` is now the only
authority on which files a run converts, in what order; nothing here keeps a parallel
list, and nothing here rediscovers a folder.

The panel also stopped being a closure. ``build_ui(parent)`` used to be a single
function holding ~30 ``tk.*Var``s in scope, which gave the shared adapters nothing to
attach a lifetime to. It is now :class:`TtsPanel`, a frame that owns its importer, its
one :class:`~shared.job_ui.MainThreadPump`, and a ``close()`` that tears both down.
``build_ui`` itself is unchanged from the launcher's point of view.

**Provenance selects the processing path**, which is exactly the distinction the
retired radio used to make. A directly added file is a file the user pointed at, so it
takes the rich chapter/pause engine and lands flat in the run (Decision 31A). A file
found under an imported folder is one of many, so it takes the chunked batch worker and
mirrors its folder's shape (Decision 7A); several folders each keep their own container
(Decision 41A). Both kinds live in one queue and convert in **one** run.

v0.6.1 Plan 4 Phase 7 moved the *run* onto the shared job foundation. One accepted
run is frozen once by ``capture_run``; a ``JobController`` owns its cooperative
pause, resume and cancel; a ``JobReporter`` mints every event from a controller
snapshot; a ``JobAdapter`` renders the whole processing side — controls, progress,
the rolling estimate, Summary and Details — and a settled ``RunResult`` is what lets
a failed item be re-run. Phase 6's separate ``threading.Event`` processing cancel is
gone: there is one cancellation authority for a run, and ``CANCELLED`` means a worker
acknowledged it at a checkpoint and cleaned up, never that a button was pressed.

Several threads have something to report — the Tk thread while a button moves the
controller, the conversion worker, and every file-worker pool thread (v0.6.5 Phase 6
onward: direct and folder items alike) that reaches a checkpoint — so they all report
through one :class:`RunPublisher`. It holds a single
lock across the whole of minting and publishing, which is what makes the order events
reach the adapter's queue the order the shared reporter numbered them.

Every occurrence's destination is planned once, before the run starts, and stored
**by occurrence id** — because re-running a failure needs identity, and a path is
not one.
The same file may sit in the queue twice, deliberately, as two occurrences with two
collision-safe destinations; a retry reuses the destination its original run planned
and therefore can never overwrite an earlier success.

v0.6.1 Plan 4 Phase 10 added a third engine. The maintainer approved all four
locally cloned Chatterbox voices on 2026-08-15, and they are registered in
``voice_registry`` alongside the Edge and Kokoro rows. What changed here is
deliberately small: the engine choice that used to be one ``is_kokoro`` boolean is
now the run's frozen ``backend``, and the worker makes a **three-way** decision at
the synthesis seam. There is no second queue, no second run, no second controller,
no second progress model and no second output planner — a Chatterbox run is the
same run, taking the same frozen snapshot down the same path, and only the call
that actually produces audio is different.

Two things are genuinely new. **A registered voice is not necessarily an available
one**: the cloning voices are backed by local reference recordings that exist only
where the maintainer put them, so a voice whose recording is missing or altered is
shown as setup-required and refuses to start a run — rather than being offered,
accepted, and failing partway through. And the engine choice is frozen as an
explicit ``backend``/``voice_id`` pair, so a retry re-runs the voice the original
run used even if the dropdown has moved on since.

The conversion engines themselves are untouched: ``run_conversion_job``,
``convert_single_pdf``, ``kokoro_file_to_mp3`` and ``pdf_to_txt`` are consumed exactly
as they were, with their timing constants, retry counts and per-source temp-chunk
isolation unchanged. They receive ``controller.cancel_check`` through the same
``cancel_check`` seam their existing chapter/chunk checkpoints already use, so
cancellation inside a conversion is as responsive as it has always been. Pause is a
coarser thing by design and happens only **between source files** — never inside a
chapter, a synthesis chunk, a network call or a PDF extraction.
"""

from __future__ import annotations

import contextlib
import io
import os
import queue
import shutil
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
try:
    import tkinter as tk
except (ImportError, ModuleNotFoundError) as _tk_err:  # Tk-less / headless Python
    sys.stderr.write(
        "\n[Audiobook Creation Tool] The graphical interface cannot start because\n"
        "this Python build has no working Tk (tkinter) support.\n\n"
        "To enable the window, install Tk and relaunch:\n"
        "  - macOS (Homebrew):  brew install python-tk@3.12\n"
        "  - then double-click Setup_and_Run-audiobook-creation-tool again.\n\n"
        f"(details: {_tk_err})\n"
    )
    raise SystemExit(1)
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

# Ensure the scripts/ root is importable so `tts.*` resolves whether this GUI is
# run directly (python scripts/tts/epub2tts_gui.py) or imported by the launcher.
_SCRIPTS_ROOT = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ROOT))

from shared import config as shared_config
from shared import ffmpeg_utils
from shared import job_control
from shared import job_ui
from shared import output_paths
from shared import subprocess_utils as sp

#: Central tool identifier for the shared output services.
TOOL_KEY = "tts"
from shared.cancellation import ConversionCancelled
from shared.import_coordination import ImportCoordinator
from shared.importing import (
    ImportedFileManager,
    SupportedType,
    SupportedTypeCatalog,
    planning_groups,
)
from shared.job_control import (
    FailureLog,
    FailureRecord,
    JobState,
    RunResult,
    capture_run,
)
from shared.output_paths import plan_flat, plan_mirrored, plan_multi_root
from shared.ui_theme import enable_mousewheel
from tts.epub2tts_edge.epub2tts_edge import (
    DEFAULT_CHAPTER_PAUSE_MS,
    DEFAULT_END_OF_BOOK_PAUSE_MS,
    DEFAULT_PARAGRAPH_PAUSE_MS,
    DEFAULT_SENTENCE_PAUSE_MS,
    DEFAULT_SPEAKER,
    DEFAULT_TITLE_PAUSE_MS,
    DEFAULT_TRIM_SILENCE_DB,
    ensure_punkt,
)
from tts.voice_registry import (
    DEFAULT_VOICE_LABEL,
    get_voice,
    display_labels,
)

#: How long ``close()`` waits for a conversion worker to unwind.
WORKER_JOIN_TIMEOUT = 5.0

#: The run id the shared controls carry before the first conversion. A panel that
#: has never run still shows its Pause/Cancel/Retry row, uniformly disabled.
IDLE_RUN_ID = "tts-idle"

#: The one stage name this tool reports. Every progress event, every current-item
#: event and every failure record carries it, so Summary and Details agree.
STAGE_CONVERT = "converting"

#: The two work categories the rolling estimate keeps apart. A whole book through
#: the chapter/pause engine and one file through the chunked batch worker are not
#: comparable units, and :class:`~shared.job_control.EtaEstimator` clears its history
#: when the category changes rather than averaging two different kinds of work.
ETA_CATEGORY_DIRECT = "direct-conversion"
ETA_CATEGORY_FOLDER = "folder-conversion"

#: The queue message carrying one settled :class:`~shared.job_control.RunResult`.
RESULT_MESSAGE = "result"

#: The queue message carrying one finished file's measured duration.
TIMING_MESSAGE = "timing"


# --------------------------------------------------------------------------- #
# v0.6.5 Phase 6 (P14) -- requested vs. effective file-worker concurrency
#
# ``Workers = X`` is a requested WHOLE-FILE concurrency level, never permission
# to parallelize the chunks inside one source file: one worker owns one file
# and processes that file's synthesis units sequentially/in order, exactly as
# every engine call below already does on its own. Effective concurrency is
# min(requested, queued files, a backend-safety ceiling, a conservative
# device-safe ceiling) -- never a fake universal hardware formula, and never
# silently ignored: the run log always states requested vs. effective.
# --------------------------------------------------------------------------- #

#: Hard backend-safety ceilings. Edge/Kokoro's are sanity limits against a
#: pathological request (e.g. "100"); Chatterbox's is a correctness
#: constraint, not a tuning choice -- see ``_device_safe_workers`` below and
#: ``chatterbox_synth._get_model``/``load_conditionals``: one cached model
#: instance per device holds mutable conditioning state
#: (``model.conds``) that a second concurrent file would race.
EDGE_BACKEND_SAFE_WORKERS = 32
KOKORO_BACKEND_SAFE_WORKERS = 8
CHATTERBOX_BACKEND_SAFE_WORKERS = 1


def _cpu_count() -> int | None:
    """A thin, patchable seam over ``os.cpu_count()``.

    Exists only so a test can substitute a known core count without touching
    the real, shared ``os`` module -- this app's actual behavior always reads
    the real machine.
    """
    return os.cpu_count()


def _device_safe_workers(backend: str) -> int:
    """A conservative per-backend ceiling from the real machine's own CPU
    count -- evidence, not an invented formula -- leaving headroom for the
    OS/UI/FFmpeg rather than trying to consume every core.

    Edge is network-bound locally: each worker's own CPU cost is a short
    trim/re-encode burst, not sustained inference, so up to one worker per
    logical core is offered. Kokoro is a local model doing sustained CPU
    inference per file, so only half the logical cores are offered, leaving
    the other half as headroom. Chatterbox's limit is a correctness
    constraint (see the module docstring above), not a capacity guess, so it
    is always 1 regardless of the machine.
    """
    if backend == "chatterbox":
        return 1
    cpu = _cpu_count() or 4
    if backend == "kokoro":
        return max(1, cpu // 2)
    return max(1, cpu)


def resolve_effective_workers(requested: int, queued_files: int, backend: str) -> int:
    """The one place P14's worker cap is computed for a run.

    Bounded by the user's own request, how many files are actually queued
    (concurrency beyond the queue is meaningless), a backend-safety ceiling,
    and a conservative device-safe ceiling read from the real machine. An
    oversized request (e.g. "100" on a 4-core machine with 2 files queued)
    degrades safely to whatever is actually supportable; it never raises and
    never returns less than 1.
    """
    backend_safe = {
        "edge": EDGE_BACKEND_SAFE_WORKERS,
        "kokoro": KOKORO_BACKEND_SAFE_WORKERS,
        "chatterbox": CHATTERBOX_BACKEND_SAFE_WORKERS,
    }.get(backend, 1)
    device_safe = _device_safe_workers(backend)
    return max(1, min(int(requested), int(queued_files), backend_safe, device_safe))


#: What the engine line says when a locally cloned voice is selected. Engine
#: wording lives here and never in a voice's name: the four voice labels are the
#: maintainer's own and are shown exactly as approved.
CHATTERBOX_ENGINE_LABEL = "Chatterbox Turbo (Local AI)"


def chatterbox_status(voice_id: str) -> tuple[bool, str]:
    """The panel's one question to the local cloning engine: can this voice run?

    Everything that makes the answer true or false — where the reference recording
    lives, what it must hash to, what cached voice data is bound to, whether the
    package is installed — belongs to ``tts/chatterbox_synth.py`` and stays there.
    This panel gets a boolean and a sentence fit to show a non-technical user, and
    knows nothing else about it.

    The import is lazy and both failure modes are answered rather than raised, so a
    machine with no local engine installed at all still builds this panel, still
    lists every voice, and still converts with Edge and Kokoro.
    """
    try:
        from tts.chatterbox_synth import voice_availability
    except Exception as exc:  # noqa: BLE001 - a missing engine is a status, not a crash
        return False, (
            "The local voice-cloning engine is not available on this computer "
            f"({exc}). Edge and Kokoro voices are unaffected."
        )
    try:
        return voice_availability(voice_id)
    except Exception as exc:  # noqa: BLE001 - likewise: report it, never crash a panel
        return False, (
            f"This voice could not be checked on this computer ({exc}). "
            "Edge and Kokoro voices are unaffected."
        )


def _default_chatterbox_status(voice_id: str) -> tuple[bool, str]:
    """The panel's default seam — one hop, so the module function stays patchable.

    A constructor keyword of the same name shadows :func:`chatterbox_status` inside
    ``__init__``, and binding the function object there would also freeze it. This
    resolves the name at call time instead.
    """
    return chatterbox_status(voice_id)


@dataclass(frozen=True)
class TimingSample:
    """How long one finished file actually took, as plain immutable data.

    The estimate lives in one :class:`~shared.job_control.EtaEstimator` that the
    shared job adapter reads, and that object is compound mutable state belonging
    to the thread that owns the widgets. So the worker never touches it: it
    measures a duration with the run's injected clock and sends *this* through the
    queue the main thread already drains.

    ``run_id`` alone would not make a late sample inert, because a retry re-runs
    the *same* frozen snapshot and carries the same id. ``attempt`` is what tells
    one attempt's leftovers from the attempt now running.
    """

    run_id: str
    attempt: int
    category: str
    duration: float


@dataclass(frozen=True)
class PlannedOutput:
    """One occurrence's frozen place in the run: where it came from, where it goes.

    ``direct`` is provenance, not preference: a file the user pointed at takes the
    rich chapter/pause engine and flat placement, a file found under an imported
    folder takes the chunked batch worker and mirrored placement. It is decided
    once, when the run is planned, and a retry re-uses this value rather than
    asking the imported list again.
    """

    source: Path
    destination: Path
    direct: bool


def build_catalog() -> SupportedTypeCatalog:
    """The two input types this tool accepts, and the only two (drop §4.1).

    There is no EPUB entry, no EPUB extension and no probe behind this: PDF and
    TXT are unconditional, so the offered set is the same on every machine.
    """
    return SupportedTypeCatalog((
        SupportedType("pdf", "PDF document", (".pdf",)),
        SupportedType("txt", "Text file", (".txt",)),
    ))


def _default_timing_preset() -> dict:
    """Defensive fallback matching voice_registry's own Edge defaults.

    Used only if the selected label somehow matches no registered voice,
    which should not happen — the dropdown only ever offers registered
    labels (readonly combobox, values from ``display_labels()``).
    """
    return {
        "sentencepause": str(DEFAULT_SENTENCE_PAUSE_MS),
        "paragraphpause": str(DEFAULT_PARAGRAPH_PAUSE_MS),
        "title_ms": str(DEFAULT_TITLE_PAUSE_MS),
        "chapter_ms": str(DEFAULT_CHAPTER_PAUSE_MS),
        "end_pause": str(DEFAULT_END_OF_BOOK_PAUSE_MS),
        "trim_dbfs": str(int(DEFAULT_TRIM_SILENCE_DB)),
        "trim_edge_chunks": True,
        "rate": "+0%",
        "kokoro_speed": "1.0",
    }


def direct_output_name(source: Path, speaker: str) -> str:
    """The filename the rich Edge engine will actually write for a direct file.

    ``make_mp3`` names its artifact ``<stem> (<speaker>).mp3`` and the runner moves
    that name into the destination directory, so a destination has to be planned
    under it. Planning ``<stem>.mp3`` would reserve a name nothing occupies and
    leave the real one unchecked.
    """
    return f"{Path(source).stem} ({speaker}).mp3"


def mp3_output_name(source: Path) -> str:
    """``<stem>.mp3`` — what the batch worker and the Kokoro path both write."""
    return f"{Path(source).stem}.mp3"


def _identity_buckets(snapshot):
    """Split a snapshot's occurrence ids the way :func:`planning_groups` splits paths.

    Returns ``(direct_ids, grouped_ids)`` — individually added occurrences in queue
    order, then folder-derived occurrences grouped by root and ordered by the root
    order the user imported in, which is exactly the shared function's own rule. The
    caller cross-checks the two against each other, so this cannot quietly drift into
    a second grouping.
    """
    direct: list[str] = []
    buckets: dict[str, list[str]] = {}
    order: list[tuple[int, str]] = []
    for entry in snapshot.files:
        if entry.mirroring_root is None:
            direct.append(entry.occurrence_id)
            continue
        key = entry.source_root.root_id
        if key not in buckets:
            buckets[key] = []
            order.append((entry.source_root.order, key))
        buckets[key].append(entry.occurrence_id)
    order.sort()
    return tuple(direct), tuple(tuple(buckets[key]) for _order, key in order)


def _pair(occurrence_ids, plan, sources, lookup, *, direct: bool) -> dict:
    """Attach one planned destination to each occurrence, or refuse.

    The identity walk and the path walk above are independent, so they are verified
    against each other rather than trusted: if the ids and the paths ever stopped
    lining up, a run would synthesise one occurrence's book into another's file, and
    that has to be a loud error rather than a quiet mix-up.
    """
    if len(occurrence_ids) != len(plan.items):
        raise output_paths.UnsafePathError(
            "the output plan does not cover every imported file",
            f"{len(occurrence_ids)} occurrences, {len(plan.items)} planned outputs",
        )
    mapping: dict[str, PlannedOutput] = {}
    for occurrence_id, item, source in zip(occurrence_ids, plan.items, sources):
        if lookup[occurrence_id] != source:
            raise output_paths.UnsafePathError(
                "an imported file was matched to another file's destination",
                f"{lookup[occurrence_id]} vs {source}",
            )
        mapping[occurrence_id] = PlannedOutput(
            source=item.source, destination=item.destination, direct=direct)
    return mapping


def plan_destinations(snapshot, run_root: Path, *, direct_rename, grouped_rename,
                      planner=None) -> dict:
    """Where every occurrence of *snapshot* writes inside *run_root*.

    :func:`~shared.importing.planning_groups` is the only bridge from the imported
    queue to Plan 2, and the three approved planners are the only things that decide
    a destination: directly chosen files land flat (Decision 31A), one folder root
    mirrors its relative parents (Decision 7A), and several roots each get their own
    collision-safe container (Decision 41A).

    All of them share one :class:`~shared.output_paths.DestinationPlanner`, so a flat
    file and a mirrored file can never be planned onto the same path, and ``Book.pdf``
    chosen twice becomes two destinations rather than one overwritten one. Nothing is
    created here: this reserves no directory and opens no file.

    Returns ``occurrence_id -> PlannedOutput``. Keying on identity rather than on the
    path is what Phase 7's retry contract needs: two deliberate duplicates share a path
    and an identity but not an occurrence id, and it is the occurrence id that decides
    which of their two destinations a retried item goes back to.
    """
    root = Path(run_root)
    tracker = output_paths.DestinationPlanner(root) if planner is None else planner
    groups = planning_groups(snapshot)
    direct_ids, grouped_ids = _identity_buckets(snapshot)
    lookup = {entry.occurrence_id: entry.path for entry in snapshot.files}

    mapping: dict[str, PlannedOutput] = {}
    if groups.direct:
        plan = plan_flat(root, groups.direct, planner=tracker, rename=direct_rename)
        mapping.update(_pair(direct_ids, plan, groups.direct, lookup, direct=True))
    if groups.grouped:
        if groups.needs_multi_root:
            plan = plan_multi_root(root, groups.grouped, planner=tracker,
                                   rename=grouped_rename)
        else:
            source_root, group_sources = groups.grouped[0]
            plan = plan_mirrored(root, group_sources, source_root, planner=tracker,
                                 rename=grouped_rename)
        flattened_ids = tuple(entry for group in grouped_ids for entry in group)
        flattened_sources = tuple(
            entry for _root, group in groups.grouped for entry in group)
        mapping.update(
            _pair(flattened_ids, plan, flattened_sources, lookup, direct=False))
    return mapping


def freeze_tts_options(
    *, speaker: str, backend: str, voice_id: str, rate: str, resume: bool,
    overwrite: bool, bitrate: str, workers: int, kokoro_speed: float,
    end_pause: int, paragraph_pause: int, pause_kw: dict,
) -> dict:
    """Everything about a run that changes what it produces, as plain frozen values.

    Deliberately small and deliberately opaque to the shared foundation: Plan 2 stays
    the only owner of what a destination *means*, so nothing here is a path. These are
    the settings the worker reads instead of reading a widget, and the settings a
    retry re-uses instead of reading today's widget.

    ``backend`` and ``voice_id`` are the run's engine identity, and they are the
    *only* thing that decides which engine synthesises it. They are explicit fields
    rather than something inferred from ``speaker`` or matched out of a display
    label, because a display label is a name shown to a person and names change —
    the maintainer may rename a voice without any run behaving differently.
    """
    return {
        "speaker": str(speaker),
        "backend": str(backend),
        "voice_id": str(voice_id),
        "rate": str(rate),
        "resume": bool(resume),
        "overwrite": bool(overwrite),
        "bitrate": str(bitrate),
        "workers": int(workers),
        "kokoro_speed": float(kokoro_speed),
        "end_pause": int(end_pause),
        "paragraph_pause": int(paragraph_pause),
        "pause_kw": dict(pause_kw),
    }


# --------------------------------------------------------------------------- #
# The run's one publication authority
# --------------------------------------------------------------------------- #


class RunPublisher:
    """The single producer that decides the order one run's events reach the UI.

    ``JobReporter`` allocates an event's number under its own lock and then hands
    the event to the publisher with that lock *released*, because §5.4 forbids
    holding a lock across caller code. Its docstring states the rule that follows:
    one run reports from one producer. This panel has several — the Tk thread while
    a button moves the controller, the conversion worker, and every thread in the
    run's file-worker pool (direct and folder items alike, v0.6.5 Phase 6 onward)
    that reaches a checkpoint and dispatches a state change — so this
    is the one producer they share.

    **Why N + 1 cannot overtake N.** The authority is held across the *whole* of
    minting and publishing, not around the counter alone. A thread that would take
    the next number cannot enter the reporter at all until the thread holding the
    previous one has already put its event on the queue, so the order events enter
    the queue is the order their numbers were allocated, and
    ``JobEventStream`` never has a lower number arriving late to refuse.

    **Why it cannot deadlock.** The guarded region calls exactly two things: one
    shared reporter method, whose own lock is a leaf, and one ``put`` on an
    unbounded queue, which never blocks. It never touches Tk, never touches the
    run's controller, and is never re-entered — so no thread can be waiting here
    for something held by a thread that is waiting for this.

    **Why retirement is not guarded.** Closing sets a flag and takes nothing, so a
    panel being torn down can never be blocked behind a report in flight. A closed
    authority publishes nothing further, and it holds the queue it was built with
    rather than reading the panel's current one — which is what keeps a retry
    clean, since a retry re-uses the original ``RunSnapshot`` and therefore the
    original run id, and a straggler from the attempt being re-run would otherwise
    be indistinguishable from a live report.
    """

    __slots__ = ("_reporter", "_sink", "_lock", "_closed", "_revision")

    def __init__(self, snapshot, *, clock, sink) -> None:
        self._sink = sink
        self._lock = threading.Lock()
        self._closed = threading.Event()
        self._revision = -1
        self._reporter = job_control.JobReporter.for_run(
            snapshot, clock=clock, publish=self._deliver)

    # -- what a caller may ask ---------------------------------------------- #

    @property
    def run_id(self) -> str:
        return self._reporter.run_id

    @property
    def lock(self) -> threading.Lock:
        """The ordering authority itself. Held, a publication is in flight."""
        return self._lock

    @property
    def sink(self):
        """The queue this run publishes into, bound when the run was accepted."""
        return self._sink

    @property
    def closed(self) -> bool:
        return self._closed.is_set()

    def close(self) -> None:
        """Retire this attempt. Idempotent, lock-free, and safe from any thread."""
        self._closed.set()

    # -- production --------------------------------------------------------- #

    def state_changed(self, snapshot):
        """Report a controller state — and never one the run has already left.

        The controller dispatches its listener with its own lock released, so two
        threads that moved the run can arrive here in the opposite order to the
        moves themselves: a ``PAUSED`` before the ``PAUSE_REQUESTED`` it answered.
        A snapshot's revision is the controller's own monotonic counter, so a
        snapshot older than the last one reported is simply not reported. Nothing
        is invented in its place and nothing already accepted is re-ordered — the
        run's current state is drawn from the state the run is currently in.
        """
        if self._closed.is_set():
            return None
        with self._lock:
            if self._closed.is_set():
                return None
            revision = snapshot.revision
            if revision <= self._revision:
                return None
            self._revision = revision
            return self._reporter.state_changed(snapshot)

    def progress(self, completed, total=None, *, item_id=None, stage=None,
                 message=""):
        return self._publish(
            lambda: self._reporter.progress(
                completed, total, item_id=item_id, stage=stage, message=message))

    def current_item(self, item_id, message=""):
        return self._publish(
            lambda: self._reporter.current_item(item_id, message))

    def failure(self, message, detail="", *, item_id=None, stage=None):
        return self._publish(
            lambda: self._reporter.failure(
                message, detail, item_id=item_id, stage=stage))

    def output_location(self, location, message=""):
        return self._publish(
            lambda: self._reporter.output_location(location, message))

    def completed(self, snapshot, message=""):
        """The run's one ending. Never revision-guarded: an ending is not a state."""
        return self._publish(lambda: self._reporter.completed(snapshot, message))

    def cancelled(self, snapshot, message=""):
        """The one ending of a run a worker stopped and cleaned up after."""
        return self._publish(lambda: self._reporter.cancelled(snapshot, message))

    # -- internals ---------------------------------------------------------- #

    def _publish(self, mint):
        """Mint and deliver one event as a single indivisible step."""
        if self._closed.is_set():
            return None
        with self._lock:
            if self._closed.is_set():
                return None
            return mint()

    def _deliver(self, entry) -> None:
        """The reporter's publisher, called from inside the guarded region.

        The queue is read at call time rather than bound once, so a test can watch
        this boundary and so nothing here outlives the queue it was given.
        """
        self._sink.put(entry)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"RunPublisher(run_id={self.run_id!r}, closed={self.closed})")


class TtsPanel(ttk.Frame):
    """The TTS tool as an embeddable, state-owning frame.

    Every keyword below is a **seam with a production default**, present so the
    suite can drive a real panel deterministically — a fake dialog, a stub thread
    factory, an injected clock, an in-memory configuration — without a display
    server, a real home directory or a real broad filesystem root. The launcher
    passes none of them.
    """

    def __init__(
        self,
        parent: tk.Misc,
        *,
        effective_config: object | None = None,
        clock=None,
        id_factory=None,
        scanner=None,
        thread_factory=None,
        home: object | None = None,
        choose_files=None,
        choose_folder=None,
        confirm_broad_root=None,
        confirm_large_result=None,
        chatterbox_status=None,
    ):
        super().__init__(parent)
        ffmpeg_utils.configure_pydub()

        self._closed = False

        # Conversion plumbing. Processing cancellation belongs to the run's
        # JobController and to nothing else — the import side's own cancellation
        # goes to the coordinator and the two never meet.
        self._busy = threading.Event()
        self._log_q: queue.Queue[tuple[str, object]] = queue.Queue()
        self._event_q: queue.Queue = queue.Queue()
        self._worker = None

        # One run's job-control state. All of it is replaced wholesale when a run
        # is accepted; a controller belongs to one attempt and is never revived.
        self._run_count = 0
        self._attempt = 0
        self._controller = None
        self._publisher = None
        self._estimator = None
        self._snapshot = None
        self._result = None
        self._destinations: dict[str, PlannedOutput] = {}
        self._run_directory: Path | None = None

        self._clock = time.monotonic if clock is None else clock
        self._effective_config = (shared_config.get_effective()
                                  if effective_config is None else effective_config)

        # The whole of this panel's knowledge about whether a locally cloned voice
        # can run: one seam that answers, one boolean, one message. Not a second
        # registry and not a second state machine — a registered voice stays
        # registered whatever this says.
        self._chatterbox_status = (chatterbox_status if chatterbox_status is not None
                                   else _default_chatterbox_status)
        self._voice_available = True

        # ---- Tk state ---------------------------------------------------- #
        # Where the next run will go, shown read-only. The numbered run folder is
        # reserved atomically when a validated conversion starts, so building this
        # panel creates nothing and promises no run number. The base is changed in
        # Preferences & Data.
        self.var_outdir = tk.StringVar(value=output_paths.destination_hint(TOOL_KEY))
        # Preferences & Data can change the base while this panel is alive; the
        # shared registry re-points this display the moment that happens.
        output_paths.register_destination_hint(TOOL_KEY, self.var_outdir)

        self.bitrate_var = tk.StringVar(value="192k")
        self.voice_var = tk.StringVar(value=DEFAULT_SPEAKER)
        self.overwrite_var = tk.BooleanVar(value=True)
        self.workers_var = tk.StringVar(value="2")
        self.resume_var = tk.BooleanVar(value=True)
        # v0.6.5 Phase 7 (Compact TTS UI, P1/P10/P14): sentence/paragraph/title/
        # chapter pause, end-silence and trim-threshold/trim-edge-chunks are no
        # longer user-editable Tk state. The maintainer-approved per-voice
        # policy behind them (voice_registry.VoiceEntry.timing_preset) is
        # applied directly in options() from the selected voice at run time --
        # unchanged in value, no longer exposed as a control (P9/P11: removing
        # a control is not license to change the policy it used to show).
        # rate/kokoro_speed remain live, user-editable controls (Band 3 keeps
        # them) and still take their per-voice default from the same preset.
        self.rate_var = tk.StringVar(value="+0%")
        self.kokoro_speed_var = tk.StringVar(value="1.0")
        self.selected_voice_label = tk.StringVar(value=DEFAULT_VOICE_LABEL)

        # ---- the shared importing foundation ------------------------------ #
        # One pump owns this panel's whole scheduled-callback chain: the import
        # poller rides its `schedule` seam and the conversion worker's queue is
        # registered as a drain. There is no second `after` loop.
        self._pump = job_ui.MainThreadPump(self)
        self.import_catalog = build_catalog()
        self._manager = ImportedFileManager(id_factory=id_factory)
        self._coordinator = ImportCoordinator(
            self._manager,
            scanner=scanner,
            clock=self._clock,
            id_factory=id_factory,
            # Handed to the coordinator rather than the adapter deliberately: the
            # coordinator asks it *before* it creates a thread, so a decline starts
            # no worker at all.
            confirm_broad_root=(self._confirm_broad_root if confirm_broad_root is None
                                else confirm_broad_root),
            thread_factory=thread_factory,
            **({} if home is None else {"home": home}),
        )

        # ---- layout ------------------------------------------------------- #
        # The imported queue sits OUTSIDE the scrollable options area, alongside
        # the action buttons and the log, so Add and Remove stay reachable however
        # far the form is scrolled. The form itself is untouched: this tool's
        # options are ~1300 px of controls against ~660 px of visible window, so
        # they still live in a vertically scrollable canvas.
        self.rowconfigure(0, weight=0)   # the imported queue — fixed, always visible
        self.rowconfigure(1, weight=1)   # scrollable options grow with the window
        self.rowconfigure(2, weight=0)   # Start — fixed, always visible
        self.rowconfigure(3, weight=1)   # the shared run controls and Summary
        self.rowconfigure(4, weight=0)   # engine transcript — fixed height
        self.columnconfigure(0, weight=1)

        self.importer = job_ui.ImportAdapter(
            self,
            catalog=self.import_catalog,
            effective_config=self._effective_config,
            pump=self._pump,
            manager=self._manager,
            coordinator=self._coordinator,
            # No theme bundle: this panel stays classic on Windows. Converting it to
            # the namespaced design system belongs to Plan 9, and an empty style name
            # is exactly what ttk means by "draw this the way the platform draws it".
            theme=None,
            clock=self._clock,
            id_factory=id_factory,
            choose_files=self._choose_files if choose_files is None else choose_files,
            choose_folder=(self._choose_folder if choose_folder is None
                           else choose_folder),
            confirm_large_result=(self._confirm_large_result
                                  if confirm_large_result is None
                                  else confirm_large_result),
            list_height=6,
        )
        self.importer.frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 6))

        canvas_wrap = ttk.Frame(self)
        canvas_wrap.grid(row=1, column=0, sticky="nsew")
        canvas_wrap.rowconfigure(0, weight=1)
        canvas_wrap.columnconfigure(0, weight=1)
        options_canvas = tk.Canvas(canvas_wrap, highlightthickness=0, borderwidth=0)
        options_canvas.grid(row=0, column=0, sticky="nsew")
        options_sb = ttk.Scrollbar(
            canvas_wrap, orient="vertical", command=options_canvas.yview
        )
        options_sb.grid(row=0, column=1, sticky="ns")
        options_canvas.configure(yscrollcommand=options_sb.set)

        frm = ttk.Frame(options_canvas, padding=10)
        _frm_window = options_canvas.create_window((0, 0), window=frm, anchor="nw")
        frm.columnconfigure(1, weight=1)

        def _sync_scrollregion(_event: object | None = None) -> None:
            options_canvas.configure(scrollregion=options_canvas.bbox("all"))

        def _sync_form_width(event: object) -> None:
            # Make the form fill the canvas width so "ew" rows expand as before.
            options_canvas.itemconfigure(_frm_window, width=event.width)

        frm.bind("<Configure>", _sync_scrollregion)
        options_canvas.bind("<Configure>", _sync_form_width)

        # The launcher reuses one root across tools, so wheel binding is scoped to
        # while the pointer is over this panel (the wrap frame, not the canvas —
        # the form frame covers the canvas, so the canvas itself almost never gets
        # the pointer).
        enable_mousewheel(options_canvas, hover_region=canvas_wrap)

        r = 0
        ttk.Label(frm, text="Output folder").grid(
            row=r, column=0, sticky="nw", pady=(8, 0))
        outf = ttk.Frame(frm)
        outf.grid(row=r, column=1, sticky="ew", pady=(8, 0))
        outf.columnconfigure(0, weight=1)
        self.entry_outdir = ttk.Entry(outf, textvariable=self.var_outdir,
                                      state="readonly")
        self.entry_outdir.grid(row=0, column=0, sticky="ew")
        r += 1
        ttk.Label(
            frm,
            text="Each conversion gets its own numbered run folder here. "
                 "Change the location in Preferences & Data.",
        ).grid(row=r, column=1, sticky="w", pady=(2, 0))
        r += 1

        # v0.6.5 Phase 7 (Compact TTS UI): Band 2 (Voice/Engine) built first, then
        # Band 3 (Audio/Processing) -- the rate control that Band 3 keeps depends
        # on which backend Band 2 selected, so the dependent widgets exist before
        # _on_voice_selected() is ever called (moved to the end of both bands).
        voice_frm = ttk.LabelFrame(frm, text="Voice / Engine", padding=8)
        voice_frm.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        voice_frm.columnconfigure(1, weight=1)
        r += 1

        ttk.Label(voice_frm, text="Voice / Engine").grid(row=0, column=0, sticky="w")
        self.voice_combo = ttk.Combobox(
            voice_frm,
            textvariable=self.selected_voice_label,
            values=display_labels(),
            state="readonly",
            width=52,
        )
        self.voice_combo.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        self.backend_label_var = tk.StringVar(value="")
        ttk.Label(voice_frm, textvariable=self.backend_label_var,
                  foreground="navy").grid(row=1, column=0, columnspan=2, sticky="w",
                                          pady=(4, 0))

        self.kokoro_notice_var = tk.StringVar(value="")
        self.kokoro_notice_lbl = ttk.Label(
            voice_frm,
            textvariable=self.kokoro_notice_var,
            wraplength=560,
            foreground="darkorange",
            justify=tk.LEFT,
        )
        self.kokoro_notice_lbl.grid(row=2, column=0, columnspan=2, sticky="w",
                                    pady=(4, 0))
        self.kokoro_notice_lbl.grid_remove()

        # The truthful "this voice cannot run here" line. Same row of the same
        # frame as every other voice message — this is the existing pattern, not a
        # new voice-management screen. It is empty and hidden unless the selected
        # voice genuinely needs setting up on this computer.
        self.voice_status_var = tk.StringVar(value="")
        self.voice_status_lbl = ttk.Label(
            voice_frm,
            textvariable=self.voice_status_var,
            wraplength=560,
            foreground="firebrick",
            justify=tk.LEFT,
        )
        self.voice_status_lbl.grid(row=3, column=0, columnspan=2, sticky="w",
                                   pady=(4, 0))
        self.voice_status_lbl.grid_remove()

        # Band 3 — Audio/Processing (§10): MP3 bitrate, requested file workers
        # with truthful effective-cap reporting (P14), and the one rate control
        # the selected backend actually supports (Edge %, Kokoro speed, or
        # neither for Chatterbox Turbo — never a fake control). Bitrate and
        # workers apply to every queued item regardless of provenance (Phase 6
        # unified direct/folder dispatch); this replaces the two separate
        # "files added directly" / "imported from a folder" groups, which had
        # become misleading once that unification landed.
        audio_frm = ttk.LabelFrame(frm, text="Audio / Processing", padding=8)
        audio_frm.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        audio_frm.columnconfigure(1, weight=1)
        r += 1
        ar = 0
        ttk.Label(audio_frm, text="MP3 bitrate").grid(row=ar, column=0, sticky="w")
        self.combo_bitrate = ttk.Combobox(
            audio_frm,
            textvariable=self.bitrate_var,
            values=("128k", "192k", "320k"),
            width=10,
            state="readonly",
        )
        self.combo_bitrate.grid(row=ar, column=1, sticky="w")
        ar += 1

        ttk.Label(audio_frm, text="File workers (requested)").grid(
            row=ar, column=0, sticky="w", pady=(6, 0))
        self.spin_workers = ttk.Spinbox(
            audio_frm, from_=1, to=16, textvariable=self.workers_var, width=6)
        self.spin_workers.grid(row=ar, column=1, sticky="w", pady=(6, 0))
        ar += 1
        ttk.Label(
            audio_frm,
            text=(
                "Concurrency is between whole files only, never inside one file's "
                "own synthesis. The effective cap actually used this run — limited "
                "by files queued, the selected engine, and this computer — is "
                "reported truthfully at the top of Engine output below."
            ),
            wraplength=560,
            justify=tk.LEFT,
            foreground="gray",
        ).grid(row=ar, column=0, columnspan=2, sticky="w", pady=(0, 6))
        ar += 1

        # Exactly one of these two is shown, chosen by the selected voice's
        # backend in _on_voice_selected(); Chatterbox Turbo shows neither, since
        # the pinned engine exposes no rate/speed parameter at all.
        self.edge_rate_frm = ttk.Frame(audio_frm)
        self.edge_rate_frm.grid(row=ar, column=0, columnspan=2, sticky="w")
        ttk.Label(self.edge_rate_frm, text="Edge speech rate:").pack(side=tk.LEFT)
        ttk.Entry(self.edge_rate_frm, textvariable=self.rate_var, width=10).pack(
            side=tk.LEFT, padx=(8, 0))
        ttk.Label(
            self.edge_rate_frm,
            text=("  e.g. +0%, -10%  (folder-imported Edge files only — direct "
                  "Edge files always use Edge's own natural pace)"),
            foreground="gray",
        ).pack(side=tk.LEFT, padx=(6, 0))

        self.kokoro_speed_frm = ttk.Frame(audio_frm)
        self.kokoro_speed_frm.grid(row=ar, column=0, columnspan=2, sticky="w")
        ttk.Label(self.kokoro_speed_frm, text="Kokoro speed (0.5 – 2.0):").pack(
            side=tk.LEFT)
        ttk.Spinbox(
            self.kokoro_speed_frm,
            from_=0.5,
            to=2.0,
            increment=0.05,
            textvariable=self.kokoro_speed_var,
            width=8,
            format="%.2f",
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(
            self.kokoro_speed_frm,
            text="  (1.0 = normal; <1.0 slower; >1.0 faster)",
            foreground="gray",
        ).pack(side=tk.LEFT, padx=(6, 0))
        ar += 1

        self.voice_combo.bind("<<ComboboxSelected>>", self._on_voice_selected)
        self._on_voice_selected()

        run_opts = ttk.Frame(frm)
        run_opts.grid(row=r, column=0, columnspan=2, sticky="w", pady=(10, 0))
        r += 1
        ttk.Checkbutton(run_opts, text="Resume (skip existing MP3s)",
                        variable=self.resume_var).pack(side=tk.LEFT)
        self.chk_overwrite = ttk.Checkbutton(
            run_opts, text="Overwrite existing outputs without asking",
            variable=self.overwrite_var)
        self.chk_overwrite.pack(side=tk.LEFT, padx=(16, 0))

        # Footer help text — last row of the scrollable form.
        ttk.Label(
            frm,
            text=(
                "Default voice: Microsoft Edge TTS — Steffan (en-US-SteffanNeural). "
                "Edge TTS voices use network synthesis via edge-tts (no Natural "
                "Reader login). Kokoro voices (Heart, Bella, Michael, Emma, George) "
                "run locally using the Kokoro-82M open-source AI model; ~300 MB "
                "model download required on first use. The cloned voices run "
                "locally too, from reference recordings kept on this computer; if "
                "a recording is not present here, that voice reports what it needs "
                "and the other voices are unaffected."
            ),
            wraplength=620,
            justify=tk.LEFT,
        ).grid(row=r, column=0, columnspan=2, sticky="w", pady=(8, 0))

        # --- Start (row 2): always visible, outside the scroll area. -----------
        # Start stays this panel's own button: the shared JobControlBar owns Pause,
        # Resume, Cancel and the retry control but deliberately does not own Start.
        # It is locked through the shared matrix all the same, as a processing option.
        btn_row = ttk.Frame(self, padding=(10, 8))
        btn_row.grid(row=2, column=0, sticky="w")
        self.go_btn = ttk.Button(btn_row, text="Start", command=self.run_job)
        self.go_btn.pack(side=tk.LEFT)
        # Neither of these is a processing option, so neither locks through the
        # shared matrix — matching the sibling MP3/M4B tools' own convention
        # (m4b_converter.py/mp3_tool.py): opening the output folder or clearing
        # the visible transcript never interferes with a run in flight.
        self.btn_open_out = ttk.Button(
            btn_row, text="Open Output Folder", command=self.open_output_folder)
        self.btn_open_out.pack(side=tk.LEFT, padx=(8, 0))
        self.btn_clear_log = ttk.Button(
            btn_row, text="Clear Log", command=self.clear_log)
        self.btn_clear_log.pack(side=tk.LEFT, padx=(8, 0))

        # --- The shared run controls (row 3): progress, ETA, Summary/Details. ---
        self.job_area = ttk.Frame(self)
        self.job_area.grid(row=3, column=0, sticky="nsew", padx=10, pady=(0, 6))
        self.job_area.rowconfigure(0, weight=1)
        self.job_area.columnconfigure(0, weight=1)

        # --- Engine transcript (row 4): raw stdout/stderr, not the job record. ---
        # The engines are unchanged and chatty; their output is captured here as a
        # transcript. What *happened* in the run — its state, its progress, what
        # failed and how it ended — is the job adapter's Summary and Details above,
        # and this box reports none of it.
        log_font = ("Consolas", 10) if sys.platform == "win32" else ("Menlo", 11)
        logf = ttk.LabelFrame(self, text="Engine output", padding=(8, 4))
        logf.grid(row=4, column=0, sticky="nsew", padx=10, pady=(0, 10))
        logf.rowconfigure(0, weight=1)
        logf.columnconfigure(0, weight=1)
        self.log = scrolledtext.ScrolledText(
            logf, height=8, state=tk.DISABLED, wrap=tk.WORD, font=log_font
        )
        self.log.grid(row=0, column=0, sticky="nsew")

        # The worker->GUI queue is a drain on the one pump, not a second chain.
        self._pump.add_drain(self._drain_worker_queue)
        self._install_jobs(IDLE_RUN_ID, ())
        self._pump.start()

    # ------- the imported queue (owned by the shared manager) -------

    @property
    def manager(self) -> ImportedFileManager:
        """The single authority on the imported queue. Read it; never shadow it."""
        return self._manager

    def imported_files(self) -> list[Path]:
        """The imported paths, in queue order, from the manager's snapshot.

        Main thread only, and the list it returns is a plain copy: what a run
        freezes is this value, so a later import mutates the manager and never a
        run that has already started.
        """
        return [imported.path for imported in self._manager.snapshot().files]

    # ------- dialogs and confirmations, all on the owner thread -------

    def _choose_files(self) -> tuple[str, ...]:
        """The Add Files dialog. Order is the dialog's, and it is preserved."""
        return tuple(filedialog.askopenfilenames(
            parent=self,
            title="Source files",
            filetypes=[
                ("Audiobook sources", "*.pdf *.txt"),
                ("All files", "*.*"),
            ],
        ) or ())

    def _choose_folder(self) -> tuple[str, ...]:
        """The Add Folder dialog. One root, returned as the tuple the seam wants."""
        chosen = filedialog.askdirectory(
            parent=self, title="Folder of PDF / TXT files", mustexist=True)
        return (str(chosen),) if chosen else ()

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
            "Add a large number of files?",
            f"{outcome.proposed_count:,} files are ready to be added.\n\n"
            "Adding this many at once can make the queue slow to work with. "
            "Add them?",
        )

    # ------- voice selection -------

    def _on_voice_selected(self, event: object | None = None) -> None:
        label = self.selected_voice_label.get()
        entry = get_voice(label)
        if entry is None:
            return

        self.voice_var.set(entry.voice_id)

        # Only the two retained, user-editable controls (Band 3) take a default
        # from the preset now; the pause/trim fields Phase 7 removed are read
        # directly from entry.timing_preset in options() instead, at run time.
        preset = entry.timing_preset
        self.rate_var.set(preset["rate"])
        self.kokoro_speed_var.set(preset["kokoro_speed"])

        if entry.backend == "chatterbox":
            # No speed/rate control at all: the pinned engine exposes no such
            # parameter, so showing Kokoro's (or Edge's) would be a lie about
            # what it does. No temperature, exaggeration or cfg_weight control
            # either — the maintainer approved these voices at the engine's own
            # defaults, and this phase integrates them rather than building a
            # tuning console.
            self.backend_label_var.set(
                f"Engine: {CHATTERBOX_ENGINE_LABEL}  |  Voice: {entry.voice_id}  "
                f"|  Group: {entry.group_label}"
            )
            self.kokoro_speed_frm.grid_remove()
            self.edge_rate_frm.grid_remove()
            self.kokoro_notice_lbl.grid_remove()
            self._refresh_voice_status(entry)
        elif entry.backend == "kokoro":
            self.backend_label_var.set(
                f"Engine: Kokoro local AI  |  Voice code: {entry.voice_id}  "
                f"|  Group: {entry.group_label}"
            )
            self.edge_rate_frm.grid_remove()
            self.kokoro_speed_frm.grid()
            notice = (
                "Kokoro voices run locally. On first use, ~300 MB of model weights "
                "may be downloaded from HuggingFace and cached under "
                "~/.cache/huggingface/. Ensure 'kokoro', 'soundfile', and 'scipy' "
                "are installed ('pip install kokoro soundfile scipy'). "
            )
            if sys.version_info >= (3, 13):
                notice += (
                    "WARNING: PyPI 'kokoro' currently requires Python 3.10–3.12. "
                    "Use a Python 3.12 virtual environment for Kokoro voices."
                )
            self.kokoro_notice_var.set(notice)
            self.kokoro_notice_lbl.grid()
            self._refresh_voice_status(entry)
        else:
            self.backend_label_var.set(
                f"Engine: Microsoft Edge TTS  |  Voice ID: {entry.voice_id}  "
                f"|  Group: {entry.group_label}"
            )
            self.kokoro_speed_frm.grid_remove()
            self.edge_rate_frm.grid()
            self.kokoro_notice_lbl.grid_remove()
            self._refresh_voice_status(entry)

    def _refresh_voice_status(self, entry) -> tuple[bool, str]:
        """Project the selected voice's real availability onto this panel.

        Main thread only, and deliberately the *whole* of the projection: one
        boolean and one message, recomputed from the engine's own answer. There is
        no second registry here and no second state machine — a voice stays
        registered whatever this returns, and this returns what the engine says
        rather than deciding anything itself.

        Asked again at Start as well as at selection, because the answer can change
        while the panel is open: a reference recording the maintainer moves between
        picking a voice and pressing Start must stop the run, not fail inside it.

        Edge and Kokoro are never asked. Nothing local has to be present for them,
        so they are unconditionally available and the local cloning engine is never
        loaded, probed or imported on their account.
        """
        if entry is None or entry.backend != "chatterbox":
            self._voice_available = True
            self.voice_status_var.set("")
            self.voice_status_lbl.grid_remove()
            return True, ""

        ok, reason = self._chatterbox_status(entry.voice_id)
        self._voice_available = bool(ok)
        if self._voice_available:
            self.voice_status_var.set("")
            self.voice_status_lbl.grid_remove()
        else:
            self.voice_status_var.set(reason)
            self.voice_status_lbl.grid()
        return self._voice_available, reason

    # ------- worker -> GUI queue drain (main thread, on the one pump) -------

    def append_log(self, msg: str) -> None:
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, msg)
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def clear_log(self) -> None:
        """Clear the visible transcript only. The run's own history — its event
        stream, its frozen result, Summary/Details above — is untouched."""
        self.log.configure(state=tk.NORMAL)
        self.log.delete("1.0", tk.END)
        self.log.configure(state=tk.DISABLED)

    def open_output_folder(self) -> None:
        """Reveal this run's own numbered output folder, or the tool's parent
        folder before any run has reserved one -- matching the sibling MP3/M4B
        tools' own Open Output Folder behavior."""
        try:
            target = (self._run_directory if self._run_directory is not None
                      else output_paths.ensure_tool_parent(TOOL_KEY))
        except output_paths.OutputPathError as exc:
            messagebox.showerror("Output folder", exc.message)
            return
        sp.reveal_in_file_manager(target)

    def _drain_worker_queue(self) -> None:
        """Drain the conversion worker's queue. Registered once, on the pump.

        The single :class:`~shared.job_ui.MainThreadPump` calls this on every tick,
        alongside the import poller and the job adapter's own drain, so exactly one
        Tk callback is ever outstanding. It carries the engine transcript, the
        measured timings and the settled result — never a state claim, which only a
        controller snapshot may make.
        """
        try:
            while True:
                kind, payload = self._log_q.get_nowait()
                if kind == "log":
                    self.append_log(payload)
                elif kind == TIMING_MESSAGE:
                    self._record_timing(payload)
                elif kind == RESULT_MESSAGE:
                    self._settle(payload)
                elif kind == "done":
                    self.append_log(str(payload) + "\n")
                    self._finish_idle()
        except queue.Empty:
            pass

    def _record_timing(self, sample: TimingSample) -> bool:
        """Apply one measured duration to this run's estimate. Main thread only.

        Reached only from the drain above, so this is the single place any estimator
        is ever mutated and the worker never holds one at all. A sample is dropped,
        inertly, if the panel has closed, if it belongs to a run this panel has moved
        on from, or if it belongs to an earlier attempt of the same run — none of
        which is an error, because the estimate it described no longer exists.
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
        """Take the settled run so the shared controls can offer what it allows.

        The result is the only authority on what failed and what may be retried;
        this panel keeps no rival list beside it.
        """
        self._result = result
        jobs = getattr(self, "jobs", None)
        if jobs is not None and not jobs.closed:
            jobs.set_result(result)

    def _finish_idle(self) -> None:
        self._busy.clear()
        self.go_btn.configure(state=tk.NORMAL)

    def set_locked(self, locked: bool) -> None:
        """The shared lock matrix's hook onto this panel's processing options.

        The imported queue is *not* locked here: it is registered with the adapter
        as imported input and locks through the same matrix as a separate kind. The
        import *status* bar deliberately stays live either way — a scan that was
        already running when a conversion started can still be stopped, and that stop
        reaches the coordinator only, never this run's controller.
        """
        for widget in (self.go_btn, self.spin_workers, self.chk_overwrite):
            widget.configure(state=tk.DISABLED if locked else tk.NORMAL)
        # The two dropdowns are pick-one lists, never typeable: unlocking them
        # returns them to "readonly", not to "normal".
        for combo in (self.combo_bitrate, self.voice_combo):
            combo.configure(state=tk.DISABLED if locked else "readonly")

    # ------- the shared run controls -------

    @property
    def job_estimator(self):
        """The current run's rolling estimate, or ``None`` before the first run."""
        return self._estimator

    def destinations(self) -> dict:
        """Occurrence id to planned output, for the frozen run. A copy, always."""
        return dict(self._destinations)

    def _install_jobs(self, run_id: str, item_ids) -> None:
        """Point the shared run controls at one run. Main thread only.

        A run owns its event stream and its estimate, and neither can be rebound, so
        a new run gets a new adapter in the same container. The retired one is closed
        first, which is what drops its drain — the pump keeps exactly one job drain
        however many runs a session performs.

        This is also the one point at which an attempt's publication authority is
        retired. It matters because a retry re-uses the original ``RunSnapshot`` and
        therefore the original run id: without retirement, a late report from the
        attempt being re-run would carry the live run's id and be indistinguishable
        from a live one.
        """
        previous = getattr(self, "jobs", None)
        if previous is not None:
            previous.close()
            previous.frame.destroy()
        retiring = getattr(self, "_publisher", None)
        if retiring is not None:
            retiring.close()
        self._publisher = None
        self._event_q = queue.Queue()
        self._estimator = job_control.EtaEstimator(run_id, clock=self._clock)
        self.jobs = job_ui.JobAdapter(
            self.job_area,
            run_id=run_id,
            pump=self._pump,
            # No theme bundle: this panel stays classic on Windows until Plan 9.
            theme=None,
            pull=job_ui.queue_pull(self._event_q),
            estimator=self._estimator,
            # The one session log this application already opens. Technical detail
            # and failures reach it through the stream; milestones deliberately do
            # not, because they are already on screen.
            bridge=job_control.LoggerBridge(),
            item_ids=item_ids,
            on_pause=self.pause,
            on_resume=self.resume,
            on_cancel=self.cancel_job,
            on_retry=self.retry_failed,
            details_height=8,
        )
        self.jobs.frame.grid(row=0, column=0, sticky="nsew")
        # One progress model, not two: this panel's indicator *is* the shared status
        # view's, so nothing can draw a second, disagreeing bar.
        self.progress = self.jobs.status.indicator
        self.jobs.register_inputs(self.importer)
        self.jobs.register_options(self)
        self.jobs.render()

    def _on_state(self, snapshot):
        """The controller's listener: copy its state into the event stream.

        The event is minted *from this snapshot*, so the UI can never show a state
        the controller did not actually reach; and it goes through the run's one
        publication authority, so it cannot overtake — or be overtaken by — a
        report the worker is making at the same moment.

        Called from whichever thread moved the run: the Tk thread for a button
        press, the worker or a pool thread for a checkpoint or a settlement.
        """
        publisher = self._publisher
        return None if publisher is None else publisher.state_changed(snapshot)

    def pause(self) -> None:
        """Ask the run to pause at its next boundary between source files."""
        controller = self._controller
        if controller is not None:
            controller.request_pause()

    def resume(self) -> None:
        """Return a paused run to running and wake its worker."""
        controller = self._controller
        if controller is not None:
            controller.resume()

    def retry_failed(self):
        """Re-run only the retryable failures, against the exact original run.

        Everything comes from the settled :class:`~shared.job_control.RunResult`: the
        snapshot the run was accepted with, the failures it actually recorded, and
        the destinations that run planned. Nothing is read from the imported list,
        the widgets or the configuration as they stand now — which is what keeps a
        retried file landing where it would originally have landed, and what stops it
        overwriting an output that already succeeded.
        """
        result = self._result
        if result is None or self._busy.is_set() or not result.has_retryable:
            return None
        request = result.retry()
        return self._launch(request.snapshot, request.item_ids)

    # ------- starting and cancelling a conversion -------

    def run_job(self) -> None:
        """Freeze the queue, reserve a run, and hand plain values to a worker."""
        if self._busy.is_set():
            return
        snapshot = self._manager.snapshot()
        if snapshot.is_empty:
            messagebox.showwarning("Missing input", "Add at least one PDF or TXT file.")
            return

        # One backend value decides everything downstream: which engine converts,
        # which controls applied, how a destination is named. It comes from the
        # registry entry, never from the label the user sees, and a run carries it
        # frozen so a retry cannot be answered by today's dropdown.
        current_voice_entry = get_voice(self.selected_voice_label.get())
        speaker = self.voice_var.get().strip() or DEFAULT_SPEAKER
        backend = "edge" if current_voice_entry is None else current_voice_entry.backend
        voice_id = (speaker if current_voice_entry is None
                    else current_voice_entry.voice_id)

        # A locally cloned voice needs its reference recording on *this* computer.
        # Asked here rather than trusted from selection time, and before anything is
        # frozen, reserved or synthesised — so an unavailable voice stops the run at
        # the button instead of failing partway through a conversion. Nothing falls
        # back to another voice or another engine.
        available, unavailable_reason = self._refresh_voice_status(current_voice_entry)
        if not available:
            messagebox.showwarning("Voice unavailable", unavailable_reason)
            return

        # v0.6.5 Phase 7 removed the user-editable pause/trim controls this used
        # to read from widgets; the maintainer-approved per-voice policy behind
        # them is unchanged and is applied here directly from the registry
        # instead (P9/P11 — removing a control is not license to change the
        # policy it used to show). These values are fixed, known-good literals
        # from voice_registry.py, never user input, so there is nothing left to
        # validate here the way the removed widgets once needed.
        preset = (current_voice_entry.timing_preset if current_voice_entry is not None
                 else _default_timing_preset())
        pause_kw: dict = {}
        if backend == "edge":
            pause_kw = {
                "sentencepause": int(preset["sentencepause"]),
                "paragraphpause": int(preset["paragraphpause"]),
                "title_trailing_pause": int(preset["title_ms"]),
                "chapter_trailing_pause": int(preset["chapter_ms"]),
                "end_of_book_pause": int(preset["end_pause"]),
                "trim_tts_padding": bool(preset["trim_edge_chunks"]),
                "trim_silence_db": float(preset["trim_dbfs"]),
            }

        # Read every remaining Tk variable here on the main thread. The worker runs
        # off-thread, and touching Tk vars/widgets from another thread raises "main
        # thread is not in main loop"; the worker must use these plain copies and
        # talk to the GUI only through the thread-safe queues the pump drains.
        try:
            workers = int(self.workers_var.get() or "2")
        except ValueError:
            workers = 2
        try:
            kokoro_speed = float(self.kokoro_speed_var.get())
        except ValueError:
            kokoro_speed = 1.0
        end_pause = int(preset["end_pause"])
        paragraph_pause = int(preset["paragraphpause"])

        # Decision 9A, in one call: the imported queue, the catalog, the import
        # options, the effective configuration and every output-affecting setting
        # are copied here, on the main thread, and never consulted again.
        self._run_count += 1
        snapshot = capture_run(
            snapshot_id=f"tts-run-{self._run_count}",
            files=self._manager,
            catalog=self.import_catalog,
            import_options=self.importer.options.options(),
            effective_config=self._effective_config,
            tool_options=freeze_tts_options(
                speaker=speaker,
                backend=backend,
                voice_id=voice_id,
                rate=self.rate_var.get().strip() or "+0%",
                resume=self.resume_var.get(),
                overwrite=self.overwrite_var.get(),
                bitrate=self.bitrate_var.get(),
                workers=workers,
                kokoro_speed=kokoro_speed,
                end_pause=end_pause,
                paragraph_pause=paragraph_pause,
                pause_kw=pause_kw,
            ),
            created_at=float(self._clock()),
        )

        # Input validated; only now is a run directory reserved. Merely opening the
        # tool, importing, browsing or switching panels creates nothing.
        try:
            reservation = output_paths.reserve_run_directory(TOOL_KEY)
        except output_paths.OutputPathError as exc:
            messagebox.showerror("Output folder", exc.message)
            return
        run_directory = reservation.run_directory

        # Every destination is decided here, on the main thread, through Plan 2's
        # planners and one shared collision tracker — so two occurrences can never
        # be planned onto the same path, whichever half of the queue they came from.
        # Keyed by occurrence id, because that is the identity a retry needs.
        try:
            destinations = plan_destinations(
                snapshot.files,
                run_directory,
                # Only the Edge engine names its own artifact after the speaker.
                # Every local engine writes ``<stem>.mp3``, so they share one shape.
                direct_rename=(
                    (lambda source: direct_output_name(source, speaker))
                    if backend == "edge" else mp3_output_name
                ),
                grouped_rename=mp3_output_name,
                planner=reservation.planner(),
            )
        except output_paths.OutputPathError as exc:
            messagebox.showerror("Output folder", exc.message)
            return

        self.var_outdir.set(str(run_directory))
        return self._launch(snapshot, snapshot.item_ids,
                            destinations=destinations, run_directory=run_directory)

    def _launch(self, snapshot, item_ids, *, destinations=None, run_directory=None):
        """Accept one run — first attempt or retry — and hand it to a worker.

        The frozen snapshot decides everything: which occurrences run, in which
        order, with which voice, at which bitrate, with which pauses, and where each
        output goes. A retry re-uses the destinations its original run planned, so a
        retried file lands exactly where it would have landed and cannot take a name
        an earlier success already occupies.
        """
        if destinations is not None:
            self._destinations = dict(destinations)
        if run_directory is not None:
            self._run_directory = run_directory

        wanted = tuple(item_ids)
        options = snapshot.tool_options
        items = []
        for occurrence_id in wanted:
            planned = self._destinations[occurrence_id]
            items.append({
                "item_id": occurrence_id,
                "source": planned.source,
                "destination": planned.destination,
                "direct": planned.direct,
            })

        self._snapshot = snapshot
        self._result = None
        self._attempt += 1
        self._controller = job_control.JobController(
            snapshot.snapshot_id, listener=self._on_state)
        self._install_jobs(snapshot.snapshot_id, snapshot.item_ids)
        # Built after the adapter, so it binds *this* attempt's queue, and before
        # the controller is started, so the very first state change is published.
        self._publisher = RunPublisher(
            snapshot, clock=self._clock, sink=self._event_q)

        params = {
            "items": items,
            "run_directory": self._run_directory,
            # Every processing setting comes from the frozen snapshot, never from a
            # widget — which is what makes a retry use the run's own settings.
            "speaker": options["speaker"],
            # The run's engine identity, frozen. A retry re-reads this and never
            # the combobox, so changing the voice after a failure cannot change
            # which engine or which voice the retry uses.
            "backend": options["backend"],
            "voice_id": options["voice_id"],
            "rate": options["rate"],
            "resume": options["resume"],
            "overwrite": options["overwrite"],
            "bitrate": options["bitrate"],
            "workers": options["workers"],
            "kokoro_speed": options["kokoro_speed"],
            "end_pause": options["end_pause"],
            "paragraph_pause": options["paragraph_pause"],
            "pause_kw": dict(options["pause_kw"]),
            "snapshot": snapshot,
            "controller": self._controller,
            # The authority, never the reporter behind it: there must be exactly
            # one way for this run to reach the queue, with nothing to bypass.
            "publisher": self._publisher,
            # Timing travels back as data, never as a shared estimator: the worker
            # is handed the clock and the labels it needs to stamp a measurement,
            # and nothing it can mutate.
            "clock": self._clock,
            "run_id": snapshot.snapshot_id,
            "attempt": self._attempt,
            # A retry is being retried precisely because it failed, so the resume
            # skip — which exists to avoid redoing finished work — must not apply.
            "first_attempt": self._attempt == 1,
        }

        self._busy.set()
        self.go_btn.configure(state=tk.DISABLED)
        self.set_locked(True)
        self._controller.start()
        if self._run_directory is not None:
            self._publisher.output_location(self._run_directory)
        self._publisher.progress(0, len(items), stage=STAGE_CONVERT)

        self._worker = threading.Thread(
            target=self.conversion_worker, args=(params,), daemon=True)
        self._worker.start()
        return self._worker

    def cancel_job(self) -> None:
        """Ask the run to stop. Cooperative, and it wakes a paused worker.

        The controller is the only authority here. Pressing this does not make the
        run cancelled — it makes it *cancel-requested*, and only a worker arriving at
        a checkpoint, cleaning up and settling can make it ``CANCELLED``.
        """
        controller = self._controller
        if controller is None or controller.is_terminal:
            return
        controller.request_cancel()
        self.append_log(
            "Cancelling… will stop at the next checkpoint (chapter / chunk).\n")

    # ------- teardown -------

    def close(self) -> None:
        """Close the import side and stop the pump. Idempotent, and safe late.

        A conversion is asked to stop first, which is what makes closing a *paused*
        run safe: the request wakes a worker waiting at a checkpoint, so the bounded
        join below finds a thread already unwinding rather than one that will never
        be woken. Closing the import adapter cancels any running scan, joins its
        worker within the coordinator's bounded timeout and makes every later event
        inert; closing the job adapter drops its drain and makes every later event
        inert; closing the pump cancels the outstanding callback and forgets every
        drain. Nothing is left scheduled.
        """
        if self._closed:
            return
        self._closed = True
        # Retired *before* the run is asked to stop, and deliberately so. Closing
        # takes no lock, so it cannot be blocked behind a report already in flight;
        # and a panel that is going away must draw nothing further, so the state
        # changes the cancellation below provokes have nowhere to go.
        publisher = self._publisher
        if publisher is not None:
            publisher.close()
        controller = self._controller
        if controller is not None and not controller.is_terminal:
            controller.request_cancel()
        worker = self._worker
        if worker is not None and hasattr(worker, "join"):
            worker.join(WORKER_JOIN_TIMEOUT)
        self._worker = None
        importer = getattr(self, "importer", None)
        if importer is not None:
            importer.close()
        jobs = getattr(self, "jobs", None)
        if jobs is not None:
            jobs.close()
        pump = getattr(self, "_pump", None)
        if pump is not None:
            pump.close()

    def destroy(self):
        self.close()
        super().destroy()

    # ------- worker (thread) -------

    def conversion_worker(self, params: dict) -> None:
        """Convert every frozen item, cooperatively, on a worker thread.

        Touches no widget, no Tk variable, no estimator and no object the main
        thread also mutates — **including the imported-file manager**: everything it
        needs arrived in *params* as frozen values, and everything it says goes out
        through the panel's queue and the run's reporter. The conversion helpers it
        calls are module-level functions taking that queue, deliberately: a worker
        that can only reach ``_log_q`` is a worker that cannot read a Tk variable by
        accident.

        Every item -- direct and folder-derived alike -- goes through one pool of
        file-level workers (P14): a directly added file still takes the rich
        chapter/pause engine and a folder-derived file still takes the chunked
        batch worker, exactly as before, but both provenances now share one
        resolved effective-worker count instead of running direct items strictly
        one at a time ahead of a separately pooled folder half. Both engines are
        called unchanged, each with the destination the main thread planned for
        it and each with the controller's own cancel predicate.
        """
        log_q = self._log_q
        run = _RunContext(params, log_q)
        with contextlib.redirect_stdout(run.writer), \
                contextlib.redirect_stderr(run.writer):
            run.execute()


# --------------------------------------------------------------------------- #
# The run body — worker-thread only, and deliberately outside the panel
# --------------------------------------------------------------------------- #


class _RunContext:
    """One attempt's worker-side state. Holds no panel and no Tk object.

    Everything here came from the frozen snapshot by way of ``params``, plus the
    queue the main thread drains and the controller that owns the run's state. It
    exists so the worker body can be read as a sequence of steps rather than one
    long function, and so that the panel attribute surface a worker touches stays a
    single queue.
    """

    def __init__(self, params: dict, log_q) -> None:
        self.params = params
        self.log_q = log_q
        self.writer = QueueWriter(log_q)
        self.controller = params["controller"]
        self.publisher = params["publisher"]
        self.snapshot = params["snapshot"]
        self.clock = params["clock"]
        self.run_id = params["run_id"]
        self.attempt = params["attempt"]
        self.cancel_check = self.controller.cancel_check
        self.items = list(params["items"])
        self.completed: list[str] = []
        self.failures: list = []
        self.cancelled = False
        self._done = 0
        self._total = len(self.items)
        self._counter = threading.Lock()

    # -- reporting ---------------------------------------------------------- #

    def log(self, message: str) -> None:
        self.log_q.put(("log", message + "\n"))

    def advance(self, item) -> None:
        """One file finished, however it finished. Progress is truthful, not tidy."""
        with self._counter:
            self._done += 1
            done = self._done
        self.publisher.progress(done, self._total, item_id=item["item_id"],
                               stage=STAGE_CONVERT)

    def record_success(self, item, duration: float, category: str) -> None:
        self.completed.append(item["item_id"])
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log(f"[{stamp}] {item['source'].name} — completed")
        self.log_q.put((TIMING_MESSAGE, TimingSample(
            run_id=self.run_id, attempt=self.attempt, category=category,
            duration=float(duration))))

    def record_failure(self, item, detail: str) -> None:
        """One source that would not convert. An item failure, never a job failure.

        The partial artifact that attempt left at *this occurrence's own* planned
        destination is removed — proved to be inside the run directory first, and
        never any sibling's output, because the planner gave every occurrence its
        own collision-safe path.
        """
        trouble = f"{item['source'].name} could not be converted."
        self.failures.append(FailureRecord(
            item_id=item["item_id"], stage=STAGE_CONVERT,
            display_message=trouble, technical_detail=detail,
            retryable=True, snapshot_id=self.snapshot.snapshot_id))
        self.publisher.failure(trouble, detail, item_id=item["item_id"],
                              stage=STAGE_CONVERT)
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log(f"[{stamp}] {item['source'].name} — FAILED: {detail}")
        discard_partial(item["destination"], self.params["run_directory"])

    # -- the run ------------------------------------------------------------ #

    def execute(self) -> None:
        try:
            ensure_punkt()
            self.filter_resumable()
            self.run_all_items()
        except ConversionCancelled:
            self.cancelled = True
        except Exception as exc:  # noqa: BLE001 - settled as a job failure below
            self.finish(lambda: self.settle_fatal(exc))
            return
        self.finish(self.settle)

    def finish(self, settler) -> None:
        """Settle the run, and release the panel whatever settling does.

        The ``done`` message is what returns the panel to idle, so it has to be sent
        even if settlement itself goes wrong. Without this, a contract error here
        would leave a non-technical user looking at a window that never unlocks and
        never says why.
        """
        try:
            settler()
        except Exception as exc:  # noqa: BLE001 - the last line of defence
            self.log_q.put(("log", f"The run could not be settled: {exc!r}\n"))
            self.log_q.put(("done", "The run could not be settled."))

    def filter_resumable(self) -> None:
        """Resume keeps its exact meaning: skip a folder target that already exists.

        A first attempt reserves a fresh numbered directory, so in the GUI this stays
        the no-op it has always been. A **retry** never applies it: a retried
        occurrence is being retried precisely because it failed, and the remains of
        that failure must not be mistaken for finished work.
        """
        if not self.params["resume"] or not self.params["first_attempt"]:
            return
        kept = []
        for item in self.items:
            if not item["direct"] and item["destination"].exists():
                self.log(f"Skipping (already exists): {item['source'].name}")
                continue
            kept.append(item)
        self.items = kept
        self._total = len(self.items)

    def run_all_items(self) -> None:
        """Every queued item -- direct and folder alike -- through one resolved
        pool of file-level workers (P14).

        One worker owns one whole source file through completion; a file's own
        synthesis units stay strictly sequential/in-order inside whichever
        engine call handles it (unchanged, below). Concurrency exists only
        *between* files. Pause is honoured at the one cooperative boundary
        each task hits before it starts real work -- ``controller.checkpoint()``
        -- so a task not yet dispatched waits there while paused, and a task
        already inside an indivisible engine call finishes it, exactly as
        this run has always behaved for a folder-pooled item.

        Every submitted future's result is drained, even one that finishes
        after cancellation was noticed elsewhere: silently discarding an
        already-completed conversion would leave a real output file on disk
        that this run never counted, logged or could retry -- an orphan, not
        a clean stop.
        """
        if not self.items:
            return
        from tts import batch_convert

        params = self.params
        backend = params["backend"]
        requested = int(params["workers"])
        effective = resolve_effective_workers(requested, len(self.items), backend)
        self.log(f"Requested workers: {requested} | Effective workers: {effective}")

        def convert(item):
            try:
                # The one cooperative boundary, and it sits *between* source
                # files: a pause or cancellation asked for during a chapter/
                # chunk is honoured here, not there.
                self.controller.checkpoint()
            except ConversionCancelled:
                return "cancelled", item, None, None
            self.publisher.current_item(
                item["item_id"], f"Converting {item['source'].name}")
            started = self.clock()
            try:
                # The one place the engines differ -- three calls deep in one
                # shared dispatch, not three pipelines. A direct Edge file
                # takes the rich chapter/pause engine; a folder-derived Edge
                # file takes the chunked batch worker. Kokoro/Chatterbox take
                # the same engine call regardless of provenance (P10).
                if backend == "kokoro":
                    convert_with_kokoro(item, params, self.log_q, self.log,
                                        self.cancel_check)
                elif backend == "chatterbox":
                    convert_with_chatterbox(item, params, self.log_q, self.log,
                                            self.cancel_check)
                elif item["direct"]:
                    convert_with_edge_engine(item, params, self.log_q,
                                             self.cancel_check)
                else:
                    status, _path, message = batch_convert.convert_single_pdf(
                        item["source"], params["run_directory"], params["speaker"],
                        params["rate"], self.log, None, self.cancel_check,
                        item["destination"], bitrate=params["bitrate"],
                    )
                    if status != "success":
                        return status, item, message, None
            except ConversionCancelled:
                discard_partial(item["destination"], params["run_directory"])
                return "cancelled", item, None, None
            except Exception as exc:  # noqa: BLE001 - one item, not the run
                return "failed", item, f"{type(exc).__name__}: {exc}", None
            category = ETA_CATEGORY_DIRECT if item["direct"] else ETA_CATEGORY_FOLDER
            return "success", item, None, (self.clock() - started, category)

        with ThreadPoolExecutor(max_workers=effective) as pool:
            futures = {pool.submit(convert, item): item for item in self.items}
            for future in as_completed(futures):
                status, item, message, extra = future.result()
                if status == "success":
                    duration, category = extra
                    self.record_success(item, duration, category)
                elif status == "cancelled":
                    self.cancelled = True
                    stamp = datetime.now().strftime("%H:%M:%S")
                    self.log(f"[{stamp}] {item['source'].name} — skipped (cancelled)")
                    discard_partial(item["destination"], params["run_directory"])
                else:
                    self.record_failure(item, message or "the conversion failed")
                self.advance(item)
                if self.cancel_check():
                    self.cancelled = True

    # -- settlement --------------------------------------------------------- #

    def settle(self) -> None:
        """Turn what happened into one terminal result, and settle the controller.

        Cancellation is claimed only if the controller genuinely acknowledged it at
        a checkpoint. If the work stopped because an engine raised at its own
        chapter/chunk checkpoint, the acknowledgement has not happened yet — so it
        is taken here, *after* this attempt's cleanup, which is exactly the order
        ``finish_cancelled`` insists on.
        """
        if self.cancelled and not self.controller.cancel_acknowledged:
            try:
                self.controller.checkpoint()
            except ConversionCancelled:
                pass
        cancelled = bool(self.controller.cancel_acknowledged)

        failures = FailureLog(snapshot_id=self.snapshot.snapshot_id,
                              records=tuple(self.failures))
        settled = RunResult.settle(self.snapshot, failures,
                                   completed_ids=tuple(self.completed),
                                   cancelled=cancelled)
        if cancelled:
            final = self.controller.finish_cancelled()
            self.publisher.cancelled(final)
        else:
            if settled.state is JobState.COMPLETED_WITH_FAILURES:
                final = self.controller.complete_with_failures()
            else:
                final = self.controller.succeed()
            self.publisher.completed(final)
        self.log_q.put((RESULT_MESSAGE, settled))
        self.log_q.put(("done", "Cancelled." if cancelled else (
            f"Conversion finished: {len(self.completed)} ok, "
            f"{len(self.failures)} failed.")))

    def settle_fatal(self, exc: BaseException) -> None:
        """The run itself broke. A job failure, and never retryable."""
        detail = f"{type(exc).__name__}: {exc}"
        message = "The conversion run could not be completed."
        fatal = FailureRecord(
            item_id=None, stage=STAGE_CONVERT, display_message=message,
            technical_detail=detail, retryable=False,
            snapshot_id=self.snapshot.snapshot_id)
        failures = FailureLog(snapshot_id=self.snapshot.snapshot_id,
                              records=tuple(self.failures) + (fatal,))
        settled = RunResult.settle(self.snapshot, failures,
                                   completed_ids=tuple(self.completed))
        self.publisher.failure(message, detail, stage=STAGE_CONVERT)
        final = self.controller.fail(message, detail)
        self.publisher.completed(final)
        self.log_q.put((RESULT_MESSAGE, settled))
        self.log_q.put(("done", message))


# --------------------------------------------------------------------------- #
# Conversion helpers — worker-thread only, and deliberately outside the panel
# --------------------------------------------------------------------------- #
#
# None of these takes the panel. They take the frozen parameters, the queue the
# pump drains and the cancel predicate, which is the whole of what a worker is
# allowed to hold. Each one calls an existing engine entry point, unchanged.
#
# **None of them checkpoints.** Pause is a boundary between source files; asking
# for one inside a chapter, a synthesis chunk, a network call or a PDF extraction
# would mean suspending an indivisible operation, which this design does not do.


def discard_partial(destination: Path, run_root) -> bool:
    """Remove one failed or cancelled occurrence's own leftover output.

    Deliberately narrow. It removes exactly the file at the destination the planner
    reserved for *this* occurrence, and only after proving that path lies inside the
    run directory — so a sibling's finished output is unreachable from here, and so
    is anything outside the run. Every occurrence has its own collision-safe
    destination, which is what makes "its own" a real distinction rather than a
    hopeful one.

    Returns whether anything was removed. A missing file is the normal case and is
    not an error; neither is a file the operating system will not let go of, because
    failing to tidy up must never turn one lost item into a lost run.
    """
    if run_root is None:
        return False
    target = Path(destination)
    try:
        output_paths.assert_contained(Path(run_root), target)
    except output_paths.OutputPathError:
        return False
    try:
        if target.is_file():
            target.unlink()
            return True
    except OSError:
        return False
    return False


def convert_with_edge_engine(item, params, log_q, cancel_check) -> None:
    """One directly added file through ``run_conversion_job``, unchanged.

    The engine names its own artifact — ``<stem> (<speaker>).mp3`` — and moves it
    into whatever directory it is handed. It is therefore handed a private staging
    directory, and the finished file is moved to the destination the shared planner
    reserved. That is what keeps two directly added files with the same stem from
    writing the same name: the one queue can now hold both, where the retired
    single-file mode could only ever hold one.

    ``progress_callback`` is deliberately not supplied. The run has one progress
    model now — the shared job status view, counting completed *source files* — and
    a second stream counting paragraphs into the same bar would contradict it. Which
    file is being converted is reported instead, as a current-item event.
    """
    from tts.epub2tts_edge import runner

    pause_kw = dict(params["pause_kw"])
    skip = {"trim_tts_padding", "trim_silence_db"}
    destination = item["destination"]
    with tempfile.TemporaryDirectory(prefix="tts_direct_") as stage:
        produced = runner.run_conversion_job(
            str(item["source"]),
            output_dir=stage,
            speaker=params["speaker"],
            audio_format="mp3",
            mp3_bitrate=params["bitrate"],
            cover=None,
            overwrite=params["overwrite"],
            trim_tts_padding=pause_kw.get("trim_tts_padding", True),
            trim_silence_db=pause_kw.get(
                "trim_silence_db", float(DEFAULT_TRIM_SILENCE_DB)),
            cancel_check=cancel_check,
            progress_callback=None,
            **{k: v for k, v in pause_kw.items() if k not in skip},
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(produced, str(destination))


def convert_with_kokoro(item, params, log_q, log, cancel_check) -> None:
    """One file through ``kokoro_file_to_mp3``, unchanged.

    A PDF is extracted to a temporary ``.txt`` first, exactly as before; a TXT is
    handed over as it stands. The import stays inside the function so loading the
    local model stack is still deferred to the first Kokoro conversion.
    """
    from tts.kokoro_synth import kokoro_file_to_mp3

    source = item["source"]
    destination = item["destination"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    # No fine-grained callback, for the same reason as the Edge path: one run has
    # one progress model, and it counts completed source files.
    progress = None

    def synthesize(text_path: str) -> None:
        kokoro_file_to_mp3(
            text_path,
            str(destination),
            voice_id=params["voice_id"],
            speed=params["kokoro_speed"],
            end_silence_ms=params["end_pause"],
            chunk_pause_ms=params["paragraph_pause"],
            log=log,
            cancel_check=cancel_check,
            progress_callback=progress,
            # The run's own "MP3 bitrate" choice. Until the Phase 12 audio audit
            # only the Edge direct path read it, so the local engines silently
            # produced whatever ffmpeg defaulted to.
            bitrate=params["bitrate"],
        )

    if source.suffix.lower() == ".txt":
        synthesize(str(source))
        return

    from tts.pdf_extractor import pdf_to_txt

    with tempfile.TemporaryDirectory(prefix=f"kk_{source.stem}_") as work:
        text_path = str(Path(work) / f"{source.stem}.txt")
        pdf_to_txt(str(source), text_path)
        synthesize(text_path)


def convert_with_chatterbox(item, params, log_q, log, cancel_check) -> None:
    """One file through ``chatterbox_file_to_mp3``, the engine's own entry point.

    Deliberately the same shape as :func:`convert_with_kokoro`, because the two are
    the same *kind* of thing: a local model that wants plain text and writes one
    MP3. A PDF therefore takes the **same** extractor the Kokoro path takes — there
    is one PDF-to-text seam in this tool and this adds no second one — and a TXT is
    handed over as it stands.

    The import stays inside the function so a machine without the local engine
    installed never loads the model stack to open this panel, and so nothing is
    imported at all unless a run actually selected this backend.

    ``progress_callback`` is deliberately not supplied, for exactly the reason the
    Kokoro path gives: the run has one progress model — the shared job status view,
    counting completed *source files* — and a second stream counting synthesis
    chunks into the same bar would contradict it. Cancellation does reach the
    engine, through the controller's own predicate, and is honoured between chunks.
    """
    from tts.chatterbox_synth import chatterbox_file_to_mp3

    source = item["source"]
    destination = item["destination"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    progress = None

    def synthesize(text_path: str) -> None:
        chatterbox_file_to_mp3(
            text_path,
            str(destination),
            voice_id=params["voice_id"],
            end_silence_ms=params["end_pause"],
            chunk_pause_ms=params["paragraph_pause"],
            log=log,
            cancel_check=cancel_check,
            progress_callback=progress,
            # The run's own "MP3 bitrate" choice. Until the Phase 12 audio audit
            # only the Edge direct path read it, so the local engines silently
            # produced whatever ffmpeg defaulted to.
            bitrate=params["bitrate"],
        )

    if source.suffix.lower() == ".txt":
        synthesize(str(source))
        return

    from tts.pdf_extractor import pdf_to_txt

    with tempfile.TemporaryDirectory(prefix=f"cb_{source.stem}_") as work:
        text_path = str(Path(work) / f"{source.stem}.txt")
        pdf_to_txt(str(source), text_path)
        synthesize(text_path)


class QueueWriter(io.TextIOBase):
    def __init__(self, q: queue.Queue) -> None:
        self._q = q

    def write(self, s: str) -> int:
        if s:
            self._q.put(("log", s))
        return len(s)

    def flush(self) -> None:
        pass


def build_ui(parent: tk.Misc) -> TtsPanel:
    """Build the TTS tool UI into ``parent`` and return the panel frame."""
    panel = TtsPanel(parent)
    panel.pack(fill=tk.BOTH, expand=True)
    return panel


def main() -> None:
    root = tk.Tk()
    root.title("TTS Audiobook — PDF / TXT → MP3")
    root.minsize(640, 680)
    panel = build_ui(root)

    def _close():
        panel.close()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", _close)
    root.mainloop()


if __name__ == "__main__":
    main()
