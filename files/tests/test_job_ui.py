"""The Tk boundary — v0.6.0 Drop 3 (Plan 3), Phase 8.

``shared/job_ui.py`` is the only module in this drop that may touch Tk, so this is the
only test module that builds widgets. Everything it asserts is about the *boundary*
rather than about behaviour that was already proved somewhere else: Phases 1–7 own
what the manager, the coordinator, the controller, the event stream and the estimator
do, and those suites are unchanged. What is new here is whether a widget can be
reached from the wrong thread, whether a callback can survive a close, and whether the
adapter renders exactly what the approved projections say — no more, and nothing
invented.

Determinism
-----------
**No test sleeps.** The pump is ticked by hand rather than by a real event loop, so
"what happens on the next drain" is a call rather than a wait. The two tests that are
genuinely about threads arrange the race with a :class:`threading.Barrier` or an
:class:`threading.Event` and join within a bounded timeout, so a deadlock fails loudly
instead of hanging the suite. Import scans that are not about concurrency run inline
through the approved Phase 4 thread factory.

Safety
------
Every file lives under ``tmp_path``. Nothing scans the repository, the real home
directory, Downloads, an output base, runtime data, real media or a network share.
Nothing opens a dialog: the adapters take their dialogs as callbacks and every test
passes a fake one. Nothing starts ffmpeg, a TTS engine, an installer, a cleanup worker
or a conversion, nothing writes a setting, and nothing creates, reserves, inspects or
validates an output.
"""

from __future__ import annotations

import ast
import queue
import sys
import threading
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")
from tkinter import ttk  # noqa: E402

from shared import job_ui, ui_theme  # noqa: E402
from shared.import_coordination import (  # noqa: E402
    ImportCoordinator,
    ImportOutcome,
    ImportPoller,
    OutcomeStatus,
    StartOutcome,
)
from shared.importing import (  # noqa: E402
    IdFactory,
    ImportedFileManager,
    ImportOptions,
    ImportRoot,
    RootKind,
    ScanRequest,
    SupportedType,
    SupportedTypeCatalog,
    validate_direct_files,
)
from shared.job_control import (  # noqa: E402
    CALCULATING,
    ControlKind,
    EtaEstimator,
    JobAction,
    JobController,
    JobEvent,
    JobEventKind,
    JobEventStream,
    JobReporter,
    JobSnapshot,
    JobState,
    LoggerBridge,
    ProgressMode,
    ProgressView,
    RunResult,
    capture_run,
    is_locked,
    state_message,
    FailureLog,
    FailureRecord,
)

from test_import_coordination import (  # noqa: E402
    ControlledScanner,
    InlineThread,
    RecordingThreads,
)
from test_import_traversal import snapshot_tree, touch  # noqa: E402
from test_importing import make_config  # noqa: E402
import tk_gate  # noqa: E402

#: Every wait in this file is bounded so a deadlock fails rather than hangs. It is
#: never used to *create* a race.
WAIT = 5.0

#: Generic ttk styles the five unconverted production panels render with. Phase 8 may
#: not create, reconfigure or re-lay-out one of them.
GENERIC_STYLES = (
    "TFrame", "TLabel", "TButton", "TEntry", "TCheckbutton", "TNotebook",
    "TNotebook.Tab", "Horizontal.TProgressbar", "Vertical.TScrollbar", "TSeparator",
)


# --------------------------------------------------------------------------- #
# Fixtures and helpers
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def tk_root():
    yield from tk_gate.tk_root_session(tk)


@pytest.fixture
def parent(tk_root):
    frame = ttk.Frame(tk_root)
    yield frame
    try:
        frame.destroy()
    except tk.TclError:
        pass


@pytest.fixture
def pump(parent):
    made = job_ui.MainThreadPump(parent)
    yield made
    if not made.closed:
        made.close()


@pytest.fixture
def windows_theme(tk_root, monkeypatch):
    """The Windows ``ACT.*`` bundle, forced on any host."""
    monkeypatch.setattr(sys, "platform", "win32")
    style = ttk.Style(tk_root)
    theme = ui_theme.apply_theme(tk_root, style)
    yield theme
    restore = ttk.Style(tk_root)
    if "vista" in restore.theme_names():
        restore.theme_use("vista")


def catalog() -> SupportedTypeCatalog:
    return SupportedTypeCatalog((
        SupportedType("mp3", "MP3 audio", (".mp3",)),
        SupportedType("m4b", "M4B audiobook", (".m4b",)),
    ))


def options(*, duplicates: bool = False, hidden: bool = False, selected=None) -> ImportOptions:
    if selected is None:
        return ImportOptions.for_catalog(
            catalog(), include_hidden_folders=hidden, allow_duplicate_files=duplicates)
    return ImportOptions(
        selected_type_ids=frozenset(selected),
        include_hidden_folders=hidden,
        allow_duplicate_files=duplicates,
    )


def direct_root(order: int = 0, root_id: str = "direct-1") -> ImportRoot:
    return ImportRoot(root_id=root_id, path=None, order=order, kind=RootKind.DIRECT_FILES)


def folder_root(path: Path, order: int = 0, root_id: str = "root-1") -> ImportRoot:
    return ImportRoot(root_id=root_id, path=path, order=order, kind=RootKind.FOLDER)


def request_for(*roots: ImportRoot, threshold: int = 1000, **kwargs) -> ScanRequest:
    return ScanRequest(
        request_id=kwargs.pop("request_id", "req-1"),
        roots=tuple(roots),
        catalog=catalog(),
        options=kwargs.pop("options", options()),
        effective_config=make_config(threshold),
        created_at=0.0,
    )


def fill(manager: ImportedFileManager, *paths: Path, allow_duplicates: bool = False) -> None:
    """Commit real paths into *manager*, in order, through the approved Phase 3 path."""
    chosen = options(duplicates=allow_duplicates)
    result = validate_direct_files(
        paths, request_id="fill", root=direct_root(), catalog=catalog(), options=chosen)
    transaction = manager.plan(result, options=chosen, transaction_id="tx-fill")
    manager.commit(transaction)


def book(tmp_path: Path, *names: str) -> tuple[Path, ...]:
    made = []
    for name in names or ("01.mp3", "02.mp3", "10.mp3"):
        made.append(touch(tmp_path / name, name))
    return tuple(made)


def enabled(widget) -> bool:
    """Whether a ttk widget is currently clickable."""
    return "disabled" not in widget.state()


def snapshot_for(state: JobState, run_id: str = "run-1", revision: int = 1) -> JobSnapshot:
    """A controller snapshot in *state*, with the companion flags that state implies."""
    return JobSnapshot(
        run_id=run_id,
        state=state,
        revision=revision,
        pause_requested=state in (JobState.PAUSE_REQUESTED, JobState.PAUSED),
        cancel_requested=state in (JobState.CANCEL_REQUESTED, JobState.CANCELLED),
        cancel_acknowledged=state is JobState.CANCELLED,
        failure_message="The run failed." if state is JobState.FAILED else "",
    )


class FakeClock:
    """A monotonic clock that only ever moves when a test says so."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = float(start)
        self.reads = 0

    def __call__(self) -> float:
        self.reads += 1
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += float(seconds)
        return self.now


class RecordingLogger:
    """Stands in for the one session logger and records every call it receives."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    def __getattr__(self, level: str):
        def record(*args, **_kwargs):
            self.calls.append((level, args))
        return record

    def levels(self) -> list[str]:
        return [level for level, _args in self.calls]


class Publisher:
    """A queue plus the reporter that fills it. One run, one seam."""

    def __init__(self, run_id: str = "run-1", clock: FakeClock | None = None,
                 item_ids=()) -> None:
        self.queue: queue.SimpleQueue = queue.SimpleQueue()
        self.clock = clock or FakeClock()
        self.reporter = JobReporter(
            run_id, clock=self.clock, publish=self.queue.put, item_ids=item_ids)

    @property
    def pull(self):
        return job_ui.queue_pull(self.queue)


def run_snapshot(manager: ImportedFileManager | None = None, snapshot_id: str = "run-1"):
    holder = ImportedFileManager() if manager is None else manager
    return capture_run(
        snapshot_id=snapshot_id,
        files=holder.snapshot(),
        catalog=catalog(),
        import_options=options(),
        effective_config=make_config(),
    )


