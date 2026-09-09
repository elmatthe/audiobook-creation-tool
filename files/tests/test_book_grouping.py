"""Decision 12A — folder to book construction, v0.6.3 Drop 1 (Plan 6), Phase 3.

Every directory that **directly contains** imported compatible files is one book.
Distinct directories are never combined, group order follows first appearance, and
files inside each book are natural-ordered whichever import entry path produced the
snapshot.

**Nothing here touches a disk.** Every fixture path is absolute and deliberately
non-existent, exactly as ``test_importing`` builds them, so a contract that quietly
started calling ``exists()`` or ``stat()`` would not merely be impure — it would
behave differently, and these tests would notice.

The importer is not re-tested here. ``scan_roots``, ``validate_direct_files``,
occurrence identity and commits stay Plan 3's; Plan 6 consumes one already-committed
``ImportedFileSnapshot`` and projects it.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path, PurePath

import pytest

from shared.book_workspace import (
    BookContractError,
    BookJob,
    NO_FILES,
    WorkspaceContractError,
    WorkspaceOperation,
    WorkspaceSnapshot,
    book_groups,
    books_from_import,
    has_meaningful_work,
    new_book_id,
    replace_workspace_from_import,
)
from shared.importing import (
    INITIAL_REVISION,
    IdFactory,
    ImportedFile,
    ImportedFileSnapshot,
    ImportRoot,
    Revision,
    RootKind,
)

from test_importing import OTHER_ROOT, ROOT_PATH, direct_root, folder_root


# --------------------------------------------------------------------------- #
# Helpers — the same builders the Plan 3 suites already use
# --------------------------------------------------------------------------- #


def entry(occurrence_id: str, relative: str, root: ImportRoot | None = None,
          identity: str | None = None) -> ImportedFile:
    """One imported occurrence at ``<root>/<relative>``."""
    source = folder_root() if root is None else root
    base = source.path if source.path is not None else ROOT_PATH
    return ImportedFile(
        occurrence_id=occurrence_id,
        path=base / relative,
        source_root=source,
        relative_path=PurePath(relative) if source.mirrors else None,
        supported_type_id="mp3",
        identity=identity or f"id-{occurrence_id}",
    )


def snapshot(*entries: ImportedFile, revision: Revision | None = None
             ) -> ImportedFileSnapshot:
    """A committed imported list. Revision 1 is what one commit would leave."""
    return ImportedFileSnapshot(
        revision if revision is not None else Revision(1), entries)


def scanned(*relatives: str, root: ImportRoot | None = None) -> ImportedFileSnapshot:
    """A snapshot shaped like a folder scan: occurrence ids in traversal order."""
    return snapshot(*(entry(f"occ-{index}", relative, root)
                      for index, relative in enumerate(relatives, start=1)))


def picked(*relatives: str) -> ImportedFileSnapshot:
    """A snapshot shaped like Add Files.

    ``validate_direct_files`` deliberately preserves the order the user clicked in
    and sorts nothing, so this is how an unsorted list genuinely reaches Plan 6.
    """
    root = direct_root()
    return snapshot(*(
        ImportedFile(
            occurrence_id=f"occ-{index}",
            path=ROOT_PATH / relative,
            source_root=root,
            relative_path=None,
            supported_type_id="mp3",
            identity=f"id-{index}",
        )
        for index, relative in enumerate(relatives, start=1)
    ))


def names(entries) -> list[str]:
    return [item.name for item in entries]


def directories(groups) -> list[str]:
    return [directory.name for directory, _entries in groups]


# --------------------------------------------------------------------------- #
# Group identity
# --------------------------------------------------------------------------- #


def test_one_containing_directory_becomes_one_book():
    groups = book_groups(scanned("Book/1.mp3", "Book/2.mp3"))
    assert len(groups) == 1
    directory, entries = groups[0]
    assert directory == ROOT_PATH / "Book"
    assert names(entries) == ["1.mp3", "2.mp3"]


def test_several_containing_directories_become_several_books():
    groups = book_groups(scanned("A/1.mp3", "B/1.mp3", "C/1.mp3"))
    assert len(groups) == 3
    assert directories(groups) == ["A", "B", "C"]


def test_one_selected_root_holding_many_book_folders_does_not_collapse():
    """The defect this exists to prevent: twelve audiobooks, twelve books."""
    relatives = [f"Book {number}/01.mp3" for number in range(1, 13)]
    relatives += [f"Book {number}/02.mp3" for number in range(1, 13)]
    groups = book_groups(scanned(*relatives))
    assert len(groups) == 12, "one selected folder, twelve directly-containing dirs"
    for _directory, entries in groups:
        assert len(entries) == 2


def test_a_deeper_nesting_still_groups_by_the_direct_parent_only():
    groups = book_groups(scanned(
        "Series/Book1/1.mp3", "Series/Book1/2.mp3", "Series/Book2/1.mp3"))
    assert directories(groups) == ["Book1", "Book2"]
    assert groups[0][0] == ROOT_PATH / "Series" / "Book1"


def test_the_same_basename_under_different_directories_stays_two_books():
    """``…/SeriesA/Book1`` and ``…/Archive/Book1`` are not one book."""
    groups = book_groups(scanned("SeriesA/Book1/1.mp3", "Archive/Book1/1.mp3"))
    assert len(groups) == 2
    assert directories(groups) == ["Book1", "Book1"], "basenames genuinely collide"
    assert groups[0][0] != groups[1][0], "full paths do not"
    assert {directory for directory, _ in groups} == {
        ROOT_PATH / "SeriesA" / "Book1", ROOT_PATH / "Archive" / "Book1"}


def test_files_from_one_parent_never_leak_into_another_group():
    groups = book_groups(scanned(
        "A/1.mp3", "B/1.mp3", "A/2.mp3", "B/2.mp3", "A/3.mp3"))
    grouped = {directory.name: names(entries) for directory, entries in groups}
    assert grouped == {"A": ["1.mp3", "2.mp3", "3.mp3"], "B": ["1.mp3", "2.mp3"]}


def test_two_roots_with_a_same_named_child_stay_distinct():
    other = folder_root(order=1, path=OTHER_ROOT, root_id="root-2")
    groups = book_groups(snapshot(
        entry("occ-1", "Book/1.mp3"),
        entry("occ-2", "Book/1.mp3", other, identity="id-2"),
    ))
    assert len(groups) == 2
    assert {directory for directory, _ in groups} == {
        ROOT_PATH / "Book", OTHER_ROOT / "Book"}


def test_a_directory_with_no_imported_files_creates_no_book():
    """Only what the importer actually committed can become a book."""
    groups = book_groups(scanned("A/1.mp3"))
    assert directories(groups) == ["A"]
    assert all(entries for _directory, entries in groups)


# --------------------------------------------------------------------------- #
# Group order
# --------------------------------------------------------------------------- #


def test_group_order_follows_first_appearance_not_the_alphabet():
    """The drop's worked example, exactly."""
    groups = book_groups(scanned(
        "B/1.mp3", "A/2.mp3", "B/2.mp3", "A/1.mp3", "C/1.mp3"))
    assert directories(groups) == ["B", "A", "C"]
    grouped = {directory.name: names(entries) for directory, entries in groups}
    assert grouped == {"B": ["1.mp3", "2.mp3"],
                       "A": ["1.mp3", "2.mp3"],
                       "C": ["1.mp3"]}


