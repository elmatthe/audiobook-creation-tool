"""The book-job vocabulary — v0.6.3 Drop 1 (Plan 6), Phase 1.

Stable book identity, the deep-frozen configuration, one imported-file snapshot per
book, Decision 49A's configuration/input split, and the immutable workspace value
Phase 2 will replace.

Phase 2 added the controller below: Add, Duplicate, Remove, Previous, Next, Select
and Replace as pure functions over that value, plus Decision 50A's meaningful-work
predicate. **Phase 3's folder-to-book grouping is still absent**, and its absence is
proved rather than merely untested — here and structurally in
``test_plan6_boundaries.py``.

Nothing here builds a Tk widget, starts a thread or touches a disk: the whole
surface is platform-neutral by design.
"""

from __future__ import annotations

import dataclasses
import threading
from dataclasses import FrozenInstanceError
from pathlib import PurePath
from types import MappingProxyType

import pytest

from shared import book_workspace
from shared.book_workspace import (
    BOOK_ID_KIND,
    BookConfigurationError,
    BookContractError,
    BookIdentityError,
    BookJob,
    BookMutation,
    EMPTY_CONFIGURATION,
    FIELD_ROLES,
    NO_FILES,
    ROLE_CONFIGURATION,
    ROLE_IDENTITY,
    ROLE_INPUTS,
    WorkspaceContractError,
    WorkspaceOperation,
    WorkspaceSnapshot,
    add_book,
    duplicate_book,
    field_role,
    has_meaningful_work,
    new_book_id,
    next_book,
    previous_book,
    remove_book,
    replace_book,
    select_book,
)
from shared.importing import (
    INITIAL_REVISION,
    IdFactory,
    ImportedFile,
    ImportedFileSnapshot,
    Revision,
)
from shared.job_control import is_frozen_options

from test_importing import folder_root


# --------------------------------------------------------------------------- #
# Helpers — the same builders the Plan 3 suites already use
# --------------------------------------------------------------------------- #


def files(count: int = 2) -> ImportedFileSnapshot:
    """A committed imported list, shaped exactly like ``test_job_control.files``."""
    root = folder_root()
    return ImportedFileSnapshot(
        INITIAL_REVISION.advance(),
        tuple(
            ImportedFile(f"occ-{index}", root.path / f"{index}.mp3", root,
                         PurePath(f"{index}.mp3"), "mp3", f"id-{index}")
            for index in range(1, count + 1)
        ),
    )


def factory() -> IdFactory:
    return IdFactory("t-")


#: One shared factory for helper-built books, so two ``book()`` calls can never
#: collide. A fresh factory per call would restart at ``t-book-000001`` and hand
#: back the same identity twice, which is the opposite of what these tests check.
_IDS = IdFactory("t-")


def book(id_factory: IdFactory | None = None, **kwargs) -> BookJob:
    maker = id_factory or _IDS
    return BookJob(book_id=new_book_id(maker), **kwargs)


# --------------------------------------------------------------------------- #
# Identity
# --------------------------------------------------------------------------- #


def test_a_book_id_is_minted_by_the_existing_plan3_factory():
    """No second identifier scheme: the id comes from ``importing.IdFactory``."""
    maker = IdFactory("run7-")
    assert new_book_id(maker) == f"run7-{BOOK_ID_KIND}-000001"
    assert new_book_id(maker) == f"run7-{BOOK_ID_KIND}-000002"


def test_book_ids_are_monotonic_and_never_repeat_within_one_factory():
    maker = factory()
    minted = [new_book_id(maker) for _ in range(50)]
    assert len(set(minted)) == 50
    assert minted == sorted(minted), "monotonic, so ordering by id is stable"


def test_two_factories_are_independent_so_a_test_can_predict_every_id():
    assert new_book_id(IdFactory("a-")) == "a-book-000001"
    assert new_book_id(IdFactory("b-")) == "b-book-000001"


def test_the_kind_is_one_word_so_a_book_id_cannot_read_as_an_occurrence_id():
    assert BOOK_ID_KIND == "book"
    assert "occ" not in new_book_id(factory())


def test_minting_refuses_anything_that_is_not_the_shared_factory():
    """A second generator cannot sneak in through the door marked ``IdFactory``."""
    class Lookalike:
        def next_id(self, kind):  # pragma: no cover - must never be called
            return "book-000001"

    for wrong in (Lookalike(), None, "book-1", 7):
        with pytest.raises(BookIdentityError):
            new_book_id(wrong)


def test_a_book_id_is_opaque_and_is_neither_an_index_nor_a_path():
    identity = new_book_id(factory())
    assert not identity.isdigit(), "an index would be a display position"
    for separator in ("/", "\\"):
        assert separator not in identity
    assert not any(character.isspace() for character in identity)


@pytest.mark.parametrize("bad", ["", "   ", "book 1", "books/1", "books\\1", None, 3, b"x"])
def test_a_malformed_book_id_cannot_be_constructed(bad):
    with pytest.raises(BookIdentityError):
        BookJob(book_id=bad)


def test_the_identity_survives_being_carried_between_workspace_values():
    """Identity is stable across the value replacement Phase 2 will do."""
    first, second = book(), book()
    one = WorkspaceSnapshot(books=(first, second), current_book_id=first.book_id)
    # Phase 2 replaces the value; the ids inside are the same objects' ids.
    two = WorkspaceSnapshot(books=(second, first), current_book_id=first.book_id)
    assert one.book_for(first.book_id) is first
    assert two.book_for(first.book_id) is first
    assert one.book_ids != two.book_ids, "order moved"
    assert set(one.book_ids) == set(two.book_ids), "identity did not"


# --------------------------------------------------------------------------- #
# The book job itself
# --------------------------------------------------------------------------- #


