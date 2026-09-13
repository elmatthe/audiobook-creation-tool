"""Decision 20B — Shared Metadata precedence, v0.6.3 Drop 1 (Plan 6), Phase 4.

Three values are kept apart and never conflated: the **raw per-book** value in
``BookJob.configuration``, the **raw shared** value stored once on the workspace,
and the **effective** value, which is computed and stored nowhere.

The contract these exist to protect is the one in section 15.2: a populated shared
field wins *even when the per-book field is also populated*, and the per-book raw
value is **preserved, not destroyed** — so clearing the shared field later restores
it exactly. That is a property of never having overwritten it, and the whole
lifecycle is pinned end to end below.

Nothing here builds a widget or decides what a control looks like. Phase 4 supplies
the disabled-field *set*; rendering it is the adapter's, in Phase 8.
"""

from __future__ import annotations

import dataclasses
from dataclasses import FrozenInstanceError
from types import MappingProxyType

import pytest

from shared import book_workspace
from shared.book_workspace import (
    BLANK,
    BookContractError,
    BookJob,
    NO_SHARED_METADATA,
    SharedMetadata,
    SharedMetadataError,
    WorkspaceContractError,
    WorkspaceOperation,
    WorkspaceSnapshot,
    add_book,
    disabled_fields,
    duplicate_book,
    effective_metadata,
    effective_value,
    is_populated,
    new_book_id,
    next_book,
    previous_book,
    remove_book,
    replace_book,
    replace_workspace_from_import,
    select_book,
    set_shared_metadata,
)
from shared.importing import IdFactory, Revision

from test_book_grouping import scanned


FIELDS = ("title", "author", "series")

_IDS = IdFactory("s-")


def book(**configuration) -> BookJob:
    return BookJob(book_id=new_book_id(_IDS), configuration=configuration)


def workspace(*books: BookJob, shared: SharedMetadata | None = None,
              revision: Revision | None = None) -> WorkspaceSnapshot:
    entries = books or (book(),)
    return WorkspaceSnapshot(
        books=entries,
        current_book_id=entries[0].book_id,
        revision=revision if revision is not None else Revision(0),
        shared=SharedMetadata.for_fields(FIELDS) if shared is None else shared,
    )


def shared_with(**values) -> SharedMetadata:
    return SharedMetadata(FIELDS, values)


# --------------------------------------------------------------------------- #
# The value model
# --------------------------------------------------------------------------- #


def test_shared_metadata_is_a_frozen_slotted_record():
    assert SharedMetadata.__dataclass_params__.frozen is True
    assert "__slots__" in SharedMetadata.__dict__
    value = shared_with(title="T")
    with pytest.raises(FrozenInstanceError):
        value.fields = ()
    assert not hasattr(value, "__dict__")


def test_the_field_vocabulary_is_declared_by_the_consumer():
    """No universal list: two consumers may declare entirely different fields."""
    one = SharedMetadata.for_fields(("title", "author"))
    two = SharedMetadata.for_fields(("album", "narrator", "isbn"))
    assert one.fields == ("title", "author")
    assert two.fields == ("album", "narrator", "isbn")


def test_no_universal_metadata_vocabulary_is_hard_coded_in_plan6():
    """The drop rejects one; a constant naming audiobook fields would be it."""
    for invented in ("UNIVERSAL_METADATA_FIELDS", "METADATA_FIELDS",
                     "DEFAULT_FIELDS", "SHARED_FIELDS", "AUDIOBOOK_FIELDS"):
        assert not hasattr(book_workspace, invented), invented


def test_the_declared_order_is_the_consumers_order():
    assert SharedMetadata.for_fields(("z", "a", "m")).fields == ("z", "a", "m")


def test_a_duplicate_declared_field_is_refused():
    with pytest.raises(SharedMetadataError):
        SharedMetadata(("title", "author", "title"))


@pytest.mark.parametrize("bad", ["", "   ", "two words", "a/b", "a\\b", None, 5])
def test_a_malformed_field_name_is_refused(bad):
    with pytest.raises(SharedMetadataError):
        SharedMetadata((bad,))


@pytest.mark.parametrize("bad", ["fields", b"fields", 7, None])
def test_fields_must_be_an_iterable_of_names(bad):
    with pytest.raises(SharedMetadataError):
        SharedMetadata(bad)


def test_a_value_for_an_undeclared_field_is_refused():
    """Narrowing the vocabulary must fail loudly, never orphan what the user typed."""
    with pytest.raises(SharedMetadataError):
        SharedMetadata(("title",), {"author": "Someone"})


