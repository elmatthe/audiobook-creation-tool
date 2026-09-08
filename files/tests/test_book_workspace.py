"""The book-job vocabulary — v0.6.3 Drop 1 (Plan 6), Phase 1.

Stable book identity, the deep-frozen configuration, one imported-file snapshot per
book, Decision 49A's configuration/input split, and the immutable workspace value
Phase 2 will replace.

**There is no controller here, and there must not be one yet.** Add, Duplicate,
Remove, Previous, Next, Select and Replace are Phase 2's, so nothing below drives
them; the structural guard in ``test_plan6_boundaries.py`` proves they are absent
rather than merely untested.

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
    EMPTY_CONFIGURATION,
    FIELD_ROLES,
    NO_FILES,
    ROLE_CONFIGURATION,
    ROLE_IDENTITY,
    ROLE_INPUTS,
    WorkspaceContractError,
    WorkspaceSnapshot,
    field_role,
    new_book_id,
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