def test_a_book_job_is_a_frozen_slotted_record():
    assert BookJob.__dataclass_params__.frozen is True
    assert "__slots__" in BookJob.__dict__, "slots, like every record in this foundation"
    entry = book()
    with pytest.raises(FrozenInstanceError):
        entry.book_id = "other"
    with pytest.raises(FrozenInstanceError):
        entry.configuration = {}
    # Slots means there is no instance ``__dict__`` for a stray attribute to land
    # in. Assigning an unknown name on a frozen+slots dataclass raises TypeError
    # from the generated ``__setattr__`` — identical to Plan 3's own ``Revision``,
    # so this asserts the property rather than a particular exception type.
    assert not hasattr(entry, "__dict__")
    with pytest.raises((AttributeError, TypeError)):
        entry.extra = "no dict to grow"


def test_a_pristine_book_owns_the_empty_snapshot_at_the_initial_revision():
    entry = book()
    assert entry.files == NO_FILES
    assert entry.files.revision == INITIAL_REVISION
    assert entry.files.is_empty is True
    assert entry.is_empty is True
    assert entry.file_count == 0


def test_a_book_owns_exactly_one_imported_file_snapshot():
    entry = book(files=files(3))
    assert isinstance(entry.files, ImportedFileSnapshot)
    assert entry.file_count == 3
    assert entry.is_empty is False
    assert entry.files.occurrence_ids == ("occ-1", "occ-2", "occ-3")


def test_emptiness_is_derived_from_the_inputs_and_never_stored_separately():
    """A stored copy could disagree with the list; a property cannot."""
    names = {entry.name for entry in dataclasses.fields(BookJob)}
    assert "is_empty" not in names and "file_count" not in names
    assert book(files=files(1)).is_empty is False
    assert book(files=NO_FILES).is_empty is True


@pytest.mark.parametrize("wrong", [[], (), None, "files", {"a": 1}, 3])
def test_a_book_refuses_any_file_list_that_is_not_the_shared_snapshot(wrong):
    """No raw ``list[Path]`` and no second file-list type."""
    with pytest.raises(BookContractError):
        BookJob(book_id=new_book_id(factory()), files=wrong)


# --------------------------------------------------------------------------- #
# Configuration — the one deep-freeze
# --------------------------------------------------------------------------- #


def test_configuration_is_frozen_by_the_existing_plan3_freeze():
    entry = book(configuration={"title": "Book", "parts": [1, 2, 3]})
    assert is_frozen_options(entry.configuration), "exactly what freeze_options produces"
    assert isinstance(entry.configuration, MappingProxyType)


def test_nested_mutable_configuration_becomes_actually_immutable():
    payload = {"tags": ["a", "b"], "nested": {"deep": [1]}}
    entry = book(configuration=payload)
    assert entry.configuration["tags"] == ("a", "b")
    assert isinstance(entry.configuration["nested"], MappingProxyType)
    assert entry.configuration["nested"]["deep"] == (1,)
    with pytest.raises(TypeError):
        entry.configuration["tags"] = ("c",)


def test_editing_the_caller_dict_afterwards_cannot_reach_the_book():
    """The whole point of freezing: a book is a value, not a window."""
    payload = {"title": "Original", "tags": ["a"]}
    entry = book(configuration=payload)
    payload["title"] = "Changed"
    payload["tags"].append("b")
    payload["added"] = True
    assert entry.configuration["title"] == "Original"
    assert entry.configuration["tags"] == ("a",)
    assert "added" not in entry.configuration


def test_a_pristine_book_has_the_empty_configuration():
    entry = book()
    assert dict(entry.configuration) == {}
    assert entry.configuration_keys == ()
    assert is_frozen_options(EMPTY_CONFIGURATION)


def test_configuration_keys_are_a_stable_sorted_view():
    entry = book(configuration={"z": 1, "a": 2, "m": 3})
    assert entry.configuration_keys == ("a", "m", "z")


def _open_file(tmp_path):
    handle = (tmp_path / "x.txt").open("w", encoding="utf-8")
    return handle


@pytest.mark.parametrize("label,value", [
    ("callable", lambda: None),
    ("thread", threading.Thread(target=lambda: None)),
    ("lock", threading.Lock()),
    ("event", threading.Event()),
    ("bytearray", bytearray(b"ab")),
    ("memoryview", memoryview(b"ab")),
    ("object", object()),
    ("class", BookJob),
])
def test_a_live_runtime_object_is_refused_by_the_existing_freeze_contract(label, value):
    """Plan 6 neither widens nor weakens what ``freeze_options`` refuses."""
    with pytest.raises(BookConfigurationError):
        book(configuration={label: value})


def test_an_open_file_is_refused(tmp_path):
    handle = _open_file(tmp_path)
    try:
        with pytest.raises(BookConfigurationError):
            book(configuration={"handle": handle})
    finally:
        handle.close()


def test_a_widget_like_object_with_a_live_getter_is_refused():
    """Stands in for a Tk variable: an object whose value can change underneath."""
    class FakeTkVariable:
        def __init__(self):
            self._value = "one"

        def get(self):  # pragma: no cover - must never be reached
            return self._value

        def set(self, value):  # pragma: no cover - must never be reached
            self._value = value

    with pytest.raises(BookConfigurationError):
        book(configuration={"title_var": FakeTkVariable()})


def test_a_mutable_dataclass_is_refused_but_a_frozen_one_is_kept():
    @dataclasses.dataclass
    class Mutable:
        value: int = 1

    @dataclasses.dataclass(frozen=True)
    class Immutable:
        value: int = 1

    with pytest.raises(BookConfigurationError):
        book(configuration={"opt": Mutable()})
    kept = book(configuration={"opt": Immutable()})
    assert kept.configuration["opt"] == Immutable()


def test_a_reference_cycle_is_refused():
    payload: dict = {"self": None}
    payload["self"] = payload
    with pytest.raises(BookConfigurationError):
        book(configuration=payload)


@pytest.mark.parametrize("bad", [[], "title=x", 7, object()])
def test_configuration_must_be_a_mapping(bad):
    with pytest.raises(BookConfigurationError):
        book(configuration=bad)


def test_a_non_string_configuration_key_is_refused():
    with pytest.raises(BookConfigurationError):
        book(configuration={1: "one"})