def test_book_order_is_not_globally_sorted():
    groups = book_groups(scanned("Z/1.mp3", "M/1.mp3", "A/1.mp3"))
    assert directories(groups) == ["Z", "M", "A"]
    assert directories(groups) != sorted(directories(groups))


def test_multiple_roots_retain_their_first_appearance_order():
    second = folder_root(order=1, path=OTHER_ROOT, root_id="root-2")
    groups = book_groups(snapshot(
        entry("occ-1", "Second/1.mp3", second, identity="id-1"),
        entry("occ-2", "First/1.mp3"),
        entry("occ-3", "Second/2.mp3", second, identity="id-3"),
    ))
    assert [directory for directory, _ in groups] == [
        OTHER_ROOT / "Second", ROOT_PATH / "First"]


def test_a_later_file_never_moves_its_group_forward():
    groups = book_groups(scanned("A/1.mp3", "B/1.mp3", "A/2.mp3"))
    assert directories(groups) == ["A", "B"]


# --------------------------------------------------------------------------- #
# Natural file order — both entry paths
# --------------------------------------------------------------------------- #


def test_files_are_natural_ordered_in_a_folder_scan_shaped_snapshot():
    groups = book_groups(scanned("Book/1.mp3", "Book/2.mp3", "Book/10.mp3"))
    assert names(groups[0][1]) == ["1.mp3", "2.mp3", "10.mp3"]