def test_removing_a_declared_field_that_still_holds_a_value_is_refused():
    populated = shared_with(series="A Series")
    assert populated.raw("series") == "A Series"
    with pytest.raises(SharedMetadataError):
        SharedMetadata(("title", "author"), dict(populated.values))


@pytest.mark.parametrize("bad", [1, 1.5, True, None, ("a",), ["a"], {"a": 1}])
def test_a_non_string_shared_value_is_refused(bad):
    """The drop defines populatedness for text; refusing keeps it from being invented."""
    with pytest.raises(SharedMetadataError):
        SharedMetadata(("title",), {"title": bad})


def test_values_must_be_a_mapping():
    for bad in ([], "title=T", 7):
        with pytest.raises(SharedMetadataError):
            SharedMetadata(("title",), bad)


def test_the_raw_values_are_frozen_and_immune_to_later_caller_edits():
    payload = {"title": "Original"}
    value = SharedMetadata(FIELDS, payload)
    payload["title"] = "Changed"
    payload["author"] = "Added"
    assert value.raw("title") == "Original"
    assert value.raw("author") == BLANK
    assert isinstance(value.values, MappingProxyType)
    with pytest.raises(TypeError):
        value.values["title"] = "Nope"


def test_an_undeclared_field_cannot_be_read_or_asked_about():
    value = shared_with(title="T")
    for method in (value.raw, value.populated):
        with pytest.raises(SharedMetadataError):
            method("narrator")


def test_the_default_shared_metadata_declares_nothing():
    assert NO_SHARED_METADATA.fields == ()
    assert dict(NO_SHARED_METADATA.values) == {}
    assert NO_SHARED_METADATA.is_empty is True
    assert disabled_fields(NO_SHARED_METADATA) == frozenset()


def test_declares_reports_the_vocabulary():
    value = SharedMetadata.for_fields(("title",))
    assert value.declares("title") is True
    assert value.declares("author") is False


# --------------------------------------------------------------------------- #
# Populatedness — one predicate
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("value,expected", [
    ("", False),
    ("   ", False),
    ("\t\n", False),
    (" ", False),
    (None, False),
    ("Title", True),
    ("  Title  ", True),
    ("0", True),
    (".", True),
])
def test_populatedness_is_non_blank_after_stripping(value, expected):
    assert is_populated(value) is expected


def test_surrounding_whitespace_does_not_make_text_blank():
    value = shared_with(title="  Series Shared  ")
    assert value.populated("title") is True


def test_the_raw_value_is_never_stripped_by_the_predicate():
    """Raw stays raw; only the question strips."""
    value = shared_with(title="  Padded  ")
    assert value.raw("title") == "  Padded  "
    entry = book(title="A")
    assert effective_value(value, entry, "title") == "  Padded  "


def test_precedence_and_the_disabled_projection_share_one_predicate():
    """Two interpretations of 'populated' would eventually disagree.

    The failure that would cause is precise: a control the user can still type
    into whose value is silently discarded. So the same fact must drive both.
    """
    for raw in ("", "   ", "\t", "T", "  T  "):
        value = shared_with(title=raw)
        overrides = effective_value(value, book(title="Own"), "title") == raw
        disabled = "title" in disabled_fields(value)
        assert overrides is disabled is is_populated(raw), raw


def test_the_predicate_is_public_so_a_consumer_need_not_invent_a_second():
    assert "is_populated" in book_workspace.__all__


# --------------------------------------------------------------------------- #
# Precedence
# --------------------------------------------------------------------------- #


def test_a_populated_shared_value_overrides_a_populated_per_book_value():
    value = shared_with(title="Series Shared")
    assert effective_value(value, book(title="Per Book"), "title") == "Series Shared"


def test_a_populated_shared_value_overrides_a_blank_per_book_value():
    value = shared_with(title="Series Shared")
    assert effective_value(value, book(title=""), "title") == "Series Shared"
    assert effective_value(value, book(), "title") == "Series Shared"


def test_a_blank_shared_value_leaves_the_per_book_value_effective():
    for blank in ("", "   ", "\t\n"):
        value = shared_with(title=blank)
        assert effective_value(value, book(title="Per Book"), "title") == "Per Book"


def test_an_absent_shared_value_leaves_the_per_book_value_effective():
    value = SharedMetadata.for_fields(FIELDS)
    assert effective_value(value, book(title="Per Book"), "title") == "Per Book"