def test_the_refusal_names_the_book_so_a_batch_failure_is_traceable():
    entry_id = new_book_id(factory())
    with pytest.raises(BookConfigurationError) as caught:
        BookJob(book_id=entry_id, configuration={"fn": lambda: None})
    assert entry_id in str(caught.value)


def test_plan6_defines_no_second_deep_freeze():
    """The refusal must come from Plan 3's function, not a copy of it."""
    source = book_workspace.__dict__
    assert source["freeze_options"].__module__ == "shared.job_control"
    text = (book_workspace.__file__)
    assert text.endswith("book_workspace.py")


# --------------------------------------------------------------------------- #
# Decision 49A — the split, in exactly one canonical place
# --------------------------------------------------------------------------- #


def test_every_book_field_is_classified_and_none_can_escape():
    """The mapping is pinned against the dataclass, so a later field cannot hide."""
    declared = {entry.name for entry in dataclasses.fields(BookJob)}
    assert set(FIELD_ROLES) == declared
    assert declared == {"book_id", "configuration", "files"}


def test_the_three_roles_are_exactly_identity_configuration_and_inputs():
    assert set(FIELD_ROLES.values()) == {ROLE_IDENTITY, ROLE_CONFIGURATION, ROLE_INPUTS}
    assert FIELD_ROLES["book_id"] == ROLE_IDENTITY
    assert FIELD_ROLES["configuration"] == ROLE_CONFIGURATION
    assert FIELD_ROLES["files"] == ROLE_INPUTS


def test_there_is_no_fourth_category():
    for unknown in ("metadata", "outputs", "cover", "state"):
        with pytest.raises(BookContractError):
            field_role(unknown)


def test_field_role_reads_the_one_table_rather_than_deciding_for_itself():
    for name, role in FIELD_ROLES.items():
        assert field_role(name) == role


def test_the_role_table_is_itself_immutable():
    assert isinstance(FIELD_ROLES, MappingProxyType)
    with pytest.raises(TypeError):
        FIELD_ROLES["invented"] = "role"


def test_field_role_refuses_a_malformed_name():
    for bad in ("", "   ", None, 5):
        with pytest.raises(BookContractError):
            field_role(bad)


def test_the_split_is_stated_once_and_the_module_exports_it():
    """One canonical place — a consumer cannot find a second, disagreeing answer."""
    exported = set(book_workspace.__all__)
    assert {"FIELD_ROLES", "field_role"} <= exported
    roles = [name for name in exported if name.startswith("ROLE_")]
    assert sorted(roles) == ["ROLE_CONFIGURATION", "ROLE_IDENTITY", "ROLE_INPUTS"]


def test_configuration_and_inputs_are_genuinely_separate_values():
    """Decision 49A is only meaningful if the two are not entangled."""
    entry = book(configuration={"title": "T"}, files=files(2))
    assert entry.configuration["title"] == "T"
    assert entry.file_count == 2
    # The inputs carry nothing from the configuration and vice versa.
    assert "title" not in entry.files.occurrence_ids
    assert all(not key.startswith("occ") for key in entry.configuration)


def test_the_pristine_input_value_is_what_a_duplicate_will_reset_to():
    """Phase 2 resets inputs to this exact value; Phase 1 only states what it is."""
    assert NO_FILES.is_empty is True
    assert NO_FILES.revision == INITIAL_REVISION
    assert NO_FILES.files == ()
    assert BookJob(book_id=new_book_id(factory())).files == NO_FILES


# --------------------------------------------------------------------------- #
# The workspace value
# --------------------------------------------------------------------------- #


def test_a_workspace_snapshot_is_a_frozen_slotted_record():
    assert WorkspaceSnapshot.__dataclass_params__.frozen is True
    assert "__slots__" in WorkspaceSnapshot.__dict__
    entry = book()
    space = WorkspaceSnapshot(books=(entry,), current_book_id=entry.book_id)
    with pytest.raises(FrozenInstanceError):
        space.books = ()
    with pytest.raises(FrozenInstanceError):
        space.current_book_id = "other"


def test_the_ordered_collection_is_retained_as_a_tuple_in_order():
    maker = factory()
    entries = tuple(book(maker) for _ in range(4))
    space = WorkspaceSnapshot(books=entries, current_book_id=entries[0].book_id)
    assert isinstance(space.books, tuple)
    assert space.books == entries
    assert space.book_ids == tuple(entry.book_id for entry in entries)


def test_a_list_of_books_is_normalised_to_a_tuple():
    entry = book()
    space = WorkspaceSnapshot(books=[entry], current_book_id=entry.book_id)
    assert isinstance(space.books, tuple)


def test_a_workspace_must_hold_at_least_one_book():
    """Decision 13A begins with one book job; ``Book X of Y`` has no reading at Y=0."""
    with pytest.raises(WorkspaceContractError):
        WorkspaceSnapshot(books=(), current_book_id="book-000001")


@pytest.mark.parametrize("wrong", ["books", b"books", None, 7])
def test_books_must_be_an_iterable_of_book_jobs(wrong):
    with pytest.raises(WorkspaceContractError):
        WorkspaceSnapshot(books=wrong, current_book_id="book-000001")


def test_a_non_book_entry_is_refused():
    entry = book()
    with pytest.raises(WorkspaceContractError):
        WorkspaceSnapshot(books=(entry, "not a book"), current_book_id=entry.book_id)


def test_duplicate_book_ids_are_refused():
    entry = book()
    twin = BookJob(book_id=entry.book_id, configuration={"a": 1})
    with pytest.raises(BookIdentityError):
        WorkspaceSnapshot(books=(entry, twin), current_book_id=entry.book_id)


def test_the_current_book_must_be_one_of_this_workspace_s_books():
    entry, stranger = book(), book()
    with pytest.raises(BookIdentityError):
        WorkspaceSnapshot(books=(entry,), current_book_id=stranger.book_id)


