"""Frozen effective values — v0.6.3 Drop 1 (Plan 6), Phase 5.

Capture freezes a whole workspace into one :class:`BookRunSnapshot`: **one existing
Plan 3 ``RunSnapshot`` per eligible book**, composed and never replaced. There is no
second snapshot type, no second freeze, no second id scheme and no controller —
which is what lets Phase 7's retry be literally ``RunResult.retry()`` on a book's own
snapshot.

The contract this module exists to protect is section 16's **total freeze**: after
capture, a later edit to the live workspace — a metadata field, a shared field, an
added file, a removed book, a whole re-import — cannot reach the captured run,
because the run never consults the workspace again. That is asserted by mutating
every layer afterwards and by **object identity**, not merely equality.

Phase 5 captures. It runs nothing: no worker, no controller, no output.
"""

from __future__ import annotations

import dataclasses
import os
from dataclasses import FrozenInstanceError
from pathlib import Path, PurePath

import pytest

from shared import book_workspace
from shared.book_workspace import (
    RUN_ID_KIND,
    BookContractError,
    BookDisposition,
    BookIdentityError,
    BookJob,
    BookRunSnapshot,
    NO_SHARED_METADATA,
    SharedMetadata,
    SharedMetadataError,
    WorkspaceContractError,
    WorkspaceSnapshot,
    add_book,
    capture_workspace_run,
    effective_run_options,
    new_book_id,
    remove_book,
    replace_book,
    replace_workspace_from_import,
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
from shared.job_control import RunSnapshot, is_frozen_options

from test_book_grouping import scanned
from test_importing import make_config


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

ROOT = Path(os.path.abspath(os.sep + "act-fixture-root"))
CATALOG = SupportedTypeCatalog((SupportedType("mp3", "MP3 audio", (".mp3",)),))
ROOTED = ImportRoot("root-1", ROOT, 0)
FIELDS = ("title", "author")

_IDS = IdFactory("t-")

#: The two skip reasons a capture may record. Named here so the shape tests below
#: read as being about the collection rather than about the enum.
EMPTY = BookDisposition.SKIPPED_EMPTY
INVALID = BookDisposition.SKIPPED_INVALID


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


def workspace(*books: BookJob, shared: SharedMetadata | None = None,
              revision: Revision | None = None) -> WorkspaceSnapshot:
    entries = books or (book(),)
    return WorkspaceSnapshot(
        books=entries, current_book_id=entries[0].book_id,
        revision=revision if revision is not None else Revision(0),
        shared=SharedMetadata.for_fields(FIELDS) if shared is None else shared)


def capture(space: WorkspaceSnapshot, *, maker: IdFactory | None = None,
            created_at: float = 100.0, is_valid=None) -> BookRunSnapshot:
    return capture_workspace_run(
        space,
        catalog=CATALOG,
        import_options=ImportOptions.for_catalog(CATALOG),
        effective_config=make_config(),
        id_factory=maker or IdFactory("r-"),
        created_at=created_at,
        is_valid=is_valid,
    )


class CaptureSpy:
    """Records every ``capture_run`` call and the exact object it returned."""

    def __init__(self, real):
        self.real = real
        self.calls: list[dict] = []
        self.returned: list[RunSnapshot] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        produced = self.real(**kwargs)
        self.returned.append(produced)
        return produced


@pytest.fixture
def spy(monkeypatch):
    watcher = CaptureSpy(book_workspace.capture_run)
    monkeypatch.setattr(book_workspace, "capture_run", watcher)
    return watcher


# --------------------------------------------------------------------------- #
# The composition value
# --------------------------------------------------------------------------- #


def test_a_book_run_snapshot_is_a_frozen_slotted_record():
    assert BookRunSnapshot.__dataclass_params__.frozen is True
    assert "__slots__" in BookRunSnapshot.__dict__
    value = capture(workspace(book()))
    with pytest.raises(FrozenInstanceError):
        value.runs = ()
    assert not hasattr(value, "__dict__")


def test_it_holds_ordered_book_id_and_run_snapshot_pairs():
    first, second = book("A"), book("B")
    value = capture(workspace(first, second))
    assert value.attempted_book_ids == (first.book_id, second.book_id)
    for book_id, snapshot in value.runs:
        assert isinstance(book_id, str)
        assert isinstance(snapshot, RunSnapshot)


def test_the_projections_report_what_was_captured():
    value = capture(workspace(book("A"), book("B"), empty_book()))
    assert value.count == 2
    assert value.skipped_count == 1
    assert value.snapshot_for(value.attempted_book_ids[0]) is value.runs[0][1]
    assert value.snapshot_for("t-book-999999") is None


def test_snapshot_for_refuses_a_malformed_identity():
    value = capture(workspace(book()))
    for bad in ("", "   ", "book 1", None, 5):
        with pytest.raises(BookIdentityError):
            value.snapshot_for(bad)


def test_an_empty_composition_is_a_valid_value():
    value = BookRunSnapshot()
    assert value.runs == ()
    assert value.attempted_book_ids == ()
    assert value.skipped_book_ids == ()
    assert value.count == 0
    assert value.shared is NO_SHARED_METADATA


def test_duplicate_attempted_book_ids_are_refused():
    snapshot = capture(workspace(book())).runs[0][1]
    with pytest.raises(BookIdentityError):
        BookRunSnapshot(runs=(("b-1", snapshot), ("b-1", snapshot)))


def test_duplicate_skipped_book_ids_are_refused():
    with pytest.raises(BookIdentityError):
        BookRunSnapshot(skipped=((("b-1", EMPTY)), ("b-1", EMPTY)))


def test_a_book_cannot_be_both_attempted_and_skipped():
    """Two answers to 'what did this run do with book X' is one too many."""
    snapshot = capture(workspace(book())).runs[0][1]
    with pytest.raises(BookIdentityError):
        BookRunSnapshot(runs=(("b-1", snapshot),), skipped=(("b-1", EMPTY),))


@pytest.mark.parametrize("bad", ["runs", b"runs", 7, None])
def test_runs_must_be_an_iterable_of_pairs(bad):
    with pytest.raises(WorkspaceContractError):
        BookRunSnapshot(runs=bad)


def test_a_run_entry_must_be_a_pair():
    snapshot = capture(workspace(book())).runs[0][1]
    for bad in [("b-1",), ("b-1", snapshot, "extra"), "b-1"]:
        with pytest.raises(WorkspaceContractError):
            BookRunSnapshot(runs=(bad,))


def test_each_run_must_carry_a_real_plan3_run_snapshot():
    """No stand-in, no duck type: the Plan 3 value or nothing."""
    class Lookalike:
        snapshot_id = "x"
        item_ids = ()

    for wrong in (Lookalike(), None, "snapshot", {"snapshot_id": "x"}):
        with pytest.raises(WorkspaceContractError):
            BookRunSnapshot(runs=(("b-1", wrong),))


@pytest.mark.parametrize("bad", ["", "   ", "book 1", "books/1", None, 5])
def test_a_malformed_book_id_is_refused_in_either_collection(bad):
    snapshot = capture(workspace(book())).runs[0][1]
    with pytest.raises(BookIdentityError):
        BookRunSnapshot(runs=((bad, snapshot),))
    with pytest.raises(BookIdentityError):
        BookRunSnapshot(skipped=((bad, EMPTY),))


def test_the_captured_shared_metadata_must_be_the_phase_four_value():
    for wrong in (None, "shared", 3, {"title": "T"}):
        with pytest.raises(WorkspaceContractError):
            BookRunSnapshot(shared=wrong)


def test_the_composition_carries_no_later_phase_state():
    """No counter, no failure, no result, no controller, no output.

    **Phase 7 transition.** The stored field is now ``skipped`` — the skipped books
    *with the reason frozen beside each one* — because telling SKIPPED_EMPTY from
    SKIPPED_INVALID afterwards would mean reading a workspace that may have changed,
    which section 16 forbids. That is the one disposition a capture may hold, because
    a skip is decided at capture rather than by running. Everything that describes
    what *happened* still lives in the result layer, not here.
    """
    stored = {entry.name for entry in dataclasses.fields(BookRunSnapshot)}
    assert stored == {"runs", "skipped", "shared"}
    for later in ("numbers", "next_number", "start_number", "dispositions",
                  "outcomes", "failures", "result", "retry", "controller",
                  "destination", "outputs"):
        assert later not in stored, later

    # ``skipped_book_ids`` survives as a DERIVED projection, so the Phase 5 spelling
    # keeps working while there is only one stored truth about the skipped books.
    assert "skipped_book_ids" not in stored
    assert isinstance(BookRunSnapshot.__dict__["skipped_book_ids"], property)


# --------------------------------------------------------------------------- #
# One capture_run per eligible book
# --------------------------------------------------------------------------- #


def test_capture_delegates_to_the_existing_plan3_capture_run(spy):
    capture(workspace(book("A")))
    assert len(spy.calls) == 1, "it went through job_control.capture_run"


@pytest.mark.parametrize("count", [1, 2, 5])
def test_exactly_one_capture_run_call_per_eligible_book(spy, count):
    books = tuple(book(f"B{index}") for index in range(count))
    value = capture(workspace(*books))
    assert len(spy.calls) == count
    assert value.count == count


def test_an_empty_book_produces_no_capture_run_call(spy):
    value = capture(workspace(book("A"), empty_book(), book("B")))
    assert len(spy.calls) == 2
    assert value.count == 2
    assert value.skipped_count == 1


def test_an_invalid_book_produces_no_capture_run_call(spy):
    first, second = book("A"), book("B")
    value = capture(workspace(first, second),
                    is_valid=lambda entry: entry.book_id != second.book_id)
    assert len(spy.calls) == 1
    assert value.attempted_book_ids == (first.book_id,)
    assert value.skipped_book_ids == (second.book_id,)


def test_every_call_receives_that_books_own_inputs(spy):
    first, second = book("A", 2), book("B", 3)
    config = make_config()
    options = ImportOptions.for_catalog(CATALOG)
    capture_workspace_run(workspace(first, second), catalog=CATALOG,
                          import_options=options, effective_config=config,
                          id_factory=IdFactory("r-"), created_at=42.0)

    assert len(spy.calls) == 2
    for call, source in zip(spy.calls, (first, second)):
        assert call["files"] is source.files, "the book's own snapshot, not a copy"
        assert call["catalog"] is CATALOG
        assert call["import_options"] is options
        assert call["effective_config"] is config
        assert call["created_at"] == 42.0


def test_each_attempted_book_gets_its_own_unique_snapshot_id():
    value = capture(workspace(book("A"), book("B"), book("C")))
    ids = [snapshot.snapshot_id for _book_id, snapshot in value.runs]
    assert len(set(ids)) == 3
    assert all(RUN_ID_KIND in identity for identity in ids)


def test_snapshot_ids_come_from_the_existing_id_factory():
    """No second counter and no UUID: the Plan 3 factory, under its own kind."""
    value = capture(workspace(book("A"), book("B")), maker=IdFactory("run7-"))
    assert [snapshot.snapshot_id for _b, snapshot in value.runs] == [
        f"run7-{RUN_ID_KIND}-000001", f"run7-{RUN_ID_KIND}-000002"]
    assert RUN_ID_KIND == "run"


def test_the_snapshot_id_does_not_encode_the_book_identity():
    """The pair carries the mapping; a decoded id would be a second one."""
    entry = book("A")
    value = capture(workspace(entry))
    assert entry.book_id not in value.runs[0][1].snapshot_id


def test_the_run_kind_cannot_be_confused_with_a_book_kind():
    from shared.book_workspace import BOOK_ID_KIND
    assert RUN_ID_KIND != BOOK_ID_KIND


def test_capture_order_follows_workspace_book_order():
    first, second, third = book("A"), book("B"), book("C")
    value = capture(workspace(first, second, third))
    assert value.attempted_book_ids == (first.book_id, second.book_id, third.book_id)


def test_item_ids_are_that_books_own_occurrence_ids():
    first, second = book("A", 2), book("B", 3)
    value = capture(workspace(first, second))
    assert value.runs[0][1].item_ids == ("A-occ-1", "A-occ-2")
    assert value.runs[1][1].item_ids == ("B-occ-1", "B-occ-2", "B-occ-3")


def test_the_files_snapshot_is_carried_by_identity_not_rebuilt():
    entry = book("A", 3)
    value = capture(workspace(entry))
    assert value.runs[0][1].files is entry.files


# --------------------------------------------------------------------------- #
# Effective tool options
# --------------------------------------------------------------------------- #


def test_non_metadata_configuration_survives_into_the_run():
    entry = book("A", title="A Title", bitrate=192, split=True)
    value = capture(workspace(entry))
    options = value.runs[0][1].tool_options
    assert options["bitrate"] == 192
    assert options["split"] is True


def test_a_populated_shared_field_is_captured_as_the_shared_value():
    entry = book("A", title="Per Book", author="Per Author")
    space = workspace(entry, shared=SharedMetadata(FIELDS, {"author": "Shared Author"}))
    options = capture(space).runs[0][1].tool_options
    assert options["author"] == "Shared Author"
    assert options["title"] == "Per Book", "the blank shared field left this alone"


def test_a_blank_shared_field_is_captured_as_the_per_book_value():
    entry = book("A", title="Per Book")
    space = workspace(entry, shared=SharedMetadata(FIELDS, {"title": "   "}))
    assert capture(space).runs[0][1].tool_options["title"] == "Per Book"


def test_separate_books_resolve_independently():
    first = book("A", title="A Title", author="A Author")
    second = book("B", title="B Title", author="B Author")
    space = workspace(first, second,
                      shared=SharedMetadata(FIELDS, {"author": "Shared Author"}))
    value = capture(space)
    assert value.runs[0][1].tool_options["title"] == "A Title"
    assert value.runs[1][1].tool_options["title"] == "B Title"
    for _book_id, snapshot in value.runs:
        assert snapshot.tool_options["author"] == "Shared Author"


def test_a_declared_field_with_no_value_anywhere_is_captured_blank():
    space = workspace(book("A"), shared=SharedMetadata.for_fields(FIELDS))
    options = capture(space).runs[0][1].tool_options
    assert options["title"] == "" and options["author"] == ""


def test_the_run_options_helper_and_the_capture_agree():
    """One merge rule, not two."""
    entry = book("A", title="Per Book", bitrate=128)
    space = workspace(entry, shared=SharedMetadata(FIELDS, {"author": "Shared"}))
    expected = effective_run_options(entry, space.shared)
    assert dict(capture(space).runs[0][1].tool_options) == expected


def test_the_raw_sources_are_untouched_by_capture():
    entry = book("A", title="Per Book", author="Per Author")
    before = dict(entry.configuration)
    space = workspace(entry, shared=SharedMetadata(FIELDS, {"author": "Shared Author"}))
    shared_before = dict(space.shared.values)
    capture(space)
    assert dict(entry.configuration) == before
    assert dict(space.shared.values) == shared_before
    assert entry.configuration["author"] == "Per Author"


def test_the_captured_options_are_deep_frozen_by_the_one_freeze():
    entry = book("A", tags=["a", "b"], nested={"deep": [1, 2]})
    options = capture(workspace(entry)).runs[0][1].tool_options
    assert is_frozen_options(options)
    assert options["tags"] == ("a", "b")
    assert options["nested"]["deep"] == (1, 2)
    with pytest.raises(TypeError):
        options["tags"] = ("c",)


def test_a_caller_owned_mutable_payload_cannot_reach_the_run():
    payload = ["a"]
    entry = book("A", tags=payload)
    value = capture(workspace(entry))
    payload.append("b")
    assert value.runs[0][1].tool_options["tags"] == ("a",)


def test_a_live_object_in_configuration_was_already_refused_upstream():
    """Plan 6 neither widens nor weakens what ``freeze_options`` accepts."""
    from shared.book_workspace import BookConfigurationError
    with pytest.raises(BookConfigurationError):
        book("A", handler=lambda: None)


def test_effective_run_options_refuses_the_wrong_arguments():
    with pytest.raises(BookContractError):
        effective_run_options("book", NO_SHARED_METADATA)
    with pytest.raises(SharedMetadataError):
        effective_run_options(book("A"), "shared")


# --------------------------------------------------------------------------- #
# Eligibility and skips
# --------------------------------------------------------------------------- #


def test_an_empty_book_is_recorded_by_id_and_gets_no_snapshot():
    entry = empty_book(title="Configured but empty")
    value = capture(workspace(book("A"), entry))
    assert entry.book_id in value.skipped_book_ids
    assert value.snapshot_for(entry.book_id) is None
    assert entry.book_id not in value.attempted_book_ids


def test_an_empty_book_is_not_treated_as_a_failure():
    """Phase 5 records eligibility; what became of a book is Phase 7's."""
    value = capture(workspace(empty_book()))
    assert value.count == 0
    assert value.skipped_count == 1
    assert not hasattr(value, "failures")
    assert not hasattr(value, "dispositions")


def test_the_validity_predicate_is_optional_and_defaults_to_every_non_empty_book():
    value = capture(workspace(book("A"), book("B")))
    assert value.count == 2 and value.skipped_count == 0


def test_the_validity_predicate_is_asked_once_per_non_empty_book():
    asked: list[str] = []
    entry, other, blank = book("A"), book("B"), empty_book()

    def is_valid(candidate):
        asked.append(candidate.book_id)
        return True

    capture(workspace(entry, other, blank), is_valid=is_valid)
    assert asked == [entry.book_id, other.book_id], "an empty book is never asked"


def test_the_validity_predicate_is_never_stored_or_frozen():
    """It is a capture-time question, not run state a worker could be handed."""
    value = capture(workspace(book("A")), is_valid=lambda entry: True)
    assert "is_valid" not in {f.name for f in dataclasses.fields(BookRunSnapshot)}
    for _book_id, snapshot in value.runs:
        assert "is_valid" not in snapshot.tool_options


def test_mixed_attempted_and_skipped_order_is_deterministic():
    first, blank, second, invalid = book("A"), empty_book(), book("B"), book("C")
    value = capture(workspace(first, blank, second, invalid),
                    is_valid=lambda entry: entry.book_id != invalid.book_id)
    assert value.attempted_book_ids == (first.book_id, second.book_id)
    assert value.skipped_book_ids == (blank.book_id, invalid.book_id)
    assert not set(value.attempted_book_ids) & set(value.skipped_book_ids)


def test_a_workspace_of_only_skipped_books_captures_nothing(spy):
    value = capture(workspace(empty_book(), empty_book()))
    assert spy.calls == []
    assert value.count == 0 and value.skipped_count == 2


# --------------------------------------------------------------------------- #
# Capture is read-only, and atomic in what it owns
# --------------------------------------------------------------------------- #


def test_capture_does_not_mutate_the_workspace():
    space = workspace(book("A"), book("B"), revision=Revision(4))
    before = (space.books, space.current_book_id, space.revision, space.shared)
    capture(space)
    assert (space.books, space.current_book_id, space.revision, space.shared) == before


def test_capture_returns_a_composition_and_not_a_mutation():
    """Capturing is an observation, so it has no WorkspaceOperation."""
    value = capture(workspace(book("A")))
    assert isinstance(value, BookRunSnapshot)
    assert not hasattr(value, "operation")
    assert not hasattr(value, "changed")
    assert not hasattr(value, "workspace")


@pytest.mark.parametrize("kwargs", [
    {"catalog": "catalog"},
    {"import_options": None},
    {"id_factory": "factory"},
    {"is_valid": "not callable"},
])
def test_a_rejected_capture_consumes_no_snapshot_id(kwargs):
    maker = IdFactory("z-")
    base = dict(catalog=CATALOG, import_options=ImportOptions.for_catalog(CATALOG),
                effective_config=make_config(), id_factory=maker, created_at=1.0)
    base.update(kwargs)
    with pytest.raises((WorkspaceContractError, BookIdentityError)):
        capture_workspace_run(workspace(book("A")), **base)
    assert maker.next_id(RUN_ID_KIND) == f"z-{RUN_ID_KIND}-000001"


def test_capture_refuses_something_that_is_not_a_workspace():
    for wrong in (None, "workspace", 3, book("A")):
        with pytest.raises(WorkspaceContractError):
            capture(wrong)


def test_classification_happens_before_any_id_is_minted():
    """An empty book never costs an id, whatever its position."""
    maker = IdFactory("m-")
    capture(workspace(empty_book(), book("A"), empty_book()), maker=maker)
    assert maker.next_id(RUN_ID_KIND) == f"m-{RUN_ID_KIND}-000002", "one book, one id"


# --------------------------------------------------------------------------- #
# The total freeze
# --------------------------------------------------------------------------- #


def loaded():
    first = book("A", title="A Title", author="A Author", bitrate=128)
    second = book("B", title="B Title", author="B Author", bitrate=192)
    blank = empty_book()
    space = workspace(first, second, blank,
                      shared=SharedMetadata(FIELDS, {"author": "Shared Author"}))
    return first, second, blank, space


def test_the_captured_run_survives_every_later_workspace_change():
    """Section 16's total freeze, against every live layer at once."""
    first, second, blank, space = loaded()
    maker = IdFactory("f-")
    captured = capture(space, maker=maker)

    before = {
        "attempted": captured.attempted_book_ids,
        "skipped": captured.skipped_book_ids,
        "ids": tuple(s.snapshot_id for _b, s in captured.runs),
        "files": tuple(s.files for _b, s in captured.runs),
        "items": tuple(s.item_ids for _b, s in captured.runs),
        "options": tuple(dict(s.tool_options) for _b, s in captured.runs),
        "configs": tuple(s.effective_config for _b, s in captured.runs),
        "shared": dict(captured.shared.values),
        "objects": tuple(s for _b, s in captured.runs),
    }

    # Change every live layer there is.
    live = set_shared_metadata(space, SharedMetadata(FIELDS, {"author": "CHANGED",
                                                             "title": "ALSO"})).workspace
    live = replace_book(live, BookJob(book_id=first.book_id,
                                      configuration={"title": "REPLACED"},
                                      files=files("Z", 1))).workspace
    live = add_book(live, id_factory=maker).workspace
    live = remove_book(live, id_factory=maker).workspace
    live = replace_workspace_from_import(
        live, scanned("New/1.mp3"), id_factory=maker).workspace

    assert captured.attempted_book_ids == before["attempted"]
    assert captured.skipped_book_ids == before["skipped"]
    assert tuple(s.snapshot_id for _b, s in captured.runs) == before["ids"]
    assert tuple(s.files for _b, s in captured.runs) == before["files"]
    assert tuple(s.item_ids for _b, s in captured.runs) == before["items"]
    assert tuple(dict(s.tool_options) for _b, s in captured.runs) == before["options"]
    assert tuple(s.effective_config for _b, s in captured.runs) == before["configs"]
    assert dict(captured.shared.values) == before["shared"]
    # The strongest claim: the very same snapshot objects, not equal copies.
    assert tuple(s for _b, s in captured.runs) == before["objects"]
    for stored, original in zip(captured.runs, before["objects"]):
        assert stored[1] is original


def test_the_composition_holds_the_exact_objects_capture_run_returned(spy):
    """Identity, asserted against what the real Plan 3 function handed back."""
    value = capture(workspace(book("A"), book("B")))
    assert len(spy.returned) == 2
    for (_book_id, stored), produced in zip(value.runs, spy.returned):
        assert stored is produced


def test_changing_shared_metadata_after_capture_cannot_reach_the_run():
    first, _second, _blank, space = loaded()
    captured = capture(space)
    resolved = captured.snapshot_for(first.book_id).tool_options["author"]
    assert resolved == "Shared Author"

    set_shared_metadata(space, SharedMetadata(FIELDS, {"author": "CHANGED"}))
    space = set_shared_metadata(space, SharedMetadata(FIELDS, {})).workspace
    assert captured.snapshot_for(first.book_id).tool_options["author"] == "Shared Author"
    assert captured.shared.raw("author") == "Shared Author"


def test_the_run_never_needs_the_live_workspace_again():
    """Everything a worker reads is inside the snapshot it was given."""
    first, _second, _blank, space = loaded()
    captured = capture(space)
    snapshot = captured.snapshot_for(first.book_id)
    assert snapshot.files is first.files
    assert snapshot.item_ids == first.files.occurrence_ids
    assert set(FIELDS) <= set(snapshot.tool_options)
    assert snapshot.effective_config is not None
    assert snapshot.created_at == 100.0


def test_two_captures_of_one_workspace_are_independent():
    _first, _second, _blank, space = loaded()
    one = capture(space, maker=IdFactory("x-"))
    two = capture(space, maker=IdFactory("y-"))
    assert one.attempted_book_ids == two.attempted_book_ids
    for (_a, left), (_b, right) in zip(one.runs, two.runs):
        assert left is not right, "each capture froze its own run"
        assert left.snapshot_id != right.snapshot_id
        assert dict(left.tool_options) == dict(right.tool_options)


# --------------------------------------------------------------------------- #
# The skip reason is frozen at capture — Phase 7 transition
#
# Phase 5 stored only the skipped ids, which was everything capture eligibility
# needed. Phase 7 has to tell SKIPPED_EMPTY from SKIPPED_INVALID, and the only
# moment that distinction exists is the moment eligibility is classified: the
# predicate has been asked, and the answer is about to be thrown away. Section 16
# forbids consulting the live workspace afterwards, so it is captured here.
#
# This is a forward evolution of the Phase 5 composition, not a Phase 5 defect.
# --------------------------------------------------------------------------- #


def test_capture_tells_an_empty_book_from_an_invalid_one():
    blank, invalid, fine = empty_book(), book("B"), book("C")
    value = capture(workspace(blank, invalid, fine),
                    is_valid=lambda entry: entry.book_id != invalid.book_id)

    assert value.skipped == ((blank.book_id, EMPTY), (invalid.book_id, INVALID))
    assert value.skip_reason(blank.book_id) is EMPTY
    assert value.skip_reason(invalid.book_id) is INVALID
    assert value.attempted_book_ids == (fine.book_id,)


def test_an_attempted_book_has_no_skip_reason():
    entry = book("A")
    value = capture(workspace(entry))
    assert value.skip_reason(entry.book_id) is None


def test_an_unknown_book_has_no_skip_reason():
    value = capture(workspace(book("A")))
    assert value.skip_reason("b-nobody") is None


def test_emptiness_is_answered_first_and_needs_no_consumer_opinion():
    """A book with nothing to work on reads as EMPTY even if the predicate agrees.

    "It had no files" is the structural truth and is true whatever the consumer
    thinks; asking the predicate to arbitrate would make the reason depend on which
    tool happened to be running.
    """
    blank = empty_book()
    value = capture(workspace(blank, book("A")), is_valid=lambda entry: False)
    assert value.skip_reason(blank.book_id) is EMPTY


def test_with_no_predicate_no_book_is_ever_invalid():
    value = capture(workspace(empty_book(), empty_book(), book("A")))
    assert {why for _book_id, why in value.skipped} == {EMPTY}


def test_the_skip_collection_is_the_one_stored_truth():
    """``skipped_book_ids`` is derived from it, so the two cannot drift apart."""
    blank, invalid = empty_book(), book("B")
    value = capture(workspace(blank, invalid, book("C")),
                    is_valid=lambda entry: entry.book_id != invalid.book_id)

    stored = {entry.name for entry in dataclasses.fields(BookRunSnapshot)}
    assert "skipped" in stored
    assert "skipped_book_ids" not in stored, "a second stored truth"

    assert value.skipped_book_ids == tuple(
        book_id for book_id, _why in value.skipped)
    assert value.skipped_count == len(value.skipped)


def test_the_frozen_skip_reason_survives_every_later_workspace_edit():
    """Section 16 again: the reason cannot be re-derived, so it must not need to be."""
    blank, invalid, fine = empty_book(), book("B"), book("C")
    space = workspace(blank, invalid, fine)
    value = capture(space, is_valid=lambda entry: entry.book_id != invalid.book_id)
    before = value.skipped

    # Give the empty book files, make the invalid one look ordinary, change the
    # shared metadata, then throw the whole workspace away.
    filled = replace_book(space, BookJob(book_id=blank.book_id, files=files("Z")))
    set_shared_metadata(filled.workspace,
                        SharedMetadata(FIELDS, {"title": "Changed"}))
    add_book(filled.workspace, id_factory=IdFactory("late-"))
    remove_book(filled.workspace, id_factory=IdFactory("late-"))
    replace_workspace_from_import(filled.workspace, scanned("Fresh"),
                                  id_factory=IdFactory("late-"))

    assert value.skipped == before
    assert value.skip_reason(blank.book_id) is EMPTY, "still empty, as captured"
    assert value.skip_reason(invalid.book_id) is INVALID


@pytest.mark.parametrize("why", [
    BookDisposition.SUCCEEDED,
    BookDisposition.FAILED,
    BookDisposition.NOT_ATTEMPTED,
])
def test_only_the_two_skip_reasons_may_be_stored_in_a_capture(why):
    """SUCCEEDED, FAILED and NOT_ATTEMPTED are facts about running.

    A skipped book never ran, so storing one of those here would be a second, older
    answer to a question the result layer derives.
    """
    with pytest.raises(WorkspaceContractError):
        BookRunSnapshot(skipped=(("b-1", why),))


@pytest.mark.parametrize("wrong", ["skipped_empty", None, 0, ("b-1",)])
def test_a_skip_reason_must_be_the_enum_member_not_its_value(wrong):
    with pytest.raises(WorkspaceContractError):
        BookRunSnapshot(skipped=(("b-1", wrong),))


def test_a_skip_entry_must_be_a_pair():
    for bad in [("b-1",), ("b-1", EMPTY, "extra"), "b-1"]:
        with pytest.raises(WorkspaceContractError):
            BookRunSnapshot(skipped=(bad,))


@pytest.mark.parametrize("bad", ["skipped", b"skipped", 7, None])
def test_the_skip_collection_must_be_an_iterable_of_pairs(bad):
    with pytest.raises(WorkspaceContractError):
        BookRunSnapshot(skipped=bad)
