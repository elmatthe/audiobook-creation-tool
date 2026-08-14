"""Typed events, Summary/Details, progress and rolling ETA — Drop 3 (Plan 3), Phase 7.

Every test here is pure. Nothing starts a thread, opens a display, converts
anything, creates an output or writes a log file: the clock is injected, the queue is
a list, the logger is a recorder, and the one filesystem-shaped value is a path that
is named and never opened.

The phase's claim is that a run can be *reported* truthfully. Most of what follows is
an attempt to make it lie — report a state the controller never reached, cancel
before the worker acknowledged, land an event from a finished run, flood the Summary
with a traceback, invent a total, count a paused hour as work — and check that each
attempt is refused rather than rendered.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest

from shared import job_control, logging_setup
from shared.importing import (
    ImportedFile,
    ImportedFileSnapshot,
    ImportOptions,
    ImportRoot,
    SupportedType,
    SupportedTypeCatalog,
)
from shared.job_control import (
    CALCULATING,
    DEFAULT_MINIMUM_SAMPLES,
    DEFAULT_SAMPLE_WINDOW,
    SUMMARY_KINDS,
    EtaEstimator,
    EventVerdict,
    JobContractError,
    JobEvent,
    JobEventKind,
    JobEventStream,
    JobReporter,
    JobSnapshot,
    JobState,
    LoggerBridge,
    ProgressMode,
    ProgressTracker,
    ProgressView,
    SummaryView,
    capture_run,
    detail_lines,
    format_duration,
    project_summary,
    state_message,
    summary_lines,
)

from test_importing import make_config

SHARED = Path(__file__).resolve().parent.parent.parent / "scripts" / "Universal" / "shared"

RUN = "run-1"
OTHER_RUN = "run-2"


# --------------------------------------------------------------------------- #
# Fixtures: an injected clock, a list for a queue, a logger that only records
# --------------------------------------------------------------------------- #


class FakeClock:
    """A monotonic clock that moves only when a test says so."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = float(start)
        self.reads = 0

    def __call__(self) -> float:
        self.reads += 1
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += float(seconds)
        return self.now

    def set(self, value: float) -> float:
        self.now = float(value)
        return self.now


class RecordingLogger:
    """Stands in for the session logger. Records; never opens a file."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    def _record(self, level: str):
        def call(*args, **kwargs) -> None:
            self.calls.append((level, args))
        return call

    def __getattr__(self, name: str):
        if name in ("debug", "info", "warning", "error", "exception", "critical"):
            return self._record(name)
        raise AttributeError(name)

    @property
    def levels(self) -> list[str]:
        return [level for level, _ in self.calls]

    @property
    def messages(self) -> list[str]:
        return [args[0] % args[1:] if len(args) > 1 else args[0] for _, args in self.calls]


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def recorder() -> RecordingLogger:
    return RecordingLogger()


def catalog() -> SupportedTypeCatalog:
    return SupportedTypeCatalog((
        SupportedType("mp3", "MP3 audio", (".mp3",)),
    ))


def occurrence(index: int, *, name: str = "") -> ImportedFile:
    """One imported occurrence. Only ever named — never created on disk."""
    label = name or f"{index:02d}.mp3"
    home = ImportRoot(
        "root-0", Path("C:/Books") if Path("C:/").is_absolute() else Path("/Books"), 0)
    return ImportedFile(
        occurrence_id=f"occ-{index:06d}",
        path=home.path / label,
        source_root=home,
        relative_path=Path(label),
        supported_type_id="mp3",
        identity=f"file:1:{index}",
    )


def run_snapshot(count: int = 3, *, snapshot_id: str = RUN):
    from shared.importing import Revision

    return capture_run(
        snapshot_id=snapshot_id,
        files=ImportedFileSnapshot(
            revision=Revision(1),
            files=tuple(occurrence(index) for index in range(1, count + 1)),
        ),
        catalog=catalog(),
        import_options=ImportOptions.for_catalog(catalog()),
        effective_config=make_config(1000),
        created_at=1.0,
    )


ITEMS = tuple(f"occ-{index:06d}" for index in range(1, 4))


def state_snapshot(state: JobState, *, run_id: str = RUN, revision: int = 1) -> JobSnapshot:
    """A controller snapshot in *state*, with the companion flags its invariants need."""
    paused = state in (JobState.PAUSE_REQUESTED, JobState.PAUSED)
    cancel_requested = state in (JobState.CANCEL_REQUESTED, JobState.CANCELLED)
    return JobSnapshot(
        run_id=run_id,
        state=state,
        revision=revision,
        pause_requested=paused,
        cancel_requested=cancel_requested,
        cancel_acknowledged=state is JobState.CANCELLED,
        failure_message="The run failed." if state is JobState.FAILED else "",
    )


def reporter(clock: FakeClock, *, run_id: str = RUN, publish=None, items=ITEMS) -> JobReporter:
    return JobReporter(run_id, clock=clock, publish=publish, item_ids=items)


def stream(*, run_id: str = RUN, items=ITEMS, bridge=None) -> JobEventStream:
    return JobEventStream(run_id, item_ids=items, bridge=bridge)


def event(kind: JobEventKind, *, run_id: str = RUN, sequence: int = 0, **kwargs) -> JobEvent:
    return JobEvent(kind=kind, run_id=run_id, sequence=sequence, timestamp=0.0, **kwargs)


# --------------------------------------------------------------------------- #
# The Phase 1 event vocabulary was not rewritten
# --------------------------------------------------------------------------- #


def test_the_event_kinds_are_exactly_the_eleven_phase_one_froze():
    assert [kind.value for kind in JobEventKind] == [
        "state_changed", "stage_changed", "progress", "current_item", "import_count",
        "warning", "failure", "output_location", "completed", "cancelled",
        "technical_detail",
    ]
    assert len(JobEventKind) == 11


def test_the_event_fields_are_exactly_the_phase_one_ones():
    assert JobEvent.__slots__ == (
        "kind", "run_id", "sequence", "timestamp", "message", "detail", "state",
        "stage", "item_id", "completed", "total", "count", "location")


def test_the_terminal_event_kinds_are_unchanged():
    assert job_control.TERMINAL_EVENT_KINDS == frozenset(
        {JobEventKind.COMPLETED, JobEventKind.CANCELLED})


def test_phase_seven_added_no_event_kind_field_or_parallel_event_type():
    """The reporting layer *uses* the frozen vocabulary; it never grows a second one."""
    for invented in ("JobEventKind2", "Event", "EventRecord", "ProgressEvent",
                     "EtaEvent", "SummaryEvent", "Severity", "EventSeverity"):
        assert not hasattr(job_control, invented), invented


def test_an_event_is_still_immutable():
    entry = event(JobEventKind.WARNING, message="Careful.")
    with pytest.raises(Exception):
        entry.message = "Changed."
    assert not hasattr(entry, "__dict__")


def test_an_event_still_refuses_a_non_finite_timestamp():
    for bad in (float("nan"), float("inf"), -1.0):
        with pytest.raises(JobContractError):
            JobEvent(kind=JobEventKind.WARNING, run_id=RUN, sequence=0,
                     timestamp=bad, message="Careful.")


def test_an_event_still_refuses_a_traceback_in_the_user_facing_message():
    with pytest.raises(JobContractError):
        JobEvent(kind=JobEventKind.WARNING, run_id=RUN, sequence=0, timestamp=0.0,
                 message="Traceback (most recent call last):")


def test_the_detail_field_is_still_unrestricted():
    entry = event(JobEventKind.TECHNICAL_DETAIL,
                  detail="Traceback (most recent call last):\n  File x\nBoom")
    assert "Traceback" in entry.detail


# --------------------------------------------------------------------------- #
# Production: the reporter
# --------------------------------------------------------------------------- #


def test_the_reporter_numbers_events_from_zero_in_producer_order(clock):
    rep = reporter(clock)
    produced = [
        rep.stage_changed("scan"),
        rep.progress(1, 3),
        rep.warning("A file was skipped."),
    ]
    assert [entry.sequence for entry in produced] == [0, 1, 2]


def test_every_reported_event_carries_the_reporters_run(clock):
    rep = reporter(clock)
    for entry in (rep.stage_changed("scan"), rep.progress(0, 1), rep.technical("x")):
        assert entry.run_id == RUN


def test_the_reporter_timestamps_from_the_injected_clock(clock):
    rep = reporter(clock)
    first = rep.stage_changed("scan")
    clock.advance(2.5)
    second = rep.stage_changed("convert")
    assert (first.timestamp, second.timestamp) == (0.0, 2.5)


def test_the_reporter_reads_the_clock_once_per_event(clock):
    rep = reporter(clock)
    rep.stage_changed("scan")
    rep.stage_changed("convert")
    assert clock.reads == 2


def test_the_reporter_publishes_to_the_queue_it_was_given(clock):
    queue: list[JobEvent] = []
    rep = reporter(clock, publish=queue.append)
    rep.stage_changed("scan")
    rep.progress(1, 2)
    assert [entry.kind for entry in queue] == [
        JobEventKind.STAGE_CHANGED, JobEventKind.PROGRESS]


def test_the_reporter_without_a_publisher_simply_returns_the_event(clock):
    rep = reporter(clock)
    assert isinstance(rep.stage_changed("scan"), JobEvent)


def test_the_reporter_refuses_a_blank_run_id(clock):
    with pytest.raises(JobContractError):
        JobReporter("   ", clock=clock)


def test_the_reporter_refuses_a_clock_that_is_not_callable():
    with pytest.raises(JobContractError):
        JobReporter(RUN, clock=object())


def test_the_reporter_refuses_a_publisher_that_is_not_callable(clock):
    with pytest.raises(JobContractError):
        JobReporter(RUN, clock=clock, publish=object())


def test_the_reporter_allocates_a_unique_sequence_under_concurrency(clock):
    """One run, several reporting threads, no two events sharing a number."""
    import threading

    rep = reporter(clock)
    produced: list[JobEvent] = []
    guard = threading.Lock()
    ready = threading.Barrier(4)

    def produce() -> None:
        ready.wait(timeout=5)
        for _ in range(25):
            entry = rep.technical("detail")
            with guard:
                produced.append(entry)

    threads = [threading.Thread(target=produce) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive(), "a reporting thread did not finish"

    numbers = sorted(entry.sequence for entry in produced)
    assert numbers == list(range(100)), "every event got its own number"


# --------------------------------------------------------------------------- #
# Production: state-bearing events are minted from the controller's own snapshot
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("state", list(JobState))
def test_a_state_event_carries_the_state_the_controller_was_actually_in(clock, state):
    rep = reporter(clock)
    entry = rep.state_changed(state_snapshot(state))
    assert entry.kind is JobEventKind.STATE_CHANGED
    assert entry.state is state


def test_a_state_event_cannot_be_minted_from_a_bare_state(clock):
    """The authority is the controller, so the argument is its snapshot, not a guess."""
    rep = reporter(clock)
    with pytest.raises(JobContractError):
        rep.state_changed(JobState.PAUSED)


def test_a_state_event_from_another_run_is_refused_at_production(clock):
    rep = reporter(clock)
    with pytest.raises(JobContractError):
        rep.state_changed(state_snapshot(JobState.RUNNING, run_id=OTHER_RUN))


def test_a_pause_that_was_only_requested_reports_pause_requested(clock):
    """§6.10: the truthful state while an indivisible stage keeps running."""
    rep = reporter(clock)
    entry = rep.state_changed(state_snapshot(JobState.PAUSE_REQUESTED))
    assert entry.state is JobState.PAUSE_REQUESTED
    assert entry.message == "Pause requested."


def test_a_pause_cannot_be_fabricated_while_the_stage_is_still_running(clock):
    """There is no way to say PAUSED without a snapshot that says PAUSED."""
    rep = reporter(clock)
    requested = state_snapshot(JobState.PAUSE_REQUESTED)
    assert requested.pause_pending and not requested.is_paused
    entry = rep.state_changed(requested)
    assert entry.state is not JobState.PAUSED


def test_cancelled_cannot_be_reported_before_the_worker_acknowledged(clock):
    """A CANCEL_REQUESTED snapshot is not a cancellation, and cannot mint one."""
    rep = reporter(clock)
    with pytest.raises(JobContractError):
        rep.cancelled(state_snapshot(JobState.CANCEL_REQUESTED))


def test_cancelled_is_reported_from_an_acknowledged_snapshot(clock):
    rep = reporter(clock)
    entry = rep.cancelled(state_snapshot(JobState.CANCELLED))
    assert entry.kind is JobEventKind.CANCELLED
    assert entry.state is JobState.CANCELLED
    assert entry.is_terminal


def test_a_cancelled_snapshot_can_never_lack_acknowledgement():
    """The Phase 5 invariant the reporter leans on, restated from this side."""
    with pytest.raises(JobContractError):
        JobSnapshot(run_id=RUN, state=JobState.CANCELLED, cancel_requested=True,
                    cancel_acknowledged=False)


@pytest.mark.parametrize("state", [
    JobState.SUCCEEDED, JobState.COMPLETED_WITH_FAILURES, JobState.FAILED])
def test_completion_is_reported_from_an_ending_snapshot(clock, state):
    rep = reporter(clock)
    entry = rep.completed(state_snapshot(state))
    assert entry.kind is JobEventKind.COMPLETED
    assert entry.state is state
    assert entry.is_terminal


@pytest.mark.parametrize("state", [
    JobState.IDLE, JobState.RUNNING, JobState.PAUSE_REQUESTED, JobState.PAUSED,
    JobState.CANCEL_REQUESTED, JobState.CANCELLED])
def test_completion_is_refused_for_a_run_that_has_not_ended(clock, state):
    rep = reporter(clock)
    with pytest.raises(JobContractError):
        rep.completed(state_snapshot(state))


def test_a_failed_completion_carries_the_controllers_own_failure_message(clock):
    rep = reporter(clock)
    entry = rep.completed(state_snapshot(JobState.FAILED))
    assert entry.message == "The run failed."


def test_a_completion_message_may_be_supplied_explicitly(clock):
    rep = reporter(clock)
    entry = rep.completed(state_snapshot(JobState.SUCCEEDED), message="All 3 files done.")
    assert entry.message == "All 3 files done."


def test_cancellation_is_refused_for_any_other_state(clock):
    rep = reporter(clock)
    for state in JobState:
        if state is JobState.CANCELLED:
            continue
        with pytest.raises(JobContractError):
            rep.cancelled(state_snapshot(state))


# --------------------------------------------------------------------------- #
# Production: item-scoped events bind to a real occurrence
# --------------------------------------------------------------------------- #


def test_a_current_item_event_names_an_occurrence_from_this_run(clock):
    rep = reporter(clock)
    entry = rep.current_item(ITEMS[1])
    assert entry.kind is JobEventKind.CURRENT_ITEM
    assert entry.item_id == ITEMS[1]


def test_a_current_item_event_refuses_an_occurrence_this_run_never_had(clock):
    rep = reporter(clock)
    with pytest.raises(JobContractError):
        rep.current_item("occ-999999")


def test_an_item_failure_refuses_a_foreign_occurrence(clock):
    rep = reporter(clock)
    with pytest.raises(JobContractError):
        rep.failure("It broke.", item_id="occ-999999")


def test_progress_refuses_a_foreign_occurrence(clock):
    rep = reporter(clock)
    with pytest.raises(JobContractError):
        rep.progress(1, 3, item_id="occ-999999")


def test_a_reporter_without_an_item_list_binds_nothing(clock):
    """Not every adopter has a snapshot yet; the binding is optional, never invented."""
    rep = JobReporter(RUN, clock=clock, item_ids=None)
    assert rep.current_item("occ-999999").item_id == "occ-999999"


def test_the_reporter_takes_its_items_from_a_run_snapshot(clock):
    rep = JobReporter.for_run(run_snapshot(), clock=clock)
    assert rep.run_id == RUN
    assert rep.current_item(ITEMS[0]).item_id == ITEMS[0]
    with pytest.raises(JobContractError):
        rep.current_item("occ-999999")


def test_two_deliberate_duplicates_of_one_path_stay_distinct_occurrences(clock):
    """§6.5's explicit duplicate override, followed all the way into reporting."""
    from shared.importing import Revision

    first = occurrence(1)
    second = ImportedFile(
        occurrence_id="occ-000009",
        path=first.path,
        source_root=first.source_root,
        relative_path=first.relative_path,
        supported_type_id=first.supported_type_id,
        identity=first.identity,
    )
    assert first.path == second.path and first.identity == second.identity
    snap = capture_run(
        snapshot_id=RUN,
        files=ImportedFileSnapshot(revision=Revision(1), files=(first, second)),
        catalog=catalog(),
        import_options=ImportOptions.for_catalog(catalog()),
        effective_config=make_config(1000),
        created_at=1.0,
    )
    rep = JobReporter.for_run(snap, clock=clock)
    events = [rep.current_item(first.occurrence_id), rep.current_item(second.occurrence_id)]
    assert [entry.item_id for entry in events] == ["occ-000001", "occ-000009"]

    flow = stream(items=snap.item_ids)
    assert [flow.accept(entry) for entry in events] == [
        EventVerdict.ACCEPTED, EventVerdict.ACCEPTED]
    tracker = ProgressTracker()
    for entry in events:
        tracker.apply(entry)
    assert tracker.current_item_id == "occ-000009"