@pytest.mark.parametrize("bad", ["", "   ", "book 1", None, 5])
def test_a_malformed_current_book_id_is_refused(bad):
    entry = book()
    with pytest.raises(BookIdentityError):
        WorkspaceSnapshot(books=(entry,), current_book_id=bad)


def test_selection_is_by_identity_and_not_by_index():
    maker = factory()
    first, second, third = book(maker), book(maker), book(maker)
    space = WorkspaceSnapshot(books=(first, second, third),
                              current_book_id=second.book_id)
    assert space.current is second
    # Reordering moves the position but not which book is selected.
    moved = WorkspaceSnapshot(books=(third, second, first),
                              current_book_id=second.book_id)
    assert moved.current is second
    assert space.current_position == 2 and moved.current_position == 2

    removed = WorkspaceSnapshot(books=(second, third), current_book_id=second.book_id)
    assert removed.current is second, "identity survived a neighbour disappearing"
    assert removed.current_position == 1, "only the display position moved"


def test_book_x_of_y_is_a_read_only_projection():
    maker = factory()
    entries = tuple(book(maker) for _ in range(3))
    for position, entry in enumerate(entries, start=1):
        space = WorkspaceSnapshot(books=entries, current_book_id=entry.book_id)
        assert space.current_position == position
        assert space.count == 3
        assert 1 <= space.current_position <= space.count


def test_the_revision_uses_the_existing_plan3_type_and_defaults_to_the_initial_one():
    entry = book()
    space = WorkspaceSnapshot(books=(entry,), current_book_id=entry.book_id)
    assert space.revision == INITIAL_REVISION
    assert isinstance(space.revision, Revision)
    carried = WorkspaceSnapshot(books=(entry,), current_book_id=entry.book_id,
                                revision=Revision(7))
    assert carried.revision == Revision(7)


@pytest.mark.parametrize("wrong", [0, "0", None, 1.0])
def test_a_revision_that_is_not_the_shared_type_is_refused(wrong):
    entry = book()
    with pytest.raises(WorkspaceContractError):
        WorkspaceSnapshot(books=(entry,), current_book_id=entry.book_id, revision=wrong)


def test_book_for_is_a_lookup_and_never_a_selection():
    maker = factory()
    first, second = book(maker), book(maker)
    space = WorkspaceSnapshot(books=(first, second), current_book_id=first.book_id)
    assert space.book_for(second.book_id) is second
    assert space.current is first, "looking a book up did not select it"
    assert space.book_for("t-book-009999") is None


def test_book_for_refuses_a_malformed_identity_rather_than_returning_none():
    entry = book()
    space = WorkspaceSnapshot(books=(entry,), current_book_id=entry.book_id)
    for bad in ("", "   ", None, 5):
        with pytest.raises(BookIdentityError):
            space.book_for(bad)


def test_constructing_a_workspace_has_no_side_effects(tmp_path):
    """Validation is pure: nothing is created, written or counted anywhere."""
    before = sorted(tmp_path.iterdir())
    maker = factory()
    entries = tuple(book(maker, configuration={"n": index}) for index in range(3))
    space = WorkspaceSnapshot(books=entries, current_book_id=entries[1].book_id)
    again = WorkspaceSnapshot(books=entries, current_book_id=entries[1].book_id)
    assert sorted(tmp_path.iterdir()) == before
    assert space == again, "two identical values compare equal"
    assert space.revision == again.revision == INITIAL_REVISION


def test_two_workspaces_over_the_same_books_are_equal_values():
    maker = factory()
    entries = tuple(book(maker) for _ in range(2))
    one = WorkspaceSnapshot(books=entries, current_book_id=entries[0].book_id)
    two = WorkspaceSnapshot(books=entries, current_book_id=entries[0].book_id)
    assert one == two
    three = WorkspaceSnapshot(books=entries, current_book_id=entries[1].book_id)
    assert one != three, "a different selection is a different value"


# =========================================================================== #
# Phase 2 — the workspace controller
#
# Pure functions over the Phase 1 value: hold a snapshot, call an operation, get
# a new snapshot back. Nothing below builds a widget, starts a thread or touches
# a disk, and no operation mutates its argument.
# =========================================================================== #


def workspace(count: int = 1, maker: IdFactory | None = None,
              **kwargs) -> WorkspaceSnapshot:
    """A workspace of *count* pristine books, selected on the first."""
    ids = maker or IdFactory("w-")
    books = tuple(BookJob(book_id=new_book_id(ids)) for _ in range(count))
    return WorkspaceSnapshot(books=books, current_book_id=books[0].book_id, **kwargs)


# --------------------------------------------------------------------------- #
# Decision 50A — the meaningful-work predicate
# --------------------------------------------------------------------------- #


def test_a_pristine_book_holds_no_meaningful_work():
    assert has_meaningful_work(book()) is False


def test_one_imported_file_makes_a_book_meaningful():
    assert has_meaningful_work(book(files=files(1))) is True


def test_one_configuration_value_makes_a_book_meaningful():
    assert has_meaningful_work(book(configuration={"title": "T"})) is True


def test_both_inputs_and_configuration_make_a_book_meaningful():
    assert has_meaningful_work(book(configuration={"title": "T"}, files=files(2))) is True


def test_the_predicate_covers_every_combination_exactly():
    """The whole truth table, so no cell is decided by accident."""
    table = {
        (False, False): False,
        (True, False): True,
        (False, True): True,
        (True, True): True,
    }
    for (has_config, has_files), expected in table.items():
        entry = book(configuration={"k": 1} if has_config else {},
                     files=files(1) if has_files else NO_FILES)
        assert has_meaningful_work(entry) is expected, (has_config, has_files)


def test_the_predicate_refuses_anything_that_is_not_a_book():
    for wrong in (None, "book", 3, workspace()):
        with pytest.raises(BookContractError):
            has_meaningful_work(wrong)


