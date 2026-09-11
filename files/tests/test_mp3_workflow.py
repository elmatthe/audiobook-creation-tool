"""The MP3 workflow model — v0.6.3 focused MP3 plan, Phase 3.

``mp3_tools/mp3_workflow.py`` is the MP3-specific **non-UI** layer: the supported-type
catalog, folder-to-Book and Add-Files projection over the Plan 6 workspace, read-only
source ID3 observation, majority / mixed calculation, per-occurrence default titles,
Chapter Titles resolution, and the signed-Time and Start # parsers.

What it is not, and what this suite proves it is not: no Tk, no FFmpeg, no output
planning, no artwork embedding, no second importer, no second workspace, no hidden
source fallback at output time.

Determinism
-----------
Every test that observes "source tags" injects a reader over test-owned values. The
one real-mutagen test writes ID3 frames onto a stub file under ``tmp_path`` with
mutagen itself, so it needs no FFmpeg and no real audio.
"""

from __future__ import annotations

import ast
import math
import os
from pathlib import Path, PurePath

import pytest

from shared import book_workspace
from shared.book_workspace import (
    BookJob,
    SharedMetadata,
    WorkspaceSnapshot,
    duplicate_book,
    effective_value,
    has_meaningful_work,
    next_book,
    set_shared_metadata,
)
from shared.importing import (
    IdFactory,
    ImportedFile,
    ImportedFileSnapshot,
    ImportRoot,
    Revision,
    SupportedTypeCatalog,
)

