"""Background import coordination — v0.6.0 Drop 3 (Plan 3), Phase 4.

Every tree here is built under ``tmp_path`` and thrown away. Nothing scans the
repository, the real home directory, Downloads, an output base, runtime data, real
media or a network share; nothing writes anywhere a scan can see; and nothing starts
ffmpeg, a TTS engine, an installer, a cleanup worker or a conversion.

**No test sleeps.** Races are *arranged*, not waited for: a scanner is parked on a
:class:`threading.Event` or a :class:`threading.Barrier` until the test has done the
thing it wants to interleave, and every wait carries a short timeout so a hang fails
loudly instead of hanging the suite. Where a race is not the point at all, the worker
runs inline on the calling thread through an injected thread factory, which makes the
event ordering exactly reproducible.

The single white-box reach in this file is ``coordinator._queue`` in the malformed-
payload tests. There is deliberately no public way to forge an illegal event, and
failing closed on one is a contract worth proving.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from shared import cancellation as processing_cancellation
from shared import import_coordination
from shared.import_coordination import (
    CloseReport,
    ImportCancellation,
    ImportCoordinationError,
    ImportCoordinator,
    ImportEvent,
    ImportEventKind,
    ImportOutcome,
    ImportPhase,
    ImportPoller,
    OutcomeStatus,
    StartOutcome,
    StartReport,
)
from shared.importing import (
    CommitResult,
    CommitStatus,
    IdFactory,
    ImportContractError,
    ImportedFileManager,
    ImportOptions,
    ImportProblem,
    ImportRoot,
    ProblemCategory,
    RootKind,
    ScanOutcome,
    ScanRequest,
    ScanResult,
    SupportedType,
    SupportedTypeCatalog,
    scan_roots,
    validate_direct_files,
)

from test_importing import make_config
from test_import_traversal import snapshot_tree, touch

#: Every wait in this file is bounded, so a deadlock fails the test rather than
#: stalling the run. It is never used to *create* a race.
WAIT = 5.0


# --------------------------------------------------------------------------- #
# Disposable fixtures
# --------------------------------------------------------------------------- #


def catalog() -> SupportedTypeCatalog:
    return SupportedTypeCatalog((
        SupportedType("mp3", "MP3 audio", (".mp3",)),
        SupportedType("m4b", "M4B audiobook", (".m4b",)),
    ))


def options(
    *, duplicates: bool = False, hidden: bool = False, selected=None) -> ImportOptions:
    if selected is None:
        return ImportOptions.for_catalog(
            catalog(), include_hidden_folders=hidden, allow_duplicate_files=duplicates)
    return ImportOptions(
        selected_type_ids=frozenset(selected),
        include_hidden_folders=hidden,
        allow_duplicate_files=duplicates,
    )


def folder_request(
    *roots: Path,
    threshold: int = 1000,
    duplicates: bool = False,
    hidden: bool = False,
    selected=None,
    request_id: str = "req-1",
) -> ScanRequest:
    return ScanRequest(
        request_id=request_id,
        roots=tuple(
            ImportRoot(f"root-{index}", path, index)
            for index, path in enumerate(roots)
        ),
        catalog=catalog(),
        options=options(duplicates=duplicates, hidden=hidden, selected=selected),
        effective_config=make_config(threshold),
        created_at=1.0,
    )


def direct_request(
    *,
    threshold: int = 1000,
    duplicates: bool = False,
    selected=None,
    request_id: str = "req-direct",
) -> ScanRequest:
    return ScanRequest(
        request_id=request_id,
        roots=(ImportRoot("picked", None, 0, RootKind.DIRECT_FILES),),
        catalog=catalog(),
        options=options(duplicates=duplicates, selected=selected),
        effective_config=make_config(threshold),
        created_at=1.0,
    )


def book(tmp_path: Path, name: str = "Book", *tracks: str) -> Path:
    """A small disposable folder of compatible files."""
    root = tmp_path / name
    for track in (tracks or ("01.mp3", "02.mp3", "10.mp3")):
        touch(root / track, track)
    return root


def cancelled_result(request: ScanRequest, discovered: int = 0) -> ScanResult:
    return ScanResult(
        request_id=request.request_id,
        outcome=ScanOutcome.CANCELLED,
        discovered_count=discovered,
        problems=(ImportProblem(
            category=ProblemCategory.CANCELLED,
            display_message="The import was cancelled and nothing was added.",
            technical_detail="cancellation acknowledged at a scan checkpoint",
        ),),
    )


def failed_result(request: ScanRequest) -> ScanResult:
    return ScanResult(
        request_id=request.request_id,
        outcome=ScanOutcome.FAILED,
        problems=(ImportProblem(
            category=ProblemCategory.UNREADABLE,
            display_message="The folder could not be read.",
            technical_detail="injected failure",
        ),),
    )


class InlineThread:
    """Runs the worker body on the caller's thread the moment ``start()`` is called.

    Nothing about the coordinator changes; the concurrency simply becomes
    deterministic, which is what most of these assertions actually care about. The
    tests that are *about* threading use real ones.
    """

    def __init__(self, target, name: str) -> None:
        self.target = target
        self.name = name
        self.starts = 0

    def start(self) -> None:
        self.starts += 1
        self.target()

    def is_alive(self) -> bool:
        return False

    def join(self, timeout: float | None = None) -> None:
        return None


class RecordingThreads:
    """A thread factory that keeps every body it was handed."""

    def __init__(self, kind=InlineThread) -> None:
        self.kind = kind
        self.made: list = []
        self.bodies: list = []

    def __call__(self, target, name):
        self.bodies.append(target)
        made = self.kind(target, name)
        self.made.append(made)
        return made

    def replay(self, index: int) -> None:
        """Re-run an earlier worker body, producing events for a finished operation."""
        self.bodies[index]()


class DoubleStartThread(InlineThread):
    """Publishes a whole worker lifetime twice, duplicating the terminal event."""

    def start(self) -> None:
        self.starts += 1
        self.target()
        self.target()


class RealThreads:
    """The real thing, joinable and non-daemon so leaks are impossible to miss."""

    def __init__(self) -> None:
        self.made: list[threading.Thread] = []

    def __call__(self, target, name):
        thread = threading.Thread(target=target, name=name, daemon=False)
        self.made.append(thread)
        return thread


class ControlledScanner:
    """A scanner with explicit gates instead of a duration.

    ``counts`` are reported through ``on_count`` before anything else; ``started`` is
    set once the scanner is running; ``release`` is waited on before the result is
    produced. Cancellation is honoured at each of those points, exactly as the real
    scanner honours it at its own checkpoints.
    """

    def __init__(
        self,
        *,
        counts=(),
        started: threading.Event | None = None,
        release: threading.Event | None = None,
        raises: BaseException | None = None,
        returns=None,
        delegate: bool = True,
    ) -> None:
        self.counts = tuple(counts)
        self.started = started
        self.release = release
        self.raises = raises
        self.returns = returns
        self.delegate = delegate
        self.calls = 0
        self.thread_idents: list[int] = []
        self.cancel_checks = 0

    def __call__(self, request, *, cancel_check, on_count, completed_at=0.0):
        self.calls += 1
        self.thread_idents.append(threading.get_ident())
        if self.started is not None:
            self.started.set()
        for count in self.counts:
            self.cancel_checks += 1
            if cancel_check():
                return cancelled_result(request, count)
            on_count(count)
        if self.release is not None:
            assert self.release.wait(WAIT), "the test never released the scanner"
        self.cancel_checks += 1
        if cancel_check():
            return cancelled_result(request, self.counts[-1] if self.counts else 0)
        if self.raises is not None:
            raise self.raises
        if self.returns is not None:
            return self.returns(request) if callable(self.returns) else self.returns
        if self.delegate:
            return scan_roots(request, completed_at=completed_at)
        raise AssertionError("nothing to return")  # pragma: no cover


class AlwaysStaleManager(ImportedFileManager):
    """A manager whose revision is always already behind. Nothing can be appended."""

    __slots__ = ("attempts",)

    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0

    def commit(self, transaction) -> CommitResult:
        self.attempts += 1
        return CommitResult(
            transaction_id=transaction.transaction_id,
            status=CommitStatus.STALE_REVISION,
            snapshot=self.snapshot(),
            expected_revision=transaction.expected_revision,
        )


class FakeScheduler:
    """``root.after`` without Tk: callbacks are queued and fired by the test."""

    def __init__(self) -> None:
        self.queued: list = []
        self.cancelled: list = []
        self.handles = 0

    def __call__(self, delay_ms: int, callback):
        self.handles += 1
        handle = f"after-{self.handles}"
        self.queued.append((handle, delay_ms, callback))
        return handle

    def cancel(self, handle) -> None:
        self.cancelled.append(handle)
        self.queued = [entry for entry in self.queued if entry[0] != handle]

    @property
    def pending(self) -> int:
        return len(self.queued)

    def run_next(self):
        handle, _delay, callback = self.queued.pop(0)
        return callback()


def coordinator_for(
    manager: ImportedFileManager | None = None, **kwargs) -> ImportCoordinator:
    """A coordinator with deterministic identifiers and no discovered home."""
    kwargs.setdefault("id_factory", IdFactory("c-"))
    kwargs.setdefault("home", None)
    kwargs.setdefault("thread_factory", RecordingThreads())
    return ImportCoordinator(
        ImportedFileManager() if manager is None else manager, **kwargs)


def run_to_completion(coordinator: ImportCoordinator, request: ScanRequest) -> ImportOutcome:
    """Start an inline import and drain it. One call, one deterministic outcome."""
    report = coordinator.start(request)
    assert report.started, report
    return coordinator.pump()


def names_in(manager: ImportedFileManager) -> list[str]:
    return [entry.path.name for entry in manager.snapshot().files]


# --------------------------------------------------------------------------- #
# The queue vocabulary
# --------------------------------------------------------------------------- #


def test_an_event_is_frozen_and_hashable_enough_to_share():
    event = ImportEvent(operation_id="op-1", kind=ImportEventKind.STARTED, at=2.0)
    with pytest.raises(Exception):
        event.kind = ImportEventKind.FAILED
    assert event.is_terminal is False


def test_a_started_event_may_not_carry_a_result(tmp_path):
    request = folder_request(book(tmp_path))
    result = scan_roots(request)
    with pytest.raises(ImportCoordinationError, match="reports no result"):
        ImportEvent(operation_id="op-1", kind=ImportEventKind.STARTED, result=result)


def test_a_completed_event_must_carry_the_result_it_completed_with():
    with pytest.raises(ImportCoordinationError, match="must carry the result"):
        ImportEvent(operation_id="op-1", kind=ImportEventKind.COMPLETED)


def test_a_completed_event_may_not_carry_a_cancelled_result(tmp_path):
    request = folder_request(book(tmp_path))
    with pytest.raises(ImportCoordinationError, match="may only carry a completed result"):
        ImportEvent(
            operation_id="op-1",
            kind=ImportEventKind.COMPLETED,
            result=cancelled_result(request),
        )


def test_a_cancelled_event_may_carry_a_cancelled_result_or_none(tmp_path):
    request = folder_request(book(tmp_path))
    assert ImportEvent(operation_id="op-1", kind=ImportEventKind.CANCELLED).result is None
    carried = ImportEvent(
        operation_id="op-1",
        kind=ImportEventKind.CANCELLED,
        result=cancelled_result(request),
    )
    assert carried.result.outcome is ScanOutcome.CANCELLED


def test_a_discovered_event_reports_a_real_count():
    with pytest.raises(ImportCoordinationError, match="nothing found is not progress"):
        ImportEvent(
            operation_id="op-1", kind=ImportEventKind.DISCOVERED, discovered_count=0)


def test_a_failed_event_must_say_why():
    with pytest.raises(ImportCoordinationError, match="must say why"):
        ImportEvent(
            operation_id="op-1",
            kind=ImportEventKind.FAILED,
            display_message="The import could not be completed.",
        )


def test_an_event_message_stays_a_single_line_and_carries_no_traceback():
    with pytest.raises(ImportContractError, match="single line"):
        ImportEvent(
            operation_id="op-1",
            kind=ImportEventKind.FAILED,
            display_message="broke\nbadly",
            technical_detail="x",
        )
    with pytest.raises(ImportContractError, match="raw traceback"):
        ImportEvent(
            operation_id="op-1",
            kind=ImportEventKind.FAILED,
            display_message="Traceback (most recent call last) something",
            technical_detail="x",
        )


def test_an_event_needs_a_whitespace_free_operation_id():
    with pytest.raises(ImportCoordinationError, match="whitespace"):
        ImportEvent(operation_id="op 1", kind=ImportEventKind.STARTED)


def test_the_terminal_kinds_are_exactly_three():
    assert import_coordination.TERMINAL_EVENT_KINDS == frozenset({
        ImportEventKind.COMPLETED,
        ImportEventKind.CANCELLED,
        ImportEventKind.FAILED,
    })
    assert len(ImportEventKind) == 5


def test_an_outcome_may_not_claim_an_append_it_did_not_make(tmp_path):
    manager = ImportedFileManager()
    request = folder_request(book(tmp_path))
    transaction = manager.plan(scan_roots(request), options=request.options)
    committed = manager.commit(transaction)
    assert committed.committed
    with pytest.raises(ImportCoordinationError, match="must not carry a committed"):
        ImportOutcome(status=OutcomeStatus.CANCELLED, commit=committed)


def test_a_committed_outcome_must_carry_the_commit_that_committed():
    with pytest.raises(ImportCoordinationError, match="carries the CommitResult"):
        ImportOutcome(status=OutcomeStatus.COMMITTED)


def test_a_started_report_needs_an_operation_id():
    with pytest.raises(ImportCoordinationError, match="has an operation id"):
        StartReport(outcome=StartOutcome.STARTED)
    assert StartReport(outcome=StartOutcome.BUSY).started is False


def test_a_close_report_defaults_to_a_clean_close():
    report = CloseReport()
    assert report.closed and report.worker_stopped and report.discarded_events == 0


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #


def test_a_new_coordinator_is_idle_and_owns_nothing():
    coordinator = coordinator_for()
    assert coordinator.phase is ImportPhase.IDLE
    assert coordinator.is_active is False
    assert coordinator.is_closed is False
    assert coordinator.operation_id == ""
    assert coordinator.discovered_count == 0
    assert coordinator.pending_transaction is None
    assert coordinator.pump().status is OutcomeStatus.IDLE


def test_one_start_creates_exactly_one_worker(tmp_path):
    threads = RecordingThreads()
    coordinator = coordinator_for(thread_factory=threads)
    report = coordinator.start(folder_request(book(tmp_path)))
    assert report.outcome is StartOutcome.STARTED
    assert report.operation_id
    assert len(threads.made) == 1
    assert threads.made[0].starts == 1


def test_a_second_start_while_one_is_active_is_refused(tmp_path):
    root = book(tmp_path)
    release = threading.Event()
    started = threading.Event()
    threads = RecordingThreads(kind=lambda target, name: threading.Thread(
        target=target, name=name, daemon=False))
    scanner = ControlledScanner(started=started, release=release)
    coordinator = coordinator_for(scanner=scanner, thread_factory=threads)
    try:
        first = coordinator.start(folder_request(root))
        assert started.wait(WAIT)

        second = coordinator.start(folder_request(root, request_id="req-2"))
        assert second.outcome is StartOutcome.BUSY
        assert second.operation_id == first.operation_id
        assert len(threads.made) == 1, "a refused start creates no worker"
    finally:
        release.set()
        coordinator.close()


def test_every_operation_gets_its_own_identity(tmp_path):
    root = book(tmp_path)
    coordinator = coordinator_for()
    first = coordinator.start(folder_request(root))
    coordinator.pump()
    second = coordinator.start(folder_request(root, request_id="req-2"))
    assert first.operation_id != second.operation_id


def test_the_request_is_frozen_before_the_worker_starts(tmp_path):
    root = book(tmp_path)
    request = folder_request(root, threshold=7)
    coordinator = coordinator_for()
    coordinator.start(request)
    # The value objects are frozen dataclasses, so "captured" is not a promise the
    # coordinator has to keep — it is a property of what it was handed.
    with pytest.raises(Exception):
        request.options.allow_duplicate_files = True
    with pytest.raises(Exception):
        request.roots = ()
    assert request.large_result_warning_threshold == 7


def test_a_started_event_arrives_before_anything_else(tmp_path):
    coordinator = coordinator_for()
    outcome = run_to_completion(coordinator, folder_request(book(tmp_path)))
    kinds = [event.kind for event in outcome.events]
    assert kinds[0] is ImportEventKind.STARTED
    assert kinds[-1] is ImportEventKind.COMPLETED
    assert sum(1 for kind in kinds if kind in import_coordination.TERMINAL_EVENT_KINDS) == 1


def test_a_successful_import_returns_the_coordinator_to_idle(tmp_path):
    coordinator = coordinator_for()
    outcome = run_to_completion(coordinator, folder_request(book(tmp_path)))
    assert outcome.status is OutcomeStatus.COMMITTED
    assert coordinator.phase is ImportPhase.IDLE
    assert coordinator.is_active is False


def test_a_failed_worker_returns_the_coordinator_to_idle(tmp_path):
    scanner = ControlledScanner(raises=RuntimeError("the disk went away"))
    coordinator = coordinator_for(scanner=scanner)
    outcome = run_to_completion(coordinator, folder_request(book(tmp_path)))
    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.display_message == "The import could not be completed."
    assert "RuntimeError: the disk went away" in outcome.technical_detail
    assert coordinator.phase is ImportPhase.IDLE


def test_a_cancelled_worker_returns_the_coordinator_to_idle(tmp_path):
    request = folder_request(book(tmp_path))
    scanner = ControlledScanner(returns=cancelled_result)
    coordinator = coordinator_for(scanner=scanner)
    outcome = run_to_completion(coordinator, request)
    assert outcome.status is OutcomeStatus.CANCELLED
    assert coordinator.phase is ImportPhase.IDLE


def test_a_duplicated_terminal_event_is_harmless(tmp_path):
    manager = ImportedFileManager()
    threads = RecordingThreads(kind=DoubleStartThread)
    coordinator = coordinator_for(manager, thread_factory=threads)
    outcome = run_to_completion(coordinator, folder_request(book(tmp_path)))

    assert outcome.status is OutcomeStatus.COMMITTED
    assert manager.count == 3, "the second terminal event must not commit again"
    assert [event.kind for event in outcome.ignored].count(
        ImportEventKind.COMPLETED) == 1
    assert coordinator.phase is ImportPhase.IDLE


def test_events_from_an_older_operation_are_ignored(tmp_path):
    root = book(tmp_path)
    manager = ImportedFileManager()
    threads = RecordingThreads()
    coordinator = coordinator_for(manager, thread_factory=threads)

    first = coordinator.start(folder_request(root))
    assert coordinator.pump().status is OutcomeStatus.COMMITTED
    assert manager.count == 3

    second = coordinator.start(folder_request(root, request_id="req-2"))
    threads.replay(0)  # the finished worker speaks again, with its own operation id
    outcome = coordinator.pump()

    assert outcome.operation_id == second.operation_id
    stale = {event.operation_id for event in outcome.ignored}
    assert stale == {first.operation_id}
    assert manager.count == 3, "the stale replay appended nothing"


def test_a_later_import_starts_cleanly_after_the_first_finished(tmp_path):
    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)
    run_to_completion(coordinator, folder_request(book(tmp_path, "One", "a.mp3")))
    outcome = run_to_completion(
        coordinator, folder_request(book(tmp_path, "Two", "b.mp3"), request_id="req-2"))
    assert outcome.status is OutcomeStatus.COMMITTED
    assert names_in(manager) == ["a.mp3", "b.mp3"]


def test_a_start_that_cannot_create_a_thread_leaves_the_coordinator_idle(tmp_path):
    class RefusingThread(InlineThread):
        def start(self) -> None:
            raise RuntimeError("can't start new thread")

    coordinator = coordinator_for(thread_factory=RecordingThreads(kind=RefusingThread))
    with pytest.raises(RuntimeError, match="can't start new thread"):
        coordinator.start(folder_request(book(tmp_path)))
    assert coordinator.phase is ImportPhase.IDLE
    assert coordinator.operation_id == ""


def test_a_request_with_no_selected_types_starts_no_worker(tmp_path):
    threads = RecordingThreads()
    coordinator = coordinator_for(thread_factory=threads)
    report = coordinator.start(folder_request(book(tmp_path), selected=set()))
    assert report.outcome is StartOutcome.NO_TYPES_SELECTED
    assert "at least one file type" in report.display_message
    assert threads.made == []


def test_direct_files_may_not_be_pushed_through_the_background_path():
    coordinator = coordinator_for()
    with pytest.raises(ImportCoordinationError, match="import_files"):
        coordinator.start(direct_request())


def test_start_refuses_anything_that_is_not_a_scan_request():
    coordinator = coordinator_for()
    with pytest.raises(ImportCoordinationError, match="needs a ScanRequest"):
        coordinator.start("C:/Books")


# --------------------------------------------------------------------------- #
# Thread ownership
# --------------------------------------------------------------------------- #


def test_the_scan_runs_off_the_calling_thread(tmp_path):
    threads = RealThreads()
    scanner = ControlledScanner()
    coordinator = coordinator_for(scanner=scanner, thread_factory=threads)
    coordinator.start(folder_request(book(tmp_path)))
    threads.made[0].join(WAIT)

    assert scanner.calls == 1
    assert scanner.thread_idents[0] != threading.get_ident()
    coordinator.pump()
    coordinator.close()


def test_a_worker_thread_may_not_pump_the_coordinator(tmp_path):
    holder: dict = {}
    release = threading.Event()

    class Trespasser(ControlledScanner):
        def __call__(self, request, **kwargs):
            try:
                holder["coordinator"].pump()
            except BaseException as exc:  # noqa: BLE001 - recorded, then re-raised
                holder["error"] = exc
                raise
            return super().__call__(request, **kwargs)  # pragma: no cover

    threads = RealThreads()
    coordinator = coordinator_for(scanner=Trespasser(release=release), thread_factory=threads)
    holder["coordinator"] = coordinator
    coordinator.start(folder_request(book(tmp_path)))
    threads.made[0].join(WAIT)
    release.set()

    assert isinstance(holder["error"], ImportCoordinationError)
    assert "must run on the thread that owns it" in str(holder["error"])
    # And the failure was converted, not leaked: the operation ends truthfully.
    outcome = coordinator.pump()
    assert outcome.status is OutcomeStatus.FAILED
    coordinator.close()


@pytest.mark.parametrize(
    "action", ["start", "import_files", "pump", "confirm_pending", "decline_pending", "close"])
def test_every_manager_touching_entry_point_is_fenced_to_the_owner_thread(action, tmp_path):
    coordinator = coordinator_for()
    errors: list = []

    def call() -> None:
        try:
            if action == "start":
                coordinator.start(folder_request(book(tmp_path)))
            elif action == "import_files":
                coordinator.import_files(direct_request(), ())
            else:
                getattr(coordinator, action)()
        except BaseException as exc:  # noqa: BLE001 - the point of the test
            errors.append(exc)

    thread = threading.Thread(target=call, name="not-the-owner")
    thread.start()
    thread.join(WAIT)

    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], ImportCoordinationError)
    assert action in str(errors[0])


def test_cancel_is_deliberately_callable_from_any_thread(tmp_path):
    release = threading.Event()
    threads = RealThreads()
    coordinator = coordinator_for(
        scanner=ControlledScanner(release=release), thread_factory=threads)
    coordinator.start(folder_request(book(tmp_path)))

    results: list = []
    helper = threading.Thread(
        target=lambda: results.append(coordinator.request_cancel()), name="cancel-button")
    helper.start()
    helper.join(WAIT)
    release.set()

    assert results == [True]
    assert coordinator.cancel_requested is True
    coordinator.close()


def test_only_immutable_values_cross_the_queue(tmp_path):
    coordinator = coordinator_for()
    outcome = run_to_completion(coordinator, folder_request(book(tmp_path)))
    for event in outcome.events:
        with pytest.raises(Exception):
            event.operation_id = "tampered"
        if event.result is not None:
            with pytest.raises(Exception):
                event.result.files = ()
            assert isinstance(event.result.files, tuple)
            assert isinstance(event.result.problems, tuple)
        assert not isinstance(event.technical_detail, BaseException)


def test_a_worker_failure_crosses_as_text_and_never_as_an_exception(tmp_path):
    boom = ValueError("multi\nline\nmessage")
    coordinator = coordinator_for(scanner=ControlledScanner(raises=boom))
    outcome = run_to_completion(coordinator, folder_request(book(tmp_path)))

    assert outcome.status is OutcomeStatus.FAILED
    assert isinstance(outcome.technical_detail, str)
    assert "\n" not in outcome.technical_detail
    assert outcome.technical_detail == "ValueError: multi line message"
    for event in outcome.events:
        assert not isinstance(event.result, BaseException)


def test_the_coordinator_reserves_no_output_and_writes_nothing(tmp_path):
    root = book(tmp_path)
    before = snapshot_tree(tmp_path)
    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)
    run_to_completion(coordinator, folder_request(root))
    coordinator.close()

    assert manager.count == 3
    assert snapshot_tree(tmp_path) == before
    assert sorted(path.name for path in tmp_path.rglob("*") if path.is_file()) == [
        "01.mp3", "02.mp3", "10.mp3"]


def test_no_thread_survives_a_deterministic_teardown(tmp_path):
    baseline = threading.active_count()
    threads = RealThreads()
    coordinator = coordinator_for(thread_factory=threads)
    coordinator.start(folder_request(book(tmp_path)))
    coordinator.pump()
    report = coordinator.close()

    assert report.worker_stopped
    for thread in threads.made:
        thread.join(WAIT)
        assert not thread.is_alive()
    assert threading.active_count() == baseline


# --------------------------------------------------------------------------- #
# Cancellation
# --------------------------------------------------------------------------- #


def test_the_import_cancellation_primitive_is_a_flag_and_not_an_exception():
    cancel = ImportCancellation()
    assert cancel.requested is False and cancel() is False
    cancel.request()
    cancel.request()  # idempotent
    assert cancel.requested is True and cancel() is True
    assert not hasattr(cancel, "reset")


def test_cancel_before_the_worker_does_meaningful_work(tmp_path):
    manager = ImportedFileManager()
    started = threading.Event()
    release = threading.Event()
    threads = RealThreads()
    scanner = ControlledScanner(started=started, release=release)
    coordinator = coordinator_for(manager, scanner=scanner, thread_factory=threads)

    coordinator.start(folder_request(book(tmp_path)))
    assert started.wait(WAIT)
    coordinator.request_cancel()
    release.set()
    threads.made[0].join(WAIT)

    outcome = coordinator.pump()
    assert outcome.status is OutcomeStatus.CANCELLED
    assert manager.count == 0
    assert outcome.added == ()


def test_cancel_during_deterministic_scanning(tmp_path):
    """The real scanner, stopped at a real checkpoint — no fake, no sleep."""
    root = book(tmp_path, "Long", *[f"{index:03d}.mp3" for index in range(1, 21)])
    manager = ImportedFileManager()
    seen: list[int] = []
    holder: dict = {}

    def stopping_scanner(request, *, cancel_check, on_count, completed_at=0.0):
        # Cancel exactly when the third candidate has been counted. The real scanner
        # then stops at its own next checkpoint — no sleep, no timing assumption.
        def watch(count: int) -> None:
            seen.append(count)
            on_count(count)
            if count == 3:
                holder["coordinator"].request_cancel()

        return scan_roots(
            request, cancel_check=cancel_check, on_count=watch, completed_at=completed_at)

    coordinator = coordinator_for(manager, scanner=stopping_scanner)
    holder["coordinator"] = coordinator
    outcome = run_to_completion(coordinator, folder_request(root))

    assert outcome.status is OutcomeStatus.CANCELLED
    assert seen[:3] == [1, 2, 3]
    assert len(seen) < 20, "the scan stopped at a checkpoint rather than finishing"
    assert manager.count == 0


def test_cancel_after_publication_but_before_handling(tmp_path):
    manager = ImportedFileManager()
    threads = RealThreads()
    coordinator = coordinator_for(manager, thread_factory=threads)
    coordinator.start(folder_request(book(tmp_path)))
    threads.made[0].join(WAIT)  # the completed event is already on the queue

    coordinator.request_cancel()
    outcome = coordinator.pump()

    # The result was complete, so it is committed: cancelling after the work is done
    # and published is honest about having arrived too late, and never invents a
    # partial list. What matters is that the append is still whole and once.
    assert outcome.status is OutcomeStatus.COMMITTED
    assert manager.count == 3
    coordinator.close()


def test_repeated_cancel_requests_are_idempotent(tmp_path):
    release = threading.Event()
    threads = RealThreads()
    coordinator = coordinator_for(
        scanner=ControlledScanner(release=release), thread_factory=threads)
    coordinator.start(folder_request(book(tmp_path)))

    assert coordinator.request_cancel() is True
    assert coordinator.request_cancel() is True
    assert coordinator.request_cancel() is True
    release.set()
    coordinator.close()


def test_cancel_with_nothing_active_does_nothing_at_all():
    coordinator = coordinator_for()
    assert coordinator.request_cancel() is False
    assert coordinator.phase is ImportPhase.IDLE
    assert coordinator.pump().status is OutcomeStatus.IDLE


def test_cancel_after_terminal_handling_does_nothing(tmp_path):
    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)
    run_to_completion(coordinator, folder_request(book(tmp_path)))

    assert coordinator.request_cancel() is False
    assert manager.count == 3
    assert coordinator.pump().status is OutcomeStatus.IDLE


def test_a_cancelled_scan_commits_nothing_even_when_it_found_things(tmp_path):
    manager = ImportedFileManager()
    request = folder_request(book(tmp_path))
    coordinator = coordinator_for(
        manager, scanner=ControlledScanner(returns=lambda req: cancelled_result(req, 9)))
    outcome = run_to_completion(coordinator, request)

    assert outcome.status is OutcomeStatus.CANCELLED
    assert manager.count == 0
    assert manager.revision.value == 0
    assert [problem.category for problem in outcome.problems] == [ProblemCategory.CANCELLED]


def test_late_progress_after_an_acknowledged_cancel_is_not_live(tmp_path):
    """A count discovered after Cancel was pressed is not shown as progress."""
    root = book(tmp_path)
    coordinator = coordinator_for()

    def scanner(request, *, cancel_check, on_count, completed_at=0.0):
        on_count(1)
        on_count(2)
        coordinator.request_cancel()
        on_count(99)          # discovered after the user pressed Cancel
        return cancelled_result(request, 99)

    coordinator = coordinator_for(scanner=scanner)
    report = coordinator.start(folder_request(root))
    assert report.started
    outcome = coordinator.pump()

    assert outcome.status is OutcomeStatus.CANCELLED
    counts = [
        event.discovered_count for event in outcome.events
        if event.kind is ImportEventKind.DISCOVERED
    ]
    assert 99 not in counts
    assert outcome.discovered_count <= 2


def test_the_worker_exits_after_a_cancel(tmp_path):
    started = threading.Event()
    release = threading.Event()
    threads = RealThreads()
    coordinator = coordinator_for(
        scanner=ControlledScanner(started=started, release=release), thread_factory=threads)
    coordinator.start(folder_request(book(tmp_path)))
    assert started.wait(WAIT)

    coordinator.request_cancel()
    release.set()
    threads.made[0].join(WAIT)
    assert not threads.made[0].is_alive()
    assert coordinator.pump().status is OutcomeStatus.CANCELLED


# --------------------------------------------------------------------------- #
# The isolation gate: Cancel Import is not Cancel Job
# --------------------------------------------------------------------------- #


def test_cancelling_an_import_leaves_a_processing_controller_untouched(tmp_path):
    """A stand-in for a running conversion, wired exactly as the existing tools wire it."""
    processing_cancel = threading.Event()
    checkpoints: list[str] = []

    def processing_checkpoint(label: str) -> None:
        processing_cancellation.raise_if_cancelled(processing_cancel.is_set, "Cancelled.")
        checkpoints.append(label)

    release = threading.Event()
    threads = RealThreads()
    coordinator = coordinator_for(
        scanner=ControlledScanner(release=release), thread_factory=threads)
    coordinator.start(folder_request(book(tmp_path)))

    processing_checkpoint("before")
    coordinator.request_cancel()
    processing_checkpoint("after")

    assert processing_cancel.is_set() is False
    assert checkpoints == ["before", "after"]
    release.set()
    coordinator.close()
    processing_checkpoint("after close")
    assert checkpoints == ["before", "after", "after close"]


def test_an_import_cancellation_is_not_a_conversion_cancellation():
    cancel = ImportCancellation()
    cancel.request()
    assert not isinstance(cancel, processing_cancellation.ConversionCancelled)
    # It is a predicate, so it could be *offered* to processing code; what matters is
    # that the coordinator never does, and that honouring it raises nothing here.
    with pytest.raises(processing_cancellation.ConversionCancelled):
        processing_cancellation.raise_if_cancelled(cancel)


def test_a_cancelled_import_raises_nothing_at_all(tmp_path):
    """Cancelling a scan returns a cancelled *result*; it never unwinds a stack."""
    coordinator = coordinator_for(scanner=ControlledScanner(returns=cancelled_result))
    outcome = run_to_completion(coordinator, folder_request(book(tmp_path)))
    assert outcome.status is OutcomeStatus.CANCELLED
    assert outcome.display_message == "The import was cancelled and nothing was added."


# --------------------------------------------------------------------------- #
# Queue and event behaviour
# --------------------------------------------------------------------------- #


def test_discovered_counts_arrive_in_order_and_never_go_backwards(tmp_path):
    root = book(tmp_path, "Many", *[f"{index:03d}.mp3" for index in range(1, 9)])
    published: list[int] = []

    def recording_scanner(request, *, cancel_check, on_count, completed_at=0.0):
        def watch(count: int) -> None:
            published.append(count)
            on_count(count)
        return scan_roots(
            request, cancel_check=cancel_check, on_count=watch, completed_at=completed_at)

    coordinator = coordinator_for(scanner=recording_scanner)
    outcome = run_to_completion(coordinator, folder_request(root))
    assert published == list(range(1, 9))
    counts = [
        event.discovered_count for event in outcome.events
        if event.kind is ImportEventKind.DISCOVERED
    ]
    assert counts == sorted(counts)
    assert outcome.status is OutcomeStatus.COMMITTED


def test_progress_is_coalesced_so_the_queue_cannot_grow_without_bound(tmp_path):
    """Ten thousand discoveries must not become ten thousand queued events."""
    coordinator = coordinator_for()

    def flooding_scanner(request, *, cancel_check, on_count, completed_at=0.0):
        for count in range(1, 10_001):
            on_count(count)
        return scan_roots(request, completed_at=completed_at)

    coordinator = coordinator_for(scanner=flooding_scanner)
    outcome = run_to_completion(coordinator, folder_request(book(tmp_path)))

    progress = [
        event for event in outcome.events if event.kind is ImportEventKind.DISCOVERED]
    assert len(progress) == 1, "an unread progress event is never joined by a second"
    assert progress[0].discovered_count == 1


def test_the_gate_reopens_once_progress_has_been_read(tmp_path):
    coordinator = coordinator_for()
    drained: list[int] = []

    def scanner(request, *, cancel_check, on_count, completed_at=0.0):
        for count in (1, 2, 3):
            on_count(count)
            drained.append(coordinator.pump().discovered_count)
        return scan_roots(request, completed_at=completed_at)

    coordinator = coordinator_for(scanner=scanner)
    outcome = run_to_completion(coordinator, folder_request(book(tmp_path)))
    assert drained == [1, 2, 3], "each drain lets the next count through"
    assert outcome.status is OutcomeStatus.COMMITTED


def test_every_event_carries_its_own_operation_id(tmp_path):
    coordinator = coordinator_for()
    report = coordinator.start(folder_request(book(tmp_path)))
    outcome = coordinator.pump()
    assert outcome.events
    assert {event.operation_id for event in outcome.events} == {report.operation_id}
    assert outcome.operation_id == report.operation_id


def test_a_terminal_result_is_published_exactly_once(tmp_path):
    coordinator = coordinator_for()
    outcome = run_to_completion(coordinator, folder_request(book(tmp_path)))
    terminal = [event for event in outcome.events if event.is_terminal]
    assert len(terminal) == 1
    assert coordinator.pump().status is OutcomeStatus.IDLE


def test_draining_an_empty_queue_is_a_deterministic_no_op(tmp_path):
    coordinator = coordinator_for()
    run_to_completion(coordinator, folder_request(book(tmp_path)))
    for _ in range(5):
        outcome = coordinator.pump()
        assert outcome.status is OutcomeStatus.IDLE
        assert outcome.events == () and outcome.ignored == ()


def test_a_running_import_reports_progress_without_committing(tmp_path):
    started = threading.Event()
    release = threading.Event()
    manager = ImportedFileManager()
    threads = RealThreads()
    coordinator = coordinator_for(
        manager,
        scanner=ControlledScanner(counts=(4,), started=started, release=release),
        thread_factory=threads,
    )
    coordinator.start(folder_request(book(tmp_path)))
    assert started.wait(WAIT)

    outcome = coordinator.pump()
    assert outcome.status in (OutcomeStatus.RUNNING,)
    assert outcome.added == ()
    assert manager.count == 0
    assert manager.revision.value == 0

    release.set()
    threads.made[0].join(WAIT)
    assert coordinator.pump().status is OutcomeStatus.COMMITTED


def test_an_illegal_queue_payload_fails_closed(tmp_path):
    manager = ImportedFileManager()
    started = threading.Event()
    release = threading.Event()
    threads = RealThreads()
    coordinator = coordinator_for(
        manager,
        scanner=ControlledScanner(started=started, release=release),
        thread_factory=threads,
    )
    coordinator.start(folder_request(book(tmp_path)))
    assert started.wait(WAIT)

    coordinator._queue.put("not an event")  # the one white-box reach; see the docstring
    outcome = coordinator.pump()

    assert outcome.status is OutcomeStatus.FAILED
    assert "illegal queue payload" in outcome.technical_detail
    assert manager.count == 0
    assert coordinator.phase is ImportPhase.IDLE
    release.set()
    coordinator.close()


def test_an_illegal_payload_arriving_after_a_commit_does_not_undo_it(tmp_path):
    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)
    run_to_completion(coordinator, folder_request(book(tmp_path)))
    assert manager.count == 3

    coordinator._queue.put(object())
    outcome = coordinator.pump()

    assert outcome.status is OutcomeStatus.FAILED
    assert manager.count == 3, "the commit already happened and is not rolled back"


def test_a_completed_event_for_another_request_is_refused(tmp_path):
    manager = ImportedFileManager()
    other = folder_request(book(tmp_path, "Other", "z.mp3"), request_id="req-other")
    foreign = scan_roots(other)
    coordinator = coordinator_for(
        manager, scanner=ControlledScanner(returns=lambda _request: foreign))

    outcome = run_to_completion(coordinator, folder_request(book(tmp_path)))

    assert outcome.status is OutcomeStatus.FAILED
    assert "did not carry this operation's own result" in outcome.technical_detail
    assert manager.count == 0


# --------------------------------------------------------------------------- #
# Broad-root confirmation, before any scanning
# --------------------------------------------------------------------------- #


def test_a_broad_root_is_declined_without_creating_a_worker(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    asked: list = []
    threads = RecordingThreads()
    scanner = ControlledScanner()
    coordinator = coordinator_for(
        scanner=scanner,
        thread_factory=threads,
        home=home,
        confirm_broad_root=lambda roots: asked.append(roots) or False,
    )

    report = coordinator.start(folder_request(home))

    assert report.outcome is StartOutcome.DECLINED_BROAD_ROOT
    assert report.broad_roots == (home,)
    assert asked == [(home,)]
    assert threads.made == [], "declining creates no worker"
    assert scanner.calls == 0, "and scans nothing"
    assert coordinator.phase is ImportPhase.IDLE


def test_an_accepted_broad_root_starts_exactly_one_worker(tmp_path):
    home = tmp_path / "home"
    touch(home / "a.mp3")
    threads = RecordingThreads()
    coordinator = coordinator_for(
        thread_factory=threads, home=home, confirm_broad_root=lambda roots: True)

    report = coordinator.start(folder_request(home))
    assert report.outcome is StartOutcome.STARTED
    assert len(threads.made) == 1
    assert coordinator.pump().status is OutcomeStatus.COMMITTED


def test_a_broad_root_with_no_confirmer_wired_up_is_refused(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    threads = RecordingThreads()
    coordinator = coordinator_for(thread_factory=threads, home=home)

    report = coordinator.start(folder_request(home))

    assert report.outcome is StartOutcome.DECLINED_BROAD_ROOT
    assert threads.made == []


def test_a_narrow_root_never_asks(tmp_path):
    asked: list = []
    coordinator = coordinator_for(
        home=tmp_path / "home", confirm_broad_root=lambda roots: asked.append(roots) or True)
    report = coordinator.start(folder_request(book(tmp_path)))
    assert report.outcome is StartOutcome.STARTED
    assert asked == []


def test_the_broad_root_check_never_scans_to_decide(tmp_path):
    """A root that does not even exist is still classified, without touching a disk."""
    missing = tmp_path / "gone"
    asked: list = []
    coordinator = coordinator_for(
        home=missing, confirm_broad_root=lambda roots: asked.append(roots) or False)
    report = coordinator.start(folder_request(missing))
    assert report.outcome is StartOutcome.DECLINED_BROAD_ROOT
    assert asked == [(missing,)]
    assert not missing.exists()


def test_every_broad_root_in_a_multi_root_request_is_reported(tmp_path):
    home = tmp_path / "home"
    touch(home / "a.mp3")
    narrow = book(tmp_path, "Narrow", "b.mp3")
    seen: list = []
    coordinator = coordinator_for(
        home=home, confirm_broad_root=lambda roots: seen.append(roots) or False)

    report = coordinator.start(folder_request(narrow, home))
    assert report.broad_roots == (home,)
    assert seen == [(home,)]


def test_a_declined_broad_root_leaves_the_manager_untouched(tmp_path):
    home = tmp_path / "home"
    touch(home / "a.mp3")
    manager = ImportedFileManager()
    coordinator = coordinator_for(
        manager, home=home, confirm_broad_root=lambda roots: False)
    coordinator.start(folder_request(home))
    assert manager.count == 0
    assert manager.revision.value == 0
    assert coordinator.pump().status is OutcomeStatus.IDLE


# --------------------------------------------------------------------------- #
# The captured large-result threshold
# --------------------------------------------------------------------------- #


def test_exactly_at_the_threshold_does_not_warn(tmp_path):
    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)
    outcome = run_to_completion(
        coordinator, folder_request(book(tmp_path), threshold=3))
    assert outcome.status is OutcomeStatus.COMMITTED
    assert manager.count == 3


def test_over_the_threshold_asks_before_committing(tmp_path):
    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)
    outcome = run_to_completion(
        coordinator, folder_request(book(tmp_path), threshold=2))

    assert outcome.status is OutcomeStatus.AWAITING_CONFIRMATION
    assert outcome.proposed_count == 3
    assert manager.count == 0, "nothing is committed while the question is open"
    assert coordinator.phase is ImportPhase.AWAITING_CONFIRMATION
    assert coordinator.pending_transaction is outcome.transaction


def test_accepting_the_threshold_commits_once(tmp_path):
    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)
    run_to_completion(coordinator, folder_request(book(tmp_path), threshold=2))

    outcome = coordinator.confirm_pending()
    assert outcome.status is OutcomeStatus.COMMITTED
    assert manager.count == 3
    assert coordinator.phase is ImportPhase.IDLE
    # A second acceptance has nothing to accept.
    assert coordinator.confirm_pending().status is OutcomeStatus.IDLE
    assert manager.count == 3


def test_declining_the_threshold_commits_nothing(tmp_path):
    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)
    run_to_completion(coordinator, folder_request(book(tmp_path), threshold=2))

    outcome = coordinator.decline_pending()
    assert outcome.status is OutcomeStatus.DECLINED
    assert manager.count == 0
    assert manager.revision.value == 0
    assert coordinator.phase is ImportPhase.IDLE
    assert coordinator.decline_pending().status is OutcomeStatus.IDLE


def test_the_held_result_is_preserved_unchanged_while_waiting(tmp_path):
    coordinator = coordinator_for()
    outcome = run_to_completion(coordinator, folder_request(book(tmp_path), threshold=1))
    held = coordinator.pending_transaction

    for _ in range(3):
        again = coordinator.pump()
        assert again.status is OutcomeStatus.AWAITING_CONFIRMATION
        assert coordinator.pending_transaction is held
    assert held is outcome.transaction
    assert [entry.path.name for entry in held.additions] == ["01.mp3", "02.mp3", "10.mp3"]


def test_the_threshold_comes_from_the_captured_config_not_a_live_read(tmp_path, monkeypatch):
    """A preference saved mid-scan cannot change the rule this result is judged by."""
    calls: list = []
    monkeypatch.setattr(
        "shared.config.get_effective",
        lambda: calls.append(1) or make_config(0),
    )
    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)
    outcome = run_to_completion(
        coordinator, folder_request(book(tmp_path), threshold=1000))

    assert outcome.status is OutcomeStatus.COMMITTED
    assert calls == [], "coordination never re-reads configuration"


def test_no_hard_maximum_exists(tmp_path):
    """A very large proposal is only ever a question, never a refusal."""
    root = book(tmp_path, "Huge", *[f"{index:04d}.mp3" for index in range(1, 51)])
    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)
    outcome = run_to_completion(coordinator, folder_request(root, threshold=10))

    assert outcome.status is OutcomeStatus.AWAITING_CONFIRMATION
    assert outcome.proposed_count == 50
    assert coordinator.confirm_pending().status is OutcomeStatus.COMMITTED
    assert manager.count == 50


def test_cancelling_while_a_confirmation_is_pending_commits_nothing(tmp_path):
    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)
    run_to_completion(coordinator, folder_request(book(tmp_path), threshold=1))

    assert coordinator.request_cancel() is True
    outcome = coordinator.pump()

    assert outcome.status is OutcomeStatus.CANCELLED
    assert manager.count == 0
    assert coordinator.phase is ImportPhase.IDLE
    assert coordinator.pending_transaction is None


def test_confirming_after_a_cancel_still_commits_nothing(tmp_path):
    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)
    run_to_completion(coordinator, folder_request(book(tmp_path), threshold=1))
    coordinator.request_cancel()

    outcome = coordinator.confirm_pending()
    assert outcome.status is OutcomeStatus.CANCELLED
    assert manager.count == 0


def test_a_start_while_a_confirmation_is_pending_is_refused(tmp_path):
    threads = RecordingThreads()
    coordinator = coordinator_for(thread_factory=threads)
    run_to_completion(coordinator, folder_request(book(tmp_path), threshold=1))

    report = coordinator.start(folder_request(book(tmp_path, "Two", "z.mp3")))
    assert report.outcome is StartOutcome.BUSY
    assert len(threads.made) == 1


# --------------------------------------------------------------------------- #
# Commit coordination and revision drift
# --------------------------------------------------------------------------- #


def test_a_successful_result_commits_once_in_the_exact_scanned_order(tmp_path):
    root = book(tmp_path, "Ordered", "10.mp3", "2.mp3", "1.mp3")
    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)
    outcome = run_to_completion(coordinator, folder_request(root))

    assert outcome.status is OutcomeStatus.COMMITTED
    assert names_in(manager) == ["1.mp3", "2.mp3", "10.mp3"]
    assert outcome.added_count == 3
    assert manager.revision.value == 1, "one append, one revision"


def test_every_problem_survives_into_the_outcome(tmp_path):
    root = tmp_path / "Mixed"
    touch(root / "01.mp3")
    touch(root / "notes.txt")
    touch(root / ".hidden.mp3")
    (root / "sub").mkdir()

    coordinator = coordinator_for()
    outcome = run_to_completion(coordinator, folder_request(root))

    categories = {problem.category for problem in outcome.problems}
    assert ProblemCategory.UNSUPPORTED_TYPE in categories
    assert ProblemCategory.HIDDEN in categories
    assert outcome.status is OutcomeStatus.COMMITTED


def test_duplicate_skips_are_reported_and_nothing_new_is_added(tmp_path):
    root = book(tmp_path, "Twice", "a.mp3")
    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)
    run_to_completion(coordinator, folder_request(root))

    outcome = run_to_completion(coordinator, folder_request(root, request_id="req-2"))

    assert outcome.status is OutcomeStatus.NOTHING_ADDED
    assert manager.count == 1
    assert [problem.category for problem in outcome.problems] == [ProblemCategory.DUPLICATE]
    assert manager.revision.value == 1, "a no-op commit does not move the revision"


def test_the_frozen_duplicate_option_is_the_one_that_applies(tmp_path):
    root = book(tmp_path, "Twice", "a.mp3")
    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)
    run_to_completion(coordinator, folder_request(root))

    outcome = run_to_completion(
        coordinator, folder_request(root, duplicates=True, request_id="req-2"))

    assert outcome.status is OutcomeStatus.COMMITTED
    assert manager.count == 2
    files = manager.snapshot().files
    assert files[0].identity == files[1].identity, "the same source, honestly"
    assert files[0].occurrence_id != files[1].occurrence_id
    assert files[0].path == files[1].path


def test_the_manager_does_not_move_until_the_owner_thread_commits(tmp_path):
    manager = ImportedFileManager()
    threads = RealThreads()
    coordinator = coordinator_for(manager, thread_factory=threads)
    coordinator.start(folder_request(book(tmp_path)))
    threads.made[0].join(WAIT)

    assert manager.count == 0, "the worker published a result and nothing more"
    assert manager.revision.value == 0

    coordinator.pump()
    assert manager.count == 3
    assert manager.revision.value == 1
    coordinator.close()


def test_a_stale_revision_is_recomputed_rather_than_merged(tmp_path):
    """The list is emptied while the confirmation is open."""
    root = book(tmp_path, "Book", "a.mp3", "b.mp3")
    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)

    # Seed the manager with the *same* a.mp3, so the scan below proposes only b.mp3.
    seed = direct_request(request_id="req-seed")
    seeded = validate_direct_files(
        [root / "a.mp3"],
        request_id=seed.request_id,
        root=seed.roots[0],
        catalog=seed.catalog,
        options=seed.options,
    )
    manager.commit(manager.plan(seeded, options=seed.options))
    assert manager.count == 1

    outcome = run_to_completion(coordinator, folder_request(root, threshold=0))
    assert outcome.status is OutcomeStatus.AWAITING_CONFIRMATION
    assert outcome.proposed_count == 1, "a.mp3 is already imported"

    manager.clear()  # the user pressed Clear while the dialog was open
    stale_revision = outcome.transaction.expected_revision
    assert manager.revision != stale_revision

    again = coordinator.confirm_pending()
    assert again.status is OutcomeStatus.AWAITING_CONFIRMATION, (
        "a materially different proposal is re-asked, never silently substituted")
    assert again.proposed_count == 2
    assert manager.count == 0

    final = coordinator.confirm_pending()
    assert final.status is OutcomeStatus.COMMITTED
    assert manager.count == 2
    assert names_in(manager) == ["a.mp3", "b.mp3"]


def test_an_immaterial_drift_is_settled_without_asking_again(tmp_path):
    root = book(tmp_path, "Book", "a.mp3", "b.mp3")
    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)

    outcome = run_to_completion(coordinator, folder_request(root, threshold=1))
    assert outcome.status is OutcomeStatus.AWAITING_CONFIRMATION

    # Something unrelated joins the list while the dialog is open.
    other = folder_request(book(tmp_path, "Other", "z.mp3"), request_id="req-other")
    manager.commit(manager.plan(scan_roots(other), options=other.options))
    assert manager.count == 1

    final = coordinator.confirm_pending()
    assert final.status is OutcomeStatus.COMMITTED
    assert final.added_count == 2
    assert names_in(manager) == ["z.mp3", "a.mp3", "b.mp3"]


def test_recomputation_keeps_the_frozen_duplicate_policy(tmp_path):
    root = book(tmp_path, "Book", "a.mp3")
    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)

    outcome = run_to_completion(
        coordinator, folder_request(root, duplicates=True, threshold=0))
    assert outcome.status is OutcomeStatus.AWAITING_CONFIRMATION

    # The same file is added by hand while the dialog waits.
    manager.commit(manager.plan(scan_roots(folder_request(root, request_id="req-hand")),
                                options=options()))
    assert manager.count == 1

    final = coordinator.confirm_pending()
    assert final.status in (OutcomeStatus.COMMITTED, OutcomeStatus.AWAITING_CONFIRMATION)
    if final.status is OutcomeStatus.AWAITING_CONFIRMATION:
        final = coordinator.confirm_pending()
    assert final.status is OutcomeStatus.COMMITTED
    assert manager.count == 2, "allow-duplicates was frozen on, so the copy is kept"


def test_a_conflict_that_will_not_settle_appends_nothing(tmp_path):
    manager = AlwaysStaleManager()
    coordinator = coordinator_for(manager)
    outcome = run_to_completion(coordinator, folder_request(book(tmp_path)))

    assert outcome.status is OutcomeStatus.CONFLICT
    assert manager.count == 0
    assert manager.attempts == 2, "recomputed once, retried once, then reported"
    assert outcome.added == ()
    assert "changed while this import was finishing" in outcome.display_message
    assert coordinator.phase is ImportPhase.IDLE


def test_a_failed_result_appends_nothing(tmp_path):
    manager = ImportedFileManager()
    coordinator = coordinator_for(
        manager, scanner=ControlledScanner(returns=failed_result))
    outcome = run_to_completion(coordinator, folder_request(book(tmp_path)))

    assert outcome.status is OutcomeStatus.FAILED
    assert manager.count == 0
    assert [problem.category for problem in outcome.problems] == [
        ProblemCategory.UNREADABLE]


def test_a_scanner_returning_something_that_is_not_a_result_appends_nothing(tmp_path):
    manager = ImportedFileManager()
    coordinator = coordinator_for(
        manager, scanner=ControlledScanner(returns=lambda _request: "surprise"))
    outcome = run_to_completion(coordinator, folder_request(book(tmp_path)))

    assert outcome.status is OutcomeStatus.FAILED
    assert "not a ScanResult" in outcome.technical_detail
    assert manager.count == 0


def test_an_empty_folder_commits_nothing_and_says_so(tmp_path):
    empty = tmp_path / "Empty"
    empty.mkdir()
    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)
    outcome = run_to_completion(coordinator, folder_request(empty))

    assert outcome.status is OutcomeStatus.NOTHING_ADDED
    assert manager.count == 0
    assert manager.revision.value == 0


def test_repeated_handling_cannot_commit_twice(tmp_path):
    manager = ImportedFileManager()
    threads = RecordingThreads()
    coordinator = coordinator_for(manager, thread_factory=threads)
    coordinator.start(folder_request(book(tmp_path)))

    first = coordinator.pump()
    assert first.status is OutcomeStatus.COMMITTED
    for _ in range(3):
        assert coordinator.pump().status is OutcomeStatus.IDLE
    threads.replay(0)
    assert coordinator.pump().status is OutcomeStatus.IDLE
    assert manager.count == 3


def test_the_manager_ordering_is_append_only(tmp_path):
    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)
    run_to_completion(coordinator, folder_request(book(tmp_path, "One", "b.mp3")))
    run_to_completion(
        coordinator,
        folder_request(book(tmp_path, "Two", "a.mp3"), request_id="req-2"),
    )
    assert names_in(manager) == ["b.mp3", "a.mp3"], "later imports append, never interleave"


# --------------------------------------------------------------------------- #
# Direct Add Files through the same commit path
# --------------------------------------------------------------------------- #


def test_add_files_validates_and_commits_on_this_thread(tmp_path):
    first = touch(tmp_path / "b.mp3")
    second = touch(tmp_path / "a.mp3")
    manager = ImportedFileManager()
    threads = RecordingThreads()
    coordinator = coordinator_for(manager, thread_factory=threads)

    outcome = coordinator.import_files(direct_request(), [first, second])

    assert outcome.status is OutcomeStatus.COMMITTED
    assert names_in(manager) == ["b.mp3", "a.mp3"], "the user's order, never re-sorted"
    assert threads.made == [], "Add Files needs no worker"


def test_add_files_refuses_a_folder_and_reports_it(tmp_path):
    folder = tmp_path / "Book"
    folder.mkdir()
    good = touch(tmp_path / "a.mp3")
    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)

    outcome = coordinator.import_files(direct_request(), [good, folder])

    assert outcome.status is OutcomeStatus.COMMITTED
    assert manager.count == 1
    assert ProblemCategory.WRONG_TYPE in {
        problem.category for problem in outcome.problems}


def test_add_files_honours_the_captured_threshold(tmp_path):
    picked = [touch(tmp_path / f"{index}.mp3") for index in range(4)]
    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)

    outcome = coordinator.import_files(direct_request(threshold=3), picked)
    assert outcome.status is OutcomeStatus.AWAITING_CONFIRMATION
    assert manager.count == 0

    assert coordinator.confirm_pending().status is OutcomeStatus.COMMITTED
    assert manager.count == 4


def test_add_files_is_refused_while_a_scan_is_running(tmp_path):
    release = threading.Event()
    started = threading.Event()
    threads = RealThreads()
    coordinator = coordinator_for(
        scanner=ControlledScanner(started=started, release=release),
        thread_factory=threads)
    coordinator.start(folder_request(book(tmp_path)))
    assert started.wait(WAIT)

    outcome = coordinator.import_files(direct_request(), [touch(tmp_path / "a.mp3")])
    assert outcome.status is OutcomeStatus.BUSY
    release.set()
    coordinator.close()


def test_add_files_needs_exactly_one_direct_root(tmp_path):
    coordinator = coordinator_for()
    with pytest.raises(ImportCoordinationError, match="exactly one direct-files root"):
        coordinator.import_files(folder_request(book(tmp_path)), [])


def test_add_files_with_no_selected_types_adds_nothing(tmp_path):
    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)
    outcome = coordinator.import_files(
        direct_request(selected=set()), [touch(tmp_path / "a.mp3")])
    assert outcome.status is OutcomeStatus.NO_TYPES_SELECTED
    assert manager.count == 0


def test_add_files_never_touches_the_files_it_refuses(tmp_path):
    good = touch(tmp_path / "a.mp3")
    folder = tmp_path / "Book"
    touch(folder / "inner.mp3")
    before = snapshot_tree(tmp_path)

    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)
    coordinator.import_files(direct_request(), [good, folder, tmp_path / "gone.mp3"])

    assert snapshot_tree(tmp_path) == before
    assert manager.count == 1


# --------------------------------------------------------------------------- #
# Shutdown
# --------------------------------------------------------------------------- #


def test_closing_an_idle_coordinator_is_clean():
    coordinator = coordinator_for()
    report = coordinator.close()
    assert report.closed and report.worker_stopped
    assert report.cancelled_operation_id == ""
    assert coordinator.is_closed


def test_closing_is_idempotent(tmp_path):
    coordinator = coordinator_for()
    coordinator.close()
    for _ in range(3):
        assert coordinator.close().closed
    assert coordinator.phase is ImportPhase.CLOSED


def test_a_closed_coordinator_refuses_everything(tmp_path):
    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)
    coordinator.close()

    assert coordinator.start(folder_request(book(tmp_path))).outcome is StartOutcome.CLOSED
    assert coordinator.import_files(direct_request(), []).status is OutcomeStatus.CLOSED
    assert coordinator.pump().status is OutcomeStatus.CLOSED
    assert coordinator.confirm_pending().status is OutcomeStatus.CLOSED
    assert coordinator.decline_pending().status is OutcomeStatus.CLOSED
    assert manager.count == 0


def test_closing_while_a_worker_is_active_cancels_and_joins_it(tmp_path):
    manager = ImportedFileManager()
    started = threading.Event()
    release = threading.Event()
    threads = RealThreads()
    coordinator = coordinator_for(
        manager,
        scanner=ControlledScanner(started=started, release=release),
        thread_factory=threads,
    )
    report = coordinator.start(folder_request(book(tmp_path)))
    assert started.wait(WAIT)

    release.set()  # the worker may finish as soon as the cancel reaches it
    close = coordinator.close()

    assert close.cancelled_operation_id == report.operation_id
    assert close.worker_stopped is True
    assert not threads.made[0].is_alive()
    assert manager.count == 0, "a closed import commits nothing"


def test_a_close_that_cannot_stop_the_worker_says_so(tmp_path):
    """§5.4: never claim a running call stopped."""
    release = threading.Event()
    threads = RealThreads()
    coordinator = coordinator_for(
        scanner=ControlledScanner(release=release),
        thread_factory=threads,
        join_timeout=0.05,
    )
    coordinator.start(folder_request(book(tmp_path)))
    close = coordinator.close()

    assert close.worker_stopped is False
    release.set()
    threads.made[0].join(WAIT)
    assert not threads.made[0].is_alive()


def test_events_published_during_a_close_cannot_mutate_the_manager(tmp_path):
    manager = ImportedFileManager()
    threads = RealThreads()
    coordinator = coordinator_for(manager, thread_factory=threads)
    coordinator.start(folder_request(book(tmp_path)))
    threads.made[0].join(WAIT)  # a whole completed result is sitting on the queue

    close = coordinator.close()

    assert close.discarded_events >= 1
    assert manager.count == 0
    assert coordinator.pump().status is OutcomeStatus.CLOSED
    assert manager.count == 0


def test_closing_while_a_confirmation_is_pending_discards_it(tmp_path):
    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)
    run_to_completion(coordinator, folder_request(book(tmp_path), threshold=1))

    close = coordinator.close()
    assert close.discarded_transaction is True
    assert manager.count == 0
    assert coordinator.pending_transaction is None


def test_no_worker_or_poller_survives_a_close(tmp_path):
    baseline = threading.active_count()
    scheduler = FakeScheduler()
    threads = RealThreads()
    coordinator = coordinator_for(thread_factory=threads)
    poller = ImportPoller(coordinator, scheduler, cancel=scheduler.cancel)
    poller.start()
    coordinator.start(folder_request(book(tmp_path)))
    threads.made[0].join(WAIT)

    poller.close()

    assert scheduler.pending == 0
    assert poller.closed and not poller.running
    assert threading.active_count() == baseline


# --------------------------------------------------------------------------- #
# The polling seam — a scheduler, never a widget
# --------------------------------------------------------------------------- #


def test_a_poller_schedules_exactly_one_callback_at_a_time(tmp_path):
    scheduler = FakeScheduler()
    coordinator = coordinator_for()
    poller = ImportPoller(coordinator, scheduler, cancel=scheduler.cancel)

    assert poller.start() is True
    assert scheduler.pending == 1
    assert poller.start() is False, "starting twice must not double the schedule"
    assert scheduler.pending == 1

    scheduler.run_next()
    assert scheduler.pending == 1, "one tick, one reschedule"


def test_a_poller_drains_the_coordinator_and_reports_outcomes(tmp_path):
    scheduler = FakeScheduler()
    manager = ImportedFileManager()
    seen: list[ImportOutcome] = []
    coordinator = coordinator_for(manager)
    poller = ImportPoller(
        coordinator, scheduler, cancel=scheduler.cancel, on_outcome=seen.append)
    poller.start()
    coordinator.start(folder_request(book(tmp_path)))

    scheduler.run_next()

    assert [outcome.status for outcome in seen] == [OutcomeStatus.COMMITTED]
    assert manager.count == 3


def test_a_stopped_poller_stops_rescheduling(tmp_path):
    scheduler = FakeScheduler()
    coordinator = coordinator_for()
    poller = ImportPoller(coordinator, scheduler, cancel=scheduler.cancel)
    poller.start()

    poller.stop()
    assert poller.running is False
    assert scheduler.pending == 0
    assert scheduler.cancelled == ["after-1"]
    poller.stop()  # idempotent
    assert scheduler.pending == 0


def test_a_callback_that_fires_after_a_stop_touches_nothing(tmp_path):
    scheduler = FakeScheduler()
    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)
    poller = ImportPoller(coordinator, scheduler)  # no cancel available, as with a
    poller.start()                                 # destroyed widget's pending after
    coordinator.start(folder_request(book(tmp_path)))
    poller.stop()

    outcome = scheduler.run_next()

    assert outcome.status is OutcomeStatus.IDLE
    assert manager.count == 0, "the late callback drained nothing"
    assert scheduler.pending == 0


def test_a_callback_that_fires_after_a_close_touches_nothing(tmp_path):
    scheduler = FakeScheduler()
    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)
    poller = ImportPoller(coordinator, scheduler)
    poller.start()
    poller.close()

    outcome = scheduler.run_next()
    assert outcome.status is OutcomeStatus.CLOSED
    assert manager.count == 0


def test_closing_a_poller_closes_its_coordinator_and_is_idempotent():
    scheduler = FakeScheduler()
    coordinator = coordinator_for()
    poller = ImportPoller(coordinator, scheduler, cancel=scheduler.cancel)
    poller.start()

    report = poller.close()
    assert isinstance(report, CloseReport) and report.closed
    assert coordinator.is_closed
    assert poller.close().closed
    assert scheduler.pending == 0


def test_an_outcome_callback_may_stop_the_poller_from_inside_a_tick(tmp_path):
    scheduler = FakeScheduler()
    coordinator = coordinator_for()
    poller = ImportPoller(coordinator, scheduler, cancel=scheduler.cancel)
    poller._on_outcome = lambda outcome: poller.stop()
    poller.start()

    scheduler.run_next()

    assert poller.running is False
    assert scheduler.pending == 0, "a stop inside the tick is not undone by rescheduling"


def test_a_poller_will_not_restart_after_being_closed():
    scheduler = FakeScheduler()
    poller = ImportPoller(coordinator_for(), scheduler, cancel=scheduler.cancel)
    poller.close()
    assert poller.start() is False
    assert scheduler.pending == 0


def test_a_poller_needs_a_real_coordinator_and_a_callable_scheduler():
    with pytest.raises(ImportCoordinationError, match="must be an ImportCoordinator"):
        ImportPoller(object(), FakeScheduler())
    with pytest.raises(ImportCoordinationError, match="must be callable"):
        ImportPoller(coordinator_for(), None)
    with pytest.raises(ImportCoordinationError, match="interval_ms"):
        ImportPoller(coordinator_for(), FakeScheduler(), interval_ms=0)


def test_the_poller_passes_its_interval_to_the_scheduler():
    scheduler = FakeScheduler()
    poller = ImportPoller(coordinator_for(), scheduler, interval_ms=250)
    poller.start()
    assert scheduler.queued[0][1] == 250
    poller.stop()


# --------------------------------------------------------------------------- #
# Safety and boundaries
# --------------------------------------------------------------------------- #


def test_an_import_never_modifies_a_source_file(tmp_path):
    root = book(tmp_path, "Book", "01.mp3", "02.mp3")
    extra = touch(tmp_path / "loose.mp3", "kept")
    before = snapshot_tree(tmp_path)

    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)
    run_to_completion(coordinator, folder_request(root))
    coordinator.import_files(direct_request(), [extra])
    manager.select([entry.occurrence_id for entry in manager.snapshot().files])
    manager.remove_selected()
    manager.clear()
    coordinator.close()

    assert manager.count == 0
    assert snapshot_tree(tmp_path) == before
    assert extra.read_text(encoding="utf-8") == "kept"


def test_the_coordinator_creates_no_output_directory(tmp_path):
    outputs = tmp_path / "Audiobook Creation Tool"
    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)
    run_to_completion(coordinator, folder_request(book(tmp_path)))
    coordinator.close()
    assert not outputs.exists()


def test_a_link_is_still_refused_through_the_coordinator(tmp_path, monkeypatch):
    """Phase 2's refusal is not weakened by running the scan on a worker."""
    root = book(tmp_path, "Book", "real.mp3")
    fake = root / "shortcut.mp3"
    fake.write_text("x", encoding="utf-8")
    monkeypatch.setattr(
        "shared.importing._is_link", lambda path: Path(path).name == "shortcut.mp3")

    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)
    outcome = run_to_completion(coordinator, folder_request(root))

    assert names_in(manager) == ["real.mp3"]
    assert ProblemCategory.LINK in {problem.category for problem in outcome.problems}