def test_the_predicate_is_the_only_place_the_question_is_answered():
    """Decision 50A in one place: removal must not grow a second opinion."""
    import inspect
    from shared import book_workspace as module
    source = inspect.getsource(module.remove_book)
    assert "has_meaningful_work" in source
    # No second inline test of emptiness beside the predicate.
    assert "configuration)" not in source and "is_empty" not in source


# --------------------------------------------------------------------------- #
# The operation / result vocabulary
# --------------------------------------------------------------------------- #


def test_the_operation_enum_is_plan6_specific_and_names_every_operation():
    """Seven from Phase 2, Phase 3's ``import``, and Phase 4's ``shared_metadata``."""
    assert {member.value for member in WorkspaceOperation} == {
        "add", "duplicate", "remove", "previous", "next", "select", "replace",
        "import", "shared_metadata"}


def test_the_operation_enum_is_not_plan3s_manager_operation():
    """Overloading ``ManagerOperation`` would make one symbol mean two things.

    The two vocabularies both have a *remove*, and that is exactly the point: the
    strings overlap, so only distinct **types** keep "remove a file from a list"
    and "remove a book from a workspace" apart. A result therefore refuses a
    member of the other enum outright.
    """
    from shared.importing import ManagerOperation
    assert WorkspaceOperation is not ManagerOperation
    assert not issubclass(WorkspaceOperation, ManagerOperation)
    assert {m.name for m in WorkspaceOperation} != {m.name for m in ManagerOperation}
    with pytest.raises(WorkspaceContractError):
        BookMutation(operation=ManagerOperation.REMOVE, changed=False,
                     workspace=workspace())


def test_a_mutation_is_a_frozen_slotted_record():
    assert BookMutation.__dataclass_params__.frozen is True
    assert "__slots__" in BookMutation.__dict__
    result = add_book(workspace(), id_factory=IdFactory("m-"))
    with pytest.raises(FrozenInstanceError):
        result.changed = False
    assert not hasattr(result, "__dict__")


def test_a_mutation_derives_selection_and_revision_rather_than_storing_them():
    """Two copies of one fact can disagree; one cannot."""
    stored = {entry.name for entry in dataclasses.fields(BookMutation)}
    assert stored == {"operation", "changed", "workspace", "removed"}
    result = add_book(workspace(), id_factory=IdFactory("m-"))
    assert result.revision is result.workspace.revision
    assert result.current_book_id == result.workspace.current_book_id
    assert result.current is result.workspace.current


@pytest.mark.parametrize("field_name,bad", [
    ("operation", "add"), ("changed", 1), ("workspace", None), ("removed", ("x",)),
])
def test_a_mutation_refuses_a_malformed_field(field_name, bad):
    space = workspace()
    good = {"operation": WorkspaceOperation.ADD, "changed": True,
            "workspace": space, "removed": ()}
    good[field_name] = bad
    with pytest.raises((WorkspaceContractError, BookContractError)):
        BookMutation(**good)


def test_every_operation_reports_which_operation_it_was():
    maker = IdFactory("op-")
    space = workspace(3, maker)
    assert add_book(space, id_factory=maker).operation is WorkspaceOperation.ADD
    assert duplicate_book(space, id_factory=maker).operation is WorkspaceOperation.DUPLICATE
    assert remove_book(space, id_factory=maker).operation is WorkspaceOperation.REMOVE
    assert previous_book(space).operation is WorkspaceOperation.PREVIOUS
    assert next_book(space).operation is WorkspaceOperation.NEXT
    assert select_book(space, space.book_ids[1]).operation is WorkspaceOperation.SELECT
    assert replace_book(space, space.current).operation is WorkspaceOperation.REPLACE


@pytest.mark.parametrize("call", [
    lambda s, m: add_book(s, id_factory=m),
    lambda s, m: duplicate_book(s, id_factory=m),
    lambda s, m: remove_book(s, id_factory=m),
    lambda s, m: previous_book(s),
    lambda s, m: next_book(s),
])
def test_every_operation_refuses_something_that_is_not_a_workspace(call):
    maker = IdFactory("bad-")
    for wrong in (None, "workspace", 3, book()):
        with pytest.raises(WorkspaceContractError):
            call(wrong, maker)


# --------------------------------------------------------------------------- #
# Add Book (Decision 13A)
# --------------------------------------------------------------------------- #


def test_add_appends_a_pristine_book_and_selects_it():
    maker = IdFactory("a-")
    space = workspace(2, maker)
    result = add_book(space, id_factory=maker)

    assert result.changed is True
    assert result.workspace.count == 3
    added = result.workspace.books[-1]
    assert result.workspace.current_book_id == added.book_id
    assert added.is_empty is True
    assert dict(added.configuration) == {}
    assert result.workspace.current_position == 3


def test_add_leaves_every_existing_book_untouched():
    maker = IdFactory("a-")
    space = WorkspaceSnapshot(
        books=(BookJob(book_id=new_book_id(maker), configuration={"n": 1}),
               BookJob(book_id=new_book_id(maker), files=files(2))),
        current_book_id="a-book-000001")
    result = add_book(space, id_factory=maker)
    assert result.workspace.books[:2] == space.books, "same objects, same order"


def test_add_advances_the_revision_exactly_once():
    space = workspace(1, revision=Revision(4))
    result = add_book(space, id_factory=IdFactory("a-"))
    assert result.revision == Revision(5)


def test_add_mints_a_fresh_identity_that_is_not_derived_from_the_index():
    maker = IdFactory("a-")
    space = workspace(1, maker)
    first = add_book(space, id_factory=maker).workspace.books[-1].book_id
    second = add_book(space, id_factory=maker).workspace.books[-1].book_id
    assert first != second, "two adds from one workspace do not collide"
    assert not first.endswith("-2"), "not derived from a position"


def test_add_does_not_mutate_the_workspace_it_was_given():
    space = workspace(2)
    before = (space.books, space.current_book_id, space.revision)
    add_book(space, id_factory=IdFactory("a-"))
    assert (space.books, space.current_book_id, space.revision) == before


# --------------------------------------------------------------------------- #
# Duplicate Book (Decisions 13A + 49A)
# --------------------------------------------------------------------------- #