def test_files_are_natural_ordered_in_a_direct_file_shaped_snapshot():
    """``validate_direct_files`` sorts nothing, so this arrives 10, 2, 1."""
    incoming = picked("Book/10.mp3", "Book/2.mp3", "Book/1.mp3")
    assert names(incoming.files) == ["10.mp3", "2.mp3", "1.mp3"], "unsorted input"
    groups = book_groups(incoming)
    assert names(groups[0][1]) == ["1.mp3", "2.mp3", "10.mp3"]


def test_natural_order_is_applied_per_group_not_across_groups():
    groups = book_groups(picked(
        "B/10.mp3", "A/10.mp3", "B/2.mp3", "A/2.mp3", "B/1.mp3", "A/1.mp3"))
    assert directories(groups) == ["B", "A"]
    for _directory, entries in groups:
        assert names(entries) == ["1.mp3", "2.mp3", "10.mp3"]


def test_natural_order_beats_lexical_order_at_every_width():
    incoming = picked(*(f"Book/{number}.mp3" for number in (100, 20, 3, 1, 10, 2)))
    groups = book_groups(incoming)
    assert names(groups[0][1]) == [
        "1.mp3", "2.mp3", "3.mp3", "10.mp3", "20.mp3", "100.mp3"]


def test_the_sort_reuses_the_importers_own_key():
    """No second natural-sort implementation: the importer's key, on its own value."""
    from shared import book_workspace as module
    import inspect
    source = inspect.getsource(module.book_groups)
    assert "natural_key" in source
    assert "item.name" in source, "the same value scan_roots sorts on"


# --------------------------------------------------------------------------- #
# Input preservation
# --------------------------------------------------------------------------- #


def test_the_exact_imported_file_objects_are_carried_through():
    first, second = entry("occ-1", "Book/1.mp3"), entry("occ-2", "Book/2.mp3")
    groups = book_groups(snapshot(first, second))
    carried = groups[0][1]
    assert carried[0] is first and carried[1] is second, "same objects, not rebuilt"


def test_occurrence_ids_are_preserved_and_never_reminted():
    incoming = picked("B/2.mp3", "A/1.mp3", "B/1.mp3")
    original = set(incoming.occurrence_ids)
    groups = book_groups(incoming)
    produced = {item.occurrence_id for _d, entries in groups for item in entries}
    assert produced == original


def test_provenance_survives_the_projection():
    source = entry("occ-1", "Series/Book/03.mp3")
    groups = book_groups(snapshot(source))
    carried = groups[0][1][0]
    assert carried.supported_type_id == "mp3"
    assert carried.identity == source.identity
    assert carried.source_root is source.source_root
    assert carried.relative_path == source.relative_path


def test_the_source_snapshot_is_not_mutated():
    incoming = picked("Book/10.mp3", "Book/1.mp3")
    before = incoming.files
    book_groups(incoming)
    assert incoming.files == before, "still in the user's original order"


def test_grouping_refuses_anything_that_is_not_a_snapshot():
    for wrong in (None, [], (), "snapshot", 3, NO_FILES.files, iter(())):
        with pytest.raises(BookContractError):
            book_groups(wrong)


def test_an_empty_snapshot_groups_into_nothing():
    assert book_groups(NO_FILES) == ()
    assert book_groups(ImportedFileSnapshot()) == ()


# --------------------------------------------------------------------------- #
# Book construction
# --------------------------------------------------------------------------- #


def test_each_group_becomes_one_book_with_a_fresh_unique_identity():
    books = books_from_import(scanned("A/1.mp3", "B/1.mp3", "C/1.mp3"),
                              id_factory=IdFactory("g-"))
    assert len(books) == 3
    assert [b.book_id for b in books] == [
        "g-book-000001", "g-book-000002", "g-book-000003"]
    assert len({b.book_id for b in books}) == 3


def test_every_constructed_book_starts_with_a_pristine_configuration():
    """Populating configuration is Phase 4's; nothing is anticipated here."""
    books = books_from_import(scanned("A/1.mp3", "B/1.mp3"),
                              id_factory=IdFactory("g-"))
    for entry_book in books:
        assert dict(entry_book.configuration) == {}
        assert entry_book.configuration_keys == ()


