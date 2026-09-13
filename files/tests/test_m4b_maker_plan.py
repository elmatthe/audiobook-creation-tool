"""The frozen M4B Maker run plan — v0.6.4 Phase 3.

``mp3_tools/m4b_maker_plan.py`` freezes one Maker operation completely before
any media is touched: the Books in order with their stable ids and exact
occurrences, the final chapter titles, the effective metadata, artwork and
Silence, the manual-or-auto series settings, the Fast-first option, the
destination mode, and every Book's collision-safe final ``.m4b`` path and
private staging path. It is the only thing Phases 4–5 and a later Retry Failed
read. Nothing here runs FFmpeg, writes a file, embeds anything or starts a
controller — and planning itself creates no media output.

Naming is Decision 51A: explicit Output Filename → Title → effective Album →
the one source-containing folder → ``Book N``; sanitised by the shared
sanitiser, ``.m4b`` appended exactly once, collision-numbered by the shared
planner. Standard mode plans every Book into the one reserved
``M4B-Maker-N``; custom mode plans straight into the user's folder with no
nested run directory and stages in an operation-owned work root elsewhere.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path, PurePath

import pytest

from shared import book_workspace, output_paths
from shared.book_workspace import (
    BookJob, BookRunSnapshot, SharedMetadata, WorkspaceSnapshot, remove_book,
    set_shared_metadata,
)
from shared.importing import (
    IdFactory, ImportOptions, ImportedFile, ImportedFileSnapshot, ImportRoot, Revision,
)
from shared.job_control import RunSnapshot

from mp3_tools import m4b_maker_plan as mp
from mp3_tools import m4b_maker_workflow as wf
from mp3_tools.m4b_maker_plan import (
    BookPlan, DestinationMode, MakerDestination, MakerRunOptions, PlanError, RunPlan,
)

from test_importing import make_config

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIVERSAL = REPO_ROOT / "scripts" / "Universal"
MODULE = UNIVERSAL / "mp3_tools" / "m4b_maker_plan.py"

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

    def make(tool_key="m4b_maker", **_kw):
        counter["n"] += 1
        directory = tmp_path / "Outputs" / "M4B-Maker-Outputs" / f"M4B-Maker-{counter['n']}"
        directory.mkdir(parents=True)
        return output_paths.RunReservation(
            tool_key=tool_key, base_directory=tmp_path / "Outputs",
            tool_directory=directory.parent, run_directory=directory,
            run_number=counter["n"])

    make.calls = counter  # type: ignore[attr-defined]
    return make


@pytest.fixture
def custom_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "Chosen"
    directory.mkdir()
    return directory


@pytest.fixture
def work_root(tmp_path: Path) -> Path:
    return tmp_path / "op-work"


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


def shared(**values) -> SharedMetadata:
    return SharedMetadata(fields=wf.SHARED_FIELDS, values=values)


def plan(space, destination, options: MakerRunOptions | None = None, **kwargs) -> RunPlan:
    return mp.plan_run(
        space, options=options or MakerRunOptions(), destination=destination,
        catalog=wf.MAKER_CATALOG,
        import_options=ImportOptions.for_catalog(wf.MAKER_CATALOG),
        effective_config=make_config(), id_factory=_IDS, **kwargs)


def listing(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*")}


# --------------------------------------------------------------------------- #
# Destinations: one reserved run, or the user's folder with nothing nested
# --------------------------------------------------------------------------- #


def test_standard_mode_plans_every_book_into_the_one_reserved_run(source_root, reserve):
    space = workspace(book(source_root, "One", ["1.mp3"], title="One"),
                      book(source_root, "Two", ["1.mp3"], title="Two"),
                      book(source_root, "Three", ["1.mp3"], title="Three"))
    made = plan(space, mp.standard_destination(reserve()))
    assert reserve.calls["n"] == 1, "exactly one reservation for the whole operation"
    assert made.mode is DestinationMode.STANDARD
    assert made.destination.reservation is not None
    assert made.root == made.destination.reservation.run_directory
    assert [entry.published.parent for entry in made.books] == [made.root] * 3
    assert [entry.published.name for entry in made.books] == ["One.m4b", "Two.m4b", "Three.m4b"]
    assert made.work_root == made.root / mp.WORK_DIRNAME
    for entry in made.books:
        assert entry.staging_dir.parent == made.work_root
        assert entry.staged == entry.staging_dir / entry.published.name


def test_custom_mode_plans_into_the_chosen_folder_with_no_nested_run(source_root, custom_dir,
                                                                      work_root):
    space = workspace(book(source_root, "One", ["1.mp3"], title="One"),
                      book(source_root, "Two", ["1.mp3"], title="Two"))
    destination = mp.custom_destination(custom_dir, work_root=work_root)
    made = plan(space, destination)
    assert made.mode is DestinationMode.CUSTOM
    assert made.destination.reservation is None
    assert made.root == custom_dir
    assert [entry.published for entry in made.books] == [custom_dir / "One.m4b",
                                                         custom_dir / "Two.m4b"]
    assert not any("M4B-Maker" in part for entry in made.books for part in entry.published.parts)
    assert made.work_root == work_root
    for entry in made.books:
        assert entry.staging_dir.parent == work_root
        assert output_paths.assert_contained(work_root, entry.staged)


def test_a_custom_work_root_must_be_absolute_and_outside_the_destination(custom_dir):
    with pytest.raises(PlanError):
        mp.custom_destination(custom_dir, work_root=Path("relative"))
    with pytest.raises(PlanError):
        mp.custom_destination(custom_dir, work_root=custom_dir / "nested")
    with pytest.raises(PlanError):
        mp.custom_destination(custom_dir, work_root=custom_dir)
    with pytest.raises(PlanError):
        mp.standard_destination("not a reservation")  # type: ignore[arg-type]


def test_a_custom_destination_that_is_not_a_directory_is_refused(tmp_path, work_root):
    with pytest.raises(PlanError):
        mp.custom_destination(tmp_path / "missing", work_root=work_root)
    with pytest.raises(PlanError):
        mp.custom_destination("relative/path", work_root=work_root)


def test_collision_names_are_deterministic_within_one_run(source_root, reserve):
    space = workspace(book(source_root, "A", ["1.mp3"], title="Dune"),
                      book(source_root, "B", ["1.mp3"], title="Dune"),
                      book(source_root, "C", ["1.mp3"], title="dune"))
    made = plan(space, mp.standard_destination(reserve()))
    assert [entry.published.name for entry in made.books] == ["Dune.m4b", "Dune-1.m4b", "dune-2.m4b"]
    again = plan(space, mp.standard_destination(reserve()))
    assert [entry.published.name for entry in again.books] == [entry.published.name
                                                               for entry in made.books]


def test_an_existing_file_in_a_custom_folder_is_never_overwritten(source_root, custom_dir,
                                                                   work_root):
    (custom_dir / "Dune.m4b").write_bytes(b"existing")
    space = workspace(book(source_root, "A", ["1.mp3"], title="Dune"))
    made = plan(space, mp.custom_destination(custom_dir, work_root=work_root))
    assert made.books[0].published == custom_dir / "Dune-1.m4b"
    assert (custom_dir / "Dune.m4b").read_bytes() == b"existing"


def test_a_book_called_dot_work_is_numbered_away_from_the_work_area(source_root, reserve):
    space = workspace(book(source_root, "A", ["1.mp3"], output_filename=".work"))
    made = plan(space, mp.standard_destination(reserve()))
    assert made.work_root.name == mp.WORK_DIRNAME
    assert made.books[0].published.name != mp.WORK_DIRNAME
    assert made.books[0].published.name.lower().endswith(".m4b")


# --------------------------------------------------------------------------- #
# Output Filename: Decision 51A priority, sanitised, .m4b exactly once
# --------------------------------------------------------------------------- #


def test_the_output_filename_follows_the_decision_51a_priority(source_root, reserve):
    # Book 5's tracks come from two folders, so its containing folder is ambiguous.
    ambiguous = BookJob(
        book_id=book_workspace.new_book_id(_IDS),
        files=ImportedFileSnapshot(Revision(1), (track(source_root, "E1", "1.mp3"),
                                                 track(source_root, "E2", "2.mp3"))))
    space = workspace(
        book(source_root, "Folder A", ["1.mp3"], output_filename="Explicit", title="T", album="A"),
        book(source_root, "Folder B", ["1.mp3"], title="Title B", album="Album B"),
        book(source_root, "Folder C", ["1.mp3"], album="Album C"),
        book(source_root, "Folder D", ["1.mp3"]),
        ambiguous,
    )
    made = plan(space, mp.standard_destination(reserve()))
    assert [entry.published.name for entry in made.books] == [
        "Explicit.m4b", "Title B.m4b", "Album C.m4b", "Folder D.m4b", "Book 5.m4b"]


def test_shared_album_is_the_effective_album_for_naming(source_root, reserve):
    space = workspace(book(source_root, "F", ["1.mp3"], album="Book Album"),
                      shared=shared(album="Shared Album"))
    made = plan(space, mp.standard_destination(reserve()))
    assert made.books[0].published.name == "Shared Album.m4b"
    assert made.books[0].album == "Shared Album"


@pytest.mark.parametrize("given,expected", [
    ("My Book", "My Book.m4b"),
    ("My Book.m4b", "My Book.m4b"),
    ("My Book.M4B", "My Book.m4b"),
    ("My Book.m4b.m4b", "My Book.m4b.m4b"),
    ("Book 1.5 - Extras", "Book 1.5 - Extras.m4b"),
    ("  padded  ", "padded.m4b"),
    ('bad:name?*', "bad_name__.m4b"),
    ("trailing dots...", "trailing dots.m4b"),
])
def test_the_m4b_suffix_is_appended_exactly_once_after_sanitising(given, expected):
    assert mp.output_filename(given) == expected


def test_an_explicit_name_that_sanitises_to_nothing_readable_falls_through(source_root, reserve):
    space = workspace(book(source_root, "Folder", ["1.mp3"], output_filename="???", title="Real"))
    made = plan(space, mp.standard_destination(reserve()))
    assert made.books[0].published.name == "Real.m4b"


def test_a_path_like_output_filename_cannot_escape_the_destination(source_root, reserve):
    space = workspace(book(source_root, "Folder", ["1.mp3"],
                           output_filename="../../escape"))
    made = plan(space, mp.standard_destination(reserve()))
    assert made.books[0].published.parent == made.root
    assert made.books[0].published.name == "escape.m4b"


def test_the_sanitiser_and_planner_are_the_shared_ones_not_a_local_regex():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert {"sanitize_component", "plan", "assert_not_input"} <= called
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
    assert "re" not in modules, "no local filename regex"
    defined = {node.name for node in ast.walk(tree)
               if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    for foreign in ("sanitize_component", "DestinationPlanner", "reserve_run_directory",
                    "validate_custom_destination", "assert_not_input", "numbered_variant",
                    "capture_workspace_run", "RunSnapshot", "BookRunSnapshot"):
        assert foreign not in defined, foreign


# --------------------------------------------------------------------------- #
# Safety: overlap and containment are refused by the shared authorities
# --------------------------------------------------------------------------- #


def test_a_standard_run_inside_a_source_tree_is_refused(source_root, tmp_path):
    inside = source_root / "Book" / "M4B-Maker-1"
    inside.mkdir(parents=True)
    reservation = output_paths.RunReservation(
        tool_key="m4b_maker", base_directory=source_root, tool_directory=inside.parent,
        run_directory=inside, run_number=1)
    space = workspace(book(source_root, "Book", ["1.mp3"], title="T"))
    with pytest.raises(output_paths.UnsafePathError):
        plan(space, mp.standard_destination(reservation))


def test_an_output_that_would_equal_an_input_is_refused(source_root, work_root):
    """Custom mode may write beside the sources — never onto one of them.

    The shared planner already numbers around a file that *exists*, so this
    input is a phantom record (no file on disk): the planner offers the bare
    name, and ``assert_not_input`` is what has to refuse it.
    """
    folder = source_root / "Book"
    folder.mkdir()
    phantom = ImportedFile("occ-phantom", folder / "Dune.m4b", ImportRoot("r", source_root, 0),
                           PurePath("Book") / "Dune.m4b", "mp3", "id-phantom")
    only = BookJob(book_id=book_workspace.new_book_id(_IDS),
                   configuration={"output_filename": "Dune"},
                   files=ImportedFileSnapshot(Revision(1), (phantom,)))
    with pytest.raises(output_paths.UnsafePathError):
        plan(workspace(only), mp.custom_destination(folder, work_root=work_root))


def test_custom_mode_beside_the_sources_is_the_explicit_exception(source_root, work_root):
    folder = source_root / "Book"
    space = workspace(book(source_root, "Book", ["1.mp3"], title="Dune"))
    made = plan(space, mp.custom_destination(folder, work_root=work_root))
    assert made.books[0].published == folder / "Dune.m4b"


# --------------------------------------------------------------------------- #
# What is frozen per Book and per run
# --------------------------------------------------------------------------- #


def test_the_book_plan_carries_every_frozen_value(source_root, reserve):
    art = source_root / "cover.jpg"
    art.write_bytes(b"jpg")
    space = workspace(
        book(source_root, "Vol 1", ["01 - Intro.mp3", "02 - Body.mp3", "03 - End.mp3"],
             title="The Title", artist="Book Artist", album_artist="AA", album="Alb",
             series="Saga", series_part="2", silence="1.5", artwork=str(art),
             chapter_titles="First\n\nSecond"))
    made = plan(space, mp.standard_destination(reserve()),
                MakerRunOptions(auto_number=False, start_part_text="", fast_first=False))
    entry = made.books[0]
    assert isinstance(entry, BookPlan)
    assert entry.book_id == space.books[0].book_id
    assert entry.number == 1
    assert isinstance(entry.snapshot, RunSnapshot)
    assert entry.occurrence_ids == tuple(f.occurrence_id for f in space.books[0].files.files)
    assert entry.sources == tuple(f.path for f in space.books[0].files.files)
    assert entry.chapter_titles == ("First", "Second", "End")
    assert (entry.title, entry.artist, entry.album_artist, entry.album, entry.series) == (
        "The Title", "Book Artist", "AA", "Alb", "Saga")
    assert entry.series_part == "2"
    assert entry.silence == 1.5
    assert entry.artwork == art
    assert entry.published == made.root / "The Title.m4b"
    assert entry.staged == made.work_root / "The Title" / "The Title.m4b"
    assert made.fast_first is False and made.auto_number is False and made.start_part == 1


def test_shared_values_override_book_values_in_the_frozen_plan(source_root, reserve):
    art = source_root / "shared.png"
    art.write_bytes(b"png")
    space = workspace(book(source_root, "V", ["1.mp3"], artist="Book", silence="3",
                           artwork=str(source_root / "book.png"), series="Book Saga"),
                      shared=shared(artist="Shared", silence="0", artwork=str(art),
                                    series="Shared Saga"))
    entry = plan(space, mp.standard_destination(reserve())).books[0]
    assert entry.artist == "Shared"
    assert entry.silence == 0.0
    assert entry.artwork == art
    assert entry.series == "Shared Saga"


def test_a_blank_title_falls_back_to_the_resolved_output_name(source_root, reserve):
    space = workspace(book(source_root, "Folder", ["1.mp3"], album="Alb"),
                      book(source_root, "Other", ["1.mp3"]),
                      book(source_root, "X", ["1.mp3"], output_filename="Named"))
    made = plan(space, mp.standard_destination(reserve()))
    assert [entry.title for entry in made.books] == ["Alb", "Other", "Named"]
    assert all(entry.title for entry in made.books), "never a nameless book"


def test_no_artwork_is_none_and_blank_chapter_text_means_automatic_titles(source_root, reserve):
    space = workspace(book(source_root, "F", ["01 - A.mp3", "02 - B.mp3"], title="T"))
    entry = plan(space, mp.standard_destination(reserve())).books[0]
    assert entry.artwork is None
    assert entry.chapter_titles == ("A", "B")
    assert entry.silence == 0.0


def test_auto_number_freezes_the_setting_and_start_part_but_consumes_no_number(source_root, reserve):
    space = workspace(book(source_root, "A", ["1.mp3"], title="A", series_part="7"),
                      book(source_root, "B", ["1.mp3"], title="B", series_part="9"))
    made = plan(space, mp.standard_destination(reserve()),
                MakerRunOptions(auto_number=True, start_part_text=" 4 "))
    assert made.auto_number is True and made.start_part == 4
    assert [entry.series_part for entry in made.books] == [None, None], (
        "with Auto-number on the manual part is not the run's; the number is Phase 5's")
    assert not any(hasattr(entry, name) for entry in made.books
                   for name in ("part", "allocated_part", "series_number"))
    off = plan(space, mp.standard_destination(reserve()), MakerRunOptions(auto_number=False))
    assert [entry.series_part for entry in off.books] == ["7", "9"]
    assert off.start_part == 1


def test_negative_silence_or_a_bad_start_part_refuses_the_whole_operation(source_root, reserve):
    bad = workspace(book(source_root, "A", ["1.mp3"], title="A"),
                    book(source_root, "B", ["1.mp3"], title="B", silence="-1"))
    with pytest.raises(wf.MakerValueError):
        plan(bad, mp.standard_destination(reserve()))
    good = workspace(book(source_root, "A", ["1.mp3"], title="A"))
    with pytest.raises(wf.MakerValueError):
        plan(good, mp.standard_destination(reserve()), MakerRunOptions(auto_number=True,
                                                                        start_part_text="0"))


def test_empty_books_are_skipped_by_the_shared_capture_and_get_no_plan(source_root, reserve):
    space = workspace(book(source_root, "A", ["1.mp3"], title="A"),
                      book(source_root, "B", [], title="Empty"))
    made = plan(space, mp.standard_destination(reserve()))
    assert isinstance(made.capture, BookRunSnapshot)
    assert [entry.book_id for entry in made.books] == [space.books[0].book_id]
    assert made.capture.skipped_book_ids == (space.books[1].book_id,)
    assert made.book_for(space.books[1].book_id) is None


def test_book_numbers_are_workspace_positions_even_past_a_skipped_book(source_root, reserve):
    space = workspace(book(source_root, "A", [], title="Empty"),
                      book(source_root, "B", ["1.mp3"]))
    made = plan(space, mp.standard_destination(reserve()))
    assert made.books[0].number == 2
    assert made.books[0].published.name == "B.m4b"


# --------------------------------------------------------------------------- #
# Immutability: the plan is a value the live workspace can no longer reach
# --------------------------------------------------------------------------- #


def test_later_workspace_edits_cannot_change_the_plan(source_root, reserve):
    space = workspace(book(source_root, "A", ["1.mp3", "2.mp3"], title="Before", silence="1"),
                      book(source_root, "B", ["1.mp3"], title="Second"))
    made = plan(space, mp.standard_destination(reserve()))
    before = (tuple(entry.title for entry in made.books),
              tuple(entry.published for entry in made.books),
              tuple(entry.occurrence_ids for entry in made.books),
              tuple(entry.chapter_titles for entry in made.books),
              tuple(entry.silence for entry in made.books))

    edited = wf.set_book_field(space, "title", "After").workspace
    edited = wf.set_book_field(edited, "chapter_titles", "Changed").workspace
    edited = wf.remove_tracks(edited, (edited.current.files.files[0].occurrence_id,)).workspace
    edited = set_shared_metadata(edited, shared(silence="9", artist="Late")).workspace
    edited = remove_book(edited, id_factory=_IDS).workspace
    assert edited.count == 1

    assert (tuple(entry.title for entry in made.books),
            tuple(entry.published for entry in made.books),
            tuple(entry.occurrence_ids for entry in made.books),
            tuple(entry.chapter_titles for entry in made.books),
            tuple(entry.silence for entry in made.books)) == before
    assert made.books[0].artist == ""
    assert len(made.books) == 2


def test_later_mutation_of_the_option_and_destination_inputs_cannot_change_the_plan(
        source_root, reserve):
    options = MakerRunOptions(auto_number=True, start_part_text="3", fast_first=True)
    space = workspace(book(source_root, "A", ["1.mp3"], title="A"))
    made = plan(space, mp.standard_destination(reserve()), options)
    with pytest.raises(dataclasses.FrozenInstanceError):
        options.fast_first = False  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        made.destination.root = Path("elsewhere")  # type: ignore[misc]
    assert made.fast_first is True and made.start_part == 3


def test_plan_structures_are_frozen_and_widget_free(source_root, reserve):
    space = workspace(book(source_root, "A", ["1.mp3"], title="A"))
    made = plan(space, mp.standard_destination(reserve()))
    for frozen in (made, made.books[0], made.destination):
        assert dataclasses.is_dataclass(frozen) and frozen.__dataclass_params__.frozen
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(frozen, "book_id", "x")
    assert isinstance(made.books, tuple)
    assert isinstance(made.books[0].chapter_titles, tuple)
    assert isinstance(made.books[0].sources, tuple)

    def walk(value, seen=None):
        seen = set() if seen is None else seen
        if id(value) in seen:
            return
        seen.add(id(value))
        kind = type(value).__module__
        assert not kind.startswith("tkinter"), type(value)
        assert not callable(value) or isinstance(value, type), type(value)
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            for field_ in dataclasses.fields(value):
                walk(getattr(value, field_.name), seen)
        elif isinstance(value, (tuple, list, frozenset)):
            for item in value:
                walk(item, seen)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item, seen)

    walk(made)


def test_planning_creates_no_file_in_the_run_or_the_sources(source_root, reserve, tmp_path):
    reservation = reserve()
    space = workspace(book(source_root, "A", ["1.mp3"], title="A"),
                      book(source_root, "B", ["1.mp3"], title="B"))
    before_sources = listing(source_root)
    made = plan(space, mp.standard_destination(reservation))
    assert listing(reservation.run_directory) == set(), "the reserved run is still empty"
    assert listing(source_root) == before_sources
    assert not made.work_root.exists()
    assert not any(entry.staged.exists() or entry.published.exists() for entry in made.books)


def test_custom_planning_creates_nothing_either(source_root, custom_dir, work_root):
    space = workspace(book(source_root, "A", ["1.mp3"], title="A"))
    made = plan(space, mp.custom_destination(custom_dir, work_root=work_root))
    assert listing(custom_dir) == set()
    assert not work_root.exists()
    assert made.books[0].published.parent == custom_dir


def test_the_plan_holds_the_capture_with_the_same_snapshot_objects(source_root, reserve):
    space = workspace(book(source_root, "A", ["1.mp3"], title="A"))
    made = plan(space, mp.standard_destination(reserve()))
    book_id, snapshot = made.capture.runs[0]
    assert made.books[0].snapshot is snapshot
    assert made.book_for(book_id) is made.books[0]


# --------------------------------------------------------------------------- #
# Structure
# --------------------------------------------------------------------------- #


def test_the_plan_module_imports_no_tk_process_media_or_ui():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
            modules |= {f"{node.module}.{alias.name}" for alias in node.names}
    for banned in ("tkinter", "subprocess", "threading", "queue", "shutil", "tempfile",
                   "wave", "json", "shared.ffmpeg_utils", "shared.subprocess_utils",
                   "shared.ui_theme", "shared.job_ui", "shared.import_coordination",
                   "shared.image_capabilities", "shared.metadata", "shared.numbering",
                   "PIL", "mutagen", "mp3_tools.m4b_maker", "mp3_tools.mp3_plan",
                   "mp3_tools.mp3_workflow", "mp3_tools.mp3_processing", "mp3_tools.mp3_tool",
                   "mp3_tools.m4b_artwork", "mp3_tools.m4b_numbering"):
        assert banned not in modules, banned
    for required in ("shared.output_paths", "shared.book_workspace", "shared.importing",
                     "mp3_tools.m4b_maker_workflow"):
        assert required in modules, required
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    for write in ("save", "write_bytes", "write_text", "mkdir", "mkdtemp", "unlink",
                  "rename", "replace", "rmtree", "touch", "open", "run", "Popen"):
        assert write not in called, write
    declared = {node.name for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    for later_phase in ("prepare_staging", "publish_book", "discard_staging", "run_fast",
                        "run_safe", "normalize_to_wav", "SuccessNumbers", "allocate"):
        assert later_phase not in declared, later_phase


def test_the_plan_module_is_registered_as_a_plan3_adopter():
    from test_plan3_boundaries import ADOPTED

    assert "mp3_tools/m4b_maker_plan.py" in ADOPTED


def test_the_maker_panel_is_still_byte_identical():
    from test_plan6_boundaries import PHASE0_PANEL_HASHES, sha256_as_checked_out_on_windows

    panel = UNIVERSAL / "mp3_tools" / "m4b_maker.py"
    assert sha256_as_checked_out_on_windows(panel) == PHASE0_PANEL_HASHES["mp3_tools/m4b_maker.py"]
    assert "m4b_maker_plan" not in panel.read_text(encoding="utf-8")