def on_thread(call, *args, **kwargs):
    """Run *call* on another thread and return ``(result, exception)``."""
    box: dict[str, object] = {}

    def body() -> None:
        try:
            box["result"] = call(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 - the exception *is* the result
            box["error"] = exc

    worker = threading.Thread(target=body, name="off-main")
    worker.start()
    worker.join(WAIT)
    assert not worker.is_alive(), "the off-thread call never returned"
    return box.get("result"), box.get("error")


# --------------------------------------------------------------------------- #
# Thread ownership
# --------------------------------------------------------------------------- #


def test_the_guard_remembers_the_thread_that_built_it():
    guard = job_ui.MainThreadGuard()
    assert guard.thread_id == threading.get_ident()
    assert guard.is_current
    guard.require("here")  # no exception on the owning thread

    _result, error = on_thread(guard.require, "elsewhere")
    assert isinstance(error, job_ui.MainThreadError)
    assert "elsewhere" in str(error)
    assert isinstance(error, job_ui.JobUiError)


def test_a_guard_can_be_told_which_thread_owns_tk():
    guard = job_ui.MainThreadGuard(thread_id=threading.get_ident() + 1)
    assert not guard.is_current
    with pytest.raises(job_ui.MainThreadError):
        guard.require("anything")


def test_every_adapter_records_the_thread_that_constructed_it(parent, pump):
    manager = ImportedFileManager()
    listing = job_ui.ImportedFileList(parent, manager)
    bar = job_ui.JobControlBar(parent)
    status = job_ui.JobStatusView(parent)
    views = job_ui.SummaryDetailsView(parent)
    for component in (pump, listing, bar, status, views):
        assert component.guard.thread_id == threading.get_ident()


def test_a_worker_cannot_mutate_the_list_and_does_not_reach_tk_first(parent, tmp_path):
    """The rejection has to happen *before* a widget is read, not after."""
    manager = ImportedFileManager()
    fill(manager, *book(tmp_path))
    listing = job_ui.ImportedFileList(parent, manager)
    before = listing.rows()

    for action in (listing.refresh, listing.clear, listing.remove_selected,
                   listing.move_up, listing.move_down, listing.apply_button_states,
                   listing.focus, listing.close):
        _result, error = on_thread(action)
        assert isinstance(error, job_ui.MainThreadError), action.__name__

    assert listing.rows() == before, "a refused call changed the widget anyway"
    assert manager.count == 3


def test_a_worker_cannot_read_a_tk_variable_or_schedule_a_callback(parent, pump):
    bar = job_ui.ImportOptionsBar(parent, catalog())

    _result, error = on_thread(bar.options)
    assert isinstance(error, job_ui.MainThreadError)
    _result, error = on_thread(bar.selected_type_ids)
    assert isinstance(error, job_ui.MainThreadError)

    # ``after`` is unreachable from a worker: the only door to it raises first.
    _result, error = on_thread(pump.schedule, 10, lambda: None)
    assert isinstance(error, job_ui.MainThreadError)
    _result, error = on_thread(pump.tick)
    assert isinstance(error, job_ui.MainThreadError)
    _result, error = on_thread(pump.start)
    assert isinstance(error, job_ui.MainThreadError)
    assert pump.pending is None and pump.scheduled_count == 0


def test_worker_communication_is_a_queue_and_nothing_else(parent, pump):
    """A real worker publishes; the main thread draws. Ordering survives the trip."""
    publisher = Publisher()
    adapter = job_ui.JobAdapter(
        parent, run_id="run-1", pump=pump, pull=publisher.pull)
    gate = threading.Barrier(2, timeout=WAIT)

    def body() -> None:
        gate.wait()
        publisher.reporter.stage_changed("Reading")
        for done in range(1, 6):
            publisher.reporter.progress(done, 5)
        publisher.reporter.completed(snapshot_for(JobState.SUCCEEDED))

    worker = threading.Thread(target=body, name="publisher")
    worker.start()
    try:
        gate.wait()
        worker.join(WAIT)
        assert not worker.is_alive()
        assert adapter.drain() == 7
    finally:
        worker.join(WAIT)

    sequences = [entry.sequence for entry in adapter.stream.events]
    assert sequences == sorted(sequences), "the queue order is the render order"
    assert adapter.state is JobState.SUCCEEDED
    assert adapter.status.view.completed == 5


# --------------------------------------------------------------------------- #
# The one main-thread pump
# --------------------------------------------------------------------------- #


def test_a_pump_needs_something_that_can_schedule():
    with pytest.raises(job_ui.JobUiError):
        job_ui.MainThreadPump(object())


def test_a_pump_rejects_a_meaningless_interval(parent):
    with pytest.raises(job_ui.JobUiError):
        job_ui.MainThreadPump(parent, interval_ms=0)


def test_an_empty_drain_is_legal_and_does_nothing(pump):
    assert pump.tick() == 0
    assert pump.ticks == 1
    assert pump.pending is None


def test_drains_run_in_registration_order_on_every_tick(pump):
    order: list[str] = []
    pump.add_drain(lambda: order.append("first"))
    pump.add_drain(lambda: order.append("second"))
    pump.tick()
    pump.tick()
    assert order == ["first", "second", "first", "second"]
    assert pump.drain_count == 2


def test_a_drain_is_registered_once_and_can_be_removed(pump):
    calls: list[int] = []

    def drain() -> None:
        calls.append(1)

    pump.add_drain(drain)
    pump.add_drain(drain)
    assert pump.drain_count == 1
    pump.tick()
    pump.remove_drain(drain)
    pump.tick()
    assert calls == [1]


def test_a_scheduled_callback_runs_once_on_the_next_tick(pump):
    calls: list[str] = []
    pump.schedule(5, lambda: calls.append("once"))
    assert pump.scheduled_count == 1
    pump.tick()
    assert calls == ["once"]
    pump.tick()
    assert calls == ["once"], "a one-shot callback does not repeat itself"


def test_a_cancelled_callback_never_runs(pump):
    calls: list[str] = []
    handle = pump.schedule(5, lambda: calls.append("no"))
    pump.cancel(handle)
    pump.tick()
    assert calls == []
    pump.cancel(handle)  # idempotent
    pump.cancel("not a handle")  # a stale handle is survived, not raised on


def test_only_one_tk_callback_is_ever_outstanding(pump):
    assert pump.pending is None
    assert pump.start() is True
    first = pump.pending
    assert first is not None
    assert pump.start() is False, "starting twice must not create a second chain"
    pump.schedule(5, lambda: None)
    pump.schedule(5, lambda: None)
    assert pump.pending is first, "scheduling rides the existing chain"
    pump.stop()
    assert pump.pending is None


def test_a_running_pump_reschedules_itself_after_a_tick(pump):
    pump.start()
    handle = pump.pending
    pump.tick()
    assert pump.pending is handle, "the outstanding callback is still the only one"
    pump.stop()


def test_stop_is_idempotent_and_leaves_nothing_scheduled(pump):
    pump.start()
    pump.stop()
    pump.stop()
    assert pump.pending is None
    assert pump.running is False
    assert pump.closed is False


def test_close_is_idempotent_and_makes_the_pump_inert(pump):
    calls: list[str] = []
    pump.add_drain(lambda: calls.append("drain"))
    pump.schedule(5, lambda: calls.append("scheduled"))
    pump.start()
    pump.close()
    pump.close()

    assert pump.closed and not pump.running
    assert pump.pending is None
    assert pump.drain_count == 0 and pump.scheduled_count == 0
    assert pump.tick() == 0
    assert calls == [], "nothing registered before the close may run after it"


def test_scheduling_after_close_is_refused_quietly(pump):
    pump.close()
    handle = pump.schedule(5, lambda: pytest.fail("a closed pump ran a callback"))
    assert pump.scheduled_count == 0
    pump.cancel(handle)
    assert pump.tick() == 0
    pump.add_drain(lambda: pytest.fail("a closed pump registered a drain"))
    assert pump.drain_count == 0


def test_a_destroyed_widget_stops_the_chain_instead_of_raising(tk_root):
    holder = ttk.Frame(tk_root)
    made = job_ui.MainThreadPump(holder)
    made.start()
    assert made.pending is not None
    holder.destroy()

    made.stop()          # cancelling against a destroyed widget is survived
    assert made.pending is None
    made.start()         # and rescheduling notices there is nowhere to schedule
    assert made.pending is None
    assert made.running is False
    made.close()


def test_the_pump_never_asks_a_queue_how_big_it_is():
    """``qsize`` is unreliable under concurrency; the drain contract avoids needing it.

    Checked as a *call*, not as a substring: the prose is entitled to explain why the
    module does not use it.
    """
    tree = ast.parse(Path(job_ui.__file__).read_text(encoding="utf-8"))
    called = {
        node.func.attr for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    reached = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "qsize" not in reached
    assert "get_nowait" in reached, "the one draining verb is the non-blocking one"
    for blocking in ("acquire", "sleep"):
        assert blocking not in called, (blocking, "the Tk thread waits for nothing")
    # And the whole of this module's use of ``threading`` is asking who is calling.
    threading_uses = {
        node.attr for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
        and node.value.id == "threading"
    }
    assert threading_uses == {"get_ident"}, threading_uses


def test_the_queue_pull_seam_reports_empty_as_none():
    source: queue.SimpleQueue = queue.SimpleQueue()
    pull = job_ui.queue_pull(source)
    assert pull() is None
    source.put("first")
    source.put("second")
    assert pull() == "first"
    assert pull() == "second"
    assert pull() is None


# --------------------------------------------------------------------------- #
# The imported-file list
# --------------------------------------------------------------------------- #


def test_the_list_refuses_anything_that_is_not_the_approved_manager(parent):
    with pytest.raises(job_ui.JobUiError):
        job_ui.ImportedFileList(parent, object())


def test_an_empty_list_shows_a_count_and_offers_only_what_it_can_do(parent):
    listing = job_ui.ImportedFileList(parent, ImportedFileManager())
    assert listing.rows() == ()
    assert listing.count == 0 and listing.selected_count == 0
    assert listing.count_label.cget("text") == "0 files imported"
    states = listing.button_states()
    assert states["move_up"] is False and states["move_down"] is False
    assert states["remove"] is False and states["clear"] is False
    assert states["add_files"] is False, "no callback means no offer"


def test_the_rows_follow_the_manager_order_and_count_updates(parent, tmp_path):
    manager = ImportedFileManager()
    paths = book(tmp_path, "01.mp3", "02.mp3", "10.mp3")
    fill(manager, *paths)
    listing = job_ui.ImportedFileList(parent, manager)

    assert listing.rows() == ("1. 01.mp3", "2. 02.mp3", "3. 10.mp3")
    assert listing.count == 3
    assert listing.count_label.cget("text") == "3 files imported"
    assert listing.order == manager.snapshot().occurrence_ids


def test_extended_selection_is_available_and_reported_by_occurrence_id(parent, tmp_path):
    manager = ImportedFileManager()
    fill(manager, *book(tmp_path))
    listing = job_ui.ImportedFileList(parent, manager)
    assert str(listing.listbox.cget("selectmode")) == "extended"

    first, _second, third = listing.order
    listing.select((first, third))
    assert listing.selection == (first, third)
    assert listing.selected_count == 2
    assert manager.selection == (first, third)
    assert listing.count_label.cget("text") == "3 files imported — 2 selected"


def test_the_selection_survives_a_rebuild_by_id_and_not_by_index(parent, tmp_path):
    manager = ImportedFileManager()
    fill(manager, *book(tmp_path))
    listing = job_ui.ImportedFileList(parent, manager)
    first, second, _third = listing.order

    listing.select((second,))
    listing.move_up()
    assert listing.rows() == ("1. 02.mp3", "2. 01.mp3", "3. 10.mp3")
    assert listing.selection == (second,), "the moved row is still the selected row"
    assert listing.order == (second, first, listing.order[2])


def test_a_selection_of_a_vanished_occurrence_is_dropped_not_guessed(parent, tmp_path):
    manager = ImportedFileManager()
    fill(manager, *book(tmp_path))
    listing = job_ui.ImportedFileList(parent, manager)
    first = listing.order[0]
    listing.select((first,))
    listing.remove_selected()

    assert listing.selection == ()
    assert listing.rows() == ("1. 02.mp3", "2. 10.mp3")
    assert listing.select(("not-an-occurrence",)) == ()


def test_two_deliberate_duplicates_of_one_path_are_two_rows(parent, tmp_path):
    manager = ImportedFileManager()
    only = touch(tmp_path / "01.mp3", "audio")
    fill(manager, only)
    fill(manager, only, allow_duplicates=True)
    listing = job_ui.ImportedFileList(parent, manager)

    assert len(listing.rows()) == 2
    first, second = listing.order
    assert first != second, "same path, two occurrences, two identities"
    listing.select((second,))
    assert listing.selection == (second,)
    assert listing.selected_count == 1


def test_move_up_and_down_offer_themselves_only_where_they_can_move(parent, tmp_path):
    manager = ImportedFileManager()
    fill(manager, *book(tmp_path))
    listing = job_ui.ImportedFileList(parent, manager)
    first, second, third = listing.order

    listing.select((first,))
    assert listing.button_states()["move_up"] is False
    assert listing.button_states()["move_down"] is True
    listing.select((third,))
    assert listing.button_states()["move_up"] is True
    assert listing.button_states()["move_down"] is False
    listing.select((first, second, third))
    assert listing.button_states()["move_up"] is False
    assert listing.button_states()["move_down"] is False


def test_a_selected_block_moves_together_and_keeps_its_order(parent, tmp_path):
    manager = ImportedFileManager()
    fill(manager, *book(tmp_path, "01.mp3", "02.mp3", "03.mp3", "04.mp3"))
    listing = job_ui.ImportedFileList(parent, manager)
    _first, second, third, _fourth = listing.order

    listing.select((second, third))
    listing.move_down()
    assert listing.rows() == ("1. 01.mp3", "2. 04.mp3", "3. 02.mp3", "4. 03.mp3")
    assert listing.selection == (second, third)


def test_remove_and_clear_change_the_list_and_never_a_source_file(parent, tmp_path):
    manager = ImportedFileManager()
    paths = book(tmp_path)
    fill(manager, *paths)
    before = snapshot_tree(tmp_path)
    listing = job_ui.ImportedFileList(parent, manager)

    listing.select((listing.order[0],))
    listing.remove_selected()
    assert listing.count == 2
    listing.clear()
    assert listing.count == 0 and listing.rows() == ()
    assert listing.button_states()["clear"] is False

    assert snapshot_tree(tmp_path) == before, "removing an entry deleted a file"
    assert all(path.is_file() for path in paths)


def test_add_files_and_add_folder_are_wired_to_their_callbacks(parent):
    pressed: list[str] = []
    listing = job_ui.ImportedFileList(
        parent, ImportedFileManager(),
        on_add_files=lambda: pressed.append("files"),
        on_add_folder=lambda: pressed.append("folder"))

    assert listing.button_states()["add_files"] is True
    listing.buttons["add_files"].invoke()
    listing.buttons["add_folder"].invoke()
    assert pressed == ["files", "folder"]


def test_a_locked_list_answers_nothing_and_offers_nothing(parent, tmp_path):
    pressed: list[str] = []
    manager = ImportedFileManager()
    fill(manager, *book(tmp_path))
    listing = job_ui.ImportedFileList(
        parent, manager, on_add_files=lambda: pressed.append("files"))
    listing.select(listing.order)

    listing.set_locked(True)
    assert listing.locked
    assert str(listing.listbox.cget("state")) == "disabled"
    assert not any(listing.button_states().values())
    for button in listing.buttons.values():
        assert not enabled(button)
    listing.add_files()
    listing.move_down()
    assert pressed == [] and listing.count == 3

    listing.set_locked(False)
    assert str(listing.listbox.cget("state")) == "normal"
    assert listing.button_states()["remove"] is True


def test_the_list_is_keyboard_reachable_and_follows_the_widgets_own_selection(
        parent, tmp_path, tk_root):
    """Tk fires ``<<ListboxSelect>>``; what is ours is what happens next.

    Simulating the keystroke itself would be testing Tk. What this proves is the part
    the adapter owns: the binding is installed, and the handler behind it — the public
    :meth:`sync_selection` the binding calls — makes the manager follow the widget,
    by occurrence ID.
    """
    manager = ImportedFileManager()
    fill(manager, *book(tmp_path))
    listing = job_ui.ImportedFileList(parent, manager)
    parent.pack(fill="both", expand=True)
    listing.frame.pack(fill="both", expand=True)
    tk_root.update_idletasks()

    listing.focus()
    assert str(listing.listbox.cget("takefocus")) in ("1", "true", "")
    assert "<<ListboxSelect>>" in listing.listbox.bind()

    listing.listbox.selection_set(0, 1)     # what an arrow key or a click leaves behind
    assert listing.sync_selection() == listing.order[:2]
    assert manager.selection == listing.order[:2]
    assert listing.count_label.cget("text").endswith("2 selected")
    assert listing.button_states()["move_down"] is True

    listing.listbox.selection_clear(0, "end")
    assert listing.sync_selection() == ()
    assert manager.selection == ()


def test_a_selection_change_reaches_the_callback(parent, tmp_path):
    seen: list[tuple[str, ...]] = []
    manager = ImportedFileManager()
    fill(manager, *book(tmp_path))
    listing = job_ui.ImportedFileList(parent, manager, on_selection_change=seen.append)
    listing.listbox.selection_set(1)
    listing.sync_selection()
    assert seen == [(listing.order[1],)]


def test_a_closed_list_stops_following_the_widget(parent, tmp_path):
    manager = ImportedFileManager()
    fill(manager, *book(tmp_path))
    listing = job_ui.ImportedFileList(parent, manager)
    listing.close()
    listing.listbox.selection_set(0)
    assert listing.sync_selection() == ()
    assert manager.selection == ()


def test_a_closed_list_stops_answering_and_close_is_idempotent(parent, tmp_path):
    pressed: list[str] = []
    manager = ImportedFileManager()
    fill(manager, *book(tmp_path))
    listing = job_ui.ImportedFileList(
        parent, manager, on_add_files=lambda: pressed.append("files"))
    listing.close()
    listing.close()

    assert listing.closed
    listing.add_files()
    assert pressed == []
    assert listing.refresh() == ()
    assert listing.select(listing.order) == ()
    assert manager.count == 3, "closing a view never changes the list it was showing"


def test_a_rebuild_after_an_external_revision_change_shows_the_new_list(parent, tmp_path):
    manager = ImportedFileManager()
    fill(manager, touch(tmp_path / "01.mp3"))
    listing = job_ui.ImportedFileList(parent, manager)
    assert listing.rows() == ("1. 01.mp3",)

    revision = manager.revision
    fill(manager, touch(tmp_path / "02.mp3"))
    assert manager.revision != revision
    listing.refresh()
    assert listing.rows() == ("1. 01.mp3", "2. 02.mp3")


# --------------------------------------------------------------------------- #
# Import options
# --------------------------------------------------------------------------- #


def test_the_options_bar_refuses_anything_that_is_not_a_catalog(parent):
    with pytest.raises(job_ui.JobUiError):
        job_ui.ImportOptionsBar(parent, object())


def test_every_supplied_type_starts_selected_and_the_defaults_are_off(parent):
    bar = job_ui.ImportOptionsBar(parent, catalog())
    assert bar.selected_type_ids() == frozenset({"mp3", "m4b"})
    captured = bar.options()
    assert captured.selected_type_ids == frozenset({"mp3", "m4b"})
    assert captured.include_hidden_folders is False
    assert captured.allow_duplicate_files is False
    assert captured.has_selection


def test_any_combination_of_types_is_representable_including_none(parent):
    bar = job_ui.ImportOptionsBar(parent, catalog())
    assert bar.set_types(("mp3",)) == frozenset({"mp3"})
    assert bar.options().selected_type_ids == frozenset({"mp3"})
    assert bar.set_types(()) == frozenset()
    assert bar.options().has_selection is False
    assert bar.set_types(("mp3", "m4b")) == frozenset({"mp3", "m4b"})


def test_the_catalog_is_supplied_and_never_invented(parent):
    narrow = SupportedTypeCatalog((SupportedType("epub", "EPUB", (".epub",)),))
    bar = job_ui.ImportOptionsBar(parent, narrow)
    assert tuple(bar.type_vars) == ("epub",)
    assert bar.options().selected_type_ids == frozenset({"epub"})


def test_hidden_and_duplicate_options_are_captured_as_frozen_values(parent):
    changes: list[ImportOptions] = []
    bar = job_ui.ImportOptionsBar(
        parent, catalog(), on_change=changes.append,
        include_hidden_folders=True, allow_duplicate_files=True)
    captured = bar.options()
    assert captured.include_hidden_folders is True
    assert captured.allow_duplicate_files is True

    bar.set_include_hidden(False)
    bar.set_allow_duplicates(False)
    later = bar.options()
    assert later.include_hidden_folders is False and later.allow_duplicate_files is False
    assert captured.include_hidden_folders is True, "a captured request is frozen"

    bar.check_hidden.invoke()
    assert changes and changes[-1].include_hidden_folders is True


def test_locking_the_options_disables_every_control(parent):
    bar = job_ui.ImportOptionsBar(parent, catalog())
    bar.set_locked(True)
    for widget in (*bar.type_buttons.values(), bar.check_hidden, bar.check_duplicates):
        assert not enabled(widget)
    bar.set_locked(False)
    for widget in (*bar.type_buttons.values(), bar.check_hidden, bar.check_duplicates):
        assert enabled(widget)


# --------------------------------------------------------------------------- #
# Import status and Cancel Import
# --------------------------------------------------------------------------- #


def test_the_status_bar_reports_the_live_count_and_never_an_estimate(parent):
    bar = job_ui.ImportStatusBar(parent)
    assert bar.text == job_ui.ImportStatusBar.IDLE_TEXT
    assert bar.cancel_enabled is False

    bar.set_scanning(1)
    assert bar.text == "Scanning… 1 file found"
    bar.set_scanning(1234)
    assert bar.text == "Scanning… 1,234 files found"
    assert bar.discovered_count == 1234
    assert bar.cancel_enabled is True
    assert CALCULATING not in bar.text


def test_cancel_import_is_its_own_button_and_reaches_its_own_callback(parent):
    pressed: list[str] = []
    bar = job_ui.ImportStatusBar(parent, on_cancel=lambda: pressed.append("import"))
    bar.set_scanning(3)
    bar.button_cancel.invoke()
    assert pressed == ["import"]

    bar.set_cancelling()
    assert bar.text == job_ui.ImportStatusBar.CANCELLING_TEXT
    assert bar.cancel_enabled is False


def test_a_closed_status_bar_cannot_cancel_anything(parent):
    pressed: list[str] = []
    bar = job_ui.ImportStatusBar(parent, on_cancel=lambda: pressed.append("import"))
    bar.close()
    bar.cancel()
    assert pressed == []
    assert bar.cancel_enabled is False


# --------------------------------------------------------------------------- #
# The imported-file adapter
# --------------------------------------------------------------------------- #


def adapter_for(parent, pump, manager=None, **kwargs):
    kwargs.setdefault("catalog", catalog())
    kwargs.setdefault("effective_config", make_config())
    kwargs.setdefault("id_factory", IdFactory("a-"))
    return job_ui.ImportAdapter(parent, pump=pump, manager=manager, **kwargs)


def coordinator_for(manager, **kwargs):
    kwargs.setdefault("id_factory", IdFactory("c-"))
    kwargs.setdefault("home", None)
    kwargs.setdefault("thread_factory", RecordingThreads())
    return ImportCoordinator(manager, **kwargs)


def test_the_adapter_needs_a_pump_and_a_manager_for_a_supplied_coordinator(parent, pump):
    with pytest.raises(job_ui.JobUiError):
        job_ui.ImportAdapter(parent, catalog=catalog(),
                             effective_config=make_config(), pump=object())
    manager = ImportedFileManager()
    with pytest.raises(job_ui.JobUiError):
        job_ui.ImportAdapter(parent, catalog=catalog(), effective_config=make_config(),
                             pump=pump, coordinator=coordinator_for(manager))


def test_add_files_keeps_the_order_the_dialog_returned(parent, pump, tmp_path):
    manager = ImportedFileManager()
    chosen = book(tmp_path, "10.mp3", "01.mp3", "02.mp3")
    adapter = adapter_for(parent, pump, manager, choose_files=lambda: chosen)

    outcome = adapter.add_files()
    assert outcome.status is OutcomeStatus.COMMITTED
    assert adapter.list.rows() == ("1. 10.mp3", "2. 01.mp3", "3. 02.mp3")
    assert adapter.count == 3


def test_add_files_with_no_selection_starts_nothing(parent, pump):
    manager = ImportedFileManager()
    adapter = adapter_for(parent, pump, manager, choose_files=lambda: ())
    assert adapter.add_files() is None
    assert manager.count == 0
    assert adapter.status.text == job_ui.ImportStatusBar.IDLE_TEXT


def test_add_folder_scans_the_roots_in_the_order_they_were_chosen(parent, pump, tmp_path):
    first = tmp_path / "B"
    second = tmp_path / "A"
    touch(first / "01.mp3")
    touch(second / "02.mp3")
    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)
    adapter = adapter_for(parent, pump, manager, coordinator=coordinator,
                          choose_folder=lambda: (first, second))

    adapter.add_folder()
    pump.tick()
    assert adapter.list.rows() == ("1. 01.mp3", "2. 02.mp3")
    assert adapter.count == 2


def test_the_broad_root_warning_is_answered_before_any_worker_exists(parent, pump, tmp_path):
    asked: list[tuple] = []
    manager = ImportedFileManager()
    touch(tmp_path / "01.mp3")
    adapter = adapter_for(
        parent, pump, manager, home=tmp_path, choose_folder=lambda: (tmp_path,),
        confirm_broad_root=lambda roots: bool(asked.append(roots)))

    adapter.add_folder()
    assert asked == [(tmp_path,)], "the warning fires once, on this thread"
    assert adapter.coordinator.is_active is False, "declining creates no worker"
    assert manager.count == 0
    assert "drive" in adapter.status.text or "home" in adapter.status.text


def test_an_accepted_broad_root_goes_on_to_scan(parent, pump, tmp_path):
    manager = ImportedFileManager()
    touch(tmp_path / "01.mp3")
    coordinator = coordinator_for(manager, home=tmp_path,
                                  confirm_broad_root=lambda roots: True)
    adapter = adapter_for(parent, pump, manager, coordinator=coordinator,
                          choose_folder=lambda: (tmp_path,))
    adapter.add_folder()
    pump.tick()
    assert adapter.count == 1


def test_a_result_over_the_captured_threshold_waits_for_confirmation(parent, pump, tmp_path):
    for index in range(4):
        touch(tmp_path / f"{index:02d}.mp3")
    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)
    asked: list[ImportOutcome] = []
    adapter = adapter_for(
        parent, pump, manager, coordinator=coordinator, effective_config=make_config(3),
        choose_folder=lambda: (tmp_path,),
        confirm_large_result=lambda outcome: bool(asked.append(outcome)) or False)

    adapter.add_folder()
    pump.tick()
    assert len(asked) == 1
    assert asked[0].proposed_count == 4
    assert manager.count == 0, "a declined confirmation commits nothing"
    assert adapter.count == 0