def duplicated(config=None, file_count=2):
    maker = IdFactory("d-")
    source = BookJob(book_id=new_book_id(maker),
                     configuration=config if config is not None else {"title": "Source"},
                     files=files(file_count))
    other = BookJob(book_id=new_book_id(maker))
    space = WorkspaceSnapshot(books=(source, other), current_book_id=source.book_id)
    return source, space, duplicate_book(space, id_factory=maker)


def test_duplicate_copies_every_configuration_key_and_value():
    payload = {"title": "T", "parts": [1, 2], "nested": {"deep": "v"}}
    source, _space, result = duplicated(config=payload)
    copy = result.workspace.current
    assert copy.configuration == source.configuration
    assert copy.configuration_keys == source.configuration_keys
    assert copy.configuration["parts"] == (1, 2)


def test_duplicate_starts_with_the_canonical_empty_snapshot():
    """Decision 49A: configuration travels, imported inputs do not."""
    _source, _space, result = duplicated()
    copy = result.workspace.current
    assert copy.files == NO_FILES
    assert copy.files.revision == INITIAL_REVISION
    assert copy.is_empty is True
    assert copy.file_count == 0


def test_duplicate_leaves_the_source_input_snapshot_untouched():
    source, _space, result = duplicated(file_count=3)
    still = result.workspace.book_for(source.book_id)
    assert still is source
    assert still.file_count == 3


def test_the_duplicate_gets_a_new_identity():
    source, _space, result = duplicated()
    copy = result.workspace.current
    assert copy.book_id != source.book_id
    assert len(set(result.workspace.book_ids)) == result.workspace.count


def test_duplicate_inserts_immediately_after_its_source_and_selects_it():
    source, space, result = duplicated()
    ids = result.workspace.book_ids
    assert ids.index(result.workspace.current_book_id) == ids.index(source.book_id) + 1
    assert result.workspace.count == space.count + 1
    assert result.changed is True


def test_duplicate_obeys_the_central_split_rather_than_restating_it():
    """If a field were added to BookJob, this would have to be classified."""
    import inspect
    from shared import book_workspace as module
    source = inspect.getsource(module.duplicate_book)
    assert "FIELD_ROLES" in source and "field_role" in source
    assert "ROLE_CONFIGURATION" in source


def test_the_two_books_share_no_mutable_state_afterwards():
    """Replacing one later must not reach the other."""
    source, _space, result = duplicated(config={"title": "Original"})
    space = result.workspace
    copy = space.current
    edited = BookJob(book_id=copy.book_id, configuration={"title": "Edited"},
                     files=files(1))
    after = replace_book(space, edited).workspace
    assert after.book_for(source.book_id).configuration["title"] == "Original"
    assert after.book_for(source.book_id).file_count == 2
    assert after.book_for(copy.book_id).configuration["title"] == "Edited"


def test_duplicate_advances_the_revision_exactly_once():
    maker = IdFactory("d-")
    space = workspace(1, maker, revision=Revision(2))
    assert duplicate_book(space, id_factory=maker).revision == Revision(3)


# --------------------------------------------------------------------------- #
# Remove Book (Decisions 13A + 50A)
# --------------------------------------------------------------------------- #


def test_remove_the_first_of_several_selects_the_one_that_took_its_slot():
    maker = IdFactory("r-")
    space = workspace(3, maker)
    result = remove_book(space, id_factory=maker)
    assert result.workspace.count == 2
    assert result.workspace.book_ids == space.book_ids[1:]
    assert result.workspace.current_book_id == space.book_ids[1]
    assert result.workspace.current_position == 1
    assert result.removed == (space.books[0],)


def test_remove_a_middle_book_selects_the_one_that_took_its_slot():
    maker = IdFactory("r-")
    space = select_book(workspace(3, maker), None or "r-book-000002").workspace
    result = remove_book(space, id_factory=maker)
    assert result.workspace.book_ids == ("r-book-000001", "r-book-000003")
    assert result.workspace.current_book_id == "r-book-000003"
    assert result.workspace.current_position == 2


def test_remove_the_last_of_several_selects_the_new_last_book():
    maker = IdFactory("r-")
    space = select_book(workspace(3, maker), "r-book-000003").workspace
    result = remove_book(space, id_factory=maker)
    assert result.workspace.book_ids == ("r-book-000001", "r-book-000002")
    assert result.workspace.current_book_id == "r-book-000002"
    assert result.workspace.current_position == 2


def test_removing_the_sole_meaningful_book_leaves_one_pristine_book():
    """Never empty, and the work really is discarded."""
    maker = IdFactory("r-")
    only = BookJob(book_id=new_book_id(maker),
                   configuration={"title": "Gone"}, files=files(2))
    space = WorkspaceSnapshot(books=(only,), current_book_id=only.book_id)
    result = remove_book(space, id_factory=maker)

    assert result.changed is True
    assert result.workspace.count == 1
    replacement = result.workspace.current
    assert replacement.book_id != only.book_id
    assert replacement.is_empty is True
    assert dict(replacement.configuration) == {}
    assert has_meaningful_work(replacement) is False
    assert result.removed == (only,)
    assert result.workspace.current_position == 1


def test_removing_a_sole_pristine_book_is_a_no_op():
    """Nothing to lose, nothing visibly changes: no revision, no consumed id."""
    maker = IdFactory("r-")
    space = workspace(1, maker, revision=Revision(3))
    result = remove_book(space, id_factory=maker)

    assert result.changed is False
    assert result.workspace is space
    assert result.revision == Revision(3)
    assert result.removed == ()
    assert new_book_id(maker) == "r-book-000002", "no identity was consumed"


def test_removal_never_produces_a_zero_book_workspace():
    maker = IdFactory("r-")
    space = workspace(3, maker)
    for _ in range(6):
        space = remove_book(space, id_factory=maker).workspace
        assert space.count >= 1
        assert 1 <= space.current_position <= space.count


