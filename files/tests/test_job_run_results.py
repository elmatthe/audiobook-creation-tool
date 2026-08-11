"""Frozen runs, locking, outcomes and Retry Failed — v0.6.0 Drop 3 (Plan 3), Phase 6.

Every test here is pure. Nothing starts a thread, opens a display, reads the
repository, creates an output or converts anything; the few filesystem-shaped values
are built under ``tmp_path`` and only ever named, never opened.

The phase's whole claim is that **one run reads one configuration**. Most of what
follows is an attempt to break that: mutate the caller's list after capture, clear
the imported-file manager, save a different preference, hand in a nested dictionary
and edit it afterwards, then check the run still describes exactly what it was
accepted with.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import MappingProxyType

import pytest

from shared import job_control
from shared.importing import (
    IdFactory,
    ImportedFile,
    ImportedFileManager,
    ImportedFileSnapshot,
    ImportOptions,
    ImportRoot,
    RootKind,
    ScanOutcome,
    ScanRequest,
    ScanResult,
    SupportedType,
    SupportedTypeCatalog,
)
from shared.job_control import (
    INPUT_LOCKED_STATES,
    LOCK_MATRIX,
    TERMINAL_STATES,
    ControlKind,
    FailureLog,
    FailureRecord,
    ItemOutcome,
    ItemStatus,
    JobAction,
    JobContractError,
    JobController,
    JobState,
    OptionFreezeError,
    RetryContractError,
    RetryRequest,
    RunResult,
    RunSnapshot,
    capture_run,
    is_available,
    is_locked,
)

from test_importing import make_config

SHARED = Path(__file__).resolve().parent.parent.parent / "scripts" / "Universal" / "shared"


# --------------------------------------------------------------------------- #
# Immutable fixtures
# --------------------------------------------------------------------------- #


def catalog() -> SupportedTypeCatalog:
    return SupportedTypeCatalog((
        SupportedType("mp3", "MP3 audio", (".mp3",)),
        SupportedType("m4b", "M4B audiobook", (".m4b",)),
    ))


def occurrence(
    index: int, name: str = "", *, root: ImportRoot | None = None,
    identity: str = "") -> ImportedFile:
    """One imported occurrence. Only named, never created on disk."""
    label = name or f"{index:02d}.mp3"
    home = root or ImportRoot("root-0", Path("C:/Books") if Path("C:/").is_absolute()
                              else Path("/Books"), 0)
    return ImportedFile(
        occurrence_id=f"occ-{index:06d}",
        path=home.path / label,
        source_root=home,
        relative_path=Path(label),
        supported_type_id="mp3",
        identity=identity or f"file:1:{index}",
    )


def files_snapshot(count: int = 3, *, revision: int = 1) -> ImportedFileSnapshot:
    from shared.importing import Revision

    return ImportedFileSnapshot(
        revision=Revision(revision),
        files=tuple(occurrence(index) for index in range(1, count + 1)),
    )


def snapshot(
    *,
    snapshot_id: str = "run-1",
    count: int = 3,
    tool_options=None,
    threshold: int = 1000,
    files=None,
) -> RunSnapshot:
    return capture_run(
        snapshot_id=snapshot_id,
        files=files_snapshot(count) if files is None else files,
        catalog=catalog(),
        import_options=ImportOptions.for_catalog(catalog()),
        effective_config=make_config(threshold),
        tool_options=tool_options,
        created_at=1.0,
    )


def failure(
    item_id: str | None,
    *,
    snapshot_id: str = "run-1",
    retryable: bool = True,
    stage: str = "convert",
    message: str = "The chapter could not be converted.",
    detail: str = "RuntimeError: ffmpeg exited 1",
) -> FailureRecord:
    return FailureRecord(
        item_id=item_id,
        stage=stage,
        display_message=message,
        technical_detail=detail,
        retryable=retryable,
        snapshot_id=snapshot_id,
    )


def log(*records: FailureRecord, snapshot_id: str = "run-1") -> FailureLog:
    return FailureLog(snapshot_id=snapshot_id, records=records)


def populated_manager(count: int = 3) -> ImportedFileManager:
    """A real manager holding real occurrences, with no filesystem behind them."""
    manager = ImportedFileManager(id_factory=IdFactory("m-"))
    result = ScanResult(
        request_id="req-1",
        outcome=ScanOutcome.COMPLETED,
        discovered_count=count,
        files=tuple(occurrence(index) for index in range(1, count + 1)),
    )
    manager.commit(manager.plan(result, options=ImportOptions.for_catalog(catalog())))
    return manager


# --------------------------------------------------------------------------- #
# Capture and one configuration per run
# --------------------------------------------------------------------------- #


def test_a_minimal_run_captures_everything_it_needs():
    run = snapshot()
    assert run.snapshot_id == "run-1"
    assert run.count == 3
    assert run.item_ids == ("occ-000001", "occ-000002", "occ-000003")
    assert run.tool_options == {}
    assert run.created_at == 1.0
    assert run.effective_config.importing.large_result_warning_threshold == 1000


def test_a_complete_run_captures_typed_tool_options():
    run = snapshot(tool_options={
        "bitrate": "192k",
        "chapters": ["one", "two"],
        "metadata": {"series": "Jack Ryan", "book": 3},
        "flags": {"trim", "normalise"},
    })
    assert run.tool_options["bitrate"] == "192k"
    assert run.tool_options["chapters"] == ("one", "two"), "lists become tuples"
    assert run.tool_options["metadata"]["series"] == "Jack Ryan"
    assert run.tool_options["flags"] == frozenset({"trim", "normalise"})


def test_capture_accepts_a_manager_without_importing_one():
    manager = populated_manager(2)
    run = capture_run(
        snapshot_id="run-1",
        files=manager,
        catalog=catalog(),
        import_options=ImportOptions.for_catalog(catalog()),
        effective_config=make_config(),
    )
    assert run.count == 2
    assert run.files == manager.snapshot()


def test_capture_refuses_something_that_is_neither_a_snapshot_nor_a_source():
    for bad in (None, "files", 7, object()):
        with pytest.raises(JobContractError):
            capture_run(
                snapshot_id="run-1",
                files=bad,
                catalog=catalog(),
                import_options=ImportOptions.for_catalog(catalog()),
                effective_config=make_config(),
            )


def test_a_caller_list_mutated_afterwards_cannot_reach_the_run():
    chapters = ["one", "two"]
    options = {"chapters": chapters}
    run = snapshot(tool_options=options)

    chapters.append("three")
    options["bitrate"] = "64k"

    assert run.tool_options["chapters"] == ("one", "two")
    assert "bitrate" not in run.tool_options


def test_a_nested_caller_dictionary_mutated_afterwards_cannot_reach_the_run():
    metadata = {"series": "Jack Ryan", "tags": ["thriller"]}
    run = snapshot(tool_options={"metadata": metadata})

    metadata["series"] = "Something Else"
    metadata["tags"].append("spy")

    assert run.tool_options["metadata"]["series"] == "Jack Ryan"
    assert run.tool_options["metadata"]["tags"] == ("thriller",)


def test_the_frozen_options_cannot_be_edited_through_the_snapshot():
    run = snapshot(tool_options={"metadata": {"series": "Jack Ryan"}})
    with pytest.raises(TypeError):
        run.tool_options["metadata"] = {}
    with pytest.raises(TypeError):
        run.tool_options["metadata"]["series"] = "Other"
    assert isinstance(run.tool_options, MappingProxyType)


def test_a_live_object_is_refused_rather_than_captured():
    class Widget:
        def __init__(self):
            self.value = "live"

    for live in (Widget(), lambda: None, open, bytearray(b"x")):
        with pytest.raises(OptionFreezeError):
            snapshot(tool_options={"thing": live})


def test_clearing_the_manager_afterwards_cannot_reach_the_run():
    manager = populated_manager(3)
    run = capture_run(
        snapshot_id="run-1",
        files=manager,
        catalog=catalog(),
        import_options=ImportOptions.for_catalog(catalog()),
        effective_config=make_config(),
    )
    before = run.item_ids

    manager.select(list(before))
    manager.remove_selected()
    manager.clear()

    assert manager.count == 0
    assert run.item_ids == before
    assert run.count == 3


def test_reordering_the_manager_afterwards_cannot_reach_the_run():
    manager = populated_manager(3)
    run = capture_run(
        snapshot_id="run-1",
        files=manager,
        catalog=catalog(),
        import_options=ImportOptions.for_catalog(catalog()),
        effective_config=make_config(),
    )
    before = run.item_ids

    manager.select([before[-1]])
    manager.move_selected_up()
    manager.move_selected_up()

    assert [entry.occurrence_id for entry in manager.snapshot().files] != list(before)
    assert run.item_ids == before, "the run keeps the order it was accepted with"


def test_a_later_configuration_cannot_reach_an_accepted_run(monkeypatch):
    """The captured config is the only one the run and its retry will ever read."""
    run = snapshot(threshold=1000)
    monkeypatch.setattr(
        "shared.config.get_effective",
        lambda: (_ for _ in ()).throw(AssertionError("a run never re-reads config")),
    )
    result = RunResult.settle(run, log(failure("occ-000001")))
    request = result.retry()

    assert run.effective_config.importing.large_result_warning_threshold == 1000
    assert request.snapshot.effective_config is run.effective_config


def test_two_runs_are_distinct_even_from_identical_inputs():
    first = snapshot(snapshot_id="run-1")
    second = snapshot(snapshot_id="run-2")
    assert first.snapshot_id != second.snapshot_id
    assert first is not second
    assert first.item_ids == second.item_ids


def test_deliberate_duplicate_occurrences_survive_as_separate_items():
    from shared.importing import Revision

    same = occurrence(1, identity="file:1:1")
    twin = ImportedFile(
        occurrence_id="occ-000002",
        path=same.path,
        source_root=same.source_root,
        relative_path=same.relative_path,
        supported_type_id=same.supported_type_id,
        identity=same.identity,
    )
    run = snapshot(files=ImportedFileSnapshot(revision=Revision(1), files=(same, twin)))

    assert run.count == 2
    assert run.item_ids == ("occ-000001", "occ-000002")
    assert run.files.files[0].identity == run.files.files[1].identity
    assert run.files.files[0].path == run.files.files[1].path


def test_unicode_and_awkward_names_survive_capture():
    from shared.importing import Revision

    root = ImportRoot("root-0", Path("C:/Böcker") if Path("C:/").is_absolute()
                      else Path("/Böcker"), 0)
    entries = tuple(
        occurrence(index, name, root=root, identity=f"file:1:{index}")
        for index, name in enumerate(
            ("01 — Prólogo.mp3", "02 O'Brien's Tale.mp3", "03 日本語.mp3"), start=1)
    )
    run = snapshot(files=ImportedFileSnapshot(revision=Revision(1), files=entries))
    assert [entry.path.name for entry in run.files.files] == [
        "01 — Prólogo.mp3", "02 O'Brien's Tale.mp3", "03 日本語.mp3"]


def test_a_snapshot_holds_no_live_machinery():
    run = snapshot(tool_options={"metadata": {"series": "Jack Ryan"}})
    for forbidden in ("_lock", "_condition", "_listener", "manager", "controller",
                      "widget", "queue", "thread"):
        assert not hasattr(run, forbidden), forbidden
    assert not hasattr(run, "__dict__"), "slots, so nothing can be attached later"
    with pytest.raises(Exception):
        run.snapshot_id = "other"


def test_a_malformed_run_is_refused_deterministically():
    with pytest.raises(JobContractError, match="snapshot_id"):
        snapshot(snapshot_id="  ")
    with pytest.raises(JobContractError, match="ImportedFileSnapshot"):
        RunSnapshot(
            snapshot_id="run-1", files="files", catalog=catalog(),
            import_options=ImportOptions.for_catalog(catalog()),
            effective_config=make_config())
    with pytest.raises(JobContractError, match="EffectiveConfig"):
        RunSnapshot(
            snapshot_id="run-1", files=files_snapshot(), catalog=catalog(),
            import_options=ImportOptions.for_catalog(catalog()),
            effective_config={"importing": {}})


def test_a_run_refuses_files_whose_type_is_not_in_its_catalog():
    thin = SupportedTypeCatalog((SupportedType("m4b", "M4B", (".m4b",)),))
    with pytest.raises(JobContractError, match="outside the catalog"):
        capture_run(
            snapshot_id="run-1",
            files=files_snapshot(),
            catalog=thin,
            import_options=ImportOptions.for_catalog(thin),
            effective_config=make_config(),
        )


# --------------------------------------------------------------------------- #
# The lock-state derivation
# --------------------------------------------------------------------------- #


def test_every_control_kind_appears_in_the_matrix():
    """A kind that is never locked maps to an empty set, never to absence."""
    assert set(LOCK_MATRIX) == set(ControlKind)
    for kind in ControlKind:
        assert isinstance(LOCK_MATRIX[kind], frozenset)


@pytest.mark.parametrize("kind", list(ControlKind), ids=lambda k: k.value)
@pytest.mark.parametrize("state", list(JobState), ids=lambda s: s.value)
def test_every_matrix_cell_is_classified(kind, state):
    """Exhaustive over all fifty-four cells — nothing can be silently unclassified."""
    answer = is_locked(kind, state)
    assert isinstance(answer, bool)
    expected = kind in (ControlKind.IMPORTED_INPUT, ControlKind.PROCESSING_OPTION) and (
        state in INPUT_LOCKED_STATES)
    assert answer is expected


def test_inputs_and_options_are_locked_exactly_while_the_job_owns_them():
    """§6.11, derived from the Phase 1 frozen set rather than restated beside it."""
    for kind in (ControlKind.IMPORTED_INPUT, ControlKind.PROCESSING_OPTION):
        locked = {state for state in JobState if is_locked(kind, state)}
        assert locked == set(INPUT_LOCKED_STATES)
        assert JobState.IDLE not in locked
        assert not (locked & TERMINAL_STATES)


@pytest.mark.parametrize(
    "kind",
    [ControlKind.JOB_CONTROL, ControlKind.LOG_VIEW, ControlKind.PROGRESS_STATUS,
     ControlKind.OPEN_OUTPUT],
    ids=lambda k: k.value,
)
def test_job_controls_logs_progress_and_open_output_are_never_locked(kind):
    """They are never *ordinary inputs*; whether they are meaningful is separate."""
    assert all(not is_locked(kind, state) for state in JobState)
    assert LOCK_MATRIX[kind] == frozenset()


def test_the_matrix_refuses_an_unknown_control_or_state():
    with pytest.raises(JobContractError, match="ControlKind"):
        is_locked("imported_input", JobState.RUNNING)
    with pytest.raises(JobContractError, match="JobState"):
        is_locked(ControlKind.IMPORTED_INPUT, "running")


@pytest.mark.parametrize("action", list(JobAction), ids=lambda a: a.value)
@pytest.mark.parametrize("state", list(JobState), ids=lambda s: s.value)
def test_every_action_is_classified_in_every_state(action, state):
    assert isinstance(is_available(action, state, has_retryable=True), bool)
    assert isinstance(is_available(action, state, has_retryable=False), bool)


def test_the_run_controls_are_available_exactly_where_they_mean_something():
    available = {
        action: {state for state in JobState if is_available(action, state)}
        for action in JobAction
    }
    assert available[JobAction.START] == {JobState.IDLE}
    assert available[JobAction.PAUSE] == {JobState.RUNNING}
    assert available[JobAction.RESUME] == {JobState.PAUSE_REQUESTED, JobState.PAUSED}
    assert available[JobAction.CANCEL] == {
        JobState.RUNNING, JobState.PAUSE_REQUESTED, JobState.PAUSED}


def test_pause_resume_and_cancel_agree_with_the_frozen_transition_table():
    """An action is never offered for a move the Phase 5 controller would refuse."""
    from shared.job_control import LEGAL_TRANSITIONS

    for state in JobState:
        if is_available(JobAction.PAUSE, state):
            assert JobState.PAUSE_REQUESTED in LEGAL_TRANSITIONS[state]
        if is_available(JobAction.RESUME, state):
            assert JobState.RUNNING in LEGAL_TRANSITIONS[state]
        if is_available(JobAction.CANCEL, state):
            assert JobState.CANCEL_REQUESTED in LEGAL_TRANSITIONS[state]
        if is_available(JobAction.START, state):
            assert JobState.RUNNING in LEGAL_TRANSITIONS[state]


def test_retry_failed_needs_both_the_right_state_and_a_retryable_failure():
    """§6.14: offered only after a run that finished with something worth retrying."""
    for state in JobState:
        assert is_available(JobAction.RETRY_FAILED, state, has_retryable=False) is False
    offered = {
        state for state in JobState
        if is_available(JobAction.RETRY_FAILED, state, has_retryable=True)
    }
    assert offered == {JobState.COMPLETED_WITH_FAILURES}
    assert not is_available(JobAction.RETRY_FAILED, JobState.FAILED, has_retryable=True)
    assert not is_available(JobAction.RETRY_FAILED, JobState.CANCELLED, has_retryable=True)


def test_availability_refuses_an_unknown_action_state_or_flag():
    with pytest.raises(JobContractError, match="JobAction"):
        is_available("pause", JobState.RUNNING)
    with pytest.raises(JobContractError, match="JobState"):
        is_available(JobAction.PAUSE, "running")
    with pytest.raises(JobContractError, match="has_retryable"):
        is_available(JobAction.RETRY_FAILED, JobState.COMPLETED_WITH_FAILURES,
                     has_retryable="yes")


# --------------------------------------------------------------------------- #
# Item outcomes
# --------------------------------------------------------------------------- #


def test_a_successful_item_carries_no_failure():
    outcome = ItemOutcome(item_id="occ-000001", status=ItemStatus.SUCCEEDED)
    assert outcome.succeeded and not outcome.failed and not outcome.retryable
    assert outcome.failure is None


def test_a_failed_item_must_carry_the_record_that_says_why():
    with pytest.raises(JobContractError, match="must carry the record"):
        ItemOutcome(item_id="occ-000001", status=ItemStatus.FAILED)


def test_a_successful_or_unattempted_item_may_not_carry_a_failure():
    for status in (ItemStatus.SUCCEEDED, ItemStatus.NOT_ATTEMPTED):
        with pytest.raises(JobContractError, match="carries no failure record"):
            ItemOutcome(
                item_id="occ-000001", status=status, failure=failure("occ-000001"))


def test_a_failure_may_not_describe_a_different_item():
    with pytest.raises(JobContractError, match="cannot describe"):
        ItemOutcome(
            item_id="occ-000001", status=ItemStatus.FAILED,
            failure=failure("occ-000002"))


def test_an_item_outcome_is_immutable_and_slotted():
    outcome = ItemOutcome(item_id="occ-000001", status=ItemStatus.SUCCEEDED)
    with pytest.raises(Exception):
        outcome.status = ItemStatus.FAILED
    assert not hasattr(outcome, "__dict__")


def test_the_item_vocabulary_is_exactly_three_answers():
    assert {status.value for status in ItemStatus} == {
        "succeeded", "failed", "not_attempted"}


def test_an_item_outcome_holds_no_output_reference():
    """§8's Phase 6 risk gate: no generic output descriptor may appear here."""
    outcome = ItemOutcome(item_id="occ-000001", status=ItemStatus.SUCCEEDED)
    for forbidden in ("output", "output_path", "destination", "planned", "reservation"):
        assert not hasattr(outcome, forbidden), forbidden