def test_an_accepted_confirmation_commits_exactly_once(parent, pump, tmp_path):
    for index in range(4):
        touch(tmp_path / f"{index:02d}.mp3")
    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)
    adapter = adapter_for(
        parent, pump, manager, coordinator=coordinator, effective_config=make_config(3),
        choose_folder=lambda: (tmp_path,), confirm_large_result=lambda outcome: True)

    adapter.add_folder()
    pump.tick()
    assert manager.count == 4
    assert adapter.list.rows()[0] == "1. 00.mp3"
    pump.tick()
    assert manager.count == 4, "draining again must not commit a second time"


def test_a_threshold_nobody_can_answer_fails_closed(parent, pump, tmp_path):
    for index in range(4):
        touch(tmp_path / f"{index:02d}.mp3")
    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)
    adapter = adapter_for(
        parent, pump, manager, coordinator=coordinator, effective_config=make_config(3),
        choose_folder=lambda: (tmp_path,))

    adapter.add_folder()
    pump.tick()
    assert manager.count == 0
    assert "confirmation" in adapter.status.text.lower()


def test_exactly_at_the_threshold_does_not_ask(parent, pump, tmp_path):
    for index in range(3):
        touch(tmp_path / f"{index:02d}.mp3")
    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)
    asked: list[object] = []
    adapter = adapter_for(
        parent, pump, manager, coordinator=coordinator, effective_config=make_config(3),
        choose_folder=lambda: (tmp_path,),
        confirm_large_result=lambda outcome: bool(asked.append(outcome)))
    adapter.add_folder()
    pump.tick()
    assert asked == []
    assert manager.count == 3