# --------------------------------------------------------------------------- #
# Production: the remaining kinds
# --------------------------------------------------------------------------- #


def test_a_stage_event_carries_the_stage(clock):
    entry = reporter(clock).stage_changed("convert")
    assert (entry.kind, entry.stage) == (JobEventKind.STAGE_CHANGED, "convert")


def test_a_progress_event_with_a_known_total(clock):
    entry = reporter(clock).progress(2, 5)
    assert (entry.completed, entry.total) == (2, 5)


def test_a_progress_event_with_an_unknown_total(clock):
    entry = reporter(clock).progress(2)
    assert (entry.completed, entry.total) == (2, None)


def test_a_progress_event_refuses_to_exceed_its_total(clock):
    with pytest.raises(JobContractError):
        reporter(clock).progress(6, 5)


def test_an_import_count_event_carries_the_count(clock):
    entry = reporter(clock).import_count(42)
    assert (entry.kind, entry.count) == (JobEventKind.IMPORT_COUNT, 42)


def test_a_warning_event_requires_a_user_facing_message(clock):
    with pytest.raises(JobContractError):
        reporter(clock).warning("")


def test_a_failure_event_requires_a_user_facing_message(clock):
    with pytest.raises(JobContractError):
        reporter(clock).failure("")


def test_a_failure_event_keeps_its_diagnostic_in_detail(clock):
    entry = reporter(clock).failure(
        "The chapter could not be converted.",
        detail="Traceback (most recent call last):\n  ffmpeg exited 1")
    assert entry.message == "The chapter could not be converted."
    assert "Traceback" in entry.detail


def test_an_output_location_event_reports_only_what_it_was_given(clock, tmp_path):
    """It names a location. It does not create, reserve, inspect or validate one."""
    destination = tmp_path / "never-created"
    entry = reporter(clock).output_location(destination)
    assert entry.location == destination
    assert not destination.exists(), "reporting a location must not create it"


def test_an_output_location_event_refuses_a_relative_path(clock):
    with pytest.raises(JobContractError):
        reporter(clock).output_location(Path("relative/place"))


def test_a_technical_event_requires_detail(clock):
    with pytest.raises(JobContractError):
        reporter(clock).technical("   ")


def test_a_technical_event_carries_no_user_facing_message(clock):
    entry = reporter(clock).technical("ffmpeg -i in.mp3 out.m4b")
    assert entry.message == ""
    assert entry.detail == "ffmpeg -i in.mp3 out.m4b"


def test_the_reporter_defines_one_method_per_event_kind(clock):
    rep = reporter(clock)
    produced = {
        rep.state_changed(state_snapshot(JobState.RUNNING)).kind,
        rep.stage_changed("scan").kind,
        rep.progress(0, 1).kind,
        rep.current_item(ITEMS[0]).kind,
        rep.import_count(1).kind,
        rep.warning("Careful.").kind,
        rep.failure("Broke.").kind,
        rep.output_location(Path("C:/out").absolute()).kind,
        rep.completed(state_snapshot(JobState.SUCCEEDED)).kind,
        rep.technical("detail").kind,
    }
    produced.add(JobReporter(OTHER_RUN, clock=clock).cancelled(
        state_snapshot(JobState.CANCELLED, run_id=OTHER_RUN)).kind)
    assert produced == set(JobEventKind)


