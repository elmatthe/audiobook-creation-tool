"""The job-control vocabulary — v0.6.0 Drop 3 (Plan 3), Phase 1.

States, transitions, the frozen run snapshot, failures, failed-only retry and the
typed event record. There is no controller yet: nothing here starts a thread,
waits on a condition, or claims a running operation stopped. Those behaviours are
Phase 5's, and the transition table below is what Phase 5 will be held to.

``EffectiveConfig`` is built in memory, so no configuration file is read or written.
"""

from __future__ import annotations

import dataclasses
import threading
from dataclasses import FrozenInstanceError, dataclass
from pathlib import Path, PurePath
from types import MappingProxyType

import pytest

from shared import job_control
from shared.importing import (
    ImportedFile,
    ImportedFileSnapshot,
    ImportOptions,
    ImportRoot,
    INITIAL_REVISION,
    SupportedType,
    SupportedTypeCatalog,
)
from shared.job_control import (
    FailureLog,
    FailureRecord,
    IllegalJobTransition,
    INPUT_LOCKED_STATES,
    JobContractError,
    JobEvent,
    JobEventKind,
    JobState,
    LEGAL_TRANSITIONS,
    OptionFreezeError,
    RetryContractError,
    RetryRequest,
    RunSnapshot,
    TERMINAL_EVENT_KINDS,
    TERMINAL_STATES,
    freeze_options,
    is_frozen_options,
    is_legal_transition,
    require_legal_transition,
)

from test_importing import ROOT_PATH, catalog, folder_root, make_config


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def files(count: int = 2) -> ImportedFileSnapshot:
    root = folder_root()
    return ImportedFileSnapshot(
        INITIAL_REVISION.advance(),
        tuple(
            ImportedFile(f"occ-{index}", root.path / f"{index}.mp3", root,
                         PurePath(f"{index}.mp3"), "mp3", f"id-{index}")
            for index in range(1, count + 1)
        ),
    )


def snapshot(snapshot_id: str = "run-1", tool_options=None, count: int = 2) -> RunSnapshot:
    book = catalog()
    return RunSnapshot(
        snapshot_id=snapshot_id,
        files=files(count),
        catalog=book,
        import_options=ImportOptions.for_catalog(book),
        effective_config=make_config(),
        tool_options={} if tool_options is None else tool_options,
        created_at=100.0,
    )


def failure(item_id, retryable=True, snapshot_id="run-1", stage="encode"):
    return FailureRecord(
        item_id=item_id,
        stage=stage,
        display_message="Something went wrong.",
        technical_detail="ffmpeg exited 1",
        retryable=retryable,
        snapshot_id=snapshot_id,
    )


# --------------------------------------------------------------------------- #
# The state vocabulary
# --------------------------------------------------------------------------- #


def test_the_nine_states_the_plan_names_all_exist():
    assert {state.value for state in JobState} == {
        "idle", "running", "pause_requested", "paused", "cancel_requested",
        "cancelled", "succeeded", "completed_with_failures", "failed",
    }


def test_the_transition_table_covers_every_state_exactly_once():
    assert set(LEGAL_TRANSITIONS) == set(JobState)
    for state, allowed in LEGAL_TRANSITIONS.items():
        assert allowed <= set(JobState), state


def test_a_terminal_state_leads_nowhere():
    """A controller belongs to one run and cannot be revived by clearing events."""
    assert TERMINAL_STATES == {
        JobState.CANCELLED, JobState.SUCCEEDED,
        JobState.COMPLETED_WITH_FAILURES, JobState.FAILED,
    }
    for state in TERMINAL_STATES:
        assert LEGAL_TRANSITIONS[state] == frozenset()
        for proposed in JobState:
            assert not is_legal_transition(state, proposed)


