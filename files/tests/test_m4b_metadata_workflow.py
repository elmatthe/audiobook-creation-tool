"""The M4B Metadata Editor source/workspace model — v0.6.4 Phase 7.

``mp3_tools/m4b_metadata_workflow.py`` is the Editor's Tk-free layer between the
shared Plan 6 workspace and the panel that adopts it later (Phase 10). One
imported M4B-family occurrence is one stable Book; each Book carries a frozen
observation of what its source contains (read through ``shared.metadata``, with
series provenance preserved), and its configuration holds **only explicit
edits** — a prefilled value is displayed from the observation, never stored as
an edit, so blank means preserve and unchanged means nothing to write.

Nothing here writes a tag, copies a file, plans an output or starts a
controller. Fixtures are tiny real M4B-family files built by the project's own
FFmpeg and tagged with mutagen through the shared writer.
"""

from __future__ import annotations

import ast
import hashlib
import subprocess
from pathlib import Path, PurePath

import pytest

from shared import book_workspace, ffmpeg_utils, metadata
from shared.book_workspace import (
    BookJob, BookMutation, SharedMetadata, WorkspaceSnapshot, disabled_fields,
    has_meaningful_work, next_book, previous_book, remove_book, select_book,
    set_shared_metadata,
)
from shared.importing import (
    IdFactory, ImportRoot, ImportedFile, ImportedFileSnapshot, Revision, SupportedTypeCatalog,
)

