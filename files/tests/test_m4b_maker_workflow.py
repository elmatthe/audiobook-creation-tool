"""The M4B Maker workspace/import model — v0.6.4 Phase 2.

``mp3_tools/m4b_maker_workflow.py`` is the Maker's Tk-free layer between the
shared Plan 6 workspace and the panel that adopts it later (Phase 6). It owns the
Maker vocabulary and the pure rules the v0.6.4 plan states (sections 5.2–5.9,
Phase 2), and it composes the shared authorities rather than growing second
ones: identity, grouping, precedence and the meaningful-work predicate are
``shared.book_workspace``'s; occurrences, snapshots and natural order are the
importer's.

Nothing here runs FFmpeg, reserves a run, plans a filename, embeds artwork or
starts a controller — those are Phases 3–5. Fixtures are test-owned
``ImportedFile`` values over paths that are never opened.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path, PurePath

import pytest

from shared import book_workspace
from shared.book_workspace import (
    BookJob, BookMutation, WorkspaceSnapshot, add_book, disabled_fields,
    duplicate_book, has_meaningful_work, next_book, remove_book, set_shared_metadata,
)
from shared.importing import (
    IdFactory, ImportRoot, ImportedFile, ImportedFileSnapshot, Revision,
    SupportedTypeCatalog,
)

from mp3_tools import m4b_maker_workflow as wf
from mp3_tools.m4b_maker_workflow import MakerContractError, MakerValueError

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIVERSAL = REPO_ROOT / "scripts" / "Universal"
MODULE = UNIVERSAL / "mp3_tools" / "m4b_maker_workflow.py"

ROOT = Path(os.path.abspath(os.sep + "act-maker-fixture-root"))
ROOTED = ImportRoot("root-1", ROOT, 0)

_IDS = IdFactory("occ-")
_BOOKS = IdFactory("book-")


# --------------------------------------------------------------------------- #
# Fixtures and helpers
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


def names(book: BookJob) -> list[str]:
    return [entry.path.name for entry in book.files.files]


def shared_with(space: WorkspaceSnapshot, **values) -> WorkspaceSnapshot:
    shared = book_workspace.SharedMetadata(fields=wf.SHARED_FIELDS, values=values)
    return set_shared_metadata(space, shared).workspace


# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #


def test_the_maker_accepts_mp3_inputs_through_its_own_catalog():
    assert isinstance(wf.MAKER_CATALOG, SupportedTypeCatalog)
    assert [entry.type_id for entry in wf.MAKER_CATALOG.types] == ["mp3"]
    assert wf.MAKER_TYPE.extensions == (".mp3",)


def test_the_shared_fields_are_exactly_the_makers_six():
    assert wf.SHARED_FIELDS == ("artist", "album_artist", "album", "series",
                                "silence", "artwork")
    assert wf.BOOK_ONLY_FIELDS == ("title", "series_part", "output_filename",
                                   "chapter_titles")
    assert set(wf.FIELD_LABELS) == set(wf.SHARED_FIELDS) | set(wf.BOOK_ONLY_FIELDS)
    # Not the MP3 Tool's vocabulary, and no fields the plan did not authorise.
    for foreign in ("time_delta", "auto_number", "start_number", "year", "genre",
                    "comment", "narrator"):
        assert foreign not in wf.SHARED_FIELDS + wf.BOOK_ONLY_FIELDS


def test_the_startup_workspace_is_one_pristine_book_with_blank_shared():
    space = empty_workspace()
    assert space.count == 1
    assert space.current.is_empty and space.current.configuration == {}
    assert has_meaningful_work(space.current) is False
    assert space.shared.fields == wf.SHARED_FIELDS
    assert space.shared.populated_fields == ()


# --------------------------------------------------------------------------- #
# Folder import: one Book per directory directly containing MP3s, natural order
# --------------------------------------------------------------------------- #


def test_folder_import_projects_one_book_per_containing_directory():
    scanned = snapshot(track("10.mp3", "Vol 2"), track("2.mp3", "Vol 2"),
                       track("01.mp3", "Vol 1"), track("1.mp3", "Vol 2"),
                       track("02.mp3", "Vol 1"))
    result = wf.import_folder(empty_workspace(), scanned, id_factory=_BOOKS)
    assert isinstance(result, BookMutation) and result.changed
    space = result.workspace
    assert space.count == 2
    assert [names(book) for book in space.books] == [
        ["1.mp3", "2.mp3", "10.mp3"], ["01.mp3", "02.mp3"]]
    assert space.current is space.books[0]
    assert len({book.book_id for book in space.books}) == 2


def test_folder_import_never_flattens_separate_directories(monkeypatch):
    scanned = snapshot(track("a.mp3", "One"), track("b.mp3", "Two"))
    space = wf.import_folder(empty_workspace(), scanned, id_factory=_BOOKS).workspace
    assert space.count == 2
    assert all(len(book.files.files) == 1 for book in space.books)


def test_folder_import_delegates_grouping_to_the_shared_projection(monkeypatch):
    asked = []
    real = book_workspace.replace_workspace_from_import

    def spy(*args, **kwargs):
        asked.append(True)
        return real(*args, **kwargs)

    monkeypatch.setattr(wf, "replace_workspace_from_import", spy)
    wf.import_folder(empty_workspace(), snapshot(track("a.mp3")), id_factory=_BOOKS)
    assert asked == [True]


def test_an_empty_folder_import_leaves_one_pristine_book():
    space = empty_workspace()
    result = wf.import_folder(space, snapshot(), id_factory=_BOOKS)
    assert result.changed is False
    assert result.workspace.count == 1 and result.workspace.current.is_empty


def test_folder_import_does_not_prefill_metadata_from_source_tags():
    """The Maker has no source-tag observation; a new Book's configuration is empty."""
    space = wf.import_folder(empty_workspace(), snapshot(track("a.mp3"), track("b.mp3")),
                             id_factory=_BOOKS).workspace
    assert space.current.configuration == {}


