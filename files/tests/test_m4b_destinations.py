"""Provenance-aware output planning — v0.6.2 Plan 5, Phase 8.

Phase 7B kept every occurrence's provenance; this is where it is spent. The
placement contract under test is the approved one:

* individually chosen **whole-book** files land **flat** in the run directory (31A);
* a **split** occurrence gets one book folder named for its source's stem, at the
  place its own provenance puts it — the **Phase 16 maintainer supersession** of
  the split half of D3/31A, after a real 12-book split run put 353 chapter MP3s
  flat in one folder, interleaved by book, 53 of them needing a collision suffix;
* one folder root **mirrors** its relative hierarchy (7A);
* several folder roots get **collision-safe named containers** (41A);
* every split segment lands wherever *its own* occurrence belongs.

**What these tests are really guarding.** Two of them carry the weight. One
proves a mixed run shares a single ``DestinationPlanner``, because a per-group
planner would let a flat output and a mirrored output claim the same path while
each tracker believed it was safe. The other proves two deliberate duplicates of
one file stay two occurrences with two independently planned destination sets —
a bridge that keyed on ``Path`` would silently merge them.

Nothing here reads media, probes a source, or creates a directory. Sources are
generated placeholders under ``tmp_path``; planning creates no file, so most
tests need no file to exist at all.
"""

from __future__ import annotations

import ast
from pathlib import Path, PurePath

import pytest

from shared.importing import (
    IdFactory,
    ImportedFile,
    ImportRoot,
    RootKind,
    capture_identity,
    planning_groups,
)
from shared.output_paths import DestinationPlanner, UnsafePathError

from mp3_tools import m4b_destinations
from mp3_tools.m4b_destinations import PlannedOccurrence, plan_outputs

MODULE_PATH = Path(m4b_destinations.__file__)


# --------------------------------------------------------------------------- #
# Building frozen occurrences without touching the manager
# --------------------------------------------------------------------------- #

_ids = IdFactory("occ-")


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not an audiobook", encoding="utf-8")
    return path


def direct_root(order: int = 0) -> ImportRoot:
    return ImportRoot(f"direct-{order}", None, order, RootKind.DIRECT_FILES)


def folder_root(path: Path, order: int = 0, root_id: str | None = None) -> ImportRoot:
    return ImportRoot(root_id or f"root-{order}", path, order, RootKind.FOLDER)


def occurrence(path: Path, root: ImportRoot, relative: PurePath | None = None) -> ImportedFile:
    """One frozen occurrence. Every call mints a fresh occurrence id."""
    import os

    if root.kind is RootKind.FOLDER and relative is None:
        relative = PurePath(path.name)
    return ImportedFile(
        occurrence_id=_ids.next_id("occ"),
        path=path,
        source_root=root,
        relative_path=relative,
        supported_type_id="m4b",
        identity=capture_identity(path, os.lstat(path)),
    )


def plan(entries, requested, run_root: Path, planner=None):
    tracker = planner if planner is not None else DestinationPlanner(run_root)
    return plan_outputs(entries, requested, run_root=run_root, planner=tracker)


def split_plan(entries, requested, run_root: Path, planner=None):
    """Plan a **split** run, which is what puts each book in its own folder."""
    tracker = planner if planner is not None else DestinationPlanner(run_root)
    return plan_outputs(entries, requested, run_root=run_root, planner=tracker,
                        split=True)


def whole(entries) -> dict[str, tuple[str, ...]]:
    """One whole-book output name per occurrence."""
    return {e.occurrence_id: (f"{e.path.stem}.mp3",) for e in entries}


def rel(run_root: Path, planned: PlannedOccurrence) -> list[str]:
    return [str(d.relative_to(run_root)).replace("\\", "/") for d in planned.destinations]


@pytest.fixture()
def run_root(tmp_path: Path) -> Path:
    root = tmp_path / "out" / "M4B-Converter-1"
    root.mkdir(parents=True)
    return root


# --------------------------------------------------------------------------- #
# Direct files — flat, Decision 31A
# --------------------------------------------------------------------------- #


def test_one_direct_whole_output_lands_in_the_run_root(tmp_path, run_root):
    entry = occurrence(touch(tmp_path / "src" / "Book.m4b"), direct_root())
    planned = plan([entry], whole([entry]), run_root)
    assert rel(run_root, planned[0]) == ["Book.mp3"]