def test_remove_advances_the_revision_exactly_once_when_it_changes_anything():
    maker = IdFactory("r-")
    space = workspace(2, maker, revision=Revision(9))
    assert remove_book(space, id_factory=maker).revision == Revision(10)


def test_the_meaningful_work_answer_is_separate_from_removal_semantics():
    """Phase 2 supplies the answer; it does not decide to ask, and shows no dialog."""
    maker = IdFactory("r-")
    loaded = BookJob(book_id=new_book_id(maker), files=files(1))
    empty = BookJob(book_id=new_book_id(maker))
    space = WorkspaceSnapshot(books=(loaded, empty), current_book_id=loaded.book_id)

    assert has_meaningful_work(space.current) is True
    # Removal itself proceeds regardless; confirming is the consumer's job.
    assert remove_book(space, id_factory=maker).changed is True

    space = select_book(space, empty.book_id).workspace
    assert has_meaningful_work(space.current) is False
    assert remove_book(space, id_factory=maker).changed is True


# --------------------------------------------------------------------------- #
# Previous / Next — non-wrapping
# --------------------------------------------------------------------------- #


def test_previous_at_the_first_book_is_a_no_op():
    space = workspace(3, revision=Revision(2))
    result = previous_book(space)
    assert result.changed is False
    assert result.workspace is space
    assert result.revision == Revision(2)


def test_next_at_the_last_book_is_a_no_op():
    maker = IdFactory("n-")
    space = select_book(workspace(3, maker), "n-book-000003").workspace
    result = next_book(space)
    assert result.changed is False
    assert result.workspace is space


def test_navigation_moves_exactly_one_book():
    maker = IdFactory("n-")
    space = workspace(4, maker)
    for expected in (2, 3, 4):
        space = next_book(space).workspace
        assert space.current_position == expected
    for expected in (3, 2, 1):
        space = previous_book(space).workspace
        assert space.current_position == expected


def test_navigation_never_rearranges_the_books():
    maker = IdFactory("n-")
    space = workspace(4, maker)
    order = space.book_ids
    space = next_book(space).workspace
    space = next_book(space).workspace
    space = previous_book(space).workspace
    assert space.book_ids == order
    assert space.count == 4


def test_navigating_away_and_back_returns_the_exact_independent_book_state():
    """The state lives in the model, not in widgets, so this is structural."""
    maker = IdFactory("n-")
    first = BookJob(book_id=new_book_id(maker),
                    configuration={"title": "First"}, files=files(3))
    second = BookJob(book_id=new_book_id(maker),
                     configuration={"title": "Second"}, files=files(1))
    space = WorkspaceSnapshot(books=(first, second), current_book_id=first.book_id)

    away = next_book(space).workspace
    back = previous_book(away).workspace

    assert back.current is first
    assert back.current.configuration["title"] == "First"
    assert back.current.file_count == 3
    assert away.book_for(second.book_id) is second
    assert back.books == space.books, "the same book objects throughout"


def test_navigation_changes_only_the_selection_and_the_revision():
    space = workspace(3, revision=Revision(1))
    result = next_book(space)
    assert result.workspace.books == space.books
    assert result.workspace.current_book_id != space.current_book_id
    assert result.revision == Revision(2)


# --------------------------------------------------------------------------- #
# Select by identity
# --------------------------------------------------------------------------- #


def test_select_moves_to_an_existing_book_and_advances_the_revision():
    maker = IdFactory("s-")
    space = workspace(3, maker, revision=Revision(5))
    result = select_book(space, "s-book-000003")
    assert result.changed is True
    assert result.workspace.current_book_id == "s-book-000003"
    assert result.workspace.current_position == 3
    assert result.revision == Revision(6)
    assert result.workspace.books == space.books


def test_selecting_the_already_current_book_is_a_no_op():
    space = workspace(3, revision=Revision(7))
    result = select_book(space, space.current_book_id)
    assert result.changed is False
    assert result.workspace is space
    assert result.revision == Revision(7)


def test_selecting_an_unknown_identity_is_rejected_atomically():
    space = workspace(3, revision=Revision(2))
    before = (space.books, space.current_book_id, space.revision)
    with pytest.raises(BookIdentityError):
        select_book(space, "s-book-999999")
    assert (space.books, space.current_book_id, space.revision) == before


@pytest.mark.parametrize("bad", ["", "   ", "book 1", "books/1", None, 5])
def test_selecting_a_malformed_identity_is_rejected(bad):
    space = workspace(2)
    with pytest.raises(BookIdentityError):
        select_book(space, bad)


def test_selection_never_accepts_a_list_index_as_an_identity():
    """An index is a display position, not an identity."""
    space = workspace(3)
    for index in (0, 1, 2, "0", "1"):
        with pytest.raises(BookIdentityError):
            select_book(space, index)


# --------------------------------------------------------------------------- #
# Replace
# --------------------------------------------------------------------------- #


def test_replace_swaps_one_value_in_place_and_keeps_order_and_selection():
    maker = IdFactory("p-")
    space = workspace(3, maker)
    space = select_book(space, "p-book-000002").workspace
    target = space.book_for("p-book-000003")
    updated = BookJob(book_id=target.book_id, configuration={"title": "New"})

    result = replace_book(space, updated)
    assert result.changed is True
    assert result.workspace.book_ids == space.book_ids, "order preserved"
    assert result.workspace.current_book_id == "p-book-000002", "selection preserved"
    assert result.workspace.book_for(target.book_id) is updated


def test_replace_identifies_its_target_by_the_identity_it_carries():
    maker = IdFactory("p-")
    space = workspace(2, maker)
    updated = BookJob(book_id="p-book-000002", files=files(1))
    assert replace_book(space, updated).workspace.book_for("p-book-000002") is updated


def test_a_replacement_carrying_a_foreign_identity_is_rejected_atomically():
    """Otherwise an ordinary edit would silently become a remove-and-add."""
    space = workspace(2, revision=Revision(4))
    before = (space.books, space.current_book_id, space.revision)
    stranger = BookJob(book_id=new_book_id(IdFactory("other-")))
    with pytest.raises(BookIdentityError):
        replace_book(space, stranger)
    assert (space.books, space.current_book_id, space.revision) == before