# --------------------------------------------------------------------------- #
# Add Files: the current Book only, natural order, identity by occurrence
# --------------------------------------------------------------------------- #


def test_add_files_appends_to_the_current_book_in_natural_order():
    space = workspace_with(track("01.mp3"))
    added = (track("10.mp3", "Elsewhere"), track("2.mp3", "Another"))
    result = wf.add_files(space, added)
    assert result.changed
    assert names(result.workspace.current) == ["01.mp3", "2.mp3", "10.mp3"]
    assert result.workspace.current.book_id == space.current.book_id


def test_add_files_targets_only_the_selected_book():
    first = BookJob(book_id=book_workspace.new_book_id(_BOOKS), files=snapshot(track("a.mp3")))
    second = BookJob(book_id=book_workspace.new_book_id(_BOOKS), files=snapshot(track("b.mp3")))
    space = WorkspaceSnapshot(books=(first, second), current_book_id=second.book_id,
                              shared=wf.new_shared_metadata())
    result = wf.add_files(space, (track("c.mp3"),))
    assert names(result.workspace.books[0]) == ["a.mp3"]
    assert names(result.workspace.books[1]) == ["b.mp3", "c.mp3"]
    assert result.workspace.books[0] is first, "the other Book is the same object"


def test_add_files_keeps_the_books_configuration_untouched():
    space = workspace_with(title="Kept", chapter_titles="One\nTwo")
    result = wf.add_files(space, (track("a.mp3"),))
    assert result.workspace.current.configuration == {"title": "Kept",
                                                      "chapter_titles": "One\nTwo"}


def test_add_files_with_nothing_is_a_no_op():
    space = workspace_with(track("a.mp3"))
    result = wf.add_files(space, ())
    assert result.changed is False
    assert result.workspace.current is space.current


def test_add_files_refuses_an_occurrence_already_in_the_book():
    first = track("a.mp3")
    space = workspace_with(first)
    with pytest.raises(MakerContractError):
        wf.add_files(space, (first,))
    with pytest.raises(MakerContractError):
        wf.add_files(space, ("not-a-file",))  # type: ignore[arg-type]


def test_a_directly_added_file_is_not_the_folder_grouping_rule():
    """Add Files never regroups by parent directory."""
    space = workspace_with(track("a.mp3", "One"))
    result = wf.add_files(space, (track("b.mp3", "Two"), track("c.mp3", "Three")))
    assert result.workspace.count == 1
    assert names(result.workspace.current) == ["a.mp3", "b.mp3", "c.mp3"]