def test_both_blank_yields_blank():
    value = shared_with(title="  ")
    assert effective_value(value, book(title=""), "title") == ""
    assert effective_value(value, book(), "title") == BLANK
    assert BLANK == ""


def test_fields_resolve_independently_of_one_another():
    """Shared author populated, shared title blank — the drop's worked example."""
    value = shared_with(author="Shared Author", title="")
    entry = book(title="Book A Title", author="Book A Author")
    assert effective_value(value, entry, "author") == "Shared Author"
    assert effective_value(value, entry, "title") == "Book A Title"


def test_effective_metadata_resolves_every_declared_field_at_once():
    value = shared_with(author="Shared Author")
    entry = book(title="A Title", author="A Author", series="A Series")
    assert dict(effective_metadata(value, entry)) == {
        "title": "A Title", "author": "Shared Author", "series": "A Series"}


def test_effective_metadata_is_immutable_and_covers_exactly_the_declared_fields():
    resolved = effective_metadata(shared_with(), book(title="T"))
    assert isinstance(resolved, MappingProxyType)
    assert set(resolved) == set(FIELDS)
    with pytest.raises(TypeError):
        resolved["title"] = "Nope"


def test_effective_resolution_refuses_an_undeclared_field():
    with pytest.raises(SharedMetadataError):
        effective_value(shared_with(), book(), "narrator")


def test_effective_resolution_refuses_the_wrong_argument_types():
    with pytest.raises(SharedMetadataError):
        effective_value("shared", book(), "title")
    with pytest.raises(BookContractError):
        effective_value(shared_with(), "book", "title")
    with pytest.raises(SharedMetadataError):
        effective_metadata(None, book())
    with pytest.raises(BookContractError):
        effective_metadata(shared_with(), None)


# --------------------------------------------------------------------------- #
# Preservation — the heart of Decision 20B
# --------------------------------------------------------------------------- #


def test_overriding_never_modifies_the_books_configuration():
    entry = book(title="Per Book")
    before = dict(entry.configuration)
    value = shared_with(title="Series Shared")
    assert effective_value(value, entry, "title") == "Series Shared"
    assert dict(entry.configuration) == before
    assert entry.configuration["title"] == "Per Book"


def test_the_full_decision_20b_lifecycle():
    """Section 15.2, step by step, exactly as the drop states it."""
    entry = book(title="Per Book")
    space = workspace(entry)

    # 1-3: shared blank, per-book effective.
    assert effective_value(space.shared, entry, "title") == "Per Book"
    assert disabled_fields(space.shared) == frozenset()

    # 4-6: shared populated, shared effective, control projected disabled.
    space = set_shared_metadata(space, shared_with(title="Series Shared")).workspace
    assert effective_value(space.shared, entry, "title") == "Series Shared"
    assert disabled_fields(space.shared) == frozenset({"title"})

    # 7: the raw per-book value is untouched, in the workspace and in the object.
    assert entry.configuration["title"] == "Per Book"
    assert space.book_for(entry.book_id).configuration["title"] == "Per Book"

    # 8-10: clearing restores exactly, and re-enables.
    space = set_shared_metadata(space, shared_with(title="")).workspace
    assert effective_value(space.shared, entry, "title") == "Per Book"
    assert disabled_fields(space.shared) == frozenset()


def test_clearing_with_whitespace_also_restores_the_per_book_value():
    entry = book(title="Per Book")
    space = set_shared_metadata(workspace(entry), shared_with(title="S")).workspace
    space = set_shared_metadata(space, shared_with(title="   ")).workspace
    assert effective_value(space.shared, entry, "title") == "Per Book"
    assert disabled_fields(space.shared) == frozenset()


def test_the_same_shared_value_applies_across_every_book():
    first, second = book(title="A Title"), book(title="B Title")
    value = shared_with(title="Series Shared")
    assert effective_value(value, first, "title") == "Series Shared"
    assert effective_value(value, second, "title") == "Series Shared"


def test_clearing_restores_each_books_own_value_with_no_cross_leakage():
    first, second = book(title="A Title"), book(title="B Title")
    cleared = shared_with(title="")
    assert effective_value(cleared, first, "title") == "A Title"
    assert effective_value(cleared, second, "title") == "B Title"