def test_hidden_folder_policy_is_carried_through_unchanged(tmp_path):
    root = tmp_path / "Book"
    touch(root / "01.mp3")
    touch(root / ".secret" / "02.mp3")

    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)
    run_to_completion(coordinator, folder_request(root))
    assert names_in(manager) == ["01.mp3"]

    manager2 = ImportedFileManager()
    coordinator2 = coordinator_for(manager2)
    run_to_completion(
        coordinator2, folder_request(root, hidden=True, request_id="req-2"))
    assert sorted(names_in(manager2)) == ["01.mp3", "02.mp3"]


def test_root_order_is_never_globally_resorted(tmp_path):
    second = book(tmp_path, "Zebra", "a.mp3")
    first = book(tmp_path, "Alpha", "b.mp3")
    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)
    run_to_completion(coordinator, folder_request(second, first))
    assert names_in(manager) == ["a.mp3", "b.mp3"]


def test_the_coordinator_starts_no_subprocess_and_reads_no_config(tmp_path, monkeypatch):
    def explode(*args, **kwargs):  # pragma: no cover - the assertion is that it is unused
        raise AssertionError("coordination must not reach this")

    monkeypatch.setattr("shared.config.load", explode)
    monkeypatch.setattr("shared.config.get_effective", explode)

    manager = ImportedFileManager()
    coordinator = coordinator_for(manager)
    outcome = run_to_completion(coordinator, folder_request(book(tmp_path)))
    coordinator.close()
    assert outcome.status is OutcomeStatus.COMMITTED