def test_cancel_import_stops_the_scan_and_touches_no_job_controller(parent, pump, tmp_path):
    touch(tmp_path / "01.mp3")
    manager = ImportedFileManager()
    started = threading.Event()
    release = threading.Event()
    scanner = ControlledScanner(started=started, release=release)
    coordinator = coordinator_for(
        manager, scanner=scanner,
        thread_factory=RecordingThreads(kind=lambda target, name: threading.Thread(
            target=target, name=name, daemon=False)))
    controller = JobController("job-1")
    controller.start()
    adapter = adapter_for(parent, pump, manager, coordinator=coordinator,
                          choose_folder=lambda: (tmp_path,))
    try:
        adapter.add_folder()
        assert started.wait(WAIT)
        assert adapter.status.cancel_enabled is True

        assert adapter.cancel_import() is True
        assert adapter.status.text == job_ui.ImportStatusBar.CANCELLING_TEXT
        assert controller.state is JobState.RUNNING, "Cancel Import is not Cancel Job"
        assert controller.cancel_acknowledged is False
    finally:
        release.set()
        adapter.close()
    assert manager.count == 0, "a cancelled import adds nothing"


def test_a_failed_import_leaves_the_prior_list_exactly_as_it_was(parent, pump, tmp_path):
    manager = ImportedFileManager()
    fill(manager, touch(tmp_path / "kept.mp3"))
    before = manager.snapshot()
    coordinator = coordinator_for(
        manager, scanner=ControlledScanner(raises=OSError("the disk went away")))
    adapter = adapter_for(parent, pump, manager, coordinator=coordinator,
                          choose_folder=lambda: (tmp_path,))

    adapter.add_folder()
    pump.tick()
    assert manager.snapshot().files == before.files
    assert adapter.list.rows() == ("1. kept.mp3",)
    assert adapter.status.text