@pytest.mark.parametrize(
    "current,proposed",
    [
        (JobState.IDLE, JobState.RUNNING),
        (JobState.RUNNING, JobState.PAUSE_REQUESTED),
        (JobState.RUNNING, JobState.CANCEL_REQUESTED),
        (JobState.RUNNING, JobState.SUCCEEDED),
        (JobState.RUNNING, JobState.COMPLETED_WITH_FAILURES),
        (JobState.RUNNING, JobState.FAILED),
        (JobState.PAUSE_REQUESTED, JobState.PAUSED),
        (JobState.PAUSE_REQUESTED, JobState.RUNNING),
        (JobState.PAUSE_REQUESTED, JobState.CANCEL_REQUESTED),
        (JobState.PAUSE_REQUESTED, JobState.SUCCEEDED),
        (JobState.PAUSED, JobState.RUNNING),
        (JobState.PAUSED, JobState.CANCEL_REQUESTED),
        (JobState.CANCEL_REQUESTED, JobState.CANCELLED),
        (JobState.CANCEL_REQUESTED, JobState.SUCCEEDED),
    ],
)
def test_the_legal_moves_are_legal(current, proposed):
    assert is_legal_transition(current, proposed)
    require_legal_transition(current, proposed)


@pytest.mark.parametrize(
    "current,proposed",
    [
        (JobState.IDLE, JobState.PAUSED),
        (JobState.IDLE, JobState.CANCEL_REQUESTED),
        (JobState.IDLE, JobState.SUCCEEDED),
        (JobState.RUNNING, JobState.PAUSED),
        (JobState.RUNNING, JobState.CANCELLED),
        (JobState.RUNNING, JobState.IDLE),
        (JobState.PAUSED, JobState.PAUSE_REQUESTED),
        (JobState.PAUSED, JobState.CANCELLED),
        (JobState.PAUSED, JobState.SUCCEEDED),
        (JobState.CANCEL_REQUESTED, JobState.PAUSED),
        (JobState.CANCEL_REQUESTED, JobState.RUNNING),
        (JobState.SUCCEEDED, JobState.RUNNING),
        (JobState.CANCELLED, JobState.RUNNING),
    ],
)
def test_the_illegal_moves_are_rejected_deterministically(current, proposed):
    assert not is_legal_transition(current, proposed)
    with pytest.raises(IllegalJobTransition):
        require_legal_transition(current, proposed)


def test_pausing_is_never_instantaneous():
    """Running must pass through PAUSE_REQUESTED; a worker acknowledges PAUSED."""
    assert not is_legal_transition(JobState.RUNNING, JobState.PAUSED)
    assert is_legal_transition(JobState.RUNNING, JobState.PAUSE_REQUESTED)
    assert is_legal_transition(JobState.PAUSE_REQUESTED, JobState.PAUSED)


def test_cancel_overrides_pause_and_is_only_final_after_acknowledgement():
    assert is_legal_transition(JobState.PAUSED, JobState.CANCEL_REQUESTED)
    assert is_legal_transition(JobState.PAUSE_REQUESTED, JobState.CANCEL_REQUESTED)
    assert not is_legal_transition(JobState.PAUSED, JobState.CANCELLED)
    assert is_legal_transition(JobState.CANCEL_REQUESTED, JobState.CANCELLED)


def test_a_request_near_the_end_may_still_report_what_really_happened():
    """A cancel or pause asked for during an indivisible stage does not stop it."""
    assert is_legal_transition(JobState.CANCEL_REQUESTED, JobState.SUCCEEDED)
    assert is_legal_transition(JobState.CANCEL_REQUESTED, JobState.FAILED)
    assert is_legal_transition(JobState.PAUSE_REQUESTED, JobState.COMPLETED_WITH_FAILURES)


def test_the_states_that_lock_the_inputs_are_named():
    """Decision 9A. Deriving the per-control matrix from this set is Phase 6."""
    assert INPUT_LOCKED_STATES == {
        JobState.RUNNING, JobState.PAUSE_REQUESTED,
        JobState.PAUSED, JobState.CANCEL_REQUESTED,
    }
    assert JobState.IDLE not in INPUT_LOCKED_STATES
    assert not (INPUT_LOCKED_STATES & TERMINAL_STATES)