# --------------------------------------------------------------------------- #
# Track order and removal on the current Book
# --------------------------------------------------------------------------- #


def test_tracks_move_one_step_and_stop_at_the_edges():
    a, b, c = track("a.mp3"), track("b.mp3"), track("c.mp3")
    space = workspace_with(a, b, c)
    moved = wf.move_tracks(space, (c.occurrence_id,), wf.UP).workspace
    assert names(moved.current) == ["a.mp3", "c.mp3", "b.mp3"]
    moved = wf.move_tracks(moved, (a.occurrence_id,), wf.UP)
    assert moved.changed is False
    moved = wf.move_tracks(space, (a.occurrence_id, b.occurrence_id), wf.DOWN).workspace
    assert names(moved.current) == ["c.mp3", "a.mp3", "b.mp3"]
    with pytest.raises(MakerContractError):
        wf.move_tracks(space, (a.occurrence_id,), 2)


def test_moving_keeps_identity_and_the_same_book_id():
    a, b = track("a.mp3"), track("b.mp3")
    space = workspace_with(a, b)
    moved = wf.move_tracks(space, (b.occurrence_id,), wf.UP).workspace
    assert moved.current.files.files == (b, a)
    assert moved.current.book_id == space.current.book_id


def test_removing_tracks_keeps_configuration_and_order():
    a, b, c = track("a.mp3"), track("b.mp3"), track("c.mp3")
    space = workspace_with(a, b, c, title="Kept")
    result = wf.remove_tracks(space, (b.occurrence_id,))
    assert names(result.workspace.current) == ["a.mp3", "c.mp3"]
    assert result.workspace.current.configuration == {"title": "Kept"}
    with pytest.raises(MakerContractError):
        wf.remove_tracks(space, ("not-here",))


# --------------------------------------------------------------------------- #
# Stable identity, Duplicate and the meaningful-work predicate
# --------------------------------------------------------------------------- #


def test_book_ids_are_stable_across_workspace_operations():
    space = wf.import_folder(empty_workspace(),
                             snapshot(track("a.mp3", "One"), track("b.mp3", "Two")),
                             id_factory=_BOOKS).workspace
    first_id, second_id = (book.book_id for book in space.books)
    space = add_book(space, id_factory=_BOOKS).workspace
    space = wf.set_book_field(space, "title", "Third").workspace
    space = next_book(space).workspace if space.current_position < space.count else space
    ids = [book.book_id for book in space.books]
    assert ids[:2] == [first_id, second_id]
    space = remove_book(space, id_factory=_BOOKS).workspace
    assert first_id in {book.book_id for book in space.books}
    assert second_id in {book.book_id for book in space.books}


def test_duplicate_copies_configuration_and_starts_with_no_inputs():
    space = workspace_with(track("a.mp3"), title="Copy me", silence="1.5",
                           chapter_titles="One\nTwo")
    copied = duplicate_book(space, id_factory=_BOOKS).workspace
    assert copied.count == 2
    original, copy = copied.books
    assert copy.book_id != original.book_id
    assert copy.configuration == original.configuration
    assert copy.is_empty and names(original) == ["a.mp3"]
    assert copied.current is copy


def test_meaningful_work_is_the_shared_predicate_and_the_maker_supplies_no_defaults():
    space = empty_workspace()
    assert has_meaningful_work(space.current) is False
    typed = wf.set_book_field(space, "title", "x").workspace
    assert has_meaningful_work(typed.current) is True
    cleared = wf.set_book_field(typed, "title", "").workspace
    assert has_meaningful_work(cleared.current) is True, "a cleared field is a stored fact"
    with_files = wf.add_files(space, (track("a.mp3"),)).workspace
    assert has_meaningful_work(with_files.current) is True


# --------------------------------------------------------------------------- #
# Shared -> Book -> blank, and the disabled projection
# --------------------------------------------------------------------------- #


def test_a_populated_shared_value_overrides_and_disables_the_book_value():
    space = workspace_with(artist="Book Artist", silence="0.5")
    overridden = shared_with(space, artist="Shared Artist", silence="2")
    values = wf.effective_values(overridden.shared, overridden.current)
    assert values["artist"] == "Shared Artist"
    assert values["silence"] == "2"
    assert values["album"] == ""
    assert disabled_fields(overridden.shared) == {"artist", "silence"}