def test_several_direct_files_all_land_in_the_run_root(tmp_path, run_root):
    entries = [occurrence(touch(tmp_path / "src" / n), direct_root())
               for n in ("A.m4b", "B.m4b", "C.m4b")]
    planned = plan(entries, whole(entries), run_root)
    assert [rel(run_root, p)[0] for p in planned] == ["A.mp3", "B.mp3", "C.mp3"]


def test_a_direct_split_gets_one_folder_named_for_its_source(tmp_path, run_root):
    """Phase 16 supersession. Was ``..._stays_flat_and_invents_no_per_book_folder``.

    The folder is the source's **stem**: ``Book.m4b`` is a book called *Book*,
    so only the final extension is dropped before the shared sanitiser sees it.
    """
    entry = occurrence(touch(tmp_path / "src" / "Book.m4b"), direct_root())
    names = ("01 - Intro.mp3", "02 - Chapter One.mp3", "03 - Chapter Two.mp3")
    planned = split_plan([entry], {entry.occurrence_id: names}, run_root)
    assert rel(run_root, planned[0]) == [f"Book/{n}" for n in names]
    assert {d.parent for d in planned[0].destinations} == {run_root / "Book"}


def test_a_whole_run_is_untouched_by_the_split_container_rule(tmp_path, run_root):
    """The half of D3/31A the maintainer kept: whole books stay flat."""
    entries = [occurrence(touch(tmp_path / "src" / n), direct_root())
               for n in ("A.m4b", "B.m4b")]
    planned = plan(entries, whole(entries), run_root)
    assert [rel(run_root, p)[0] for p in planned] == ["A.mp3", "B.mp3"]
    assert all(d.parent == run_root for p in planned for d in p.destinations)


def test_a_chapterless_split_item_still_gets_its_book_folder(tmp_path, run_root):
    """One output, but a split run, so it belongs with the others."""
    entry = occurrence(touch(tmp_path / "src" / "Whole Book.m4b"), direct_root())
    planned = split_plan([entry], {entry.occurrence_id: ("Whole Book.mp3",)}, run_root)
    assert rel(run_root, planned[0]) == ["Whole Book/Whole Book.mp3"]


def test_two_different_sources_with_the_same_stem_get_separate_folders(tmp_path, run_root):
    a = occurrence(touch(tmp_path / "one" / "Book.m4b"), direct_root())
    b = occurrence(touch(tmp_path / "two" / "Book.m4b"), direct_root())
    names = ("01 - Intro.mp3", "02 - Two.mp3")
    planned = split_plan([a, b], {a.occurrence_id: names, b.occurrence_id: names},
                         run_root)
    assert rel(run_root, planned[0]) == [f"Book/{n}" for n in names]
    assert rel(run_root, planned[1]) == [f"Book-1/{n}" for n in names]


def test_two_duplicate_occurrences_of_one_file_get_separate_folders(tmp_path, run_root):
    """Occurrence identity, not path: one file added twice is two books here."""
    source = touch(tmp_path / "src" / "Book.m4b")
    a = occurrence(source, direct_root())
    b = occurrence(source, direct_root())
    assert a.occurrence_id != b.occurrence_id
    names = ("01 - Intro.mp3",)
    planned = split_plan([a, b], {a.occurrence_id: names, b.occurrence_id: names},
                         run_root)
    assert rel(run_root, planned[0]) == ["Book/01 - Intro.mp3"]
    assert rel(run_root, planned[1]) == ["Book-1/01 - Intro.mp3"]


def test_stems_that_sanitise_onto_each_other_still_get_separate_folders(tmp_path, run_root):
    """Two names the sanitiser cannot tell apart must not share one folder."""
    a = occurrence(touch(tmp_path / "one" / "Book?.m4b"), direct_root())
    b = occurrence(touch(tmp_path / "two" / "Book_.m4b"), direct_root())
    names = ("01 - Intro.mp3",)
    planned = split_plan([a, b], {a.occurrence_id: names, b.occurrence_id: names},
                         run_root)
    first = planned[0].destinations[0].parent
    second = planned[1].destinations[0].parent
    assert first != second, (first, second)


def test_a_segment_name_collision_cannot_escape_its_book_folder(tmp_path, run_root):
    """Two segments of one book asking for one name stay inside that book."""
    entry = occurrence(touch(tmp_path / "src" / "Book.m4b"), direct_root())
    names = ("01 - Same.mp3", "01 - Same.mp3", "02 - Other.mp3")
    planned = split_plan([entry], {entry.occurrence_id: names}, run_root)
    assert {d.parent for d in planned[0].destinations} == {run_root / "Book"}
    assert len({d for d in planned[0].destinations}) == 3, "each got its own path"


