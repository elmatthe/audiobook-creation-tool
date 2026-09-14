"""Shared-value semantics of the M4B Metadata Editor — re-pointed at v0.6.4 Phase 10.

Drop 2 proved the old batch-global panel's ``_shared_tags`` detection: a value
common to every file was pre-filled, a differing one showed "(varies)", an
album-implied series and the Series Part were never treated as shared, an
unreadable file was excluded rather than fatal, and values compared after
``strip()``. That panel is gone; the Editor is one page per file over the
Phase 7 model, and the plan (section 6.6) deliberately inverts the first rule:
**Shared starts blank even when every source agrees**, so source coincidence
can never become an explicit global override. Every other invariant survives,
and this file proves each one where it lives now — display-free, no Tk, no
FFmpeg: the readers are injected with canned tags.
"""

from __future__ import annotations

from pathlib import Path, PurePath

import pytest

from shared.book_workspace import SharedMetadata, set_shared_metadata
from shared.importing import (
    IdFactory, ImportRoot, ImportedFile, ImportedFileSnapshot, Revision,
)

from mp3_tools import m4b_metadata_workflow as wf
from mp3_tools.m4b_metadata_workflow import ObservationStore

_IDS = IdFactory("eds-")


def imported(name: str) -> ImportedFile:
    root = ImportRoot("r", Path("C:/canned"), 0)
    occurrence = _IDS.next_id("occurrence")
    return ImportedFile(occurrence, Path("C:/canned") / name, root, PurePath(name),
                        wf.EDITOR_TYPE.type_id, f"id-{occurrence}")


def workspace_of(tags_by_name: dict, chapters=()):
    """Canned sources become Books through the real projection; no file is read."""
    entries = tuple(imported(name) for name in tags_by_name)
    by_path = {entry.path: tags_by_name[entry.path.name] for entry in entries}

    def reader(path):
        found = by_path[Path(path)]
        if found is None:
            raise OSError("cannot read this one")
        return dict(found)

    result = wf.import_folder(wf.new_workspace(id_factory=_IDS),
                              ImportedFileSnapshot(Revision(1), entries),
                              id_factory=_IDS, store=ObservationStore(),
                              reader=reader, chapters=lambda _p: list(chapters))
    return result.mutation.workspace, result.store


def test_shared_starts_blank_even_when_every_source_agrees():
    space, store = workspace_of({
        "a.m4b": {"artist": "X", "title": "Book 1"},
        "b.m4b": {"artist": "X", "title": "Book 2"},
        "c.m4b": {"artist": "X", "title": "Book 3"},
    })
    assert space.shared.values == {}
    assert wf.shared_intent(space.shared) == {}
    # Each page still shows its own source; nothing was pre-populated into Shared.
    assert [wf.page_values(space.shared, book, store)["artist"] for book in space.books] == [
        "X", "X", "X"]
    assert [wf.page_values(space.shared, book, store)["title"] for book in space.books] == [
        "Book 1", "Book 2", "Book 3"]
    assert all(wf.explicit_edits(space.shared, book, store) == {} for book in space.books)


def test_a_populated_shared_value_is_an_explicit_override_for_every_book():
    space, store = workspace_of({
        "a.m4b": {"artist": "X", "title": "Book 1"},
        "b.m4b": {"title": "Book 2"},          # no artist on this one
    })
    shared = SharedMetadata(fields=wf.SHARED_FIELDS, values={"artist": "Y"})
    space = set_shared_metadata(space, shared).workspace
    assert wf.shared_intent(space.shared) == {"artist": "Y"}
    for book in space.books:
        assert wf.edit_intent(space.shared, book, store, "artist") == "Y"
    cleared = set_shared_metadata(space, SharedMetadata(fields=wf.SHARED_FIELDS,
                                                        values={"artist": ""})).workspace
    assert wf.shared_intent(cleared.shared) == {}
    assert [wf.edit_intent(cleared.shared, book, store, "artist") for book in cleared.books] == [
        None, None]


def test_album_implied_series_is_readback_only_and_never_written_back():
    space, store = workspace_of({
        "a.m4b": {"album": "S", "series": "S", "series_source": "album-implied"},
        "b.m4b": {"album": "S", "series": "S", "series_source": "album-implied"},
    })
    for book in space.books:
        seen = store.for_book(book)
        assert seen.series_name_implied
        assert wf.prefill_values(seen)["series"] == ""
        assert wf.page_values(space.shared, book, store)["series"] == ""
        assert wf.explicit_edits(space.shared, book, store) == {}
        assert "album-implied" in wf.series_readback(seen), "shown as provenance, not as a tag"


def test_series_part_is_display_only():
    space, store = workspace_of({
        "a.m4b": {"series_part": "1", "series_part_source": "freeform:com.apple.iTunes"},
        "b.m4b": {"series_part": "1", "series_part_source": "freeform:com.apple.iTunes"},
    })
    assert "series_part" not in wf.SHARED_FIELDS and "series_part" not in wf.TEXT_FIELDS
    for book in space.books:
        assert store.for_book(book).series_part == "1"
        assert "series_part" not in wf.prefill_values(store.for_book(book))
    with pytest.raises(wf.EditorContractError):
        wf.set_book_field(space, "series_part", "2")


def test_an_unreadable_file_is_a_book_beside_the_readable_ones_not_fatal():
    space, store = workspace_of({
        "a.m4b": {"artist": "X"},
        "broken.m4b": None,
        "c.m4b": {"artist": "X"},
    })
    assert space.count == 3
    readable = [store.for_book(book).readable for book in space.books]
    assert readable == [True, False, True]
    broken = space.books[1]
    assert store.for_book(broken).error
    assert wf.prefill_values(store.for_book(broken)) == {name: "" for name in wf.TEXT_FIELDS}
    assert "unavailable" in wf.series_readback(store.for_book(broken))


def test_an_empty_workspace_is_one_pristine_book_with_nothing_to_show():
    space = wf.new_workspace(id_factory=_IDS)
    store = ObservationStore()
    assert space.count == 1 and space.current.is_empty
    assert store.for_book(space.current) is None
    assert wf.prefill_values(None) == {name: "" for name in wf.TEXT_FIELDS}
    assert wf.explicit_edits(space.shared, space.current, store) == {}


def test_values_are_compared_after_strip():
    space, store = workspace_of({"a.m4b": {"artist": "X"}})
    typed = wf.set_book_field(space, "artist", " X ").workspace
    assert wf.edit_intent(typed.shared, typed.current, store, "artist") is None
    changed = wf.set_book_field(space, "artist", " Y ").workspace
    assert wf.edit_intent(changed.shared, changed.current, store, "artist") == "Y"