def test_replacing_with_an_equal_value_is_a_no_op():
    space = workspace(2, revision=Revision(3))
    same = BookJob(book_id=space.current_book_id)
    assert same == space.current
    result = replace_book(space, same)
    assert result.changed is False
    assert result.workspace is space
    assert result.revision == Revision(3)


def test_replace_refuses_anything_that_is_not_a_book():
    space = workspace(2)
    for wrong in (None, "book", 3, space):
        with pytest.raises(WorkspaceContractError):
            replace_book(space, wrong)


def test_there_is_no_partial_replacement_primitive():
    """One primitive that swaps a whole value cannot disagree with itself."""
    from shared import book_workspace as module
    for invented in ("replace_configuration", "replace_files", "replace_metadata",
                     "update_configuration", "set_files"):
        assert not hasattr(module, invented), invented


# --------------------------------------------------------------------------- #
# Revision, Book X of Y, and atomicity across every operation
# --------------------------------------------------------------------------- #


def test_a_no_op_never_advances_the_revision():
    maker = IdFactory("v-")
    space = workspace(1, maker, revision=Revision(6))
    for result in (previous_book(space),
                   next_book(space),
                   select_book(space, space.current_book_id),
                   replace_book(space, space.current),
                   remove_book(space, id_factory=maker)):
        assert result.changed is False, result.operation
        assert result.revision == Revision(6), result.operation
        assert result.workspace is space, result.operation


def test_every_real_change_advances_the_revision_exactly_once():
    maker = IdFactory("v-")
    space = workspace(3, maker, revision=Revision(0))
    steps = [
        lambda s: add_book(s, id_factory=maker),
        # Duplicate leaves the copy selected and last, so Previous is the step
        # that genuinely moves here; Next would correctly be a no-op.
        lambda s: duplicate_book(s, id_factory=maker),
        lambda s: previous_book(s),
        lambda s: select_book(s, s.book_ids[0]),
        lambda s: remove_book(s, id_factory=maker),
        lambda s: replace_book(s, BookJob(book_id=s.current_book_id,
                                          configuration={"n": s.count})),
    ]
    expected = 0
    for step in steps:
        result = step(space)
        assert result.changed is True, result.operation
        expected += 1
        assert result.revision == Revision(expected), result.operation
        space = result.workspace


def test_book_x_of_y_stays_valid_after_every_operation():
    maker = IdFactory("x-")
    space = workspace(2, maker)
    operations = [
        lambda s: add_book(s, id_factory=maker),
        lambda s: duplicate_book(s, id_factory=maker),
        lambda s: previous_book(s),
        lambda s: next_book(s),
        lambda s: select_book(s, s.book_ids[0]),
        lambda s: remove_book(s, id_factory=maker),
        lambda s: replace_book(s, BookJob(book_id=s.current_book_id)),
    ]
    for step in operations:
        space = step(space).workspace
        assert space.count >= 1, "Y >= 1"
        assert 1 <= space.current_position <= space.count, "1 <= X <= Y"
        assert space.current_book_id in space.book_ids


def test_the_selected_book_identity_survives_every_operation_that_does_not_remove_it():
    maker = IdFactory("k-")
    space = workspace(3, maker)
    space = select_book(space, "k-book-000002").workspace
    kept = space.current_book_id

    for step in (lambda s: add_book(s, id_factory=maker),
                 lambda s: replace_book(s, BookJob(book_id=s.current_book_id,
                                                   configuration={"n": 1}))):
        after = step(space).workspace
        if after.current_book_id != kept:
            # Add deliberately selects the new book; the old one still exists.
            assert kept in after.book_ids
        else:
            assert after.current_book_id == kept


def test_no_operation_mutates_the_workspace_it_was_given():
    maker = IdFactory("i-")
    space = workspace(3, maker)
    snapshot = (space.books, space.current_book_id, space.revision)
    add_book(space, id_factory=maker)
    duplicate_book(space, id_factory=maker)
    remove_book(space, id_factory=maker)
    previous_book(space)
    next_book(space)
    select_book(space, space.book_ids[2])
    replace_book(space, BookJob(book_id=space.current_book_id))
    assert (space.books, space.current_book_id, space.revision) == snapshot


def test_a_rejected_operation_consumes_no_identity():
    """Validation happens before the factory is asked."""
    maker = IdFactory("z-")
    for call in (lambda: add_book("not a workspace", id_factory=maker),
                 lambda: duplicate_book(None, id_factory=maker),
                 lambda: remove_book(7, id_factory=maker)):
        with pytest.raises(WorkspaceContractError):
            call()
    assert new_book_id(maker) == "z-book-000001", "nothing was minted"


# --------------------------------------------------------------------------- #
# Phase 6 must remain absent
#
# Phase 5 delivered the frozen run, so capture now exists and is covered in
# ``test_book_run_snapshot.py``. The absence boundary moves forward with the plan
# rather than being retired: numbering is Phase 6's, and dispositions and retry
# are Phase 7's.
# --------------------------------------------------------------------------- #


def test_no_numbering_or_disposition_exists_yet():
    """Phases 6 and 7 own these. Absence is proved, not merely untested."""
    from shared import book_workspace as module
    for later in ("SuccessNumbers", "Tentative", "NumberingError",
                  "BookRunResult", "BookDisposition", "retry_failed_books",
                  "RunResult", "RetryRequest"):
        assert not hasattr(module, later), later


def test_a_book_still_stores_only_its_own_raw_values():
    """Precedence resolves live; nothing frozen or effective is stored on a book."""
    entry = book(configuration={"title": "Only"})
    assert entry.configuration["title"] == "Only"
    assert not hasattr(entry, "effective_configuration")
    assert not hasattr(entry, "shared")
    names = {item.name for item in dataclasses.fields(BookJob)}
    assert names == {"book_id", "configuration", "files"}