def test_transitions_are_only_between_states():
    with pytest.raises(JobContractError):
        is_legal_transition("running", JobState.PAUSED)


# --------------------------------------------------------------------------- #
# Copy-safe option freezing
# --------------------------------------------------------------------------- #


def test_freezing_copies_rather_than_aliasing():
    live = {"chapters": ["a", "b"], "nested": {"tags": {"x"}}}
    frozen = freeze_options(live)

    live["chapters"].append("c")
    live["nested"]["tags"].add("y")
    live["new"] = 1

    assert frozen["chapters"] == ("a", "b")
    assert frozen["nested"]["tags"] == frozenset({"x"})
    assert "new" not in frozen


def test_freezing_converts_every_container_to_an_immutable_one():
    frozen = freeze_options({
        "list": [1, 2],
        "tuple": (3, 4),
        "set": {5},
        "frozen": frozenset({6}),
        "map": {"deep": {"deeper": [7]}},
    })
    assert isinstance(frozen, MappingProxyType)
    assert isinstance(frozen["list"], tuple)
    assert isinstance(frozen["tuple"], tuple)
    assert isinstance(frozen["set"], frozenset)
    assert isinstance(frozen["frozen"], frozenset)
    assert isinstance(frozen["map"], MappingProxyType)
    assert isinstance(frozen["map"]["deep"], MappingProxyType)
    assert frozen["map"]["deep"]["deeper"] == (7,)
    with pytest.raises(TypeError):
        frozen["list"] = ()


def test_freezing_keeps_the_immutable_values_it_is_given():
    frozen = freeze_options({
        "none": None, "flag": True, "count": 3, "ratio": 0.5,
        "name": "x", "raw": b"y", "path": Path("/tmp/x"), "pure": PurePath("a/b"),
        "state": JobState.RUNNING,
    })
    assert frozen["none"] is None and frozen["flag"] is True
    assert frozen["path"] == Path("/tmp/x")
    assert frozen["state"] is JobState.RUNNING


def test_an_empty_or_absent_payload_is_an_empty_frozen_mapping():
    assert freeze_options(None) == {}
    assert freeze_options({}) == {}
    assert isinstance(freeze_options(None), MappingProxyType)


@dataclasses.dataclass
class _Mutable:
    value: int = 1


@dataclasses.dataclass(frozen=True)
class _Frozen:
    value: int = 1


@dataclasses.dataclass(frozen=True)
class _FrozenButLeaky:
    payload: object = None


def test_a_frozen_dataclass_is_accepted_and_a_mutable_one_is_not():
    frozen = freeze_options({"ok": _Frozen(2)})
    assert frozen["ok"] == _Frozen(2)
    with pytest.raises(OptionFreezeError):
        freeze_options({"bad": _Mutable()})


def test_a_frozen_dataclass_hiding_a_live_object_is_still_rejected():
    with pytest.raises(OptionFreezeError):
        freeze_options({"bad": _FrozenButLeaky(payload=threading.Event())})


@pytest.mark.parametrize(
    "payload",
    [
        {"callable": len},
        {"event": threading.Event()},
        {"lock": threading.Lock()},
        {"module": dataclasses},
        {"object": object()},
        {"buffer": bytearray(b"x")},
        {"view": memoryview(b"x")},
        {"generator": (index for index in range(2))},
        {"nan": float("nan")},
        {"inf": float("inf")},
        {"nested": {"deep": [object()]}},
    ],
)
def test_a_live_or_unusable_payload_is_rejected_rather_than_stored(payload):
    with pytest.raises(OptionFreezeError):
        freeze_options(payload)


def test_option_keys_must_be_strings():
    with pytest.raises(OptionFreezeError):
        freeze_options({1: "x"})
    with pytest.raises(OptionFreezeError):
        freeze_options({"outer": {2: "x"}})


def test_options_must_be_a_mapping():
    for bad in ([("a", 1)], "abc", 5):
        with pytest.raises(OptionFreezeError):
            freeze_options(bad)