def test_a_failure_record_keeps_the_sentence_and_the_diagnostics_apart():
    record = failure("occ-000001")
    assert record.display_message == "The chapter could not be converted."
    assert record.technical_detail == "RuntimeError: ffmpeg exited 1"
    assert record.retryable and not record.is_fatal


def test_a_failure_message_must_stay_display_safe():
    for bad in ("two\nlines", "Traceback (most recent call last) boom", ""):
        with pytest.raises(JobContractError):
            failure("occ-000001", message=bad)


def test_a_fatal_failure_has_no_item_and_can_never_be_retryable():
    fatal = failure(None, retryable=False, message="The run could not start.")
    assert fatal.is_fatal
    with pytest.raises(JobContractError, match="no item to retry"):
        failure(None, retryable=True)


def test_a_failure_record_holds_no_raw_exception():
    record = failure("occ-000001", detail="RuntimeError: ffmpeg exited 1")
    assert isinstance(record.technical_detail, str)
    assert not isinstance(record.technical_detail, BaseException)
    with pytest.raises(JobContractError):
        FailureRecord(
            item_id="occ-000001", stage="convert",
            display_message="It broke.", technical_detail=RuntimeError("boom"),
            retryable=True, snapshot_id="run-1")


# --------------------------------------------------------------------------- #
# The run's disposition
# --------------------------------------------------------------------------- #


