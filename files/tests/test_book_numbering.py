"""Success-only numbering for books — v0.6.3 Drop 1 (Plan 6), Phase 6.

Decisions 21A, 28A and 48A, proved as the **consumer protocol** against the Phase 5
frozen run and the promoted ``shared.numbering.SuccessNumbers``.

This module deliberately does **not** re-test the allocator's own 51 contracts —
``test_m4b_numbering.py`` owns those and still owns them. What is proved here is the
part Plan 6 is responsible for: that a multi-book consumer, driving that one
allocator, gets a gap-free sequence in which only genuine successes consume a
number, and that the counter never leaks into a frozen snapshot.

There is no second numbering state machine. A wrapper that merely delegated
``propose``/``commit`` would be exactly that, so none exists: the tests below call
the shared allocator directly, which is what a consumer will do.

**The start is a test-consumer option.** ``shared/book_workspace.py`` deliberately
hard-codes no universal ``start_number`` key — the consumer owns its own tool-option
vocabulary, exactly as it owns its Shared Metadata field names — so these tests use
their own field name to demonstrate the contract.
"""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path, PurePath

import pytest

from shared import book_workspace
from shared.book_workspace import (
    BookJob,
    BookRunSnapshot,
    SharedMetadata,
    WorkspaceSnapshot,
    capture_workspace_run,
    new_book_id,
    replace_book,
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
from shared.numbering import NumberingError, SuccessNumbers, Tentative

from test_importing import make_config


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

ROOT = Path(os.path.abspath(os.sep + "act-fixture-root"))
CATALOG = SupportedTypeCatalog((SupportedType("mp3", "MP3 audio", (".mp3",)),))
ROOTED = ImportRoot("root-1", ROOT, 0)

#: This suite's own consumer option name. Plan 6 production defines no universal
#: one, and inventing a key in the shared layer would be inventing a schema.
START = "series_start"

_IDS = IdFactory("n-")


def files(label: str, count: int = 1) -> ImportedFileSnapshot:
    return ImportedFileSnapshot(Revision(1), tuple(
        ImportedFile(f"{label}-occ-{index}", ROOT / label / f"{index}.mp3", ROOTED,
                     PurePath(label) / f"{index}.mp3", "mp3", f"{label}-id-{index}")
        for index in range(1, count + 1)))


def book(label: str, count: int = 1, **configuration) -> BookJob:
    return BookJob(book_id=new_book_id(_IDS), configuration=configuration,
                   files=files(label, count) if count else ImportedFileSnapshot())


def workspace(*books: BookJob, shared: SharedMetadata | None = None
              ) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(
        books=books, current_book_id=books[0].book_id,
        shared=shared if shared is not None else SharedMetadata.for_fields(("title",)))


def capture(space: WorkspaceSnapshot, *, is_valid=None) -> BookRunSnapshot:
    return capture_workspace_run(
        space, catalog=CATALOG, import_options=ImportOptions.for_catalog(CATALOG),
        effective_config=make_config(), id_factory=IdFactory("r-"),
        created_at=100.0, is_valid=is_valid)


def allocator_for(captured: BookRunSnapshot, book_id: str) -> SuccessNumbers:
    """Build this attempt's allocator from the value frozen into the run.

    Decision 48A: the start comes from the run, never from the live workspace.
    """
    snapshot = captured.snapshot_for(book_id)
    return SuccessNumbers(snapshot.tool_options[START])


def run_books(numbers: SuccessNumbers, outcomes) -> tuple[int, ...]:
    """Drive the consumer protocol over a sequence of simulated outcomes.

    ``propose`` before the work, ``commit`` if and only if the work genuinely
    succeeded. Nothing else touches the counter. Returns the numbers that were
    actually earned.
    """
    earned: list[int] = []
    for succeeded in outcomes:
        tentative = numbers.propose()          # before the work
        if succeeded:                          # only a real success commits
            earned.append(numbers.commit(tentative))
    return tuple(earned)


# --------------------------------------------------------------------------- #
# One allocator, promoted (Plan 6 section 17.1)
# --------------------------------------------------------------------------- #


def test_the_allocator_now_lives_in_shared_and_the_old_path_is_the_same_object():
    """One implementation, two import paths — not a fork."""
    from mp3_tools import m4b_numbering
    from shared import numbering

    assert m4b_numbering.SuccessNumbers is numbering.SuccessNumbers is SuccessNumbers
    assert m4b_numbering.Tentative is numbering.Tentative is Tentative
    assert m4b_numbering.NumberingError is numbering.NumberingError is NumberingError


def test_the_legacy_module_declares_no_allocator_of_its_own():
    import ast
    from mp3_tools import m4b_numbering

    tree = ast.parse(Path(m4b_numbering.__file__).read_text(encoding="utf-8"))
    declared = {node.name for node in ast.walk(tree)
                if isinstance(node, (ast.ClassDef, ast.FunctionDef))}
    assert declared == set(), declared


def test_plan6_defines_no_second_numbering_state_machine():
    """A wrapper that delegated propose/commit would be a second counter."""
    for invented in ("SuccessNumbers", "BookNumbers", "SeriesNumbers", "Tentative",
                     "propose", "commit_number", "next_number"):
        assert not hasattr(book_workspace, invented), invented


# --------------------------------------------------------------------------- #
# Decision 48A — a configurable start, frozen into the run
# --------------------------------------------------------------------------- #


def test_the_start_comes_from_the_frozen_run_not_the_live_workspace():
    entry = book("A", **{START: 7})
    captured = capture(workspace(entry))
    assert captured.snapshot_for(entry.book_id).tool_options[START] == 7
    assert allocator_for(captured, entry.book_id).start == 7


def test_editing_the_live_start_after_capture_cannot_move_the_attempt():
    """Decision 48A with Decision 9A: the attempt began from the captured value."""
    entry = book("A", **{START: 7})
    space = workspace(entry)
    captured = capture(space)

    # The user changes their mind after pressing the button.
    live = replace_book(space, BookJob(book_id=entry.book_id,
                                       configuration={START: 999},
                                       files=entry.files)).workspace
    assert live.book_for(entry.book_id).configuration[START] == 999

    numbers = allocator_for(captured, entry.book_id)
    assert numbers.start == 7, "the run began where it was frozen"
    assert numbers.propose().number == 7


def test_a_shared_metadata_change_after_capture_cannot_move_the_start_either():
    entry = book("A", **{START: 3})
    space = workspace(entry)
    captured = capture(space)
    set_shared_metadata(space, SharedMetadata(("title",), {"title": "Changed"}))
    assert allocator_for(captured, entry.book_id).start == 3


@pytest.mark.parametrize("start", [1, 2, 7, 42, 100])
def test_any_configured_start_is_honoured(start):
    entry = book("A", **{START: start})
    captured = capture(workspace(entry))
    numbers = allocator_for(captured, entry.book_id)
    assert numbers.start == start
    assert numbers.next_number == start
    assert numbers.propose().number == start


def test_one_allocator_belongs_to_one_execution_attempt():
    """Two attempts over one frozen run each begin from the same frozen start."""
    entry = book("A", **{START: 5})
    captured = capture(workspace(entry))

    first = allocator_for(captured, entry.book_id)
    first.commit(first.propose())
    assert first.consumed == 1 and first.next_number == 6

    second = allocator_for(captured, entry.book_id)
    assert second.consumed == 0, "a fresh attempt, not a continuation"
    assert second.next_number == 5


# --------------------------------------------------------------------------- #
# Decision 21A — only a success consumes
# --------------------------------------------------------------------------- #


def test_proposing_before_the_work_consumes_nothing():
    """The number must exist before the output does, without being spent."""
    numbers = SuccessNumbers(1)
    assert numbers.propose().number == 1
    assert numbers.propose().number == 1
    assert numbers.consumed == 0
    assert numbers.next_number == 1


def test_only_a_genuine_success_commits():
    entry_a, entry_b = book("A", **{START: 1}), book("B")
    captured = capture(workspace(entry_a, entry_b))
    numbers = allocator_for(captured, entry_a.book_id)

    assert run_books(numbers, [True, False]) == (1,)
    assert numbers.consumed == 1


def test_a_failed_book_consumes_nothing():
    numbers = SuccessNumbers(1)
    tentative = numbers.propose()
    # the work failed: no commit
    assert numbers.consumed == 0
    assert numbers.next_number == 1
    assert tentative == Tentative(1)


def test_an_abandoned_proposal_costs_nothing():
    """Forgetting to commit is free; that is why asking is a separate call."""
    numbers = SuccessNumbers(4)
    for _ in range(5):
        numbers.propose()
    assert numbers.consumed == 0
    assert numbers.next_number == 4


def test_the_allocator_does_not_decide_whether_the_work_succeeded():
    """Success is the consumer's judgement; the counter only records it."""
    import inspect
    source = inspect.getsource(SuccessNumbers)
    for outcome_word in ("succeeded", "failed", "outcome", "status", "result"):
        assert f"def {outcome_word}" not in source, outcome_word
    methods = {name for name, _ in inspect.getmembers(SuccessNumbers, inspect.isfunction)}
    assert methods <= {"__init__", "__repr__", "propose", "commit"}, methods


def test_committing_a_spent_token_is_an_error_not_a_silent_skip():
    numbers = SuccessNumbers(1)
    tentative = numbers.propose()
    numbers.commit(tentative)
    with pytest.raises(NumberingError):
        numbers.commit(tentative)
    assert numbers.consumed == 1, "the failed second commit changed nothing"


# --------------------------------------------------------------------------- #
# Decision 28A — no gaps
# --------------------------------------------------------------------------- #


def test_the_canonical_middle_failure_leaves_no_gap():
    """Three books, the second fails: the third is 2, not 3."""
    numbers = SuccessNumbers(1)

    first = numbers.propose()
    assert first.number == 1
    assert numbers.commit(first) == 1                      # A succeeds

    second = numbers.propose()
    assert second.number == 2                              # B is offered 2
    # B fails: nothing is committed.

    third = numbers.propose()
    assert third.number == 2, "C receives the number B did not earn"
    assert numbers.commit(third) == 2                      # C succeeds

    assert numbers.consumed == 2
    assert numbers.next_number == 3


def test_the_canonical_sequence_through_the_consumer_protocol():
    numbers = SuccessNumbers(1)
    assert run_books(numbers, [True, False, True]) == (1, 2)
    assert numbers.consumed == 2
    assert numbers.next_number == 3


def test_the_same_sequence_at_a_configurable_start():
    numbers = SuccessNumbers(7)
    assert run_books(numbers, [True, False, True]) == (7, 8), "not (7, 9)"
    assert numbers.consumed == 2
    assert numbers.next_number == 9


@pytest.mark.parametrize("start", [1, 7, 50])
def test_many_failures_still_produce_a_contiguous_sequence(start):
    numbers = SuccessNumbers(start)
    outcomes = [True, False, False, True, False, True, False]
    earned = run_books(numbers, outcomes)
    assert earned == tuple(range(start, start + 3))
    assert list(earned) == sorted(earned)
    assert numbers.consumed == 3


def test_every_book_failing_consumes_nothing_at_all():
    numbers = SuccessNumbers(1)
    assert run_books(numbers, [False, False, False]) == ()
    assert numbers.consumed == 0
    assert numbers.next_number == 1


def test_a_failure_does_not_abort_the_books_after_it():
    """Decision 28A: report the failure, carry on, and keep the sequence dense."""
    numbers = SuccessNumbers(1)
    earned = run_books(numbers, [False, True, True])
    assert earned == (1, 2), "the first failure cost the run nothing"


# --------------------------------------------------------------------------- #
# Skipped books consume nothing either
# --------------------------------------------------------------------------- #


def test_an_empty_book_never_reaches_the_allocator():
    """It is not attempted, so there is nothing to propose for."""
    attempted, empty = book("A", **{START: 1}), book("E", count=0)
    captured = capture(workspace(attempted, empty))

    assert captured.attempted_book_ids == (attempted.book_id,)
    assert captured.skipped_book_ids == (empty.book_id,)

    numbers = allocator_for(captured, attempted.book_id)
    assert run_books(numbers, [True]) == (1,)
    assert numbers.consumed == 1, "the skipped book cost nothing"


def test_a_consumer_invalid_book_never_reaches_the_allocator():
    first, invalid = book("A", **{START: 1}), book("B")
    captured = capture(workspace(first, invalid),
                       is_valid=lambda entry: entry.book_id != invalid.book_id)

    assert captured.skipped_book_ids == (invalid.book_id,)
    numbers = allocator_for(captured, first.book_id)
    assert run_books(numbers, [True]) == (1,)
    assert numbers.next_number == 2


def test_a_book_not_attempted_before_its_work_began_consumes_nothing():
    """A run stopped part-way spends nothing on the books it never reached."""
    numbers = SuccessNumbers(1)
    numbers.commit(numbers.propose())      # A ran and succeeded
    # The run was cancelled here: B and C were never attempted at all.
    assert numbers.consumed == 1
    assert numbers.next_number == 2


def test_reading_the_next_number_repeatedly_consumes_nothing():
    numbers = SuccessNumbers(9)
    for _ in range(10):
        assert numbers.next_number == 9
    assert numbers.consumed == 0


def test_the_whole_mixed_run_produces_a_dense_sequence():
    """Attempted successes, an attempted failure, an empty book and an invalid one."""
    first = book("A", **{START: 1})
    failing = book("B")
    empty = book("E", count=0)
    invalid = book("C")
    last = book("D")

    captured = capture(workspace(first, failing, empty, invalid, last),
                       is_valid=lambda entry: entry.book_id != invalid.book_id)
    assert captured.attempted_book_ids == (first.book_id, failing.book_id,
                                           last.book_id)
    assert captured.skipped_book_ids == (empty.book_id, invalid.book_id)

    numbers = allocator_for(captured, first.book_id)
    assert run_books(numbers, [True, False, True]) == (1, 2)
    assert numbers.consumed == 2


# --------------------------------------------------------------------------- #
# The counter is execution state, never frozen state
# --------------------------------------------------------------------------- #


def test_no_frozen_plan6_record_stores_a_counter():
    """A snapshot is what a retry re-reads; a counter is a fact about one attempt."""
    from shared.book_workspace import BookMutation
    from shared.job_control import RunSnapshot

    for record in (BookJob, WorkspaceSnapshot, BookRunSnapshot, BookMutation,
                   SharedMetadata, RunSnapshot):
        names = {entry.name for entry in dataclasses.fields(record)}
        for counter_word in ("numbers", "counter", "allocator", "consumed",
                             "next_number", "sequence"):
            assert counter_word not in names, (record.__name__, counter_word)


def test_capture_does_not_construct_an_allocator():
    """Phase 5 captures; allocating is the execution layer's, later."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(capture_workspace_run))
    called = {node.func.id for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert "SuccessNumbers" not in called
    assert "SuccessNumbers" not in dir(book_workspace)


def test_only_the_frozen_start_travels_in_tool_options():
    """The opaque consumer value, and nothing the allocator produced."""
    entry = book("A", **{START: 4})
    captured = capture(workspace(entry))
    options = captured.snapshot_for(entry.book_id).tool_options
    assert options[START] == 4
    for produced in ("consumed", "next_number", "tentative", "numbers"):
        assert produced not in options, produced


def test_the_allocator_knows_nothing_about_books():
    """It is handed an integer. It has never heard of a BookJob."""
    import inspect
    source = inspect.getsource(SuccessNumbers)
    for concept in ("BookJob", "book_id", "WorkspaceSnapshot", "BookRunSnapshot",
                    "RunSnapshot", "metadata", "retry", "Path"):
        assert concept not in source, concept