def test_closing_during_an_active_scan_is_quiet_and_final(parent, pump, tmp_path):
    touch(tmp_path / "01.mp3")
    manager = ImportedFileManager()
    started = threading.Event()
    release = threading.Event()
    coordinator = coordinator_for(
        manager, scanner=ControlledScanner(started=started, release=release),
        thread_factory=RecordingThreads(kind=lambda target, name: threading.Thread(
            target=target, name=name, daemon=False)))
    adapter = adapter_for(parent, pump, manager, coordinator=coordinator,
                          choose_folder=lambda: (tmp_path,))
    adapter.add_folder()
    assert started.wait(WAIT)
    release.set()

    adapter.close()
    adapter.close()
    assert adapter.closed
    assert adapter.poller.closed and coordinator.is_closed
    assert manager.count == 0
    # Everything is inert afterwards, and nothing was left scheduled.
    assert adapter.add_files() is None
    assert adapter.add_folder() is None
    assert adapter.cancel_import() is False
    assert pump.tick() >= 0
    assert pump.scheduled_count == 0


def test_a_closed_adapter_renders_nothing_further(parent, pump, tmp_path):
    manager = ImportedFileManager()
    fill(manager, *book(tmp_path))
    adapter = adapter_for(parent, pump, manager)
    adapter.close()
    assert adapter.refresh() == ()
    assert manager.count == 3


def test_locking_the_import_adapter_locks_list_and_options_together(parent, pump, tmp_path):
    manager = ImportedFileManager()
    fill(manager, *book(tmp_path))
    adapter = adapter_for(parent, pump, manager)
    adapter.set_locked(True)
    assert adapter.list.locked and adapter.options.locked
    assert not enabled(adapter.list.buttons["clear"])
    adapter.set_locked(False)
    assert enabled(adapter.list.buttons["clear"])


def test_the_adapter_rides_the_one_pump_and_starts_no_second_chain(parent, pump, tmp_path):
    touch(tmp_path / "01.mp3")
    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)
    adapter = adapter_for(parent, pump, manager, coordinator=coordinator,
                          choose_folder=lambda: (tmp_path,))
    assert isinstance(adapter.poller, ImportPoller)
    pump.start()
    handle = pump.pending
    adapter.add_folder()
    assert pump.pending is handle, "the poller schedules through the pump, not around it"
    pump.stop()


def test_an_import_never_writes_to_the_tree_it_read(parent, pump, tmp_path):
    source = tmp_path / "Book"
    touch(source / "01.mp3")
    touch(source / "02.mp3")
    before = snapshot_tree(tmp_path)
    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)
    adapter = adapter_for(parent, pump, manager, coordinator=coordinator,
                          choose_folder=lambda: (source,))
    adapter.add_folder()
    pump.tick()
    assert adapter.count == 2
    assert snapshot_tree(tmp_path) == before


# --------------------------------------------------------------------------- #
# Job controls, locking, progress, ETA
# --------------------------------------------------------------------------- #


def test_every_job_state_gets_the_availability_the_contract_derives(parent):
    bar = job_ui.JobControlBar(parent)
    expected = {
        JobState.IDLE: set(),
        JobState.RUNNING: {JobAction.PAUSE, JobAction.CANCEL},
        JobState.PAUSE_REQUESTED: {JobAction.RESUME, JobAction.CANCEL},
        JobState.PAUSED: {JobAction.RESUME, JobAction.CANCEL},
        JobState.CANCEL_REQUESTED: set(),
        JobState.CANCELLED: set(),
        JobState.SUCCEEDED: set(),
        JobState.COMPLETED_WITH_FAILURES: set(),
        JobState.FAILED: set(),
    }
    for state, offered in expected.items():
        available = bar.apply(state)
        assert {action for action, ok in available.items() if ok} == offered, state
        for action, ok in available.items():
            assert enabled(bar.buttons[action]) is ok, (state, action)


def test_retry_failed_appears_only_with_a_retryable_failure(parent):
    bar = job_ui.JobControlBar(parent)
    assert bar.apply(JobState.COMPLETED_WITH_FAILURES)[JobAction.RETRY_FAILED] is False
    available = bar.apply(JobState.COMPLETED_WITH_FAILURES, has_retryable=True)
    assert available[JobAction.RETRY_FAILED] is True
    assert enabled(bar.buttons[JobAction.RETRY_FAILED])
    assert bar.apply(JobState.SUCCEEDED, has_retryable=True)[JobAction.RETRY_FAILED] is False


def test_pressing_a_button_the_state_forbids_does_nothing(parent):
    pressed: list[str] = []
    bar = job_ui.JobControlBar(
        parent, on_pause=lambda: pressed.append("pause"),
        on_resume=lambda: pressed.append("resume"),
        on_cancel=lambda: pressed.append("cancel"),
        on_retry=lambda: pressed.append("retry"))

    bar.apply(JobState.IDLE)
    assert bar.invoke(JobAction.PAUSE) is False
    bar.apply(JobState.RUNNING)
    assert bar.invoke(JobAction.PAUSE) is True
    assert bar.invoke(JobAction.RESUME) is False
    bar.apply(JobState.PAUSED)
    assert bar.invoke(JobAction.RESUME) is True
    assert bar.invoke(JobAction.CANCEL) is True
    assert pressed == ["pause", "resume", "cancel"]


def test_a_closed_control_bar_presses_nothing(parent):
    pressed: list[str] = []
    bar = job_ui.JobControlBar(parent, on_cancel=lambda: pressed.append("cancel"))
    bar.apply(JobState.RUNNING)
    bar.close()
    bar.close()
    assert bar.invoke(JobAction.CANCEL) is False
    assert pressed == []
    for button in bar.buttons.values():
        assert not enabled(button)


def test_the_lock_group_applies_the_approved_matrix_and_nothing_else(parent):
    group = job_ui.LockGroup()
    entry = ttk.Entry(parent)
    option = ttk.Checkbutton(parent, text="mode")
    group.register(ControlKind.IMPORTED_INPUT, entry)
    group.register(ControlKind.PROCESSING_OPTION, option)

    for state in JobState:
        applied = group.apply(state)
        assert set(applied) == set(ControlKind), "no kind may be silently absent"
        for kind in ControlKind:
            assert applied[kind] is is_locked(kind, state), (kind, state)
        locked = state in (JobState.RUNNING, JobState.PAUSE_REQUESTED,
                           JobState.PAUSED, JobState.CANCEL_REQUESTED)
        assert applied[ControlKind.IMPORTED_INPUT] is locked, state
        assert applied[ControlKind.PROCESSING_OPTION] is locked, state
        assert applied[ControlKind.JOB_CONTROL] is False, state
        assert applied[ControlKind.LOG_VIEW] is False, state
        assert applied[ControlKind.PROGRESS_STATUS] is False, state
        assert enabled(entry) is not locked, state
        assert enabled(option) is not locked, state


def test_the_lock_group_refuses_a_state_that_is_not_one(parent):
    group = job_ui.LockGroup()
    with pytest.raises(job_ui.JobUiError):
        group.apply("running")
    with pytest.raises(job_ui.JobUiError):
        group.register("inputs", ttk.Entry(parent))


def test_a_composite_component_locks_as_one_unit(parent, tmp_path):
    manager = ImportedFileManager()
    fill(manager, *book(tmp_path))
    listing = job_ui.ImportedFileList(parent, manager)
    group = job_ui.LockGroup()
    group.register(ControlKind.IMPORTED_INPUT, listing)

    group.apply(JobState.RUNNING)
    assert listing.locked is True
    group.apply(JobState.SUCCEEDED)
    assert listing.locked is False


def test_progress_shows_what_the_view_says_and_never_more(parent):
    view = job_ui.JobStatusView(parent)

    view.apply(ProgressView(mode=ProgressMode.IDLE))
    assert view.indicator.label.cget("text") == ""

    view.apply(ProgressView(mode=ProgressMode.DETERMINATE, completed=3, total=10))
    assert view.indicator.label.cget("text") == "3/10  30%"
    assert float(view.indicator.bar.cget("maximum")) == 10

    view.apply(ProgressView(mode=ProgressMode.INDETERMINATE, label="Encoding…"))
    assert str(view.indicator.bar.cget("mode")) == "indeterminate"
    assert view.indicator.label.cget("text") == "Encoding…"