def test_two_direct_books_with_identical_segment_names_collide_safely(tmp_path, run_root):
    a = occurrence(touch(tmp_path / "one" / "Book.m4b"), direct_root())
    b = occurrence(touch(tmp_path / "two" / "Book.m4b"), direct_root())
    names = ("01 - Intro.mp3",)
    planned = plan([a, b], {a.occurrence_id: names, b.occurrence_id: names}, run_root)
    assert rel(run_root, planned[0]) == ["01 - Intro.mp3"]
    assert rel(run_root, planned[1]) == ["01 - Intro-1.mp3"]


def test_identical_direct_whole_names_collide_safely(tmp_path, run_root):
    a = occurrence(touch(tmp_path / "one" / "Book.m4b"), direct_root())
    b = occurrence(touch(tmp_path / "two" / "Book.m4b"), direct_root())
    planned = plan([a, b], whole([a, b]), run_root)
    assert rel(run_root, planned[0]) == ["Book.mp3"]
    assert rel(run_root, planned[1]) == ["Book-1.mp3"]


# --------------------------------------------------------------------------- #
# One folder root — mirrored, Decision 7A
# --------------------------------------------------------------------------- #


@pytest.fixture()
def library(tmp_path: Path):
    root = tmp_path / "Library"
    top = touch(root / "Top.m4b")
    nested = touch(root / "Series" / "Nested.m4b")
    deep = touch(root / "Series" / "Part A" / "Deep.m4b")
    source = folder_root(root)
    return root, [
        occurrence(top, source, PurePath("Top.m4b")),
        occurrence(nested, source, PurePath("Series/Nested.m4b")),
        occurrence(deep, source, PurePath("Series/Part A/Deep.m4b")),
    ]


def test_one_root_mirrors_the_relative_hierarchy(library, run_root):
    _root, entries = library
    planned = plan(entries, whole(entries), run_root)
    assert [rel(run_root, p)[0] for p in planned] == [
        "Top.mp3", "Series/Nested.mp3", "Series/Part A/Deep.mp3"]


def test_a_root_level_source_lands_directly_at_the_run_root(library, run_root):
    _root, entries = library
    planned = plan(entries, whole(entries), run_root)
    assert planned[0].destination.parent == run_root


def test_every_split_segment_shares_its_owning_source_location(library, run_root):
    """Segments belong where the *item* belongs — now inside that book's folder.

    Phase 16 supersession: mirroring decides the parent, then the book folder
    goes inside it, then the segments go inside that.
    """
    _root, entries = library
    nested = entries[1]
    names = ("01 - A.mp3", "02 - B.mp3", "03 - C.mp3")
    planned = split_plan([nested], {nested.occurrence_id: names}, run_root)
    assert rel(run_root, planned[0]) == [f"Series/Nested/{n}" for n in names]
    assert {d.parent for d in planned[0].destinations} == {
        run_root / "Series" / "Nested"}


def test_a_mirrored_split_puts_the_book_folder_under_its_mirrored_parent(library, run_root):
    """Was ``..._invents_no_per_book_directory``. Phase 16 supersession."""
    _root, entries = library
    deep = entries[2]
    planned = split_plan([deep], {deep.occurrence_id: ("01 - A.mp3",)}, run_root)
    assert planned[0].destination.parent == run_root / "Series" / "Part A" / "Deep"


def test_a_root_level_split_source_gets_its_folder_at_the_run_root(library, run_root):
    """A book directly inside the chosen folder: ``run/Top/…``, not ``run/…``."""
    _root, entries = library
    top = entries[0]
    planned = split_plan([top], {top.occurrence_id: ("01 - A.mp3", "02 - B.mp3")},
                         run_root)
    assert rel(run_root, planned[0]) == ["Top/01 - A.mp3", "Top/02 - B.mp3"]


# --------------------------------------------------------------------------- #
# Several folder roots — named containers, Decision 41A
# --------------------------------------------------------------------------- #


@pytest.fixture()
def two_roots(tmp_path: Path):
    first = tmp_path / "A" / "Books"
    second = tmp_path / "B" / "Books"
    a = touch(first / "One.m4b")
    b = touch(second / "Deep" / "Two.m4b")
    return (
        [occurrence(a, folder_root(first, 0, "root-a"), PurePath("One.m4b")),
         occurrence(b, folder_root(second, 1, "root-b"), PurePath("Deep/Two.m4b"))],
    )


