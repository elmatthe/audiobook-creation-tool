"""Reusable Tk adapters for the importing and job-control foundation.

v0.6.0 Drop 3 (Plan 3), Phase 8 — §6.15 of the active drop.

This module is the *only* place in Plan 3 that is allowed to know Tk exists, and it
is deliberately the thinnest layer in the drop. Every decision it renders was already
made somewhere else:

===========================  =========================================================
Question                     Who answers it
===========================  =========================================================
What is in the list?         :class:`~shared.importing.ImportedFileManager`
What may be added?           :func:`~shared.importing.scan_roots` / ``validate_direct_files``
When may a scan start?       :class:`~shared.import_coordination.ImportCoordinator`
What state is the job in?    :class:`~shared.job_control.JobController`, through its events
Which controls are locked?   :data:`~shared.job_control.LOCK_MATRIX` / ``is_locked``
Which buttons are offered?   :func:`~shared.job_control.is_available`
Which events count?          :class:`~shared.job_control.JobEventStream`
What does Summary say?       :func:`~shared.job_control.project_summary`
What does Details say?       :func:`~shared.job_control.detail_lines`
How much progress?           :class:`~shared.job_control.ProgressView`
How long is left?            :class:`~shared.job_control.EtaEstimator`
Where does a log line go?    :class:`~shared.job_control.LoggerBridge`
What does it look like?      :mod:`shared.ui_theme` — ``ACT.*`` on Windows, native on aqua
===========================  =========================================================

Nothing above is reimplemented here. There is no second manager, no second
coordinator, no second cancellation controller, no second event stream, no second
progress implementation, no second logger bridge, no second estimator, no output
planner and no job-state authority. If a question is not answered by one of the
services in that table, this module does not answer it either.

Composition, not inheritance
---------------------------
§6.15 asks for "composition and callback/protocol boundaries rather than a universal
base panel or inheritance hierarchy that later tools must fight". So every class here
*owns* a ``frame`` rather than *being* one, every decision a tool must make arrives as
a callback, and nothing is abstract. A future production panel builds what it wants
and hands these components a parent widget; it never inherits from one, and it is
never forced into a layout this module chose.

The main-thread rule, made testable
-----------------------------------
Widgets, Tk variables, dialogs, styles, ``ProgressIndicator`` and ``after`` scheduling
are touched on the thread that constructed the adapter, and on no other. That is not
left to convention: every method that could reach Tk begins with
:meth:`MainThreadGuard.require`, so a call from a worker raises :class:`MainThreadError`
*before* a widget is read or written, and a test can prove it by calling from a thread
and finding the widget unchanged. Workers communicate one way only — by putting
immutable values on a queue that the main thread drains.

One scheduled callback
----------------------
:class:`MainThreadPump` owns the single ``after`` chain. Import polling and job event
draining both ride on it, so "how often does this adapter wake up" has exactly one
answer and "is anything still scheduled after close" has exactly one place to look.
:class:`~shared.import_coordination.ImportPoller` is composed rather than replaced: it
is handed the pump's ``schedule``/``cancel`` seam, which is the same shape as
``root.after``/``root.after_cancel``, so its approved Phase 4 lifecycle keeps running
while the pump keeps the promise that at most one Tk callback is ever outstanding.

What this module still does not do
----------------------------------
It adopts nothing. No production panel imports it, the launcher gains no seventh tool,
no output is created, reserved, inspected or validated, no source file is touched, no
subprocess runs, no setting is written, and no real broad location is scanned. Plans
4–8 own adoption; Plan 9 owns the remaining visual and platform work.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from tkinter import ttk

from shared import ui_theme
from shared.import_coordination import (
    DEFAULT_POLL_INTERVAL_MS,
    ImportCoordinator,
    ImportOutcome,
    ImportPoller,
    OutcomeStatus,
    StartOutcome,
    TERMINAL_STATUSES,
)
from shared.importing import (
    IdFactory,
    ImportedFileManager,
    ImportOptions,
    ImportRoot,
    RootKind,
    ScanRequest,
    SupportedTypeCatalog,
)
from shared.job_control import (
    CALCULATING,
    ControlKind,
    DEFAULT_PUMP_LIMIT,
    EtaEstimator,
    JobAction,
    JobEvent,
    JobEventStream,
    JobState,
    LoggerBridge,
    ProgressMode,
    ProgressView,
    RunResult,
    SummaryView,
    detail_lines,
    is_available,
    is_locked,
    project_summary,
)

__all__ = [
    "JobUiError",
    "MainThreadError",
    "MainThreadGuard",
    "DEFAULT_PUMP_INTERVAL_MS",
    "style_name",
    "queue_pull",
    "MainThreadPump",
    "LockGroup",
    "ImportedFileList",
    "ImportOptionsBar",
    "ImportStatusBar",
    "ImportAdapter",
    "JobControlBar",
    "JobStatusView",
    "SummaryDetailsView",
    "JobAdapter",
    "ask_files",
    "ask_folder",
    "ask_confirm",
]

#: How often the single ``after`` chain wakes up. The same default the approved Phase 4
#: poller already uses, so composing the two changes nobody's cadence.
DEFAULT_PUMP_INTERVAL_MS = DEFAULT_POLL_INTERVAL_MS

#: How many follow-up outcomes one user action may resolve to before the adapter stops
#: chasing them. A confirmation resolves to a commit, and that is the end of it; the
#: bound exists so a future coordinator change can never turn this into a spin.
_MAX_OUTCOME_FOLLOW_UPS = 4

#: Distinguishes "the caller passed nothing" from "the caller passed ``None``", which
#: for ``home`` are genuinely different requests — the same sentinel the coordinator
#: uses, for the same reason.
_UNSET = object()


class JobUiError(RuntimeError):
    """Raised when an adapter is used in a way its contract forbids."""


class MainThreadError(JobUiError):
    """Raised when Tk would have been touched from somewhere other than its thread."""


# --------------------------------------------------------------------------- #
# Thread ownership
# --------------------------------------------------------------------------- #


class MainThreadGuard:
    """Remembers which thread owns Tk, and refuses every other one.

    Constructed by each adapter on the thread that built its widgets, which in a Tk
    application is the main thread. ``thread_id`` exists so a test can construct an
    adapter on one thread and still assert what a *different* identity would be told;
    production code never passes it.

    :meth:`require` raises rather than returning a flag on purpose. A guard that can
    be ignored is a comment, and the whole point of §5.1 is that the boundary holds
    even when somebody forgets it exists.
    """

    __slots__ = ("_thread_id",)

    def __init__(self, thread_id: int | None = None) -> None:
        self._thread_id = threading.get_ident() if thread_id is None else int(thread_id)

    @property
    def thread_id(self) -> int:
        return self._thread_id

    @property
    def is_current(self) -> bool:
        return threading.get_ident() == self._thread_id

    def require(self, action: str) -> None:
        if not self.is_current:
            raise MainThreadError(
                f"{action}() touches Tk and must run on the thread that owns it "
                f"(owner={self._thread_id}, caller={threading.get_ident()}); a worker "
                "puts immutable values on a queue and the main thread drains them")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"MainThreadGuard(thread_id={self._thread_id})"


# --------------------------------------------------------------------------- #
# Small widget helpers
# --------------------------------------------------------------------------- #


def _alive(widget: object) -> bool:
    """Whether *widget* still exists. A destroyed widget is an answer, not a crash."""
    if widget is None:
        return False
    exists = getattr(widget, "winfo_exists", None)
    if exists is None:
        return False
    try:
        return bool(exists())
    except tk.TclError:
        return False


def _configure(widget: object, **options: object) -> bool:
    """Configure *widget* if it is still there. Returns whether anything happened."""
    if not _alive(widget):
        return False
    try:
        widget.configure(**options)  # type: ignore[attr-defined]
    except tk.TclError:
        return False
    return True


def _enable(widget: object, enabled: bool) -> bool:
    return _configure(widget, state="normal" if enabled else "disabled")


def style_name(theme: Mapping[str, object] | None, key: str) -> str:
    """The registered ``ACT.*`` style for *key*, or ``""`` for the native branch.

    Only the Windows branch of :func:`shared.ui_theme.apply_theme` publishes a
    ``styles`` mapping. On macOS aqua and on the classic branch there is none, and an
    empty style name is exactly what ttk means by "draw this the way the platform
    draws it" — which is how the native Finder appearance is preserved without this
    module ever testing ``sys.platform`` for itself.
    """
    styles = (theme or {}).get("styles") or {}
    if not isinstance(styles, Mapping):
        return ""
    name = styles.get(key, "")
    return name if isinstance(name, str) else ""


def queue_pull(source: "queue.Queue | queue.SimpleQueue") -> Callable[[], object]:
    """Wrap a queue as the ``pull`` seam :meth:`JobEventStream.pump` expects.

    Returns the next item, or ``None`` when the queue is empty. Never blocks and never
    asks how many items are waiting — ``qsize`` is unreliable under concurrency and
    the whole draining contract is written to avoid needing it.
    """
    get_nowait = source.get_nowait

    def pull() -> object:
        try:
            return get_nowait()
        except queue.Empty:
            return None

    return pull


# --------------------------------------------------------------------------- #
# The one main-thread pump
# --------------------------------------------------------------------------- #


class _Handle:
    """A cancellable token for one scheduled callback. Deliberately opaque."""

    __slots__ = ("callback", "cancelled")

    def __init__(self, callback: Callable[[], object]) -> None:
        self.callback = callback
        self.cancelled = False

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"_Handle(cancelled={self.cancelled})"


class MainThreadPump:
    """The single ``after`` chain every adapter drains on.

    Two kinds of work ride it:

    * **drains** — registered once with :meth:`add_drain` and run on every tick, in
      registration order. The job adapter's queue drain is one of these.
    * **scheduled callbacks** — one-shot, registered through :meth:`schedule`, which
      has the exact shape of ``root.after``. :class:`ImportPoller` re-registers itself
      through this seam on every tick, so the approved Phase 4 lifecycle runs unchanged
      while still costing no second ``after`` handle.

    Guarantees, all of them checked by ``files/tests/test_job_ui.py``:

    * at most one Tk callback is outstanding at any moment;
    * insertion order is preserved and draining is deterministic;
    * an empty tick is legal and does nothing;
    * :meth:`stop` and :meth:`close` are idempotent, cancel the outstanding callback,
      and leave nothing scheduled;
    * a tick that arrives after :meth:`close` returns immediately;
    * a destroyed widget stops the chain instead of raising through it.
    """

    __slots__ = (
        "_widget", "_guard", "_interval_ms", "_drains", "_due", "_handle",
        "_running", "_closed", "_ticks",
    )

    def __init__(
        self,
        widget: object,
        *,
        interval_ms: int = DEFAULT_PUMP_INTERVAL_MS,
        thread_id: int | None = None,
    ) -> None:
        if not callable(getattr(widget, "after", None)):
            raise JobUiError("a pump needs a Tk widget or root with .after()")
        interval = int(interval_ms)
        if interval < 1:
            raise JobUiError(f"interval_ms must be at least 1, got {interval_ms!r}")
        self._widget = widget
        self._guard = MainThreadGuard(thread_id)
        self._interval_ms = interval
        self._drains: list[Callable[[], object]] = []
        self._due: list[_Handle] = []
        self._handle: object | None = None
        self._running = False
        self._closed = False
        self._ticks = 0

    # -- reading ----------------------------------------------------------- #

    @property
    def guard(self) -> MainThreadGuard:
        return self._guard

    @property
    def interval_ms(self) -> int:
        return self._interval_ms

    @property
    def running(self) -> bool:
        return self._running

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def pending(self) -> object | None:
        """The outstanding ``after`` id, or ``None``. There is never more than one."""
        return self._handle

    @property
    def scheduled_count(self) -> int:
        """How many one-shot callbacks are waiting for the next tick."""
        return sum(1 for handle in self._due if not handle.cancelled)

    @property
    def drain_count(self) -> int:
        return len(self._drains)

    @property
    def ticks(self) -> int:
        return self._ticks

    # -- registration ------------------------------------------------------ #

    def add_drain(self, drain: Callable[[], object]) -> None:
        """Run *drain* on every tick, after any earlier-registered drain."""
        self._guard.require("add_drain")
        if not callable(drain):
            raise JobUiError("a drain must be callable")
        if self._closed:
            return
        if drain not in self._drains:
            self._drains.append(drain)

    def remove_drain(self, drain: Callable[[], object]) -> None:
        self._guard.require("remove_drain")
        if drain in self._drains:
            self._drains.remove(drain)

    def schedule(self, delay_ms: int, callback: Callable[[], object]) -> object:
        """The ``root.after`` seam. Runs *callback* on the next tick of this chain.

        The pump's own cadence is the delay: a caller asking for "about 120 ms" is
        answered by the chain that already wakes up on that interval, which is what
        keeps the single-outstanding-callback promise true. The returned handle is
        accepted by :meth:`cancel`.
        """
        self._guard.require("schedule")
        if not callable(callback):
            raise JobUiError("a scheduled callback must be callable")
        handle = _Handle(callback)
        if self._closed:
            handle.cancelled = True
            return handle
        self._due.append(handle)
        if self._running:
            self._reschedule()
        return handle

    def cancel(self, handle: object) -> None:
        """The ``root.after_cancel`` seam. Idempotent, and safe for a stale handle."""
        if isinstance(handle, _Handle):
            handle.cancelled = True

    # -- running ----------------------------------------------------------- #

    def start(self) -> bool:
        """Begin ticking. ``False`` when already running or already closed."""
        self._guard.require("start")
        if self._closed or self._running:
            return False
        self._running = True
        self._reschedule()
        return True

    def tick(self) -> int:
        """Run every drain, then every one-shot callback. Returns how many ran.

        Exposed publicly because a deterministic test needs to advance the adapter
        without a real event loop, and because a manual harness occasionally wants to
        flush before it asks a question.
        """
        self._guard.require("tick")
        if self._closed:
            return 0
        self._ticks += 1
        ran = 0
        for drain in tuple(self._drains):
            if self._closed:
                break
            drain()
            ran += 1
        due, self._due = self._due, []
        for handle in due:
            if self._closed:
                break
            if handle.cancelled:
                continue
            handle.callback()
            ran += 1
        if self._running and not self._closed:
            self._reschedule()
        return ran

    def stop(self) -> None:
        """Stop ticking and cancel the outstanding callback. Idempotent."""
        self._guard.require("stop")
        self._running = False
        self._cancel_pending()

    def close(self) -> None:
        """Stop, forget every drain and callback, and refuse all further work.

        Idempotent. Afterwards :attr:`pending` is ``None``, no drain remains
        registered, and a late Tk callback that was already in flight returns without
        touching anything.
        """
        self._guard.require("close")
        if self._closed:
            return
        self._running = False
        self._cancel_pending()
        self._closed = True
        self._drains.clear()
        for handle in self._due:
            handle.cancelled = True
        self._due.clear()

    # -- internals --------------------------------------------------------- #

    def _reschedule(self) -> None:
        if self._handle is not None or self._closed or not self._running:
            return
        if not _alive(self._widget):
            self._running = False
            return
        try:
            self._handle = self._widget.after(  # type: ignore[attr-defined]
                self._interval_ms, self._on_after)
        except tk.TclError:
            # The root went away between the liveness check and the call. Stopping is
            # the honest response; resurrecting the chain is not.
            self._running = False
            self._handle = None

    def _on_after(self) -> None:
        self._handle = None
        if self._closed or not self._running:
            return
        self.tick()

    def _cancel_pending(self) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        cancel = getattr(self._widget, "after_cancel", None)
        if cancel is None or not _alive(self._widget):
            return
        try:
            cancel(handle)
        except tk.TclError:
            pass

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"MainThreadPump(running={self._running}, closed={self._closed}, "
                f"pending={self._handle is not None}, drains={len(self._drains)})")


# --------------------------------------------------------------------------- #
# Input and processing-option locking
# --------------------------------------------------------------------------- #


class LockGroup:
    """Applies the approved UI-neutral lock contract to real widgets.

    A caller registers widgets under a :class:`~shared.job_control.ControlKind` and
    calls :meth:`apply` with the job's state. Which kinds lock in which states is not
    decided here — :data:`~shared.job_control.LOCK_MATRIX` decided it in Phase 6, and
    this only turns the answer into ``state="disabled"``.

    A registered target may be a widget, or any object exposing ``set_locked(bool)``
    (which is how the composite components below register as a single unit).
    """

    __slots__ = ("_guard", "_targets", "_closed", "_last")

    def __init__(self, *, thread_id: int | None = None) -> None:
        self._guard = MainThreadGuard(thread_id)
        self._targets: dict[ControlKind, list[object]] = {}
        self._closed = False
        self._last: Mapping[ControlKind, bool] = {}

    @property
    def last_applied(self) -> Mapping[ControlKind, bool]:
        return dict(self._last)

    @property
    def closed(self) -> bool:
        return self._closed

    def register(self, kind: ControlKind, *targets: object) -> None:
        self._guard.require("register")
        if not isinstance(kind, ControlKind):
            raise JobUiError(f"kind must be a ControlKind, got {type(kind).__name__}")
        if self._closed:
            return
        bucket = self._targets.setdefault(kind, [])
        for target in targets:
            if target is not None and target not in bucket:
                bucket.append(target)

    def registered(self, kind: ControlKind) -> tuple[object, ...]:
        return tuple(self._targets.get(kind, ()))

    def apply(self, state: JobState) -> Mapping[ControlKind, bool]:
        """Lock or unlock every registered target. Returns kind -> locked."""
        self._guard.require("apply")
        if not isinstance(state, JobState):
            raise JobUiError(f"state must be a JobState, got {type(state).__name__}")
        applied: dict[ControlKind, bool] = {}
        for kind in ControlKind:
            locked = is_locked(kind, state)
            applied[kind] = locked
            if self._closed:
                continue
            for target in self._targets.get(kind, ()):
                setter = getattr(target, "set_locked", None)
                if callable(setter):
                    setter(locked)
                else:
                    _enable(target, not locked)
        self._last = applied
        return applied

    def close(self) -> None:
        self._guard.require("close")
        self._closed = True
        self._targets.clear()


# --------------------------------------------------------------------------- #
# The imported-file list
# --------------------------------------------------------------------------- #


class ImportedFileList:
    """An extended-selection list over an :class:`ImportedFileManager`.

    The manager owns the order, the occurrences and the selection; this owns pixels.
    Every action delegates — :meth:`move_up` is ``manager.move_selected_up()`` and
    nothing else — and every rebuild restores the selection **by occurrence ID**, so a
    row that moved is still the row that is selected and two deliberate duplicates of
    the same path stay two independently selectable rows.
    """

    __slots__ = (
        "_guard", "_manager", "_theme", "_closed", "_locked", "_order",
        "_on_add_files", "_on_add_folder", "_on_selection_change",
        "frame", "listbox", "scrollbar", "count_label", "buttons",
    )

    #: Action key -> button text, in the order §6.15 lists them.
    ACTIONS = (
        ("add_files", "Add Files…"),
        ("add_folder", "Add Folder…"),
        ("move_up", "Move Up"),
        ("move_down", "Move Down"),
        ("remove", "Remove"),
        ("clear", "Clear"),
    )

    def __init__(
        self,
        parent: object,
        manager: ImportedFileManager,
        *,
        theme: Mapping[str, object] | None = None,
        thread_id: int | None = None,
        height: int = 10,
        on_add_files: Callable[[], object] | None = None,
        on_add_folder: Callable[[], object] | None = None,
        on_selection_change: Callable[[tuple[str, ...]], object] | None = None,
    ) -> None:
        if not isinstance(manager, ImportedFileManager):
            raise JobUiError(
                f"manager must be an ImportedFileManager, got {type(manager).__name__}")
        self._guard = MainThreadGuard(thread_id)
        self._manager = manager
        self._theme = theme
        self._closed = False
        self._locked = False
        self._order: tuple[str, ...] = ()
        self._on_add_files = on_add_files
        self._on_add_folder = on_add_folder
        self._on_selection_change = on_selection_change

        self.frame = ttk.Frame(parent, style=style_name(theme, "card"))
        self.count_label = ttk.Label(
            self.frame, text=_count_text(0, 0), style=style_name(theme, "secondary_label"))
        self.count_label.grid(row=0, column=0, columnspan=2, sticky="w")

        self.listbox = tk.Listbox(
            self.frame, selectmode="extended", exportselection=False,
            height=max(1, int(height)), activestyle="none")
        ui_theme.style_tk_widget(self.listbox, theme or {}, "list")
        self.listbox.grid(row=1, column=0, sticky="nsew")

        self.scrollbar = ttk.Scrollbar(
            self.frame, orient="vertical", command=self.listbox.yview,
            style=style_name(theme, "vscrollbar"))
        self.scrollbar.grid(row=1, column=1, sticky="ns")
        self.listbox.configure(yscrollcommand=self.scrollbar.set)

        actions = ttk.Frame(self.frame, style=style_name(theme, "card"))
        actions.grid(row=2, column=0, columnspan=2, sticky="w")
        handlers = {
            "add_files": self.add_files,
            "add_folder": self.add_folder,
            "move_up": self.move_up,
            "move_down": self.move_down,
            "remove": self.remove_selected,
            "clear": self.clear,
        }
        self.buttons: dict[str, ttk.Button] = {}
        for column, (key, label) in enumerate(self.ACTIONS):
            button = ttk.Button(
                actions, text=label, command=handlers[key],
                style=style_name(theme, "button"))
            button.grid(row=0, column=column, padx=(0 if column == 0 else 6, 0))
            self.buttons[key] = button

        self.frame.rowconfigure(1, weight=1)
        self.frame.columnconfigure(0, weight=1)
        self.listbox.bind(
            "<<ListboxSelect>>", lambda _event: self.sync_selection(), add="+")
        self.refresh()

    # -- reading ----------------------------------------------------------- #

    @property
    def guard(self) -> MainThreadGuard:
        return self._guard

    @property
    def manager(self) -> ImportedFileManager:
        return self._manager

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def locked(self) -> bool:
        return self._locked

    @property
    def order(self) -> tuple[str, ...]:
        """The occurrence IDs currently on screen, top to bottom."""
        return self._order

    @property
    def count(self) -> int:
        return self._manager.count

    @property
    def selected_count(self) -> int:
        return len(self.selection)

    @property
    def selection(self) -> tuple[str, ...]:
        """The selected occurrence IDs, in list order — never indices, never paths."""
        if self._closed or not _alive(self.listbox):
            return ()
        try:
            indices = self.listbox.curselection()
        except tk.TclError:
            return ()
        return tuple(
            self._order[index] for index in indices if 0 <= index < len(self._order))

    def rows(self) -> tuple[str, ...]:
        """The row text currently on screen. Reads the widget, so: main thread."""
        self._guard.require("rows")
        if self._closed or not _alive(self.listbox):
            return ()
        try:
            return tuple(self.listbox.get(0, "end"))
        except tk.TclError:
            return ()

    def button_states(self) -> Mapping[str, bool]:
        """Action key -> enabled. Derived, so the buttons cannot drift from the list."""
        self._guard.require("button_states")
        count = self._manager.count
        selected = self.selection
        indices = tuple(
            index for index, occurrence in enumerate(self._order)
            if occurrence in set(selected))
        usable = not self._locked and not self._closed
        return {
            "add_files": usable and self._on_add_files is not None,
            "add_folder": usable and self._on_add_folder is not None,
            "move_up": usable and bool(indices) and min(indices) > 0,
            "move_down": usable and bool(indices) and max(indices) < count - 1,
            "remove": usable and bool(indices),
            "clear": usable and count > 0,
        }

    # -- rendering --------------------------------------------------------- #

    def refresh(self, selection: Iterable[str] | None = None) -> tuple[str, ...]:
        """Rebuild every row from the manager and restore the selection by ID."""
        self._guard.require("refresh")
        if self._closed or not _alive(self.listbox):
            return ()
        snapshot = self._manager.snapshot()
        wanted = tuple(self._manager.selection if selection is None else selection)
        self._order = snapshot.occurrence_ids
        try:
            self.listbox.delete(0, "end")
            for position, imported in enumerate(snapshot.files, start=1):
                self.listbox.insert("end", _row_text(position, imported))
        except tk.TclError:
            return ()
        restored = self._apply_selection(wanted)
        self._render_count()
        self.apply_button_states()
        return restored

    def select(self, occurrence_ids: Iterable[str]) -> tuple[str, ...]:
        """Select exactly these occurrences, in both the manager and the widget."""
        self._guard.require("select")
        if self._closed:
            return ()
        restored = self._apply_selection(tuple(occurrence_ids))
        self._render_count()
        self.apply_button_states()
        return restored

    def clear_selection(self) -> None:
        self._guard.require("clear_selection")
        self.select(())

    def sync_selection(self) -> tuple[str, ...]:
        """Adopt whatever the widget is showing as selected.

        This is what the ``<<ListboxSelect>>`` binding calls, and it is public because
        that is the one path a click or an arrow key travels: Tk changes the widget,
        and the manager has to follow. Keeping it named means the behaviour can be
        driven in a test without simulating a mouse.
        """
        self._guard.require("sync_selection")
        if self._closed:
            return ()
        selected = self.selection
        self._manager.select(selected)
        self._render_count()
        self.apply_button_states()
        self._notify(selected)
        return selected

    def apply_button_states(self) -> Mapping[str, bool]:
        self._guard.require("apply_button_states")
        states = self.button_states()
        for key, enabled in states.items():
            _enable(self.buttons.get(key), enabled)
        return states

    def set_locked(self, locked: bool) -> None:
        """Lock the whole component as one unit, the way §6.11 locks inputs."""
        self._guard.require("set_locked")
        self._locked = bool(locked)
        if self._closed:
            return
        _configure(self.listbox, state="disabled" if self._locked else "normal")
        self.apply_button_states()

    def focus(self) -> None:
        self._guard.require("focus")
        if self._closed or not _alive(self.listbox):
            return
        try:
            self.listbox.focus_set()
        except tk.TclError:
            pass

    # -- actions ----------------------------------------------------------- #

    def add_files(self) -> None:
        self._guard.require("add_files")
        if self._closed or self._locked or self._on_add_files is None:
            return
        self._on_add_files()

    def add_folder(self) -> None:
        self._guard.require("add_folder")
        if self._closed or self._locked or self._on_add_folder is None:
            return
        self._on_add_folder()

    def move_up(self) -> tuple[str, ...]:
        return self._mutate("move_up", self._manager.move_selected_up)

    def move_down(self) -> tuple[str, ...]:
        return self._mutate("move_down", self._manager.move_selected_down)

    def remove_selected(self) -> tuple[str, ...]:
        return self._mutate("remove_selected", self._manager.remove_selected)

    def clear(self) -> tuple[str, ...]:
        return self._mutate("clear", self._manager.clear)

    def close(self) -> None:
        """Stop responding. Idempotent, and safe after the widgets are destroyed."""
        self._guard.require("close")
        if self._closed:
            return
        self._closed = True
        if _alive(self.listbox):
            try:
                self.listbox.unbind("<<ListboxSelect>>")
            except tk.TclError:
                pass
        self._on_add_files = None
        self._on_add_folder = None
        self._on_selection_change = None

    # -- internals --------------------------------------------------------- #

    def _mutate(self, action: str, operation: Callable[[], object]) -> tuple[str, ...]:
        self._guard.require(action)
        if self._closed or self._locked:
            return self.selection
        result = operation()
        restored = self.refresh(getattr(result, "selection", None))
        self._notify(restored)
        return restored

    def _apply_selection(self, wanted: Sequence[str]) -> tuple[str, ...]:
        present = set(self._order)
        keep = tuple(occurrence for occurrence in wanted if occurrence in present)
        self._manager.select(keep)
        if not _alive(self.listbox):
            return keep
        try:
            self.listbox.selection_clear(0, "end")
            for index, occurrence in enumerate(self._order):
                if occurrence in set(keep):
                    self.listbox.selection_set(index)
        except tk.TclError:
            return keep
        return keep

    def _notify(self, selected: tuple[str, ...]) -> None:
        if self._on_selection_change is not None:
            self._on_selection_change(selected)

    def _render_count(self) -> None:
        _configure(self.count_label,
                   text=_count_text(self._manager.count, len(self.selection)))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"ImportedFileList(count={self._manager.count}, "
                f"selected={self.selected_count}, locked={self._locked})")


def _row_text(position: int, imported: object) -> str:
    """One row. The relative path when there is one, so mirrored roots read clearly."""
    relative = getattr(imported, "relative_path", None)
    label = str(relative) if relative is not None else getattr(imported, "path").name
    return f"{position}. {label}"


def _count_text(count: int, selected: int) -> str:
    noun = "file" if count == 1 else "files"
    if selected:
        return f"{count:,} {noun} imported — {selected:,} selected"
    return f"{count:,} {noun} imported"


# --------------------------------------------------------------------------- #
# Import options
# --------------------------------------------------------------------------- #


class ImportOptionsBar:
    """Supported-type checkboxes plus the two frozen per-import options.

    The catalog is supplied by the adopting tool, never invented here: §6.2 is explicit
    that the shared layer contains no universal media list. Every supplied type starts
    selected, any combination is representable including none, and
    :meth:`options` captures the Tk variables into a frozen
    :class:`~shared.importing.ImportOptions` **on the main thread** so a worker only
    ever sees immutable values.
    """

    __slots__ = (
        "_guard", "_catalog", "_theme", "_closed", "_locked", "_on_change",
        "frame", "type_vars", "type_buttons", "var_hidden", "var_duplicates",
        "check_hidden", "check_duplicates",
    )

    def __init__(
        self,
        parent: object,
        catalog: SupportedTypeCatalog,
        *,
        theme: Mapping[str, object] | None = None,
        thread_id: int | None = None,
        include_hidden_folders: bool = False,
        allow_duplicate_files: bool = False,
        on_change: Callable[[ImportOptions], object] | None = None,
    ) -> None:
        if not isinstance(catalog, SupportedTypeCatalog):
            raise JobUiError(
                f"catalog must be a SupportedTypeCatalog, got {type(catalog).__name__}")
        self._guard = MainThreadGuard(thread_id)
        self._catalog = catalog
        self._theme = theme
        self._closed = False
        self._locked = False
        self._on_change = on_change

        self.frame = ttk.Frame(parent, style=style_name(theme, "card"))
        selected = set(catalog.default_selection())
        self.type_vars: dict[str, tk.BooleanVar] = {}
        self.type_buttons: dict[str, ttk.Checkbutton] = {}
        for column, supported in enumerate(catalog.types):
            variable = tk.BooleanVar(master=self.frame,
                                     value=supported.type_id in selected)
            button = ttk.Checkbutton(
                self.frame, text=supported.label, variable=variable,
                command=self._changed, style=style_name(theme, "checkbutton"))
            button.grid(row=0, column=column, sticky="w", padx=(0 if column == 0 else 10, 0))
            self.type_vars[supported.type_id] = variable
            self.type_buttons[supported.type_id] = button

        self.var_hidden = tk.BooleanVar(master=self.frame, value=bool(include_hidden_folders))
        self.check_hidden = ttk.Checkbutton(
            self.frame, text="Include hidden folders", variable=self.var_hidden,
            command=self._changed, style=style_name(theme, "checkbutton"))
        self.check_hidden.grid(row=1, column=0, columnspan=max(1, len(catalog.types)),
                               sticky="w", pady=(6, 0))

        self.var_duplicates = tk.BooleanVar(master=self.frame,
                                            value=bool(allow_duplicate_files))
        self.check_duplicates = ttk.Checkbutton(
            self.frame, text="Allow duplicate files", variable=self.var_duplicates,
            command=self._changed, style=style_name(theme, "checkbutton"))
        self.check_duplicates.grid(row=2, column=0, columnspan=max(1, len(catalog.types)),
                                   sticky="w")

    # -- reading ----------------------------------------------------------- #

    @property
    def guard(self) -> MainThreadGuard:
        return self._guard

    @property
    def catalog(self) -> SupportedTypeCatalog:
        return self._catalog

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def locked(self) -> bool:
        return self._locked

    def selected_type_ids(self) -> frozenset[str]:
        self._guard.require("selected_type_ids")
        return frozenset(
            type_id for type_id, variable in self.type_vars.items()
            if _read_bool(variable))

    def options(self) -> ImportOptions:
        """Freeze the current widget values. Main thread only, by construction."""
        self._guard.require("options")
        return ImportOptions(
            selected_type_ids=self.selected_type_ids(),
            include_hidden_folders=_read_bool(self.var_hidden),
            allow_duplicate_files=_read_bool(self.var_duplicates),
        )

    # -- writing ----------------------------------------------------------- #

    def set_types(self, type_ids: Iterable[str]) -> frozenset[str]:
        self._guard.require("set_types")
        wanted = set(type_ids)
        for type_id, variable in self.type_vars.items():
            _write_bool(variable, type_id in wanted)
        return self.selected_type_ids()

    def set_include_hidden(self, value: bool) -> None:
        self._guard.require("set_include_hidden")
        _write_bool(self.var_hidden, bool(value))

    def set_allow_duplicates(self, value: bool) -> None:
        self._guard.require("set_allow_duplicates")
        _write_bool(self.var_duplicates, bool(value))

    def set_locked(self, locked: bool) -> None:
        self._guard.require("set_locked")
        self._locked = bool(locked)
        if self._closed:
            return
        for button in (*self.type_buttons.values(), self.check_hidden,
                       self.check_duplicates):
            _enable(button, not self._locked)

    def close(self) -> None:
        self._guard.require("close")
        self._closed = True
        self._on_change = None

    # -- internals --------------------------------------------------------- #

    def _changed(self) -> None:
        if self._closed or self._on_change is None:
            return
        self._on_change(self.options())

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ImportOptionsBar(types={len(self.type_vars)}, locked={self._locked})"


def _read_bool(variable: tk.BooleanVar) -> bool:
    try:
        return bool(variable.get())
    except tk.TclError:
        return False


def _write_bool(variable: tk.BooleanVar, value: bool) -> None:
    try:
        variable.set(bool(value))
    except tk.TclError:
        pass


# --------------------------------------------------------------------------- #
# Import status and Cancel Import
# --------------------------------------------------------------------------- #


class ImportStatusBar:
    """Live import status, the discovered count, and a *separate* Cancel Import.

    §6.7 is emphatic that this button controls the scan and only the scan. There is
    nothing here that could reach a processing job: the callback is supplied by the
    import adapter, which wires it to
    :meth:`~shared.import_coordination.ImportCoordinator.request_cancel` and to
    nothing else.
    """

    __slots__ = ("_guard", "_theme", "_closed", "_on_cancel", "_count",
                 "frame", "var_status", "label", "button_cancel")

    IDLE_TEXT = "No import running."
    CANCELLING_TEXT = "Cancelling the import…"

    def __init__(
        self,
        parent: object,
        *,
        theme: Mapping[str, object] | None = None,
        thread_id: int | None = None,
        on_cancel: Callable[[], object] | None = None,
    ) -> None:
        self._guard = MainThreadGuard(thread_id)
        self._theme = theme
        self._closed = False
        self._on_cancel = on_cancel
        self._count = 0

        self.frame = ttk.Frame(parent, style=style_name(theme, "card"))
        self.var_status = tk.StringVar(master=self.frame, value=self.IDLE_TEXT)
        self.label = ttk.Label(self.frame, textvariable=self.var_status,
                               style=style_name(theme, "secondary_label"))
        self.label.grid(row=0, column=0, sticky="w")
        self.button_cancel = ttk.Button(
            self.frame, text="Cancel Import", command=self.cancel,
            style=style_name(theme, "button"))
        self.button_cancel.grid(row=0, column=1, padx=(10, 0))
        self.frame.columnconfigure(0, weight=1)
        _enable(self.button_cancel, False)

    @property
    def guard(self) -> MainThreadGuard:
        return self._guard

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def discovered_count(self) -> int:
        return self._count

    @property
    def text(self) -> str:
        try:
            return str(self.var_status.get())
        except tk.TclError:
            return ""

    @property
    def cancel_enabled(self) -> bool:
        if not _alive(self.button_cancel):
            return False
        try:
            return "disabled" not in self.button_cancel.state()
        except tk.TclError:
            return False

    def set_message(self, message: str) -> None:
        self._guard.require("set_message")
        if self._closed:
            return
        try:
            self.var_status.set(str(message))
        except tk.TclError:
            pass

    def set_idle(self, message: str = "") -> None:
        self._guard.require("set_idle")
        self._count = 0
        self.set_message(message or self.IDLE_TEXT)
        self.set_cancel_enabled(False)

    def set_scanning(self, discovered: int) -> None:
        """The live count: compatible candidates found so far, never an estimate."""
        self._guard.require("set_scanning")
        self._count = max(0, int(discovered))
        noun = "file" if self._count == 1 else "files"
        self.set_message(f"Scanning… {self._count:,} {noun} found")
        self.set_cancel_enabled(True)

    def set_cancelling(self) -> None:
        self._guard.require("set_cancelling")
        self.set_message(self.CANCELLING_TEXT)
        self.set_cancel_enabled(False)

    def set_cancel_enabled(self, enabled: bool) -> None:
        self._guard.require("set_cancel_enabled")
        _enable(self.button_cancel, bool(enabled) and not self._closed)

    def set_locked(self, locked: bool) -> None:
        # The import status is a report, not an input: a running *job* does not disable
        # it, and Cancel Import stays governed by whether an import is actually running.
        self._guard.require("set_locked")

    def cancel(self) -> None:
        self._guard.require("cancel")
        if self._closed or self._on_cancel is None:
            return
        self._on_cancel()

    def close(self) -> None:
        self._guard.require("close")
        self._closed = True
        self._on_cancel = None
        _enable(self.button_cancel, False)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ImportStatusBar(count={self._count}, closed={self._closed})"


# --------------------------------------------------------------------------- #
# The imported-file adapter
# --------------------------------------------------------------------------- #


class ImportAdapter:
    """One compositional adapter for the whole imported-file side of §6.15.

    It owns three components (list, options, status), composes one
    :class:`~shared.import_coordination.ImportCoordinator` and one
    :class:`~shared.import_coordination.ImportPoller`, and rides the caller's
    :class:`MainThreadPump`. Everything the user can decide arrives as a main-thread
    callback:

    * ``choose_files`` / ``choose_folder`` open the dialogs, and are called on the main
      thread before any worker exists;
    * ``confirm_broad_root`` is handed straight to the coordinator, which calls it
      *before* creating a thread and refuses the scan if it says no;
    * ``confirm_large_result`` answers Plan 2's captured threshold after the scan has
      completed and before anything is committed.

    A missing confirmer fails closed. An import that would need a decision nobody wired
    up is declined and says so, rather than being taken silently.
    """

    __slots__ = (
        "_guard", "_pump", "_catalog", "_effective_config", "_clock", "_ids",
        "_manager", "_coordinator", "_poller", "_choose_files", "_choose_folder",
        "_confirm_large", "_on_outcome", "_closed", "_reason",
        "frame", "list", "options", "status",
    )

    def __init__(
        self,
        parent: object,
        *,
        catalog: SupportedTypeCatalog,
        effective_config: object,
        pump: MainThreadPump,
        manager: ImportedFileManager | None = None,
        coordinator: ImportCoordinator | None = None,
        theme: Mapping[str, object] | None = None,
        thread_id: int | None = None,
        clock: Callable[[], float] | None = None,
        id_factory: IdFactory | None = None,
        choose_files: Callable[[], Iterable[object]] | None = None,
        choose_folder: Callable[[], Iterable[object]] | None = None,
        confirm_broad_root: Callable[[tuple[Path, ...]], bool] | None = None,
        confirm_large_result: Callable[[ImportOutcome], bool] | None = None,
        on_outcome: Callable[[ImportOutcome], object] | None = None,
        home: object = _UNSET,
        list_height: int = 10,
    ) -> None:
        if not isinstance(pump, MainThreadPump):
            raise JobUiError(f"pump must be a MainThreadPump, got {type(pump).__name__}")
        self._guard = MainThreadGuard(thread_id)
        self._pump = pump
        self._catalog = catalog
        self._effective_config = effective_config
        self._clock = (lambda: 0.0) if clock is None else clock
        self._ids = IdFactory() if id_factory is None else id_factory
        self._choose_files = choose_files
        self._choose_folder = choose_folder
        self._confirm_large = confirm_large_result
        self._on_outcome = on_outcome
        self._closed = False
        # Why the *adapter* refused, when that is more informative than the coordinator's
        # own "nothing was added" — a decline nobody chose should say so.
        self._reason = ""

        if coordinator is None:
            self._manager = ImportedFileManager() if manager is None else manager
            extra = {} if home is _UNSET else {"home": home}
            self._coordinator = ImportCoordinator(
                self._manager,
                clock=self._clock,
                confirm_broad_root=confirm_broad_root,
                **extra,
            )
        else:
            if manager is None:
                raise JobUiError(
                    "a supplied coordinator must arrive with the manager it commits to; "
                    "the adapter renders that list and never reaches inside for it")
            self._manager = manager
            self._coordinator = coordinator

        self.frame = ttk.Frame(parent, style=style_name(theme, "surface"))
        self.list = ImportedFileList(
            self.frame, self._manager, theme=theme, thread_id=thread_id,
            height=list_height, on_add_files=self.add_files,
            on_add_folder=self.add_folder)
        self.options = ImportOptionsBar(
            self.frame, catalog, theme=theme, thread_id=thread_id)
        self.status = ImportStatusBar(
            self.frame, theme=theme, thread_id=thread_id, on_cancel=self.cancel_import)

        self.list.frame.grid(row=0, column=0, sticky="nsew")
        self.options.frame.grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.status.frame.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.frame.rowconfigure(0, weight=1)
        self.frame.columnconfigure(0, weight=1)

        self._poller = ImportPoller(
            self._coordinator, pump.schedule, cancel=pump.cancel,
            interval_ms=pump.interval_ms, on_outcome=self._handle_outcome)

    # -- reading ----------------------------------------------------------- #

    @property
    def guard(self) -> MainThreadGuard:
        return self._guard

    @property
    def coordinator(self) -> ImportCoordinator:
        return self._coordinator

    @property
    def poller(self) -> ImportPoller:
        return self._poller

    @property
    def manager(self) -> ImportedFileManager:
        return self._manager

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def count(self) -> int:
        return self.manager.count

    @property
    def selected_count(self) -> int:
        return self.list.selected_count

    @property
    def is_importing(self) -> bool:
        return self._coordinator.is_active

    # -- actions ----------------------------------------------------------- #

    def add_files(self) -> ImportOutcome | None:
        """Add individually chosen files, in the order the dialog returned them."""
        self._guard.require("add_files")
        if self._closed or self._choose_files is None:
            return None
        paths = tuple(self._choose_files() or ())
        if not paths:
            return None
        root = ImportRoot(root_id=self._ids.next_id("root"), path=None, order=0,
                          kind=RootKind.DIRECT_FILES)
        outcome = self._coordinator.import_files(self._request((root,)), paths)
        return self._handle_outcome(outcome)

    def add_folder(self) -> ImportOutcome | None:
        """Start a background scan of one or more chosen roots, in chosen order."""
        self._guard.require("add_folder")
        if self._closed or self._choose_folder is None:
            return None
        chosen = tuple(self._choose_folder() or ())
        if not chosen:
            return None
        roots = tuple(
            ImportRoot(root_id=self._ids.next_id("root"), path=Path(entry),
                       order=order, kind=RootKind.FOLDER)
            for order, entry in enumerate(chosen))
        report = self._coordinator.start(self._request(roots))
        if report.outcome is StartOutcome.STARTED:
            self.status.set_scanning(0)
            self._poller.start()
            return None
        self.status.set_idle(report.display_message)
        return None

    def cancel_import(self) -> bool:
        """`Cancel Import`. Touches this scan and nothing else, ever."""
        self._guard.require("cancel_import")
        if self._closed:
            return False
        cancelled = self._coordinator.request_cancel()
        if cancelled:
            self.status.set_cancelling()
        return cancelled

    def refresh(self) -> tuple[str, ...]:
        self._guard.require("refresh")
        return self.list.refresh()

    def set_locked(self, locked: bool) -> None:
        """Lock the imported inputs and the import options as one unit."""
        self._guard.require("set_locked")
        self.list.set_locked(locked)
        self.options.set_locked(locked)

    def close(self) -> None:
        """Cancel any scan, stop polling, and make every later event inert.

        Idempotent. The coordinator's own close cancels the worker, joins it within its
        bounded timeout and empties its queue, so nothing published during teardown can
        be mistaken for live work — and nothing here claims an indivisible ``scandir``
        was interrupted, because it was not.
        """
        self._guard.require("close")
        if self._closed:
            return
        self._closed = True
        self._poller.close()
        self.list.close()
        self.options.close()
        self.status.close()
        self._choose_files = None
        self._choose_folder = None
        self._confirm_large = None
        self._on_outcome = None

    # -- internals --------------------------------------------------------- #

    def _request(self, roots: tuple[ImportRoot, ...]) -> ScanRequest:
        """Freeze the widgets into an immutable request, on this thread."""
        return ScanRequest(
            request_id=self._ids.next_id("req"),
            roots=roots,
            catalog=self._catalog,
            options=self.options.options(),
            effective_config=self._effective_config,
            created_at=self._clock(),
        )

    def _handle_outcome(self, outcome: ImportOutcome) -> ImportOutcome:
        """Render one coordinator outcome, and resolve any decision it asked for."""
        if self._closed:
            return outcome
        for _ in range(_MAX_OUTCOME_FOLLOW_UPS):
            status = outcome.status
            if status is OutcomeStatus.RUNNING:
                self.status.set_scanning(outcome.discovered_count)
                break
            if status is OutcomeStatus.AWAITING_CONFIRMATION:
                follow_up = self._resolve_confirmation(outcome)
                if follow_up is None:
                    break
                outcome = follow_up
                continue
            if status in TERMINAL_STATUSES or status is OutcomeStatus.CLOSED:
                self._poller.stop()
                self.list.refresh()
                reason, self._reason = self._reason, ""
                self.status.set_idle(reason or outcome.display_message)
                break
            if status in (OutcomeStatus.BUSY, OutcomeStatus.NO_TYPES_SELECTED):
                self.status.set_message(outcome.display_message)
                break
            # ``IDLE`` — nothing was drained and nothing is waiting. Say nothing.
            break
        if self._on_outcome is not None:
            self._on_outcome(outcome)
        return outcome

    def _resolve_confirmation(self, outcome: ImportOutcome) -> ImportOutcome | None:
        proposed = outcome.proposed_count
        if self._confirm_large is None:
            # Fail closed, exactly as the coordinator does for an unwired broad-root
            # warning: a threshold nobody can answer must not be answered by silence.
            self._reason = (
                f"{proposed:,} files need confirmation, which is not available here. "
                "Nothing was added.")
            self.status.set_message(self._reason)
            return self._coordinator.decline_pending()
        self.status.set_message(f"{proposed:,} files found — waiting for confirmation…")
        if self._confirm_large(outcome):
            return self._coordinator.confirm_pending()
        return self._coordinator.decline_pending()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"ImportAdapter(count={self.count}, importing={self.is_importing}, "
                f"closed={self._closed})")


# --------------------------------------------------------------------------- #
# Job controls
# --------------------------------------------------------------------------- #


class JobControlBar:
    """Pause / Resume / Cancel / Retry Failed, offered exactly when §6.14 allows.

    Availability is not decided here. :func:`~shared.job_control.is_available` decided
    it in Phase 6, including the rule that Retry Failed appears only when a completed
    run actually holds a retryable failure, and this turns that answer into button
    state. Pressing a button calls the caller's callback; the adapter never guesses
    what a tool wants pausing or retrying to mean.
    """

    __slots__ = ("_guard", "_theme", "_closed", "_state", "_has_retryable",
                 "_callbacks", "frame", "buttons")

    LABELS = {
        JobAction.PAUSE: "Pause",
        JobAction.RESUME: "Resume",
        JobAction.CANCEL: "Cancel",
        JobAction.RETRY_FAILED: "Retry Failed",
    }

    def __init__(
        self,
        parent: object,
        *,
        theme: Mapping[str, object] | None = None,
        thread_id: int | None = None,
        on_pause: Callable[[], object] | None = None,
        on_resume: Callable[[], object] | None = None,
        on_cancel: Callable[[], object] | None = None,
        on_retry: Callable[[], object] | None = None,
    ) -> None:
        self._guard = MainThreadGuard(thread_id)
        self._theme = theme
        self._closed = False
        self._state = JobState.IDLE
        self._has_retryable = False
        self._callbacks: dict[JobAction, Callable[[], object] | None] = {
            JobAction.PAUSE: on_pause,
            JobAction.RESUME: on_resume,
            JobAction.CANCEL: on_cancel,
            JobAction.RETRY_FAILED: on_retry,
        }

        self.frame = ttk.Frame(parent, style=style_name(theme, "card"))
        self.buttons: dict[JobAction, ttk.Button] = {}
        danger = style_name(theme, "danger_button")
        neutral = style_name(theme, "button")
        for column, action in enumerate(self.LABELS):
            button = ttk.Button(
                self.frame, text=self.LABELS[action],
                command=lambda bound=action: self.invoke(bound),
                style=danger if action is JobAction.CANCEL else neutral)
            button.grid(row=0, column=column, padx=(0 if column == 0 else 6, 0))
            self.buttons[action] = button
        self.apply(JobState.IDLE)

    @property
    def guard(self) -> MainThreadGuard:
        return self._guard

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def state(self) -> JobState:
        return self._state

    @property
    def has_retryable(self) -> bool:
        return self._has_retryable

    def availability(self) -> Mapping[JobAction, bool]:
        return {
            action: is_available(action, self._state, has_retryable=self._has_retryable)
            for action in self.LABELS
        }

    def apply(self, state: JobState, *, has_retryable: bool = False) -> Mapping[JobAction, bool]:
        self._guard.require("apply")
        if not isinstance(state, JobState):
            raise JobUiError(f"state must be a JobState, got {type(state).__name__}")
        self._state = state
        self._has_retryable = bool(has_retryable)
        available = self.availability()
        if not self._closed:
            for action, enabled in available.items():
                _enable(self.buttons.get(action), enabled)
        return available

    def invoke(self, action: JobAction) -> bool:
        """Press one button. A press the current state forbids does nothing at all."""
        self._guard.require("invoke")
        if self._closed or not self.availability().get(action, False):
            return False
        callback = self._callbacks.get(action)
        if callback is None:
            return False
        callback()
        return True

    def set_locked(self, locked: bool) -> None:
        # Job controls are the one kind §6.11 keeps usable during a run: locking them
        # would remove Cancel exactly when it matters. Availability alone governs them.
        self._guard.require("set_locked")

    def close(self) -> None:
        self._guard.require("close")
        if self._closed:
            return
        self._closed = True
        for button in self.buttons.values():
            _enable(button, False)
        self._callbacks = dict.fromkeys(self._callbacks, None)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"JobControlBar(state={self._state.name}, closed={self._closed})"


class JobStatusView:
    """The shared :class:`~shared.ui_theme.ProgressIndicator`, plus stage, item and ETA.

    The indicator is the existing one — §5.2 forbids a second progress implementation,
    so this creates no progressbar of its own and passes it no style, leaving the five
    unconverted panels' rendering untouched. What is shown is exactly what the
    Phase 7 :class:`~shared.job_control.ProgressView` says: an unknown total stays
    indeterminate, a cancelled or failed run keeps the count it really reached, and
    nothing is ever rounded up to a hundred per cent to make an ending look tidy.
    """

    __slots__ = ("_guard", "_theme", "_closed", "_view",
                 "frame", "indicator", "var_stage", "var_eta", "var_status",
                 "label_stage", "label_eta", "label_status")

    def __init__(
        self,
        parent: object,
        *,
        theme: Mapping[str, object] | None = None,
        thread_id: int | None = None,
        progress_length: int = 240,
    ) -> None:
        self._guard = MainThreadGuard(thread_id)
        self._theme = theme
        self._closed = False
        self._view: ProgressView | None = None

        self.frame = ttk.Frame(parent, style=style_name(theme, "card"))
        self.indicator = ui_theme.ProgressIndicator(self.frame, length=progress_length)
        self.indicator.frame.grid(row=0, column=0, columnspan=2, sticky="ew")

        self.var_stage = tk.StringVar(master=self.frame, value="")
        self.label_stage = ttk.Label(self.frame, textvariable=self.var_stage,
                                     style=style_name(theme, "secondary_label"))
        self.label_stage.grid(row=1, column=0, sticky="w")

        self.var_eta = tk.StringVar(master=self.frame, value=CALCULATING)
        self.label_eta = ttk.Label(self.frame, textvariable=self.var_eta,
                                   style=style_name(theme, "secondary_label"))
        self.label_eta.grid(row=1, column=1, sticky="e")

        self.var_status = tk.StringVar(master=self.frame, value="")
        self.label_status = ttk.Label(self.frame, textvariable=self.var_status,
                                      style=style_name(theme, "status_label"))
        self.label_status.grid(row=2, column=0, columnspan=2, sticky="w")
        self.frame.columnconfigure(0, weight=1)

    @property
    def guard(self) -> MainThreadGuard:
        return self._guard

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def view(self) -> ProgressView | None:
        return self._view

    @property
    def stage_text(self) -> str:
        return _read_str(self.var_stage)

    @property
    def eta_text(self) -> str:
        return _read_str(self.var_eta)

    @property
    def status_text(self) -> str:
        return _read_str(self.var_status)

    def apply(
        self,
        view: ProgressView,
        *,
        stage: str | None = None,
        item_id: str | None = None,
    ) -> ProgressView:
        self._guard.require("apply")
        if not isinstance(view, ProgressView):
            raise JobUiError(f"view must be a ProgressView, got {type(view).__name__}")
        self._view = view
        if self._closed or not _alive(self.indicator.bar):
            return view
        # The indicator is the shared one and knows nothing about teardown, so the
        # destroyed-widget guard belongs here: a worker's last event can easily arrive
        # after the window went away, and drawing it must be a no-op rather than a
        # traceback out of an ``after`` callback.
        try:
            if view.mode is ProgressMode.DETERMINATE and view.total is not None:
                self.indicator.update(view.completed, view.total)
            elif view.mode is ProgressMode.INDETERMINATE:
                self.indicator.set_indeterminate(view.label or "Working…")
            else:
                self.indicator.reset()
        except tk.TclError:
            return view
        self._write(self.var_stage, _stage_text(stage, item_id))
        return view

    def set_eta(self, text: str) -> None:
        self._guard.require("set_eta")
        self._write(self.var_eta, str(text))

    def set_status(self, text: str) -> None:
        self._guard.require("set_status")
        self._write(self.var_status, str(text))

    def finish(self) -> None:
        """End-of-run cleanup. Stops an animation; never invents a completion."""
        self._guard.require("finish")
        if self._closed or not _alive(self.indicator.bar):
            return
        try:
            self.indicator.finish()
        except tk.TclError:
            pass

    def set_locked(self, locked: bool) -> None:
        # Progress and status stay readable in every state, exactly as §6.11 requires.
        self._guard.require("set_locked")

    def close(self) -> None:
        self._guard.require("close")
        self._closed = True

    def _write(self, variable: tk.StringVar, value: str) -> None:
        try:
            variable.set(value)
        except tk.TclError:
            pass

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"JobStatusView(eta={self.eta_text!r}, closed={self._closed})"


def _read_str(variable: tk.StringVar) -> str:
    try:
        return str(variable.get())
    except tk.TclError:
        return ""


def _stage_text(stage: str | None, item_id: str | None) -> str:
    if stage and item_id:
        return f"{stage} — {item_id}"
    return stage or item_id or ""


class SummaryDetailsView:
    """The Summary / Details pair, each fed by its own approved projection.

    Summary renders :func:`~shared.job_control.project_summary`'s lines; Details
    renders :func:`~shared.job_control.detail_lines`. Neither is filtered, reordered or
    embellished here — in particular Summary is never given a diagnostic, because the
    projection that builds it never reads the field diagnostics live in.
    """

    __slots__ = ("_guard", "_theme", "_closed", "_summary", "_details",
                 "frame", "summary_text", "details_text",
                 "summary_frame", "details_frame")

    def __init__(
        self,
        parent: object,
        *,
        theme: Mapping[str, object] | None = None,
        thread_id: int | None = None,
        height: int = 10,
        width: int = 60,
    ) -> None:
        self._guard = MainThreadGuard(thread_id)
        self._theme = theme
        self._closed = False
        self._summary: tuple[str, ...] = ()
        self._details: tuple[str, ...] = ()

        self.frame = ttk.Notebook(parent, style=style_name(theme, "notebook"))
        self.summary_frame, self.summary_text = self._page(theme, height, width)
        self.details_frame, self.details_text = self._page(theme, height, width)
        self.frame.add(self.summary_frame, text="Summary")
        self.frame.add(self.details_frame, text="Details")

    @property
    def guard(self) -> MainThreadGuard:
        return self._guard

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def summary(self) -> tuple[str, ...]:
        return self._summary

    @property
    def details(self) -> tuple[str, ...]:
        return self._details

    def set_summary(self, lines: Iterable[str]) -> tuple[str, ...]:
        self._guard.require("set_summary")
        self._summary = tuple(str(line) for line in lines)
        self._write(self.summary_text, self._summary)
        return self._summary

    def set_details(self, lines: Iterable[str]) -> tuple[str, ...]:
        self._guard.require("set_details")
        self._details = tuple(str(line) for line in lines)
        self._write(self.details_text, self._details)
        return self._details

    def show_summary(self) -> None:
        self._guard.require("show_summary")
        self._select(0)

    def show_details(self) -> None:
        self._guard.require("show_details")
        self._select(1)

    def selected_tab(self) -> int:
        """Which page is showing. Reads the widget, so: main thread."""
        self._guard.require("selected_tab")
        if not _alive(self.frame):
            return -1
        try:
            return self.frame.index(self.frame.select())
        except tk.TclError:
            return -1

    def rendered(self, widget: tk.Text) -> str:
        """What one pane is actually displaying. Reads the widget, so: main thread."""
        self._guard.require("rendered")
        if not _alive(widget):
            return ""
        try:
            return widget.get("1.0", "end-1c")
        except tk.TclError:
            return ""

    def set_locked(self, locked: bool) -> None:
        # §6.11 keeps the log views usable in every state; they are read-only already.
        self._guard.require("set_locked")

    def close(self) -> None:
        self._guard.require("close")
        self._closed = True

    # -- internals --------------------------------------------------------- #

    def _page(
        self, theme: Mapping[str, object] | None, height: int, width: int,
    ) -> tuple[ttk.Frame, tk.Text]:
        page = ttk.Frame(self.frame, style=style_name(theme, "surface"))
        text = tk.Text(page, height=max(1, int(height)), width=max(1, int(width)),
                       wrap="none", state="disabled")
        ui_theme.style_tk_widget(text, theme or {}, "log")
        text.grid(row=0, column=0, sticky="nsew")
        bar = ttk.Scrollbar(page, orient="vertical", command=text.yview,
                            style=style_name(theme, "vscrollbar"))
        bar.grid(row=0, column=1, sticky="ns")
        text.configure(yscrollcommand=bar.set)
        page.rowconfigure(0, weight=1)
        page.columnconfigure(0, weight=1)
        return page, text

    def _write(self, widget: tk.Text, lines: Sequence[str]) -> None:
        if self._closed or not _alive(widget):
            return
        try:
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            if lines:
                widget.insert("1.0", "\n".join(lines))
            widget.configure(state="disabled")
        except tk.TclError:
            return

    def _select(self, index: int) -> None:
        if self._closed or not _alive(self.frame):
            return
        try:
            self.frame.select(index)
        except tk.TclError:
            pass

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"SummaryDetailsView(summary={len(self._summary)}, "
                f"details={len(self._details)}, closed={self._closed})")


# --------------------------------------------------------------------------- #
# The job adapter
# --------------------------------------------------------------------------- #


class JobAdapter:
    """One compositional adapter for the whole job side of §6.15.

    Its only source of truth is the :class:`~shared.job_control.JobEventStream`. Every
    state-bearing event in that stream was minted by Phase 7's reporter *from a
    controller snapshot*, so rendering the stream is rendering the controller — and the
    two claims §5.4 forbids are unconstructible rather than merely avoided: a `PAUSED`
    the worker never acknowledged and a `CANCELLED` that came before cleanup cannot
    exist as events, so they cannot be drawn.

    Draining happens on the caller's :class:`MainThreadPump`. A stale-run event, an
    unknown occurrence, a second ending and anything after an ending are rejected by
    the stream itself, and a rejected event is inert here too: it is not rendered, not
    counted, and not logged. Accepted technical events are already forwarded by the
    stream's :class:`~shared.job_control.LoggerBridge`, so this never logs them again.
    """

    __slots__ = (
        "_guard", "_pump", "_stream", "_estimator", "_pull", "_limit", "_closed",
        "_result", "_summary_view", "_verdicts", "_on_event", "_on_terminal",
        "frame", "controls", "status", "views", "locks",
    )

    def __init__(
        self,
        parent: object,
        *,
        run_id: str,
        pump: MainThreadPump,
        theme: Mapping[str, object] | None = None,
        thread_id: int | None = None,
        pull: Callable[[], object] | None = None,
        stream: JobEventStream | None = None,
        estimator: EtaEstimator | None = None,
        bridge: LoggerBridge | None = None,
        item_ids: Iterable[str] | None = None,
        limit: int = DEFAULT_PUMP_LIMIT,
        on_pause: Callable[[], object] | None = None,
        on_resume: Callable[[], object] | None = None,
        on_cancel: Callable[[], object] | None = None,
        on_retry: Callable[[], object] | None = None,
        on_event: Callable[[JobEvent], object] | None = None,
        on_terminal: Callable[[JobEvent], object] | None = None,
        details_height: int = 10,
    ) -> None:
        if not isinstance(pump, MainThreadPump):
            raise JobUiError(f"pump must be a MainThreadPump, got {type(pump).__name__}")
        self._guard = MainThreadGuard(thread_id)
        self._pump = pump
        self._stream = (
            JobEventStream(run_id, item_ids=item_ids, bridge=bridge)
            if stream is None else stream)
        if self._stream.run_id != run_id:
            raise JobUiError(
                f"the supplied stream belongs to run {self._stream.run_id!r}, "
                f"not {run_id!r}")
        self._estimator = estimator
        self._pull = pull
        self._limit = int(limit)
        self._closed = False
        self._result: RunResult | None = None
        self._summary_view: SummaryView | None = None
        self._verdicts: tuple[object, ...] = ()
        self._on_event = on_event
        self._on_terminal = on_terminal

        self.frame = ttk.Frame(parent, style=style_name(theme, "surface"))
        self.controls = JobControlBar(
            self.frame, theme=theme, thread_id=thread_id, on_pause=on_pause,
            on_resume=on_resume, on_cancel=on_cancel, on_retry=on_retry)
        self.status = JobStatusView(self.frame, theme=theme, thread_id=thread_id)
        self.views = SummaryDetailsView(
            self.frame, theme=theme, thread_id=thread_id, height=details_height)
        self.locks = LockGroup(thread_id=thread_id)

        self.controls.frame.grid(row=0, column=0, sticky="w")
        self.status.frame.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.views.frame.grid(row=2, column=0, sticky="nsew", pady=(8, 0))
        self.frame.rowconfigure(2, weight=1)
        self.frame.columnconfigure(0, weight=1)

        self.locks.register(ControlKind.JOB_CONTROL, self.controls)
        self.locks.register(ControlKind.PROGRESS_STATUS, self.status)
        self.locks.register(ControlKind.LOG_VIEW, self.views)

        pump.add_drain(self.drain)
        self.render()

    # -- reading ----------------------------------------------------------- #

    @property
    def guard(self) -> MainThreadGuard:
        return self._guard

    @property
    def run_id(self) -> str:
        return self._stream.run_id

    @property
    def stream(self) -> JobEventStream:
        return self._stream

    @property
    def estimator(self) -> EtaEstimator | None:
        return self._estimator

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def state(self) -> JobState:
        view = self._summary_view
        return JobState.IDLE if view is None or view.state is None else view.state

    @property
    def summary_view(self) -> SummaryView | None:
        return self._summary_view

    @property
    def result(self) -> RunResult | None:
        return self._result

    @property
    def last_verdicts(self) -> tuple[object, ...]:
        """What the stream made of the events drained on the most recent tick."""
        return self._verdicts

    # -- draining ---------------------------------------------------------- #

    def drain(self) -> int:
        """One bounded drain of the worker queue, then one render. Main thread only."""
        self._guard.require("drain")
        if self._closed or self._pull is None:
            self._verdicts = ()
            return 0
        before = len(self._stream.events)
        self._verdicts = self._stream.pump(self._pull, limit=self._limit)
        accepted = self._stream.events[before:]
        for entry in accepted:
            if self._estimator is not None:
                self._estimator.observe(entry)
            if self._on_event is not None:
                self._on_event(entry)
        if accepted:
            self.render()
            terminal = self._stream.terminal
            if terminal is not None and terminal in accepted and self._on_terminal:
                self._on_terminal(terminal)
        return len(accepted)

    def render(self) -> SummaryView:
        """Redraw everything from the accepted events. Deterministic and idempotent."""
        self._guard.require("render")
        events = self._stream.events
        view = project_summary(events)
        view = replace(view, eta=self._eta_text(view.progress))
        self._summary_view = view
        if self._closed:
            return view
        state = view.state or JobState.IDLE
        self.status.apply(view.progress, stage=view.stage, item_id=view.current_item_id)
        self.status.set_eta(view.eta)
        self.status.set_status(view.final or _summary_status(view))
        self.views.set_summary(view.lines)
        self.views.set_details(detail_lines(events))
        self.controls.apply(state, has_retryable=self.has_retryable)
        self.locks.apply(state)
        if state in _ENDED_STATES:
            self.status.finish()
        return view

    @property
    def has_retryable(self) -> bool:
        """Only a settled run can offer Retry Failed, and only if it holds one."""
        result = self._result
        return bool(result is not None and result.has_retryable)

    def set_result(self, result: RunResult | None) -> SummaryView:
        """Hand the adapter the settled run so Retry Failed can become available."""
        self._guard.require("set_result")
        if result is not None and not isinstance(result, RunResult):
            raise JobUiError(f"result must be a RunResult, got {type(result).__name__}")
        self._result = result
        return self.render()

    def register_inputs(self, *targets: object) -> None:
        """Register imported-input widgets so a run locks them through the matrix."""
        self._guard.require("register_inputs")
        self.locks.register(ControlKind.IMPORTED_INPUT, *targets)

    def register_options(self, *targets: object) -> None:
        """Register processing-option widgets so a run locks them through the matrix."""
        self._guard.require("register_options")
        self.locks.register(ControlKind.PROCESSING_OPTION, *targets)

    def close(self) -> None:
        """Detach from the pump and make every later event inert. Idempotent."""
        self._guard.require("close")
        if self._closed:
            return
        self._closed = True
        self._pump.remove_drain(self.drain)
        self._pull = None
        self.controls.close()
        self.status.close()
        self.views.close()
        self.locks.close()
        self._on_event = None
        self._on_terminal = None

    # -- internals --------------------------------------------------------- #

    def _eta_text(self, progress: ProgressView) -> str:
        if self._estimator is None:
            return CALCULATING
        remaining: int | None = None
        if progress.mode is ProgressMode.DETERMINATE and progress.total is not None:
            remaining = max(0, progress.total - progress.completed)
        return self._estimator.display(remaining, run_id=self.run_id)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"JobAdapter(run_id={self.run_id!r}, state={self.state.name}, "
                f"closed={self._closed})")


#: States in which an animating indeterminate bar should stop. A determinate bar keeps
#: whatever count it genuinely reached — see ``ProgressIndicator.finish``.
_ENDED_STATES = frozenset({
    JobState.SUCCEEDED, JobState.COMPLETED_WITH_FAILURES, JobState.FAILED,
    JobState.CANCELLED,
})


def _summary_status(view: SummaryView) -> str:
    """A one-line status while a run is still going: the last Summary line."""
    return view.lines[-1] if view.lines else ""


# --------------------------------------------------------------------------- #
# Optional main-thread dialog helpers
# --------------------------------------------------------------------------- #
#
# The adapters take their dialogs as callbacks so a test can drive them without a
# single modal window. These three are what a real panel — or the developer harness —
# passes in. Every one of them imports its Tk dialog module *inside* the function, so
# merely importing this module opens nothing, and the adapters keep working on a host
# where no dialog can be shown.


def ask_files(parent: object, title: str = "Add files",
              filetypes: Sequence[tuple[str, str]] = ()) -> tuple[str, ...]:
    """Ask for files. The dialog's filter is convenience; Phase 3 revalidates them."""
    from tkinter import filedialog

    chosen = filedialog.askopenfilenames(
        parent=parent, title=title, filetypes=tuple(filetypes) or [("All files", "*.*")])
    return tuple(chosen or ())


def ask_folder(parent: object, title: str = "Add folder") -> tuple[str, ...]:
    """Ask for one folder root. Returns a tuple so it matches ``choose_folder``."""
    from tkinter import filedialog

    chosen = filedialog.askdirectory(parent=parent, title=title, mustexist=True)
    return (chosen,) if chosen else ()


def ask_confirm(parent: object, title: str, message: str) -> bool:
    """A yes/no confirmation, on the main thread, before anything is committed."""
    from tkinter import messagebox

    return bool(messagebox.askyesno(title=title, message=message, parent=parent))