def test_a_run_where_everything_worked_simply_succeeded():
    run = snapshot()
    result = RunResult.settle(run, completed_ids=run.item_ids)

    assert result.state is JobState.SUCCEEDED
    assert result.succeeded_count == 3
    assert result.failed_count == 0 and result.not_attempted_count == 0
    assert not result.has_retryable
    assert [entry.status for entry in result.outcomes] == [ItemStatus.SUCCEEDED] * 3


def test_a_mixed_run_completed_with_failures_rather_than_failing():
    """The whole point of §6.14: losing an item is not losing the run."""
    run = snapshot()
    result = RunResult.settle(
        run,
        log(failure("occ-000002")),
        completed_ids=("occ-000001", "occ-000003"),
    )

    assert result.state is JobState.COMPLETED_WITH_FAILURES
    assert result.state is not JobState.FAILED
    assert result.succeeded_count == 2 and result.failed_count == 1
    assert result.has_retryable and result.retryable_ids == ("occ-000002",)


def test_a_run_where_every_item_failed_still_completed_its_orchestration():
    run = snapshot(count=2)
    result = RunResult.settle(
        run, log(failure("occ-000001"), failure("occ-000002")))

    assert result.state is JobState.COMPLETED_WITH_FAILURES
    assert result.failed_count == 2 and result.succeeded_count == 0