def test_one_shared_field_overrides_while_others_stay_per_book():
    """The drop's multi-book, multi-field example in full."""
    first = book(title="A Title", author="A Author")
    second = book(title="B Title", author="B Author")
    value = shared_with(author="Shared Author")
    assert dict(effective_metadata(value, first)) == {
        "title": "A Title", "author": "Shared Author", "series": BLANK}
    assert dict(effective_metadata(value, second)) == {
        "title": "B Title", "author": "Shared Author", "series": BLANK}


# --------------------------------------------------------------------------- #
# Disabled-field projection
# --------------------------------------------------------------------------- #


def test_the_projection_returns_exactly_the_populated_shared_fields():
    value = shared_with(title="T", author="   ", series="S")
    assert disabled_fields(value) == frozenset({"title", "series"})


def test_the_projection_excludes_blank_and_absent_fields():
    assert disabled_fields(SharedMetadata.for_fields(FIELDS)) == frozenset()
    assert disabled_fields(shared_with(title="", author="\t")) == frozenset()


def test_an_unknown_field_cannot_enter_the_projection():
    """Construction already refused it, so the projection cannot leak one."""
    with pytest.raises(SharedMetadataError):
        SharedMetadata(("title",), {"narrator": "X"})
    assert disabled_fields(shared_with(title="T")) <= set(FIELDS)


def test_the_projection_is_immutable_and_deterministic():
    value = shared_with(title="T", series="S")
    once, twice = disabled_fields(value), disabled_fields(value)
    assert once == twice
    assert isinstance(once, frozenset)


def test_the_projection_refuses_a_non_shared_metadata_argument():
    for wrong in (None, "shared", 3, {"title": "T"}):
        with pytest.raises(SharedMetadataError):
            disabled_fields(wrong)


def test_populated_fields_keeps_the_declared_order():
    value = SharedMetadata(("z", "a", "m"), {"z": "Z", "m": "M"})
    assert value.populated_fields == ("z", "m")


# --------------------------------------------------------------------------- #
# The workspace holds it once
# --------------------------------------------------------------------------- #


def test_shared_metadata_lives_on_the_workspace_and_not_on_a_book():
    stored = {entry.name for entry in dataclasses.fields(WorkspaceSnapshot)}
    assert "shared" in stored
    book_stored = {entry.name for entry in dataclasses.fields(BookJob)}
    assert book_stored == {"book_id", "configuration", "files"}
    assert "shared" not in book_stored


def test_a_workspace_defaults_to_declaring_nothing():
    entry = book()
    space = WorkspaceSnapshot(books=(entry,), current_book_id=entry.book_id)
    assert space.shared is NO_SHARED_METADATA


def test_a_workspace_refuses_a_shared_value_that_is_not_shared_metadata():
    entry = book()
    for wrong in (None, "shared", 3, {"title": "T"}):
        with pytest.raises(WorkspaceContractError):
            WorkspaceSnapshot(books=(entry,), current_book_id=entry.book_id,
                              shared=wrong)


def test_no_effective_value_is_stored_as_a_second_truth():
    """Effective values are projections; storing one is how two truths diverge."""
    for record in (BookJob, WorkspaceSnapshot):
        names = {entry.name for entry in dataclasses.fields(record)}
        assert not any("effective" in name for name in names), names


# --------------------------------------------------------------------------- #
# The update operation
# --------------------------------------------------------------------------- #


def test_setting_shared_metadata_changes_only_the_shared_value():
    first, second = book(title="A"), book(title="B")
    space = workspace(first, second, revision=Revision(4))
    result = set_shared_metadata(space, shared_with(title="S"))

    assert result.operation is WorkspaceOperation.SHARED_METADATA
    assert result.changed is True
    assert result.workspace.books == space.books, "same book objects"
    assert result.workspace.current_book_id == space.current_book_id
    assert result.revision == Revision(5), "exactly once"
    assert result.removed == ()


def test_the_operation_is_its_own_member():
    assert WorkspaceOperation.SHARED_METADATA.value == "shared_metadata"
    assert WorkspaceOperation.SHARED_METADATA not in (
        WorkspaceOperation.REPLACE, WorkspaceOperation.IMPORT)


def test_setting_the_same_value_is_a_no_op():
    space = workspace(revision=Revision(3))
    result = set_shared_metadata(space, space.shared)
    assert result.changed is False
    assert result.workspace is space
    assert result.revision == Revision(3)


def test_an_equal_but_distinct_value_is_also_a_no_op():
    space = workspace(shared=shared_with(title="S"))
    result = set_shared_metadata(space, shared_with(title="S"))
    assert result.changed is False
    assert result.workspace is space


