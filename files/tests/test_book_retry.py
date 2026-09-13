"""Book dispositions and Retry Failed — v0.6.3 Drop 1 (Plan 6), Phase 7.

Drop §18. Plan 6 owns the **book-level** outcome vocabulary Plan 3 delegated, and
composes Plan 3's own values by book identity: one existing ``RunResult`` per
attempted book, Plan 3's own ``JobState`` for the batch, and one existing
``RetryRequest`` per retryable book.

Three claims run through everything below.

**A book failure is not a batch failure** (Decision 28A). A run that lost a book but
orchestrated correctly is ``COMPLETED_WITH_FAILURES`` — which is precisely the one
state in which Plan 3 offers Retry Failed at all.

**Nothing is rebuilt** (Decision 37A). The chain
``BookRunSnapshot -> RunResult -> RetryRequest`` holds the *same* ``RunSnapshot``
object at every link, proved with ``is``. An equal-but-distinct copy is the signature
of a rebuilt run, and a retry built from one would quietly use today's configuration
while claiming to re-run the original.

**Phase 7 describes a retry; it never runs one.** ``retry_failed_books`` takes no
workspace, reads nothing live, and returns values. Re-running them is the consumer's
job, exactly as it is today for the Converter, Cover and TTS panels.

Fixtures here build **real** Plan 3 failures — ``FailureRecord`` and ``FailureLog``
against that book's own ``snapshot_id``, naming real occurrence ids — and settle
every per-book result through the existing ``RunResult.settle``. Nothing fakes a
RunResult-shaped object, and no Plan 3 validation is weakened to make a fixture
easier.
"""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path, PurePath

import pytest

from shared import book_workspace
from shared.book_workspace import (
    SKIP_DISPOSITIONS,
    BookDisposition,
    BookIdentityError,
    BookJob,
    BookRunSnapshot,
    SharedMetadata,
    WorkspaceContractError,
    WorkspaceRunResult,
    WorkspaceSnapshot,
    add_book,
    capture_workspace_run,
    effective_metadata,
    new_book_id,
    remove_book,
    replace_book,
    replace_workspace_from_import,
    retry_failed_books,
    set_shared_metadata,
)
from shared.importing import (
    IdFactory,
    ImportedFile,
    ImportedFileSnapshot,
    ImportOptions,
    ImportRoot,
    Revision,
    SupportedType,
    SupportedTypeCatalog,
)
from shared.job_control import (
    FailureLog,
    FailureRecord,
    ItemStatus,
    JobAction,
    JobState,
    RetryRequest,
    RunResult,
    RunSnapshot,
    is_available,
)

from test_book_grouping import scanned
from test_importing import make_config


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

ROOT = Path(os.path.abspath(os.sep + "act-fixture-root"))
CATALOG = SupportedTypeCatalog((SupportedType("mp3", "MP3 audio", (".mp3",)),))
ROOTED = ImportRoot("root-1", ROOT, 0)
FIELDS = ("title", "author")

EMPTY = BookDisposition.SKIPPED_EMPTY
INVALID = BookDisposition.SKIPPED_INVALID
SUCCEEDED = BookDisposition.SUCCEEDED
FAILED = BookDisposition.FAILED
NOT_ATTEMPTED = BookDisposition.NOT_ATTEMPTED

_IDS = IdFactory("t-")


def files(label: str, count: int = 2) -> ImportedFileSnapshot:
    return ImportedFileSnapshot(Revision(1), tuple(
        ImportedFile(f"{label}-occ-{index}", ROOT / label / f"{index}.mp3", ROOTED,
                     PurePath(label) / f"{index}.mp3", "mp3", f"{label}-id-{index}")
        for index in range(1, count + 1)))


def book(label: str = "A", count: int = 2, **configuration) -> BookJob:
    return BookJob(book_id=new_book_id(_IDS), configuration=configuration,
                   files=files(label, count) if count else ImportedFileSnapshot())


def empty_book(**configuration) -> BookJob:
    return BookJob(book_id=new_book_id(_IDS), configuration=configuration)


def workspace(*books: BookJob, shared: SharedMetadata | None = None
              ) -> WorkspaceSnapshot:
    entries = books or (book(),)
    return WorkspaceSnapshot(
        books=entries, current_book_id=entries[0].book_id,
        shared=SharedMetadata.for_fields(FIELDS) if shared is None else shared)


def capture(space: WorkspaceSnapshot, *, is_valid=None) -> BookRunSnapshot:
    return capture_workspace_run(
        space, catalog=CATALOG, import_options=ImportOptions.for_catalog(CATALOG),
        effective_config=make_config(), id_factory=IdFactory("r-"),
        created_at=100.0, is_valid=is_valid)


# -- real Plan 3 outcomes, built through Plan 3's own contracts -------------- #


def succeeded(snapshot: RunSnapshot) -> RunResult:
    """Every occurrence finished. ``settle`` derives SUCCEEDED for itself."""
    return RunResult.settle(snapshot, completed_ids=snapshot.item_ids)


def failed_retryable(snapshot: RunSnapshot) -> RunResult:
    """One real occurrence failed, retryably. -> COMPLETED_WITH_FAILURES."""
    first, *rest = snapshot.item_ids
    log = FailureLog(snapshot_id=snapshot.snapshot_id, records=(
        FailureRecord(item_id=first, stage="encode",
                      display_message="Encoding failed.",
                      technical_detail="ffmpeg exit 1",
                      retryable=True, snapshot_id=snapshot.snapshot_id),
    ))
    return RunResult.settle(snapshot, log, completed_ids=tuple(rest))


def failed_unretryable(snapshot: RunSnapshot) -> RunResult:
    """A real occurrence failed in a way re-running cannot fix."""
    first, *rest = snapshot.item_ids
    log = FailureLog(snapshot_id=snapshot.snapshot_id, records=(
        FailureRecord(item_id=first, stage="probe",
                      display_message="That file is not audio.",
                      technical_detail="unsupported container",
                      retryable=False, snapshot_id=snapshot.snapshot_id),
    ))
    return RunResult.settle(snapshot, log, completed_ids=tuple(rest))


def fatal(snapshot: RunSnapshot) -> RunResult:
    """The book's own run broke as a whole. Plan 3: item_id=None, retryable=False."""
    log = FailureLog(snapshot_id=snapshot.snapshot_id, records=(
        FailureRecord(item_id=None, stage="startup",
                      display_message="The converter could not start.",
                      technical_detail="ffmpeg missing",
                      retryable=False, snapshot_id=snapshot.snapshot_id),
    ))
    return RunResult.settle(snapshot, log)