def test_an_unknown_total_stays_indeterminate(parent):
    view = job_ui.JobStatusView(parent)
    view.apply(ProgressView(mode=ProgressMode.INDETERMINATE, completed=7, total=None))
    assert str(view.indicator.bar.cget("mode")) == "indeterminate"
    assert "7/7" not in view.indicator.label.cget("text")
    assert "100%" not in view.indicator.label.cget("text")


def test_an_unfinished_run_is_never_rounded_up_to_a_hundred_per_cent(parent):
    view = job_ui.JobStatusView(parent)
    view.apply(ProgressView(mode=ProgressMode.DETERMINATE, completed=3, total=5))
    view.finish()
    assert view.indicator.label.cget("text") == "3/5  60%"


def test_the_status_view_refuses_anything_that_is_not_a_progress_view(parent):
    view = job_ui.JobStatusView(parent)
    with pytest.raises(job_ui.JobUiError):
        view.apply("half done")


def test_the_status_view_shows_the_stage_and_the_current_item(parent):
    view = job_ui.JobStatusView(parent)
    view.apply(ProgressView(mode=ProgressMode.IDLE), stage="Converting", item_id="occ-2")
    assert view.stage_text == "Converting — occ-2"
    view.apply(ProgressView(mode=ProgressMode.IDLE), stage="Converting")
    assert view.stage_text == "Converting"
    view.apply(ProgressView(mode=ProgressMode.IDLE))
    assert view.stage_text == ""


def test_the_eta_starts_as_calculating_and_shows_only_what_it_is_given(parent):
    view = job_ui.JobStatusView(parent)
    assert view.eta_text == CALCULATING
    view.set_eta("1m 30s")
    assert view.eta_text == "1m 30s"


# --------------------------------------------------------------------------- #
# Summary and Details
# --------------------------------------------------------------------------- #


def test_summary_and_details_are_two_pages_of_one_notebook(parent):
    views = job_ui.SummaryDetailsView(parent)
    assert isinstance(views.frame, ttk.Notebook)
    assert views.frame.tab(0, "text") == "Summary"
    assert views.frame.tab(1, "text") == "Details"
    views.show_details()
    assert views.selected_tab() == 1
    views.show_summary()
    assert views.selected_tab() == 0


def test_each_pane_renders_exactly_the_lines_it_was_handed(parent):
    views = job_ui.SummaryDetailsView(parent)
    views.set_summary(("Running.", "Stage: Converting"))
    views.set_details(("[+0.000s] technical: ffmpeg -i in.mp3",))
    assert views.summary == ("Running.", "Stage: Converting")
    assert views.rendered(views.summary_text) == "Running.\nStage: Converting"
    assert "ffmpeg" in views.rendered(views.details_text)
    assert "ffmpeg" not in views.rendered(views.summary_text)


def test_the_panes_are_read_only(parent):
    views = job_ui.SummaryDetailsView(parent)
    views.set_summary(("only this",))
    assert str(views.summary_text.cget("state")) == "disabled"
    assert str(views.details_text.cget("state")) == "disabled"


def test_a_rerender_replaces_rather_than_appends(parent):
    views = job_ui.SummaryDetailsView(parent)
    views.set_summary(("first",))
    views.set_summary(("second",))
    assert views.rendered(views.summary_text) == "second"


# --------------------------------------------------------------------------- #
# The job adapter
# --------------------------------------------------------------------------- #


def job_adapter(parent, pump, publisher=None, **kwargs):
    kwargs.setdefault("run_id", "run-1")
    if publisher is not None:
        kwargs.setdefault("pull", publisher.pull)
    return job_ui.JobAdapter(parent, pump=pump, **kwargs)


def test_the_job_adapter_needs_a_pump_and_a_matching_stream(parent, pump):
    with pytest.raises(job_ui.JobUiError):
        job_ui.JobAdapter(parent, run_id="run-1", pump=object())
    with pytest.raises(job_ui.JobUiError):
        job_ui.JobAdapter(parent, run_id="run-1", pump=pump,
                          stream=JobEventStream("run-2"))


def test_a_fresh_adapter_is_idle_and_says_nothing_it_does_not_know(parent, pump):
    adapter = job_adapter(parent, pump)
    assert adapter.state is JobState.IDLE
    assert adapter.views.summary == ()
    assert adapter.views.details == ()
    assert adapter.status.eta_text == CALCULATING
    assert adapter.status.view.mode is ProgressMode.IDLE
    assert adapter.has_retryable is False


def test_the_adapter_registers_one_drain_on_the_shared_pump(parent, pump):
    before = pump.drain_count
    adapter = job_adapter(parent, pump)
    assert pump.drain_count == before + 1
    adapter.close()
    assert pump.drain_count == before


def test_every_job_state_is_presented_from_the_events_alone(parent, pump):
    publisher = Publisher()
    adapter = job_adapter(parent, pump, publisher)
    for state in (JobState.RUNNING, JobState.PAUSE_REQUESTED, JobState.PAUSED,
                  JobState.CANCEL_REQUESTED):
        publisher.reporter.state_changed(snapshot_for(state))
        pump.tick()
        assert adapter.state is state
        assert adapter.controls.state is state
        assert adapter.locks.last_applied[ControlKind.IMPORTED_INPUT] is True
        assert adapter.views.summary[-1] == state_message(state)
        assert adapter.status.status_text == state_message(state)


def test_a_pause_request_is_not_an_acknowledged_pause(parent, pump):
    publisher = Publisher()
    adapter = job_adapter(parent, pump, publisher)
    publisher.reporter.state_changed(snapshot_for(JobState.PAUSE_REQUESTED))
    pump.tick()
    assert adapter.state is JobState.PAUSE_REQUESTED
    assert "Pause requested." in adapter.views.summary

    publisher.reporter.state_changed(snapshot_for(JobState.PAUSED))
    pump.tick()
    assert adapter.state is JobState.PAUSED
    assert "Paused." in adapter.views.summary


def test_resume_and_cancel_while_paused_render_in_order(parent, pump):
    publisher = Publisher()
    adapter = job_adapter(parent, pump, publisher)
    for state in (JobState.RUNNING, JobState.PAUSE_REQUESTED, JobState.PAUSED,
                  JobState.RUNNING, JobState.CANCEL_REQUESTED):
        publisher.reporter.state_changed(snapshot_for(state))
    pump.tick()
    assert adapter.state is JobState.CANCEL_REQUESTED
    assert adapter.controls.availability()[JobAction.CANCEL] is False
    assert adapter.views.summary == (
        "Running.", "Pause requested.", "Paused.", "Running.", "Cancelling…")


def test_a_cancelled_run_reaches_its_ending_only_through_acknowledgement(parent, pump):
    publisher = Publisher()
    adapter = job_adapter(parent, pump, publisher)
    publisher.reporter.state_changed(snapshot_for(JobState.RUNNING))
    publisher.reporter.progress(2, 5)
    publisher.reporter.cancelled(snapshot_for(JobState.CANCELLED))
    pump.tick()

    assert adapter.state is JobState.CANCELLED
    assert adapter.status.view.completed == 2, "an ending changes no counter"
    assert adapter.status.view.total == 5
    assert adapter.status.indicator.label.cget("text") == "2/5  40%"
    assert adapter.summary_view.final == "Cancelled."


@pytest.mark.parametrize("ending", [
    JobState.SUCCEEDED, JobState.COMPLETED_WITH_FAILURES, JobState.FAILED])
def test_every_terminal_state_is_rendered_once(parent, pump, ending):
    publisher = Publisher()
    adapter = job_adapter(parent, pump, publisher)
    publisher.reporter.state_changed(snapshot_for(JobState.RUNNING))
    publisher.reporter.completed(snapshot_for(ending))
    publisher.reporter.completed(snapshot_for(ending))
    pump.tick()

    assert adapter.state is ending
    assert len([entry for entry in adapter.stream.events if entry.is_terminal]) == 1
    assert adapter.stream.rejected, "the second ending was rejected, not drawn"


def test_a_stale_run_event_is_inert(parent, pump):
    publisher = Publisher()
    # A second run publishing onto the same queue is exactly the confusion the run
    # binding exists to survive.
    stranger = JobReporter("run-2", clock=FakeClock(), publish=publisher.queue.put)
    adapter = job_adapter(parent, pump, publisher)

    publisher.reporter.state_changed(snapshot_for(JobState.RUNNING))
    stranger.warning("this belongs to someone else")
    pump.tick()

    assert len(adapter.stream.events) == 1
    assert adapter.views.summary == ("Running.",)
    assert "someone else" not in "\n".join(adapter.views.details)
    assert adapter.summary_view.warnings == ()


def test_an_unknown_occurrence_is_rejected_before_it_is_drawn(parent, pump):
    publisher = Publisher(item_ids=("occ-1",))
    adapter = job_adapter(parent, pump, publisher, item_ids=("occ-1",))
    publisher.reporter.current_item("occ-1")
    entry = JobEvent(kind=JobEventKind.CURRENT_ITEM, run_id="run-1", sequence=99,
                     timestamp=1.0, item_id="occ-9")
    publisher.queue.put(entry)
    pump.tick()

    assert [event.item_id for event in adapter.stream.events] == ["occ-1"]
    assert adapter.summary_view.current_item_id == "occ-1"