def test_a_reference_cycle_is_refused():
    looped: dict = {}
    looped["self"] = looped
    with pytest.raises(OptionFreezeError):
        freeze_options({"outer": looped})

    listed: list = []
    listed.append(listed)
    with pytest.raises(OptionFreezeError):
        freeze_options({"outer": listed})


def test_a_shared_but_acyclic_reference_is_fine():
    shared = {"k": 1}
    frozen = freeze_options({"a": shared, "b": [shared, shared]})
    assert frozen["a"]["k"] == 1
    assert frozen["b"][0]["k"] == 1


def test_a_mapping_view_is_not_mistaken_for_a_container_it_can_copy():
    """A live view over someone else's dict is exactly what must not be stored."""
    live = {"a": 1}
    for view in (live.keys(), live.values(), live.items()):
        with pytest.raises(OptionFreezeError):
            freeze_options({"bad": view})


def test_is_frozen_options_recognises_only_the_real_thing():
    assert is_frozen_options(freeze_options({"a": [1]}))
    assert not is_frozen_options({"a": 1})
    assert not is_frozen_options(MappingProxyType({1: "x"}))
    assert not is_frozen_options(None)


# --------------------------------------------------------------------------- #
# The frozen run snapshot
# --------------------------------------------------------------------------- #


def test_a_snapshot_freezes_the_options_it_is_handed():
    live = {"mode": "split", "chapters": ["a"]}
    run = snapshot(tool_options=live)
    live["mode"] = "whole"
    live["chapters"].append("b")

    assert run.tool_options["mode"] == "split"
    assert run.tool_options["chapters"] == ("a",)
    assert is_frozen_options(run.tool_options)
    with pytest.raises(TypeError):
        run.tool_options["mode"] = "whole"


def test_a_snapshot_refuses_a_live_option_payload_outright():
    with pytest.raises(OptionFreezeError):
        snapshot(tool_options={"widget": threading.Event()})


def test_a_snapshot_exposes_the_ordered_items_of_its_run():
    run = snapshot(count=3)
    assert run.item_ids == ("occ-1", "occ-2", "occ-3")
    assert run.count == 3


def test_a_snapshot_is_immutable_and_slotted():
    run = snapshot()
    with pytest.raises(FrozenInstanceError):
        run.snapshot_id = "other"
    assert not hasattr(run, "__dict__")


def test_a_later_edit_to_the_imported_list_cannot_reach_a_running_snapshot():
    """Decision 9A in data form: the run reads the snapshot, never the live list."""
    run = snapshot(count=1)
    grown = files(3)
    assert run.files.count == 1
    assert grown.count == 3
    assert run.item_ids == ("occ-1",)


def test_a_snapshot_refuses_types_outside_its_own_catalog():
    narrow = SupportedTypeCatalog((SupportedType("m4b", "M4B", (".m4b",)),))
    with pytest.raises(JobContractError):
        RunSnapshot("run", files(1), narrow, ImportOptions.for_catalog(narrow),
                    make_config(), {}, 1.0)


def test_a_snapshot_refuses_a_selection_the_catalog_does_not_know():
    book = catalog()
    with pytest.raises(JobContractError):
        RunSnapshot("run", files(1), book, ImportOptions(selected_type_ids={"epub"}),
                    make_config(), {}, 1.0)


@pytest.mark.parametrize(
    "field,value",
    [
        ("snapshot_id", "  "),
        ("snapshot_id", "two words"),
        ("files", ()),
        ("catalog", None),
        ("import_options", {}),
        ("effective_config", {"importing": {}}),
        ("created_at", -1.0),
        ("created_at", float("inf")),
    ],
)
def test_an_invalid_snapshot_cannot_be_constructed(field, value):
    book = catalog()
    kwargs = dict(
        snapshot_id="run", files=files(1), catalog=book,
        import_options=ImportOptions.for_catalog(book),
        effective_config=make_config(), tool_options={}, created_at=1.0)
    kwargs[field] = value
    with pytest.raises((JobContractError, OptionFreezeError)):
        RunSnapshot(**kwargs)