def test_a_rejected_update_is_atomic_and_consumes_no_identity():
    maker = IdFactory("r-")
    space = workspace(book(title="A"), revision=Revision(2))
    before = (space.books, space.current_book_id, space.revision, space.shared)
    for wrong in (None, "shared", 3, {"title": "T"}):
        with pytest.raises(SharedMetadataError):
            set_shared_metadata(space, wrong)
    assert (space.books, space.current_book_id, space.revision, space.shared) == before
    assert new_book_id(maker) == "r-book-000001"


def test_updating_on_something_that_is_not_a_workspace_is_refused():
    for wrong in (None, "workspace", 3, book()):
        with pytest.raises(WorkspaceContractError):
            set_shared_metadata(wrong, shared_with(title="S"))


def test_the_declared_vocabulary_may_be_widened_by_an_update():
    space = workspace()
    wider = SharedMetadata(FIELDS + ("narrator",), {"narrator": "N"})
    result = set_shared_metadata(space, wider)
    assert result.changed is True
    assert result.workspace.shared.declares("narrator") is True


# --------------------------------------------------------------------------- #
# Preservation through every Phase 2 and Phase 3 operation
# --------------------------------------------------------------------------- #


def loaded_workspace() -> WorkspaceSnapshot:
    first, second, third = book(title="A"), book(title="B"), book(title="C")
    return workspace(first, second, third, shared=shared_with(author="Shared Author"))


@pytest.mark.parametrize("name", [
    "add", "duplicate", "remove", "previous", "next", "select", "replace", "import",
])
def test_every_workspace_operation_preserves_shared_metadata(name):
    """Nothing may silently discard what the user shared across books."""
    maker = IdFactory("p-")
    space = loaded_workspace()
    space = next_book(space).workspace  # so Previous is a real move too

    operations = {
        "add": lambda s: add_book(s, id_factory=maker),
        "duplicate": lambda s: duplicate_book(s, id_factory=maker),
        "remove": lambda s: remove_book(s, id_factory=maker),
        "previous": lambda s: previous_book(s),
        "next": lambda s: next_book(s),
        "select": lambda s: select_book(s, s.book_ids[0]),
        "replace": lambda s: replace_book(
            s, BookJob(book_id=s.current_book_id, configuration={"title": "New"})),
        "import": lambda s: replace_workspace_from_import(
            s, scanned("X/1.mp3", "Y/1.mp3"), id_factory=maker),
    }
    result = operations[name](space)
    assert result.changed is True, name
    assert result.workspace.shared == space.shared, name
    assert result.workspace.shared.raw("author") == "Shared Author", name


def test_an_import_does_not_erase_workspace_level_shared_metadata():
    """The approved contract does not say to clear it, so it is preserved."""
    space = loaded_workspace()
    result = replace_workspace_from_import(
        space, scanned("Book1/1.mp3", "Book2/1.mp3"), id_factory=IdFactory("i-"))
    assert result.workspace.count == 2
    assert result.workspace.shared == space.shared
    for entry in result.workspace.books:
        assert effective_value(result.workspace.shared, entry, "author") == "Shared Author"


def test_duplicate_carries_the_books_own_configuration_and_not_shared_state():
    """Decision 49A is unchanged: shared state stays at workspace level."""
    entry = book(title="Per Book")
    space = workspace(entry, shared=shared_with(author="Shared Author"))
    copy = duplicate_book(space, id_factory=IdFactory("d-")).workspace.current
    assert copy.configuration["title"] == "Per Book"
    assert "author" not in copy.configuration, "shared value was not copied into a book"


def test_navigation_alters_neither_raw_nor_effective_state():
    entry = book(title="Per Book")
    space = workspace(entry, book(title="Other"),
                      shared=shared_with(author="Shared Author"))
    away = next_book(space).workspace
    back = previous_book(away).workspace
    assert back.shared == space.shared
    assert back.book_for(entry.book_id).configuration["title"] == "Per Book"
    assert effective_value(back.shared, entry, "title") == "Per Book"
    assert effective_value(back.shared, entry, "author") == "Shared Author"


def test_removing_the_sole_meaningful_book_keeps_the_shared_vocabulary():
    entry = book(title="Only")
    space = workspace(entry, shared=shared_with(author="Shared Author"))
    result = remove_book(space, id_factory=IdFactory("r-"))
    assert result.changed is True
    assert result.workspace.shared == space.shared
    assert result.workspace.current.is_empty is True