def cancelled_midway(snapshot: RunSnapshot) -> RunResult:
    """Stopped part-way through this book's own work. -> JobState.CANCELLED."""
    first, *_rest = snapshot.item_ids
    return RunResult.settle(snapshot, completed_ids=(first,), cancelled=True)


def build(*books: BookJob, is_valid=None, outcomes=None,
          state: JobState = JobState.SUCCEEDED, settle_all: bool = True):
    """Capture a workspace and settle the named books. Returns (snapshot, result).

    ``outcomes`` maps a book to the factory that builds its result; a book with no
    entry either succeeds (``settle_all``) or never settles at all.
    """
    space = workspace(*books)
    snapshot = capture(space, is_valid=is_valid)
    chosen = outcomes or {}
    results = []
    for book_id in snapshot.attempted_book_ids:
        run = snapshot.snapshot_for(book_id)
        maker = chosen.get(book_id)
        if maker is None:
            if not settle_all:
                continue
            maker = succeeded
        results.append((book_id, maker(run)))
    return space, WorkspaceRunResult(snapshot=snapshot, results=tuple(results),
                                     state=state)


# --------------------------------------------------------------------------- #
# The vocabulary — section 18.1
# --------------------------------------------------------------------------- #


def test_a_book_has_exactly_five_dispositions():
    assert [member.name for member in BookDisposition] == [
        "SUCCEEDED", "FAILED", "SKIPPED_EMPTY", "SKIPPED_INVALID", "NOT_ATTEMPTED"]
    assert [member.value for member in BookDisposition] == [
        "succeeded", "failed", "skipped_empty", "skipped_invalid", "not_attempted"]


def test_there_is_no_book_level_cancelled():
    """Cancellation is a fact about the batch, and JobState already says it.

    Asking a book "were you cancelled?" gives two different answers for the same run
    depending on how far it got — which is exactly what FAILED and NOT_ATTEMPTED
    already tell apart.
    """
    assert not hasattr(BookDisposition, "CANCELLED")
    assert not hasattr(BookDisposition, "SKIPPED"), "a sixth value by another name"
    assert JobState.CANCELLED.value == "cancelled", "the batch keeps saying it"


def test_plan3_item_status_was_not_widened():
    """A BookJob is not a Plan 3 item, so Plan 3's three answers stay three."""
    assert [member.name for member in ItemStatus] == [
        "SUCCEEDED", "FAILED", "NOT_ATTEMPTED"]
    assert not hasattr(ItemStatus, "SKIPPED")
    assert ItemStatus is not BookDisposition


def test_only_the_two_skip_reasons_belong_to_a_capture():
    assert SKIP_DISPOSITIONS == {EMPTY, INVALID}
    assert SUCCEEDED not in SKIP_DISPOSITIONS
    assert FAILED not in SKIP_DISPOSITIONS
    assert NOT_ATTEMPTED not in SKIP_DISPOSITIONS


# --------------------------------------------------------------------------- #
# Derivation — the one rule, in order
# --------------------------------------------------------------------------- #


def test_a_successful_book_is_succeeded():
    entry = book("A")
    _space, result = build(entry)
    assert result.disposition_for(entry.book_id) is SUCCEEDED


def test_a_book_that_completed_with_failures_is_failed():
    """Its OWN run lost an item; at book level that book did not succeed."""
    entry, other = book("A"), book("B")
    _space, result = build(entry, other,
                           outcomes={entry.book_id: failed_retryable},
                           state=JobState.COMPLETED_WITH_FAILURES)
    assert result.result_for(entry.book_id).state is JobState.COMPLETED_WITH_FAILURES
    assert result.disposition_for(entry.book_id) is FAILED
    assert result.disposition_for(other.book_id) is SUCCEEDED


def test_a_book_whose_run_failed_fatally_is_failed():
    entry, other = book("A"), book("B")
    _space, result = build(entry, other, outcomes={entry.book_id: fatal},
                           state=JobState.COMPLETED_WITH_FAILURES)
    assert result.result_for(entry.book_id).state is JobState.FAILED
    assert result.disposition_for(entry.book_id) is FAILED


def test_a_book_cancelled_part_way_through_its_own_work_is_failed():
    """It was attempted and did not succeed. Anything softer would hide it."""
    entry, other = book("A"), book("B")
    _space, result = build(entry, other, outcomes={entry.book_id: cancelled_midway},
                           state=JobState.CANCELLED)
    assert result.result_for(entry.book_id).state is JobState.CANCELLED
    assert result.disposition_for(entry.book_id) is FAILED
    assert result.disposition_for(entry.book_id) is not NOT_ATTEMPTED


def test_a_captured_empty_book_is_skipped_empty():
    blank = empty_book(title="Configured but empty")
    _space, result = build(book("A"), blank)
    assert result.disposition_for(blank.book_id) is EMPTY
    assert result.result_for(blank.book_id) is None


def test_a_consumer_invalid_book_is_skipped_invalid():
    entry, invalid = book("A"), book("B")
    _space, result = build(entry, invalid,
                           is_valid=lambda candidate: candidate.book_id != invalid.book_id)
    assert result.disposition_for(invalid.book_id) is INVALID
    assert result.result_for(invalid.book_id) is None


def test_a_frozen_book_the_batch_never_reached_is_not_attempted():
    first, never = book("A"), book("B")
    _space, result = build(first, never, outcomes={first.book_id: succeeded},
                           state=JobState.CANCELLED, settle_all=False)
    assert result.result_for(never.book_id) is None
    assert result.disposition_for(never.book_id) is NOT_ATTEMPTED
    assert result.disposition_for(first.book_id) is SUCCEEDED


def test_a_never_started_book_is_never_called_failed():
    """The Plan 3 rule for items, at book level: absence is not failure."""
    first, never = book("A"), book("B")
    _space, result = build(first, never, state=JobState.CANCELLED, settle_all=False)
    assert result.disposition_for(never.book_id) is not FAILED


def test_a_skipped_book_is_never_called_not_attempted():
    """It was ruled out on purpose; "nobody got round to it" is a different fact."""
    blank, invalid, fine = empty_book(), book("B"), book("C")
    _space, result = build(blank, invalid, fine,
                           is_valid=lambda c: c.book_id != invalid.book_id)
    assert result.disposition_for(blank.book_id) is EMPTY
    assert result.disposition_for(invalid.book_id) is INVALID
    for book_id in (blank.book_id, invalid.book_id):
        assert result.disposition_for(book_id) is not NOT_ATTEMPTED


def test_a_book_this_run_never_heard_of_has_no_disposition():
    _space, result = build(book("A"))
    assert result.disposition_for("b-nobody") is None