def test_a_job_level_failure_is_the_only_thing_that_fails_a_run():
    run = snapshot()
    result = RunResult.settle(
        run,
        log(failure(None, retryable=False, message="The tool could not start."),
            failure("occ-000001")),
        completed_ids=("occ-000002",),
    )

    assert result.state is JobState.FAILED
    assert result.failures.fatal
    assert result.failed_count == 1, "the item failure is still recorded truthfully"


def test_a_failed_state_needs_a_fatal_record():
    run = snapshot()
    with pytest.raises(JobContractError, match="an item failure is not a job failure"):
        RunResult(snapshot=run, failures=log(failure("occ-000001")),
                  state=JobState.FAILED)


def test_a_cancelled_run_outranks_everything_and_invents_no_failures():
    run = snapshot()
    result = RunResult.settle(
        run, log(failure("occ-000001")), completed_ids=("occ-000002",), cancelled=True)

    assert result.state is JobState.CANCELLED
    assert result.cancelled
    statuses = [entry.status for entry in result.outcomes]
    assert statuses == [ItemStatus.FAILED, ItemStatus.SUCCEEDED, ItemStatus.NOT_ATTEMPTED]
    assert result.not_attempted_count == 1, "the item it never reached is not a failure"


def test_an_unreached_item_is_never_fabricated_into_a_failure():
    run = snapshot(count=4)
    result = RunResult.settle(run, completed_ids=("occ-000001",), cancelled=True)
    assert result.failed_count == 0
    assert result.not_attempted_count == 3
    assert not result.has_retryable