def test_clearing_shared_restores_the_book_value_unchanged():
    space = workspace_with(artist="Book Artist", album="Book Album")
    overridden = shared_with(space, artist="Shared Artist")
    restored = shared_with(overridden)
    assert restored.current.configuration["artist"] == "Book Artist"
    values = wf.effective_values(restored.shared, restored.current)
    assert values["artist"] == "Book Artist"
    assert values["album"] == "Book Album"
    assert disabled_fields(restored.shared) == frozenset()


def test_effective_values_cover_exactly_the_shared_fields():
    space = workspace_with(title="Not shared")
    values = wf.effective_values(space.shared, space.current)
    assert tuple(values) == wf.SHARED_FIELDS
    assert "title" not in values


def test_book_only_fields_are_never_shared():
    with pytest.raises(Exception):
        book_workspace.SharedMetadata(fields=wf.SHARED_FIELDS, values={"title": "x"})
    for name in wf.BOOK_ONLY_FIELDS:
        assert name not in wf.new_shared_metadata().fields


# --------------------------------------------------------------------------- #
# Book configuration
# --------------------------------------------------------------------------- #


def test_set_book_field_stores_raw_text_and_blank_is_a_stored_fact():
    space = empty_workspace()
    result = wf.set_book_field(space, "title", "  Raw ")
    assert result.workspace.current.configuration == {"title": "  Raw "}
    cleared = wf.set_book_field(result.workspace, "title", "")
    assert cleared.workspace.current.configuration == {"title": ""}
    again = wf.set_book_field(cleared.workspace, "title", "")
    assert again.changed is False


def test_set_book_field_accepts_every_maker_field_and_nothing_else():
    space = empty_workspace()
    for name in wf.SHARED_FIELDS + wf.BOOK_ONLY_FIELDS:
        space = wf.set_book_field(space, name, "v").workspace
    assert set(space.current.configuration) == set(wf.SHARED_FIELDS + wf.BOOK_ONLY_FIELDS)
    with pytest.raises(MakerContractError):
        wf.set_book_field(space, "time_delta", "1")
    with pytest.raises(MakerContractError):
        wf.set_book_field(space, "title", 3)  # type: ignore[arg-type]


def test_the_text_accessors_read_the_book_and_default_to_blank():
    space = workspace_with(title="T", series_part="3", output_filename="Name",
                           chapter_titles="A\nB")
    book = space.current
    assert wf.title_text(book) == "T"
    assert wf.series_part_text(book) == "3"
    assert wf.output_filename_text(book) == "Name"
    assert wf.chapter_titles_text(book) == "A\nB"
    pristine = empty_workspace().current
    assert (wf.title_text(pristine), wf.series_part_text(pristine),
            wf.output_filename_text(pristine), wf.chapter_titles_text(pristine)) == ("", "", "", "")


# --------------------------------------------------------------------------- #
# Chapter titles: the Maker's own deterministic defaults and the pasted-list rule
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("stem,expected", [
    ("01 - Chapter One", "Chapter One"),
    ("07", "07"),
    ("Book_ The Beginning", "Book: The Beginning"),
    # The first underscore is always the ``: `` rewrite; the possessive and
    # question rules apply to a later one. Pinned to the existing Maker exactly.
    ("Its_s a trap", "Its: s a trap"),
    ("Chapter_ Its_s time_", "Chapter: Its’s time?"),
    ("Where are we_", "Where are we:"),
    ("  many   spaces  ", "many spaces"),
    ("3.Prologue", "Prologue"),
])
def test_the_automatic_title_is_the_makers_cleaned_filename(stem, expected):
    assert wf.normalize_title(stem) == expected