def test_dispositions_lists_attempted_books_in_frozen_order_then_skips():
    first, blank, second = book("A"), empty_book(), book("B")
    _space, result = build(first, blank, second)
    assert result.dispositions == (
        (first.book_id, SUCCEEDED), (second.book_id, SUCCEEDED),
        (blank.book_id, EMPTY))


def test_there_is_one_derivation_and_the_listing_agrees_with_it():
    first, blank, failing = book("A"), empty_book(), book("C")
    _space, result = build(first, blank, failing,
                           outcomes={failing.book_id: failed_retryable},
                           state=JobState.COMPLETED_WITH_FAILURES)
    for book_id, why in result.dispositions:
        assert result.disposition_for(book_id) is why


# --------------------------------------------------------------------------- #
# Composition — section 18.2
# --------------------------------------------------------------------------- #


def test_the_result_is_frozen_and_slotted():
    _space, result = build(book("A"))
    assert dataclasses.is_dataclass(WorkspaceRunResult)
    params = WorkspaceRunResult.__dataclass_params__
    assert params.frozen is True
    assert WorkspaceRunResult.__slots__
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError, TypeError)):
        result.state = JobState.FAILED
    with pytest.raises((AttributeError, TypeError)):
        result.invented = True


def test_the_result_stores_exactly_three_facts():
    """No counter, no second failure log, no controller, no output, no counts."""
    stored = {entry.name for entry in dataclasses.fields(WorkspaceRunResult)}
    assert stored == {"snapshot", "results", "state"}
    for derived in ("dispositions", "counts", "succeeded_count", "failed_count",
                    "retryable_book_ids", "has_retryable", "can_retry_failed",
                    "numbers", "controller", "destination", "outputs", "failures"):
        assert derived not in stored, derived


def test_the_result_holds_the_exact_captured_snapshot_object():
    space = workspace(book("A"))
    snapshot = capture(space)
    result = WorkspaceRunResult(
        snapshot=snapshot,
        results=((snapshot.attempted_book_ids[0],
                  succeeded(snapshot.runs[0][1])),))
    assert result.snapshot is snapshot


def test_every_stored_result_is_a_real_plan3_run_result():
    _space, result = build(book("A"), book("B"))
    for _book_id, entry in result.results:
        assert isinstance(entry, RunResult)
        assert type(entry) is RunResult, "not a subclass, not a stand-in"


def test_a_run_result_lookalike_is_refused():
    space = workspace(book("A"))
    snapshot = capture(space)
    book_id = snapshot.attempted_book_ids[0]

    class Lookalike:
        state = JobState.SUCCEEDED
        has_retryable = False

        def __init__(self, run):
            self.snapshot = run

        def retry(self):
            raise AssertionError("never reached")

    for wrong in (Lookalike(snapshot.runs[0][1]), None, "result", {"state": "ok"}):
        with pytest.raises(WorkspaceContractError):
            WorkspaceRunResult(snapshot=snapshot, results=((book_id, wrong),))


def test_a_result_for_an_unknown_book_is_refused():
    space = workspace(book("A"))
    snapshot = capture(space)
    with pytest.raises(BookIdentityError):
        WorkspaceRunResult(snapshot=snapshot,
                           results=(("b-nobody", succeeded(snapshot.runs[0][1])),))


def test_a_result_for_a_skipped_book_is_refused():
    """It received no snapshot, so it cannot have run, so it has no result."""
    entry, blank = book("A"), empty_book()
    space = workspace(entry, blank)
    snapshot = capture(space)
    with pytest.raises(BookIdentityError):
        WorkspaceRunResult(
            snapshot=snapshot,
            results=((entry.book_id, succeeded(snapshot.runs[0][1])),
                     (blank.book_id, succeeded(snapshot.runs[0][1]))))


def test_a_duplicate_book_result_is_refused():
    space = workspace(book("A"))
    snapshot = capture(space)
    book_id, run = snapshot.runs[0]
    with pytest.raises(BookIdentityError):
        WorkspaceRunResult(snapshot=snapshot,
                           results=((book_id, succeeded(run)),
                                    (book_id, failed_retryable(run))))


def test_a_result_carrying_another_books_snapshot_is_refused():
    """The central protection: a retry must never re-run the wrong book."""
    first, second = book("A"), book("B")
    space = workspace(first, second)
    snapshot = capture(space)
    (first_id, first_run), (second_id, second_run) = snapshot.runs
    with pytest.raises(WorkspaceContractError):
        WorkspaceRunResult(
            snapshot=snapshot,
            results=((first_id, succeeded(second_run)),
                     (second_id, succeeded(second_run))))


def test_an_equal_but_distinct_snapshot_copy_is_refused():
    """Identity, not equality. A rebuilt snapshot is a rebuilt run."""
    space = workspace(book("A"))
    snapshot = capture(space)
    book_id, run = snapshot.runs[0]

    copy = dataclasses.replace(run)
    assert copy == run and copy is not run, "the fixture must really be a copy"

    with pytest.raises(WorkspaceContractError):
        WorkspaceRunResult(snapshot=snapshot, results=((book_id, succeeded(copy)),))


@pytest.mark.parametrize("bad", ["results", b"results", 7, None])
def test_results_must_be_an_iterable_of_pairs(bad):
    snapshot = capture(workspace(book("A")))
    with pytest.raises(WorkspaceContractError):
        WorkspaceRunResult(snapshot=snapshot, results=bad, state=JobState.CANCELLED)


def test_a_result_entry_must_be_a_pair():
    snapshot = capture(workspace(book("A")))
    run = snapshot.runs[0][1]
    for wrong in [("b-1",), ("b-1", succeeded(run), "extra"), "b-1"]:
        with pytest.raises(WorkspaceContractError):
            WorkspaceRunResult(snapshot=snapshot, results=(wrong,),
                               state=JobState.CANCELLED)


@pytest.mark.parametrize("wrong", [None, "snapshot", 3, {"runs": ()}])
def test_the_snapshot_must_be_the_phase_five_composition(wrong):
    with pytest.raises(WorkspaceContractError):
        WorkspaceRunResult(snapshot=wrong)


# --------------------------------------------------------------------------- #
# Result order
# --------------------------------------------------------------------------- #


def test_results_are_canonicalised_into_the_frozen_attempted_order():
    first, second, third = book("A"), book("B"), book("C")
    space = workspace(first, second, third)
    snapshot = capture(space)
    runs = dict(snapshot.runs)

    # Handed over backwards.
    result = WorkspaceRunResult(snapshot=snapshot, results=(
        (third.book_id, succeeded(runs[third.book_id])),
        (first.book_id, succeeded(runs[first.book_id])),
        (second.book_id, succeeded(runs[second.book_id])),
    ))
    assert tuple(book_id for book_id, _ in result.results) == (
        first.book_id, second.book_id, third.book_id)
    assert tuple(book_id for book_id, _ in result.results) == \
        snapshot.attempted_book_ids