def test_a_cancelled_result_cannot_be_rewritten_as_a_completion():
    run = snapshot()
    cancelled = RunResult.settle(run, cancelled=True)
    assert cancelled.state is JobState.CANCELLED
    with pytest.raises(Exception):
        cancelled.state = JobState.SUCCEEDED
    # Settling again produces a *new* value; the original is untouched.
    completed = RunResult.settle(run, completed_ids=run.item_ids)
    assert completed.state is JobState.SUCCEEDED
    assert cancelled.state is JobState.CANCELLED


def test_outcomes_keep_the_order_the_run_was_given():
    run = snapshot(count=4)
    result = RunResult.settle(
        run, log(failure("occ-000003")), completed_ids=("occ-000002", "occ-000001"))
    assert [entry.item_id for entry in result.outcomes] == [
        "occ-000001", "occ-000002", "occ-000003", "occ-000004"]
    assert [entry.status for entry in result.outcomes] == [
        ItemStatus.SUCCEEDED, ItemStatus.SUCCEEDED,
        ItemStatus.FAILED, ItemStatus.NOT_ATTEMPTED]


def test_counts_are_derived_and_can_never_disagree_with_the_records():
    run = snapshot(count=5)
    result = RunResult.settle(
        run, log(failure("occ-000002"), failure("occ-000004", retryable=False)),
        completed_ids=("occ-000001", "occ-000003"))
    assert dict(result.counts) == {
        ItemStatus.SUCCEEDED: 2, ItemStatus.FAILED: 2, ItemStatus.NOT_ATTEMPTED: 1}
    assert sum(result.counts.values()) == run.count
    with pytest.raises(TypeError):
        result.counts[ItemStatus.SUCCEEDED] = 99