def test_the_automatic_title_rule_is_the_existing_makers_verbatim():
    """The panel is hash-pinned, so its rule is read by AST and compared to ours."""
    panel = ast.parse((UNIVERSAL / "mp3_tools" / "m4b_maker.py").read_text(encoding="utf-8"))
    model = ast.parse(MODULE.read_text(encoding="utf-8"))

    def body_of(tree, name):
        """The function's statements with any docstring dropped, as a canonical dump."""
        node = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == name)
        statements = [s for s in node.body
                      if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
        return ast.dump(ast.Module(body=statements, type_ignores=[]))

    for name in ("strip_leading_numbers", "normalize_title"):
        assert body_of(panel, name) == body_of(model, name), name


def test_default_titles_follow_the_books_current_order():
    a, b = track("01 - Intro.mp3"), track("02 - Body.mp3")
    space = workspace_with(a, b)
    assert wf.default_titles(space.current) == ("Intro", "Body")
    moved = wf.move_tracks(space, (b.occurrence_id,), wf.UP).workspace
    assert wf.default_titles(moved.current) == ("Body", "Intro")


def test_fewer_pasted_titles_fall_back_to_the_automatic_ones():
    space = workspace_with(track("01 - A.mp3"), track("02 - B.mp3"), track("03 - C.mp3"),
                           chapter_titles="First\n\n  Second  \n")
    assert wf.book_chapter_titles(space.current) == ("First", "Second", "C")


def test_extra_pasted_titles_are_ignored_and_blank_text_means_all_defaults():
    space = workspace_with(track("01 - A.mp3"), chapter_titles="One\nTwo\nThree")
    assert wf.book_chapter_titles(space.current) == ("One",)
    blank = workspace_with(track("01 - A.mp3"), track("02 - B.mp3"), chapter_titles="\n \n")
    assert wf.book_chapter_titles(blank.current) == ("A", "B")
    assert wf.resolve_chapter_titles(None, ("x",)) == ("x",)


# --------------------------------------------------------------------------- #
# Parsers: silence is non-negative; Start Part is a positive whole number
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("text,expected", [
    ("", 0.0), ("   ", 0.0), ("0", 0.0), ("1.5", 1.5), (" 2 ", 2.0), ("0.25", 0.25),
])
def test_silence_parses_blank_as_zero_and_accepts_non_negative_seconds(text, expected):
    assert wf.parse_silence(text) == expected


@pytest.mark.parametrize("text", ["-1", "-0.5", "nan", "inf", "-inf", "abc", "1_000", "1e999"])
def test_negative_or_non_numeric_silence_is_rejected(text):
    with pytest.raises(MakerValueError):
        wf.parse_silence(text)
    with pytest.raises(MakerContractError):
        wf.parse_silence(None)


def test_negative_zero_silence_is_zero():
    assert wf.parse_silence("-0") == 0.0


@pytest.mark.parametrize("text,expected", [("", 1), ("  ", 1), ("1", 1), (" 7 ", 7), ("12", 12)])
def test_start_part_parses_blank_as_one(text, expected):
    assert wf.parse_start_part(text) == expected


@pytest.mark.parametrize("text", ["0", "-1", "1.5", "one", "٣", "1e2"])
def test_start_part_refuses_anything_but_a_positive_whole_number(text):
    with pytest.raises(MakerValueError):
        wf.parse_start_part(text)


def test_effective_silence_is_parsed_from_the_effective_text():
    space = workspace_with(silence="1.5")
    assert wf.effective_silence(space.shared, space.current) == 1.5
    overridden = shared_with(space, silence="0")
    assert wf.effective_silence(overridden.shared, overridden.current) == 0.0
    bad = workspace_with(silence="-2")
    with pytest.raises(MakerValueError):
        wf.effective_silence(bad.shared, bad.current)


# --------------------------------------------------------------------------- #
# Output-name inputs (Decision 51A): candidates only; sanitising is Phase 3's
# --------------------------------------------------------------------------- #


def test_source_folder_name_is_the_one_containing_directory_or_none():
    assert wf.source_folder_name(workspace_with(track("a.mp3", "Vol 1"),
                                                track("b.mp3", "Vol 1")).current) == "Vol 1"
    assert wf.source_folder_name(workspace_with(track("a.mp3", "One"),
                                                track("b.mp3", "Two")).current) is None
    assert wf.source_folder_name(empty_workspace().current) is None


def test_output_name_candidates_follow_the_decision_51a_order():
    space = workspace_with(track("a.mp3", "Folder"), output_filename=" Explicit ",
                           title="Title", album="Album")
    assert wf.output_name_candidates(space.shared, space.current, 3) == (
        "Explicit", "Title", "Album", "Folder", "Book 3")


def test_output_name_candidates_skip_blank_and_use_effective_album():
    space = workspace_with(track("a.mp3", "One"), track("b.mp3", "Two"), album="Book Album")
    overridden = shared_with(space, album="Shared Album")
    assert wf.output_name_candidates(overridden.shared, overridden.current, 1) == (
        "Shared Album", "Book 1")
    pristine = empty_workspace()
    assert wf.output_name_candidates(pristine.shared, pristine.current, 2) == ("Book 2",)


def test_the_display_hint_is_title_then_effective_album_then_folder():
    space = workspace_with(track("a.mp3", "Folder"))
    assert wf.display_hint(space.shared, space.current) == "Folder"
    with_album = wf.set_book_field(space, "album", "Album").workspace
    assert wf.display_hint(with_album.shared, with_album.current) == "Album"
    with_title = wf.set_book_field(with_album, "title", "Title").workspace
    assert wf.display_hint(with_title.shared, with_title.current) == "Title"


# --------------------------------------------------------------------------- #
# Structure: Tk-free, disk-free, and composed over the shared authorities
# --------------------------------------------------------------------------- #


def _imports(tree: ast.Module) -> set[str]:
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
    return modules


def test_the_model_module_imports_no_tk_process_media_or_output_service():
    modules = _imports(ast.parse(MODULE.read_text(encoding="utf-8")))
    for banned in ("tkinter", "tkinter.ttk", "subprocess", "threading", "queue",
                   "shutil", "tempfile", "wave", "json", "shared.output_paths",
                   "shared.ffmpeg_utils", "shared.subprocess_utils", "shared.ui_theme",
                   "shared.job_ui", "shared.job_control", "shared.import_coordination",
                   "shared.image_capabilities", "shared.metadata", "PIL", "pillow_heif",
                   "mutagen", "mp3_tools.m4b_maker", "mp3_tools.mp3_workflow",
                   "mp3_tools.mp3_tool", "mp3_tools.mp3_plan", "mp3_tools.mp3_processing",
                   "mp3_tools.m4b_artwork"):
        assert banned not in modules, banned
    assert "shared.book_workspace" in modules
    assert "shared.importing" in modules


def test_the_model_module_defines_no_processing_planning_or_writes():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    declared = {node.name for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    for forbidden in ("run_ff", "concat", "ffmeta", "encode", "embed", "reserve_run",
                      "plan_", "capture_run", "retry", "publish", "stage"):
        assert not any(forbidden in name.lower() for name in declared), (forbidden, sorted(declared))
    for owned_elsewhere in ("DestinationPlanner", "ImportedFileManager", "ImportCoordinator",
                            "JobController", "WorkspaceSnapshot", "BookJob", "RunSnapshot",
                            "book_groups", "add_book", "duplicate_book", "remove_book",
                            "select_book", "effective_value", "effective_metadata",
                            "disabled_fields", "is_populated", "has_meaningful_work",
                            "natural_key", "scan_roots"):
        assert owned_elsewhere not in declared, owned_elsewhere
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    for write in ("save", "write_bytes", "write_text", "mkdir", "unlink", "rename",
                  "rmtree", "touch", "open", "read_bytes", "read_text", "exists",
                  "is_file", "stat"):
        assert write not in called, write


def test_the_model_reuses_the_plan6_operations_rather_than_rebuilding_them():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    called = {node.func.id for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    for reused in ("replace_book", "replace_workspace_from_import", "effective_metadata",
                   "natural_key"):
        assert reused in called, reused


def test_the_model_is_registered_as_a_plan3_adopter():
    from test_plan3_boundaries import ADOPTED

    assert "mp3_tools/m4b_maker_workflow.py" in ADOPTED


def test_the_maker_panel_is_still_byte_identical_and_adopts_nothing():
    """Phase 2 builds the model; the panel conversion is Phase 6."""
    from test_plan6_boundaries import PHASE0_PANEL_HASHES, sha256_as_checked_out_on_windows

    panel = UNIVERSAL / "mp3_tools" / "m4b_maker.py"
    assert sha256_as_checked_out_on_windows(panel) == PHASE0_PANEL_HASHES["mp3_tools/m4b_maker.py"]
    assert "m4b_maker_workflow" not in panel.read_text(encoding="utf-8")