def test_a_mapping_of_results_is_accepted_and_canonicalised():
    first, second = book("A"), book("B")
    space = workspace(first, second)
    snapshot = capture(space)
    runs = dict(snapshot.runs)
    result = WorkspaceRunResult(snapshot=snapshot, results={
        second.book_id: succeeded(runs[second.book_id]),
        first.book_id: succeeded(runs[first.book_id]),
    })
    assert tuple(book_id for book_id, _ in result.results) == (
        first.book_id, second.book_id)


def test_the_order_is_not_a_global_sort_of_ids():
    """Frozen workspace order, which need not be alphabetical."""
    late = BookJob(book_id="z-first", files=files("A"))
    early = BookJob(book_id="a-second", files=files("B"))
    space = workspace(late, early)
    snapshot = capture(space)
    runs = dict(snapshot.runs)
    result = WorkspaceRunResult(snapshot=snapshot, results=(
        (early.book_id, succeeded(runs[early.book_id])),
        (late.book_id, succeeded(runs[late.book_id])),
    ))
    assert tuple(book_id for book_id, _ in result.results) == ("z-first", "a-second")


# --------------------------------------------------------------------------- #
# Batch state — Plan 3's JobState, reused
# --------------------------------------------------------------------------- #


def test_the_batch_state_is_plan3s_own_job_state():
    _space, result = build(book("A"))
    assert isinstance(result.state, JobState)
    assert not hasattr(book_workspace, "WorkspaceState")


@pytest.mark.parametrize("state", [
    JobState.IDLE, JobState.RUNNING, JobState.PAUSED, JobState.PAUSE_REQUESTED,
    JobState.CANCEL_REQUESTED,
])
def test_a_non_terminal_batch_state_is_refused(state):
    """A result describes a finished run."""
    space = workspace(book("A"))
    snapshot = capture(space)
    book_id, run = snapshot.runs[0]
    with pytest.raises(WorkspaceContractError):
        WorkspaceRunResult(snapshot=snapshot, results=((book_id, succeeded(run)),),
                           state=state)


@pytest.mark.parametrize("wrong", ["succeeded", None, 3, ItemStatus.SUCCEEDED])
def test_the_batch_state_must_be_a_job_state(wrong):
    snapshot = capture(workspace(book("A")))
    with pytest.raises(WorkspaceContractError):
        WorkspaceRunResult(snapshot=snapshot, state=wrong)


def test_succeeded_needs_every_eligible_book_to_have_succeeded():
    entry, other = book("A"), book("B")
    space = workspace(entry, other)
    snapshot = capture(space)
    runs = dict(snapshot.runs)
    with pytest.raises(WorkspaceContractError):
        WorkspaceRunResult(snapshot=snapshot, results=(
            (entry.book_id, succeeded(runs[entry.book_id])),
            (other.book_id, failed_retryable(runs[other.book_id])),
        ), state=JobState.SUCCEEDED)


def test_succeeded_needs_every_attempted_book_to_have_settled():
    entry, other = book("A"), book("B")
    space = workspace(entry, other)
    snapshot = capture(space)
    runs = dict(snapshot.runs)
    with pytest.raises(WorkspaceContractError):
        WorkspaceRunResult(
            snapshot=snapshot,
            results=((entry.book_id, succeeded(runs[entry.book_id])),),
            state=JobState.SUCCEEDED)


def test_skipped_books_do_not_stop_a_batch_from_succeeding():
    """An empty or invalid book is not a failure."""
    entry, blank, invalid = book("A"), empty_book(), book("C")
    _space, result = build(entry, blank, invalid,
                           is_valid=lambda c: c.book_id != invalid.book_id,
                           state=JobState.SUCCEEDED)
    assert result.state is JobState.SUCCEEDED
    assert result.skipped_empty_count == 1 and result.skipped_invalid_count == 1


def test_completed_with_failures_needs_a_book_that_did_not_succeed():
    entry, other = book("A"), book("B")
    space = workspace(entry, other)
    snapshot = capture(space)
    runs = dict(snapshot.runs)
    with pytest.raises(WorkspaceContractError):
        WorkspaceRunResult(snapshot=snapshot, results=(
            (entry.book_id, succeeded(runs[entry.book_id])),
            (other.book_id, succeeded(runs[other.book_id])),
        ), state=JobState.COMPLETED_WITH_FAILURES)


def test_completed_with_failures_needs_every_attempted_book_to_have_settled():
    entry, other = book("A"), book("B")
    space = workspace(entry, other)
    snapshot = capture(space)
    runs = dict(snapshot.runs)
    with pytest.raises(WorkspaceContractError):
        WorkspaceRunResult(
            snapshot=snapshot,
            results=((entry.book_id, failed_retryable(runs[entry.book_id])),),
            state=JobState.COMPLETED_WITH_FAILURES)


def test_a_cancelled_batch_may_leave_later_books_unsettled():
    first, second, third = book("A"), book("B"), book("C")
    _space, result = build(first, second, third,
                           outcomes={first.book_id: succeeded},
                           state=JobState.CANCELLED, settle_all=False)
    assert result.disposition_for(first.book_id) is SUCCEEDED
    assert result.disposition_for(second.book_id) is NOT_ATTEMPTED
    assert result.disposition_for(third.book_id) is NOT_ATTEMPTED


def test_a_cancelled_batch_keeps_what_already_settled():
    first, second, third = book("A"), book("B"), book("C")
    _space, result = build(first, second, third, outcomes={
        first.book_id: succeeded, second.book_id: failed_retryable,
    }, state=JobState.CANCELLED, settle_all=False)
    assert result.disposition_for(first.book_id) is SUCCEEDED
    assert result.disposition_for(second.book_id) is FAILED
    assert result.disposition_for(third.book_id) is NOT_ATTEMPTED


def test_a_cancelled_batch_keeps_the_captured_skip_reasons():
    blank, invalid, fine = empty_book(), book("B"), book("C")
    _space, result = build(blank, invalid, fine,
                           is_valid=lambda c: c.book_id != invalid.book_id,
                           state=JobState.CANCELLED, settle_all=False)
    assert result.disposition_for(blank.book_id) is EMPTY
    assert result.disposition_for(invalid.book_id) is INVALID