def test_a_constructed_book_holds_only_its_own_group():
    books = books_from_import(scanned("A/1.mp3", "B/1.mp3", "A/2.mp3"),
                              id_factory=IdFactory("g-"))
    assert [b.file_count for b in books] == [2, 1]
    assert names(books[0].files.files) == ["1.mp3", "2.mp3"]
    assert names(books[1].files.files) == ["1.mp3"]
    assert all(item.path.parent == ROOT_PATH / "A" for item in books[0].files.files)
    assert all(item.path.parent == ROOT_PATH / "B" for item in books[1].files.files)


def test_a_constructed_book_is_not_empty_and_holds_meaningful_work():
    books = books_from_import(scanned("A/1.mp3"), id_factory=IdFactory("g-"))
    assert books[0].is_empty is False
    assert has_meaningful_work(books[0]) is True


def test_each_group_snapshot_keeps_the_source_revision():
    """A revision stamps which manager version a list came from; that is provenance.

    Resetting to ``INITIAL_REVISION`` would be worse than arbitrary: that is what
    :data:`NO_FILES` uses to mean *nothing was ever imported*, so an imported book
    would become indistinguishable from a pristine one.
    """
    incoming = scanned("A/1.mp3", "B/1.mp3")
    assert incoming.revision == Revision(1)
    books = books_from_import(incoming, id_factory=IdFactory("g-"))
    for entry_book in books:
        assert entry_book.files.revision == incoming.revision
        assert entry_book.files.revision != INITIAL_REVISION


def test_an_imported_book_is_distinguishable_from_a_pristine_one():
    imported_book = books_from_import(scanned("A/1.mp3"),
                                      id_factory=IdFactory("g-"))[0]
    pristine = BookJob(book_id=new_book_id(IdFactory("p-")))
    assert pristine.files.revision == INITIAL_REVISION
    assert imported_book.files.revision != pristine.files.revision


def test_construction_from_an_empty_snapshot_makes_no_books():
    maker = IdFactory("g-")
    assert books_from_import(NO_FILES, id_factory=maker) == ()
    assert new_book_id(maker) == "g-book-000001", "no identity was consumed"


def test_construction_validates_before_minting_any_identity():
    maker = IdFactory("g-")
    with pytest.raises(BookContractError):
        books_from_import("not a snapshot", id_factory=maker)
    assert new_book_id(maker) == "g-book-000001", "nothing was minted"


# --------------------------------------------------------------------------- #
# Atomic workspace replacement
# --------------------------------------------------------------------------- #


def seeded(count: int = 1, meaningful: bool = False) -> WorkspaceSnapshot:
    maker = IdFactory("seed-")
    books = tuple(
        BookJob(book_id=new_book_id(maker),
                configuration={"title": "Kept"} if meaningful else {})
        for _ in range(count))
    return WorkspaceSnapshot(books=books, current_book_id=books[0].book_id)


def test_an_import_replaces_the_whole_workspace_in_one_operation():
    space = seeded(3, meaningful=True)
    result = replace_workspace_from_import(
        space, scanned("A/1.mp3", "B/1.mp3"), id_factory=IdFactory("i-"))

    assert result.operation is WorkspaceOperation.IMPORT
    assert result.changed is True
    assert result.workspace.count == 2
    assert result.removed == space.books, "every old book is gone"


def test_the_import_operation_is_its_own_member_not_an_overloaded_replace():
    """``REPLACE`` swaps one book; this replaces every book and the selection."""
    assert WorkspaceOperation.IMPORT is not WorkspaceOperation.REPLACE
    assert WorkspaceOperation.IMPORT.value == "import"


def test_the_selection_lands_on_the_first_new_book():
    result = replace_workspace_from_import(
        seeded(), scanned("B/1.mp3", "A/1.mp3"), id_factory=IdFactory("i-"))
    assert result.workspace.current_book_id == result.workspace.books[0].book_id
    assert result.workspace.current_position == 1
    assert names(result.workspace.current.files.files) == ["1.mp3"]
    assert result.workspace.books[0].files.files[0].path.parent == ROOT_PATH / "B"


def test_the_revision_advances_once_for_the_replacement_not_once_per_book():
    space = seeded(1, meaningful=True)
    assert space.revision == INITIAL_REVISION
    result = replace_workspace_from_import(
        space, scanned("A/1.mp3", "B/1.mp3", "C/1.mp3", "D/1.mp3"),
        id_factory=IdFactory("i-"))
    assert result.workspace.count == 4
    assert result.revision == Revision(1), "one replacement, one revision"