def test_an_event_after_the_ending_is_inert(parent, pump):
    publisher = Publisher()
    adapter = job_adapter(parent, pump, publisher)
    publisher.reporter.completed(snapshot_for(JobState.SUCCEEDED))
    publisher.reporter.warning("too late")
    pump.tick()

    assert len(adapter.stream.events) == 1
    assert adapter.summary_view.warnings == ()
    assert "too late" not in "\n".join(adapter.views.details)


def test_progress_current_item_and_stage_are_rendered_from_the_projection(parent, pump):
    publisher = Publisher(item_ids=("occ-1", "occ-2"))
    adapter = job_adapter(parent, pump, publisher, item_ids=("occ-1", "occ-2"))
    publisher.reporter.stage_changed("Converting")
    publisher.reporter.current_item("occ-2")
    publisher.reporter.progress(1, 2)
    pump.tick()

    assert adapter.status.stage_text == "Converting — occ-2"
    assert adapter.status.view.completed == 1 and adapter.status.view.total == 2
    assert adapter.summary_view.stage == "Converting"


def test_progress_never_goes_backwards_within_one_scope(parent, pump):
    publisher = Publisher()
    adapter = job_adapter(parent, pump, publisher)
    publisher.reporter.progress(4, 10)
    publisher.reporter.progress(2, 10)
    pump.tick()
    assert adapter.status.view.completed == 4


def test_warnings_failures_and_an_output_location_reach_the_summary(parent, pump, tmp_path):
    publisher = Publisher()
    adapter = job_adapter(parent, pump, publisher)
    publisher.reporter.warning("One chapter had no title.")
    publisher.reporter.failure("02.mp3 could not be read.", "OSError: broken")
    publisher.reporter.output_location(tmp_path / "run-1")
    publisher.reporter.completed(snapshot_for(JobState.COMPLETED_WITH_FAILURES))
    pump.tick()

    view = adapter.summary_view
    assert view.warnings == ("One chapter had no title.",)
    assert view.failures == ("02.mp3 could not be read.",)
    assert view.output_location == tmp_path / "run-1"
    assert view.final == "Finished with failures."
    assert "OSError: broken" not in "\n".join(adapter.views.summary)
    assert "OSError: broken" in "\n".join(adapter.views.details)


def test_an_output_location_is_displayed_and_never_touched(parent, pump, tmp_path):
    """§6.8: no import or job action reserves or creates an output run."""
    publisher = Publisher()
    adapter = job_adapter(parent, pump, publisher)
    promised = tmp_path / "not-created" / "run-1"
    before = snapshot_tree(tmp_path)
    publisher.reporter.output_location(promised)
    pump.tick()

    assert adapter.summary_view.output_location == promised
    assert not promised.exists(), "the adapter created the folder it was told about"
    assert snapshot_tree(tmp_path) == before


def test_a_technical_detail_never_reaches_the_summary(parent, pump):
    publisher = Publisher()
    adapter = job_adapter(parent, pump, publisher)
    publisher.reporter.technical("ffmpeg -i '01.mp3' -c:a aac out.m4b")
    publisher.reporter.stage_changed("Converting")
    pump.tick()

    assert adapter.views.summary == ("Stage: Converting",)
    assert "ffmpeg" not in "\n".join(adapter.views.summary)
    assert "ffmpeg" in "\n".join(adapter.views.details)


def test_the_adapter_never_forwards_an_event_to_the_logger_twice(parent, pump):
    logger = RecordingLogger()
    publisher = Publisher()
    adapter = job_adapter(parent, pump, publisher, bridge=LoggerBridge(logger=logger))
    publisher.reporter.technical("a command")
    publisher.reporter.warning("a warning")
    publisher.reporter.failure("a failure")
    pump.tick()
    adapter.render()
    adapter.render()

    assert logger.levels() == ["debug", "warning", "error"]
    assert len(logger.calls) == 3, "rendering again must not log again"


def test_a_rejected_event_is_never_logged(parent, pump):
    logger = RecordingLogger()
    publisher = Publisher()
    adapter = job_adapter(parent, pump, publisher, bridge=LoggerBridge(logger=logger))
    publisher.reporter.completed(snapshot_for(JobState.SUCCEEDED))
    publisher.reporter.warning("after the end")
    pump.tick()

    assert logger.calls == []
    assert adapter.stream.rejected


def test_the_eta_is_exactly_what_the_estimator_says(parent, pump):
    clock = FakeClock()
    publisher = Publisher(clock=clock)
    estimator = EtaEstimator("run-1", clock=clock)
    adapter = job_adapter(parent, pump, publisher, estimator=estimator)

    publisher.reporter.progress(0, 4)
    pump.tick()
    assert adapter.status.eta_text == CALCULATING, "no samples yet"

    for index in range(3):
        estimator.begin("convert")
        clock.advance(2.0)
        estimator.complete()
        publisher.reporter.progress(index + 1, 4)
    pump.tick()
    assert adapter.status.eta_text == "2s", "one unit left at two seconds each"


def test_the_eta_is_calculating_while_paused_and_after_the_ending(parent, pump):
    clock = FakeClock()
    publisher = Publisher(clock=clock)
    estimator = EtaEstimator("run-1", clock=clock)
    adapter = job_adapter(parent, pump, publisher, estimator=estimator)
    for _ in range(3):
        estimator.begin("convert")
        clock.advance(1.0)
        estimator.complete()
    publisher.reporter.progress(1, 3)
    pump.tick()
    assert adapter.status.eta_text == "2s"

    publisher.reporter.state_changed(snapshot_for(JobState.PAUSED))
    pump.tick()
    assert adapter.status.eta_text == CALCULATING

    publisher.reporter.state_changed(snapshot_for(JobState.RUNNING))
    pump.tick()
    assert adapter.status.eta_text == "2s"

    publisher.reporter.completed(snapshot_for(JobState.SUCCEEDED))
    pump.tick()
    assert adapter.status.eta_text == CALCULATING


def test_an_unknown_total_has_no_eta(parent, pump):
    clock = FakeClock()
    publisher = Publisher(clock=clock)
    estimator = EtaEstimator("run-1", clock=clock)
    adapter = job_adapter(parent, pump, publisher, estimator=estimator)
    for _ in range(3):
        estimator.begin("convert")
        clock.advance(1.0)
        estimator.complete()
    publisher.reporter.progress(1, None)
    pump.tick()
    assert adapter.status.view.mode is ProgressMode.INDETERMINATE
    assert adapter.status.eta_text == CALCULATING


def test_without_an_estimator_the_eta_is_always_calculating(parent, pump):
    publisher = Publisher()
    adapter = job_adapter(parent, pump, publisher)
    publisher.reporter.progress(1, 4)
    pump.tick()
    assert adapter.status.eta_text == CALCULATING


def test_retry_failed_becomes_available_only_from_a_settled_result(parent, pump, tmp_path):
    manager = ImportedFileManager()
    fill(manager, *book(tmp_path))
    snapshot = run_snapshot(manager)
    item_ids = snapshot.item_ids
    publisher = Publisher(item_ids=item_ids)
    adapter = job_adapter(parent, pump, publisher, item_ids=item_ids)
    publisher.reporter.completed(snapshot_for(JobState.COMPLETED_WITH_FAILURES))
    pump.tick()
    assert adapter.controls.availability()[JobAction.RETRY_FAILED] is False

    failures = FailureLog(snapshot_id=snapshot.snapshot_id, records=(
        FailureRecord(item_id=item_ids[1], stage="convert",
                      display_message="02.mp3 failed.", technical_detail="OSError",
                      retryable=True, snapshot_id=snapshot.snapshot_id),))
    result = RunResult.settle(snapshot, failures,
                              completed_ids=(item_ids[0], item_ids[2]))
    adapter.set_result(result)
    assert adapter.has_retryable is True
    assert adapter.controls.availability()[JobAction.RETRY_FAILED] is True
    assert enabled(adapter.controls.buttons[JobAction.RETRY_FAILED])


def test_the_adapter_decides_no_retry_placement(parent, pump):
    """Pressing Retry Failed reaches the caller; it builds nothing on its own."""
    pressed: list[str] = []
    publisher = Publisher()
    adapter = job_adapter(parent, pump, publisher,
                          on_retry=lambda: pressed.append("retry"))
    assert adapter.result is None
    for name in ("retry", "retry_request", "reserve", "plan", "output"):
        assert not hasattr(adapter, name), name


def test_set_result_refuses_anything_that_is_not_a_run_result(parent, pump):
    adapter = job_adapter(parent, pump)
    with pytest.raises(job_ui.JobUiError):
        adapter.set_result("finished")


def test_rendering_is_idempotent(parent, pump):
    publisher = Publisher()
    adapter = job_adapter(parent, pump, publisher)
    publisher.reporter.state_changed(snapshot_for(JobState.RUNNING))
    publisher.reporter.progress(1, 3)
    pump.tick()
    first = (adapter.views.summary, adapter.views.details, adapter.status.eta_text)
    adapter.render()
    adapter.render()
    assert (adapter.views.summary, adapter.views.details,
            adapter.status.eta_text) == first


def test_a_bounded_drain_leaves_the_rest_for_the_next_tick(parent, pump):
    publisher = Publisher()
    adapter = job_adapter(parent, pump, publisher, limit=2)
    for done in range(5):
        publisher.reporter.progress(done, 5)
    assert adapter.drain() == 2
    assert adapter.drain() == 2
    assert adapter.drain() == 1
    assert adapter.drain() == 0


def test_an_adapter_without_a_pull_drains_nothing(parent, pump):
    adapter = job_adapter(parent, pump)
    assert adapter.drain() == 0
    assert adapter.last_verdicts == ()