def test_a_failed_batch_may_leave_later_books_unattempted():
    first, second = book("A"), book("B")
    _space, result = build(first, second, outcomes={first.book_id: fatal},
                           state=JobState.FAILED, settle_all=False)
    assert result.disposition_for(first.book_id) is FAILED
    assert result.disposition_for(second.book_id) is NOT_ATTEMPTED


# --------------------------------------------------------------------------- #
# Decision 28A — a book failure is not a batch failure
# --------------------------------------------------------------------------- #


def test_a_lost_book_does_not_make_the_batch_failed():
    """A succeeds, B fails, C succeeds. The batch orchestrated fine."""
    first, failing, last = book("A"), book("B"), book("C")
    _space, result = build(first, failing, last,
                           outcomes={failing.book_id: failed_retryable},
                           state=JobState.COMPLETED_WITH_FAILURES)

    assert result.state is JobState.COMPLETED_WITH_FAILURES
    assert result.state is not JobState.FAILED
    assert result.dispositions == (
        (first.book_id, SUCCEEDED), (failing.book_id, FAILED),
        (last.book_id, SUCCEEDED))


def test_the_failure_did_not_abort_the_books_after_it():
    """Decision 28A: report it, carry on. C settled, so C was reached."""
    first, failing, last = book("A"), book("B"), book("C")
    _space, result = build(first, failing, last,
                           outcomes={failing.book_id: failed_retryable},
                           state=JobState.COMPLETED_WITH_FAILURES)
    assert result.result_for(last.book_id) is not None
    assert result.disposition_for(last.book_id) is not NOT_ATTEMPTED


def test_even_a_book_whose_own_run_failed_fatally_leaves_the_batch_completed():
    """The book's run broke; the batch's orchestration did not."""
    first, broken, last = book("A"), book("B"), book("C")
    _space, result = build(first, broken, last, outcomes={broken.book_id: fatal},
                           state=JobState.COMPLETED_WITH_FAILURES)
    assert result.result_for(broken.book_id).state is JobState.FAILED
    assert result.state is JobState.COMPLETED_WITH_FAILURES


# --------------------------------------------------------------------------- #
# Counts
# --------------------------------------------------------------------------- #


def test_every_disposition_is_counted():
    _space, result = build(book("A"))
    assert set(result.counts) == set(BookDisposition)


def test_a_mixed_run_counts_each_kind_once():
    won, lost, blank, invalid, never = (
        book("A"), book("B"), empty_book(), book("D"), book("E"))
    _space, result = build(won, lost, blank, invalid, never,
                           is_valid=lambda c: c.book_id != invalid.book_id,
                           outcomes={won.book_id: succeeded,
                                     lost.book_id: failed_retryable},
                           state=JobState.CANCELLED, settle_all=False)
    assert result.succeeded_count == 1
    assert result.failed_count == 1
    assert result.skipped_empty_count == 1
    assert result.skipped_invalid_count == 1
    assert result.not_attempted_count == 1
    assert sum(result.counts.values()) == 5, "every book counted exactly once"


def test_the_counts_agree_with_the_listing_they_summarise():
    won, lost, blank = book("A"), book("B"), empty_book()
    _space, result = build(won, lost, blank,
                           outcomes={lost.book_id: failed_retryable},
                           state=JobState.COMPLETED_WITH_FAILURES)
    for why, count in result.counts.items():
        assert count == sum(1 for _b, found in result.dispositions if found is why)


def test_the_counts_are_a_read_only_view():
    _space, result = build(book("A"))
    with pytest.raises(TypeError):
        result.counts[SUCCEEDED] = 99


def test_counts_are_derived_rather_than_stored():
    stored = {entry.name for entry in dataclasses.fields(WorkspaceRunResult)}
    for name in ("counts", "succeeded_count", "failed_count", "skipped_empty_count",
                 "skipped_invalid_count", "not_attempted_count"):
        assert name not in stored, name
        assert isinstance(WorkspaceRunResult.__dict__[name], property)


# --------------------------------------------------------------------------- #
# Retryability
# --------------------------------------------------------------------------- #


def test_a_failed_book_with_a_retryable_failure_is_retryable():
    entry = book("A")
    _space, result = build(entry, book("B"),
                           outcomes={entry.book_id: failed_retryable},
                           state=JobState.COMPLETED_WITH_FAILURES)
    assert result.retryable_book_ids == (entry.book_id,)
    assert result.has_retryable is True


def test_a_failed_book_with_no_retryable_failure_is_excluded():
    entry = book("A")
    _space, result = build(entry, book("B"),
                           outcomes={entry.book_id: failed_unretryable},
                           state=JobState.COMPLETED_WITH_FAILURES)
    assert result.disposition_for(entry.book_id) is FAILED
    assert result.retryable_book_ids == ()
    assert result.has_retryable is False


def test_a_fatally_failed_book_is_excluded():
    """Plan 3: a fatal failure can never be retryable, so neither can its book."""
    entry = book("A")
    _space, result = build(entry, book("B"), outcomes={entry.book_id: fatal},
                           state=JobState.COMPLETED_WITH_FAILURES)
    assert result.disposition_for(entry.book_id) is FAILED
    assert result.retryable_book_ids == ()


def test_a_succeeded_book_is_never_retryable():
    entry = book("A")
    _space, result = build(entry)
    assert result.disposition_for(entry.book_id) is SUCCEEDED
    assert result.retryable_book_ids == ()


def test_neither_skip_is_ever_retryable():
    blank, invalid = empty_book(), book("B")
    _space, result = build(book("A"), blank, invalid,
                           is_valid=lambda c: c.book_id != invalid.book_id)
    assert result.retryable_book_ids == ()
    assert blank.book_id not in result.retryable_book_ids
    assert invalid.book_id not in result.retryable_book_ids


def test_a_not_attempted_book_is_never_retryable():
    """The same rule Plan 3 states for items: absence is not failure."""
    first, never = book("A"), book("B")
    _space, result = build(first, never, state=JobState.CANCELLED, settle_all=False)
    assert result.disposition_for(never.book_id) is NOT_ATTEMPTED
    assert never.book_id not in result.retryable_book_ids


def test_retryable_ids_follow_the_frozen_run_order():
    """Not the order failures arrived across books, and not the caller's."""
    first, second, third, fourth = book("A"), book("B"), book("C"), book("D")
    space = workspace(first, second, third, fourth)
    snapshot = capture(space)
    runs = dict(snapshot.runs)
    # Handed over in a deliberately jumbled order.
    result = WorkspaceRunResult(snapshot=snapshot, results=(
        (fourth.book_id, failed_retryable(runs[fourth.book_id])),
        (second.book_id, failed_retryable(runs[second.book_id])),
        (third.book_id, succeeded(runs[third.book_id])),
        (first.book_id, failed_retryable(runs[first.book_id])),
    ), state=JobState.COMPLETED_WITH_FAILURES)

    assert result.retryable_book_ids == (
        first.book_id, second.book_id, fourth.book_id)