def test_the_old_workspace_is_not_mutated():
    space = seeded(2, meaningful=True)
    before = (space.books, space.current_book_id, space.revision)
    replace_workspace_from_import(space, scanned("A/1.mp3"),
                                  id_factory=IdFactory("i-"))
    assert (space.books, space.current_book_id, space.revision) == before


def test_book_x_of_y_is_valid_after_an_import():
    for count in (1, 2, 5):
        relatives = [f"Book{index}/1.mp3" for index in range(count)]
        result = replace_workspace_from_import(
            seeded(), scanned(*relatives), id_factory=IdFactory("i-"))
        space = result.workspace
        assert space.count == count
        assert 1 <= space.current_position <= space.count


def test_an_empty_import_leaves_exactly_one_pristine_book():
    """Never a zero-book workspace, even for an import that found nothing."""
    space = seeded(3, meaningful=True)
    result = replace_workspace_from_import(space, NO_FILES,
                                           id_factory=IdFactory("i-"))
    assert result.changed is True
    assert result.workspace.count == 1
    only = result.workspace.current
    assert only.is_empty is True
    assert dict(only.configuration) == {}
    assert has_meaningful_work(only) is False
    assert result.removed == space.books


def test_an_empty_import_onto_an_already_pristine_workspace_is_a_no_op():
    """The accepted Phase 2 disposition, applied unchanged rather than re-decided."""
    maker = IdFactory("i-")
    space = seeded()
    result = replace_workspace_from_import(space, NO_FILES, id_factory=maker)
    assert result.changed is False
    assert result.workspace is space
    assert result.revision == space.revision
    assert result.removed == ()
    assert new_book_id(maker) == "i-book-000001", "no identity was consumed"


def test_a_rejected_import_leaves_the_workspace_untouched():
    maker = IdFactory("i-")
    space = seeded(2, meaningful=True)
    before = (space.books, space.current_book_id, space.revision)
    for wrong in (None, "snapshot", 3, []):
        with pytest.raises(BookContractError):
            replace_workspace_from_import(space, wrong, id_factory=maker)
    assert (space.books, space.current_book_id, space.revision) == before
    assert new_book_id(maker) == "i-book-000001", "no identity was consumed"


def test_an_import_onto_something_that_is_not_a_workspace_is_rejected():
    maker = IdFactory("i-")
    for wrong in (None, "workspace", 3, BookJob(book_id="x-1")):
        with pytest.raises(WorkspaceContractError):
            replace_workspace_from_import(wrong, scanned("A/1.mp3"),
                                          id_factory=maker)
    assert new_book_id(maker) == "i-book-000001", "workspace checked before minting"


def test_the_imported_books_carry_the_grouping_through_to_the_workspace():
    result = replace_workspace_from_import(
        seeded(), scanned("B/1.mp3", "A/2.mp3", "B/10.mp3", "A/1.mp3"),
        id_factory=IdFactory("i-"))
    space = result.workspace
    assert space.count == 2
    assert names(space.books[0].files.files) == ["1.mp3", "10.mp3"]
    assert names(space.books[1].files.files) == ["1.mp3", "2.mp3"]
    assert len(set(space.book_ids)) == 2


# --------------------------------------------------------------------------- #
# Purity
# --------------------------------------------------------------------------- #


def test_grouping_never_consults_the_filesystem():
    """Every fixture path is absolute and does not exist; this must not matter."""
    incoming = scanned("Book/1.mp3", "Book/2.mp3")
    for item in incoming.files:
        assert not item.path.exists(), "the fixture really is not on disk"
    groups = book_groups(incoming)
    assert len(groups) == 1
    books = books_from_import(incoming, id_factory=IdFactory("g-"))
    assert books[0].file_count == 2


def test_grouping_creates_no_directory_and_plans_no_output(tmp_path):
    before = sorted(tmp_path.iterdir())
    replace_workspace_from_import(seeded(), scanned("A/1.mp3"),
                                  id_factory=IdFactory("i-"))
    assert sorted(tmp_path.iterdir()) == before


def test_the_result_holds_no_output_path_of_any_kind():
    result = replace_workspace_from_import(
        seeded(), scanned("A/1.mp3"), id_factory=IdFactory("i-"))
    stored = {field.name for field in dataclasses.fields(BookJob)}
    assert stored == {"book_id", "configuration", "files"}
    assert not hasattr(result.workspace.current, "destination")