def test_an_item_cannot_both_succeed_and_fail():
    run = snapshot()
    with pytest.raises(JobContractError, match="both succeeded and failed"):
        RunResult.settle(
            run, log(failure("occ-000001")), completed_ids=("occ-000001",))


def test_a_result_refuses_items_and_failures_from_another_run():
    run = snapshot(snapshot_id="run-1")
    with pytest.raises(JobContractError, match="does not belong to run"):
        RunResult.settle(run, log(failure("occ-000001", snapshot_id="run-2"),
                                  snapshot_id="run-2"))
    with pytest.raises(JobContractError, match="does not belong to snapshot"):
        RunResult.settle(run, completed_ids=("occ-999999",))
    with pytest.raises(JobContractError, match="does not belong to snapshot"):
        RunResult.settle(run, log(failure("occ-999999")))


def test_a_result_refuses_a_duplicate_completed_id():
    run = snapshot()
    with pytest.raises(JobContractError, match="listed twice"):
        RunResult.settle(run, completed_ids=("occ-000001", "occ-000001"))


def test_a_result_describes_a_finished_run_only():
    run = snapshot()
    for state in (JobState.IDLE, JobState.RUNNING, JobState.PAUSED,
                  JobState.PAUSE_REQUESTED, JobState.CANCEL_REQUESTED):
        with pytest.raises(JobContractError, match="not a terminal state"):
            RunResult(snapshot=run, failures=log(), state=state)


def test_a_result_is_immutable_and_holds_no_live_machinery():
    result = RunResult.settle(snapshot(), completed_ids=("occ-000001",))
    with pytest.raises(Exception):
        result.state = JobState.FAILED
    assert not hasattr(result, "__dict__")
    for forbidden in ("controller", "manager", "_lock", "_condition", "widget"):
        assert not hasattr(result, forbidden), forbidden


def test_settling_never_touches_a_controller():
    """An item failure must not reach the authoritative job transition mechanism."""
    controller = JobController("run-1")
    controller.start()
    run = snapshot()

    result = RunResult.settle(run, log(failure("occ-000001")))

    assert result.state is JobState.COMPLETED_WITH_FAILURES
    assert controller.state is JobState.RUNNING, "the controller was not touched"
    # The worker settles the controller itself, once, with what the result says.
    controller.complete_with_failures()
    assert controller.state is JobState.COMPLETED_WITH_FAILURES


def test_the_result_module_never_calls_the_controller_to_fail():
    """Structural: nothing in the Phase 6 section reaches for the Phase 5 object."""
    tree = ast.parse((SHARED / "job_control.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name not in (
                "RunResult", "ItemOutcome"):
            continue
        called = {
            inner.func.attr for inner in ast.walk(node)
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute)
        }
        for controller_call in ("fail", "succeed", "complete_with_failures",
                                "finish_cancelled", "checkpoint", "request_cancel",
                                "request_pause", "resume", "start"):
            assert controller_call not in called, (node.name, controller_call)


# --------------------------------------------------------------------------- #
# Retry Failed
# --------------------------------------------------------------------------- #


def test_a_retry_selects_all_and_only_the_retryable_failures():
    run = snapshot(count=4)
    result = RunResult.settle(
        run,
        log(failure("occ-000002"), failure("occ-000003", retryable=False),
            failure("occ-000004")),
        completed_ids=("occ-000001",),
    )
    request = result.retry()

    assert request.item_ids == ("occ-000002", "occ-000004")
    assert "occ-000001" not in request.item_ids, "a successful item is never retried"
    assert "occ-000003" not in request.item_ids, "a non-retryable failure is not retried"