def test_retryability_is_not_re_derived_from_failure_records():
    """RunResult already derives it; a second reading is a second opinion."""
    entry = book("A")
    _space, result = build(entry, book("B"),
                           outcomes={entry.book_id: failed_retryable},
                           state=JobState.COMPLETED_WITH_FAILURES)
    run_result = result.result_for(entry.book_id)
    assert run_result.has_retryable is True
    assert (entry.book_id in result.retryable_book_ids) is run_result.has_retryable


# --------------------------------------------------------------------------- #
# Availability — Plan 3's table, delegated whole
# --------------------------------------------------------------------------- #


def test_retry_failed_availability_is_plan3s_answer():
    entry = book("A")
    _space, result = build(entry, book("B"),
                           outcomes={entry.book_id: failed_retryable},
                           state=JobState.COMPLETED_WITH_FAILURES)
    assert result.can_retry_failed is is_available(
        JobAction.RETRY_FAILED, result.state, has_retryable=result.has_retryable)


def test_completed_with_failures_and_something_retryable_offers_retry():
    entry = book("A")
    _space, result = build(entry, book("B"),
                           outcomes={entry.book_id: failed_retryable},
                           state=JobState.COMPLETED_WITH_FAILURES)
    assert result.can_retry_failed is True


def test_completed_with_failures_and_nothing_retryable_does_not():
    """Offering it would promise something the model cannot deliver."""
    entry = book("A")
    _space, result = build(entry, book("B"),
                           outcomes={entry.book_id: failed_unretryable},
                           state=JobState.COMPLETED_WITH_FAILURES)
    assert result.has_retryable is False
    assert result.can_retry_failed is False


def test_a_succeeded_batch_never_offers_retry():
    _space, result = build(book("A"))
    assert result.can_retry_failed is False


def test_a_cancelled_batch_never_offers_retry():
    """Even with a genuinely retryable book: Plan 3's table says CWF only."""
    entry = book("A")
    _space, result = build(entry, book("B"),
                           outcomes={entry.book_id: failed_retryable},
                           state=JobState.CANCELLED, settle_all=False)
    assert result.has_retryable is True, "the book itself is retryable"
    assert result.can_retry_failed is False, "but the batch state forbids offering it"
    assert is_available(JobAction.RETRY_FAILED, JobState.CANCELLED,
                        has_retryable=True) is False


def test_a_failed_batch_never_offers_retry():
    entry = book("A")
    _space, result = build(entry, book("B"),
                           outcomes={entry.book_id: failed_retryable},
                           state=JobState.FAILED, settle_all=False)
    assert result.can_retry_failed is False
    assert is_available(JobAction.RETRY_FAILED, JobState.FAILED,
                        has_retryable=True) is False