from mp3_tools import m4b_metadata_workflow as wf
from mp3_tools.m4b_metadata_workflow import (
    EditorContractError, ObservationStore, SourceObservation,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIVERSAL = REPO_ROOT / "scripts" / "Universal"
MODULE = UNIVERSAL / "mp3_tools" / "m4b_metadata_workflow.py"

_IDS = IdFactory("ed-")
_BOOKS = IdFactory("edbook-")


# --------------------------------------------------------------------------- #
# Fixtures: tiny real containers, never repository media
# --------------------------------------------------------------------------- #


def require_ffmpeg() -> None:
    if not ffmpeg_utils.have_ffmpeg():
        pytest.fail("ffmpeg/ffprobe could not be resolved; the Editor model cannot be proved")


def _ff(*args) -> None:
    out = subprocess.run([ffmpeg_utils.ffmpeg_cmd(), "-hide_banner", "-v", "error", "-y", *args],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert out.returncode == 0, out.stdout.decode("utf-8", "replace")[-600:]


_META = """;FFMETADATA1
[CHAPTER]
TIMEBASE=1/1000
START=0
END=2999
title=Opening
[CHAPTER]
TIMEBASE=1/1000
START=3000
END=5999
title=Closing
"""


@pytest.fixture(scope="module")
def container(tmp_path_factory) -> Path:
    """One six-second AAC file with two chapters and a JPEG cover; copied per test."""
    require_ffmpeg()
    work = tmp_path_factory.mktemp("editor-model")
    meta = work / "meta.txt"
    meta.write_text(_META, encoding="utf-8")
    _ff("-f", "lavfi", "-i", "sine=frequency=440:duration=6", "-c:a", "aac", "-b:a", "48k",
        str(work / "audio.m4a"))
    _ff("-f", "lavfi", "-i", "color=c=red:s=32x32:d=1", "-frames:v", "1", str(work / "c.jpg"))
    target = work / "base.m4b"
    _ff("-i", str(work / "audio.m4a"), "-i", str(work / "c.jpg"), "-i", str(meta),
        "-map", "0:a", "-map", "1:v", "-map_metadata", "2", "-map_chapters", "2",
        "-c:a", "copy", "-c:v", "copy", "-disposition:v:0", "attached_pic", str(target))
    return target


@pytest.fixture
def sources(tmp_path: Path) -> Path:
    root = tmp_path / "Sources"
    root.mkdir()
    return root


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def listing(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*")}


def m4b(container: Path, path: Path, **tags) -> Path:
    """A copy of the base container carrying *tags* through the shared writer."""
    import shutil

    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(container, path)
    if tags:
        metadata.write_m4b_tags(path, tags)
    return path


def vendor_series(path: Path, *, name: str | None = None, part: str | None = None,
                  movement: tuple[str, int] | None = None) -> Path:
    """Write a *vendor* freeform or native movement series onto *path* with mutagen."""
    from mutagen.mp4 import MP4, MP4FreeForm

    mp4 = MP4(str(path))
    if mp4.tags is None:
        mp4.add_tags()
    if name is not None:
        mp4.tags["----:com.pilabor.tone:SERIES"] = [MP4FreeForm(name.encode("utf-8"))]
    if part is not None:
        mp4.tags["----:com.pilabor.tone:PART"] = [MP4FreeForm(part.encode("utf-8"))]
    if movement is not None:
        mp4.tags["\xa9mvn"] = [movement[0]]
        mp4.tags["\xa9mvi"] = [movement[1]]
    mp4.save()
    return path


def imported(sources: Path, relative: str, path: Path | None = None) -> ImportedFile:
    """An importer record for *relative* under *sources* (the file need not exist)."""
    target = sources / relative if path is None else path
    occurrence = _IDS.next_id("occurrence")
    return ImportedFile(occurrence, target, ImportRoot("r", sources, 0), PurePath(relative),
                        wf.EDITOR_TYPE.type_id, f"id-{occurrence}-{relative.replace('/', '-')}")


def snapshot(*entries: ImportedFile) -> ImportedFileSnapshot:
    return ImportedFileSnapshot(Revision(1), tuple(entries))


def import_all(entries, store: ObservationStore | None = None):
    return wf.import_folder(wf.new_workspace(id_factory=_BOOKS), snapshot(*entries),
                            id_factory=_BOOKS, store=store or ObservationStore())


def shared_with(space: WorkspaceSnapshot, **values) -> WorkspaceSnapshot:
    return set_shared_metadata(
        space, SharedMetadata(fields=wf.SHARED_FIELDS, values=values)).workspace


# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #


def test_the_editor_accepts_the_m4b_family_through_its_own_catalog():
    assert isinstance(wf.EDITOR_CATALOG, SupportedTypeCatalog)
    assert wf.EDITOR_TYPE.extensions == (".m4b", ".m4a", ".mp4")
    assert [entry.type_id for entry in wf.EDITOR_CATALOG.types] == [wf.EDITOR_TYPE.type_id]


def test_the_shared_fields_are_the_editors_eight_and_series_part_is_not_one():
    assert wf.SHARED_FIELDS == ("title", "artist", "album", "year", "genre", "comment",
                                "series", "artwork")
    assert wf.TEXT_FIELDS == ("title", "artist", "album", "year", "genre", "comment", "series")
    assert "series_part" not in wf.SHARED_FIELDS and "series_part" not in wf.TEXT_FIELDS
    assert wf.BOOK_ONLY_FIELDS == ("chapter_titles",)
    assert set(wf.FIELD_LABELS) >= set(wf.SHARED_FIELDS) | {"chapter_titles", "series_part"}
    for foreign in ("silence", "time_delta", "output_filename", "album_artist"):
        assert foreign not in wf.SHARED_FIELDS + wf.BOOK_ONLY_FIELDS


def test_the_startup_workspace_is_one_pristine_book_with_blank_shared():
    space = wf.new_workspace(id_factory=_BOOKS)
    assert space.count == 1 and space.current.is_empty
    assert space.shared.fields == wf.SHARED_FIELDS and space.shared.populated_fields == ()


# --------------------------------------------------------------------------- #
# One occurrence = one Book
# --------------------------------------------------------------------------- #


def test_one_occurrence_becomes_one_stable_book(container, sources):
    entry = imported(sources, "Book/one.m4b", m4b(container, sources / "Book" / "one.m4b"))
    result = import_all((entry,))
    assert isinstance(result.mutation, BookMutation) and result.mutation.changed
    space = result.mutation.workspace
    assert space.count == 1
    book = space.current
    assert [f.occurrence_id for f in book.files.files] == [entry.occurrence_id]
    assert wf.source_of(book) is entry
    assert book.configuration == {}, "prefill is displayed from the observation, not stored"


def test_two_m4bs_in_one_directory_are_two_books_not_one(container, sources):
    a = imported(sources, "Book/a.m4b", m4b(container, sources / "Book" / "a.m4b"))
    b = imported(sources, "Book/b.m4b", m4b(container, sources / "Book" / "b.m4b"))
    space = import_all((a, b)).mutation.workspace
    assert space.count == 2
    assert [wf.source_of(book).occurrence_id for book in space.books] == [
        a.occurrence_id, b.occurrence_id]
    assert len({book.book_id for book in space.books}) == 2


def test_distinct_occurrences_of_one_path_stay_distinct_books(container, sources):
    path = m4b(container, sources / "same.m4b")
    a = imported(sources, "same.m4b", path)
    b = ImportedFile(_IDS.next_id("occurrence"), path, ImportRoot("r2", sources, 1),
                     PurePath("same.m4b"), wf.EDITOR_TYPE.type_id, "id-other-root")
    space = import_all((a, b)).mutation.workspace
    assert space.count == 2


def test_folder_import_replaces_and_add_files_appends_by_identity(container, sources):
    a = imported(sources, "A/a.m4b", m4b(container, sources / "A" / "a.m4b"))
    result = import_all((a,))
    space, store = result.mutation.workspace, result.store
    b = imported(sources, "B/b.m4b", m4b(container, sources / "B" / "b.m4b"))
    again = ImportedFile(_IDS.next_id("occurrence"), a.path, a.source_root, a.relative_path,
                         a.supported_type_id, a.identity)
    added = wf.add_files(space, (b, again), store=store)
    assert added.mutation.changed
    assert added.mutation.workspace.count == 2, "the same identity is not added twice"
    assert added.skipped == 1
    assert added.mutation.workspace.current.book_id == added.mutation.workspace.books[-1].book_id
    replaced = wf.import_folder(added.mutation.workspace, snapshot(b), id_factory=_BOOKS,
                                store=added.store)
    assert replaced.mutation.workspace.count == 1
    assert wf.source_of(replaced.mutation.workspace.current) is b


def test_an_empty_import_leaves_one_pristine_book(sources):
    space = wf.new_workspace(id_factory=_BOOKS)
    result = wf.import_folder(space, snapshot(), id_factory=_BOOKS, store=ObservationStore())
    assert result.mutation.changed is False and result.mutation.workspace.count == 1


def test_book_ids_survive_navigation_and_edits(container, sources):
    entries = tuple(imported(sources, f"{n}.m4b", m4b(container, sources / f"{n}.m4b"))
                    for n in ("a", "b", "c"))
    space = import_all(entries).mutation.workspace
    ids = [book.book_id for book in space.books]
    space = next_book(space).workspace
    space = wf.set_book_field(space, "title", "Edited").workspace
    space = previous_book(space).workspace
    space = select_book(space, ids[2]).workspace
    assert [book.book_id for book in space.books] == ids
    space = remove_book(space, id_factory=_BOOKS).workspace
    assert [book.book_id for book in space.books] == ids[:2]
    assert space.books[1].configuration == {"title": "Edited"}


# --------------------------------------------------------------------------- #
# Source observation
# --------------------------------------------------------------------------- #


def test_a_source_is_observed_with_every_field_provenance_chapters_and_cover(container, sources):
    path = m4b(container, sources / "full.m4b", title="The Title", artist="An Author",
               album="The Album", year="2021", genre="Fantasy", comment="Note",
               series="Saga", series_part="2")
    before, snap = sha(path), listing(sources)
    seen = wf.observe_source(path)
    assert isinstance(seen, SourceObservation) and seen.readable and seen.error == ""
    assert (seen.title, seen.artist, seen.album, seen.year, seen.genre, seen.comment) == (
        "The Title", "An Author", "The Album", "2021", "Fantasy", "Note")
    assert (seen.series, seen.series_part) == ("Saga", "2")
    assert seen.series_source == "freeform:com.apple.iTunes"
    assert seen.series_atom == "----:com.apple.iTunes:SERIES"
    assert seen.series_part_source == "freeform:com.apple.iTunes"
    assert seen.has_cover is True
    assert seen.chapter_titles == ("Opening", "Closing") and seen.chapter_count == 2
    assert sha(path) == before and listing(sources) == snap, "read-only, no sidecar"


def test_vendor_and_movement_series_provenance_survive_observation(container, sources):
    vendor = vendor_series(m4b(container, sources / "vendor.m4b", album="Alb"),
                           name="Tone Saga", part="3")
    seen = wf.observe_source(vendor)
    assert (seen.series, seen.series_part) == ("Tone Saga", "3")
    assert seen.series_source == "freeform:com.pilabor.tone"
    assert seen.series_atom == "----:com.pilabor.tone:SERIES"
    assert seen.series_part_atom == "----:com.pilabor.tone:PART"
    moved = vendor_series(m4b(container, sources / "movement.m4b"), movement=("Moves", 4))
    seen = wf.observe_source(moved)
    assert (seen.series, seen.series_part) == ("Moves", "4")
    assert seen.series_source == "movement" and seen.series_part_source == "movement"
    assert not seen.series_name_implied and not seen.series_part_implied


def test_implied_series_values_are_observations_not_prefill(container, sources):
    """An album-implied name is display-only; a track-implied part likewise."""
    from mutagen.mp4 import MP4

    path = m4b(container, sources / "implied.m4b", album="Grouping Album")
    mp4 = MP4(str(path))
    mp4.tags["trkn"] = [(2, 5)]
    mp4.save()
    seen = wf.observe_source(path)
    assert seen.series == "Grouping Album" and seen.series_source == "album-implied"
    assert seen.series_part == "2" and seen.series_part_source == "track-implied"
    assert seen.series_name_implied and seen.series_part_implied
    prefill = wf.prefill_values(seen)
    assert prefill["series"] == "", "an implied name is never prefilled for writing"
    assert "series_part" not in prefill
    assert prefill["album"] == "Grouping Album"
    assert "Grouping Album" in wf.series_readback(seen)


def test_the_series_readback_line_is_the_existing_editors_rule(container, sources):
    """The four "Detected on file" cases, worded exactly as the old panel worded them.

    Phase 7 proved this line equal to the old panel's ``_series_readback_text``;
    v0.6.4 Phase 10 retired that method with the batch-global panel, so the
    accepted wording is pinned here literally and the model is the authority
    the production panel now displays through.
    """
    cases = {
        "full.m4b": (dict(series="Saga", series_part="2", album="A"),
                     "Detected on file: Saga #2  (source: ----:com.apple.iTunes:SERIES)"),
        "partless.m4b": (dict(series="Saga"),
                         "Detected on file: Saga  (source: ----:com.apple.iTunes:SERIES)"),
        "nothing.m4b": (dict(), "Detected on file: none — this file has no series tag"),
        "implied.m4b": (dict(album="Alb"),
                        "Detected on file: part #3 only — no series name on file; "
                        "Audiobookshelf likely groups by Album: 'Alb'  (source: trkn)"),
    }
    for name, (tags, expected) in cases.items():
        path = m4b(container, sources / name, **tags)
        if name == "implied.m4b":
            from mutagen.mp4 import MP4
            mp4 = MP4(str(path))
            mp4.tags["trkn"] = [(3, 9)]
            mp4.save()
        seen = wf.observe_source(path)
        assert wf.series_readback(seen) == expected, name


def test_an_unreadable_source_settles_safely_beside_readable_books(container, sources):
    good = imported(sources, "good.m4b", m4b(container, sources / "good.m4b", title="Good"))
    junk = sources / "junk.m4b"
    junk.write_bytes(b"not an mp4 at all")
    bad = imported(sources, "junk.m4b", junk)
    before = sha(junk)
    result = import_all((good, bad))
    space, store = result.mutation.workspace, result.store
    assert space.count == 2, "the unreadable source is a Book, not silently dropped"
    seen_bad = store.for_book(space.books[1])
    assert seen_bad is not None and not seen_bad.readable
    assert seen_bad.error and seen_bad.occurrence_id == bad.occurrence_id
    assert seen_bad.chapter_titles == () and seen_bad.has_cover is False
    assert wf.prefill_values(seen_bad) == {name: "" for name in wf.TEXT_FIELDS}
    seen_good = store.for_book(space.books[0])
    assert seen_good.readable and seen_good.title == "Good"
    assert sha(junk) == before
    assert listing(sources) == {"good.m4b", "junk.m4b"}


def test_observations_are_keyed_by_occurrence_and_never_by_row(container, sources):
    a = imported(sources, "a.m4b", m4b(container, sources / "a.m4b", title="A"))
    b = imported(sources, "b.m4b", m4b(container, sources / "b.m4b", title="B"))
    result = import_all((a, b))
    space, store = result.mutation.workspace, result.store
    space = remove_book(space, id_factory=_BOOKS).workspace
    assert store.for_book(space.current).title == "B"
    assert store.get(a.occurrence_id).title == "A", "the store is immutable and keeps history"


def test_observing_is_the_shared_readers_and_reads_no_atoms_itself():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    # The readers are injectable defaults (``reader=metadata.read_m4b_tags``),
    # so they are referenced as attributes rather than called by name here.
    referenced = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert {"read_m4b_tags", "read_chapter_titles"} <= referenced
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
            modules |= {f"{node.module}.{alias.name}" for alias in node.names}
    assert "mutagen" not in modules and "mutagen.mp4" not in modules
    literals = {node.value for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert not any(v.startswith("----:") or v.startswith("\xa9") for v in literals)


# --------------------------------------------------------------------------- #
# Source versus edit intent
# --------------------------------------------------------------------------- #


def test_prefill_is_displayed_not_stored_and_an_edit_keeps_the_observation(container, sources):
    entry = imported(sources, "one.m4b", m4b(container, sources / "one.m4b", title="Source T",
                                              artist="Source A"))
    result = import_all((entry,))
    space, store = result.mutation.workspace, result.store
    page = wf.page_values(space.shared, space.current, store)
    assert page["title"] == "Source T" and page["artist"] == "Source A" and page["year"] == ""
    assert space.current.configuration == {}
    edited = wf.set_book_field(space, "title", "New T").workspace
    assert edited.current.configuration == {"title": "New T"}
    assert store.for_book(edited.current).title == "Source T", "the observation is untouched"
    assert wf.page_values(edited.shared, edited.current, store)["title"] == "New T"


def test_unchanged_prefill_blank_and_explicit_change_are_told_apart(container, sources):
    entry = imported(sources, "one.m4b", m4b(container, sources / "one.m4b", title="Source T",
                                              series="Saga"))
    result = import_all((entry,))
    space, store = result.mutation.workspace, result.store
    assert wf.edit_intent(space.shared, space.current, store, "title") is None
    assert wf.edit_intent(space.shared, space.current, store, "series") is None
    same = wf.set_book_field(space, "title", "Source T").workspace
    assert wf.edit_intent(same.shared, same.current, store, "title") is None, "typed the same"
    blank = wf.set_book_field(space, "title", "").workspace
    assert wf.edit_intent(blank.shared, blank.current, store, "title") is None, "blank preserves"
    changed = wf.set_book_field(space, "title", "New T").workspace
    assert wf.edit_intent(changed.shared, changed.current, store, "title") == "New T"
    assert wf.explicit_edits(changed.shared, changed.current, store) == {"title": "New T"}
    migrated = wf.set_book_field(space, "series", "Saga").workspace
    assert wf.edit_intent(migrated.shared, migrated.current, store, "series") is None, (
        "an unchanged series value is never migrated to the canonical atom")


def test_an_unreadable_book_has_no_prefill_but_can_still_carry_an_edit(sources):
    junk = sources / "junk.m4b"
    junk.write_bytes(b"nope")
    entry = imported(sources, "junk.m4b", junk)
    result = import_all((entry,))
    space, store = result.mutation.workspace, result.store
    assert wf.page_values(space.shared, space.current, store)["title"] == ""
    edited = wf.set_book_field(space, "title", "Typed").workspace
    assert wf.edit_intent(edited.shared, edited.current, store, "title") == "Typed"


# --------------------------------------------------------------------------- #
# Shared: starts blank, overrides when populated, restores when cleared
# --------------------------------------------------------------------------- #


def test_shared_starts_blank_even_when_every_source_agrees(container, sources):
    entries = tuple(imported(sources, f"{n}.m4b", m4b(container, sources / f"{n}.m4b",
                                                       artist="Same Author", series="Saga"))
                    for n in ("a", "b"))
    space = import_all(entries).mutation.workspace
    assert space.shared.populated_fields == ()
    assert disabled_fields(space.shared) == frozenset()


def test_blank_shared_means_no_override_and_no_write_intent(container, sources):
    entry = imported(sources, "a.m4b", m4b(container, sources / "a.m4b", artist="Author"))
    result = import_all((entry,))
    space, store = result.mutation.workspace, result.store
    assert wf.shared_intent(space.shared) == {}
    assert wf.explicit_edits(space.shared, space.current, store) == {}
    assert wf.page_values(space.shared, space.current, store)["artist"] == "Author"


def test_populated_shared_overrides_and_disables_and_clearing_restores(container, sources):
    entry = imported(sources, "a.m4b", m4b(container, sources / "a.m4b", artist="Source Author"))
    result = import_all((entry,))
    space, store = result.mutation.workspace, result.store
    space = wf.set_book_field(space, "artist", "Book Author").workspace
    overridden = shared_with(space, artist="Shared Author")
    assert disabled_fields(overridden.shared) == {"artist"}
    assert wf.page_values(overridden.shared, overridden.current, store)["artist"] == "Shared Author"
    assert wf.shared_intent(overridden.shared) == {"artist": "Shared Author"}
    assert wf.explicit_edits(overridden.shared, overridden.current, store) == {
        "artist": "Shared Author"}
    restored = shared_with(overridden)
    assert disabled_fields(restored.shared) == frozenset()
    assert restored.current.configuration["artist"] == "Book Author"
    assert wf.page_values(restored.shared, restored.current, store)["artist"] == "Book Author"
    assert wf.explicit_edits(restored.shared, restored.current, store) == {"artist": "Book Author"}


def test_shared_artwork_is_an_explicit_replacement_intent(container, sources, tmp_path):
    from PIL import Image

    art = tmp_path / "cover.png"
    Image.new("RGB", (8, 8), (1, 2, 3)).save(art, format="PNG")
    entry = imported(sources, "a.m4b", m4b(container, sources / "a.m4b"))
    result = import_all((entry,))
    space, store = result.mutation.workspace, result.store
    assert store.for_book(space.current).has_cover is True
    assert wf.artwork_intent(space.shared, space.current) is None, "blank preserves the source"
    with_book = wf.set_book_field(space, "artwork", str(art)).workspace
    assert wf.artwork_intent(with_book.shared, with_book.current) == str(art)
    with_shared = shared_with(space, artwork=str(art))
    assert wf.artwork_intent(with_shared.shared, with_shared.current) == str(art)


# --------------------------------------------------------------------------- #
# Chapters: observed in order; edits are positional; blank preserves
# --------------------------------------------------------------------------- #


def test_chapter_edits_are_positional_blank_preserves_and_extra_lines_are_ignored(
        container, sources):
    entry = imported(sources, "a.m4b", m4b(container, sources / "a.m4b"))
    result = import_all((entry,))
    space, store = result.mutation.workspace, result.store
    seen = store.for_book(space.current)
    assert seen.chapter_titles == ("Opening", "Closing")
    assert wf.chapter_edits(space.current, seen) == (None, None), "no buffer, nothing changes"
    edited = wf.set_book_field(space, "chapter_titles", "\nEnd\nExtra").workspace
    assert wf.chapter_lines(edited.current) == ("", "End", "Extra")
    assert wf.chapter_edits(edited.current, seen) == (None, "End")
    same = wf.set_book_field(space, "chapter_titles", "Opening\nClosing").workspace
    assert wf.chapter_edits(same.current, seen) == (None, None), "unchanged titles preserve"


def test_series_part_is_readback_and_the_auto_number_parser_is_separate(container, sources):
    entry = imported(sources, "a.m4b", m4b(container, sources / "a.m4b", series="Saga",
                                            series_part="7"))
    result = import_all((entry,))
    space, store = result.mutation.workspace, result.store
    seen = store.for_book(space.current)
    assert seen.series_part == "7"
    with pytest.raises(EditorContractError):
        wf.set_book_field(space, "series_part", "8")
    assert wf.parse_start_part("") == 1 and wf.parse_start_part(" 4 ") == 4
    with pytest.raises(wf.EditorValueError):
        wf.parse_start_part("0")


# --------------------------------------------------------------------------- #
# Structure
# --------------------------------------------------------------------------- #


def test_the_model_imports_no_tk_process_output_or_writer_and_writes_nothing():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
            modules |= {f"{node.module}.{alias.name}" for alias in node.names}
    for banned in ("tkinter", "subprocess", "threading", "queue", "shutil", "tempfile",
                   "shared.output_paths", "shared.ffmpeg_utils", "shared.job_ui",
                   "shared.job_control", "shared.import_coordination", "shared.numbering",
                   "mp3_tools.m4b_metadata_editor", "mp3_tools.m4b_maker",
                   "mp3_tools.m4b_maker_workflow", "mp3_tools.mp3_workflow",
                   "mp3_tools.m4b_artwork", "PIL"):
        assert banned not in modules, banned
    for required in ("shared.book_workspace", "shared.importing", "shared.metadata"):
        assert required in modules, required
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    for write in ("write_m4b_tags", "clear_metadata_keep_chapters", "clear_series_numbering",
                  "apply_chapter_titles", "save", "write_bytes", "write_text", "mkdir",
                  "unlink", "rename", "replace", "copy2", "copyfile", "rmtree", "open"):
        assert write not in called, write
    declared = {node.name for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    for forbidden in ("plan_", "reserve", "publish", "stage", "retry", "apply_", "clear_",
                      "remove_series", "JobController"):
        assert not any(forbidden in name.lower() for name in declared), (forbidden, sorted(declared))
    for owned_by_plan6 in ("book_groups", "add_book", "duplicate_book", "remove_book",
                           "select_book", "effective_value", "disabled_fields",
                           "is_populated", "has_meaningful_work", "WorkspaceSnapshot", "BookJob"):
        assert owned_by_plan6 not in declared, owned_by_plan6


def test_the_model_is_registered_as_a_plan3_adopter():
    from test_plan3_boundaries import ADOPTED

    assert "mp3_tools/m4b_metadata_workflow.py" in ADOPTED


def test_the_editor_panel_now_consumes_this_model():
    """Phase 7 built the model behind an untouched panel; v0.6.4 Phase 10 made
    the panel its consumer (the old byte-identity pin retired with the conversion)."""
    from test_plan6_boundaries import EDITOR_PHASE0_HASH, sha256_as_checked_out_on_windows

    panel = UNIVERSAL / "mp3_tools" / "m4b_metadata_editor.py"
    assert sha256_as_checked_out_on_windows(panel) != EDITOR_PHASE0_HASH
    tree = ast.parse(panel.read_text(encoding="utf-8"))
    modules = {f"{node.module}.{alias.name}" for node in ast.walk(tree)
               if isinstance(node, ast.ImportFrom) for alias in node.names}
    modules |= {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    modules |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                for alias in node.names}
    assert "mp3_tools.m4b_metadata_workflow" in modules
    declared = {node.name for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    for owned_here in ("observe_source", "prefill_values", "page_values", "edit_intent",
                       "explicit_edits", "series_readback", "chapter_edits", "display_hint"):
        assert owned_here not in declared, owned_here