def test_a_retry_uses_the_exact_original_snapshot_object():
    run = snapshot()
    result = RunResult.settle(run, log(failure("occ-000001")))
    request = result.retry()
    assert request.snapshot is run, "identity, not a copy or a rebuild"
    assert request.snapshot.tool_options == run.tool_options


def test_a_retry_preserves_the_original_relative_order():
    run = snapshot(count=5)
    result = RunResult.settle(
        run, log(failure("occ-000004"), failure("occ-000002"), failure("occ-000005")))
    # Asked for in a scrambled order; answered in the order they failed.
    request = result.retry(["occ-000005", "occ-000002", "occ-000004"])
    assert request.item_ids == ("occ-000004", "occ-000002", "occ-000005")
    assert result.retry().item_ids == request.item_ids


def test_a_retry_keeps_deliberate_duplicates_as_separate_occurrences():
    from shared.importing import Revision

    first = occurrence(1, identity="file:1:1")
    twin = ImportedFile(
        occurrence_id="occ-000002", path=first.path, source_root=first.source_root,
        relative_path=first.relative_path, supported_type_id="mp3",
        identity=first.identity)
    run = snapshot(files=ImportedFileSnapshot(revision=Revision(1), files=(first, twin)))
    result = RunResult.settle(
        run, log(failure("occ-000001"), failure("occ-000002")))

    request = result.retry()
    assert request.item_ids == ("occ-000001", "occ-000002")
    assert len(set(request.item_ids)) == 2, "the same source, two occurrences, both retried"


def test_a_run_with_no_retryable_failure_offers_no_retry():
    run = snapshot()
    result = RunResult.settle(run, completed_ids=run.item_ids)
    assert not result.has_retryable
    with pytest.raises(RetryContractError, match="no retryable failure"):
        result.retry()

    fatal_only = RunResult.settle(
        run, log(failure(None, retryable=False, message="The tool could not start.")))
    assert not fatal_only.has_retryable
    with pytest.raises(RetryContractError, match="no retryable failure"):
        fatal_only.retry()


def test_a_retry_refuses_an_unknown_a_successful_and_a_nonretryable_item():
    run = snapshot(count=4)
    result = RunResult.settle(
        run,
        log(failure("occ-000002"), failure("occ-000003", retryable=False)),
        completed_ids=("occ-000001",),
    )
    with pytest.raises(RetryContractError, match="did not fail in this run"):
        result.retry(["occ-000001"])
    with pytest.raises(RetryContractError, match="not retryable"):
        result.retry(["occ-000003"])
    with pytest.raises(RetryContractError, match="did not fail in this run"):
        result.retry(["occ-000004"])
    with pytest.raises(RetryContractError, match="did not fail in this run"):
        result.retry(["occ-999999"])


def test_a_retry_refuses_a_duplicate_selection_and_an_empty_one():
    run = snapshot()
    result = RunResult.settle(run, log(failure("occ-000001")))
    with pytest.raises(RetryContractError, match="listed twice"):
        result.retry(["occ-000001", "occ-000001"])
    with pytest.raises(RetryContractError, match="at least one item"):
        result.retry([])


def test_a_retry_refuses_failures_from_another_run():
    first, second = snapshot(snapshot_id="run-1"), snapshot(snapshot_id="run-2")
    foreign = log(failure("occ-000001", snapshot_id="run-2"), snapshot_id="run-2")
    with pytest.raises(RetryContractError, match="does not belong to run"):
        RetryRequest.from_failures(first, foreign)
    with pytest.raises(RetryContractError, match="does not belong to snapshot"):
        RetryRequest(snapshot=second, item_ids=("occ-999999",))


def test_a_retry_does_not_mutate_the_result_it_came_from():
    run = snapshot(count=3)
    result = RunResult.settle(
        run, log(failure("occ-000002")), completed_ids=("occ-000001",))
    before_outcomes = result.outcomes
    before_counts = dict(result.counts)

    result.retry()
    result.retry(["occ-000002"])

    assert result.outcomes == before_outcomes
    assert dict(result.counts) == before_counts
    assert result.state is JobState.COMPLETED_WITH_FAILURES
    assert result.failures.records[0].item_id == "occ-000002"


def test_a_retry_is_deterministic_when_built_repeatedly():
    run = snapshot(count=4)
    result = RunResult.settle(run, log(failure("occ-000003"), failure("occ-000001")))
    requests = [result.retry() for _ in range(5)]
    assert all(request.item_ids == ("occ-000003", "occ-000001") for request in requests)
    assert all(request.snapshot is run for request in requests)


def test_a_retry_is_immutable():
    run = snapshot()
    request = RunResult.settle(run, log(failure("occ-000001"))).retry()
    with pytest.raises(Exception):
        request.item_ids = ()
    with pytest.raises(Exception):
        request.snapshot = snapshot(snapshot_id="run-2")
    assert not hasattr(request, "__dict__")


