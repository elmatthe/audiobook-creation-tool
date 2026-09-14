"""The frozen M4B Metadata Editor action plans — v0.6.4 Phase 8.

``mp3_tools/m4b_metadata_plan.py`` freezes **exact intent** for the three Editor
actions — Save Tags, Clear All Tags (keep chapters), Remove Series Numbering —
from the Phase 7 model's intent functions, together with one standard run and
flat, collision-safe staged/final paths through ``output_paths``. It keeps the
source observation, the Shared overrides, the Book edits and the action apart;
it never collapses them into "whatever the page shows". Nothing here copies,
writes, clears, allocates a number or starts a controller.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path, PurePath

import pytest

from shared import book_workspace, output_paths
from shared.book_workspace import (
    BookDisposition, BookJob, SharedMetadata, WorkspaceSnapshot, remove_book,
    set_shared_metadata,
)
from shared.importing import (
    IdFactory, ImportOptions, ImportedFile, ImportedFileSnapshot, ImportRoot, Revision,
)
from shared.job_control import RunSnapshot

from mp3_tools import m4b_metadata_plan as mp
from mp3_tools import m4b_metadata_workflow as wf
from mp3_tools.m4b_metadata_plan import (
    BookPlan, EditorAction, EditorRunOptions, PlanError, RunPlan,
)
from mp3_tools.m4b_metadata_workflow import ObservationStore

from test_importing import make_config
from test_m4b_metadata_workflow import _META, _ff, m4b, require_ffmpeg, vendor_series

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIVERSAL = REPO_ROOT / "scripts" / "Universal"
MODULE = UNIVERSAL / "mp3_tools" / "m4b_metadata_plan.py"

_IDS = IdFactory("ep-")


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def container(tmp_path_factory) -> Path:
    require_ffmpeg()
    work = tmp_path_factory.mktemp("editor-plan")
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


@pytest.fixture
def reserve(tmp_path: Path):
    counter = {"n": 0}

    def make(**_kw):
        counter["n"] += 1
        directory = tmp_path / "Outputs" / "M4B-Metadata-Outputs" / f"M4B-Metadata-{counter['n']}"
        directory.mkdir(parents=True)
        return output_paths.RunReservation(
            tool_key="m4b_metadata", base_directory=tmp_path / "Outputs",
            tool_directory=directory.parent, run_directory=directory, run_number=counter["n"])

    make.calls = counter  # type: ignore[attr-defined]
    return make


def imported(sources: Path, relative: str, path: Path) -> ImportedFile:
    occurrence = _IDS.next_id("occurrence")
    return ImportedFile(occurrence, path, ImportRoot("r", sources, 0), PurePath(relative),
                        wf.EDITOR_TYPE.type_id, f"id-{occurrence}-{relative.replace('/', '-')}")


def build(container, sources, *specs):
    """``specs``: (relative, tags dict) → a workspace of one Book per source, and its store."""
    entries = []
    for relative, tags in specs:
        path = m4b(container, sources / relative, **tags)
        entries.append(imported(sources, relative, path))
    result = wf.import_folder(wf.new_workspace(id_factory=_IDS),
                              ImportedFileSnapshot(Revision(1), tuple(entries)),
                              id_factory=_IDS, store=ObservationStore())
    return result.mutation.workspace, result.store


def shared_with(space: WorkspaceSnapshot, **values) -> WorkspaceSnapshot:
    return set_shared_metadata(
        space, SharedMetadata(fields=wf.SHARED_FIELDS, values=values)).workspace


def plan(space, store, reserve, action=EditorAction.SAVE_TAGS,
         options: EditorRunOptions | None = None) -> RunPlan:
    return mp.plan_run(
        space, store, action=action, options=options or EditorRunOptions(),
        reservation=reserve(), catalog=wf.EDITOR_CATALOG,
        import_options=ImportOptions.for_catalog(wf.EDITOR_CATALOG),
        effective_config=make_config(), id_factory=_IDS)


def listing(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*")}


# --------------------------------------------------------------------------- #
# Save Tags: only actual intended writes are frozen
# --------------------------------------------------------------------------- #


def test_unchanged_prefill_freezes_no_write(container, sources, reserve):
    space, store = build(container, sources, ("a.m4b", dict(title="Source T", artist="A",
                                                             series="Saga", series_part="2")))
    made = plan(space, store, reserve)
    assert made.action is EditorAction.SAVE_TAGS
    entry = made.books[0]
    assert isinstance(entry, BookPlan)
    assert entry.shared_overrides == {} and entry.book_edits == {}
    assert entry.writes == {}
    assert entry.artwork is None
    assert entry.chapter_edits == (None, None)
    assert entry.has_intent is False
    assert entry.observation.title == "Source T" and entry.observation.series == "Saga"


def test_blank_and_equal_book_values_preserve_but_a_changed_one_is_frozen(container, sources,
                                                                          reserve):
    space, store = build(container, sources, ("a.m4b", dict(title="Source T", album="Alb")))
    space = wf.set_book_field(space, "title", "").workspace
    space = wf.set_book_field(space, "album", "Alb").workspace
    space = wf.set_book_field(space, "artist", "New Author").workspace
    entry = plan(space, store, reserve).books[0]
    assert entry.book_edits == {"artist": "New Author"}
    assert entry.writes == {"artist": "New Author"}
    assert entry.has_intent


def test_populated_shared_is_an_override_and_clearing_it_restores(container, sources, reserve):
    space, store = build(container, sources, ("a.m4b", dict(artist="Source A")),
                         ("b.m4b", dict(artist="Other A")))
    space = wf.set_book_field(space, "artist", "Book A").workspace
    overridden = shared_with(space, artist="Shared A")
    made = plan(overridden, store, reserve)
    assert [entry.shared_overrides for entry in made.books] == [{"artist": "Shared A"}] * 2
    assert [entry.writes["artist"] for entry in made.books] == ["Shared A", "Shared A"]
    assert made.books[0].book_edits == {}, "a Shared override is not also a Book edit"
    restored = plan(shared_with(overridden), store, reserve)
    assert restored.books[0].shared_overrides == {}
    assert restored.books[0].book_edits == {"artist": "Book A"}
    assert restored.books[1].writes == {}


def test_blank_shared_is_no_global_write(container, sources, reserve):
    space, store = build(container, sources, ("a.m4b", dict(artist="Same")),
                         ("b.m4b", dict(artist="Same")))
    made = plan(space, store, reserve)
    assert all(entry.writes == {} for entry in made.books)


def test_observed_vendor_series_is_not_migrated_but_an_explicit_edit_is(container, sources,
                                                                        reserve):
    path = vendor_series(m4b(container, sources / "v.m4b", album="Alb"), name="Tone Saga",
                         part="3")
    entry_file = imported(sources, "v.m4b", path)
    result = wf.import_folder(wf.new_workspace(id_factory=_IDS),
                              ImportedFileSnapshot(Revision(1), (entry_file,)),
                              id_factory=_IDS, store=ObservationStore())
    space, store = result.mutation.workspace, result.store
    untouched = plan(space, store, reserve).books[0]
    assert untouched.observation.series_source == "freeform:com.pilabor.tone"
    assert "series" not in untouched.writes, "displayed is not written"
    retyped = wf.set_book_field(space, "series", "Tone Saga").workspace
    assert "series" not in plan(retyped, store, reserve).books[0].writes
    edited = wf.set_book_field(space, "series", "Canon Saga").workspace
    assert plan(edited, store, reserve).books[0].writes == {"series": "Canon Saga"}


def test_artwork_replacement_is_frozen_only_when_explicit(container, sources, reserve, tmp_path):
    from PIL import Image

    art = tmp_path / "cover.png"
    Image.new("RGB", (8, 8), (9, 9, 9)).save(art, format="PNG")
    space, store = build(container, sources, ("a.m4b", {}), ("b.m4b", {}))
    assert all(entry.artwork is None for entry in plan(space, store, reserve).books)
    assert store.for_book(space.books[0]).has_cover is True
    book_only = wf.set_book_field(space, "artwork", str(art)).workspace
    made = plan(book_only, store, reserve)
    assert [entry.artwork for entry in made.books] == [str(art), None]
    everywhere = shared_with(space, artwork=str(art))
    assert [entry.artwork for entry in plan(everywhere, store, reserve).books] == [str(art)] * 2


def test_positional_chapter_edits_preserve_blank_and_equal_lines(container, sources, reserve):
    space, store = build(container, sources, ("a.m4b", {}))
    space = wf.set_book_field(space, "chapter_titles", "\nEnd\nExtra").workspace
    entry = plan(space, store, reserve).books[0]
    assert entry.chapter_edits == (None, "End")
    assert entry.has_intent
    same = wf.set_book_field(space, "chapter_titles", "Opening\nClosing").workspace
    assert plan(same, store, reserve).books[0].chapter_edits == (None, None)


# --------------------------------------------------------------------------- #
# Clear All Tags: reapply only what was explicitly asked for
# --------------------------------------------------------------------------- #


def test_clear_all_never_reapplies_unchanged_prefill(container, sources, reserve):
    space, store = build(container, sources, ("a.m4b", dict(title="Source T", artist="A",
                                                             series="Saga")))
    entry = plan(space, store, reserve, EditorAction.CLEAR_ALL_TAGS).books[0]
    assert entry.action is EditorAction.CLEAR_ALL_TAGS
    assert entry.writes == {} and entry.artwork is None
    assert entry.chapter_edits == (None, None)
    assert entry.has_intent, "clearing is itself the intent"


def test_clear_all_reapplies_explicit_shared_book_and_artwork_only(container, sources, reserve,
                                                                   tmp_path):
    from PIL import Image

    art = tmp_path / "cover.png"
    Image.new("RGB", (8, 8), (9, 9, 9)).save(art, format="PNG")
    space, store = build(container, sources, ("a.m4b", dict(title="Source T", artist="A")))
    space = wf.set_book_field(space, "title", "Kept Title").workspace
    space = wf.set_book_field(space, "artist", "A").workspace          # equal → not reapplied
    space = wf.set_book_field(space, "chapter_titles", "\nEnd").workspace
    space = shared_with(space, genre="Shared Genre", artwork=str(art))
    entry = plan(space, store, reserve, EditorAction.CLEAR_ALL_TAGS).books[0]
    assert entry.shared_overrides == {"genre": "Shared Genre"}
    assert entry.book_edits == {"title": "Kept Title"}
    assert entry.writes == {"title": "Kept Title", "genre": "Shared Genre"}
    assert entry.artwork == str(art)
    assert entry.chapter_edits == (None, "End")
    assert entry.observation.has_cover is True, "the source fact is kept beside the intent"


# --------------------------------------------------------------------------- #
# Remove Series Numbering: removal intent only
# --------------------------------------------------------------------------- #


def test_remove_series_numbering_freezes_nothing_but_the_action(container, sources, reserve,
                                                                tmp_path):
    from PIL import Image

    art = tmp_path / "cover.png"
    Image.new("RGB", (8, 8), (9, 9, 9)).save(art, format="PNG")
    space, store = build(container, sources, ("a.m4b", dict(series="Saga", series_part="4",
                                                             title="T")))
    space = wf.set_book_field(space, "title", "Pending Title").workspace
    space = wf.set_book_field(space, "artwork", str(art)).workspace
    space = wf.set_book_field(space, "chapter_titles", "New\nEnd").workspace
    space = shared_with(space, artist="Pending Shared")
    made = plan(space, store, reserve, EditorAction.REMOVE_SERIES_NUMBERING,
                EditorRunOptions(auto_number=True, start_part_text="3"))
    entry = made.books[0]
    assert entry.action is EditorAction.REMOVE_SERIES_NUMBERING
    assert entry.shared_overrides == {} and entry.book_edits == {} and entry.writes == {}
    assert entry.artwork is None
    assert entry.chapter_edits == ()
    assert entry.has_intent
    assert entry.observation.series == "Saga" and entry.observation.series_part == "4", (
        "the Series Name is a source fact the action preserves; only numbering goes")
    assert made.auto_number is False and made.start_part == 1, (
        "auto-numbering is a Save concern; removal never numbers")


# --------------------------------------------------------------------------- #
# Series auto-number: configuration frozen, no number assigned
# --------------------------------------------------------------------------- #


def test_auto_number_freezes_the_start_part_without_assigning_numbers(container, sources,
                                                                     reserve):
    space, store = build(container, sources, ("a.m4b", dict(series_part="7")),
                         ("b.m4b", {}))
    off = plan(space, store, reserve)
    assert off.auto_number is False and off.start_part == 1
    assert all("series_part" not in entry.writes for entry in off.books)
    on = plan(space, store, reserve, options=EditorRunOptions(auto_number=True,
                                                              start_part_text=" 5 "))
    assert on.auto_number is True and on.start_part == 5
    assert all("series_part" not in entry.writes for entry in on.books)
    assert not any(hasattr(entry, name) for entry in on.books
                   for name in ("part", "allocated_part", "series_number"))
    assert on.has_intent, "auto-numbering alone is something to do"
    with pytest.raises(wf.EditorValueError):
        plan(space, store, reserve, options=EditorRunOptions(auto_number=True,
                                                             start_part_text="0"))


# --------------------------------------------------------------------------- #
# Outputs: one run, flat, collision-safe, extension kept, nothing created
# --------------------------------------------------------------------------- #


def test_one_reservation_flat_outputs_and_deterministic_collisions(container, sources, reserve):
    space, store = build(container, sources, ("One/Book.m4b", {}), ("Two/Book.m4b", {}),
                         ("Three/other.m4a", {}), ("Four/clip.mp4", {}))
    made = plan(space, store, reserve)
    assert reserve.calls["n"] == 1
    assert made.run_directory == made.reservation.run_directory
    assert [entry.published.parent for entry in made.books] == [made.run_directory] * 4
    assert [entry.published.name for entry in made.books] == [
        "Book.m4b", "Book-1.m4b", "other.m4a", "clip.mp4"]
    assert made.work_root == made.run_directory / mp.WORK_DIRNAME
    for entry in made.books:
        assert entry.staging_dir.parent == made.work_root
        assert entry.staged == entry.staging_dir / entry.published.name
        assert entry.staged.suffix == entry.source.suffix
    again = plan(space, store, reserve)
    assert [e.published.name for e in again.books] == [e.published.name for e in made.books]


def test_an_existing_output_is_never_overwritten(container, sources, reserve):
    reservation = reserve()
    (reservation.run_directory / "Book.m4b").write_bytes(b"someone else's")
    space, store = build(container, sources, ("Book.m4b", {}))
    made = mp.plan_run(space, store, action=EditorAction.SAVE_TAGS, options=EditorRunOptions(),
                       reservation=reservation, catalog=wf.EDITOR_CATALOG,
                       import_options=ImportOptions.for_catalog(wf.EDITOR_CATALOG),
                       effective_config=make_config(), id_factory=_IDS)
    assert made.books[0].published.name == "Book-1.m4b"
    assert (reservation.run_directory / "Book.m4b").read_bytes() == b"someone else's"


def test_a_run_inside_a_source_tree_is_refused(container, sources, tmp_path):
    inside = sources / "Book" / "M4B-Metadata-1"
    inside.mkdir(parents=True)
    reservation = output_paths.RunReservation(
        tool_key="m4b_metadata", base_directory=sources, tool_directory=inside.parent,
        run_directory=inside, run_number=1)
    space, store = build(container, sources, ("Book/a.m4b", {}))
    with pytest.raises(output_paths.UnsafePathError):
        mp.plan_run(space, store, action=EditorAction.SAVE_TAGS, options=EditorRunOptions(),
                    reservation=reservation, catalog=wf.EDITOR_CATALOG,
                    import_options=ImportOptions.for_catalog(wf.EDITOR_CATALOG),
                    effective_config=make_config(), id_factory=_IDS)


def test_planning_creates_no_file_and_copies_nothing(container, sources, reserve):
    space, store = build(container, sources, ("a.m4b", {}), ("b.m4b", {}))
    before = listing(sources)
    reservation = reserve()
    made = mp.plan_run(space, store, action=EditorAction.CLEAR_ALL_TAGS,
                       options=EditorRunOptions(), reservation=reservation,
                       catalog=wf.EDITOR_CATALOG,
                       import_options=ImportOptions.for_catalog(wf.EDITOR_CATALOG),
                       effective_config=make_config(), id_factory=_IDS)
    assert listing(reservation.run_directory) == set()
    assert listing(sources) == before
    assert not made.work_root.exists()
    assert not any(e.staged.exists() or e.published.exists() for e in made.books)


# --------------------------------------------------------------------------- #
# Unreadable sources and immutability
# --------------------------------------------------------------------------- #


def test_an_unreadable_source_is_skipped_invalid_and_keeps_its_identity(container, sources,
                                                                       reserve):
    good_path = m4b(container, sources / "good.m4b", title="Good")
    junk = sources / "junk.m4b"
    junk.write_bytes(b"not an mp4")
    good, bad = imported(sources, "good.m4b", good_path), imported(sources, "junk.m4b", junk)
    result = wf.import_folder(wf.new_workspace(id_factory=_IDS),
                              ImportedFileSnapshot(Revision(1), (good, bad)),
                              id_factory=_IDS, store=ObservationStore())
    space, store = result.mutation.workspace, result.store
    made = plan(space, store, reserve)
    assert [entry.book_id for entry in made.books] == [space.books[0].book_id]
    skipped = dict(made.capture.skipped)
    assert skipped == {space.books[1].book_id: BookDisposition.SKIPPED_INVALID}
    assert made.book_for(space.books[1].book_id) is None
    assert made.observation_for(space.books[1].book_id).readable is False
    assert made.observation_for(space.books[1].book_id).error


def test_later_workspace_edits_cannot_change_the_plan(container, sources, reserve):
    space, store = build(container, sources, ("a.m4b", dict(title="Before")),
                         ("b.m4b", {}))
    space = wf.set_book_field(space, "title", "Edited").workspace
    made = plan(space, store, reserve)
    before = (tuple(e.writes for e in made.books), tuple(e.published for e in made.books),
              tuple(e.chapter_edits for e in made.books), tuple(e.artwork for e in made.books),
              made.auto_number, made.start_part)
    edited = wf.set_book_field(space, "title", "Changed Again").workspace
    edited = wf.set_book_field(edited, "chapter_titles", "X\nY").workspace
    edited = shared_with(edited, artist="Late", artwork=str(sources / "late.png"))
    edited = remove_book(edited, id_factory=_IDS).workspace
    grown = store.with_observations((dataclasses.replace(store.for_book(space.books[0]),
                                                         title="Rewritten"),))
    assert grown.for_book(space.books[0]).title == "Rewritten"
    assert (tuple(e.writes for e in made.books), tuple(e.published for e in made.books),
            tuple(e.chapter_edits for e in made.books), tuple(e.artwork for e in made.books),
            made.auto_number, made.start_part) == before
    assert made.books[0].observation.title == "Before"
    assert len(made.books) == 2


def test_plan_structures_are_frozen_and_hold_no_live_state(container, sources, reserve):
    space, store = build(container, sources, ("a.m4b", {}))
    made = plan(space, store, reserve)
    for frozen in (made, made.books[0], made.books[0].observation):
        assert dataclasses.is_dataclass(frozen) and frozen.__dataclass_params__.frozen
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(frozen, "book_id", "x")
    with pytest.raises(TypeError):
        made.books[0].writes["title"] = "x"  # type: ignore[index]
    assert isinstance(made.books[0].snapshot, RunSnapshot)
    assert made.books[0].snapshot is made.capture.runs[0][1]

    def walk(value, seen=None):
        seen = set() if seen is None else seen
        if id(value) in seen:
            return
        seen.add(id(value))
        assert not type(value).__module__.startswith("tkinter"), type(value)
        assert not callable(value) or isinstance(value, type), type(value)
        assert not isinstance(value, (WorkspaceSnapshot, BookJob, ObservationStore)), type(value)
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            for f in dataclasses.fields(value):
                walk(getattr(value, f.name), seen)
        elif isinstance(value, (tuple, list, frozenset)):
            for item in value:
                walk(item, seen)
        elif isinstance(value, dict) or hasattr(value, "items"):
            for item in value.items():
                walk(item[1], seen)

    walk(made)


# --------------------------------------------------------------------------- #
# Structure
# --------------------------------------------------------------------------- #


def test_the_plan_module_imports_no_tk_process_media_or_writer_and_writes_nothing():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
            modules |= {f"{node.module}.{alias.name}" for alias in node.names}
    for banned in ("tkinter", "subprocess", "threading", "queue", "shutil", "tempfile",
                   "shared.metadata", "shared.ffmpeg_utils", "shared.job_ui",
                   "shared.import_coordination", "shared.numbering", "mutagen", "PIL",
                   "mp3_tools.m4b_metadata_editor", "mp3_tools.m4b_artwork",
                   "mp3_tools.m4b_maker_plan", "mp3_tools.mp3_plan", "re"):
        assert banned not in modules, banned
    for required in ("shared.output_paths", "shared.book_workspace", "shared.importing",
                     "mp3_tools.m4b_metadata_workflow"):
        assert required in modules, required
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    for write in ("copy2", "copyfile", "write_m4b_tags", "clear_metadata_keep_chapters",
                  "clear_series_numbering", "apply_chapter_titles", "embed_cover", "save",
                  "write_bytes", "write_text", "mkdir", "mkdtemp", "unlink", "rename",
                  "replace", "rmtree", "touch", "open", "run", "Popen", "propose", "commit"):
        assert write not in called, write
    assert {"sanitize_component", "plan", "assert_not_input"} & called or "plan" in called
    declared = {node.name for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    for later in ("prepare_staging", "publish_book", "discard_staging", "SuccessNumbers",
                  "JobController", "retry", "stage_book"):
        assert later not in declared, later


def test_the_plan_module_is_registered_as_a_plan3_adopter():
    from test_plan3_boundaries import ADOPTED

    assert "mp3_tools/m4b_metadata_plan.py" in ADOPTED


def test_the_editor_panel_is_still_byte_identical():
    from test_plan6_boundaries import PHASE0_PANEL_HASHES, sha256_as_checked_out_on_windows

    panel = UNIVERSAL / "mp3_tools" / "m4b_metadata_editor.py"
    assert sha256_as_checked_out_on_windows(panel) == PHASE0_PANEL_HASHES[
        "mp3_tools/m4b_metadata_editor.py"]
    assert "m4b_metadata_plan" not in panel.read_text(encoding="utf-8")