def test_plan6_does_not_restate_the_action_state_table():
    """A second copy is a second chance to disagree with the controller."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(WorkspaceRunResult))
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    called |= {node.func.id for node in ast.walk(tree)
               if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert "is_available" in called
    source = inspect.getsource(book_workspace)
    assert "_ACTION_STATES" not in source
    assert not hasattr(book_workspace, "_ACTION_STATES")


# --------------------------------------------------------------------------- #
# Retry Failed — section 18.3, Decision 37A
# --------------------------------------------------------------------------- #


def test_one_request_per_retryable_book():
    first, second, won = book("A"), book("B"), book("C")
    _space, result = build(first, second, won, outcomes={
        first.book_id: failed_retryable, second.book_id: failed_retryable,
    }, state=JobState.COMPLETED_WITH_FAILURES)

    requests = retry_failed_books(result)
    assert len(requests) == 2 == len(result.retryable_book_ids)


def test_the_returned_values_are_plan3_retry_requests():
    entry = book("A")
    _space, result = build(entry, book("B"),
                           outcomes={entry.book_id: failed_retryable},
                           state=JobState.COMPLETED_WITH_FAILURES)
    for request in retry_failed_books(result):
        assert isinstance(request, RetryRequest)
        assert type(request) is RetryRequest, "not a wrapper, not a subclass"


def test_plan6_invented_no_retry_type():
    for invented in ("BookRetryRequest", "WorkspaceRetryRequest", "BookRetry",
                     "RetryManager", "RetryController"):
        assert not hasattr(book_workspace, invented), invented
    assert book_workspace.RetryRequest is RetryRequest


def test_each_request_is_built_by_that_books_own_run_result():
    entry = book("A")
    _space, result = build(entry, book("B"),
                           outcomes={entry.book_id: failed_retryable},
                           state=JobState.COMPLETED_WITH_FAILURES)
    request = retry_failed_books(result)[0]
    expected = result.result_for(entry.book_id).retry()
    assert request == expected


def test_retry_delegates_to_run_result_retry_rather_than_building_a_request():
    """Structural: the production path calls .retry(), it does not construct one."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(retry_failed_books))
    attrs = {node.func.attr for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    names = {node.func.id for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert "retry" in attrs
    assert "RetryRequest" not in names, "constructed instead of delegated"
    assert "from_failures" not in attrs, "bypassed RunResult.retry"


def test_the_requests_are_in_retryable_book_id_order():
    """The zip contract: the ids and the requests line up, position for position."""
    first, second, third = book("A"), book("B"), book("C")
    space = workspace(first, second, third)
    snapshot = capture(space)
    runs = dict(snapshot.runs)
    result = WorkspaceRunResult(snapshot=snapshot, results=(
        (third.book_id, failed_retryable(runs[third.book_id])),
        (first.book_id, failed_retryable(runs[first.book_id])),
        (second.book_id, succeeded(runs[second.book_id])),
    ), state=JobState.COMPLETED_WITH_FAILURES)

    requests = retry_failed_books(result)
    assert result.retryable_book_ids == (first.book_id, third.book_id)
    for book_id, request in zip(result.retryable_book_ids, requests, strict=True):
        assert request.snapshot is result.snapshot.snapshot_for(book_id)


def test_the_failed_item_subset_comes_from_that_books_own_failure_log():
    entry = book("A", count=3)
    _space, result = build(entry, book("B"),
                           outcomes={entry.book_id: failed_retryable},
                           state=JobState.COMPLETED_WITH_FAILURES)
    run_result = result.result_for(entry.book_id)
    request = retry_failed_books(result)[0]

    assert request.item_ids == run_result.retryable_ids
    assert request.item_ids == run_result.failures.retryable_ids()
    assert set(request.item_ids) < set(request.snapshot.item_ids), "a subset"


def test_nothing_retryable_yields_no_requests():
    entry = book("A")
    _space, result = build(entry, book("B"),
                           outcomes={entry.book_id: failed_unretryable},
                           state=JobState.COMPLETED_WITH_FAILURES)
    assert retry_failed_books(result) == ()


def test_a_wholly_successful_run_yields_no_requests():
    _space, result = build(book("A"), book("B"))
    assert retry_failed_books(result) == ()


def test_skipped_and_not_attempted_books_never_appear_in_the_requests():
    won, lost, blank, invalid, never = (
        book("A"), book("B"), empty_book(), book("D"), book("E"))
    _space, result = build(won, lost, blank, invalid, never,
                           is_valid=lambda c: c.book_id != invalid.book_id,
                           outcomes={won.book_id: succeeded,
                                     lost.book_id: failed_retryable},
                           state=JobState.CANCELLED, settle_all=False)

    requests = retry_failed_books(result)
    assert len(requests) == 1
    assert requests[0].snapshot is result.snapshot.snapshot_for(lost.book_id)
    for excluded in (blank.book_id, invalid.book_id, never.book_id, won.book_id):
        assert excluded not in result.retryable_book_ids


@pytest.mark.parametrize("wrong", [None, "result", 7, {"state": "cancelled"}])
def test_retry_failed_books_refuses_anything_but_a_workspace_result(wrong):
    with pytest.raises(WorkspaceContractError):
        retry_failed_books(wrong)


def test_retry_failed_books_takes_no_workspace_parameter():
    """There is nothing a live workspace could contribute — so it cannot ask."""
    import inspect

    parameters = inspect.signature(retry_failed_books).parameters
    assert list(parameters) == ["result"]
    for live in ("workspace", "space", "snapshot", "books", "id_factory"):
        assert live not in parameters, live


# --------------------------------------------------------------------------- #
# The identity chain — no copy, no recapture
# --------------------------------------------------------------------------- #


def test_the_whole_chain_holds_one_snapshot_object():
    """BookRunSnapshot -> RunResult -> RetryRequest, all the same object."""
    entry = book("A")
    space = workspace(entry, book("B"))
    captured = capture(space)
    runs = dict(captured.runs)
    original = runs[entry.book_id]

    result = WorkspaceRunResult(snapshot=captured, results=(
        (entry.book_id, failed_retryable(original)),
        (captured.attempted_book_ids[1], succeeded(runs[captured.attempted_book_ids[1]])),
    ), state=JobState.COMPLETED_WITH_FAILURES)

    assert result.snapshot is captured
    assert result.snapshot.snapshot_for(entry.book_id) is original
    assert result.result_for(entry.book_id).snapshot is original
    assert retry_failed_books(result)[0].snapshot is original


def test_the_same_book_id_maps_to_the_same_snapshot_across_the_retry():
    first, second = book("A"), book("B")
    _space, result = build(first, second, outcomes={
        first.book_id: failed_retryable, second.book_id: failed_retryable,
    }, state=JobState.COMPLETED_WITH_FAILURES)

    requests = retry_failed_books(result)
    for book_id, request in zip(result.retryable_book_ids, requests, strict=True):
        assert request.snapshot is result.snapshot.snapshot_for(book_id)
        assert request.snapshot is not result.snapshot.snapshot_for(
            next(other for other in result.retryable_book_ids if other != book_id))


def test_book_identity_is_not_encoded_into_the_snapshot_id():
    """The (book_id, RunSnapshot) pair carries the mapping; a decoded id would be
    a second one."""
    entry = book("A")
    _space, result = build(entry, book("B"),
                           outcomes={entry.book_id: failed_retryable},
                           state=JobState.COMPLETED_WITH_FAILURES)
    request = retry_failed_books(result)[0]
    assert entry.book_id not in request.snapshot.snapshot_id
    assert request.snapshot.snapshot_id.startswith("r-run-")


def test_the_request_does_not_hold_a_book_id_of_its_own():
    """RetryRequest is a Plan 3 value and Phase 7 did not widen it."""
    entry = book("A")
    _space, result = build(entry, book("B"),
                           outcomes={entry.book_id: failed_retryable},
                           state=JobState.COMPLETED_WITH_FAILURES)
    stored = {field.name for field in dataclasses.fields(RetryRequest)}
    assert stored == {"snapshot", "item_ids"}
    assert "book_id" not in stored


def test_calling_retry_twice_still_names_the_same_snapshot_object():
    entry = book("A")
    _space, result = build(entry, book("B"),
                           outcomes={entry.book_id: failed_retryable},
                           state=JobState.COMPLETED_WITH_FAILURES)
    first_call = retry_failed_books(result)
    second_call = retry_failed_books(result)
    assert first_call == second_call
    assert first_call[0].snapshot is second_call[0].snapshot


# --------------------------------------------------------------------------- #
# Nothing live — Decision 37A, the central proof
# --------------------------------------------------------------------------- #


def test_a_retry_reads_nothing_live_however_the_workspace_changes():
    """Mutate every layer there is, then ask again. Nothing moves."""
    won, lost = book("A", **{"title": "Original", "bitrate": 128}), book("B")
    space = workspace(won, lost)
    captured = capture(space)
    runs = dict(captured.runs)

    result = WorkspaceRunResult(snapshot=captured, results=(
        (won.book_id, succeeded(runs[won.book_id])),
        (lost.book_id, failed_retryable(runs[lost.book_id])),
    ), state=JobState.COMPLETED_WITH_FAILURES)

    before_ids = result.retryable_book_ids
    before = retry_failed_books(result)
    snapshots = [request.snapshot for request in before]
    item_ids = [request.item_ids for request in before]
    options = [dict(request.snapshot.tool_options) for request in before]
    file_lists = [request.snapshot.files for request in before]
    captured_metadata = effective_metadata(captured.shared, lost)

    # 1. per-book configuration
    changed = replace_book(space, BookJob(book_id=lost.book_id,
                                          configuration={"title": "Rewritten",
                                                         "bitrate": 320},
                                          files=lost.files)).workspace
    # 2. Shared Metadata
    changed = set_shared_metadata(
        changed, SharedMetadata(FIELDS, {"title": "Shared now"})).workspace
    # 3. that book's imported files
    changed = replace_book(changed, BookJob(book_id=lost.book_id,
                                            files=files("Replaced", 4))).workspace
    # 4. add a book
    changed = add_book(changed, id_factory=IdFactory("late-")).workspace
    # 5. remove one
    changed = remove_book(changed, id_factory=IdFactory("late-")).workspace
    # 6. throw the entire workspace away and re-import
    replace_workspace_from_import(changed, scanned("Elsewhere"),
                                  id_factory=IdFactory("late-"))

    after = retry_failed_books(result)
    assert result.retryable_book_ids == before_ids
    assert after == before
    for index, request in enumerate(after):
        assert request.snapshot is snapshots[index], "the original object"
        assert request.item_ids == item_ids[index]
        assert dict(request.snapshot.tool_options) == options[index]
        assert request.snapshot.files is file_lists[index]
    assert effective_metadata(captured.shared, lost) == captured_metadata


def test_the_dispositions_do_not_move_when_the_workspace_does():
    won, lost, blank = book("A"), book("B"), empty_book()
    space = workspace(won, lost, blank)
    captured = capture(space)
    runs = dict(captured.runs)
    result = WorkspaceRunResult(snapshot=captured, results=(
        (won.book_id, succeeded(runs[won.book_id])),
        (lost.book_id, failed_retryable(runs[lost.book_id])),
    ), state=JobState.COMPLETED_WITH_FAILURES)
    before = result.dispositions

    replace_book(space, BookJob(book_id=blank.book_id, files=files("NowFull")))
    set_shared_metadata(space, SharedMetadata(FIELDS, {"title": "Later"}))
    add_book(space, id_factory=IdFactory("late-"))

    assert result.dispositions == before
    assert result.disposition_for(blank.book_id) is EMPTY, "as captured"


def test_the_result_needs_nothing_from_the_workspace_it_came_from():
    """Everything a retry consumes is already inside the frozen value."""
    entry = book("A", **{"title": "Frozen"})
    space = workspace(entry, book("B"))
    captured = capture(space)
    runs = dict(captured.runs)
    result = WorkspaceRunResult(snapshot=captured, results=(
        (entry.book_id, failed_retryable(runs[entry.book_id])),
        (captured.attempted_book_ids[1],
         succeeded(runs[captured.attempted_book_ids[1]])),
    ), state=JobState.COMPLETED_WITH_FAILURES)

    del space
    request = retry_failed_books(result)[0]
    assert request.item_ids
    assert request.snapshot.tool_options["title"] == "Frozen"
    assert request.snapshot.files is entry.files
    assert request.snapshot.item_ids


# --------------------------------------------------------------------------- #
# Retry executes nothing
# --------------------------------------------------------------------------- #


def test_building_a_retry_captures_nothing_and_mints_no_id():
    """A spy on the one capture path: Retry Failed must never reach it."""
    calls = []
    original = book_workspace.capture_run

    entry = book("A")
    _space, result = build(entry, book("B"),
                           outcomes={entry.book_id: failed_retryable},
                           state=JobState.COMPLETED_WITH_FAILURES)

    def spy(**kwargs):
        calls.append(kwargs)
        return original(**kwargs)

    book_workspace.capture_run = spy
    try:
        retry_failed_books(result)
    finally:
        book_workspace.capture_run = original
    assert calls == [], "a retry re-runs a snapshot; it does not make one"


def test_retry_construction_reaches_no_worker_disk_or_process():
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(retry_failed_books))
    called = {node.func.id for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    called |= {node.func.attr for node in ast.walk(tree)
               if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    for forbidden in ("Thread", "Popen", "run", "open", "mkdir", "makedirs",
                      "capture_run", "capture_workspace_run", "SuccessNumbers",
                      "JobController", "reserve_run_directory", "propose", "commit"):
        assert forbidden not in called, forbidden


def test_no_job_controller_is_built_or_stored_anywhere():
    """One controller per run, and the consumer owns it."""
    won = book("A")
    _space, result = build(won)
    for record in (BookRunSnapshot, WorkspaceRunResult, BookJob, WorkspaceSnapshot):
        stored = {entry.name for entry in dataclasses.fields(record)}
        for name in ("controller", "job", "runner", "pump", "events", "stream"):
            assert name not in stored, (record.__name__, name)
    assert not hasattr(book_workspace, "JobController")
    assert not hasattr(result, "controller")


# --------------------------------------------------------------------------- #
# Retry and numbering — a cross-contract protocol proof
#
# The allocator stays where Phase 6 put it: outside, in the consumer's execution
# state. This test owns its own counter, exactly as a consumer would, and proves
# the approved section 18.3 behaviour end to end.
# --------------------------------------------------------------------------- #


def test_a_retry_costs_no_number_and_a_retried_success_takes_the_next_one():
    from shared.numbering import SuccessNumbers

    won, lost, last = book("A"), book("B"), book("C")
    space = workspace(won, lost, last)
    captured = capture(space)
    runs = dict(captured.runs)

    numbers = SuccessNumbers(1)                    # the consumer's, not Plan 6's

    # The original run: A succeeds, B fails, C succeeds.
    first = numbers.propose()
    assert numbers.commit(first) == 1              # A
    offered = numbers.propose()
    assert offered.number == 2                     # B is offered 2 and fails
    third = numbers.propose()
    assert numbers.commit(third) == 2              # C takes it instead

    result = WorkspaceRunResult(snapshot=captured, results=(
        (won.book_id, succeeded(runs[won.book_id])),
        (lost.book_id, failed_retryable(runs[lost.book_id])),
        (last.book_id, succeeded(runs[last.book_id])),
    ), state=JobState.COMPLETED_WITH_FAILURES)

    assert numbers.consumed == 2 and numbers.next_number == 3

    # Building Retry Failed consumes nothing at all.
    requests = retry_failed_books(result)
    assert requests and result.retryable_book_ids == (lost.book_id,)
    assert numbers.consumed == 2, "describing a retry is not doing one"
    assert numbers.next_number == 3

    # If that retry is then executed and genuinely succeeds, it takes the next
    # number in sequence: 1, 2, 3 — no gap, and no duplicate.
    retried = numbers.propose()
    assert retried.number == 3
    assert numbers.commit(retried) == 3
    assert numbers.consumed == 3


def test_retry_production_code_does_not_reach_the_allocator():
    """The counter is execution state. Plan 6 describes retries; it allocates none."""
    import ast

    tree = ast.parse(Path(book_workspace.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported |= {alias.name for alias in node.names}
    assert "shared.numbering" not in imported
    assert "numbering" not in imported
    assert "SuccessNumbers" not in imported


def test_no_allocator_state_is_stored_in_any_frozen_value():
    for record in (BookRunSnapshot, WorkspaceRunResult):
        stored = {entry.name for entry in dataclasses.fields(record)}
        for counter in ("numbers", "counter", "allocator", "consumed",
                        "next_number", "start_number", "series"):
            assert counter not in stored, (record.__name__, counter)