# --------------------------------------------------------------------------- #
# The stream: run binding, ordering, staleness, exactly one ending
# --------------------------------------------------------------------------- #


def test_the_stream_accepts_events_from_its_own_run(clock):
    flow, rep = stream(), reporter(clock)
    assert flow.accept(rep.stage_changed("scan")) is EventVerdict.ACCEPTED
    assert len(flow.events) == 1


def test_the_stream_rejects_an_event_from_another_run(clock):
    flow = stream()
    foreign = JobReporter(OTHER_RUN, clock=clock).stage_changed("scan")
    assert flow.accept(foreign) is EventVerdict.STALE_RUN
    assert flow.events == ()


def test_a_rejected_stale_event_reaches_neither_the_log_nor_the_projection(
        clock, recorder):
    flow = stream(bridge=LoggerBridge(logger=recorder))
    foreign = JobReporter(OTHER_RUN, clock=clock).failure("Broke.", detail="stack")
    assert flow.accept(foreign) is EventVerdict.STALE_RUN
    assert recorder.calls == []
    assert summary_lines(flow.events) == ()
    assert detail_lines(flow.events) == ()


def test_the_stream_rejects_an_item_this_run_never_had(clock):
    flow = stream()
    loose = JobReporter(RUN, clock=clock).current_item("occ-999999")
    assert flow.accept(loose) is EventVerdict.UNKNOWN_ITEM
    assert flow.events == ()


def test_the_stream_without_an_item_list_binds_nothing(clock):
    flow = JobEventStream(RUN, item_ids=None)
    loose = JobReporter(RUN, clock=clock).current_item("occ-999999")
    assert flow.accept(loose) is EventVerdict.ACCEPTED


def test_the_stream_keeps_producer_order(clock):
    flow, rep = stream(), reporter(clock)
    for index in range(5):
        flow.accept(rep.progress(index, 5))
    assert [entry.sequence for entry in flow.events] == [0, 1, 2, 3, 4]


def test_the_stream_rejects_a_repeated_sequence_number(clock):
    flow = stream()
    first = event(JobEventKind.WARNING, sequence=3, message="One.")
    again = event(JobEventKind.WARNING, sequence=3, message="Two.")
    assert flow.accept(first) is EventVerdict.ACCEPTED
    assert flow.accept(again) is EventVerdict.OUT_OF_ORDER


def test_the_stream_rejects_a_sequence_that_went_backwards(clock):
    flow = stream()
    flow.accept(event(JobEventKind.WARNING, sequence=5, message="Later."))
    assert flow.accept(
        event(JobEventKind.WARNING, sequence=4, message="Earlier.")) is (
            EventVerdict.OUT_OF_ORDER)


def test_a_gap_in_the_sequence_is_not_an_error(clock):
    """A bounded drain legitimately sees 0, 1, 2 now and 3, 4 next time."""
    flow = stream()
    flow.accept(event(JobEventKind.WARNING, sequence=0, message="One."))
    assert flow.accept(
        event(JobEventKind.WARNING, sequence=9, message="Nine.")) is EventVerdict.ACCEPTED


def test_exactly_one_terminal_event_is_accepted(clock):
    flow, rep = stream(), reporter(clock)
    assert flow.accept(rep.completed(state_snapshot(JobState.SUCCEEDED))) is (
        EventVerdict.ACCEPTED)
    assert flow.is_closed
    assert flow.terminal is not None


def test_a_second_terminal_event_is_refused(clock):
    flow, rep = stream(), reporter(clock)
    flow.accept(rep.completed(state_snapshot(JobState.SUCCEEDED)))
    assert flow.accept(rep.completed(state_snapshot(JobState.SUCCEEDED))) is (
        EventVerdict.DUPLICATE_TERMINAL)
    assert len(flow.events) == 1


def test_a_cancellation_after_a_completion_is_refused(clock):
    flow, rep = stream(), reporter(clock)
    flow.accept(rep.completed(state_snapshot(JobState.SUCCEEDED)))
    assert flow.accept(rep.cancelled(state_snapshot(JobState.CANCELLED))) is (
        EventVerdict.DUPLICATE_TERMINAL)


def test_an_ordinary_event_after_the_ending_is_refused(clock):
    flow, rep = stream(), reporter(clock)
    flow.accept(rep.completed(state_snapshot(JobState.SUCCEEDED)))
    assert flow.accept(rep.progress(3, 3)) is EventVerdict.AFTER_TERMINAL
    assert len(flow.events) == 1


def test_a_post_terminal_event_reaches_neither_the_log_nor_the_projection(clock, recorder):
    flow = stream(bridge=LoggerBridge(logger=recorder))
    rep = reporter(clock)
    flow.accept(rep.completed(state_snapshot(JobState.SUCCEEDED)))
    recorder.calls.clear()
    assert flow.accept(rep.failure("Too late.", detail="stack")) is (
        EventVerdict.AFTER_TERMINAL)
    assert recorder.calls == []
    assert not any("Too late." in line for line in summary_lines(flow.events))
    assert not any("Too late." in line for line in detail_lines(flow.events))


def test_the_stream_records_why_it_rejected_each_event(clock):
    flow = stream()
    foreign = JobReporter(OTHER_RUN, clock=clock).stage_changed("scan")
    flow.accept(foreign)
    assert [verdict for _, verdict in flow.rejected] == [EventVerdict.STALE_RUN]


def test_the_stream_refuses_something_that_is_not_an_event():
    with pytest.raises(JobContractError):
        stream().accept("state_changed")


def test_the_stream_is_bound_to_one_run_id():
    with pytest.raises(JobContractError):
        JobEventStream("   ")


def test_the_stream_takes_its_binding_from_a_run_snapshot(clock):
    flow = JobEventStream.for_run(run_snapshot())
    assert flow.run_id == RUN
    loose = JobReporter(RUN, clock=clock).current_item("occ-999999")
    assert flow.accept(loose) is EventVerdict.UNKNOWN_ITEM


# --------------------------------------------------------------------------- #
# Draining: deterministic, bounded, and never a timing assumption
# --------------------------------------------------------------------------- #


def test_draining_an_empty_source_accepts_nothing():
    flow = stream()
    assert flow.drain(()) == ()
    assert flow.events == ()


def test_draining_an_iterable_preserves_order(clock):
    rep = reporter(clock)
    queued = [rep.stage_changed("scan"), rep.progress(1, 3), rep.progress(2, 3)]
    flow = stream()
    assert flow.drain(queued) == (EventVerdict.ACCEPTED,) * 3
    assert [entry.sequence for entry in flow.events] == [0, 1, 2]


def test_a_bounded_drain_takes_only_its_limit(clock):
    rep = reporter(clock)
    queued = [rep.progress(index, 9) for index in range(9)]
    flow = stream()
    assert len(flow.drain(queued, limit=4)) == 4
    assert len(flow.events) == 4


def test_a_bounded_drain_refuses_a_nonsense_limit():
    with pytest.raises(JobContractError):
        stream().drain((), limit=0)
    with pytest.raises(JobContractError):
        stream().drain((), limit=-1)


def test_pumping_pulls_until_the_source_is_empty(clock):
    rep = reporter(clock)
    queued = [rep.progress(index, 3) for index in range(3)]
    flow = stream()

    def pull():
        return queued.pop(0) if queued else None

    assert flow.pump(pull) == (EventVerdict.ACCEPTED,) * 3
    assert queued == []


def test_pumping_stops_at_its_limit_and_leaves_the_rest(clock):
    rep = reporter(clock)
    queued = [rep.progress(index, 9) for index in range(9)]
    flow = stream()

    def pull():
        return queued.pop(0) if queued else None

    assert len(flow.pump(pull, limit=3)) == 3
    assert len(queued) == 6, "the rest waits for the next pump; nothing is dropped"


def test_pumping_never_blocks_on_an_empty_source():
    flow = stream()
    assert flow.pump(lambda: None) == ()


def test_pumping_refuses_a_source_that_is_not_callable():
    with pytest.raises(JobContractError):
        stream().pump(object())


def test_a_drain_reports_every_verdict_including_the_rejections(clock):
    rep = reporter(clock)
    foreign = JobReporter(OTHER_RUN, clock=clock).progress(1, 2)
    flow = stream()
    verdicts = flow.drain([rep.progress(0, 2), foreign, rep.progress(1, 2)])
    assert verdicts == (
        EventVerdict.ACCEPTED, EventVerdict.STALE_RUN, EventVerdict.ACCEPTED)


def test_draining_stops_accepting_after_the_ending_but_still_reports(clock):
    rep = reporter(clock)
    flow = stream()
    verdicts = flow.drain([
        rep.completed(state_snapshot(JobState.SUCCEEDED)),
        rep.progress(3, 3),
        rep.warning("Late."),
    ])
    assert verdicts == (
        EventVerdict.ACCEPTED, EventVerdict.AFTER_TERMINAL, EventVerdict.AFTER_TERMINAL)