# --------------------------------------------------------------------------- #
# Failures
# --------------------------------------------------------------------------- #


def test_a_failure_keeps_the_sentence_and_the_diagnostics_apart():
    record = failure("occ-1")
    assert record.display_message == "Something went wrong."
    assert record.technical_detail == "ffmpeg exited 1"
    assert record.retryable is True
    assert record.is_fatal is False


def test_a_fatal_job_failure_has_no_item_and_can_never_be_retryable():
    fatal = FailureRecord(None, "startup", "The run could not start.", "", False, "run-1")
    assert fatal.is_fatal
    with pytest.raises(JobContractError):
        FailureRecord(None, "startup", "The run could not start.", "", True, "run-1")


def test_a_failure_message_must_stay_display_safe():
    with pytest.raises(JobContractError):
        FailureRecord("occ-1", "encode", "line\nline", "", True, "run-1")
    with pytest.raises(JobContractError):
        FailureRecord("occ-1", "encode", "Traceback (most recent call last): x",
                      "", True, "run-1")
    with pytest.raises(JobContractError):
        FailureRecord("occ-1", "encode", "   ", "", True, "run-1")


def test_a_failure_refuses_a_truthy_stand_in_for_retryable():
    with pytest.raises(JobContractError):
        FailureRecord("occ-1", "encode", "Nope.", "", 1, "run-1")


def test_a_log_keeps_failures_in_the_order_they_happened():
    log = FailureLog("run-1", (failure("occ-2"), failure("occ-1"), failure("occ-3", False)))
    assert log.retryable_ids() == ("occ-2", "occ-1")
    assert log.has_retryable
    assert log.for_item("occ-3").retryable is False
    assert log.for_item("nope") is None


def test_an_empty_log_offers_no_retry():
    log = FailureLog("run-1")
    assert log.is_empty and not log.has_retryable and log.retryable_ids() == ()


def test_a_log_refuses_a_record_from_a_different_run():
    with pytest.raises(JobContractError):
        FailureLog("run-1", (failure("occ-1", snapshot_id="run-2"),))


def test_a_log_refuses_two_records_for_one_item():
    """"The ordered subset of failed ids" must not be ambiguous."""
    with pytest.raises(JobContractError):
        FailureLog("run-1", (failure("occ-1"), failure("occ-1", stage="tag")))


def test_a_log_may_hold_several_fatal_records():
    log = FailureLog("run-1", (
        FailureRecord(None, "startup", "One.", "", False, "run-1"),
        FailureRecord(None, "cleanup", "Two.", "", False, "run-1"),
    ))
    assert len(log.fatal) == 2
    assert not log.has_retryable


# --------------------------------------------------------------------------- #
# Retry
# --------------------------------------------------------------------------- #


def test_a_retry_references_the_exact_original_snapshot_object():
    run = snapshot(count=3)
    log = FailureLog("run-1", (failure("occ-2"), failure("occ-3")))
    request = RetryRequest.from_failures(run, log)

    assert request.snapshot is run, "retry must use the run's own frozen configuration"
    assert request.snapshot_id == "run-1"
    assert request.item_ids == ("occ-2", "occ-3")
    assert request.count == 2


def test_a_retry_defaults_to_every_retryable_failure_in_failure_order():
    run = snapshot(count=3)
    log = FailureLog("run-1", (
        failure("occ-3"), failure("occ-1", retryable=False), failure("occ-2")))
    assert RetryRequest.from_failures(run, log).item_ids == ("occ-3", "occ-2")


def test_a_requested_subset_is_normalised_to_failure_order():
    """The same set of ids always produces the same request."""
    run = snapshot(count=3)
    log = FailureLog("run-1", (failure("occ-3"), failure("occ-1"), failure("occ-2")))
    assert RetryRequest.from_failures(run, log, ["occ-2", "occ-3"]).item_ids == (
        "occ-3", "occ-2")