def test_two_roots_with_the_same_basename_get_distinct_containers(two_roots, run_root):
    """Two source trees must never merge because their roots share a name."""
    entries, = two_roots
    planned = plan(entries, whole(entries), run_root)
    assert rel(run_root, planned[0]) == ["Books/One.mp3"]
    assert rel(run_root, planned[1]) == ["Books-1/Deep/Two.mp3"]


def test_multi_root_keeps_nested_hierarchy_under_its_container(two_roots, run_root):
    entries, = two_roots
    planned = plan(entries, whole(entries), run_root)
    assert planned[1].destination.parent == run_root / "Books-1" / "Deep"


def test_multi_root_split_segments_stay_with_their_owning_root(two_roots, run_root):
    """Root container, then mirrored parent, then the book folder, then segments.

    Phase 16 supersession: the multi-root collision containers (41A) are decided
    first and unchanged; the book folder is added at the item's mirrored place.
    """
    entries, = two_roots
    names = ("01 - A.mp3", "02 - B.mp3")
    planned = split_plan(entries, {entries[0].occurrence_id: names,
                                   entries[1].occurrence_id: names}, run_root)
    assert rel(run_root, planned[0]) == [f"Books/One/{n}" for n in names]
    assert rel(run_root, planned[1]) == [f"Books-1/Deep/Two/{n}" for n in names]


def test_root_order_follows_the_user_not_the_alphabet(tmp_path, run_root):
    second = touch(tmp_path / "Z" / "Zed" / "z.m4b")
    first = touch(tmp_path / "A" / "Alpha" / "a.m4b")
    entries = [
        occurrence(second, folder_root(tmp_path / "Z" / "Zed", 0, "root-z"), PurePath("z.m4b")),
        occurrence(first, folder_root(tmp_path / "A" / "Alpha", 1, "root-a"), PurePath("a.m4b")),
    ]
    planned = plan(entries, whole(entries), run_root)
    assert rel(run_root, planned[0]) == ["Zed/z.mp3"]
    assert rel(run_root, planned[1]) == ["Alpha/a.mp3"]


# --------------------------------------------------------------------------- #
# Mixed runs — one collision domain
# --------------------------------------------------------------------------- #


def test_direct_and_folder_occurrences_plan_in_one_run(tmp_path, run_root):
    picked = occurrence(touch(tmp_path / "picked" / "Chosen.m4b"), direct_root())
    root = tmp_path / "Library"
    inside = occurrence(touch(root / "Book.m4b"), folder_root(root), PurePath("Book.m4b"))
    planned = plan([picked, inside], whole([picked, inside]), run_root)
    assert rel(run_root, planned[0]) == ["Chosen.mp3"]
    assert rel(run_root, planned[1]) == ["Book.mp3"]


def test_one_planner_covers_flat_and_mirrored_halves(tmp_path, run_root):
    """The load-bearing collision test.

    A directly chosen ``Book.m4b`` and a root-level folder ``Book.m4b`` both want
    ``Book.mp3`` in the run root. Separate planners would each believe that name
    was free.
    """
    picked = occurrence(touch(tmp_path / "picked" / "Book.m4b"), direct_root())
    root = tmp_path / "Library"
    inside = occurrence(touch(root / "Book.m4b"), folder_root(root), PurePath("Book.m4b"))

    planned = plan([picked, inside], whole([picked, inside]), run_root)
    destinations = [p.destination for p in planned]
    assert len(set(destinations)) == 2, destinations
    assert rel(run_root, planned[0]) == ["Book.mp3"]
    assert rel(run_root, planned[1]) == ["Book-1.mp3"]


def test_planning_is_deterministic_for_the_same_frozen_input(tmp_path, run_root):
    picked = occurrence(touch(tmp_path / "picked" / "Book.m4b"), direct_root())
    root = tmp_path / "Library"
    inside = occurrence(touch(root / "Book.m4b"), folder_root(root), PurePath("Book.m4b"))
    entries = [picked, inside]

    first = plan(entries, whole(entries), run_root, planner=DestinationPlanner(run_root))
    second = plan(entries, whole(entries), run_root, planner=DestinationPlanner(run_root))
    assert [p.destinations for p in first] == [p.destinations for p in second]


# --------------------------------------------------------------------------- #
# Occurrence identity
# --------------------------------------------------------------------------- #