def test_a_retry_ignores_every_later_change_to_live_state(monkeypatch):
    """The one guarantee Retry Failed exists to make."""
    manager = populated_manager(3)
    run = capture_run(
        snapshot_id="run-1",
        files=manager,
        catalog=catalog(),
        import_options=ImportOptions.for_catalog(catalog()),
        effective_config=make_config(1000),
        tool_options={"bitrate": "192k"},
    )
    failed_id = run.item_ids[1]
    result = RunResult.settle(run, log(failure(failed_id)))

    # Everything the user could plausibly change afterwards.
    manager.clear()
    monkeypatch.setattr(
        "shared.config.get_effective",
        lambda: (_ for _ in ()).throw(AssertionError("a retry never re-reads config")),
    )

    request = result.retry()

    assert request.item_ids == (failed_id,)
    assert request.snapshot is run
    assert request.snapshot.count == 3
    assert request.snapshot.tool_options["bitrate"] == "192k"
    assert request.snapshot.effective_config.importing.large_result_warning_threshold == 1000
    assert manager.count == 0, "the live list really did change; the retry ignored it"


def test_a_retry_decides_nothing_about_where_output_goes():
    run = snapshot()
    request = RunResult.settle(run, log(failure("occ-000001"))).retry()
    for forbidden in ("output", "destination", "output_base", "run_directory",
                      "reserve", "plan", "planner"):
        assert not hasattr(request, forbidden), forbidden
    assert set(request.__slots__) == {"snapshot", "item_ids"}


def test_a_retry_holds_no_recursive_or_live_chain():
    run = snapshot()
    result = RunResult.settle(run, log(failure("occ-000001")))
    request = result.retry()
    assert not hasattr(request, "result")
    assert not hasattr(request, "controller")
    assert not hasattr(request, "parent")
    assert request.snapshot is run


# --------------------------------------------------------------------------- #
# Boundaries
# --------------------------------------------------------------------------- #


def test_the_phase_six_contracts_reserve_no_output_and_touch_no_disk(tmp_path):
    """A whole run described end to end, with nothing created anywhere."""
    before = sorted(tmp_path.rglob("*"))
    run = snapshot(count=3, tool_options={"metadata": {"series": "Jack Ryan"}})
    result = RunResult.settle(
        run, log(failure("occ-000002")), completed_ids=("occ-000001",))
    result.retry()

    assert sorted(tmp_path.rglob("*")) == before
    assert not (tmp_path / "Audiobook Creation Tool").exists()


def test_the_module_still_imports_no_tk_and_no_output_or_subprocess_service():
    """Checked as imports, not substrings: the prose may name a boundary it keeps."""
    tree = ast.parse((SHARED / "job_control.py").read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    for forbidden in ("tkinter", "subprocess", "shared.output_paths",
                      "shared.import_coordination", "shared.maintenance",
                      "shared.logging_setup", "shared.subprocess_utils"):
        assert not any(
            entry == forbidden or entry.startswith(forbidden + ".")
            for entry in imported), (forbidden, sorted(imported))

    text = (SHARED / "job_control.py").read_text(encoding="utf-8")
    for widgetry in ("ttk.", "StringVar", "BooleanVar", ".after("):
        assert widgetry not in text, widgetry


def test_phase_one_and_five_vocabulary_is_reused_rather_than_restated():
    """The lock matrix derives from the frozen set; it does not copy it."""
    text = (SHARED / "job_control.py").read_text(encoding="utf-8")
    assert "INPUT_LOCKED_STATES if kind in _LOCKED_KINDS else frozenset()" in text
    assert set(LOCK_MATRIX[ControlKind.IMPORTED_INPUT]) == set(INPUT_LOCKED_STATES)

    # ``ItemStatus`` describes an *item*, not a second job-state machine: three
    # answers, a distinct type, and no transition table of its own. The word
    # "failed" appearing in both is the English language, not a duplicated model.
    assert job_control.ItemStatus is not job_control.JobState
    assert len(ItemStatus) == 3 and len(JobState) == 9
    assert not hasattr(job_control, "ITEM_TRANSITIONS")
    assert not any(
        isinstance(value, dict) and set(value) <= set(ItemStatus)
        for value in vars(job_control).values()
    ), "no second transition table was introduced for items"


def test_the_phase_five_controller_semantics_are_untouched():
    controller = JobController("run-1")
    controller.start()
    controller.request_pause()
    assert controller.state is JobState.PAUSE_REQUESTED, "still not claiming PAUSED"
    controller.request_cancel()
    assert controller.state is JobState.CANCEL_REQUESTED
    assert not controller.cancel_acknowledged, "requesting is still not acknowledging"


def test_a_run_result_and_the_controller_agree_on_the_terminal_vocabulary():
    for state in (JobState.SUCCEEDED, JobState.COMPLETED_WITH_FAILURES,
                  JobState.FAILED, JobState.CANCELLED):
        assert state in TERMINAL_STATES
    run = snapshot()
    assert RunResult.settle(run, completed_ids=run.item_ids).state in TERMINAL_STATES
