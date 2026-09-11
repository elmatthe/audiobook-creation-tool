"""The frozen MP3 run plan — v0.6.3 focused MP3 plan, Phase 5.

``mp3_tools/mp3_plan.py`` turns one workspace into one immutable execution plan
before any media is touched: one reserved run for the whole operation, one Book
subfolder per eligible Book, every track's final Title / number / filename, the
staged and published destination of every output, and the Plan 6 capture the
retry contract is built on. It reuses the shared reservation, sanitiser and
collision planner and reimplements none of them.

What it does not do, and what this suite proves it does not: no FFmpeg, no tag
write, no artwork embedding, no controller, no retry execution. The staging and
publication *boundaries* are exercised here with plain files, because that is
filesystem mechanics, not media work.

Determinism
-----------
Every run is reserved under ``tmp_path`` through a stub with the real
``RunReservation`` shape. Source "MP3s" are placeholders that are never opened.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path, PurePath

import pytest

from shared import book_workspace, output_paths
from shared.book_workspace import (
    BookJob,
    BookRunSnapshot,
    SharedMetadata,
    WorkspaceSnapshot,
    remove_book,
    set_shared_metadata,
)
from shared.importing import (
    IdFactory,
    ImportOptions,
    ImportedFile,
    ImportedFileSnapshot,
    ImportRoot,
    Revision,
)
from shared.job_control import RunSnapshot

from mp3_tools import mp3_plan as mp
from mp3_tools import mp3_workflow as wf
from mp3_tools.mp3_plan import BookPlan, MP3Operation, PlanError, RunPlan, TrackPlan

from test_importing import make_config

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIVERSAL = REPO_ROOT / "scripts" / "Universal"
MODULE = UNIVERSAL / "mp3_tools" / "mp3_plan.py"

_IDS = IdFactory("plan-")


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def source_root(tmp_path: Path) -> Path:
    root = tmp_path / "Sources"
    root.mkdir()
    return root


@pytest.fixture
def reserve(tmp_path: Path):
    """The real ``RunReservation`` shape, inside ``tmp_path``. Counts calls."""
    counter = {"n": 0}

    def make(tool_key="mp3_tool", **_kw):
        counter["n"] += 1
        directory = tmp_path / "Outputs" / f"MP3-Tool-{counter['n']}"
        directory.mkdir(parents=True)
        return output_paths.RunReservation(
            tool_key=tool_key, base_directory=tmp_path / "Outputs",
            tool_directory=tmp_path / "Outputs", run_directory=directory,
            run_number=counter["n"])

    make.calls = counter  # type: ignore[attr-defined]
    return make


def track(source_root: Path, folder: str, name: str) -> ImportedFile:
    path = source_root / folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not audio")
    occurrence = _IDS.next_id("occurrence")
    return ImportedFile(occurrence, path, ImportRoot("r", source_root, 0),
                        PurePath(folder) / name, "mp3", f"id-{occurrence}")


def book(source_root: Path, folder: str, names, **configuration) -> BookJob:
    files = tuple(track(source_root, folder, name) for name in names)
    return BookJob(book_id=book_workspace.new_book_id(_IDS),
                   configuration=configuration,
                   files=ImportedFileSnapshot(Revision(1), files) if files
                   else ImportedFileSnapshot())


def workspace(*books: BookJob, shared: SharedMetadata | None = None) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(
        books=books, current_book_id=books[0].book_id,
        shared=wf.new_shared_metadata() if shared is None else shared)


def observe(*books: BookJob) -> wf.ObservationStore:
    store = wf.ObservationStore()
    for entry in books:
        store = store.with_observations(
            wf.observe_files(entry.files.files, reader=lambda p: wf.SourceTags()))
    return store


def plan(space, store, reserve, operation=MP3Operation.WRITE_ID3, **kwargs) -> RunPlan:
    return mp.plan_run(
        space, store, operation=operation, reservation=reserve("mp3_tool"),
        catalog=wf.MP3_CATALOG,
        import_options=ImportOptions.for_catalog(wf.MP3_CATALOG),
        effective_config=make_config(), id_factory=_IDS, **kwargs)


# --------------------------------------------------------------------------- #
# One run, one reservation, one folder per Book
# --------------------------------------------------------------------------- #


def test_one_reservation_serves_a_many_book_run(source_root, reserve):
    books = tuple(book(source_root, f"B{n}", ["1.mp3", "2.mp3"], album=f"Album {n}")
                  for n in range(1, 6))
    space = workspace(*books)
    made = plan(space, observe(*books), reserve)
    assert reserve.calls["n"] == 1
    assert len(made.books) == 5
    assert isinstance(made.reservation, output_paths.RunReservation)
    assert made.run_directory == made.reservation.run_directory
    for entry in made.books:
        assert entry.published_dir.parent == made.run_directory
        assert entry.staging_dir.parent == made.work_root
    assert made.work_root == made.run_directory / mp.WORK_DIRNAME


def test_book_folders_follow_album_then_source_folder_then_book_n(source_root, reserve):
    a = book(source_root, "Folder A", ["1.mp3"], album="The Hobbit")
    b = book(source_root, "Folder B", ["1.mp3"])
    c = book(source_root, "X", ["1.mp3"])
    mixed = BookJob(book_id=book_workspace.new_book_id(_IDS), files=ImportedFileSnapshot(
        Revision(1), (track(source_root, "P", "1.mp3"), track(source_root, "Q", "2.mp3"))))
    space = workspace(a, b, c, mixed)
    made = plan(space, observe(a, b, c, mixed), reserve,
                numbers={a.book_id: 1, b.book_id: 2, c.book_id: 3, mixed.book_id: 7})
    names = [entry.folder_name for entry in made.books]
    assert names == ["The Hobbit", "Folder B", "X", "Book 7"]
    assert made.books[3].published_dir == made.run_directory / "Book 7"


def test_book_n_falls_back_to_the_frozen_position_without_a_number_map(source_root, reserve):
    mixed = BookJob(book_id=book_workspace.new_book_id(_IDS), files=ImportedFileSnapshot(
        Revision(1), (track(source_root, "P", "1.mp3"), track(source_root, "Q", "2.mp3"))))
    made = plan(workspace(mixed), observe(mixed), reserve)
    assert made.books[0].folder_name == "Book 1"


def test_repeated_albums_get_collision_safe_folders_in_one_run(source_root, reserve):
    books = tuple(book(source_root, f"F{n}", ["1.mp3"], album="Dune") for n in range(3))
    made = plan(workspace(*books), observe(*books), reserve)
    assert [b.folder_name for b in made.books] == ["Dune", "Dune-1", "Dune-2"]
    assert len({b.published_dir for b in made.books}) == 3
    assert len({b.staging_dir for b in made.books}) == 3
    assert [b.staging_dir.name for b in made.books] == ["Dune", "Dune-1", "Dune-2"]


def test_a_shared_album_wins_the_folder_name(source_root, reserve):
    a = book(source_root, "F", ["1.mp3"], album="Book's own")
    shared = SharedMetadata(wf.SHARED_FIELDS, {"album": "Everyone's"})
    made = plan(workspace(a, shared=shared), observe(a), reserve)
    assert made.books[0].folder_name == "Everyone's"
    assert made.books[0].album == "Everyone's"


def test_invalid_filename_characters_are_sanitised_identically_everywhere(source_root, reserve):
    a = book(source_root, "F", ["1.mp3"], album='Dune: Part <One>/Two?')
    made = plan(workspace(a), observe(a), reserve)
    expected = output_paths.sanitize_component('Dune: Part <One>/Two?')
    assert made.books[0].folder_name == expected
    assert ":" not in expected and "/" not in expected and "?" not in expected
    assert made.books[0].published_dir == made.run_directory / expected


def test_a_folder_named_like_the_work_root_cannot_collide_with_it(source_root, reserve):
    a = book(source_root, "F", ["1.mp3"], album=mp.WORK_DIRNAME)
    made = plan(workspace(a), observe(a), reserve)
    assert made.books[0].published_dir != made.work_root
    assert made.books[0].folder_name == f"{mp.WORK_DIRNAME}-1"


def test_unicode_albums_and_paths_survive(source_root, reserve):
    a = book(source_root, "Straße — Ünïcödé", ["Καλημέρα 01.mp3"], album="日本語のアルバム")
    made = plan(workspace(a), observe(a), reserve)
    assert made.books[0].folder_name == "日本語のアルバム"
    assert made.books[0].tracks[0].filename.endswith(".mp3")
    assert "Καλημέρα" in made.books[0].tracks[0].title


# --------------------------------------------------------------------------- #
# Track Titles, numbers and filenames
# --------------------------------------------------------------------------- #


def test_filenames_come_from_the_final_title_with_a_two_digit_prefix(source_root, reserve):
    a = book(source_root, "F", ["02 Chapter 741_ Home Again.mp3", "03 Next.mp3"])
    made = plan(workspace(a), observe(a), reserve)
    tracks = made.books[0].tracks
    assert [t.title for t in tracks] == ["Chapter 741: Home Again", "Next"]
    assert [t.filename for t in tracks] == ["01 Chapter 741_ Home Again.mp3", "02 Next.mp3"]
    assert [t.track_number for t in tracks] == [1, 2]
    assert [t.position for t in tracks] == [1, 2]


def test_an_existing_leading_number_in_a_title_never_doubles(source_root, reserve):
    a = book(source_root, "F", ["1.mp3", "2.mp3"], chapter_titles="17 Chapter Seventeen\n02 - Intro")
    made = plan(workspace(a), observe(a), reserve)
    assert [t.filename for t in made.books[0].tracks] == [
        "01 Chapter Seventeen.mp3", "02 Intro.mp3"]
    assert [t.title for t in made.books[0].tracks] == ["17 Chapter Seventeen", "02 - Intro"], (
        "the embedded Title keeps what the user typed; only the filename is renumbered")


def test_width_expands_for_a_hundred_or_more_tracks(source_root, reserve):
    a = book(source_root, "F", [f"{n}.mp3" for n in range(1, 101)])
    made = plan(workspace(a), observe(a), reserve)
    names = [t.filename for t in made.books[0].tracks]
    assert names[0] == "001 1.mp3" and names[99] == "100 100.mp3"
    assert made.books[0].tracks[99].track_number == 100
    short = book(source_root, "G", [f"{n}.mp3" for n in range(1, 10)])
    made = plan(workspace(short), observe(short), reserve)
    assert made.books[0].tracks[0].filename == "01 1.mp3"


def test_a_non_default_start_number_shifts_numbers_and_width(source_root, reserve):
    a = book(source_root, "F", ["a.mp3", "b.mp3", "c.mp3"], start_number="99")
    made = plan(workspace(a), observe(a), reserve)
    tracks = made.books[0].tracks
    assert [t.track_number for t in tracks] == [99, 100, 101]
    assert [t.filename for t in tracks] == ["099 a.mp3", "100 b.mp3", "101 c.mp3"]
    assert made.books[0].start_number == 99
    blank = book(source_root, "G", ["a.mp3"], start_number="")
    assert plan(workspace(blank), observe(blank), reserve).books[0].start_number == 1


def test_track_numbers_are_plain_integers_never_padded_text(source_root, reserve):
    a = book(source_root, "F", ["a.mp3", "b.mp3"], start_number="7")
    made = plan(workspace(a), observe(a), reserve)
    for entry in made.books[0].tracks:
        assert type(entry.track_number) is int
    assert made.books[0].tracks[0].track_number == 7


def test_auto_number_off_adds_no_prefix_and_no_track_number(source_root, reserve):
    a = book(source_root, "F", ["01 Intro.mp3", "02 Body.mp3"], auto_number=False)
    made = plan(workspace(a), observe(a), reserve)
    tracks = made.books[0].tracks
    assert [t.filename for t in tracks] == ["Intro.mp3", "Body.mp3"]
    assert [t.track_number for t in tracks] == [None, None]
    assert made.books[0].auto_number is False


def test_duplicate_filenames_within_a_book_are_collision_numbered(source_root, reserve):
    a = book(source_root, "F", ["x.mp3", "y.mp3", "z.mp3"], auto_number=False,
             chapter_titles="Same\nSame\nSame")
    made = plan(workspace(a), observe(a), reserve)
    assert [t.filename for t in made.books[0].tracks] == ["Same.mp3", "Same-1.mp3", "Same-2.mp3"]
    assert len({t.published for t in made.books[0].tracks}) == 3
    assert len({t.staged for t in made.books[0].tracks}) == 3


def test_partial_chapter_titles_override_only_their_positions(source_root, reserve):
    a = book(source_root, "F", [f"{n:02d} Track {n}.mp3" for n in range(1, 8)],
             chapter_titles="One\n\nTwo\n\n\nThree\n")
    made = plan(workspace(a), observe(a), reserve)
    titles = [t.title for t in made.books[0].tracks]
    assert titles[:3] == ["One", "Two", "Three"]
    assert titles[3:] == ["Track 4", "Track 5", "Track 6", "Track 7"]
    assert titles == list(wf.book_titles(a, observe(a)))


def test_a_title_that_sanitises_to_nothing_falls_back_to_the_source_name(source_root, reserve):
    a = book(source_root, "F", ["05 Real Name.mp3"], chapter_titles="???")
    made = plan(workspace(a), observe(a), reserve)
    entry = made.books[0].tracks[0]
    assert entry.title == "???"
    assert entry.filename == "01 Real Name.mp3"


def test_an_invalid_start_number_or_time_is_a_clear_plan_error(source_root, reserve):
    bad_start = book(source_root, "F", ["a.mp3"], start_number="zero")
    with pytest.raises(wf.MP3ValueError):
        plan(workspace(bad_start), observe(bad_start), reserve)
    bad_time = book(source_root, "G", ["a.mp3"], time_delta="lots")
    with pytest.raises(wf.MP3ValueError):
        plan(workspace(bad_time), observe(bad_time), reserve)
    assert reserve.calls["n"] == 2, "the reservation was taken before the plan refused"


# --------------------------------------------------------------------------- #
# Frozen metadata, time and artwork
# --------------------------------------------------------------------------- #


def test_effective_metadata_time_and_artwork_are_frozen_exactly(source_root, reserve, tmp_path):
    art = tmp_path / "cover.png"
    art.write_bytes(b"png")
    a = book(source_root, "F", ["a.mp3"], artist="Book Artist", album_artist="Narr",
             album="Album", time_delta="-1.5", artwork=str(art))
    shared = SharedMetadata(wf.SHARED_FIELDS, {"artist": "Shared Artist"})
    made = plan(workspace(a, shared=shared), observe(a), reserve)
    entry = made.books[0]
    assert entry.artist == "Shared Artist"
    assert entry.album_artist == "Narr"
    assert entry.album == "Album"
    assert entry.time_delta == -1.5
    assert entry.artwork == art
    blank = book(source_root, "G", ["a.mp3"])
    made = plan(workspace(blank), observe(blank), reserve)
    entry = made.books[0]
    assert (entry.artist, entry.album_artist, entry.album) == ("", "", "")
    assert entry.time_delta == 0.0 and entry.artwork is None
    assert entry.book_id == blank.book_id


def test_the_plan_carries_the_plan6_capture_and_its_exact_snapshots(source_root, reserve):
    a = book(source_root, "F", ["a.mp3", "b.mp3"], album="A")
    empty = BookJob(book_id=book_workspace.new_book_id(_IDS))
    b = book(source_root, "G", ["c.mp3"], album="B")
    space = workspace(a, empty, b)
    made = plan(space, observe(a, b), reserve)
    assert isinstance(made.capture, BookRunSnapshot)
    assert [book_id for book_id, _ in made.capture.runs] == [a.book_id, b.book_id]
    assert made.capture.skipped_book_ids == (empty.book_id,)
    assert [entry.book_id for entry in made.books] == [a.book_id, b.book_id], (
        "an empty Book gets no folder and no plan")
    snapshot = made.capture.snapshot_for(a.book_id)
    assert isinstance(snapshot, RunSnapshot)
    assert made.books[0].snapshot is snapshot
    assert tuple(t.occurrence_id for t in made.books[0].tracks) == snapshot.item_ids
    assert made.book_for(a.book_id) is made.books[0]
    assert made.book_for(empty.book_id) is None


def test_every_track_keeps_its_occurrence_and_source(source_root, reserve):
    a = book(source_root, "F", ["1.mp3", "2.mp3"])
    made = plan(workspace(a), observe(a), reserve)
    for entry, imported in zip(made.books[0].tracks, a.files.files):
        assert entry.occurrence_id == imported.occurrence_id
        assert entry.source == imported.path
        assert made.books[0].track_for(imported.occurrence_id) is entry
    assert made.books[0].track_for("nope") is None
    assert made.books[0].source_paths == tuple(f.path for f in a.files.files)


# --------------------------------------------------------------------------- #
# Live edits after capture change nothing
# --------------------------------------------------------------------------- #


def test_live_edits_after_capture_do_not_move_a_single_planned_value(source_root, reserve):
    a = book(source_root, "F", ["1.mp3", "2.mp3"], album="Before", chapter_titles="One")
    b = book(source_root, "G", ["3.mp3"], album="Other")
    space = workspace(a, b)
    store = observe(a, b)
    made = plan(space, store, reserve)
    frozen = (made.books[0].folder_name, made.books[0].published_dir,
              tuple(t.filename for t in made.books[0].tracks),
              tuple(t.title for t in made.books[0].tracks),
              tuple(t.staged for t in made.books[0].tracks), made.books[0].album)

    # Edit everything live: Shared, the Book, its tracks, the workspace shape.
    edited = wf.set_book_field(space, "album", "After").workspace
    edited = wf.set_book_field(edited, "chapter_titles", "Completely\nDifferent").workspace
    edited = wf.move_tracks(edited, (a.files.files[1].occurrence_id,), wf.UP).workspace
    edited = set_shared_metadata(edited, SharedMetadata(
        wf.SHARED_FIELDS, {"album": "Shared Now", "time_delta": "9"})).workspace
    edited = remove_book(edited, id_factory=_IDS).workspace
    assert edited.count == 1

    assert (made.books[0].folder_name, made.books[0].published_dir,
            tuple(t.filename for t in made.books[0].tracks),
            tuple(t.title for t in made.books[0].tracks),
            tuple(t.staged for t in made.books[0].tracks), made.books[0].album) == frozen
    assert made.books[0].time_delta == 0.0
    assert [e.book_id for e in made.books] == [a.book_id, b.book_id]


def test_the_plan_is_immutable_and_holds_no_workspace_reference(source_root, reserve):
    a = book(source_root, "F", ["1.mp3"])
    made = plan(workspace(a), observe(a), reserve)
    with pytest.raises(Exception):
        made.books = ()  # type: ignore[misc]
    with pytest.raises(Exception):
        made.books[0].tracks[0].filename = "x"  # type: ignore[misc]
    for field_name in ("workspace", "store", "space"):
        assert not hasattr(made, field_name)


# --------------------------------------------------------------------------- #
# Retry-stable destinations, staging and publication
# --------------------------------------------------------------------------- #


def test_staged_and_published_destinations_are_distinct_and_frozen(source_root, reserve):
    a = book(source_root, "F", ["1.mp3", "2.mp3"], album="Dune")
    made = plan(workspace(a), observe(a), reserve, operation=MP3Operation.COMBINE)
    entry = made.books[0]
    assert entry.staging_dir == made.work_root / "Dune"
    assert entry.published_dir == made.run_directory / "Dune"
    for t in entry.tracks:
        assert t.staged.parent == entry.staging_dir
        assert t.published.parent == entry.published_dir
        assert t.staged.name == t.published.name
    assert entry.combined_filename == "Dune.mp3"
    assert entry.combined_published == entry.published_dir / "Dune.mp3"
    assert entry.combined_staged == entry.staging_dir / "Dune.mp3"
    assert entry.timestamps_published == entry.published_dir / mp.TIMESTAMPS_NAME
    assert entry.timestamps_staged == entry.staging_dir / mp.TIMESTAMPS_NAME
    assert set(entry.staged_outputs) == {entry.combined_staged, entry.timestamps_staged}
    assert set(entry.published_outputs) == {entry.combined_published, entry.timestamps_published}


def test_write_id3_publishes_every_track_and_combine_publishes_one_file(source_root, reserve):
    a = book(source_root, "F", ["1.mp3", "2.mp3"])
    write = plan(workspace(a), observe(a), reserve, operation=MP3Operation.WRITE_ID3)
    assert write.books[0].combined_filename is None
    assert write.books[0].combined_published is None
    assert set(write.books[0].published_outputs) == {t.published for t in write.books[0].tracks}
    combine = plan(workspace(a), observe(a), reserve, operation=MP3Operation.COMBINE)
    assert combine.books[0].combined_filename is not None
    assert combine.operation is MP3Operation.COMBINE


def test_a_combined_name_cannot_collide_with_a_track_of_the_same_name(source_root, reserve):
    a = book(source_root, "F", ["x.mp3"], album="Same", auto_number=False, chapter_titles="Same")
    made = plan(workspace(a), observe(a), reserve, operation=MP3Operation.COMBINE)
    entry = made.books[0]
    assert entry.tracks[0].published != entry.combined_published
    assert {entry.tracks[0].filename, entry.combined_filename} == {"Same.mp3", "Same-1.mp3"}


def test_no_destination_is_ever_a_source_and_none_lands_in_a_source_tree(source_root, reserve):
    a = book(source_root, "F", ["1.mp3"])
    made = plan(workspace(a), observe(a), reserve)
    entry = made.books[0]
    sources = set(entry.source_paths)
    for path in (*entry.staged_outputs, *entry.published_outputs, entry.staging_dir,
                 entry.published_dir):
        assert path not in sources
        assert source_root not in path.parents
        assert made.run_directory in path.parents


def test_a_run_directory_inside_a_source_tree_is_refused(source_root, tmp_path):
    a = book(source_root, "F", ["1.mp3"])
    inside = source_root / "F" / "MP3-Tool-1"
    inside.mkdir()
    reservation = output_paths.RunReservation(
        tool_key="mp3_tool", base_directory=source_root, tool_directory=source_root,
        run_directory=inside, run_number=1)
    with pytest.raises(output_paths.UnsafePathError):
        mp.plan_run(workspace(a), observe(a), operation=MP3Operation.WRITE_ID3,
                    reservation=reservation, catalog=wf.MP3_CATALOG,
                    import_options=ImportOptions.for_catalog(wf.MP3_CATALOG),
                    effective_config=make_config(), id_factory=_IDS)


def test_planning_creates_nothing_on_disk(source_root, reserve):
    a = book(source_root, "F", ["1.mp3"], album="Dune")
    made = plan(workspace(a), observe(a), reserve)
    assert sorted(p.name for p in made.run_directory.iterdir()) == []
    assert not made.work_root.exists()
    assert not made.books[0].staging_dir.exists()
    assert not made.books[0].published_dir.exists()


def _stage_all(entry: BookPlan) -> None:
    mp.prepare_staging(entry)
    for path in entry.staged_outputs:
        path.write_bytes(b"staged " + path.name.encode("utf-8"))


def test_prepare_staging_creates_only_the_private_work_area(source_root, reserve):
    a = book(source_root, "F", ["1.mp3"], album="Dune")
    made = plan(workspace(a), observe(a), reserve)
    entry = made.books[0]
    assert mp.prepare_staging(entry) == entry.staging_dir
    assert entry.staging_dir.is_dir()
    assert made.work_root.name.startswith(".")
    assert not entry.published_dir.exists(), "nothing visible yet"
    assert mp.prepare_staging(entry) == entry.staging_dir, "idempotent"


def test_publish_moves_every_staged_output_into_the_book_folder(source_root, reserve):
    a = book(source_root, "F", ["1.mp3", "2.mp3"], album="Dune")
    made = plan(workspace(a), observe(a), reserve)
    entry = made.books[0]
    _stage_all(entry)
    published = mp.publish_book(entry)
    assert set(published) == set(entry.published_outputs)
    for path in entry.published_outputs:
        assert path.is_file()
        assert path.read_bytes() == b"staged " + path.name.encode("utf-8")
    for path in entry.staged_outputs:
        assert not path.exists()
    assert mp.is_published(entry) is True
    assert sorted(p.name for p in made.run_directory.iterdir()) == [mp.WORK_DIRNAME, "Dune"]


def test_a_book_with_a_missing_staged_output_is_not_published_at_all(source_root, reserve):
    a = book(source_root, "F", ["1.mp3", "2.mp3", "3.mp3"], album="Dune")
    made = plan(workspace(a), observe(a), reserve)
    entry = made.books[0]
    mp.prepare_staging(entry)
    entry.tracks[0].staged.write_bytes(b"one")
    entry.tracks[2].staged.write_bytes(b"three")      # track 2 failed
    with pytest.raises(PlanError):
        mp.publish_book(entry)
    assert not entry.published_dir.exists(), "no partial Book is visible"
    assert entry.tracks[0].staged.is_file() and entry.tracks[2].staged.is_file(), (
        "the successful pieces survive in private staging for a retry")
    assert mp.is_published(entry) is False


def test_publication_rolls_back_if_a_move_fails_midway(source_root, reserve, monkeypatch):
    a = book(source_root, "F", ["1.mp3", "2.mp3", "3.mp3"], album="Dune")
    made = plan(workspace(a), observe(a), reserve)
    entry = made.books[0]
    _stage_all(entry)
    real_replace = os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk went away")
        real_replace(src, dst)

    monkeypatch.setattr(mp.os, "replace", flaky)
    with pytest.raises(PlanError):
        mp.publish_book(entry)
    monkeypatch.setattr(mp.os, "replace", real_replace)
    assert all(path.is_file() for path in entry.staged_outputs), "everything is back"
    assert not any(path.exists() for path in entry.published_outputs)
    assert mp.is_published(entry) is False


def test_publish_never_overwrites_an_existing_published_file(source_root, reserve):
    a = book(source_root, "F", ["1.mp3"], album="Dune")
    made = plan(workspace(a), observe(a), reserve)
    entry = made.books[0]
    _stage_all(entry)
    entry.published_dir.mkdir(parents=True)
    entry.tracks[0].published.write_bytes(b"someone else's")
    with pytest.raises(PlanError):
        mp.publish_book(entry)
    assert entry.tracks[0].published.read_bytes() == b"someone else's"
    assert entry.tracks[0].staged.is_file()


def test_publish_refuses_a_staged_link(source_root, reserve):
    a = book(source_root, "F", ["1.mp3"], album="Dune")
    made = plan(workspace(a), observe(a), reserve)
    entry = made.books[0]
    mp.prepare_staging(entry)
    target = entry.tracks[0].staged
    try:
        os.symlink(entry.tracks[0].source, target)
    except (OSError, NotImplementedError):
        pytest.skip("this environment cannot create a file symlink")
    with pytest.raises(PlanError):
        mp.publish_book(entry)
    assert not entry.published_dir.exists()


def test_discard_staging_removes_only_the_books_private_area(source_root, reserve):
    a = book(source_root, "F", ["1.mp3"], album="Dune")
    b = book(source_root, "G", ["2.mp3"], album="Other")
    made = plan(workspace(a, b), observe(a, b), reserve)
    first, second = made.books
    _stage_all(first)
    _stage_all(second)
    (first.staging_dir / "wavs").mkdir()
    (first.staging_dir / "wavs" / "0001.wav").write_bytes(b"pcm")
    (first.staging_dir / "inputs.txt").write_text("file 'x'", encoding="utf-8")
    removed = mp.discard_staging(first)
    assert removed >= 3
    assert not first.staging_dir.exists()
    assert second.staging_dir.is_dir() and all(p.is_file() for p in second.staged_outputs)
    for path in first.source_paths:
        assert path.is_file(), "sources are never touched"
    assert mp.discard_staging(first) == 0, "idempotent"


def test_discard_staging_refuses_to_follow_a_link_out_of_the_work_area(source_root, reserve, tmp_path):
    a = book(source_root, "F", ["1.mp3"], album="Dune")
    made = plan(workspace(a), observe(a), reserve)
    entry = made.books[0]
    mp.prepare_staging(entry)
    outside = tmp_path / "precious"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")
    try:
        os.symlink(outside, entry.staging_dir / "escape", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this environment cannot create a directory symlink")
    mp.discard_staging(entry)
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_discard_run_staging_removes_only_an_empty_work_root(source_root, reserve):
    a = book(source_root, "F", ["1.mp3"], album="Dune")
    made = plan(workspace(a), observe(a), reserve)
    entry = made.books[0]
    _stage_all(entry)
    assert mp.discard_run_staging(made) is False, "a Book's staging is still there"
    mp.publish_book(entry)
    assert mp.discard_run_staging(made) is True
    assert not made.work_root.exists()
    assert entry.published_dir.is_dir()
    assert mp.discard_run_staging(made) is False


def test_discard_refuses_a_plan_whose_staging_is_not_under_its_run(source_root, reserve, tmp_path):
    a = book(source_root, "F", ["1.mp3"], album="Dune")
    made = plan(workspace(a), observe(a), reserve)
    entry = made.books[0]
    rogue = BookPlan(**{**{f: getattr(entry, f) for f in entry.__dataclass_fields__},
                       "staging_dir": tmp_path / "elsewhere"})
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "elsewhere" / "victim.txt").write_text("x", encoding="utf-8")
    with pytest.raises(PlanError):
        mp.discard_staging(rogue)
    assert (tmp_path / "elsewhere" / "victim.txt").exists()


# --------------------------------------------------------------------------- #
# Boundaries: pure planning, no media, one collision authority
# --------------------------------------------------------------------------- #


def test_the_planning_module_reaches_no_tk_media_or_controller():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
            modules |= {f"{node.module}.{alias.name}" for alias in node.names}
    for banned in ("tkinter", "subprocess", "threading", "queue", "shutil", "mutagen",
                   "PIL", "shared.ffmpeg_utils", "shared.subprocess_utils",
                   "shared.job_ui", "shared.ui_theme", "shared.import_coordination",
                   "mp3_tools.mp3_tool", "shared.image_capabilities"):
        assert banned not in modules, banned
    assert "shared.output_paths" in modules
    assert "shared.book_workspace" in modules
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    for forbidden in ("rmtree", "run", "Popen", "save", "write_bytes", "write_text",
                      "copy", "copyfile", "copy2"):
        assert forbidden not in called, forbidden


def test_the_planning_module_declares_no_second_sanitiser_or_collision_loop():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    declared = {node.name for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    for owned_elsewhere in ("sanitize_component", "sanitize", "numbered_variant",
                            "reserve_run_directory", "DestinationPlanner",
                            "RunReservation", "capture_run", "capture_workspace_run",
                            "RetryRequest", "retry_failed_books", "resolve_titles",
                            "parse_start_number", "parse_time_delta", "SuccessNumbers"):
        assert owned_elsewhere not in declared, owned_elsewhere
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    called |= {node.func.id for node in ast.walk(tree)
               if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    for reused in ("plan", "plan_directory", "sanitize_component", "capture_workspace_run",
                   "book_titles", "parse_start_number", "parse_time_delta",
                   "assert_not_input", "assert_outside_source_trees", "effective_scalars"):
        assert reused in called, reused


def test_the_planning_module_is_registered_as_an_adopter():
    from test_plan3_boundaries import ADOPTED

    assert "mp3_tools/mp3_plan.py" in ADOPTED


def test_the_directory_planner_extension_shares_the_one_collision_authority(tmp_path):
    planner = output_paths.DestinationPlanner(tmp_path)
    first = planner.plan_directory("Dune")
    second = planner.plan_directory("dune")
    assert first == tmp_path / "Dune"
    assert second == tmp_path / "Dune-1", "case-insensitive, like files"
    (tmp_path / "Dune-2").mkdir()
    assert planner.plan_directory("Dune") == tmp_path / "Dune-3"
    # A file planned with the same stem does not share the directory's name.
    assert planner.plan("Dune") == tmp_path / "Dune-4"
    assert planner.plan_directory("a/b:c") == tmp_path / output_paths.sanitize_component("a/b:c")
    # Traversal is neutralised by the shared sanitiser, never planned.
    assert planner.plan_directory("..") == tmp_path / output_paths.sanitize_component("..")
    assert tmp_path in planner.plan_directory("../../etc").parents
    assert sorted(p.name for p in tmp_path.iterdir()) == ["Dune-2"], "nothing was created"