def test_an_end_to_end_import_keeps_every_rule_at_once(tmp_path):
    """One pass over the whole phase: warn, scan, count, confirm, commit, close."""
    home = tmp_path / "home"
    library = tmp_path / "Library"
    touch(library / "Disc 1" / "10.mp3")
    touch(library / "Disc 1" / "2.mp3")
    touch(library / "Disc 1" / "1.mp3")
    touch(library / "notes.txt")
    touch(library / ".hidden" / "skipped.mp3")
    loose = touch(tmp_path / "bonus.mp3")
    before = snapshot_tree(tmp_path)

    manager = ImportedFileManager()
    asked: list = []
    threads = RecordingThreads()
    coordinator = coordinator_for(
        manager,
        thread_factory=threads,
        home=home,
        confirm_broad_root=lambda roots: asked.append(roots) or False,
    )

    # 1. The home folder is refused before anything is scanned.
    assert coordinator.start(folder_request(home)).outcome is StartOutcome.DECLINED_BROAD_ROOT
    assert asked == [(home,)]
    assert threads.made == []

    # 2. A narrow root scans, proposes three, and asks because the threshold is two.
    outcome = run_to_completion(coordinator, folder_request(library, threshold=2))
    assert outcome.status is OutcomeStatus.AWAITING_CONFIRMATION
    assert outcome.proposed_count == 3
    assert manager.count == 0

    # 3. Accepting commits once, in natural order, with every skip reported.
    committed = coordinator.confirm_pending()
    assert committed.status is OutcomeStatus.COMMITTED
    assert names_in(manager) == ["1.mp3", "2.mp3", "10.mp3"]
    categories = {problem.category for problem in committed.problems}
    assert ProblemCategory.UNSUPPORTED_TYPE in categories
    assert ProblemCategory.HIDDEN in categories

    # 4. Add Files appends in the user's own order, on this thread.
    assert coordinator.import_files(
        direct_request(), [loose]).status is OutcomeStatus.COMMITTED
    assert names_in(manager)[-1] == "bonus.mp3"

    # 5. Re-importing the same folder adds nothing and says why.
    again = run_to_completion(
        coordinator, folder_request(library, threshold=2, request_id="req-again"))
    assert again.status is OutcomeStatus.NOTHING_ADDED
    assert manager.count == 4

    # 6. Closing is clean, and nothing on disk moved at any point.
    assert coordinator.close().worker_stopped
    assert snapshot_tree(tmp_path) == before