def test_a_retry_is_unavailable_without_a_retryable_failure():
    run = snapshot()
    log = FailureLog("run-1", (failure("occ-1", retryable=False),))
    with pytest.raises(RetryContractError) as excinfo:
        RetryRequest.from_failures(run, log)
    assert "Retry Failed is unavailable" in str(excinfo.value)


def test_a_retry_refuses_a_foreign_snapshot():
    run = snapshot("run-1")
    other = FailureLog("run-2", (failure("occ-1", snapshot_id="run-2"),))
    with pytest.raises(RetryContractError):
        RetryRequest.from_failures(run, other)


@pytest.mark.parametrize(
    "requested,fragment",
    [
        (["occ-1"], "did not fail"),
        (["occ-3"], "not retryable"),
        (["occ-2", "occ-2"], "listed twice"),
        (["nope"], "did not fail"),
    ],
)
def test_a_retry_refuses_an_unknown_successful_duplicate_or_nonretryable_item(
        requested, fragment):
    run = snapshot(count=3)
    log = FailureLog("run-1", (failure("occ-2"), failure("occ-3", retryable=False)))
    with pytest.raises(RetryContractError) as excinfo:
        RetryRequest.from_failures(run, log, requested)
    assert fragment in str(excinfo.value)


def test_a_retry_refuses_an_item_that_is_not_in_the_run():
    run = snapshot(count=1)
    with pytest.raises(RetryContractError):
        RetryRequest(run, ("occ-9",))


def test_a_retry_needs_at_least_one_item():
    run = snapshot()
    with pytest.raises(RetryContractError):
        RetryRequest(run, ())
    with pytest.raises(RetryContractError):
        RetryRequest.from_failures(run, FailureLog("run-1", (failure("occ-1"),)), [])


def test_a_retry_decides_nothing_about_where_output_goes():
    """Placement belongs to the adopting plan, through Plan 2's services."""
    run = snapshot()
    request = RetryRequest.from_failures(run, FailureLog("run-1", (failure("occ-1"),)))
    for absent in ("destination", "output_dir", "run_directory", "reservation"):
        assert not hasattr(request, absent)
    assert set(RetryRequest.__dataclass_fields__) == {"snapshot", "item_ids"}


# --------------------------------------------------------------------------- #
# Events
# --------------------------------------------------------------------------- #


def test_every_event_kind_the_plan_names_exists():
    assert {kind.value for kind in JobEventKind} == {
        "state_changed", "stage_changed", "progress", "current_item", "import_count",
        "warning", "failure", "output_location", "completed", "cancelled",
        "technical_detail",
    }
    assert TERMINAL_EVENT_KINDS == {JobEventKind.COMPLETED, JobEventKind.CANCELLED}


def test_an_event_is_immutable_and_ordered_by_sequence():
    first = JobEvent(JobEventKind.PROGRESS, "run-1", 0, 1.0, completed=1)
    second = JobEvent(JobEventKind.PROGRESS, "run-1", 1, 1.0, completed=2)
    assert first.sequence < second.sequence
    with pytest.raises(FrozenInstanceError):
        first.sequence = 5
    assert not hasattr(first, "__dict__")


def test_a_user_facing_message_stays_one_line_while_detail_may_be_long():
    event = JobEvent(
        JobEventKind.WARNING, "run-1", 0, 1.0,
        message="Two folders were skipped.",
        detail="Traceback (most recent call last):\n  File ...\nPermissionError",
    )
    assert "\n" not in event.message
    assert "\n" in event.detail, "diagnostics survive; they just do not reach Summary"


def test_a_summary_message_may_not_carry_a_traceback():
    with pytest.raises(JobContractError):
        JobEvent(JobEventKind.WARNING, "run-1", 0, 1.0,
                 message="Traceback (most recent call last): boom")