def test_two_deliberate_duplicates_stay_two_occurrences(tmp_path, run_root):
    """A bridge keyed on ``Path`` would merge these two into one."""
    source = touch(tmp_path / "src" / "Book.m4b")
    root = direct_root()
    a, b = occurrence(source, root), occurrence(source, root)
    assert a.path == b.path and a.occurrence_id != b.occurrence_id

    planned = plan([a, b], whole([a, b]), run_root)
    assert len(planned) == 2
    assert planned[0].occurrence_id == a.occurrence_id
    assert planned[1].occurrence_id == b.occurrence_id
    assert planned[0].destinations != planned[1].destinations
    assert rel(run_root, planned[0]) == ["Book.mp3"]
    assert rel(run_root, planned[1]) == ["Book-1.mp3"]


def test_duplicate_occurrences_each_get_their_own_segment_set(tmp_path, run_root):
    source = touch(tmp_path / "src" / "Book.m4b")
    root = direct_root()
    a, b = occurrence(source, root), occurrence(source, root)
    names = ("01 - Intro.mp3", "02 - One.mp3")
    planned = plan([a, b], {a.occurrence_id: names, b.occurrence_id: names}, run_root)
    assert rel(run_root, planned[0]) == ["01 - Intro.mp3", "02 - One.mp3"]
    assert rel(run_root, planned[1]) == ["01 - Intro-1.mp3", "02 - One-1.mp3"]


def test_requested_names_stay_with_the_right_occurrence(tmp_path, run_root):
    a = occurrence(touch(tmp_path / "src" / "A.m4b"), direct_root())
    b = occurrence(touch(tmp_path / "src" / "B.m4b"), direct_root())
    planned = plan([a, b], {a.occurrence_id: ("from-a.mp3",),
                            b.occurrence_id: ("from-b.mp3",)}, run_root)
    by_id = {p.occurrence_id: rel(run_root, p) for p in planned}
    assert by_id[a.occurrence_id] == ["from-a.mp3"]
    assert by_id[b.occurrence_id] == ["from-b.mp3"]


def test_the_result_carries_occurrence_ids_and_sources(tmp_path, run_root):
    entry = occurrence(touch(tmp_path / "src" / "Book.m4b"), direct_root())
    planned = plan([entry], whole([entry]), run_root)
    assert planned[0].occurrence_id == entry.occurrence_id
    assert planned[0].source == entry.path


def test_an_occurrence_with_no_requested_names_is_refused(tmp_path, run_root):
    entry = occurrence(touch(tmp_path / "src" / "Book.m4b"), direct_root())
    with pytest.raises(ValueError):
        plan([entry], {entry.occurrence_id: ()}, run_root)
    with pytest.raises(ValueError):
        plan([entry], {}, run_root)


def test_an_empty_queue_plans_nothing(run_root):
    assert plan([], {}, run_root) == ()


# --------------------------------------------------------------------------- #
# Safety
# --------------------------------------------------------------------------- #


def test_a_destination_equal_to_an_input_is_refused(tmp_path):
    """The run root is the source folder and the name matches: refuse."""
    source = touch(tmp_path / "Book.mp3")
    entry = occurrence(source, direct_root())
    with pytest.raises(UnsafePathError):
        plan([entry], {entry.occurrence_id: ("Book.mp3",)}, tmp_path,
             planner=DestinationPlanner(tmp_path, check_filesystem=False))


def test_every_destination_stays_under_the_run_root(library, run_root):
    _root, entries = library
    planned = plan(entries, whole(entries), run_root)
    for item in planned:
        for destination in item.destinations:
            assert destination.is_relative_to(run_root)


def test_no_destination_is_placed_inside_a_source_tree(library, run_root):
    source_root, entries = library
    planned = plan(entries, whole(entries), run_root)
    for item in planned:
        for destination in item.destinations:
            assert not destination.is_relative_to(source_root)


def test_an_existing_file_is_never_overwritten(tmp_path, run_root):
    entry = occurrence(touch(tmp_path / "src" / "Book.m4b"), direct_root())
    (run_root / "Book.mp3").write_text("already here", encoding="utf-8")
    planned = plan([entry], whole([entry]), run_root)
    assert rel(run_root, planned[0]) == ["Book-1.mp3"]
    assert (run_root / "Book.mp3").read_text(encoding="utf-8") == "already here"