def test_the_drain_uses_no_queue_size_and_no_timing(clock):
    """Correctness comes from the source running out, never from how many it had."""
    tree = ast.parse((SHARED / "job_control.py").read_text(encoding="utf-8"))
    called = {
        node.func.attr for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    for forbidden in ("qsize", "empty", "sleep", "join", "wait_for"):
        assert forbidden not in called, forbidden


# --------------------------------------------------------------------------- #
# Lifecycle compatibility with Phases 5 and 6
# --------------------------------------------------------------------------- #


def build_run(clock, *, publish=None):
    rep = reporter(clock, publish=publish)
    flow = stream()
    return rep, flow


def test_a_whole_successful_run_reads_as_one_ordered_story(clock):
    rep, flow = build_run(clock)
    flow.drain([
        rep.state_changed(state_snapshot(JobState.RUNNING)),
        rep.stage_changed("convert"),
        rep.current_item(ITEMS[0]),
        rep.progress(1, 3),
        rep.current_item(ITEMS[1]),
        rep.progress(2, 3),
        rep.current_item(ITEMS[2]),
        rep.progress(3, 3),
        rep.completed(state_snapshot(JobState.SUCCEEDED)),
    ])
    view = project_summary(flow.events)
    assert view.state is JobState.SUCCEEDED
    assert view.stage == "convert"
    assert view.current_item_id == ITEMS[2]
    assert view.progress.completed == 3 and view.progress.total == 3
    assert view.final == "Finished."


def test_pause_request_then_acknowledgement_then_resume_reads_truthfully(clock):
    rep, flow = build_run(clock)
    flow.drain([
        rep.state_changed(state_snapshot(JobState.RUNNING)),
        rep.state_changed(state_snapshot(JobState.PAUSE_REQUESTED)),
        rep.state_changed(state_snapshot(JobState.PAUSED)),
        rep.state_changed(state_snapshot(JobState.RUNNING)),
    ])
    assert summary_lines(flow.events) == (
        "Running.", "Pause requested.", "Paused.", "Running.")
    assert project_summary(flow.events).state is JobState.RUNNING


def test_cancel_request_then_acknowledgement_reads_truthfully(clock):
    rep, flow = build_run(clock)
    flow.drain([
        rep.state_changed(state_snapshot(JobState.RUNNING)),
        rep.state_changed(state_snapshot(JobState.CANCEL_REQUESTED)),
        rep.cancelled(state_snapshot(JobState.CANCELLED)),
    ])
    assert summary_lines(flow.events)[-2:] == ("Cancelling…", "Cancelled.")
    assert project_summary(flow.events).state is JobState.CANCELLED


def test_cancel_while_paused_is_reportable(clock):
    rep, flow = build_run(clock)
    flow.drain([
        rep.state_changed(state_snapshot(JobState.PAUSED)),
        rep.state_changed(state_snapshot(JobState.CANCEL_REQUESTED)),
        rep.cancelled(state_snapshot(JobState.CANCELLED)),
    ])
    assert project_summary(flow.events).state is JobState.CANCELLED


def test_a_run_that_finished_before_the_pause_landed_reports_success(clock):
    """§6.9: PAUSE_REQUESTED may end directly, and saying so is the honest outcome."""
    rep, flow = build_run(clock)
    flow.drain([
        rep.state_changed(state_snapshot(JobState.PAUSE_REQUESTED)),
        rep.completed(state_snapshot(JobState.SUCCEEDED)),
    ])
    assert project_summary(flow.events).state is JobState.SUCCEEDED


def test_a_run_that_finished_before_the_cancel_landed_reports_success(clock):
    rep, flow = build_run(clock)
    flow.drain([
        rep.state_changed(state_snapshot(JobState.CANCEL_REQUESTED)),
        rep.completed(state_snapshot(JobState.SUCCEEDED)),
    ])
    assert project_summary(flow.events).state is JobState.SUCCEEDED


def test_completed_with_failures_is_reported_as_itself(clock):
    rep, flow = build_run(clock)
    flow.drain([
        rep.failure("Chapter 2 could not be converted.", item_id=ITEMS[1]),
        rep.completed(state_snapshot(JobState.COMPLETED_WITH_FAILURES)),
    ])
    view = project_summary(flow.events)
    assert view.state is JobState.COMPLETED_WITH_FAILURES
    assert view.final == "Finished with failures."


def test_an_item_failure_does_not_become_a_fatal_job_failure(clock):
    """Reporting an item failure changes no state; only the controller ends a run."""
    rep, flow = build_run(clock)
    flow.accept(rep.failure("Chapter 2 broke.", item_id=ITEMS[1]))
    assert project_summary(flow.events).state is None


def test_a_fatal_failure_is_reported_as_a_completed_event_carrying_failed(clock):
    rep, flow = build_run(clock)
    flow.accept(rep.completed(state_snapshot(JobState.FAILED)))
    view = project_summary(flow.events)
    assert view.state is JobState.FAILED
    assert view.final == "The run failed."


def test_the_run_controller_and_the_reporter_agree_end_to_end(clock):
    """The real Phase 5 controller drives the reporter; nothing is hand-built."""
    controller = job_control.JobController(RUN)
    rep, flow = build_run(clock)
    flow.accept(rep.state_changed(controller.start()))
    controller.request_pause()
    flow.accept(rep.state_changed(controller.snapshot()))
    flow.accept(rep.state_changed(controller.resume()))
    flow.accept(rep.completed(controller.succeed()))
    assert [entry.state for entry in flow.events] == [
        JobState.RUNNING, JobState.PAUSE_REQUESTED, JobState.RUNNING, JobState.SUCCEEDED]
    assert flow.is_closed


def test_a_retry_request_is_untouched_by_reporting(clock):
    """§6.14: Retry Failed still reads the frozen snapshot, never the event stream."""
    from shared.job_control import FailureLog, FailureRecord, RunResult

    snap = run_snapshot()
    failures = FailureLog(snapshot_id=RUN, records=(
        FailureRecord(item_id=ITEMS[1], stage="convert", display_message="Broke.",
                      technical_detail="RuntimeError", retryable=True, snapshot_id=RUN),
    ))
    result = RunResult.settle(snap, failures, completed_ids=(ITEMS[0],))
    rep, flow = build_run(clock)
    flow.drain([
        rep.failure("Broke.", item_id=ITEMS[1]),
        rep.completed(state_snapshot(JobState.COMPLETED_WITH_FAILURES)),
    ])
    retry = result.retry()
    assert retry.snapshot is snap
    assert retry.item_ids == (ITEMS[1],)


# --------------------------------------------------------------------------- #
# Summary versus Details
# --------------------------------------------------------------------------- #


def test_the_summary_kinds_are_the_milestones_and_nothing_else():
    assert SUMMARY_KINDS == frozenset({
        JobEventKind.STATE_CHANGED, JobEventKind.STAGE_CHANGED,
        JobEventKind.IMPORT_COUNT, JobEventKind.WARNING, JobEventKind.FAILURE,
        JobEventKind.OUTPUT_LOCATION, JobEventKind.COMPLETED, JobEventKind.CANCELLED,
    })


@pytest.mark.parametrize("kind", [
    JobEventKind.PROGRESS, JobEventKind.CURRENT_ITEM, JobEventKind.TECHNICAL_DETAIL])
def test_the_per_item_churn_never_becomes_a_summary_line(kind):
    assert kind not in SUMMARY_KINDS


def test_the_summary_is_not_flooded_by_per_file_diagnostics(clock):
    """Two hundred files' worth of churn; four milestones."""
    rep, flow = build_run(clock)
    queued = [rep.stage_changed("convert")]
    for index in range(200):
        queued.append(rep.current_item(ITEMS[index % 3]))
        queued.append(rep.progress(index, 200))
        queued.append(rep.technical(f"ffmpeg -i {index}.mp3 out.m4b"))
    queued.append(rep.warning("One file was skipped."))
    queued.append(rep.completed(state_snapshot(JobState.SUCCEEDED)))
    flow.drain(queued)

    assert len(flow.events) == 603
    assert summary_lines(flow.events) == (
        "Stage: convert", "One file was skipped.", "Finished.")
    assert len(detail_lines(flow.events)) == 603


def test_no_raw_command_reaches_the_summary(clock):
    rep, flow = build_run(clock)
    flow.drain([
        rep.technical("ffmpeg -hide_banner -i \"C:/in.mp3\" -c:a aac out.m4b"),
        rep.failure("The chapter could not be converted.",
                    detail="ffmpeg -hide_banner -i in.mp3 out.m4b"),
    ])
    joined = "\n".join(summary_lines(flow.events))
    assert "ffmpeg" not in joined
    assert "The chapter could not be converted." in joined


def test_no_traceback_reaches_the_summary(clock):
    rep, flow = build_run(clock)
    flow.accept(rep.failure(
        "The chapter could not be converted.",
        detail="Traceback (most recent call last):\n  File \"x.py\"\nRuntimeError: 1"))
    joined = "\n".join(summary_lines(flow.events))
    assert "Traceback" not in joined and "RuntimeError" not in joined


def test_the_summary_never_contains_any_detail_text(clock):
    rep, flow = build_run(clock)
    flow.drain([
        rep.warning("Careful.", detail="SECRET-DIAGNOSTIC"),
        rep.failure("Broke.", detail="SECRET-DIAGNOSTIC"),
        rep.technical("SECRET-DIAGNOSTIC"),
    ])
    assert "SECRET-DIAGNOSTIC" not in "\n".join(summary_lines(flow.events))


def test_a_concise_warning_reaches_the_summary(clock):
    rep, flow = build_run(clock)
    flow.accept(rep.warning("Two files were skipped."))
    assert "Two files were skipped." in summary_lines(flow.events)


def test_a_concise_failure_reaches_the_summary(clock):
    rep, flow = build_run(clock)
    flow.accept(rep.failure("Chapter 2 could not be converted."))
    assert "Chapter 2 could not be converted." in summary_lines(flow.events)


def test_the_import_count_reaches_the_summary(clock):
    rep, flow = build_run(clock)
    flow.accept(rep.import_count(42))
    assert summary_lines(flow.events) == ("42 files imported.",)


def test_an_explicitly_supplied_output_location_reaches_the_summary(clock, tmp_path):
    rep, flow = build_run(clock)
    destination = tmp_path / "Output"
    flow.accept(rep.output_location(destination))
    assert summary_lines(flow.events) == (f"Output: {destination}",)
    assert not destination.exists()


def test_the_summary_view_exposes_the_output_location_without_touching_it(clock, tmp_path):
    rep, flow = build_run(clock)
    destination = tmp_path / "Output"
    flow.accept(rep.output_location(destination))
    assert project_summary(flow.events).output_location == destination
    assert list(tmp_path.iterdir()) == []


def test_the_details_keep_every_accepted_event(clock):
    rep, flow = build_run(clock)
    flow.drain([rep.stage_changed("scan"), rep.progress(1, 2), rep.technical("cmd")])
    assert len(detail_lines(flow.events)) == 3


def test_the_details_are_timestamped_from_the_injected_clock(clock):
    rep, flow = build_run(clock)
    flow.accept(rep.stage_changed("scan"))
    clock.advance(1.5)
    flow.accept(rep.stage_changed("convert"))
    lines = detail_lines(flow.events)
    assert lines[0].startswith("[+0.000s]")
    assert lines[1].startswith("[+1.500s]")


def test_the_details_measure_elapsed_time_from_the_first_event(clock):
    """A monotonic clock has no wall-clock meaning, so Details show elapsed time."""
    clock.set(9_999.0)
    rep, flow = build_run(clock)
    flow.accept(rep.stage_changed("scan"))
    clock.advance(0.25)
    flow.accept(rep.stage_changed("convert"))
    assert detail_lines(flow.events)[0].startswith("[+0.000s]")
    assert detail_lines(flow.events)[1].startswith("[+0.250s]")


def test_the_details_name_the_kind_of_every_event(clock):
    rep, flow = build_run(clock)
    flow.drain([rep.stage_changed("scan"), rep.current_item(ITEMS[0])])
    lines = detail_lines(flow.events)
    assert "stage_changed" in lines[0]
    assert "current_item" in lines[1]


def test_the_details_retain_useful_subprocess_output(clock):
    rep, flow = build_run(clock)
    flow.accept(rep.technical("ffmpeg version 7.0 Copyright (c) 2000-2024"))
    assert "ffmpeg version 7.0" in "\n".join(detail_lines(flow.events))


def test_the_details_retain_the_technical_exception_detail(clock):
    rep, flow = build_run(clock)
    flow.accept(rep.failure("Broke.", detail="RuntimeError: ffmpeg exited 1"))
    assert "RuntimeError: ffmpeg exited 1" in "\n".join(detail_lines(flow.events))


def test_a_multi_line_diagnostic_is_indented_rather_than_flattened(clock):
    rep, flow = build_run(clock)
    flow.accept(rep.technical("Traceback (most recent call last):\n  File \"x.py\"\nBoom"))
    lines = detail_lines(flow.events)
    assert len(lines) == 4, "one heading, then the three lines of the diagnostic"
    assert lines[0] == "[+0.000s] technical_detail"
    assert lines[1:] == (
        "    Traceback (most recent call last):", "      File \"x.py\"", "    Boom")


def test_the_details_name_the_occurrence_of_an_item_scoped_event(clock):
    rep, flow = build_run(clock)
    flow.accept(rep.current_item(ITEMS[1]))
    assert ITEMS[1] in detail_lines(flow.events)[0]


def test_both_projections_are_deterministic(clock):
    rep, flow = build_run(clock)
    flow.drain([rep.stage_changed("scan"), rep.warning("Careful."),
                rep.completed(state_snapshot(JobState.SUCCEEDED))])
    assert summary_lines(flow.events) == summary_lines(flow.events)
    assert detail_lines(flow.events) == detail_lines(flow.events)


def test_both_projections_accept_a_bare_list_of_events(clock):
    rep = reporter(clock)
    events = [rep.warning("Careful.")]
    assert summary_lines(events) == ("Careful.",)
    assert len(detail_lines(events)) == 1


def test_both_projections_are_empty_for_an_empty_run():
    assert summary_lines(()) == ()
    assert detail_lines(()) == ()


def test_the_summary_view_of_an_empty_run_claims_nothing():
    view = project_summary(())
    assert view.state is None and view.stage is None
    assert view.current_item_id is None
    assert view.progress.mode is ProgressMode.IDLE
    assert view.eta == CALCULATING
    assert view.final == ""


def test_the_summary_view_is_immutable(clock):
    view = project_summary(())
    with pytest.raises(Exception):
        view.final = "Finished."
    assert not hasattr(view, "__dict__")


def test_the_summary_view_collects_warnings_and_failures_separately(clock):
    rep, flow = build_run(clock)
    flow.drain([rep.warning("Careful."), rep.failure("Broke."), rep.warning("Again.")])
    view = project_summary(flow.events)
    assert view.warnings == ("Careful.", "Again.")
    assert view.failures == ("Broke.",)


def test_the_summary_view_carries_the_eta_it_is_given(clock):
    view = project_summary((), eta="2m 30s")
    assert view.eta == "2m 30s"


def test_the_summary_view_defaults_to_calculating(clock):
    assert project_summary(()).eta == CALCULATING


def test_every_state_has_one_central_concise_message():
    for state in JobState:
        text = state_message(state)
        assert text and "\n" not in text
        assert len(text) < 60
    assert state_message(JobState.PAUSE_REQUESTED) == "Pause requested."
    assert state_message(JobState.CANCELLED) == "Cancelled."


def test_the_state_message_refuses_something_that_is_not_a_state():
    with pytest.raises(JobContractError):
        state_message("running")


# --------------------------------------------------------------------------- #
# The bridge to the one existing session logger
# --------------------------------------------------------------------------- #


def test_the_bridge_resolves_the_existing_session_logger(monkeypatch, recorder):
    """It asks ``logging_setup.get_logger()``; it never builds a logger of its own."""
    asked: list[int] = []

    def fake_get_logger():
        asked.append(1)
        return recorder

    monkeypatch.setattr(logging_setup, "get_logger", fake_get_logger)
    bridge = LoggerBridge()
    assert bridge.logger is recorder
    assert asked == [1]


def test_the_bridge_resolves_the_logger_only_once(monkeypatch, recorder):
    calls: list[int] = []
    monkeypatch.setattr(
        logging_setup, "get_logger", lambda: (calls.append(1), recorder)[1])
    bridge = LoggerBridge()
    bridge.forward(event(JobEventKind.TECHNICAL_DETAIL, detail="one"))
    bridge.forward(event(JobEventKind.TECHNICAL_DETAIL, sequence=1, detail="two"))
    assert calls == [1]


def test_the_bridge_does_not_resolve_a_logger_until_it_forwards(monkeypatch):
    """Constructing a bridge must never open a session log file."""
    def explode():
        raise AssertionError("the logger was resolved too early")

    monkeypatch.setattr(logging_setup, "get_logger", explode)
    LoggerBridge()


def test_a_bridge_with_an_explicit_logger_never_asks_for_the_session_one(
        monkeypatch, recorder):
    """Which is why no test in this module ever opens a real session log file."""
    monkeypatch.setattr(
        logging_setup, "get_logger",
        lambda: pytest.fail("an injected logger must never be replaced"))
    bridge = LoggerBridge(logger=recorder)
    bridge.forward(event(JobEventKind.TECHNICAL_DETAIL, detail="x"))
    assert recorder.levels == ["debug"]


def test_the_bridge_adds_no_handler_to_the_logger_it_was_given(recorder):
    real = logging.getLogger("audiobook_tool.phase7_probe")
    before = list(real.handlers)
    LoggerBridge(logger=real).forward(event(JobEventKind.TECHNICAL_DETAIL, detail="x"))
    assert real.handlers == before == []


def test_a_technical_event_is_forwarded_at_debug(recorder):
    LoggerBridge(logger=recorder).forward(
        event(JobEventKind.TECHNICAL_DETAIL, detail="ffmpeg -i in.mp3"))
    assert recorder.levels == ["debug"]
    assert "ffmpeg -i in.mp3" in recorder.messages[0]


def test_a_warning_event_is_forwarded_at_warning(recorder):
    LoggerBridge(logger=recorder).forward(
        event(JobEventKind.WARNING, message="Two files were skipped."))
    assert recorder.levels == ["warning"]


def test_a_failure_event_is_forwarded_at_error(recorder):
    LoggerBridge(logger=recorder).forward(
        event(JobEventKind.FAILURE, message="Broke.", detail="RuntimeError"))
    assert recorder.levels == ["error"]
    assert "RuntimeError" in recorder.messages[0]


@pytest.mark.parametrize("kind", [
    JobEventKind.STATE_CHANGED, JobEventKind.STAGE_CHANGED, JobEventKind.PROGRESS,
    JobEventKind.CURRENT_ITEM, JobEventKind.IMPORT_COUNT,
    JobEventKind.OUTPUT_LOCATION, JobEventKind.COMPLETED, JobEventKind.CANCELLED])
def test_an_ordinary_milestone_is_not_forwarded_to_the_log(recorder, kind, clock):
    payload = {
        JobEventKind.STATE_CHANGED: {"state": JobState.RUNNING},
        JobEventKind.STAGE_CHANGED: {"stage": "scan"},
        JobEventKind.PROGRESS: {"completed": 1, "total": 2},
        JobEventKind.CURRENT_ITEM: {"item_id": ITEMS[0]},
        JobEventKind.IMPORT_COUNT: {"count": 3},
        JobEventKind.OUTPUT_LOCATION: {"location": Path("C:/out").absolute()},
        JobEventKind.COMPLETED: {"state": JobState.SUCCEEDED},
        JobEventKind.CANCELLED: {"state": JobState.CANCELLED},
    }[kind]
    assert LoggerBridge(logger=recorder).forward(event(kind, **payload)) is False
    assert recorder.calls == []


def test_the_bridge_names_the_run_it_is_reporting(recorder):
    LoggerBridge(logger=recorder).forward(event(JobEventKind.TECHNICAL_DETAIL, detail="x"))
    assert RUN in recorder.messages[0]


def test_the_stream_forwards_each_accepted_event_exactly_once(clock, recorder):
    flow = stream(bridge=LoggerBridge(logger=recorder))
    rep = reporter(clock)
    flow.drain([rep.technical("one"), rep.warning("two"), rep.failure("three")])
    assert recorder.levels == ["debug", "warning", "error"]
    assert len(recorder.calls) == 3


def test_the_stream_forwards_nothing_without_a_bridge(clock, recorder):
    flow = stream()
    flow.accept(reporter(clock).technical("one"))
    assert recorder.calls == []


def test_the_bridge_refuses_something_that_is_not_an_event(recorder):
    with pytest.raises(JobContractError):
        LoggerBridge(logger=recorder).forward("technical")


def test_the_bridge_uses_lazy_percent_formatting(recorder):
    """The logging convention this repository already follows."""
    LoggerBridge(logger=recorder).forward(
        event(JobEventKind.TECHNICAL_DETAIL, detail="100% done"))
    level, args = recorder.calls[0]
    assert level == "debug"
    assert args[0] == "%s" and len(args) == 2


def test_no_second_logger_file_handler_or_retention_policy_was_created():
    text = (SHARED / "job_control.py").read_text(encoding="utf-8")
    for owned_by_logging_setup in (
        "FileHandler", "StreamHandler", "basicConfig", "addHandler", "setFormatter",
        "Formatter", "setLevel", "getLogger", "max_sessions", "_prune_old_logs",
        "session_", "LOGS_DIR", "logs_dir",
    ):
        assert owned_by_logging_setup not in text, owned_by_logging_setup


def test_the_logging_module_itself_is_not_imported_by_the_foundation():
    """The bridge reuses the session logger; it never reaches for ``logging``."""
    tree = ast.parse((SHARED / "job_control.py").read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names.add(module)
            for alias in node.names:
                names.add(f"{module}.{alias.name}" if module else alias.name)
    assert "logging" not in names, "the bridge uses the session logger, not logging"
    assert "shared.logging_setup" in names


def test_logging_setup_still_has_exactly_its_approved_surface():
    for name in ("get_logger", "configured_max_sessions", "DEFAULT_MAX_SESSIONS",
                 "MAX_SESSIONS"):
        assert hasattr(logging_setup, name), name
    assert logging_setup.DEFAULT_MAX_SESSIONS == 30
    assert logging_setup._LOGGER_NAME == "audiobook_tool"


def test_logging_setup_learned_nothing_about_the_foundation():
    tree = ast.parse((SHARED / "logging_setup.py").read_text(encoding="utf-8"))
    text = (SHARED / "logging_setup.py").read_text(encoding="utf-8")
    for plan3 in ("job_control", "importing", "import_coordination", "job_ui"):
        assert plan3 not in text, plan3
    assert isinstance(tree, ast.Module)


# --------------------------------------------------------------------------- #
# Progress: truthful, monotonic, and never a fabricated hundred per cent
# --------------------------------------------------------------------------- #


def test_a_fresh_tracker_is_idle():
    view = ProgressTracker().view
    assert view.mode is ProgressMode.IDLE
    assert (view.completed, view.total) == (0, None)


def test_a_known_total_is_determinate(clock):
    tracker = ProgressTracker()
    tracker.apply(reporter(clock).progress(2, 5))
    assert tracker.view.mode is ProgressMode.DETERMINATE
    assert (tracker.view.completed, tracker.view.total) == (2, 5)


def test_an_unknown_total_stays_indeterminate(clock):
    tracker = ProgressTracker()
    tracker.apply(reporter(clock).progress(7))
    view = tracker.view
    assert view.mode is ProgressMode.INDETERMINATE
    assert view.total is None
    assert view.completed == 7


def test_progress_advances_monotonically(clock):
    rep, tracker = reporter(clock), ProgressTracker()
    for index in (1, 2, 3):
        tracker.apply(rep.progress(index, 3))
    assert tracker.view.completed == 3


def test_a_regressive_progress_report_is_refused(clock):
    rep, tracker = reporter(clock), ProgressTracker()
    tracker.apply(rep.progress(3, 5))
    tracker.apply(rep.progress(1, 5))
    assert tracker.view.completed == 3, "progress never goes backwards inside one stage"


def test_a_repeated_progress_report_changes_nothing(clock):
    rep, tracker = reporter(clock), ProgressTracker()
    tracker.apply(rep.progress(2, 5))
    before = tracker.view
    tracker.apply(rep.progress(2, 5))
    assert tracker.view == before


def test_a_stage_change_starts_the_count_again(clock):
    """A new category is a new comparable scope; carrying the old count would lie."""
    rep, tracker = reporter(clock), ProgressTracker()
    tracker.apply(rep.progress(5, 5))
    tracker.apply(rep.stage_changed("upload"))
    assert tracker.view.mode is ProgressMode.IDLE
    assert tracker.view.completed == 0
    tracker.apply(rep.progress(1, 4))
    assert (tracker.view.completed, tracker.view.total) == (1, 4)


def test_the_tracker_reports_the_stage_it_is_in(clock):
    rep, tracker = reporter(clock), ProgressTracker()
    tracker.apply(rep.stage_changed("convert"))
    assert tracker.stage == "convert"


def test_the_tracker_reports_the_current_occurrence(clock):
    rep, tracker = reporter(clock), ProgressTracker()
    tracker.apply(rep.current_item(ITEMS[1]))
    assert tracker.current_item_id == ITEMS[1]


def test_the_current_occurrence_does_not_move_the_counter(clock):
    rep, tracker = reporter(clock), ProgressTracker()
    tracker.apply(rep.progress(2, 5))
    tracker.apply(rep.current_item(ITEMS[0]))
    assert tracker.view.completed == 2


def test_an_import_count_is_not_processing_progress(clock):
    rep, tracker = reporter(clock), ProgressTracker()
    tracker.apply(rep.import_count(900))
    assert tracker.view.mode is ProgressMode.IDLE
    assert tracker.view.completed == 0


def test_an_item_failure_does_not_advance_progress(clock):
    rep, tracker = reporter(clock), ProgressTracker()
    tracker.apply(rep.progress(1, 3))
    tracker.apply(rep.failure("Chapter 2 broke.", item_id=ITEMS[1]))
    assert tracker.view.completed == 1


def test_a_cancelled_run_is_never_shown_as_complete(clock):
    rep, tracker = reporter(clock), ProgressTracker()
    tracker.apply(rep.progress(1, 5))
    tracker.apply(rep.cancelled(state_snapshot(JobState.CANCELLED)))
    assert (tracker.view.completed, tracker.view.total) == (1, 5)
    assert tracker.view.completed != tracker.view.total


def test_a_failed_run_is_never_shown_as_complete(clock):
    rep, tracker = reporter(clock), ProgressTracker()
    tracker.apply(rep.progress(2, 5))
    tracker.apply(rep.completed(state_snapshot(JobState.FAILED)))
    assert tracker.view.completed == 2


def test_a_successful_run_is_shown_complete_only_because_the_events_said_so(clock):
    rep, tracker = reporter(clock), ProgressTracker()
    tracker.apply(rep.progress(5, 5))
    tracker.apply(rep.completed(state_snapshot(JobState.SUCCEEDED)))
    assert (tracker.view.completed, tracker.view.total) == (5, 5)


def test_a_successful_run_that_never_reported_the_last_file_is_not_rounded_up(clock):
    """The strongest form of the rule: success alone does not mean 100%."""
    rep, tracker = reporter(clock), ProgressTracker()
    tracker.apply(rep.progress(3, 5))
    tracker.apply(rep.completed(state_snapshot(JobState.SUCCEEDED)))
    assert tracker.view.completed == 3
    assert tracker.view.total == 5


def test_an_unknown_total_is_never_turned_into_one_of_one(clock):
    rep, tracker = reporter(clock), ProgressTracker()
    tracker.apply(rep.progress(4))
    tracker.apply(rep.completed(state_snapshot(JobState.SUCCEEDED)))
    assert tracker.view.total is None
    assert tracker.view.mode is not ProgressMode.DETERMINATE


def test_the_tracker_refuses_something_that_is_not_an_event():
    with pytest.raises(JobContractError):
        ProgressTracker().apply("progress")


def test_the_progress_view_is_immutable():
    view = ProgressView(mode=ProgressMode.DETERMINATE, completed=1, total=2)
    with pytest.raises(Exception):
        view.completed = 5
    assert not hasattr(view, "__dict__")


def test_a_determinate_view_needs_a_total():
    with pytest.raises(JobContractError):
        ProgressView(mode=ProgressMode.DETERMINATE, completed=1, total=None)


def test_a_determinate_view_cannot_exceed_its_total():
    with pytest.raises(JobContractError):
        ProgressView(mode=ProgressMode.DETERMINATE, completed=3, total=2)


def test_an_indeterminate_view_has_no_total():
    with pytest.raises(JobContractError):
        ProgressView(mode=ProgressMode.INDETERMINATE, completed=1, total=5)


def test_an_idle_view_counts_nothing():
    with pytest.raises(JobContractError):
        ProgressView(mode=ProgressMode.IDLE, completed=1)


def test_the_view_refuses_a_negative_count():
    with pytest.raises(JobContractError):
        ProgressView(mode=ProgressMode.INDETERMINATE, completed=-1)


def test_the_progress_modes_map_onto_the_existing_indicator():
    """§6.13/§5.2: reuse ``ProgressIndicator``; add no second progress framework."""
    assert [mode.value for mode in ProgressMode] == [
        "idle", "determinate", "indeterminate"]
    from shared import ui_theme

    for method in ("update", "set_indeterminate", "reset", "finish"):
        assert hasattr(ui_theme.ProgressIndicator, method), method


def test_the_foundation_builds_no_progress_widget():
    text = (SHARED / "job_control.py").read_text(encoding="utf-8")
    for widget in ("Progressbar", "ProgressIndicator(", "ttk.", "tkinter"):
        assert widget not in text, widget


def test_the_view_carries_a_label_for_the_status_line(clock):
    rep, tracker = reporter(clock), ProgressTracker()
    tracker.apply(rep.progress(2, 5, message="Converting chapter 2."))
    assert tracker.view.label == "Converting chapter 2."


def test_the_tracker_starts_from_an_explicit_stage():
    tracker = ProgressTracker(stage="convert")
    assert tracker.stage == "convert"


# --------------------------------------------------------------------------- #
# The rolling ETA
# --------------------------------------------------------------------------- #


def estimator(clock: FakeClock, **kwargs) -> EtaEstimator:
    return EtaEstimator(RUN, clock=clock, **kwargs)


def sample(est: EtaEstimator, clock: FakeClock, category: str, seconds: float) -> None:
    est.begin(category)
    clock.advance(seconds)
    est.complete()


def test_the_defaults_are_the_plans_three_and_twenty():
    assert (DEFAULT_MINIMUM_SAMPLES, DEFAULT_SAMPLE_WINDOW) == (3, 20)


def test_an_estimator_with_no_samples_is_calculating(clock):
    assert estimator(clock).display(5) == CALCULATING


def test_two_samples_are_not_enough(clock):
    est = estimator(clock)
    for _ in range(2):
        sample(est, clock, "convert", 10.0)
    assert est.sample_count == 2
    assert est.display(5) == CALCULATING


def test_three_samples_are_enough(clock):
    est = estimator(clock)
    for _ in range(3):
        sample(est, clock, "convert", 10.0)
    assert est.display(5) == "50s"


def test_the_estimate_is_the_mean_of_the_comparable_samples(clock):
    est = estimator(clock)
    for seconds in (10.0, 20.0, 30.0):
        sample(est, clock, "convert", seconds)
    assert est.estimate(2) == pytest.approx(40.0)


def test_the_window_keeps_only_the_latest_twenty(clock):
    est = estimator(clock)
    for _ in range(25):
        sample(est, clock, "convert", 1.0)
    assert est.sample_count == DEFAULT_SAMPLE_WINDOW


def test_the_window_replaces_the_oldest_sample_first(clock):
    est = estimator(clock)
    for _ in range(20):
        sample(est, clock, "convert", 100.0)
    assert est.estimate(1) == pytest.approx(100.0)
    for _ in range(20):
        sample(est, clock, "convert", 1.0)
    assert est.sample_count == 20
    assert est.estimate(1) == pytest.approx(1.0), "the slow twenty rolled all the way out"


def test_the_window_size_is_configurable_but_defaults_to_the_plans_twenty(clock):
    est = EtaEstimator(RUN, clock=clock, window=5)
    for _ in range(9):
        sample(est, clock, "convert", 1.0)
    assert est.sample_count == 5


def test_a_changed_work_category_isolates_the_samples(clock):
    est = estimator(clock)
    for _ in range(3):
        sample(est, clock, "convert", 10.0)
    assert est.display(1) == "10s"
    est.begin("upload")
    clock.advance(1.0)
    est.complete()
    assert est.sample_count == 1
    assert est.display(1) == CALCULATING


def test_the_estimate_returns_after_the_new_category_has_enough(clock):
    est = estimator(clock)
    for _ in range(3):
        sample(est, clock, "convert", 10.0)
    for _ in range(3):
        sample(est, clock, "upload", 2.0)
    assert est.display(2) == "4s"


def test_the_category_is_reported(clock):
    est = estimator(clock)
    est.begin("convert")
    assert est.category == "convert"


def test_a_cancelled_unit_contributes_no_sample(clock):
    est = estimator(clock)
    for _ in range(3):
        sample(est, clock, "convert", 10.0)
    est.begin("convert")
    clock.advance(999.0)
    est.discard()
    assert est.sample_count == 3
    assert est.estimate(1) == pytest.approx(10.0)


def test_a_failed_unit_contributes_no_sample(clock):
    est = estimator(clock)
    est.begin("convert")
    clock.advance(5.0)
    est.discard()
    assert est.sample_count == 0


def test_an_incomplete_unit_contributes_no_sample(clock):
    """Never completed, never discarded: it simply never becomes history."""
    est = estimator(clock)
    est.begin("convert")
    clock.advance(5.0)
    assert est.sample_count == 0
    assert est.display(1) == CALCULATING


def test_completing_without_beginning_is_refused(clock):
    with pytest.raises(JobContractError):
        estimator(clock).complete()


def test_beginning_twice_without_finishing_is_refused(clock):
    est = estimator(clock)
    est.begin("convert")
    with pytest.raises(JobContractError):
        est.begin("convert")


def test_beginning_needs_a_category(clock):
    with pytest.raises(JobContractError):
        estimator(clock).begin("")


def test_paused_time_is_excluded_from_the_sample(clock):
    est = estimator(clock)
    est.begin("convert")
    clock.advance(2.0)
    est.note_state(JobState.PAUSED)
    clock.advance(600.0)
    est.note_state(JobState.RUNNING)
    clock.advance(3.0)
    assert est.complete() == pytest.approx(5.0)


def test_repeated_pause_and_resume_intervals_are_all_excluded(clock):
    est = estimator(clock)
    est.begin("convert")
    for _ in range(4):
        clock.advance(1.0)
        est.note_state(JobState.PAUSED)
        clock.advance(100.0)
        est.note_state(JobState.RUNNING)
    assert est.complete() == pytest.approx(4.0)


def test_a_pause_that_is_only_requested_does_not_stop_the_clock(clock):
    """§6.10: the stage is still running, so the time it takes is still work."""
    est = estimator(clock)
    est.begin("convert")
    clock.advance(1.0)
    est.note_state(JobState.PAUSE_REQUESTED)
    clock.advance(4.0)
    assert est.complete() == pytest.approx(5.0)


def test_a_paused_run_reports_calculating(clock):
    est = estimator(clock)
    for _ in range(3):
        sample(est, clock, "convert", 10.0)
    est.note_state(JobState.PAUSED)
    assert est.display(2) == CALCULATING


def test_resuming_restores_the_estimate(clock):
    est = estimator(clock)
    for _ in range(3):
        sample(est, clock, "convert", 10.0)
    est.note_state(JobState.PAUSED)
    est.note_state(JobState.RUNNING)
    assert est.display(2) == "20s"


@pytest.mark.parametrize("state", [
    JobState.SUCCEEDED, JobState.COMPLETED_WITH_FAILURES, JobState.FAILED,
    JobState.CANCELLED])
def test_a_finished_run_reports_calculating(clock, state):
    est = estimator(clock)
    for _ in range(3):
        sample(est, clock, "convert", 10.0)
    est.note_state(state)
    assert est.display(2) == CALCULATING


def test_an_unknown_total_reports_calculating(clock):
    est = estimator(clock)
    for _ in range(3):
        sample(est, clock, "convert", 10.0)
    assert est.display(None) == CALCULATING


def test_no_remaining_work_still_formats_a_duration(clock):
    est = estimator(clock)
    for _ in range(3):
        sample(est, clock, "convert", 10.0)
    assert est.display(0) == "0s"


def test_a_negative_remaining_count_is_refused(clock):
    est = estimator(clock)
    for _ in range(3):
        sample(est, clock, "convert", 10.0)
    with pytest.raises(JobContractError):
        est.display(-1)


def test_a_backwards_clock_produces_no_sample(clock):
    est = estimator(clock)
    est.begin("convert")
    clock.set(clock.now - 10.0)
    assert est.complete() is None
    assert est.sample_count == 0


# --------------------------------------------------------------------------- #
# An already-measured duration
# --------------------------------------------------------------------------- #
#
# ``begin``/``complete`` measure with the estimator's own clock, which means the
# thread that times a unit of work is also the thread that mutates the estimator.
# A tool whose work happens on a worker thread cannot use that pair without
# sharing this object across threads, so :meth:`EtaEstimator.record` accepts a
# duration somebody else measured. It is the same reliability policy either way:
# the category rule, the finite/non-negative rule, the bounded window, the
# three-sample minimum and ``Calculating…`` are all unchanged, and this reads no
# clock at all.


def test_a_recorded_duration_becomes_a_sample(clock):
    est = estimator(clock)
    assert est.record("convert", 12.5) == pytest.approx(12.5)
    assert est.samples == pytest.approx((12.5,))
    assert est.category == "convert"


def test_recording_reads_no_clock(clock):
    """The whole point: the duration came from somewhere else."""
    est = estimator(clock)
    before = clock.reads
    for _ in range(3):
        est.record("convert", 10.0)
    assert clock.reads == before


def test_three_recorded_samples_estimate_exactly_as_three_measured_ones(clock):
    measured = estimator(clock)
    for _ in range(3):
        sample(measured, clock, "convert", 10.0)
    recorded = estimator(clock)
    for _ in range(3):
        recorded.record("convert", 10.0)
    assert recorded.estimate(5) == measured.estimate(5)
    assert recorded.display(5) == measured.display(5) == "50s"


def test_two_recorded_samples_are_still_not_enough(clock):
    est = estimator(clock)
    for _ in range(2):
        est.record("convert", 10.0)
    assert est.display(5) == CALCULATING


def test_a_recorded_window_still_keeps_only_the_latest_twenty(clock):
    est = estimator(clock)
    for _ in range(25):
        est.record("convert", 1.0)
    assert est.sample_count == DEFAULT_SAMPLE_WINDOW


def test_a_changed_category_clears_recorded_history_too(clock):
    est = estimator(clock)
    for _ in range(3):
        est.record("convert", 10.0)
    assert est.display(1) == "10s"
    est.record("upload", 2.0)
    assert est.sample_count == 1
    assert est.category == "upload"
    assert est.display(1) == CALCULATING


def test_recorded_and_measured_samples_share_one_category_history(clock):
    est = estimator(clock)
    sample(est, clock, "convert", 10.0)
    est.record("convert", 10.0)
    sample(est, clock, "convert", 10.0)
    assert est.sample_count == 3
    assert est.display(1) == "10s"


@pytest.mark.parametrize("duration", [-0.001, float("inf"), float("nan")])
def test_an_unusable_duration_records_nothing(clock, duration):
    est = estimator(clock)
    assert est.record("convert", duration) is None
    assert est.sample_count == 0


def test_a_zero_duration_is_a_real_sample(clock):
    """Work faster than the clock's resolution is still work that finished."""
    est = estimator(clock)
    for _ in range(3):
        est.record("convert", 0.0)
    assert est.sample_count == 3
    assert est.display(5) == "0s"


@pytest.mark.parametrize("duration", ["10", None, True, [1.0]])
def test_a_duration_that_is_not_a_number_is_refused(clock, duration):
    with pytest.raises(JobContractError):
        estimator(clock).record("convert", duration)


def test_recording_needs_a_category(clock):
    with pytest.raises(JobContractError):
        estimator(clock).record("", 1.0)


def test_recording_while_a_unit_is_being_timed_is_refused(clock):
    """The two ways of measuring are alternatives, never a mixture in flight."""
    est = estimator(clock)
    est.begin("convert")
    with pytest.raises(JobContractError):
        est.record("convert", 1.0)
    assert est.sample_count == 0


def test_a_paused_run_still_reports_calculating_for_recorded_samples(clock):
    est = estimator(clock)
    for _ in range(3):
        est.record("convert", 10.0)
    est.note_state(JobState.PAUSED)
    assert est.display(2) == CALCULATING


def test_a_finished_run_still_reports_calculating_for_recorded_samples(clock):
    est = estimator(clock)
    for _ in range(3):
        est.record("convert", 10.0)
    est.note_state(JobState.SUCCEEDED)
    assert est.display(2) == CALCULATING


def test_recording_belongs_to_the_estimators_own_run(clock):
    est = estimator(clock)
    for _ in range(3):
        est.record("convert", 10.0)
    assert est.display(2, run_id=RUN) == "20s"
    assert est.display(2, run_id=OTHER_RUN) == CALCULATING


def test_recording_added_no_event_kind_field_or_transition():
    """The narrow additive change is one estimator method and nothing else."""
    assert len(JobEventKind) == 11
    assert set(job_control.TERMINAL_EVENT_KINDS) == {
        JobEventKind.COMPLETED, JobEventKind.CANCELLED}
    assert len(JobState) == 9
    tree = ast.parse((SHARED / "job_control.py").read_text(encoding="utf-8"))
    estimator_methods = {
        node.name
        for klass in ast.walk(tree)
        if isinstance(klass, ast.ClassDef) and klass.name == "EtaEstimator"
        for node in klass.body
        if isinstance(node, ast.FunctionDef)
    }
    assert "record" in estimator_methods
    assert {"begin", "complete", "discard", "note_state", "observe", "estimate",
            "display"} <= estimator_methods


def test_a_backwards_clock_leaves_earlier_samples_intact(clock):
    est = estimator(clock)
    for _ in range(3):
        sample(est, clock, "convert", 10.0)
    est.begin("convert")
    clock.set(clock.now - 5.0)
    est.complete()
    assert est.sample_count == 3
    assert est.display(1) == "10s"


def test_a_non_finite_clock_produces_no_sample(clock):
    est = estimator(clock)
    est.begin("convert")
    clock.set(float("inf"))
    assert est.complete() is None
    assert est.sample_count == 0


def test_a_non_finite_clock_at_the_start_is_refused(clock):
    clock.set(float("nan"))
    est = estimator(clock)
    with pytest.raises(JobContractError):
        est.begin("convert")


def test_a_zero_duration_clock_is_deterministic(clock):
    """A fake clock that never moves gives three honest zero-second samples."""
    est = estimator(clock)
    for _ in range(3):
        est.begin("convert")
        est.complete()
    assert est.sample_count == 3
    assert est.estimate(10) == pytest.approx(0.0)
    assert est.display(10) == "0s"


def test_a_new_run_never_inherits_the_previous_runs_history(clock):
    first = estimator(clock)
    for _ in range(3):
        sample(first, clock, "convert", 10.0)
    second = EtaEstimator(OTHER_RUN, clock=clock)
    assert second.sample_count == 0
    assert second.display(2) == CALCULATING


def test_a_retry_never_inherits_the_original_runs_history(clock):
    est = estimator(clock)
    for _ in range(3):
        sample(est, clock, "convert", 10.0)
    retry = EtaEstimator("run-1-retry", clock=clock)
    assert retry.display(1) == CALCULATING


def test_asking_about_a_different_run_reports_calculating(clock):
    est = estimator(clock)
    for _ in range(3):
        sample(est, clock, "convert", 10.0)
    assert est.display(2, run_id=RUN) == "20s"
    assert est.display(2, run_id=OTHER_RUN) == CALCULATING


def test_the_estimator_observes_only_its_own_runs_events(clock):
    est = estimator(clock)
    for _ in range(3):
        sample(est, clock, "convert", 10.0)
    foreign = JobEvent(kind=JobEventKind.STATE_CHANGED, run_id=OTHER_RUN, sequence=0,
                       timestamp=0.0, state=JobState.CANCELLED)
    assert est.observe(foreign) is False
    assert est.display(2) == "20s", "a stray event from elsewhere changed nothing"


def test_observing_a_state_event_updates_the_estimator(clock):
    est = estimator(clock)
    for _ in range(3):
        sample(est, clock, "convert", 10.0)
    assert est.observe(event(JobEventKind.STATE_CHANGED, state=JobState.PAUSED)) is True
    assert est.display(2) == CALCULATING


def test_observing_a_terminal_event_ends_the_estimate(clock):
    est = estimator(clock)
    for _ in range(3):
        sample(est, clock, "convert", 10.0)
    est.observe(event(JobEventKind.COMPLETED, state=JobState.SUCCEEDED))
    assert est.display(2) == CALCULATING


def test_observing_an_unrelated_event_changes_nothing(clock):
    est = estimator(clock)
    for _ in range(3):
        sample(est, clock, "convert", 10.0)
    est.observe(event(JobEventKind.PROGRESS, completed=1, total=3))
    assert est.display(2) == "20s"


def test_the_estimator_refuses_something_that_is_not_an_event(clock):
    with pytest.raises(JobContractError):
        estimator(clock).observe("completed")


def test_a_media_duration_is_never_a_timing_sample(clock):
    """§6.13: probes measure content length, not how long the work took."""
    text = (SHARED / "job_control.py").read_text(encoding="utf-8").lower()
    for probe in ("ffprobe", "media_length", "audio_length", "mutagen",
                  "pydub", "soundfile", "probe("):
        assert probe not in text, probe
    # And the only durations it knows are ones somebody measured across real work
    # with an injected clock. There are exactly two sanctioned entry points: the
    # estimator times the unit itself (``complete``), or it is handed a duration
    # a caller timed on its own thread (``record``). A third would be a new way
    # for a number of unknown provenance to become history.
    tree = ast.parse((SHARED / "job_control.py").read_text(encoding="utf-8"))
    appending = {
        node.name for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and any(
            isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
            and call.func.attr == "append"
            and isinstance(call.func.value, ast.Attribute)
            and call.func.value.attr == "_samples"
            for call in ast.walk(node))
    }
    assert appending == {"complete", "record"}, appending
    # ``record`` in particular invents nothing: it reads no clock of its own, so
    # the number it stores can only be the one it was given.
    recorder = next(node for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef) and node.name == "record")
    reached = {node.attr for node in ast.walk(recorder)
               if isinstance(node, ast.Attribute)}
    for clock_access in ("_clock", "_read_clock"):
        assert clock_access not in reached, clock_access


def test_the_estimator_persists_nothing(clock):
    """No file, no database, no settings write — the history dies with the run."""
    tree = ast.parse((SHARED / "job_control.py").read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules.add((node.module or "").split(".")[0])
    for persistence in ("json", "pickle", "shelve", "sqlite3", "csv", "configparser",
                        "tomllib", "os"):
        assert persistence not in modules, persistence
    text = (SHARED / "job_control.py").read_text(encoding="utf-8")
    assert "shared.settings" not in text


def test_the_estimator_refuses_a_clock_that_is_not_callable():
    with pytest.raises(JobContractError):
        EtaEstimator(RUN, clock=object())


def test_the_estimator_refuses_a_nonsense_minimum(clock):
    for bad in (0, -1):
        with pytest.raises(JobContractError):
            EtaEstimator(RUN, clock=clock, minimum_samples=bad)


def test_the_estimator_refuses_a_window_smaller_than_the_minimum(clock):
    with pytest.raises(JobContractError):
        EtaEstimator(RUN, clock=clock, minimum_samples=5, window=4)


def test_a_stricter_minimum_is_honoured(clock):
    est = EtaEstimator(RUN, clock=clock, minimum_samples=5)
    for _ in range(4):
        sample(est, clock, "convert", 10.0)
    assert est.display(1) == CALCULATING
    sample(est, clock, "convert", 10.0)
    assert est.display(1) == "10s"


# --------------------------------------------------------------------------- #
# Central duration formatting
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("seconds,expected", [
    (0.0, "0s"),
    (1.0, "1s"),
    (1.4, "1s"),
    (1.6, "2s"),
    (59.0, "59s"),
    (59.6, "1m 0s"),
    (60.0, "1m 0s"),
    (90.0, "1m 30s"),
    (600.0, "10m 0s"),
    (3599.0, "59m 59s"),
    (3600.0, "1h 0m"),
    (3661.0, "1h 1m"),
    (86_400.0, "24h 0m"),
])
def test_a_duration_is_formatted_the_same_way_everywhere(seconds, expected):
    assert format_duration(seconds) == expected


def test_a_negative_duration_is_never_formatted():
    with pytest.raises(JobContractError):
        format_duration(-1.0)


def test_a_non_finite_duration_is_never_formatted():
    for bad in (float("nan"), float("inf")):
        with pytest.raises(JobContractError):
            format_duration(bad)


def test_the_calculating_text_matches_the_one_the_application_already_shows():
    from shared import maintenance

    assert CALCULATING == maintenance.CALCULATING_TEXT == "Calculating…"


def test_the_estimator_formats_through_the_one_function(clock):
    est = estimator(clock)
    for _ in range(3):
        sample(est, clock, "convert", 45.0)
    assert est.display(2) == format_duration(90.0) == "1m 30s"


# --------------------------------------------------------------------------- #
# Nothing here touches a display, a disk, a process or a real workload
# --------------------------------------------------------------------------- #


def test_the_reporting_layer_starts_no_process_and_reads_no_media():
    tree = ast.parse((SHARED / "job_control.py").read_text(encoding="utf-8"))
    called = {
        node.func.attr for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    } | {
        node.func.id for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    for forbidden in ("run", "popen", "Popen", "check_output", "open", "system",
                      "urlopen", "connect"):
        assert forbidden not in called, forbidden


def test_the_reporting_layer_reads_no_clock_of_its_own():
    """Every timestamp and every duration comes from an injected clock."""
    tree = ast.parse((SHARED / "job_control.py").read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules.add((node.module or "").split(".")[0])
    assert "time" not in modules
    assert "datetime" not in modules
    called = {
        node.func.attr for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    for clock_call in ("monotonic", "perf_counter", "now", "utcnow", "time"):
        assert clock_call not in called, clock_call


def test_no_phase_seven_test_here_needs_a_display_or_a_disk(tmp_path):
    """The whole module's fixture budget: a fake clock, a list and a recorder."""
    assert list(tmp_path.iterdir()) == []