@pytest.mark.parametrize(
    "kind,kwargs",
    [
        (JobEventKind.STATE_CHANGED, {"state": JobState.RUNNING}),
        (JobEventKind.STAGE_CHANGED, {"stage": "encoding"}),
        (JobEventKind.PROGRESS, {"completed": 2, "total": 4}),
        (JobEventKind.PROGRESS, {"completed": 2}),
        (JobEventKind.CURRENT_ITEM, {"item_id": "occ-1"}),
        (JobEventKind.IMPORT_COUNT, {"count": 41}),
        (JobEventKind.WARNING, {"message": "One folder was skipped."}),
        (JobEventKind.FAILURE, {"message": "One file failed.", "item_id": "occ-1"}),
        (JobEventKind.OUTPUT_LOCATION, {"location": ROOT_PATH / "out"}),
        (JobEventKind.COMPLETED, {"state": JobState.SUCCEEDED}),
        (JobEventKind.COMPLETED, {"state": JobState.COMPLETED_WITH_FAILURES}),
        (JobEventKind.CANCELLED, {"state": JobState.CANCELLED}),
        (JobEventKind.CANCELLED, {}),
        (JobEventKind.TECHNICAL_DETAIL, {"detail": "ffmpeg -i x"}),
    ],
)
def test_a_well_formed_event_of_every_kind_can_be_built(kind, kwargs):
    event = JobEvent(kind, "run-1", 0, 1.0, **kwargs)
    assert event.kind is kind
    assert event.is_terminal == (kind in TERMINAL_EVENT_KINDS)


@pytest.mark.parametrize(
    "kind,kwargs",
    [
        (JobEventKind.STATE_CHANGED, {}),
        (JobEventKind.STAGE_CHANGED, {}),
        (JobEventKind.PROGRESS, {}),
        (JobEventKind.PROGRESS, {"completed": 5, "total": 4}),
        (JobEventKind.CURRENT_ITEM, {}),
        (JobEventKind.IMPORT_COUNT, {}),
        (JobEventKind.WARNING, {}),
        (JobEventKind.FAILURE, {}),
        (JobEventKind.OUTPUT_LOCATION, {}),
        (JobEventKind.OUTPUT_LOCATION, {"location": Path("relative/out")}),
        (JobEventKind.COMPLETED, {}),
        (JobEventKind.COMPLETED, {"state": JobState.CANCELLED}),
        (JobEventKind.CANCELLED, {"state": JobState.SUCCEEDED}),
        (JobEventKind.TECHNICAL_DETAIL, {}),
    ],
)
def test_an_event_missing_its_own_payload_is_refused(kind, kwargs):
    with pytest.raises(JobContractError):
        JobEvent(kind, "run-1", 0, 1.0, **kwargs)


@pytest.mark.parametrize(
    "field,value",
    [("run_id", ""), ("run_id", "two words"), ("sequence", -1),
     ("sequence", True), ("timestamp", -0.5), ("timestamp", float("nan"))],
)
def test_an_event_refuses_an_unusable_envelope(field, value):
    kwargs = dict(kind=JobEventKind.CANCELLED, run_id="run-1", sequence=0, timestamp=1.0)
    kwargs[field] = value
    with pytest.raises(JobContractError):
        JobEvent(**kwargs)


def test_an_event_carries_no_eta_or_estimate():
    """ETA is Phase 7. Nothing here may quietly imply it already exists."""
    assert "eta" not in JobEvent.__dataclass_fields__
    assert not [name for name in JobEvent.__dataclass_fields__
                if "estimate" in name or "remaining" in name]


# --------------------------------------------------------------------------- #
# No side effects
# --------------------------------------------------------------------------- #


def test_building_the_whole_job_vocabulary_starts_no_thread_and_writes_nothing(tmp_path):
    threads_before = threading.active_count()
    entries_before = sorted(tmp_path.iterdir())

    run = snapshot(tool_options={"mode": "whole", "targets": [1, 2]})
    log = FailureLog("run-1", (failure("occ-1"),))
    RetryRequest.from_failures(run, log)
    JobEvent(JobEventKind.COMPLETED, "run-1", 3, 9.0, state=JobState.COMPLETED_WITH_FAILURES)

    assert threading.active_count() == threads_before
    assert sorted(tmp_path.iterdir()) == entries_before