from mp3_tools import mp3_workflow as wf
from mp3_tools.mp3_workflow import (
    BookSourceSummary,
    Consensus,
    MP3ContractError,
    MP3ValueError,
    ObservationStore,
    SourceTags,
    TrackObservation,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIVERSAL = REPO_ROOT / "scripts" / "Universal"
MODULE = UNIVERSAL / "mp3_tools" / "mp3_workflow.py"

ROOT = Path(os.path.abspath(os.sep + "act-mp3-fixture-root"))
ROOTED = ImportRoot("root-1", ROOT, 0)

_IDS = IdFactory("occ-")
_BOOKS = IdFactory("book-")


# --------------------------------------------------------------------------- #
# Fixtures and helpers — test-owned values over paths that are never opened
# --------------------------------------------------------------------------- #


def track(name: str, folder: str = "Book A") -> ImportedFile:
    occurrence = _IDS.next_id("occurrence")
    return ImportedFile(occurrence, ROOT / folder / name, ROOTED,
                        PurePath(folder) / name, "mp3", f"id-{occurrence}")


def snapshot(*entries: ImportedFile) -> ImportedFileSnapshot:
    return ImportedFileSnapshot(Revision(1), tuple(entries))


def empty_workspace() -> WorkspaceSnapshot:
    return wf.new_workspace(id_factory=_BOOKS)


def workspace_with(*entries: ImportedFile, **configuration) -> WorkspaceSnapshot:
    book = BookJob(book_id=book_workspace.new_book_id(_BOOKS),
                   configuration=configuration, files=snapshot(*entries))
    return WorkspaceSnapshot(books=(book,), current_book_id=book.book_id,
                             shared=wf.new_shared_metadata())


class Reader:
    """A deterministic stand-in for the ID3 reader: path name -> tags."""

    def __init__(self, **by_name: SourceTags) -> None:
        self.by_name = by_name
        self.asked: list[Path] = []

    def __call__(self, path: Path) -> SourceTags:
        self.asked.append(path)
        return self.by_name.get(path.name, SourceTags())


def tags(title="", artist="", album_artist="", album="") -> SourceTags:
    return SourceTags(title=title, artist=artist, album_artist=album_artist,
                     album=album)


# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #


def test_the_supported_type_catalog_is_mp3_only():
    assert isinstance(wf.MP3_CATALOG, SupportedTypeCatalog)
    assert wf.MP3_CATALOG.type_ids == ("mp3",)
    assert wf.MP3_CATALOG.extensions == (".mp3",)
    assert wf.MP3_CATALOG.types[0].matches("Chapter.MP3")
    assert not wf.MP3_CATALOG.types[0].matches("book.m4b")


def test_the_shared_field_set_is_exactly_the_five_of_the_plan():
    assert wf.SHARED_FIELDS == ("artist", "album_artist", "album", "time_delta",
                                "artwork")
    assert dict(wf.FIELD_LABELS) == {
        "artist": "Artist / Author",
        "album_artist": "Album Artist / Author",
        "album": "Album",
        "time_delta": "Add/Remove Time at End of Each Track (seconds)",
        "artwork": "Book Artwork",
    }
    assert wf.BOOK_ONLY_FIELDS == ("auto_number", "start_number", "chapter_titles")
    for absent in ("title", "chapter_titles", "start_number", "narrator", "year",
                   "genre", "composer", "comment"):
        assert absent not in wf.SHARED_FIELDS


def test_a_new_workspace_is_one_pristine_book_with_the_shared_vocabulary():
    space = empty_workspace()
    assert space.count == 1
    assert space.current_position == 1
    assert not has_meaningful_work(space.current)
    assert space.shared.fields == wf.SHARED_FIELDS
    assert wf.auto_number_enabled(space.current) is True, "enabled, stored nowhere"
    assert wf.start_number_text(space.current) == ""
    assert wf.chapter_titles_text(space.current) == ""


def test_the_scalar_fields_are_the_three_source_observed_ones():
    assert wf.SCALAR_FIELDS == ("artist", "album_artist", "album")


# --------------------------------------------------------------------------- #
# Source observation: read-only, injected, and per occurrence
# --------------------------------------------------------------------------- #


def test_observation_captures_tags_and_a_default_title_per_occurrence():
    a = track("01 Intro.mp3")
    b = track("02 Chapter 741_ Home Again.mp3")
    reader = Reader(**{"01 Intro.mp3": tags(title="Introduction", artist="X")})
    observed = wf.observe_files((a, b), reader=reader)
    assert [entry.occurrence_id for entry in observed] == [a.occurrence_id,
                                                           b.occurrence_id]
    assert observed[0].tags == tags(title="Introduction", artist="X")
    assert observed[0].default_title == "Introduction", "usable ID3 title wins"
    assert observed[1].tags == SourceTags()
    assert observed[1].default_title == "Chapter 741: Home Again", "filename fallback"
    assert reader.asked == [a.path, b.path], "each occurrence read exactly once"


def test_a_blank_or_whitespace_id3_title_falls_back_to_the_filename():
    entry = track("03 - The Road.mp3")
    for blank in ("", "   ", "\t"):
        observed = wf.observe_files((entry,), reader=Reader(**{entry.name: tags(title=blank)}))
        assert observed[0].default_title == "The Road"


def test_a_reader_failure_yields_blank_tags_rather_than_a_failed_import():
    entry = track("04.mp3")

    def broken(path):
        raise OSError("unreadable")

    observed = wf.observe_files((entry,), reader=broken)
    assert observed[0].tags == SourceTags()
    assert observed[0].default_title == "04"


@pytest.mark.parametrize("filename,expected", [
    ("02 Chapter 741_ Home Again.mp3", "Chapter 741: Home Again"),
    ("01 Intro.mp3", "Intro"),
    ("01-Intro.mp3", "Intro"),
    ("01. Intro.mp3", "Intro"),
    ("01_Intro.mp3", "Intro"),
    ("001 - Chapter 1.mp3", "Chapter 1"),
    ("Chapter 12 The Storm.mp3", "Chapter 12 The Storm"),
    ("The Road_ Part 2.mp3", "The Road: Part 2"),
    ("Home_Again.mp3", "Home Again"),
    ("  Double   Space .mp3", "Double Space"),
    ("07.mp3", "07"),
    ("1984 Orwell.mp3", "1984 Orwell"),
    ("Track.MP3", "Track"),
])
def test_filename_titles_are_cleaned_deterministically(filename, expected):
    assert wf.title_from_filename(filename) == expected


def test_the_default_title_never_carries_the_filename_number_into_the_title():
    assert wf.default_title("", "17 Chapter Seventeen.mp3") == "Chapter Seventeen"
    assert wf.default_title("Chapter 17", "17 Chapter Seventeen.mp3") == "Chapter 17"
    assert wf.default_title("  spaced   out  ", "x.mp3") == "spaced out"


# --------------------------------------------------------------------------- #
# Majority and mixed
# --------------------------------------------------------------------------- #


def test_agreeing_values_are_not_mixed():
    result = wf.consensus(["Frank Herbert", "Frank Herbert", "Frank Herbert"])
    assert result == Consensus(value="Frank Herbert", mixed=False, distinct=1)


def test_cosmetic_differences_do_not_count_as_disagreement():
    result = wf.consensus(["Frank Herbert", " frank  herbert ", "FRANK HERBERT",
                           "Frank Herbert", "Ｆrank Herbert"])
    assert result.mixed is False
    assert result.distinct == 1
    assert result.value == "Frank Herbert", "the first natural spelling is kept"


def test_the_majority_wins_and_the_minority_marks_it_mixed():
    result = wf.consensus(["Dune", "Dune Messiah", "Dune", "Children of Dune"])
    assert result.value == "Dune"
    assert result.mixed is True
    assert result.distinct == 3


def test_a_tie_goes_to_the_first_value_encountered():
    assert wf.consensus(["B", "A", "A", "B"]).value == "B"
    assert wf.consensus(["A", "B", "B", "A"]).value == "A"


def test_blank_participates_honestly_and_nothing_is_fabricated():
    mostly_blank = wf.consensus(["", "", "Someone"])
    assert mostly_blank.value == ""
    assert mostly_blank.mixed is True
    all_blank = wf.consensus(["", "  ", ""])
    assert all_blank == Consensus(value="", mixed=False, distinct=1)
    assert wf.consensus([]) == Consensus(value="", mixed=False, distinct=0)


def test_a_book_summary_covers_exactly_the_three_scalars():
    entries = [track(f"{n:02d}.mp3") for n in range(1, 4)]
    reader = Reader(**{
        "01.mp3": tags(artist="A", album_artist="AA", album="X"),
        "02.mp3": tags(artist="A", album_artist="AA", album="Y"),
        "03.mp3": tags(artist="a", album_artist="", album="X"),
    })
    summary = wf.summarise(wf.observe_files(entries, reader=reader))
    assert isinstance(summary, BookSourceSummary)
    assert summary.artist == Consensus("A", False, 1)
    assert summary.album_artist == Consensus("AA", True, 2)
    assert summary.album == Consensus("X", True, 2)
    assert wf.mixed_fields(summary) == frozenset({"album_artist", "album"})
    assert summary.value_for("artist") == "A"
    assert wf.summarise(()) == BookSourceSummary(
        Consensus("", False, 0), Consensus("", False, 0), Consensus("", False, 0))


# --------------------------------------------------------------------------- #
# The observation store: keyed by occurrence, never by row or path
# --------------------------------------------------------------------------- #


def test_the_store_is_immutable_and_keyed_by_occurrence():
    a, b = track("01.mp3"), track("02.mp3")
    observed = wf.observe_files((a, b), reader=Reader())
    store = ObservationStore().with_observations(observed)
    assert store.count == 2
    assert store.get(a.occurrence_id) is observed[0]
    assert store.get("stranger") is None
    with pytest.raises(TypeError):
        store.entries[a.occurrence_id] = observed[1]  # type: ignore[index]
    again = store.with_observations(observed)
    assert again.count == 2, "re-observing replaces, never duplicates"


def test_default_titles_follow_the_books_track_order_not_the_store_order():
    a, b, c = track("01.mp3"), track("02.mp3"), track("03.mp3")
    reader = Reader(**{"01.mp3": tags(title="One"), "02.mp3": tags(title="Two"),
                       "03.mp3": tags(title="Three")})
    store = ObservationStore().with_observations(
        wf.observe_files((c, a, b), reader=reader))
    book = BookJob(book_id="book-x", files=snapshot(a, b, c))
    assert wf.default_titles(book, store) == ("One", "Two", "Three")


def test_reordering_and_removing_keep_titles_aligned_to_occurrences():
    a, b, c = track("01 One.mp3"), track("02 Two.mp3"), track("03 Three.mp3")
    space = workspace_with(a, b, c)
    store = ObservationStore().with_observations(
        wf.observe_files((a, b, c), reader=Reader()))
    assert wf.default_titles(space.current, store) == ("One", "Two", "Three")

    moved = wf.move_tracks(space, (c.occurrence_id,), wf.UP).workspace
    assert moved.current.files.occurrence_ids == (a.occurrence_id, c.occurrence_id,
                                                  b.occurrence_id)
    assert wf.default_titles(moved.current, store) == ("One", "Three", "Two")

    fewer = wf.remove_tracks(moved, (a.occurrence_id,)).workspace
    assert fewer.current.files.occurrence_ids == (c.occurrence_id, b.occurrence_id)
    assert wf.default_titles(fewer.current, store) == ("Three", "Two")
    assert store.count == 3, "the store is not a list; removal is a workspace fact"


def test_an_occurrence_the_store_never_observed_defaults_from_its_filename():
    a = track("05 Late Addition.mp3")
    book = BookJob(book_id="book-x", files=snapshot(a))
    assert wf.default_titles(book, ObservationStore()) == ("Late Addition",)


def test_a_duplicate_book_carries_no_observation_because_it_has_no_occurrence():
    a = track("01.mp3")
    space = workspace_with(a, artist="Someone")
    store = ObservationStore().with_observations(
        wf.observe_files((a,), reader=Reader(**{"01.mp3": tags(title="T")})))
    copy = duplicate_book(space, id_factory=_BOOKS).workspace.current
    assert copy.configuration["artist"] == "Someone", "configuration copies"
    assert copy.files.is_empty, "inputs do not"
    assert wf.default_titles(copy, store) == ()
    assert wf.summarise(store.for_book(copy)) == wf.summarise(())


# --------------------------------------------------------------------------- #
# Import Folder: one Book per directly-containing directory, never merged
# --------------------------------------------------------------------------- #


def test_folder_import_projects_one_book_per_containing_directory():
    files = (track("01.mp3", "Book A"), track("02.mp3", "Book A"),
             track("01.mp3", "Book B/Part 1"), track("02.mp3", "Book B/Part 1"),
             track("03.mp3", "Book B/Part 2"))
    reader = Reader(**{"01.mp3": tags(artist="Author", album="Album A")})
    result = wf.import_folder(empty_workspace(), snapshot(*files),
                              id_factory=_BOOKS, store=ObservationStore(),
                              reader=reader)
    space = result.workspace
    assert space.count == 3
    names = [wf.source_folder_name(book) for book in space.books]
    assert names == ["Book A", "Part 1", "Part 2"]
    assert [book.file_count for book in space.books] == [2, 2, 1]
    assert space.current_position == 1
    assert result.store.count == 5


def test_distinct_directories_with_the_same_basename_never_merge():
    files = (track("01.mp3", "Series/Book1"), track("01.mp3", "Archive/Book1"))
    result = wf.import_folder(empty_workspace(), snapshot(*files),
                              id_factory=_BOOKS, store=ObservationStore(),
                              reader=Reader())
    assert result.workspace.count == 2
    assert [b.file_count for b in result.workspace.books] == [1, 1]


def test_folder_import_prepopulates_each_book_from_its_own_majority():
    files = (track("01.mp3", "A"), track("02.mp3", "A"), track("01.mp3", "B"))
    store = ObservationStore()

    def reader(path: Path) -> SourceTags:
        if path.parent.name == "A":
            return tags(artist="Author A", album="Album A")
        return tags(artist="Author B", album_artist="Narr B")

    result = wf.import_folder(empty_workspace(), snapshot(*files),
                              id_factory=_BOOKS, store=store, reader=reader)
    first, second = result.workspace.books
    assert first.configuration.get("artist") == "Author A"
    assert first.configuration.get("album") == "Album A"
    assert "album_artist" not in first.configuration, "blank majority writes nothing"
    assert second.configuration.get("artist") == "Author B"
    assert second.configuration.get("album_artist") == "Narr B"
    assert "album" not in second.configuration


def test_folder_import_replaces_the_whole_workspace_as_one_value():
    before = workspace_with(track("old.mp3"), artist="Old")
    result = wf.import_folder(before, snapshot(track("01.mp3", "New")),
                              id_factory=_BOOKS, store=ObservationStore(),
                              reader=Reader())
    assert result.workspace.count == 1
    assert result.workspace.current.configuration.get("artist") is None
    assert before.current.configuration["artist"] == "Old", "the input is untouched"
    assert result.workspace.revision.value > before.revision.value


def test_an_empty_folder_import_leaves_one_pristine_book():
    result = wf.import_folder(empty_workspace(), ImportedFileSnapshot(),
                              id_factory=_BOOKS, store=ObservationStore(),
                              reader=Reader())
    assert result.workspace.count == 1
    assert not has_meaningful_work(result.workspace.current)


def test_files_within_a_book_are_in_natural_order():
    files = (track("10.mp3"), track("2.mp3"), track("1.mp3"))
    result = wf.import_folder(empty_workspace(), snapshot(*files),
                              id_factory=_BOOKS, store=ObservationStore(),
                              reader=Reader())
    assert [f.name for f in result.workspace.current.files.files] == [
        "1.mp3", "2.mp3", "10.mp3"]


# --------------------------------------------------------------------------- #
# Add Files: into the current Book, regardless of parent folder
# --------------------------------------------------------------------------- #


def test_add_files_lands_in_the_current_book_whatever_the_parents_are():
    space = empty_workspace()
    added = (track("a.mp3", "Somewhere"), track("b.mp3", "Elsewhere"),
             track("c.mp3", "Somewhere"))
    result = wf.add_files(space, added, store=ObservationStore(), reader=Reader())
    assert result.workspace.count == 1, "no regrouping by parent"
    assert result.workspace.current.files.occurrence_ids == tuple(
        entry.occurrence_id for entry in added), "the dialog's order is kept"
    assert result.store.count == 3


def test_add_files_targets_the_current_book_not_the_first():
    space = empty_workspace()
    space = book_workspace.add_book(space, id_factory=_BOOKS).workspace
    assert space.current_position == 2
    result = wf.add_files(space, (track("x.mp3"),), store=ObservationStore(),
                          reader=Reader())
    assert result.workspace.books[0].files.is_empty
    assert result.workspace.books[1].file_count == 1


def test_first_files_into_an_empty_book_prepopulate_its_scalars():
    space = empty_workspace()
    reader = Reader(**{"x.mp3": tags(artist="Author", album_artist="Narr",
                                     album="Album")})
    result = wf.add_files(space, (track("x.mp3"),), store=ObservationStore(),
                          reader=reader)
    book = result.workspace.current
    assert book.configuration["artist"] == "Author"
    assert book.configuration["album_artist"] == "Narr"
    assert book.configuration["album"] == "Album"


def test_later_files_never_overwrite_a_users_typed_or_cleared_value():
    a = track("a.mp3")
    space = workspace_with(a, artist="Typed By Me", album="")
    reader = Reader(**{"b.mp3": tags(artist="From Source", album="Source Album")})
    result = wf.add_files(space, (track("b.mp3"),), store=ObservationStore(),
                          reader=reader)
    book = result.workspace.current
    assert book.configuration["artist"] == "Typed By Me"
    assert book.configuration["album"] == "", "an explicit clear stays cleared"
    assert "album_artist" not in book.configuration, "and nothing new is invented"
    assert book.file_count == 2


def test_adding_files_updates_the_mixed_diagnostic_without_touching_values():
    a = track("a.mp3")
    reader = Reader(**{"a.mp3": tags(album="One"), "b.mp3": tags(album="Two")})
    first = wf.add_files(empty_workspace(), (a,), store=ObservationStore(),
                         reader=reader)
    assert wf.mixed_fields(wf.summary_for(first.workspace.current, first.store)) == frozenset()
    second = wf.add_files(first.workspace, (track("b.mp3"),), store=first.store,
                          reader=reader)
    assert second.workspace.current.configuration["album"] == "One"
    assert wf.mixed_fields(wf.summary_for(second.workspace.current, second.store)) == {"album"}


def test_add_files_refuses_an_occurrence_the_book_already_holds():
    a = track("a.mp3")
    space = workspace_with(a)
    with pytest.raises(MP3ContractError):
        wf.add_files(space, (a,), store=ObservationStore(), reader=Reader())


def test_add_files_with_nothing_is_a_no_op():
    space = workspace_with(track("a.mp3"))
    result = wf.add_files(space, (), store=ObservationStore(), reader=Reader())
    assert result.workspace is space
    assert result.mutation.changed is False


# --------------------------------------------------------------------------- #
# Track operations on the current Book
# --------------------------------------------------------------------------- #


def test_move_up_and_down_are_bounded_and_keep_identity():
    a, b, c = track("1.mp3"), track("2.mp3"), track("3.mp3")
    space = workspace_with(a, b, c)
    ids = lambda s: s.current.files.occurrence_ids  # noqa: E731
    top = wf.move_tracks(space, (a.occurrence_id,), wf.UP)
    assert top.changed is False, "already at the top"
    down = wf.move_tracks(space, (a.occurrence_id,), wf.DOWN).workspace
    assert ids(down) == (b.occurrence_id, a.occurrence_id, c.occurrence_id)
    bottom = wf.move_tracks(down, (c.occurrence_id,), wf.DOWN)
    assert bottom.changed is False
    both = wf.move_tracks(space, (b.occurrence_id, c.occurrence_id), wf.UP).workspace
    assert ids(both) == (b.occurrence_id, c.occurrence_id, a.occurrence_id)


def test_remove_tracks_drops_only_the_named_occurrences():
    a, b, c = track("1.mp3"), track("2.mp3"), track("3.mp3")
    space = workspace_with(a, b, c)
    result = wf.remove_tracks(space, (b.occurrence_id,))
    assert result.workspace.current.files.occurrence_ids == (a.occurrence_id,
                                                             c.occurrence_id)
    assert wf.remove_tracks(space, ()).changed is False
    with pytest.raises(MP3ContractError):
        wf.remove_tracks(space, ("not-here",))
    with pytest.raises(MP3ContractError):
        wf.move_tracks(space, ("not-here",), wf.UP)


def test_track_operations_never_touch_configuration_or_other_books():
    a, b = track("1.mp3"), track("2.mp3")
    space = workspace_with(a, b, artist="Kept")
    space = book_workspace.add_book(space, id_factory=_BOOKS).workspace
    space = book_workspace.previous_book(space).workspace
    result = wf.move_tracks(space, (b.occurrence_id,), wf.UP).workspace
    assert result.current.configuration["artist"] == "Kept"
    assert result.books[1].files.is_empty
    assert result.count == 2


# --------------------------------------------------------------------------- #
# Source-folder fallback identity
# --------------------------------------------------------------------------- #


def test_a_book_from_one_directory_knows_its_containing_folder():
    space = workspace_with(track("1.mp3", "The Hobbit"), track("2.mp3", "The Hobbit"))
    assert wf.source_folder_name(space.current) == "The Hobbit"


def test_a_manually_mixed_book_has_no_trustworthy_folder():
    space = workspace_with(track("1.mp3", "Here"), track("2.mp3", "There"))
    assert wf.source_folder_name(space.current) is None
    assert wf.source_folder_name(BookJob(book_id="b")) is None


def test_the_display_hint_prefers_effective_album_then_folder_then_nothing():
    space = workspace_with(track("1.mp3", "Folder Name"))
    assert wf.display_hint(space.shared, space.current) == "Folder Name"
    titled = wf.set_book_field(space, "album", "Typed Album").workspace
    assert wf.display_hint(titled.shared, titled.current) == "Typed Album"
    shared = SharedMetadata(wf.SHARED_FIELDS, {"album": "Shared Album"})
    overridden = set_shared_metadata(titled, shared).workspace
    assert wf.display_hint(overridden.shared, overridden.current) == "Shared Album"
    assert wf.display_hint(space.shared, BookJob(book_id="b")) == ""


# --------------------------------------------------------------------------- #
# Chapter Titles
# --------------------------------------------------------------------------- #


def test_blank_lines_collapse_and_consume_no_track():
    raw = "Chapter One\n\nChapter Two\n\n\nChapter Three\n"
    assert wf.usable_lines(raw) == ("Chapter One", "Chapter Two", "Chapter Three")
    assert wf.usable_lines("") == ()
    assert wf.usable_lines("  \n \t\n") == ()
    assert wf.usable_lines("  padded  \r\nwindows\r\n") == ("padded", "windows")


def test_a_partial_list_leaves_the_remaining_defaults_intact():
    defaults = tuple(f"Default {n}" for n in range(1, 31))
    resolved = wf.resolve_titles("A\n\nB\nC\nD\nE\n", defaults)
    assert len(resolved) == 30
    assert resolved[:5] == ("A", "B", "C", "D", "E")
    assert resolved[5:] == defaults[5:]


def test_a_blank_line_is_never_read_as_clear_this_track():
    defaults = ("D1", "D2", "D3")
    assert wf.resolve_titles("\n\nOnly", defaults) == ("Only", "D2", "D3")
    assert wf.resolve_titles("", defaults) == defaults


def test_extra_lines_beyond_the_track_count_are_ignored():
    assert wf.resolve_titles("a\nb\nc\nd", ("D1", "D2")) == ("a", "b")
    assert wf.resolve_titles("a\nb", ()) == ()


def test_book_titles_compose_the_stored_text_with_the_stored_defaults():
    a, b, c = track("01 One.mp3"), track("02 Two.mp3"), track("03 Three.mp3")
    space = workspace_with(a, b, c, chapter_titles="First\n\nSecond")
    store = ObservationStore().with_observations(
        wf.observe_files((a, b, c), reader=Reader()))
    assert wf.book_titles(space.current, store) == ("First", "Second", "Three")


# --------------------------------------------------------------------------- #
# Parsers
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("text,expected", [
    ("", 0.0), ("   ", 0.0), ("0", 0.0), ("2.5", 2.5), ("-1.25", -1.25),
    (" 3 ", 3.0), ("+4", 4.0), ("1e1", 10.0),
])
def test_signed_time_parses_finite_numbers_and_blank_as_zero(text, expected):
    assert wf.parse_time_delta(text) == expected


@pytest.mark.parametrize("text", ["nan", "NaN", "inf", "-inf", "Infinity", "abc",
                                  "1,5", "2s", "--1", "0x10"])
def test_signed_time_rejects_nan_infinity_and_malformed_text(text):
    with pytest.raises(MP3ValueError):
        wf.parse_time_delta(text)


def test_the_value_error_is_the_contract_error_and_a_value_error():
    assert issubclass(MP3ValueError, MP3ContractError)
    assert issubclass(MP3ValueError, ValueError)


@pytest.mark.parametrize("text,expected", [("", 1), ("  ", 1), ("1", 1), ("7", 7),
                                           (" 42 ", 42), ("007", 7)])
def test_start_number_blank_means_one(text, expected):
    assert wf.parse_start_number(text) == expected


@pytest.mark.parametrize("text", ["0", "-1", "1.5", "one", "1e1", "+", "٣"])
def test_start_number_nonblank_invalid_is_an_explicit_error(text):
    with pytest.raises(MP3ValueError):
        wf.parse_start_number(text)


def test_a_non_string_is_refused_by_both_parsers():
    for wrong in (None, 3, 2.5, b"1"):
        with pytest.raises(MP3ContractError):
            wf.parse_time_delta(wrong)
        with pytest.raises(MP3ContractError):
            wf.parse_start_number(wrong)


def test_time_delta_rejects_a_non_finite_float_even_when_spelled_as_a_number():
    for text in (repr(math.inf), repr(-math.inf), repr(math.nan)):
        with pytest.raises(MP3ValueError):
            wf.parse_time_delta(text)


# --------------------------------------------------------------------------- #
# Book field edits, and no hidden fallback
# --------------------------------------------------------------------------- #


def test_set_book_field_writes_raw_text_and_clears_by_removing_nothing():
    space = workspace_with(track("1.mp3"))
    typed = wf.set_book_field(space, "artist", "  Someone ").workspace
    assert typed.current.configuration["artist"] == "  Someone ", "raw stays raw"
    cleared = wf.set_book_field(typed, "artist", "").workspace
    assert cleared.current.configuration["artist"] == "", "blank is a stored fact"
    assert wf.set_book_field(cleared, "artist", "").changed is False
    with pytest.raises(MP3ContractError):
        wf.set_book_field(space, "title", "no such field")
    with pytest.raises(MP3ContractError):
        wf.set_book_field(space, "artist", 7)


def test_book_only_fields_are_settable_and_readable():
    space = workspace_with(track("1.mp3"))
    space = wf.set_book_field(space, "auto_number", False).workspace
    space = wf.set_book_field(space, "start_number", "5").workspace
    space = wf.set_book_field(space, "chapter_titles", "A\nB").workspace
    assert wf.auto_number_enabled(space.current) is False
    assert wf.start_number_text(space.current) == "5"
    assert wf.chapter_titles_text(space.current) == "A\nB"
    with pytest.raises(MP3ContractError):
        wf.set_book_field(space, "auto_number", "yes")


def test_clearing_a_prefilled_scalar_yields_blank_and_no_source_value_returns():
    a = track("a.mp3")
    reader = Reader(**{"a.mp3": tags(artist="Source Author", album="Source Album")})
    result = wf.add_files(empty_workspace(), (a,), store=ObservationStore(),
                          reader=reader)
    space = result.workspace
    assert effective_value(space.shared, space.current, "artist") == "Source Author"
    cleared = wf.set_book_field(space, "artist", "").workspace
    assert effective_value(cleared.shared, cleared.current, "artist") == ""
    scalars = wf.effective_scalars(cleared.shared, cleared.current)
    assert scalars["artist"] == ""
    assert scalars["album"] == "Source Album", "the untouched one is still there"
    # The store still knows the source value; nothing consults it for output.
    assert result.store.get(a.occurrence_id).tags.artist == "Source Author"


def test_effective_scalars_follow_shared_then_book_then_blank():
    space = workspace_with(track("1.mp3"), artist="Book Artist")
    shared = SharedMetadata(wf.SHARED_FIELDS, {"artist": "Shared Artist"})
    space = set_shared_metadata(space, shared).workspace
    scalars = wf.effective_scalars(space.shared, space.current)
    assert scalars["artist"] == "Shared Artist"
    assert scalars["album_artist"] == ""
    assert set(scalars) == set(wf.SHARED_FIELDS)


def test_the_source_seed_is_a_title_fallback_only_never_a_scalar_fallback():
    """Structural: nothing that computes an effective value names the store."""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if not node.name.startswith("effective_"):
            continue
        names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
        names |= {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
        for hidden in ("ObservationStore", "store", "summary", "summarise",
                       "BookSourceSummary", "consensus", "tags", "default_title"):
            assert hidden not in names, (node.name, hidden)


# --------------------------------------------------------------------------- #
# The real reader, on a stub file mutagen itself tagged
# --------------------------------------------------------------------------- #


def test_the_real_reader_reads_the_four_frames_and_nothing_else(tmp_path):
    from mutagen.id3 import ID3, TALB, TIT2, TPE1, TPE2, TXXX, TYER

    path = tmp_path / "01 Intro.mp3"
    path.write_bytes(b"\x00" * 64)
    frames = ID3()
    frames.add(TIT2(encoding=3, text=["Introduction"]))
    frames.add(TPE1(encoding=3, text=["Author"]))
    frames.add(TPE2(encoding=3, text=["Narrator"]))
    frames.add(TALB(encoding=3, text=["The Album"]))
    frames.add(TYER(encoding=3, text=["1999"]))
    frames.add(TXXX(encoding=3, desc="custom", text=["x"]))
    frames.save(path)
    before = path.read_bytes()

    read = wf.read_source_tags(path)
    assert read == tags(title="Introduction", artist="Author",
                        album_artist="Narrator", album="The Album")
    assert path.read_bytes() == before, "read-only"
    assert not hasattr(read, "year") and not hasattr(read, "comment")


def test_the_real_reader_is_blank_for_an_untagged_or_missing_file(tmp_path):
    untagged = tmp_path / "02.mp3"
    untagged.write_bytes(b"\x00" * 64)
    assert wf.read_source_tags(untagged) == SourceTags()
    assert wf.read_source_tags(tmp_path / "missing.mp3") == SourceTags()


def test_multi_valued_frames_are_joined_readably(tmp_path):
    from mutagen.id3 import ID3, TPE1

    path = tmp_path / "03.mp3"
    path.write_bytes(b"\x00" * 64)
    frames = ID3()
    frames.add(TPE1(encoding=3, text=["A", "B"]))
    frames.save(path)
    assert wf.read_source_tags(path).artist == "A / B"


# --------------------------------------------------------------------------- #
# Boundaries: pure, Tk-free, processing-free
# --------------------------------------------------------------------------- #


def test_the_model_module_imports_no_tk_process_or_output_service():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
    for banned in ("tkinter", "tkinter.ttk", "subprocess", "threading", "queue",
                   "shutil", "shared.output_paths", "shared.ffmpeg_utils",
                   "shared.subprocess_utils", "shared.ui_theme", "shared.job_ui",
                   "shared.import_coordination", "shared.image_capabilities",
                   "PIL", "pillow_heif", "mp3_tools.mp3_tool"):
        assert banned not in modules, banned
    assert "shared.book_workspace" in modules
    assert "shared.importing" in modules


def test_the_model_module_defines_no_processing_or_planning():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    declared = {node.name for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    for forbidden in ("run_ff", "concat", "combine", "write_id3", "embed",
                      "apic", "reserve_run", "plan_outputs", "capture_run", "retry"):
        assert not any(forbidden in name.lower() for name in declared), (
            forbidden, sorted(declared))
    for owned_elsewhere in ("DestinationPlanner", "ImportedFileManager",
                            "ImportCoordinator", "JobController", "WorkspaceSnapshot",
                            "BookJob", "RunSnapshot", "BookRunSnapshot"):
        assert owned_elsewhere not in declared, owned_elsewhere
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    for write in ("save", "write_bytes", "write_text", "mkdir", "unlink", "rename",
                  "rmtree", "touch", "open"):
        assert write not in called, write


def test_the_model_reuses_the_plan6_operations_rather_than_rebuilding_them():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    called = {node.func.id for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    for reused in ("replace_book", "replace_workspace_from_import",
                   "effective_metadata"):
        assert reused in called, reused
    declared = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    for owned_by_plan6 in ("book_groups", "books_from_import", "add_book",
                           "duplicate_book", "remove_book", "select_book",
                           "effective_value", "disabled_fields", "is_populated",
                           "has_meaningful_work"):
        assert owned_by_plan6 not in declared, owned_by_plan6


def test_the_model_is_registered_as_a_plan3_adopter():
    from test_plan3_boundaries import ADOPTED

    assert "mp3_tools/mp3_workflow.py" in ADOPTED


def test_the_mp3_tool_panel_is_untouched_by_phase_three():
    from test_plan6_boundaries import PHASE0_PANEL_HASHES, sha256_of

    assert (sha256_of(UNIVERSAL / "mp3_tools/mp3_tool.py")
            == PHASE0_PANEL_HASHES["mp3_tools/mp3_tool.py"])
    tree = ast.parse((UNIVERSAL / "mp3_tools/mp3_tool.py").read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
    assert "mp3_tools.mp3_workflow" not in modules