def test_case_only_collisions_are_treated_as_collisions(tmp_path, run_root):
    a = occurrence(touch(tmp_path / "one" / "Book.m4b"), direct_root())
    b = occurrence(touch(tmp_path / "two" / "BOOK.m4b"), direct_root())
    planned = plan([a, b], whole([a, b]), run_root)
    assert planned[0].destination != planned[1].destination
    assert rel(run_root, planned[1]) == ["BOOK-1.mp3"]


def test_planning_creates_no_file_or_directory(library, run_root):
    _root, entries = library
    plan(entries, whole(entries), run_root)
    assert list(run_root.iterdir()) == []


def test_a_deep_mirrored_tree_is_represented_faithfully(tmp_path, run_root):
    """A long, deep relative path must survive or fail truthfully (§24)."""
    root = tmp_path / "Deep"
    parts = ["level-%02d" % n for n in range(8)]
    source = touch(root.joinpath(*parts) / "Book.m4b")
    entry = occurrence(source, folder_root(root),
                       PurePath(*parts, "Book.m4b"))
    planned = plan([entry], whole([entry]), run_root)
    assert rel(run_root, planned[0]) == ["/".join(parts) + "/Book.mp3"]


def test_a_long_segment_name_is_sanitised_by_the_shared_planner(tmp_path, run_root):
    entry = occurrence(touch(tmp_path / "src" / "Book.m4b"), direct_root())
    long_name = ("A" * 300) + ".mp3"
    planned = plan([entry], {entry.occurrence_id: (long_name,)}, run_root)
    name = planned[0].destination.name
    assert len(name) <= 255 and name.endswith(".mp3")


def test_the_local_division_is_cross_checked_against_the_shared_one(tmp_path, run_root):
    """The bucketing copy cannot drift from ``planning_groups`` unnoticed."""
    root = tmp_path / "Library"
    entry = occurrence(touch(root / "Book.m4b"), folder_root(root), PurePath("Book.m4b"))
    groups = planning_groups((entry,))
    assert groups.direct == ()
    assert groups.grouped == ((root, (entry.path,)),)

    calls: list = []
    original = m4b_destinations.planning_groups

    def watched(entries):
        calls.append(entries)
        return original(entries)

    m4b_destinations.planning_groups = watched
    try:
        plan([entry], whole([entry]), run_root)
    finally:
        m4b_destinations.planning_groups = original
    assert calls, "planning_groups must be consulted, not merely imitated"


# --------------------------------------------------------------------------- #
# Boundaries
# --------------------------------------------------------------------------- #


def tree() -> ast.Module:
    return ast.parse(MODULE_PATH.read_text(encoding="utf-8"), filename=str(MODULE_PATH))


def named() -> set[str]:
    parsed = tree()
    out = {n.id for n in ast.walk(parsed) if isinstance(n, ast.Name)}
    out |= {n.attr for n in ast.walk(parsed) if isinstance(n, ast.Attribute)}
    out |= {n.name for n in ast.walk(parsed)
            if isinstance(n, (ast.ClassDef, ast.FunctionDef))}
    return out


def test_the_shared_planners_are_consumed_not_reimplemented():
    defined = {n.name for n in ast.walk(tree())
               if isinstance(n, (ast.ClassDef, ast.FunctionDef))}
    for banned in ("plan_flat", "plan_mirrored", "plan_multi_root",
                   "DestinationPlanner", "planning_groups", "sanitize_component",
                   "assert_not_input"):
        assert banned not in defined, banned


def test_no_collision_or_sanitisation_logic_is_hand_rolled():
    literals = {n.value for n in ast.walk(tree())
                if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    for banned in ("-1", "-2", "{stem}-{index}"):
        assert banned not in literals, banned
    assert "casefold" not in named()


def test_no_chapter_probing_arrived_with_destination_planning():
    for banned in ("plan_timeline", "ChapterProbe", "probe_audio_stream",
                   "ffprobe", "read_chapter_titles", "segment_filename"):
        assert banned not in named(), banned


def test_no_phase_nine_or_later_vocabulary_arrived():
    for banned in ("JobController", "JobAdapter", "JobReporter", "RunResult",
                   "ConversionPlan", "ItemPlan", "SegmentPlan", "EtaEstimator",
                   "LockGroup", "Popen", "subprocess"):
        assert banned not in named(), banned


def test_the_module_is_media_free_and_tk_free():
    imported: set[str] = set()
    for node in ast.walk(tree()):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"__future__", "collections", "dataclasses", "pathlib", "shared"}
    for banned in ("tkinter", "subprocess", "threading", "os"):
        assert banned not in imported, banned