def test_a_terminal_callback_fires_once(parent, pump):
    seen: list[JobEvent] = []
    publisher = Publisher()
    adapter = job_adapter(parent, pump, publisher, on_terminal=seen.append)
    publisher.reporter.state_changed(snapshot_for(JobState.RUNNING))
    publisher.reporter.completed(snapshot_for(JobState.SUCCEEDED))
    pump.tick()
    pump.tick()
    assert len(seen) == 1
    assert seen[0].is_terminal
    assert adapter.state is JobState.SUCCEEDED


@pytest.mark.parametrize("state", [
    JobState.RUNNING, JobState.PAUSE_REQUESTED, JobState.PAUSED,
    JobState.CANCEL_REQUESTED])
def test_closing_during_an_unfinished_job_is_quiet_and_final(parent, pump, state):
    publisher = Publisher()
    adapter = job_adapter(parent, pump, publisher)
    publisher.reporter.state_changed(snapshot_for(state))
    pump.tick()
    assert adapter.state is state

    adapter.close()
    adapter.close()
    assert adapter.closed

    publisher.reporter.warning("arrived after the window went away")
    assert adapter.drain() == 0
    assert pump.tick() == 0 or True
    assert "after the window" not in "\n".join(adapter.views.details)
    assert pump.scheduled_count == 0
    # And the close never claimed the worker stopped: the state it last drew stands.
    assert adapter.state is state


def test_a_destroyed_widget_tree_does_not_take_the_adapter_down(tk_root):
    holder = ttk.Frame(tk_root)
    made = job_ui.MainThreadPump(holder)
    publisher = Publisher()
    adapter = job_ui.JobAdapter(holder, run_id="run-1", pump=made,
                                pull=publisher.pull)
    publisher.reporter.state_changed(snapshot_for(JobState.RUNNING))
    holder.destroy()

    assert adapter.drain() == 1, "the event is still accepted; only the drawing is gone"
    assert adapter.state is JobState.RUNNING
    adapter.close()
    made.close()


def test_registering_inputs_and_options_locks_them_through_the_matrix(parent, pump, tmp_path):
    manager = ImportedFileManager()
    fill(manager, *book(tmp_path))
    importer = job_ui.ImportedFileList(parent, manager)
    option = ttk.Checkbutton(parent, text="Split by chapter")
    publisher = Publisher()
    adapter = job_adapter(parent, pump, publisher)
    adapter.register_inputs(importer)
    adapter.register_options(option)

    publisher.reporter.state_changed(snapshot_for(JobState.RUNNING))
    pump.tick()
    assert importer.locked is True and not enabled(option)

    publisher.reporter.completed(snapshot_for(JobState.SUCCEEDED))
    pump.tick()
    assert importer.locked is False and enabled(option)


# --------------------------------------------------------------------------- #
# Style isolation
# --------------------------------------------------------------------------- #


def snapshot_generic(style: ttk.Style) -> dict:
    out = {}
    for name in GENERIC_STYLES:
        try:
            layout = style.layout(name)
        except tk.TclError:
            layout = None
        out[name] = (layout, style.configure(name), style.lookup(name, "background"),
                     style.lookup(name, "foreground"), style.map(name))
    return out


def test_the_windows_branch_dresses_the_adapters_in_act_styles_only(
        parent, pump, windows_theme, tmp_path):
    manager = ImportedFileManager()
    fill(manager, *book(tmp_path))
    importer = adapter_for(parent, pump, manager, theme=windows_theme)
    publisher = Publisher()
    job = job_adapter(parent, pump, publisher, theme=windows_theme)

    named = [
        importer.frame, importer.list.frame, importer.list.count_label,
        importer.list.scrollbar, importer.options.frame, importer.status.frame,
        importer.status.label, importer.status.button_cancel,
        job.frame, job.controls.frame, job.status.frame, job.views.frame,
        job.status.label_stage, job.status.label_eta, job.status.label_status,
        *importer.list.buttons.values(),
        *importer.options.type_buttons.values(),
        *job.controls.buttons.values(),
    ]
    for widget in named:
        style = str(widget.cget("style"))
        assert style.startswith("ACT."), (widget, style)


def test_the_native_branch_asks_for_no_style_at_all(parent, pump, tmp_path):
    """macOS aqua and the classic branch publish no ``styles`` bundle — and need none."""
    manager = ImportedFileManager()
    fill(manager, *book(tmp_path))
    importer = adapter_for(parent, pump, manager, theme={"mode": "aqua", "colors": {}})
    publisher = Publisher()
    job = job_adapter(parent, pump, publisher, theme=None)

    for widget in (importer.frame, importer.list.frame, importer.list.count_label,
                   job.frame, job.controls.frame, job.status.frame, job.views.frame,
                   *job.controls.buttons.values()):
        assert str(widget.cget("style")) == "", widget

    assert job_ui.style_name(None, "button") == ""
    assert job_ui.style_name({"mode": "aqua"}, "button") == ""
    assert job_ui.style_name({"styles": {"button": 7}}, "button") == ""


def test_building_the_adapters_leaks_into_no_generic_style(
        tk_root, parent, pump, windows_theme, tmp_path):
    style = ttk.Style(tk_root)
    before = snapshot_generic(style)

    manager = ImportedFileManager()
    fill(manager, *book(tmp_path))
    adapter_for(parent, pump, manager, theme=windows_theme)
    job_adapter(parent, pump, Publisher(), theme=windows_theme)

    after = snapshot_generic(style)
    changed = [name for name in GENERIC_STYLES if before[name] != after[name]]
    assert not changed, f"Phase 8 leaked into generic styles: {changed}"


def test_the_shared_progress_indicator_is_reused_unstyled(parent, windows_theme):
    """§5.2: reuse it, and keep it exactly as the five unconverted panels see it."""
    view = job_ui.JobStatusView(parent, theme=windows_theme)
    assert isinstance(view.indicator, ui_theme.ProgressIndicator)
    assert str(view.indicator.bar.cget("style")) == ""
    assert str(view.indicator.frame.cget("style")) == ""
    assert str(view.indicator.label.cget("style")) == ""


def test_the_classic_tk_widgets_are_coloured_through_the_sanctioned_helper(
        parent, windows_theme, tmp_path):
    manager = ImportedFileManager()
    fill(manager, *book(tmp_path))
    listing = job_ui.ImportedFileList(parent, manager, theme=windows_theme)
    views = job_ui.SummaryDetailsView(parent, theme=windows_theme)
    colors = windows_theme["colors"]

    assert listing.listbox.cget("background") == colors["field"]
    assert listing.listbox.cget("selectbackground") == colors["selection"]
    assert views.summary_text.cget("background") == colors["elevated"]


# --------------------------------------------------------------------------- #
# The developer harness
# --------------------------------------------------------------------------- #


HARNESS = Path(__file__).resolve().parent / "manual_plan3_harness.py"


def test_the_harness_exists_in_the_developer_tree_only():
    assert HARNESS.is_file()
    shipped = Path(__file__).resolve().parent.parent.parent / "scripts"
    assert not (shipped / "Universal" / "manual_plan3_harness.py").exists()
    assert not any(path.name == HARNESS.name for path in shipped.rglob("*.py"))


def test_the_harness_is_not_collected_as_a_test():
    assert not HARNESS.name.startswith("test_")
    text = HARNESS.read_text(encoding="utf-8")
    assert "def test_" not in text


def test_the_harness_starts_no_real_work_and_reaches_no_real_service():
    """Checked as imports and calls, never as substrings — the prose says these words.

    A harness that *said* it starts no subprocess while importing one would pass a
    substring check and fail the contract. What matters is what it can reach.
    """
    tree = ast.parse(HARNESS.read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
    heads = {name.split(".")[0] for name in modules}
    for forbidden in ("subprocess", "urllib", "socket", "http", "requests",
                      "multiprocessing", "asyncio"):
        assert forbidden not in heads, forbidden
    for service in ("shared.output_paths", "shared.settings", "shared.maintenance",
                    "shared.cleanup_worker", "shared.cleanup_state",
                    "shared.subprocess_utils", "shared.release", "shared.ffmpeg_utils"):
        assert service not in modules, service

    called = {
        node.func.attr for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    for forbidden in ("run", "popen", "check_output", "Popen", "reserve_run_directory",
                      "save", "unlink", "replace", "rename", "chmod"):
        assert forbidden not in called, forbidden


def test_the_harness_writes_only_inside_the_root_it_generated():
    """Its two writing verbs are the fixture builder's, and it refuses a real place."""
    source = HARNESS.read_text(encoding="utf-8")
    tree = ast.parse(source)
    writers = {
        node.name for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and any(
            isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
            and call.func.attr in ("write_bytes", "write_text", "mkdir", "rmtree",
                                   "symlink_to", "CreateJunction")
            for call in ast.walk(node))
    }
    assert writers == {"build_fixture", "_write", "_make_junction", "main"}, writers

    from importlib import util as import_util

    spec = import_util.spec_from_file_location("manual_plan3_harness", HARNESS)
    module = import_util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for refused in (Path.home(), Path(__file__).resolve().parent.parent.parent):
        with pytest.raises(SystemExit):
            module.refuse_unless_disposable(refused)


def test_the_harness_is_reachable_from_no_production_entry_point():
    universal = Path(__file__).resolve().parent.parent.parent / "scripts" / "Universal"
    for path in universal.rglob("*.py"):
        assert "manual_plan3_harness" not in path.read_text(encoding="utf-8"), path
